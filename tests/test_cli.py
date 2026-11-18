"""The command line: version, help, init-db and record, with fakes for broker and database."""

import subprocess
import sys
from pathlib import Path
from importlib.metadata import version

import pytest
from click.testing import CliRunner
from fakes import CONFIG, FakeClient, FakeConnection, message

from swim_project import __main__ as cli
from swim_project import db
from swim_project import stream as stream_module
from swim_project.db import DatabaseError

TOPIC_FILTER = "site-a/building-1/room/101/+/S/+/+"


@pytest.fixture(autouse=True)
def _plain_output(monkeypatch):
    for name in ("FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stream_module.mqtt, "Client", FakeClient)
    FakeClient.messages = [message(), message(payload=b"[]"), message()]
    FakeClient.unreachable = False


@pytest.fixture(name="config")
def config_file(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(CONFIG)
    return str(path)


@pytest.fixture(name="conn")
def fake_connection(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(cli, "connect", lambda _settings: conn)
    return conn


def invoke(*args):
    return CliRunner().invoke(cli.main, list(args))


def test_version_and_module_entry_point():
    assert version("swim_project") in invoke("--version").output
    done = subprocess.run(
        [sys.executable, "-m", "swim_project", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert version("swim_project") in done.stdout


def test_help_shows_examples_and_panels():
    assert "Examples" in invoke("--help").output
    output = invoke("record", "--help").output
    assert "Connection" in output and "Behaviour" in output and "\x1b[" not in output
    assert "--display" in output


def test_init_db_creates_the_tables(config, conn):
    result = invoke("init-db", "--config", config)
    assert result.exit_code == 0, result.output
    assert result.output == "tables ready: device, reading\n"
    assert "CREATE TABLE IF NOT EXISTS device" in conn.executed[-1][0] and conn.closed


def test_init_db_force_reports_migrated_tables(config, conn):
    conn.names[db.STALE_TABLES] = ["device"]
    result = invoke("init-db", "--config", config, "--force")
    assert result.exit_code == 0, result.output
    assert "migrated device, keeping its rows" in result.output


def test_init_db_clean_needs_force(config, conn):
    result = invoke("init-db", "--config", config, "--clean")
    assert result.exit_code == 2 and "only works with --force" in result.output
    assert not conn.executed


def test_init_db_force_clean_drops_first(config, conn):
    result = invoke("init-db", "--config", config, "--force", "--clean")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("dropped device, reading\n")
    assert conn.executed[0][0] == db.DROP_TABLES


def test_record_with_display_stores_and_summarises(config, conn):
    result = invoke("record", "--config", config, "--display", "--limit", "2")
    assert result.exit_code == 0, result.output
    assert "Live readings at" in result.output and "23.98 Cel" in result.output
    assert "readings stored" in result.output
    assert "skipped (payload is not a JSON object)" in result.output
    assert sum("INSERT INTO reading" in sql for sql, _ in conn.executed) == 2


def test_record_uses_the_configured_topics(config, conn):
    result = invoke("record", "--config", config, "--limit", "2")
    assert result.exit_code == 0, result.output
    assert "Live readings at" not in result.output and "readings stored" in result.output
    assert [topic for topic, _ in FakeClient.last.subscribed] == [
        "site-a/building-1/room/101/+/S/+/+",
        "site-a/building-1/room/102/#",
    ]
    assert conn.closed


@pytest.mark.usefixtures("conn")
def test_topic_option_replaces_the_configured_topics(config):
    invoke("record", "--config", config, "--topic", "lab/#", "--limit", "1")
    assert FakeClient.last.subscribed == [("lab/#", 1)]


def test_record_needs_some_topics(tmp_path, conn):
    path = tmp_path / "config.ini"
    path.write_text(CONFIG.split("topics=", maxsplit=1)[0])
    result = invoke("record", "--config", str(path))
    assert result.exit_code == 1
    assert "[mqtt] has no topics, and no --topic was given" in result.stderr
    assert not conn.executed


def test_dry_run_needs_no_database(config, monkeypatch):
    monkeypatch.setattr(cli, "connect", pytest.fail)
    result = invoke("record", "--config", config, "--limit", "1", "--dry-run")
    assert result.exit_code == 0, result.output
    assert "dry run: nothing written" in result.output and "readings received" in result.output


def test_refusal_exits_1_with_the_reason(config, monkeypatch):
    def refuse(_settings):
        raise DatabaseError("cannot connect to database sensors\ntimeout expired")

    monkeypatch.setattr(cli, "connect", refuse)
    result = invoke("record", "--config", config, "--topic", TOPIC_FILTER)
    assert result.exit_code == 1
    assert "Error: cannot connect to database sensors\n  timeout expired" in result.stderr


def test_stream_command_is_gone(config):
    assert invoke("stream", "--config", config).exit_code == 2


def test_config_defaults_to_the_current_directory(config, conn, monkeypatch):
    monkeypatch.chdir(Path(config).parent)
    result = invoke("init-db")
    assert result.exit_code == 0, result.output
    assert conn.closed


def test_missing_default_config_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = invoke("record", "--dry-run")
    assert result.exit_code == 2 and "config.ini" in result.output


def test_init_writes_into_the_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = invoke("init")
    assert result.exit_code == 0, result.output
    assert "wrote config.ini" in result.output and "next: fill in" in result.output
    assert (tmp_path / "docs" / "database.md").is_file()
    again = invoke("init")
    assert again.exit_code == 1 and "init --force" in again.stderr
    assert invoke("init", "--force").exit_code == 0


def test_export_needs_a_format(config):
    result = invoke("export", "--config", config)
    assert result.exit_code == 2 and "choose --csv, --jsonl or both" in result.output


def test_export_writes_into_the_current_directory(config, conn, tmp_path, monkeypatch):
    conn.rows = {"device": ["TRH-0001,S"], "reading": []}
    monkeypatch.chdir(tmp_path)
    result = invoke("export", "--config", config, "--csv")
    assert result.exit_code == 0, result.output
    assert result.output == "device.csv: 1 rows\nreading.csv: 0 rows\n"
    assert (tmp_path / "device.csv").is_file() and conn.closed


def test_export_entries(config, conn, tmp_path, monkeypatch):
    conn.rows = {"device": [], "reading": []}
    monkeypatch.chdir(tmp_path)
    result = invoke("export", "--config", config, "--jsonl", "--entries", "5")
    assert result.exit_code == 0, result.output
    assert all("LIMIT 5) AS t" in sql for sql, _ in conn.executed if "row_to_json" in sql)


def test_export_entries_must_be_positive(config):
    result = invoke("export", "--config", config, "--csv", "--entries", "0")
    assert result.exit_code == 2 and "--entries" in result.output
