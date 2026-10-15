#include "BluetoothSerial.h"

BluetoothSerial SerialBT;

const int PINS[] = {34};            // add more ADC1 pins here later (32, 33, 35, 36)
const int N = sizeof(PINS) / sizeof(PINS[0]);
const int SAMPLES = 8;
const unsigned long PERIOD_MS = 20; // 50 readings per second

unsigned long lastSend = 0;

int readAvg(int pin) {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) sum += analogRead(pin);
  return sum / SAMPLES;
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  for (int i = 0; i < N; i++) analogSetPinAttenuation(PINS[i], ADC_11db);
  SerialBT.begin("SignSpeak-Glove");
}

void loop() {
  if (millis() - lastSend < PERIOD_MS) return;
  lastSend = millis();

  String line = "";
  for (int i = 0; i < N; i++) {
    line += readAvg(PINS[i]);
    if (i < N - 1) line += ',';
  }
  SerialBT.println(line);
  Serial.println(line);
}
