"""C2 acceptance: an app signs people in with Eugene (OpenID Connect).

Design: `docs/design/sign-in-with-eugene.md`. One real control root and one
real agent on ephemeral loopback ports, onboarded through the API. The app
is Authlib -- the client library Open WebUI signs in with -- driven the way
an app's server drives it, against the issuer at the agent's `/oidc`. The
browser's part (opening the sign-in page, posting the form) is done with
httpx, since the page is a plain server-rendered form.

What it proves, in order:

- discovery, JWKS and the endpoints are where OIDC says, RS256 only;
- the solo case: with no people, the page asks for Eugene's passphrase and
  nothing else, and the owner signs in as `operator`;
- the tokens open nothing in the hub;
- PKCE, single-use codes, exact redirect URIs and client secrets are
  enforced;
- a person signs in with their own name and password, is refused for an
  app they are not given, and is cut off at the next refresh once disabled,
  revoked or given a new password.

Run with Python holding editable installs of agent and control, plus
`authlib` (scripts/requirements-acceptance.txt).

**Before C2 this fails at its first check**: there is no `/oidc` anywhere.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

RESULTS: list[tuple[str, bool, str]] = []


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append((number, bool(passed), str(detail)))
    tail = f"  -- {detail}" if detail not in ("", None) else ""
    print(f"  {'PASS' if passed else 'FAIL'}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


class Abort(Exception):
    pass


def must(number: str, claim: str, passed: bool, detail: object = "") -> None:
    if not check(number, claim, passed, detail):
        raise Abort(f"{number}: {claim}")


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    else:
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(config_file=directory / "agent.yaml", default_topology=False, bind_port=port)
        )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


# --------------------------------------------------------------------------- #
# the browser's part
# --------------------------------------------------------------------------- #


def form_fields(page: str) -> dict[str, str]:
    """The sign-in form's hidden fields and which inputs it asks for."""
    fields = {
        m.group(1): html.unescape(m.group(2))
        for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page)
    }
    fields["__asks__"] = " ".join(sorted(set(re.findall(r'<input[^>]*name="(name|password)"', page))))
    return fields


def sign_in(browser: httpx.Client, authorize_url: str, *, password: str, name: str | None = None,
            new_password: str | None = None):
    """Open the page, post the form. Returns (status, location or page text)."""
    page = browser.get(authorize_url)
    if page.status_code != 200:
        return page.status_code, page.text
    fields = form_fields(page.text)
    data = {k: v for k, v in fields.items() if not k.startswith("__") and k not in ("name", "password")}
    data["password"] = password
    if new_password is not None:
        if 'name="new_password"' not in page.text:
            return 0, "the page offers no way to change a password"
        data["new_password"] = data["new_password_again"] = new_password
    if name is not None:
        data["name"] = name
    answer = browser.post(urlsplit(authorize_url)._replace(query="").geturl(), data=data)
    if answer.status_code in (302, 303):
        return answer.status_code, answer.headers.get("location", "")
    return answer.status_code, answer.text


def code_from(location: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlsplit(location).query)
    return (query.get("code") or [None])[0], (query.get("state") or [None])[0]


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


def exercise(directory: Path) -> None:
    for name in [k for k in os.environ if k.startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    from authlib.integrations.httpx_client import OAuth2Client
    from joserfc import jwt
    from joserfc.jwk import KeySet

    names = ("control", "agent")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=10, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url(name) + path, headers=headers, **kwargs)

    def wait(check_fn, label: str, seconds: float = 15):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check_fn():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise Abort("timed out: " + label)

    def start(name: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory", str(work),
             "--port", str(ports[name])],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    try:
        print("== a root and an agent, onboarded through the API", flush=True)
        start("control")
        start("agent")
        must("1", "control initializes",
             call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).status_code == 204)
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root, json={"nodeName": "c2-node"}).json()["token"]
        local = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        enrolled = call("agent", "POST", "/v1/node/enroll", local,
                        json={"controlUrl": url("control"), "token": join, "name": "c2-node"}, timeout=60)
        must("2", "the agent enrolls with the root", enrolled.status_code == 200, enrolled.text[:200])
        wait(lambda: call("agent", "GET", "/healthz").status_code == 200, "agent after enrolment")
        operator = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        issuer = url("agent") + "/oidc"

        print("\n== discovery and keys", flush=True)
        found = call("agent", "GET", "/oidc/.well-known/openid-configuration")
        must("10", "discovery answers at the agent's /oidc", found.status_code == 200, found.status_code)
        meta = found.json()
        check("11", "the issuer is the address the app asked at", meta.get("issuer") == issuer, meta.get("issuer"))
        check("12", "ID tokens are RS256 and nothing else",
              meta.get("id_token_signing_alg_values_supported") == ["RS256"],
              meta.get("id_token_signing_alg_values_supported"))
        check("13", "PKCE S256 is offered, and only the code flow",
              "S256" in (meta.get("code_challenge_methods_supported") or [])
              and meta.get("response_types_supported") == ["code"], meta.get("response_types_supported"))
        jwks = httpx.get(meta["jwks_uri"], trust_env=False).json()
        keys = jwks.get("keys") or []
        check("14", "the JWKS holds one RSA key, with a kid", len(keys) == 1 and keys[0].get("kty") == "RSA"
              and bool(keys[0].get("kid")) and "d" not in keys[0], [k.get("kty") for k in keys])
        key_set = KeySet.import_key_set(jwks)

        print("\n== an app is registered", flush=True)
        callback = "http://127.0.0.1:9/callback"
        made = call("control", "POST", "/v1/oidc/clients", root,
                    json={"name": "Acceptance app", "redirectUris": [callback]})
        must("20", "the owner registers an app; its secret is shown once", made.status_code == 201
             and bool(made.json().get("clientSecret")), made.text[:200])
        app_id, app_secret = made.json()["client"]["clientId"], made.json()["clientSecret"]
        listed = call("control", "GET", "/v1/oidc/clients", root)
        check("21", "the list never shows the secret", app_secret not in listed.text, listed.status_code)

        def rp(secret: str = app_secret) -> OAuth2Client:
            return OAuth2Client(client_id=app_id, client_secret=secret, redirect_uri=callback,
                                scope="openid profile", code_challenge_method="S256", trust_env=False,
                                token_endpoint_auth_method="client_secret_basic")

        def begin(session: OAuth2Client):
            verifier = secrets.token_urlsafe(48)
            nonce = secrets.token_urlsafe(16)
            authorize, state = session.create_authorization_url(
                meta["authorization_endpoint"], code_verifier=verifier, nonce=nonce)
            return authorize, state, verifier, nonce

        def validated(id_token: str, nonce: str) -> dict:
            claims = jwt.decode(id_token, key_set, algorithms=["RS256"]).claims
            assert claims["iss"] == issuer, claims
            assert claims["aud"] in (app_id, [app_id]), claims
            assert claims["nonce"] == nonce, claims
            assert claims["exp"] > time.time(), claims
            return claims

        print("\n== the solo case: Eugene's passphrase, nothing else", flush=True)
        browser = httpx.Client(trust_env=False, follow_redirects=False, timeout=10)
        session = rp()
        authorize, state, verifier, nonce = begin(session)
        page = browser.get(authorize)
        asks = form_fields(page.text)["__asks__"] if page.status_code == 200 else page.status_code
        check("30", "with no people, the page asks for the passphrase only", asks == "password", asks)
        status, location = sign_in(browser, authorize, password="not the passphrase")
        check("31", "a wrong passphrase stays on the page and issues no code",
              status == 200 and code_from(location if status in (302, 303) else "")[0] is None, status)
        status, location = sign_in(browser, authorize, password=passphrase)
        code, back = code_from(location) if status in (302, 303) else (None, None)
        must("32", "the passphrase sends the browser back to the app with a code and its state",
             bool(code) and back == state and location.startswith(callback), location[:120])
        tokens = session.fetch_token(meta["token_endpoint"], code=code, code_verifier=verifier)
        claims = validated(tokens["id_token"], nonce)
        check("33", "the ID token says the owner signed in", claims.get("sub") == "operator"
              and claims.get("eugene_role") == "operator", {k: claims.get(k) for k in ("sub", "eugene_role")})
        info = httpx.get(meta["userinfo_endpoint"], trust_env=False,
                         headers={"Authorization": f"Bearer {tokens['access_token']}"})
        check("34", "userinfo answers the access token with the same subject",
              info.status_code == 200 and info.json().get("sub") == "operator", info.text[:120])
        for label, token in (("ID token", tokens["id_token"]), ("access token", tokens["access_token"])):
            hub = [call("agent", "GET", "/v1/node", token).status_code,
                   call("control", "GET", "/v1/nodes", token).status_code,
                   call("agent", "GET", "/v1/logs", token).status_code]
            check("35", f"the {label} opens nothing in the hub", all(c == 401 for c in hub), hub)
        again = httpx.post(meta["token_endpoint"], trust_env=False, auth=(app_id, app_secret),
                           data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                 "redirect_uri": callback})
        check("36", "a code works once", again.status_code == 400 and again.json().get("error") == "invalid_grant",
              again.text[:120])

        print("\n== what the provider refuses", flush=True)
        session = rp()
        authorize, state, verifier, nonce = begin(session)
        _, location = sign_in(browser, authorize, password=passphrase)
        code, _ = code_from(location)
        wrong = httpx.post(meta["token_endpoint"], trust_env=False, auth=(app_id, app_secret),
                           data={"grant_type": "authorization_code", "code": code,
                                 "code_verifier": secrets.token_urlsafe(48), "redirect_uri": callback})
        check("40", "the wrong PKCE verifier is refused", wrong.status_code == 400
              and wrong.json().get("error") == "invalid_grant", wrong.text[:120])
        _, location = sign_in(browser, begin(session)[0], password=passphrase)
        code, _ = code_from(location)
        bad_secret = httpx.post(meta["token_endpoint"], trust_env=False, auth=(app_id, "not-the-secret"),
                                data={"grant_type": "authorization_code", "code": code,
                                      "code_verifier": verifier, "redirect_uri": callback})
        check("41", "the wrong client secret is refused", bad_secret.status_code == 401
              and bad_secret.json().get("error") == "invalid_client", bad_secret.text[:120])
        no_pkce = browser.get(meta["authorization_endpoint"], params={
            "response_type": "code", "client_id": app_id, "redirect_uri": callback,
            "scope": "openid", "state": "s", "nonce": "n"})
        check("42", "a request with no PKCE challenge is refused back to the app",
              no_pkce.status_code in (302, 303) and "error=invalid_request" in no_pkce.headers.get("location", ""),
              no_pkce.headers.get("location", no_pkce.status_code))
        elsewhere = browser.get(meta["authorization_endpoint"], params={
            "response_type": "code", "client_id": app_id, "redirect_uri": "http://evil.example/cb",
            "scope": "openid", "state": "s", "nonce": "n", "code_challenge": "x" * 43,
            "code_challenge_method": "S256"})
        check("43", "a redirect URI the app did not register is an error page, never a redirect",
              elsewhere.status_code == 400 and "location" not in elsewhere.headers, elsewhere.status_code)

        print("\n== a small business: people", flush=True)
        made = call("control", "POST", "/v1/people", root,
                    json={"name": "Ada", "displayName": "Ada Lovelace", "password": "first-password-ada"})
        must("50", "the owner adds a person", made.status_code == 201, made.text[:200])
        ada = made.json()
        listed = call("control", "GET", "/v1/people", root)
        check("51", "the list never shows a password or its verifier",
              "first-password-ada" not in listed.text and "argon2" not in listed.text, listed.status_code)
        session = rp()
        authorize, state, verifier, nonce = begin(session)
        page = browser.get(authorize)
        check("52", "with people, the page asks for a name and a password",
              form_fields(page.text)["__asks__"] == "name password", form_fields(page.text)["__asks__"])
        status, location = sign_in(browser, authorize, name="ada", password="first-password-ada")
        code, _ = code_from(location) if status in (302, 303) else (None, None)
        must("53", "Ada signs in with her own name (any case) and password", bool(code), location[:160])
        tokens = session.fetch_token(meta["token_endpoint"], code=code, code_verifier=verifier)
        claims = validated(tokens["id_token"], nonce)
        check("54", "the ID token names Ada, a member", claims.get("sub") == ada["id"]
              and claims.get("eugene_role") == "member" and claims.get("preferred_username") == "Ada",
              {k: claims.get(k) for k in ("sub", "eugene_role", "preferred_username")})
        status, page_text = sign_in(browser, begin(rp())[0], name="Ada", password="wrong-password")
        _, other = sign_in(browser, begin(rp())[0], name="Nobody", password="wrong-password")
        check("55", "a wrong password and an unknown name get the same answer",
              status == 200 and "Ada" not in page_text and _message(page_text) == _message(other),
              _message(page_text))
        status, location = sign_in(browser, begin(rp())[0], name="operator", password=passphrase)
        check("56", "the owner still signs in, as operator, with the passphrase", status in (302, 303)
              and bool(code_from(location)[0]), status)

        refreshed = session.refresh_token(meta["token_endpoint"], refresh_token=tokens["refresh_token"])
        check("57", "Ada's app refreshes her sign-in", bool(refreshed.get("id_token")), list(refreshed))

        other_app = call("control", "POST", "/v1/oidc/clients", root,
                         json={"name": "Second app", "redirectUris": ["http://127.0.0.1:9/two"]}).json()
        limited = call("control", "PATCH", f"/v1/people/{ada['id']}", root,
                       json={"apps": [other_app["client"]["clientId"]]})
        check("58", "the owner limits Ada to the second app", limited.status_code == 200, limited.text[:120])
        status, page_text = sign_in(browser, begin(rp())[0], name="Ada", password="first-password-ada")
        check("59", "Ada is refused for an app she is not given, with a sentence and no code",
              status == 403 and "Acceptance app" in page_text, (status, _message(page_text)))
        call("control", "PATCH", f"/v1/people/{ada['id']}", root, json={"apps": None})

        print("\n== taking it back", flush=True)
        session = rp()
        authorize, state, verifier, nonce = begin(session)
        _, location = sign_in(browser, authorize, name="Ada", password="first-password-ada")
        tokens = session.fetch_token(meta["token_endpoint"], code=code_from(location)[0], code_verifier=verifier)
        reset = call("control", "PUT", f"/v1/people/{ada['id']}/password", root,
                     json={"password": "second-password-ada"})
        check("60", "the owner sets Ada a new password", reset.status_code == 204, reset.status_code)
        old = _refresh(meta, app_id, app_secret, tokens["refresh_token"])
        check("61", "a refresh from before the new password is refused", old == "invalid_grant", old)
        status, _ = sign_in(browser, begin(rp())[0], name="Ada", password="first-password-ada")
        check("62", "the old password no longer signs her in", status == 200, status)

        session = rp()
        authorize, state, verifier, nonce = begin(session)
        _, location = sign_in(browser, authorize, name="Ada", password="second-password-ada")
        tokens = session.fetch_token(meta["token_endpoint"], code=code_from(location)[0], code_verifier=verifier)
        disabled = call("control", "PATCH", f"/v1/people/{ada['id']}", root, json={"disabled": True})
        check("63", "the owner disables Ada", disabled.status_code == 200, disabled.text[:120])
        check("64", "her app's next refresh is refused",
              _refresh(meta, app_id, app_secret, tokens["refresh_token"]) == "invalid_grant")
        status, page_text = sign_in(browser, begin(rp())[0], name="Ada", password="second-password-ada")
        check("65", "and she cannot sign in: no code, and the page says signing in is off for her",
              status == 403 and "turned off" in _message(page_text), (status, _message(page_text)))
        call("control", "PATCH", f"/v1/people/{ada['id']}", root, json={"disabled": False})

        session = rp()
        authorize, state, verifier, nonce = begin(session)
        _, location = sign_in(browser, authorize, name="Ada", password="second-password-ada")
        tokens = session.fetch_token(meta["token_endpoint"], code=code_from(location)[0], code_verifier=verifier)
        revoked = httpx.post(meta["revocation_endpoint"], trust_env=False, auth=(app_id, app_secret),
                             data={"token": tokens["refresh_token"], "token_type_hint": "refresh_token"})
        check("66", "the app signs Ada out by revoking its refresh token", revoked.status_code == 200,
              revoked.status_code)
        check("67", "a revoked sign-in does not refresh",
              _refresh(meta, app_id, app_secret, tokens["refresh_token"]) == "invalid_grant")

        session = rp()
        authorize, state, verifier, nonce = begin(session)
        _, location = sign_in(browser, authorize, name="Ada", password="second-password-ada")
        earlier = session.fetch_token(meta["token_endpoint"], code=code_from(location)[0], code_verifier=verifier)
        session = rp()
        authorize, state, verifier, nonce = begin(session)
        status, location = sign_in(browser, authorize, name="Ada", password="second-password-ada",
                                   new_password="a-password-ada-chose")
        changed = session.fetch_token(meta["token_endpoint"], code=code_from(location)[0],
                                      code_verifier=verifier) if status in (302, 303) else {}
        check("68", "Ada makes her password her own on the sign-in page, and is signed in",
              bool(changed.get("id_token")), (status, location[:120]))
        check("69", "her sign-in from before the change does not refresh; the new one does",
              _refresh(meta, app_id, app_secret, earlier["refresh_token"]) == "invalid_grant"
              and _refresh(meta, app_id, app_secret, changed.get("refresh_token", "")) == "ok")

        print("\n== a sign-in is not a console session", flush=True)
        check("70", "the owner's console session still works beside it",
              call("agent", "GET", "/v1/node", operator).status_code == 200)
    except Abort as exc:
        print(f"\nABORTED at {exc}", flush=True)
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    if failed:
        for name in ("control", "agent"):
            log = directory / name / "process.log"
            if log.is_file():
                print(f"\n--- {name} log (tail)\n" + log.read_text(encoding="utf-8", errors="replace")[-3000:])
        raise SystemExit(1)


def _message(page: str) -> str:
    found = re.search(r'<p class="error"[^>]*>(.*?)</p>', page, re.S)
    return html.unescape(found.group(1)).strip() if found else ""


def _refresh(meta: dict, client_id: str, secret: str, refresh_token: str) -> str:
    answer = httpx.post(meta["token_endpoint"], trust_env=False, auth=(client_id, secret),
                        data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    return "ok" if answer.status_code == 200 else answer.json().get("error", str(answer.status_code))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-c2-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory)
