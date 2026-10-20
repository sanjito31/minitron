#pragma once

// Call once during startup, after WiFi starts. Returns 0 on success.
int init_device_id();

// Returns the persisted UUID, or nullptr until initialization succeeds.
const char *get_device_id();
