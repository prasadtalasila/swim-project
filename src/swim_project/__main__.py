"""The `swim-project` command line."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.text import Text

from swim_project.config import ConfigError, load_db, load_mqtt
from swim_project.console import print_error, print_summary
from swim_project.db import DatabaseError, DatabaseSink, connect, create_schema
from swim_project.export import ExportError, export_tables
from swim_project.live import LiveReadings
from swim_project.stream import Recorder, StreamFailed, stream
from swim_project.workspace import InitError, write_files

REFUSALS = (ConfigError, DatabaseError, StreamFailed, InitError, ExportError)

EXAMPLES = Text.from_markup(
    """[b]Examples[/]

Write config.ini, README.md and docs/ into the current directory:
  swim-project init

Every other command reads config.ini from the current directory unless
--config names another file.

Create the device and reading tables, or migrate them after an upgrade:
  swim-project init-db
  swim-project init-db --force

Watch the live readings of the configured topics without storing them:
  swim-project record --display --dry-run

Record them until Ctrl+C or SIGTERM, with no terminal output until then:
  swim-project record --config /etc/swim-project/config.ini

Record one room instead of the configured topics, showing the readings:
  swim-project record --display --topic 'site-a/building-1/room/101/+/S/+/+'

Export both tables as device.csv and reading.csv, and as JSON Lines:
  swim-project export --csv --jsonl

Export only the 1000 newest readings (and at most 1000 devices):
  swim-project export --csv --entries 1000"""
)

CONFIG_HELP = (
    "INI file with [mqtt] and [database] sections, as written by `swim-project init`. "
    "Defaults to config.ini in the current directory."
)

config_option = click.option(
    "--config",
    "config_path",
    default="config.ini",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=CONFIG_HELP,
)


def _refusing[T](action: Callable[[], T]) -> T:
    """Run `action`; print a refusal on stderr and exit 1 instead of a traceback."""
    try:
        return action()
    except REFUSALS as error:
        print_error(str(error), Console(stderr=True))
        raise SystemExit(1) from error


@click.group(epilog=EXAMPLES)
@click.version_option(package_name="swim_project")
def main() -> None:
    """Record sensor readings from an MQTT broker into a PostgreSQL database."""


@main.command("init", epilog=EXAMPLES)
@click.option(
    "--force", is_flag=True, help="Overwrite config.ini, README.md and docs/ files that exist."
)
def init_command(force: bool) -> None:
    """Write config.ini, README.md and docs/ into the current directory.

    Without --force nothing is written if any of them exists. config.ini is
    readable by you only; fill it in next, as README.md describes.
    """
    target = Path.cwd()
    written = _refusing(lambda: write_files(target, force=force))
    console = Console()
    for path in written:
        console.print(f"wrote {path}", soft_wrap=True, highlight=False)
    console.print(f"next: fill in {target / 'config.ini'}", soft_wrap=True, highlight=False)


@main.command("init-db", epilog=EXAMPLES)
@config_option
@click.option(
    "--force", is_flag=True, help="Migrate tables whose schema is out of date, keeping their rows."
)
@click.option(
    "--clean",
    is_flag=True,
    help="Needs --force. Drop the device and reading tables, and every row, then recreate them.",
)
def init_db(config_path: Path, force: bool, clean: bool) -> None:
    """Create the device and reading tables, or bring them up to date.

    Uses the [database] section. Without --force, existing tables and rows
    are left as they are, and an out-of-date table is refused.
    """
    if clean and not force:
        raise click.UsageError("--clean deletes every reading, so it only works with --force")

    def create() -> list[str]:
        conn = connect(load_db(config_path))
        with conn:
            return create_schema(conn, force=force, clean=clean)

    migrated = _refusing(create)
    console = Console()
    if clean:
        console.print("dropped device, reading", soft_wrap=True)
    for table in migrated:
        console.print(f"migrated {table}, keeping its rows", soft_wrap=True)
    console.print("tables ready: device, reading", soft_wrap=True)


@dataclass(frozen=True)
class RecordOptions:
    config_path: Path
    topics: tuple[str, ...]
    display: bool
    refresh: float
    limit: int | None
    dry_run: bool


def _record(options: RecordOptions) -> LiveReadings:
    settings = load_mqtt(options.config_path)
    topics = options.topics or settings.topics
    if not topics:
        raise ConfigError(f"{options.config_path}: [mqtt] has no topics, and no --topic was given")
    refresh = options.refresh if options.display else None
    console = Console()
    if options.dry_run:
        recorder = Recorder(topics, lambda _: None, options.limit)
        return stream(settings, recorder, console=console, refresh=refresh)
    conn = connect(load_db(options.config_path))
    with conn:
        recorder = Recorder(topics, DatabaseSink(conn), options.limit)
        return stream(settings, recorder, console=console, refresh=refresh)


@main.command("record", epilog=EXAMPLES)
@click.option_panel("Connection", options=["--config", "--topic"])
@click.option_panel("Behaviour", options=["--display", "--refresh", "--limit", "--dry-run"])
@config_option
@click.option(
    "--topic",
    "topics",
    multiple=True,
    help="Topic filter to subscribe to instead of [mqtt] topics; + and # allowed. Repeatable.",
)
@click.option("--display", is_flag=True, help="Show a live table of the latest readings.")
@click.option(
    "--refresh",
    default=10.0,
    show_default=True,
    type=click.FloatRange(min=0.5),
    help="Seconds between redraws of the --display table.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    help="Stop after this many readings; without it, record until Ctrl+C or SIGTERM.",
)
@click.option("--dry-run", is_flag=True, help="Receive and count readings, but store nothing.")
def record_command(**options) -> None:
    """Subscribe to the topics and store every reading in the database.

    The topics are the [mqtt] topics of the config file, or the --topic
    filters. Prints a summary on Ctrl+C, SIGTERM or at --limit. Messages
    with a malformed topic or payload are skipped and counted. A refusal
    exits 1.
    """
    record_options = RecordOptions(**options)
    readings = _refusing(lambda: _record(record_options))
    print_summary(readings, Console(), dry_run=record_options.dry_run)


@main.command("export", epilog=EXAMPLES)
@config_option
@click.option("--csv", "csv_", is_flag=True, help="Write device.csv and reading.csv, with headers.")
@click.option("--jsonl", is_flag=True, help="Write device.jsonl and reading.jsonl.")
@click.option(
    "--entries",
    type=click.IntRange(min=1),
    metavar="N",
    help="Write at most N rows per table: the newest readings and most recently seen devices.",
)
def export_command(config_path: Path, csv_: bool, jsonl: bool, entries: int | None) -> None:
    """Export every table into the current directory, one file per table and format.

    Files are named after their table and replace any of the same name. Both
    tables come from one consistent snapshot; timestamps are in UTC. Rows
    are in key order, also with --entries.
    """
    formats = tuple(name for name, chosen in (("csv", csv_), ("jsonl", jsonl)) if chosen)
    if not formats:
        raise click.UsageError("choose --csv, --jsonl or both")

    def export() -> list[tuple[Path, int]]:
        conn = connect(load_db(config_path))
        with conn:
            return export_tables(conn, Path.cwd(), formats, entries)

    console = Console()
    for path, rows in _refusing(export):
        console.print(f"{path.name}: {rows} rows", soft_wrap=True, highlight=False)


if __name__ == "__main__":  # pragma: no cover
    main()
