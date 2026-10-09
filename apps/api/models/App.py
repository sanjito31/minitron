from typing import Callable
from utils.TimeKeeper import now

DEFAULT_TTL = 60

class App():

    id: str
    name: str

    enabled: bool
    ttl: float
    last_updated: float

    cache: dict | None
    config: dict | None

    update_fn: Callable
    render_fn: Callable


    def __init__(self, id, name, update_fn, render_fn, config = None, cache=None, enabled=False, ttl=DEFAULT_TTL):
        self.id = id
        self.name = name

        self.enabled = enabled
        self.ttl = ttl
        self.last_updated = 0.0

        self.config = config
        self.cache = cache

        self.update_fn = update_fn
        self.render_fn = render_fn


    def update(self, force=False):
        if self.cache is None or self.is_stale() or force:
            cache = self.update_fn(self.config)
            if cache is None:
                print(f"Update failed: {self.name}")
            else:
                self.cache = cache
                self.last_updated = now()

    def render(self) -> bytes:
        if not self.cache:
            self.update()
        return self.render_fn(self.cache)

    def is_stale(self):
        return (now() - self.last_updated) > self.ttl
