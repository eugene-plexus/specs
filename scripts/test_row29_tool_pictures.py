"""Row 29's acceptance must detect a lost picture and a false replay claim."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def acceptance():
    path = Path(__file__).with_name("row29-tool-pictures-acceptance.py")
    spec = importlib.util.spec_from_file_location("row29", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_picture_acceptance_checks_pixels_origin_and_omission_notes():
    row = acceptance()
    body = {
        "messages": [
            {"role": "tool", "content": "It is attached."},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "The image returned by tool call row29-0:",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": row.picture_url(0, False)},
                    },
                ],
            },
        ]
    }
    row.verify(body, [0], large=False, attached=1, omitted=0)
    with pytest.raises(AssertionError):
        row.verify(body, [1], large=False, attached=1, omitted=0)
    with pytest.raises(AssertionError):
        row.verify(body, [0], large=False, attached=1, omitted=1)
    body["messages"][1]["content"][0]["text"] = "A person's picture"
    with pytest.raises(AssertionError):
        row.verify(body, [0], large=False, attached=1, omitted=0)


def test_picture_fixture_is_four_mib_and_vision_has_to_be_explicit():
    row = acceptance()
    assert len(row.picture(0, True)) == 4 * 1024 * 1024
    row.verify(
        {"messages": [{"role": "tool", "content": "The person sees it; you do not."}]},
        [],
        large=False,
        attached=0,
        omitted=0,
        unseen=1,
    )
    with pytest.raises(AssertionError):
        row.verify(
            {"messages": [{"role": "tool", "content": "It is attached."}]},
            [],
            large=False,
            attached=0,
            omitted=0,
            unseen=1,
        )


def test_backend_fixture_reports_capabilities_and_requests_the_next_picture():
    pytest.importorskip(
        "mcp", reason="This fixture check needs the acceptance runtime's MCP SDK"
    )
    from fastapi.testclient import TestClient

    row = acceptance()
    row.mcp_server()  # Tool annotations and output types must be constructible.
    with TestClient(row.fixture_app()) as client:
        models = client.get("/v1/models/user").json()["data"]
        assert models[0]["architecture"]["input_modalities"] == ["text", "image"]
        assert models[1]["architecture"]["input_modalities"] == ["text"]
        body = {
            "model": "vision",
            "messages": [{"role": "user", "content": "row29 count=1 large=1"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "remember", "parameters": {}},
                },
                {
                    "type": "function",
                    "function": {
                        "name": "screenshot",
                        "parameters": {
                            "properties": {
                                "index": {"type": "integer"},
                                "large": {"type": "boolean"},
                            }
                        },
                    },
                },
            ],
        }
        reply = client.post("/v1/chat/completions", json=body).json()["choices"][0]
        assert reply["finish_reason"] == "tool_calls"
        assert reply["message"]["tool_calls"][0]["id"] == "row29-0"
        assert reply["message"]["tool_calls"][0]["function"]["name"] == "screenshot"
        body["messages"].append({"role": "tool", "content": "It is attached."})
        body["stream"] = True
        reply = client.post("/v1/chat/completions", json=body)
        assert '"finish_reason": "stop"' in reply.text
        assert client.get("/seen").json() == body


def test_candidate_keeps_the_workbench_identity_for_job_sites(tmp_path, monkeypatch):
    row = acceptance()
    assert row.APP == "workbench"
    manifest = {
        "id": "workbench",
        "version": "shipped",
        "source": "https://example.test/shipped.tar.gz",
        "localActions": True,
        "signIn": True,
    }
    apps = SimpleNamespace(
        load_catalogue=lambda: [
            SimpleNamespace(model_dump=lambda **kwargs: manifest),
        ]
    )
    monkeypatch.setitem(sys.modules, "eugene_plexus_agent", SimpleNamespace(apps=apps))
    row.workbench_catalogue(tmp_path, "a" * 40)
    (candidate,) = yaml.safe_load((tmp_path / "catalogue.yaml").read_text())
    assert row.APP == candidate["id"] == "workbench"
    assert candidate["signIn"] is True
    assert candidate["localActions"] is False
    assert candidate["version"] == "a" * 40
    assert candidate["source"].endswith("/" + "a" * 40 + ".tar.gz")


def test_site_fixture_pins_its_person_and_signs_held_approvals(tmp_path, monkeypatch):
    pytest.importorskip("regex", reason="The site fixture needs the acceptance runtime")
    pytest.importorskip("mcp", reason="The site fixture needs the acceptance runtime")
    row = acceptance()
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "site-host/src")
    )
    pytest.importorskip(
        "eugene_plexus_site_host",
        reason="This check needs CI's sibling site-host checkout",
    )
    from eugene_plexus_site_host.identity import Enrollment, Identity
    from eugene_plexus_site_host.signing import key_id, parse_key

    me = {"sub": "ada-subject", "name": "Ada"}
    enrolled = Enrollment(
        site="s-" + "a" * 26,
        owner=me["sub"],
        ownerName="ada",
        label="Pictures",
        url="http://127.0.0.1:12345",
        rootKey="unused",
        enrolledAt="2026-10-23T00:00:00+00:00",
    )
    key = row.configure_site(tmp_path, me, enrolled)
    Identity(tmp_path).record(key, enrolled)
    import uvicorn
    from fastapi.testclient import TestClient

    from eugene_plexus_site_host import local_channel
    from eugene_plexus_site_host._generated.models import SiteReport

    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app))
    row.serve_site(tmp_path, 12345)
    app = captured["app"]
    link = app.state.host.links.for_subject(me["sub"])
    assert link.account == local_channel.own_account()
    assert link.keys[0].id == key_id(key.public_key().public_bytes_raw())
    assert parse_key(
        link.keys[0].id,
        "Ed25519",
        row.base64.b64encode(link.keys[0].public).decode(),
        "fixture",
    )
    assert app.state.host.policy.owner == me["sub"]
    assert app.state.host.policy.enabled == {"pictures": True}
    assert app.state.host.policy.tools_for(me["sub"], "pictures") == {
        "screenshot": "allow"
    }
    assert app.state.host.signing_state(me["sub"]) == "unconfirmed"

    async def idle():
        await row.asyncio.Future()

    monkeypatch.setattr(app.state.channel, "run", idle)
    with TestClient(app) as client:
        assert row.approve_site(client, "", tmp_path, me["sub"], key) == [
            "rules.confirm"
        ]
        assert app.state.host.signing_state(me["sub"]) == "signed"
        report = SiteReport.model_validate(app.state.channel.report())
        assert report.site.owner == me["sub"]
        assert report.site.servers[0].enabled
