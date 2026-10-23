"""Row 58: real google-genai SDK and measured CLI wire through signed fixture processes.

Uses gemini-acceptance's signed install and provider fixture, and row 2's
agent entry-point harness. No live provider or hardware run. All processes
use ephemeral ports, cleared Eugene variables and isolated state. Run in CI's
cross-component environment, with google-genai installed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent


def load_provider():
    spec = importlib.util.spec_from_file_location("row58_provider_acceptance", HERE / "gemini-acceptance.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(directory, url, call, operator, token, seen):
    from google import genai
    from google.genai import types

    provider = load_provider()
    model = f"gem/{provider.CHAT}"
    headers = {"x-goog-api-key": token}
    changed = call("gateway", "PATCH", "/v1/config", operator, json={
        "modelSlots": [{"model": "role:chat", "targets": [model]}],
        "geminiModelNames": [{"model": "sdk-alias", "targets": [model]}],
    })
    assert changed.status_code == 200 and not changed.json()["rejected"], changed.text
    with httpx.Client(base_url=url("gateway"), trust_env=False, timeout=30) as raw:
        for version in ("v1beta", "v1"):
            with genai.Client(api_key=token, http_options=types.HttpOptions(
                base_url=url("gateway"), api_version=version, timeout=30000,
                client_args={"trust_env": False},
            )) as sdk:
                reply = sdk.models.generate_content(model="sdk-alias", contents="ping")
                assert reply.text == "pong" and reply.model_version == model, reply
                assert reply.usage_metadata.prompt_token_count == provider.USAGE["promptTokenCount"]
                frames = list(sdk.models.generate_content_stream(model=model, contents="ping"))
                assert "".join(frame.text or "" for frame in frames) == "pong", frames
                assert frames[-1].model_version == model

                tools = [{"function_declarations": [{"name": "get_weather", "parameters_json_schema": {
                    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"],
                }}]}]
                config = {"tools": tools, "automatic_function_calling": {"disable": True}}
                first = sdk.models.generate_content(model=model, contents="Weather?", config=config)
                assert first.function_calls and first.function_calls[0].name == "get_weather", first
                second = sdk.models.generate_content(model=model, contents=[
                    types.Content(role="user", parts=[types.Part(text="Weather?")]),
                    first.candidates[0].content,
                    types.Content(role="user", parts=[types.Part.from_function_response(
                        name="get_weather", response={"temperature": 21},
                    )]),
                ], config=config)
                assert "sunny" in second.text, second
                structured = sdk.models.generate_content(model=model, contents="JSON please", config={
                    "response_mime_type": "application/json",
                    "response_json_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
                })
                assert json.loads(structured.text)["answer"]
                assert sdk.models.count_tokens(model=model, contents="ping").total_tokens == 23
                listed = list(sdk.models.list(config={"page_size": 2}))
                assert any(m.name == f"models/{model}" for m in listed), listed
                assert sdk.models.get(model=model).name == f"models/{model}"
            print(f"PASS {version}: SDK chat, streaming, tool round trip, structured output, counting and paged discovery", flush=True)

        # The two request shapes retained by gemini-door.md section 2. Private
        # system text and tool schemas were not retained by that measurement;
        # the fixture contains its measured fields and a representative tool.
        recorded = json.loads((HERE / "fixtures" / "row58-gemini-cli.json").read_text(encoding="utf-8"))
        before = len(seen(provider.CHAT))
        routing = raw.post(recorded[0]["path"], headers=headers, json=recorded[0]["body"])
        assert routing.status_code == 200, routing.text
        routed = json.loads(routing.json()["candidates"][0]["content"]["parts"][0]["text"])
        assert isinstance(routed["complexity_score"], int) and routed["complexity_reasoning"]
        assert len(seen(provider.CHAT)) == before + 1, "the CLI routing JSON must parse on its first attempt"
        streamed = raw.post(recorded[1]["path"], headers=headers, json=recorded[1]["body"])
        assert streamed.status_code == 200 and streamed.headers["content-type"].startswith("text/event-stream"), streamed.text
        data = [json.loads(line[6:]) for line in streamed.text.splitlines() if line.startswith("data: ")]
        assert data[-1]["candidates"][0]["finishReason"] == "STOP", data
        assert data[-1]["modelVersion"] == model
        offered = {f["name"] for t in recorded[1]["body"]["tools"] for f in t["functionDeclarations"]}
        returned = [p["functionCall"]["name"] for frame in data for c in frame.get("candidates", [])
                    for p in c.get("content", {}).get("parts", []) if "functionCall" in p]
        assert returned and set(returned) <= offered, returned
        print("PASS CLI routing JSON parses first try; streamed turn uses the Chat role and Gemini SSE", flush=True)

        counted = raw.post(f"/v1beta/models/{model}:countTokens", headers=headers, json={
            "generateContentRequest": {"model": f"models/{model}", "contents": [{"parts": [{"text": "ping"}]}],
                                       "systemInstruction": {"parts": [{"text": "Be brief"}]}}
        })
        assert counted.json() == {"totalTokens": 23}, counted.text
        assert seen(provider.CHAT)[-1]["body"]["generateContentRequest"]["systemInstruction"]
        embeddings = raw.post("/v1/embeddings", headers={"authorization": f"Bearer {token}"}, json={
            "model": f"gem/{provider.EMBED}", "input": ["one", "two"], "dimensions": 2,
        })
        assert embeddings.status_code == 200, embeddings.text
        assert len(embeddings.json()["data"][0]["embedding"]) == 2
        assert "dimensions" not in embeddings.headers.get("x-eugene-plexus-ignored-settings", "")

        for fmt, mime in (("mp3", "audio/mpeg"), ("opus", "audio/ogg")):
            import av
            import io

            speech = raw.post("/v1/audio/speech", headers={"authorization": f"Bearer {token}"}, json={
                "model": f"gem/{provider.TTS}", "input": "Hello", "voice": "Kore", "response_format": fmt,
            })
            assert speech.status_code == 200 and speech.headers["content-type"] == mime, speech.text
            with av.open(io.BytesIO(speech.content)) as audio:
                assert list(audio.decode(audio=0)), f"{fmt} did not decode"
        print("PASS native full-prompt count, applied dimensions, decodable mp3 and opus", flush=True)

        keyed = raw.post(f"/v1beta/models/{model}:generateContent", params={"key": token}, json={"contents": [{"parts": [{"text": "ping"}]}]})
        assert keyed.status_code == 200, keyed.text
        invalid = "row58-query-key-must-not-be-logged"
        refused = raw.post(f"/v1beta/models/{model}:generateContent", params={"key": invalid}, json={"contents": [{"parts": [{"text": "ping"}]}]})
        assert refused.status_code == 401 and refused.json()["error"]["status"] == "UNAUTHENTICATED", refused.text
        metrics = raw.get("/v1/metrics/requests", headers={"authorization": f"Bearer {operator}"})
        assert metrics.status_code == 200 and token not in metrics.text and invalid not in metrics.text
        log = (directory / "gateway" / "process.log").read_text(encoding="utf-8", errors="replace")
        assert "generateContent" in log, "access log check did not observe requests"
        assert token not in log and invalid not in log and "?key=" not in log
        print("PASS query keys checked and absent from access logs and metrics", flush=True)


if __name__ == "__main__":
    root = Path(os.environ.get("EP_ROW58_TEMP", Path.cwd() / ".codex-tmp"))
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="row58-gemini-door-", dir=root))
    print(f"Isolated state and logs: {directory}", flush=True)
    load_provider().exercise(directory, live=False, live_video=False, door_check=check)
