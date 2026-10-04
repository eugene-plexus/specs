# Remove Eugene from Windows or Mac

The offline removal utilities described here are included in the development
installers after v0.1.0. Existing installs gain them when updated with an
installer that includes this change. Published v0.1.0 installer assets remain
unchanged.

On **Windows**, open **Settings → Apps → Installed apps → Eugene Plexus →
Uninstall**. Windows asks for administrator access for a service installation.
On **Mac**, open **Remove Eugene Plexus** in your home folder's **Applications**
folder. A custom installation has a short identifier appended to the app name.
Both utilities work without Eugene running and without an internet connection.

The removal window shows the size of the software and the optional data groups.
By default it removes Eugene's Python environments, bundled tools, installed
app versions and startup integration, while keeping settings, app data, logs,
engine downloads and model copies. Original model folders are always kept.

Two unchecked choices let you also delete:

- **Settings, app data and logs**: includes local identity/configuration and
  conversations stored by installed apps. This cannot be undone.
- **Downloaded engines and model copies**: includes downloads attributed to
  this installation. This does not delete original Library model folders.

Shared operating-system dependencies, such as the Microsoft Visual C++ runtime,
are kept. Unknown files and download locations whose ownership cannot be
established are kept and reported.

## Retained files and later cleanup

The remaining files move to a sibling folder named
`<installation>.removed-<timestamp>`. This is a data folder with a small offline
cleanup utility, not a runnable Eugene installation. The final report names
the folder and each retained download location. Windows service installs often
have original models in this folder's `models` subfolder; keep or move those
models before deleting the folder yourself.

To change the cleanup choices later:

- Windows: run `uninstall\remove.ps1 -Interactive` in the retained folder using
  PowerShell (**Run as administrator** for a service installation;
  `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
  "<retained folder>\uninstall\remove.ps1" -Interactive`).
- Mac: open `uninstall/Remove Eugene.command` in the retained folder.

The cleanup receipt preserves the original download locations. Later cleanup
works even after Python, `agent.yaml` and the application have been removed.
Repeated cleanup does not delete original model folders or affect a new
installation at the former path.

## Command-line removal

Use the locally saved utility:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\EugenePlexus\uninstall\remove.ps1" -Interactive
```

```sh
sh "$HOME/.local/share/eugene-plexus/uninstall/remove.sh" --interactive
```

The current source installers also accept `-Uninstall` / `--uninstall`.
Add `-PurgeDownloads` / `--purge-downloads` to delete managed downloads, and
`-PurgeData` / `--purge-data` to delete settings and app data. An explicit
`-Prefix` / `--prefix` selects one installation or retained folder. Without a
prefix, Windows discovers registered/default installations; follow-up purge
also finds receipts beside the default locations. The Mac installer finds
receipts beside its selected/default prefix.

These changes also cover POSIX per-user installs. The Linux system-account
uninstall retains its existing behavior; `--purge-data` and the interactive
desktop flow are not offered for that layout.

## If something remains

The final report is also saved at `uninstall/receipt/report.txt`. A failed
cleanup returns a nonzero exit code and records the observed error and the
remaining work. Closing a removal window before confirmation changes no
services or files other than its small inventory.

Credentials are removed from the invoking user's vault and, for a Windows
LocalSystem service, from SYSTEM's vault through a temporary task. A locked or
unavailable vault is reported, never described as empty. A legacy unscoped
credential is retained when ownership cannot be established. On Mac, removing
an existing firewall exception can request administrator permission. A shared
Windows Eugene firewall rule is retained if another installation still uses it.

## Maintenance

The source is `scripts/uninstall.ps1`, `scripts/uninstall.sh` and
`scripts/uninstall_inventory.py`. After changes run
`python scripts/embed-uninstall.py`; `--check` verifies that the self-contained
installers contain the exact current utilities. Do not edit the embedded copies.
Release assets are immutable; these utilities ship in the next release.

The native entry points follow Microsoft's
[uninstall registration](https://learn.microsoft.com/en-us/windows/win32/msi/uninstall-registry-key)
and Apple's [application bundle keys](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CoreFoundationKeys.html).
