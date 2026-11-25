#!/usr/bin/env python3
"""MAD NODE TAPE — the node's public forward record (flags vs outcomes).

The operator's feedback, point 6: "No record of its own. No
published forward tape of its flags versus outcomes. Before I pay
for a grader, I want its receipts."

The tape is the node's receipts, published in the open:

  * every FLAG verdict, the moment it lands (the catch);
  * every paid verdict served through the A2A door (the sale);
  * every task grade the node delivers (the work);
  * every tape-head anchor filed in the witness ledger (the proof).

Same hash-chained record discipline as the Complaint Desk and MAD
TASKS: seq, prev_hash, payload_sha256, entry_hash — recomputable
by anyone, in order, with nothing editable after the fact. A
FLAG's outcome arrives later as its own entry (type "outcome",
referencing the flag's entry_hash): what the follow-up found. A
flag with no outcome yet says "open" — the tape never claims a
resolution it has not run.

The tape is public by design: GET /v1/node/tape on the serve door
(free), `mad node tape` on the command line, and the file itself
(node-tape.jsonl) in the node's home. The standing recompute reads
it as a source (see NODE_TAPE.md): a node's flags, outcomes,
served verdicts and task grades are verified work, and verified
work is what a standing is made of.

A verdict is signed before it is taped: verdict_hash is keccak-256
of the canonical JSON of the verdict record (without the signature
fields), and the signature is the operator's EIP-191 personal_sign
over that hash's hex. Any third agent verifies it with eth_account
(or the pure-stdlib verifier in signing.py) from the record alone
— never the messenger.
"""
import hashlib
import json
import os
import time

try:
    import signing
except ImportError:  # run from elsewhere; the node dir is the package
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import signing

TAPE_NAME = "node-tape.jsonl"
SIG_FIELDS = ("verdict_hash", "signature", "signer", "signed")


def node_dir():
    return os.environ.get("MAD_NODE_DIR") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")


def tape_path(ndir=None):
    return os.path.join(ndir or node_dir(), TAPE_NAME)


def canonical(record):
    """Canonical JSON for hashing: sorted keys, tight separators,
    signature fields stripped (the hash is over the verdict, not
    over its own signature)."""
    stripped = {k: v for k, v in record.items() if k not in SIG_FIELDS}
    return json.dumps(stripped, sort_keys=True, separators=(",", ":"))


def verdict_hash(record):
    """keccak-256 of the canonical verdict, hex."""
    return "0x" + signing.keccak256(canonical(record)).hex()


def sign_verdict(record, privkey):
    """Return a copy of the record with verdict_hash, signature and
    signer. The signature is the operator's EIP-191 personal_sign
    over the verdict hash's hex text."""
    out = dict(record)
    vh = verdict_hash(out)
    sig, signer = signing.sign_message(vh, privkey)
    out["verdict_hash"] = vh
    out["signature"] = "0x" + sig.hex()
    out["signer"] = signer
    out["signed"] = True
    return out


def verify_signed_verdict(record):
    """True iff the record's signature recovers its claimed signer
    over its own verdict hash. A third agent runs this and needs
    nothing but the record."""
    try:
        if not record.get("signed"):
            return False
        if record.get("verdict_hash") != verdict_hash(record):
            return False
        sig = bytes.fromhex(record["signature"].removeprefix("0x"))
        return signing.verify_message(record["verdict_hash"], sig,
                                      record["signer"])
    except (ValueError, TypeError, AttributeError):
        return False


def read_tape(ndir=None):
    """All tape entries, in order. Returns (entries, chain_ok,
    broken_at_seq_or_None). The chain is recomputed, not trusted."""
    path = tape_path(ndir)
    entries = []
    try:
        with open(path) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    except OSError:
        return [], True, None
    prev = "0" * 64
    for e in entries:
        payload = {k: v for k, v in e.items()
                   if k not in ("payload_sha256", "entry_hash")}
        expect_payload = hashlib.sha256(
            json.dumps(payload, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest()
        expect_entry = hashlib.sha256(
            (e["prev_hash"] + expect_payload + e["ts"]).encode()
        ).hexdigest()
        if (e["prev_hash"] != prev or e["payload_sha256"] != expect_payload
                or e["entry_hash"] != expect_entry):
            return entries, False, e.get("seq")
        prev = e["entry_hash"]
    return entries, True, None


def append_tape(ndir, entry):
    """Append one hash-chained entry. Returns the stored record."""
    path = tape_path(ndir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entries, chain_ok, _ = read_tape(ndir)
    if entries and not chain_ok:
        raise ValueError("tape chain is broken — refusing to append "
                         "to a record I cannot verify")
    rec = dict(entry)
    rec["seq"] = (entries[-1]["seq"] + 1) if entries else 1
    rec["prev_hash"] = entries[-1]["entry_hash"] if entries else "0" * 64
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    rec["payload_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    rec["entry_hash"] = hashlib.sha256(
        (rec["prev_hash"] + rec["payload_sha256"] + rec["ts"]).encode()
    ).hexdigest()
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def tape_flag(ndir, verdict_record):
    """Tape a FLAG verdict: the catch, as it lands."""
    findings = verdict_record.get("findings") or []
    return append_tape(ndir, {
        "type": "flag",
        "chain": verdict_record.get("chain"),
        "chainId": verdict_record.get("chainId"),
        "block": verdict_record.get("block"),
        "block_hash": verdict_record.get("block_hash"),
        "verdict": "FLAG",
        "verdict_hash": verdict_record.get("verdict_hash"),
        "signature": verdict_record.get("signature"),
        "signer": verdict_record.get("signer"),
        "checks": sorted({f.get("check") for f in findings
                          if f.get("check")}),
        "severities": sorted({f.get("severity") for f in findings
                              if f.get("severity")}),
        "outcome": "open",
    })


def tape_outcome(ndir, flag_entry_hash, outcome, evidence):
    """Resolve a flag: what the follow-up found. Appends its own
    entry — the flag is never edited."""
    return append_tape(ndir, {
        "type": "outcome",
        "flag_entry_hash": flag_entry_hash,
        "outcome": outcome,
        "evidence": evidence,
    })


def tape_served(ndir, block, verdict_hash, payer, settle_tx, split):
    """A paid verdict served through the A2A door: the sale, on
    the record, with the toll split as configured."""
    return append_tape(ndir, {
        "type": "served",
        "block": block,
        "verdict_hash": verdict_hash,
        "payer": payer,
        "settle_tx": settle_tx,
        "toll_usdc": 0.01,
        "split": split,
    })


def tape_task(ndir, task_id, target, verdict, verdict_hash):
    """A task grade the node delivered: the work, on the record."""
    return append_tape(ndir, {
        "type": "task",
        "task_id": task_id,
        "target": target,
        "verdict": verdict,
        "verdict_hash": verdict_hash,
    })


def tape_anchor(ndir, witness_seq, head_entry_hash, head_seq):
    """The tape head, anchored in the witness ledger."""
    return append_tape(ndir, {
        "type": "anchor",
        "witness_seq": witness_seq,
        "head_entry_hash": head_entry_hash,
        "head_seq": head_seq,
    })


def selftest():
    ok = True

    def check(label, cond, detail):
        nonlocal ok
        print("  [%s] %s: %s" % ("PASS" if cond else "FAIL", label, detail))
        ok = ok and cond

    print("== node tape selftest ==")
    import tempfile
    ndir = tempfile.mkdtemp(prefix="mad-tape-test-")
    # Sign + verify a verdict record.
    rec = {"grader": "mad-block-grader-rh", "version": "0.2-rh2",
           "chain": "robinhood", "chainId": 4663, "block": 122000000,
           "verdict": "FLAG", "tx_count": 3, "findings": []}
    signed = sign_verdict(rec, 1)
    check("signed verdict verifies from the record alone",
          verify_signed_verdict(signed), signed["signer"])
    check("verdict hash is stable (signature fields excluded)",
          verdict_hash(signed) == signed["verdict_hash"],
          signed["verdict_hash"][:18] + "...")
    tampered = dict(signed)
    tampered["block"] = 122000001
    check("a tampered verdict fails verification",
          not verify_signed_verdict(tampered), "false")
    unsigned = dict(rec)
    check("an unsigned verdict fails verification",
          not verify_signed_verdict(unsigned), "false")
    # Tape: flag, outcome, served, anchor; chain recomputes clean.
    f = tape_flag(ndir, signed)
    check("flag entry chained (seq 1)", f["seq"] == 1
          and f["prev_hash"] == "0" * 64, "seq %d" % f["seq"])
    o = tape_outcome(ndir, f["entry_hash"], "LIVE",
                     "registry follow-up: agent 7622 LIVE in census")
    check("outcome entry references the flag", o["flag_entry_hash"]
          == f["entry_hash"], "linked")
    s = tape_served(ndir, 122000000, signed["verdict_hash"],
                    "0x1111111111111111111111111111111111111111",
                    "0x" + "ab" * 32,
                    {"operator_share_pct": None,
                     "operator_usdc": None, "mad_usdc": None,
                     "note": "split unset — founder sets X"})
    check("served entry recorded", s["type"] == "served"
          and s["toll_usdc"] == 0.01, "1c")
    entries, chain_ok, broken = read_tape(ndir)
    check("tape chain recomputes clean", chain_ok and len(entries) == 3,
          "%d entries" % len(entries))
    # A tampered tape file is caught.
    with open(tape_path(ndir), "a") as fh:
        fh.write(json.dumps({"seq": 99, "type": "flag",
                             "prev_hash": "0" * 64,
                             "payload_sha256": "0" * 64,
                             "entry_hash": "0" * 64,
                             "ts": "2026-11-24T00:00:00Z"}) + "\n")
    _, chain_ok2, broken2 = read_tape(ndir)
    check("a broken tape is caught, not trusted",
          not chain_ok2 and broken2 == 99, "broken at seq 99")
    print("== node tape selftest", "PASS ==" if ok else "FAIL ==")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
