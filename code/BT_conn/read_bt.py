import serial  # pip install pyserial

PORT = "COM12"  # replace with the Outgoing COM port Windows assigns to SignSpeak-Glove

# Baud rate is ignored by Bluetooth serial, but pyserial requires a value
ser = serial.Serial(PORT, 115200, timeout=1)

while True:
    line = ser.readline().decode(errors="ignore").strip()
    if not line:
        continue
    try:
        values = [int(v) for v in line.split(",")]
    except ValueError:
        continue  # skip partial lines at connection start
    print(values)
