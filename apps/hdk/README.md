# Minitron HDK

A hardware development kit (HDK) for ESP32 that fetches, stores, and renders WebP images and animations on a HUB75 LED matrix panel.

## Overview

This project turns an ESP32 into a networked display system that periodically downloads WebP graphics from a remote API endpoint and displays them on a DMA-driven HUB75 LED matrix panel. Perfect for creating dynamic digital signage, art installations, or live data visualizations.

## Features

- **WiFi Connectivity**: Connects to your network on startup
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
#define OTA_PASSWORD "your-ota-password"
```

Use a strong OTA password and keep `include/secrets.h` out of Git. The OTA
handler initializes after WiFi connects, uses the hostname `minitron.local` and
port 3232, and logs update progress and errors to serial. If `OTA_PASSWORD` is
missing or empty, OTA stays disabled and display startup continues.

The handler exposes `handle_ota()` for frequent servicing and
`ota_update_in_progress()` so image downloads can pause during an update.
The current main loop does not yet service the handler; that integration is
the next step before network uploads can work.

### 3. Build and Upload

```bash
pio run --target upload
pio device monitor
```

## API Endpoint

The ESP32 expects a server running at the configured `SERVER_API_URL` with the following endpoint:

```
GET /api/current
```

**Response**: Raw WebP image data (binary)

**Example**: Your server should return a WebP file when this endpoint is accessed. The ESP32 will poll this endpoint every 10 seconds.

## How It Works

1. **Startup**: ESP32 connects to WiFi and initializes the LED matrix display
2. **Initial Display**: Shows a default "no apps" graphic from embedded assets
3. **Main Loop**:
   - Requests new graphic from `SERVER_API_URL/api/current`
   - Downloads WebP data into memory
   - Decodes WebP and renders pixels to the LED matrix
   - Waits 10 seconds and repeats
4. **Background Rendering**: A separate FreeRTOS task handles continuous display updates for animations

## Project Structure

- [src/main.cpp](src/main.cpp) - Main program loop and initialization
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
