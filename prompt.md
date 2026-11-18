# Install and set up swim-project

You are helping a user install `swim_project`, whose `swim-project`
command records sensor readings from an MQTT broker into a PostgreSQL
database. Work through the steps below in order, on the user's machine.
Explain each step briefly before running it, and stop to ask whenever a
step says so.

## Rules

- **Passwords.** The broker and database passwords go only into
  `config.ini`. Never put them on a command line, in an environment
  variable you print, or in your replies; never print `config.ini` back
  in full. Ask the user to type a password into the file themselves if
  they prefer.
- **Destructive commands need the user's explicit yes, each time:**
  `swim-project init --force` (overwrites `config.ini`),
  `swim-project init-db --force` (alters the tables) and above all
  `swim-project init-db --force --clean` (deletes every reading).
- **Installing other software** (uv, Python) needs the user's yes first.
- Report what you did and what failed, with the command's output. Do not
  claim a step worked without seeing it work.

## 1. Gather what you need

Ask the user for:

1. Where to install from: a wheel file (`swim_project-<version>-py3-none-any.whl`)
   or the repository URL.
2. The directory to hold the configuration, default
   `~/.config/swim-project`.
3. The MQTT broker: host, port, whether it uses TLS (usually port 8883)
   or not (usually 1883), and the account's username and password, if any.
4. The topic filters to record, for example
   `site-a/building-1/room/101/+/S/+/+`. Topics have the shape
   `<location...>/<S|A>/<device_id>/<parameter>`.
5. The PostgreSQL database: host, port (usually 5432), database name,
   username and password. Skip this if the user only wants to watch
   readings for now.

## 2. Check the prerequisites

```bash
python3 --version   # needs 3.12 or later
uv --version        # or: pipx --version
```

If neither uv nor pipx is present, ask, then install uv following
<https://docs.astral.sh/uv/getting-started/installation/>.

## 3. Install

```bash
uv tool install <wheel-file-or-git+repository-url>
swim-project --version
```

If `swim-project` is not found, run `uv tool update-shell` and open a
new shell. With pipx, use `pipx install` with the same argument.

## 4. Initialise the configuration directory

```bash
mkdir -p ~/.config/swim-project && cd ~/.config/swim-project
swim-project init
```

This writes `config.ini` (mode 600), `README.md` and `docs/`. If it
refuses because files exist, show the user which ones and ask before
using `--force`; a filled-in `config.ini` would be lost.

## 5. Fill in config.ini

Edit `config.ini` in place, replacing every example value with the
user's answers from step 1. `README.md`, section Configure, describes
every key. In particular:

- `tls=false` only for a broker without TLS.
- Leave `username` and `password` out under `[mqtt]` for an anonymous
  broker.
- Each topic filter on its own indented line under `topics=`.
- A `%` is literal and a `#` after a value becomes part of it.

Check the file is still private: `ls -l config.ini` shows `-rw-------`.

## 6. Check the broker

```bash
swim-project record --display --dry-run --limit 20
```

It stores nothing. Expect a table with every device the user expects
and `0 skipped`. If it fails:

- `cannot reach the broker`: wrong host or port, or a firewall.
- `the broker refused the connection: Not authorized`: wrong username
  or password, or the account may not read those topics.
- No readings at all: the topic filters match nothing; ask the user to
  confirm them.
- Messages skipped: the summary names the reason; `docs/data-format.md`
  lists what each reason means. Show the user, do not change the filters
  on your own.

## 7. Set up the database

```bash
swim-project init-db
```

`tables ready: device, reading` means done. If it reports an outdated
table, an older version created it: offer
`swim-project export --csv` as a backup first, then ask before running
`swim-project init-db --force`, which migrates it and keeps every row.
`permission denied` means the database role lacks rights; the
Privileges section of `docs/database.md` lists what each command needs.

Then record a few readings for real and check they arrive:

```bash
swim-project record --limit 20
swim-project export --csv
```

`reading.csv` should list them.

## 8. Run it continuously (ask first)

Ask whether the user wants recording to run in the background. It stops
cleanly on SIGTERM and prints its summary.

If `ps -p 1 -o comm=` prints `systemd`, offer a user service. Write
`~/.config/systemd/user/swim-project.service`, with the full path from
`command -v swim-project`:

```ini
[Unit]
Description=swim-project MQTT recorder
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
WorkingDirectory=%h/.config/swim-project
ExecStart=/full/path/to/swim-project record
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now swim-project
systemctl --user status swim-project
loginctl enable-linger "$USER"   # keeps it running after logout; ask first
journalctl --user -u swim-project
```

Without systemd (a container, for example), run it detached and tell the
user it will not restart on its own:

```bash
cd ~/.config/swim-project
setsid nohup swim-project record >> recorder.log 2>&1 &
```

## 9. Report

Tell the user, briefly: the installed version, the configuration
directory, which checks passed (broker, database, readings stored),
how it is running if you set that up, and how to stop it. Do not repeat
any password.
