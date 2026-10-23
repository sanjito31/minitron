#include <HTTPClient.h>
#include <WiFi.h>
#include <cstdio>

#include "device_id.h"
#include "ota.h"
#include "request.h"
#include "uuid.h"
#include "webp/demux.h"

namespace {
constexpr int HTTP_TIMEOUT_MS = 3000;
constexpr unsigned long DOWNLOAD_TIMEOUT_MS = 15000;
constexpr unsigned int MAX_ATTEMPTS = 3;
constexpr unsigned long RETRY_DELAY_MS = 500;

// Owned by the image polling task. Retained across calls, but not across reboots.
char pending_request_id[UUID_LENGTH + 1] = {};

bool requests_paused()
{
    return ota_update_in_progress() || WiFi.status() != WL_CONNECTED;
}

bool valid_webp(const uint8_t *buffer, size_t length)
{
    const WebPData data = {buffer, length};
    WebPAnimDecoder *decoder = WebPAnimDecoderNew(&data, nullptr);
    if (decoder == nullptr) {
        return false;
    }

    WebPAnimInfo info;
    bool valid = WebPAnimDecoderGetInfo(decoder, &info) && info.frame_count > 0;
    for (uint32_t i = 0; valid && i < info.frame_count; ++i) {
        if (ota_update_in_progress()) {
            valid = false;
            break;
        }
        uint8_t *pixels = nullptr;
        int timestamp = 0;
        valid = WebPAnimDecoderGetNext(decoder, &pixels, &timestamp);
        // Yield while checking animations without waiting for frame timestamps.
        delay(1);
    }
    WebPAnimDecoderDelete(decoder);
    return valid && !ota_update_in_progress();
}

int download_graphic(const String &endpoint, const String &body,
                     uint8_t **buffer, size_t *length)
{
    HTTPClient http;
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(endpoint)) {
        Serial.println("Could not initialize image request.");
        http.end();
        return -1;
    }
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Accept", "image/webp");
    const unsigned long started_ms = millis();
    const int code = http.POST(body);
    if (code != HTTP_CODE_OK) {
        http.end();
        Serial.printf("Image download failed: %d\n", code);
        return -1;
    }

    const int content_length = http.getSize();
    if (content_length <= 0) {
        Serial.println("Missing or invalid image content length.");
        http.end();
        return -1;
    }
    if (requests_paused() || millis() - started_ms >= DOWNLOAD_TIMEOUT_MS) {
        http.end();
        return -1;
    }

    const size_t expected = static_cast<size_t>(content_length);
    uint8_t *download = static_cast<uint8_t *>(ps_malloc(expected));
    if (!download) {
        download = static_cast<uint8_t *>(malloc(expected));
    }
    if (!download) {
        Serial.println("Could not allocate image download buffer.");
        http.end();
        return -1;
    }

    WiFiClient *stream = http.getStreamPtr();
    size_t received = 0;
    while (received < expected) {
        if (requests_paused() || millis() - started_ms >= DOWNLOAD_TIMEOUT_MS) {
            Serial.println("Image download paused, disconnected, or timed out.");
            break;
        }

        const size_t available = stream->available();
        if (available == 0) {
            if (!http.connected()) {
                break;
            }
            delay(1);
            continue;
        }

        const size_t remaining = expected - received;
        const size_t to_read = available < remaining ? available : remaining;
        const int count = stream->read(download + received, to_read);
        if (count <= 0) {
            break;
        }
        received += count;
    }
    http.end();

    if (received != expected) {
        Serial.printf("Incomplete image: got %u of %u bytes\n",
                      static_cast<unsigned int>(received),
                      static_cast<unsigned int>(expected));
        free(download);
        return -1;
    }
    if (ota_update_in_progress() || !valid_webp(download, received)) {
        Serial.println("WebP validation failed or was interrupted for OTA.");
        free(download);
        return -1;
    }

    *buffer = download;
    *length = received;
    return 0;
}
}

int requestGraphic(const String &URL, uint8_t **buf, size_t *len)
{
    *buf = nullptr;
    *len = 0;
    const char *device_id = get_device_id();
    if (device_id == nullptr || requests_paused()) {
        return -1;
    }

    if (pending_request_id[0] == '\0') {
        generate_uuid(pending_request_id);
    }
    const String endpoint = URL + "/api/current";
    // UUIDs contain only hexadecimal digits and hyphens, so no JSON escaping is needed.
    char json[sizeof("{\"device_id\":\"\",\"request_id\":\"\"}") + 2 * UUID_LENGTH];
    snprintf(json, sizeof(json), "{\"device_id\":\"%s\",\"request_id\":\"%s\"}",
             device_id, pending_request_id);
    const String body(json);

    for (unsigned int attempt = 0; attempt < MAX_ATTEMPTS; ++attempt) {
        if (requests_paused()) {
            break;
        }
        Serial.printf("Image request %s, attempt %u/%u\n",
                      pending_request_id, attempt + 1, MAX_ATTEMPTS);
        if (download_graphic(endpoint, body, buf, len) == 0) {
            // A successful HTTP status alone is not enough: the entire WebP is valid.
            pending_request_id[0] = '\0';
            return 0;
        }
        if (requests_paused()) {
            break;
        }
        if (attempt + 1 < MAX_ATTEMPTS) {
            delay(RETRY_DELAY_MS);
        }
    }

    Serial.printf("Keeping request %s for the next polling cycle.\n", pending_request_id);
    return -1;
}
