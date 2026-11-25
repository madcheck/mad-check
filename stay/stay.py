#!/usr/bin/env python3
"""MAD STAY — the supervisor that stays.

Born 2026-11-22, the night MAD found out why the Mad Check API "died"
every ~2 hours: the VM underneath it gets replaced on that cadence and
every nohup process dies with the house. systemd user units exist on
disk but this runtime's user manager cannot start (its runtime-dir
helper cannot reach a system bus), so the supervision has to live in
user space, in the home directory, where things persist.

MAD STAY runs both long-lived MAD services as its own children:

  * mad-check-api  (~/workspace/mad-check-api/server.py, 127.0.0.1:8402)
  * mad-watch      (~/workspace/mad-watch/watch.py)

Duties:
  * restart a child within seconds of ANY exit, with backoff;
  * health-probe the API and restart it if it wedges (alive process,
    dead answers) — patiently: a 60s grace after every start, because
    the API loads a 99k-record feed before it can answer;
  * adopt a healthy foreign copy of a service instead of double-starting
    (a hand-started server.py is monitored, never duplicated);
  * write status.json every loop so any other tool (or MAD) can see the
    state of the house at a glance.

MAD STAY itself is kept alive by a 1-minute cron guard: if stay.py is
not running, the guard starts it. Cron survives VM replacement and the
home directory persists, so after every demolition the whole stack
reassembles itself within about a minute: guard -> supervisor ->
services. The watchdogs keep their alerting jobs; restarts belong to
MAD STAY now.

Stdlib only. No cost. No account. No excuses.
"""
import fcntl
import json
import os
import subprocess
import time
import urllib.request

HOME = os.path.expanduser("~")
VENV_PY = os.path.join(HOME, "workspace/mad-watch/venv/bin/python")
STAY_DIR = os.path.join(HOME, "workspace/mad-stay")
STATUS_PATH = os.path.join(STAY_DIR, "status.json")
STAY_LOG = os.path.join(STAY_DIR, "stay.log")
LOCK_PATH = os.path.join(STAY_DIR, "stay.lock")
LOOP_S = 5

CHILD_ENV = dict(
    os.environ,
    HTTPS_PROXY="http://hatch-egress-proxy:3128",
    HTTP_PROXY="http://hatch-egress-proxy:3128",
    ALL_PROXY="http://hatch-egress-proxy:3128",
    NO_PROXY="localhost,127.0.0.1,::1",
)

SERVICES = [
    {
        "name": "mad-check-api",
        "cmd": [VENV_PY, "server.py"],
        "cwd": os.path.join(HOME, "workspace/mad-check-api"),
        "log": os.path.join(HOME, "workspace/mad-check-api", "server.log"),
        "match": "server.py",
        "health_url": "http://127.0.0.1:8402/v1/health",
        "health_needle": '"status": "ok"',
        "start_grace_s": 60,
        "wedge_after": 6,  # 6 failed probes * 5s = 30s of dead answers
    },
    {
        "name": "mad-watch",
        "cmd": [VENV_PY, "watch.py"],
        "cwd": os.path.join(HOME, "workspace/mad-watch"),
        "log": os.path.join(HOME, "workspace/mad-watch", "watch.log"),
        "match": "watch.py",
        "health_url": None,
        "health_needle": None,
        "start_grace_s": 30,
        "wedge_after": None,
    },
    {
        # Live block-feed bridge: pushes the grader's verdict ring
        # buffer to PAGES KV ("live-feed") for the public SSE door.
        # No HTTP health endpoint by design (it only ever pushes);
        # STAY restarts it on exit and adopts the running copy.
        "name": "push-feed",
        "cmd": [VENV_PY, "push_feed.py"],
        "cwd": os.path.join(HOME, "workspace/mad-block-grader"),
        "log": os.path.join(HOME, "workspace/mad-block-grader",
                            "push_feed.log"),
        "match": "push_feed.py",
        "health_url": None,
        "health_needle": None,
        "start_grace_s": 30,
        "wedge_after": None,
    },
    {
        # Tokyo MAD PASS directory bridge: pushes the sweep's merged
        # state to PAGES KV ("tokyo-pass") for the public /v1/tokyo-pass
        # door and the "Tokyo City — Verified Agents" directory. No
        # HTTP health endpoint by design (it only ever pushes); STAY
        # restarts it on exit and adopts the running copy.
        # Registered 2026-11-24 for the v17 Tokyo directory.
        "name": "push-tokyo-pass",
        "cmd": [VENV_PY, "push_tokyo_pass.py"],
        "cwd": os.path.join(HOME, "workspace/mad-pass-tokyo"),
        "log": os.path.join(HOME, "workspace/mad-pass-tokyo",
                            "push_tokyo_pass.log"),
        "match": "push_tokyo_pass.py",
        "health_url": None,
        "health_needle": None,
        "start_grace_s": 30,
        "wedge_after": None,
    },
    {
        # Live block grader: grades Base blocks continuously into
        # verdicts.jsonl, which the API ring and push-feed tail.
        # It is a finite-run tool (--blocks N), so run it with a
        # huge count and let STAY restart it on exit; it resumes
        # from the last graded block in verdicts.jsonl. No HTTP
        # health endpoint by design. Registered 2026-11-24 after
        # the feed froze: run 8 had finished and nothing resumed
        # live grading after the backfill merge.
        "name": "mad-block-grader",
        "cmd": [VENV_PY, "grader.py", "--blocks", "1000000"],
        "cwd": os.path.join(HOME, "workspace/mad-block-grader"),
        "log": os.path.join(HOME, "workspace/mad-block-grader",
                            "grader-live.log"),
        "match": "grader.py",
        "health_url": None,
        "health_needle": None,
        "start_grace_s": 60,
        "wedge_after": None,
    },
    {
        # Robinhood block grader: the v0.2-rh1 port, same finite-run
        # shape as the Base grader — huge --blocks, STAY restarts on
        # exit, resumes from verdicts-robinhood.jsonl. Registered
        # 2026-11-24 as MAD's own first Robinhood node (node mode
        # 0.1.3): MAD runs it by itself and grades others on its rail.
        "name": "mad-block-grader-rh",
        "cmd": [VENV_PY, "grader_robinhood.py", "--blocks", "1000000"],
        "cwd": os.path.join(HOME, "workspace/mad-block-grader"),
        "log": os.path.join(HOME, "workspace/mad-block-grader",
                            "grader-rh-live.log"),
        "match": "grader_robinhood.py",
        "health_url": None,
        "health_needle": None,
        "start_grace_s": 60,
        "wedge_after": None,
    },
]

_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(msg):
    line = "%s [mad-stay] %s" % (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    try:
        with open(STAY_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def foreign_pid(match, cwd):
    """Pid of a running copy we did not spawn, or None.

    A match is exact, not a substring: one argv element must be
    exactly the script name, and the process must run from the
    service's own directory. A substring match adopted anything
    with the name inside it — the mirror test's site_server.py
    was adopted as the API (2026-11-25 00:05 EST) and the real
    API never started. A cwd match keeps a --local test copy or
    a selftest instance on another port from being adopted as
    the canonical service.
    """
    want_cwd = os.path.realpath(cwd)
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return None
    for tok in sorted(pids, key=int):
        pid = int(tok)
        if pid == os.getpid():
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                args = [a.decode("utf-8", "replace")
                        for a in f.read().split(b"\0") if a]
            if not any(os.path.basename(a) == match for a in args):
                continue
            if os.path.realpath("/proc/%d/cwd" % pid) != want_cwd:
                continue
        except (OSError, ValueError):
            continue
        return pid
    return None


def probe(url, needle):
    try:
        with _direct.open(url, timeout=4) as r:
            return needle in r.read().decode("utf-8", "replace")
    except Exception:
        return False


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg["name"]
        self.proc = None          # owned child (Popen) or None
        self.adopted_pid = None   # foreign pid we monitor
        self.restarts = 0
        self.fails = 0            # consecutive quick exits (backoff)
        self.started_at = 0.0
        self.next_start = 0.0
        self.health_fails = 0
        self.last_exit = None

    def alive(self):
        if self.proc is not None:
            return self.proc.poll() is None
        if self.adopted_pid is not None:
            try:
                os.kill(self.adopted_pid, 0)
                return True
            except OSError:
                return False
        return False

    def start(self):
        logf = open(self.cfg["log"], "ab")
        self.proc = subprocess.Popen(
            self.cfg["cmd"], cwd=self.cfg["cwd"], env=CHILD_ENV,
            stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        self.adopted_pid = None
        self.started_at = time.time()
        self.health_fails = 0
        log("%s started, pid %d" % (self.name, self.proc.pid))

    def kill_owned(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def step(self, now):
        # owned child exited?
        if self.proc is not None and self.proc.poll() is not None:
            self.last_exit = self.proc.returncode
            lived = now - self.started_at
            self.fails = self.fails + 1 if lived < 300 else 0
            self.proc = None
            self.restarts += 1
            backoff = min(60, 5 * (2 ** min(self.fails, 3)))
            self.next_start = now + backoff
            log("%s exited rc=%s after %.0fs — restart in %ds" % (
                self.name, self.last_exit, lived, backoff))
        # adopted copy vanished?
        if self.proc is None and self.adopted_pid is not None \
                and not self.alive():
            log("%s adopted pid %d gone — taking over" % (
                self.name, self.adopted_pid))
            self.adopted_pid = None
            self.next_start = now
        # nothing running: adopt a foreign copy or start our own
        if self.proc is None and self.adopted_pid is None \
                and now >= self.next_start:
            pid = foreign_pid(self.cfg["match"], self.cfg["cwd"])
            if pid is not None:
                self.adopted_pid = pid
                self.started_at = now
                log("%s adopted foreign pid %d (monitor only)" % (
                    self.name, pid))
            else:
                self.start()
        # health / wedge watch (API only)
        if self.cfg["health_url"] and self.alive() \
                and now - self.started_at > self.cfg["start_grace_s"]:
            if probe(self.cfg["health_url"], self.cfg["health_needle"]):
                self.health_fails = 0
            else:
                self.health_fails += 1
                if self.health_fails >= self.cfg["wedge_after"]:
                    log("%s WEDGED — %d straight failed health probes, "
                        "restarting" % (self.name, self.health_fails))
                    if self.proc is not None:
                        self.kill_owned()
                        self.health_fails = 0
                        self.next_start = now
                    else:
                        # Adopted (foreign) copy never answered this
                        # service's health URL. It is not ours to
                        # kill and not this service — the wedge kill
                        # once SIGTERMed a test API that only shared
                        # the script name. Drop the adoption and
                        # start our own now, instead of re-adopting
                        # the same foreign copy on the next step.
                        self.adopted_pid = None
                        self.health_fails = 0
                        self.next_start = now
                        self.start()
                        return

    def status(self, now):
        return {
            "name": self.name,
            "mode": "owned" if self.proc is not None else
                    ("adopted" if self.adopted_pid is not None else "down"),
            "pid": (self.proc.pid if self.proc is not None
                    else self.adopted_pid),
            "alive": self.alive(),
            "restarts": self.restarts,
            "last_exit": self.last_exit,
            "uptime_s": int(now - self.started_at) if self.alive() else 0,
            "health_fails": self.health_fails,
        }


def main():
    os.makedirs(STAY_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another MAD STAY already runs — stand down
    log("MAD STAY up (pid %d)" % os.getpid())
    svcs = [Service(c) for c in SERVICES]
    while True:
        now = time.time()
        for s in svcs:
            try:
                s.step(now)
            except Exception as e:  # a supervisor must not die on a bug
                log("%s step error: %r" % (s.name, e))
        try:
            with open(STATUS_PATH, "w") as f:
                json.dump({"ts": int(now),
                           "supervisor_pid": os.getpid(),
                           "services": [s.status(now) for s in svcs]}, f)
        except OSError:
            pass
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
