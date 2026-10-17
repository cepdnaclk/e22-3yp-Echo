#include "BluetoothSerial.h"

BluetoothSerial SerialBT;

// --- Pin & Sensor Configuration ---
// Currently using 1 sensor on GPIO34 (ADC1).
// To expand to 5 sensors, add ADC1 pins: {34, 32, 33, 35, 36}
const int PINS[] = {34};
const int N = sizeof(PINS) / sizeof(PINS[0]);

// --- Sampling & Averaging Configuration ---
// Target sampling rate: 50 Hz (one sample taken approximately every 20 ms)
const unsigned long SAMPLE_INTERVAL_MS = 20;

// Accumulate 5 consecutive samples before computing arithmetic mean and transmitting
// 5 samples * 20 ms = ~100 ms per transmitted packet (target output rate: 10 Hz)
const int SAMPLES_PER_AVERAGE = 5;

// --- Timing & Accumulator State ---
unsigned long lastSampleTime = 0;
long pinAccumulators[N] = {0};
int sampleCount = 0;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  for (int i = 0; i < N; i++) {
    analogSetPinAttenuation(PINS[i], ADC_11db);
  }
  SerialBT.begin("SignSpeak-Glove");
  Serial.println("SignSpeak-Glove Bluetooth stream initialized.");
}

void loop() {
  unsigned long currentMillis = millis();

  // Non-blocking sampling interval check (~20 ms / 50 Hz)
  if (currentMillis - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }

  // Prevent drift while handling any large hiccups gracefully
  if (currentMillis - lastSampleTime >= 2 * SAMPLE_INTERVAL_MS) {
    lastSampleTime = currentMillis;
  } else {
    lastSampleTime += SAMPLE_INTERVAL_MS;
  }

  // 1. Read each configured sensor pin and accumulate
  for (int i = 0; i < N; i++) {
    pinAccumulators[i] += analogRead(PINS[i]);
  }
  sampleCount++;

  // 2. When 5 consecutive samples have been accumulated (~100 ms):
  if (sampleCount >= SAMPLES_PER_AVERAGE) {
    String line = "";
    for (int i = 0; i < N; i++) {
      int avgVal = pinAccumulators[i] / SAMPLES_PER_AVERAGE;
      line += avgVal;
      if (i < N - 1) {
        line += ',';
      }
      pinAccumulators[i] = 0; // Reset accumulator for next averaging window
    }
    sampleCount = 0; // Reset sample counter

    // 3. Send one averaged integer per Bluetooth line (or comma-separated if N > 1)
    SerialBT.println(line);

    // Keep USB Serial debugging output active and identical without blocking
    Serial.println(line);
  }
}
