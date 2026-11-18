"""Subscribe to the broker, hand each valid reading to a sink, and optionally show a live table.

paho's network thread runs the callbacks (parse, store, count); the main
thread waits, redrawing the table every `refresh` seconds when asked to,
until Ctrl+C, SIGTERM, the message limit, or a failure stops the stream.
"""

import signal
import ssl
import threading
from collections.abc import Callable
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from rich.console import Console
from rich.live import Live

from swim_project.config import MqttSettings
from swim_project.db import DatabaseError
from swim_project.live import LiveReadings
from swim_project.model import InvalidMessage, Reading, to_reading

Sink = Callable[[Reading], None]


class StreamFailed(Exception):
    """The broker could not be reached or refused us, or the sink failed."""


class Recorder:
    """The MQTT callbacks: parse each message, store it, count it, stop at the limit."""

    def __init__(self, topics: tuple[str, ...], sink: Sink, limit: int | None) -> None:
        self.topics = topics
        self.sink = sink
        self.limit = limit
        self.readings = LiveReadings()
        self.stop = threading.Event()
        self.failure: str | None = None

    def on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            self._fail(f"the broker refused the connection: {reason_code}")
            return
        # Subscribing here renews the subscriptions after paho reconnects.
        client.subscribe([(topic, 1) for topic in self.topics])

    def on_message(self, _client, _userdata, message) -> None:
        if self.stop.is_set():
            return
        try:
            reading = to_reading(message.topic, message.payload, datetime.now(UTC))
        except InvalidMessage as error:
            self.readings.skip(str(error))
            return
        try:
            self.sink(reading)
        except DatabaseError as error:
            self._fail(str(error))
            return
        self.readings.record(reading)
        if self.limit is not None and self.readings.received >= self.limit:
            self.stop.set()

    def _fail(self, message: str) -> None:
        self.failure = message
        self.stop.set()


def build_client(settings: MqttSettings, recorder: Recorder) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.tls:
        client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
    if settings.username:
        client.username_pw_set(settings.username, settings.password)
    client.on_connect = recorder.on_connect
    client.on_message = recorder.on_message
    return client


def _watch(recorder: Recorder, live: Live, refresh: float) -> None:
    """Redraw the table every `refresh` seconds until the stream stops or Ctrl+C."""
    try:
        while not recorder.stop.wait(refresh):
            live.update(recorder.readings.table(datetime.now().astimezone()), refresh=True)
    except KeyboardInterrupt:
        pass
    live.update(recorder.readings.table(datetime.now().astimezone()), refresh=True)


def _wait(recorder: Recorder) -> None:
    """Block until the stream stops or Ctrl+C."""
    try:
        recorder.stop.wait()
    except KeyboardInterrupt:
        pass


def _display(recorder: Recorder, console: Console, refresh: float) -> None:
    table = recorder.readings.table(datetime.now().astimezone())
    with Live(table, console=console, auto_refresh=False) as live:
        _watch(recorder, live, refresh)


def stream(
    settings: MqttSettings, recorder: Recorder, *, console: Console, refresh: float | None
) -> LiveReadings:
    """Record readings until Ctrl+C, SIGTERM or the recorder's limit.

    With `refresh` set, show the live table redrawn that often. Raise
    StreamFailed on a failure.
    """
    client = build_client(settings, recorder)
    try:
        client.connect(settings.host, settings.port, keepalive=60)
    except OSError as error:
        where = f"{settings.host}:{settings.port}"
        raise StreamFailed(f"cannot reach the broker at {where}\n{error}") from error
    # A service manager stops the recorder with SIGTERM; treat it as Ctrl+C.
    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
    client.loop_start()
    try:
        if refresh is None:
            _wait(recorder)
        else:
            _display(recorder, console, refresh)
    finally:
        client.disconnect()
        client.loop_stop()
        signal.signal(signal.SIGTERM, previous)
    if recorder.failure:
        raise StreamFailed(recorder.failure)
    return recorder.readings
