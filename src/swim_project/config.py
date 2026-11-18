"""The INI configuration file: the broker's and the database's connection settings."""

import configparser
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """The configuration file is missing a section or a key, or holds a bad value."""


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    tls: bool
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class DbSettings:
    hostname: str
    port: int
    db_name: str
    username: str
    password: str


def _section(path: Path, name: str) -> configparser.SectionProxy:
    # No interpolation: passwords may hold a literal %.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as error:
        raise ConfigError(f"{path} is not a valid INI file: {error}") from error
    if not parser.has_section(name):
        raise ConfigError(f"{path} has no [{name}] section")
    return parser[name]


def _require(section: configparser.SectionProxy, key: str) -> str:
    value = section.get(key, "").strip()
    if not value:
        raise ConfigError(f"[{section.name}] has no {key}")
    return value


def _port(section: configparser.SectionProxy) -> int:
    raw = _require(section, "port")
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"[{section.name}] port is not a number: {raw!r}") from error


def _lines(section: configparser.SectionProxy, key: str) -> tuple[str, ...]:
    """A multi-line value, one item per non-blank line; comment lines are already dropped."""
    return tuple(line.strip() for line in section.get(key, "").splitlines() if line.strip())


def load_mqtt(path: Path) -> MqttSettings:
    """Read the [mqtt] section; tls defaults to on, the login and topics are optional."""
    section = _section(path, "mqtt")
    try:
        tls = section.getboolean("tls", fallback=True)
    except ValueError as error:
        raise ConfigError(f"[mqtt] tls is not a boolean: {section['tls']!r}") from error
    return MqttSettings(
        host=_require(section, "host"),
        port=_port(section),
        username=section.get("username") or None,
        password=section.get("password") or None,
        tls=tls,
        topics=_lines(section, "topics"),
    )


def load_db(path: Path) -> DbSettings:
    """Read the [database] section; every key is required."""
    section = _section(path, "database")
    return DbSettings(
        hostname=_require(section, "hostname"),
        port=_port(section),
        db_name=_require(section, "db_name"),
        username=_require(section, "username"),
        password=_require(section, "password"),
    )
