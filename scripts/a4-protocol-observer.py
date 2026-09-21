"""Transparent local acceptance observer. Records shapes, never keys or images.

For WSL clients talking to a Windows test gateway, bind only the WSL host
interface. Authorization is forwarded unchanged; the real gateway verifies it.
"""

import argparse
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
import uvicorn


def create_app(target, output):
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=target, timeout=660, trust_env=False
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward(path: str, request: Request):
        if path not in {"v1/models", "v1/chat/completions", "v1/messages"}:
            return Response(status_code=404)
        raw = await request.body()
        record = {
            "time": time.time(),
            "path": path,
            "query": request.url.query,
            "authorizationHeader": "authorization" in request.headers,
            "apiKeyHeader": "x-api-key" in request.headers,
            "bytes": len(raw),
        }
        if raw:
            body = json.loads(raw)
            config = body.get("output_config")
            if isinstance(config, dict):
                record["outputConfigKeys"] = sorted(config)
                record["effort"] = (
                    config.get("effort")
                    if config.get("effort") in {"low", "medium", "high", "xhigh", "max"}
                    else "absent-or-other"
                )
            record.update(
                {
                    "keys": sorted(body),
                    "model": body.get("model"),
                    "stream": body.get("stream"),
                    "tools": [
                        t.get("name") or t.get("function", {}).get("name")
                        for t in body.get("tools", [])
                    ],
                }
            )
            messages = []
            for message in body.get("messages", []):
                content = message.get("content")
                item = {
                    "role": message.get("role"),
                    "contentType": type(content).__name__,
                }
                if isinstance(content, list):
                    item["parts"] = [part.get("type") for part in content]
                    item["imageHashes"] = [
                        hashlib.sha256(part["image_url"]["url"].encode()).hexdigest()
                        for part in content
                        if part.get("type") == "image_url"
                    ]
                messages.append(item)
            record["messages"] = messages
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower()
            in {
                "authorization",
                "x-api-key",
                "content-type",
                "accept",
                "anthropic-version",
                "anthropic-beta",
            }
        }
        upstream = await app.state.client.send(
            app.state.client.build_request(
                request.method,
                "/" + path + ("?" + request.url.query if request.url.query else ""),
                content=raw,
                headers=headers,
            ),
            stream=True,
        )
        record["status"] = upstream.status_code
        with output.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")

        async def chunks():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            chunks(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.target, args.output),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
