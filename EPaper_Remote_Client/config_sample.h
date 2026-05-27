#ifndef CONFIG_H
#define CONFIG_H

// ===========================================
// WiFi — station mode (connects to your router)
// ===========================================
#define WIFI_SSID      "YourWiFiSSID"
#define WIFI_PASSWORD  "YourWiFiPassword"
#define WIFI_TIMEOUT_MS  15000

// ===========================================
// Remote Server
// ===========================================
#define SERVER_HOST    "your-server-ip-or-domain"  // bare host only, no http://
#define SERVER_PORT    80   // 80 for HTTP, 443 for HTTPS
#define HTTPS_ENABLED  0    // 0=HTTP, 1=HTTPS (uses setInsecure — no cert pinning)

// Optional shared secret sent as X-API-Key header.
// Leave empty string "" to disable.
#define API_KEY  ""

// ===========================================
// Polling
// ===========================================
#define POLL_INTERVAL_MS  60000UL   // Check for updates every 60 seconds

// ===========================================
// E-Paper Display (4.2" V2, 400x300 mono)
// ===========================================
#define EPD_WIDTH   400
#define EPD_HEIGHT  300
#define IMAGE_BUFFER_SIZE  15000  // 400*300/8

// SPI pins (Waveshare ESP32 Driver Board)
#define PIN_SPI_SCK   13
#define PIN_SPI_DIN   14
#define PIN_SPI_CS    15
#define PIN_SPI_BUSY  25
#define PIN_SPI_RST   26
#define PIN_SPI_DC    27
#define PIN_SPI_PWR   33

#endif // CONFIG_H
