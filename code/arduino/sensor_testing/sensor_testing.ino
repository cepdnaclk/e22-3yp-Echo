// ESP32 flex sensor reader (voltage divider on GPIO34)
// Wiring: 3V3 -> flex sensor -> GPIO34 -> 10k resistor -> GND

const int FLEX_PIN = 34;      // ADC1 pin (safe to use with WiFi)
const int SAMPLES  = 16;      // averaging to reduce ADC noise

// Calibrate these: open the Serial Monitor, hold the sensor flat,
// then fully bent, and copy the "raw" values here.
int FLAT_RAW = 1550;
int BENT_RAW = 1050;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);                    // 0..4095
  analogSetPinAttenuation(FLEX_PIN, ADC_11db); // full 0..3.3V range
}

int readFlex() {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    sum += analogRead(FLEX_PIN);
    delay(2);
  }
  return sum / SAMPLES;
}

void loop() {
  int raw = readFlex();
  float volts = raw * 3.3 / 4095.0;

  // Map to 0-90 degrees (bending raises resistance, so voltage drops)
  int angle = map(raw, FLAT_RAW, BENT_RAW, 0, 90);
  angle = constrain(angle, 0, 90);

  Serial.printf("raw: %d  volts: %.2f  angle: %d\n", raw, volts, angle);
  delay(100);
}