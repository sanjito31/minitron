from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from inspect import iscoroutinefunction
from typing import Any


Config = dict[str, Any]
AppData = dict[str, Any]
UpdateResult = tuple[AppData, datetime]
RenderResult = tuple[bytes, datetime]
Updater = Callable[[Config], UpdateResult | None]
Renderer = Callable[[AppData, Config], RenderResult]


class App:
    """One shared graphic implementation; all working data is call-local.

    The loader binds service access to the updater before constructing this App.
    PlaylistApp merges defaults with placement overrides and owns graphic caching.
    Replace the entire App in the registry when publishing a new implementation.
    """

    id: str
    config: Config
    update_fn: Updater
    render_fn: Renderer

    def __init__(
        self,
        id: str,
        config: Config,
        update: Updater,
        render: Renderer,
    ):
        if not isinstance(id, str) or not id.strip():
            raise ValueError("App.id must be a nonempty string.")
        if not isinstance(config, dict):
            raise TypeError("App.config must be a dictionary.")
        for name, function in (("update", update), ("render", render)):
            if not callable(function) or iscoroutinefunction(function):
                raise TypeError(f"App.{name} must be a synchronous callable.")

        self.id = id
        self.config = deepcopy(config)
        self.update_fn = update
        self.render_fn = render

    def update(self, config: Config) -> UpdateResult | None:
        return self.update_fn(config)

    def render(self, data: AppData, config: Config) -> RenderResult:
        return self.render_fn(data, config)
