#include <Arduino.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#include <atomic>

#include "ota.h"
#include "secrets.h"

namespace {
bool ota_started = false;
std::atomic<bool> update_in_progress{false};
unsigned int last_progress = 101;
}

int init_ota()
{
    if (ota_started) {
        return 0;
    }

#ifndef OTA_PASSWORD
    Serial.println("OTA disabled: define OTA_PASSWORD in include/secrets.h.");
    return 1;
#else
    const char *password = OTA_PASSWORD;
    if (password == nullptr || password[0] == '\0') {
        Serial.println("OTA disabled: OTA_PASSWORD must not be empty.");
        return 1;
    }

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("OTA initialization requires a WiFi connection.");
        return 1;
    }

    ArduinoOTA.setHostname(HOSTNAME);
    ArduinoOTA.setPort(PORT);
    ArduinoOTA.setPassword(password);

    ArduinoOTA.onStart([]() {
        update_in_progress.store(true);
        last_progress = 101;
        Serial.println("OTA update started.");
    });

    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        if (total == 0) {
            return;
        }

        const unsigned int percent =
            (static_cast<uint64_t>(progress) * 100) / total;
        if (percent != last_progress) {
            Serial.printf("OTA progress: %u%%\n", percent);
            last_progress = percent;
        }
    });

    ArduinoOTA.onEnd([]() {
        // Keep image downloads paused until the successful update reboots.
        Serial.println("OTA update complete. Rebooting...");
    });

    ArduinoOTA.onError([](ota_error_t error) {
        update_in_progress.store(false);
        const char *reason = "unknown error";
        switch (error) {
            case OTA_AUTH_ERROR: reason = "authentication failed"; break;
            case OTA_BEGIN_ERROR: reason = "could not begin update"; break;
            case OTA_CONNECT_ERROR: reason = "connection failed"; break;
            case OTA_RECEIVE_ERROR: reason = "transfer failed"; break;
            case OTA_END_ERROR: reason = "could not finalize update"; break;
            default: break;
        }
        Serial.printf("OTA error %u: %s\n", static_cast<unsigned int>(error), reason);
    });

    ArduinoOTA.begin();
    ota_started = true;
    Serial.println("OTA ready: minitron.local (" + WiFi.localIP().toString() + "), port 3232.");
    return 0;
#endif
}

void handle_ota()
{
    if (ota_started && WiFi.status() == WL_CONNECTED) {
        ArduinoOTA.handle();
    }
}

bool ota_update_in_progress()
{
    return update_in_progress.load();
}
