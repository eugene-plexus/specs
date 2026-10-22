"""Row 29's acceptance must detect a lost picture and a false replay claim."""

import importlib.util
from pathlib import Path

import pytest


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
