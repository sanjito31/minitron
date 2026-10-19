#include <WiFi.h>
#include "secrets.h"

// WiFi Network Info
const char* SSID        = WIFI_SSID;
const char* PASS        = WIFI_PASS;
int WIFI_CONN           = 0;

int init_wifi()
{
	Serial.println("Trying WiFi...");
	pinMode(LED_BUILTIN, OUTPUT);
	digitalWrite(LED_BUILTIN, LOW);
	WiFi.mode(WIFI_STA);
	WiFi.setAutoReconnect(true);
	WiFi.begin(SSID, PASS);
	
	const unsigned long connection_timeout_ms = 25000;
	const unsigned long connection_started_ms = millis();
	while (WiFi.status() != WL_CONNECTED) {
		if (millis() - connection_started_ms >= connection_timeout_ms) {
			Serial.println("\nWiFi connection timed out.");
			return 1;
		}
		Serial.print(".");
		delay(500);
	}

  	digitalWrite(LED_BUILTIN, HIGH);
  	Serial.println("\nWi-Fi connected. IP = " + WiFi.localIP().toString());
    return 0;
}
