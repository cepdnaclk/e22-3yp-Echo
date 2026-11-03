
#include <Wire.h>

#define SDA_PIN 21
#define SCL_PIN 22

void setup() {
  Serial.begin(115200);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  delay(500);

  Serial.println("\n--- ADS1115 Diagnostic ---");

  Serial.print("SDA state: ");
  Serial.println(digitalRead(SDA_PIN));

  Serial.print("SCL state: ");
  Serial.println(digitalRead(SCL_PIN));

  Serial.println("\nScanning address 0x48...");

  Wire.beginTransmission(0x48);
  byte error = Wire.endTransmission();

  Serial.print("I2C result: ");
  Serial.println(error);

  if (error == 0) {
    Serial.println("SUCCESS: Device detected at 0x48!");
  } else if (error == 2) {
    Serial.println("ERROR: Address not acknowledged.");
  } else {
    Serial.println("Other I2C error.");
  }
}

void loop() {
}
