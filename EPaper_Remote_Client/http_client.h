#ifndef HTTP_CLIENT_H
#define HTTP_CLIENT_H

#include <HTTPClient.h>
#if HTTPS_ENABLED
#include <WiFiClientSecure.h>
#endif
#include <ArduinoJson.h>
#include "config.h"
#include "image_buffer.h"
#include "epd_driver.h"

// Build a full URL from a path component
static String buildUrl(const char* path) {
    String url = HTTPS_ENABLED ? "https://" : "http://";
    url += SERVER_HOST;
    url += ":";
    url += SERVER_PORT;
    url += path;
    return url;
}

// Add common headers (API key if configured)
static void addCommonHeaders(HTTPClient& http) {
    if (strlen(API_KEY) > 0) {
        http.addHeader("X-API-Key", API_KEY);
    }
}

// Poll /api/content/version — returns version string, "" on failure
String pollVersion() {
    HTTPClient http;

#if HTTPS_ENABLED
    WiFiClientSecure client;
    client.setInsecure();
    http.begin(client, buildUrl("/api/content/version"));
#else
    http.begin(buildUrl("/api/content/version"));
#endif

    http.setTimeout(10000);
    addCommonHeaders(http);

    String version = "";
    int code = http.GET();

    if (code == HTTP_CODE_OK) {
        String body = http.getString();
        StaticJsonDocument<128> doc;
        if (deserializeJson(doc, body) == DeserializationError::Ok) {
            version = doc["version"].as<String>();
        } else {
            Serial.println("[HTTP] JSON parse error for version");
        }
    } else {
        Serial.printf("[HTTP] Version poll failed: %d\n", code);
    }

    http.end();
    return version;
}

// Download /api/content/image (15000 raw bytes) and render to display
// Returns true on success
bool downloadAndDisplay() {
    HTTPClient http;

#if HTTPS_ENABLED
    WiFiClientSecure client;
    client.setInsecure();
    http.begin(client, buildUrl("/api/content/image"));
#else
    http.begin(buildUrl("/api/content/image"));
#endif

    http.setTimeout(30000);
    addCommonHeaders(http);

    int code = http.GET();
    if (code != HTTP_CODE_OK) {
        Serial.printf("[HTTP] Image download failed: %d\n", code);
        http.end();
        return false;
    }

    int contentLen = http.getSize();
    Serial.printf("[HTTP] Content-Length: %d (expected %d)\n", contentLen, IMAGE_BUFFER_SIZE);

    if (contentLen != IMAGE_BUFFER_SIZE) {
        Serial.println("[HTTP] Unexpected content length — aborting");
        http.end();
        return false;
    }

    // Stream directly into the image buffer
    WiFiClient* stream = http.getStreamPtr();
    uint8_t* buf = ImageBuffer_GetPtr();
    int remaining = IMAGE_BUFFER_SIZE;
    uint32_t deadline = millis() + 30000;

    while (remaining > 0 && millis() < deadline) {
        int avail = stream->available();
        if (avail > 0) {
            int n = stream->readBytes(buf + (IMAGE_BUFFER_SIZE - remaining),
                                      min(avail, remaining));
            remaining -= n;
        } else if (!http.connected()) {
            break;
        } else {
            delay(1);
        }
    }

    http.end();

    if (remaining != 0) {
        Serial.printf("[HTTP] Incomplete download — %d bytes missing\n", remaining);
        return false;
    }

    Serial.println("[EPD] Rendering image to display...");
    EPD_4in2_V2_Display(buf);
    Serial.println("[EPD] Done");
    return true;
}

#endif // HTTP_CLIENT_H
