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

See [clock_contract.py](apps/clock_contract.py) for a real clock example with an
animated WebP and expiration at the next minute boundary.

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

The first successful load assigns a UUID4 and saves the filename-to-ID mapping in
`apps/.app_catalog.json` before publishing the app. Keep this catalog with the app
files across restarts and deployments. App names and source contents can change
without changing IDs. Renaming a file requires updating its catalog key to retain
the same ID; an unknown filename is treated as a new app.

Calling `load_catalog()` again reloads edited files into fresh module namespaces,
keeps unchanged registrations, and unregisters removed files. Deleted filenames
remain in the catalog so restoring a file reuses its ID. Failed reloads preserve
the working revision, while failures in other files do not block valid apps.
A corrupt catalog raises an error instead of generating replacement identities.

There is no background watcher yet. Rescan explicitly to apply later changes.
Catalog writes are atomic and coordinated across startup workers using a file
lock on macOS/Linux. The lock file is runtime state; the JSON catalog is persistent.
