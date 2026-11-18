"""Splitting topics into segments and parsing payloads into readings."""

from datetime import UTC, datetime, timedelta

import pytest
from fakes import PAYLOAD, TOPIC

from swim_project.model import InvalidMessage, parse_topic, to_reading

NOW = datetime(2026, 11, 18, 8, 31, 25, tzinfo=UTC)


def test_topic_segments():
    topic = parse_topic(TOPIC)
    assert topic.location == ("site-a", "building-1", "room", "101", "desk-1")
    assert (topic.kind, topic.device_id, topic.parameter) == ("S", "TRH-0001", "temperature")


@pytest.mark.parametrize(
    ("topic", "location"),
    [
        ("lab/A/valve-7/position", ("lab",)),
        ("a/b/c/d/e/f/g/h/S/dev/temperature", tuple("abcdefgh")),
    ],
)
def test_location_has_any_depth(topic, location):
    assert parse_topic(topic).location == location


def test_reading_from_payload():
    reading = to_reading(TOPIC, PAYLOAD, NOW)
    assert (reading.value, reading.unit_of_measure, reading.received_at) == (23.98, "Cel", NOW)
    assert reading.measured_at.utcoffset() == timedelta(hours=8)
    assert reading.measured_at == datetime(2026, 11, 18, 8, 31, 23, tzinfo=UTC)


def test_integer_value_becomes_float():
    payload = b'{"value": 22, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}'
    assert to_reading(TOPIC, payload, NOW).value == 22.0


@pytest.mark.parametrize(
    ("topic", "message"),
    [
        ("S/dev/temperature", "fewer than 4 segments or an empty one"),
        ("site-a/building-1//S/dev/temperature", "fewer than 4 segments or an empty one"),
        ("site-a/building-1/S/dev/", "fewer than 4 segments or an empty one"),
        ("site-a/building-1/desk-1/X/dev/temperature", "neither S nor A"),
    ],
)
def test_topic_refusals(topic, message):
    with pytest.raises(InvalidMessage, match=message):
        parse_topic(topic)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"\xff", "not UTF-8 JSON"),
        (b"{", "not UTF-8 JSON"),
        (b"[1]", "not a JSON object"),
        (b'{"value": "hot", "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}', "not a number"),
        (b'{"value": true, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}', "not a number"),
        (b'{"value": 1, "ts": "2026-11-18T16:31:23+08:00"}', "unit is not a string"),
        (b'{"value": 1, "unit": "Cel"}', "no ISO 8601 ts"),
        (b'{"value": 1, "ts": "yesterday", "unit": "Cel"}', "no ISO 8601 ts"),
        (b'{"value": 1, "ts": "2026-11-18T16:31:23", "unit": "Cel"}', "no UTC offset"),
    ],
)
def test_payload_refusals(payload, message):
    with pytest.raises(InvalidMessage, match=message):
        to_reading(TOPIC, payload, NOW)
