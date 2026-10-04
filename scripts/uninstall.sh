#!/bin/sh
# Offline removal. The installer embeds this script and inventory.py.
set -eu
PREFIX=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
INTERACTIVE=0 PURGE_DOWNLOADS=0 PURGE_DATA=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --interactive) INTERACTIVE=1; shift ;;
        --purge-downloads|--purge-model-copies) PURGE_DOWNLOADS=1; shift ;;
        --purge-data) PURGE_DATA=1; shift ;;
        *) echo "Unknown removal option: $1" >&2; exit 2 ;;
    esac
done
PLATFORM=$(uname -s)
case "$PREFIX" in ''|/|"$HOME"|/Applications|/usr|/var|/opt|*/../*|*/./*) echo "Not an installation folder: $PREFIX" >&2; exit 1 ;; esac
if [ ! -d "$PREFIX" ]; then echo "Nothing installed at $PREFIX"; exit 0; fi
if [ -L "$PREFIX" ]; then echo "Refusing a linked installation folder: $PREFIX" >&2; exit 1; fi
if [ ! -f "$PREFIX/agent.yaml" ] && [ ! -f "$PREFIX/node.yaml" ] && [ ! -f "$PREFIX/bin/uv" ] && [ ! -f "$PREFIX/uninstall/receipt/inventory.json" ]; then
    echo "No Eugene installation or removal receipt at $PREFIX. Nothing was removed." >&2; exit 1
fi
PREFIX=$(CDPATH= cd -- "$PREFIX" && pwd -P)
RECEIPT=$PREFIX/uninstall/receipt
mkdir -p "$RECEIPT"
chmod 700 "$RECEIPT"
WARNINGS=$RECEIPT/current-warnings.txt
: > "$WARNINGS"
warn() { printf 'warning: %s\n' "$*" >&2; printf '%s\n' "$*" >> "$WARNINGS"; }
fail() {
    warn "$*"
    if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
        /usr/bin/osascript - "$*" <<'APPLE' || true
on run argv
    display dialog (item 1 of argv) with title "Eugene removal did not finish" buttons {"OK"} default button "OK" with icon caution
end run
APPLE
    fi
    exit 1
}
PYBIN=$PREFIX/venv/bin/python
if [ ! -f "$RECEIPT/inventory.json" ] || { [ ! -f "$RECEIPT/removed.txt" ] && [ -x "$PYBIN" ]; }; then
    if [ -x "$PYBIN" ]; then
        "$PYBIN" -I "$PREFIX/uninstall/inventory.py" --prefix "$PREFIX" --output "$RECEIPT/inventory.json" || fail "Could not inventory this installation. Nothing was removed."
    else
        printf '%s\n' "$PREFIX" > "$RECEIPT/original-prefix.txt"
        for name in venv pythons bin .cache/uv update; do printf '%s/%s\n' "$PREFIX" "$name"; done > "$RECEIPT/software.txt"
        : > "$RECEIPT/data.txt"; : > "$RECEIPT/downloads.txt"
        printf '%s/models\n' "$PREFIX" > "$RECEIPT/protected.txt"
        printf '%s\n' 'Python is missing. Settings, downloads and credentials were kept; review the remaining folder.' > "$RECEIPT/warnings.txt"
        printf '{}\n' > "$RECEIPT/inventory.json"
    fi
fi
ORIGINAL=$(cat "$RECEIPT/original-prefix.txt")
map_path() {
    case "$1" in "$ORIGINAL"/*) printf '%s%s\n' "$PREFIX" "${1#"$ORIGINAL"}" ;; *) printf '%s\n' "$1" ;; esac
}
group_size() {
    total=0 unknown=0
    while IFS= read -r original; do
        path=$(map_path "$original")
        if [ -e "$path" ] && [ ! -L "$path" ]; then
            if usage=$(du -sk "$path" 2>/dev/null); then
                kb=$(printf '%s\n' "$usage" | awk '{print $1}')
                total=$((total + ${kb:-0}))
            else unknown=1; fi
        fi
    done < "$RECEIPT/$1.txt"
    if [ "$unknown" = 1 ]; then printf 'size unavailable'; else awk -v kb="$total" 'BEGIN {printf "%.2f GB", kb/1048576}'; fi
}
if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
    if ! CHOICE=$(/usr/bin/osascript - "$(group_size software)" "$(group_size data)" "$(group_size downloads)" "$PREFIX" <<'APPLE'
on run argv
    set dataChoice to "Delete settings, app data and logs (" & item 2 of argv & ")"
    set downloadChoice to "Delete downloaded engines and model copies (" & item 3 of argv & ")"
    set picked to choose from list {dataChoice, downloadChoice} with title "Remove Eugene Plexus" with prompt ("Software to remove: " & item 1 of argv & return & "Original model folders will be kept." & return & "Optionally select data to delete:") default items {} OK button name "Continue" cancel button name "Cancel" with multiple selections allowed and empty selection allowed
    if picked is false then error number -128
    display dialog ("Remove Eugene from this computer?" & return & item 4 of argv & return & "Items you did not select will be kept.") with title "Remove Eugene Plexus" buttons {"Cancel", "Remove Eugene"} default button "Cancel" cancel button "Cancel" with icon caution
    set answer to ""
    if picked contains dataChoice then set answer to answer & "data "
    if picked contains downloadChoice then set answer to answer & "downloads"
    return answer
end run
APPLE
    ); then echo 'Removal cancelled.'; exit 0; fi
    case "$CHOICE" in *data*) PURGE_DATA=1 ;; esac
    case "$CHOICE" in *downloads*) PURGE_DOWNLOADS=1 ;; esac
fi
if [ -s "$RECEIPT/warnings.txt" ]; then cat "$RECEIPT/warnings.txt" >> "$WARNINGS"; fi

if [ ! -f "$RECEIPT/removed.txt" ]; then
    if [ "$PLATFORM" = Darwin ]; then
        LABEL=com.eugeneplexus.agent
        PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
        if [ -f "$PLIST" ]; then
            OWNER=$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$PLIST") || fail "Cannot read $PLIST. Nothing was removed."
            case "$OWNER" in "$PREFIX"/*) ;; *) fail "The startup job belongs to $OWNER. Use that install's removal utility." ;; esac
            if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
                launchctl bootout "gui/$(id -u)/$LABEL" || fail "macOS could not stop Eugene. Try removal again after signing out and back in."
            fi
            rm -f "$PLIST"
        fi
    else
        UNIT=$HOME/.config/systemd/user/eugene-plexus-agent.service
        if [ -f "$UNIT" ]; then
            grep -F -- "$PREFIX/" "$UNIT" >/dev/null || fail "The startup job belongs to another installation."
            systemctl --user disable --now eugene-plexus-agent || fail 'Could not stop the user service.'
            rm -f "$UNIT"
            systemctl --user daemon-reload || fail 'Could not reload the user service manager.'
        fi
    fi
    # launchd normally terminates the job's process group; also cover a
    # manually started process. Match an executable path, never a regex.
    PIDS=$(ps -axo pid=,comm= | awk -v root="$PREFIX/" '{pid=$1; sub(/^[[:space:]]*[0-9]+[[:space:]]+/, ""); if(index($0,root)==1) print pid}')
    for pid in $PIDS; do kill -TERM "$pid" 2>/dev/null || true; done
    tries=0
    while [ "$tries" -lt 15 ]; do
        alive=0
        for pid in $PIDS; do if kill -0 "$pid" 2>/dev/null; then alive=1; fi; done
        [ "$alive" = 0 ] && break
        sleep 1; tries=$((tries + 1))
    done
    for pid in $PIDS; do
        if kill -0 "$pid" 2>/dev/null; then fail "Eugene process $pid is still running. Close it and run removal again."; fi
    done
    if [ -x "$PYBIN" ]; then
        if "$PYBIN" -I "$PREFIX/uninstall/inventory.py" --keyring-only --prefix "$PREFIX" --output "$RECEIPT/credentials-user.json" 2> "$RECEIPT/credential-warnings.txt"; then
            cat "$RECEIPT/credential-warnings.txt" >> "$WARNINGS"
        else warn 'Credential cleanup failed. Review Eugene entries in Keychain Access or your OS credential store.'; fi
    else warn 'Credential cleanup could not run: the installed Python is missing.'; fi
    if [ "$PLATFORM" = Darwin ]; then
        # Only entries for this install's Python; no shared firewall rules.
        FW=/usr/libexec/ApplicationFirewall/socketfilterfw
        if [ -f "$RECEIPT/firewall.txt" ]; then
            while IFS= read -r program; do
                if "$FW" --listapps 2>/dev/null | grep -F -- "$program" >/dev/null; then
                    if ! /usr/bin/osascript - "$program" <<'APPLE'
on run argv
    do shell script "/usr/libexec/ApplicationFirewall/socketfilterfw --remove " & quoted form of (item 1 of argv) with administrator privileges
end run
APPLE
                    then warn "Firewall entry kept: $program. Remove it in System Settings > Network > Firewall > Options."; fi
                fi
            done < "$RECEIPT/firewall.txt"
        fi
    fi
    cp "$WARNINGS" "$RECEIPT/integration-warnings.txt"
elif [ -s "$RECEIPT/integration-warnings.txt" ]; then
    cat "$RECEIPT/integration-warnings.txt" >> "$WARNINGS"
fi

safe_remove() {
    target=$1 kind=$2
    case "$target" in /*) ;; *) warn "Kept non-absolute path: $target"; return ;; esac
    case "$target" in /|/usr|/var|/opt|/Applications|/Users|/home|"$HOME"|"$PREFIX"|*/../*|*/./*) warn "Kept unsafe path: $target"; return ;; esac
    case "$PREFIX/" in "$target"/*) warn "Kept parent of the installation: $target"; return ;; esac
    if [ "$kind" != downloads ]; then
        case "$target" in "$PREFIX"/*) ;; *) warn "Kept path outside the installation: $target"; return ;; esac
    fi
    cursor=$target
    while [ "$cursor" != / ] && [ -n "$cursor" ]; do
        if [ -L "$cursor" ]; then warn "Kept linked path: $target"; return; fi
        cursor=$(dirname -- "$cursor")
    done
    while IFS= read -r original; do
        protected=$(map_path "$original")
        case "$target/" in "$protected/"*) warn "Kept original model folder: $target"; return ;; esac
        case "$protected/" in "$target/"*) warn "Kept parent of an original model folder: $target"; return ;; esac
    done < "$RECEIPT/protected.txt"
    if ! rm -rf -- "$target"; then warn "Could not remove $target. Check its permissions and run cleanup again."; fi
}
for kind in software downloads data; do
    [ "$kind" = downloads ] && [ "$PURGE_DOWNLOADS" != 1 ] && continue
    [ "$kind" = data ] && [ "$PURGE_DATA" != 1 ] && continue
    while IFS= read -r original; do
        [ -n "$original" ] || continue
        safe_remove "$(map_path "$original")" "$kind"
    done < "$RECEIPT/$kind.txt"
done

KEEP=$PREFIX
if [ ! -f "$RECEIPT/removed.txt" ]; then
    case "$PREFIX" in *.removed-*) ;; *)
        KEEP=$PREFIX.removed-$(date +%Y%m%d%H%M%S)
        [ ! -e "$KEEP" ] || fail "The retained folder already exists: $KEEP"
        mv -- "$PREFIX" "$KEEP" || fail "Could not move the retained files to $KEEP. Check permissions and try again."
        ;;
    esac
fi
PREFIX=$KEEP
RECEIPT=$KEEP/uninstall/receipt
WARNINGS=$RECEIPT/current-warnings.txt
printf '%s\n' 'Startup disabled; see report.txt for remaining work.' > "$RECEIPT/removed.txt"
if [ "$PLATFORM" = Darwin ] && [ -f "$RECEIPT/mac-app.txt" ]; then
    APP=$(cat "$RECEIPT/mac-app.txt")
    case "$APP" in "$HOME/Applications/Remove Eugene Plexus"*.app)
        # Only our own bundle (identified by its exact stored prefix).
        if [ -f "$APP/Contents/Resources/prefix.txt" ] && [ "$(cat "$APP/Contents/Resources/prefix.txt")" = "$ORIGINAL" ]; then rm -rf -- "$APP"; fi ;;
    esac
fi
{
    echo "Eugene's removal finished."
    echo "Retained files and cleanup utility: $KEEP"
    echo 'Original model folders were kept.'
    while IFS= read -r original; do
        path=$(map_path "$original")
        if [ -e "$path" ]; then echo "Retained download: $path"; fi
    done < "$RECEIPT/downloads.txt"
    echo 'To change your cleanup choices, open uninstall/Remove Eugene.command in the retained folder.'
    if [ -s "$WARNINGS" ]; then echo 'Items to review:'; cat "$WARNINGS"; fi
} > "$RECEIPT/report.txt"
cat "$RECEIPT/report.txt"
if [ "$INTERACTIVE" = 1 ] && [ "$PLATFORM" = Darwin ]; then
    /usr/bin/osascript - "$(cat "$RECEIPT/report.txt")" <<'APPLE'
on run argv
    display dialog (item 1 of argv) with title "Eugene removal" buttons {"OK"} default button "OK"
end run
APPLE
fi
[ ! -s "$WARNINGS" ] || exit 1
