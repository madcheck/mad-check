#!/usr/bin/env python3
"""MAD BLOCK GRADER v0.1 — queue worker (the slow path, AFTER the stream).

Reads queue.jsonl items the hot path enqueued and grades them with the
slow checks the stream never waits for. Runs only when invoked, never
during a live run — the queue exists precisely so the next block is
never blocked by a follow-up.

v0.1 handles one item type:
  new_registration / registry_activity — fetch the tx receipt
  (eth_getTransactionReceipt, 1 RPC call), find the ERC-8004
  Transfer log (emitter = registry, topic0 = Transfer), read the
  agentId from topic[3], and look it up in the census lookup
  (lookup.json). A newborn is absent from the census by definition:
  it reads UNGRADED — born today, grade pending — which is the
  honest answer and the exact gap Born Graded's gate closes.

Follow-up verdicts append to followups.jsonl in How / Why / Fix /
Evidence form, and the queue item is marked done in place. An item
whose receipt cannot be read after retries stays pending with its
failure recorded — never silently dropped, never faked as graded.

Usage:
  ~/workspace/mad-watch/venv/bin/python queue_worker.py --drain
  ~/workspace/mad-watch/venv/bin/python queue_worker.py --list
"""
import argparse
import json
import os
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE_PATH = os.path.join(HERE, "queue.jsonl")
FOLLOWUPS_PATH = os.path.join(HERE, "followups.jsonl")
LOOKUP_PATH = os.path.join(HERE, "lookup.json")

RPC_URL = "https://base-rpc.publicnode.com"
REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
# keccak("Transfer(address,address,uint256)") — the ERC-721 mint log.
T_TRANSFER = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4d"
              "f523b3ef")
UA = {"User-Agent": "mad-block-grader/0.1-queue (+agent verification)",
      "Content-Type": "application/json"}


def rpc_call(method, params, timeout=30):
    """One JSON-RPC POST through a keep-alive requests session — the
    transport MAD WATCH proved against this proxy (urllib died on a
    truncated full-block body in the grader's first live run)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    for attempt in range(3):
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
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"rpc {method} failed 3 times: {last}")


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
    try:
        with open(LOOKUP_PATH) as f:
            return json.load(f).get("lookup", {})
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


def process_item(item, lookup):
    """Grade one queued item. Returns a follow-up record."""
    txh = item.get("tx_hash")
    block = item.get("block")
    base = {"queue_type": item.get("type"), "block": block,
            "tx_hash": txh, "ts": int(time.time())}
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
    grade = lookup.get("base", {}).get(str(agent_id))
    if grade is None:
        return {**base, "verdict": "UNGRADED",
                "agentId": agent_id,
                "how": (f"Newborn agentId {agent_id}: the receipt's "
                        "Transfer log proves the mint, and the census "
                        "lookup holds no grade for it — it was born "
                        "after the census ran."),
                "why": ("The census is a snapshot (100,000 graded "
                        "agents, 2026-11-22). A registration from this "
                        "block cannot be in it."),
                "fix": ("Grade it now via check/agent (the live door), "
                        "and Born Graded's gate is the standing fix "
                        "for newborns that trade before they are "
                        "graded."),
                "evidence": {"agentId": agent_id,
                             "census_lookup": "absent",
                             "receipt_status": receipt.get("status")}}
    return {**base, "verdict": grade,
            "agentId": agent_id,
            "how": (f"AgentId {agent_id} resolves in the census: "
                    f"{grade}."),
            "why": "The birth re-minted an agentId the census already "
                   "graded (re-registration of a known id).",
            "fix": "Read the census grade before trusting the newborn.",
            "evidence": {"agentId": agent_id, "census_grade": grade}}


def drain():
    items = load_queue()
    pending = [it for it in items if it.get("status") == "pending"]
    print(f"[queue] {len(pending)} pending of {len(items)} total",
          flush=True)
    if not pending:
        return {"drained": 0, "done": 0, "retried": 0}
    lookup = load_lookup()
    done = 0
    retried = 0
    for item in pending:
        rec = process_item(item, lookup)
        retry = rec.pop("_retry", False)
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
            done += 1
        print(f"[queue] {item.get('tx_hash', '')[:18]}... "
              f"block {item.get('block')} -> {rec.get('verdict')}",
              flush=True)
    save_queue(items)
    return {"drained": len(pending), "done": done, "retried": retried}


def main():
    ap = argparse.ArgumentParser(description="MAD Block Grader queue")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for it in load_queue():
            print(json.dumps(it))
        return
    if args.drain:
        print(json.dumps(drain()))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
