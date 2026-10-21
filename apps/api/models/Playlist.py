from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from weakref import ReferenceType, ref

from .App import App
from .Registry import app_registry


@dataclass
class PlaylistApp:
    """One configured placement of a graphic, with its own WebP cache."""

    app_id: str
    name: str = ""
    config: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()), kw_only=True)
    cached_gfx_bytes: bytes | None = field(default=None, init=False, repr=False)
    cached_gfx_expires: datetime | None = field(default=None, init=False)
    _cached_config: dict | None = field(default=None, init=False, repr=False)
    _cached_app: ReferenceType[App] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self):
        self.config = deepcopy(self.config)

    def get_graphic(self, app: App) -> bytes | None:
        """Use the request's resolved App for both update and render.

        Overrides replace top-level default values, including entire nested
        objects. Copies keep updater/renderer mutations out of shared defaults
        and the placement's settings. DeviceManager serializes these calls.
        """
        config = deepcopy(app.config | self.config)
        if (
            self.cached_gfx_bytes is not None
            and self.cached_gfx_expires is not None
            and datetime.now(timezone.utc) < self.cached_gfx_expires
            and self._cached_config == config
            and self._cached_app is not None
            and self._cached_app() is app
        ):
            return self.cached_gfx_bytes

        data = app.update(deepcopy(config))
        if data is None:
            return None

        graphic, expires = app.render(data, deepcopy(config))
        if not isinstance(graphic, bytes):
            raise TypeError("App.render() must return graphic bytes.")
        if (
            not isinstance(expires, datetime)
            or expires.tzinfo is None
            or expires.utcoffset() is None
        ):
            raise ValueError("App.render() must return a timezone-aware expiration.")

        # Publish only a complete valid result. Failed refreshes preserve the
        # previous cache without treating expired or incompatible bytes as fresh.
        self.cached_gfx_bytes = graphic
        self.cached_gfx_expires = expires.astimezone(timezone.utc)
        self._cached_config = config
        # Detect registry replacement without keeping a retired App alive.
        self._cached_app = ref(app)
        return graphic


class Playlist:
    """A device's ordered entries; rendering keeps the current entry selected."""

    current_app_idx: int
    apps: list[PlaylistApp]

    def __init__(self, apps: Iterable[PlaylistApp] = ()):
        self.apps = list(apps)
        self.current_app_idx = 0

    @property
    def num_apps(self) -> int:
        return len(self.apps)

    @property
    def current_app(self) -> PlaylistApp | None:
        if not self.apps:
            return None
        return self.apps[self.current_app_idx % len(self.apps)]

    def get_num_apps(self) -> int:
        return len(self.apps)

    def advance_app(self) -> None:
        if self.apps:
            self.current_app_idx = (self.current_app_idx + 1) % len(self.apps)

    def add_app(self, app: PlaylistApp) -> None:
        self.apps.append(app)

    def get_graphic(self) -> bytes | None:
        # Resolve once per attempt; app functions use that same instance even if
        # the registry is replaced while this request is rendering.
        for _ in range(len(self.apps)):
            entry = self.current_app
            if entry is None:
                return None
            app = app_registry.get(entry.app_id)
            if app is not None:
                return entry.get_graphic(app)
            self.advance_app()
        return None
