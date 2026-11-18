"""A topic split into its segments, and an MQTT message parsed into a reading.

Topics end in three fixed segments after a location of one or more:
<location...>/<S|A>/<device_id>/<parameter>, for example
site-a/building-1/room/101/desk-1/S/TRH-0001/temperature.
Payloads are JSON objects: {"value": 24.11, "ts": "2026-11-18T16:31:20+08:00", "unit": "Cel"}.
See docs/data-format.md.
"""

import json
from dataclasses import dataclass
from datetime import datetime

KINDS = ("S", "A")  # sensor, actuator
FIXED_SEGMENTS = 3  # kind, device_id, parameter


class InvalidMessage(ValueError):
    """A message the recorder skips: its topic or its payload has the wrong shape."""


@dataclass(frozen=True)
class Topic:
    location: tuple[str, ...]
    kind: str
    device_id: str
    parameter: str


@dataclass(frozen=True)
class Reading:
    topic: Topic
    value: float
    unit_of_measure: str
    measured_at: datetime
    received_at: datetime


def parse_topic(topic: str) -> Topic:
    """Split a topic into its location segments, kind, device id and parameter."""
    parts = topic.split("/")
    if len(parts) <= FIXED_SEGMENTS or not all(parts):
        raise InvalidMessage("topic has fewer than 4 segments or an empty one")
    *location, kind, device_id, parameter = parts
    if kind not in KINDS:
        raise InvalidMessage("topic's sensor-or-actuator segment is neither S nor A")
    return Topic(tuple(location), kind, device_id, parameter)


def _json_object(raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidMessage("payload is not UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise InvalidMessage("payload is not a JSON object")
    return payload


def _measured_at(payload: dict) -> datetime:
    try:
        measured_at = datetime.fromisoformat(payload["ts"])
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidMessage("payload has no ISO 8601 ts") from error
    if measured_at.tzinfo is None:
        raise InvalidMessage("payload ts has no UTC offset")
    return measured_at


def to_reading(topic: str, raw: bytes, received_at: datetime) -> Reading:
    """Parse one message; raise InvalidMessage when the recorder should skip it."""
    parsed = parse_topic(topic)
    payload = _json_object(raw)
    value = payload.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidMessage("payload value is not a number")
    unit = payload.get("unit")
    if not isinstance(unit, str):
        raise InvalidMessage("payload unit is not a string")
    return Reading(parsed, float(value), unit, _measured_at(payload), received_at)
