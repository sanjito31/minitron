# Minitron

Minitron is a networked LED matrix display. A Python API renders display apps as
WebP images and animations; ESP32 firmware downloads them over WiFi, decodes them,
and drives a HUB75 LED matrix panel.

## Repository layout

| Directory | Purpose | Details |
| --- | --- | --- |
| [`apps/api`](apps/api/) | FastAPI backend, display apps, and WebP rendering | [API README](apps/api/README.md) |
| [`apps/hdk`](apps/hdk/) | ESP32 hardware development kit (HDK), written in C/C++ using Arduino and PlatformIO | [HDK README](apps/hdk/README.md) |

The HDK requests `GET /api/current` from the API every 10 seconds. The API rotates
through display apps, and the HDK renders the returned graphic on the panel.

Commands below run from the monorepo root unless stated otherwise.

## Clone and initialize dependencies

```bash
git clone --recurse-submodules <repository-url> minitron
cd minitron
```

For an existing checkout, download the submodules with:

```bash
git submodule update --init --recursive
```

libwebp is a Git submodule at `apps/hdk/lib/libwebp`. Its URL and path are declared
in the root [`.gitmodules`](.gitmodules), with the path relative to the monorepo
root. Git checks out the libwebp revision recorded by this repository.

## API development

Use Python 3.13 for the pinned dependencies. Create `apps/api/.env` using the
variables listed in the [API README](apps/api/README.md#environment-variables).

```bash
cd apps/api
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

The server listens on port 8000. Open `http://localhost:8000/docs` for its API
documentation. Run these commands from `apps/api` so that local imports, assets,
and the `.env` file resolve correctly.

## HDK development

### Tools and configuration

Install [PlatformIO IDE for VS Code](https://docs.platformio.org/en/latest/integration/ide/vscode.html)
or [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html).
The IDE includes its own Core installation and terminal.

[`apps/hdk/platformio.ini`](apps/hdk/platformio.ini) defines the firmware project:

- Platform: `espressif32`.
- Board: `esp32doit-devkit-v1`.
- Framework: `arduino`.
- Registry libraries: HUB75 matrix driver, Adafruit GFX, and ArduinoJson.
- Local libraries: libwebp and embedded display assets under `apps/hdk/lib`.

PlatformIO installs the required platform, compiler toolchain, framework, and
registry dependencies when processing the project. Initialize the libwebp
submodule separately using the Git command above.

Create the Git-ignored `apps/hdk/include/secrets.h` with your WiFi credentials
and API base URL:

```cpp
#pragma once

#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASS "your-wifi-password"
#define SERVER_API_URL "http://192.168.1.100:8000"
```

Use an address reachable from the ESP32, such as your API computer's LAN address.
The firmware appends `/api/current` to this URL. See the
[HDK README](apps/hdk/README.md#hardware-requirements) for panel wiring.

### Build, upload, and monitor

```bash
# Build firmware.
pio run -d apps/hdk

# Build and flash a connected ESP32.
pio run -d apps/hdk -t upload

# Read serial output using the HDK project's monitor settings.
(cd apps/hdk && pio device monitor)
```

`-d apps/hdk` selects the PlatformIO project directory. It is equivalent to
changing into `apps/hdk` and running `pio run`, just as when the HDK was a
standalone repository. `$PROJECT_DIR` in the build configuration refers to
`apps/hdk`, even when the command runs from the monorepo root.

PlatformIO runs a compiler on your computer that produces ESP32 machine code,
rather than a program for your computer. The build preprocesses includes and
macros, compiles C/C++ sources into object files, links them with framework and
library code, and packages the firmware. Build outputs live under
`apps/hdk/.pio/build/esp32doit-devkit-v1/`.

### libwebp build settings

The environment in `platformio.ini` includes these settings:

```ini
build_flags =
    -I"$PROJECT_DIR/lib/libwebp"

build_unflags =
    -DHAVE_CONFIG_H
```

PlatformIO automatically adds the library's `src` directory to the compiler's
include paths. That resolves application includes such as `webp/decode.h` and
`webp/demux.h`; adding `lib/libwebp/src` explicitly would be redundant.

libwebp also uses internal includes such as `src/dec/alphai_dec.h`. Those require
the library root as an additional include path, which is what the explicit flag
provides. Header lookup joins an include directory with the path written in
`#include`; it does not recursively search the project or infer a library root
from the location of `platformio.ini`. For example:

```text
lib/libwebp     + src/dec/alphai_dec.h = lib/libwebp/src/dec/alphai_dec.h
lib/libwebp/src + webp/decode.h       = lib/libwebp/src/webp/decode.h
```

The ESP32 framework supplies `HAVE_CONFIG_H`, which makes libwebp expect
`src/webp/config.h`. That file is normally generated by libwebp's own build
system; this PlatformIO integration does not generate it. Removing the definition
lets libwebp use its fallback configuration without that generated header.

### VS Code and `compile_commands.json`

When opening the entire monorepo in VS Code, install Microsoft's **C/C++**
extension and generate the HDK compilation database:

```bash
pio run -d apps/hdk -t compiledb
```

This creates `apps/hdk/compile_commands.json`, recording each source file's
compiler command, include paths, and macro definitions. It contains local paths
and should be regenerated for your checkout.

Create `.vscode/c_cpp_properties.json` at the **monorepo root**:

```json
{
  "version": 4,
  "configurations": [
    {
      "name": "ESP32",
      "compileCommands": [
        "${workspaceFolder}/apps/hdk/compile_commands.json"
      ]
    }
  ]
}
```

VS Code uses this database for IntelliSense, header resolution, and editor
diagnostics. **PlatformIO does not read it to build the firmware.** The build
configuration comes from `platformio.ini` and the selected platform/framework.

| Change | Regenerate the compilation database? |
| --- | --- |
| Edit existing source or header contents | Usually no; build normally. |
| Add, remove, or move source files | Yes, to update the recorded compilation commands. |
| Change libraries, include paths, build flags, board, or framework | Yes, to keep IntelliSense aligned with the build. |
| Move the checkout or change toolchain installation paths | Yes, to refresh local paths. |

Regeneration can happen before or after a build. A stale database can cause
incorrect editor warnings but does not affect compilation. After updating the
configuration, use **Developer: Reload Window** if VS Code still shows stale
diagnostics.

Alternatively, open `apps/hdk` directly in VS Code, or use **File > Add Folder to
Workspace** to make it a workspace folder. PlatformIO IDE can then manage the
project's editor configuration through its normal project workflow.

### Multiple PlatformIO installations

If the terminal reports an obsolete Core while VS Code uses a newer one, check
which installation is selected:

```bash
which -a pio
pio --version
```

Use the PlatformIO IDE terminal to use its managed Core. On macOS, if that Core
is installed under `~/.platformio/penv`, you can also select it in a normal shell:

```bash
export PATH="$HOME/.platformio/penv/bin:$PATH"
rehash
pio --version
```

Add the `export` line at the end of `~/.zshrc` to persist that preference. See
[PlatformIO's troubleshooting guide](https://docs.platformio.org/en/latest/core/installation/troubleshooting.html#multiple-platformio-cores-in-a-system)
for removing duplicate installations.
