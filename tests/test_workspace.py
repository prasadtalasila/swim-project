"""The files `init` writes, and the templates' agreement with the repository."""

import stat
import subprocess
import sys
from pathlib import Path

import pytest

from swim_project.workspace import InitError, template_files, write_files

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {
    Path("config.ini"),
    Path("README.md"),
    Path("docs/data-format.md"),
    Path("docs/database.md"),
}


def test_templates_match_the_repository():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_templates.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout


def test_writes_every_file(tmp_path):
    assert set(write_files(tmp_path, force=False)) == EXPECTED
    for path, template in template_files():
        assert (tmp_path / path).read_bytes() == template.read_bytes()
    assert "[database]" in (tmp_path / "config.ini").read_text()


def test_config_is_private(tmp_path):
    write_files(tmp_path, force=False)
    assert stat.S_IMODE((tmp_path / "config.ini").stat().st_mode) == 0o600


def test_existing_files_are_refused_and_nothing_is_written(tmp_path):
    (tmp_path / "README.md").write_text("mine")
    with pytest.raises(InitError, match="already has README.md; .*init --force"):
        write_files(tmp_path, force=False)
    assert [path.name for path in tmp_path.iterdir()] == ["README.md"]
    assert (tmp_path / "README.md").read_text() == "mine"


def test_force_overwrites_and_keeps_other_files(tmp_path):
    (tmp_path / "README.md").write_text("mine")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("keep")
    write_files(tmp_path, force=True)
    assert (tmp_path / "README.md").read_text() != "mine"
    assert (tmp_path / "docs" / "notes.md").read_text() == "keep"


def test_unwritable_target(tmp_path):
    target = tmp_path / "file"
    target.write_text("not a directory")
    with pytest.raises(InitError, match="cannot write into"):
        write_files(target, force=True)
