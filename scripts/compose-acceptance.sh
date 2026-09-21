#!/usr/bin/env bash
#
# Install-paths §9 step 5 acceptance: the control-plane image and Compose file.
#
# TWO HALVES, AND THE SPLIT IS DELIBERATE. The structural checks below
# need no container runtime and are real regression guards — several of
# them derive what they expect from the agent's own source rather than
# restating it, so a new component kind or a moved config path fails
# here instead of at somebody's first `up`. The runtime checks need
# docker or podman and SKIP loudly when there is none, naming the two
# commands that close them; they are not quietly dropped.
#
# THE CLAIM THE RUNTIME HALF EXISTS FOR is that the four services inside
# the container bind 0.0.0.0. A component binds loopback unless its node
# advertises a non-loopback address — and inside a container there is no
# address to advertise at build time and no config file to write it
# into. A loopback bind is invisible from the outside: the published
# port simply refuses, and every "is it up?" check that runs INSIDE the
# container passes. So the binds are read from inside and the reachable
# surface is read from outside, and both are required.
#
# Structural checks (no runtime):
#    1. compose.yaml parses and declares exactly one service
#    2. it publishes 8079/8080/8083 and NOT the library's 8082
#    3. the volume is mounted at the parent of the config file the image sets
#    4. init is on and the stop grace period beats the runtime's 10s default
#    5. the image sets a BIND_HOST for every kind the agent can spawn
#       -- the expected set is read from the agent's _COMPONENT_SPECS
#    6. the image installs via scripts/install.sh, so pins live in one file
#    7. the base image pins a Debian release, not a floating `stable`
#    8. it runs as a non-root user
#    9. the command declares --unattended rather than relying on no TTY
#   10. the image, the Unraid template and the Compose file agree on
#       where the models volume is mounted -- the directory the image
#       tells the library to scan
#
# Runtime checks (docker or podman):
#   11. the image builds
#   12. the container reports healthy
#   13. inside it, all four components are listening on 0.0.0.0
#   14. the UI is served on the published 8079 from outside
#   15. the control root answers on the published 8083 from outside
#   16. the library's 8082 is NOT reachable from outside
#   17. with nothing mounted at /models, the library reports its default
#       directory MISSING and its health degraded, rather than scanning
#       an empty directory inside the container
#   18. a stop runs the agent's and all three children's lifespan shutdown
#   19. state survives down + up: the same install comes back
#   20. the image runs as --user 99:100 against a directory OWNED by
#       99:100 -- the uid it does not contain, and the one the Unraid
#       template ships
#   21. a data directory whose logs/ it cannot write degrades to console
#       output instead of killing the agent
#   23. the container declares a hostname, so the control host does not
#       enrol under its own container ID
#   22. a GGUF in a directory mounted at /models is catalogued at
#       startup with nobody having opened Config
#
# Design: docs/design/install-paths-and-distribution.md §9 step 5, §1, §4
set -uo pipefail

FAILURES=0
CHECKS=0
say()  { printf '\n== %s\n' "$*"; }
ok()   { CHECKS=$((CHECKS + 1)); printf '  PASS  %s\n' "$*"; }
bad()  { CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1)); printf '  FAIL  %s\n' "$*"; }
skip() { printf '  SKIP  %s\n' "$*"; }

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
COMPOSE="$REPO/docker/compose.yaml"
DOCKERFILE="$REPO/docker/Dockerfile"
TEMPLATE="$REPO/unraid/eugene-plexus.xml"
# The agent checkout, for the checks that derive their expectations from
# its source instead of repeating them.
AGENT_SRC="${EP_AGENT_SRC:-$REPO/../agent/src/eugene_plexus_agent}"

# ---------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------
say "structural: the Compose file"

py() { python "$@"; }

# Git Bash hands out `/d/py/...`, which the Windows python this script
# finds cannot open -- the first run of this script failed all four
# Compose checks with a FileNotFoundError wearing a check's clothes.
# Convert once, here, rather than at each call site.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}
COMPOSE_P=$(winpath "$COMPOSE")
TEMPLATE_P=$(winpath "$TEMPLATE")
SUPERVISOR_P=$(winpath "$AGENT_SRC/supervisor.py")

svc_count=$(py -c "
import yaml
d = yaml.safe_load(open(r'$COMPOSE_P', encoding='utf-8'))
print(len(d.get('services') or {}))
" 2>&1)
[ "$svc_count" = 1 ] && ok "1. exactly one service -- an agent, not four components" \
                     || bad "1. $svc_count services; the container runs an agent that supervises the rest"

ports=$(py -c "
import yaml
d = yaml.safe_load(open(r'$COMPOSE_P', encoding='utf-8'))
s = next(iter(d['services'].values()))
print(' '.join(sorted(str(p).split(':')[-1] for p in s.get('ports', []))))
" 2>&1)
if [ "$ports" = "8079 8080 8083" ]; then
  ok "2. publishes 8079/8080/8083 and leaves the library's 8082 closed"
else
  bad "2. published container ports are '$ports', expected '8079 8080 8083'"
fi

# 3 cross-checks two files against each other. Moving the config path in
# the Dockerfile without moving the mount would otherwise produce a
# container that starts, works, and loses everything on recreate.
cfg_dir=$(grep -oE 'EUGENE_PLEXUS_AGENT_CONFIG_FILE=[^ ]+' "$DOCKERFILE" | head -1 | cut -d= -f2)
cfg_dir=$(dirname "$cfg_dir")
mount_at=$(py -c "
import yaml
d = yaml.safe_load(open(r'$COMPOSE_P', encoding='utf-8'))
s = next(iter(d['services'].values()))
print(' '.join(str(v).split(':')[1] for v in s.get('volumes', []) if ':' in str(v)))
" 2>&1)
if [ "$cfg_dir" = "$mount_at" ]; then
  ok "3. the volume is mounted at $mount_at, which is where the image puts agent.yaml"
else
  bad "3. the image writes config under '$cfg_dir' but the volume is mounted at '$mount_at'"
fi

initflag=$(py -c "
import yaml
d = yaml.safe_load(open(r'$COMPOSE_P', encoding='utf-8'))
s = next(iter(d['services'].values()))
print(s.get('init'), s.get('stop_grace_period'))
" 2>&1)
case "$initflag" in
  "True 60s"|"True 90s"|"True 120s")
    ok "4. init is on and the stop grace period is $(echo "$initflag" | cut -d' ' -f2)" ;;
  *)
    bad "4. init/stop_grace_period are '$initflag'; a supervisor as PID 1 needs a reaper and more than 10s to stop its children" ;;
esac

# 23a. **A node cannot be renamed, so the name it takes on its first
# boot is the name forever.** It comes from `socket.gethostname()` at
# enrollment (`enrollment.py`), and a container's default hostname is its
# own container ID -- so without an explicit one the control host enrols
# as something like `468e3ed662bf` and wears that hex string in the node
# registry, the Config tab, the resource tree and Home's "kept on ..."
# line. Found on the live install 2026-09-16, after it had been true for
# every containerised install ever made.
compose_host=$(py -c "
import yaml
d = yaml.safe_load(open(r'$COMPOSE_P', encoding='utf-8'))
print((d['services']['control-plane'].get('hostname') or '').strip())
" 2>&1)
tmpl_host=$(py -c "
import xml.etree.ElementTree as ET
print('--hostname' in (ET.parse(r'$TEMPLATE_P').getroot().findtext('ExtraParams') or ''))
" 2>&1)
[ -n "$compose_host" ] && [ "$tmpl_host" = "True" ] \
  && ok "23. Compose sets hostname '$compose_host' and the template passes --hostname" \
  || bad "23. no explicit hostname (compose '$compose_host', template --hostname $tmpl_host); the control host would enrol as its container ID"

say "structural: the image"

# 5 is the one that matters most, and it reads the answer out of the
# agent rather than restating it: every component kind the supervisor
# can spawn needs its BIND_HOST widened, or that component comes up on
# loopback inside the container and is unreachable through a published
# port. A kind added later fails here.
if [ -d "$AGENT_SRC" ]; then
  expected=$(py -c "
import re, pathlib
src = pathlib.Path(r'$SUPERVISOR_P').read_text(encoding='utf-8')
print(' '.join(sorted(set(re.findall(r'env_prefix=\"(EUGENE_PLEXUS_[A-Z_]+)\"', src)))))
" 2>&1)
  missing=""
  for prefix in $expected; do
    grep -q "${prefix}_BIND_HOST=0.0.0.0" "$DOCKERFILE" || missing="$missing $prefix"
  done
  if [ -n "$expected" ] && [ -z "$missing" ]; then
    ok "5. every spawnable kind has BIND_HOST widened ($(echo "$expected" | wc -w | tr -d ' ') of them, read from the agent's own spec table)"
  else
    bad "5. BIND_HOST missing for:$missing (expected set from supervisor.py: $expected)"
  fi
else
  skip "5. agent checkout not at $AGENT_SRC -- set EP_AGENT_SRC to check the BIND_HOST set"
fi

grep -q 'install.sh --prefix' "$DOCKERFILE" \
  && ok "6. the image installs by running scripts/install.sh, so the pins live in one file" \
  || bad "6. the image does not use install.sh -- pins would be duplicated"

base=$(grep -oE '^FROM +[^ ]+' "$DOCKERFILE" | head -1 | awk '{print $2}')
case "$base" in
  *:stable*|*:latest|*:rolling*)
    bad "7. base image '$base' floats -- it becomes a different major version on release day" ;;
  *:*)
    ok "7. base image is pinned to a release ($base)" ;;
  *)
    bad "7. base image '$base' has no tag at all" ;;
esac

grep -qE '^USER +[a-z]' "$DOCKERFILE" \
  && ok "8. the image drops to a non-root user" \
  || bad "8. no USER instruction -- the control plane would run as root"

grep -q '\-\-unattended' "$DOCKERFILE" \
  && ok "9. the command declares --unattended rather than relying on there being no TTY" \
  || bad "9. no --unattended; a docker run -it would hang on the first-boot question"

# 10 cross-checks three files, as 3 does two. The image tells the library
# which directory the models volume is mounted at
# (EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS); the Unraid template mounts
# "Models" somewhere; the Compose file's example mount names a path. Move
# one without the others and the container starts, works, and scans a
# directory nothing is mounted at -- reported missing, correctly, and
# still a broken install.
img_roots=$(grep -oE 'EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=[^ ]+' "$DOCKERFILE" | head -1 | cut -d= -f2)
tpl_roots=$(py -c "
import re, pathlib
src = pathlib.Path(r'$TEMPLATE_P').read_text(encoding='utf-8')
m = re.search(r'Name=\"Models\"\s+Target=\"([^\"]+)\"', src)
print(m.group(1) if m else '')
" 2>&1)
tpl_var=$(py -c "
import re, pathlib
src = pathlib.Path(r'$TEMPLATE_P').read_text(encoding='utf-8')
m = re.search(r'Target=\"EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS\"\s+Default=\"([^\"]+)\"', src)
print(m.group(1) if m else '')
" 2>&1)
compose_roots=$(grep -oE '^ *#? *- /[^:]+:/[^ ]+' "$COMPOSE" | head -1 | sed 's/.*://')
if [ -n "$img_roots" ] && [ "$img_roots" = "$tpl_roots" ] && [ "$img_roots" = "$tpl_var" ] \
   && [ "$img_roots" = "$compose_roots" ]; then
  ok "10. the image tells the library to scan $img_roots, which is where the template and the Compose file mount the models"
else
  bad "10. models path disagrees: image '$img_roots', template Models '$tpl_roots', template variable '$tpl_var', compose '$compose_roots'"
fi

# ---------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------
RT=""
for c in docker podman; do command -v "$c" >/dev/null 2>&1 && { RT=$c; break; }; done
if [ -z "$RT" ] && command -v wsl.exe >/dev/null 2>&1; then
  for c in docker podman; do
    wsl.exe -e bash -c "command -v $c" >/dev/null 2>&1 && { RT="wsl:$c"; break; }
  done
fi

if [ -z "$RT" ]; then
  say "runtime: skipped"
  skip "11-23. no container runtime on this machine or in WSL."
  printf '        To close them, install one and re-run:\n'
  printf '            wsl -d Ubuntu -- sudo apt-get install -y docker.io\n'
  printf '            wsl -d Ubuntu -- sudo usermod -aG docker $USER   # then restart the distro\n'
  printf '        or Docker Desktop on Windows. Then:\n'
  printf '            bash scripts/compose-acceptance.sh\n'
  say "result"
  printf '  %d checks, %d failures (runtime half not run)\n' "$CHECKS" "$FAILURES"
  [ "$FAILURES" -eq 0 ] || exit 1
  exit 0
fi

case "$RT" in
  wsl:*) DC="wsl.exe -e ${RT#wsl:} compose"; CT="wsl.exe -e ${RT#wsl:}" ;;
  *)     DC="$RT compose";                   CT="$RT" ;;
esac
say "runtime: using $RT"

# A compose project name of its own so this never touches a real deployment.
PROJECT=ep-compose-accept
DCP="$DC -p $PROJECT -f $COMPOSE"

$DCP down -v >/dev/null 2>&1 || true

say "runtime: build"
BUILD_LOG=$(mktemp)
if $DCP build >"$BUILD_LOG" 2>&1; then
  rm -f "$BUILD_LOG"
  ok "11. the image builds"
else
  bad "11. the image did not build:"
  cat "$BUILD_LOG"
  rm -f "$BUILD_LOG"
  $DCP down -v >/dev/null 2>&1 || true
  say "result"; printf '  %d checks, %d failures\n' "$CHECKS" "$FAILURES"; exit 1
fi

$DCP up -d >/dev/null 2>&1
CID=$($DCP ps -q control-plane 2>/dev/null | tr -d '\r')

health=unhealthy
for _ in $(seq 1 60); do
  state=$($CT inspect -f '{{.State.Health.Status}}' "$CID" 2>/dev/null | tr -d '\r')
  [ "$state" = healthy ] && { health=healthy; break; }
  sleep 2
done
[ "$health" = healthy ] && ok "12. the container reports healthy" \
                        || bad "12. health stayed '$state' -- $DCP logs"

# 13 is read from INSIDE, because a loopback bind is invisible from
# outside: the published port just refuses, and every in-container "is
# it up" check passes regardless.
binds=$($CT exec "$CID" sh -c "cat /proc/net/tcp | awk 'NR>1 {print \$2}'" 2>/dev/null | tr -d '\r' \
        | awk -F: '{print strtonum("0x" $2)}' | sort -n | tr '\n' ' ')
wide=$($CT exec "$CID" sh -c "cat /proc/net/tcp | awk 'NR>1 && \$2 ~ /^00000000:/ {print \$2}'" 2>/dev/null \
        | tr -d '\r' | awk -F: '{print strtonum("0x" $2)}' | sort -n | tr '\n' ' ')
missing=""
for p in 8079 8080 8082 8083; do
  case " $wide " in *" $p "*) : ;; *) missing="$missing $p" ;; esac
done
[ -z "$missing" ] && ok "13. all four components listen on 0.0.0.0 inside the container" \
                  || bad "13. these are not on 0.0.0.0 inside the container:$missing (wide: $wide, all: $binds)"

# 23b. The hostname the CONTAINER REALLY HAS, read off the container
# Compose started -- not off one this script launched itself.
#
# The first version of this check ran its own `docker run` with no
# `--hostname` and then asserted the hostname was not the container id.
# It could only ever fail, and it did, in CI, on the very commit that
# added the setting: "the container's hostname is 'f98493efad09' and its
# id is 'f98493efad09'". The subject was a container that had never been
# given the thing under test. Same family as M10's check 7 and the
# tool-call fragmentation checks: an assertion pointed somewhere its
# subject was not.
if [ -n "$CID" ]; then
  got=$($CT exec "$CID" hostname 2>/dev/null | tr -d '\r\n')
  short=$(printf '%s' "$CID" | cut -c1-12)
  if [ -n "$got" ] && [ "$got" != "$short" ]; then
    ok "23b. the Compose container's hostname is '$got', not its id '$short' -- it will not enrol as hex"
  else
    bad "23b. the container's hostname is '$got' against id '$short' -- it would enrol as a hex string"
  fi
else
  bad "23b. no compose container to read a hostname from"
fi

say "runtime: the surface from outside"
root=$(curl -fsS -m 5 http://127.0.0.1:8079/ 2>/dev/null | head -c 200)
if printf '%s' "$root" | grep -q '<!DOCTYPE html>' \
   && ! printf '%s' "$root" | grep -qi 'no web UI installed'; then
  ok "14. the UI is served on the published 8079"
else
  bad "14. / on 8079 returned: $(printf '%s' "$root" | head -c 80)"
fi

ctl=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8083/healthz 2>/dev/null)
case "$ctl" in
  200|503) ok "15. the control root answers on the published 8083 (HTTP $ctl)" ;;
  *)       bad "15. the control root returned '$ctl' on 8083" ;;
esac

lib=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8082/healthz 2>/dev/null)
[ -z "$lib" ] || [ "$lib" = 000 ] \
  && ok "16. the library's 8082 is not published, as intended" \
  || bad "16. 8082 answered '$lib' from outside -- it should not be published"

say "runtime: the library knows where the models are, and says so when they are not there"
# 17. The Compose file ships with the models line commented, so nothing is
# mounted at /models and the image does not create it. The library must
# not scan an empty directory inside the container -- a download would
# land in the container's own layer and die with the next recreate -- but
# report the image's default root missing and its health degraded. Read
# from inside, because 16 just proved 8082 is not reachable from here.
libhealth=""
for _ in $(seq 1 45); do
  libhealth=$($CT exec "$CID" curl -fsS -m 3 http://127.0.0.1:8082/healthz 2>/dev/null | tr -d '\r')
  printf '%s' "$libhealth" | grep -q '"unreadableRoots"' && break
  sleep 2
done
verdict=$(printf '%s' "$libhealth" | py -c "
import json, sys
try:
    h = json.load(sys.stdin)
except Exception as exc:
    print('unparseable:', exc); raise SystemExit
d = h.get('details') or {}
print(h.get('status'), d.get('rootsConfigured'), ' '.join(d.get('unreadableRoots') or []))
" 2>&1)
[ "$verdict" = "degraded 1 /models" ] \
  && ok "17. with nothing mounted, the library reports its default /models MISSING and goes degraded, rather than scanning an empty directory" \
  || bad "17. library health with nothing mounted: '$verdict' (expected 'degraded 1 /models'); body: $(printf '%s' "$libhealth" | head -c 200)"

say "runtime: stopping is graceful, and state survives"
$DCP stop >/dev/null 2>&1
logs=$($DCP logs --no-color 2>/dev/null | tr -d '\r')
own=$(printf '%s' "$logs" | grep -cE '(^|\| *)INFO: +Application shutdown complete')
kids=0
for k in control gateway library; do
  printf '%s' "$logs" | grep -qE "\[$k\] INFO: +Application shutdown complete" && kids=$((kids + 1))
done
[ "$kids" = 3 ] && [ "$own" -ge 1 ] \
  && ok "18. the agent and all three children ran their ASGI lifespan shutdown" \
  || bad "18. graceful shutdown: agent=$own children=$kids/3"

$DCP up -d >/dev/null 2>&1
for _ in $(seq 1 45); do curl -sf -m 2 http://127.0.0.1:8079/healthz >/dev/null 2>&1 && break; sleep 1; done
decl=$($CT exec "$CID" sh -c "grep -c '^- kind: ' /data/agent.yaml" 2>/dev/null | tr -d '\r')
[ "${decl:-0}" = 3 ] && ok "19. state survived the restart: the same three components are declared" \
                     || bad "19. /data/agent.yaml declares '${decl:-0}' components after a restart"

$DCP down -v >/dev/null 2>&1 || true

# ---------------------------------------------------------------------
# 22. The other half of "Where the models go": a directory mounted at
# /models is scanned at startup with nobody having opened Config, and a
# GGUF in it is catalogued. The file is written here against the
# documented GGUF layout -- magic, version 3, tensor and KV counts, then
# KV pairs -- rather than copied from anywhere, so the fixture cannot
# agree with the reader about something wrong. Mounted READ-ONLY: the
# claim is "catalogued as they are", and a scanner that needed to write
# into the operator's directory would fail here, which is the point.
#
# Runs before the sudo-gated checks because it needs no root: the
# directory is world-readable, which is what every user share is.
# ---------------------------------------------------------------------
say "runtime: a directory mounted at /models is catalogued with nobody having opened Config"
MODELSDIR=$(mktemp -d)
chmod 755 "$MODELSDIR"
py - "$MODELSDIR/acceptance-7B-Q4_K_M.gguf" <<'PY'
import struct, sys

def s(text):
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw

def kv(key, value):
    out = s(key)
    if isinstance(value, bool):
        return out + struct.pack("<I", 7) + struct.pack("<?", value)
    if isinstance(value, int):
        return out + struct.pack("<I", 4) + struct.pack("<I", value)
    if isinstance(value, float):
        return out + struct.pack("<I", 6) + struct.pack("<f", value)
    if isinstance(value, str):
        return out + struct.pack("<I", 8) + s(value)
    if isinstance(value, list):
        head = struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", len(value))
        return out + head + b"".join(s(v) for v in value)
    raise TypeError(type(value))

pairs = {
    "general.architecture": "llama",
    "general.type": "model",
    "general.name": "Acceptance 7B",
    "general.size_label": "7B",
    "llama.block_count": 32,
    "llama.context_length": 4096,
    "llama.embedding_length": 4096,
    "tokenizer.ggml.tokens": [f"tok{i}" for i in range(16)],
    "general.quantization_version": 2,
    "general.file_type": 15,
}
body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(pairs))
for key, value in pairs.items():
    body += kv(key, value)
with open(sys.argv[1], "wb") as fh:
    fh.write(body + b"\0" * 4096)
PY
chmod 644 "$MODELSDIR"/*.gguf

$CT rm -f ep-models-check >/dev/null 2>&1 || true
if $CT run -d --name ep-models-check --init -v "$MODELSDIR:/models:ro" -p 18279:8079 \
     eugene-plexus/control-plane:0.1 >/dev/null 2>&1; then
  verdict=""
  for _ in $(seq 1 60); do
    body=$($CT exec ep-models-check curl -fsS -m 3 http://127.0.0.1:8082/healthz 2>/dev/null | tr -d '\r')
    verdict=$(printf '%s' "$body" | py -c "
import json, sys
try:
    h = json.load(sys.stdin)
except Exception:
    print('starting'); raise SystemExit
d = h.get('details') or {}
print(h.get('status'), d.get('rootsConfigured'), d.get('modelsKnown'), d.get('scanState'))
" 2>/dev/null)
    case "$verdict" in *" done"|*" failed") break ;; esac
    sleep 2
  done
  [ "$verdict" = "ok 1 1 done" ] \
    && ok "22. a GGUF in a read-only directory mounted at /models is catalogued at startup, with nobody having opened Config" \
    || { bad "22. library health with /models mounted: '$verdict' (expected 'ok 1 1 done')"
         $CT logs ep-models-check 2>&1 | grep -i 'library' | tail -8 | sed 's/^/      /'; }
else
  bad "22. could not start the image with a directory mounted at /models"
fi
$CT rm -f ep-models-check >/dev/null 2>&1 || true
rm -rf "$MODELSDIR"

# ---------------------------------------------------------------------
# 20. The UnRAID case: a uid the image has never heard of.
#
# `unraid/eugene-plexus.xml` ships `--user 99:100` because that is what a
# NAS owns its appdata with, and the image bakes in uid 10001. So the
# container runs as a uid with **no /etc/passwd entry**, which is the
# part that can actually break: `$HOME` resolves to nothing, and an agent
# that insisted on a writable home would die on first start with an error
# that reads like our bug rather than a permissions mistake.
#
# `container.md` has claimed this works since step 5, verified as a plain
# process. This is the same claim in a container, which is where the
# template puts it.
#
# The directory is made world-writable rather than chowned because that
# needs root on the host and this script must not. Ownership is an
# ordinary filesystem concern the NAS gets right on its own; the unknown
# uid is the part worth proving.
# ---------------------------------------------------------------------
say "runtime: the Unraid case -- an unknown uid, and a directory it does not own"

# The first version of this check made the directory `chmod 777`, which
# meant it could not fail the way reality did: on 2026-09-12 an operator
# mounted a data directory owned by uid 10001 into a container running as
# `--user 99:100` and the agent died on `/data/logs/agent.log`. A
# world-writable fixture proves the uid has no home directory and nothing
# about ownership, which is the half that broke. So: real ownership, via
# sudo, and skipped rather than faked where sudo is not free.
UIDDIR=$(mktemp -d)
if sudo -n chown 99:100 "$UIDDIR" 2>/dev/null; then
  chmod 755 "$UIDDIR"

  $CT rm -f ep-uid-check >/dev/null 2>&1 || true
  if $CT run -d --name ep-uid-check --init --user 99:100 \
       -v "$UIDDIR:/data" -p 18079:8079 \
       eugene-plexus/control-plane:0.1 >/dev/null 2>&1; then
    uidok=""
    for _ in $(seq 1 90); do
      curl -sf -m 2 http://127.0.0.1:18079/healthz >/dev/null 2>&1 && { uidok=yes; break; }
      sleep 1
    done
    [ -n "$uidok" ] \
      && ok "20. healthy as uid 99:100 against a directory owned by 99:100" \
      || { bad "20. as --user 99:100 the agent never answered /healthz"
           $CT logs ep-uid-check 2>&1 | tail -12 | sed 's/^/      /'; }
  else
    bad "20. could not start the image with --user 99:100"
  fi
  $CT rm -f ep-uid-check >/dev/null 2>&1 || true

  # 21. The reported failure exactly: /data writable, logs/ not.
  #
  # `install_console_capture` used to die here, because
  # `mkdir(exist_ok=True)` does not care who owns an existing directory
  # and the handler that opens the file inside it does. A mirrored log is
  # a convenience and the console copy still works, so this must degrade
  # rather than take the supervisor down with it -- `degraded-mode-required`
  # applied to the agent's own conveniences instead of only to config.
  LOGDIR=$(mktemp -d)
  sudo -n chown 99:100 "$LOGDIR" 2>/dev/null
  sudo -n mkdir -p "$LOGDIR/logs" 2>/dev/null
  sudo -n chown 0:0 "$LOGDIR/logs" 2>/dev/null
  sudo -n chmod 755 "$LOGDIR/logs" 2>/dev/null

  $CT rm -f ep-logs-check >/dev/null 2>&1 || true
  if $CT run -d --name ep-logs-check --init --user 99:100 \
       -v "$LOGDIR:/data" -p 18179:8079 \
       eugene-plexus/control-plane:0.1 >/dev/null 2>&1; then
    logok=""
    for _ in $(seq 1 90); do
      curl -sf -m 2 http://127.0.0.1:18179/healthz >/dev/null 2>&1 && { logok=yes; break; }
      sleep 1
    done
    if [ -n "$logok" ]; then
      said=$($CT logs ep-logs-check 2>&1 | grep -c "console output only")
      [ "${said:-0}" -ge 1 ] \
        && ok "21. an unwritable logs/ degrades to console output and says so" \
        || bad "21. it came up with an unwritable logs/ but never said the file copy was off"
    else
      bad "21. an unwritable logs/ stopped the agent -- the defect this check exists for"
      $CT logs ep-logs-check 2>&1 | tail -12 | sed 's/^/      /'
    fi
  else
    bad "21. could not start the image for the unwritable-logs case"
  fi
  $CT rm -f ep-logs-check >/dev/null 2>&1 || true
  sudo -n rm -rf "$LOGDIR" 2>/dev/null || rm -rf "$LOGDIR"
else
  skip "20-21. passwordless sudo is needed to own a directory as 99:100; faking it with"
  printf '        chmod 777 would remove the very thing these check.
'
fi
rm -rf "$UIDDIR"

say "result"
printf '  %d checks, %d failures\n' "$CHECKS" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
