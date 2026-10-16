"""Disposable upstream provider for U4 acceptance, never a deployable identity service."""

from __future__ import annotations

import html
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import jwt
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from eugene_plexus_control import oidc

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
issuer = config["issuer"] + "/"
key, jwk = oidc.new_signing_key()
codes = {}
app = FastAPI()


@app.get("/healthz")
async def health():
    return {"ok": True}


@app.get("/.well-known/openid-configuration")
async def discovery():
    return {
        "issuer": issuer,
        "authorization_endpoint": issuer + "authorize",
        "token_endpoint": issuer + "token",
        "jwks_uri": issuer + "keys",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
    }


@app.get("/keys")
async def keys():
    return {"keys": [jwk]}


@app.get("/authorize")
async def authorize(request: Request):
    fields = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in request.query_params.items()
    )
    return HTMLResponse(
        "<!doctype html><html lang='en'><title>Local acceptance provider</title>"
        "<h1>Local acceptance provider</h1><form method='post'>"
        + fields
        + "<button>Sign in as Ada</button></form></html>"
    )


@app.post("/authorize")
async def approve(request: Request):
    form = dict(await request.form())
    assert form["client_id"] == "eugene-acceptance"
    assert form["code_challenge_method"] == "S256"
    assert urlsplit(form["redirect_uri"]).hostname == "127.0.0.1"
    code = secrets.token_urlsafe(32)
    codes[code] = {**form, "expires": time.time() + 60}
    return RedirectResponse(
        form["redirect_uri"]
        + "?"
        + urlencode(
            {
                "code": code,
                "state": form["state"],
                "iss": issuer,
            }
        ),
        status_code=303,
    )


@app.post("/token")
async def token(request: Request):
    form = await request.form()
    given = codes.pop(str(form.get("code")), None)
    if (
        not given
        or given["expires"] < time.time()
        or form.get("client_secret") != config["secret"]
        or form.get("client_id") != given["client_id"]
        or form.get("redirect_uri") != given["redirect_uri"]
        or not oidc.pkce_matches(
            str(form.get("code_verifier")), given["code_challenge"]
        )
    ):
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    proof = jwt.encode(
        {
            "iss": issuer,
            "sub": "external-ada",
            "aud": given["client_id"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": given["nonce"],
            "email": "ada@example.test",
            "email_verified": True,
        },
        key,
        algorithm="RS256",
        headers={"kid": jwk["kid"]},
    )
    return {"id_token": proof, "token_type": "Bearer", "access_token": "unused"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=urlsplit(issuer).port,
        log_level="error",
        access_log=False,
    )
