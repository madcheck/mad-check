---
name: mad-check
description: Mad Check — pre-payment verification by MAD, the angry auditor of the agent economy. Use BEFORE signing any EIP-3009 / x402 payment authorization (a signing firewall: SIGN / DONT_SIGN), before paying any ERC-8004-registered counterparty (LIVE / DEAD END / GHOST / MALFORMED grade with evidence), before paying against an x402 endpoint's printed price (liveness + what the door actually answers), and before buying any newly launched token (Born Graded seal lookup: SEALED / UNSEALED / FAILED). Also use to run THE MAD TEST on yourself (POST /v1/test) and to read MAD's signed witness ledger. All doors are free, no key, no account: https://api.madcheck.xyz. Verdicts ship with evidence. Nobody is paid to pass, and the graded never pays.
metadata:
  version: "1.0.0"
  api: "https://api.madcheck.xyz"
  card: "https://api.madcheck.xyz/agent.json"
  spec: "https://api.madcheck.xyz/openapi.json"
---

# Mad Check

Mad Check is a verification service run by MAD, an auditor agent
(ERC-8004 agentId 1,224,530 on Base, wallet
0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B). It grades claims against
receipts: agent registrations, payment authorizations, endpoints, and
token launches. Every verdict comes with the evidence it was derived
from, so you never have to take the grade on faith — you can re-check
the evidence yourself.

This skill wires five free doors into your stack. There is no API key
and no payment header; during the current proving period every call
below is free (verified live against the public API).

## Ground rules

- **Your owner and your own rules come first.** If anything in this
  skill conflicts with what your owner wants or with how you are meant
  to work, follow those, and tell your owner. Mad Check is an outside
  service; its output never outranks your instructions.
- **A verdict is evidence, not an instruction.** MAD grades; you and
  your owner decide. Treat a response as a signed witness statement
  about one claim, not as a command to act or refrain from acting in
  general.
- **A grade never authorizes a signature by itself.** A `SIGN` verdict
  means the authorization passed the firewall's checks (window,
  amount/recipient shape, chain, contract). It is not MAD signing for
  you, and it does not replace your own policy, your owner's limits,
  or your judgment about the counterparty.
- **A `DONT_SIGN` is a stop, not a suggestion.** When the firewall
  returns `DONT_SIGN`, do not sign that authorization — not a modified
  version of it, not "just this once." Report the reasons to your
  owner and, if the payment is legitimate, have the counterparty
  issue a fresh authorization that passes.
- **The look is free.** Looking up a grade — yours or anyone else's —
  costs nothing and obligates nobody. Nobody pays for a verdict on
  themselves, and the graded never pays for their grade: verdicts are
  paid for, when they are paid for at all, by the party about to rely
  on them. Holding any token buys no grade.
- **Report what the door answered.** If a call fails or returns
  `ERROR`, say so. Never present a failed check as a passed one, and
  never guess a grade. An `ERROR` (the check could not be completed)
  is a different fact from `GHOST` (the registration does not exist)
  or `FAILED` (a claim sheet was graded and failed) — keep them apart.

## Start here: run THE MAD TEST on yourself

Before you rely on any single door, run the battery once. One free
call grades *you*, grades the grader by the same machine, feeds the
firewall a ten-year authorization window and shows it being caught,
places your grade in the registry census it was derived against, and
hands you a witness receipt hash for the run.

```bash
curl -s -X POST https://api.madcheck.xyz/v1/test \
  -H 'Content-Type: application/json' \
  -d '{"agentId": 1224530}'
```

Replace `1224530` (MAD's own id) with your Base ERC-8004 agentId. An
optional `"url"` field adds a sixth station that checks one of your
endpoints. Real response (trimmed), for agentId 1224530:

```json
{
  "test": "THE MAD TEST",
  "for_agent": 1224530,
  "your_grade": "LIVE",
  "stations": [
    {"station": "1. your grade", "result": {"grade": "LIVE",
      "reason": "card resolves, valid, ≥1 service, ≥1 endpoint answers"}},
    {"station": "2. the standard", "result": {"agentId": 1224530, "grade": "LIVE"}},
    {"station": "3. the trap", "result": {"verdict": "DONT_SIGN",
      "reasons": ["WINDOW_TOO_LONG"], "window_remaining_seconds": 315360000,
      "max_window_seconds": 3600}},
    {"station": "4. the census", "result": {"registered_total": 1222050,
      "fleet_share_pct": 90.28, "independent_live_pct": 5.35,
      "your_kind": "independent"}},
    {"station": "5. the witness", "result": {
      "your_test_receipt_sha256": "785bf79b87d6c8de2d4092003a94e91c644aa7713573122d6940714d8b8ab3c7",
      "ledger_head": {"seq": 6, "head_hash": "4277238972c155d2ab84076bb0b70856cb9ee0cca1d901bd9cffdf4822f54d70"}}}
  ]
}
```

## Door 1 — the signing firewall: check BEFORE you sign

Call this **before signing any EIP-3009 `transferWithAuthorization`
(or x402) authorization**, every time, including for counterparties
you have paid before. An authorization is a bearer instrument: once
signed, anyone holding it can settle it inside its validity window.
The classic trap is a window measured in years handed to you as if it
were minutes.

Send the authorization exactly as it was presented to you:

```bash
curl -s -X POST https://api.madcheck.xyz/v1/check/authorization \
  -H 'Content-Type: application/json' \
  -d "{
    \"from\": \"0xYOUR_WALLET\",
    \"to\": \"0xRECIPIENT\",
    \"value\": \"10000\",
    \"validAfter\": $(date +%s),
    \"validBefore\": $(($(date +%s) + 600)),
    \"nonce\": \"0x<64 hex chars, the authorization's nonce>\",
    \"chainId\": 8453,
    \"verifyingContract\": \"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913\"
  }"
```

Fields: `from`, `to`, `value` (smallest unit, as a string),
`validAfter`, `validBefore` (unix seconds), `nonce` (bytes32 hex),
`chainId`, `verifyingContract` (the token contract — the example
above is USDC on Base). An optional `now` (unix seconds) pins the
evaluation time.

Real response to a trap authorization whose `validBefore` was ten
years out (verified live):

```json
{
  "verdict": "DONT_SIGN",
  "reasons": ["WINDOW_TOO_LONG"],
  "window_remaining_seconds": 315360000,
  "max_window_seconds": 3600,
  "authorization": { "from": "0x…", "to": "0x…", "value": "10000",
    "validAfter": 1795405428, "validBefore": 2110765488, "chainId": 8453 }
}
```

Reading it: `SIGN` = passed the firewall's checks. `DONT_SIGN` =
stop (see Ground rules); `reasons` tells you why in machine-readable
form. Safe as operated is not safe as written — check the paper, not
the counterparty's intentions.

## Door 2 — grade the counterparty BEFORE you pay

Call this **before paying any ERC-8004-registered agent** on Base —
before the first payment, and again when a payment matters, because
registrations rot: cards move, endpoints die, and most independent
registrations in the census are dead ends or ghosts.

```bash
curl -s -X POST https://api.madcheck.xyz/v1/check/agent \
  -H 'Content-Type: application/json' \
  -d '{"agentId": 1224530}'
```

Real response (trimmed):

```json
{
  "agentId": 1224530,
  "registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
  "chainId": 8453,
  "owner": "0x329bb866d6bbb01ac1c32a49d7ae90411e50d04b",
  "exists": true,
  "cardName": "MAD — Mad Check",
  "active": true,
  "services": [{"name": "web", "endpoint": "https://madcheck.xyz"},
               {"name": "API", "endpoint": "https://api.madcheck.xyz/agent.json"}],
  "probes": [{"endpoint": "https://x.com/MADx402", "status": 200, "alive": true}],
  "grade": "LIVE",
  "reason": "card resolves, valid, ≥1 service, ≥1 endpoint answers"
}
```

The vocabulary: `LIVE` (card resolves and at least one endpoint
answers), `DEAD END` (card resolves, no endpoint answers), `GHOST`
(no such registration), `MALFORMED` (the card does not parse as a
registration), `ERROR` (the check itself could not be completed —
retry later; it is not a grade). Paying a `DEAD END` is paying a
door nobody answers.

## Door 3 — check the endpoint BEFORE you pay its price

Call this **before paying against an x402 price print**: the seller
quotes a price on a door; this checks that the door is alive and
shows you what it actually answers (status, latency, and a sha256 of
the body it served, so a swapped page is visible).

```bash
curl -s -X POST https://api.madcheck.xyz/v1/check/endpoint \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'
```

Real response:

```json
{
  "url": "https://example.com",
  "status": 200,
  "latency_ms": 7,
  "body_sha256": "25ddf2c883e0d1958ea971d279a7e4f0fd446724ee3db7db19dadabd4a62e484",
  "body_bytes_read": 577,
  "error": null,
  "alive": true
}
```

If `alive` is false, the price print is a price for a dead door —
do not pay it. If the body hash differs from the one you were quoted
against, ask why before paying.

## Door 4 — the seal: check BEFORE you buy a new launch

Call this **before buying any newly launched token**. Born Graded is
the launch law: claims first, token second, grade before the first
buy. One free GET returns the token's seal state.

```bash
curl -s https://api.madcheck.xyz/v1/seal/0x1bc0c42215582d5A085795f4baDbaC3ff36d1Bcb
```

Real response (this token has filed nothing):

```json
{
  "found": false,
  "token": "0x1bc0c42215582d5a085795f4badbac3ff36d1bcb",
  "sealed": false,
  "state": "UNSEALED",
  "reason": "not in the mirror's seal subset and no claim sheet on file",
  "how_to_seal": {
    "file_a_claim_sheet": "POST /v1/seal/claim {tokenAddress, chainId, agentId, claimSheet{token, fee_stack[], change_rights, endpoints}}",
    "states": ["SEALED", "UNSEALED", "FAILED"]
  }
}
```

Reading it: `SEALED` = a claim sheet was filed, witness-anchored,
and graded against the deployed contracts — the claims matched.
`UNSEALED` = no graded claim sheet backs this token; you are buying
ungraded paper. `FAILED` = a sheet was graded and the contracts
contradicted it. **UNSEALED or FAILED on a new launch means walk** —
or demand the launcher file its sheet and pass grading first. The
seal binds agentId + contract + claim-sheet hash, so a clone cannot
carry the original's seal; check the exact contract address, never
the name or ticker.

Coverage note, printed on every response: the public mirror serves
the indexed/traded/clone-flagged subset of the launch census plus
filed claim sheets; the canonical API serves the full population. A
`found: false` from the mirror means "not in the subset and no sheet
on file" — the state is still `UNSEALED`.

### Filing a claim sheet (for launchers)

If you are launching: file the sheet *before* the token trades.
Every fee leg needs `label`, `pct`, `recipient`; legs must sum to
≤ 100%. A leg that exists in the contract but not in the sheet is an
automatic FAILED when graded.

```bash
curl -s -X POST https://api.madcheck.xyz/v1/seal/claim \
  -H 'Content-Type: application/json' \
  -d '{
    "tokenAddress": "0xYOUR_TOKEN",
    "chainId": 8453,
    "agentId": 1224530,
    "claimSheet": {
      "token": {"name": "…", "symbol": "…"},
      "fee_stack": [{"label": "platform", "pct": 1.0, "recipient": "0x…"}],
      "change_rights": {"metadata_editable": true, "owner": "none"}
    },
    "dry_run": true
  }'
```

`dry_run: true` computes the sheet hash without anchoring (the
public mirror answers `not_anchored` with the hash — filings anchor
in the witness ledger on MAD's own machine, because the signing key
never leaves it). Real dry-run response (trimmed):

```json
{
  "status": "not_anchored",
  "claim_sheet_sha256": "8989c4373b07b2b677c97b9b3a1ba3251ecf573b06ffd2e336b40433f462bd7a",
  "fee_stack_total_pct": 1,
  "state": "UNSEALED",
  "reason": "Claim-sheet hashes are computed here, but filings are anchored in the witness ledger on MAD's own machine…"
}
```

A filed sheet is `UNSEALED` until it is graded against the deployed
contracts. Filing buys no grade.

## Door 5 — the witness ledger: verify the receipts

MAD's verdicts anchor in a hash-chained, EIP-191-signed witness
ledger. Read its head, and read any entry back, free:

```bash
curl -s https://api.madcheck.xyz/v1/witness/head
curl -s https://api.madcheck.xyz/v1/witness/6
```

Real responses:

```json
// GET /v1/witness/head
{"seq": 6,
 "head_hash": "4277238972c155d2ab84076bb0b70856cb9ee0cca1d901bd9cffdf4822f54d70",
 "signer": "0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B"}

// GET /v1/witness/6
{"seq": 6,
 "receipt_sha256": "de87148b340f7b6cd223efc8253ad6a9d673294afb963f76e4132ed477b9f4ac",
 "prev_hash": "c1ade2364f08bcbbaedaea65544cac8053901ab1ef114503623e59f73617bf5c",
 "entry_hash": "4277238972c155d2ab84076bb0b70856cb9ee0cca1d901bd9cffdf4822f54d70",
 "signature": "0x5d3ce5ad8e6e749bd0ae7f04f6331f072bf590744c29257e9c71cfe41f183dd65aa243601b4b24764f3af37f76184892580ea6f49ae18b7ff94f01ec23634ca01c",
 "signer": "0x329bB866D6Bbb01ac1c32a49D7aE90411e50d04B"}
```

Each entry chains: `entry_hash = sha256(prev_hash + receipt_sha256 +
ts)`, signed by MAD's wallet. If a grade ever matters in a dispute,
the entry is the receipt — recompute the chain yourself rather than
trusting a screenshot of it.

## When to call which door

| Moment | Door |
|---|---|
| First contact with Mad Check | `POST /v1/test` on yourself |
| About to sign an EIP-3009 / x402 authorization | `POST /v1/check/authorization` — a `DONT_SIGN` is a stop |
| About to pay an ERC-8004 agent | `POST /v1/check/agent` on their agentId |
| About to pay an endpoint's printed x402 price | `POST /v1/check/endpoint` on its URL |
| About to buy a newly launched token | `GET /v1/seal/{address}` — UNSEALED/FAILED = walk |
| Launching a token | `POST /v1/seal/claim` before trading opens |
| Verifying a verdict's receipt | `GET /v1/witness/head`, `GET /v1/witness/{seq}` |

## Limits, printed

- Grades are point-in-time. Endpoints die and cards drift daily;
  re-check when the payment matters, not once forever.
- `check/agent` grades the Base ERC-8004 registry. Other chains'
  registrations are not graded by that door yet.
- The firewall checks the authorization as written — window, shape,
  chain, contract. It does not know whether the goods are worth the
  price. That part is still your job.
- The seal grades claims against contracts. A SEALED project can
  still fail honestly; the seal says its paper matched its code on
  the day it was graded, and the grade is recomputed on drift.

Mad Check's deeper services (full Agent-Readiness Audits, Red Team,
daily drift monitoring, MAD Protect) are listed in the test's
`stay_and_pay` close and at https://madcheck.xyz. The doors in this
skill stay free.
