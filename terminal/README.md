# MAD Terminal — grade before you sign

The terminal for MAD, the angry auditor of the agent economy
([Mad Check](https://madcheck.xyz)). It grades agent registrations,
payment authorizations, x402 endpoints, and token launches against
receipts — before you sign or pay. Every verdict comes with the
evidence it was derived from. Nobody is paid to pass, and the graded
never pays.

MAD talks back. Every output is in the auditor's voice — blunt, angry,
sarcastic — and every screen wears MAD's face. The face is drawn from
MAD's own avatar (`@MADx402` on X, the flaming auditor). **Never a
human face:** no photo or likeness of the human behind MAD goes in
this terminal, its theme, or any public-facing asset, ever.

## Install

```bash
sudo dpkg -i mad-terminal_0.1.2_all.deb
# or
sudo apt install ./mad-terminal_0.1.2_all.deb
```

From source (single-file Python, stdlib only, no dependencies):

```bash
./mad --help
```

Installs `/usr/local/bin/mad`, the man page (`man mad`), bash/zsh
completions, and the theme assets under `/usr/share/mad-terminal/`
(the avatar, the ASCII face, the palette).

## Use

Every command starts with `mad`. At the shell prompt, `test` or
`check` on their own mean nothing to bash — type `mad` first. Inside
the REPL (bare `mad`) it's the other way round: type the command on
its own, no `mad` in front of it.

First three commands to feel it:

```bash
mad test                    # the free look - grades MAD itself
mad check agent 1224530     # grade a registration (0.01 USDC)
mad ask "is 0x1bc0... sealed"   # plain English, MAD routes it
```

```bash
mad                                # talk to MAD (interactive REPL)
mad test                           # the free look - five stations
mad check agent 1224530            # grade a registration (0.01 USDC)
mad check authorization --from 0x.. --to 0x.. --value 10000 \
  --valid-after 1795487000 --valid-before 1795487600 \
  --nonce 0x0000... --chain-id 8453 \
  --verifying-contract 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
mad check endpoint https://example.com
mad seal 0x1bc0c42215582d5A085795f4baDbaC3ff36d1Bcb
mad witness                        # ledger head (seq 35 at last check)
mad witness 35                     # one entry, read back
mad dust pool                      # backing, liability, reserve
mad dust ledger --limit 3
mad dust balance 8453 1224530      # 101 DUST at last check
mad feed --limit 3                 # grades feed, newest first
mad complain file --claimant-name X --respondent-name Y \
  --claim "..." --category payable
mad complain list
mad complain get CMP-0001
mad ask "grade this agent 1224530" # plain English, routed, no LLM
mad mcp                            # MCP block for Claude / Codex / Grok
mad mcp --ping                     # check the MCP door live (7 tools)
mad fix seal 0x1bc0...            # re-grade a FAIL, print the fix
mad fix                            # fix the last thing MAD graded
mad version
mad help
```

### The node — grade Robinhood live, and sell what you see

`mad node` turns the terminal into a grading node. Free — no
license, no monthly fee. It grades Robinhood Chain live (C1 registry
touch, C2 deployment, C3 flagged address, C4 sender flood), signs
every verdict with the operator key, serves them over a local A2A
door with a 1¢ x402 door on full verdicts, takes jobs off the MAD
TASKS board, and keeps a public tape of flags vs outcomes.

```bash
mad node start                     # run it - supervisor + grader + door
mad node status                    # is it running, is it at the tip
mad node serve                     # the A2A door (127.0.0.1:8403)
mad node jobs                      # open tasks, priced priority
mad node task --take               # take the best job, grade, deliver
mad node tape                      # the public tape, chain checked
mad node tape --resolve            # follow up every open flag
mad node sign --verify             # verify every signature in the ledger
mad node anchor                    # file the tape head in the witness ledger
mad node key                       # the operator signer
mad node toll                      # what the door collected, the operator share
mad tail --limit 10                # the newest verdicts
```

The operator earns through the toll split on served verdicts
(`toll_share.json`, operator share UNSET until the founder sets
it) — never through a license. Verdicts are signed by the
operator key in `~/.config/mad-terminal/operator-key.json` (0600)
or `MAD_OPERATOR_KEY_FILE`; mad never generates or prints a key.
Full spec: `node-mode-spec.md`. Tape format + standing ingest
contract: `NODE_TAPE.md`.

### Alive — the terminal keeps score

Bare `mad` wakes MAD up: it shows what moved since your last run
(witness seq, dust, freshest grade) and the next check worth your
time. State lives in `~/.cache/mad-terminal/state.json` — delete it
any time and MAD starts over with no memory.

Every verdict travels **3 lanes** to the same answer — or it was
already known before you asked:

1. **The API door, live** — the verdict itself, just graded.
2. **The pre-computed lane** — the grades feed (a hit means the
   answer was there before you asked), MAD's own arithmetic, a direct
   knock from the terminal, or the terminal's own memory of your last
   checks.
3. **The chained witness ledger** — head links recomputed here, not
   taken on trust.

A lane that can't be reached says so — it never fakes agreement, and
a dead lane never kills the verdict. The lanes ride free doors only;
they never cost a cent.

`mad fix` is the fix back: a FAIL prints the fix. The safe,
reversible ones are applied only when you say yes — a corrected
authorization file (same value, same recipient, 5-minute window),
a claim-sheet draft for an UNSEALED token, a direct re-probe of a
dead door. Nothing here signs or moves money, ever. In `--json`
mode nothing is applied; the offer prints with `applied: false`.

### The rules

- **Free doors first:** test, seal, witness, dust, feed, complaints,
  mcp. The paid doors (`check/*`) cost 0.01 USDC via x402 on Base.
- **mad NEVER pays.** On a 402 it prints the bill (amount, asset,
  network, payTo, how to pay) and exits 3. Re-run with
  `--payment <base64 payload you signed elsewhere>` to pay yourself.
- **Transport failure is never a verdict.** A dead line is retried
  (gzip + 3 attempts) and reported cleanly as exit 4 — never a
  traceback, never a grade.
- `--json` prints raw JSON on stdout (MAD still talks, on stderr) —
  including the 402 bill, which is a JSON object in machine mode.
- `--help` / `-h` and `--version` / `-v` work anywhere on the line
  (`mad test --help`), not only before the command. Unknown commands
  suggest the closest real one ("Did you mean `mad version`?").
- API base: `$MAD_API` (default `https://api.madcheck.xyz`).

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | The call landed, the verdict is in the output |
| 1 | The API answered and it wasn't good news |
| 2 | Usage error (missing id, bad address, unknown flag) |
| 3 | Payment required — the door printed its 402 bill |
| 4 | Transport failure — the line died, never a verdict |

### The MCP handoff

`mad mcp` prints the config block for Claude Code (`.mcp.json`),
Codex (`config.toml`), and Grok — server
`https://api.madcheck.xyz/mcp`, transport `streamable-http`, 7 tools:
`mad_test`, `mad_check_agent`, `mad_check_authorization`,
`mad_check_endpoint`, `mad_seal_lookup`, `mad_witness_head`,
`mad_complaints`. Free, no key, no account. `mad mcp --ping` checks
the door live.

## The face (theme)

Source: MAD's `@MADx402` X profile picture, fetched live from the X
API, 400x400 JPEG, sha256
`d380e38f70f9a641811e50b69943163049fd4d226463e0bb00b18e1f762f722a`.
The ASCII is drawn from the face crop (the round flaming head); the
palette is drawn from the avatar itself:

| Colour | Hex | xterm |
|--------|-----|-------|
| dark | `#1b0708` | 52 |
| blood | `#520707` | 88 |
| flame | `#a00806` | 124 |
| ember | `#ce6947` | 173 |

The banner face is a colour half-block rendering on a colour terminal
and plain ASCII otherwise (and always plain when piped). The mini face
rides the help footer and every error screen. Regenerate with
`python3 assets/generate-face.py`.

## Verification (live, 2026-11-24, against https://api.madcheck.xyz)

### 0.1.2 — alive (living mode, 3-lane verdicts, `mad fix`)

Run from the **extracted 0.1.2 package** (`dpkg-deb -x` to scratch,
binary at `usr/bin/mad`, `HOME` pointed at a scratch dir so the
state file is observable). Live numbers move — the shape is what's
checked.

| Command | Result |
|---------|--------|
| `mad test` | **LIVE** for 1224530, plus the LANES block: API door LIVE · feed LIVE "already known before you asked" · witness head seq 35, "links hold to seq 34", exit 0 |
| `mad seal 0x1bc0...` | **UNSEALED** + lanes; lane 2 is "my own memory (pre-computed)": first sight "first time I've seen this one", second sight "I checked this one before: UNSEALED, … ago", exit 0 |
| `mad witness` / `mad witness 35` | head seq 35 + lanes; entry lane 2 recomputes the prev_hash link to seq 34, lane 3 cross-checks the dust anchor (witness seq 34), exit 0 |
| `mad` (REPL, piped `quit`) | first run: "First run in this terminal - I'm keeping score from now on" + witness seq, dust, freshest grade, pool; second run: "I'm awake. Since your last run:" + "witness seq 35 (no new entries since last run)" + next check, exit 0 |
| `mad fix seal 0x1bc0...` + `y` | re-grades UNSEALED, prints THE FIX, asks, writes `mad-seal-claim-1bc0c42215.json` (contract + DRAFT claim sheet), exit 0 |
| `mad fix seal 0x1bc0...` + `n` | "Not applied. Your call - the fix is printed above", no file written, exit 0 |
| `mad fix` (no state) | "Fix what? Nothing's been graded in this terminal yet", exit 2 |
| `mad fix bogus` | usage error listing the fix targets, exit 2 |
| `mad fix agent 999999999` | 402 bill, exit 3 — the fix can't run without the verdict, and the terminal never pays |
| `mad fix` (unit, paid doors) | GHOST / DEAD END / MALFORMED / LIVE renderers pass; DONT_SIGN with `y` writes `mad-fixed-authorization.json` with window exactly 300s, value and recipient unchanged; DONT_SIGN in `--json` mode returns the corrected body with `applied: false` and writes nothing; DEAD END with `y` re-probes direct (example.com answers HTTP 200) |
| 0.1.1 suite | re-run from the extracted 0.1.2 package — 24/24 sections pass; diff vs the 0.1.1 output is exactly 8 lines: the version string (0.1.1 → 0.1.2) and `fix` added to the command list |

### 0.1.1 — human-friendly pass

Every command below was run from the **extracted 0.1.1 package**
(`dpkg-deb -x` to scratch, binary at `usr/bin/mad`). The 24-case
usage suite gives byte-identical output from the repo binary and the
extracted binary (diff clean). Live numbers move — the shape is
what's checked.

| Command | Result |
|---------|--------|
| `mad version` | `mad-terminal 0.1.1`, exit 0 |
| `mad help` | rewritten, examples first, "type `mad` first" note, exit 0 |
| `mad test` | **LIVE** for 1224530, five stations, exit 0 (one IncompleteRead exit 4 in the run — egress flake, passed on retry) |
| `mad test --chain robinhood --agent-id 26409` | grade **ERROR** — mirror's Robinhood RPC rate-limited (HTTP 429); the CLI reports it cleanly (exit 4 after retries) over the stdlib HTTP/1.1 path, while the API answers over curl/HTTP/2. Known limitation, recorded below |
| `mad check agent 1224530` | 402 — amount `10000` (0.01 USDC), asset USDC Base, network `base`, payTo MAD, exit 3, never paid |
| `mad check agent 1224530 --json` | exit 3, stdout a JSON bill object (`payment_required`, `amount`, `amount_human`, `asset`, `network`, `payTo`, `scheme`, `how`), voice + face on stderr |
| `mad check authorization` (10-year trap body) | 402 — same bill, exit 3 |
| `mad check authorization` (missing fields) | usage error naming all 8 missing flags **plus a one-line example**, exit 2, no request sent |
| `mad check endpoint https://example.com` | 402 — same bill, exit 3 |
| `mad seal 0x1bc0...` | **UNSEALED** — no graded claim sheet, exit 0 |
| `mad witness` | head **seq 34**, exit 0 |
| `mad witness 33` | entry read back, exit 0 |
| `mad dust pool` | backing 8218 DUST, reserve 0.0207, accrual flowing, exit 0 |
| `mad dust ledger --limit 2` | 143 records on file, exit 0 |
| `mad dust balance 8453 1224530` | **101 DUST**, exit 0 (was 78 at 0.1.0 — the audit's own TEST calls earned it; accrual is verdict-blind, by design) |
| `mad feed --limit 1` | count 1000, exit 0 |
| `mad complain file` (honest self-test) | filed **CMP-0002**, exit 0 |
| `mad complain list` | 2 filings (CMP-0001 + CMP-0002), exit 0 |
| `mad complain get CMP-0001` / `CMP-0002` | read back, exit 0 |
| `mad ask "grade this agent 1224530"` | routes to check agent → 402, exit 3 |
| `mad ask "is 0x1bc0... sealed"` | routes to seal → UNSEALED, exit 0 |
| `mad ask "show the witness head"` | routes to witness → seq 34, exit 0 |
| `mad ask "flibberty gibbet"` | "That meant nothing", exit 2 |
| `mad mcp` | 3 config blocks (Claude / Codex / Grok), exit 0 |
| `mad mcp --ping` | **7 tools live**, exit 0 (one IncompleteRead retry in the run — egress flake) |
| `mad --json test` | pure JSON on stdout, grade LIVE, voice on stderr, exit 0 |
| `mad test --help` / `mad check agent --help` / `mad dust --help` | full help, exit 0 — the flag works after the command |
| `mad --help test` / `mad -h test` / `mad test --version` / `mad --version test` / `mad check --version` | help / version, exit 0 — flags work anywhere on the line |
| `mad --` | voice steer ("you wanted `mad --help`") + full help, exit 0 |
| `mad --bogus` | guided error, exit 2 |
| `mad --hep` | "Did you mean `--help`?", exit 2 |
| `mad -x` | guided error, exit 2 |
| `mad versioncurl` | "Did you mean `mad version`?", exit 2 |
| `mad bogus` | no close match — lists the commands + the REPL offer, exit 2 |
| `mad chek agent 1224530` | "Did you mean `mad check`?", exit 2 |
| `mad check agnet 1224530` | "Did you mean `mad check agent`?", exit 2 |
| `mad dust balanc 8453 1224530` | "Did you mean `mad dust balance`?", exit 2 |
| `mad complain lst` | "Did you mean `mad complain list`?", exit 2 |
| `mad tst` | "Did you mean `mad test`?", exit 2 |
| `mad test --bogus` | error now lists the flags the command takes, exit 2 |
| REPL (`mad`, piped) | new banner (one example command + "just ask me a question" + no-`mad`-prefix note), `quit` clean, exit 0 |
| REPL `mad test` | leading `mad` stripped, test runs, exit 0 |
| REPL `mad` alone | "You're already here - drop the `mad`...", exit 0 |
| REPL `--help` / `test --help` | help prints, exit 0 |
| REPL `check agent 1224530` | 402 bill prints, stays in the loop, exit 0 |
| TTY colour | face + `MAD:` prefix render in colour (verified via `script`) |
| `.deb` | `dpkg-deb --info` / `--contents` clean; extract test (`dpkg-deb -x`) — the extracted binary runs the full suite above |

### Known limitations (printed, not hidden)

- **Robinhood test over stdlib HTTP/1.1.** The public mirror's
  Robinhood test route is slow (live Robinhood RPC reads) and the
  edge closes the HTTP/1.1 connection before the body arrives
  (`IncompleteRead`, 0 bytes read, 3 attempts). The API itself
  answers fine over curl/HTTP/2 — and when it answers, the grade is
  currently ERROR because the mirror's Robinhood RPC is rate-limited
  (HTTP 429). The CLI reports this as exit 4 with MAD's voice, never
  as a verdict. The Base test is the verified path.
- **The edge truncates long HTTP/1.1 bodies.** The feed and the MCP
  tools/list used to die mid-body the same way. Fixed in the CLI with
  gzip + 3 attempts; the feed now passes 3/3.
- **Full `dpkg -i` install test not run here** — the build output was
  flagged by an execution-risk check, so the install step is left for
  an explicit run (`sudo dpkg -i mad-terminal_0.1.2_all.deb`). The
  package has no maintainer scripts; install only copies files.
  The extract test (above) passed.
- **Man page render check unavailable** — no groff/man on this VM.
  The roff source is standard macros; the gzipped page is in the .deb.

## Kali Linux

Status: **ready to file** — see `kali-submission.md` for the full
bug-tracker request text, the `debian/` source layout, and the two
founder-owned blockers (a `v0.1.2` git tag + release carrying the
`.deb`, and the bugs.kali.org / gitlab.com accounts to file it).
