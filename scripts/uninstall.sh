#!/bin/sh
# Offline removal. The installer embeds this script and inventory.py.
set -eu
PREFIX=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
INTERACTIVE=0 PURGE_DOWNLOADS=0 PURGE_DATA=0 PERSON=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --interactive) INTERACTIVE=1; shift ;;
        --purge-downloads|--purge-model-copies) PURGE_DOWNLOADS=1; shift ;;
        --purge-data) PURGE_DATA=1; shift ;;
        --person) PERSON=$2; shift 2 ;;
        *) echo "Unknown removal option: $1" >&2; exit 2 ;;
    esac
done
PLATFORM=$(uname -s)
case "$PREFIX" in ''|/|"$HOME"|/Applications|/usr|/usr/local|/var|/opt|*/../*|*/./*) echo "Not an installation folder: $PREFIX" >&2; exit 1 ;; esac
if [ ! -d "$PREFIX" ]; then echo "Nothing installed at $PREFIX"; exit 0; fi
if [ -L "$PREFIX" ]; then echo "Refusing a linked installation folder: $PREFIX" >&2; exit 1; fi

# --- a Mac's system install (row 8) -----------------------------------------
# Eugene runs as a LaunchDaemon in its own account, `_eugeneplexus`, from a
# prefix only that account can read. Removing it is root's work: stop the
# job, keep the files as root's alone, and remove the account only when the
# installer recorded making it. Nothing from the prefix runs here, because
# that account can write it: this is root's own copy of the script, outside
# the prefix, and only system tools run as root. A daemon whose program is
# in another folder is another install's, and is left alone.
DAEMON_LABEL=com.eugeneplexus.agent
DAEMON_PLIST=/Library/LaunchDaemons/$DAEMON_LABEL.plist
RECEIPTS=/usr/local/lib/eugene-plexus
SERVICE_ACCOUNT=_eugeneplexus
IS_DAEMON=0 PLIST_OURS=0
if [ "$PLATFORM" = Darwin ]; then
    if [ -f "$DAEMON_PLIST" ]; then
        PROGRAM=$(/usr/bin/plutil -extract ProgramArguments.0 raw -o - "$DAEMON_PLIST" 2>/dev/null \
            || /usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$DAEMON_PLIST" 2>/dev/null || true)
        REAL_PREFIX=$(CDPATH= cd -- "$PREFIX" 2>/dev/null && pwd -P || printf '%s' "$PREFIX")
        case "$PROGRAM" in "$PREFIX"/*|"$REAL_PREFIX"/*) PLIST_OURS=1 ;; esac
    fi
    # A prefix Eugene's account owns is the daemon layout even with its job
    # gone, and root must never run the Python in it (the steps below do).
    if [ "$PLIST_OURS" = 1 ] || [ "$(stat -f %Su "$PREFIX" 2>/dev/null)" = "$SERVICE_ACCOUNT" ]; then
        IS_DAEMON=1
    fi
fi
if [ "$IS_DAEMON" = 1 ]; then
    dialog() {
        [ "$INTERACTIVE" = 1 ] || return 0
        /usr/bin/osascript - "$1" "$2" <<'APPLE' >/dev/null 2>&1 || true
on run argv
    display dialog (item 2 of argv) with title (item 1 of argv) buttons {"OK"} default button "OK"
end run
APPLE
    }
    die_daemon() {
        printf 'error: %s\n' "$*" >&2
        dialog "Eugene removal did not finish" "$*"
        exit 1
    }
    if [ "$(id -u)" != 0 ]; then
        # Root runs this script again, so it must be root's: owned by root,
        # written by nobody else, in a folder only root can write.
        SELF=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/$(basename -- "$0")
        for path in "$SELF" "$(dirname -- "$SELF")"; do
            [ "$(stat -f %u "$path" 2>/dev/null)" = 0 ] || die_daemon "Removing Eugene needs root's own copy of its removal: run $RECEIPTS/remove.sh. Nothing was removed."
            case "$(stat -f %Sp "$path" 2>/dev/null)" in
                ?????w*|????????w*) die_daemon "$path can be changed by others, so it was not run as root. Nothing was removed." ;;
            esac
        done
        set -- /bin/sh "$SELF" --prefix "$PREFIX" --person "$(id -un)"
        [ "$PURGE_DOWNLOADS" != 1 ] || set -- "$@" --purge-downloads
        [ "$PURGE_DATA" != 1 ] || set -- "$@" --purge-data
        if [ "$INTERACTIVE" != 1 ]; then
            exec sudo "$@"
        fi
        if ! /usr/bin/osascript - "$PREFIX" <<'APPLE' >/dev/null 2>&1
on run argv
    display dialog ("Remove Eugene from this Mac?" & return & "It stops starting at boot, and its own account is removed. Its settings are kept, readable by administrators only, beside " & item 1 of argv & ".") with title "Remove Eugene Plexus" buttons {"Cancel", "Remove Eugene"} default button "Cancel" cancel button "Cancel" with icon caution
end run
APPLE
        then echo 'Removal cancelled.'; exit 0; fi
        if REPORT=$(/usr/bin/osascript - "$@" <<'APPLE' 2>&1
on run argv
    set command to ""
    repeat with anArgument in argv
        set command to command & " " & quoted form of (contents of anArgument)
    end repeat
    do shell script command with administrator privileges
end run
APPLE
        ); then
            printf '%s\n' "$REPORT"
            dialog "Eugene removal" "$REPORT"
            exit 0
        fi
        die_daemon "Eugene was not removed: $REPORT"
    fi

    # Root from here on.
    WARNINGS=$(mktemp "/tmp/eugene-plexus-removal.XXXXXX")
    warn() { printf 'warning: %s\n' "$*" >&2; printf '%s\n' "$*" >> "$WARNINGS"; }
    if [ "$PLIST_OURS" = 1 ]; then
        if launchctl print "system/$DAEMON_LABEL" >/dev/null 2>&1; then
            if ! SAID=$(launchctl bootout "system/$DAEMON_LABEL" 2>&1); then
                rm -f "$WARNINGS"
                die_daemon "macOS refused to stop Eugene's startup job: ${SAID:-launchctl gave no reason}. Nothing was removed."
            fi
        fi
        rm -f "$DAEMON_PLIST"
    fi
    # Anything still running from the prefix, its engines included. Match
    # an executable's path, never a pattern.
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
        if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || warn "Eugene process $pid did not stop."; fi
    done
    # The firewall entry the installer added for this install's Python.
    if [ -f "$RECEIPTS/firewall.txt" ]; then
        while IFS= read -r program; do
            case "$program" in "$PREFIX"/*) ;; *) continue ;; esac
            /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$program" >/dev/null 2>&1 \
                || warn "Firewall entry kept: $program. Remove it in System Settings > Network > Firewall > Options."
        done < "$RECEIPTS/firewall.txt"
    fi
    # Keychain entries the person's own install made before it moved to the
    # daemon (os_keyring); they are named by this install's master salt.
    SALT=$(sed -n 's/^[[:space:]]*masterSalt:[[:space:]]*//p' "$PREFIX/agent.yaml" 2>/dev/null | head -n 1 | tr -d "'\"")
    if [ -n "$PERSON" ] && [ -n "$SALT" ] && id -u "$PERSON" >/dev/null 2>&1 && [ "$PERSON" != root ]; then
        FP=$(printf '%s' "$SALT" | base64 --decode 2>/dev/null | shasum -a 256 | cut -c1-12)
        for service in eugene-plexus-agent eugene-plexus-control; do
            for name in "master-key:$FP" "master-key-$FP"; do
                rc=0
                sudo -u "$PERSON" /usr/bin/security delete-generic-password -s "$service" -a "$name" >/dev/null 2>&1 || rc=$?
                case "$rc" in 0|44) ;; *) warn "Keychain entry kept: $service ($name). Remove it in Keychain Access." ;; esac
            done
        done
    fi
    # The files stay, as root's alone: the account goes next, and files
    # left with its number would belong to whichever account gets it.
    KEEP=$PREFIX.removed-$(date +%Y%m%d%H%M%S)
    [ ! -e "$KEEP" ] || die_daemon "The retained folder already exists: $KEEP. Nothing more was removed."
    mv -- "$PREFIX" "$KEEP" || die_daemon "Could not move $PREFIX to $KEEP. Eugene no longer starts; run the removal again."
    chown -R -P root:wheel "$KEEP" || warn "Could not give $KEEP to root."
    chmod 0700 "$KEEP"
    # The engine builds and model copies this install downloaded, as the
    # Linux system removal names them: the account's home is the prefix.
    if [ "$PURGE_DOWNLOADS" = 1 ]; then rm -rf -- "$KEEP/engines" "$KEEP/.eugene-plexus" || warn "Could not remove the engine builds in $KEEP."; fi
    if [ "$PURGE_DATA" = 1 ]; then
        # Everything but a models folder, which holds a person's files.
        for item in "$KEEP"/* "$KEEP"/.[!.]*; do
            [ -e "$item" ] || [ -L "$item" ] || continue
            [ "${item##*/}" = models ] && continue
            rm -rf -- "$item" || warn "Could not remove $item."
        done
        rmdir "$KEEP" 2>/dev/null || true
    fi
    # The account, only when the installer made it, and only that account.
    if [ -f "$RECEIPTS/account.txt" ]; then
        read -r _kind UID_MADE GID_MADE GROUP_MADE < "$RECEIPTS/account.txt" || true
        if [ "$(id -u "$SERVICE_ACCOUNT" 2>/dev/null)" = "$UID_MADE" ] && [ -n "$UID_MADE" ] && [ "$UID_MADE" != 0 ]; then
            for group in $(id -Gn "$SERVICE_ACCOUNT" 2>/dev/null); do
                [ "$group" = "$SERVICE_ACCOUNT" ] && continue
                dseditgroup -o edit -d "$SERVICE_ACCOUNT" -t user "$group" >/dev/null 2>&1 || true
            done
            dscl . -delete "/Users/$SERVICE_ACCOUNT" || warn "Could not remove the $SERVICE_ACCOUNT account: sudo dscl . -delete /Users/$SERVICE_ACCOUNT"
        fi
        if [ "$GROUP_MADE" = 1 ] && [ -n "$GID_MADE" ] && [ "$GID_MADE" != 0 ] \
                && [ "$(dscl . -read "/Groups/$SERVICE_ACCOUNT" PrimaryGroupID 2>/dev/null | awk '{print $2}')" = "$GID_MADE" ]; then
            dscl . -delete "/Groups/$SERVICE_ACCOUNT" || warn "Could not remove the $SERVICE_ACCOUNT group: sudo dscl . -delete /Groups/$SERVICE_ACCOUNT"
        fi
    fi
    # The removal app, only ours (its recorded prefix is this one).
    if [ -f "$RECEIPTS/mac-app.txt" ]; then
        APP=$(cat "$RECEIPTS/mac-app.txt")
        case "$APP" in */Applications/"Remove Eugene Plexus"*.app)
            if [ -f "$APP/Contents/Resources/prefix.txt" ] && [ "$(cat "$APP/Contents/Resources/prefix.txt")" = "$PREFIX" ]; then rm -rf -- "$APP"; fi ;;
        esac
    fi
    rm -f "$RECEIPTS/account.txt" "$RECEIPTS/firewall.txt" "$RECEIPTS/mac-app.txt" "$RECEIPTS/remove.sh"
    rmdir "$RECEIPTS" 2>/dev/null || true
    echo "Eugene's removal finished. It no longer starts at boot."
    if [ -d "$KEEP" ]; then
        echo "Its settings and logs are kept, readable by administrators only: $KEEP"
        echo "Delete them when you are sure: sudo rm -rf '$KEEP'"
    fi
    echo 'Your model folders were kept.'
    if [ -s "$WARNINGS" ]; then echo 'Items to review:'; cat "$WARNINGS"; rm -f "$WARNINGS"; exit 1; fi
    rm -f "$WARNINGS"
    exit 0
fi
# A per-user install is removed by its person: as root this would run the
# Python in their folder as root.
if [ "$PLATFORM" = Darwin ] && [ "$(id -u)" = 0 ]; then
    echo "The install at $PREFIX belongs to a person's own account. Run its removal as that person, without sudo. Nothing was removed." >&2
    exit 1
fi
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
