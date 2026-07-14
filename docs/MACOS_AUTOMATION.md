# macOS Automation (launchd)

This adds optional local scheduling via macOS `launchd`, running
`prayonit_social.py` automatically 45 minutes before each Buffer posting
time (Buffer posts are scheduled for 8:00 AM and 7:00 PM; launchd triggers
at 7:15 AM and 6:15 PM local time).

Nothing here is loaded or run automatically — you must explicitly run the
setup commands below.

## Files

```
automation/macos/run_prayonit.sh                                shell runner invoked by launchd
automation/macos/com.nextwavestudios.prayonit.morning.plist      7:15 AM agent
automation/macos/com.nextwavestudios.prayonit.evening.plist      6:15 PM agent
automation/macos/install.sh                                      copy + load both agents
automation/macos/uninstall.sh                                    unload + remove both agents
automation/macos/status.sh                                       show load state + recent logs
automation/macos/test.sh                                         validate + one safe dry run
```

## One-time setup

```bash
chmod +x automation/macos/*.sh
```

## Commands

```bash
automation/macos/test.sh        # validates syntax + plists, runs ONE dry run (TEST_MODE only)
automation/macos/install.sh     # copies plists to ~/Library/LaunchAgents and loads them
automation/macos/status.sh      # shows whether agents are loaded + recent log tails
automation/macos/uninstall.sh   # unloads agents and removes the copied plist files only
```

## Important notes

- **`TEST_MODE` must stay `true` while setting this up.** `test.sh` refuses
  to run at all if `TEST_MODE` is not `true` in `.env`.
- **The Mac must be powered on** at the scheduled time for launchd to fire.
- **If the Mac is asleep**, launchd will typically run the job shortly after
  wake, not necessarily exactly on schedule.
- **Logs** are written to:
  - `logs/automation.log` / `logs/automation-error.log` (from `run_prayonit.sh`)
  - `logs/launchd-output.log` / `logs/launchd-error.log` (from launchd itself)
- **To pause automation**, run `automation/macos/uninstall.sh`. This only
  unloads the two agents and deletes their copied plist files from
  `~/Library/LaunchAgents` — it never touches logs, the database, project
  files, or generated images.
- **To reinstall**, run `automation/macos/install.sh` again — it safely
  unloads any prior copy first, then reloads fresh.
- **To verify the exact Python interpreter** being used, run:
  ```bash
  /Users/davidtischler/Developer/prayonit_social_automation/.venv/bin/python --version
  /Users/davidtischler/Developer/prayonit_social_automation/.venv/bin/python -c "import sys; print(sys.executable)"
  ```
- **To check launchctl status directly:**
  ```bash
  launchctl print gui/$(id -u)/com.nextwavestudios.prayonit.morning
  launchctl print gui/$(id -u)/com.nextwavestudios.prayonit.evening
  ```
  (or just run `automation/macos/status.sh`, which wraps this.)
- **To manually trigger each agent safely** (only after `install.sh` has
  loaded them, and only when you intend a real run):
  ```bash
  launchctl kickstart gui/$(id -u)/com.nextwavestudios.prayonit.morning
  launchctl kickstart gui/$(id -u)/com.nextwavestudios.prayonit.evening
  ```
  This executes the same `run_prayonit.sh` script the schedule would use —
  keep `TEST_MODE=true` if you just want to verify behavior without
  publishing anything.

## What `run_prayonit.sh` does

- Validates the slot argument is exactly `morning` or `evening`, exiting
  with a clear error otherwise.
- Creates `logs/` if missing.
- Runs `.venv/bin/python prayonit_social.py --slot "$1"`, appending stdout
  to `logs/automation.log` and stderr to `logs/automation-error.log`, each
  with a timestamp header/footer.
- Never prints or logs secrets — it only forwards the slot argument; any
  secret values live in `.env` and are read directly by the Python process,
  not by this shell script.
