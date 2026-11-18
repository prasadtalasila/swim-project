#!/usr/bin/env bash
# Export the device and reading tables to CSV and JSONL, from within the
# project's venv, and move the files to /workspace/common/data, replacing
# the previous day's. Run daily by cron:
#
#   0 23 * * * /home/user/swim-project/export_daily.sh >> /home/user/swim-project/export_daily.log 2>&1
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")" && pwd)"
DEST=/workspace/common/data

# Export into a fresh staging directory, so only this run's files are moved.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# shellcheck disable=SC1091
source "$PROJECT/.venv/bin/activate"
cd "$STAGE"
echo "$(date -Is) exporting"
swim-project export --csv --jsonl --config "$PROJECT/config.ini"
mv -f device.csv reading.csv device.jsonl reading.jsonl "$DEST"/
echo "$(date -Is) moved to $DEST"
