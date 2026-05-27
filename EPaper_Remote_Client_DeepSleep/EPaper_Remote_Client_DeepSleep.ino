/**
 * EPaper Remote Client — Deep Sleep Edition
 *
 * Functionally identical to EPaper_Remote_Client but uses ESP32 deep sleep
 * between polls, reducing average current from ~80 mA to ~5 mA.
 *
 * Key differences from the normal version:
 *   - Deep sleep causes a full reboot — setup() runs on every wake
 *   - storedVersion lives in RTC memory and survives across deep sleeps
 *   - loop() is never reached; setup() ends by calling esp_deep_sleep_start()
 *   - POLL_INTERVAL_MS can be set much longer (5–30 min) to save more power
 */

#include <WiFi.h>
#include "config.h"
#include "epd_driver.h"
#include "image_buffer.h"
#include "http_client.h"

// Survives deep sleep — tracks the last successfully displayed version
RTC_DATA_ATTR char storedVersion[16] = {0};

// ── WiFi ──────────────────────────────────────────────────────────
static bool connectWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT_MS) {
            Serial.println("\n[WiFi] Timeout");
            return false;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n[WiFi] IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
}

// ── Poll and optionally update display ────────────────────────────
static void checkAndUpdate() {
    String newVersion = pollVersion();

    if (newVersion.length() == 0) {
        Serial.println("[Poll] Server unreachable");
        return;
    }

    if (strcmp(newVersion.c_str(), storedVersion) == 0) {
        Serial.printf("[Poll] No change (%s)\n", storedVersion);
        return;
    }

    Serial.printf("[Poll] Version changed: [%s] → [%s]\n", storedVersion, newVersion.c_str());

    if (downloadAndDisplay()) {
        strncpy(storedVersion, newVersion.c_str(), sizeof(storedVersion) - 1);
        storedVersion[sizeof(storedVersion) - 1] = '\0';
        Serial.println("[Poll] Display updated — version saved to RTC memory");
    } else {
        Serial.println("[Poll] Update failed — will retry next wake");
    }
}

// ── Setup — runs on every wake from deep sleep ────────────────────
void setup() {
    Serial.begin(115200);
    delay(100);

    Serial.println("\n==========================================");
    Serial.println("  EPaper Remote Client (Deep Sleep)");
    Serial.printf("  Wake cause: %s\n",
        esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER ? "timer" : "power-on/reset");
    Serial.printf("  Stored version: [%s]\n", storedVersion);
    Serial.println("==========================================");

    EPD_Init_Pins();
    ImageBuffer_Init();

    if (connectWiFi()) {
        checkAndUpdate();
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
    }

    // Hold GPIO levels during sleep so display SPI pins stay stable
    gpio_deep_sleep_hold_en();

    Serial.printf("[Sleep] Next poll in %lu s\n", POLL_INTERVAL_MS / 1000);
    Serial.flush();

    esp_sleep_enable_timer_wakeup((uint64_t)POLL_INTERVAL_MS * 1000ULL);
    esp_deep_sleep_start();  // never returns
}

// ── Loop ──────────────────────────────────────────────────────────
void loop() {
    // Never reached — setup() always ends in deep sleep
}
