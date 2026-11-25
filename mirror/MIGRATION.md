# MAD MIRROR — migration note

The public stack moves off the managed edge platform and onto one plain
box. One codebase, one box, no middleman. Nothing below is done yet —
this is the order of operations for cutover day.

## What moves

- **DNS, at the registrar (Spaceship — login already saved):**
  one A record for `api.madcheck.xyz` and one for `madcheck.xyz`
  (plus `www`), all to the new box's IP. The domain's nameservers
  move off the provider at the same time, to the registrar's own DNS.
  Lower the TTLs to 300s a day before cutover so the flip propagates
  in minutes, not hours.
- **The data, once:** the canonical ledgers (witness, dust, tasks,
  receipts, complaints, loop trades, churn, standing changes) rsync
  from this machine to the new box at deploy time. The deploy script
  copies them on a fresh deploy only — a re-deploy never overwrites
  the target's own ledgers.
- **The secrets, once:** `~/.secrets/mad_wallet.json` (the API cannot
  sign without it) and `~/.secrets/priors_facilitator_key.json`,
  copied 0600, owned by the `mad` user, only if the target does not
  already have them.

## What dies

- The Worker mirror (`worker.src.js` → `worker.js`, the second
  codebase that had to stay in sync with the canonical API by hand).
- Both key-value namespaces (PAGES, holding the site in 64KB chunks
  and the live feed; DUST, holding the public dust records).
- `deploy.py` chunking, `cf_recover.py` + `cf_recover_loop.sh`,
  the `mad-cf-recover` cron, and the mirror snapshot redeploys.
- The KV PUTs in `push_feed.py` and `push_tokyo_pass.py`. The live
  feed is served by the API itself from its own ring buffer (the
  graders on the new box feed it); the Tokyo directory is a static
  JSON file rebuilt from the on-disk sweep data by the same merge
  function, writing to a file instead of a remote store.
- The dust reconciler's mirror leg: with no mirror, dust writes go
  straight to the new box's API, so there is nothing to merge in.
  The reconciler itself can be retired.
- The Worker's `/node` page, replaced by the static `node.html`
  served by the front door.

## What it costs

**Hetzner Cloud CX22 — 2 shared vCPU, 4 GB RAM, 40 GB NVMe, 20 TB
traffic — approximately €4.49/month ex-VAT (~$4.60/month).**
That is the list price as of November 2026; Hetzner repriced the
CX/CAX lines in 2026 (CX22 was €3.79 before), so verify the current
number at hetzner.com/cloud before buying. The ARM equivalent,
CAX11 (2 vCPU, 4 GB RAM), is cheaper at roughly €3.29–€3.79/month
and runs this stack fine (pure Python), if the founder prefers the
lowest number. Nothing is bought yet — the founder buys the box (or
orders it). No other recurring cost: the API, the graders and the
front door are all open-source software on the box, and TLS certs
come free from Let's Encrypt.

## Cutover order

1. **Buy the box.** Fresh Ubuntu 24.04, any region. Note its IP.
2. **Deploy.** `bash deploy-mirror.sh mad@<box-ip>` from this
   machine. It provisions the box, syncs the code + data, starts
   the API, the two block graders, the Tokyo writer and the front
   door, then prints a verification report. Every check must pass,
   and TEST 7622 / standing / health must match the canonical API
   on this machine.
3. **Let the graders catch up.** The new box's graders start from
   the live tip and build their own verdict ledgers; the stream
   sample fills as they grade. The API answers from the copied
   ledgers immediately — the graders' catch-up does not block the
   cutover.
4. **Lower the DNS TTLs** to 300s (do this a day before, step 0 if
   you are planning ahead).
5. **Final ledger sync.** The old API is still taking writes on
   this machine (Tokyo jobs anchor to it). Sync the append-only
   ledgers one last time, then restart the new box's API so it
   picks them up:
   ```sh
   rsync -a ~/workspace/mad-check-api/ledger.jsonl \
             ~/workspace/mad-check-api/dust.jsonl \
             ~/workspace/mad-check-api/tasks.jsonl \
             ~/workspace/mad-check-api/receipts.jsonl \
             ~/workspace/mad-check-api/complaints.jsonl \
             ~/workspace/mad-check-api/loop-trades.jsonl \
             ~/workspace/mad-check-api/churn.jsonl \
             ~/workspace/mad-check-api/standing-changes.jsonl \
             mad@<box-ip>:/home/mad/workspace/mad-check-api/
   ssh mad@<box-ip> 'sudo systemctl restart mad-api'
   ```
6. **Re-point the Tokyo job scripts** (`~/workspace/tokyo-run/`) to
   post witness receipts to `https://api.madcheck.xyz/v1/witness`
   instead of `http://127.0.0.1:8402/v1/witness`. Do this in the
   same minute as step 5, then run the step-5 sync once more to
   catch any receipt that landed on the old API in the window.
   After this, the new box is the only witness record.
7. **Flip DNS** at the registrar (A records + nameservers).
8. **Verify from the public internet:** `https://api.madcheck.xyz/v1/health`
   answers ok, the landing loads at `https://madcheck.xyz`, the
   sample stream replays at `/v1/stream/sample`, and an unpaid
   `/v1/stream` returns 402.
9. **TLS.** `bash deploy-mirror.sh --tls mad@<box-ip>` (only works
   after DNS points at the box).
10. **Move the remaining crons to the new box:** the standing
    recompute loop and the daily witness anchor (plain scripts +
    cron entries, no provider involved). The dust reconciler is
    retired (see above).
11. **Only then delete the provider pieces:** the Worker, both
    key-value namespaces, and the `mad-cf-recover` cron.
12. **Keep the old VM running as a hot spare for a week.** Its API
    still answers on localhost and its graders still grade; if the
    new box fails, DNS flips back in minutes. Retire it after a
    clean week.

## Notes

- **Supervision changes shape.** This VM is replaced about every
  two hours, which is why the API runs under a user-space
  supervisor here. A real box does not get replaced: systemd with
  `Restart=always` is the supervisor on the target, and no
  supervisor daemon is ported over.
- **The API never faces the internet directly.** It binds
  127.0.0.1 only; the front door (nginx) proxies to it, serves
  the static site, and terminates TLS.
- **The census/watch pipeline stays on this machine for now.**
  The API reads its output files (the grades feed, the bankr
  feed), which re-sync on every deploy. Moving the watcher to the
  new box is a separate job, not part of this cutover.
- **The 402 gates do not change.** The paid routes keep the same
  1¢ x402 doors, the same payee wallet, the same free routes.
  Nothing about the API's behavior changes — only where it runs.
- **--local on this VM dodges the supervisor.** The supervisor
  here adopts any process whose command line contains
  "server.py" and kills it as "wedged" when its probes to port
  8402 fail — which is exactly what it did to the first --local
  run after a VM replacement (adopted the local API on 8406,
  killed it, then adopted the site process). So --local runs the
  API copy as `mirror_api.py` and the site as `site_gate.py`:
  same code, names the supervisor will not match. Stop the
  local mirror with `--local-stop` when verification is done;
  do not leave it running alongside the supervisor.
