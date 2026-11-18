"""`swim-project export`: every table into its own file, as CSV or JSON Lines.

Both tables are read in one repeatable-read transaction, so the files
form one consistent snapshot even while a recorder is writing, and every
timestamp is written in UTC. `SELECT *` keeps a database that still
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

SNAPSHOT = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
UTC = "SET LOCAL TimeZone = 'UTC'"


class ExportError(Exception):
    """An export file cannot be written."""


def _csv(conn: psycopg.Connection, table: str, out: BinaryIO) -> int:
    query = f"SELECT * FROM {table} ORDER BY {ORDER_BY[table]}"
    with conn.cursor() as cursor:
        with cursor.copy(f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER)") as copy:
            for chunk in copy:
                out.write(chunk)
        return cursor.rowcount


def _jsonl(conn: psycopg.Connection, table: str, out: BinaryIO) -> int:
    order = ", ".join(f"t.{column}" for column in ORDER_BY[table].split(", "))
    rows = 0
    # A server-side cursor streams the rows instead of loading the table.
    with conn.cursor(name=f"export_{table}") as cursor:
        cursor.execute(f"SELECT row_to_json(t)::text FROM {table} AS t ORDER BY {order}")
        for (line,) in cursor:
            out.write(line.encode() + b"\n")
            rows += 1
    return rows


WRITERS: dict[str, Callable[[psycopg.Connection, str, BinaryIO], int]] = {
    "csv": _csv,
    "jsonl": _jsonl,
}


def _export_table(conn: psycopg.Connection, table: str, fmt: str, directory: Path) -> int:
    """Write `<table>.<fmt>` through a `.part` file, so a failure leaves no partial export."""
    path = directory / f"{table}.{fmt}"
    part = path.with_name(f"{path.name}.part")
    try:
        with part.open("wb") as out:
            rows = WRITERS[fmt](conn, table, out)
        part.replace(path)
    except OSError as error:
        raise ExportError(f"cannot write {path}\n{error}") from error
    finally:
        part.unlink(missing_ok=True)
    return rows


def export_tables(
    conn: psycopg.Connection, directory: Path, formats: tuple[str, ...]
) -> list[tuple[Path, int]]:
    """Write every table in every format into `directory`; return each file and its rows."""
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
                    rows = _export_table(conn, table, fmt, directory)
                    written.append((directory / f"{table}.{fmt}", rows))
    except psycopg.Error as error:
        raise DatabaseError(f"cannot export the tables\n{error}") from error
    return written
