#!/usr/bin/env python3
"""MAD NODE STAY — the node's staying-alive kit.

The operator's feedback, point 5: "No staying-alive kit. It's a
detached process that dies when my box restarts, with no heartbeat
another agent can check. For day-and-night work I need it
supervised, and a status door that proves it's at the tip."

This is MAD STAY, cut down to one node: the same shape as
~/workspace/mad-stay/stay.py (flock single-instance, adopt a
healthy foreign copy instead of double-starting, restart within
seconds of any exit with backoff, heartbeat + status.json every
loop), supervising two children:

  * the block grader (grades Robinhood live, writes verdicts);
  * the serve door (the A2A API on 127.0.0.1:8403 — the status
    door another agent can check over HTTP).

`mad node start` starts THIS, not the grader directly. `mad node
stop` stops this, and it stops both children with it. `mad node
status` reads the status.json this writes, and the serve door
answers the same numbers over HTTP.

Stdlib only. No license, no fee, no key, no signing — the
supervisor watches processes, nothing more.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
STATUS_PATH = os.path.join(NODE_DIR, "node-stay-status.json")
HEARTBEAT_PATH = os.path.join(NODE_DIR, "node-heartbeat.json")
STAY_LOG = os.path.join(NODE_DIR, "node-stay.log")
LOCK_PATH = os.path.join(NODE_DIR, "node-stay.lock")
GRADER_LOG = os.path.join(NODE_DIR, "node.log")
SERVE_LOG = os.path.join(NODE_DIR, "node-serve.log")
VERDICTS_PATH = os.path.join(NODE_DIR, "verdicts-robinhood.jsonl")
CONFIG_PATH = os.path.join(NODE_DIR, "node-config.json")
LOOP_S = 5
RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Content-Type": "application/json"}


def log(msg):
    line = "%s [mad-node-stay] %s" % (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    try:
        with open(STAY_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _serve_config():
    cfg = {"serve_port": 8403, "serve_host": "127.0.0.1"}
    try:
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def _last_verdict():
    """Last graded block + verdict, or (None, None)."""
    try:
        last = None
        with open(VERDICTS_PATH) as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return None, None
        r = json.loads(last)
        return r.get("block"), r.get("verdict")
    except (OSError, ValueError):
        return None, None


def _tip():
    """Live chain tip, or None (a dead RPC is a dead probe, not a
    verdict — the status says so). Content-Type: application/json
    is required (the RPC 415s without it) and the default opener
    is used — the VM routes through a proxy, and a direct opener
    dies on SSL (wrong version number)."""
    try:
        data = json.dumps({"jsonrpc": "2.0", "id": 1,
                           "method": "eth_blockNumber",
                           "params": []}).encode()
        headers = dict(UA)
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(RPC_URL, data=data,
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return int(json.loads(r.read())["result"], 16)
    except Exception:
        return None


def _foreign_pid(match):
    """Pid of a running copy we did not spawn, or None."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", match],
            capture_output=True, text=True, timeout=10).stdout.split()
    except Exception:
        return None
    for tok in out:
        try:
            pid = int(tok)
        except ValueError:
            continue
        if pid != os.getpid():
            return pid
    return None


def _counts():
    n = 0
    verdicts = {"PASS": 0, "FLAG": 0}
    try:
        with open(VERDICTS_PATH) as f:
            for line in f:
                if not line.strip():
                    continue
                n += 1
                try:
                    v = json.loads(line).get("verdict")
                except ValueError:
                    continue
                if v in verdicts:
                    verdicts[v] += 1
    except OSError:
        pass
    return n, verdicts


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg["name"]
        self.proc = None
        self.adopted_pid = None
        self.restarts = 0
        self.fails = 0
        self.started_at = 0.0
        self.next_start = 0.0
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

    def _start(self):
        logf = open(self.cfg["log"], "ab")
        env = dict(os.environ)
        env["MAD_NODE_DIR"] = NODE_DIR
        self.proc = subprocess.Popen(
            self.cfg["cmd"], cwd=NODE_DIR, stdin=subprocess.DEVNULL,
            stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True, env=env)
        self.adopted_pid = None
        self.started_at = time.time()
        log("%s started, pid %d" % (self.name, self.proc.pid))

    def _kill_owned(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def step(self, now):
        if self.proc is not None and self.proc.poll() is not None:
            self.last_exit = self.proc.returncode
            lived = now - self.started_at
            self.fails = self.fails + 1 if lived < 300 else 0
            self.proc = None
            self.restarts += 1
            backoff = min(60, 5 * (2 ** min(self.fails, 3)))
            self.next_start = now + backoff
            log("%s exited rc=%s after %.0fs — restart in %ds"
                % (self.name, self.last_exit, lived, backoff))
        if self.proc is None and self.adopted_pid is not None \
                and not self.alive():
            log("%s adopted pid %d gone — taking over"
                % (self.name, self.adopted_pid))
            self.adopted_pid = None
            self.next_start = now
        if self.proc is None and self.adopted_pid is None \
                and now >= self.next_start:
            pid = _foreign_pid(self.cfg["match"])
            if pid is not None:
                self.adopted_pid = pid
                self.started_at = now
                log("%s adopted foreign pid %d (monitor only)"
                    % (self.name, pid))
            else:
                self._start()

    def status(self, now):
        return {
            "name": self.name,
            "mode": ("owned" if self.proc is not None else
                     ("adopted" if self.adopted_pid is not None
                      else "down")),
            "pid": (self.proc.pid if self.proc is not None
                    else self.adopted_pid),
            "alive": self.alive(),
            "restarts": self.restarts,
            "last_exit": self.last_exit,
            "uptime_s": int(now - self.started_at) if self.alive() else 0,
        }


def services():
    scfg = _serve_config()
    return [
        {"name": "grader",
         "cmd": [sys.executable, os.path.join(HERE, "node_grader.py"),
                 "--blocks", "1000000"],
         "log": GRADER_LOG, "match": r"node_grader\.py"},
        {"name": "serve",
         "cmd": [sys.executable, os.path.join(HERE, "node_serve.py"),
                 "--port", str(scfg["serve_port"]),
                 "--host", scfg["serve_host"]],
         "log": SERVE_LOG, "match": r"node_serve\.py"},
    ]


def main():
    os.makedirs(NODE_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another node stay already runs — stand down
    log("MAD NODE STAY up (pid %d)" % os.getpid())
    svcs = [Service(c) for c in services()]
    while True:
        now = time.time()
        for s in svcs:
            try:
                s.step(now)
            except Exception as e:  # a supervisor must not die on a bug
                log("%s step error: %r" % (s.name, e))
        try:
            last_block, last_verdict = _last_verdict()
            tip = _tip()
            total, verdicts = _counts()
            st = {
                "node": "mad-node-robinhood",
                "supervisor_pid": os.getpid(),
                "services": [s.status(now) for s in svcs],
                "grader": next((s.status(now) for s in svcs
                                if s.name == "grader"), {}),
                "serve": next((s.status(now) for s in svcs
                               if s.name == "serve"), {}),
                "blocks_graded": total,
                "verdicts": verdicts,
                "last_block": last_block,
                "last_verdict": last_verdict,
                "chain_tip": tip,
                "lag_blocks": (tip - last_block
                               if tip is not None
                               and last_block is not None else None),
                "at_tip": bool(tip is not None and last_block is not None
                               and tip - last_block <= 2),
                "ts": int(now),
            }
            with open(STATUS_PATH, "w") as f:
                json.dump(st, f)
            with open(HEARTBEAT_PATH, "w") as f:
                json.dump({"ts": int(now),
                           "supervisor_pid": os.getpid(),
                           "grader_pid": st["grader"].get("pid"),
                           "grader_alive": st["grader"].get("alive"),
                           "serve_pid": st["serve"].get("pid"),
                           "serve_alive": st["serve"].get("alive"),
                           "last_block": last_block,
                           "chain_tip": tip,
                           "lag_blocks": st["lag_blocks"],
                           "at_tip": st["at_tip"]}, f)
        except OSError:
            pass
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
