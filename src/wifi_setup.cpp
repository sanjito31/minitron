#include <WiFi.h>
#include "secrets.h"

// WiFi Network Info
const char* SSID        = WIFI_SSID;
const char* PASS        = WIFI_PASS;
int WIFI_CONN           = 0;

int init_wifi()
{
	Serial.println("Trying WiFi...");
	WiFi.begin(SSID, PASS);
	pinMode(LED_BUILTIN, OUTPUT);
	
	int cycle = 0;
	if(WiFi.status() != WL_CONNECTED) {
		Serial.println(".");
		delay(500);
		if(cycle++ >= 50) { // 500ms * 50 = 25 seconds
			Serial.println("WiFi connection timed out.");
			return 1;
		}
	}

  	digitalWrite(LED_BUILTIN, HIGH);
  	Serial.println("\nWi-Fi connected. IP = " + WiFi.localIP().toString());
        return 0;
}