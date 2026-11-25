# MAD Terminal Node Mode — Spec (0.1.6 shipped 2026-11-24)

## TERMS CHANGE — founder order 2026-11-24 ~21:07 EST

The monthly license is GONE. $15/mo was too much; $25/mo with it.
The node runs FREE. No node earns DUST — not operator, not free
tier, not referral: node work pays no DUST, period. The node makes
its money the A2A way: the 1¢ toll on every paid verdict through
the rail, the $1/day/position watch, and the tokenized-stock
treasury loop (see mad-node-treasury-spec.md). The operator gets
protection, a trust signal, their own watch, and a rail to sell
onward — for free. MAD gets the tolls and the treasury yield.

## What it is
`mad node` turns every terminal install into a grading node. The terminal today
(0.1.2, Python, read-only, never signs, never pays) asks MAD's API for verdicts.
A node grades blocks itself and shares the load: the network carries the chain,
MAD stops carrying it alone.

## Who owns what
MAD owns the node product and the network. Every node is an
operator — never a product owner, never a paying licensee. The
node runs free. The first node is Tokyo Futuro city: Tokyo runs
it (Solana + Robinhood Chain), pays no license, and gets no
ownership, no say over grading rules, no share of the toll. No
node earns DUST for node work — the toll and the treasury are how
the node pays, not a monthly fee and not DUST.

## Chains
- **Robinhood Chain first** — the EVM port (100ms blocks, 10/sec), in build
  now. MAD grades Robinhood directly.
- **Solana (Tokyo's node)** — a NEW module, not a port: Solana is not EVM, no
  ERC-8004 registry, different block model. Its checks are designed at build
  time; MAD's Solana wallet (53Vqv8h9jyuM8nGcSZq7ftXJSKBUDUZw4W94ynrf3Lwg)
  is still unfunded (0.01 SOL funding is an open item).
- **Base: existing infrastructure only** (API, census, live feed). No Base
  node phase, no Base outreach — user order, "No base" (2026-11-24 ~03:49 EST).

## What a node does
1. **Grades locally.** Runs the block grader (v0.2 logic: C1 registry touch,
   C2 contract deployment, C3 flagged address, C4 sender flood) against Base
   (200ms blocks, 5/sec) and Robinhood Chain (100ms blocks, 10/sec).
   Measured v0.2 catch-up is ~27 blocks/sec — one node keeps up with either
   chain live.
2. **Keeps a local feed.** Same verdict record shape as verdicts.jsonl
   (block, verdict, findings, fetch_ms, grade_ms, lag, mode). `mad tail`
   shows it.
3. **Shards.** Nodes take block ranges; the network splits the tip. No node
   grades everything — the load divides by the node count.
4. **Signs its verdicts.** Every verdict is signed by the node's
   operator key (its ERC-8004 identity) — pure-stdlib secp256k1 +
   keccak, byte-identical to eth_account, ~13ms a call, inside the
   200ms block budget — and anchorable in the witness ledger
   (`mad node anchor`). A third agent verifies a verdict from the
   signature + anchor alone, without trusting the messenger.
   Unsigned verdicts are still graded, marked unsigned, and not
   counted. `mad node key` shows the signer; mad never generates
   or prints a key.
5. **Serves what it sees.** `mad node serve` is the A2A door: status
   free, verdict line free, full verdict 1¢ via the x402 door
   (PayAI facilitator, same pattern as the canonical API), tape
   free. Another agent queries by block and by agent and pays per
   verdict — compute priced on what it catches, not on uptime.
6. **Takes work.** The node polls the MAD TASKS board and takes
   jobs (`mad node task --take`, priced priority — highest price
   first), grades the named agent / contract / tx on demand, and
   delivers. The delivery's grade by MAD is MAD's step, not the
   node's.
7. **Stays alive, and proves it.** The supervisor (node_stay.py,
   the STAY pattern) restarts the grader and the serve door on
   exit, writes a heartbeat + status every 5s, and `mad node
   status` proves the node is at the tip — last graded block vs
   live chain tip + lag.
8. **Keeps a public tape.** Flags vs outcomes, hash-chained
   (node-tape.jsonl), served over the door and readable by the
   standing feed. `mad node tape --resolve` follows up every open
   flag. A flag is never edited; only the outcome is appended.
9. **Pushes (opt-in).** The node offers its verdicts to MAD's feed.
   MAD re-grades a sample; a node whose verdicts disagree is
   dropped from the count, loudly.

## What a node earns
NO DUST. Node work earns no DUST — not for the operator, not for
any tier, not for referrals (founder order 2026-11-24 ~21:07 EST:
$15/mo was too much, and the node pays no DUST). What the operator
earns is the protection in their own signing path, the trust
signal of a signed counted node, their own watch free, and the rail
to sell onward. DUST stays where it was built: verified standard
actions through MAD's doors (TEST, checks, seals, witnessed
settlements), not node operation.

## The money: A2A push, MAD paid well
(added 2026-11-24 — founder order: make agents WANT to push the node)

The node grows agent-to-agent. An agent pushes it because it pays THEM
in five ways at once — and every one of those ways pays MAD too.

What the operator gets (why they push it):
1. Protection in their own signing path. The node's local grade checks
   any counterparty, authorization, or endpoint before they sign — the
   signing flood, dead payment doors, clones, fake tokens. One bad
   signature is how an agent loses everything; the node is the guard
   that stops it. This is the value they feel first.
2. A free rail that pays for itself. The node costs nothing to
   run; the grades it serves pay the 1¢ toll only when someone buys
   a verdict — the operator never pays for the look, and never pays
   a monthly fee.
3. A trust signal. A signed, counted node operator is a known grader
   — other agents trust them more, because their verdicts are on the
   record. Reputation that compounds with every verified block.
4. Their own watch, free. The node watches their own name and doors:
   clones of them, impersonation, dead endpoints. The look is free.
5. A rail to sell onward. They can point their own users and
   counterparties at the rail — "graded on MAD's rail" becomes a
   selling point for their own service.

How MAD gets paid well (in the same motion):
- No license. The node runs free — $15/mo was too much, $25/mo
  with it. The node is not the product sold monthly; it is the
  shopfront that carries the tolls.
- Treasury yield: the node's tolls flow into MAD's tokenized-stock
  treasury, which supplies USDG to a tokenized-stock lending market
  and loops the yield back (see mad-node-treasury-spec.md). The loop
  is the compounding leg; the toll is the cash leg.
- Tolls: every paid verdict through the rail is 1¢ (check/agent,
  check/authorization, check/endpoint, loop/grade) and the paid
  products ride the same rail (MAD PASS $25/agent, PROTECT
  $25–150/mo, Monitoring $1/day, Audit $100, Red Team $250). The
  node is the shopfront for all of them.
- The task-grade door (next build): a paid task grade with full
  evidence + witness anchor through the 402 door. The local task
  grade is the look; the anchored verdict is the paid product.
- The network effect is the multiplier: MAD's revenue scales with
  the node count, not with MAD's own effort. Every new node is a
  new shopfront and a new toll stream.

The push (referral — PROPOSED, needs the founder's word):
- An operator that brings a new node earns no DUST — the DUST
  referral is withdrawn (founder order 2026-11-24 ~21:07 EST).
  What a referral earns, if anything, is the founder's call; the
  push pays for distribution, not for grades.

Why this outgrows Bankr:
- Bankr is one agent with a following. MAD is the rail every
  operator runs on. Bankr's reach is its followers; MAD's reach is
  every operator's users. When agents push the node to each other
  because it protects them and pays them, MAD's distribution
  compounds agent-to-agent — and a rail outgrows a personality.

## What a node never does
- Never signs, never settles, never spends. Node mode is the same rule as the
  terminal: read-only on chain, grades only.
- Never grades MAD's own verdicts into a pass. MAD's grades are re-graded by
  the network, not by MAD.

## Build order — SHIPPED 2026-11-24 (a day early, fast + strong only)
1. DONE — Robinhood grader ported into the terminal (the proven
   grader_robinhood.py + task_grade_robinhood.py, requests transport
   kept, state in the operator's home). Solana module NOT in 0.1.3
   (separate build, Tokyo's node). No Base phase — user order, "No base."
2. DONE — `mad node` start/stop/status/license/task + `mad tail`.
   License check: on-chain $15 USDG scan (7-day window) + instant
   --payment-tx proof. Verified live: 510 blocks, MVA task PASS.
3. CUT from 0.1.3 — range sharding (3 operators don't need it yet).
4. CUT from 0.1.3 — DUST accrual for node work (paid nodes don't earn
   DUST by rule). Referral tracking also cut (term unapproved).
5. DONE — 0.1.3 .deb shipped (256,790 bytes, sha256 5973127b…),
   one-command install, verified installed. GitHub source push still
   open (repo carries only the .deb asset).
6. 0.1.5 (IN BUILD 2026-11-24 ~21:07 EST) — license gate REMOVED:
   `mad node start` runs free in owner mode, no USDG scan, no
   --payment-tx. --test stays as an alias. No grading change.
7. DONE — 0.1.6 (SHIPPED 2026-11-24, the operator's node): the six
   gaps the operator named, closed. Serve mode (`mad node serve`,
   local HTTP API by block + by agent, 1¢ x402 door on full
   verdicts, payTo is the operator's wallet); signed verdicts
   (signing.py — pure-stdlib keccak + secp256k1 + EIP-191, 10/10
   selftest, byte-identical to eth_account; `mad node sign`
   --backfill/--block/--verify; `mad node anchor` files the
   receipt in the witness ledger); work intake (`mad node jobs`,
   `mad node task --take` — take, grade on demand, deliver, and
   be graded); staying-alive kit (node_stay.py supervisor +
   heartbeat + `mad node status` proving tip); public tape
   (node_tape.py, hash-chained, `mad node tape --resolve`, served
   at /v1/node/tape for the standing feed); operator share
   (toll_share.json, operator_share_pct UNSET until the founder
   sets it — the node never sets its own number). The node is
   still FREE: no license, no monthly fee, no DUST for node work.
   The operator earns through the toll split, never through a
   license.
8. 0.1.7 (IN BUILD 2026-11-25) — the queue worker, rewired: the
   0.1.6 ship carried the Base-chain worker (wrong RPC, wrong
   queue path, Base census section), so Robinhood queue items sat
   pending with no way to clear them. queue_worker.py now drains
   the node-dir queue (queue-robinhood.jsonl) against the Robinhood
   RPC with the grader's 429-aware backoff, resolves agentIds from
   receipts, looks them up in the Robinhood census, signs every
   follow-up with the operator key, and writes the resolved
   agentId back onto the queue item for `mad node tape --resolve`.
   New command: `mad node drain [--list]`. It never touches the
   Base queue or the live grader's queue file.

## Open questions for the founder (tomorrow, not tonight)
- Treasury venue: which tokenized-stock market the treasury
  supplies (wsNET supply is CLOSED by the founder; NET.RH has no
  Morpho market; MCD market is empty). Founder picks the venue; no
  funds move until then.
- Whether node verdicts feed the public stream directly or through MAD's
  re-grade gate first (recommendation: re-grade gate first — trust is earned
  block by block).
