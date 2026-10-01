"""Sabotage pass for C2 (signing in with Eugene over OpenID Connect).

Each sabotage puts one defect back into a component's working tree, runs
the tests that guard it, and requires them to FAIL. Restores are from byte
copies taken before the first edit, never `git checkout --`
(feedback: sabotage-runs-restore-from-a-copy), and the pass opens with a
baseline that must pass.

The whole flow with a real OpenID Connect client is
`c2-sign-in-acceptance.py`; this pass is what makes each guard in it
answer for itself.

The first pass escaped two. One was a test that could not fail (a node
without the gateway grant cannot mint the gateway token it forged); the
other was a route's own password-length check behind the contract's
`minLength: 12`, which refuses first, so the spare was deleted.

    python scripts/c2-sabotage.py [words in a label, to run only those]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
CONTROL = ROOT / "control"
UI = ROOT / "ui"
C = CONTROL / "src/eugene_plexus_control"
A = AGENT / "src/eugene_plexus_agent"
ROUTES = C / "routes/oidc.py"
PROVIDER = C / "oidc.py"
PEOPLE = C / "routes/people.py"
APPLIED = C / "applied.py"
FORWARD = A / "routes/oidc_forward.py"
APPS_ROUTE = A / "routes/apps.py"
APPS = A / "apps.py"
LAUNCHER = A / "app_launcher.py"
UI_PEOPLE = UI / "src/app/people/page.tsx"
UI_APP = UI / "src/app/apps/app/page.tsx"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


def pytest(repo: Path, *tests: str):
    return lambda: [str(python(repo)), "-m", "pytest", "-q", "-p", "no:warnings", "-p",
                    "no:cacheprovider", *tests]


RUNNERS = {
    CONTROL: pytest(CONTROL, "tests/test_oidc.py", "tests/test_replay_equivalence.py"),
    AGENT: pytest(AGENT, "tests/test_sign_in_with_eugene.py", "tests/test_app_accounts.py"),
    UI: lambda: ["npx", "vitest", "run", "src/app/people", "src/lib/people.test.ts",
                 "src/app/apps/app/page.test.tsx"],
}

SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    # --- whom the root believes -------------------------------------------
    (
        "a forwarded host is believed with no agent token",
        CONTROL, ROUTES,
        "    if not token or not host:\n        return None\n",
        "    if not host:\n        return None\n    if not token:\n        return host, \"http\", \"unknown\"\n",
    ),
    (
        "a forwarded host is believed beside any service token",
        CONTROL, ROUTES,
        "    if claims.sub != tokens.SUB_AGENT or claims.issuer_node is None:\n",
        "    if claims.issuer_node is None:\n",
    ),
    (
        "the client secret is not compared",
        CONTROL, ROUTES,
        '    if not hmac.compare_digest(oidc.secret_verifier(unquote(secret)), client["secretVerifier"]):\n        return None\n',
        "",
    ),
    # --- the page ---------------------------------------------------------
    (
        "an unregistered return address is followed",
        CONTROL, ROUTES,
        '    if redirect_uri not in client["redirectUris"]:\n',
        "    if False:\n",
    ),
    (
        "PKCE plain is accepted",
        CONTROL, ROUTES,
        '    if q.get("code_challenge_method") != "S256" or not 43 <= len(challenge) <= 128:\n',
        "    if not 43 <= len(challenge) <= 128:\n",
    ),
    (
        "no limit on failed sign-ins",
        CONTROL, ROUTES,
        "    for bucket in buckets:\n        if auth.is_login_rate_limited(\n",
        "    for bucket in []:\n        if auth.is_login_rate_limited(\n",
    ),
    (
        "an unknown name skips the password check, so its timing says so",
        CONTROL, ROUTES,
        "        if security.verify_passphrase(password, verifier) and person is not None:\n",
        "        if person is not None and security.verify_passphrase(password, verifier):\n",
    ),
    (
        "a turned-off person signs in",
        CONTROL, ROUTES,
        '    if person is not None and person.get("disabled"):\n',
        "    if False:\n",
    ),
    (
        "a person signs in to an app they are not given",
        CONTROL, ROUTES,
        '    if person is not None and not oidc.may_use(person, client["clientId"]):\n',
        "    if False:\n",
    ),
    (
        "the page escapes nothing",
        CONTROL, PROVIDER,
        "    e = html.escape\n",
        "    e = str\n",
    ),
    (
        "the light page's button text falls under the contrast minimum",
        CONTROL, PROVIDER,
        "--on-accent: #ffffff;",
        "--on-accent: #0f141c;",
    ),
    (
        "the page can be framed",
        CONTROL, PROVIDER,
        "f\"frame-ancestors 'none'; form-action {form_action}\"",
        'f"form-action {form_action}"',
    ),
    # --- a person's own password (D10) ------------------------------------
    (
        "two different new passwords are taken",
        CONTROL, ROUTES,
        '        if new_password != str(form.get("new_password_again") or ""):\n',
        "        if False:\n",
    ),
    (
        "a short new password is taken",
        CONTROL, ROUTES,
        "        if len(new_password) < oidc.MIN_PASSWORD:\n",
        "        if False:\n",
    ),
    (
        "the owner's passphrase is offered for change on the page",
        CONTROL, ROUTES,
        "        if person is None:\n            return again(\n                400,",
        "        if False:\n            return again(\n                400,",
    ),
    # --- the code ---------------------------------------------------------
    (
        "a code works twice",
        CONTROL, PROVIDER,
        "            return self._codes.pop(value, None)\n",
        "            return self._codes.get(value)\n",
    ),
    (
        "another app's code is taken",
        CONTROL, ROUTES,
        '                or issued.client_id != client["clientId"]\n',
        "",
    ),
    (
        "the code's return address is not checked",
        CONTROL, ROUTES,
        '                or issued.redirect_uri != form.get("redirect_uri")\n',
        "",
    ),
    (
        "PKCE is not checked",
        CONTROL, ROUTES,
        '                or not oidc.pkce_matches(str(form.get("code_verifier") or ""), issued.challenge)\n',
        "",
    ),
    # --- tokens -----------------------------------------------------------
    (
        "a token of one kind passes as another",
        CONTROL, PROVIDER,
        '        if header.get("typ") != typ or header.get("alg") != "RS256":\n',
        '        if header.get("alg") != "RS256":\n',
    ),
    (
        "a revoked sign-in refreshes",
        CONTROL, PROVIDER,
        '    if claims.get("sid") in state.revoked_sign_ins:\n        return None\n',
        "",
    ),
    (
        "a turned-off person refreshes",
        CONTROL, PROVIDER,
        '    if person is None or person.get("disabled") or not may_use(person, client_id):\n',
        "    if person is None or not may_use(person, client_id):\n",
    ),
    (
        "a sign-in from before a new password refreshes",
        CONTROL, PROVIDER,
        '    if isinstance(auth_at, (int, float)) and iso_to_epoch(person["passwordChangedAt"]) > auth_at:\n',
        "    if False:\n",
    ),
    (
        "revoking records nothing",
        CONTROL, ROUTES,
        '    if claims["sid"] not in machine.state.revoked_sign_ins:\n',
        "    if False:\n",
    ),
    (
        "the signing key is replicated in the clear",
        CONTROL, PROVIDER,
        '                        "sealedKey": security.seal_b64(pem, master),\n',
        '                        "sealedKey": pem.decode(),\n',
    ),
    (
        "the log takes a sign-in key with its private part",
        CONTROL, APPLIED,
        '    if not isinstance(jwk, dict) or jwk.get("kty") != "RSA" or "d" in jwk:\n',
        '    if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":\n',
    ),
    # --- people and apps on the console -----------------------------------
    (
        "people and apps are open to anyone",
        CONTROL, PEOPLE,
        'router = APIRouter(tags=["people"], dependencies=[Depends(require_operator)])\n',
        'router = APIRouter(tags=["people"])\n',
    ),
    (
        "a person may be called operator",
        CONTROL, PEOPLE,
        "    if name.casefold() == OPERATOR_NAME:\n",
        "    if False:\n",
    ),
    (
        "a return address may carry a fragment",
        CONTROL, PEOPLE,
        '        if parts.scheme not in ("http", "https") or not parts.netloc or parts.fragment:\n',
        '        if parts.scheme not in ("http", "https") or not parts.netloc:\n',
    ),
    (
        "deleting an app leaves it on people's lists",
        CONTROL, APPLIED,
        '            {**person, "apps": [a for a in person["apps"] if a != client_id]}\n',
        "            person\n",
    ),
    # --- the agent's forward ----------------------------------------------
    (
        "every header the caller sends crosses to the root",
        AGENT, FORWARD,
        "    headers = {k: v for k, v in request.headers.items() if k.lower() in _PASSED_ON}\n",
        "    headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}\n",
    ),
    (
        "every header the root sets comes back",
        AGENT, FORWARD,
        "    back = {k: v for k, v in answer.headers.items() if k.lower() in _PASSED_BACK}\n",
        "    back = {k: v for k, v in answer.headers.items() if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')}\n",
    ),
    (
        "the forward carries no agent token",
        AGENT, FORWARD,
        '        headers[NODE_TOKEN_HEADER] = request.app.state.auth_state.trust.agent_token("control")\n',
        "        pass\n",
    ),
    # --- installing an app that signs in ----------------------------------
    (
        "an app is registered with the agent's own token, not the caller's",
        AGENT, APPS_ROUTE,
        '        authorization=request.headers.get("authorization"),\n        body={\n            "name": manifest.name,\n',
        '        authorization=None,\n        body={\n            "name": manifest.name,\n',
    ),
    (
        "a retried install registers a second client",
        AGENT, APPS_ROUTE,
        "    if store.oidc_client(manifest.id) and secret_file.is_file() and secret_file.stat().st_size:\n        return\n",
        "",
    ),
    (
        "an app that does not sign in gets no secret file",
        AGENT, APPS_ROUTE,
        '        if not secret_file.exists():\n            write_private(secret_file, "")\n',
        "        pass\n",
    ),
    (
        "uninstalling goes on when the root keeps the client",
        AGENT, APPS_ROUTE,
        "    except HTTPException as exc:\n        if exc.status_code != status.HTTP_404_NOT_FOUND:\n            raise\n    manager.store.drop_oidc_client(app_id)\n",
        "    except HTTPException:\n        pass\n    manager.store.drop_oidc_client(app_id)\n",
    ),
    (
        "an app that does not sign in is told how",
        AGENT, APPS,
        "        if record.manifest.signIn and client_id and issuer:\n",
        "        if client_id and issuer:\n",
    ),
    (
        "the reserved port is handed out again",
        AGENT, APPS,
        "        taken = self.store.taken_ports() | set(self._reserved_ports.values())\n",
        "        taken = self.store.taken_ports()\n",
    ),
    (
        "an install takes a port other than the one its callback names",
        AGENT, APPS,
        "                    port=self._reserved_ports.pop(manifest.id, 0) or self.allocate_port(),\n",
        "                    port=self.allocate_port(),\n",
    ),
    (
        "the launcher never points the app at its secret",
        AGENT, LAUNCHER,
        '    if env.get("EUGENE_PLEXUS_APP_OIDC_CLIENT_ID") and spec.get("oidcSecretFile"):\n',
        "    if False:\n",
    ),
    (
        "the launcher ignores the secret systemd hands over",
        AGENT, LAUNCHER,
        '    if not spec.get("oidcSecretFile") and credentials:\n',
        "    if False:\n",
    ),
    # --- the console ------------------------------------------------------
    (
        "a new app's secret stays on screen",
        UI, UI_PEOPLE,
        "onClick={() => setMade(null)}",
        "onClick={() => undefined}",
    ),
    (
        "a new person meant for every app is given none",
        UI, UI_PEOPLE,
        "        apps: every ? null : chosen,\n",
        "        apps: chosen,\n",
    ),
    (
        "the sign-in address links somewhere other than where it is set",
        UI, UI_PEOPLE,
        'const ROOT_SETTINGS = "/config?sel=control";\n',
        'const ROOT_SETTINGS = "/config";\n',
    ),
    (
        "an installed app's page does not link to People",
        UI, UI_APP,
        '                <Link href="/people" className="underline">\n',
        '                <Link href="/apps" className="underline">\n',
    ),
]


def run(repo: Path) -> int:
    result = subprocess.run(RUNNERS[repo](), cwd=repo, capture_output=True, text=True, timeout=1200,
                            encoding="utf-8", errors="replace",
                            shell=sys.platform == "win32" and repo == UI)
    tail = (result.stdout + result.stderr).strip().splitlines()
    summary = next((line for line in reversed(tail) if "passed" in line or "failed" in line), "")
    print(f"    {repo.name}: exit={result.returncode}  {summary.strip()}", flush=True)
    return result.returncode


def main() -> None:
    only = " ".join(sys.argv[1:]).lower()
    chosen = [s for s in SABOTAGES if only in s[0].lower()]
    files = {path for _, _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    for label, _, path, old, _ in SABOTAGES:
        if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
            raise SystemExit(f"sabotage anchor not found exactly once: {label}")
    caught, escaped = 0, []
    try:
        print("baseline: every guard passes unsabotaged", flush=True)
        if any(run(repo) != 0 for repo in RUNNERS):
            raise SystemExit("BASELINE FAILED; fix that first")
        print("baseline PASS\n", flush=True)
        for label, repo, path, old, new in chosen:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            print(f"sabotage: {label}", flush=True)
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run(repo)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n", flush=True)
            else:
                escaped.append(label)
                print("    ESCAPED\n", flush=True)
        print(f"{caught} of {len(chosen)} caught")
        for label in escaped:
            print(f"ESCAPED: {label}")
        if escaped:
            sys.exit(1)
    finally:
        for path, raw in copies.items():
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
