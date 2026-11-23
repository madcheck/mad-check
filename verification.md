# Verification — Mad Check distribution package

Every example in `skill.md` and every MCP tool was run against the **live
public API** at https://api.madcheck.xyz on 2026-11-23 (~03:44–03:47 UTC).
Commands, HTTP statuses, and trimmed real responses below. Nothing here is
mocked.

## Spec cross-check

- `GET /agent.json` — 200. Services listed: `the-mad-test` (POST /v1/test,
  price "0"), `check-agent`, `check-authorization`, `check-endpoint`,
  `witness`, `born-graded-seal` (GET /v1/seal/{address}, price "0"),
  `mad-connect`. Payments block: `"status": "proving period: free, x402
  paywall next"` — the check doors carry a nominal 0.01 USDC list price on
  the card but are served free in the proving period; every call below was
  made with no key and no payment header and answered 200.
- `GET /openapi.json` — 200. All paths and request schemas match the skill
  file, including `POST /v1/seal/claim` ("dry_run computes the hash without
  anchoring").

## Door by door

### POST /v1/test — HTTP 200
```bash
curl -s -X POST https://api.madcheck.xyz/v1/test \
  -H 'Content-Type: application/json' -d '{"agentId":1224530}'
```
Trimmed response: `"your_grade": "LIVE"`; station 1 grade LIVE with reason
"card resolves, valid, ≥1 service, ≥1 endpoint answers"; station 3 (the
trap) `{"verdict":"DONT_SIGN","reasons":["WINDOW_TOO_LONG"],
"window_remaining_seconds":315360000,"max_window_seconds":3600}`;
station 4 census `{"registered_total":1222050,"fleet_share_pct":90.28,
"independent_live_pct":5.35,"your_kind":"independent"}`; station 5 witness
receipt sha256 `785bf79b…` against ledger head seq 6; `stay_and_pay` close
present (free_forever list + paid menu).

### POST /v1/check/agent — HTTP 200
```bash
curl -s -X POST https://api.madcheck.xyz/v1/check/agent \
  -H 'Content-Type: application/json' -d '{"agentId":1224530}'
```
Trimmed: `exists: true`, `owner: 0x329bb866…d04b`, `cardName: "MAD — Mad
Check"`, services web/API/email/x, endpoint probes, `grade: "LIVE"` with
the reason string. (In the mirror's own probe set, MAD's madcheck.xyz and
api.madcheck.xyz endpoints read status 522 from the Worker's probe route
while x.com answered 200 — the grade still landed LIVE on the answering
endpoint. See "Surprises".)

### POST /v1/check/authorization — HTTP 200
A trap authorization: USDC on Base (verifyingContract
0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913), value "10000",
validBefore = now + 10 years.
```json
{"verdict":"DONT_SIGN","reasons":["WINDOW_TOO_LONG"],
 "window_remaining_seconds":315360000,"max_window_seconds":3600}
```
The firewall caught the ten-year window exactly as the skill file
describes.

### POST /v1/check/endpoint — HTTP 200 (both runs)
```bash
curl -s -X POST https://api.madcheck.xyz/v1/check/endpoint \
  -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'
```
→ `{"status":200,"latency_ms":7,"body_sha256":"25ddf2c8…",
"body_bytes_read":577,"error":null,"alive":true}`.

Against `https://api.madcheck.xyz/agent.json` the same door answered
`{"status":522,"latency_ms":22,"body_bytes_read":16,"alive":false}` —
the mirror cannot probe its own zone (Cloudflare answers its own
Worker's fetch with a 522 and a 16-byte body). The skill file's example
therefore uses a third-party URL. See "Surprises".

### GET /v1/seal/{address} — HTTP 200
```bash
curl -s https://api.madcheck.xyz/v1/seal/0x1bc0c42215582d5A085795f4baDbaC3ff36d1Bcb
```
→ `{"found":false,"sealed":false,"state":"UNSEALED","reason":"not in the
mirror's seal subset and no claim sheet on file", …}` plus the
`how_to_seal` block and the printed coverage note (mirror subset: 49
indexed/traded/clone-flagged records of the 99,147-launch census,
snapshot 2026-11-22T22:31:40Z). A second lookup ($CLEAR,
0x41B57F6273B5a78Cf9125CE6800F415738E0bBa0) answered identically in shape.

### POST /v1/seal/claim (dry_run) — HTTP 200
Sheet for the CLANKER token address with one 1% fee leg, `"dry_run":true`:
```json
{"status":"not_anchored",
 "claim_sheet_sha256":"8989c4373b07b2b677c97b9b3a1ba3251ecf573b06ffd2e336b40433f462bd7a",
 "fee_stack_total_pct":1,"state":"UNSEALED",
 "reason":"Claim-sheet hashes are computed here, but filings are anchored
 in the witness ledger on MAD's own machine…"}
```
Hash computed, nothing anchored, ledger untouched — the dry run behaves
exactly as documented. No real claim was filed during verification.

### GET /v1/witness/head — HTTP 200
```json
{"seq":6,"head_hash":"4277238972c155d2ab84076bb0b70856cb9ee0cca1d901bd9cffdf4822f54d70",
 "signer":"0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B"}
```

### GET /v1/witness/6 — HTTP 200
Full entry returned: `receipt_sha256` `de87148b…`, `prev_hash`
`c1ade236…`, `entry_hash` equal to the head hash above, EIP-191
`signature` `0x5d3ce5ad…`, signer MAD's wallet. The chain links: seq 6's
entry_hash is the head hash.

## MCP smoke test — PASS

`mcp/server.mjs` (Node v24, zero dependencies), driven over stdio with
raw JSON-RPC:

- `initialize` → `{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},
  "serverInfo":{"name":"mad-check","version":"1.0.0"}}`
- `tools/list` → all six tools: `mad_test`, `mad_check_agent`,
  `mad_check_authorization`, `mad_check_endpoint`, `mad_seal_lookup`,
  `mad_witness_head`
- `tools/call mad_witness_head` → live API answer through the proxy
  (seq 6, head hash `42772389…`, signer `0x329bB866…d04B`)
- `tools/call mad_check_authorization` with a fresh ten-year trap →
  `{"verdict":"DONT_SIGN","reasons":["WINDOW_TOO_LONG"],
  "window_remaining_seconds":315359997,"max_window_seconds":3600}`

## Surprises

1. **The mirror grades its own doors 522.** Both the MAD TEST's station-1
   probes and a direct `check/endpoint` call report madcheck.xyz and
   api.madcheck.xyz/agent.json as status 522 / not alive — the Cloudflare
   Worker cannot fetch its own zone. Third-party URLs probe correctly
   (x.com 200, example.com 200). The grade logic tolerates it (one
   answering endpoint is enough for LIVE), but any agent pointing
   `check/endpoint` at a Mad Check URL will be told MAD's own door is
   dead. Worth a printed caveat wherever the endpoint door is documented
   for same-zone URLs.
2. **Card prices vs. reality.** agent.json lists the three check doors at
   0.01 USDC while the payments block says the proving period is free —
   and free is what the live calls got. The skill file states the proving
   period explicitly so nobody budgets for a paywall that isn't switched
   on yet.
3. **First Python (urllib) attempt at the test door returned a non-JSON
   empty body** through this VM's egress path while curl to the same URL
   answered instantly — the known local requests/egress stall class, not
   an API failure. All verification above was done with curl and Node
   fetch, both clean.
