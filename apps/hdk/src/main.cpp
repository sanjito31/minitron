#include <Arduino.h>
#include "secrets.h"
#include "request.h"
#include "graphics.h"
#include "wifi_setup.h"
#include "ota.h"
#include "display.h"
#include "assets.h"


// Serial BAUD Rate
#define BAUD            	115200

#define	GFX_LOOP_INTERVAL_S	10



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

	// Initialize Graphics and Display
	if (init_graphics(ASSET_NOAPPS_WEBP, ASSET_NOAPPS_WEBP_LEN)) {
		Serial.println("Error initializing graphics or display.");
		return;
	}

}

uint8_t *webp = nullptr;
size_t len = 0;

void loop() 
{
	if (requestGraphic(SERVER_API_URL, &webp, &len)) {
		Serial.println("Failed to get new image.");
	} else {
		update_graphics(webp, len);
		if (webp) free(webp);
	}

	vTaskDelay(pdMS_TO_TICKS(GFX_LOOP_INTERVAL_S * 1000UL));
}
