"""The latest reading of every device parameter, rendered as a table while streaming.

The MQTT network thread records readings; the main thread renders the
table. A lock keeps the two apart.
"""

import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from rich import box
from rich.table import Table

from swim_project.model import Reading

COLUMNS = ("location", "device", "parameter", "value", "measured at", "readings")


@dataclass
class Latest:
    reading: Reading
    count: int = 0


class LiveReadings:
    """Counts of stored and skipped messages, and the latest reading per device parameter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[tuple[str, str], Latest] = {}
        self.received = 0
        self.skipped: Counter[str] = Counter()

    def record(self, reading: Reading) -> None:
        key = (reading.topic.device_id, reading.topic.parameter)
        with self._lock:
            latest = self._latest.setdefault(key, Latest(reading))
            latest.reading = reading
            latest.count += 1
            self.received += 1

    def skip(self, reason: str) -> None:
        with self._lock:
            self.skipped[reason] += 1

    def latest(self) -> list[Latest]:
        """The latest readings, ordered by device then parameter."""
        with self._lock:
            return [Latest(item.reading, item.count) for _, item in sorted(self._latest.items())]

    @property
    def devices(self) -> int:
        with self._lock:
            return len({device for device, _ in self._latest})

    def table(self, now: datetime) -> Table:
        """The live table: one row per device parameter, its latest value and its count."""
        caption = f"{self.received} readings, {sum(self.skipped.values())} skipped"
        table = Table(
            title=f"Live readings at {now:%Y-%m-%d %H:%M:%S}",
            caption=caption,
            box=box.SIMPLE_HEAD,
        )
        for column in COLUMNS:
            justify = "right" if column in ("value", "readings") else "left"
            table.add_column(column, justify=justify, no_wrap=column not in ("location", "device"))
        for item in self.latest():
            reading = item.reading
            table.add_row(
                "/".join(reading.topic.location),
                reading.topic.device_id,
                reading.topic.parameter,
                f"{reading.value:.2f} {reading.unit_of_measure}",
                f"{reading.measured_at.astimezone():%H:%M:%S}",
                str(item.count),
            )
        return table
