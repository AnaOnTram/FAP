#ifndef IMAGE_BUFFER_H
#define IMAGE_BUFFER_H

#include <Arduino.h>
#include "config.h"

// Image buffer in PSRAM if available, otherwise regular RAM
uint8_t* imageBuffer = nullptr;
uint16_t bufferIndex = 0;
bool bufferReady = false;

void ImageBuffer_Init() {
    // Try to allocate in PSRAM first (ESP32-WROVER modules)
    if (psramFound()) {
        imageBuffer = (uint8_t*)ps_malloc(IMAGE_BUFFER_SIZE);
        Serial.println("Image buffer allocated in PSRAM");
    } else {
        imageBuffer = (uint8_t*)malloc(IMAGE_BUFFER_SIZE);
        Serial.println("Image buffer allocated in RAM");
    }

    if (imageBuffer == nullptr) {
        Serial.println("ERROR: Failed to allocate image buffer!");
        return;
    }

    // Clear buffer (white = 0xFF for e-paper)
    memset(imageBuffer, 0xFF, IMAGE_BUFFER_SIZE);
    bufferIndex = 0;
    bufferReady = false;
}

void ImageBuffer_Clear() {
    if (imageBuffer != nullptr) {
        memset(imageBuffer, 0xFF, IMAGE_BUFFER_SIZE);
    }
    bufferIndex = 0;
    bufferReady = false;
}

bool ImageBuffer_IsReady() {
    return bufferReady && (imageBuffer != nullptr);
}

uint8_t* ImageBuffer_GetPtr() {
    return imageBuffer;
}

uint16_t ImageBuffer_GetSize() {
    return IMAGE_BUFFER_SIZE;
}

// Receive image data chunk (already processed 1-bit data)
bool ImageBuffer_Receive(const uint8_t* data, uint16_t len) {
    if (imageBuffer == nullptr) return false;

    uint16_t copyLen = min(len, (uint16_t)(IMAGE_BUFFER_SIZE - bufferIndex));
    if (copyLen > 0) {
        memcpy(imageBuffer + bufferIndex, data, copyLen);
        bufferIndex += copyLen;
    }

    if (bufferIndex >= IMAGE_BUFFER_SIZE) {
        bufferReady = true;
        Serial.printf("Image buffer full: %d bytes\n", bufferIndex);
    }

    return true;
}

// Reset buffer for new image
void ImageBuffer_Reset() {
    bufferIndex = 0;
    bufferReady = false;
}

// Get current buffer fill level
uint16_t ImageBuffer_GetFillLevel() {
    return bufferIndex;
}

// Set a single byte at position
void ImageBuffer_SetByte(uint16_t pos, uint8_t value) {
    if (imageBuffer != nullptr && pos < IMAGE_BUFFER_SIZE) {
        imageBuffer[pos] = value;
    }
}

// Set a pixel at position (x, y)
// In 1-bit mode: 0 = black, 1 = white
void ImageBuffer_SetPixel(uint16_t x, uint16_t y, bool white) {
    if (imageBuffer == nullptr) return;
    if (x >= EPD_WIDTH || y >= EPD_HEIGHT) return;

    uint16_t byteIndex = (y * EPD_WIDTH + x) / 8;
    uint8_t bitIndex = 7 - (x % 8);  // MSB first

    if (byteIndex < IMAGE_BUFFER_SIZE) {
        if (white) {
            imageBuffer[byteIndex] |= (1 << bitIndex);
        } else {
            imageBuffer[byteIndex] &= ~(1 << bitIndex);
        }
    }
}

// Fill buffer with a test pattern
void ImageBuffer_TestPattern() {
    if (imageBuffer == nullptr) return;

    // Create a simple test pattern: checkerboard
    for (uint16_t y = 0; y < EPD_HEIGHT; y++) {
        for (uint16_t x = 0; x < EPD_WIDTH; x++) {
            bool white = ((x / 20) + (y / 20)) % 2 == 0;
            ImageBuffer_SetPixel(x, y, white);
        }
    }
    bufferReady = true;
}

#endif // IMAGE_BUFFER_H
