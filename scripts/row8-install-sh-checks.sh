#!/usr/bin/env bash
# Row 8, the POSIX half -- `install.sh`'s `--label`, and its Mac system
# layout driven on stand-ins for the Mac's tools, with no network and no
# root.
#
# Design: docs/design/rows/row-08.md. Run on Linux (CI's POSIX installer job,
# or WSL from a Windows box). It never touches a real install: `$HOME` is a
# throwaway folder, every prefix is under the work folder, and the Mac runs
# use a COPY of install.sh whose two root paths -- the LaunchDaemons folder
# and the receipts folder -- are rewritten into the work folder. That is the
# only edit, and the copy is checked for it before anything runs.
#
# Stand-ins: `uv`, `curl`, `systemctl`, `loginctl` (as r22 has them), and for
# the Mac `uname`, `sudo`, `dscl`, `dseditgroup`, `id` (for Eugene's account
# only, and root for U1), `launchctl`, `plutil` (Python's plistlib, so the
# plist is really parsed), `ditto`, `install`, `chown` and `chmod` (owners
# and ACL entries kept in files, as `ls -lden` then prints them), `ls`
# (`-lden` only), `mv` (what was recorded follows a rename), `mkdir`,
# `tar` (GNU tar, each call logged with what its input is), `lsof`, `ps`,
# `df` and `sleep` (no waiting). Every branch of install.sh is real. What a
# stand-in cannot show -- launchd running the job as the account, real ACLs,
# Metal, the firewall -- is the macOS acceptance's
# (row8-macos-daemon-acceptance.py, on GitHub's macOS runners).
#
#   L1. --label without --join is refused, before anything is made
#   L2. --label 'Studio PC' reaches the agent's join as one argument; so do
#       an apostrophe and a dollar sign
#   L3. a job site's join takes --label before --name
#   M1. on a Mac the default layout is the system one: a LaunchDaemon in
#       _eugeneplexus, no LaunchAgent, the account hidden with no shell and
#       no password, in the person's group, a free number below 400, the
#       receipt, the passphrase file, passphrase_file mode
#   M2. a plist naming root, or nobody, or an account numbered 0, is refused
#       and never moved into place
#   M3. --user beside the daemon is refused
#   M4. a LaunchAgent install moves: words first, its state copied, paths and
#       securityMode rewritten, its port kept, the old folder moved aside
#   M5. launchctl refusing the daemon puts the LaunchAgent back, with
#       launchctl's words, the old folder untouched and the copy and the
#       account removed
#   M6. a move refuses --no-start
#   M7. a link Eugene's account left under its prefix is refused, and root
#       never makes, chowns or chmods through it
#   M4b. a copied engine build stays only when every file matches the
#       record the agent made at download; a changed one, one with no
#       record and a link are not kept, and the newest that went is listed
#       for the agent to fetch again (R8-ENGINES-COPY)
#   M8. a move commits only when launchd's daemon is what answers; not
#       when (b) another process listens on the port too, (c) the job's
#       program only starts with the agent's name, (d) the process changes
#       between the samples and the health answer, or (e) the same pid runs
#       another program by the second sample
#   M9. a rollback that cannot stop the daemon does not start the
#       LaunchAgent beside it
#   M10. the old folder is kept inside a folder root made and closed, so an
#       ACL entry on the old folder, or one the new folder inherited, opens
#       nothing; M11, an entry root cannot take off stops the move
#   M12. a link swapped in for the old folder after the checks is never
#       followed and stops the move; M13, one swapped in as it is renamed
#       is refused inside root's folder and renamed back
#   M13b. ~/.local/share swapped for a link to a folder of root's: the
#       rename is the person's, so nothing of root's moves; M13c, an
#       interrupt once the old folder is kept puts it back before anything
#       is removed; M13d, an old folder on another disk is refused; M13e,
#       a size that cannot be read is refused; M13f, a folder that grows
#       while it is copied is cut off
#   M14. a refused move takes out the home's ACL entry it added, though the
#       models group was there before; M15, so does a refused fresh
#       install; M15b, one that will not come out is said and its receipt
#       kept; M2, an entry an earlier install made stays (read by name:
#       `ls -len` prints the group as a UUID)
#   M16. a staff membership an earlier build gave the account is taken back
#   M17. a disk without room for the copy is refused, with the numbers
#   U1. root's removal, run by root alone, takes the home's entry out,
#       deletes the copy a move kept, and closes what it keeps
#   M1 and M4 also hold the review's other fixes: the models group in place
#   of staff, the copy read as the person (a planted link stays a link)
#   and streamed with nothing but names and contents restored, and the
#   old folder kept in root's closed folder.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
INSTALL_SH=$HERE/install.sh
WORK=${EP_WORKDIR:-/tmp/ep-row8}

FAILURES=0
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
say() { printf '\n== %s\n' "$*"; }
show() { printf '%s\n' "$1" | tail -n "${2:-8}" | sed 's/^/      /'; }

[ -f "$INSTALL_SH" ] || { echo "no install.sh at $INSTALL_SH" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is needed for the plist stand-in" >&2; exit 2; }
rm -rf "$WORK"
mkdir -p "$WORK"

# --- stand-ins shared by every run ---------------------------------------
write_common_stubs() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/uv" <<'STUB'
#!/bin/sh
case "$1" in
  --version) echo "uv 0.12.22 (stub)" ;;
  venv)
    for last in "$@"; do :; done
    mkdir -p "$last/bin"
    cp "$EP_STUB_BIN/python-stub" "$last/bin/python"
    cp "$EP_STUB_BIN/agent-stub" "$last/bin/eugene-plexus-agent"
    chmod +x "$last/bin/python" "$last/bin/eugene-plexus-agent"
    ;;
esac
exit 0
STUB
  # The install's Python: answers the two questions install.sh asks of it
  # by -c, runs a script given on stdin with -I (the move's rewrite), and
  # swallows everything else (the package check).
  cat > "$bin/python-stub" <<'STUB'
#!/bin/sh
case "$*" in
  *platform.machine*) echo arm64; exit 0 ;;
  *os.path.realpath*) echo "$(dirname "$(dirname "$0")")/../pythons/cpython-3.12/bin/python3.12"; exit 0 ;;
esac
if [ "${1:-}" = -I ] && [ "${2:-}" = - ]; then shift 2; exec python3 -I - "$@"; fi
cat >/dev/null 2>&1 || true
exit 0
STUB
  # The agent: records every argument on a line of its own.
  cat > "$bin/agent-stub" <<'STUB'
#!/bin/sh
for a in "$@"; do printf '%s\n' "$a"; done > "${EP_STUB_ARGS:-/dev/null}"
exit 0
STUB
  # EP_STUB_PID_FLIP: each health answer comes from another process than
  # the one before it (the daemon's pid moves between 4242 and 4343).
  cat > "$bin/curl" <<'STUB'
#!/bin/sh
case "$*" in
  *healthz*)
    [ "${EP_STUB_HEALTH_FAILS:-0}" = 1 ] && exit 7
    if [ "${EP_STUB_PID_FLIP:-0}" = 1 ]; then
      if [ "$(cat "$EP_STUB_STATE/daemon-pid" 2>/dev/null || echo 4242)" = 4242 ]; then
        echo 4343 > "$EP_STUB_STATE/daemon-pid"
      else
        echo 4242 > "$EP_STUB_STATE/daemon-pid"
      fi
    fi
    exit 0 ;;
esac
OUTFILE=
prev=
for a in "$@"; do
  [ "$prev" = "-o" ] && OUTFILE=$a
  prev=$a
done
emit() {
  case "$*" in
    *astral.sh/uv/install.sh*)
      echo 'mkdir -p "$UV_UNMANAGED_INSTALL"'
      echo 'cp "$EP_STUB_BIN/uv" "$UV_UNMANAGED_INSTALL/uv"'
      ;;
    *) echo ok ;;
  esac
}
if [ -n "$OUTFILE" ] && [ "$OUTFILE" != /dev/null ]; then emit "$@" > "$OUTFILE"; else emit "$@"; fi
exit 0
STUB
  for name in systemctl loginctl; do
    printf '#!/bin/sh\ncase "$*" in *Linger*) echo yes ;; esac\nexit 0\n' > "$bin/$name"
  done
  chmod +x "$bin"/*
}

# --- stand-ins for a Mac ----------------------------------------------------
write_mac_stubs() {
  local bin=$1
  printf '#!/bin/sh\ncase "${1:-}" in -m) echo arm64 ;; *) echo Darwin ;; esac\n' > "$bin/uname"
  # Not root here: sudo runs the command as this account, and says so in a
  # log, so a check can tell what ran with root's access.
  # EP_STUB_AS says whom the command runs as, for the stand-ins that
  # emulate a permission (mv): root, or the account sudo -u names.
  cat > "$bin/sudo" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/sudo.log"
EP_STUB_AS=root
while [ $# -gt 0 ]; do
  case "$1" in -v|-n) shift ;; -u) EP_STUB_AS=$2; shift 2 ;; --) shift; break ;; *) break ;; esac
done
export EP_STUB_AS
[ $# -gt 0 ] || exit 0
exec "$@"
STUB
  # The directory service, kept in a file. 400 is taken, so the account
  # must get 399.
  cat > "$bin/dscl" <<'STUB'
#!/bin/sh
state=$EP_STUB_STATE/dscl
shift
verb=$1; shift
printf '%s %s\n' "$verb" "$*" >> "$EP_STUB_STATE/dscl.log"
case "$verb" in
  -list)
    case "$1" in
      /Users) printf 'root 0\ndaemon 1\n_taken 400\n'
              grep '^/Users/[^ ]* UniqueID ' "$state" 2>/dev/null | sed 's|^/Users/||; s/ UniqueID / /' ;;
      /Groups) printf 'wheel 0\nstaff 20\n'
               grep '^/Groups/[^ ]* PrimaryGroupID ' "$state" 2>/dev/null | sed 's|^/Groups/||; s/ PrimaryGroupID / /' ;;
    esac ;;
  -read)
    if [ "${2:-}" = NFSHomeDirectory ] && [ "$1" = "/Users/$EP_STUB_PERSON" ]; then
      echo "NFSHomeDirectory: $HOME"; exit 0
    fi
    v=$(grep "^$1 ${2:-} " "$state" 2>/dev/null | tail -n 1 | cut -d' ' -f3-)
    [ -n "$v" ] || exit 56
    echo "${2}: $v" ;;
  -create)
    [ $# -ge 3 ] && printf '%s %s %s\n' "$1" "$2" "$3" >> "$state"
    touch "$state" ;;
  -delete)
    sed -i "\\|^$1 |d" "$state" 2>/dev/null || true ;;
esac
exit 0
STUB
  cat > "$bin/dseditgroup" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/dseditgroup.log"
case "$*" in *checkmember*) exit 1 ;; esac
exit 0
STUB
  # `id` for Eugene's account comes from the directory service; anything
  # else is the real one.
  cat > "$bin/id" <<'STUB'
#!/bin/sh
for a in "$@"; do
  if [ "$a" = _eugeneplexus ]; then
    uid=$(grep '^/Users/_eugeneplexus UniqueID ' "$EP_STUB_STATE/dscl" 2>/dev/null | tail -n 1 | cut -d' ' -f3)
    gid=$(grep '^/Users/_eugeneplexus PrimaryGroupID ' "$EP_STUB_STATE/dscl" 2>/dev/null | tail -n 1 | cut -d' ' -f3)
    [ -n "$uid" ] || exit 1
    [ -z "${EP_STUB_ACCOUNT_UID:-}" ] || uid=$EP_STUB_ACCOUNT_UID
    case "$1" in -u) echo "$uid" ;; -g) echo "$gid" ;; -Gn) echo _eugeneplexus ;; *) echo "uid=$uid(_eugeneplexus)" ;; esac
    exit 0
  fi
done
# The removal runs as root: EP_STUB_ROOT makes `id -u` say so.
if [ "${EP_STUB_ROOT:-0}" = 1 ] && [ "$*" = -u ]; then echo 0; exit 0; fi
exec /usr/bin/id "$@"
STUB
  # launchd: a bootstrapped system job runs as pid 4242 (unless it is told
  # to stay silent; the pid is in state/daemon-pid when a check moves it),
  # and lsof and ps say what that pid is. EP_STUB_SWAP_OLD: once the daemon
  # starts -- after the move's checks and copy -- a program running as the
  # person puts a link where the old folder was.
  cat > "$bin/launchctl" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/launchctl.log"
pid=$(cat "$EP_STUB_STATE/daemon-pid" 2>/dev/null || echo 4242)
case "$*" in
  "bootstrap system "*)
    if [ "${EP_STUB_LAUNCHCTL_FAIL:-}" = bootstrap ]; then
      echo "Bootstrap failed: 5: Input/output error" >&2; exit 5
    fi
    [ "${EP_STUB_DAEMON_SILENT:-0}" = 1 ] || touch "$EP_STUB_STATE/daemon-running"
    [ "${EP_STUB_SWAP_OLD:-0}" != 1 ] || "$EP_STUB_BIN/swap-old" ;;
  "bootout system/"*)
    if [ "${EP_STUB_BOOTOUT_FAILS:-0}" = 1 ]; then
      echo "Boot-out failed: 5: Input/output error" >&2; exit 5
    fi
    rm -f "$EP_STUB_STATE/daemon-running" ;;
  "print system/"*)
    if [ -f "$EP_STUB_STATE/daemon-running" ] || [ "${EP_STUB_DAEMON_LOADED:-0}" = 1 ]; then
      printf 'system/com.eugeneplexus.agent = {\n\tstate = running\n\tpid = %s\n}\n' "$pid"; exit 0
    fi
    exit 113 ;;
  print*) exit 113 ;;
esac
exit 0
STUB
  # The old folder swapped for a link to a folder of someone else's, as a
  # program running as the person could do it while the move runs.
  cat > "$bin/swap-old" <<'STUB'
#!/bin/sh
old=$HOME/.local/share/eugene-plexus
[ -L "$old" ] && exit 0
/bin/mv "$old" "$old.real" && ln -s "${EP_STUB_STATE%/state}/victim" "$old"
STUB
  # Every listener on the port: the daemon's pid, and EP_STUB_EXTRA_LISTENER
  # (another process listening there as well) after it.
  cat > "$bin/lsof" <<'STUB'
#!/bin/sh
pid=$(cat "$EP_STUB_STATE/daemon-pid" 2>/dev/null || echo 4242)
[ -f "$EP_STUB_STATE/daemon-running" ] && echo "$pid"
[ -z "${EP_STUB_EXTRA_LISTENER:-}" ] || echo "$EP_STUB_EXTRA_LISTENER"
exit 0
STUB
  # The daemon's command line; EP_STUB_PS_PROGRAM_SUFFIX makes its program
  # one whose name only starts with the agent's, and EP_STUB_ARGV_FLIP has
  # the same pid run another program at every second look (an exec).
  cat > "$bin/ps" <<'STUB'
#!/bin/sh
pid=$(cat "$EP_STUB_STATE/daemon-pid" 2>/dev/null || echo 4242)
case "$*" in
  *"-p $pid")
    suffix=${EP_STUB_PS_PROGRAM_SUFFIX:-}
    if [ "${EP_STUB_ARGV_FLIP:-0}" = 1 ]; then
      n=$(( $(cat "$EP_STUB_STATE/ps-looks" 2>/dev/null || echo 0) + 1 ))
      echo "$n" > "$EP_STUB_STATE/ps-looks"
      [ $((n % 2)) = 1 ] || suffix=-exec
    fi
    echo "$EP_STUB_VENV/bin/python $EP_STUB_VENV/bin/eugene-plexus-agent$suffix --unattended"
    exit 0 ;;
esac
exec /bin/ps "$@"
STUB
  # macOS's chmod: ACL entries are kept in state/acl, one "path<TAB>entry"
  # a line (+a adds, -a takes one out, -N takes all of a path's out unless
  # EP_STUB_ACL_STICKS), and -h on a link changes nothing it points to.
  cat > "$bin/chmod" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/chmod.log"
acl=$EP_STUB_STATE/acl
touch "$acl"
nofollow=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h) nofollow=1; shift ;;
    -f|-v) shift ;;
    +a)
      for p in "$3"; do printf '%s\t%s\n' "$p" "$2" >> "$acl"; done
      exit 0 ;;
    -a)
      [ "${EP_STUB_ACL_REMOVE_FAILS:-0}" != 1 ] || { echo "chmod: Failed to remove ACL entry" >&2; exit 1; }
      awk -F '\t' -v p="$3" -v e="$2" '!($1 == p && $2 == e)' "$acl" > "$acl.new" && /bin/mv "$acl.new" "$acl"
      exit 0 ;;
    -N)
      shift
      [ "${EP_STUB_ACL_STICKS:-0}" = 1 ] && exit 0
      for p in "$@"; do
        awk -F '\t' -v p="$p" '$1 != p' "$acl" > "$acl.new" && /bin/mv "$acl.new" "$acl"
      done
      exit 0 ;;
    *) break ;;
  esac
done
if [ "$nofollow" = 1 ]; then
  for last do :; done
  [ -L "$last" ] && exit 0
fi
exec /bin/chmod "$@"
STUB
  # `ls -lden PATH` and `ls -led PATH`, as macOS prints them: the owner
  # chown recorded (root:wheel is 0 0), a + after the mode and one line per
  # ACL entry -- by name under -led, and with the principal as a UUID under
  # -lden, as -n makes macOS print it. EP_STUB_INT_AT_KEEP: the second look
  # at root's keeping folder (just after the old folder went into it)
  # interrupts the installer. Every other ls is the real one.
  cat > "$bin/ls" <<'STUB'
#!/bin/sh
if [ "$#" = 2 ] && { [ "$1" = -lden ] || [ "$1" = -led ]; }; then
  how=$1 p=$2
  if [ "${EP_STUB_INT_AT_KEEP:-0}" = 1 ] && [ "$how" = -lden ]; then
    case "$p" in
      *.moved-[0-9]*/*) ;;
      *.moved-[0-9]*)
        n=$(( $(cat "$EP_STUB_STATE/keep-looks" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$EP_STUB_STATE/keep-looks"
        [ "$n" != 2 ] || pkill -INT -f "$EP_STUB_INSTALLER" ;;
    esac
  fi
  line=$(/bin/ls -ldn "$p") || exit $?
  set -f; set -- $line; set +f
  mode=${1%.}; uid=$3; gid=$4
  own=$(awk -F '\t' -v p="$p" '$1 == p {o = $2} END {print o}' "$EP_STUB_STATE/owners" 2>/dev/null)
  [ "$own" != root:wheel ] || { uid=0; gid=0; }
  entries=$(awk -F '\t' -v p="$p" '$1 == p {print $2}' "$EP_STUB_STATE/acl" 2>/dev/null)
  [ -z "$entries" ] || mode="$mode+"
  printf '%s 1 %s %s 0 Jan 1 00:00 %s\n' "$mode" "$uid" "$gid" "$p"
  if [ -n "$entries" ] && [ "$how" = -led ]; then
    printf '%s\n' "$entries" | awk '{printf " %d: %s\n", NR - 1, $0}'
  elif [ -n "$entries" ]; then
    printf '%s\n' "$entries" | awk '{
      split($1, who, ":"); rest = $0; sub(/^[^ ]* /, "", rest)
      printf " %d: %s:ABCDEFAB-CDEF-ABCD-EFAB-%012d %s\n", NR - 1, who[1], length(who[2]) * 7919, rest
    }'
  fi
  exit 0
fi
exec /bin/ls "$@"
STUB
  # mv, with what chmod and chown recorded following the rename. With
  # EP_STUB_SWAP_AT_MV, the old folder is swapped for a link just before it
  # is renamed: the race a check made beforehand cannot see; with
  # EP_STUB_SWAP_SHARE_AT_MV, ~/.local/share is, for a link to a folder of
  # root's (state/../rootlib) holding an `eugene-plexus` of its own. Run as
  # anyone but root, a rename out of a folder recorded as root's is refused,
  # as macOS refuses it.
  cat > "$bin/mv" <<'STUB'
#!/bin/sh
opts=
while [ $# -gt 0 ]; do
  case "$1" in -f|-n|-v|-i) opts="$opts $1"; shift ;; --) shift; break ;; *) break ;; esac
done
old=$HOME/.local/share/eugene-plexus
if [ "${EP_STUB_SWAP_AT_MV:-0}" = 1 ] && [ "$1" = "$old" ] && [ ! -L "$old" ]; then "$EP_STUB_BIN/swap-old"; fi
if [ "${EP_STUB_SWAP_SHARE_AT_MV:-0}" = 1 ] && [ "$1" = "$old" ] && [ ! -L "$HOME/.local/share" ]; then
  /bin/mv "$HOME/.local/share" "$HOME/.local/share.real" && ln -s "${EP_STUB_STATE%/state}/rootlib" "$HOME/.local/share"
fi
# Out of a folder of root's needs its delete_child entry; into one, its
# add_subdirectory entry.
roots_without() {
  [ -n "$1" ] && awk -F '\t' -v p="$1" '$1 == p && $2 == "root:wheel" {f = 1} END {exit !f}' \
      "$EP_STUB_STATE/owners" 2>/dev/null \
    && ! awk -F '\t' -v p="$1" -v r="$2" '$1 == p && $2 ~ ("^user:.* allow .*" r) {f = 1} END {exit !f}' \
      "$EP_STUB_STATE/acl" 2>/dev/null
}
if [ "${EP_STUB_AS:-person}" != root ] && [ -n "${EP_STUB_STATE:-}" ] && [ "$#" = 2 ]; then
  from=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)
  to=$(cd "$(dirname "$2")" 2>/dev/null && pwd -P)
  if roots_without "$from" delete_child || roots_without "$to" add_subdirectory; then
    echo "mv: rename $1 to $2: Permission denied" >&2
    exit 1
  fi
fi
src=$1; into=${2:-}
if [ "$#" = 2 ] && [ -d "$2" ] && [ ! -L "$2" ]; then into=$2/${1##*/}; fi
/bin/mv $opts -- "$@" || exit $?
if [ "$#" = 2 ] && [ -n "${EP_STUB_STATE:-}" ]; then
  for f in "$EP_STUB_STATE/acl" "$EP_STUB_STATE/owners"; do
    [ -f "$f" ] || continue
    awk -F '\t' -v OFS='\t' -v s="$src" -v d="$into" \
      '{ if ($1 == s) $1 = d; else if (index($1, s "/") == 1) $1 = d substr($1, length(s) + 1); print }' \
      "$f" > "$f.new" && /bin/mv "$f.new" "$f"
  done
fi
exit 0
STUB
  # A folder made beside the prefix takes an inheritable entry from its
  # parent when EP_STUB_INHERIT_ACL is set, as /usr/local could hand one on.
  cat > "$bin/mkdir" <<'STUB'
#!/bin/sh
/bin/mkdir "$@" || exit $?
if [ "${EP_STUB_INHERIT_ACL:-0}" = 1 ] && [ -n "${EP_STUB_STATE:-}" ]; then
  for last do :; done
  case "$last" in
    *.moved-*) printf '%s\tgroup:everyone allow list,search\n' "$last" >> "$EP_STUB_STATE/acl" ;;
  esac
fi
exit 0
STUB
  # tar: each call logged with what its standard input is (a pipe, or a
  # file somebody could have swapped); bsdtar's Mac-only flags dropped
  # before GNU tar runs.
  # EP_STUB_GROW: the old folder's control-state grows by 100 MiB once the
  # copy has been measured, as the person's tar starts reading it.
  cat > "$bin/tar" <<'STUB'
#!/bin/sh
if [ -p /dev/stdin ]; then in=pipe; elif [ -f /dev/stdin ]; then in=file; else in=other; fi
printf 'stdin=%s %s\n' "$in" "$*" >> "$EP_STUB_STATE/tar.log"
if [ "${EP_STUB_GROW:-0}" = 1 ] && [ "${1:-}" = -cf ] && [ "${3:-}" = -C ]; then
  case "$4" in
    */.local/share/eugene-plexus) dd if=/dev/zero of="$4/control-state/grown.bin" bs=1048576 count=100 2>/dev/null ;;
  esac
fi
real=/usr/bin/tar
[ -x "$real" ] || real=/bin/tar
for a do
  shift
  case "$a" in --no-fflags|--no-mac-metadata) continue ;; esac
  set -- "$@" "$a"
done
exec "$real" "$@"
STUB
  # df: the real one, or a disk with EP_STUB_DF_FREE_KB free; with
  # EP_STUB_OTHER_DISK the home is on a disk of its own.
  cat > "$bin/df" <<'STUB'
#!/bin/sh
if [ -n "${EP_STUB_DF_FREE_KB:-}" ] || [ "${EP_STUB_OTHER_DISK:-0}" = 1 ]; then
  for last do :; done
  fs=stubfs
  if [ "${EP_STUB_OTHER_DISK:-0}" = 1 ]; then case "$last" in "$HOME"|"$HOME"/*) fs=stubhome ;; esac; fi
  printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n%s 1000000000 1 %s 1%% /\n' \
    "$fs" "${EP_STUB_DF_FREE_KB:-999999999}"
  exit 0
fi
exec /bin/df "$@"
STUB
  # du: the real one, or one that cannot size anything (EP_STUB_DU_FAILS).
  cat > "$bin/du" <<'STUB'
#!/bin/sh
if [ "${EP_STUB_DU_FAILS:-0}" = 1 ]; then echo "du: fts_read: Permission denied" >&2; exit 1; fi
exec /usr/bin/du "$@"
STUB
  # No waiting: every wait in install.sh is a loop that asks again.
  printf '#!/bin/sh\nexit 0\n' > "$bin/sleep"
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$EP_STUB_STATE/chgrp.log"\nexit 0\n' > "$bin/chgrp"
  # plutil: the plist really parsed, by Python's plistlib.
  cat > "$bin/plutil" <<'STUB'
#!/bin/sh
case "$1" in
  -lint) exec python3 -c 'import plistlib, sys; plistlib.load(open(sys.argv[1], "rb")); print(sys.argv[1] + ": OK")' "$2" ;;
  -extract)
    key=$2; file=$6   # plutil -extract KEY raw -o - FILE
    if [ "$key" = UserName ] && [ -n "${EP_STUB_PLIST_USER+set}" ]; then
      [ -n "$EP_STUB_PLIST_USER" ] || exit 1
      printf '%s' "$EP_STUB_PLIST_USER"; exit 0
    fi
    exec python3 -c '
import plistlib, sys
value = plistlib.load(open(sys.argv[2], "rb"))
for part in sys.argv[1].split("."):
    try:
        value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError):
        sys.exit(1)
sys.stdout.write("true" if value is True else "false" if value is False else str(value))
' "$key" "$file" ;;
esac
exit 1
STUB
  cat > "$bin/ditto" <<'STUB'
#!/bin/sh
if [ -d "$1" ]; then mkdir -p "$2" && cp -R "$1/." "$2/"; else cp -p "$1" "$2"; fi
STUB
  cat > "$bin/install" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/install.log"
if [ "$1" = -d ]; then
  shift; mode=
  while [ $# -gt 0 ]; do
    case "$1" in -m) mode=$2; shift 2 ;; -o|-g) shift 2 ;; *) break ;; esac
  done
  for d in "$@"; do mkdir -p "$d"; [ -z "$mode" ] || /bin/chmod "$mode" "$d"; done
  exit 0
fi
exec /usr/bin/install "$@"
STUB
  # chown: logged, and the owner kept in state/owners for `ls -lden`.
  cat > "$bin/chown" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$EP_STUB_STATE/chown.log"
while [ $# -gt 0 ]; do case "$1" in -h|-R|-f) shift ;; *) break ;; esac; done
owner=$1; shift
for p in "$@"; do printf '%s\t%s\n' "$p" "$owner" >> "$EP_STUB_STATE/owners"; done
exit 0
STUB
  chmod +x "$bin"/*
}

# A copy of install.sh whose two root paths are under the work folder.
mac_copy() {
  local root=$1
  python3 - "$INSTALL_SH" "$root/install.sh" "$root/LaunchDaemons" "$root/receipts" <<'PY'
import sys
source, target, daemons, receipts = sys.argv[1:]
text = open(source, encoding="utf-8").read()
for old, new in (
    ("LAUNCHD_DAEMON=/Library/LaunchDaemons/$LAUNCHD_LABEL.plist\n",
     f"LAUNCHD_DAEMON={daemons}/$LAUNCHD_LABEL.plist\n"),
    ("MAC_RECEIPTS=/usr/local/lib/eugene-plexus\n", f"MAC_RECEIPTS={receipts}\n"),
):
    if text.count(old) != 1:
        sys.exit(f"refusing to run: {old.strip()!r} appears {text.count(old)} times")
    text = text.replace(old, new)
open(target, "w", encoding="utf-8", newline="\n").write(text)
PY
  mkdir -p "$root/LaunchDaemons"
}

# run_linux TAG [args...] -> OUT, RC; a per-user install, as r22 runs it.
run_linux() {
  local tag=$1; shift
  local root=$WORK/$tag
  rm -rf "$root"; mkdir -p "$root/bin" "$root/home" "$root/run"
  write_common_stubs "$root/bin"
  OUT=$(env -i HOME="$root/home" XDG_RUNTIME_DIR="$root/run" PATH="$root/bin:/usr/bin:/bin" \
    EP_STUB_BIN="$root/bin" EP_STUB_ARGS="$root/args.txt" \
    sh "$INSTALL_SH" --user --prefix "$root/prefix" --no-start "$@" 2>&1)
  RC=$?
}

# run_mac TAG [args...] -> OUT, RC; the Mac's default layout, on stand-ins.
# Reuses TAG's folder when it exists, so a second run sees the first.
run_mac() {
  local tag=$1; shift
  ROOT=$WORK/$tag
  if [ ! -d "$ROOT/bin" ]; then
    mkdir -p "$ROOT/bin" "$ROOT/home" "$ROOT/state"
    write_common_stubs "$ROOT/bin"
    write_mac_stubs "$ROOT/bin"
    mac_copy "$ROOT"
  fi
  PREFIX=$ROOT/eugene-plexus
  DAEMON=$ROOT/LaunchDaemons/com.eugeneplexus.agent.plist
  OUT=$(cd "$ROOT" && env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
    EP_STUB_BIN="$ROOT/bin" EP_STUB_STATE="$ROOT/state" EP_STUB_PERSON="$(id -un)" \
    EP_STUB_ARGS="$ROOT/args.txt" EP_STUB_VENV="$ROOT/eugene-plexus/venv" \
    EP_STUB_INSTALLER="$ROOT/install.sh" ${EP_EXTRA_ENV:-} \
    sh "$ROOT/install.sh" --prefix "$PREFIX" "$@" 2>&1)
  RC=$?
}

plist() { python3 -c '
import plistlib, sys
value = plistlib.load(open(sys.argv[1], "rb"))
for part in sys.argv[2].split("."):
    value = value[int(part)] if isinstance(value, list) else value[part]
print(value)' "$1" "$2" 2>/dev/null; }

# What the stand-ins recorded: a path's ACL entries, its last owner, and
# whether ROOT's home carries the models group's entry.
acl_of() { awk -F '\t' -v p="$1" '$1 == p {print $2}' "$ROOT/state/acl" 2>/dev/null; }
owner_of() { awk -F '\t' -v p="$1" '$1 == p {o = $2} END {print o}' "$ROOT/state/owners" 2>/dev/null; }
has_home_ace() {
  awk -F '\t' -v p="$1/home" '$1 == p && $2 == "group:_eugeneplexusmodels allow search" {f = 1} END {exit !f}' \
    "$1/state/acl" 2>/dev/null
}

# --- L. --label ---------------------------------------------------------------
say "L1. --label without --join is refused, before anything is made"
run_linux label-alone --label 'Studio PC'
if [ "$RC" = 2 ] && printf '%s' "$OUT" | grep -q "The first machine's name is asked on its setup page" \
    && [ ! -e "$WORK/label-alone/prefix" ]; then
  ok "refused with the setup page named, and no prefix made"
else
  bad "rc=$RC"; show "$OUT"
fi

say "L2. --label reaches the agent's join as one argument"
for shown in 'Studio PC' "Troy's \$HOME box"; do
  run_linux label-join --join http://192.0.2.10:8083 --token t0k --name studio --label "$shown"
  args=$(cat "$WORK/label-join/args.txt" 2>/dev/null)
  next=$(printf '%s\n' "$args" | awk 'p { print; exit } $0 == "--label" { p = 1 }')
  if [ "$RC" = 0 ] && [ "$next" = "$shown" ] && printf '%s\n' "$args" | grep -qx -- '--name'; then
    ok "join got --label [$shown] whole, after --name"
  else
    bad "rc=$RC; the join got: $(printf '%s' "$args" | tr '\n' '|')"; show "$OUT"
  fi
done

say "L3. a job site's join takes --label before --name"
run_linux label-site
rm -f "$WORK/label-site/args.txt"
OUT=$(env -i HOME="$WORK/label-site/home" XDG_RUNTIME_DIR="$WORK/label-site/run" \
  PATH="$WORK/label-site/bin:/usr/bin:/bin" EP_STUB_BIN="$WORK/label-site/bin" \
  EP_STUB_ARGS="$WORK/label-site/args.txt" \
  sh "$INSTALL_SH" --user --prefix "$WORK/label-site/prefix" --join https://nodes.example.com \
  --token t --job-site --owner ada --name studio --label 'Studio PC' 2>&1)
args=$(cat "$WORK/label-site/args.txt" 2>/dev/null)
if [ "$(printf '%s\n' "$args" | awk 'p { print; exit } $0 == "--label" { p = 1 }')" = 'Studio PC' ] \
    && printf '%s\n' "$args" | head -n 2 | tr '\n' ' ' | grep -q '^site join'; then
  ok "site join got --label 'Studio PC', not the --name"
else
  bad "site join got: $(printf '%s' "$args" | tr '\n' '|')"; show "$OUT"
fi

# --- M. the Mac ---------------------------------------------------------------
say "M1. on a Mac the default is a LaunchDaemon in _eugeneplexus"
run_mac fresh --no-start
STATE=$ROOT/state
if [ "$RC" = 0 ]; then ok "the install ran to the end"; else bad "rc=$RC"; show "$OUT" 15; fi
if [ -f "$DAEMON" ] && [ ! -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ]; then
  ok "a LaunchDaemon plist, and no LaunchAgent"
else
  bad "daemon=$([ -f "$DAEMON" ] && echo yes || echo no) agent=$([ -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && echo yes || echo no)"
fi
if [ "$(plist "$DAEMON" UserName)" = _eugeneplexus ] && [ "$(plist "$DAEMON" GroupName)" = _eugeneplexus ] \
    && [ "$(plist "$DAEMON" ProgramArguments.0)" = "$PREFIX/venv/bin/eugene-plexus-agent" ] \
    && [ "$(plist "$DAEMON" KeepAlive)" = True ] && [ "$(plist "$DAEMON" RunAtLoad)" = True ]; then
  ok "it parses, runs the prefix's agent as _eugeneplexus:_eugeneplexus, and is kept alive"
else
  bad "the plist: $(cat "$DAEMON" 2>/dev/null | tr '\n' ' ' | head -c 600)"
fi
if [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_PASSPHRASE_FILE)" = "$PREFIX/passphrase" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE)" = "$PREFIX/passphrase" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.HOME)" = "$PREFIX" ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_ENGINE_ROOT)" = "$PREFIX/engines" ] \
    && grep -qx 'securityMode: passphrase_file' "$PREFIX/agent.yaml" 2>/dev/null; then
  ok "it unlocks from the passphrase file in the prefix, its home and engines there too"
else
  bad "environment or securityMode: $(grep securityMode "$PREFIX/agent.yaml" 2>/dev/null)"
fi
if grep -qx '/Users/_eugeneplexus UniqueID 399' "$STATE/dscl" \
    && grep -qx '/Users/_eugeneplexus UserShell /usr/bin/false' "$STATE/dscl" \
    && grep -qx '/Users/_eugeneplexus IsHidden 1' "$STATE/dscl" \
    && grep -qx "/Users/_eugeneplexus Password \*" "$STATE/dscl" \
    && grep -qx "/Users/_eugeneplexus NFSHomeDirectory $PREFIX" "$STATE/dscl" \
    && grep -qx '/Groups/_eugeneplexus PrimaryGroupID 399' "$STATE/dscl"; then
  ok "the account: number 399 (400 was taken), no shell, hidden, no password, home the prefix"
else
  bad "the account: $(grep _eugeneplexus "$STATE/dscl" 2>/dev/null | tr '\n' '|')"
fi
# Least privilege (row 8 review): a group of its own for the models
# folder, holding Eugene's account and the person; never the person's own
# group, which on a Mac is staff, every person's.
if grep -qx -- "-o edit -a _eugeneplexus -t user _eugeneplexusmodels" "$STATE/dseditgroup.log" 2>/dev/null \
    && grep -qx -- "-o edit -a $(id -un) -t user _eugeneplexusmodels" "$STATE/dseditgroup.log" \
    && ! grep -q -- "-t user $(id -gn)\$" "$STATE/dseditgroup.log" \
    && grep -qx '/Groups/_eugeneplexusmodels PrimaryGroupID 398' "$STATE/dscl" \
    && [ "$(cat "$ROOT/receipts/models-group.txt" 2>/dev/null)" = "group 398" ]; then
  ok "a models group of its own (398) holds the account and the person; the person's own group is not joined"
else
  bad "groups: $(cat "$STATE/dseditgroup.log" 2>/dev/null | tr '\n' '|')"
fi
models_mode=$(stat -c %a "$ROOT/home/Eugene Models" 2>/dev/null)
if [ "$models_mode" = 2770 ] && grep -qx -- "-h _eugeneplexusmodels $ROOT/home/Eugene Models" "$STATE/chgrp.log" \
    && grep -q -- "+a group:_eugeneplexusmodels allow search $ROOT/home\$" "$STATE/chmod.log" \
    && has_home_ace "$ROOT"; then
  ok "~/Eugene Models is the models group's, 2770, and the home lets that group pass through only"
else
  bad "models folder mode '$models_mode'; chgrp: $(tr '\n' '|' < "$STATE/chgrp.log" 2>/dev/null); acl: $(grep -- '+a' "$STATE/chmod.log" | tr '\n' '|')"
fi
if [ "$(cat "$ROOT/receipts/account.txt" 2>/dev/null)" = "account 399 399 1" ]; then
  ok "the receipt records the account and group this installer made"
else
  bad "receipt: $(cat "$ROOT/receipts/account.txt" 2>/dev/null)"
fi
if [ -f "$ROOT/receipts/remove.sh" ] && grep -q 'DAEMON_PLIST=' "$ROOT/receipts/remove.sh" \
    && [ -x "$ROOT/home/Applications/Remove Eugene Plexus.app/Contents/MacOS/remove" ]; then
  ok "root's own removal script, outside the prefix, and the removal app"
else
  bad "removal: script=$([ -f "$ROOT/receipts/remove.sh" ] && echo yes || echo no)"
fi
if printf '%s' "$OUT" | grep -q 'any program you run as you'; then
  bad "the system layout printed the per-user warning"
fi

say "M2. a startup job for root, for nobody, or for account 0 is refused"
for case_ in "EP_STUB_PLIST_USER=root" "EP_STUB_PLIST_USER=" "EP_STUB_ACCOUNT_UID=0"; do
  rm -f "$DAEMON"
  EP_EXTRA_ENV=$case_ run_mac fresh --no-start
  if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -qi 'refusing a startup job\|must be a service' \
      && [ ! -f "$DAEMON" ]; then
    ok "$case_: refused, and no plist moved into place"
  else
    bad "$case_: rc=$RC daemon=$([ -f "$DAEMON" ] && echo present || echo absent)"; show "$OUT" 4
  fi
done
EP_EXTRA_ENV=
# The home's entry was there before these runs (M1's install made it), so
# a refused run leaves it: only what a run added itself is taken out.
if has_home_ace "$ROOT"; then
  ok "the home's ACL entry from the install before was kept"
else
  bad "a refused run took out the home's ACL entry an earlier install made"
fi

say "M3. --user beside the daemon is refused"
run_mac fresh --no-start
OUT_KEEP=$OUT
EP_EXTRA_ENV= run_mac fresh --user --no-start
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "This Mac already starts Eugene at boot. Re-run without --user to update it." \
    && [ ! -e "$ROOT/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ]; then
  ok "refused, in the design's words, and no LaunchAgent written"
else
  bad "rc=$RC"; show "$OUT" 4; show "$OUT_KEEP" 3
fi

# An engine build as the agent leaves one: install.json, with every file's
# SHA-256 as it was downloaded (row 8, R8-ENGINES-COPY). CONTENT is what
# llama-server holds now, RECORDED what was downloaded; with no RECORDED,
# a build from before the agent kept that record.
engine_build() {
  local dir=$1 when=$2 content=$3 recorded=${4-} sum
  mkdir -p "$dir"
  printf '%s' "$content" > "$dir/llama-server"
  if [ -n "$recorded" ]; then
    sum=$(printf '%s' "$recorded" | sha256sum | cut -d' ' -f1)
    printf '{"version": "%s", "variant": "macos-arm64", "binary": "llama-server", "installedAt": "%s", "files": {"llama-server": "sha256:%s"}, "links": {}}\n' \
      "${dir##*/}" "$when" "$sum" > "$dir/install.json"
  else
    printf '{"version": "%s", "variant": "macos-arm64", "binary": "llama-server", "installedAt": "%s"}\n' \
      "${dir##*/}" "$when" > "$dir/install.json"
  fi
}

# A per-user Mac install as the old layout left it: a LaunchAgent naming
# its prefix, on port 18279, onboarded with the Keychain. Its engine store:
# b1 as downloaded; b2, the newest, changed after it was downloaded; b0
# from before the record; b9 a link to a build somewhere else; and the
# architecture lists, which are not builds.
old_install() {
  local home=$1 old=$1/.local/share/eugene-plexus store=$1/.eugene-plexus/engines/llama_cpp
  mkdir -p "$old/venv/bin" "$old/logs" "$old/control-state" "$home/Library/LaunchAgents" \
    "$store/architectures" "$home/elsewhere"
  engine_build "$store/b1" 2026-10-01T00:00:00+00:00 build build
  engine_build "$store/b2" 2026-10-10T00:00:00+00:00 changed downloaded
  engine_build "$store/b0" 2026-09-01T00:00:00+00:00 old
  engine_build "$home/elsewhere/b9" 2026-10-20T00:00:00+00:00 planted planted
  ln -s "$home/elsewhere/b9" "$store/b9"
  printf '{}\n' > "$store/architectures/b1.json"
  printf 'name: studio\nnodeKey: abc\n' > "$old/node.yaml"
  cat > "$old/agent.yaml" <<YAML
securityMode: os_keyring
firstRunComplete: true
components:
- kind: control
  spawn:
    configFile: $old/control.yaml
modelCopyDir: $old
YAML
  printf 'securityMode: os_keyring\nstateDir: %s/control-state\n' "$old" > "$old/control.yaml"
  printf '{"profiles": {"p1": {"modelPath": "%s/Eugene Models/m.gguf"}}}\n' "$home" > "$old/library-state.json"
  printf 'snapshot\n' > "$old/control-state/snap.bin"
  # A link a program running as the person could plant, to a file the
  # person may not read: the move must copy the link, never what it names.
  printf 'root only\n' > "$home/root-only.txt"
  ln -s "$home/root-only.txt" "$old/planted"
  # A file the person left open to everyone: the copy sets its own modes.
  printf 'loose\n' > "$old/loose.txt"
  chmod 0666 "$old/loose.txt"
  cat > "$home/Library/LaunchAgents/com.eugeneplexus.agent.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.eugeneplexus.agent</string>
    <key>ProgramArguments</key>
    <array><string>$old/venv/bin/eugene-plexus-agent</string><string>--unattended</string></array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>EUGENE_PLEXUS_AGENT_CONFIG_FILE</key><string>$old/agent.yaml</string>
        <key>EUGENE_PLEXUS_AGENT_BIND_PORT</key><string>18279</string>
        <key>EUGENE_PLEXUS_AGENT_BIND_HOST</key><string>0.0.0.0</string>
    </dict>
</dict>
</plist>
PLIST
}

say "M4. a LaunchAgent install moves to the daemon"
mkdir -p "$WORK/move/home"
old_install "$WORK/move/home"
OLD=$WORK/move/home/.local/share/eugene-plexus
run_mac move
STATE=$ROOT/state
if [ "$RC" = 0 ]; then ok "the move finished"; else bad "rc=$RC"; show "$OUT" 15; fi
words=$(printf '%s' "$OUT" | grep -n 'Eugene will start when this Mac starts, before anyone signs in' | cut -d: -f1 | head -n 1)
copied=$(printf '%s' "$OUT" | grep -n 'copying its identity' | cut -d: -f1 | head -n 1)
if [ -n "$words" ] && [ -n "$copied" ] && [ "$words" -lt "$copied" ] \
    && printf '%s' "$OUT" | grep -q 'sign in to Eugene once; from then on'; then
  ok "it says what happens before it does anything"
else
  bad "the words: line ${words:-none}, the copy: line ${copied:-none}"
fi
if grep -q "^bootout gui/$(id -u)/com.eugeneplexus.agent$" "$STATE/launchctl.log" \
    && grep -q "^bootstrap system $DAEMON$" "$STATE/launchctl.log"; then
  ok "the LaunchAgent was booted out and the daemon bootstrapped"
else
  bad "launchctl: $(tr '\n' '|' < "$STATE/launchctl.log")"
fi
if [ "$(cat "$PREFIX/node.yaml" 2>/dev/null)" = "$(printf 'name: studio\nnodeKey: abc')" ] \
    && [ -f "$PREFIX/control-state/snap.bin" ] && [ -f "$PREFIX/library-state.json" ] \
    && [ -f "$PREFIX/engines/llama_cpp/b1/llama-server" ] && [ ! -e "$PREFIX/uninstall" ]; then
  ok "identity, control state, Library state and engine builds came along; the old removal did not"
else
  bad "copied: $(ls -A "$PREFIX" 2>/dev/null | tr '\n' ' ')"
fi
if grep -qx 'securityMode: passphrase_file' "$PREFIX/agent.yaml" \
    && grep -qx 'securityMode: passphrase_file' "$PREFIX/control.yaml" \
    && grep -q "configFile: $PREFIX/control.yaml" "$PREFIX/agent.yaml" \
    && grep -qx "modelCopyDir: $PREFIX" "$PREFIX/agent.yaml" \
    && grep -q "stateDir: $PREFIX/control-state" "$PREFIX/control.yaml" \
    && ! grep -q "$OLD" "$PREFIX/agent.yaml" "$PREFIX/control.yaml" \
    && grep -q "$WORK/move/home/Eugene Models/m.gguf" "$PREFIX/library-state.json"; then
  ok "paths now name the new prefix, the Keychain mode became passphrase_file, models stayed put"
else
  bad "rewritten: $(tr '\n' '|' < "$PREFIX/agent.yaml") // $(tr '\n' '|' < "$PREFIX/control.yaml")"
fi
if [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_PORT)" = 18279 ] \
    && [ "$(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_HOST)" = 0.0.0.0 ]; then
  ok "the daemon keeps the LaunchAgent's port 18279 and its wide bind"
else
  bad "port/host: $(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_PORT) $(plist "$DAEMON" EnvironmentVariables.EUGENE_PLEXUS_AGENT_BIND_HOST)"
fi
# Row 8 review, blocker 2: nothing of the old folder is read with root's
# access, and a link in it arrives as a link.
if [ -L "$PREFIX/planted" ] && [ "$(readlink "$PREFIX/planted")" = "$WORK/move/home/root-only.txt" ] \
    && ! grep -qE '^(ditto|tar -c|cp )' "$STATE/sudo.log" \
    && grep -q -- '-u _eugeneplexus -- env .* tar -x .*-f '"$PREFIX/.move.tar -C $PREFIX" "$STATE/sudo.log"; then
  ok "the old folder was read as the person and written as the account; a planted link stayed a link"
else
  bad "planted: $(ls -l "$PREFIX/planted" 2>&1); root ran: $(grep -E 'ditto|tar' "$STATE/sudo.log" | tr '\n' '|')"
fi
# Row 8 review, blocker 3 and re-review A: the old folder holds the
# machine's keys in clear, so it is kept beside the new prefix INSIDE a
# folder root made and closed (root:wheel, 0700, no ACL entry) -- whatever
# the person left on the old folder itself then opens nothing -- and the
# person is told where it is and how to delete it.
moved=$(ls -d "$PREFIX".moved-* 2>/dev/null | head -n 1)
if [ ! -e "$WORK/move/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && [ ! -e "$OLD" ] \
    && [ -z "$(ls -d "$OLD".moved-* 2>/dev/null)" ] && [ -n "$moved" ] \
    && [ -d "$moved/eugene-plexus" ] && [ ! -L "$moved/eugene-plexus" ] && [ -f "$moved/eugene-plexus/node.yaml" ] \
    && [ "$(stat -c %a "$moved")" = 700 ] && [ "$(owner_of "$moved")" = root:wheel ] && [ -z "$(acl_of "$moved")" ] \
    && [ ! -e "$WORK/move/home/.eugene-plexus/engines" ] \
    && printf '%s' "$OUT" | grep -q "readable by administrators only" \
    && printf '%s' "$OUT" | grep -qF "sudo rm -rf '$moved'"; then
  ok "the LaunchAgent is gone, the old folder kept in root's closed ${moved##*/}, the engine store moved, the way to delete it said"
else
  bad "after: agent plist $([ -e "$WORK/move/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] && echo kept || echo gone), old $([ -e "$OLD" ] && echo kept || echo gone), in home '$(ls -d "$OLD".moved-* 2>/dev/null)', kept in '${moved}' ($(ls -A "$moved" 2>/dev/null | tr '\n' ' ')) mode $(stat -c %a "$moved" 2>/dev/null) owner '$(owner_of "$moved")' acl '$(acl_of "$moved")'"
  show "$OUT" 6
fi
# Re-reviews B and 6: the person's tar streams to the account, which keeps
# the stream in its own prefix (closed to the person: nothing between them
# the person could swap) and cuts it off at what was measured; the
# account's tar restores no owner, permissions, ACL or extended attribute
# from it; the modes are the install's own.
extract=$(grep -F -- "-C $PREFIX" "$STATE/tar.log" 2>/dev/null)
loose_mode=$(stat -c %a "$PREFIX/loose.txt" 2>/dev/null)
if [ -n "$extract" ] && ! printf '%s\n' "$extract" | grep -vqF -- "-f $PREFIX/.move.tar -C $PREFIX" \
    && grep -q -- "-u _eugeneplexus -- env .* sh -c umask 077 && head -c" "$STATE/sudo.log" \
    && [ ! -e "$PREFIX/.move.tar" ] \
    && ! printf '%s\n' "$extract" | tr ' ' '\n' | grep -qE '^-[A-Za-z]*p[A-Za-z]*$' \
    && ! printf '%s\n' "$extract" | grep -v -- '--no-same-owner' | grep -q . \
    && ! printf '%s\n' "$extract" | grep -v -- '--no-same-permissions' | grep -q . \
    && ! printf '%s\n' "$extract" | grep -v -- '--no-acls' | grep -q . \
    && ! printf '%s\n' "$extract" | grep -v -- '--no-xattrs' | grep -q . \
    && [ "$loose_mode" = 600 ]; then
  ok "the copy was kept by the account in its prefix, bounded, restored no owner, mode, ACL or attribute, and set its own modes"
else
  bad "extraction: $(printf '%s' "$extract" | tr '\n' '|'); loose.txt mode '$loose_mode'"
fi
if grep -q '^print system/com.eugeneplexus.agent$' "$STATE/launchctl.log"; then
  ok "the move was committed only once launchd's daemon held the port"
else
  bad "nothing asked launchd which process the daemon is: $(tr '\n' '|' < "$STATE/launchctl.log")"
fi

# R8-ENGINES-COPY: the daemon runs the copied builds as its own account,
# so a copied build stays only when every file is what was downloaded. A
# changed one, one from before the record and a link where a build
# belongs are not kept, and the newest that went is listed for the agent
# to fetch again from upstream when it starts.
say "M4b. a copied engine build stays only when every file matches its record; the rest are fetched again"
E=$PREFIX/engines/llama_cpp
listed=$(python3 -c '
import json, sys
print(" ".join(":".join((b["engine"], b["version"], b["variant"])) for b in json.load(open(sys.argv[1]))["builds"]))
' "$PREFIX/engines/refetch.json" 2>/dev/null)
if [ "$(cat "$E/b1/llama-server" 2>/dev/null)" = build ] && [ ! -e "$E/b2" ] && [ ! -e "$E/b0" ] \
    && [ ! -e "$E/b9" ] && [ ! -L "$E/b9" ] && [ -f "$E/architectures/b1.json" ]; then
  ok "b1 (as downloaded) kept; b2 (changed), b0 (no record) and the link b9 not kept; the architecture lists kept"
else
  bad "engine store after the move: $(ls -A "$E" 2>/dev/null | tr '\n' ' ')"
fi
if [ "$listed" = "llama_cpp:b2:macos-arm64" ] \
    && printf '%s' "$OUT" | grep -q "did not keep the llama_cpp build b2: llama-server changed after it was downloaded" \
    && printf '%s' "$OUT" | grep -q "fetches llama_cpp b2 again from GitHub when it starts"; then
  ok "b2, the newest, is listed to be fetched again, and the move says why"
else
  bad "listed: '$listed'"; show "$OUT" 12
fi

say "M5. launchctl refusing the daemon puts the LaunchAgent back"
rm -rf "$WORK/back"
mkdir -p "$WORK/back/home"
old_install "$WORK/back/home"
OLD=$WORK/back/home/.local/share/eugene-plexus
BEFORE=$(cd "$OLD" && find . -type f -exec sha256sum {} + | sort)
EP_EXTRA_ENV=EP_STUB_LAUNCHCTL_FAIL=bootstrap run_mac back
STATE=$ROOT/state
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'Bootstrap failed: 5: Input/output error'; then
  ok "the run stops with launchctl's own words"
else
  bad "rc=$RC"; show "$OUT" 10
fi
if grep -q "^bootstrap gui/$(id -u) $WORK/back/home/Library/LaunchAgents/com.eugeneplexus.agent.plist$" "$STATE/launchctl.log" \
    && [ -f "$WORK/back/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && printf '%s' "$OUT" | grep -q 'Eugene runs again from'; then
  ok "the LaunchAgent was bootstrapped again and answers"
else
  bad "launchctl: $(tr '\n' '|' < "$STATE/launchctl.log")"; show "$OUT" 4
fi
if [ "$(cd "$OLD" 2>/dev/null && find . -type f -exec sha256sum {} + | sort)" = "$BEFORE" ] \
    && [ -f "$WORK/back/home/.eugene-plexus/engines/llama_cpp/b1/llama-server" ]; then
  ok "the old folder and its engine store are untouched"
else
  bad "the old folder changed"
fi
if [ ! -e "$PREFIX" ] && [ ! -f "$DAEMON" ] && [ ! -f "$ROOT/receipts/account.txt" ] \
    && grep -q '^-delete /Users/_eugeneplexus' "$STATE/dscl.log"; then
  ok "the copy, the daemon plist and the account this run made are gone"
else
  bad "left: prefix=$([ -e "$PREFIX" ] && echo yes || echo no) daemon=$([ -f "$DAEMON" ] && echo yes || echo no) receipt=$([ -f "$ROOT/receipts/account.txt" ] && echo yes || echo no)"
fi

say "M6. a move refuses --no-start, having changed nothing"
rm -rf "$WORK/nostart"
mkdir -p "$WORK/nostart/home"
old_install "$WORK/nostart/home"
run_mac nostart --no-start
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'Re-run without --no-start' && [ ! -e "$PREFIX" ] \
    && [ ! -s "$ROOT/state/launchctl.log" ]; then
  ok "refused before stopping anything"
else
  bad "rc=$RC"; show "$OUT" 4
fi

# Row 8 review, blocker 1: Eugene's account owns its prefix and can put a
# link where its logs folder belongs. Root must never make, chown or chmod
# through it -- here it points at root's own receipts.
say "M7. a link the account left under its prefix is refused, and root never follows it"
run_mac linked --no-start
rm -rf "$PREFIX/logs"
ln -s "$ROOT/receipts" "$PREFIX/logs"
chmod 0755 "$ROOT/receipts"
: > "$ROOT/state/install.log"
run_mac linked --no-start
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "$PREFIX/logs is a link" \
    && ! grep -q "$PREFIX/logs" "$ROOT/state/install.log" \
    && [ "$(stat -c %a "$ROOT/receipts")" = 755 ]; then
  ok "refused, and root's install touched nothing under the prefix"
else
  bad "rc=$RC; root's install: $(tr '\n' '|' < "$ROOT/state/install.log")"; show "$OUT" 4
fi

# not_committed TAG ENV...: a move run with the stand-ins' ENV is never
# committed -- the run fails, the LaunchAgent and its folder are as they
# were and it is started again, and the copy is gone.
not_committed() {
  local tag=$1; shift
  rm -rf "${WORK:?}/$tag"
  mkdir -p "$WORK/$tag/home"
  old_install "$WORK/$tag/home"
  OLD=$WORK/$tag/home/.local/share/eugene-plexus
  EP_EXTRA_ENV="$*" run_mac "$tag"
  EP_EXTRA_ENV=
  [ "$RC" != 0 ] && [ -f "$WORK/$tag/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && [ -f "$OLD/node.yaml" ] && [ ! -L "$OLD" ] && [ ! -e "$PREFIX" ] \
    && grep -q "^bootstrap gui/$(id -u) " "$ROOT/state/launchctl.log"
}

# Row 8 review, item 4: an answer on the port is not the daemon. Here the
# job never starts, and something else answers.
say "M8. a move commits only when launchd's daemon is what answers"
if not_committed silent EP_STUB_DAEMON_SILENT=1; then
  ok "not committed: the LaunchAgent and its folder are back as they were"
else
  bad "rc=$RC old=$([ -e "$OLD" ] && echo kept || echo gone) prefix=$([ -e "$PREFIX" ] && echo kept || echo gone)"; show "$OUT" 6
fi

# Re-review C: every listener on the port is the daemon, its program is
# exactly this install's agent, and the health answer is bound to it.
say "M8b. another process listening on the port as well: not committed"
if not_committed extra EP_STUB_EXTRA_LISTENER=777; then
  ok "a second listener (777) beside launchd's daemon kept the move from being committed"
else
  bad "rc=$RC"; show "$OUT" 6
fi
say "M8c. a program whose name only starts with the agent's: not committed"
if not_committed prog EP_STUB_PS_PROGRAM_SUFFIX=-old; then
  ok "eugene-plexus-agent-old is not this install's agent"
else
  bad "rc=$RC"; show "$OUT" 6
fi
say "M8d. the process changes between the samples and the health answer: not committed"
if not_committed flip EP_STUB_PID_FLIP=1; then
  ok "a health answer from another process than the one sampled does not count"
else
  bad "rc=$RC"; show "$OUT" 6
fi
if printf '%s' "$OUT" | grep -q 'last seen:'; then
  ok "the refusal says what it last saw on the port"
else
  bad "the refusal does not say what it saw"; show "$OUT" 4
fi

# Row 8 review, item 5: a daemon that will not stop is never left running
# beside a restarted LaunchAgent.
# Re-review 4: the same pid can run another program by the second sample.
say "M8e. the job's program changes between the samples (an exec): not committed"
if not_committed argv EP_STUB_ARGV_FLIP=1; then
  ok "the command line is checked again after the health answer"
else
  bad "rc=$RC"; show "$OUT" 6
fi

say "M9. a rollback that cannot stop the daemon stops there"
rm -rf "$WORK/stuck"
mkdir -p "$WORK/stuck/home"
old_install "$WORK/stuck/home"
EP_EXTRA_ENV="EP_STUB_LAUNCHCTL_FAIL=bootstrap EP_STUB_DAEMON_LOADED=1 EP_STUB_BOOTOUT_FAILS=1" run_mac stuck
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'macOS refused to stop the new startup job: Boot-out failed' \
    && ! grep -q "^bootstrap gui/" "$ROOT/state/launchctl.log" && [ -e "$PREFIX" ]; then
  ok "the LaunchAgent was not started beside it, nothing was taken apart, and the person is told"
else
  bad "rc=$RC; launchctl: $(tr '\n' '|' < "$ROOT/state/launchctl.log")"; show "$OUT" 6
fi
EP_EXTRA_ENV=

# Re-review A(1): the person can leave an ACL entry on the old folder
# (numeric modes do not touch one), and the new folder can inherit one
# from its parent. Neither may open the kept keys.
say "M10. an ACL entry on the old folder, or one inherited, opens nothing kept"
rm -rf "$WORK/acl"
mkdir -p "$WORK/acl/home" "$WORK/acl/state"
old_install "$WORK/acl/home"
OLD=$WORK/acl/home/.local/share/eugene-plexus
printf '%s\t%s\n' "$OLD" "user:$(id -un) allow list,search" > "$WORK/acl/state/acl"
EP_EXTRA_ENV=EP_STUB_INHERIT_ACL=1 run_mac acl
EP_EXTRA_ENV=
moved=$(ls -d "$PREFIX".moved-* 2>/dev/null | head -n 1)
if [ "$RC" = 0 ] && [ -n "$moved" ] && [ -f "$moved/eugene-plexus/node.yaml" ] \
    && [ -z "$(acl_of "$moved")" ] && [ "$(owner_of "$moved")" = root:wheel ] \
    && [ "$(stat -c %a "$moved")" = 700 ] && grep -qx -- "-h -N $moved" "$ROOT/state/chmod.log"; then
  ok "the keys sit inside root's ${moved##*/}: 0700, root's, its inherited entry taken off; the old folder's own entry opens nothing"
else
  bad "rc=$RC kept '${moved}' ($(ls -A "$moved" 2>/dev/null | tr '\n' ' ')) acl '$(acl_of "$moved" | tr '\n' '|')' owner '$(owner_of "$moved")'"
  show "$OUT" 6
fi

say "M11. an ACL entry root cannot take off the keeping folder stops the move"
rm -rf "$WORK/sticks"
mkdir -p "$WORK/sticks/home"
old_install "$WORK/sticks/home"
OLD=$WORK/sticks/home/.local/share/eugene-plexus
EP_EXTRA_ENV="EP_STUB_INHERIT_ACL=1 EP_STUB_ACL_STICKS=1" run_mac sticks
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'ACL entry' \
    && [ -f "$OLD/node.yaml" ] && [ ! -L "$OLD" ] && [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] \
    && [ -f "$WORK/sticks/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && grep -q "^bootstrap gui/$(id -u) " "$ROOT/state/launchctl.log"; then
  ok "not committed: the old folder stayed, the empty keeping folder went, the LaunchAgent is back"
else
  bad "rc=$RC old=$([ -f "$OLD/node.yaml" ] && echo kept || echo gone) kept='$(ls -d "$PREFIX".moved-* 2>/dev/null)'"; show "$OUT" 6
fi

# Re-review A(2) and A(3): a link put where the old folder was, after the
# move's checks, is never followed by root, and keeping the old folder
# failing stops the move before it is committed.
say "M12. a link swapped in after the checks: never followed, and the move stops"
rm -rf "$WORK/swap"
mkdir -p "$WORK/swap/home" "$WORK/swap/victim"
printf 'theirs\n' > "$WORK/swap/victim/file"
chmod 0755 "$WORK/swap/victim"
old_install "$WORK/swap/home"
OLD=$WORK/swap/home/.local/share/eugene-plexus
EP_EXTRA_ENV=EP_STUB_SWAP_OLD=1 run_mac swap
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && [ "$(stat -c %a "$WORK/swap/victim")" = 755 ] && [ -L "$OLD" ] \
    && [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] \
    && ! grep -q "$WORK/swap/victim" "$ROOT/state/chmod.log" "$ROOT/state/chown.log" 2>/dev/null \
    && [ -f "$WORK/swap/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && grep -q "^bootstrap gui/$(id -u) " "$ROOT/state/launchctl.log"; then
  ok "the link was left where it was, its target untouched (0755), and the LaunchAgent started again"
else
  bad "rc=$RC victim mode $(stat -c %a "$WORK/swap/victim") old $([ -L "$OLD" ] && echo link || echo moved) kept '$(ls -d "$PREFIX".moved-* 2>/dev/null)'"
  show "$OUT" 6
fi

say "M13. a link swapped in as the old folder is renamed: never followed, put back, and the move stops"
rm -rf "$WORK/race"
mkdir -p "$WORK/race/home" "$WORK/race/victim"
printf 'theirs\n' > "$WORK/race/victim/file"
chmod 0755 "$WORK/race/victim"
old_install "$WORK/race/home"
OLD=$WORK/race/home/.local/share/eugene-plexus
EP_EXTRA_ENV=EP_STUB_SWAP_AT_MV=1 run_mac race
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && [ "$(stat -c %a "$WORK/race/victim")" = 755 ] \
    && [ -L "$OLD" ] && [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] \
    && printf '%s' "$OUT" | grep -q "is not the folder Eugene was moved from" \
    && [ -f "$WORK/race/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ]; then
  ok "the link was refused inside root's folder and renamed back where it was; its target untouched; nothing committed"
else
  bad "rc=$RC victim mode $(stat -c %a "$WORK/race/victim") old $([ -L "$OLD" ] && echo link || echo gone) kept '$(ls -d "$PREFIX".moved-* 2>/dev/null)'"
  show "$OUT" 6
fi

# Re-review 1: the person can make a path component above the old folder a
# link -- ~/.local/share to a folder of root's -- after the checks. The
# rename is the person's own, so it moves nothing of root's.
say "M13b. ~/.local/share swapped for a link to root's folder: nothing of root's moves"
rm -rf "$WORK/share"
mkdir -p "$WORK/share/home" "$WORK/share/state" "$WORK/share/rootlib/eugene-plexus"
printf 'receipts\n' > "$WORK/share/rootlib/eugene-plexus/account.txt"
printf '%s\troot:wheel\n' "$WORK/share/rootlib" "$WORK/share/rootlib/eugene-plexus" > "$WORK/share/state/owners"
old_install "$WORK/share/home"
EP_EXTRA_ENV=EP_STUB_SWAP_SHARE_AT_MV=1 run_mac share
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && [ -f "$WORK/share/rootlib/eugene-plexus/account.txt" ] \
    && [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] && [ ! -e "$PREFIX" ]; then
  ok "root's folder stayed where it was; the move stopped and was put back"
else
  bad "rc=$RC root's folder $([ -f "$WORK/share/rootlib/eugene-plexus/account.txt" ] && echo kept || echo MOVED) kept '$(ls -d "$PREFIX".moved-* 2>/dev/null)'"
  show "$OUT" 6
fi

# Re-review 3: an interrupt after the old folder went into root's folder,
# before the commit, puts it back before anything is removed.
say "M13c. an interrupt once the old folder is kept: it is put back, then the move is undone"
rm -rf "$WORK/int"
mkdir -p "$WORK/int/home"
old_install "$WORK/int/home"
OLD=$WORK/int/home/.local/share/eugene-plexus
EP_EXTRA_ENV=EP_STUB_INT_AT_KEEP=1 run_mac int
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && [ -d "$OLD" ] && [ ! -L "$OLD" ] && [ -f "$OLD/node.yaml" ] \
    && [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] && [ ! -e "$PREFIX" ] \
    && [ -f "$WORK/int/home/Library/LaunchAgents/com.eugeneplexus.agent.plist" ] \
    && grep -q "^bootstrap gui/$(id -u) " "$ROOT/state/launchctl.log"; then
  ok "the old folder is back with its node.yaml, root's folder and the copy are gone, the LaunchAgent is back"
else
  bad "rc=$RC old $([ -f "$OLD/node.yaml" ] && echo back || echo MISSING) kept '$(ls -d "$PREFIX".moved-* 2>/dev/null)' prefix $([ -e "$PREFIX" ] && echo kept || echo gone)"
  show "$OUT" 8
fi

# Re-review 2: across disks a rename is a copy; refused before anything.
say "M13d. the old folder on another disk than the prefix: refused, nothing changed"
rm -rf "$WORK/disk"
mkdir -p "$WORK/disk/home"
old_install "$WORK/disk/home"
EP_EXTRA_ENV=EP_STUB_OTHER_DISK=1 run_mac disk
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "is on another disk than" \
    && printf '%s' "$OUT" | grep -q "Nothing was changed" && [ ! -e "$PREFIX" ] \
    && ! grep -q '^bootout gui/' "$ROOT/state/launchctl.log" 2>/dev/null; then
  ok "refused, with what to do instead, before Eugene was stopped"
else
  bad "rc=$RC"; show "$OUT" 6
fi

# Re-review 6: a size that cannot be read stops the move; a folder that
# grows while it is copied is cut off and the move stops.
say "M13e. a size that cannot be read: refused, nothing changed"
rm -rf "$WORK/nosize"
mkdir -p "$WORK/nosize/home"
old_install "$WORK/nosize/home"
EP_EXTRA_ENV=EP_STUB_DU_FAILS=1 run_mac nosize
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q "could not tell how big" \
    && printf '%s' "$OUT" | grep -q "Nothing was changed" && [ ! -e "$PREFIX" ]; then
  ok "refused before Eugene was stopped"
else
  bad "rc=$RC"; show "$OUT" 6
fi
say "M13f. the old folder grows by 100 MiB while it is copied: cut off, not committed"
if not_committed grow EP_STUB_GROW=1 && printf '%s' "$OUT" | grep -q "grew past"; then
  ok "the copy stopped at what was measured plus its slack, and the move was put back"
else
  bad "rc=$RC"; show "$OUT" 6
fi
rm -f "$WORK/grow/home/.local/share/eugene-plexus/control-state/grown.bin"

# Re-review D: the home's ACL entry goes on every way out of a run that
# added it, whoever made the group; a removal run by root alone takes it
# out too; and a membership an earlier build gave the account goes.
say "M14. a refused move takes out the home's entry it added, though the group was there before"
rm -rf "$WORK/group"
mkdir -p "$WORK/group/home" "$WORK/group/state"
old_install "$WORK/group/home"
printf '/Groups/_eugeneplexusmodels PrimaryGroupID 397\n' > "$WORK/group/state/dscl"
EP_EXTRA_ENV=EP_STUB_LAUNCHCTL_FAIL=bootstrap run_mac group
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && grep -q -- "+a group:_eugeneplexusmodels allow search $ROOT/home\$" "$ROOT/state/chmod.log" \
    && ! has_home_ace "$ROOT"; then
  ok "the entry this run added is gone again"
else
  bad "rc=$RC entry $(has_home_ace "$ROOT" && echo kept || echo gone); chmod: $(grep -- 'a group' "$ROOT/state/chmod.log" | tr '\n' '|')"
fi

say "M15. a fresh install refused after the entry was added takes it out"
EP_EXTRA_ENV=EP_STUB_PLIST_USER=root run_mac fresh2 --no-start
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && grep -q -- "+a group:_eugeneplexusmodels allow search $ROOT/home\$" "$ROOT/state/chmod.log" \
    && ! has_home_ace "$ROOT" && [ ! -f "$ROOT/receipts/models-ace.txt" ]; then
  ok "refused, and the home's entry and its receipt are gone"
else
  bad "rc=$RC entry $(has_home_ace "$ROOT" && echo kept || echo gone) receipt $([ -f "$ROOT/receipts/models-ace.txt" ] && echo kept || echo gone)"
  show "$OUT" 4
fi

# Re-review 5: an entry that will not come out is said, and its receipt
# stays for the removal to find.
say "M15b. an entry that will not come out: said, and its receipt kept"
EP_EXTRA_ENV="EP_STUB_PLIST_USER=root EP_STUB_ACL_REMOVE_FAILS=1" run_mac fresh3 --no-start
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && has_home_ace "$ROOT" && [ -f "$ROOT/receipts/models-ace.txt" ] \
    && printf '%s' "$OUT" | grep -q "could not take Eugene's entry out of"; then
  ok "the entry stayed, the person was told the command, and the receipt is kept"
else
  bad "rc=$RC entry $(has_home_ace "$ROOT" && echo kept || echo gone) receipt $([ -f "$ROOT/receipts/models-ace.txt" ] && echo kept || echo gone)"
  show "$OUT" 4
fi

say "M16. a staff membership an earlier build gave the account is taken back"
mkdir -p "$WORK/staff/state"
printf '/Groups/staff GroupMembership _eugeneplexus\n' > "$WORK/staff/state/dscl"
run_mac staff --no-start
if [ "$RC" = 0 ] && grep -qx -- "-o edit -d _eugeneplexus -t user staff" "$ROOT/state/dseditgroup.log"; then
  ok "_eugeneplexus was taken out of staff"
else
  bad "rc=$RC dseditgroup: $(tr '\n' '|' < "$ROOT/state/dseditgroup.log")"; show "$OUT" 4
fi

# Re-review E: a disk without room for the copy is refused, with the
# numbers, before anything is stopped.
say "M17. no room for the copy: refused with the numbers, nothing changed"
rm -rf "$WORK/full"
mkdir -p "$WORK/full/home"
old_install "$WORK/full/home"
EP_EXTRA_ENV=EP_STUB_DF_FREE_KB=1000 run_mac full
EP_EXTRA_ENV=
if [ "$RC" != 0 ] && printf '%s' "$OUT" | grep -q 'MiB free' && printf '%s' "$OUT" | grep -q 'Nothing was changed' \
    && [ ! -e "$PREFIX" ] && ! grep -q '^bootout gui/' "$ROOT/state/launchctl.log" 2>/dev/null \
    && [ -f "$WORK/full/home/.local/share/eugene-plexus/node.yaml" ]; then
  ok "refused before Eugene was stopped: $(printf '%s' "$OUT" | grep -o 'the move needs [0-9]* MiB' | head -n 1)"
else
  bad "rc=$RC"; show "$OUT" 4
fi

# Re-review D and E, in the removal: root's own removal, run by root with
# no --person, takes the home's entry out (the install recorded where it
# put it), deletes the old folder the move kept, and closes what it keeps
# to everyone but root, an ACL entry the account left included.
# root_removal ROOT [ENV...]: root's own removal from ROOT's receipts, its
# root paths moved under ROOT, run by root alone -> OUT, RC.
root_removal() {
  local root=$1; shift
  python3 - "$root/receipts/remove.sh" "$root/remove-here.sh" "$root/LaunchDaemons" "$root/receipts" <<'PY'
import sys
source, target, daemons, receipts = sys.argv[1:]
text = open(source, encoding="utf-8").read()
# The two root paths, and the one tool the removal names by its full path
# to read the daemon's program: here it is the plist stand-in.
for old, new in (
    ("DAEMON_PLIST=/Library/LaunchDaemons/$DAEMON_LABEL.plist\n", f"DAEMON_PLIST={daemons}/$DAEMON_LABEL.plist\n"),
    ("RECEIPTS=/usr/local/lib/eugene-plexus\n", f"RECEIPTS={receipts}\n"),
    ("PROGRAM=$(/usr/bin/plutil -extract", "PROGRAM=$(plutil -extract"),
):
    if text.count(old) != 1:
        sys.exit(f"refusing to run: {old.strip()!r} appears {text.count(old)} times")
    text = text.replace(old, new)
open(target, "w", encoding="utf-8", newline="\n").write(text)
PY
  OUT=$(cd "$root" && env -i HOME="$root/home" PATH="$root/bin:/usr/bin:/bin" EP_STUB_BIN="$root/bin" \
    EP_STUB_STATE="$root/state" EP_STUB_PERSON="$(id -un)" EP_STUB_VENV="$root/eugene-plexus/venv" \
    EP_STUB_ROOT=1 "$@" sh "$root/remove-here.sh" --prefix "$root/eugene-plexus" 2>&1)
  RC=$?
}

say "U1. root's removal, run by root alone, after a move"
ROOT=$WORK/acl
PREFIX=$ROOT/eugene-plexus
printf '%s\t%s\n' "$PREFIX" "user:$(id -un) allow list,search" >> "$ROOT/state/acl"
root_removal "$ROOT"
kept=$(ls -d "$PREFIX".removed-* 2>/dev/null | head -n 1)
if [ "$RC" = 0 ] && ! has_home_ace "$ROOT" && [ ! -f "$ROOT/receipts/models-ace.txt" ]; then
  ok "the home's ACL entry is gone, with no --person given"
else
  bad "rc=$RC entry $(has_home_ace "$ROOT" && echo kept || echo gone)"; show "$OUT" 8
fi
if [ -z "$(ls -d "$PREFIX".moved-* 2>/dev/null)" ] && printf '%s' "$OUT" | grep -q "Deleted the copy kept"; then
  ok "the old folder the move kept was deleted, and the removal says so"
else
  bad "kept from the move: '$(ls -d "$PREFIX".moved-* 2>/dev/null)'"; show "$OUT" 8
fi
if [ -n "$kept" ] && [ -z "$(acl_of "$kept")" ] && [ "$(owner_of "$kept")" = root:wheel ] \
    && [ "$(stat -c %a "$kept")" = 700 ]; then
  ok "what it keeps (${kept##*/}) is root's, 0700, the account's ACL entry taken off"
else
  bad "kept '$kept' acl '$(acl_of "$kept" | tr '\n' '|')' owner '$(owner_of "$kept")'"; show "$OUT" 8
fi

# Re-review 5, in the removal: an entry that will not come out is said,
# and its receipt stays for the next try.
say "U2. root's removal, when the home's entry will not come out"
ROOT=$WORK/fresh
root_removal "$ROOT" EP_STUB_ACL_REMOVE_FAILS=1
if has_home_ace "$ROOT" && [ -f "$ROOT/receipts/models-ace.txt" ] \
    && printf '%s' "$OUT" | grep -q "Could not take Eugene's entry out of"; then
  ok "said, with the command, and the receipt kept"
else
  bad "rc=$RC entry $(has_home_ace "$ROOT" && echo kept || echo gone) receipt $([ -f "$ROOT/receipts/models-ace.txt" ] && echo kept || echo gone)"
  show "$OUT" 8
fi

printf '\n'
if [ "$FAILURES" = 0 ]; then
  printf 'Row 8 (install.sh): all checks passed\n'
else
  printf 'Row 8 (install.sh): %s FAILED\n' "$FAILURES"
fi
exit $([ "$FAILURES" = 0 ] && echo 0 || echo 1)
