# Database

The recorder writes to two PostgreSQL tables, `device` and `reading`.
`swim-project init-db` creates them; the DDL is `SCHEMA` in the
`swim_project.db` module. How a message becomes a row is in
[data-format.md](data-format.md).

```text
device 1 ──── * reading
  device_id ◄──── device_id
```

## device

One row per device, written the first time the device is seen.

| Column | Type | Null | From | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `device_id` | `text` | no | topic, third segment from the end | Primary key |
| `kind` | `text` | no | topic, fourth segment from the end | `S` sensor or `A` actuator (checked) |
| `location` | `text[]` | no | topic, every segment before `kind` | The location path, widest first; at least one element (checked) |
| `first_seen` | `timestamptz` | no | database clock | When the row was inserted |

A device keeps the kind and location it was first seen with
(`ON CONFLICT DO NOTHING`). A device that moves, or publishes under two
locations, keeps its first location until its row is updated by hand.

## reading

One row per stored message.

| Column | Type | Null | From | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `device_id` | `text` | no | topic | References `device` |
| `parameter` | `text` | no | topic, last segment | What was measured or set |
| `measured_at` | `timestamptz` | no | payload `ts` | The device's timestamp, converted to an instant (its UTC offset is not kept) |
| `value` | `double precision` | no | payload `value` | The reading |
| `unit_of_measure` | `text` | no | payload `unit` | As sent, unchecked |
| `received_at` | `timestamptz` | no | recorder clock (UTC) | When the recorder received the message |

Primary key: `(device_id, parameter, measured_at)`. A second message with
the same key is ignored (`ON CONFLICT DO NOTHING`), so redelivery never
stores a reading twice. Index: `reading_measured_at` on `measured_at`,
for time-range queries across devices.

Each reading is written in its own transaction together with its device
row, so a reading never exists without its device.

## Example rows

The message

```text
topic:   site-a/building-1/room/101/desk-1/S/TRH-0001/temperature
payload: {"value": 23.98, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}
```

received at 08:36:41.5 UTC, followed by its humidity twin, gives:

```text
device
 device_id | kind |               location                |          first_seen
-----------+------+---------------------------------------+-------------------------------
 TRH-0001  | S    | {site-a,building-1,room,101,desk-1}   | 2026-11-18 08:36:41.512+00

reading
 device_id |     parameter     |      measured_at       | value | unit_of_measure |        received_at
-----------+-------------------+------------------------+-------+-----------------+----------------------------
 TRH-0001  | temperature       | 2026-11-18 08:31:23+00 | 23.98 | Cel             | 2026-11-18 08:36:41.505+00
 TRH-0001  | relative_humidity | 2026-11-18 08:31:23+00 | 55.56 | %RH             | 2026-11-18 08:36:41.705+00
```

`measured_at` is shown in the session's time zone (UTC here); the
device's `+08:00` is not stored.

## Queries

### Latest value per device and parameter

```sql
SELECT DISTINCT ON (device_id, parameter)
       device_id, parameter, value, unit_of_measure, measured_at
FROM reading
ORDER BY device_id, parameter, measured_at DESC;
```

### Querying by location

PostgreSQL arrays are 1-based. With a five-level location
`site/building/space_type/space/zone`:

```sql
-- The zone (last level) of every device
SELECT device_id, location[cardinality(location)] AS zone FROM device;

-- Every device in room 101, whatever its zone (prefix match)
SELECT device_id FROM device
WHERE location[1:4] = ARRAY['site-a', 'building-1', 'room', '101'];

-- Any device with 'desk-1' at any level
SELECT device_id FROM device WHERE 'desk-1' = ANY (location);

-- The location as one string, as the live table shows it
SELECT device_id, array_to_string(location, '/') FROM device;
```

### Latest temperature per zone

```sql
SELECT DISTINCT ON (d.location)
       array_to_string(d.location, '/') AS location, r.value, r.unit_of_measure, r.measured_at
FROM reading r JOIN device d USING (device_id)
WHERE r.parameter = 'temperature'
ORDER BY d.location, r.measured_at DESC;
```

### Five-minute means over the last day

```sql
SELECT device_id, parameter,
       date_bin('5 minutes', measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
       avg(value) AS mean, count(*) AS n
FROM reading
WHERE measured_at > now() - interval '1 day'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
```

### Device clock offset

`received_at - measured_at` is the device clock's offset plus the
delivery delay. A sudden change means a clock was reset or messages
queued up.

```sql
SELECT device_id,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY received_at - measured_at) AS median_lag
FROM reading
WHERE received_at > now() - interval '1 hour'
GROUP BY device_id;
```

### Gaps: devices that stopped reporting

```sql
SELECT device_id, max(received_at) AS last_heard
FROM reading GROUP BY device_id
HAVING max(received_at) < now() - interval '1 minute';
```

## Exporting

`swim-project export` writes every table into the current directory, one
file per table and format, named after the table. Files of the same name
are replaced.

```bash
swim-project export --csv           # device.csv, reading.csv
swim-project export --jsonl         # device.jsonl, reading.jsonl
swim-project export --csv --jsonl   # all four
swim-project export --csv --entries 1000   # at most 1000 rows per table
```

```text
device.csv: 5 rows
reading.csv: 6307 rows
```

Both tables are read in one read-only, repeatable-read transaction, so
the files are one consistent snapshot even while a recorder is writing.
Rows are in primary-key order and every timestamp is in UTC.
`--entries N` writes at most N rows per table: the N readings with the
latest `measured_at` and the N devices with the latest `first_seen`,
still in primary-key order. The two cuts are independent, so with fewer
devices exported than exist, some readings may name a device missing
from `device.csv`. A file is
written under a `.part` name and renamed when complete, so a failed
export leaves no truncated file behind. Every column is exported, in the
table's own column order, so a database that still awaits `init-db
--force` can be exported first as a backup. A `device` table migrated
by `init-db --force` has `location` as its last column rather than its
third; read columns by header or key, not by position.

CSV has a header row; `location` is a PostgreSQL array literal and
timestamps use PostgreSQL's text format:

```text
device_id,kind,location,first_seen
TRH-0001,S,"{site-a,building-1,room,101,desk-1}",2026-11-18 08:36:41.512+00

device_id,parameter,measured_at,value,unit_of_measure,received_at
TRH-0001,relative_humidity,2026-11-18 08:31:23+00,55.56,%RH,2026-11-18 08:36:41.705+00
TRH-0001,temperature,2026-11-18 08:31:23+00,23.98,Cel,2026-11-18 08:36:41.505+00
```

JSON Lines has one object per row; `location` is a JSON array,
timestamps are ISO 8601, and a non-finite value is the string `"NaN"` or
`"Infinity"`:

```json
{"device_id":"TRH-0001","kind":"S","location":["site-a","building-1","room","101","desk-1"],"first_seen":"2026-11-18T08:36:41.512+00:00"}
{"device_id":"TRH-0001","parameter":"temperature","measured_at":"2026-11-18T08:31:23+00:00","value":23.98,"unit_of_measure":"Cel","received_at":"2026-11-18T08:36:41.505+00:00"}
```

## Volume

Each row of `reading` holds about 100 bytes of data plus its share of
the primary key and the time index. Ten parameters reporting every three
seconds give 288,000 rows a day, roughly 50 to 60 MB a day including
indexes.

## Privileges

| Command | Needs |
| :--- | :--- |
| `init-db` | `CREATE` on the schema (once) |
| `init-db --force` | Ownership of `device` and `reading`, to alter them |
| `init-db --force --clean` | Ownership of `device` and `reading`, to drop them |
| `record` | `SELECT`, `INSERT` on `device` and `reading` |
| `record --dry-run` | No database at all |
| `export` | `SELECT` on `device` and `reading` |

A separate read-only role with `SELECT` is enough for analysis.

## Schema changes

`init-db` brings the two tables to the schema of the installed version,
in one transaction, and touches no other table:

| Command | Missing table | Outdated table | Current table |
| :--- | :--- | :--- | :--- |
| `init-db` | Created | Refused, exit 1, nothing changed | Left alone |
| `init-db --force` | Created | Migrated in place, every row kept | Left alone |
| `init-db --force --clean` | Created | Dropped and recreated empty | Dropped and recreated empty |

A table is outdated when it lacks a column the recorder writes. `record`
refuses to start on an outdated table and names the command that fixes
it. Stop every running recorder before migrating: the migration locks
the table.

`--clean` deletes every reading and is refused without `--force`. It
drops only `device` and `reading`, without `CASCADE`, so a view built on
them makes it fail rather than disappear.

| From | Table | Migration |
| :--- | :--- | :--- |
| The first layout (five named columns) | `device` | `project`, `building`, `level`, `unit`, `area` become `location text[]` in that order |

The migration SQL is `MIGRATE_DEVICE_LOCATION` in
the `swim_project.db` module.
