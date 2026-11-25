#!/usr/bin/env python3
"""NODE SENTINEL — the node's watcher of the watcher (0.1.8).

Cut down from the sentinel on MAD's own stack (Journal #048):
a tiny plain process that checks two heartbeats every 30
seconds and restarts what fell, with no agent, no tool call,
and no approval anywhere in its life.

Wards (each judged by its own heartbeat, never by a pid alone):

  * the supervisor — node-stay-status.json is rewritten every
    few seconds by node_stay.py; stale > 120s means the
    supervisor fell, so the sentinel respawns it detached
    (orphan-to-init, via node_hold.spawn_detached). The
    supervisor's own flock makes a double start impossible:
    the second copy stands down.
  * the hold recorder — the last line of node-hold-log.jsonl
    is its heartbeat; stale > 300s means the witness fell, so
    the sentinel respawns it the same way.

Every restart is re-checked against a fresh heartbeat read in
the same breath, and every ward carries a cooldown so a slow
beat can never spawn duplicates. Before any respawn the
sentinel also checks for a live process (exact script name +
node-dir cwd): a cold start can make a heartbeat look dead
while the process is still booting, and a spawn then stands
down on the flock but burns the cooldown and delays a real
restart — the 0.1.8 isolation drill caught exactly that, so a
live copy means watch, never spawn. A live copy still silent
past 3x its stale line is wedged: it is the kit's own
component, so the sentinel terminates that exact pid and
respawns (the supervisor's children live in their own
sessions and are adopted by the successor). The sentinel
writes its own heartbeat (node-sentinel-heartbeat.txt) every
cycle and logs every act to node-sentinel.log. A flock
guarantees one sentinel. Thresholds can be shortened for
drills/tests via MAD_NODE_HOLD_STALE_S /
MAD_NODE_HOLD_RECORDER_STALE_S — the mechanics are identical
at any threshold.

node_stay.py starts the sentinel; the sentinel brings
node_stay.py back. Neither holds a key or moves a fund.
Stdlib only.
"""
import fcntl
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import node_hold  # noqa: E402

NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
STATUS_PATH = os.path.join(NODE_DIR, "node-stay-status.json")
HOLD_LOG = os.path.join(NODE_DIR, "node-hold-log.jsonl")
LOG_PATH = os.path.join(NODE_DIR, "node-sentinel.log")
LOCK_PATH = os.path.join(NODE_DIR, "node-sentinel.lock")
PID_PATH = os.path.join(NODE_DIR, "node-sentinel.pid")
HEARTBEAT_PATH = os.path.join(NODE_DIR, "node-sentinel-heartbeat.txt")
STAY_SCRIPT = "node_stay.py"
RECORDER_SCRIPT = "node_hold_recorder.py"
STAY_OUT = os.path.join(NODE_DIR, "node-stay.log")
RECORDER_OUT = os.path.join(NODE_DIR, "node-hold-recorder.out")

CYCLE_S = 30
STAY_STALE_S = int(os.environ.get("MAD_NODE_HOLD_STALE_S", "120"))
STAY_COOLDOWN_S = 180
RECORDER_STALE_S = int(os.environ.get(
    "MAD_NODE_HOLD_RECORDER_STALE_S", "300"))
RECORDER_COOLDOWN_S = 600


def log(msg):
    line = "%s [node-sentinel] %s" % (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def status_ts():
    try:
        with open(STATUS_PATH) as f:
            return float(json.load(f)["ts"])
    except (OSError, ValueError, KeyError):
        return None


def hold_log_ts():
    """Ts of the recorder's newest line, or None."""
    try:
        last = None
        with open(HOLD_LOG) as f:
            for line in f:
                if line.strip():
                    last = line
        if last is None:
            return None
        return float(json.loads(last)["ts"])
    except (OSError, ValueError, KeyError):
        return None


class Ward:
    def __init__(self, name, stale_s, cooldown_s):
        self.name = name
        self.stale_s = stale_s
        self.cooldown_s = cooldown_s
        self.last_restart = 0.0
        self.was_stale = False
        self.age = 0.0

    def due(self, now):
        return now - self.last_restart >= self.cooldown_s


def _env():
    env = dict(os.environ)
    env["MAD_NODE_DIR"] = NODE_DIR
    return env


def _respawn(ward, script, out_path, now):
    """Respawn a ward's process detached (orphan-to-init) —
    unless a live copy already runs from the node dir. A live
    copy with a stale heartbeat is booting or slow: watch, and
    never burn the cooldown on it. A live copy still silent
    past 3x the stale line is wedged; it is the kit's own
    component, so terminate that exact pid first."""
    live = node_hold.foreign_pid(script, NODE_DIR)
    if live is not None:
        if ward.age == float("inf") or ward.age <= ward.stale_s * 3:
            # No heartbeat yet (a cold start still booting) or a
            # heartbeat only just stale: the process is alive —
            # watch, never spawn over it, never burn the cooldown.
            log("%s ward: %s pid %d alive, heartbeat stale — "
                "watching, no spawn" % (ward.name, script, live))
            return
        try:
            os.kill(live, signal.SIGTERM)
            log("%s ward: wedged %s pid %d terminated"
                % (ward.name, script, live))
        except OSError:
            pass
    pid = node_hold.spawn_detached(
        [sys.executable, os.path.join(HERE, script)], NODE_DIR,
        out_path, env=_env())
    ward.last_restart = now
    log("%s ward: %s respawned detached, pid %s"
        % (ward.name, script, pid))


def cycle(now, wards):
    stay, recorder = wards

    # --- the supervisor: status.json freshness ---
    ts = status_ts()
    age = (now - ts) if ts is not None else float("inf")
    stay.age = age
    if age > STAY_STALE_S:
        if not stay.was_stale:
            log("supervisor ward: status stale (age %s) — watching"
                % ("inf" if age == float("inf") else "%.0fs" % age))
            stay.was_stale = True
        if stay.due(now):
            # re-check in the same breath: never restart on a
            # heartbeat that just refreshed
            ts2 = status_ts()
            if ts2 is None or now - ts2 > STAY_STALE_S:
                _respawn(stay, STAY_SCRIPT, STAY_OUT, now)
    else:
        stay.was_stale = False

    # --- the hold recorder: hold-log freshness ---
    ts = hold_log_ts()
    age = (now - ts) if ts is not None else float("inf")
    recorder.age = age
    if age > RECORDER_STALE_S:
        if not recorder.was_stale:
            log("recorder ward: hold log stale (age %s) — watching"
                % ("inf" if age == float("inf") else "%.0fs" % age))
            recorder.was_stale = True
        if recorder.due(now):
            ts2 = hold_log_ts()
            if ts2 is None or now - ts2 > RECORDER_STALE_S:
                _respawn(recorder, RECORDER_SCRIPT, RECORDER_OUT, now)
    else:
        recorder.was_stale = False


def main():
    os.makedirs(NODE_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # a sentinel already stands — never run two
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    log("sentinel up (pid %d) — wards: supervisor (>%ds), "
        "recorder (>%ds)" % (os.getpid(), STAY_STALE_S,
                             RECORDER_STALE_S))
    wards = (Ward("supervisor", STAY_STALE_S, STAY_COOLDOWN_S),
             Ward("recorder", RECORDER_STALE_S, RECORDER_COOLDOWN_S))
    while True:
        now = time.time()
        try:
            with open(HEARTBEAT_PATH, "w") as f:
                f.write(str(int(now)))
        except OSError:
            pass
        try:
            cycle(now, wards)
        except Exception as e:  # the watcher must not die on a bug
            log("cycle error: %r" % e)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
