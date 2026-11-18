"""Subscribing, recording, refreshing and stopping the stream."""

import os
import signal

import pytest
from fakes import FakeClient, message
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode
from rich.console import Console

from swim_project import stream as stream_module
from swim_project.config import MqttSettings
from swim_project.db import DatabaseError
from swim_project.stream import Recorder, StreamFailed, _watch, stream

SETTINGS = MqttSettings("broker.example.org", 8883, "recorder", "secret", tls=True)
TOPICS = ("site-a/building-1/room/101/+/S/+/+",)


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    monkeypatch.setattr(stream_module.mqtt, "Client", FakeClient)
    FakeClient.messages = [message()]
    FakeClient.reason = ReasonCode(PacketTypes.CONNACK, "Success")
    FakeClient.unreachable = False


def run(sink=lambda _: None, limit=1, settings=SETTINGS, refresh=10):
    recorder = Recorder(TOPICS, sink, limit)
    return stream(settings, recorder, refresh=refresh, console=Console(width=120))


def test_records_until_the_limit_and_cleans_up():
    stored = []
    FakeClient.messages = [message(), message(topic="bad/topic"), message(), message()]
    readings = run(stored.append, limit=2)
    assert (readings.received, len(stored)) == (2, 2)
    assert readings.skipped == {"topic has fewer than 4 segments or an empty one": 1}
    client = FakeClient.last
    assert client.subscribed == [(TOPICS[0], 1)]
    assert client.calls[:3] == [
        "tls",
        ("login", "recorder"),
        ("connect", "broker.example.org", 8883, 60),
    ]
    assert client.calls[-2:] == ["disconnect", "loop_stop"]


def test_without_display_records_silently(capsys):
    FakeClient.messages = [message(), message()]
    assert run(limit=2, refresh=None).received == 2
    assert capsys.readouterr().out == ""


def test_plain_anonymous_connection():
    run(settings=MqttSettings("localhost", 1883, None, None, tls=False))
    assert FakeClient.last.calls[0] == ("connect", "localhost", 1883, 60)


def test_unreachable_broker():
    FakeClient.unreachable = True
    with pytest.raises(StreamFailed, match="cannot reach the broker at broker.example.org:8883"):
        run()


def test_refused_connection():
    FakeClient.reason = ReasonCode(PacketTypes.CONNACK, "Not authorized")
    with pytest.raises(StreamFailed, match="refused the connection: Not authorized"):
        run()


def test_sink_failure_stops_the_stream():
    def fail(_reading):
        raise DatabaseError("cannot store a reading")

    FakeClient.messages = [message(), message()]
    with pytest.raises(StreamFailed, match="cannot store a reading"):
        run(fail, limit=None)


class Stop:
    """A stop event whose wait() returns the queued results, then raises one interruption."""

    def __init__(self, *results):
        self.results = list(results)

    def wait(self, _timeout=None):
        if not self.results:
            raise KeyboardInterrupt
        return self.results.pop(0)


class FakeLive:
    def __init__(self):
        self.updates = 0

    def update(self, _table, refresh):
        assert refresh
        self.updates += 1


def test_watch_redraws_until_stopped():
    recorder = Recorder(TOPICS, lambda _: None, None)
    recorder.stop = Stop(False, False, True)
    live = FakeLive()
    _watch(recorder, live, 10)
    assert live.updates == 3


def test_watch_stops_on_ctrl_c():
    recorder = Recorder(TOPICS, lambda _: None, None)
    recorder.stop = Stop(False)
    live = FakeLive()
    _watch(recorder, live, 10)
    assert live.updates == 2


class Terminate:
    """A stop event whose wait() receives SIGTERM, as from `systemctl stop` or `kill`."""

    def wait(self, _timeout=None):
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM did not interrupt the wait")


def test_sigterm_stops_like_ctrl_c():
    before = signal.getsignal(signal.SIGTERM)
    FakeClient.messages = []
    recorder = Recorder(TOPICS, lambda _: None, None)
    recorder.stop = Terminate()
    readings = stream(SETTINGS, recorder, refresh=None, console=Console())
    assert readings.received == 0
    assert FakeClient.last.calls[-2:] == ["disconnect", "loop_stop"]
    assert signal.getsignal(signal.SIGTERM) is before
