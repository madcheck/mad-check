#!/usr/bin/env python3
"""MAD BLOCK GRADER v0.2-rh1 — queue worker (the slow path, AFTER the stream).

Reads queue-robinhood.jsonl items the hot path enqueued and grades
them with the slow checks the stream never waits for. Runs only
when invoked, never during a live run — the queue exists precisely
so the next block is never blocked by a follow-up.

v0.1.7 (this file): the 0.1.6 ship was a copy of the Base-chain
worker — wrong RPC (base-rpc.publicnode.com), wrong queue
(HERE/queue.jsonl in the package dir), and it looked newborns up
in the Base census section. Robinhood receipts read against Base
return nothing, so every item failed and stayed pending, and there
was no `mad node drain` to run it with anyway. This rewrite:
  - RPC https://rpc.mainnet.chain.robinhood.com, browser UA, the
    same 429-aware backoff the Robinhood grader runs (Journal
    #038) — a rate limit is a pause, not a death.
  - Queue + follow-ups live in the node's state dir
    (MAD_NODE_DIR, default ~/.local/share/mad-terminal/node/):
    queue-robinhood.jsonl, followups-robinhood.jsonl. The same
    file node_grader.py enqueues into. The live grader's queue
    (~/workspace/mad-block-grader/queue-robinhood.jsonl) and the
    Base queue.jsonl are never touched — _guard_paths() refuses
    to run if the resolved paths point at either.
  - Census lookup is the Robinhood section of lookup.json.
  - Follow-ups are signed with the operator key (node_tape's
    signed-verdict path, same as the grader): verdict_hash,
    signature, signer, signed. No key, no signature — the record
    lands unsigned and says so loudly, never faked as signed.
  - A resolved agentId is written back onto the queue item, so
    `mad node tape --resolve` can report the newborn's grade.

v0.1 handles one item type:
  new_registration / registry_activity — fetch the tx receipt
  (eth_getTransactionReceipt, 1 RPC call), find the ERC-8004
  Transfer log (emitter = registry, topic0 = Transfer), read the
  agentId from topic[3], and look it up in the Robinhood census
  lookup (lookup.json). A newborn is absent from the census by
  definition: it reads UNGRADED — born today, grade pending —
  which is the honest answer and the exact gap Born Graded's gate
  closes.

Follow-up verdicts append to followups-robinhood.jsonl in How /
Why / Fix / Evidence form, and the queue item is marked done in
place. An item whose receipt cannot be read after retries stays
pending with its failure recorded — never silently dropped, never
faked as graded.

Usage:
  mad node drain          grade every pending item in the node queue
  mad node drain --list   show the queue without grading it
  ~/workspace/mad-watch/venv/bin/python queue_worker.py --drain
  ~/workspace/mad-watch/venv/bin/python queue_worker.py --list
"""
import argparse
import json
import os
import time

import requests

# Chain constants: single source of truth is node_grader.py (the
# Robinhood grader this worker follows). Guarded: an old install
# without node_grader still drains against the right chain.
try:
    from node_grader import REGISTRY, RPC_URL, UA
except Exception:  # noqa: BLE001 - old install, local constants
    REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
    RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36",
          "Content-Type": "application/json"}

# Signed follow-ups: the grader's path (node_tape.sign_verdict +
# signing.load_operator_key). Guarded exactly like node_grader:
# no signing modules, no key — the worker still grades, unsigned,
# and says so loudly.
try:
    import signing as _signing
    import node_tape as _tape
    _OP_KEY = _signing.load_operator_key()
except Exception:  # noqa: BLE001 - unsigned worker still grades
    _signing = None
    _tape = None
    _OP_KEY = None

HERE = os.path.dirname(os.path.abspath(__file__))
# State (queue, follow-ups) lives in the operator's home, never in
# the package dir: the .deb installs read-only, the node writes here.
# Same resolution as node_grader.py and `mad`'s _node_dir().
NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
os.makedirs(NODE_DIR, exist_ok=True)
QUEUE_PATH = os.path.join(NODE_DIR, "queue-robinhood.jsonl")
FOLLOWUPS_PATH = os.path.join(NODE_DIR, "followups-robinhood.jsonl")
LOOKUP_PATH = os.path.join(HERE, "lookup.json")

CHAIN = "robinhood"
CHAIN_ID = 4663
# keccak("Transfer(address,address,uint256)") — the ERC-721 mint log.
T_TRANSFER = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4d"
              "f523b3ef")

# Rate-limit backoff (same ladder as node_grader v0.2-rh2, Journal
# #038): a 429 is the RPC asking for room. Fewer attempts than the
# grader's 12 — this is a one-shot drain, not a long-lived process:
# a receipt that will not come is left pending for the next drain
# instead of burning minutes on one item.
RL_BASE_S = 5.0
RL_CAP_S = 60.0
RL_MAX_ATTEMPTS = 6
RL_HARD_ATTEMPTS = 3


def _is_rate_limit(exc):
    """True when an exception is the RPC rate-limiting us."""
    s = str(exc).lower()
    return ("429" in s or "too many requests" in s
            or "rate limit" in s)


def _guard_paths():
    """Refuse to run if the resolved queue is the live grader's
    file or the old Base queue — the node drains its own queue
    and nothing else. This is the line that keeps a config slip
    from corrupting the production queue."""
    q = os.path.realpath(QUEUE_PATH)
    if "mad-block-grader" in q:
        raise RuntimeError(
            "refusing to drain the live grader's queue: %s" % q)
    if os.path.basename(q) == "queue.jsonl":
        raise RuntimeError(
            "refusing to drain the Base queue: %s" % q)


def rpc_call(method, params, timeout=30):
    """One JSON-RPC POST through a keep-alive requests session —
    the Robinhood transport (browser UA; the public RPC 403s
    anything else). 429s back off and retry; other errors get
    the old 3-attempt bounded retry, then raise."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    rl_attempts = 0
    hard_attempts = 0
    for _ in range(RL_MAX_ATTEMPTS + RL_HARD_ATTEMPTS):
        try:
            r = _SESSION.post(RPC_URL, json=body, headers=UA,
                              timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"rpc error: {data['error']}")
            return data["result"]
        except Exception as e:  # noqa: BLE001
            last = e
            if _is_rate_limit(e):
                rl_attempts += 1
                if rl_attempts > RL_MAX_ATTEMPTS:
                    break
                wait = min(RL_BASE_S * (2 ** (rl_attempts - 1)),
                           RL_CAP_S)
                print(f"[queue] rate-limited — backing off {wait:.0f}s "
                      f"(attempt {rl_attempts})", flush=True)
                time.sleep(wait)
                continue
            hard_attempts += 1
            if hard_attempts < RL_HARD_ATTEMPTS:
                time.sleep(1.0 * hard_attempts)
            else:
                break
    raise RuntimeError(f"rpc {method} failed: {last}")


_SESSION = requests.Session()


def load_queue():
    if not os.path.exists(QUEUE_PATH):
        return []
    with open(QUEUE_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_queue(items):
    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
    os.replace(tmp, QUEUE_PATH)


def load_lookup():
    """The Robinhood census section: agentId -> grade. The Base
    section is a different chain's ids — a Robinhood receipt
    resolves against Robinhood, never Base."""
    try:
        with open(LOOKUP_PATH) as f:
            return json.load(f).get("lookup", {}).get("robinhood", {})
    except FileNotFoundError:
        return {}


def agent_id_from_receipt(receipt):
    """agentId = topic[3] of the registry's Transfer log (mint: from
    the zero address). Returns None when the receipt carries no such
    log — printed as UNRESOLVED, never guessed."""
    if not receipt:
        return None
    for log in receipt.get("logs", []) or []:
        if (log.get("address", "").lower() != REGISTRY):
            continue
        topics = log.get("topics", []) or []
        if len(topics) < 4 or topics[0].lower() != T_TRANSFER:
            continue
        try:
            return int(topics[3], 16)
        except (ValueError, TypeError):
            return None
    return None


def _sign_record(rec):
    """Sign a resolved follow-up with the operator key, the
    grader's path. Returns (record, signed_bool). No key or no
    signing modules: the record lands unsigned and says so."""
    if _OP_KEY and _tape is not None:
        try:
            return _tape.sign_verdict(rec, _OP_KEY), True
        except Exception as e:  # noqa: BLE001
            print(f"[queue] WARNING: signing failed: {e}", flush=True)
    rec["signed"] = False
    return rec, False


def process_item(item, lookup):
    """Grade one queued item. Returns a follow-up record."""
    txh = item.get("tx_hash")
    block = item.get("block")
    base = {"queue_type": item.get("type"), "block": block,
            "tx_hash": txh, "ts": int(time.time()),
            "chain": CHAIN, "chainId": CHAIN_ID}
    if item.get("type") not in ("new_registration", "registry_activity"):
        return {**base, "verdict": "UNSUPPORTED",
                "how": f"Queue type {item.get('type')!r} has no worker "
                       "in v0.1.",
                "why": "The worker only resolves registry births.",
                "fix": "Add a worker leg for this type, or drop it.",
                "evidence": {}}
    try:
        receipt = rpc_call("eth_getTransactionReceipt", [txh])
    except Exception as e:  # noqa: BLE001
        return {**base, "verdict": "ERROR",
                "how": "The receipt could not be read.",
                "why": f"RPC failure: {e}",
                "fix": "Leave the item pending and retry on the next "
                       "drain — the receipt is chain fact, it will "
                       "still be there.",
                "evidence": {"error": str(e)[:200]},
                "_retry": True}
    if receipt is None:
        return {**base, "verdict": "ERROR",
                "how": "The receipt is not available yet.",
                "why": "The transaction is not yet mined or the node "
                       "has not indexed its receipt.",
                "fix": "Leave the item pending and retry on the next "
                       "drain.",
                "evidence": {},
                "_retry": True}
    agent_id = agent_id_from_receipt(receipt)
    if agent_id is None:
        return {**base, "verdict": "UNRESOLVED",
                "how": ("The receipt carries no ERC-8004 Transfer log "
                        "from the registry — no agentId to grade."),
                "why": ("The tx touched the registry without minting: "
                        "a non-register call, or a call that reverted "
                        "before minting."),
                "fix": ("No grade follows from this tx. If the call "
                        "was a register() that reverted, the revert "
                        "reason is the finding — read it from the "
                        "receipt status."),
                "evidence": {"receipt_status": receipt.get("status"),
                             "logs_in_receipt": len(
                                 receipt.get("logs", []) or [])}}
    grade = lookup.get(str(agent_id))
    if grade is None:
        return {**base, "verdict": "UNGRADED",
                "agentId": agent_id,
                "how": (f"Newborn agentId {agent_id}: the receipt's "
                        "Transfer log proves the mint, and the "
                        "Robinhood census lookup holds no grade for "
                        "it — it was born after the census ran."),
                "why": ("The census is a snapshot (100,000 graded "
                        "agents, 2026-11-22). A registration from this "
                        "block cannot be in it."),
                "fix": ("Grade it now via check/agent (the live door, "
                        "chain 4663), and Born Graded's gate is the "
                        "standing fix for newborns that trade before "
                        "they are graded."),
                "evidence": {"agentId": agent_id,
                             "census_lookup": "absent",
                             "receipt_status": receipt.get("status")}}
    return {**base, "verdict": grade,
            "agentId": agent_id,
            "how": (f"AgentId {agent_id} resolves in the Robinhood "
                    f"census: {grade}."),
            "why": "The birth re-minted an agentId the census already "
                   "graded (re-registration of a known id).",
            "fix": "Read the census grade before trusting the newborn.",
            "evidence": {"agentId": agent_id, "census_grade": grade,
                         "chain": CHAIN}}


def drain():
    _guard_paths()
    print(f"[queue] draining {QUEUE_PATH} (chain {CHAIN} "
          f"{CHAIN_ID}, RPC {RPC_URL})", flush=True)
    if not _OP_KEY or _tape is None:
        print("[queue] WARNING: no operator key — follow-ups land "
              "unsigned. `mad node key` shows where the key goes.",
              flush=True)
    items = load_queue()
    pending = [it for it in items if it.get("status") == "pending"]
    print(f"[queue] {len(pending)} pending of {len(items)} total",
          flush=True)
    if not pending:
        return {"drained": 0, "done": 0, "retried": 0, "signed": 0}
    lookup = load_lookup()
    done = 0
    retried = 0
    signed = 0
    for item in pending:
        rec = process_item(item, lookup)
        retry = rec.pop("_retry", False)
        if retry:
            rec["signed"] = False
        else:
            rec, was_signed = _sign_record(rec)
            if was_signed:
                signed += 1
        with open(FOLLOWUPS_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
        if retry:
            item["status"] = "pending"
            item["last_error_ts"] = int(time.time())
            retried += 1
        else:
            item["status"] = "done"
            item["done_ts"] = int(time.time())
            item["followup_verdict"] = rec.get("verdict")
            if rec.get("agentId") is not None:
                # The tape resolver reads agentId off the queue
                # item to report the newborn's grade.
                item["agentId"] = rec["agentId"]
            done += 1
        print(f"[queue] {item.get('tx_hash', '')[:18]}... "
              f"block {item.get('block')} -> {rec.get('verdict')}"
              f"{' (signed)' if rec.get('signed') else ''}",
              flush=True)
        # Save after every item: a kill mid-drain loses at most
        # the in-flight item, never the ones already graded.
        save_queue(items)
    summary = {"drained": len(pending), "done": done,
               "retried": retried, "signed": signed}
    print(f"[queue] drained {summary['drained']}, done "
          f"{summary['done']}, still pending {summary['retried']}, "
          f"signed {summary['signed']}", flush=True)
    print(json.dumps(summary), flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser(description="MAD Block Grader queue "
                                             "(Robinhood Chain)")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        _guard_paths()
        for it in load_queue():
            print(json.dumps(it))
        return
    if args.drain:
        drain()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
