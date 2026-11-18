"""The stream summary and refusals rendered with rich for the terminal.

Off a terminal (a pipe, a file, a test runner) rich writes plain text
without ANSI codes.
"""

from rich import box
from rich.console import Console
from rich.table import Table

from swim_project.live import LiveReadings


def print_summary(readings: LiveReadings, console: Console, *, dry_run: bool) -> None:
    """Print the counts table: readings stored (or received), devices and skips by reason."""
    console.line()
    if dry_run:
        console.print("dry run: nothing written", style="bold yellow", soft_wrap=True)
    table = Table(box=box.SIMPLE, show_header=False, title="Stream")
    table.add_column("what")
    table.add_column("count", justify="right")
    table.add_row("readings received" if dry_run else "readings stored", str(readings.received))
    table.add_row("devices", str(readings.devices))
    for reason, count in sorted(readings.skipped.items()):
        table.add_row(f"skipped ({reason})", str(count))
    console.print(table)


def print_error(message: str, console: Console) -> None:
    """Print `Error: ` and the message's first line, then each further line indented."""
    first, *details = message.splitlines()
    console.print(f"Error: {first}", style="bold red", markup=False, soft_wrap=True)
    for detail in details:
        console.print(f"  {detail}", style="red", markup=False, highlight=False, soft_wrap=True)
