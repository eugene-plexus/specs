"""Fast S10 instrument checks and deliberate regressions, safe beside an install."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def run(command, expected=0):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == expected, result.stdout + result.stderr
    return result.stdout + result.stderr


def checks():
    print(run([sys.executable, str(HERE / "s10-network-checks.py")]).strip())
    with tempfile.TemporaryDirectory(prefix="ep-s10-guards-") as work:
        root = Path(work).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        for name in ("s10-network.py", "s10-network-checks.py"):
            shutil.copyfile(HERE / name, root / name)
        network = root / "s10-network.py"
        original = network.read_bytes()
        try:
            source = original.decode("utf-8")
            old = "max(self.next, time.monotonic() - self.burst / self.rate)"
            assert old in source
            network.write_text(source.replace(old, "(time.monotonic() - self.burst / self.rate)"), encoding="utf-8")
            output = run([sys.executable, str(root / "s10-network-checks.py")], 1)
            assert "AssertionError" in output
            print("CAUGHT: independent transfers evade the shared cap")
        finally:
            network.write_bytes(original)
        run([sys.executable, str(root / "s10-network-checks.py")])

        if sys.platform != "win32":
            return
        installer = root / "install.ps1"
        original = (HERE / "install.ps1").read_bytes()
        installer.write_bytes(original)
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(HERE / "s10-isolation-checks.ps1"), "-Installer", str(installer)]
        print(run(command).strip())
        source = original.decode("utf-8")
        for label, old, new in [
            ("isolated mode permits startup", "-or -not $NoStart -or", "-or $false -or"),
            ("isolated prefix overlaps the live install", 'Die "the isolated prefix must be outside the existing install"', 'Say "the isolated prefix must be outside the existing install"'),
            ("isolated install stops the live autostart", "-not $Isolated -and ((Get-AgentTask)", "((Get-AgentTask)"),
            ("isolated install writes the account config path", 'if (-not $Isolated) {\n    [Environment]::SetEnvironmentVariable', 'if ($true) {\n    [Environment]::SetEnvironmentVariable'),
            ("isolated install writes persistent ports", 'if ($Isolated) {\n    Say "isolated install:', 'if ($false) {\n    Say "isolated install:'),
        ]:
            # Universal newlines here, restoring the exact original bytes later.
            normalized = source.replace("\r\n", "\n")
            assert old in normalized, label
            try:
                installer.write_text(normalized.replace(old, new, 1), encoding="utf-8")
                output = run(command, 1)
                assert "Isolated install" in output or "Isolated argument" in output, output
                print("CAUGHT: " + label)
            finally:
                installer.write_bytes(original)
        run(command)
        print("PASS: restored isolation guards")


if __name__ == "__main__":
    checks()
