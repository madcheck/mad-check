# MAD STAY

The supervisor that stays. Keeps the Mad Check API and MAD WATCH alive
on a VM that gets replaced every couple of hours.

- `stay.py` — the supervisor (stdlib only). Runs server.py and watch.py
  as children; restarts either within seconds of any exit; health-probes
  the API and restarts it if it wedges (60s grace after each start —
  the API loads a 99k-record feed before it can answer); adopts a
  healthy foreign copy instead of double-starting; flock single
  instance. Full story in its docstring.
- `guard.sh` — fired by the `mad-stay-guard` cron every 5 minutes:
  starts stay.py if it is not running, silent otherwise.
- `status.json` — rewritten every 5s: per-service mode (owned/adopted),
  pid, alive, restarts, last exit. Read this before believing any
  watchdog.
- `stay.log` — the supervisor's own log.
- systemd user units for both services also exist in
  `~/.config/systemd/user/` (written for the day this runtime's user
  manager can start — its runtime-dir helper cannot reach a system bus
  today, verified 2026-11-22). They are NOT enabled, on purpose:
  if that manager ever wakes up, enabling them then is a deliberate act,
  so nothing ever double-starts.

Journal of Completion entry: #006 (2026-11-22).
