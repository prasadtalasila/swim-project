"""The latest-reading table and its counts."""

import time
from datetime import UTC, datetime

import pytest
from fakes import PAYLOAD, TOPIC
from rich.console import Console

from swim_project.live import LiveReadings
from swim_project.model import to_reading

NOW = datetime(2026, 11, 18, 8, 31, 25, tzinfo=UTC)
HUMIDITY = TOPIC.replace("temperature", "relative_humidity")


@pytest.fixture(autouse=True)
def _singapore_time(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Singapore")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def render(table):
    console = Console(width=140, record=True)
    console.print(table)
    return console.export_text()


def test_keeps_latest_reading_per_device_parameter():
    readings = LiveReadings()
    newer = PAYLOAD.replace(b"23.98", b"24.5").replace(b"23+08", b"26+08")
    for topic, payload in ((TOPIC, PAYLOAD), (TOPIC, newer), (HUMIDITY, PAYLOAD)):
        readings.record(to_reading(topic, payload, NOW))
    readings.skip("payload is not a JSON object")
    latest = readings.latest()
    assert [item.reading.topic.parameter for item in latest] == ["relative_humidity", "temperature"]
    assert (latest[1].reading.value, latest[1].count) == (24.5, 2)
    assert (readings.received, readings.devices) == (3, 1)

    text = render(readings.table(NOW))
    assert "Live readings at 2026-11-18 08:31:25" in text
    assert "24.50 Cel" in text and "16:31:26" in text
    assert "3 readings, 1 skipped" in text


def test_empty_table():
    text = render(LiveReadings().table(NOW))
    assert "0 readings, 0 skipped" in text
