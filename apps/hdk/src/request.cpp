#include <HTTPClient.h>
#include <WiFi.h>
#include "ota.h"
#include "request.h"

#define SUB_PATH	"/api/current"

namespace {
constexpr int HTTP_TIMEOUT_MS = 3000;
constexpr unsigned long DOWNLOAD_TIMEOUT_MS = 15000;
}

int requestGraphic(const String& URL, uint8_t **buf, size_t *len)
{
	*buf = nullptr;
	*len = 0;
	if (ota_update_in_progress() || WiFi.status() != WL_CONNECTED) {
		return -1;
	}

	size_t _len 	= 0;
	uint8_t *_buf 	= nullptr;

	HTTPClient http;
	http.setConnectTimeout(HTTP_TIMEOUT_MS);
	http.setTimeout(HTTP_TIMEOUT_MS);
	if (!http.begin(URL + SUB_PATH)) {
		Serial.println("Could not initialize image request.");
		return -1;
	}
	const unsigned long download_started_ms = millis();
	int code = http.GET();

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
	_len = static_cast<size_t>(content_length);

	if (ota_update_in_progress() ||
		millis() - download_started_ms >= DOWNLOAD_TIMEOUT_MS) {
		http.end();
		return -1;
	}


	_buf = (uint8_t *)ps_malloc(_len);
	if (!_buf) _buf = (uint8_t*)malloc(_len);
  	if (!_buf) {
    		Serial.println("Allocation failed");
    		http.end();
    		return -1;
  	}
	
	WiFiClient* stream = http.getStreamPtr();

	size_t totalRead = 0;
	while (totalRead < _len) {
		if (ota_update_in_progress()) {
			Serial.println("Image download cancelled for OTA.");
			break;
		}
		if (WiFi.status() != WL_CONNECTED ||
			millis() - download_started_ms >= DOWNLOAD_TIMEOUT_MS) {
			Serial.println("Image download disconnected or timed out.");
			break;
		}

    		size_t available = stream->available();
    		if (available == 0) {
			if (!http.connected()) {
				break;
			}
      			delay(1);
      			continue;
    		}

		const size_t remaining = _len - totalRead;
		const size_t bytes_to_read = available < remaining ? available : remaining;
		const int bytesRead = stream->read(_buf + totalRead, bytes_to_read);
		if (bytesRead <= 0) {
			break;
		}
    		totalRead += bytesRead;
  	}

	http.end();

	if (totalRead == _len) {
		Serial.printf("Received %d bytes\n", totalRead);
		*buf = _buf;
		*len = _len;
		return 0;
	}

	Serial.printf("Incomplete: got %d of %d bytes\n", totalRead, _len);
	free(_buf);
	return -1;
}
