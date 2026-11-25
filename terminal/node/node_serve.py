#!/usr/bin/env python3
"""MAD NODE SERVE — the node's A2A door.

The operator's feedback, point 1: "No A2A door. The verdicts land
in a JSON file on my disk. There's no API I can query, no feed I
can subscribe to, no x402 endpoint where I pay per verdict. Another
agent can't buy what my node sees — so the compute has no way to
earn."

This is the door. Another agent queries what the node sees and
pays per verdict — 1c, through the same x402 rail as the public
mirror (EIP-3009, scheme "exact", network "base", PayAI
facilitator verify + settle). The price is per verdict — what the
compute catches, not uptime. The look is free: the status door,
the verdict line, and the tape cost nothing; the full verdict
(findings, evidence, signature, anchor) is the 1c door.

Doors (all JSON):
  GET /                          the door list (free)
  GET /v1/node/status            running, tip, lag, counts (free)
  GET /v1/node/verdicts?block=N
                                 the verdict line (free — the look)
  GET /v1/node/verdicts?block=N&full=1
                                 the full verdict (1c x402 door)
  GET /v1/node/agent/<id>?chainId=4663
                                 verdicts touching one agent (free
                                 summary; &full=1 is the 1c door)
  GET /v1/node/tape?limit=N     the public tape, newest first (free)
  GET /v1/node/verify?block=N   re-verify the signature + hash (free)
  GET /v1/node/toll             the toll ledger + split config (free)

The toll split: every settled 1c is recorded in toll-ledger.jsonl
with the split as configured in toll_share.json. The operator share
X% is a named config the founder sets — until it is set the split
is UNSET (null), the 1c is held by the operator, and the ledger
says so plainly. No split is ever invented here.

Stdlib only. No signing of transactions, no sending, no funds
moved by this process — it verifies a payment through the
facilitator and serves a verdict. The operator's wallet is the
payTo: the toll goes to the operator who ran the compute.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import node_tape as tape  # noqa: E402

NODE_DIR = os.environ.get("MAD_NODE_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "mad-terminal", "node")
VERDICTS_PATH = os.path.join(NODE_DIR, "verdicts-robinhood.jsonl")
TASK_GRADES_PATH = os.path.join(NODE_DIR, "task-grades-robinhood.jsonl")
QUEUE_PATH = os.path.join(NODE_DIR, "queue-robinhood.jsonl")
TOLL_LEDGER = os.path.join(NODE_DIR, "toll-ledger.jsonl")
TOLL_CONFIG = os.path.join(NODE_DIR, "toll_share.json")
LICENSE_PATH = os.path.join(NODE_DIR, "license.json")
STAY_STATUS = os.path.join(NODE_DIR, "node-stay-status.json")

MAD_WALLET = "0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bd029029"
X402_FACILITATOR = "https://facilitator.payai.network"
X402_PRICE_MICRO = "10000"  # 0.01 USDC
TOLL_USDC = 0.01
RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Content-Type": "application/json"}
TAIL_LINES = 50000  # recent verdicts scanned first; older = full scan


# ------------------------------------------------------------------ config --

def operator_wallet():
    """The operator's wallet: license.json (written by `mad node
    start`), or None — without it the paid door refuses to open
    (there is nobody to pay)."""
    try:
        with open(LICENSE_PATH) as f:
            w = json.load(f).get("wallet", "")
        if w and w not in ("test", "free") and w.startswith("0x"):
            return w
    except (OSError, ValueError):
        pass
    return os.environ.get("MAD_NODE_WALLET") or None


def toll_config():
    """The toll split config. operator_share_pct is null until the
    founder sets X — the default is UNSET, never 0 pretending to
    be a decision."""
    cfg = {"operator_share_pct": None,
           "operator_wallet": operator_wallet(),
           "mad_wallet": MAD_WALLET,
           "note": "operator share X% is set by the founder; "
                   "until then the split is unset"}
    try:
        with open(TOLL_CONFIG) as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items()
                        if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def toll_split():
    """The split for one 1c verdict, as configured."""
    cfg = toll_config()
    pct = cfg.get("operator_share_pct")
    if pct is None:
        return {"operator_share_pct": None, "operator_usdc": None,
                "mad_usdc": None,
                "note": "split unset — founder sets X; the 1c is "
                        "held by the operator"}
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return {"operator_share_pct": None, "operator_usdc": None,
                "mad_usdc": None,
                "note": "toll_share.json operator_share_pct is not "
                        "a number — split unset"}
    if not 0 <= pct <= 100:
        return {"operator_share_pct": None, "operator_usdc": None,
                "mad_usdc": None,
                "note": "operator_share_pct out of range 0-100 — "
                        "split unset"}
    op = round(TOLL_USDC * pct / 100, 6)
    return {"operator_share_pct": pct, "operator_usdc": op,
            "mad_usdc": round(TOLL_USDC - op, 6), "note": None}


def toll_totals():
    """Totals from the toll ledger: what the door has actually
    collected, and what each side is owed under the split."""
    total = 0.0
    served = 0
    payers = set()
    try:
        with open(TOLL_LEDGER) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                total += float(r.get("toll_usdc") or 0)
                served += 1
                if r.get("payer"):
                    payers.add(r["payer"])
    except OSError:
        pass
    split = toll_split()
    pct = split.get("operator_share_pct")
    return {"served_verdicts": served, "toll_collected_usdc": round(total, 4),
            "unique_payers": len(payers),
            "operator_owed_usdc": (round(total * pct / 100, 6)
                                   if pct is not None else None),
            "mad_owed_usdc": (round(total * (100 - pct) / 100, 6)
                              if pct is not None else None),
            "split": split}


def append_toll_ledger(block, verdict_hash, payer, settle_tx, split):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "block": block, "verdict_hash": verdict_hash,
           "payer": payer, "settle_tx": settle_tx,
           "toll_usdc": TOLL_USDC, "split": split}
    with open(TOLL_LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


# ------------------------------------------------------------------ verdicts --

def _read_lines_tail(path, limit=TAIL_LINES):
    """Last `limit` lines of a file (cheap on a big ledger)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            step = 1024 * 1024
            data = b""
            while len(data) < size and data.count(b"\n") <= limit:
                take = min(step, size - len(data))
                f.seek(size - len(data) - take)
                data = f.read(take) + data
                if take == size - len(data):
                    break
        return [l for l in data.decode(errors="replace").splitlines()
                if l.strip()]
    except OSError:
        return []


def _read_lines_all(path):
    try:
        with open(path) as f:
            return [l for l in f if l.strip()]
    except OSError:
        return []


def find_verdict(block):
    """The verdict record for one block, or None. Recent blocks
    come from the tail scan; older ones fall back to a full scan."""
    for line in reversed(_read_lines_tail(VERDICTS_PATH)):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("block") == block:
            return r
    for line in _read_lines_all(VERDICTS_PATH):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("block") == block:
            return r
    return None


def verdict_line(record):
    """The free look: block, verdict, counts, signed — no findings,
    no evidence. The look is free; the verdict is paid."""
    return {"block": record.get("block"),
            "verdict": record.get("verdict"),
            "tx_count": record.get("tx_count"),
            "findings_count": len(record.get("findings") or []),
            "signed": bool(record.get("signed")),
            "signer": record.get("signer"),
            "verdict_hash": record.get("verdict_hash")}


def agent_hits(agent_id, chain_id):
    """Blocks + txs touching one agent: C1 registry follow-ups in
    the queue, and task grades naming the agent's wallet. Returns
    (summary_list, full_records)."""
    summary = []
    full = []
    for line in _read_lines_tail(QUEUE_PATH, 20000):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("agentId")) == str(agent_id):
            summary.append({"kind": "registry_touch",
                            "block": r.get("block"),
                            "agentId": agent_id})
            full.append(r)
    for line in _read_lines_tail(TASK_GRADES_PATH, 20000):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        task = r.get("task") or {}
        actor = task.get("actor") or {}
        if str(actor.get("agentId")) == str(agent_id):
            summary.append({"kind": "task_grade",
                            "tx": task.get("tx_hash"),
                            "block": task.get("block"),
                            "verdict": r.get("verdict")})
            full.append(r)
    return summary, full


def chain_tip():
    try:
        data = json.dumps({"jsonrpc": "2.0", "id": 1,
                           "method": "eth_blockNumber",
                           "params": []}).encode()
        req = urllib.request.Request(RPC_URL, data=data, headers=UA,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return int(json.loads(r.read())["result"], 16)
    except Exception:
        return None


# --------------------------------------------------------------------- x402 --

def _b64_json(obj):
    return base64.b64encode(
        json.dumps(obj).encode()).decode()


def _b64_decode_json(s):
    raw = base64.b64decode("".join(str(s).split()))
    return json.loads(raw.decode())


def x402_requirements(resource, description, pay_to):
    return {"scheme": "exact", "network": "base",
            "maxAmountRequired": X402_PRICE_MICRO,
            "resource": resource, "description": description,
            "mimeType": "application/json", "payTo": pay_to,
            "maxTimeoutSeconds": 300, "asset": USDC_BASE,
            "extra": {"name": "USD Coin", "version": "2"}}


def x402_required(req, reason):
    body = {"x402Version": 1, "error": reason, "accepts": [req]}
    return 402, body, {
        "X-PAYMENT-REQUIRED": _b64_json(
            {"x402Version": 1, "accepts": [req]})}


def _facilitator(path, payload, requirements):
    data = json.dumps({"x402Version": 1, "paymentPayload": payload,
                       "paymentRequirements": requirements}).encode()
    req = urllib.request.Request(
        X402_FACILITATOR + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        return {"_text": text[:200]}


def x402_gate(handler, resource, description):
    """The 1c door. Returns (gate, error_response_or_None). Inputs
    are validated BEFORE the gate, so a malformed call is a free
    400, never a charged error. Mirrors the public mirror's gate
    (worker.src.js x402Gate) — same facilitator, same price, same
    headers — except the payTo is the OPERATOR: the toll goes to
    the one who ran the compute."""
    pay_to = operator_wallet()
    if not pay_to:
        return None, (503, {"error": "the paid door is closed: no "
                            "operator wallet configured — run "
                            "`mad node start --wallet 0x...` first"},
                      {})
    req = x402_requirements(resource, description, pay_to)
    hdr = (handler.headers.get("PAYMENT-SIGNATURE")
           or handler.headers.get("X-PAYMENT"))
    if not hdr:
        return None, x402_required(
            req, "PAYMENT-SIGNATURE (or X-PAYMENT) header is required: "
                 "this verdict costs 0.01 USDC via x402 (EIP-3009, "
                 "Base). The free look is the verdict line.")
    try:
        payload = _b64_decode_json(hdr)
    except Exception:
        return None, x402_required(
            req, "payment header is not valid base64-encoded JSON")
    v = _facilitator("/verify", payload, req)
    if not v or v.get("isValid") is not True:
        return None, x402_required(
            req, "payment verification failed: " + str(
                (v or {}).get("invalidReason") or (v or {}).get("errorReason")
                or (v or {}).get("message")
                or "the facilitator did not validate it"))
    s = _facilitator("/settle", payload, req)
    if not s or s.get("success") is not True:
        return None, x402_required(
            req, "payment settlement failed: " + str(
                (s or {}).get("errorReason") or (s or {}).get("message")
                or "the facilitator did not settle it"))
    auth = (payload or {}).get("payload", {}).get("authorization") or {}
    return {"requirements": req,
            "settle": {"success": True,
                       "transaction": s.get("transaction"),
                       "network": s.get("network") or "base",
                       "payer": s.get("payer") or auth.get("from")}}, None


# ------------------------------------------------------------------ handler --

class NodeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the log clean
        sys.stderr.write("[node-serve] %s\n" % (fmt % args))

    def _send(self, status, obj, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _resource(self):
        host = self.headers.get("Host") or "127.0.0.1:8403"
        return "http://" + host + self.path

    def do_GET(self):
        try:
            self._route()
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 - a door must not die
            self._send(500, {"error": "node door error: %s" % e})

    def _route(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        if path == "/":
            return self._send(200, {
                "node": "mad-node-robinhood", "version": "0.1.8",
                "doors": {
                    "/v1/node/status": "free — running, tip, lag",
                    "/v1/node/verdicts?block=N": "free — the look",
                    "/v1/node/verdicts?block=N&full=1":
                        "1c x402 — the full verdict",
                    "/v1/node/agent/<id>": "free summary; &full=1 is 1c",
                    "/v1/node/tape": "free — the public tape",
                    "/v1/node/verify?block=N": "free — re-verify",
                    "/v1/node/toll": "free — the toll ledger",
                },
                "price": "0.01 USDC per full verdict, via x402 "
                         "(EIP-3009, Base). The look is free.",
                "operator": operator_wallet(),
                "toll_split": toll_split(),
                "hold_kit": {
                    "name": "MAD HOLD KIT (0.1.8) — the node holds",
                    "proves": [
                        "door-answer health: the supervisor GETs "
                        "this door and demands the node needle — a "
                        "live pid is not proof of life; six straight "
                        "failed probes past the start grace declare "
                        "a wedge and restart the door",
                        "a sentinel watches the supervisor and "
                        "respawns it detached if it falls",
                        "every daemon the kit (re)starts goes out "
                        "orphan-to-init, so no starter's death "
                        "takes the node down",
                        "an uptime recorder probes every 30s and "
                        "keeps the log — `mad node hold` reads "
                        "the receipt back",
                    ],
                    "drill": "FREE — `mad node drill` kills this "
                             "door and times the hold bringing it "
                             "back; the receipt is signed by the "
                             "operator's ERC-8004 key and chained "
                             "onto the node's tape. Proof is the "
                             "free look; the drill is never sold.",
                    "binding": "verdicts and drill receipts are "
                               "signed by the operator identity "
                               "and hash-chained on the tape, "
                               "anchored against MAD's witness "
                               "ledger — a clone gets the code, "
                               "never the identity, the history, "
                               "or the standing."}})
        if path == "/v1/node/status":
            return self._status()
        if path == "/v1/node/verdicts":
            return self._verdicts(q)
        if path.startswith("/v1/node/agent/"):
            return self._agent(path, q)
        if path == "/v1/node/tape":
            return self._tape(q)
        if path == "/v1/node/verify":
            return self._verify(q)
        if path == "/v1/node/toll":
            return self._send(200, {"toll": toll_totals(),
                                    "config": toll_config()})
        return self._send(404, {"error": "no such door: %s" % path})

    def _status(self):
        st = None
        try:
            with open(STAY_STATUS) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = None
        tip = chain_tip()
        last_block = st.get("last_block") if st else None
        if last_block is None:
            try:
                lines = _read_lines_tail(VERDICTS_PATH, 1)
                last_block = (json.loads(lines[-1]).get("block")
                              if lines else None)
            except (ValueError, IndexError):
                last_block = None
        return self._send(200, {
            "node": "mad-node-robinhood", "version": "0.1.8",
            "running": bool(st and st.get("grader", {}).get("alive")),
            "grader_pid": (st or {}).get("grader", {}).get("pid"),
            "supervisor_pid": (st or {}).get("supervisor_pid"),
            "hold": (st or {}).get("hold"),
            "hold_kit": "MAD HOLD KIT (0.1.8): door-answer "
                        "health, a sentinel over the supervisor, "
                        "orphan-to-init restarts, an uptime "
                        "record — `mad node hold` reads it, "
                        "`mad node drill` proves it, free.",
            "restarts": (st or {}).get("grader", {}).get("restarts", 0),
            "last_block": last_block,
            "chain_tip": tip,
            "lag_blocks": (tip - last_block
                           if tip is not None and last_block is not None
                           else None),
            "at_tip": bool(tip is not None and last_block is not None
                           and tip - last_block <= 2),
            "operator": operator_wallet(),
            "paid_door": ("open" if operator_wallet() else
                          "closed — no operator wallet"),
            "price": "0.01 USDC per full verdict via x402"})

    def _verdicts(self, q):
        raw = (q.get("block") or [None])[0]
        try:
            block = int(raw) if raw is not None else None
        except ValueError:
            block = None
        if block is None:
            return self._send(400, {"error": "block is required: "
                                "?block=<number> (free 400 — inputs "
                                "are validated before the gate)"})
        rec = find_verdict(block)
        if rec is None:
            return self._send(404, {"error": "block %d not graded "
                                "by this node (yet)" % block})
        if (q.get("full") or ["0"])[0] not in ("1", "true"):
            return self._send(200, {"verdict": verdict_line(rec),
                                    "full": False,
                                    "note": "the look is free — the "
                                    "full verdict (findings, evidence, "
                                    "signature) is 1c via x402"})
        gate, err = x402_gate(
            self, self._resource(),
            "MAD node verdict: robinhood block %d (%s)"
            % (block, rec.get("verdict")))
        if err:
            status, body, headers = err
            return self._send(status, body, headers)
        append_toll_ledger(block, rec.get("verdict_hash"),
                           gate["settle"].get("payer"),
                           gate["settle"].get("transaction"),
                           toll_split())
        try:
            tape.tape_served(NODE_DIR, block, rec.get("verdict_hash"),
                             gate["settle"].get("payer"),
                             gate["settle"].get("transaction"),
                             toll_split())
        except ValueError:
            pass  # a broken tape never blocks a paid serve
        resp = {"verdict": rec, "full": True,
                "verified": tape.verify_signed_verdict(rec),
                "split": toll_split()}
        return self._send(200, resp, {
            "X-PAYMENT-RESPONSE": _b64_json(gate["settle"]),
            "PAYMENT-RESPONSE": _b64_json(gate["settle"])})

    def _agent(self, path, q):
        agent_id = path.rsplit("/", 1)[-1]
        chain_id = (q.get("chainId") or ["4663"])[0]
        if not agent_id.isdigit():
            return self._send(400, {"error": "agent id must be a "
                                "number (free 400)"})
        summary, full = agent_hits(agent_id, chain_id)
        if (q.get("full") or ["0"])[0] not in ("1", "true"):
            return self._send(200, {"agentId": int(agent_id),
                                    "chainId": int(chain_id),
                                    "hits": summary, "full": False,
                                    "note": "the summary is free — "
                                    "full records are 1c via x402"})
        gate, err = x402_gate(
            self, self._resource(),
            "MAD node agent record: agent %s on chain %s"
            % (agent_id, chain_id))
        if err:
            status, body, headers = err
            return self._send(status, body, headers)
        return self._send(200, {"agentId": int(agent_id),
                                "chainId": int(chain_id),
                                "records": full, "full": True}, {
            "X-PAYMENT-RESPONSE": _b64_json(gate["settle"]),
            "PAYMENT-RESPONSE": _b64_json(gate["settle"])})

    def _tape(self, q):
        try:
            limit = int((q.get("limit") or ["50"])[0])
        except ValueError:
            limit = 50
        entries, chain_ok, broken = tape.read_tape(NODE_DIR)
        return self._send(200, {
            "tape": list(reversed(entries))[:max(0, limit)],
            "entries": len(entries), "chain_ok": chain_ok,
            "broken_at_seq": broken,
            "note": "the tape is public — flags vs outcomes, served "
                    "verdicts, task grades, anchors. Chain recomputed "
                    "on read."})

    def _verify(self, q):
        raw = (q.get("block") or [None])[0]
        try:
            block = int(raw) if raw is not None else None
        except ValueError:
            block = None
        if block is None:
            return self._send(400, {"error": "block is required: "
                                "?block=<number> (free 400)"})
        rec = find_verdict(block)
        if rec is None:
            return self._send(404, {"error": "block %d not graded "
                                "by this node (yet)" % block})
        ok = tape.verify_signed_verdict(rec)
        return self._send(200, {
            "block": block, "verdict": rec.get("verdict"),
            "verdict_hash": rec.get("verdict_hash"),
            "signer": rec.get("signer"),
            "signature": rec.get("signature"),
            "verified": ok,
            "note": "verified from the record alone — the signature "
                    "recovers the signer, the hash matches the "
                    "record. No trust in the messenger needed."})


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="MAD node serve door")
    ap.add_argument("--port", type=int, default=8403)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), NodeHandler)
    print("[node-serve] MAD node door on http://%s:%d — status free, "
          "verdict line free, full verdict 1c x402, payTo %s"
          % (args.host, args.port, operator_wallet() or "UNSET"),
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
