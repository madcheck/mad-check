#!/usr/bin/env python3
"""NODE DRILL — the hold kit's kill drill (0.1.8).

An operator command: `mad node drill`. It kills the node's own
serve door — by its exact pid, read from the supervisor's
status — and times the hold bringing it back: the supervisor
sees the exit, restarts the door, and the door answers again.
The drill prints the recovery time and files a DRILL RECEIPT
on the node's public tape (node-tape.jsonl, hash-chained),
signed by the operator's ERC-8004 key when one is configured.

The drill is FREE, by doctrine (founder, 2026-11-25): the
drill is proof, and proof is the free look. It is never gated
behind a payment, and it runs for any operator whose node is
up — running another node feature in parallel is the normal
case, not a condition.

The signed receipt is the anti-clone binding in miniature: a
clone can copy this code, but it arrives with no operator
identity, no tape history, and no standing. The receipt
carries the operator's signature over its own hash and names
the tape's last witness anchor — the point where this node's
record was last tied to MAD's witness ledger. On the tape it
is stored as the "receipt" object of a drill entry, byte-
identical to what was signed, so any third agent can pull it
out and verify it with node_tape.verify_signed_verdict —
nothing but the record is needed. Without a configured key
the receipt is filed unsigned and says so; an unsigned
receipt is a local record, not a proof.

Safety: the drill kills ONLY the serve door pid the supervisor
itself reports, after re-verifying that pid's command line is
this package's node_serve.py. It never touches the grader,
the supervisor, the sentinel, or the recorder, and never any
process outside the node dir. If the door does not answer
again within 180 seconds the receipt records FAIL — the drill
reports the hold's failure, it never covers for it.

Stdlib only. Prints human lines, then one JSON summary line.
"""
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import node_hold  # noqa: E402
import node_tape  # noqa: E402
import signing  # noqa: E402

NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
STATUS_PATH = os.path.join(NODE_DIR, "node-stay-status.json")
CONFIG_PATH = os.path.join(NODE_DIR, "node-config.json")
TIMEOUT_S = 180


def read_status():
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def serve_url():
    host, port = "127.0.0.1", 8403
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        host = cfg.get("serve_host", host)
        port = cfg.get("serve_port", port)
    except (OSError, ValueError):
        pass
    return "http://%s:%s/v1/node/status" % (host, port)


def is_serve_pid(pid):
    """The pid's argv carries exactly node_serve.py — the drill
    kills the door it verified, never a number it was handed."""
    return node_hold.foreign_pid("node_serve.py", NODE_DIR) == pid


def last_anchor_seq():
    entries, _ok, _at = node_tape.read_tape(NODE_DIR)
    seq = None
    for e in entries:
        if e.get("type") == "anchor":
            seq = e.get("witness_seq")
    return seq


def main():
    st = read_status()
    if not st:
        print("drill: no supervisor status at %s — is the node "
              "running? `mad node start` first." % STATUS_PATH)
        print(json.dumps({"drill": "serve-kill", "result": "FAIL",
                          "reason": "node not running"}))
        return 1
    serve = st.get("serve") or {}
    old_pid = serve.get("pid")
    if not serve.get("alive") or not old_pid:
        print("drill: the serve door is not up — nothing to kill, "
              "nothing proven. `mad node status` shows the hold.")
        print(json.dumps({"drill": "serve-kill", "result": "FAIL",
                          "reason": "serve door not up"}))
        return 1
    if not is_serve_pid(old_pid):
        print("drill: status names serve pid %s but that pid is "
              "not this node's serve door — refusing to kill a "
              "number I cannot verify." % old_pid)
        print(json.dumps({"drill": "serve-kill", "result": "FAIL",
                          "reason": "serve pid unverifiable"}))
        return 1
    url = serve_url()
    print("drill: killing the serve door (pid %d) — the hold "
          "has to bring it back." % old_pid)
    t0 = time.time()
    os.kill(old_pid, signal.SIGTERM)
    recovery = None
    new_pid = None
    while time.time() - t0 < TIMEOUT_S:
        st2 = read_status()
        pid2 = ((st2 or {}).get("serve") or {}).get("pid")
        if pid2 and pid2 != old_pid:
            up, _lat = node_hold.door_probe(
                url, '"mad-node-robinhood"', timeout=3)
            if up:
                recovery = round(time.time() - t0, 1)
                new_pid = pid2
                break
        time.sleep(0.25)
    result = "PASS" if recovery is not None else "FAIL"
    if recovery is not None:
        print("drill: door back as pid %d in %.1fs — supervisor "
              "pid %s never blinked." % (
                  new_pid, recovery, st.get("supervisor_pid")))
    else:
        print("drill: the door did NOT come back in %ds. The "
              "hold failed, and the receipt says so." % TIMEOUT_S)
    receipt = {
        "type": "drill",
        "drill": "serve-kill",
        "kit": "hold-0.1.8",
        "result": result,
        "serve_pid_before": old_pid,
        "serve_pid_after": new_pid,
        "recovery_s": recovery,
        "supervisor_pid": st.get("supervisor_pid"),
        "last_witness_anchor_seq": last_anchor_seq(),
    }
    key = signing.load_operator_key()
    if key:
        receipt = node_tape.sign_verdict(receipt, key)
    else:
        receipt["signed"] = False
    # The signed receipt is stored as the entry's "receipt"
    # object, byte-identical to what was signed — the tape's
    # chain fields (seq, prev_hash, entry_hash) wrap it, they
    # never enter it, so the signature verifies from the tape
    # alone.
    stored = node_tape.append_tape(
        NODE_DIR, {"type": "drill", "receipt": receipt})
    print("drill: receipt on the tape — seq %s, entry %s%s." % (
        stored.get("seq"), stored.get("entry_hash", "")[:16],
        ", signed by %s" % receipt.get("signer")
        if receipt.get("signed") else ", UNSIGNED (no operator "
        "key configured — a local record, not a proof)"))
    print(json.dumps({
        "drill": "serve-kill", "result": result,
        "recovery_s": recovery, "serve_pid_before": old_pid,
        "serve_pid_after": new_pid,
        "tape_seq": stored.get("seq"),
        "entry_hash": stored.get("entry_hash"),
        "signed": bool(receipt.get("signed")),
        "signer": receipt.get("signer")}))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
