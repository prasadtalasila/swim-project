"""The files `swim-project init` writes into a directory: config.ini, README.md and docs/.

The templates are generated from the repository's config.example.ini,
README.md and docs/ by scripts/build_templates.py, which must run before
testing or building; the directory is git-ignored.
"""

from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

TEMPLATES = files("swim_project") / "templates"

# Holds the broker and database passwords once filled in.
PRIVATE = Path("config.ini")


class InitError(Exception):
    """A file `init` would write already exists, or cannot be written."""


def _walk(node: Traversable, prefix: Path) -> Iterator[tuple[Path, Traversable]]:
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        path = prefix / child.name
        if child.is_dir():
            yield from _walk(child, path)
        else:
            yield path, child


def template_files() -> list[tuple[Path, Traversable]]:
    """Every file `init` writes, as (path relative to the target, template)."""
    return list(_walk(TEMPLATES, Path()))


def write_files(target: Path, *, force: bool) -> list[Path]:
    """Write every template under `target`; without `force`, refuse if any exists."""
    templates = template_files()
    existing = [str(path) for path, _ in templates if (target / path).exists()]
    if existing and not force:
        raise InitError(
            f"{target} already has {', '.join(existing)}; "
            "`swim-project init --force` overwrites them"
        )
    try:
        for path, template in templates:
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(template.read_bytes())
            if path == PRIVATE:
                destination.chmod(0o600)
    except OSError as error:
        raise InitError(f"cannot write into {target}\n{error}") from error
    return [path for path, _ in templates]
