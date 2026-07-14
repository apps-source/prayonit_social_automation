#!/bin/bash
set -euo pipefail

# Uninstalls (unloads and removes) both Prayonit launch agents.
# Does NOT delete logs, the database, project files, or generated images.

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

MORNING_LABEL="com.nextwavestudios.prayonit.morning"
EVENING_LABEL="com.nextwavestudios.prayonit.evening"

MORNING_PLIST_DEST="$LAUNCH_AGENTS_DIR/${MORNING_LABEL}.plist"
EVENING_PLIST_DEST="$LAUNCH_AGENTS_DIR/${EVENING_LABEL}.plist"

UID_NUM="$(id -u)"

echo "Unloading launch agents (safe if not currently loaded) ..."
launchctl bootout "gui/${UID_NUM}" "$MORNING_PLIST_DEST" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}" "$EVENING_PLIST_DEST" 2>/dev/null || true

echo "Removing copied plist files ..."
rm -f "$MORNING_PLIST_DEST"
rm -f "$EVENING_PLIST_DEST"

echo ""
echo "Uninstalled:"
echo "  - $MORNING_LABEL"
echo "  - $EVENING_LABEL"
echo ""
echo "Logs, the local database, project files, and generated images were left untouched."
