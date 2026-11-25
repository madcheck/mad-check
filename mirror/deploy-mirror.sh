#!/usr/bin/env bash
# ==========================================================================
# MAD MIRROR — the whole public stack on one plain box, no edge provider.
#
# What this replaces: the public API used to run behind a managed edge
# platform — a second, separate codebase kept in sync by hand, a remote
# key-value store holding the site in chunks and the live feed, and a
# recovery loop that re-deployed whenever the provider's command line
# flaked. That stack froze the public stream for 8 hours once and lags
# minutes behind the canonical API on a good day.
#
# What this does instead: the public API IS the canonical API
# (server.py, one codebase, no drift, no snapshot redeploy). The site
# is plain static files on disk (no chunking). The live stream is served
# by the API itself from its own ring buffer, fed by the block graders
# running on the same box. The Tokyo directory is a static JSON file
# rebuilt from the on-disk sweep data. Supervision is systemd with
# Restart=always — a real box does not get replaced every two hours,
# so no user-space supervisor is needed on the target.
#
# Usage:
#   deploy-mirror.sh <user@host>   deploy to a fresh Ubuntu 24.04 box over SSH
#   deploy-mirror.sh --local        install + run the same stack on THIS machine
#                                   (API on 8406, site on 8080) for verification
#   deploy-mirror.sh --local-stop   stop the --local install
#   deploy-mirror.sh --tls <user@host>
#                                   after DNS points at the box: issue TLS certs
#   deploy-mirror.sh --help
#
# The script never touches the live services on this machine (ports
# 8402-8405 are refused in --local mode), never moves DNS, never buys
# anything, never posts, never moves funds, never signs anything.
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$HOME/workspace"

# --- sources on this machine (read-only; nothing here is modified) ---------
API_SRC="$WORKSPACE/mad-check-api"
GRADER_SRC="$WORKSPACE/mad-block-grader"
PASS_SRC="$WORKSPACE/mad-pass-tokyo"
LANDING_SRC="$WORKSPACE/mad-check-worker/landing.html"
NODE_PAGE_SRC="$SCRIPT_DIR/node.html"
SITE_SERVER_SRC="$SCRIPT_DIR/site_gate.py"

# --- ports -----------------------------------------------------------------
API_PORT_REMOTE=8402
API_PORT_LOCAL=8406
SITE_PORT_LOCAL=8080
# The live stack on this machine owns 8402 (API), 8403 (node serve),
# 8404 (selftest) and 8405 (wall). --local never binds any of them.
FORBIDDEN_LOCAL_PORTS="8402 8403 8404 8405"

# --- pinned Python deps (the versions the canonical API runs on) -----------
PINNED_DEPS="eth-account==0.14.0 eth-abi==6.0.0 eth-utils==6.0.0 requests==2.34.2"

# --- target layout (mirrors this machine's home layout, so server.py -----
# --- works unmodified: it reads its ledgers next to itself and tails -----
# --- ~/workspace/mad-block-grader/verdicts.jsonl for the stream) ----------
REMOTE_USER="mad"
REMOTE_HOME="/home/mad"
REMOTE_WS="$REMOTE_HOME/workspace"
REMOTE_API="$REMOTE_WS/mad-check-api"
REMOTE_GRADER="$REMOTE_WS/mad-block-grader"
REMOTE_PASS="$REMOTE_WS/mad-pass-tokyo"
REMOTE_VENV="$REMOTE_HOME/venv"
SITE_ROOT="/var/www/madcheck.xyz"
API_FILES_ROOT="/var/www/api"
TOKYO_PASS_OUT="$API_FILES_ROOT/tokyo-pass.json"

# --- local layout -----------------------------------------------------------
LOCAL_ROOT="$SCRIPT_DIR/local"
LOCAL_API="$LOCAL_ROOT/api"
LOCAL_SITE="$LOCAL_ROOT/site"
LOCAL_PASS="$LOCAL_ROOT/pass-tokyo"

log()  { printf '[mad-mirror %s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die()  { printf '[mad-mirror] FATAL: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage:
  deploy-mirror.sh <user@host>   deploy to a fresh Ubuntu 24.04 box over SSH
  deploy-mirror.sh --local        install + run the same stack on THIS machine
                                  (API 127.0.0.1:8406, site 127.0.0.1:8080)
  deploy-mirror.sh --local-stop   stop the --local install
  deploy-mirror.sh --tls <user@host>
                                  after DNS points at the box: issue TLS certs
  deploy-mirror.sh --help
EOF
}

# --- port guards ------------------------------------------------------------
port_free() { # port_free <port> — true when nothing listens on 127.0.0.1:port
    ! (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null
}

guard_local_ports() {
    for p in $FORBIDDEN_LOCAL_PORTS; do
        case " $API_PORT_LOCAL $SITE_PORT_LOCAL " in
            *" $p "*) die "refusing: local install would bind $p, owned by the live stack" ;;
        esac
    done
    port_free "$API_PORT_LOCAL" || die "port $API_PORT_LOCAL is already in use — stop whatever holds it first"
    port_free "$SITE_PORT_LOCAL" || die "port $SITE_PORT_LOCAL is already in use — stop whatever holds it first"
}

# --- rsync payloads ---------------------------------------------------------
# Append-only ledgers: copied on a FRESH deploy only. On a re-deploy the
# target's own ledgers are the live record and must never be overwritten
# by this machine's older copies.
LEDGER_FILES="ledger.jsonl dust.jsonl tasks.jsonl receipts.jsonl complaints.jsonl loop-trades.jsonl churn.jsonl standing-changes.jsonl"
# Computed snapshots (standings, grades feed, bankr feed) ride along with
# the code sync — they are regenerated state, safe to refresh every deploy.

API_EXCLUDES="--exclude=__pycache__/ --exclude=*.log --exclude=*.pid --exclude=*.bak* --exclude=.bak-pre-* --exclude=fork-quarantine-*/ --exclude=selftest.py.bak*"
GRADER_FILES="grader.py grader_robinhood.py lookup.json flagged_addresses.json flagged_addresses_robinhood.json known_agents_robinhood.json"
PASS_FILES="tokyo-ids.json records-madpass-tokyo-pilot.jsonl records-madpass-tokyo.jsonl results-madpass-tokyo.jsonl checkpoint-madpass-tokyo.json checkpoint-madpass-tokyo-pilot.json push_tokyo_pass.py"

sync_api_code() { # sync_api_code <dest> [extra rsync args...]
    # Code + computed snapshots, never the append-only ledgers.
    local dest="$1"; shift
    rsync -a $API_EXCLUDES "$@" \
        --exclude=ledger.jsonl --exclude=dust.jsonl --exclude=tasks.jsonl \
        --exclude=receipts.jsonl --exclude=complaints.jsonl \
        --exclude=loop-trades.jsonl --exclude=churn.jsonl \
        --exclude=standing-changes.jsonl \
        "$API_SRC/" "$dest/"
}

sync_ledgers() { # sync_ledgers <dest> [extra rsync args...] — fresh deploy only
    local dest="$1"; shift
    for f in $LEDGER_FILES; do
        [ -f "$API_SRC/$f" ] || continue
        rsync -a "$@" "$API_SRC/$f" "$dest/"
    done
}

sync_grader_code() { # sync_grader_code <dest> [extra rsync args...]
    local dest="$1"; shift
    for f in $GRADER_FILES; do
        [ -f "$GRADER_SRC/$f" ] || { log "skip missing grader file: $f"; continue; }
        rsync -a "$@" "$GRADER_SRC/$f" "$dest/"
    done
}

sync_pass_data() { # sync_pass_data <dest> [extra rsync args...]
    local dest="$1"; shift
    for f in $PASS_FILES; do
        [ -f "$PASS_SRC/$f" ] || { log "skip missing pass file: $f"; continue; }
        rsync -a "$@" "$PASS_SRC/$f" "$dest/"
    done
}

# --- tokyo-pass: file output instead of a remote put ------------------------
# The deployed copy of push_tokyo_pass.py is patched in place (the live
# copy on this machine is never touched): the remote-put import becomes
# a stub, and the put call becomes a write of the same JSON blob to a
# file the web server serves. build_feed() is untouched — one merge
# function, no second codebase.
patch_pass_to_file() { # patch_pass_to_file <path-to-copied-push_tokyo_pass.py>
    local file="$1"
    python3 - "$file" <<'PATCH_EOF'
import sys
path = sys.argv[1]
src = open(path).read()
lines = src.split("\n")
out = []
did_import = did_put = did_log = False
for line in lines:
    if line.startswith("from deploy import"):
        out.append("cf_execute = None  # file output only; no remote put")
        out.append("PAGES_NS = None")
        did_import = True
        continue
    stripped = line.strip()
    if stripped.startswith("nbytes = ") and "FEED_KEY, feed" in line:
        indent = line[:len(line) - len(line.lstrip())]
        out.append(indent + 'out_path = os.environ.get("TOKYO_PASS_OUT", "/var/www/api/tokyo-pass.json")')
        out.append(indent + 'with open(out_path, "wb") as f:')
        out.append(indent + "    f.write(blob)")
        out.append(indent + "nbytes = len(blob)")
        did_put = True
        continue
    if "-> PAGES/" in line:
        line = line.replace("-> PAGES/", "-> file:")
        did_log = True
    out.append(line)
if not (did_import and did_put):
    sys.exit("patch anchors not found in %s (import=%s put=%s)" % (path, did_import, did_put))
open(path, "w").write("\n".join(out))
print("patched %s (log line updated: %s)" % (path, did_log))
PATCH_EOF
}

# --- python venv -------------------------------------------------------------
make_venv() { # make_venv <venv-path>
    local venv="$1"
    if [ ! -x "$venv/bin/python" ]; then
        log "creating venv at $venv"
        python3 -m venv "$venv"
    fi
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q $PINNED_DEPS
    log "venv ready: $($venv/bin/python --version), deps pinned"
}

# --- wait for the API --------------------------------------------------------
wait_health() { # wait_health <base-url> [timeout-secs] — 0 when /v1/health says ok
    local base="$1" timeout="${2:-180}" i=0
    while [ "$i" -lt "$timeout" ]; do
        if curl -fsS -m 5 "$base/v1/health" 2>/dev/null | grep -q '"status": "ok"'; then
            return 0
        fi
        sleep 5; i=$((i + 5))
    done
    return 1
}

# --- --local -----------------------------------------------------------------
cmd_local() {
    # Stop any previous --local install first, so the port guard below
    # sees a free 8406/8080 on a re-run (by pid file, never by pattern).
    cmd_local_stop_quiet
    guard_local_ports
    [ -f "$API_SRC/server.py" ] || die "canonical API not found at $API_SRC/server.py"
    [ -f "$LANDING_SRC" ] || die "landing page not found at $LANDING_SRC"
    [ -f "$NODE_PAGE_SRC" ] || die "node page not found at $NODE_PAGE_SRC"
    [ -f "$SITE_SERVER_SRC" ] || die "site server not found at $SITE_SERVER_SRC"

    log "local install root: $LOCAL_ROOT (fresh snapshot every run)"
    rm -rf "$LOCAL_API" "$LOCAL_SITE"
    mkdir -p "$LOCAL_API" "$LOCAL_SITE" "$LOCAL_PASS" "$LOCAL_ROOT/grader"
    sync_api_code "$LOCAL_API"
    # Rename the local API copy: STAY (the supervisor on THIS vm) adopts
    # any process whose cmdline contains "server.py" and then kills it as
    # "wedged" when its probes to port 8402 fail — our copy serves 8406.
    # mirror_api.py is the same file, only the name differs (server.py
    # locates its data relative to __file__, so the rename is safe).
    # The remote deploy keeps the canonical name server.py (no STAY there).
    mv "$LOCAL_API/server.py" "$LOCAL_API/mirror_api.py"
    sync_ledgers "$LOCAL_API"
    sync_grader_code "$LOCAL_ROOT/grader"
    sync_pass_data "$LOCAL_PASS"
    patch_pass_to_file "$LOCAL_PASS/push_tokyo_pass.py"

    cp "$LANDING_SRC" "$LOCAL_SITE/index.html"
    cp "$NODE_PAGE_SRC" "$LOCAL_SITE/node.html"

    # The Tokyo directory JSON, built once from the copied sweep data.
    local py
    if [ -x "$WORKSPACE/mad-watch/venv/bin/python" ]; then
        py="$WORKSPACE/mad-watch/venv/bin/python"
    else
        make_venv "$LOCAL_ROOT/venv"; py="$LOCAL_ROOT/venv/bin/python"
    fi
    (cd "$LOCAL_PASS" && TOKYO_PASS_OUT="$LOCAL_SITE/tokyo-pass.json" \
        "$py" push_tokyo_pass.py --once) | tail -2

    log "starting API on 127.0.0.1:$API_PORT_LOCAL (data: $LOCAL_API)"
    # exec so $! is the python process itself, not a subshell wrapper —
    # otherwise stopping by pid file leaves the server orphaned.
    (cd "$LOCAL_API" && exec nohup env MAD_PORT=$API_PORT_LOCAL "$py" mirror_api.py \
        >>"$LOCAL_ROOT/api.log" 2>&1 & echo $! >"$LOCAL_ROOT/api.pid")
    log "starting site on 127.0.0.1:$SITE_PORT_LOCAL (root: $LOCAL_SITE)"
    (exec nohup "$py" "$SITE_SERVER_SRC" $SITE_PORT_LOCAL "$LOCAL_SITE" \
        >>"$LOCAL_ROOT/site.log" 2>&1 & echo $! >"$LOCAL_ROOT/site.pid")

    log "waiting for the API (up to 180s — it loads the 99k-record feed)..."
    wait_health "http://127.0.0.1:$API_PORT_LOCAL" 180 \
        || die "API did not answer /v1/health; see $LOCAL_ROOT/api.log"
    log "API healthy"
    verify_report "http://127.0.0.1:$API_PORT_LOCAL" "http://127.0.0.1:$SITE_PORT_LOCAL" ""
    log "local mirror running: API http://127.0.0.1:$API_PORT_LOCAL  site http://127.0.0.1:$SITE_PORT_LOCAL"
    log "stop it with: $0 --local-stop"
}

cmd_local_stop_quiet() {
    for name in api site; do
        local pidfile="$LOCAL_ROOT/$name.pid"
        [ -f "$pidfile" ] || continue
        local pid; pid="$(cat "$pidfile")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 "$pid" 2>/dev/null || break; sleep 1
            done
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
            log "stopped previous local $name (pid $pid)"
        fi
        rm -f "$pidfile"
    done
}

cmd_local_stop() {
    cmd_local_stop_quiet
    log "local mirror stopped"
}

# --- verification ------------------------------------------------------------
# vcurl runs curl here, or on the target box when V_TARGET is set.
# Every argument is a single space-free token, so it round-trips through
# ssh's remote shell untouched.
V_TARGET=""
vcurl() {
    if [ -n "$V_TARGET" ]; then ssh "$V_TARGET" curl -s "$@"
    else curl -s "$@"; fi
}

verify_report() { # verify_report <api-base> <site-base>
    local api="$1" site="$2"
    local tmp; tmp="$(mktemp -d)"
    local fails=0 checks=0
    check() { # check <name> <ok|bad> <detail>
        checks=$((checks + 1))
        if [ "$2" = ok ]; then printf '  PASS  %-13s %s\n' "$1" "$3"
        else printf '  FAIL  %-13s %s\n' "$1" "$3"; fails=$((fails + 1)); fi
    }
    # 1. health
    local health; health="$(vcurl -m 10 "$api/v1/health" || true)"
    printf '%s' "$health" >"$tmp/m-health.json"
    if [[ "$health" == *'"status": "ok"'* ]]; then
        check health ok "status ok, witness_seq $(printf '%s' "$health" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("witness_seq"))' 2>/dev/null)"
    else check health bad "no ok status: $(printf '%s' "$health" | head -c 120)"; fi

    # 2. TEST 7622 — must read LIVE on Robinhood, same as canonical
    local test_m; test_m="$(vcurl -m 60 -X POST -H Content-Type:application/json -d '{"agentId":7622}' "$api/v1/test" || true)"
    printf '%s' "$test_m" >"$tmp/m-test.json"
    local grade chain
    grade="$(printf '%s' "$test_m" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("your_grade"))' 2>/dev/null)"
    chain="$(printf '%s' "$test_m" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("chainId"))' 2>/dev/null)"
    if [ "$grade" = "LIVE" ] && [ "$chain" = "4663" ]; then
        check test-7622 ok "grade LIVE, chainId 4663 (robinhood)"
    else check test-7622 bad "grade=$grade chainId=$chain (want LIVE / 4663)"; fi

    # 3. standing — top entry
    local standing; standing="$(vcurl -m 30 "$api/v1/standing" || true)"
    printf '%s' "$standing" >"$tmp/m-standing.json"
    local top; top="$(printf '%s' "$standing" | python3 -c 'import sys,json;e=json.load(sys.stdin)["entries"][0];print(e["agentId"],e["score"],e["chainId"])' 2>/dev/null)"
    if [ -n "$top" ]; then check standing ok "top entry: agent $top"
    else check standing bad "no ranked entries in response"; fi

    # 4. /node page (static, served by the front door)
    local node_resp node_body node_status
    node_resp="$(vcurl -m 10 -w "||STATUS=%{http_code}" "$site/node" || true)"
    node_status="${node_resp##*||STATUS=}"
    node_body="${node_resp%||STATUS=*}"
    if [ "$node_status" = "200" ] && [[ "$node_body" == *"MAD NODE"* ]]; then
        check node ok "200, node page served"
    else check node bad "status=$node_status"; fi

    # 5. free sample stream (bounded read — the wire stays open)
    local sample_resp sample_body sample_status
    sample_resp="$(vcurl -m 10 -w "||STATUS=%{http_code}" "$api/v1/stream/sample" || true)"
    sample_status="${sample_resp##*||STATUS=}"
    sample_body="${sample_resp%||STATUS=*}"
    if [ "$sample_status" = "200" ] && [[ "$sample_body" == *"data:"* ]]; then
        check sample ok "200, SSE events replaying"
    elif [ "$sample_status" = "200" ]; then
        check sample bad "200 but no SSE data in the first 10s (ring empty?)"
    else check sample bad "status=$sample_status"; fi

    # 6. paid stream without payment — must be 402
    local stream_resp stream_status
    stream_resp="$(vcurl -m 10 -w "||STATUS=%{http_code}" -o /dev/null "$api/v1/stream" || true)"
    stream_status="${stream_resp##*||STATUS=}"
    if [ "$stream_status" = "402" ]; then check stream-402 ok "402 without payment"
    else check stream-402 bad "status=$stream_status (want 402)"; fi

    # 7. landing page
    local land_resp land_body land_status
    land_resp="$(vcurl -m 10 -w "||STATUS=%{http_code}" "$site/" || true)"
    land_status="${land_resp##*||STATUS=}"
    land_body="${land_resp%||STATUS=*}"
    if [ "$land_status" = "200" ] && [[ "$land_body" == *"blocks graded"* ]]; then
        check landing ok "200, contains 'blocks graded'"
    else check landing bad "status=$land_status"; fi

    # 8. Tokyo directory JSON (static file, rebuilt from the sweep data)
    local tp_resp tp_body tp_status tp_total
    tp_resp="$(vcurl -m 10 -w "||STATUS=%{http_code}" "$site/v1/tokyo-pass" || true)"
    tp_status="${tp_resp##*||STATUS=}"
    tp_body="${tp_resp%||STATUS=*}"
    tp_total="$(printf '%s' "$tp_body" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total"))' 2>/dev/null)"
    if [ "$tp_status" = "200" ] && [ "$tp_total" = "109" ]; then
        check tokyo-pass ok "200, total 109 agents"
    else check tokyo-pass bad "status=$tp_status total=$tp_total (want 200 / 109)"; fi

    # --- same responses as the canonical API? (only when it answers here) --
    if curl -fsS -m 10 http://127.0.0.1:8402/v1/health >/dev/null 2>&1; then
        curl -fsS -m 10 http://127.0.0.1:8402/v1/health >"$tmp/c-health.json" 2>/dev/null || true
        curl -fsS -m 60 -X POST -H Content-Type:application/json -d '{"agentId":7622}' \
            http://127.0.0.1:8402/v1/test >"$tmp/c-test.json" 2>/dev/null || true
        curl -fsS -m 30 http://127.0.0.1:8402/v1/standing >"$tmp/c-standing.json" 2>/dev/null || true
        python3 - "$tmp" <<'CMP_EOF'
import json, sys
d = sys.argv[1]
def load(n):
    try:
        with open("%s/%s" % (d, n)) as f: return json.load(f)
    except Exception:
        return None
mh, ch = load("m-health.json"), load("c-health.json")
mt, ct = load("m-test.json"), load("c-test.json")
ms, cs = load("m-standing.json"), load("c-standing.json")
print("  --- vs canonical (127.0.0.1:8402) ---")
if mh and ch:
    print("  health:  mirror witness_seq=%s  canonical witness_seq=%s  signer match=%s"
          % (mh.get("witness_seq"), ch.get("witness_seq"),
             mh.get("signer") == ch.get("signer")))
    if mh.get("witness_seq") != ch.get("witness_seq"):
        print("  note: witness_seq differs — the mirror is a snapshot; "
              "re-sync the ledgers at cutover (see MIGRATION.md)")
if mt and ct:
    print("  test:    mirror grade=%s chain=%s  canonical grade=%s chain=%s  match=%s"
          % (mt.get("your_grade"), mt.get("chainId"),
             ct.get("your_grade"), ct.get("chainId"),
             mt.get("your_grade") == ct.get("your_grade")
             and mt.get("chainId") == ct.get("chainId")))
if ms and cs:
    me = (ms.get("entries") or [{}])[0]
    ce = (cs.get("entries") or [{}])[0]
    print("  standing: mirror top agent=%s score=%s  canonical top agent=%s score=%s  match=%s"
          % (me.get("agentId"), me.get("score"), ce.get("agentId"), ce.get("score"),
             me.get("agentId") == ce.get("agentId") and me.get("score") == ce.get("score")))
CMP_EOF
    else
        echo "  (canonical API not answering on 127.0.0.1:8402 — comparison skipped)"
    fi
    rm -rf "$tmp"
    echo "verification: $((checks - fails))/$checks checks passed"
    [ "$fails" = 0 ]
}

# --- remote deploy -----------------------------------------------------------
remote_prep() { # remote_prep <target> <sudo> — OS check, packages, user, dirs
    local target="$1" sudo="$2"
    ssh "$target" $sudo bash -s <<'PREP_EOF'
set -euo pipefail
. /etc/os-release
if [ "$VERSION_ID" != "24.04" ]; then echo "FATAL: need Ubuntu 24.04, found $VERSION_ID" >&2; exit 1; fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx rsync ufw curl
id mad 2>/dev/null || useradd -m -s /bin/bash mad
mkdir -p /home/mad/workspace /var/www/madcheck.xyz /var/www/api
chown mad:mad /home/mad/workspace /var/www/api
chown mad:mad /home/mad
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow 8443/tcp >/dev/null 2>&1 || true
ufw allow 80/tcp >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
echo "prep done: $PRETTY_NAME"
PREP_EOF
}

remote_install() { # remote_install <target> <sudo> — units + front door
    local target="$1" sudo="$2"
    ssh "$target" $sudo bash -s <<'UNITS_EOF'
set -euo pipefail
cat > /etc/systemd/system/mad-api.service <<'UNIT'
[Unit]
Description=MAD Check API (public)
After=network-online.target
Wants=network-online.target

[Service]
User=mad
WorkingDirectory=/home/mad/workspace/mad-check-api
ExecStart=/home/mad/venv/bin/python server.py
Environment=MAD_PORT=8402
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/mad-grader-base.service <<'UNIT'
[Unit]
Description=MAD block grader (Base)
After=network-online.target
Wants=network-online.target

[Service]
User=mad
WorkingDirectory=/home/mad/workspace/mad-block-grader
ExecStart=/home/mad/venv/bin/python grader.py --blocks 1000000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/mad-grader-rh.service <<'UNIT'
[Unit]
Description=MAD block grader (Robinhood)
After=network-online.target
Wants=network-online.target

[Service]
User=mad
WorkingDirectory=/home/mad/workspace/mad-block-grader
ExecStart=/home/mad/venv/bin/python grader_robinhood.py --blocks 1000000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/mad-tokyo-pass.service <<'UNIT'
[Unit]
Description=MAD PASS Tokyo directory writer
After=network-online.target
Wants=network-online.target

[Service]
User=mad
WorkingDirectory=/home/mad/workspace/mad-pass-tokyo
ExecStart=/home/mad/venv/bin/python push_tokyo_pass.py --interval 60
Environment=TOKYO_PASS_OUT=/var/www/api/tokyo-pass.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/nginx/sites-available/madcheck <<'NGINX'
server {
    listen 80;
    server_name madcheck.xyz www.madcheck.xyz;
    root /var/www/madcheck.xyz;
    index index.html;
    location = /node { rewrite ^ /node.html break; }
    location = /v1/tokyo-pass {
        alias /var/www/api/tokyo-pass.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin *;
    }
    location / { try_files $uri $uri/ =404; }
}
server {
    listen 80;
    server_name api.madcheck.xyz;
    client_max_body_size 10m;
    location = /v1/tokyo-pass {
        alias /var/www/api/tokyo-pass.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin *;
    }
    location = /node {
        alias /var/www/madcheck.xyz/node.html;
        default_type text/html;
    }
    location / {
        proxy_pass http://127.0.0.1:8402;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/madcheck /etc/nginx/sites-enabled/madcheck
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now mad-api mad-grader-base mad-grader-rh mad-tokyo-pass
systemctl reload nginx || systemctl restart nginx
echo "units + front door up"
UNITS_EOF
}

cmd_remote() {
    local target="$1"
    case "$target" in *@*:*) ;; *) die "target must be user@host" ;; esac
    [ -f "$API_SRC/server.py" ] || die "canonical API not found at $API_SRC/server.py"
    [ -f "$LANDING_SRC" ] || die "landing page not found at $LANDING_SRC"
    [ -f "$NODE_PAGE_SRC" ] || die "node page not found at $NODE_PAGE_SRC"
    [ -f "$HOME/.secrets/mad_wallet.json" ] || die "missing ~/.secrets/mad_wallet.json — the API cannot sign without it"

    log "checking ssh to $target"
    ssh -o ConnectTimeout=20 "$target" 'echo ok' >/dev/null || die "ssh to $target failed"
    local sudo_cmd="" rsync_path="rsync"
    if ssh "$target" 'test "$(id -u)" = 0'; then
        log "target user is root"
    else
        ssh "$target" 'sudo -n true' 2>/dev/null \
            || die "target needs passwordless sudo (or run as root)"
        sudo_cmd="sudo"; rsync_path="sudo rsync"
        log "target user has passwordless sudo"
    fi

    log "preparing the box (packages, user, dirs, firewall)"
    remote_prep "$target" "$sudo_cmd"

    log "syncing the payload"
    sync_api_code "$target:$REMOTE_API/" -e ssh --rsync-path="$rsync_path"
    if ! ssh "$target" $sudo_cmd test -f "$REMOTE_API/ledger.jsonl"; then
        log "fresh deploy: syncing the canonical ledgers once"
        sync_ledgers "$target:$REMOTE_API/" -e ssh --rsync-path="$rsync_path"
    else
        log "re-deploy: keeping the target's own ledgers (never overwritten)"
    fi
    sync_grader_code "$target:$REMOTE_GRADER/" -e ssh --rsync-path="$rsync_path"
    sync_pass_data "$target:$REMOTE_PASS/" -e ssh --rsync-path="$rsync_path"
    rsync -a -e ssh --rsync-path="$rsync_path" "$LANDING_SRC" "$target:$SITE_ROOT/index.html"
    rsync -a -e ssh --rsync-path="$rsync_path" "$NODE_PAGE_SRC" "$target:$SITE_ROOT/node.html"

    # Secrets: copied only if the target does not already have them.
    ssh "$target" $sudo_cmd mkdir -p "$REMOTE_HOME/.secrets"
    ssh "$target" $sudo_cmd chown mad:mad "$REMOTE_HOME/.secrets"
    for key in mad_wallet.json priors_facilitator_key.json; do
        [ -f "$HOME/.secrets/$key" ] || { log "skip missing secret: $key"; continue; }
        if ! ssh "$target" $sudo_cmd test -f "$REMOTE_HOME/.secrets/$key"; then
            rsync -a --chmod=0600 -e ssh --rsync-path="$rsync_path" \
                "$HOME/.secrets/$key" "$target:$REMOTE_HOME/.secrets/$key"
            ssh "$target" $sudo_cmd chown mad:mad "$REMOTE_HOME/.secrets/$key"
            ssh "$target" $sudo_cmd chmod 0600 "$REMOTE_HOME/.secrets/$key"
            log "copied secret $key to the target (0600, mad only)"
        fi
    done

    log "building the venv on the target"
    ssh "$target" sudo -u mad python3 -m venv "$REMOTE_VENV"
    ssh "$target" sudo -u mad "$REMOTE_VENV/bin/pip" install -q --upgrade pip
    ssh "$target" sudo -u mad "$REMOTE_VENV/bin/pip" install -q $PINNED_DEPS

    log "patching the Tokyo writer to file output (same merge, no remote put)"
    rsync -a -e ssh --rsync-path="$rsync_path" "$SCRIPT_DIR/deploy-mirror.sh" "$target:/tmp/deploy-mirror.sh"
    ssh "$target" sudo -u mad bash /tmp/deploy-mirror.sh __patch_pass "$REMOTE_PASS/push_tokyo_pass.py"
    ssh "$target" sudo -u mad env TOKYO_PASS_OUT="$TOKYO_PASS_OUT" \
        "$REMOTE_VENV/bin/python" "$REMOTE_PASS/push_tokyo_pass.py" --once

    log "installing units + front door"
    remote_install "$target" "$sudo_cmd"

    log "waiting for the API on the box (up to 180s)..."
    local i=0
    while [ "$i" -lt 180 ]; do
        if ssh "$target" "curl -fsS -m 5 http://127.0.0.1:$API_PORT_REMOTE/v1/health" 2>/dev/null | grep -q '"status": "ok"'; then
            break
        fi
        sleep 5; i=$((i + 5))
    done
    [ "$i" -lt 180 ] || die "API did not come up on the box; check: ssh $target 'sudo systemctl status mad-api'"

    V_TARGET="$target"
    verify_report "http://127.0.0.1:$API_PORT_REMOTE" "http://127.0.0.1"
    log "remote mirror deployed on $target"
    log "next: verify DNS, then flip it (see MIGRATION.md), then run: $0 --tls $target"
}

cmd_tls() { # cmd_tls <user@host> — run AFTER DNS points at the box
    local target="$1"
    case "$target" in *@*:*) ;; *) die "target must be user@host" ;; esac
    log "issuing TLS certs (needs DNS already pointing at the box)"
    ssh "$target" sudo certbot --nginx -d madcheck.xyz -d www.madcheck.xyz -d api.madcheck.xyz \
        --non-interactive --agree-tos -m madcheck@proton.me --redirect \
        || die "certbot failed — DNS probably does not point at the box yet"
    ssh "$target" "curl -fsS -m 10 https://api.madcheck.xyz/v1/health" | grep -q '"status": "ok"' \
        && log "TLS live: https://api.madcheck.xyz/v1/health answers ok" \
        || die "certs issued but https://api.madcheck.xyz/v1/health does not answer"
}

# --- main --------------------------------------------------------------------
main() {
    case "${1:-}" in
        --help|-h|"") usage; exit 0 ;;
        --local) cmd_local ;;
        --local-stop) cmd_local_stop ;;
        --tls) [ -n "${2:-}" ] || die "--tls needs <user@host>"; cmd_tls "$2" ;;
        __patch_pass) [ -n "${2:-}" ] || die "__patch_pass needs a file"; patch_pass_to_file "$2" ;;
        --*) die "unknown option: $1 (see --help)" ;;
        *) cmd_remote "$1" ;;
    esac
}
main "$@"
