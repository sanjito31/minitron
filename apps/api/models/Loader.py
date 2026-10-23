"""Discover standalone graphic modules and publish validated app revisions."""

from collections.abc import Iterable
import fcntl
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock
from uuid import UUID, uuid4
from weakref import finalize

from .Registry import AppRegistration, AppRegistry


logger = logging.getLogger(__name__)


class AppLoader:
    """Ingest new app files as app_<uuid hex>.py and keep catalog IDs in sync.

    Re-running load_catalog() refreshes changed files and unregisters removed
    files. Failed replacements retain the last working registration. Helpers
    beginning with '_' and subdirectories are excluded. This does not start a
    background watcher; call load_catalog() again to reconcile later changes.
    """

    def __init__(
        self,
        registry: AppRegistry,
        *,
        apps_dir: str | Path | None = None,
        services: object = None,
        exclude_files: Iterable[str] = (),
    ):
        self.registry = registry
        self.apps_dir = (
            Path(apps_dir) if apps_dir is not None
            else Path(__file__).resolve().parents[1] / "apps"
        ).resolve()
        self.services = services
        self._exclude_files = frozenset(exclude_files)
        self.errors: dict[Path, Exception] = {}
        self._loaded: dict[Path, AppRegistration] = {}
        self._lock = Lock()

    def load_catalog(self) -> list[AppRegistration]:
        """Scan and register apps; inspect errors for individual file failures.

        A corrupt catalog raises rather than silently assigning replacement IDs.
        The file lock coordinates ID assignment across startup workers. Catalog
        entries are retained for deleted files so restoring a file restores its ID.
        """
        if not self.apps_dir.is_dir():
            raise FileNotFoundError(f"App directory does not exist: {self.apps_dir}")
        with self._lock, (self.apps_dir / ".app_catalog.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._load_catalog()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load_catalog(self) -> list[AppRegistration]:
        catalog, default_ids = self._read_catalog()
        self.registry.set_default_playlist(default_ids)
        paths = sorted(
            path for path in self.apps_dir.glob("*.py")
            if path.is_file() and path.stem.isidentifier()
            and not path.name.startswith("_")
            and path.name not in self._exclude_files
        )
        self.errors = {}
        registrations = []
        seen_paths = set(paths)
        for path in paths:
            managed_path = path
            renamed = False
            try:
                filename_id = self._filename_id(path.name)
                app_id = filename_id or catalog.get(path.name) or str(uuid4())
                managed_path = self.apps_dir / f"app_{UUID(app_id).hex}.py"
                # Recover a rename interrupted before its catalog update. A second
                # existing file claiming this UUID must never replace the first.
                aliases = [name for name, value in catalog.items() if value == app_id and name != managed_path.name]
                for name in aliases:
                    if name != path.name and (self.apps_dir / name).exists():
                        raise ValueError(f"App UUID {app_id} is already associated with {name}")
                source = path.read_bytes()
                revision = hashlib.sha256(source).hexdigest()
                previous = self._loaded.get(path)
                if (
                    path == managed_path and previous is not None
                    and previous.revision == revision
                    and catalog.get(path.name) == previous.app.id
                    and self.registry.get_registration(previous.app.id) is previous
                ):
                    registrations.append(previous)
                    continue

                if path != managed_path:
                    self._move_without_overwrite(path, managed_path)
                    renamed = True
                candidate = self._load_candidate(managed_path, source, app_id, revision)
                updated = {
                    name: value for name, value in catalog.items()
                    if name not in aliases
                } | {managed_path.name: app_id}
                # Publish only after the managed filename and its catalog agree.
                if updated != catalog or not (self.apps_dir / ".app_catalog.json").exists():
                    self._write_catalog(updated, default_ids)
                    catalog = updated
                renamed = False
                seen_paths.discard(path)
                seen_paths.add(managed_path)
                record = self.registry.register(
                    candidate.app, name=candidate.name, author=candidate.author,
                    revision=candidate.revision, source=candidate.source,
                )
                self._loaded[managed_path] = record
                registrations.append(record)
            except Exception as exc:
                if renamed:
                    try:
                        self._move_without_overwrite(managed_path, path)
                    except OSError as rollback_error:
                        exc = RuntimeError(f"{exc}; could not restore {path.name}: {rollback_error}")
                self.errors[path] = exc
                logger.warning("Could not load app %s: %s", path.name, exc)

        for path in self._loaded.keys() - seen_paths:
            previous = self._loaded.pop(path)
            if self.registry.get_registration(previous.app.id) is previous:
                self.registry.unregister(previous.app.id)
        return registrations

    @staticmethod
    def _filename_id(filename: str) -> str | None:
        if not filename.startswith("app_") or filename.endswith("_contract.py"):
            return None
        app_id = UUID(Path(filename).stem[4:])
        if app_id.version != 4 or filename != f"app_{app_id.hex}.py":
            raise ValueError(f"Invalid managed app filename: {filename}")
        return str(app_id)

    @staticmethod
    def _move_without_overwrite(source: Path, destination: Path) -> None:
        # Both paths are in the same directory. link() atomically refuses an
        # existing destination, unlike rename(), which can overwrite a file.
        os.link(source, destination)
        try:
            source.unlink()
        except OSError:
            destination.unlink()
            raise

    def _load_candidate(
        self, path: Path, source: bytes, app_id: str, revision: str,
    ) -> AppRegistration:
        # A fresh namespace preserves old function globals during a reload.
        module_name = f"_minitron_app_{UUID(app_id).hex}_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None:
            raise ImportError(f"Cannot create an import specification for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            # Compile the exact hashed bytes, bypassing timestamp-based .pyc reuse.
            exec(compile(source, str(path), "exec"), module.__dict__)
            staging = AppRegistry()
            record = staging.register_module(
                app_id, module, services=self.services,
                revision=revision, source=str(path),
            )
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        # Keep module introspection working for active/in-flight apps, then release
        # retired namespaces when no request or registry retains their App.
        finalize(record.app, sys.modules.pop, module_name, None)
        return record

    def _read_catalog(self) -> tuple[dict[str, str], list[str]]:
        path = self.apps_dir / ".app_catalog.json"
        if not path.exists():
            return {}, []
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != 1:
                raise ValueError("Unsupported catalog format")
            catalog = document.get("apps")
            if not isinstance(catalog, dict):
                raise ValueError("Catalog apps must be a filename-to-UUID mapping")
            for filename, app_id in catalog.items():
                if (
                    not isinstance(filename, str) or Path(filename).name != filename
                    or not filename.endswith(".py") or not isinstance(app_id, str)
                    or UUID(app_id).version != 4 or str(UUID(app_id)) != app_id
                ):
                    raise ValueError("Invalid filename or UUID4 in catalog")
                filename_id = self._filename_id(filename)
                if filename_id is not None and filename_id != app_id:
                    raise ValueError(f"Filename UUID does not match catalog UUID: {filename}")
            if len(set(catalog.values())) != len(catalog):
                raise ValueError("Duplicate app IDs in catalog")
            default_ids = document.get("default_playlist")
            if default_ids is None:
                # Migrate the original catalog before dropping its friendly keys.
                default_ids = [catalog[name] for name in ("clock_contract.py", "weather_contract.py") if name in catalog]
            if (
                not isinstance(default_ids, list)
                or any(not isinstance(value, str) or value not in catalog.values() for value in default_ids)
                or len(set(default_ids)) != len(default_ids)
            ):
                raise ValueError("Default playlist must contain unique catalog app UUIDs")
            return catalog, default_ids
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid app catalog {path}: {exc}") from exc

    def _write_catalog(self, catalog: dict[str, str], default_ids: list[str]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.apps_dir,
                prefix=".app_catalog-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    {"version": 1, "apps": catalog, "default_playlist": default_ids},
                    stream, indent=2, sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.apps_dir / ".app_catalog.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
