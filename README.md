# swim_project

The `swim-project` command subscribes to sensor topics on an MQTT broker
and stores every reading in a PostgreSQL database. It can show a live
table of the latest readings and export the tables to CSV or JSON Lines.

Developing the package itself is described in `PROJECT.md` in the
repository.

## Install

Python 3.12 or later is required. Install the command into its own
environment with [uv](https://docs.astral.sh/uv/), from a wheel file or
from the repository:

```bash
uv tool install ./swim_project-0.1.0-py3-none-any.whl
uv tool install git+<repository-url>
swim-project --version
```

`pipx install` takes the same arguments. To have an AI coding assistant
install and set it up for you, give it `prompt.md` from the repository.

## Initialise

Choose a directory for the recorder, for example
`~/.config/swim-project`, and run `init` there:

```bash
mkdir -p ~/.config/swim-project && cd ~/.config/swim-project
swim-project init
```

It writes `config.ini` (readable by you only), this `README.md` and
`docs/`. It refuses if any of them exists; `swim-project init --force`
overwrites them, including a `config.ini` you have filled in, and leaves
other files alone.

## Configure

Every command except `init` reads `config.ini` from the current
directory; `--config PATH` names another file. The file has two
sections:

```ini
[database]
hostname=db.example.org
port=5432
db_name=sensors
username=recorder
password=change-me

[mqtt]
host=broker.example.org
port=8883
username=recorder
password=change-me
tls=true
topics=
    site-a/building-1/room/101/+/S/+/+
    site-a/building-1/room/102/#
```

### `[database]`: the PostgreSQL database

| Key | Required | Meaning |
| :--- | :--- | :--- |
| `hostname` | yes | Host name or address of the PostgreSQL server |
| `port` | yes | Its port, usually `5432` |
| `db_name` | yes | The database that holds the `device` and `reading` tables |
| `username` | yes | The role to log in as; see [Privileges](docs/database.md#privileges) |
| `password` | yes | Its password |

`record --dry-run` does not use this section.

### `[mqtt]`: the broker and what to record

| Key | Required | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `host` | yes | | Host name or address of the MQTT broker |
| `port` | yes | | Its port: usually `8883` with TLS, `1883` without |
| `username` | no | none | The account to log in with; leave out for an anonymous broker |
| `password` | no | none | Its password |
| `tls` | no | `true` | `true` verifies the broker's certificate against the system's certificate authorities; `false` connects in plain text (a local test broker only) |
| `topics` | see below | none | Topic filters to subscribe to, one per indented line |

`topics` is required unless every `record` is given `--topic`, which
replaces the whole list for that run. Filters may use the MQTT wildcards
`+` (one segment) and `#` (all remaining segments); see
[docs/data-format.md](docs/data-format.md#subscribing).

### Rules of the file

- `config.ini` holds two passwords: keep it readable by you only
  (`init` creates it so) and never commit or share it.
- A `%` is literal; there is no interpolation.
- `true`/`false` may also be written `yes`/`no`, `on`/`off` or `1`/`0`.
- A comment is a whole line starting with `#` or `;`. A `#` after a
  value is part of the value.
- Each topic filter goes on its own line, indented under `topics=`;
  comment lines between them are allowed.

## Use

Create the tables once; existing tables and rows are left alone:

```bash
swim-project init-db
```

Watch the configured topics without writing anything:

```bash
swim-project record --display --dry-run --limit 20
```

Record them until Ctrl+C or SIGTERM:

```bash
swim-project record
```

Without `--display` nothing is printed until the recorder stops, which
suits running it as a service. On stopping it prints a summary: readings
stored, devices, and skipped messages by reason. Messages whose topic or
payload has the wrong shape are skipped and counted; a database or
broker failure stops the recorder and exits 1.

| `record` option | Effect |
| :--- | :--- |
| `--config PATH` | Read this file instead of `./config.ini` |
| `--topic FILTER` | Record this filter instead of `[mqtt] topics`; repeatable |
| `--display` | Show the live table of latest readings |
| `--refresh SECONDS` | Redraw interval of the `--display` table (default 10) |
| `--limit N` | Stop after N readings |
| `--dry-run` | Receive and count readings, store nothing, need no database |

Export every table into the current directory, one file per table:

```bash
swim-project export --csv            # device.csv, reading.csv
swim-project export --jsonl          # device.jsonl, reading.jsonl
swim-project export --csv --jsonl    # both
```

The formats are described in
[docs/database.md](docs/database.md#exporting).

`swim-project --help` lists the commands, and `swim-project <command>
--help` describes each one with examples.

### Upgrading the tables

After an upgrade that changes a table, `record` refuses to start and
`init-db` reports the outdated table. Export it first if you want a
backup, then migrate it, keeping every row:

```bash
swim-project export --csv
swim-project init-db --force
```

`init-db --force --clean` instead drops `device` and `reading`, with
every reading in them, and recreates them empty. `--clean` is refused
without `--force`.

## Topics, payloads and tables

Topics are `<location...>/<S|A>/<device_id>/<parameter>`, with a location
of one or more segments, for example
`site-a/building-1/room/101/desk-1/S/TRH-0001/temperature`. Payloads are
JSON objects: `{"value": 23.98, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}`.
The full rules, with examples of accepted and skipped messages, are in
[docs/data-format.md](docs/data-format.md).

The tables mirror that structure:

| Table | Row per | Columns |
| :--- | :--- | :--- |
| `device` | device | `device_id` (key), `kind` (`S` sensor or `A` actuator), `location` (`text[]`, the location segments), `first_seen` |
| `reading` | message | `device_id` (→ `device`), `parameter`, `measured_at` (payload `ts`), `value`, `unit_of_measure`, `received_at` |

`reading`'s key is `(device_id, parameter, measured_at)`, so a redelivered
message is stored once. Columns, example rows and queries are in
[docs/database.md](docs/database.md).

Latest temperature per location:

```sql
SELECT DISTINCT ON (d.location)
       array_to_string(d.location, '/') AS location, r.value, r.unit_of_measure, r.measured_at
FROM reading r JOIN device d USING (device_id)
WHERE r.parameter = 'temperature'
ORDER BY d.location, r.measured_at DESC;
```
