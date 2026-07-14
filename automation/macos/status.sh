#!/bin/bash
set -euo pipefail

# Reports the status of both Prayonit launch agents without modifying anything.

PROJECT_DIR="/Users/davidtischler/Developer/prayonit_social_automation"

MORNING_LABEL="com.nextwavestudios.prayonit.morning"
EVENING_LABEL="com.nextwavestudios.prayonit.evening"

UID_NUM="$(id -u)"

echo "=== Launch agent status ==="
for LABEL in "$MORNING_LABEL" "$EVENING_LABEL"; do
  echo ""
  echo "--- ${LABEL} ---"
  if launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
    echo "Loaded: yes"
    launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | grep -E "state|program|last exit" || true
  else
    echo "Loaded: no"
  fi
done

echo ""
echo "=== Configured schedules (from plist files) ==="
echo "morning: 07:15 local time (Buffer posts scheduled for 08:00)"
echo "evening: 18:15 local time (Buffer posts scheduled for 19:00)"

echo ""
echo "=== Last 30 lines: logs/automation.log ==="
if [[ -f "$PROJECT_DIR/logs/automation.log" ]]; then
  tail -n 30 "$PROJECT_DIR/logs/automation.log"
else
  echo "(no log file yet)"
fi

echo ""
echo "=== Last 30 lines: logs/automation-error.log ==="
if [[ -f "$PROJECT_DIR/logs/automation-error.log" ]]; then
  tail -n 30 "$PROJECT_DIR/logs/automation-error.log"
else
  echo "(no error log file yet)"
fi
