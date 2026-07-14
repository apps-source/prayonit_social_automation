#!/bin/bash
set -euo pipefail

# Installs both Prayonit launch agents for the current macOS user.
# This does NOT run the automation immediately (RunAtLoad is false in the plists).

PROJECT_DIR="/Users/davidtischler/Developer/prayonit_social_automation"
AUTOMATION_DIR="$PROJECT_DIR/automation/macos"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

MORNING_LABEL="com.nextwavestudios.prayonit.morning"
EVENING_LABEL="com.nextwavestudios.prayonit.evening"

MORNING_PLIST_SRC="$AUTOMATION_DIR/${MORNING_LABEL}.plist"
EVENING_PLIST_SRC="$AUTOMATION_DIR/${EVENING_LABEL}.plist"

MORNING_PLIST_DEST="$LAUNCH_AGENTS_DIR/${MORNING_LABEL}.plist"
EVENING_PLIST_DEST="$LAUNCH_AGENTS_DIR/${EVENING_LABEL}.plist"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

echo "Copying plist files to $LAUNCH_AGENTS_DIR ..."
cp "$MORNING_PLIST_SRC" "$MORNING_PLIST_DEST"
cp "$EVENING_PLIST_SRC" "$EVENING_PLIST_DEST"

chmod 644 "$MORNING_PLIST_DEST"
chmod 644 "$EVENING_PLIST_DEST"

UID_NUM="$(id -u)"

echo "Unloading any prior copies (safe if not currently loaded) ..."
launchctl bootout "gui/${UID_NUM}" "$MORNING_PLIST_DEST" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}" "$EVENING_PLIST_DEST" 2>/dev/null || true

echo "Loading launch agents ..."
launchctl bootstrap "gui/${UID_NUM}" "$MORNING_PLIST_DEST"
launchctl bootstrap "gui/${UID_NUM}" "$EVENING_PLIST_DEST"

echo ""
echo "Installed and loaded:"
echo "  - $MORNING_LABEL"
echo "  - $EVENING_LABEL"
echo ""
echo "Note: RunAtLoad is false, so nothing runs immediately."
echo "The agents will run at their scheduled times (7:15 AM and 6:15 PM local)."
