"""The PostgreSQL tables that mirror the topic hierarchy, and the sink that fills them.

`device` holds a device's kind and location (every topic segment before
the kind); `reading` holds one row per message, keyed by device,
parameter (the last segment) and the sensor's own timestamp. See
docs/database.md.

`init-db` creates missing tables; with --force it also migrates tables
whose columns are out of date, keeping their rows, and with --force
--clean it drops both tables first. No other table is ever touched.
"""

import psycopg

from swim_project.config import DbSettings
from swim_project.model import Reading

TABLES = ("device", "reading")

# The columns each table must have; a table lacking one is out of date.
COLUMNS = {
    "device": ("device_id", "kind", "location", "first_seen"),
    "reading": (
        "device_id",
        "parameter",
        "measured_at",
        "value",
        "unit_of_measure",
        "received_at",
    ),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS device (
    device_id   text PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('S', 'A')),
    location    text[] NOT NULL CHECK (cardinality(location) > 0),
    first_seen  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reading (
    device_id        text NOT NULL REFERENCES device (device_id),
    parameter        text NOT NULL,
    measured_at      timestamptz NOT NULL,
    value            double precision NOT NULL,
    unit_of_measure  text NOT NULL,
    received_at      timestamptz NOT NULL,
    PRIMARY KEY (device_id, parameter, measured_at)
);
CREATE INDEX IF NOT EXISTS reading_measured_at ON reading (measured_at);
"""

INSERT_DEVICE = """
INSERT INTO device (device_id, kind, location)
VALUES (%s, %s, %s)
ON CONFLICT (device_id) DO NOTHING
"""

INSERT_READING = """
INSERT INTO reading (device_id, parameter, measured_at, value, unit_of_measure, received_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (device_id, parameter, measured_at) DO NOTHING
"""

MISSING_TABLES = "SELECT name FROM unnest(%s::text[]) AS name WHERE to_regclass(name) IS NULL"

STALE_TABLES = """
SELECT DISTINCT expected.table_name
FROM unnest(%s::text[], %s::text[]) AS expected (table_name, column_name)
WHERE to_regclass(expected.table_name) IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns AS actual
      WHERE actual.table_schema = current_schema()
        AND actual.table_name = expected.table_name
        AND actual.column_name = expected.column_name)
ORDER BY 1
"""

# From the first layout: five named location columns become one array, in topic order.
MIGRATE_DEVICE_LOCATION = """
ALTER TABLE device ADD COLUMN location text[];
UPDATE device SET location = ARRAY[project, building, level, unit, area];
ALTER TABLE device
    ALTER COLUMN location SET NOT NULL,
    ADD CONSTRAINT device_location_check CHECK (cardinality(location) > 0),
    DROP COLUMN project,
    DROP COLUMN building,
    DROP COLUMN level,
    DROP COLUMN unit,
    DROP COLUMN area;
"""

MIGRATIONS = {"device": MIGRATE_DEVICE_LOCATION}

# No CASCADE: a view or table that depends on these makes the drop fail.
DROP_TABLES = "DROP TABLE IF EXISTS reading, device"


class DatabaseError(Exception):
    """The database cannot be reached, lacks the tables, or refused a write."""


def connect(settings: DbSettings) -> psycopg.Connection:
    """Open an autocommit connection; each reading gets its own transaction."""
    try:
        return psycopg.connect(
            host=settings.hostname,
            port=settings.port,
            dbname=settings.db_name,
            user=settings.username,
            password=settings.password,
            autocommit=True,
            connect_timeout=10,
        )
    except psycopg.Error as error:
        where = f"{settings.db_name} at {settings.hostname}:{settings.port}"
        raise DatabaseError(f"cannot connect to database {where}\n{error}") from error


def _names(conn: psycopg.Connection, sql: str, params: tuple) -> list[str]:
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def missing_tables(conn: psycopg.Connection) -> list[str]:
    return _names(conn, MISSING_TABLES, (list(TABLES),))


def stale_tables(conn: psycopg.Connection) -> list[str]:
    """The existing tables that lack a column the recorder writes."""
    pairs = [(table, column) for table, columns in COLUMNS.items() for column in columns]
    return _names(conn, STALE_TABLES, ([t for t, _ in pairs], [c for _, c in pairs]))


def _outdated(stale: list[str]) -> str:
    return f"the {', '.join(stale)} table has an outdated schema"


def _migrate(conn: psycopg.Connection, force: bool) -> list[str]:
    stale = stale_tables(conn)
    if stale and not force:
        raise DatabaseError(
            f"{_outdated(stale)}; `swim-project init-db --force` migrates it, keeping its rows"
        )
    for table in stale:
        if table not in MIGRATIONS:
            raise DatabaseError(
                f"no migration for the {table} table; "
                "`swim-project init-db --force --clean` recreates it empty"
            )
        conn.execute(MIGRATIONS[table])
    return stale


def create_schema(
    conn: psycopg.Connection, *, force: bool = False, clean: bool = False
) -> list[str]:
    """Bring the tables to the current schema in one transaction; return those migrated.

    Missing tables are created. Out-of-date ones are refused, or migrated
    with `force`. `clean` drops both tables first, losing every row.
    """
    try:
        with conn.transaction():
            if clean:
                conn.execute(DROP_TABLES)
            migrated = _migrate(conn, force)
            conn.execute(SCHEMA)
    except psycopg.Error as error:
        raise DatabaseError(f"cannot create the tables\n{error}") from error
    return migrated


class DatabaseSink:
    """Store each reading, adding its device the first time the device is seen."""

    def __init__(self, conn: psycopg.Connection) -> None:
        missing = missing_tables(conn)
        if missing:
            raise DatabaseError(
                f"the database has no {', '.join(missing)} table; run `swim-project init-db` first"
            )
        stale = stale_tables(conn)
        if stale:
            raise DatabaseError(f"{_outdated(stale)}; run `swim-project init-db --force` first")
        self._conn = conn

    def __call__(self, reading: Reading) -> None:
        topic = reading.topic
        row = (topic.device_id, topic.parameter, reading.measured_at, reading.value)
        try:
            with self._conn.transaction():
                # psycopg adapts a list, not a tuple, to a PostgreSQL array.
                self._conn.execute(
                    INSERT_DEVICE, (topic.device_id, topic.kind, list(topic.location))
                )
                self._conn.execute(
                    INSERT_READING, (*row, reading.unit_of_measure, reading.received_at)
                )
        except psycopg.Error as error:
            raise DatabaseError(
                f"cannot store a reading from {topic.device_id}\n{error}"
            ) from error
