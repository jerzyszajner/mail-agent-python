#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.jerzy.mail-agent"
PLIST_SRC="$ROOT/launchd/${LABEL}.plist"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ ! -f "$PLIST_SRC" ]]; then
	echo "Missing $PLIST_SRC" >&2
	exit 1
fi
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
	echo "No venv at $ROOT/venv — run: python -m venv venv && pip install -r requirements.txt" >&2
	exit 1
fi

mkdir -p "$ROOT/logs"
cp "$PLIST_SRC" "$DEST"
chmod 644 "$DEST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"

echo "LaunchAgent loaded: $LABEL"
echo "Logs: $ROOT/logs/launchd-out.log / launchd-err.log"
echo "Unload: launchctl bootout gui/$(id -u)/$LABEL"
