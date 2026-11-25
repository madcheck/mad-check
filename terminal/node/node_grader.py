#!/usr/bin/env python3
"""MAD BLOCK GRADER v0.2-rh1 — the Base grader (v0.2) ported to
Robinhood Chain. Same four checks (C1 registry touch, C2 deployment
info-only, C3 flagged address, C4 sender flood), same verdict record
shape plus a chain field, separate outputs
(verdicts-robinhood.jsonl / queue-robinhood.jsonl) — the Base grader's
files, processes and verdicts.jsonl are never touched.

ROBINHOOD DIFFERENCES, measured live 2026-11-24:
  - Chain 4663, ~100ms blocks, 10/sec (tip moved ~100 blocks in ~10s
    during probing). BLOCK_INTERVAL_S 0.1; the 200ms hot-path budget
    per block is kept.
  - RPC https://rpc.mainnet.chain.robinhood.com. python urllib gets
    HTTP 403 without a browser User-Agent — this port sends a browser
    UA on a keep-alive requests session (the Base grader's proven
    transport). Batch verified live: 8 full-tx blocks in 543ms
    (~68ms/block share), so catch-up drains faster than the chain
    produces.
  - ERC-8004 registry 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432 — the
    SAME address as Base; register() selector 0x32434a2e unchanged.
  - Flag list starts EMPTY (flagged_addresses_robinhood.json). The
    Base list is empty too, and no Base flag would carry to Robinhood
    without its own cited source anyway — a flag without a citation
    is a rumour, and the grader does not print rumours.
  - Lookup: the shared lookup.json (census covers Base + Robinhood);
    read-only, hot path never touches the chain.

Run with the mad-watch venv python and the full inherited env
(egress proxy lives in env; a stripped env kills TLS):
  ~/workspace/mad-watch/venv/bin/python grader_robinhood.py --blocks 50
  ~/workspace/mad-watch/venv/bin/python grader_robinhood.py --self-test
"""
import argparse
import json
import os
import sys
import time

import requests

# 0.1.6: signed verdicts + the public tape. Guarded: if the signing
# modules are missing (an old install), the grader still grades —
# unsigned, and says so loudly. The operator key is read once, from
# MAD_OPERATOR_KEY_FILE / MAD_OPERATOR_KEY / the operator-key file
# (see signing.py); no key is ever generated or written here.
try:
    import signing as _signing
    import node_tape as _tape
    _OP_KEY = _signing.load_operator_key()
except Exception:  # noqa: BLE001 - an unsigned grader still grades
    _signing = None
    _tape = None
    _OP_KEY = None

HERE = os.path.dirname(os.path.abspath(__file__))
# State (verdicts, queue) lives in the operator's home, never in the
# package dir: the .deb installs read-only, the node writes here.
NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
os.makedirs(NODE_DIR, exist_ok=True)
VERDICTS_PATH = os.path.join(NODE_DIR, "verdicts-robinhood.jsonl")
QUEUE_PATH = os.path.join(NODE_DIR, "queue-robinhood.jsonl")
LOOKUP_PATH = os.path.join(HERE, "lookup.json")
FLAGGED_PATH = os.path.join(HERE, "flagged_addresses_robinhood.json")

VERSION = "0.2-rh2"
GRADER = "mad-block-grader-rh"
CHAIN = "robinhood"
CHAIN_ID = 4663
RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
# keccak("register(address,string)")[:4] — verified live 2026-11-24
# with eth_hash against the ERC-8004 registry register() signature.
SEL_REGISTER = "0x32434a2e"
# Sender flood: more than this many txs from one address in one block.
FLOOD_THRESHOLD = 20
# Block budget: Robinhood makes a block every ~100ms (10/sec).
# The hot path must fit inside the 200ms budget per block.
BLOCK_BUDGET_MS = 200
BLOCK_INTERVAL_S = 0.1
# Batching: blocks fetched per JSON-RPC round trip. The round trip
# dominates (measured 2026-11-24, live, main grader sharing the
# RPC: 32 blocks 656ms, 64 blocks 1065ms — the payload is nearly
# free), so a bigger batch is pure throughput. 96 blocks 429s —
# the RPC rate-limits the request size, so 64 is the ceiling. At
# 32 the node graded ~9.7/sec sustained against the chain's
# 10/sec and held a steady 20-40 block lag, never the tip. At 64
# the cycle is ~2.6s for 64 blocks (~25/sec burst, ~15-20/sec
# sustained with the 0.4s gap + ~13ms signing per verdict) — a
# real margin over the chain, so the node HOLDS the tip instead
# of trailing it. (0.1.6.)
BATCH_SIZE = 64
# Catch-up: while the tip is more than this many blocks ahead of the
# next block to grade, grade batches back-to-back with no pacing.
# Within ~2 blocks the timestamp pacing below holds the tip.
CATCHUP_LAG = 10
# Pacing margin: sleep until the next batch's end block should exist,
# from the last graded block's timestamp, plus this much slack for
# block propagation and timestamp-vs-wall-clock skew.
PACE_MARGIN_S = 0.1
# Fetch lead: the batch request is sent this far BEFORE the target
# time above, because the request itself spends ~0.2-0.5s in transit
# + proxy before the server reads the tip (measured live 2026-11-24:
# without the lead, tip-mode batches landed with the tip 2-3 blocks
# past the batch end and the end lag stuck at 5). If the lead sends
# the request a block early, the null-retry grades the prefix and
# re-fetches the rest 0.1s later — cheap, never a skip.
FETCH_LEAD_S = 0.3
# Robinhood RPC 403s non-browser User-Agents (urllib default dies).
# A browser UA on the keep-alive session is the working route.
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Content-Type": "application/json"}


# ------------------------------------------------------------------ lookup --
def load_lookup():
    """The pre-computed census grades, agentId-keyed. Loaded once at
    startup; the hot path only reads the dict, never the chain.
    Returns (lookup_dict, meta). Missing file = empty lookup, printed."""
    try:
        with open(LOOKUP_PATH) as f:
            data = json.load(f)
        return data.get("lookup", {}), data.get("meta", {})
    except FileNotFoundError:
        print(f"[{GRADER}] WARNING: {LOOKUP_PATH} missing — run lookup.py "
              f"first. Lookup is empty; registry follow-ups will read "
              f"UNGRADED.", flush=True)
        return {}, {}


def load_flagged():
    """flagged_addresses.json: entries need a cited source (case file /
    filing / grade). Sourceless entries are dropped, loudly — a flag
    without a citation is a rumour, and the grader does not print
    rumours."""
    try:
        with open(FLAGGED_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[{GRADER}] WARNING: {FLAGGED_PATH} missing — flagged set "
              f"empty.", flush=True)
        return {}
    out = {}
    for entry in data.get("addresses", []):
        addr = str(entry.get("address", "")).lower()
        source = entry.get("source", "")
        reason = entry.get("reason", "")
        if not addr.startswith("0x") or len(addr) != 42:
            print(f"[{GRADER}] flagged entry dropped (bad address): "
                  f"{entry}", flush=True)
            continue
        if not source or not reason:
            print(f"[{GRADER}] flagged entry dropped (no source/reason): "
                  f"{addr}", flush=True)
            continue
        out[addr] = {"source": source, "reason": reason}
    return out


# Rate-limit backoff (v0.2-rh2, Journal #038): the Robinhood public
# RPC 429s the catch-up burst — batches back-to-back, no pacing. A
# 429 is not a bug, it is the RPC asking for room. On a 429, back off
# exponentially (5s, 10s, 20s, 40s, 60s cap) and keep retrying up to
# RL_MAX_ATTEMPTS before giving up — the process must not die on a
# rate limit, or STAY restarts it into the same burst and it dies
# again (the 2026-11-24 crash-loop: 6 restarts in ~11 min, each
# "rpc batch failed 3 times: 429 Too Many Requests"). Non-429 errors
# keep the old 3-attempt bounded retry, so a real bug still surfaces
# instead of spinning forever.
RL_BASE_S = 5.0
RL_CAP_S = 60.0
RL_MAX_ATTEMPTS = 12
# Catch-up gap: pause this long between batches while catching up,
# so the RPC is not hammered into 429s in the first place (the
# mirror's paced transport proved 400ms gaps complete Robinhood
# grades instead of ERRORing). 8 blocks per batch + 0.4s gap still
# drains ~20 blocks/sec.
CATCHUP_GAP_S = 0.4


def _is_rate_limit(exc):
    """True when an exception is the RPC rate-limiting us: HTTP 429
    from raise_for_status, or a 429 / 'too many requests' / 'rate
    limit' string in an RPC error body."""
    s = str(exc).lower()
    return ("429" in s or "too many requests" in s
            or "rate limit" in s)


# --------------------------------------------------------------------- RPC --
def rpc_call(method, params, timeout=30):
    """One JSON-RPC POST through a keep-alive requests session — the
    same transport MAD WATCH v1.2 proved against this proxy. The first
    build used urllib here and died on its first live block:
    IncompleteRead at 64,983 bytes of a full-tx block body (Journal
    #020's short-read failure, same shape). Retries keep the attempt
    count small; a second failure raises — the caller holds position
    and retries the same block, never skips forward."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    rl_attempts = 0
    hard_attempts = 0
    for _ in range(RL_MAX_ATTEMPTS):
        try:
            r = _SESSION.post(RPC_URL, json=body, headers=UA,
                              timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"rpc error: {data['error']}")
            return data["result"]
        except Exception as e:  # noqa: BLE001 - retry, then raise
            last = e
            if _is_rate_limit(e):
                # Rate limit: exponential backoff, keep going. The
                # RPC recovers; the process must not die on this.
                rl_attempts += 1
                wait = min(RL_BASE_S * (2 ** (rl_attempts - 1)), RL_CAP_S)
                print(f"[{GRADER}] rate-limited — backing off {wait:.0f}s "
                      f"(attempt {rl_attempts})", flush=True)
                time.sleep(wait)
                continue
            # Non-429: the old 3-attempt bounded retry, so a real bug
            # still surfaces instead of spinning forever.
            hard_attempts += 1
            if hard_attempts < 3:
                time.sleep(0.25 * hard_attempts)
            else:
                break
    raise RuntimeError(f"rpc {method} failed: {last}")


_SESSION = requests.Session()


def get_tip():
    return int(rpc_call("eth_blockNumber", []), 16)


def get_block(number):
    """Full block with tx objects, or None if the block is not out yet."""
    return rpc_call("eth_getBlockByNumber", [hex(number), True])


def parse_batch_results(data, count):
    """Batch response -> results in call order. Items arrive in any
    order; match by id. A null result is a block not out yet, kept as
    None. An item error raises — the caller retries the batch."""
    if not isinstance(data, list) or len(data) != count:
        raise RuntimeError(
            "rpc batch: expected %d results, got %s"
            % (count, repr(data)[:200]))
    by_id = {}
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            raise RuntimeError(
                "rpc batch: malformed item %s" % repr(item)[:200])
        by_id[item["id"]] = item
    out = []
    for i in range(1, count + 1):
        item = by_id.get(i)
        if item is None:
            raise RuntimeError(f"rpc batch: missing result id {i}")
        if "error" in item:
            raise RuntimeError(f"rpc batch item error: {item['error']}")
        out.append(item.get("result"))
    return out


def rpc_batch(calls, timeout=60):
    """One JSON-RPC batch POST through the keep-alive session: all
    calls in one round trip, results in call order. Same retry shape
    as rpc_call — 3 attempts, short backoff — then raise; the caller
    holds position and retries the same blocks, never skips."""
    body = [{"jsonrpc": "2.0", "id": i + 1, "method": m, "params": p}
            for i, (m, p) in enumerate(calls)]
    last = None
    rl_attempts = 0
    hard_attempts = 0
    for _ in range(RL_MAX_ATTEMPTS):
        try:
            r = _SESSION.post(RPC_URL, json=body, headers=UA,
                              timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"rpc batch error: {data['error']}")
            return parse_batch_results(data, len(calls))
        except Exception as e:  # noqa: BLE001 - retry, then raise
            last = e
            if _is_rate_limit(e):
                # Rate limit: exponential backoff, keep going. This
                # is the crash-loop line — the old code raised here
                # after 3 short retries and the process died.
                rl_attempts += 1
                wait = min(RL_BASE_S * (2 ** (rl_attempts - 1)), RL_CAP_S)
                print(f"[{GRADER}] rate-limited — backing off {wait:.0f}s "
                      f"(attempt {rl_attempts})", flush=True)
                time.sleep(wait)
                continue
            # Non-429: the old 3-attempt bounded retry.
            hard_attempts += 1
            if hard_attempts < 3:
                time.sleep(0.25 * hard_attempts)
            else:
                break
    raise RuntimeError(f"rpc batch failed: {last}")


def get_blocks_batch(numbers):
    """One JSON-RPC batch: eth_blockNumber + one
    eth_getBlockByNumber(full txs) per block in `numbers`, in order.
    Returns (tip, [block or None, ...]) — a None entry is a block not
    produced yet. The tip rides in the same round trip, so lag is
    measured per batch instead of bought with a separate ~1.4s call
    (v0.1 run 3: that call alone cost 7 blocks of lag)."""
    calls = [("eth_blockNumber", [])]
    calls += [("eth_getBlockByNumber", [hex(x), True]) for x in numbers]
    results = rpc_batch(calls, timeout=60)
    tip = int(results[0], 16)
    return tip, results[1:]


# ------------------------------------------------------------------ checks --
# Pure functions over one block dict. No RPC, no I/O. The check set is
# deliberately small for v0.1: every check is O(txs) and runs in
# microseconds-to-milliseconds on a live block.
def grade_block(block, flagged):
    """Return (verdict, findings, queue_items, stats). A finding is
    How / Why / Fix / Evidence; severity info never flips the verdict,
    medium/high do. Queue items are slow follow-ups, never blockers."""
    number = int(block["number"], 16)
    txs = block.get("transactions", []) or []
    findings = []
    queue_items = []
    deployments = 0
    registry_txs = []
    flagged_hits = []
    sender_counts = {}

    for tx in txs:
        frm = (tx.get("from") or "").lower()
        to = (tx.get("to") or "").lower() if tx.get("to") else ""
        txh = tx.get("hash", "")
        sender_counts[frm] = sender_counts.get(frm, 0) + 1
        if not tx.get("to"):
            deployments += 1
        if to == REGISTRY:
            registry_txs.append(tx)
        for side, addr in (("from", frm), ("to", to)):
            if addr and addr in flagged:
                flagged_hits.append((side, addr, txh))

    # C1 — registry touch: a tx into the ERC-8004 registry this block.
    # A register() call is a new agent being born; anything else to the
    # registry is registry activity worth a look. Medium: it flips the
    # verdict, because a birth ungraded is exactly what Born Graded
    # exists to catch — and the follow-up (receipt -> agentId -> census
    # lookup) rides the queue, never the hot path.
    for tx in registry_txs:
        txh = tx.get("hash", "")
        inp = (tx.get("input") or "0x")
        is_register = inp[:10].lower() == SEL_REGISTER
        findings.append({
            "check": "C1_REGISTRY_TOUCH",
            "severity": "medium",
            "how": ("A transaction in this block calls the ERC-8004 "
                    "Identity Registry "
                    f"({REGISTRY})"
                    + (" via register(address,string) — a new agent "
                       "registration." if is_register else
                       " (not a register() call — registry activity, "
                       "not a birth).")),
            "why": ("A new registration is an agent born ungraded. "
                    "The census lookup is agentId-keyed and a block "
                    "tx carries no agentId, so the hot path cannot "
                    "grade the newborn — it flags the birth and queues "
                    "the receipt read."),
            "fix": ("Queue worker resolves the agentId from the "
                    "receipt's Transfer log and looks it up in the "
                    "census; a newborn absent from the census reads "
                    "UNGRADED until check/agent grades it. Born "
                    "Graded's gate is the standing fix for births "
                    "that trade before they are graded."),
            "evidence": {"tx_hash": txh, "to": REGISTRY,
                         "is_register_call": is_register,
                         "input_selector": inp[:10] if len(inp) >= 10
                         else inp},
        })
        queue_items.append({
            "type": "new_registration" if is_register else
                    "registry_activity",
            "block": number, "tx_hash": txh,
            "reason": "registry tx in block %d; resolve agentId from "
                      "receipt Transfer log, then census lookup" % number,
            "status": "pending",
            "enqueued_ts": int(time.time()),
        })

    # C2 — contract deployment: tx with no `to`. Info only: deploying
    # a contract is not a verdict on the deployer. Counted, cited,
    # never a flag by itself.
    if deployments:
        deploy_hashes = [t.get("hash", "") for t in txs if not t.get("to")]
        findings.append({
            "check": "C2_CONTRACT_DEPLOYMENT",
            "severity": "info",
            "how": (f"{deployments} contract-creation transaction(s) in "
                    f"this block."),
            "why": ("A deployment is neutral on its own — the code "
                    "behind it is what grades. The hot path does not "
                    "read code (that is an eth_getCode per deployment, "
                    "a slow check); the count is printed so a "
                    "deployment burst is visible."),
            "fix": ("No fix for a deployment. If the deployer or the "
                    "deployed code later flags, the follow-up grades "
                    "the code from the queue."),
            "evidence": {"deployments": deployments,
                         "tx_hashes": deploy_hashes},
        })

    # C3 — flagged address: tx from/to an address in flagged_addresses.json.
    for side, addr, txh in flagged_hits:
        entry = flagged[addr]
        findings.append({
            "check": "C3_FLAGGED_ADDRESS",
            "severity": "high",
            "how": (f"Transaction {side} a flagged address: {addr}."),
            "why": entry["reason"],
            "fix": ("Do not trust this counterparty on the strength "
                    "of this block alone — read the cited grade "
                    "before signing anything with it."),
            "evidence": {"tx_hash": txh, "side": side, "address": addr,
                         "source": entry["source"]},
        })

    # C4 — sender flood: one address sending >20 txs in a single block.
    # Cheap count, real shape: a flood is how a signing-spam or
    # Sybil burst looks from inside one block. Medium, not high —
    # a busy relayer or bundler can legitimately batch.
    for sender, count in sender_counts.items():
        if count > FLOOD_THRESHOLD:
            flood_hashes = [t.get("hash", "") for t in txs
                            if (t.get("from") or "").lower() == sender]
            findings.append({
                "check": "C4_SENDER_FLOOD",
                "severity": "medium",
                "how": (f"One sender, {sender}, sent {count} "
                        f"transactions in this single block "
                        f"(threshold {FLOOD_THRESHOLD})."),
                "why": ("A single block should not carry a burst from "
                        "one wallet unless something is batching, "
                        "spamming, or farming. Legitimate bundlers do "
                        "batch — which is why this is medium, not "
                        "high, and why the fix is a look, not a block."),
                "fix": ("Read the sender's txs: same target, same "
                        "selector, same value pattern = one machine "
                        "acting at once. If it is a farm, the "
                        "counterparty grade follows."),
                "evidence": {"sender": sender, "tx_count": count,
                             "tx_hashes": flood_hashes[:10],
                             "tx_hashes_total": len(flood_hashes)},
            })

    verdict = "FLAG" if any(f["severity"] in ("medium", "high")
                            for f in findings) else "PASS"
    stats = {"tx_count": len(txs), "deployments": deployments,
             "registry_txs": len(registry_txs),
             "flagged_hits": len(flagged_hits)}
    return verdict, findings, queue_items, stats


# ------------------------------------------------------------------ ledger --
def append_jsonl(path, record):
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def last_graded_block():
    """Last block number in verdicts.jsonl, or None if the ledger is
    empty/missing. The default start resumes here + 1 — never skip."""
    try:
        last = None
        with open(VERDICTS_PATH) as f:
            for line in f:
                if line.strip():
                    last = line
        if last:
            return json.loads(last)["block"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None
    return None


# -------------------------------------------------------------------- main --
def run(blocks, from_block=None):
    lookup, meta = load_lookup()
    flagged = load_flagged()
    total_known = meta.get("total")
    print(f"[{GRADER}] v{VERSION} starting: lookup "
          f"{total_known if total_known is not None else '?'} graded "
          f"agents loaded (base "
          f"{meta.get('counts', {}).get('base', '?')} + robinhood "
          f"{meta.get('counts', {}).get('robinhood', '?')}); flagged "
          f"addresses: {len(flagged)}; RPC {RPC_URL}; budget "
          f"{BLOCK_BUDGET_MS}ms/block; batch {BATCH_SIZE}", flush=True)

    tip = get_tip()
    if from_block is not None:
        start_block = from_block
        print(f"[{GRADER}] starting at block {from_block} (live tip "
              f"{tip}, lag {tip - from_block})", flush=True)
    else:
        last = last_graded_block()
        if last is None:
            start_block = tip
            print(f"[{GRADER}] no verdicts yet — starting at live tip "
                  f"{tip}", flush=True)
        else:
            start_block = last + 1
            print(f"[{GRADER}] resuming at block {start_block} (last "
                  f"graded {last}, live tip {tip}, lag "
                  f"{tip - start_block})", flush=True)
    tip_known = tip

    results = []
    n = start_block
    graded = 0
    # Wall-clock time (time.time()) when the next batch's end block
    # should exist, from the last graded block's own timestamp.
    # None until the first batch lands. A target in the past means
    # catch-up: fetch immediately, no sleep.
    ready_at = None

    while graded < blocks:
        batch_n = min(BATCH_SIZE, blocks - graded)
        end_block = n + batch_n - 1
        batch_start = n
        if ready_at is None:
            # First batch: if the whole batch already exists, fetch
            # now (catch-up); otherwise wait for its end block.
            if tip_known < end_block:
                wait_s = (end_block - tip_known) * BLOCK_INTERVAL_S
                if wait_s > 0:
                    time.sleep(wait_s)
        else:
            wait_s = ready_at - time.time()
            if wait_s > 0:
                # Cap: a legit tip-mode wait is at most one batch of
                # chain time (1.6s). Anything longer is clock skew,
                # not the chain — fetch and let the null-retry hold.
                time.sleep(min(wait_s, 5.0))
        t0 = time.monotonic()
        tip_known, fetched = get_blocks_batch(
            list(range(n, n + batch_n)))
        batch_fetch_ms = (time.monotonic() - t0) * 1000
        # A null in the batch is a block not produced yet — grade the
        # prefix that exists, hold position on the rest. Never skip.
        first_null = next((i for i, b in enumerate(fetched)
                           if b is None), None)
        if first_null is not None:
            fetched = fetched[:first_null]
            if not fetched:
                time.sleep(0.1)
                continue
        mode = ("catchup" if tip_known - batch_start > CATCHUP_LAG
                else "tip")
        # The batch round trip is shared across its blocks: the honest
        # per-block fetch share is the batch cost divided by the batch.
        fetch_ms_each = batch_fetch_ms / len(fetched)
        for block in fetched:
            g0 = time.monotonic()
            verdict, findings, queue_items, stats = grade_block(
                block, flagged)
            grade_ms = (time.monotonic() - g0) * 1000
            total_ms = fetch_ms_each + grade_ms

            record = {
                "grader": GRADER, "version": VERSION, "chain": CHAIN,
                "chainId": CHAIN_ID,
                "ts": int(time.time()),
                "block": n,
                "block_hash": block.get("hash"),
                "verdict": verdict,
                "tx_count": stats["tx_count"],
                "findings": findings,
                "queue_enqueued": len(queue_items),
                "fetch_ms": round(fetch_ms_each, 1),
                "grade_ms": round(grade_ms, 1),
                "total_ms": round(total_ms, 1),
                "budget_ms": BLOCK_BUDGET_MS,
                "within_budget": total_ms <= BLOCK_BUDGET_MS,
                "lag_blocks": tip_known - n,
                "lag_tip_sample": tip_known,
                "lag_tip_sampled_at_block": batch_start,
                "batch_size": len(fetched),
                "batch_fetch_ms": round(batch_fetch_ms, 1),
                "mode": mode,
            }
            # 0.1.6: sign the verdict before it lands. ~13ms in pure
            # Python — inside the 200ms block budget. A verdict with
            # no operator key is still graded, marked unsigned.
            if _OP_KEY and _tape is not None:
                try:
                    record = _tape.sign_verdict(record, _OP_KEY)
                except Exception as e:  # noqa: BLE001
                    record["signed"] = False
                    print(f"[{GRADER}] WARNING: signing failed: {e}",
                          flush=True)
            else:
                record["signed"] = False
            append_jsonl(VERDICTS_PATH, record)
            if verdict == "FLAG" and _tape is not None:
                try:
                    _tape.tape_flag(NODE_DIR, record)
                except Exception as e:  # noqa: BLE001 - a tape failure
                    # never breaks grading; it is printed, loudly.
                    print(f"[{GRADER}] WARNING: tape failed: {e}",
                          flush=True)
            for item in queue_items:
                append_jsonl(QUEUE_PATH, item)
            results.append(record)
            over = "" if record["within_budget"] else " OVER BUDGET"
            print(f"[{GRADER}] block {n} {verdict} "
                  f"txs={stats['tx_count']} findings={len(findings)} "
                  f"queued={len(queue_items)} "
                  f"total_ms={record['total_ms']} "
                  f"lag={record['lag_blocks']} mode={mode}{over}",
                  flush=True)
            for fnd in findings:
                print(f"[{GRADER}]   {fnd['check']} [{fnd['severity']}] "
                      f"{fnd['evidence'].get('tx_hash', '')}", flush=True)
            graded += 1
            n += 1
        # Pace the next batch off the last graded block's timestamp:
        # its end block exists ~0.2s per block after it. If that time
        # is already past we are in catch-up and the sleep is zero.
        # The request goes out FETCH_LEAD_S early: it spends that long
        # in transit before the server reads the tip, so a request
        # sent "on time" lands 2-3 blocks late (run 6's steady state).
        last_ts = int(fetched[-1].get("timestamp", "0x0"), 16)
        next_n = min(BATCH_SIZE, blocks - graded)
        next_end = n + next_n - 1
        ready_at = (last_ts + (next_end - (n - 1)) * BLOCK_INTERVAL_S
                    + PACE_MARGIN_S - FETCH_LEAD_S)
        # Catch-up gap (v0.2-rh2): in catch-up the timestamp pacing
        # above is already past, so batches would fire back-to-back
        # and 429 the RPC. A 0.4s gap between batches keeps the
        # drain fast (~20 blocks/sec) without hammering.
        if tip_known - n > CATCHUP_LAG:
            time.sleep(CATCHUP_GAP_S)

    # Final lag: one tip read at the end, so the run reports the true
    # distance behind the tip instead of the last sample.
    try:
        end_tip = get_tip()
    except Exception:  # noqa: BLE001
        end_tip = tip_known
    totals = [r["total_ms"] for r in results]
    totals_sorted = sorted(totals)
    p95 = totals_sorted[max(0, int(len(totals_sorted) * 0.95) - 1)]
    summary = {
        "grader": GRADER, "version": VERSION, "chain": CHAIN,
        "blocks_graded": len(results),
        "first_block": results[0]["block"],
        "last_block": results[-1]["block"],
        "verdicts": {"PASS": sum(1 for r in results
                                 if r["verdict"] == "PASS"),
                     "FLAG": sum(1 for r in results
                                 if r["verdict"] == "FLAG")},
        "findings_total": sum(len(r["findings"]) for r in results),
        "queued_total": sum(r["queue_enqueued"] for r in results),
        "total_ms_mean": round(sum(totals) / len(totals), 1),
        "total_ms_p95": round(p95, 1),
        "total_ms_max": round(max(totals), 1),
        "budget_ms": BLOCK_BUDGET_MS,
        "over_budget_blocks": sum(1 for r in results
                                  if not r["within_budget"]),
        "batch_size": BATCH_SIZE,
        "catchup_blocks": sum(1 for r in results
                              if r["mode"] == "catchup"),
        "tip_blocks": sum(1 for r in results if r["mode"] == "tip"),
        "tip_at_start": tip, "tip_at_end": end_tip,
        "lag_at_end_blocks": end_tip - results[-1]["block"],
        "gaps": "none — blocks are consecutive by construction; a null "
                "fetch retries the same block, never skips",
    }
    print(f"[{GRADER}] SUMMARY " + json.dumps(summary), flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser(description="MAD Block Grader v0.2-rh1 (Robinhood Chain)")
    ap.add_argument("--blocks", type=int, default=10,
                    help="consecutive blocks to grade (default 10)")
    ap.add_argument("--from", dest="from_block", type=int, default=None,
                    help="start block (default: live tip)")
    ap.add_argument("--self-test", action="store_true",
                    help="run the offline self-test, no network")
    args = ap.parse_args()
    if args.self_test:
        from selftest_robinhood import run_selftest
        sys.exit(run_selftest())
    run(args.blocks, from_block=args.from_block)


if __name__ == "__main__":
    main()
