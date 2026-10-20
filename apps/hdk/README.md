# Minitron HDK

A hardware development kit (HDK) for ESP32 that fetches, stores, and renders WebP images and animations on a HUB75 LED matrix panel.

## Overview

This project turns an ESP32 into a networked display system that periodically downloads WebP graphics from a remote API endpoint and displays them on a DMA-driven HUB75 LED matrix panel. Perfect for creating dynamic digital signage, art installations, or live data visualizations.

## Features

- **WiFi Connectivity**: Connects to your network on startup
- **Persistent Device ID**: Stores a UUID v4 in NVS and exposes it through a getter
- **Periodic API Polling**: Fetches new graphics from a configurable endpoint every 10 seconds
- **WebP Decoding**: Renders WebP images and animations using libwebp
- **DMA Display**: Uses ESP32 HUB75 LED matrix panel with DMA for smooth, flicker-free rendering
- **Dual-core Processing**: Graphics rendering runs on a separate FreeRTOS task for optimal performance
- **Memory Management**: Smart memory allocation using PSRAM when available

## Hardware Requirements

- ESP32 development board (tested with ESP32 DOIT DevKit v1)
- HUB75 LED matrix panel
- HUB75 adapter board with the following pin configuration:
  - R1: GPIO18, G1: GPIO25, B1: GPIO5
  - R2: GPIO17, G2: GPIO33, B2: GPIO16
  - A: GPIO4, B: GPIO3, C: GPIO0, D: GPIO21, E: GPIO32
  - LAT: GPIO19, OE: GPIO15, CLK: GPIO2

## Software Dependencies

The project uses PlatformIO with the following libraries:

- `ESP32 HUB75 LED MATRIX PANEL DMA Display` (v3.0.14)
- `Adafruit GFX Library` (v1.12.4)
- `ArduinoJson` (v7.4.2)
- `libwebp` (included as git submodule)

## Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd minitron-hdk
git submodule update --init --recursive
```

### 2. Configure WiFi and API

Edit [include/secrets.h](include/secrets.h) with your credentials:

```cpp
#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASS "your-wifi-password"
#define SERVER_API_URL "http://your-api-server:port"
```

Create `apps/hdk/.env` using [.env.example](.env.example) as a reference:

```dotenv
MINITRON_OTA_PASSWORD='your-ota-password'
```

Keep `.env` and `include/secrets.h` out of Git. `upload.py` reads the password
and passes it to PlatformIO through the `build_flags` and `upload_flags` in
`platformio.ini`. Do not define `OTA_PASSWORD` in `secrets.h`.

The OTA handler initializes after WiFi connects, uses the hostname
`minitron.local` and port 3232, and logs update progress and errors to serial.

The handler exposes `handle_ota()` for frequent servicing and
`ota_update_in_progress()` so image downloads can pause during an update.
The main loop services the handler every 10 ms when idle. Image polling runs
in a separate FreeRTOS task, so a slow API request does not block OTA servicing.
New image requests pause during OTA, and an active image body download checks
for OTA cancellation between reads. HTTP connection and read timeouts are
3 seconds; the image body loop also enforces a 15-second request deadline.
During OTA, the graphics task stops starting new frames and leaves the last
frame in the display buffer. An in-flight frame can finish before rendering
pauses. An interrupted animation releases its decoder; after an OTA error,
rendering resumes from the beginning of the current animation. Successful
updates reboot into the new firmware.

### 3. Build and Upload

Run the following commands from the monorepo root. Install the upload script's
dependency once:

```bash
python3 -m pip install -r apps/hdk/requirements.txt
```

Connect the ESP32 over USB and list the available devices:

```bash
pio device list
```

On macOS, the ESP32's device path will likely look like
`/dev/cu.usbserial-0001` or `/dev/cu.SLAB_USBtoUART`. Use the exact path listed
for your board. If you are unsure which entry is yours, compare the list with
the ESP32 unplugged and plugged in.

Pass the selected path to `upload.py` using `--usb --port`. Replace
`/dev/cu.usbserial-0001` below with your device's path, including
`/dev/cu.SLAB_USBtoUART` if that is the one listed:

```bash
# Build without uploading.
python3 apps/hdk/upload.py --build-only

# Build and upload to the selected ESP32 over USB.
python3 apps/hdk/upload.py --usb --port /dev/cu.usbserial-0001

# Monitor serial output from the same device.
pio device monitor --port /dev/cu.usbserial-0001 --baud 115200
```

### 4. Upload over WiFi

`MINITRON_OTA_PASSWORD` in the Git-ignored `apps/hdk/.env` is the single source
of truth for both firmware and upload authentication. The Python script loads
the file using `python-dotenv`; no manual export or `source` command is needed.
Use a single-line assignment, with quotes around passwords containing spaces
or `#`. Shell variables and commands are not expanded.

From the monorepo root, build and upload over WiFi with:

```bash
python3 apps/hdk/upload.py
```

This targets `minitron.local`. To use an IP address instead:

```bash
python3 apps/hdk/upload.py --port 192.168.1.50
```

Replace the generic example IP address with the ESP32's address printed on serial.

The script runs the normal PlatformIO build-and-upload command. PlatformIO
injects `OTA_PASSWORD` into the compiler and uses the same password for upload
authentication. It only uploads if the build succeeds. The ESP32 pauses image
downloads and rendering during transfer and reboots on success.

The first upload of OTA-enabled firmware must use USB. USB is also the way to
apply a changed OTA password: until new firmware is installed, the device still
expects the old password. For USB uploads and builds without uploading:

```bash
python3 apps/hdk/upload.py --usb --port /dev/cu.usbserial-0001
python3 apps/hdk/upload.py --build-only
```

Replace the example serial port with yours. Omitting `--port` with `--usb` uses
automatic port selection. Use `upload.py` for builds and uploads so the password
flags are set automatically.

## Device identity

After WiFi and OTA initialization, startup reads the `device_id` string in the
`minitron` NVS namespace. A valid UUID v4 is reused without writing to flash.
If the entry is missing or malformed, the ESP32 generates a random UUID v4
and commits it to NVS before using it. Generation runs with WiFi active to
provide entropy to the [ESP32 hardware random generator](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-reference/system/random.html).

The UUID is printed to serial at startup. Firmware code can include
`device_id.h` and call `get_device_id()` to access it as a `const char *`.
The getter returns `nullptr` until initialization succeeds.

The ID survives power cycles and normal firmware uploads, including OTA, as
long as the NVS partition is preserved. A full flash erase removes it. A future
factory-reset flow can erase just the `device_id` key from the `minitron`
namespace and reboot to generate a new identity; no reset command is added here.

NVS read or write failures stop image polling and are logged to serial. OTA
remains available for recovery. The getter never exposes an ID that could not
be successfully saved.

## API Endpoint

The ESP32 expects a server running at the configured `SERVER_API_URL` with the following endpoint:

```
GET /api/current
```

**Response**: Raw WebP image data (binary)

**Example**: Your server should return a WebP file when this endpoint is accessed. The ESP32 will poll this endpoint every 10 seconds.

## How It Works

1. **Startup**: ESP32 connects to WiFi, starts OTA, loads or creates its device UUID, and initializes the LED matrix display
2. **Initial Display**: Shows a default "no apps" graphic from embedded assets
3. **Image Polling Task**:
   - Requests new graphic from `SERVER_API_URL/api/current`
   - Downloads WebP data into memory
   - Decodes WebP and renders pixels to the LED matrix
   - Waits 10 seconds and repeats
4. **Main Loop**: Services OTA and yields for 10 ms between calls
5. **Background Rendering**: A separate FreeRTOS task handles continuous display updates for animations

## Project Structure

- [src/main.cpp](src/main.cpp) - Main program loop and initialization
- [src/device_id.cpp](src/device_id.cpp) - Device identity initialization and NVS storage
- [src/uuid.cpp](src/uuid.cpp) - Reusable UUID v4 generation and validation
- [src/display.cpp](src/display.cpp) - HUB75 LED matrix display driver
- [src/graphics.cpp](src/graphics.cpp) - WebP decoding and rendering logic
- [src/request.cpp](src/request.cpp) - HTTP client for fetching graphics
- [src/wifi_setup.cpp](src/wifi_setup.cpp) - WiFi connection handling
- [include/](include/) - Header files and configuration
- [lib/libwebp/](lib/libwebp/) - WebP decoder library

## Configuration

Key settings can be modified in [src/main.cpp](src/main.cpp):

- `GFX_LOOP_INTERVAL_S` (default: 10) - Seconds between API requests
- `BAUD` (default: 115200) - Serial monitor baud rate

Display dimensions are configured in [src/display.cpp](src/display.cpp) via `MATRIX_WIDTH`, `MATRIX_HEIGHT`, and `CHAIN_LENGTH`.

## License

See LICENSE file for details.
