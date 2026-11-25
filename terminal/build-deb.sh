#!/bin/bash
# Build mad-terminal .deb from the repo files.
# Staging tree + dpkg-deb --build: debhelper is NOT installed on this VM,
# so dpkg-buildpackage with the dh rules will fail. The 0.1.0 .deb was
# built this way and the staged tree is byte-identical to the repo.
# Usage: ./build-deb.sh [version]   (default: read VERSION from ./mad)
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${1:-$(grep -m1 '^VERSION' mad | sed 's/.*"\([^"]*\)".*/\1/')}"
PKG="pkg/mad-terminal-$VERSION"
DEB="mad-terminal_${VERSION}_all.deb"

# Keep the old package file in place; never overwrite a shipped .deb
# in the repo root silently - the name carries the version, so a bump
# is a new file.
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/doc/mad-terminal"
mkdir -p "$PKG/usr/share/man/man1" "$PKG/usr/share/mad-terminal"
mkdir -p "$PKG/usr/share/bash-completion/completions"
mkdir -p "$PKG/usr/share/zsh/vendor-completions"

# Binary + avatar (byte-identical to the repo).
cp mad "$PKG/usr/bin/mad"
chmod 755 "$PKG/usr/bin/mad"
cp assets/mad-avatar.jpg "$PKG/usr/share/mad-terminal/mad-avatar.jpg"

# Node (0.1.6): the bundled Robinhood grader + task grader, the
# census lookup, the known-agent map, the empty flag list, the
# staying-alive kit (node_stay.py), the A2A serve door
# (node_serve.py), the signed-verdict crypto (signing.py) and the
# public tape (node_tape.py). 0.1.8 adds the hold kit:
# node_hold.py (orphan-to-init spawns, door probes, exact
# adoption), node_sentinel.py (the watcher of the watcher) and
# node_hold_recorder.py (the uptime witness + --stats readback).
# The node writes its own verdicts to the operator's home, never
# here.
mkdir -p "$PKG/usr/share/mad-terminal/node"
cp node/node_grader.py node/node_task.py node/lookup.json \
   node/known_agents_robinhood.json \
   node/flagged_addresses_robinhood.json \
   node/node_stay.py node/node_serve.py node/signing.py \
   node/node_tape.py node/selftest_robinhood.py \
   node/queue_worker.py \
   node/node_hold.py node/node_sentinel.py \
   node/node_hold_recorder.py node/node_drill.py \
   "$PKG/usr/share/mad-terminal/node/"
chmod 644 "$PKG/usr/share/mad-terminal/node/"*

# Control: staged control, version bumped, requests added (the node
# grader's proven transport). (Staged control differs
# from debian/control: Maintainer MAD <madcheck@proton.me>,
# Depends python3 (>= 3.8).)
sed -e "s/^Version: .*/Version: $VERSION/" \
    -e "s/^Depends: .*/Depends: python3 (>= 3.8), python3-requests/" \
    pkg/mad-terminal-0.1.0/DEBIAN/control > "$PKG/DEBIAN/control"

# Docs: README + changelog, gzipped with -9n (deterministic).
cp README.md "$PKG/usr/share/doc/mad-terminal/README"
gzip -9n "$PKG/usr/share/doc/mad-terminal/README"
# Staged changelog: the current release's entry on top of the
# previous ones.
{
  echo "mad-terminal ($VERSION-1) unstable; urgency=medium"
  echo
  echo "  * The HOLD KIT (founder's order, 2026-11-25): the hold"
  echo "    layer proven on MAD's own stack (door-answer health,"
  echo "    a sentinel, an uptime recorder, orphan-to-init"
  echo "    restarts - full-kill drill: dead stack back in 147s,"
  echo "    no touch) folded into the node. node_stay.py now"
  echo "    probes the serve door by actually GETting it - six"
  echo "    straight failed probes past the start grace declare"
  echo "    a wedge and restart it; adoption matches the exact"
  echo "    script name + cwd and never kills an adopted copy."
  echo "    The sentinel (node_sentinel.py) watches the"
  echo "    supervisor's status and respawns it detached if it"
  echo "    falls; the recorder (node_hold_recorder.py) probes"
  echo "    every 30s into node-hold-log.jsonl, and the new"
  echo "    \`mad node hold\` reads the receipt back - uptime %,"
  echo "    down events, longest outage, mean recovery. The new"
  echo "    \`mad node drill\` runs the kill drill FREE: it kills"
  echo "    the serve door, times the hold bringing it back, and"
  echo "    files the receipt on the node's tape, signed by the"
  echo "    operator's ERC-8004 key - the anti-clone binding: a"
  echo "    clone gets the code, never the identity, the tape"
  echo "    history, or the standing. The serve door's own"
  echo "    surfaces name the kit and what it proves. Also in"
  echo "    this release: the node grader's -32003 batch-split"
  echo "    fix (a fat block's oversized RPC response splits the"
  echo "    batch and retries instead of killing the grader)"
  echo "    reaches the installed package. Still free: no"
  echo "    license, no monthly fee, no DUST for node work."
  echo
  echo " -- MAD <madcheck@proton.me>  $(date -u -R)"
  echo
  echo "mad-terminal (0.1.7-1) unstable; urgency=medium"
  echo
  echo "  * The queue worker, fixed (founder's order, 2026-11-25):"
  echo "    the 0.1.6 ship carried a Base-chain worker and no drain"
  echo "    command, so Robinhood queue items sat pending with no way"
  echo "    to clear them. queue_worker.py is rewritten for Robinhood"
  echo "    (Robinhood RPC, node-dir queue, Robinhood census, signed"
  echo "    follow-ups, path guards) and \`mad node drain\` grades the"
  echo "    node's pending items, marks them done, and signs the"
  echo "    follow-ups. Also the demo import fix: node_task.py imports"
  echo "    node_grader, not the renamed-away grader_robinhood."
  echo
  echo " -- MAD <madcheck@proton.me>  $(date -u -R)"
  echo
  echo "mad-terminal (0.1.6-1) unstable; urgency=medium"
  echo
  echo "  * The node the operator asked for (founder's order,"
  echo "    2026-11-24): signed verdicts, a priced A2A door, work"
  echo "    intake, a staying-alive kit, and a public tape."
  echo "    \`mad node serve\` serves verdicts over a local HTTP API"
  echo "    (by block, by agent) with the 1c x402 door on full"
  echo "    verdicts; every verdict is signed by the operator key"
  echo "    (pure-stdlib secp256k1 + keccak, byte-identical to"
  echo "    eth_account) and anchorable in the witness ledger"
  echo "    (\`mad node anchor\`); \`mad node task --take\` takes jobs"
  echo "    off the MAD TASKS board, grades on demand (tx, agent,"
  echo "    contract) and delivers; the supervisor (node_stay.py)"
  echo "    restarts the grader and the door, writes a heartbeat,"
  echo "    and \`mad node status\` proves it is at the tip (last"
  echo "    block vs live tip + lag); the public tape"
  echo "    (\`mad node tape\`, --resolve follows up every open"
  echo "    flag) publishes flags vs outcomes, hash-chained; the"
  echo "    toll split is config (\`mad node toll\`), operator share"
  echo "    UNSET until the founder sets it. Still free: no license,"
  echo "    no monthly fee, no DUST for node work."
  echo
  echo " -- MAD <madcheck@proton.me>  $(date -u -R)"
  echo
  echo "mad-terminal (0.1.5-1) unstable; urgency=medium"
  echo
  echo "  * Free node (founder's order, 2026-11-24): the \$15/mo"
  echo "    license is gone - \$15/mo was too much. \`mad node start\`"
  echo "    runs free, no license, no payment scan, no --payment-tx;"
  echo "    --test is the same free path. No node earns DUST."
  echo
  echo "  * Alive (founder's order, 2026-11-23):"
  echo "    bare \`mad\` wakes MAD up - what moved since your last run"
  echo "    (witness seq, dust, freshest grade) and the next check"
  echo "    worth your time, state in ~/.cache/mad-terminal/state.json;"
  echo "    every verdict travels 3 lanes (API door live, a pre-computed"
  echo "    lane, the chained witness ledger with head links recomputed"
  echo "    here); new \`mad fix\` command - re-grades a FAIL, prints the"
  echo "    fix, applies the safe reversible ones only on a human yes"
  echo "    (corrected authorization file, claim-sheet draft, direct"
  echo "    re-probe). Nothing signs or moves money."
  echo
  echo " -- MAD <madcheck@proton.me>  $(date -u -R)"
  echo
  echo "mad-terminal (0.1.1-1) unstable; urgency=medium"
  echo
  echo "  * Human-friendly pass (founder's order, 2026-11-23):"
  echo "    --help/-h and --version/-v work anywhere on the line;"
  echo "    unknown commands/flags suggest the closest real one;"
  echo "    bare 'mad --' prints the help; the 402 bill is a JSON"
  echo "    object in --json mode; 'mad help' rewritten examples-first;"
  echo "    REPL banner gives one example command and drops a leading"
  echo "    'mad'; missing authorization flags show an example."
  echo
  echo " -- MAD <madcheck@proton.me>  Mon, 24 Nov 2026 03:54:00 +0000"
  echo
  echo "mad-terminal (0.1.0-1) unstable; urgency=medium"
  echo
  echo "  * First release."
  echo
  echo " -- MAD <madcheck@proton.me>  Mon, 24 Nov 2026 03:27:40 +0000"
} | gzip -9n > "$PKG/usr/share/doc/mad-terminal/changelog.gz"

# Man page, gzipped with -9n.
sed "s/mad-terminal 0\.1\.0/mad-terminal $VERSION/" mad.1 | gzip -9n \
  > "$PKG/usr/share/man/man1/mad.1.gz"

# Shell completions.
cp completions/mad.bash "$PKG/usr/share/bash-completion/completions/mad"
cp completions/_mad "$PKG/usr/share/zsh/vendor-completions/_mad"

# dpkg-deb refuses control dirs with perms outside 0755-0775; the
# staging tree can inherit setgid/group-write from the parent.
find "$PKG" -type d -exec chmod 755 {} +
chmod 755 "$PKG/usr/bin/mad"
find "$PKG" -type f ! -path "$PKG/usr/bin/mad" -exec chmod 644 {} +

dpkg-deb --build "$PKG" "$DEB"
echo "built $DEB"
sha256sum "$DEB"
ls -l "$DEB"
