"""Generate src/swim_project/templates/ from README.md, config.example.ini and docs/.

`swim-project init` writes these templates into a user's directory. They
are generated rather than committed (the directory is git-ignored), so the
repository's own files stay the single source and no symlinks are needed.
Run this before testing or building the package, and again after editing
any of the sources:

    uv run python scripts/build_templates.py          # regenerate
    uv run python scripts/build_templates.py --check  # exit 1 if out of date
"""

import argparse
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "src" / "swim_project" / "templates"


def sources() -> Iterator[tuple[Path, Path]]:
    """Each source file and its path inside the templates."""
    yield ROOT / "README.md", Path("README.md")
    yield ROOT / "config.example.ini", Path("config.ini")
    for doc in sorted((ROOT / "docs").rglob("*.md")):
        yield doc, doc.relative_to(ROOT)


def out_of_date() -> list[str]:
    """Templates that are missing, differ from their source, or have no source."""
    expected = dict((path, source) for source, path in sources())
    problems = [
        str(path)
        for path, source in expected.items()
        if not (TEMPLATES / path).is_file()
        or (TEMPLATES / path).read_bytes() != source.read_bytes()
    ]
    if TEMPLATES.is_dir():
        present = (path.relative_to(TEMPLATES) for path in TEMPLATES.rglob("*") if path.is_file())
        problems += [f"{path} (no source)" for path in present if path not in expected]
    return problems


def build() -> int:
    """Replace the templates with fresh copies of their sources; return how many."""
    if TEMPLATES.exists():
        shutil.rmtree(TEMPLATES)
    copied = 0
    for source, path in sources():
        (TEMPLATES / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, TEMPLATES / path)
        copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the templates are stale")
    if not parser.parse_args().check:
        print(f"copied {build()} files into {TEMPLATES.relative_to(ROOT)}")
        return 0
    problems = out_of_date()
    for problem in problems:
        print(f"out of date: {problem}")
    if problems:
        print("run `uv run python scripts/build_templates.py`")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
