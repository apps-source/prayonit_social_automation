#!/bin/bash
set -euo pipefail

# Prayonit Marketing Engine - macOS launchd runner
# Usage: ./run_prayonit.sh morning
#        ./run_prayonit.sh evening
#
# This script never prints or logs secrets. It only forwards the slot
# argument to prayonit_social.py and captures stdout/stderr to log files.

PROJECT_DIR="/Users/davidtischler/Developer/prayonit_social_automation"
PYTHON_BIN="/Users/davidtischler/Developer/prayonit_social_automation/.venv/bin/python"

cd "$PROJECT_DIR"

SLOT="${1:-}"

if [[ "$SLOT" != "morning" && "$SLOT" != "evening" ]]; then
  echo "ERROR: slot must be 'morning' or 'evening' (got: '${SLOT}')" >&2
  echo "Usage: $0 morning|evening" >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/logs"

LOG_FILE="$PROJECT_DIR/logs/automation.log"
ERROR_LOG_FILE="$PROJECT_DIR/logs/automation-error.log"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

{
  echo "----- ${TIMESTAMP} : starting slot=${SLOT} -----"
} >> "$LOG_FILE"

set +e
"$PYTHON_BIN" prayonit_social.py --slot "$SLOT" >> "$LOG_FILE" 2>> "$ERROR_LOG_FILE"
EXIT_CODE=$?
set -e

FINISH_TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

if [[ $EXIT_CODE -eq 0 ]]; then
  echo "----- ${FINISH_TIMESTAMP} : slot=${SLOT} finished successfully -----" >> "$LOG_FILE"
else
  echo "----- ${FINISH_TIMESTAMP} : slot=${SLOT} FAILED (exit ${EXIT_CODE}) -----" >> "$ERROR_LOG_FILE"
fi

exit $EXIT_CODE
