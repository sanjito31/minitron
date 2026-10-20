#include <Arduino.h>
#include <esp_random.h>
#include <nvs.h>
#include <cstring>

#include "device_id.h"

namespace {
constexpr char NVS_NAMESPACE[] = "minitron";
constexpr char NVS_KEY[] = "device_id";
constexpr size_t UUID_LENGTH = 36;
char device_id[UUID_LENGTH + 1] = {};

bool valid_uuid(const char *uuid)
{
    if (strlen(uuid) != UUID_LENGTH || uuid[14] != '4' ||
        strchr("89abAB", uuid[19]) == nullptr) {
        return false;
    }

    for (size_t i = 0; i < UUID_LENGTH; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (uuid[i] != '-') {
                return false;
            }
        } else if (!((uuid[i] >= '0' && uuid[i] <= '9') ||
                     (uuid[i] >= 'a' && uuid[i] <= 'f') ||
                     (uuid[i] >= 'A' && uuid[i] <= 'F'))) {
            return false;
        }
    }
    return true;
}

void generate_uuid(char *uuid)
{
    uint8_t bytes[16];
    // WiFi must be active to supply entropy to the hardware RNG.
    esp_fill_random(bytes, sizeof(bytes));
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // UUID version 4.
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC UUID variant.

    constexpr char HEX_DIGITS[] = "0123456789abcdef";
    size_t position = 0;
    for (size_t i = 0; i < sizeof(bytes); ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10) {
            uuid[position++] = '-';
        }
        uuid[position++] = HEX_DIGITS[bytes[i] >> 4];
        uuid[position++] = HEX_DIGITS[bytes[i] & 0x0f];
    }
    uuid[position] = '\0';
}
}

int init_device_id()
{
    if (device_id[0] != '\0') {
        return 0;
    }

    // Arduino initializes the default NVS partition before setup().
    nvs_handle_t handle;
    esp_err_t error = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (error != ESP_OK) {
        Serial.printf("Could not open device ID storage: %s\n", esp_err_to_name(error));
        return 1;
    }

    char candidate[UUID_LENGTH + 1] = {};
    size_t length = sizeof(candidate);
    error = nvs_get_str(handle, NVS_KEY, candidate, &length);
    if (error == ESP_OK && valid_uuid(candidate)) {
        memcpy(device_id, candidate, sizeof(device_id));
        nvs_close(handle);
        return 0;
    }

    if (error != ESP_OK && error != ESP_ERR_NVS_NOT_FOUND &&
        error != ESP_ERR_NVS_INVALID_LENGTH && error != ESP_ERR_NVS_TYPE_MISMATCH) {
        Serial.printf("Could not read device ID: %s\n", esp_err_to_name(error));
        nvs_close(handle);
        return 1;
    }

    if (error != ESP_ERR_NVS_NOT_FOUND) {
        Serial.println("Stored device ID is invalid; generating a new UUID.");
    }
    generate_uuid(candidate);
    error = nvs_set_str(handle, NVS_KEY, candidate);
    if (error == ESP_OK) {
        error = nvs_commit(handle);
    }
    nvs_close(handle);
    if (error != ESP_OK) {
        Serial.printf("Could not persist device ID: %s\n", esp_err_to_name(error));
        return 1;
    }

    // Publish the ID only after it has been saved successfully.
    memcpy(device_id, candidate, sizeof(device_id));
    return 0;
}

const char *get_device_id()
{
    return device_id[0] == '\0' ? nullptr : device_id;
}
