"""Stand-ins for paho's client and psycopg's connection, and a sample message."""

from contextlib import nullcontext
from types import SimpleNamespace

import psycopg
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from swim_project import db

TOPIC = "site-a/building-1/room/101/desk-1/S/TRH-0001/temperature"
PAYLOAD = b'{"value":23.98,"ts":"2026-11-18T16:31:23+08:00","unit":"Cel"}'
CONFIG = """[database]
hostname=db.example.org
port=5432
db_name=sensors
username=recorder
password=p%ss

[mqtt]
host=broker.example.org
port=8883
username=recorder
password=secret
topics=
    site-a/building-1/room/101/+/S/+/+
    # comment lines are dropped
    site-a/building-1/room/102/#
"""


def _unset(*_args):
    raise AssertionError("callback not set")


def message(topic=TOPIC, payload=PAYLOAD):
    return SimpleNamespace(topic=topic, payload=payload)


class FakeClient:
    """Delivers `messages` as soon as the network loop starts; records what was called."""

    messages: list = []
    reason = ReasonCode(PacketTypes.CONNACK, "Success")
    unreachable = False
    last = None

    def __init__(self, *_args, **_kwargs):
        self.calls = []
        self.subscribed = None
        self.on_connect = self.on_message = _unset
        FakeClient.last = self

    def tls_set(self, **_kwargs):
        self.calls.append("tls")

    def username_pw_set(self, username, _password):
        self.calls.append(("login", username))

    def connect(self, host, port, keepalive):
        if FakeClient.unreachable:
            raise ConnectionRefusedError("connection refused")
        self.calls.append(("connect", host, port, keepalive))

    def subscribe(self, topics):
        self.subscribed = topics

    def loop_start(self):
        self.on_connect(self, None, None, FakeClient.reason, None)
        for item in FakeClient.messages:
            self.on_message(self, None, item)

    def loop_stop(self):
        self.calls.append("loop_stop")

    def disconnect(self):
        self.calls.append("disconnect")


class FakeCursor:
    """A cursor that answers COPY ... TO STDOUT and iteration from `rows` by table."""

    def __init__(self, conn):
        self.conn = conn
        self.rowcount = -1
        self.lines = []

    def _select(self, sql):
        self.conn.execute(sql)
        self.lines = self.conn.rows["reading" if "FROM reading" in sql else "device"]
        self.rowcount = len(self.lines)

    def copy(self, sql):
        self._select(sql)
        return nullcontext([b"header\n", *(f"{line}\n".encode() for line in self.lines)])

    def execute(self, sql):
        self._select(sql)

    def __iter__(self):
        return iter((line,) for line in self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass


class FakeConnection:
    """Records executed SQL; reports `missing` and `stale` tables; `fail_on` SQL raises.

    `rows` are the lines a cursor returns for each table.
    """

    def __init__(self, missing=(), stale=(), fail_on=None, rows=None):
        self.names = {db.MISSING_TABLES: list(missing), db.STALE_TABLES: list(stale)}
        self.fail_on = fail_on
        self.rows = rows or {"device": [], "reading": []}
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        if self.fail_on and self.fail_on in sql:
            raise psycopg.errors.UniqueViolation("refused")
        self.executed.append((sql, params))
        names = self.names.get(sql, [])
        return SimpleNamespace(fetchall=lambda: [(name,) for name in names])

    def cursor(self, name=None):
        del name
        return FakeCursor(self)

    def transaction(self):
        return nullcontext()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True
