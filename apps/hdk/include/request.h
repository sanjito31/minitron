#pragma once
#include <ArduinoJson.h>


// struct JsonResponse {
//         JsonDocument doc;
//         int httpCode;
//         DeserializationError jsonErr;
//         bool ok;
// };


// JsonResponse requestJSON(const String& URL);

int requestGraphic(const String& URL, uint8_t **buf, size_t *len);