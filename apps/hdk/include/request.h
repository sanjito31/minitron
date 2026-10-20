#pragma once

#include <Arduino.h>

// Call only from the image polling task. Retries share an in-memory UUID across
// calls until a complete, decodable WebP is downloaded. Returns 0 on success.
// The caller owns *buf on success and must free it; failure leaves nullptr/0.
int requestGraphic(const String &URL, uint8_t **buf, size_t *len);
