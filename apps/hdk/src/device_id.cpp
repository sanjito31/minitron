#include <Arduino.h>
#include <nvs.h>
#include <cstring>

#include "device_id.h"
#include "uuid.h"

namespace {
constexpr char NVS_NAMESPACE[] = "minitron";
constexpr char NVS_KEY[] = "device_id";
char device_id[UUID_LENGTH + 1] = {};
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
