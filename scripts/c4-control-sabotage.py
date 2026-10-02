"""Sabotage for C4's control half: a person's optional email, and the
`email` scope that gives it to an app.

Each sabotage edits control's source, runs the sign-in tests, and restores
the file from a byte copy taken first. A baseline run that must pass opens
it. A timeout counts as caught.

    python scripts/c4-control-sabotage.py [--control ../control]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OIDC = "src/eugene_plexus_control/oidc.py"
ROUTES = "src/eugene_plexus_control/routes/oidc.py"
PEOPLE = "src/eugene_plexus_control/routes/people.py"
APPLIED = "src/eugene_plexus_control/applied.py"
TESTS = ["tests/test_oidc.py"]

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "the email goes out without the email scope",
        OIDC,
        '        if self.email and "email" in scope.split():',
        "        if self.email:",
    ),
    (
        "the email is called verified",
        OIDC,
        '            claims["email_verified"] = False',
        '            claims["email_verified"] = True',
    ),
    (
        "a person's email is not read into their sign-in",
        OIDC,
        '        email=person.get("email"),\n',
        "",
    ),
    (
        "the granted scope drops email",
        ROUTES,
        'GRANTED_SCOPES = ("openid", "profile", "email")',
        'GRANTED_SCOPES = ("openid", "profile")',
    ),
    (
        "userinfo ignores the token's scope",
        ROUTES,
        '    scope = str(claims.get("scope") or "openid")\n',
        '    scope = "openid profile email"\n',
    ),
    (
        "two people may share an email",
        PEOPLE,
        '        raise problem(409, "That email is taken"',
        '        pass\n    if False:\n        raise problem(409, "That email is taken"',
    ),
    (
        "emails are compared as typed",
        PEOPLE,
        '        (p.get("email") or "").casefold() == email.casefold() and p["id"] != except_id',
        '        (p.get("email") or "") == email and p["id"] != except_id',
    ),
    (
        "a person cannot keep their own address",
        PEOPLE,
        '        email = _check_email(machine, changes["email"], except_id=person_id)',
        '        email = _check_email(machine, changes["email"])',
    ),
    (
        "clearing an email leaves it",
        PEOPLE,
        '        else:\n            record.pop("email", None)\n',
        "",
    ),
    (
        "the log refuses a person with an email",
        APPLIED,
        '        "email",\n        "passwordVerifier",',
        '        "passwordVerifier",',
    ),
    (
        "the log takes any email",
        APPLIED,
        '    if email is not None and (not isinstance(email, str) or "@" not in email):',
        "    if False:",
    ),
]


def run(control: Path) -> bool:
    python = control / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = control / ".venv" / "bin" / "python"
    try:
        done = subprocess.run(
            [str(python), "-m", "pytest", "-q", "-x", *TESTS],
            cwd=control,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--control", type=Path, default=Path(__file__).resolve().parents[2] / "control"
    )
    control = parser.parse_args().control.resolve()
    if not run(control):
        print("BASELINE FAILED: the tests do not pass unsabotaged")
        return 2
    print("baseline passes")
    caught = 0
    for name, rel, old, new in SABOTAGES:
        path = control / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:  # a Windows checkout
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} matches): {name}")
            return 2
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(control)
        finally:
            path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}")
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
