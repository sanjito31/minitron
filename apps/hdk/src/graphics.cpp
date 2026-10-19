#include <Adafruit_GFX.h>
#include "graphics.h"
#include "display.h"
#include "ota.h"

extern "C" {
    #include "webp/demux.h"
    #include "webp/decode.h"
}

struct graphic_state *state = nullptr;

int init_graphics(const void *webp, size_t len)
{
	if (state) {
		Serial.println("Graphics state already initialized.");
		return 1;
	}

	state = (struct graphic_state *)calloc(1, sizeof(struct graphic_state));

	state->_buf = ps_calloc(1, len);
	if (!state->_buf) 
		state->_buf = calloc(1, len);
	if (!state->_buf) {
		Serial.println("Could not allocate memory.");
		return 1;
	}

	memcpy(state->_buf, webp, len);
	state->_counter = 0;
	state->_len = len;
	state->_mutex = xSemaphoreCreateMutex();

	if (state->_mutex == NULL) {
		Serial.println("Could not create mutex.");
		return 1;
	}

	if (init_display()) {
		Serial.println("Could not initialize display.");
		return 1;
	}

	BaseType_t ret = xTaskCreatePinnedToCore(
		loop_graphics,
		"loop_graphics",
		4096,
		NULL,
		2,
		NULL,
		1
	);

	if (ret != pdPASS) {
		Serial.println("Could not pin task.");
		return 1;
	}
	
	return 0;

}

void loop_graphics(void *arg)
{
	void *webp = nullptr;
	size_t len = 0;
	int counter = -1;

	for (;;) {
		if (ota_update_in_progress()) {
			// Leave the current frame in the display buffer while OTA runs.
			vTaskDelay(pdMS_TO_TICKS(10));
			continue;
		}

		if (pdTRUE != xSemaphoreTake(state->_mutex, portMAX_DELAY)) {
			Serial.println("Could not take mutex.");
			return;
		}

		if (counter != state->_counter) {
			if (state->_len > len) {
				if (webp) free(webp);
				webp = ps_malloc(state->_len);
				if (!webp)
					webp = malloc(state->_len);
				if (!webp) {
					Serial.println("Could not allocate.");
					return;
				}
			}
			memcpy(webp, state->_buf, state->_len);
			len = state->_len;
			counter = state->_counter;
		}

		if (pdTRUE != xSemaphoreGive(state->_mutex)) {
			Serial.println("Could not give mutex.");
			return;
		}

		if (draw_webp_graphic((uint8_t *)webp, len)) {
			Serial.println("Could not draw graphic.");
			return;
		}
	}

	return;
}


int update_graphics(const void *webp, size_t len)
{
	if (pdTRUE != xSemaphoreTake(state->_mutex, portMAX_DELAY)) {
		Serial.println("Could not take mutex.");
		return 1;
	}

	if (len > state->_len) {
		free(state->_buf);
		state->_buf = ps_malloc(len);
		if (!state->_buf)
			state->_buf = malloc(len);
		if (!state->_buf) {
			Serial.println("Could not allocate graphics buffer.");
			return 1;
		}
	}

	memcpy(state->_buf, webp, len);
	state->_len = len;
	state->_counter++;
	
	if (pdTRUE != xSemaphoreGive(state->_mutex)) {
		Serial.println("Could not give mutex.");
		return 1;
	}
	
	return 0;
}

int draw_webp_graphic(uint8_t *buf, size_t len)
{
	if (ota_update_in_progress()) {
		return 0;
	}

	WebPData webpData;
  	WebPDataInit(&webpData);
  	webpData.bytes = buf;
  	webpData.size = len;

  	WebPAnimDecoderOptions decoderOptions;
  	WebPAnimDecoderOptionsInit(&decoderOptions);
  	decoderOptions.color_mode = MODE_RGBA;

  	WebPAnimDecoder *decoder = WebPAnimDecoderNew(&webpData, &decoderOptions);
  	if (decoder == NULL) {
    		Serial.println("Could not create WEBP decoder.");
    		return 1;
  	}

  	WebPAnimInfo animation;
  	if (!WebPAnimDecoderGetInfo(decoder, &animation)) {
    		Serial.println("Could not get WebP animation");
    		return 1;
  	}

  	int lastTimestamp = 0;
  	int delay = 0;
  	TickType_t drawStartTick = xTaskGetTickCount();

  	// Draw each frame, and sleep for the delay
  	for (int j = 0; j < animation.frame_count; j++) {
		if (ota_update_in_progress()) {
			break;
		}

    		uint8_t *pix;
    		int timestamp;
    		WebPAnimDecoderGetNext(decoder, &pix, &timestamp);
    		if (delay > 0)
      			xTaskDelayUntil(&drawStartTick, pdMS_TO_TICKS(delay));
		if (ota_update_in_progress()) {
			break;
		}
    		drawStartTick = xTaskGetTickCount();
    		display_draw(pix, animation.canvas_width, animation.canvas_height, 4, 0, 1, 2);
    		delay = timestamp - lastTimestamp;
    		lastTimestamp = timestamp;
	}
	if (delay > 0 && !ota_update_in_progress())
    		xTaskDelayUntil(&drawStartTick, pdMS_TO_TICKS(delay));

  	// In case of a single frame, sleep for 1s
	if (animation.frame_count == 1 && !ota_update_in_progress()) {
    		xTaskDelayUntil(&drawStartTick, pdMS_TO_TICKS(1000));
  	}

  	WebPAnimDecoderDelete(decoder);
  	return 0;
}
