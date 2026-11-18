"""Exporting every table to CSV and JSON Lines files."""

import pytest
from fakes import FakeConnection

from swim_project import db, export
from swim_project.db import DatabaseError

ROWS = {
    "device": ["TRH-0001,S"],
    "reading": ['{"device_id":"TRH-0001","value":23.98}', '{"device_id":"TRH-0001","value":24.0}'],
}


def statements(conn):
    return [sql for sql, _ in conn.executed]


def test_writes_one_file_per_table_and_format(tmp_path):
    conn = FakeConnection(rows=ROWS)
    written = export.export_tables(conn, tmp_path, ("csv", "jsonl"))
    assert [(path.name, rows) for path, rows in written] == [
        ("device.csv", 1),
        ("device.jsonl", 1),
        ("reading.csv", 2),
        ("reading.jsonl", 2),
    ]
    assert (tmp_path / "device.csv").read_text() == "header\nTRH-0001,S\n"
    assert (tmp_path / "reading.jsonl").read_text().splitlines() == ROWS["reading"]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        path.name for path, _ in written
    )


def test_reads_one_utc_snapshot_in_key_order(tmp_path):
    conn = FakeConnection(rows=ROWS)
    export.export_tables(conn, tmp_path, ("csv", "jsonl"))
    missing, snapshot, utc, device_csv, device_jsonl, reading_csv, reading_jsonl = statements(conn)
    assert missing == db.MISSING_TABLES
    assert (snapshot, utc) == (export.SNAPSHOT, export.UTC)
    assert "COPY (SELECT * FROM device ORDER BY device_id) TO STDOUT" in device_csv
    assert device_jsonl.endswith("FROM device AS t ORDER BY t.device_id")
    assert "ORDER BY device_id, parameter, measured_at) TO STDOUT" in reading_csv
    assert reading_jsonl.endswith(
        "FROM reading AS t ORDER BY t.device_id, t.parameter, t.measured_at"
    )


def test_missing_tables_are_refused(tmp_path):
    conn = FakeConnection(missing=["reading"])
    with pytest.raises(DatabaseError, match="no reading table; nothing to export"):
        export.export_tables(conn, tmp_path, ("csv",))


def test_database_failure_leaves_no_partial_file(tmp_path):
    conn = FakeConnection(rows=ROWS, fail_on="FROM reading")
    with pytest.raises(DatabaseError, match="cannot export the tables"):
        export.export_tables(conn, tmp_path, ("csv",))
    assert [path.name for path in tmp_path.iterdir()] == ["device.csv"]


def test_unwritable_directory(tmp_path):
    with pytest.raises(export.ExportError, match="cannot write .*device.csv"):
        export.export_tables(FakeConnection(rows=ROWS), tmp_path / "absent", ("csv",))
