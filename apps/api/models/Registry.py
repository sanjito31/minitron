from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass
from functools import partial
from inspect import signature
from threading import Lock
from types import ModuleType
from typing import cast
from uuid import uuid4

from .App import App, Renderer, UpdateResult


@dataclass(frozen=True)
class AppRegistration:
    """An implementation and its metadata, published as one registry snapshot."""

    app: App
    name: str
    author: str
    revision: str
    source: str | None = None


class AppRegistry(MutableMapping[str, App]):
    """Process-local registry; registration never invokes app functions.

    Normal mapping reads return Apps for Playlist compatibility. Metadata readers
    can capture get_registration() or snapshot() under the same registry lock.
    File discovery, identity assignment, and watching belong to the loader.
    """

    def __init__(self):
        self._registrations: dict[str, AppRegistration] = {}
        self._lock = Lock()

    def __getitem__(self, app_id: str) -> App:
        with self._lock:
            return self._registrations[app_id].app

    def __setitem__(self, app_id: str, app: App) -> None:
        if not isinstance(app, App):
            raise TypeError("Registry values must be App instances.")
        if app_id != app.id:
            raise ValueError("The registry key must match App.id.")
        self.register(app)

    def __delitem__(self, app_id: str) -> None:
        with self._lock:
            del self._registrations[app_id]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._registrations))

    def __len__(self) -> int:
        with self._lock:
            return len(self._registrations)

    def clear(self) -> None:
        with self._lock:
            self._registrations.clear()

    def register(
        self,
        app: App,
        *,
        name: str | None = None,
        author: str = "",
        revision: str | None = None,
        source: str | None = None,
    ) -> AppRegistration:
        if not isinstance(app, App):
            raise TypeError("Registry values must be App instances.")
        registration = AppRegistration(
            app=app,
            name=name if name is not None else app.id,
            author=author,
            revision=revision if revision is not None else uuid4().hex,
            source=source,
        )
        with self._lock:
            self._registrations[app.id] = registration
        return registration

    def get_registration(self, app_id: str) -> AppRegistration | None:
        with self._lock:
            return self._registrations.get(app_id)

    def snapshot(self) -> dict[str, AppRegistration]:
        with self._lock:
            return dict(self._registrations)

    def unregister(self, app_id: str) -> App | None:
        with self._lock:
            registration = self._registrations.pop(app_id, None)
        return registration.app if registration is not None else None

    def register_module(
        self,
        app_id: str,
        module: ModuleType,
        *,
        services: object = None,
        revision: str | None = None,
        source: str | None = None,
    ) -> AppRegistration:
        """Validate a loaded module, bind services, then publish its candidate.

        app_id is supplied by the loader from persistent identity, never from
        the module's display name. Failed validation leaves the current App alone.
        """
        name = getattr(module, "NAME", None)
        author = getattr(module, "AUTHOR", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("An app module must define a nonempty NAME.")
        if not isinstance(author, str):
            raise ValueError("An app module must define AUTHOR as a string.")

        config = getattr(module, "DEFAULT_CONFIG", None)
        if not isinstance(config, dict):
            raise TypeError("App.config must be a dictionary.")
        updater = getattr(module, "update", None)
        if not callable(updater):
            raise TypeError("App.update must be a synchronous callable.")
        renderer = getattr(module, "render", None)
        if not callable(renderer):
            raise TypeError("App.render must be a synchronous callable.")
        # Dynamic modules supply these return types through the app contract;
        # call signatures are checked below without executing either function.
        updater = cast(Callable[..., UpdateResult | None], updater)
        renderer = cast(Renderer, renderer)
        # App also rejects asynchronous callables before publication.
        candidate = App(
            app_id,
            config,
            updater,
            renderer,
        )
        try:
            signature(renderer).bind({}, {})
            update_signature = signature(updater)
            try:
                update_signature.bind({}, services=services)
            except TypeError:
                update_signature.bind({})
                bound_updater = updater
            else:
                bound_updater = partial(updater, services=services)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "App modules must provide update(config) (optionally accepting "
                "services as a keyword) and "
                "render(data, config)."
            ) from exc
        candidate.update_fn = bound_updater
        return self.register(
            candidate, name=name, author=author,
            revision=revision, source=source,
        )


app_registry = AppRegistry()
