"""
Echo — Assistive Smart-Glove System
Terminal-Based Bluetooth Data Collector

Receives averaged flex sensor readings streamed from ESP32 ('SignSpeak-Glove')
over Bluetooth Serial (RFCOMM) and logs labelled repetitions for SLSL gesture dataset.

Features:
- Continuous background serial consumption (prevents OS buffer backlog during user input)
- Interactive recording controls (Participant ID, Session ID, Sign Label, Repetition)
- Flushing old buffered readings on recording start
- CSV appending to data/raw/training_data.csv without overwriting
- Graceful error handling for missing hardware, malformed packets, and keyboard interruption
- Modular parsing and storage supporting 1 sensor now and 5 sensors in the future
"""

import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, List, Optional, Tuple

try:
    import serial  # pip install pyserial
except ImportError:
    serial = None

# Default connection settings
PORT = "COM12"  # replace with the Outgoing COM port Windows assigns to SignSpeak-Glove
BAUDRATE = 115200  # Baud rate is ignored by Bluetooth serial, but pyserial requires a value
TIMEOUT = 1.0

# Path configuration
# Resolves repository root (../../ from code/BT_conn)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "raw" / "training_data.csv"

# CSV column headers
CSV_HEADER_1_SENSOR = [
    "timestamp",
    "user_id",
    "session_id",
    "sign_label",
    "repetition",
    "raw_value",
]

# Modular future 5-sensor header for reference
CSV_HEADER_5_SENSORS = [
    "timestamp",
    "user_id",
    "session_id",
    "sign_label",
    "repetition",
    "thumb",
    "index",
    "middle",
    "ring",
    "pinky",
]

# Baseline gesture labels from classifier specifications
DEFAULT_GESTURE_LABELS = ["Hello", "Yes", "Me", "Water", "Help"]


def parse_sensor_line(line: str) -> Optional[List[int]]:
    """
    Parses a raw line received from ESP32 into a list of integer sensor readings.

    Supports:
      - Single-sensor packet: "1480" -> [1480]
      - Multi-sensor packet:  "1480,1320,1500,1210,1400" -> [1480, 1320, 1500, 1210, 1400]

    Returns None for empty lines, partial tokens, or malformed values.
    """
    if not line:
        return None
    cleaned = line.strip()
    if not cleaned:
        return None
    tokens = [t.strip() for t in cleaned.split(",") if t.strip()]
    if not tokens:
        return None
    try:
        return [int(t) for t in tokens]
    except ValueError:
        return None


def format_csv_record(
    timestamp: str,
    user_id: str,
    session_id: str,
    sign_label: str,
    repetition: int,
    values: List[int],
) -> List[str]:
    """
    Formats metadata and sensor readings into CSV column values.
    Extracts raw_value for 1-sensor setup while modularly accommodating 5 sensors.
    """
    base = [timestamp, user_id, session_id, sign_label, str(repetition)]
    if len(values) == 1:
        return base + [str(values[0])]
    else:
        return base + [str(v) for v in values]


def ensure_csv_file(csv_path: Path, header: Optional[List[str]] = None) -> None:
    """
    Ensures parent directories exist and writes CSV header if file is new or empty.
    Preserves all existing records without overwriting.
    """
    if header is None:
        header = CSV_HEADER_1_SENSOR
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if needs_header:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)


class BluetoothDataCollector:
    """
    Manages continuous background serial reception from the ESP32 glove
    and thread-safe recording to CSV.
    """

    def __init__(
        self,
        port: str = PORT,
        baudrate: int = BAUDRATE,
        timeout: float = TIMEOUT,
        csv_path: Path = DEFAULT_CSV_PATH,
        serial_instance: Optional[Any] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.csv_path = Path(csv_path)

        self.serial_conn: Optional[Any] = serial_instance
        self._owns_serial = serial_instance is None

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None

        # State tracking
        self.latest_reading: Optional[List[int]] = None
        self.latest_timestamp: Optional[float] = None
        self.total_samples_received: int = 0
        self.last_error: Optional[str] = None

        # Recording state
        self.is_recording: bool = False
        self._user_id: str = ""
        self._session_id: str = ""
        self._sign_label: str = ""
        self._repetition: int = 1
        self._current_rep_samples: int = 0

        # File handle
        self._csv_file = None
        self._csv_writer = None

    def connect(self) -> None:
        """
        Opens serial connection to ESP32 Bluetooth port if not already provided.
        """
        if self.serial_conn is not None:
            return

        if serial is None:
            raise ImportError(
                "pyserial is not installed. Please install it using: pip install pyserial"
            )

        try:
            self.serial_conn = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
        except Exception as e:
            raise ConnectionError(
                f"Could not connect to {self.port} at {self.baudrate} baud: {e}"
            )

    def start(self) -> None:
        """
        Initializes CSV file and starts the background reader thread.
        """
        ensure_csv_file(self.csv_path)
        self._csv_file = open(self.csv_path, mode="a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)

        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="BT-ReaderThread", daemon=True
        )
        self._reader_thread.start()

    def stop(self) -> None:
        """
        Stops background thread, flushes data, and closes connections safely.
        """
        self._stop_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        with self._lock:
            self.is_recording = False
            if self._csv_file and not self._csv_file.closed:
                try:
                    self._csv_file.flush()
                    self._csv_file.close()
                except Exception:
                    pass
                self._csv_file = None
                self._csv_writer = None

        if self._owns_serial and self.serial_conn is not None:
            try:
                self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None

    def start_recording(
        self, user_id: str, session_id: str, sign_label: str, repetition: int
    ) -> None:
        """
        Begins recording samples for the specified gesture repetition.

        Timing & Buffer Management:
        Flushes the serial input buffer (reset_input_buffer) to clear any pending
        in-transit bytes before enabling the recording flag. Only fresh packets received
        after this call are written to CSV.

        Driver Limitation Note:
        Windows RFCOMM virtual Bluetooth COM ports may hold ~1-2 packets in driver
        memory before reset_input_buffer() clears them. Continuous background reading
        keeps driver queue backlog near zero during idle user interactions.
        """
        with self._lock:
            if self.serial_conn and hasattr(self.serial_conn, "reset_input_buffer"):
                try:
                    self.serial_conn.reset_input_buffer()
                except Exception:
                    pass

            self._user_id = str(user_id)
            self._session_id = str(session_id)
            self._sign_label = str(sign_label)
            self._repetition = int(repetition)
            self._current_rep_samples = 0
            self.is_recording = True

    def stop_recording(self) -> int:
        """
        Stops active recording, flushes the CSV file, and returns the sample count.
        """
        with self._lock:
            self.is_recording = False
            count = self._current_rep_samples
            if self._csv_file and not self._csv_file.closed:
                try:
                    self._csv_file.flush()
                except Exception:
                    pass
            return count

    def get_status(self) -> dict:
        """
        Returns a thread-safe snapshot of connection and recording status.
        """
        with self._lock:
            return {
                "connected": self.serial_conn is not None,
                "recording": self.is_recording,
                "latest_reading": self.latest_reading,
                "latest_timestamp": self.latest_timestamp,
                "total_received": self.total_samples_received,
                "current_rep_samples": self._current_rep_samples,
                "last_error": self.last_error,
            }

    def _reader_loop(self) -> None:
        """
        Continuously reads Bluetooth lines in the background.
        Consumes data regardless of whether recording is active, preventing
        OS serial buffer accumulation while the user interacts with the terminal.
        """
        while not self._stop_event.is_set():
            if self.serial_conn is None:
                time.sleep(0.05)
                continue

            try:
                raw_bytes = self.serial_conn.readline()
                if not raw_bytes:
                    continue

                line_str = raw_bytes.decode(errors="ignore").strip()
                if not line_str:
                    continue

                values = parse_sensor_line(line_str)
                if values is None:
                    continue

                with self._lock:
                    self.latest_reading = values
                    self.latest_timestamp = time.time()
                    self.total_samples_received += 1

                    if self.is_recording and self._csv_writer is not None:
                        timestamp_str = datetime.now().isoformat()
                        record = format_csv_record(
                            timestamp=timestamp_str,
                            user_id=self._user_id,
                            session_id=self._session_id,
                            sign_label=self._sign_label,
                            repetition=self._repetition,
                            values=values,
                        )
                        self._csv_writer.writerow(record)
                        self._csv_file.flush()
                        self._current_rep_samples += 1

            except Exception as e:
                if not self._stop_event.is_set():
                    with self._lock:
                        self.last_error = str(e)
                time.sleep(0.02)


def run_interactive_collector(
    port: str = PORT,
    csv_path: Path = DEFAULT_CSV_PATH,
    mock_serial: Optional[Any] = None,
) -> None:
    """
    Runs the terminal-based interactive data collector loop.
    """
    print("=" * 64)
    print("      Echo — SLSL Data Collector (SignSpeak Glove)")
    print("=" * 64)
    print(f"Target Bluetooth Port : {port}")
    print(f"Target CSV Output     : {csv_path}")

    collector = BluetoothDataCollector(
        port=port, csv_path=csv_path, serial_instance=mock_serial
    )

    try:
        if mock_serial is None:
            print(f"\nConnecting to Bluetooth device on {port}...")
            collector.connect()
            print("Connected successfully!")
        else:
            print("\nUsing simulated serial connection (mock mode).")

        collector.start()
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print("1. Ensure ESP32 is powered on and running BT_conn/esp32_bt_stream.ino.")
        print(
            "2. In Windows 'Bluetooth & devices', confirm 'SignSpeak-Glove' is paired."
        )
        print(
            "3. In Device Manager > Ports (COM & LPT), verify the Outgoing COM port."
        )
        print("4. Specify port override with: python read_bt.py --port COMxx")
        return

    try:
        # Prompt Participant and Session IDs
        print("\n--- Session Setup ---")
        user_id = input("Enter Participant ID [default: P01]: ").strip() or "P01"
        session_id = input("Enter Session ID     [default: S01]: ").strip() or "S01"

        # Default sign selection
        sign_label = DEFAULT_GESTURE_LABELS[0]
        repetition = 1

        while True:
            status = collector.get_status()
            reading_str = (
                str(status["latest_reading"][0])
                if status["latest_reading"]
                else "Waiting for data..."
            )

            print("\n" + "=" * 64)
            print(f" Participant: {user_id} | Session: {session_id}")
            print(
                f" Port: {port} | Latest ADC: {reading_str} | Total Packets: {status['total_received']}"
            )
            print(f" Current Sign: '{sign_label}' | Next Repetition: {repetition}")
            print("=" * 64)
            print("Commands:")
            print(f"  [Enter]  START recording repetition {repetition}")
            print("  [s]      Select/change sign label")
            print("  [r]      Change repetition number")
            print("  [p]      Change participant or session ID")
            print("  [m]      Monitor live stream (5 seconds)")
            print("  [q]      Quit collector")

            choice = input("\nAction > ").strip().lower()

            if choice == "q":
                print("\nExiting collector...")
                break

            elif choice == "s":
                print("\nSelect Sign Label:")
                for idx, lbl in enumerate(DEFAULT_GESTURE_LABELS, 1):
                    print(f"  {idx}. {lbl}")
                custom = input("Choose number or type custom sign label: ").strip()
                if custom.isdigit() and 1 <= int(custom) <= len(
                    DEFAULT_GESTURE_LABELS
                ):
                    sign_label = DEFAULT_GESTURE_LABELS[int(custom) - 1]
                elif custom:
                    sign_label = custom
                repetition = 1
                print(f"Selected sign: '{sign_label}' (Repetition reset to 1)")

            elif choice == "r":
                rep_input = input(
                    f"Enter new repetition number [current: {repetition}]: "
                ).strip()
                if rep_input.isdigit() and int(rep_input) > 0:
                    repetition = int(rep_input)
                    print(f"Repetition set to: {repetition}")

            elif choice == "p":
                user_id = (
                    input(f"Enter Participant ID [current: {user_id}]: ").strip()
                    or user_id
                )
                session_id = (
                    input(f"Enter Session ID     [current: {session_id}]: ").strip()
                    or session_id
                )
                print(f"Updated session: {user_id} / {session_id}")

            elif choice == "m":
                print("\nMonitoring live stream for 5 seconds (Press Ctrl+C to stop)...")
                t_end = time.time() + 5.0
                try:
                    while time.time() < t_end:
                        curr = collector.get_status()
                        val = (
                            curr["latest_reading"]
                            if curr["latest_reading"]
                            else "No data"
                        )
                        print(
                            f"  Live ADC: {val}  (Packets: {curr['total_received']})    ",
                            end="\r",
                            flush=True,
                        )
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    pass
                print("\nLive monitor ended.")

            elif choice == "":
                # Start recording repetition
                collector.start_recording(
                    user_id=user_id,
                    session_id=session_id,
                    sign_label=sign_label,
                    repetition=repetition,
                )

                print("\n" + "*" * 60)
                print(f"  >>> RECORDING ACTIVE: '{sign_label}' (Repetition {repetition})")
                print("  >>> Receiving packets at ~10 Hz...")
                print("  >>> Press [ENTER] when gesture is complete to STOP recording.")
                print("*" * 60)

                input()  # Wait for Enter to stop

                samples_saved = collector.stop_recording()

                print("-" * 60)
                print("  >>> RECORDING STOPPED")
                print(
                    f"  >>> Successfully saved {samples_saved} samples for '{sign_label}' (Rep {repetition})"
                )
                print(f"  >>> Output: {csv_path}")
                print("-" * 60)

                repetition += 1

            else:
                print(f"Unknown command: '{choice}'")

    except KeyboardInterrupt:
        print("\n\nSession interrupted by user.")
    finally:
        collector.stop()
        print("Collector closed safely. Data saved.")


def run_simple_monitor(port: str = PORT) -> None:
    """
    Backwards-compatible live stream monitor (matches original read_bt.py behaviour).
    """
    if serial is None:
        print("pyserial is required. Install with: pip install pyserial")
        sys.exit(1)

    print(f"Connecting to {port} at {BAUDRATE} baud...")
    ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT)
    print("Streaming incoming sensor packets (Press Ctrl+C to exit):")
    try:
        while True:
            line = ser.readline().decode(errors="ignore").strip()
            if not line:
                continue
            values = parse_sensor_line(line)
            if values is None:
                continue
            print(values)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        ser.close()


def main():
    parser = argparse.ArgumentParser(
        description="Echo Bluetooth Data Collector for ESP32 Flex Glove"
    )
    parser.add_argument(
        "--port",
        default=PORT,
        help=f"Bluetooth serial port (default: {PORT})",
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV_PATH),
        help=f"Target CSV file path (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run simple stream monitor mode without data recording",
    )
    args = parser.parse_args()

    if args.monitor:
        run_simple_monitor(port=args.port)
    else:
        run_interactive_collector(port=args.port, csv_path=Path(args.csv))


if __name__ == "__main__":
    main()
