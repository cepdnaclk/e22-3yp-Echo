"""
Unit and integration tests for read_bt.py (Echo SLSL Bluetooth Data Collector)

Executes software-only validation for:
- Packet parsing (single-sensor and modular 5-sensor)
- Handling of malformed/empty lines
- CSV initialization, header safety, and appending
- Background serial thread consumption and buffering behavior
- Recording start/stop isolation (ensuring idle buffer packets are discarded)
"""

import csv
from pathlib import Path
import queue
import tempfile
import time
from typing import List, Optional
import pytest

from read_bt import (
    parse_sensor_line,
    format_csv_record,
    ensure_csv_file,
    BluetoothDataCollector,
    CSV_HEADER_1_SENSOR,
    CSV_HEADER_5_SENSORS,
)


class MockSerial:
    """
    Simulates a serial connection (pyserial interface) for software-only tests.
    """

    def __init__(self, incoming_lines: Optional[List[str]] = None):
        self.queue = queue.Queue()
        self.reset_buffer_called = False
        self.closed = False
        if incoming_lines:
            for line in incoming_lines:
                self.queue.put(line.encode("utf-8"))

    def put_line(self, line: str) -> None:
        self.queue.put((line + "\n").encode("utf-8"))

    def readline(self) -> bytes:
        try:
            return self.queue.get(timeout=0.1)
        except queue.Empty:
            return b""

    def reset_input_buffer(self) -> None:
        self.reset_buffer_called = True
        # Drain any unread bytes currently waiting in the simulated buffer
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def close(self) -> None:
        self.closed = True


# =====================================================================
# 1. Packet Parsing Tests
# =====================================================================

def test_parse_sensor_line_single_value():
    assert parse_sensor_line("1480") == [1480]
    assert parse_sensor_line("1480\r\n") == [1480]
    assert parse_sensor_line("  1480  \n") == [1480]
    assert parse_sensor_line("0") == [0]
    assert parse_sensor_line("4095") == [4095]


def test_parse_sensor_line_multi_sensor():
    line = "1480,1320,1500,1210,1400"
    expected = [1480, 1320, 1500, 1210, 1400]
    assert parse_sensor_line(line) == expected
    assert parse_sensor_line(" 1480, 1320, 1500, 1210, 1400 \r\n") == expected


def test_parse_sensor_line_malformed_and_empty():
    assert parse_sensor_line("") is None
    assert parse_sensor_line("   \r\n") is None
    assert parse_sensor_line("abc") is None
    assert parse_sensor_line("1480,corrupt") is None
    assert parse_sensor_line("14.85") is None
    assert parse_sensor_line(",,,") is None


# =====================================================================
# 2. Record Formatting Tests (Current 1-Sensor & Future 5-Sensor)
# =====================================================================

def test_format_csv_record_single_sensor():
    record = format_csv_record(
        timestamp="2026-10-17T12:00:00",
        user_id="P01",
        session_id="S01",
        sign_label="Hello",
        repetition=1,
        values=[1480],
    )
    assert record == ["2026-10-17T12:00:00", "P01", "S01", "Hello", "1", "1480"]
    assert len(record) == len(CSV_HEADER_1_SENSOR)


def test_format_csv_record_modular_five_sensors():
    values = [1480, 1320, 1500, 1210, 1400]
    record = format_csv_record(
        timestamp="2026-10-17T12:00:00",
        user_id="P01",
        session_id="S01",
        sign_label="Water",
        repetition=2,
        values=values,
    )
    assert record == [
        "2026-10-17T12:00:00",
        "P01",
        "S01",
        "Water",
        "2",
        "1480",
        "1320",
        "1500",
        "1210",
        "1400",
    ]
    assert len(record) == len(CSV_HEADER_5_SENSORS)


# =====================================================================
# 3. CSV File Management & Append Preservation Tests
# =====================================================================

def test_ensure_csv_file_creates_dir_and_header():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "data" / "raw" / "training_data.csv"
        assert not csv_path.exists()

        ensure_csv_file(csv_path)

        assert csv_path.exists()
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            assert len(reader) == 1
            assert reader[0] == CSV_HEADER_1_SENSOR


def test_ensure_csv_file_preserves_existing_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "training_data.csv"
        # Create initial CSV with 1 row of data
        ensure_csv_file(csv_path)
        with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["2026-10-17T12:00:00", "P01", "S01", "Hello", "1", "1450"])

        # Run ensure_csv_file again
        ensure_csv_file(csv_path)

        # Confirm header is not duplicated and data is preserved
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            assert len(reader) == 2
            assert reader[0] == CSV_HEADER_1_SENSOR
            assert reader[1][3] == "Hello"


# =====================================================================
# 4. Collector Streaming, Recording Control, and Buffer Isolation
# =====================================================================

def test_collector_buffering_and_recording_isolation():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "training_data.csv"
        mock_serial = MockSerial()

        collector = BluetoothDataCollector(
            port="MOCK_PORT", csv_path=csv_path, serial_instance=mock_serial
        )
        collector.start()

        # Step 1: Send samples while recording is IDLE (not active)
        for val in [1000, 1010, 1020]:
            mock_serial.put_line(str(val))

        time.sleep(0.3)
        status = collector.get_status()
        assert status["total_received"] == 3
        assert status["latest_reading"] == [1020]

        # Verify CSV has NO data rows yet (only header)
        with open(csv_path, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
            assert len(rows) == 1  # Only header

        # Step 2: Start recording repetition 1
        collector.start_recording(
            user_id="P01", session_id="S01", sign_label="Hello", repetition=1
        )
        assert mock_serial.reset_buffer_called is True

        # Send 4 samples during active recording
        for val in [1480, 1485, 1490, 1495]:
            mock_serial.put_line(str(val))

        time.sleep(0.3)
        saved_count = collector.stop_recording()
        assert saved_count == 4

        # Step 3: Send samples after recording stopped
        for val in [2000, 2010]:
            mock_serial.put_line(str(val))

        time.sleep(0.2)
        collector.stop()

        # Step 4: Verify CSV contents
        with open(csv_path, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
            assert len(rows) == 5  # 1 header + 4 recorded samples
            assert rows[0] == CSV_HEADER_1_SENSOR
            for i, r in enumerate(rows[1:]):
                assert r[1] == "P01"
                assert r[2] == "S01"
                assert r[3] == "Hello"
                assert r[4] == "1"
                assert r[5] in ["1480", "1485", "1490", "1495"]


def test_collector_ignores_malformed_lines_during_recording():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "training_data.csv"
        mock_serial = MockSerial()

        collector = BluetoothDataCollector(
            port="MOCK_PORT", csv_path=csv_path, serial_instance=mock_serial
        )
        collector.start()

        collector.start_recording(
            user_id="P02", session_id="S01", sign_label="Yes", repetition=1
        )

        mock_serial.put_line("1500")
        mock_serial.put_line("corrupt_line")
        mock_serial.put_line("")
        mock_serial.put_line("   ")
        mock_serial.put_line("1510")

        time.sleep(0.3)
        saved_count = collector.stop_recording()
        collector.stop()

        assert saved_count == 2
        with open(csv_path, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
            assert len(rows) == 3  # header + 2 valid rows
            assert rows[1][5] == "1500"
            assert rows[2][5] == "1510"


def test_collector_multiple_repetitions_append_correctly():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "training_data.csv"
        mock_serial = MockSerial()

        collector = BluetoothDataCollector(
            port="MOCK_PORT", csv_path=csv_path, serial_instance=mock_serial
        )
        collector.start()

        # Repetition 1
        collector.start_recording("P01", "S01", "Me", 1)
        mock_serial.put_line("1200")
        mock_serial.put_line("1205")
        time.sleep(0.2)
        assert collector.stop_recording() == 2

        # Repetition 2
        collector.start_recording("P01", "S01", "Me", 2)
        mock_serial.put_line("1210")
        mock_serial.put_line("1215")
        mock_serial.put_line("1220")
        time.sleep(0.2)
        assert collector.stop_recording() == 3

        collector.stop()

        with open(csv_path, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
            assert len(rows) == 6  # header + 2 + 3 rows
            reps = [r[4] for r in rows[1:]]
            assert reps == ["1", "1", "2", "2", "2"]
