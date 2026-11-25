#!/usr/bin/env python3
"""MAD BLOCK GRADER v0.2-rh1 — offline self-test (Robinhood Chain). No network, no RPC.

Feeds synthetic blocks through the same grade_block() the live run
uses and asserts the verdicts, plus the batch-response parser the
v0.2 hot path depends on. Run:
  ~/workspace/mad-watch/venv/bin/python node_grader.py --self-test
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_grader import grade_block, REGISTRY, SEL_REGISTER  # noqa: E402


def _tx(txh, frm, to=None, inp="0x"):
    return {"hash": txh, "from": frm, "to": to, "value": "0x0",
            "input": inp, "transactionIndex": "0x0"}


def _block(number, txs):
    return {"number": hex(number), "hash": "0x" + "ab" * 32,
            "transactions": txs}


def run_selftest():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"[self-test] {name}: {'OK' if cond else 'FAIL'} {detail}")
        if not cond:
            ok = False

    flagged = {"0xdead000000000000000000000000000000000001":
               {"source": "self-test fixture",
                "reason": "fixture-flagged address"}}
    a = "0x1111111111111111111111111111111111111111"
    b = "0x2222222222222222222222222222222222222222"

    # 1. Clean block: two plain transfers -> PASS, no findings.
    v, f, q, s = grade_block(_block(1, [_tx("0xt1", a, b),
                                        _tx("0xt2", b, a)]), {})
    check("clean block PASS", v == "PASS" and f == [] and q == [],
          f"verdict={v} findings={len(f)}")

    # 2. Registry register() call -> FLAG medium + 1 queue item.
    v, f, q, s = grade_block(_block(2, [
        _tx("0xreg1", a, REGISTRY, SEL_REGISTER + "00" * 64)]), {})
    check("registry register FLAG", v == "FLAG"
          and len(f) == 1 and f[0]["check"] == "C1_REGISTRY_TOUCH"
          and f[0]["severity"] == "medium"
          and f[0]["evidence"]["is_register_call"] is True,
          f"verdict={v}")
    check("registry register queued", len(q) == 1
          and q[0]["type"] == "new_registration"
          and q[0]["tx_hash"] == "0xreg1",
          f"queued={len(q)}")
    check("finding has How/Why/Fix/Evidence",
          all(k in f[0] for k in ("how", "why", "fix", "evidence")))

    # 3. Registry non-register call -> FLAG, queued as registry_activity.
    v, f, q, s = grade_block(_block(3, [
        _tx("0xreg2", a, REGISTRY, "0x12345678")]), {})
    check("registry non-register FLAG + activity queue",
          v == "FLAG" and q[0]["type"] == "registry_activity"
          and f[0]["evidence"]["is_register_call"] is False)

    # 4. Contract deployment alone -> PASS with an info finding.
    v, f, q, s = grade_block(_block(4, [_tx("0xdep1", a, None)]), {})
    check("deployment alone PASS (info only)",
          v == "PASS" and len(f) == 1
          and f[0]["check"] == "C2_CONTRACT_DEPLOYMENT"
          and f[0]["severity"] == "info" and q == [],
          f"verdict={v}")

    # 5. Flagged address on either side -> FLAG high.
    v, f, q, s = grade_block(_block(5, [
        _tx("0xflg1", "0xdead000000000000000000000000000000000001", b)]),
        flagged)
    check("flagged address FLAG high",
          v == "FLAG" and f[0]["check"] == "C3_FLAGGED_ADDRESS"
          and f[0]["severity"] == "high"
          and f[0]["evidence"]["source"] == "self-test fixture")

    # 6. Sender flood: 21 txs from one sender -> FLAG medium.
    flood = [_tx(f"0xf{i}", a, b) for i in range(21)]
    v, f, q, s = grade_block(_block(6, flood), {})
    check("sender flood FLAG medium",
          v == "FLAG" and any(x["check"] == "C4_SENDER_FLOOD"
                              for x in f)
          and s["tx_count"] == 21)
    # 7. Exactly at threshold (20) -> no flood finding.
    v, f, q, s = grade_block(_block(7, [_tx(f"0xg{i}", a, b)
                                        for i in range(20)]), {})
    check("20 txs is not a flood",
          v == "PASS" and not any(x["check"] == "C4_SENDER_FLOOD"
                                  for x in f))

    # 8. Queue worker: receipt -> agentId from the Transfer log.
    from queue_worker import agent_id_from_receipt, T_TRANSFER
    from node_grader import REGISTRY as REG2
    receipt = {"status": "0x1", "logs": [{
        "address": REG2, "topics": [T_TRANSFER,
            "0x0000000000000000000000000000000000000000000000000000000000000000",
            "0x0000000000000000000000001111111111111111111111111111111111111111",
            "0x000000000000000000000000000000000000000000000000000000000012af52"],
        "data": "0x"}]}
    check("receipt yields agentId 1224530",
          agent_id_from_receipt(receipt) == 1224530)
    check("receipt without registry log yields None",
          agent_id_from_receipt({"status": "0x1", "logs": []}) is None)

    # 9. Batch parse: results returned in call order even when the
    # wire order differs; a null result (block not out yet) is kept.
    from node_grader import parse_batch_results
    resp = [{"jsonrpc": "2.0", "id": 2, "result": {"number": "0x2"}},
            {"jsonrpc": "2.0", "id": 1, "result": "0x1234"},
            {"jsonrpc": "2.0", "id": 3, "result": None}]
    check("batch parse keeps call order + null",
          parse_batch_results(resp, 3)
          == ["0x1234", {"number": "0x2"}, None])
    # 10. Batch parse: an item error raises; a short response raises.
    try:
        parse_batch_results([{"jsonrpc": "2.0", "id": 1,
                              "error": {"code": -32602,
                                        "message": "bad"}}], 1)
        check("batch parse raises on item error", False)
    except RuntimeError:
        check("batch parse raises on item error", True)
    try:
        parse_batch_results([{"jsonrpc": "2.0", "id": 1,
                              "result": "0x1"}], 2)
        check("batch parse raises on short response", False)
    except RuntimeError:
        check("batch parse raises on short response", True)

    print(f"[self-test] {'ALL CHECKS PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_selftest())
