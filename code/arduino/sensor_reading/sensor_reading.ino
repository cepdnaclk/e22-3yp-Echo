#include <Wire.h>
#include <Adafruit_ADS1X15.h>

#define I2C_SDA_PIN 21
#define I2C_SCL_PIN 22
#define ADS1_I2C_ADDR 0x48  // ADDR -> GND
#define ADS2_I2C_ADDR 0x49  // ADDR -> 3V3

// 1 = thumb only, 4 = four fingers on ADS #1, 5 = all fingers (needs ADS #2)
#define ACTIVE_FINGERS 1

const int NUM_SAMPLES = 2;

Adafruit_ADS1115 ads1;
Adafruit_ADS1115 ads2;

int16_t readings[5];

void scanI2C() {
  Serial.print("I2C devices:");
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", addr);
    }
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n--- SignSpeak Echo Glove: flex sensor reader ---");

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000);
  scanI2C();

  // The library waits forever for a conversion if the chip is missing, so stop here instead
  if (!ads1.begin(ADS1_I2C_ADDR, &Wire)) {
    while (true) {
      Serial.println("ADS1115 #1 not found at 0x48 - check wiring and ADDR pin");
      delay(1000);
    }
  }
  ads1.setGain(GAIN_ONE);
  ads1.setDataRate(RATE_ADS1115_860SPS);

#if ACTIVE_FINGERS > 4
  if (!ads2.begin(ADS2_I2C_ADDR, &Wire)) {
    while (true) {
      Serial.println("ADS1115 #2 not found at 0x49 - check wiring and ADDR pin");
      delay(1000);
    }
  }
  ads2.setGain(GAIN_ONE);
  ads2.setDataRate(RATE_ADS1115_860SPS);
#endif
}

void readSensors() {
  long sum[5] = {0, 0, 0, 0, 0};
  for (int s = 0; s < NUM_SAMPLES; s++) {
    for (int f = 0; f < ACTIVE_FINGERS; f++) {
      sum[f] += (f < 4) ? ads1.readADC_SingleEnded(f) : ads2.readADC_SingleEnded(0);
    }
  }
  for (int f = 0; f < ACTIVE_FINGERS; f++) {
    readings[f] = sum[f] / NUM_SAMPLES;
  }
}

void loop() {
  readSensors();
  for (int f = 0; f < ACTIVE_FINGERS; f++) {
    Serial.print(readings[f]);
    Serial.print(f < ACTIVE_FINGERS - 1 ? ',' : '\n');
  }
  delay(20);
}
