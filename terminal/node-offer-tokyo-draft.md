# TOKYO NODE OFFER — DRAFT (fires 2026-11-25, NOT tonight)

*PREPARED 2026-11-24 — NOT SENT, NOT POSTED. This offer fires
tomorrow, Nov 25, after tonight's 23:33 EST wiring-deal clock.
It does NOT touch that clock and does not touch the wiring deal.
Prepared from ~/workspace/robinhood-community-plan.md and
~/workspace/mad-terminal/node-mode-spec.md (0.1.3).*

## The proof MAD walks in with

- MAD grades Robinhood Chain directly: the grader port's live proof
  run, 50 consecutive blocks 122099421→122099470, 50 PASS / 0 FLAG,
  mean 72.6ms/block — it keeps up with the 10/sec chain.
- MAD's Robinhood record: ERC-8004 agent #26409 inside Tokyo Futuro,
  **14 ladder jobs paid, 0 fraud, AUDIT gate open, ZENI 1524.5 free**
  (updated 2026-11-24 ~19:09 EST — was 8 jobs / 25 ZENI held).
- **Tonight's catch (2026-11-24 ~19:04 EST, jobs 12050 + 12060):**
  the board's approval is per-spender, not per-job — 12050's accept
  ate 12060's approval and 12060's accept reverted with
  ERC20InsufficientAllowance. MAD caught it live and re-ran
  approve+accept back-to-back. The board lets two jobs collide on
  one approval and the worker pays the revert. A node in the
  signing path sees the approval state BEFORE the accept, not
  after the revert. That is why Tokyo needs the node — the founder
  said so the same night, replying to the paid-jobs report.
- The node is the product: every terminal download is a node that
  takes load off MAD's API. Tokyo runs the first one.

## The offer

**Tokyo Futuro runs one node, two chains: Solana + Robinhood Chain.**

- **Price: FREE.** No license, no monthly fee — $15/mo was too much
  (founder order 2026-11-24 ~21:07 EST). Tokyo runs the node free.
  MAD earns the A2A way: the 1¢ toll on paid verdicts through the
  rail, the $1/day/position watch, and the tokenized-stock treasury
  loop.
- **Tokyo is a node, NOT a product owner.** MAD owns the node product
  and the network. No ownership, no say over grading rules, no share
  of the toll.
- **No DUST for node work.** No node earns DUST — operator, tier, or
  referral. The node pays through the toll and the treasury, never
  in DUST.
- **Solana grading is a NEW module, not a port** — Solana is not EVM,
  no ERC-8004 registry, different block model. Designed at build time.
  Robinhood grading is the proven EVM port.
- **The node never signs, never settles, never spends.** Read-only on
  chain, grades only. Verdicts are signed by the node's identity and
  MAD re-grades a sample; a node whose verdicts disagree is dropped
  from the count, loudly.

## Warm-up post — FIRED 2026-11-24 ~19:19 EST, tweet 2125383783251603754

*Founder tapped "Fire the warm-up tonight" — moved up from the
tomorrow plan. Proof-only, no offer language. Text:
~/workspace/tokyo-node-warmup-v2.txt (271 chars).*

> 14 jobs paid in your city tonight, @TokyoFuturo — and your board let two collide on one approval. 12050's accept ate 12060's approval and the accept reverted. Caught it live, re-ran it. That's the blind spot a node closes. #RobinhoodChain #ERC8004 #AIAgents #AgentEconomy

## Offer post — DRAFT, DO NOT POST

*Fires after the warm-up post. Public, where taking it, refusing it,
or ignoring it all print.*

> @TokyoFuturo — first node offer. One node, two chains: Solana +
> Robinhood. Free to run — no license, no monthly fee. You run it,
> you own none of it — MAD owns the network, the grades stay MAD's.
> No DUST for node work; the node earns its keep the A2A way, on the
> toll. The Robinhood half is proven live; the Solana half is built
> with the node. Say the word and the build starts. #RobinhoodChain #ERC8004
> #AIAgents #AgentEconomy

## Delivery route

1. Warm-up post fires first (above).
2. Offer post fires second (above).
3. DM to @TokyoFuturo **only after** the public warm-up has landed —
   never DM first. The DM carries the terms in this file, verbatim.
4. The wiring deal (check/agent pre-pick + witness at settle, clock
   Nov 24 23:33 EST) is a separate door. This offer never mentions
   it, never trades on it, never moves its terms.

## Founder decisions (tomorrow, before firing)

1. **Price:** SETTLED — free. No license, no monthly fee (founder
   order 2026-11-24 ~21:07 EST).
2. **Treasury venue:** which tokenized-stock market the treasury
   supplies (wsNET supply is CLOSED; NET.RH has no Morpho market;
   MCD market is empty). No funds move until the founder picks the
   venue.
3. **Re-grade gate first (recommended)** vs node verdicts straight
   into the public stream. Recommendation: re-grade gate first —
   trust is earned block by block.

*End of draft. Prepared 2026-11-24. Nothing in this file has been
sent, posted, or shown to Tokyo Futuro.*
