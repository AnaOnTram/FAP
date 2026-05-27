/**
 * EPaper Remote Client
 * ESP32 in WiFi station mode — polls a remote server for display updates.
 *
 * Flow:
 *   1. Connect to WiFi
 *   2. Every POLL_INTERVAL_MS: GET /api/content/version
 *   3. If version changed: GET /api/content/image (15000 raw bytes)
 *   4. Render to 4.2" V2 E-Paper display
 */

#include <WiFi.h>
#include "config.h"
#include "epd_driver.h"
#include "image_buffer.h"
#include "http_client.h"

String  currentVersion  = "";
unsigned long lastPollMs = 0;

// ── WiFi ──────────────────────────────────────────────────────────
void connectWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT_MS) {
            Serial.println("\n[WiFi] Connection timeout");
            return;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n[WiFi] Connected — IP: %s\n", WiFi.localIP().toString().c_str());
}

// ── Poll + update ─────────────────────────────────────────────────
void checkAndUpdate() {
    Serial.println("[Poll] Checking server for updates...");

    String newVersion = pollVersion();
    if (newVersion.length() == 0) {
        Serial.println("[Poll] Could not reach server");
        return;
    }

    if (newVersion == currentVersion) {
        Serial.printf("[Poll] No change (version: %s)\n", newVersion.c_str());
        return;
    }

    Serial.printf("[Poll] New version detected: %s → %s\n",
                  currentVersion.c_str(), newVersion.c_str());

    if (downloadAndDisplay()) {
        currentVersion = newVersion;
        Serial.println("[Poll] Display updated successfully");
    } else {
        Serial.println("[Poll] Display update failed — will retry next poll");
    }
}

// ── Setup ─────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\n==========================================");
    Serial.println("  EPaper Remote Client — Starting");
    Serial.println("==========================================");

    EPD_Init_Pins();
    Serial.println("[EPD] Pins initialized");

    ImageBuffer_Init();
    Serial.println("[BUF] Image buffer allocated");

    connectWiFi();

    if (WiFi.status() == WL_CONNECTED) {
        lastPollMs = millis() - POLL_INTERVAL_MS;  // Poll immediately on boot
    }

    Serial.println("==========================================");
    Serial.printf("  Server: %s://%s:%d\n",
                  HTTPS_ENABLED ? "https" : "http", SERVER_HOST, SERVER_PORT);
    Serial.printf("  Poll interval: %lu s\n", POLL_INTERVAL_MS / 1000);
    Serial.println("==========================================\n");
}

// ── Loop ──────────────────────────────────────────────────────────
void loop() {
    // Reconnect if dropped
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] Disconnected — reconnecting...");
        WiFi.reconnect();
        delay(5000);
        return;
    }

    if (millis() - lastPollMs >= POLL_INTERVAL_MS) {
        lastPollMs = millis();
        checkAndUpdate();
    }

    delay(100);
}
