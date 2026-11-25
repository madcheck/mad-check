#!/usr/bin/env python3
"""NODE HOLD RECORDER — the node's uptime witness (0.1.8).

Cut down from the recorder on MAD's own stack (Journal #048):
every 30 seconds it probes the node's services and appends one
JSON line per service to node-hold-log.jsonl in the node dir:

    {"ts": <epoch>, "service": <name>, "up": <bool>,
     "latency_ms": <float>}

Probes are door-first, the lesson learned the hard way (a live
pid once masked a dead API):

  * serve — a real HTTP GET of the serve door's status URL, up
    only on a 200 whose body carries the node needle;
  * grader and supervisor have no listening port by design, so
    the probe is process-alive: the pid the supervisor records
    in node-stay-status.json must answer os.kill(pid, 0), and a
    pid the supervisor itself calls dead counts as down even if
    a same-numbered stranger now holds it.

Plain process, stdlib only. A flock guarantees exactly one
recorder. Read the numbers back with `--stats` (also what
`mad node hold` runs): uptime %, down events, longest outage,
mean recovery, over the last 1h / 24h / all-time.
"""
import fcntl
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import node_hold  # noqa: E402

NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
STATUS_PATH = os.path.join(NODE_DIR, "node-stay-status.json")
LOG_PATH = os.path.join(NODE_DIR, "node-hold-log.jsonl")
LOCK_PATH = os.path.join(NODE_DIR, "node-hold-recorder.lock")
PID_PATH = os.path.join(NODE_DIR, "node-hold-recorder.pid")
CONFIG_PATH = os.path.join(NODE_DIR, "node-config.json")
INTERVAL_S = 30
SERVICES = ["supervisor", "grader", "serve"]


def _serve_url():
    host, port = "127.0.0.1", 8403
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        host = cfg.get("serve_host", host)
        port = cfg.get("serve_port", port)
    except (OSError, ValueError):
        pass
    return "http://%s:%s/v1/node/status" % (host, port)


def read_status():
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def probe_round():
    status = read_status() or {}
    lines = []
    for name in SERVICES:
        ts = time.time()
        if name == "serve":
            up, latency_ms = node_hold.door_probe(
                _serve_url(), '"mad-node-robinhood"', timeout=5)
        elif name == "supervisor":
            up, latency_ms = node_hold.pid_alive(
                status.get("supervisor_pid")), 0.0
        else:  # grader
            entry = status.get("grader") or {}
            up = node_hold.pid_alive(entry.get("pid"))
            if entry.get("alive") is False:
                up = False
            latency_ms = 0.0
        lines.append({
            "ts": round(ts, 3),
            "service": name,
            "up": bool(up),
            "latency_ms": round(latency_ms, 2),
        })
    with open(LOG_PATH, "a") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def main():
    os.makedirs(NODE_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # a recorder already runs — never run two
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    while True:
        try:
            probe_round()
        except Exception:
            pass  # the witness must not die on a bad round
        time.sleep(INTERVAL_S)


# ---------------------------------------------------------------- stats
WINDOWS = [("last 1h", 3600), ("last 24h", 86400), ("all-time", None)]


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    rows.sort(key=lambda r: r["ts"])
    return rows


def service_stats(rows):
    """rows: one service's records, ts-ascending."""
    total = len(rows)
    ups = sum(1 for r in rows if r["up"])
    uptime = (100.0 * ups / total) if total else 0.0
    events = []  # (duration_s, closed?)
    i = 0
    while i < total:
        if rows[i]["up"]:
            i += 1
            continue
        j = i
        while j < total and not rows[j]["up"]:
            j += 1
        if j < total:
            events.append((rows[j]["ts"] - rows[i]["ts"], True))
        else:
            events.append((rows[-1]["ts"] - rows[i]["ts"], False))
        i = j
    closed = [d for d, c in events if c]
    longest = max((d for d, _ in events), default=0.0)
    longest_open = any(not c and d == longest for d, c in events)
    mean_rec = (sum(closed) / len(closed)) if closed else 0.0
    return {
        "probes": total,
        "uptime_pct": uptime,
        "down_events": len(events),
        "longest_outage_s": longest,
        "longest_ongoing": longest_open and bool(events),
        "mean_recovery_s": mean_rec,
    }


def fmt_dur(s):
    if s < 90:
        return "%.0fs" % s
    if s < 5400:
        return "%.1fm" % (s / 60.0)
    return "%.2fh" % (s / 3600.0)


def stats_main():
    if not os.path.exists(LOG_PATH):
        print("no hold log at %s — is the node running?" % LOG_PATH)
        return 1
    rows = load(LOG_PATH)
    if not rows:
        print("hold log is empty")
        return 1
    t_end = rows[-1]["ts"]

    def tstr(ts):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

    services = sorted({r["service"] for r in rows})
    print("hold log: %d probes, %s .. %s" % (
        len(rows), tstr(rows[0]["ts"]), tstr(t_end)))
    for label, span in WINDOWS:
        print("\n== %s ==" % label)
        print("%-12s %8s %8s %9s %11s %11s" % (
            "service", "probes", "uptime", "down evts",
            "longest out", "mean recov"))
        for name in services:
            sub = [r for r in rows if r["service"] == name
                   and (span is None or r["ts"] >= t_end - span)]
            if not sub:
                print("%-12s %8s" % (name, "—"))
                continue
            st = service_stats(sub)
            longest = fmt_dur(st["longest_outage_s"])
            if st["longest_ongoing"] and st["down_events"]:
                longest += "*"
            print("%-12s %8d %7.2f%% %9d %11s %11s" % (
                name, st["probes"], st["uptime_pct"],
                st["down_events"], longest,
                fmt_dur(st["mean_recovery_s"])))
    print("\n(* = outage still open at the log's end)")
    return 0


if __name__ == "__main__":
    if "--stats" in sys.argv:
        sys.exit(stats_main())
    main()
