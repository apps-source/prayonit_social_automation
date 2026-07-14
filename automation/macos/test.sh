#!/bin/bash
set -euo pipefail

# Validates the automation setup WITHOUT loading launch agents or publishing
# anything. Only runs while TEST_MODE=true in .env.
#
# Checks performed:
#   1. Shell syntax check of run_prayonit.sh (bash -n)
#   2. plutil validation of both plist files
#   3. A single manual dry-run invocation of the morning slot (TEST_MODE only)

PROJECT_DIR="/Users/davidtischler/Developer/prayonit_social_automation"
AUTOMATION_DIR="$PROJECT_DIR/automation/macos"
ENV_FILE="$PROJECT_DIR/.env"

echo "=== Checking TEST_MODE ==="
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

TEST_MODE_VALUE="$(grep -E '^TEST_MODE=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2 | tr -d '[:space:]')"

if [[ "$TEST_MODE_VALUE" != "true" ]]; then
  echo "ERROR: TEST_MODE is not 'true' (found: '${TEST_MODE_VALUE}')." >&2
  echo "Refusing to run test.sh unless TEST_MODE=true. This never publishes anything." >&2
  exit 1
fi
echo "TEST_MODE=true confirmed."

echo ""
echo "=== Shell syntax check: run_prayonit.sh ==="
bash -n "$AUTOMATION_DIR/run_prayonit.sh"
echo "OK: run_prayonit.sh syntax is valid."

echo ""
echo "=== plutil validation: plist files ==="
plutil -lint "$AUTOMATION_DIR/com.nextwavestudios.prayonit.morning.plist"
plutil -lint "$AUTOMATION_DIR/com.nextwavestudios.prayonit.evening.plist"

echo ""
echo "=== Manual dry run: morning slot (TEST_MODE=true, no publishing) ==="
"$AUTOMATION_DIR/run_prayonit.sh" morning

echo ""
echo "=== test.sh complete ==="
echo "No launch agents were loaded. Nothing was published."
