"""`swim-project export`: every table into its own file, as CSV or JSON Lines.

Both tables are read in one repeatable-read transaction, so the files
form one consistent snapshot even while a recorder is writing, and every
timestamp is written in UTC. With `entries`, each table is cut to its
most recent rows, still written in key order. `SELECT *` keeps a database that still
awaits `init-db --force` exportable, as a backup before migrating.
"""

from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import psycopg

from swim_project.db import DatabaseError, missing_tables

# Each table in primary-key order.
ORDER_BY = {
    "device": "device_id",
    "reading": "device_id, parameter, measured_at",
}

# Each table newest first, for `entries`; ties broken by the key.
NEWEST = {
    "device": "first_seen DESC, device_id",
    "reading": "measured_at DESC, device_id, parameter",
}

SNAPSHOT = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
UTC = "SET LOCAL TimeZone = 'UTC'"


class ExportError(Exception):
    """An export file cannot be written."""


def _rows(table: str, entries: int | None) -> str:
    """The FROM clause, as `t`: the whole table, or its `entries` newest rows."""
    if entries is None:
        return f"{table} AS t"
    return f"(SELECT * FROM {table} ORDER BY {NEWEST[table]} LIMIT {int(entries)}) AS t"


def _order(table: str) -> str:
    return ", ".join(f"t.{column}" for column in ORDER_BY[table].split(", "))


def _csv(conn: psycopg.Connection, table: str, rows: str, out: BinaryIO) -> int:
    query = f"SELECT * FROM {rows} ORDER BY {_order(table)}"
    with conn.cursor() as cursor:
        with cursor.copy(f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER)") as copy:
            for chunk in copy:
                out.write(chunk)
        return cursor.rowcount


def _jsonl(conn: psycopg.Connection, table: str, rows: str, out: BinaryIO) -> int:
    count = 0
    # A server-side cursor streams the rows instead of loading the table.
    with conn.cursor(name=f"export_{table}") as cursor:
        cursor.execute(f"SELECT row_to_json(t)::text FROM {rows} ORDER BY {_order(table)}")
        for (line,) in cursor:
            out.write(line.encode() + b"\n")
            count += 1
    return count


WRITERS: dict[str, Callable[[psycopg.Connection, str, str, BinaryIO], int]] = {
    "csv": _csv,
    "jsonl": _jsonl,
}


def _export_table(
    conn: psycopg.Connection, table: str, fmt: str, directory: Path, entries: int | None
) -> int:
    """Write `<table>.<fmt>` through a `.part` file, so a failure leaves no partial export."""
    path = directory / f"{table}.{fmt}"
    part = path.with_name(f"{path.name}.part")
    try:
        with part.open("wb") as out:
            rows = WRITERS[fmt](conn, table, _rows(table, entries), out)
        part.replace(path)
    except OSError as error:
        raise ExportError(f"cannot write {path}\n{error}") from error
    finally:
        part.unlink(missing_ok=True)
    return rows


def export_tables(
    conn: psycopg.Connection,
    directory: Path,
    formats: tuple[str, ...],
    entries: int | None = None,
) -> list[tuple[Path, int]]:
    """Write every table in every format into `directory`; return each file and its rows.

    `entries` keeps at most that many of each table's most recent rows.
    """
    missing = missing_tables(conn)
    if missing:
        raise DatabaseError(f"the database has no {', '.join(missing)} table; nothing to export")
    written = []
    try:
        with conn.transaction():
            conn.execute(SNAPSHOT)
            conn.execute(UTC)
            for table in ORDER_BY:
                for fmt in formats:
                    rows = _export_table(conn, table, fmt, directory, entries)
                    written.append((directory / f"{table}.{fmt}", rows))
    except psycopg.Error as error:
        raise DatabaseError(f"cannot export the tables\n{error}") from error
    return written
