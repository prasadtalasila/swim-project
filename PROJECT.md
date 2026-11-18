# Project Instructions

Instructions specific to swim_project, for contributors and
coding agents alike. `AGENTS.md` holds the general coding guidelines;
this file holds what cannot be inferred from them.

## Autonomy

Work through the full cycle for routine changes without pausing at each
step. Pause only for irreversible actions (force-push, history rewrite,
deletion, publishing) or requirements with two defensible readings that
lead to materially different work.

## Behaviour

**Think before coding.** State assumptions. Where several readings
exist, present them rather than choosing silently.

**Simplicity first.** Write the minimum that solves the stated problem.
No speculative abstraction, unrequested configurability, or defensive
handling for impossible states.

**Surgical changes.** Every changed line traces to the task. Match local
style. Remove imports your change orphans; report pre-existing dead code
instead of deleting it in the same diff.

**Goal-driven execution.** Turn the task into a check you can run.
"Fix the bug" becomes "write a failing test, then make it pass."

## Build and test commands

The project is managed with [uv](https://docs.astral.sh/uv/).

| Task | Command |
| :--- | :--- |
| Install | `uv sync` |
| Generate templates | `uv run python scripts/build_templates.py` |
| Test | `uv run pytest --cov --cov-report=term-missing` |
| Lint | `uv run ruff check . && uv run ruff format --check . && uv run pylint src tests` |
| Build | `uv run python scripts/build_templates.py && uv build` |

### Generated templates

`swim-project init` writes copies of `README.md`, `config.example.ini`
(as `config.ini`) and `docs/**/*.md` into a user's directory. The copies
live in `src/swim_project/templates/`, which is generated and
git-ignored, so the repository's own files stay the single source and no
symlinks are needed. uv_build packages the generated files into both the
wheel and the sdist.

Generate them before running the tests or building, and again after
editing any source. Without them `init` and its tests fail;
`tests/test_workspace.py` runs `build_templates.py --check` and fails
with the command to run when they are out of date. A wheel built without
this step has no templates and a broken `init`.

`README.md` is therefore the user guide of an installed package as well
as the repository's front page: write it for someone who installed the
wheel, and keep developer material in this file. Links in `docs/` must
work in a user's directory too, so they never point outside `docs/`.

### Running from a checkout

```bash
uv sync
uv run python scripts/build_templates.py
cp config.example.ini config.ini          # then fill it in
uv run swim-project --help                 # the commands
uv run swim-project record --help          # one command, with examples
uv run swim-project record --display --dry-run --limit 20
```

Every command reads `config.ini` from the current directory, which is
the repository root here.

### Building and installing the wheel

```bash
uv run python scripts/build_templates.py && uv build
uv tool install --force dist/swim_project-0.1.0-py3-none-any.whl
```

The wheel holds only the `swim_project` package, its templates and the
licence: never a `config.ini`. Check with
`unzip -l dist/swim_project-*.whl` before handing a wheel on.

`prompt.md` is the set-up guide a user gives an AI coding assistant to
install and initialise the package. Keep its commands in step with the
README when the CLI changes.

## Verifying a change

Run the test and lint commands above. Line and branch coverage stays at
100%. Compare against the merge base before reporting a regression: run
the same command there and compare counts. Report pre-existing failures;
do not fix them in the same diff.

For a change to the topic or payload parsing (`model.py`) or the
tables (`db.py`), also run a dry run against the real broker, with the
topics set in `config.ini`, and check the live table shows every device
with nothing skipped:

```bash
uv run swim-project record --display --dry-run --limit 20
```

`config.ini` holds credentials; never commit it.

Claim something passes only after seeing it pass.

## Shipping

1. Branch from the default branch. Never commit to it directly.
1. Commit following the format below.
1. Sweep documentation your change made stale. Search the repository for
   paths, names and numbers you moved.
   Regenerate the templates after editing `README.md`,
   `config.example.ini` or `docs/`.
1. Open a pull request using `.github/pull_request_template.md`.
1. Address review, then merge.

## Commit messages

- **Title:** imperative mood, concise, describing the change's effect.
  Pull requests are squash-merged and the PR title becomes the commit
  title. Never add the PR number by hand; GitHub appends it.
- **Body:** a blank line, then bullets that each start with a
  present-tense verb (Fix, Add, Remove) and name a concrete change. No
  preamble. Lines wrap at 72 characters; continuation lines are indented
  two spaces.
- **No closing keywords** (`Closes #N`) in the commit; they belong in
  the PR description.

## Versioning

Semantic versioning, in `pyproject.toml`'s `[project].version`, bumped
by the most significant change in a release:

- **PATCH:** bug fixes, documentation, tests, CI.
- **MINOR:** new backward-compatible behaviour, such as a new optional
  CLI option or a new nullable column.
- **MAJOR:** a change to an existing table's columns or key, the
  configuration file's keys, or an existing CLI option's shape.

## Code standards

ruff (`pyproject.toml`) and pylint (`.pylintrc`) enforce style. Run them
rather than reasoning about style. pylint also enforces the size limits
from `AGENTS.md`: at most 25 statements per function and 250 lines per
module. Add a dependency only when the task requires it.

## Output contract

The recorder writes only to the `device` and `reading` tables and never
stores a reading twice: `reading` is keyed by device, parameter and the
sensor's timestamp. Only `init-db --force` alters those two tables, and
it keeps every row; only `init-db --force --clean` drops them. No
command touches any other table. `export` only reads, and writes
files named after the tables into the current directory; `init` writes
only its template files there. A change to a table's columns ships a
migration in `MIGRATIONS` (`db.py`). The design is in
`developer/adr/0001-tables-mirror-topic-hierarchy.md` and
`developer/adr/0002-device-location-is-a-variable-depth-array.md`; the
tables are documented in `docs/database.md`.

