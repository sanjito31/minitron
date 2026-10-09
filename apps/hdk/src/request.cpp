#include <HTTPClient.h>
#include "request.h"

#define SUB_PATH	"/api/current"


int requestGraphic(const String& URL, uint8_t **buf, size_t *len)
{
	size_t _len 	= 0;
	uint8_t *_buf 	= nullptr;

	HTTPClient http;
	http.begin(URL + SUB_PATH);
	int code = http.GET();

	if (code != HTTP_CODE_OK) {
		http.end();
		Serial.printf("Image download failed: %d\n", code);
		return -1;
	}

	_len = http.getSize();

	if (_len <= 0) {
		Serial.println("Unknown content length");
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
  	while (totalRead < _len && http.connected()) {
    		size_t available = stream->available();
    		if (available == 0) {
      			delay(1);
      			continue;
    		}

    		size_t bytesRead = stream->readBytes(_buf + totalRead, _len - totalRead);
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
