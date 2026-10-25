#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("Starting ADS1115 I2C test");

  bool started = Wire.begin(21, 22);

  if (!started) {
    Serial.println("I2C initialization failed");
    return;
  }

  Wire.setClock(100000);
  Serial.println("I2C initialized on SDA=21, SCL=22");

  int found = 0;

  for (byte address = 0x48; address <= 0x4B; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();

    Serial.print("Address 0x");
    Serial.print(address, HEX);
    Serial.print(": ");

    if (error == 0) {
      Serial.println("DEVICE FOUND");
      found++;
    } else {
      Serial.println("No response");
    }
  }

  if (found == 0) {
    Serial.println("No ADS1115 address responded.");
  }
}

void loop() {}