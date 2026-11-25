#!/usr/bin/env python3
"""NODE HOLD — the shared mechanics of the node's hold kit (0.1.8).

The hold layer was built and proven on MAD's own stack first
(2026-11-25, Journal #048): a supervisor that health-checks by
DOOR-ANSWER (a real HTTP probe demanding the ok body — a live pid
is not proof of life), a sentinel that watches the supervisor, an
uptime recorder that keeps the receipt, and one restart shape
that actually survives the restarter.

This module is the kit's toolbox, imported by node_stay.py,
node_sentinel.py and node_hold_recorder.py:

  * spawn_detached() — the orphan-to-init restart form. A daemon
    started by a worker dies with the worker's process group
    unless the process that launches it lets go in the same
    instant. Two drills on MAD's own stack proved it (Journal
    #048, addendum): plain nohup and plain setsid both died with
    the starting run; the subshell-that-exits form —
    `(setsid nohup <cmd> &)` — left the daemon parented to PID 1
    from its first breath, and it stayed. spawn_detached() is
    that shape in Python: an intermediate child calls setsid,
    spawns the daemon in its own session, reports the pid back
    through a pipe, and exits immediately. Verify afterwards by
    reading files, never by holding the child.

  * door_probe() — a real HTTP GET through a proxy-bypassing
    opener, up only on a 200 whose body carries the needle.

  * foreign_pid() — adoption matching, exact: one argv element
    whose basename is exactly the script name AND the process's
    cwd is the service's own directory. A substring match once
    adopted a test server as the production API (2026-11-25);
    the kit never kills an adopted copy — that rule lives in
    node_stay.py, this is only the finder.

Stdlib only. The kit watches processes and answers doors; it
never holds a key, never signs, never moves funds.
"""
import os
import subprocess
import time
import urllib.request

_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def spawn_detached(argv, cwd, out_path, env=None):
    """Spawn argv as a daemon orphaned to init; return its pid.

    The intermediate child exits in the same instant it spawns
    the daemon, so nothing that started the daemon stays alive
    as its parent — the lesson two failed drills taught. The
    caller verifies by file reads afterwards, never by waiting
    on the daemon itself.
    """
    r, w = os.pipe()
    pid = os.fork()
    if pid > 0:
        os.close(w)
        data = b""
        try:
            while True:
                chunk = os.read(r, 64)
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(r)
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        try:
            return int(data.decode("utf-8", "replace").strip())
        except ValueError:
            return None
    # Intermediate child: new session, spawn, report, exit — now.
    try:
        os.close(r)
        os.setsid()
        out = open(out_path, "ab")
        p = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True)
        os.write(w, str(p.pid).encode())
    except Exception:
        pass
    finally:
        try:
            os.close(w)
        except OSError:
            pass
        os._exit(0)


def door_probe(url, needle, timeout=4):
    """(up, latency_ms): a real GET of the door, up only on a
    200 whose body carries the needle."""
    t0 = time.time()
    up = False
    try:
        with _direct.open(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            up = r.status == 200 and needle in body
    except Exception:
        up = False
    return up, (time.time() - t0) * 1000.0


def foreign_pid(match, cwd):
    """Pid of a running copy we did not spawn, or None.

    Exact, never a substring: one argv element's basename must
    be exactly `match`, and the process must run from `cwd`.
    A substring match adopted a stranger as the service once;
    a cwd match keeps a test copy or a drill instance on
    another directory from being adopted as the real one.
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


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def read_pid(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_epoch(path):
    """Epoch seconds from a heartbeat file, or None."""
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None
