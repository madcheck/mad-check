#!/usr/bin/env python3
"""MAD TASK GRADER v0.1-rh1 — Robinhood Chain.

Grades an agent's on-chain TASK (one transaction) the way MAD grades
anything: against the chain, with the receipt as the evidence.

A task is one tx. The grade answers four questions, in order:
  WHEN  - the block + timestamp the task happened, and when it was graded.
  HOW   - the checks run (receipt, actor identity, census liveness,
          terms match for payments, registry touch).
  WHY   - the reason for the verdict, in one paragraph.
  STANDARD - the rule the task was measured against.

THE STANDARD (v0.1-rh1):
  A task counts when the actor is a registered ERC-8004 agent reading
  LIVE in the census, the receipt settled on chain, and — for a
  payment — the value matches the agreed terms. Identity unverified
  is INCONCLUSIVE, never a pass. A reverted receipt is a FAIL.
  MAD never grades its own tasks: MAD's wallet is in the known map
  only so the grader can SKIP it, loudly.

Identity resolves two ways, both on-chain:
  - the tx submitter (tx.from), or the value actor in a token
    Transfer log, matched against known_agents_robinhood.json
    (agentId + wallet pairs MAD has verified, with a cited source).
  - a tx into the ERC-8004 registry: the newborn agentId is read
    from the receipt's Transfer log (the C1 follow-up).

An actor in neither map is UNVERIFIED — the grade says so and stops
at INCONCLUSIVE on that axis. The grader does not guess identity.

Run with the mad-watch venv python (egress proxy lives in env):
  ~/workspace/mad-watch/venv/bin/python task_grade_robinhood.py --tx 0x...
  ~/workspace/mad-watch/venv/bin/python task_grade_robinhood.py --block 122471679
  ~/workspace/mad-watch/venv/bin/python task_grade_robinhood.py --demo
"""
import argparse
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKUP_PATH = os.path.join(HERE, "lookup.json")
KNOWN_PATH = os.path.join(HERE, "known_agents_robinhood.json")
# State (task grades) lives in the operator's home, never in the
# package dir: the .deb installs read-only, the node writes here.
NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
os.makedirs(NODE_DIR, exist_ok=True)
OUT_PATH = os.path.join(NODE_DIR, "task-grades-robinhood.jsonl")

VERSION = "0.1-rh1"
GRADER = "mad-task-grader-rh"
CHAIN = "robinhood"
CHAIN_ID = 4663
RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"  # real USDG, 6 decimals
# keccak("Transfer(address,address,uint256)")
TRANSFER_SIG = ("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4"
                "df523b3ef")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Content-Type": "application/json"}

STANDARD = (
    "A task counts when the actor is a registered ERC-8004 agent "
    "reading LIVE in the census, the receipt settled on chain, and — "
    "for a payment — the value matches the agreed terms. Identity "
    "unverified is INCONCLUSIVE, never a pass. A reverted receipt "
    "is a FAIL. MAD never grades its own tasks."
)

_SESSION = requests.Session()


def rpc_call(method, params, timeout=30):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    for attempt in range(3):
        try:
            r = _SESSION.post(RPC_URL, json=body, headers=UA, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"rpc error: {data['error']}")
            return data["result"]
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"rpc {method} failed 3 times: {last}")


def load_lookup():
    try:
        with open(LOOKUP_PATH) as f:
            data = json.load(f)
        return data.get("lookup", {}).get("robinhood", {})
    except FileNotFoundError:
        print(f"[{GRADER}] WARNING: {LOOKUP_PATH} missing — census empty.",
              flush=True)
        return {}


def load_known():
    """agentId + wallet pairs MAD has verified, each with a source.
    Returns (by_wallet, by_agentId). Self entries carry self: true."""
    try:
        with open(KNOWN_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, {}
    by_wallet, by_id = {}, {}
    for a in data.get("agents", []):
        w = str(a.get("wallet", "")).lower()
        if w.startswith("0x"):
            by_wallet[w] = a
        by_id[str(a.get("agentId"))] = a
    return by_wallet, by_id


def parse_transfer_log(log):
    """A USDG Transfer log -> (from, to, value_raw) or None."""
    topics = log.get("topics", []) or []
    if len(topics) < 3 or topics[0].lower() != TRANSFER_SIG:
        return None
    if (log.get("address") or "").lower() != USDG:
        return None
    frm = "0x" + topics[1][-40:]
    to = "0x" + topics[2][-40:]
    try:
        val = int(log.get("data", "0x0"), 16)
    except ValueError:
        val = 0
    return frm.lower(), to.lower(), val


def grade_task(tx_hash, lookup, by_wallet, agreed=None):
    """Grade one tx. `agreed` is an optional terms dict for a payment
    task: {"value_usdg": 3.0, "to": "0x...", "what": "funder rerun #9-11"}.
    Returns the grade record (also appended to task-grades jsonl)."""
    tx = rpc_call("eth_getTransactionByHash", [tx_hash])
    if tx is None:
        raise RuntimeError(f"tx not found: {tx_hash}")
    rc = rpc_call("eth_getTransactionReceipt", [tx_hash])
    block = int(tx["blockNumber"], 16)
    blk = rpc_call("eth_getBlockByNumber", [hex(block), False])
    block_ts = int(blk["timestamp"], 16)
    graded_at = int(time.time())
    submitter = (tx.get("from") or "").lower()
    to = (tx.get("to") or "").lower() if tx.get("to") else ""
    is_registry = to == REGISTRY
    is_deploy = not tx.get("to")

    # Value actor: the token Transfer log wins over the submitter
    # (a facilitator can submit for an agent; the Transfer names
    # the agent who paid). Fall back to the submitter.
    transfers = []
    actor = submitter
    actor_source = "tx.from (submitter)"
    if rc is not None:
        for log in rc.get("logs", []) or []:
            parsed = parse_transfer_log(log)
            if parsed:
                transfers.append(parsed)
    if transfers:
        actor = transfers[0][0]
        actor_source = "USDG Transfer log (value actor)"

    checks = []
    # T1 — receipt settled.
    settled = rc is not None and rc.get("status") == "0x1"
    checks.append({"check": "T1_RECEIPT_SETTLED", "pass": settled,
                   "detail": ("receipt status 1 — the task settled."
                              if settled else
                              "receipt status 0 or missing — the task "
                              "did not settle.")})
    # T2 — actor identity.
    known = by_wallet.get(actor)
    identity = "UNVERIFIED"
    agent_id = None
    census = None
    if known:
        if known.get("self"):
            identity = "SELF_SKIP"
        else:
            agent_id = known.get("agentId")
            census = lookup.get(str(agent_id), "UNGRADED")
            identity = "RESOLVED"
    checks.append({"check": "T2_ACTOR_IDENTITY", "pass": identity == "RESOLVED",
                   "detail": (f"actor {actor} is {known.get('name')} "
                              f"(ERC-8004 #{agent_id}); source: "
                              f"{known.get('source')}"
                              if identity == "RESOLVED" else
                              f"actor {actor} ({actor_source}) matches no "
                              f"verified agent wallet — identity "
                              f"unverified."
                              if identity == "UNVERIFIED" else
                              f"actor {actor} is MAD itself — skipped, "
                              f"never graded.")})
    # T3 — census liveness (only when identity resolved).
    if identity == "RESOLVED":
        checks.append({"check": "T3_CENSUS_LIVENESS",
                       "pass": census == "LIVE",
                       "detail": f"agent #{agent_id} reads {census} in "
                                 f"the census."})
    # T4 — payment terms (only when agreed terms are given).
    terms_ok = None
    if agreed and transfers:
        want_val = int(round(agreed["value_usdg"] * 1_000_000))
        want_to = agreed["to"].lower()
        got = [(f, t, v) for (f, t, v) in transfers
               if t == want_to and v == want_val]
        terms_ok = bool(got)
        checks.append({"check": "T4_PAYMENT_TERMS", "pass": terms_ok,
                       "detail": (f"{agreed['value_usdg']} USDG to "
                                  f"{want_to} — {agreed['what']}: "
                                  f"{'matched exactly.' if terms_ok else 'NOT matched.'}")})
    # T5 — registry touch (birth/activity).
    if is_registry:
        checks.append({"check": "T5_REGISTRY_TOUCH", "pass": True,
                       "detail": "tx calls the ERC-8004 registry — a "
                                 "birth or registry activity; the "
                                 "newborn agentId resolves from the "
                                 "receipt Transfer log."})

    if identity == "SELF_SKIP":
        verdict = "SKIP"
        why = ("The actor is MAD itself. MAD grades others on its "
               "rail; it never grades its own tasks into a pass.")
    elif not settled:
        verdict = "FAIL"
        why = "The receipt did not settle — the task did not happen."
    elif identity == "UNVERIFIED":
        verdict = "INCONCLUSIVE"
        why = ("The receipt settled, but the actor matches no verified "
               "agent wallet, so the task cannot be attributed to a "
               "registered agent. The task is recorded, not graded.")
    elif census != "LIVE":
        verdict = "INCONCLUSIVE"
        why = (f"The actor is {known.get('name')} (#{agent_id}), but the "
               f"agent reads {census} in the census — a task by a "
               f"non-live agent is not a counted task.")
    elif agreed and terms_ok is False:
        verdict = "FAIL"
        why = ("The receipt settled and the actor is a live agent, but "
               "the payment does not match the agreed terms.")
    else:
        verdict = "PASS"
        why = ("The actor is a registered agent reading LIVE, the "
               "receipt settled"
               + (", and the payment matches the agreed terms."
                  if agreed else ".")
               + " The task counts.")

    kind = ("registry" if is_registry else "deployment" if is_deploy
            else "payment" if transfers else "contract_call")
    record = {
        "grader": GRADER, "version": VERSION, "chain": CHAIN,
        "chainId": CHAIN_ID,
        "task": {"tx_hash": tx_hash, "block": block, "kind": kind,
                 "actor": actor, "actor_source": actor_source,
                 "agent_id": agent_id},
        "verdict": verdict,
        "when": {"block": block,
                 "block_time": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime(block_ts)),
                 "graded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime(graded_at))},
        "how": checks,
        "why": why,
        "standard": STANDARD,
        "evidence": {"tx": {"from": submitter, "to": to or None,
                            "value_wei": tx.get("value")},
                     "receipt_status": rc.get("status") if rc else None,
                     "transfers_usdg": [
                         {"from": f, "to": t, "value_usdg": v / 1_000_000}
                         for (f, t, v) in transfers],
                     "census": census,
                     "agreed_terms": agreed},
    }
    with open(OUT_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def print_grade(r):
    t = r["task"]
    print(f"\n[{GRADER}] TASK {t['tx_hash'][:14]}… block {t['block']} "
          f"({t['kind']}) — {r['verdict']}")
    print(f"  WHEN: block {r['when']['block']} at "
          f"{r['when']['block_time']}, graded {r['when']['graded_at']}")
    print(f"  STANDARD: {r['standard']}")
    for c in r["how"]:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  HOW [{mark}] {c['check']}: {c['detail']}")
    print(f"  WHY: {r['why']}")
    print(f"  EVIDENCE: {json.dumps(r['evidence'])}")


def grade_block_tasks(block_number, lookup, by_wallet):
    """Grade every task (tx) in one block, after grading the block
    itself with the node's own block grader. Returns (block_record,
    [task_records])."""
    from node_grader import grade_block, load_flagged
    blk = rpc_call("eth_getBlockByNumber", [hex(block_number), True])
    if blk is None:
        raise RuntimeError(f"block not out yet: {block_number}")
    flagged = load_flagged()
    verdict, findings, queue_items, stats = grade_block(blk, flagged)
    block_record = {"block": block_number, "verdict": verdict,
                    "findings": findings, "tx_count": stats["tx_count"]}
    print(f"[{GRADER}] BLOCK {block_number} {verdict} "
          f"txs={stats['tx_count']} findings={len(findings)}")
    for fnd in findings:
        print(f"[{GRADER}]   {fnd['check']} [{fnd['severity']}] "
              f"{fnd['evidence'].get('tx_hash', '')}")
    records = []
    for tx in blk.get("transactions", []) or []:
        try:
            r = grade_task(tx["hash"], lookup, by_wallet)
        except Exception as e:  # noqa: BLE001 - one bad task never
            # blocks the rest of the block.
            print(f"[{GRADER}] task {tx['hash'][:14]}… ERROR: {e}",
                  flush=True)
            continue
        print_grade(r)
        records.append(r)
    return block_record, records


def main():
    ap = argparse.ArgumentParser(description="MAD Task Grader v0.1-rh1 (Robinhood)")
    ap.add_argument("--tx", default=None, help="grade one task by tx hash")
    ap.add_argument("--block", type=int, default=None,
                    help="grade every task in one block (block first)")
    ap.add_argument("--demo", action="store_true",
                    help="end-to-end: live tip block churn + MVA payment task")
    args = ap.parse_args()
    lookup = load_lookup()
    by_wallet, _ = load_known()
    print(f"[{GRADER}] v{VERSION}: census robinhood "
          f"{len(lookup)} agents; known wallets {len(by_wallet)}",
          flush=True)
    if args.demo:
        tip = int(rpc_call("eth_blockNumber", []), 16)
        print(f"[{GRADER}] DEMO — live tip block {tip}", flush=True)
        grade_block_tasks(tip, lookup, by_wallet)
        print(f"\n[{GRADER}] DEMO — known-actor task: MVA's 3 USDG "
              f"payment for the #9-11 rerun", flush=True)
        r = grade_task(
            "0x6aa418c7fc61c3fb0fde966810bd1b3a4100ba8f629319817dda55cf4be5c1f4",
            lookup, by_wallet,
            agreed={"value_usdg": 3.0,
                    "to": "0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B",
                    "what": "funder rerun #9-11, agreed price 3 USDG"})
        print_grade(r)
        return
    if args.tx:
        print_grade(grade_task(args.tx, lookup, by_wallet))
        return
    if args.block is not None:
        grade_block_tasks(args.block, lookup, by_wallet)
        return
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
