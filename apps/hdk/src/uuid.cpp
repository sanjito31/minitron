#include <esp_random.h>
#include <cstdint>
#include <cstring>

#include "uuid.h"

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
