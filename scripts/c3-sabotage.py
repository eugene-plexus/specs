"""Sabotage pass for C3 (Workbench, version 1).

Each sabotage puts one defect back into a working tree, runs the tests
that guard it, and requires them to FAIL. Restores are from byte copies
taken before the first edit, never `git checkout --`
(feedback: sabotage-runs-restore-from-a-copy), and the pass opens with a
baseline that must pass.

The first pass escaped one and hung on another. Reusing a sign-in was
refused anyway, by Eugene's single-use code and by the binding cookie
already being gone, so the test now re-presents the binding and requires
Workbench to refuse before Eugene is asked. A refresh that kept a revoked
session left a test's event stream open forever; that test is bounded
now, and a run that times out counts as caught.

The second pass escaped two, each a missing check: with `ownerReadsChats`
on, nothing asked whether another *member* could open a person's chat; and
a streamed piece the page already had was tested only as the last one, so
cutting off what followed it went unseen. Both are tests now.

The third pass added the live install's finding (2026-10-01): installing
from another machine's console sent the console's token past its
audience to the root, and the root's 401 signed the operator out. Fourteen
sabotages guard the fix at the agent and the root, the two
over-corrections among them; all 60 caught on the first run.

The whole flow, with real processes and the system Chrome, is
`c3-workbench-acceptance.py`; this pass is what makes each guard in
Workbench, the gateway and the agent answer for itself.

    python scripts/c3-sabotage.py [words in a label, to run only those]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKBENCH = ROOT / "workbench"
WEB = WORKBENCH / "web"
GATEWAY = ROOT / "gateway"
AGENT = ROOT / "agent"
W = WORKBENCH / "src/eugene_plexus_workbench"
G = GATEWAY / "src/eugene_plexus_gateway"
SESSIONS = W / "sessions.py"
SIGNIN = W / "signin.py"
API = W / "api.py"
CONFIG = W / "config.py"
ANSWERS = W / "answers.py"
STORE = W / "store.py"
HUB = W / "hub.py"
CONVERSATION = W / "conversation.py"
FILES = W / "files.py"
WEBPY = W / "web.py"
MARKDOWN = WEB / "src/components/Markdown.tsx"
COMPOSER = WEB / "src/components/Composer.tsx"
USECHAT = WEB / "src/lib/useChat.ts"
SESSION_TS = WEB / "src/lib/session.ts"
WORDS = WEB / "src/lib/words.ts"
MESSAGE = WEB / "src/components/MessageView.tsx"
ROUTES = G / "routes/inference.py"
ROUTING = G / "routing.py"
CATALOGUE = AGENT / "src/eugene_plexus_agent/apps_catalogue.yaml"
CONTROL = ROOT / "control"
C = CONTROL / "src/eugene_plexus_control"
ACTING = C / "dependencies.py"
ROOT_KEYS = C / "routes/client_keys.py"
ROOT_PEOPLE = C / "routes/people.py"
REGISTRY = AGENT / "src/eugene_plexus_agent/client_key_registry.py"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


def pytest(repo: Path, *tests: str):
    return lambda: [str(python(repo)), "-m", "pytest", "-q", "-p", "no:warnings", "-p",
                    "no:cacheprovider", *tests]


RUNNERS = {
    WORKBENCH: pytest(WORKBENCH),
    WEB: lambda: ["npx", "vitest", "run"],
    GATEWAY: pytest(GATEWAY, "tests/test_server_tools.py", "tests/test_admission.py",
                    "tests/test_safe_mode.py"),
    AGENT: pytest(AGENT, "tests/test_apps.py", "tests/test_acting_for_operator.py"),
    CONTROL: pytest(CONTROL, "tests/test_acting_node.py", "tests/test_client_keys.py",
                    "tests/test_oidc.py"),
}

SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    # --- a session needs both halves (W3) ----------------------------------
    (
        "a cookie alone opens a session",
        WORKBENCH, SESSIONS,
        "        if not cookie or not secret:\n"
        "            raise SignedOut(\"none\", \"Sign in with Eugene to use Workbench.\")\n"
        "        row = await self._store.session(digest(cookie))\n"
        "        if row is None or not hmac.compare_digest(row.secret_hash, digest(secret)):\n",
        "        if not cookie:\n"
        "            raise SignedOut(\"none\", \"Sign in with Eugene to use Workbench.\")\n"
        "        row = await self._store.session(digest(cookie))\n"
        "        if row is None:\n",
    ),
    (
        "a changing call from another origin is accepted",
        WORKBENCH, SESSIONS,
        '        if request.method in _UNSAFE and request.headers.get("origin") != own_origin(request):\n',
        "        if False:\n",
    ),
    # --- signing in (W2) ---------------------------------------------------
    (
        "a sign-in is finished in a browser that did not start it",
        WORKBENCH, API,
        "    if pending is None or not secrets.compare_digest(\n"
        '        request.cookies.get(SIGNIN_COOKIE, ""), pending.binding\n'
        "    ):\n",
        "    if pending is None:\n",
    ),
    (
        "a sign-in's state is good twice",
        WORKBENCH, SIGNIN,
        "        return self._pending.pop(state, None)\n",
        "        return self._pending.get(state)\n",
    ),
    (
        "an ID token for another app is accepted",
        WORKBENCH, SIGNIN,
        '                aud={"essential": True, "value": self.client_id or ""},\n',
        "",
    ),
    (
        "an ID token for another sign-in is accepted",
        WORKBENCH, SIGNIN,
        '            if nonce is not None and claims.get("nonce") != nonce:\n',
        "            if False:\n",
    ),
    (
        "an access token passes as an ID token",
        WORKBENCH, SIGNIN,
        '            if decoded.header.get("typ", "JWT") != "JWT":\n',
        "            if False:\n",
    ),
    (
        "a refused refresh keeps the session",
        WORKBENCH, SESSIONS,
        "            except SignInRefused:\n"
        "                await self._store.delete_session(row.id_hash)\n"
        '                raise SignedOut("revoked", _REVOKED) from None\n',
        "            except SignInRefused:\n                return\n",
    ),
    (
        "Eugene being unreachable signs people out",
        WORKBENCH, SESSIONS,
        "                raise HTTPException(\n"
        "                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,\n",
        "                await self._store.delete_session(row.id_hash)\n"
        "                raise HTTPException(\n"
        "                    status_code=status.HTTP_401_UNAUTHORIZED,\n",
    ),
    # --- chats are their owner's (W4) --------------------------------------
    (
        "a chat that is not yours can be changed",
        WORKBENCH, API,
        "    if chat is None or chat.owner != person.sub:\n",
        "    if chat is None:\n",
    ),
    (
        "the owner reads people's chats with the setting off",
        WORKBENCH, API,
        "    if chat is not None and person.is_owner and await config.owner_reads_chats(store):\n",
        "    if chat is not None and person.is_owner:\n",
    ),
    (
        "a member reads people's chats when the setting is on",
        WORKBENCH, API,
        "    if chat is not None and person.is_owner and await config.owner_reads_chats(store):\n",
        "    if chat is not None and await config.owner_reads_chats(store):\n",
    ),
    (
        "a member sees the people list",
        WORKBENCH, API,
        "    if not person.is_owner:\n        raise _problem(status.HTTP_403_FORBIDDEN, \"Only the owner",
        "    if False:\n        raise _problem(status.HTTP_403_FORBIDDEN, \"Only the owner",
    ),
    (
        "a file in another person's chat can be downloaded",
        WORKBENCH, API,
        "    await _readable_chat(request, person, record.chat_id)\n",
        "",
    ),
    (
        "the settings open without the agent's admin token",
        WORKBENCH, CONFIG,
        '    if not expected or not hmac.compare_digest(given, f"Bearer {expected}"):\n',
        "    if False:\n",
    ),
    # --- answers are the server's (W1) -------------------------------------
    (
        "an answer stops when its last tab closes",
        WORKBENCH, API,
        "        finally:\n            watch.close()\n",
        "        finally:\n            watch.close()\n            await answers.stop(chat.id)\n",
    ),
    (
        "Stop does not stop",
        WORKBENCH, ANSWERS,
        "        running.task.cancel()\n        with contextlib.suppress(asyncio.CancelledError, Exception):\n",
        "        with contextlib.suppress(asyncio.CancelledError, Exception):\n",
    ),
    (
        "a restart leaves an answer running forever",
        WORKBENCH, STORE,
        "                \"WHERE status = 'running'\",\n",
        "                \"WHERE status = 'never'\",\n",
    ),
    (
        "a shutdown calls an answer stopped",
        WORKBENCH, ANSWERS,
        '            m.status = "interrupted" if running.shutting_down else "stopped"\n',
        '            m.status = "stopped"\n',
    ),
    (
        "a piece of an answer carries no offset",
        WORKBENCH, ANSWERS,
        '            event["contentAt"] = _js_length(m.content)\n',
        "",
    ),
    (
        "an offset is counted in Python's code points",
        WORKBENCH, ANSWERS,
        '    return len(text.encode("utf-16-le")) // 2\n',
        "    return len(text)\n",
    ),
    (
        "a stream that stops without its end is a finished answer",
        WORKBENCH, HUB,
        '        raise HubError("The answer stopped part-way: the gateway closed the stream.", kind="stream")\n',
        "        return\n",
    ),
    # --- the hub (W6, W11) --------------------------------------------------
    (
        "the search switch asks for nothing",
        WORKBENCH, CONVERSATION,
        '        body["web_search_options"] = {}\n',
        "        pass\n",
    ),
    (
        "a revoked key is reported as any other refusal",
        WORKBENCH, HUB,
        "    if status in (401, 403):\n",
        "    if False:\n",
    ),
    (
        "Workbench's gateway client follows the environment's proxy",
        WORKBENCH, HUB,
        "httpx.Timeout(30.0, read=900.0), trust_env=False)",
        "httpx.Timeout(30.0, read=900.0))",
    ),
    # --- attachments (W7) ---------------------------------------------------
    (
        "a file whose bytes are not what its name says is kept",
        WORKBENCH, FILES,
        "    if declared and declared in KINDS and declared != sniffed:\n        return None\n",
        "",
    ),
    (
        "a file over the gateway's limit is taken",
        WORKBENCH, API,
        "    if len(data) > limit:\n",
        "    if False:\n",
    ),
    (
        "a chat's attachments are not added up",
        WORKBENCH, API,
        "    if sum(r.size for r in existing) + len(data) > files.CHAT_LIMIT:\n",
        "    if False:\n",
    ),
    # --- the page's own server (W5, W9) -------------------------------------
    (
        "the policy lets inline script run",
        WORKBENCH, WEBPY,
        "        \"script-src 'self'\",\n",
        "        \"script-src 'self' 'unsafe-inline'\",\n",
    ),
    (
        "the policy lets images come from anywhere",
        WORKBENCH, WEBPY,
        "        \"img-src 'self' data: blob:\",\n",
        "        \"img-src *\",\n",
    ),
    (
        "a path that climbs out of the build is served",
        WORKBENCH, WEBPY,
        "candidate.is_file() and candidate.is_relative_to(built)",
        "candidate.is_file()",
    ),
    # --- the page (W5, W6, W7) ----------------------------------------------
    (
        "an image an answer names is fetched",
        WEB, MARKDOWN,
        '    if (!href) return <span className="text-muted">[{label}]</span>;\n',
        '    if (href) return <img src={href} alt={alt ?? ""} />;\n'
        '    if (!href) return <span className="text-muted">[{label}]</span>;\n',
    ),
    (
        "a javascript: address is a link",
        WEB, MARKDOWN,
        "const SAFE = /^(https?:|mailto:)/i;\n",
        "const SAFE = /^/;\n",
    ),
    (
        "a piece the page already has is added again",
        WEB, USECHAT,
        "  if (at + piece.length <= text.length) return { text, gap: false };\n",
        "",
    ),
    (
        "a gap is papered over",
        WEB, USECHAT,
        "  return { text, gap: true };\n",
        "  return { text: text + piece, gap: false };\n",
    ),
    (
        "the switch is on though the install cannot search",
        WEB, COMPOSER,
        '  if (!models.webSearch.available) return models.webSearch.reason ?? "Search cannot run here.";\n',
        "",
    ),
    (
        "an image goes to a model that does not take images",
        WEB, COMPOSER,
        '    if (kind === "image" && !model.imageInput) missing.add("images");\n',
        "",
    ),
    (
        "the secret stays in the address bar",
        WEB, SESSION_TS,
        '  window.history.replaceState(null, "", window.location.pathname + window.location.search);\n',
        "",
    ),
    (
        "an answer that searched and cites nothing looks unsearched",
        WEB, MESSAGE,
        "      {(message.sources.length > 0 || message.searches > 0) && (\n",
        "      {message.sources.length > 0 && (\n",
    ),
    (
        "a workshop name is on screen in version 1",
        WEB, WORDS,
        'export const SEARCH_LABEL = "Search the web";\n',
        'export const SEARCH_LABEL = "Toolbox: Search the web";\n',
    ),
    # --- the gateway (section 3) ---------------------------------------------
    (
        "the model list says a search can run whatever the key and the install",
        GATEWAY, ROUTES,
        "    reason = server_tools.why_not(table, context)\n",
        "    reason = None\n",
    ),
    (
        "a model that neither searches nor calls tools reads as reachable",
        GATEWAY, ROUTING,
        "    for b in backends:\n        caps = b.caps\n        if caps is None:\n            continue\n"
        '        if "webSearchOptions" in set(caps.supportedSettings or []) or caps.toolCalling is True:\n'
        "            return True\n    return False\n",
        "    return bool(backends)\n",
    ),
    (
        "a model that searches itself reads as unreachable",
        GATEWAY, ROUTING,
        '        if "webSearchOptions" in set(caps.supportedSettings or []) or caps.toolCalling is True:\n',
        "        if caps.toolCalling is True:\n",
    ),
    (
        "safe mode says it is starting up",
        GATEWAY, ROUTES,
        '        reason = "this gateway is in safe mode, which routes nothing and runs no search"\n',
        "        pass\n",
    ),
    # --- the catalogue -------------------------------------------------------
    (
        "Workbench's catalogue entry follows a branch, not its commit",
        AGENT, CATALOGUE,
        "  version: 736e1ceb85a2dfd71f67f0b708f54f03b92a218a\n",
        "  version: dist\n",
    ),
    (
        "Workbench is said to run what a model chooses",
        AGENT, CATALOGUE,
        "  localActions: false\n",
        "  localActions: true\n",
    ),
    # --- installing from another machine's console (2026-10-01) ------------
    # The live install's loop: the worker sent the console's token, addressed
    # to the worker alone, on to the root, and the root's 401 signed the
    # operator out. The worker now acts for the operator; the root takes that
    # only for the worker's own apps.
    (
        "the worker sends the console's token on to the root as it is",
        AGENT, REGISTRY,
        "        return {\"Authorization\": own, SUBJECT_TOKEN_HEADER: token}\n",
        "        return {\"Authorization\": authorization}\n",
    ),
    (
        "every caller rides as a subject, a session addressed to the root included",
        AGENT, REGISTRY,
        "                    recipient=tokens.RECIPIENT_CONTROL,\n"
        "                    classes=(tokens.TYP_SESSION,),\n",
        "                    recipient=\"nowhere\",\n"
        "                    classes=(tokens.TYP_SESSION,),\n",
    ),
    (
        "a refusal at the root reaches the console as a 401",
        AGENT, REGISTRY,
        "            if exc.response.status_code == 401 and authorization is not None:\n",
        "            if False:\n",
    ),
    (
        "every 401 from the root becomes a 502, a revoked client key's included",
        AGENT, REGISTRY,
        "            if exc.response.status_code == 401 and authorization is not None:\n",
        "            if exc.response.status_code == 401:\n",
    ),
    (
        "the root ignores the subject",
        CONTROL, ACTING,
        "    subject = request.headers.get(SUBJECT_TOKEN_HEADER)\n",
        "    subject = None\n",
    ),
    (
        "the subject may be addressed to any machine, not the one presenting it",
        CONTROL, ACTING,
        "            recipient=tokens.node_recipient(node),\n",
        "            recipient=__import__(\"jwt\").decode(subject.strip(), "
        "options={\"verify_signature\": False})[\"aud\"][0],\n",
    ),
    (
        "the subject may be a token the machine minted for itself",
        CONTROL, ACTING,
        "            recipient=tokens.node_recipient(node),\n"
        "            classes=(tokens.TYP_SESSION,),\n",
        "            recipient=tokens.node_recipient(node),\n"
        "            classes=(tokens.TYP_SESSION, tokens.TYP_SERVICE),\n",
    ),
    (
        "any service token may act, not only an agent speaking for itself",
        CONTROL, ACTING,
        "    actor = require_node_actor(request, creds)\n",
        "    actor = verify_bearer(request, _bearer(request, creds), classes=(tokens.TYP_SERVICE,))\n",
    ),
    (
        "a machine acting for the operator may name anything",
        CONTROL, ACTING,
        "        return self.node is None or named_for_node(name, self.node)\n",
        "        return True\n",
    ),
    (
        "a name that only begins with the machine's own counts as its own",
        CONTROL, ACTING,
        "re.fullmatch(rf\"app:[^@\\s]+@{re.escape(node)}\", str(name))",
        "re.match(rf\"app:[^@\\s]+@{re.escape(node)}\", str(name))",
    ),
    (
        "a machine acting for the operator may revoke any key",
        CONTROL, ROOT_KEYS,
        "    if not op.may_name(record.get(\"name\")):\n",
        "    if False:\n",
    ),
    (
        "a machine acting for the operator may register sign-in for anything",
        CONTROL, ROOT_PEOPLE,
        "    if not op.may_name(body.owner):\n",
        "    if False:\n",
    ),
    (
        "a machine acting for the operator may remove any app's sign-in",
        CONTROL, ROOT_PEOPLE,
        "    if not op.may_name(record.get(\"owner\")):\n",
        "    if False:\n",
    ),
    (
        "the pair also lists every key",
        CONTROL, ROOT_KEYS,
        "    dependencies=[Depends(require_operator)],\n"
        ")\n"
        "async def list_keys(request: Request) -> ClientKeyList:\n",
        ")\n"
        "async def list_keys(request: Request, op: ActingOperator) -> ClientKeyList:\n",
    ),
]


#: A sabotage that makes a guard hang has been caught too: the guard cannot
#: pass. Found by the first pass, where a refresh that kept a revoked
#: session left a test's event stream open and the run waited 20 minutes.
TIMEOUT = 300


def run(repo: Path) -> int:
    try:
        result = subprocess.run(RUNNERS[repo](), cwd=repo, capture_output=True, text=True,
                                timeout=TIMEOUT, encoding="utf-8", errors="replace",
                                shell=sys.platform == "win32" and repo == WEB)
    except subprocess.TimeoutExpired:
        print(f"    {repo.name}: did not finish in {TIMEOUT} s", flush=True)
        return 124
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
