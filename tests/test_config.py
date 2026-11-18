"""Reading the [mqtt] and [database] sections of the INI file."""

import pytest
from fakes import CONFIG

from swim_project.config import ConfigError, load_db, load_mqtt


def write(tmp_path, text):
    path = tmp_path / "config.ini"
    path.write_text(text)
    return path


def test_loads_both_sections(tmp_path):
    path = write(tmp_path, CONFIG)
    mqtt = load_mqtt(path)
    assert (mqtt.host, mqtt.port, mqtt.username, mqtt.tls) == (
        "broker.example.org",
        8883,
        "recorder",
        True,
    )
    assert mqtt.topics == ("site-a/building-1/room/101/+/S/+/+", "site-a/building-1/room/102/#")
    database = load_db(path)
    assert (database.db_name, database.port, database.password) == ("sensors", 5432, "p%ss")


def test_mqtt_login_is_optional_and_tls_can_be_off(tmp_path):
    mqtt = load_mqtt(write(tmp_path, "[mqtt]\nhost=localhost\nport=1883\ntls=false\n"))
    assert (mqtt.username, mqtt.password, mqtt.tls, mqtt.topics) == (None, None, False, ())


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[database]\nhostname=x\n", "has no [mqtt] section"),
        ("[mqtt]\nport=1883\n", "[mqtt] has no host"),
        ("[mqtt]\nhost=x\nport=eighty\n", "port is not a number: 'eighty'"),
        ("[mqtt]\nhost=x\nport=1\ntls=maybe\n", "tls is not a boolean: 'maybe'"),
        ("no section header\n", "is not a valid INI file"),
    ],
)
def test_mqtt_refusals(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_mqtt(write(tmp_path, text))


def test_database_needs_every_key(tmp_path):
    with pytest.raises(ConfigError, match="has no password"):
        load_db(write(tmp_path, "[database]\nhostname=x\nport=1\ndb_name=d\nusername=u\n"))
