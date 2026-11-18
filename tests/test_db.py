"""Connecting, creating the tables and storing readings."""

from datetime import UTC, datetime

import psycopg
import pytest
from fakes import PAYLOAD, TOPIC, FakeConnection

from swim_project import db
from swim_project.config import DbSettings
from swim_project.model import to_reading

SETTINGS = DbSettings("db.example.org", 5432, "sensors", "recorder", "secret")
READING = to_reading(TOPIC, PAYLOAD, datetime(2026, 11, 18, 8, 31, 25, tzinfo=UTC))


def test_connect_passes_settings(monkeypatch):
    seen = {}
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: seen.update(kwargs) or "conn")
    assert db.connect(SETTINGS) == "conn"
    assert seen["dbname"] == "sensors" and seen["autocommit"] is True


def test_connect_failure_names_the_database(monkeypatch):
    def refuse(**_kwargs):
        raise psycopg.OperationalError("timeout expired")

    monkeypatch.setattr(psycopg, "connect", refuse)
    with pytest.raises(db.DatabaseError, match="sensors at db.example.org:5432\ntimeout"):
        db.connect(SETTINGS)


def statements(conn):
    return [sql for sql, _ in conn.executed]


def test_create_schema_runs_the_ddl():
    conn = FakeConnection()
    assert not db.create_schema(conn)
    assert statements(conn) == [db.STALE_TABLES, db.SCHEMA]
    assert "PRIMARY KEY (device_id, parameter, measured_at)" in db.SCHEMA


def test_stale_query_lists_every_expected_column():
    conn = FakeConnection()
    db.stale_tables(conn)
    tables, columns = conn.executed[0][1]
    assert list(zip(tables, columns))[:4] == [
        ("device", "device_id"),
        ("device", "kind"),
        ("device", "location"),
        ("device", "first_seen"),
    ]
    assert len(tables) == len(columns) == 10


def test_outdated_table_is_refused_without_force():
    conn = FakeConnection(stale=["device"])
    with pytest.raises(db.DatabaseError, match="device table has an outdated schema; .*--force"):
        db.create_schema(conn)
    assert db.SCHEMA not in statements(conn)


def test_force_migrates_before_creating():
    conn = FakeConnection(stale=["device"])
    assert db.create_schema(conn, force=True) == ["device"]
    assert statements(conn) == [db.STALE_TABLES, db.MIGRATE_DEVICE_LOCATION, db.SCHEMA]


def test_force_refuses_a_table_without_a_migration():
    with pytest.raises(db.DatabaseError, match="no migration for the reading table; .*--clean"):
        db.create_schema(FakeConnection(stale=["reading"]), force=True)


def test_clean_drops_both_tables_first():
    conn = FakeConnection()
    db.create_schema(conn, force=True, clean=True)
    assert statements(conn)[0] == db.DROP_TABLES == "DROP TABLE IF EXISTS reading, device"
    assert statements(conn)[-1] == db.SCHEMA


def test_create_schema_failure():
    with pytest.raises(db.DatabaseError, match="cannot create the tables"):
        db.create_schema(FakeConnection(fail_on="CREATE TABLE"))


def test_sink_needs_the_tables():
    with pytest.raises(db.DatabaseError, match="no device, reading table; run `swim-project"):
        db.DatabaseSink(FakeConnection(missing=["device", "reading"]))


def test_sink_refuses_outdated_tables():
    with pytest.raises(
        db.DatabaseError, match="device table has an outdated schema; run .*--force"
    ):
        db.DatabaseSink(FakeConnection(stale=["device"]))


def test_sink_stores_device_then_reading():
    conn = FakeConnection()
    db.DatabaseSink(conn)(READING)
    assert statements(conn)[:2] == [db.MISSING_TABLES, db.STALE_TABLES]
    device_sql, device = conn.executed[2]
    reading_sql, row = conn.executed[3]
    assert device_sql == db.INSERT_DEVICE
    assert device == ("TRH-0001", "S", ["site-a", "building-1", "room", "101", "desk-1"])
    assert reading_sql == db.INSERT_READING
    assert row[:2] == ("TRH-0001", "temperature")
    assert row[3:5] == (23.98, "Cel")


def test_sink_failure_names_the_device():
    sink = db.DatabaseSink(FakeConnection(fail_on="INSERT INTO reading"))
    with pytest.raises(db.DatabaseError, match="from TRH-0001"):
        sink(READING)
