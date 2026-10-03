#!/usr/bin/env bash
# R3.7: execute both POSIX setup scripts against isolated command stand-ins.
# Runs on Linux/WSL. Darwin/CPU facts are simulated; this is not a Mac test.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILURES=0
CHECKS=0

check() {
    CHECKS=$((CHECKS + 1))
    if "$@"; then
        printf 'PASS %s\n' "$LABEL"
    else
        printf 'FAIL %s\n' "$LABEL"
        cat "$ROOT/output"
        FAILURES=$((FAILURES + 1))
    fi
}

make_stubs() {
    mkdir -p "$ROOT/bin" "$ROOT/home"
    cat > "$ROOT/bin/uname" <<'STUB'
#!/bin/sh
case "$1" in
    -s) echo "$R37_OS" ;;
    -m) echo "$R37_ARCH" ;;
    *) exec /usr/bin/uname "$@" ;;
esac
STUB
    cat > "$ROOT/bin/sysctl" <<'STUB'
#!/bin/sh
echo "sysctl:$*" >> "$R37_TRACE"
case "$*" in
    '-n hw.optional.arm64')
        [ "$R37_ARM" != unknown ] || exit 1
        echo "$R37_ARM" ;;
    *) exit 1 ;;
esac
STUB
    cat > "$ROOT/bin/uv-template" <<'STUB'
#!/bin/sh
if [ "${R37_FAIL_STEP:-}" = "$1" ]; then
    echo "injected $1 download failure" >&2
    exit 37
fi
case "$1" in
    --version)
        # The version sits beside the stand-in, so one installed in the
        # prefix can be old while the one a fetch puts there is new.
        version=$(cat "$0.version" 2>/dev/null || echo 0.12.22)
        case "$version" in
            silent) echo 'uv: no version here' ;;
            *) echo "uv $version (x86_64-unknown-linux-gnu)" ;;
        esac ;;
    venv)
        request=
        previous=
        for argument in "$@"; do
            [ "$previous" != --python ] || request=$argument
            previous=$argument
        done
        destination=$argument
        printf 'venv:%s:%s\n' "$request" "$destination" >> "$R37_TRACE"
        mkdir -p "$destination/bin"
        case "$request" in
            *-macos-aarch64-none) architecture=arm64 ;;
            *) architecture=$R37_ARCH ;;
        esac
        printf '%s\n' "${R37_WRONG_PY:-$architecture}" > "$destination/architecture"
        cp "$R37_BIN/python-template" "$destination/bin/python"
        printf '#!/bin/sh\nexit 0\n' > "$destination/bin/eugene-plexus-agent"
        cp "$destination/bin/eugene-plexus-agent" "$destination/bin/pre-commit"
        chmod +x "$destination/bin/"* ;;
    pip) echo "pip:$*" >> "$R37_TRACE" ;;
    *) echo "unexpected uv call: $*" >&2; exit 2 ;;
esac
STUB
    cat > "$ROOT/bin/python-template" <<'STUB'
#!/bin/sh
case "$1" in
    -c)
        architecture=$(cat "$(dirname "$0")/../architecture")
        [ "$architecture" != probe-failed ] || exit 1
        echo "$architecture" ;;
    --version) echo 'Python 3.12' ;;
    -) cat >/dev/null ;;
    *) echo "unexpected Python call: $*" >&2; exit 2 ;;
esac
STUB
    cat > "$ROOT/bin/curl" <<'STUB'
#!/bin/sh
output=
previous=
for argument in "$@"; do
    [ "$previous" != -o ] || output=$argument
    previous=$argument
done
emit() {
    echo 'if [ "${R37_FAIL_STEP:-}" = bootstrap ]; then echo "injected bootstrap download failure" >&2; exit 37; fi'
    echo 'echo uv-bootstrap >> "$R37_TRACE"'
    echo 'mkdir -p "$UV_UNMANAGED_INSTALL"'
    echo 'cp "$R37_BIN/uv-template" "$UV_UNMANAGED_INSTALL/uv"'
    echo 'chmod +x "$UV_UNMANAGED_INSTALL/uv"'
    echo 'echo "${R37_FETCHED_UV:-0.12.22}" > "$UV_UNMANAGED_INSTALL/uv.version"'
}
if [ -n "$output" ]; then emit > "$output"; else emit; fi
STUB
    cat > "$ROOT/bin/git" <<'STUB'
#!/bin/sh
[ "$1" = clone ] || exit 2
for destination in "$@"; do :; done
mkdir -p "$destination/.git"
STUB
    chmod +x "$ROOT/bin/"*
    : > "$ROOT/trace"
}

run_case() {
    local script=$1 os=$2 architecture=$3 arm=$4 expected=$5
    local python=${6:-3.12} uv_mode=${7:-fetch}
    ROOT=$WORK/$script-$os-$architecture-$arm-$uv_mode-${python//\//_}
    make_stubs
    local options
    if [ "$script" = install ]; then
        options=(--prefix "$ROOT/prefix" --no-service --no-start)
    else
        options=(--root "$ROOT/repos" --no-node --python "$python")
    fi
    if [ "$uv_mode" = existing ]; then
        cp "$ROOT/bin/uv-template" "$ROOT/bin/uv"
        mkdir -p "$ROOT/prefix/bin"
        cp "$ROOT/bin/uv-template" "$ROOT/prefix/bin/uv"
    fi
    RC=0
    env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
        R37_OS="$os" R37_ARCH="$architecture" R37_ARM="$arm" \
        R37_TRACE="$ROOT/trace" R37_BIN="$ROOT/bin" \
        sh "$HERE/$script.sh" "${options[@]}" > "$ROOT/output" 2>&1 || RC=$?
    LABEL="$script $os/$architecture arm=$arm finishes"
    check test "$RC" = 0
    local expected_count=1
    # One virtualenv per Python repo bootstrap sets up: seven since P8 added
    # the tool-driver.
    [ "$script" != bootstrap ] || expected_count=7
    LABEL="$script $os/$architecture requests $expected in every environment"
    check test "$(grep -c "^venv:$expected:" "$ROOT/trace" || true)" = "$expected_count"
    if [ "$os" = Linux ]; then
        LABEL="$script Linux does not query Apple hardware"
        check test "$(grep -c '^sysctl:' "$ROOT/trace" || true)" = 0
    fi
}

make_existing_environment() {
    local directory=$1 architecture=$2
    mkdir -p "$directory/bin"
    cp "$ROOT/bin/python-template" "$directory/bin/python"
    printf '%s\n' "$architecture" > "$directory/architecture"
    printf '#!/bin/sh\nexit 0\n' > "$directory/bin/pre-commit"
    cp "$directory/bin/pre-commit" "$directory/bin/eugene-plexus-agent"
    chmod +x "$directory/bin/"*
    echo keep-this > "$directory/untouched"
}

bad_environment() {
    local script=$1 variant=$2
    ROOT=$WORK/bad-$script-$variant
    make_stubs
    local directory options wrong=
    if [ "$script" = install ]; then
        directory=$ROOT/prefix/venv
        options=(--prefix "$ROOT/prefix" --no-service --no-start)
    else
        directory=$ROOT/repos/agent/.venv
        options=(--root "$ROOT/repos" --no-node)
        [ "$variant" != tooling ] || directory=$ROOT/repos/.bootstrap/venv
    fi
    if [ "$variant" = created ]; then
        wrong=x86_64
    else
        local architecture=x86_64
        [ "$variant" != probe-failed ] || architecture=probe-failed
        make_existing_environment "$directory" "$architecture"
    fi
    echo 'operator settings' > "$ROOT/settings-to-preserve"
    RC=0
    env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
        R37_OS=Darwin R37_ARCH=x86_64 R37_ARM=1 \
        R37_TRACE="$ROOT/trace" R37_BIN="$ROOT/bin" R37_WRONG_PY="$wrong" \
        sh "$HERE/$script.sh" "${options[@]}" > "$ROOT/output" 2>&1 || RC=$?
    LABEL="$script rejects $variant Intel Python on Apple Silicon"
    check test "$RC" != 0
    LABEL="$script names the incompatible interpreter and native remedy"
    if [ "$variant" = probe-failed ]; then
        check grep -q 'could not inspect' "$ROOT/output"
    else
        check grep -q 'Native arm64 Python is required for Metal' "$ROOT/output"
    fi
    LABEL="$script identifies the environment needing repair"
    if [ "$variant" = created ] && [ "$script" = bootstrap ]; then
        directory=$ROOT/repos/.bootstrap/venv
    fi
    check grep -Fq "$directory" "$ROOT/output"
    LABEL="$script installs no packages into the incompatible environment"
    check test "$(grep -F "pip:" "$ROOT/trace" | grep -Fc "$directory/bin/python" || true)" = 0
    if [ "$variant" != created ]; then
        LABEL="$script preserves the existing environment"
        check grep -qx keep-this "$directory/untouched"
    fi
    LABEL="$script preserves operator files"
    check grep -qx 'operator settings' "$ROOT/settings-to-preserve"
}

failed_install_step() {
    local step=$1
    ROOT=$WORK/failed-install-$step
    make_stubs
    RC=0
    env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
        R37_OS=Linux R37_ARCH=x86_64 R37_ARM=0 R37_FAIL_STEP="$step" \
        R37_TRACE="$ROOT/trace" R37_BIN="$ROOT/bin" \
        sh -c 'sh "$1" --prefix "$2" --no-service --no-start && touch "$3"' \
        sh "$HERE/install.sh" "$ROOT/prefix" "$ROOT/build-continued" \
        > "$ROOT/output" 2>&1 || RC=$?
    LABEL="install preserves the $step command's failure status"
    check test "$RC" = 37
    LABEL="failed $step prevents a Docker-style command chain from continuing"
    check test ! -e "$ROOT/build-continued"
    LABEL="failed $step includes the original diagnosis"
    check grep -q "injected $step download failure" "$ROOT/output"
}

rerun_native() {
    local script=$1 options
    run_case "$script" Darwin x86_64 1 cpython-3.12-macos-aarch64-none 3.12 existing
    if [ "$script" = install ]; then
        options=(--prefix "$ROOT/prefix" --no-service --no-start)
    else
        options=(--root "$ROOT/repos" --no-node)
    fi
    local created
    created=$(grep -c '^venv:' "$ROOT/trace")
    RC=0
    env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
        R37_OS=Darwin R37_ARCH=x86_64 R37_ARM=1 \
        R37_TRACE="$ROOT/trace" R37_BIN="$ROOT/bin" \
        sh "$HERE/$script.sh" "${options[@]}" > "$ROOT/output" 2>&1 || RC=$?
    LABEL="$script reuses a verified native environment successfully"
    check test "$RC" = 0
    LABEL="$script rerun creates no replacement environments"
    check test "$(grep -c '^venv:' "$ROOT/trace")" = "$created"
}

# 2026-10-03, the upstream drift audit: an install kept the uv it was first
# made with forever, because step 1 skipped the download whenever a uv was
# there, and in-app updates re-run install.sh. uv 0.12.7-0.12.17 had a
# Windows path traversal (GHSA-2cv4-cqwr-gwf7). Now a uv older than
# UV_MINIMUM (0.12.18), or one that cannot say its version, is fetched
# again; one new enough is left alone exactly as before.
#   uv_present HAVE keep|fetch|fail-fetch|still-old [FETCHED]
uv_present() {
    local have=$1 expect=$2 fetched=${3:-0.12.22} fail=
    [ "$expect" != fail-fetch ] || fail=bootstrap
    ROOT=$WORK/uv-$have-$expect
    make_stubs
    mkdir -p "$ROOT/prefix/bin"
    cp "$ROOT/bin/uv-template" "$ROOT/prefix/bin/uv"
    echo "$have" > "$ROOT/prefix/bin/uv.version"
    RC=0
    env -i HOME="$ROOT/home" PATH="$ROOT/bin:/usr/bin:/bin" \
        R37_OS=Linux R37_ARCH=x86_64 R37_ARM=0 R37_FAIL_STEP="$fail" \
        R37_FETCHED_UV="$fetched" R37_TRACE="$ROOT/trace" R37_BIN="$ROOT/bin" \
        sh "$HERE/install.sh" --prefix "$ROOT/prefix" --no-service --no-start \
        > "$ROOT/output" 2>&1 || RC=$?
    local fetches
    fetches=$(grep -c '^uv-bootstrap$' "$ROOT/trace" || true)
    case "$expect" in
        keep)
            LABEL="uv $have is new enough: the install finishes"
            check test "$RC" = 0
            LABEL="uv $have is new enough: nothing is fetched"
            check test "$fetches" = 0
            LABEL="uv $have is new enough: said in the words it always was"
            check grep -Fq "uv already present (uv $have (" "$ROOT/output" ;;
        fetch)
            LABEL="uv $have is replaced: the install finishes"
            check test "$RC" = 0
            LABEL="uv $have is replaced: uv's own installer runs once"
            check test "$fetches" = 1
            LABEL="uv $have is replaced: the run says why"
            if [ "$have" = silent ]; then
                check grep -Fq 'does not say its version; fetching uv again' "$ROOT/output"
            else
                check grep -Fq "uv $have is older than 0.12.18" "$ROOT/output"
            fi
            LABEL="uv $have is replaced: the prefix's uv is now $fetched"
            check grep -qx "$fetched" "$ROOT/prefix/bin/uv.version"
            LABEL="uv $have is replaced: the virtualenv is built with the new one"
            check test "$(grep -c '^venv:' "$ROOT/trace" || true)" = 1 ;;
        fail-fetch)
            LABEL="uv $have and no network: the run stops with uv's installer's status"
            check test "$RC" = 37
            LABEL="uv $have and no network: the run says why it fetched"
            check grep -Fq "uv $have is older than 0.12.18" "$ROOT/output"
            LABEL="uv $have and no network: the download's own failure is shown"
            check grep -q 'injected bootstrap download failure' "$ROOT/output"
            LABEL="uv $have and no network: nothing is installed with the old uv"
            check test "$(grep -c '^venv:\|^pip:' "$ROOT/trace" || true)" = 0 ;;
        still-old)
            LABEL="uv $have is still $fetched after the fetch: the run stops"
            check test "$RC" != 0
            LABEL="uv $have is still $fetched after the fetch: it says so"
            check grep -Fq "is $fetched after fetching it" "$ROOT/output"
            LABEL="uv $have is still $fetched after the fetch: nothing is installed with it"
            check test "$(grep -c '^venv:\|^pip:' "$ROOT/trace" || true)" = 0 ;;
    esac
}

for step in bootstrap venv pip; do
    failed_install_step "$step"
done

uv_present 0.12.22 keep
uv_present 0.12.18 keep          # the minimum itself
uv_present 0.13.0 keep
uv_present 1.0.0 keep
uv_present 0.12.17 fetch         # the last affected release
uv_present 0.12.7 fetch          # the first affected release
uv_present 0.12.9 fetch          # as text, 0.12.9 sorts after 0.12.18
uv_present 0.9.30 fetch          # as text, 0.9.30 sorts after 0.12.18
uv_present silent fetch          # a uv that cannot say its version
uv_present 0.12.17 fail-fetch
uv_present 0.12.17 still-old 0.12.17

for script in install bootstrap; do
    run_case "$script" Linux x86_64 0 3.12
    run_case "$script" Linux aarch64 1 3.12
    run_case "$script" Darwin x86_64 0 3.12
    run_case "$script" Darwin x86_64 unknown 3.12
    run_case "$script" Darwin arm64 1 cpython-3.12-macos-aarch64-none
    run_case "$script" Darwin x86_64 1 cpython-3.12-macos-aarch64-none
    rerun_native "$script"
    run_case "$script" Darwin arm64 unknown cpython-3.12-macos-aarch64-none
    run_case "$script" Darwin aarch64 unknown cpython-3.12-macos-aarch64-none
    bad_environment "$script" existing
    bad_environment "$script" created
    bad_environment "$script" probe-failed
done
bad_environment bootstrap tooling
run_case bootstrap Darwin x86_64 1 cpython-3.13-macos-aarch64-none 3.13
run_case bootstrap Darwin x86_64 1 /custom/python /custom/python
printf '%s checks; %s failures (simulated platforms, no live install)\n' "$CHECKS" "$FAILURES"
test "$FAILURES" = 0
