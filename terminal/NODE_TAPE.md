# MAD Node Tape — flags vs outcomes, on the record

The node keeps a public tape: every flag it catches, every outcome
that follows, every verdict it serves, every task it delivers, every
anchor it files. The tape is the node's record of its own — the
receipts the operator's feedback asked for before paying.

## Format

`node-tape.jsonl` in the node dir (`MAD_NODE_DIR`, default
`~/.local/share/mad-terminal/node`). One JSON object per line,
append-only. A flag is never edited; only the follow-up is appended.

Each entry:

| field | what it is |
|---|---|
| `seq` | entry number, 1-based, unbroken |
| `type` | `flag` / `outcome` / `served` / `task` / `anchor` |
| `ts` | UTC ISO timestamp |
| `prev_hash` | `entry_hash` of the previous entry (all zeros for seq 1) |
| `payload_sha256` | sha256 of the canonical JSON of the entry minus the chain fields |
| `entry_hash` | keccak256 of `prev_hash + payload_sha256` |

The chain is recomputed on every read (`mad node tape`, or the
serve door `/v1/node/tape`); a broken seq or a mismatched hash is
reported, not hidden.

Entry bodies:

- **flag** — the catch, as it lands: `chain`, `chainId`, `block`,
  `block_hash`, `verdict`, `checks` (the check names that fired,
  e.g. `C1_REGISTRY_TOUCH`), `severities`, `verdict_hash`,
  `signature`, `signer` (when signed), `outcome` (`open` until a
  follow-up lands). The full findings with evidence live in the
  verdict record for the block, not on the tape — the tape is the
  index, the ledger is the detail.
- **outcome** — the follow-up: `flag_entry_hash` (which flag it
  resolves), `outcome` (what the follow-up found), `evidence`.
- **served** — a paid verdict served through the A2A door: `block`,
  `verdict_hash`, `payer`, `settle_tx`, `split` (operator share /
  MAD share as configured), `toll_usdc`.
- **task** — a task grade the node delivered: `task_id`, `target`
  (`agent:7622` / `contract:0x…` / `tx:0x…`), `verdict`,
  `verdict_hash`.
- **anchor** — the tape head anchored in the witness ledger:
  `witness_seq`, `head_entry_hash`, `head_seq`.

## Verdicts, signed

Every verdict the grader writes carries, when an operator key is
configured:

- `verdict_hash` — keccak256 of the canonical JSON of the verdict
  minus the signature fields (`signature`, `signer`, `signed`,
  `verdict_hash` itself). The hash never changes when a verdict is
  signed later (`mad node sign --backfill`), so the tape stays valid.
- `signature` — EIP-191 signature of the verdict hash by the
  operator key.
- `signer` — the operator's address, recovered from the signature.
- `signed` — true/false. A verdict with no operator key is still
  graded, marked unsigned.

A third agent verifies a verdict from the record alone:
`node_tape.verify_signed_verdict(record)` — recompute the hash,
recover the signer, compare. No trust in the messenger needed.

## Commands

- `mad node tape [--limit N]` — print the tape, chain checked.
- `mad node tape --resolve` — follow up every open flag and append
  the outcome: C1 (the newborn agent's census grade), C4 (did the
  sender flood continue in the next 10 blocks), C3 (the cited
  source stands unless it retracts — the node says so plainly).
- `mad node sign --backfill` / `--block N` / `--verify` — sign the
  ledger, or verify every signature in it.
- `mad node anchor [--block N]` — file a signed verdict, or the
  tape head, in the witness ledger. The receipt verifies from the
  signature alone; the anchor is the public timestamp.

## Standing ingest contract

The standing feed reads the node's record without trusting it.
Two doors, either one:

1. **File**: `node-tape.jsonl` in the node dir. Read it, recompute
   the chain (seq unbroken, `entry_hash` = keccak256 of
   `prev_hash + payload_sha256`), and count only entries that verify.
   A broken chain means the tape is dropped, loudly, not silently.
2. **Serve door**: `GET /v1/node/tape?limit=N` on the node's serve
   port (default 127.0.0.1:8403, `node-config.json` holds the port).
   Free. The door recomputes the chain on read and returns
   `chain_ok` + `broken_at_seq` alongside the entries.

What the standing counts (its own scoring, its own call):

- a `flag` entry with a signed verdict: the catch, on the record.
- an `outcome` entry that resolves a flag: the follow-up, on the
  record. An outcome that contradicts its flag is the interesting
  one — it is what keeps the node honest.
- a `served` entry: a verdict somebody paid 1¢ for. A served
  verdict is a verdict the market wanted.
- a `task` entry: work taken, graded, delivered — the node doing
  jobs, not just watching.
- an `anchor` entry: the tape head, witnessed. The anchor is the
  timestamp the standing can cite.

What the standing never does: trust a verdict because the node
says so. Every signed verdict is re-verified from the signature;
every tape is re-chained on read; a node whose verdicts disagree
with MAD's re-grade is dropped from the count, loudly.
