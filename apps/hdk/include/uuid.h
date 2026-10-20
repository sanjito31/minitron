#pragma once

#include <cstddef>

constexpr size_t UUID_LENGTH = 36;

bool valid_uuid(const char *uuid);

// Requires a buffer of at least UUID_LENGTH + 1 bytes and active WiFi for entropy.
void generate_uuid(char *uuid);
