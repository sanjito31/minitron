import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from PIL import Image
from fastapi.testclient import TestClient

from apps.api.apps import clock_contract
from apps.api.models.Loader import AppLoader
from apps.api.models.Playlist import PlaylistApp
from apps.api.models.Registry import AppRegistry


APP_SOURCE = '''
from datetime import datetime, timedelta, timezone
NAME = "Test Graphic"
DEFAULT_CONFIG = {"label": "default", "style": {"color": "white", "size": 15}}
VALUE = "old"

def update(config, *, services=None):
    return {"label": config["label"], "version": VALUE}, datetime.now(timezone.utc) + timedelta(minutes=5)

def render(data, config):
    return (data["version"] + data["label"]).encode(), datetime.now(timezone.utc) + timedelta(minutes=10)
'''


class AppLoaderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.registry = AppRegistry()
        self.loader = AppLoader(self.registry, apps_dir=self.directory)

    def write_app(self, name="graphic.py", source=APP_SOURCE):
        path = self.directory / name
        path.write_text(source, encoding="utf-8")
        return path

    def test_scan_ignores_helpers_and_subdirectories_and_does_not_run_functions(self):
        self.write_app(source=APP_SOURCE.replace(
            'return {"label": config["label"], "version": VALUE}, datetime.now(timezone.utc) + timedelta(minutes=5)',
            'raise AssertionError("update ran during loading")',
        ).replace(
            'return (data["version"] + data["label"]).encode(), datetime.now(timezone.utc) + timedelta(minutes=10)',
            'raise AssertionError("render ran during loading")',
        ))
        for name in ("__init__.py", "_helper.py", ".temporary.py", "graphic.backup.py"):
            self.write_app(name, 'raise AssertionError("helper imported")')
        nested = self.directory / "helpers"
        nested.mkdir()
        (nested / "other.py").write_text(APP_SOURCE)
        records = self.loader.load_catalog()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].name, "Test Graphic")
        self.assertEqual(records[0].author, "")
        self.assertFalse(self.loader.errors)
        self.assertEqual(UUID(records[0].app.id).version, 4)

    def test_ids_survive_restart_and_edits_without_renaming_source(self):
        path = self.write_app()
        first, = self.loader.load_catalog()
        second_registry = AppRegistry()
        second, = AppLoader(second_registry, apps_dir=self.directory).load_catalog()
        self.assertEqual(second.app.id, first.app.id)
        path.write_text(APP_SOURCE.replace('NAME = "Test Graphic"', 'NAME = "New Name"'))
        changed, = self.loader.load_catalog()
        self.assertEqual(changed.app.id, first.app.id)
        self.assertEqual(changed.name, "New Name")
        self.assertNotEqual(changed.revision, first.revision)
        self.assertTrue(path.exists())
        catalog = json.loads((self.directory / ".app_catalog.json").read_text())
        self.assertEqual(catalog["apps"], {path.name: first.app.id})

    def test_duplicate_display_names_have_distinct_ids(self):
        self.write_app("first.py")
        self.write_app("second.py")
        records = self.loader.load_catalog()
        self.assertEqual([record.name for record in records], ["Test Graphic"] * 2)
        self.assertNotEqual(records[0].app.id, records[1].app.id)

    def test_unchanged_rescan_keeps_the_same_app_and_cache(self):
        self.write_app()
        first, = self.loader.load_catalog()
        entry = PlaylistApp(first.app.id)
        entry.get_graphic(first.app)
        with patch.object(first.app, "update", side_effect=AssertionError("cache missed")):
            again, = self.loader.load_catalog()
            self.assertIs(again, first)
            self.assertEqual(entry.get_graphic(again.app), b"olddefault")

    def test_reload_uses_fresh_globals_even_when_file_size_and_timestamp_match(self):
        path = self.write_app()
        original, = self.loader.load_catalog()
        previous_stat = path.stat()
        path.write_text(APP_SOURCE.replace('VALUE = "old"', 'VALUE = "new"'))
        os.utime(path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
        replacement, = self.loader.load_catalog()
        self.assertEqual(original.app.update(original.app.config)[0]["version"], "old")
        self.assertEqual(replacement.app.update(replacement.app.config)[0]["version"], "new")
        self.assertEqual(replacement.app.id, original.app.id)

    def test_invalid_files_do_not_block_valid_apps_or_replace_working_apps(self):
        path = self.write_app()
        original, = self.loader.load_catalog()
        path.write_text(APP_SOURCE.replace('NAME = "Test Graphic"', 'NAME = ""'))
        self.write_app("broken.py", "invalid python source!")
        self.write_app("other.py")
        with self.assertLogs("apps.api.models.Loader", level="WARNING"):
            records = self.loader.load_catalog()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(self.loader.errors), 2)
        self.assertIs(self.registry.get_registration(original.app.id), original)
        catalog = json.loads((self.directory / ".app_catalog.json").read_text())
        self.assertNotIn("broken.py", catalog["apps"])

    def test_removed_file_is_unregistered_and_restore_reuses_id(self):
        path = self.write_app()
        original, = self.loader.load_catalog()
        path.unlink()
        self.assertEqual(self.loader.load_catalog(), [])
        self.assertIsNone(self.registry.get(original.app.id))
        self.write_app()
        restored, = self.loader.load_catalog()
        self.assertEqual(restored.app.id, original.app.id)

    def test_catalog_must_be_persisted_before_publication(self):
        self.write_app()
        with patch.object(self.loader, "_write_catalog", side_effect=OSError("read only")):
            with self.assertLogs("apps.api.models.Loader", level="WARNING"):
                self.assertEqual(self.loader.load_catalog(), [])
        self.assertEqual(len(self.registry), 0)
        self.assertEqual(len(self.loader.errors), 1)

    def test_corrupt_catalog_does_not_silently_replace_ids(self):
        self.write_app()
        self.loader.load_catalog()
        previous = self.registry.snapshot()
        (self.directory / ".app_catalog.json").write_text("{bad JSON")
        with self.assertRaisesRegex(ValueError, "Invalid app catalog"):
            self.loader.load_catalog()
        self.assertEqual(self.registry.snapshot(), previous)

    def test_concurrent_loaders_use_the_same_persisted_id(self):
        self.write_app()

        def load(_):
            loader = AppLoader(AppRegistry(), apps_dir=self.directory)
            record, = loader.load_catalog()
            return record.app.id

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(load, range(4)))
        self.assertEqual(len(set(ids)), 1)

    def test_simple_updater_and_config_overrides_use_the_earliest_deadline(self):
        self.write_app(source='''
from datetime import datetime, timedelta, timezone
NAME = "Config test"
DEFAULT_CONFIG = {"label": "default", "style": {"color": "white", "size": 15}}
DATA_EXPIRES = datetime.now(timezone.utc) + timedelta(minutes=5)
RENDER_EXPIRES = DATA_EXPIRES + timedelta(minutes=5)

def update(config):
    assert config == {"label": "custom", "style": {"size": 10}}
    config["style"]["size"] = 99
    return {"label": config["label"]}, DATA_EXPIRES

def render(data, config):
    assert config["style"] == {"size": 10}
    return data["label"].encode(), RENDER_EXPIRES
''')
        record, = self.loader.load_catalog()
        entry = PlaylistApp(record.app.id, config={"label": "custom", "style": {"size": 10}})
        self.assertEqual(entry.get_graphic(record.app), b"custom")
        _, data_expires = record.app.update(deepcopy(record.app.config | entry.config))
        self.assertEqual(entry.cached_gfx_expires, data_expires)
        self.assertEqual(entry.config["style"], {"size": 10})
        self.assertEqual(record.app.config["style"], {"color": "white", "size": 15})

    def test_services_are_bound_without_entering_device_config(self):
        self.write_app(source=APP_SOURCE.replace(
            'return {"label": config["label"], "version": VALUE}, datetime.now(timezone.utc) + timedelta(minutes=5)',
            'return services, datetime.now(timezone.utc) + timedelta(minutes=5)',
        ))
        services = {"provider": "test"}
        loader = AppLoader(self.registry, apps_dir=self.directory, services=services)
        record, = loader.load_catalog()
        data, _ = record.app.update(record.app.config)
        self.assertIs(data, services)

    def test_clock_example_loads_and_renders_real_webp(self):
        shutil.copyfile(clock_contract.__file__, self.directory / "clock.py")
        record, = self.loader.load_catalog()
        entry = PlaylistApp(record.app.id, config={"24hourtime": True, "timezone": "UTC"})
        graphic = entry.get_graphic(record.app)
        with Image.open(BytesIO(graphic)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (64, 32))
            self.assertEqual(image.n_frames, 2)
        self.assertIsNotNone(entry.cached_gfx_expires)
        self.assertEqual(entry.cached_gfx_expires.tzinfo, timezone.utc)

    def test_server_lifespan_loads_catalog_and_passes_services(self):
        from apps.api.main import create_server

        self.write_app()
        services = object()
        with patch("apps.api.main.AppLoader", return_value=self.loader) as constructor:
            server = create_server(registry=self.registry, services=services)
            constructor.assert_called_once_with(self.registry, services=services)
            self.assertEqual(len(self.registry), 0)
            with TestClient(server):
                self.assertEqual(len(self.registry), 1)
                self.assertIs(server.state.app_loader, self.loader)

    def test_server_can_disable_startup_loading(self):
        from apps.api.main import create_server

        self.write_app()
        with patch("apps.api.main.AppLoader", return_value=self.loader):
            with TestClient(create_server(registry=self.registry, load_apps=False)):
                self.assertEqual(len(self.registry), 0)
                self.assertFalse((self.directory / ".app_catalog.json").exists())


if __name__ == "__main__":
    unittest.main()
