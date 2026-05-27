#ifndef EPD_DRIVER_H
#define EPD_DRIVER_H

#include <Arduino.h>
#include "config.h"

// ===========================================
// Low-level SPI Functions (matching original)
// ===========================================

void EPD_Init_Pins() {
    pinMode(PIN_SPI_BUSY, INPUT);
    pinMode(PIN_SPI_RST, OUTPUT);
    pinMode(PIN_SPI_DC, OUTPUT);
    pinMode(PIN_SPI_SCK, OUTPUT);
    pinMode(PIN_SPI_DIN, OUTPUT);
    pinMode(PIN_SPI_CS, OUTPUT);
    pinMode(PIN_SPI_PWR, OUTPUT);

    digitalWrite(PIN_SPI_CS, HIGH);
    digitalWrite(PIN_SPI_PWR, HIGH);
    digitalWrite(PIN_SPI_SCK, LOW);
}

// Software SPI transfer - matches original exactly
void EPD_SPI_Transfer(uint8_t data) {
    digitalWrite(PIN_SPI_CS, LOW);

    for (int i = 0; i < 8; i++) {
        if ((data & 0x80) == 0)
            digitalWrite(PIN_SPI_DIN, LOW);
        else
            digitalWrite(PIN_SPI_DIN, HIGH);

        data <<= 1;
        digitalWrite(PIN_SPI_SCK, HIGH);
        digitalWrite(PIN_SPI_SCK, LOW);
    }

    digitalWrite(PIN_SPI_CS, HIGH);
}

void EPD_SendCommand(uint8_t cmd) {
    digitalWrite(PIN_SPI_DC, LOW);
    EPD_SPI_Transfer(cmd);
}

void EPD_SendData(uint8_t data) {
    digitalWrite(PIN_SPI_DC, HIGH);
    EPD_SPI_Transfer(data);
}

// Wait until idle (BUSY pin LOW = idle)
void EPD_WaitUntilIdle() {
    // 0: busy, 1: idle
    while (digitalRead(PIN_SPI_BUSY) == 0) {
        delay(100);
    }
}

// Wait until idle for V2 displays (BUSY pin HIGH = busy, LOW = idle)
void EPD_WaitUntilIdle_high() {
    // 1: busy, 0: idle
    while (digitalRead(PIN_SPI_BUSY) == 1) {
        delay(100);
    }
}

void EPD_Reset() {
    digitalWrite(PIN_SPI_RST, HIGH);
    delay(200);
    digitalWrite(PIN_SPI_RST, LOW);
    delay(2);
    digitalWrite(PIN_SPI_RST, HIGH);
    delay(200);
}

// Helper functions matching original
void EPD_Send_1(uint8_t c, uint8_t v1) {
    EPD_SendCommand(c);
    EPD_SendData(v1);
}

void EPD_Send_2(uint8_t c, uint8_t v1, uint8_t v2) {
    EPD_SendCommand(c);
    EPD_SendData(v1);
    EPD_SendData(v2);
}

void EPD_Send_4(uint8_t c, uint8_t v1, uint8_t v2, uint8_t v3, uint8_t v4) {
    EPD_SendCommand(c);
    EPD_SendData(v1);
    EPD_SendData(v2);
    EPD_SendData(v3);
    EPD_SendData(v4);
}

// ===========================================
// 4.2" V2 Display Functions (matching original exactly)
// ===========================================

void EPD_4in2_V2_Init() {
    Serial.println("Initializing 4.2\" V2 E-Paper...");

    EPD_Reset();
    EPD_WaitUntilIdle_high();

    EPD_SendCommand(0x12);  // SW Reset
    EPD_WaitUntilIdle_high();

    EPD_Send_2(0x21, 0x40, 0x00);  // Display Update Control
    EPD_Send_1(0x3C, 0x05);        // Border Waveform
    EPD_Send_1(0x11, 0x03);        // Data Entry Mode

    EPD_Send_2(0x44, 0x00, 0x31);              // RAM X address range
    EPD_Send_4(0x45, 0x00, 0x00, 0x2B, 0x01);  // RAM Y address range

    EPD_Send_1(0x4E, 0x00);        // RAM X counter
    EPD_Send_2(0x4F, 0x00, 0x00);  // RAM Y counter

    // Clear display with white
    EPD_SendCommand(0x24);  // Write RAM
    for (int i = 0; i < 15000; i++) {
        EPD_SendData(0xFF);
    }

    // Trigger refresh to clear
    EPD_SendCommand(0x22);
    EPD_SendData(0xF7);
    EPD_SendCommand(0x20);
    EPD_WaitUntilIdle_high();

    // Ready to receive new image data
    EPD_SendCommand(0x24);

    Serial.println("4.2\" V2 E-Paper initialized");
}

void EPD_4in2_V2_Show() {
    EPD_SendCommand(0x22);
    EPD_SendData(0xF7);
    EPD_SendCommand(0x20);
    EPD_WaitUntilIdle_high();

    // Enter deep sleep
    EPD_SendCommand(0x10);
    EPD_SendData(0x01);
}

void EPD_4in2_V2_Clear() {
    Serial.println("Clearing display...");
    EPD_4in2_V2_Init();
    // Init already clears and shows, then prepares for new data
    Serial.println("Display cleared");
}

void EPD_4in2_V2_Display(const uint8_t* image) {
    Serial.println("Displaying image...");

    EPD_Reset();
    EPD_WaitUntilIdle_high();

    EPD_SendCommand(0x12);  // SW Reset
    EPD_WaitUntilIdle_high();

    EPD_Send_2(0x21, 0x40, 0x00);
    EPD_Send_1(0x3C, 0x05);
    EPD_Send_1(0x11, 0x03);

    EPD_Send_2(0x44, 0x00, 0x31);
    EPD_Send_4(0x45, 0x00, 0x00, 0x2B, 0x01);

    EPD_Send_1(0x4E, 0x00);
    EPD_Send_2(0x4F, 0x00, 0x00);

    // Write image data
    EPD_SendCommand(0x24);
    for (int i = 0; i < IMAGE_BUFFER_SIZE; i++) {
        EPD_SendData(image[i]);
    }

    // Trigger display refresh
    EPD_4in2_V2_Show();

    Serial.println("Display update complete");
}

void EPD_4in2_V2_Sleep() {
    Serial.println("Entering deep sleep...");
    EPD_SendCommand(0x10);
    EPD_SendData(0x01);
    delay(100);
    Serial.println("Display in deep sleep");
}

#endif // EPD_DRIVER_H
