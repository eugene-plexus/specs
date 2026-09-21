# A4: application workflows and bounded images

Status: implementation and acceptance completed 2026-09-21. Real coding, chat,
image preflight and user-supplied image tasks passed. The
[acceptance record](../acceptance/a4-application-workflows.md) owns those results.

OpenAI chat accepts ordered `text` and `image_url` content parts on user
messages. Text-only part arrays are normalized to text for every other engine.
Scalar strings and nullable assistant tool-call turns retain their behavior.
The shared Message carries the same parts without fetching or rewriting images.
Anthropic Messages continues to reject image/document blocks explicitly; A4's
image application is Open WebUI through OpenAI chat.

Initially images must be inline `data:image/png;base64,...` or
`data:image/jpeg;base64,...`. Remote URLs, local paths, file IDs, other MIME
types and animated images are refused. Limits apply to the whole conversation:
four images, 5 MiB decoded per image, 10 MiB decoded total, 16 million pixels
per image, and 8192 pixels on either side. The HTTP JSON body limit is 16 MiB,
including text and base64 overhead, enforced while reading even without a
Content-Length header. Clients should resize larger attachments themselves.
Image headers, MIME agreement and decodability are checked within these bounds.
`detail` may be absent or `auto`; explicit high/low fidelity is refused because
the supported llama.cpp path does not promise those OpenAI processing modes.

Both gateway and driver validate image requests. Failures name the field and
reason without reflecting payloads. Debug logging and backend-error reporting
must not record image data, including an upstream error that echoes its input.

Image support is a statement about the loaded backend, not the GGUF's name or
the HTTP provider kind. Initially the driver verifies llama.cpp's `/props`
vision modality and the served model identity. Unknown means unsupported.
The driver rechecks before image generation; metadata alone cannot authorize
forwarding after a runtime replacement. Gateway selection and fallback retain
only confirmed image-capable candidates. Stopped on-demand models may wake
before the capability decision; the refreshed loaded backend is authoritative.
The runtime also reports a separate `vision` flag, so an audio projector does
not imply image support. A model/alias advertises image input when at least one
candidate supports it, since image requests filter out the others.

Acceptance uses isolated component state with authentication enabled and
registered application keys. Claude Code uses an isolated configuration and a
disposable repository with bounded tool permissions. Open WebUI uses separate
data/configuration and a user-chosen image. Record exact versions, measured
request shapes (no credentials or image bodies), model artifacts, results and
limitations. Do not change the live install merely to prepare this test.

Primary protocol references:

- [OpenAI image input](https://developers.openai.com/api/docs/guides/images-vision)
- [Open WebUI compatible connections](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/)
- [llama.cpp multimodal support](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp server properties](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [Pillow bounded image inspection](https://pillow.readthedocs.io/en/stable/reference/Image.html)
