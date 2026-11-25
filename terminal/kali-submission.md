# Kali Linux submission — mad-terminal 0.1.2

Status: **READY TO FILE, blocked on one founder-owned step** (the accounts — see §4). The release/tag step is done: v0.1.2 published 2026-11-24.
Everything else is built and in this repo.

## 1. Where it goes

Kali's documented process (read live 2026-11-24,
https://www.kali.org/docs/tools/submitting-tools/ and
https://www.kali.org/docs/development/public-packaging/):

1. File a request on the Kali bug tracker, **bugs.kali.org**:
   Report issue → Category **New Tool Requests** → Reproducibility **N/A**
   → Severity **minor** → Priority **normal** → Summary
   "mad-terminal - grade-before-you-sign terminal for agent payments"
   → Description = the filled template in §2 below.
2. The Kali team packages accepted tools in
   `https://gitlab.com/kalilinux/packages/<name>/` (e.g. the
   detect-it-easy precedent: bug 0009223 → packaged at
   `gitlab.com/kalilinux/packages/detect-it-easy/` within a month).
   A community member can also open a merge request carrying the
   `debian/` directory from this repo — the layout in §3 is built for
   exactly that.
3. Kali prefers tools already packaged for Debian (they flow in
   automatically), but the direct Kali route via the bug tracker +
   GitLab MR is the documented path for a new tool, and it is the
   one prepared here.

Kali does not accept every request — a tool can be refused for being
too new or duplicating an older one. The honest answer to "similar
tools" is in §2: nothing else grades ERC-8004 / x402 claims
pre-sign from a terminal.

## 2. The bug-tracker request text (paste verbatim)

```
[Name] - mad-terminal
[Version] - 0.1.2 (git tag v0.1.2 - see note below)
[Homepage] - https://madcheck.xyz
[Download] - https://github.com/madcheck/mad-check/releases/tag/v0.1.2
  (.deb: mad-terminal_0.1.2_all.deb, 90,032 bytes, sha256 3905ba3b573c6811d95ccf75f314d676911d0463204247209f861463253eadaf, also in the repo)
[Author] - MAD <madcheck@proton.me>
[License] - MIT
[Description] - The terminal for MAD, the angry auditor of the agent
  economy. It grades agent registrations (ERC-8004), payment
  authorizations (EIP-3009 signing firewall), x402 endpoints, and
  token launches (Born Graded seal) against receipts - before you sign
  or pay. Every output talks back in MAD's voice, and every screen
  wears MAD's face, drawn from MAD's own @MADx402 avatar. Free doors
  first (test, seal, witness, dust, feed, complaints, MCP); the paid
  doors cost 0.01 USDC via x402 and the terminal never pays for you.
  Includes the MCP handoff block for Claude, Codex and Grok, a
  plain-English `ask` router, and an interactive REPL.
[Dependencies] - python3 (>= 3.8). No other dependencies. Network
  access to https://api.madcheck.xyz (the Mad Check API).
[Similar tools] - New Jazz City's terminal (same pattern - Claude /
  Codex / Grok + an MCP server, plain-English asks - but the deal
  side: it finds jobs and buys tokens). Nothing else grades
  ERC-8004 / x402 claims pre-sign from a terminal; mad-terminal is
  the audit side of that same pattern.
[Activity] - Project started 2026-11-23, actively developed. Mad Check
  itself has run since 2026-11-21 (live API, census of 100,000+
  graded agents, signed witness ledger).
[How to install] - `sudo dpkg -i mad-terminal_0.1.2_all.deb` or
  `sudo apt install ./mad-terminal_0.1.2_all.deb`. From source:
  the single-file Python CLI `mad` runs as-is (`./mad --help`).
  A `debian/` directory is included in the source for packaging.
[How to use] -
  mad test                          # the free look, five stations
  mad check agent 1224530           # grade a registration (0.01 USDC)
  mad seal 0x1bc0...                # SEALED / UNSEALED / FAILED
  mad witness                       # witness ledger head
  mad mcp --ping                    # MCP door check, 7 tools
  mad ask "grade this agent 1224530"
[Packaged] - Not yet packaged for Debian. A full `debian/` directory
  (control, changelog 0.1.2-0kali1, copyright, rules, install,
  source/format, watch) is in the source repo, ready for review.
```

## 3. Source package layout (in this repo)

```
mad                  single-file Python CLI, stdlib only
mad.1                man page
completions/mad.bash completions/_mad
assets/              mad-avatar.jpg (MAD's @MADx402 avatar, theme asset),
                     mad-face*.txt (ASCII + colour face), palette.json,
                     generate-face.py (regenerates the theme)
debian/control       Source: mad-terminal, Maintainer: Kali Developers,
                     Uploaders: MAD <madcheck@proton.me>, Section: utils,
                     Build-Depends: debhelper-compat (= 13)
debian/changelog     mad-terminal (0.1.2-0kali1) kali-dev; urgency=medium
debian/copyright     MIT (Files: * and Files: debian/*)
debian/rules         dh, installs mad to /usr/local/bin/mad, theme assets
                     to /usr/share/mad-terminal/, completions, man page
debian/mad-terminal.install  mad.1 -> usr/share/man/man1/
debian/source/format 3.0 (quilt)
debian/watch         GitHub tags for mad-check
debian/docs          README.md
```

Notes for the reviewer: the binary installs to `/usr/local/bin/mad`
by design (a single-file terminal kept out of the distro's `/usr/bin`
namespace); move it to `/usr/bin` if the team prefers. The avatar
bundled in the package is MAD's own @MADx402 profile picture — never
a human face; the rule is written in the source.

## 4. What the founder must do (blockers, nothing else)

1. **Tag the release — DONE 2026-11-24.** Tag v0.1.2 published on
   the mad-check repo with `mad-terminal_0.1.2_all.deb` attached:
   https://github.com/madcheck/mad-check/releases/tag/v0.1.2
   (90,032 bytes, sha256 3905ba3b… verified from the download).
   The [Version] and [Download] lines in §2 now point at a live release.
2. **File the request.** Needs accounts the founder must own:
   a bugs.kali.org account (to file the New Tool Request) and,
   for the MR path, a gitlab.com account. Do NOT file under any
   identity but MAD's. MAD did not create either account.
3. **Optional, after acceptance:** the Kali team may ask for the
   package to go through Debian first. If so, the same `debian/`
   directory is the submission — only the changelog distribution
   and Maintainer lines change.

## 5. Verification done here (not filed)

- `.deb` built with `dpkg-deb --build`: `mad-terminal_0.1.2_all.deb`
  (90,032 bytes, sha256 3905ba3b573c6811d95ccf75f314d676911d0463204247209f861463253eadaf, `dpkg-deb --info` / `--contents` clean).
- Extract test (`dpkg-deb -x` to a temp dir): the extracted
  `/usr/bin/mad` runs — `mad version` and `mad witness` verified
  live against the API from the extracted tree.
- Full `dpkg -i` install test: **not run** — the build output was
  flagged by an execution-risk check, so the install step is left for
  the founder/parent to run explicitly (`sudo dpkg -i
  mad-terminal_0.1.2_all.deb`, then `sudo dpkg -r mad-terminal`).
  The package has no maintainer scripts (no preinst/postinst), so
  install only copies files.
- Man page: included, gzipped; render check unavailable (no groff/man
  on this VM).
- Every CLI command verified live against https://api.madcheck.xyz —
  see README.md § Verification.
