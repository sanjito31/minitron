#include <Arduino.h>
#include <WiFi.h>
#include "secrets.h"
#include "request.h"
#include "graphics.h"
#include "wifi_setup.h"
#include "ota.h"
#include "display.h"
#include "assets.h"
#include "device_id.h"


// Serial BAUD Rate
#define BAUD            	115200

#define	GFX_LOOP_INTERVAL_S	10

static void poll_graphics(void *arg);


void setup() 
{
	// Start
	Serial.begin(BAUD);
	Serial.println("Starting...");

	// WiFi	
	if (init_wifi()) {
		Serial.println("WIFI ERROR");
		return;
	}

	// Initialize OTA before graphics so display errors do not prevent recovery.
	if (init_ota()) {
		Serial.println("OTA is unavailable; continuing display startup.");
	}

	if (init_device_id()) {
		Serial.println("Device ID unavailable; image polling stopped. OTA remains available.");
		return;
	}
	Serial.printf("Device ID: %s\n", get_device_id());

	// Initialize Graphics and Display
	if (init_graphics(ASSET_NOAPPS_WEBP, ASSET_NOAPPS_WEBP_LEN)) {
		Serial.println("Error initializing graphics or display.");
		return;
	}

	if (xTaskCreate(poll_graphics, "poll_graphics", 8192, nullptr, 1, nullptr) != pdPASS) {
		Serial.println("Could not start image polling; OTA remains available.");
	}

}

void loop() 
{
	handle_ota();
	vTaskDelay(pdMS_TO_TICKS(10));
}

static void poll_graphics(void *arg)
{
	for (;;) {
		if (WiFi.status() == WL_CONNECTED && !ota_update_in_progress()) {
			uint8_t *webp = nullptr;
			size_t len = 0;
			if (requestGraphic(SERVER_API_URL, &webp, &len)) {
				Serial.println("Failed to get new image.");
			} else if (!ota_update_in_progress()) {
				update_graphics(webp, len);
			}
			free(webp);
		}

		vTaskDelay(pdMS_TO_TICKS(GFX_LOOP_INTERVAL_S * 1000UL));
	}
}
