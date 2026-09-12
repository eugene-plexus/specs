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
#
# Runtime checks (docker or podman):
#   10. the image builds
#   11. the container reports healthy
#   12. inside it, all four components are listening on 0.0.0.0
#   13. the UI is served on the published 8079 from outside
#   14. the control root answers on the published 8083 from outside
#   15. the library's 8082 is NOT reachable from outside
#   16. a stop runs the agent's and all three children's lifespan shutdown
#   17. state survives down + up: the same install comes back
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
  skip "10-17. no container runtime on this machine or in WSL."
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
if $DCP build >/dev/null 2>&1; then
  ok "10. the image builds"
else
  bad "10. the image did not build -- re-run without the output suppressed:"
  printf '        %s build\n' "$DCP"
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
[ "$health" = healthy ] && ok "11. the container reports healthy" \
                        || bad "11. health stayed '$state' -- $DCP logs"

# 12 is read from INSIDE, because a loopback bind is invisible from
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
[ -z "$missing" ] && ok "12. all four components listen on 0.0.0.0 inside the container" \
                  || bad "12. these are not on 0.0.0.0 inside the container:$missing (wide: $wide, all: $binds)"

say "runtime: the surface from outside"
root=$(curl -fsS -m 5 http://127.0.0.1:8079/ 2>/dev/null | head -c 200)
if printf '%s' "$root" | grep -q '<!DOCTYPE html>' \
   && ! printf '%s' "$root" | grep -qi 'no web UI installed'; then
  ok "13. the UI is served on the published 8079"
else
  bad "13. / on 8079 returned: $(printf '%s' "$root" | head -c 80)"
fi

ctl=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8083/healthz 2>/dev/null)
case "$ctl" in
  200|503) ok "14. the control root answers on the published 8083 (HTTP $ctl)" ;;
  *)       bad "14. the control root returned '$ctl' on 8083" ;;
esac

lib=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8082/healthz 2>/dev/null)
[ -z "$lib" ] || [ "$lib" = 000 ] \
  && ok "15. the library's 8082 is not published, as intended" \
  || bad "15. 8082 answered '$lib' from outside -- it should not be published"

say "runtime: stopping is graceful, and state survives"
$DCP stop >/dev/null 2>&1
logs=$($DCP logs --no-color 2>/dev/null | tr -d '\r')
own=$(printf '%s' "$logs" | grep -cE '(^|\| *)INFO: +Application shutdown complete')
kids=0
for k in control gateway library; do
  printf '%s' "$logs" | grep -qE "\[$k\] INFO: +Application shutdown complete" && kids=$((kids + 1))
done
[ "$kids" = 3 ] && [ "$own" -ge 1 ] \
  && ok "16. the agent and all three children ran their ASGI lifespan shutdown" \
  || bad "16. graceful shutdown: agent=$own children=$kids/3"

$DCP up -d >/dev/null 2>&1
for _ in $(seq 1 45); do curl -sf -m 2 http://127.0.0.1:8079/healthz >/dev/null 2>&1 && break; sleep 1; done
decl=$($CT exec "$CID" sh -c "grep -c '^- kind: ' /data/agent.yaml" 2>/dev/null | tr -d '\r')
[ "${decl:-0}" = 3 ] && ok "17. state survived the restart: the same three components are declared" \
                     || bad "17. /data/agent.yaml declares '${decl:-0}' components after a restart"

$DCP down -v >/dev/null 2>&1 || true

say "result"
printf '  %d checks, %d failures\n' "$CHECKS" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
