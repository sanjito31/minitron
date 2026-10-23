# Loading graphic apps

`AppLoader` scans direct `.py` files in `apps/api/apps/`. Each app must expose
`NAME` (a nonempty string), `DEFAULT_CONFIG` (a dictionary), `update`, and `render`.
`AUTHOR` is optional and defaults to an empty string. Files beginning with `_`,
temporary filenames, and subdirectories are excluded.

Apps define their metadata and functions without constructing an `App` or
registering themselves. Importing an app must not fetch data or start rendering.
Legacy files that do not implement this contract are reported and skipped.

```python
from datetime import datetime, timedelta, timezone
from io import BytesIO
from PIL import Image

NAME = "Solid Color"
# AUTHOR = "optional publisher handle"
DEFAULT_CONFIG = {"color": [255, 0, 0], "width": 64, "height": 32}

def update(config, *, services=None):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    return {"color": tuple(config["color"]), "expires_at": expires_at}, expires_at

def render(data, config):
    image = Image.new("RGB", (config["width"], config["height"]), data["color"])
    output = BytesIO()
    image.save(output, "WEBP")
    return output.getvalue(), data["expires_at"]
```

The update result is `(data_dictionary, expires_at)`; the render result is
`(graphic_bytes, expires_at)`. Both deadlines must be timezone-aware datetimes.
`update` may return `None` when data is unavailable; the renderer will not run.
The graphic cache expires at the earlier of the update and render deadlines.
Rendering cannot extend the lifetime of the input data.

`update(config)` without a services parameter is also supported. If the updater
accepts a `services` keyword, the registry binds the object supplied to
`AppLoader(..., services=services)`. Services are separate from device settings.

See [the Clock app](apps/app_895e394c1ade4e4abf48dbe710ea325c.py) for a real example with an
animated WebP and expiration at the next minute boundary.

## Built-in apps and device defaults

The server loads these managed app files. The UUID in each filename matches its
catalog and registration UUID (filenames omit UUID hyphens).

| App | Source |
| --- | --- |
| Clock | [app_895e394c1ade4e4abf48dbe710ea325c.py](apps/app_895e394c1ade4e4abf48dbe710ea325c.py) |
| Weather | [app_da0036fb23304e14a268efa68ae00cd6.py](apps/app_da0036fb23304e14a268efa68ae00cd6.py) |
| MTA | [app_bd31308600994194b53d6104888fe022.py](apps/app_bd31308600994194b53d6104888fe022.py) |
| Flights Overhead | [app_7bbefa52ec4145bfb0526be7bce8430f.py](apps/app_7bbefa52ec4145bfb0526be7bce8430f.py) |

An unknown device UUID automatically creates an in-memory device with its own
Clock-only playlist. Weather, MTA, and flights are registered but are not
added to default playlists. Each device's playlist entries, overrides, and caches
are independent. Devices and playlists are not persisted.

Weather reads `OPEN_WEATHER_API_KEY`, `LAT`, and `LON` from environment variables
or the API directory's `.env` at update time. Entry settings `lat` and `lon`
override that location; `units` accepts `imperial`, `metric`, or `standard`.
No weather credentials are required to start the server or render the clock.
If weather settings are missing or the provider request fails, the endpoint
returns 503 with `Retry-After: 1`; retry the same request ID to stay on weather.

MTA exposes `api_url`, `stations`, `lines`, `sections`, `min_wait`, and `max_wait`
as settings. It retains arrival timestamps and computes countdowns while
rendering, shortening graphic expiration when a displayed countdown changes.
Defaults retain the original B/D and F display and stations.

Flights reads `LAT`, `LON`, `LATMIN`, `LATMAX`, `LOMIN`, and `LOMAX`, with matching
lowercase entry overrides. Without explicit bounds it queries within 0.2 degrees
of the configured location. `OPENSKY_ACCESS_TOKEN` is optional; without one it
uses anonymous access. Route lookups are limited by `max_route_lookups`. An empty
area renders a "No flights" graphic; unavailable route metadata retains the
nearest aircraft's callsign. Upstream request failures return no graphic.

All three provider apps support `ttl`, `timeout`, `width`, `height`, `fontsize`,
`bg`, and `fg`. They use `services.http` if supplied (a requests-compatible HTTP
client); otherwise they use `requests`. Loading an app does not contact providers.

Provider references: [OpenWeather current weather](https://openweathermap.org/current),
[MTA developer resources](https://api.mta.info/),
[OpenSky REST API](https://github.com/openskynetwork/opensky-api/blob/master/docs/free/rest.rst),
and [ADSBDB](https://www.adsbdb.com/).

## Configuration overrides

For each playlist entry, `PlaylistApp` builds:

```python
effective_config = app.config | entry.config
```

Entry values override defaults by top-level key. A nested dictionary in an entry
replaces that entire default dictionary. Both update and render receive separate
deep copies of the same effective configuration, so app mutations do not change
defaults or another entry's settings. Each placement has its own graphic cache.

## Loading and identity

The server lifespan calls `load_catalog()` at startup. It can also be called
explicitly from the API directory:

```python
from models.Loader import AppLoader
from models.Registry import app_registry

loader = AppLoader(app_registry)  # Optional: apps_dir=..., services=...
registrations = loader.load_catalog()
# registrations contain the App, UUID, name, author, revision, and source path.
# loader.errors maps failed source paths to their exceptions.
```

Add a new app using a descriptive filename such as `my_clock_contract.py`. The
loader assigns a UUID4 and moves it to `app_<uuid hex>.py`. An existing catalog
UUID is preserved when migrating an older descriptive filename. Keep the managed
filename when editing the app; display names, authors, defaults, and code can
change without changing its UUID.

The loader validates the module at its final path and saves the matching
filename-to-ID mapping in `apps/.app_catalog.json` before publishing the app.
Validation or catalog-write failures restore the original filename. Existing
destination files are never overwritten. A managed filename can recover its UUID
even if the catalog entry is missing; a conflicting catalog UUID is rejected.

The catalog's `default_playlist` array contains ordered app UUIDs. It selects
Clock without depending on source filenames or display names. The original
catalog format is migrated automatically with Clock as its default. Keep the
catalog with the app files across restarts and deployments.

Calling `load_catalog()` again reloads edited files into fresh module namespaces,
keeps unchanged registrations, and unregisters removed files. Deleted filenames
remain in the catalog so restoring a file reuses its ID. Failed reloads preserve
the working revision, while failures in other files do not block valid apps.
A corrupt catalog raises an error instead of generating replacement identities.

There is no background watcher yet. Rescan explicitly to apply later changes.
Catalog writes are atomic and coordinated across startup workers using a file
lock on macOS/Linux. The lock file is runtime state; the JSON catalog is persistent.
