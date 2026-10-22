# Row 29: pictures in tool results

Lane GW, position 10. Sources: RC3 ("Not done" in
`docs/history/workbench-rich-content-roadmap.md` §RC3), `gateway.yaml` §"Claude
Code's image arrives inside a `tool_result`", `components/common.yaml`
(`MessageContent`, `ImageContentPart`), Workbench `content.py` and `tools.py`,
site-host `host.py`, control `routes/sites.py`.

## 1. What it delivers

- **A model that can see pictures sees the pictures its tools return.** A
  browser tool's screenshot, a chart a tool drew, a photo from a Job Site
  folder: today Workbench shows them to the person and tells the model "The
  person sees it; you do not." With a vision model, the model now gets the
  picture, and the replayed line says so.
- **Pictures up to Workbench's own 5 MiB limit pass a Job Site and a direct
  MCP server.** Today a site's whole answer is capped at 70,000 bytes, so
  only small pictures pass, and a direct MCP server's at 2 MiB.
- **One rule for every door.** An OpenAI chat caller may put a picture in a
  `tool` message, as Anthropic and Responses callers already may in a tool
  result. The gateway carries all three the same way.

## 2. Design

### How a tool's picture reaches the model

The gateway already carries an Anthropic `tool_result` picture and a
Responses `function_call_output` picture on the user message that follows,
with a note in the tool's text ("[The tool returned an image; it is
attached to the next user message.]") and a text part before the picture
("The image returned by tool call {id}:"). Every vision backend takes
pictures on user messages; OpenAI's API refuses them in tool messages, and
no backend Eugene drives was measured taking them there. So:

- **The driver contract does not change.** `GenerateRequest` keeps pictures
  on user messages only. The gateway is the one place that moves them.
- **The OpenAI chat door** accepts `image_url` parts in a `tool` message's
  content array and moves them by the same code (`images.py`), so one
  function serves three doors.
- A later row may pass pictures natively to a backend that takes them in a
  tool result (the Anthropic API), measured first.

### Contract (`components/common.yaml`, `gateway.yaml`)

- `MessageContent`: "Images ride on user messages and on tool results (the
  gateway carries a tool's picture on the next user message). Audio and
  files ride on user messages only." `ImageContentPart` is unchanged (PNG or
  JPEG data URL; the doors re-encode GIF and WebP to PNG as the Anthropic
  door does now).
- `ChatCompletionMessage.content` on a tool message: "the result, as a string
  or an array of text and image parts".
- `inference-driver.yaml`: one sentence on `Message.toolCallId`: tool
  messages carry text; the gateway moves pictures.
- No new fields, so no consumer regenerates for a schema. Workbench and the
  gateway regenerate for the descriptions only if their codegen reads
  them; measure by regenerating.

### Limits, and pictures over them

The gateway's image limits (`maxImagesPerRequest`, 12 by default; 5 MiB a
picture; 10 MiB a request) count tool pictures too. Over a limit, **the
gateway keeps the newest tool pictures** and replaces each older one with a
note in its tool message: "[A picture this tool returned is not attached:
this request holds at most 12 pictures.]". A person's own pictures are
never dropped; if they alone are over a limit, the 400 stands, as today.
This holds for all three doors: an agent's loop of screenshots keeps
working instead of failing at the thirteenth. (Default built; the model is
told exactly what it did not get.)

A model with no confirmed image input still gets the 400 it gets today
("No ready backend serving this model confirms image input…"). Workbench
never sends it one (below).

### Workbench

- `tools.transcript` replays a tool call's kept pictures as `image_url`
  parts in its tool message **only when the chat's model reports
  `imageInput: true`** (`/api/models`, from `x_eugene_plexus.image_input`).
  Otherwise nothing changes.
- At most the **8 newest** tool pictures, and at most **10 MiB** of them
  (the gateway's default request limit), in one request, read from the
  person's store at send time; older ones keep today's line.
- The replayed line says what happened to each picture:
  - attached: `[The tool returned a picture, "chart.png" (image/png, 120 KB). It is attached.]`
  - not attached: today's line, "The person sees it; you do not."
- Only PNG, JPEG and WebP pictures are kept as pictures (RC3); the others
  stay files and are never attached.
- A picture that was not kept (over a limit) stays a line, as now.

### Caps on the way in

| Where | Today | After |
|---|---|---|
| site-host `MAX_ANSWER` (a site's whole JSON-RPC answer) | 70,000 bytes | 8 MiB for a tool call's answer; other answers keep 70,000 |
| control `MAX_RESULT` (`/v1/sites/operations/{id}/result`) | 70,000 bytes | 8 MiB; results are held in memory (`sites.py` broker futures), never in the log |
| Workbench `node_folders.MAX_ANSWER` | 100,000 bytes | 8 MiB for a tool call |
| Workbench `tools.MAX_RESPONSE` (direct MCP, not streamed) | 2 MiB | 8 MiB |
| Workbench `max_sse_event_size` (direct MCP, streamed) | 1 MiB | 8 MiB |

8 MiB holds one 5 MiB picture in base64 with its JSON. Workbench's own
limits (5 MiB a picture, 8 files and 20 MiB a call) still decide what is
kept. Control holds at most one result per running job; the cap bounds
memory per job, and the existing per-site job limit bounds the rest.
`control.yaml` and `site-host.yaml` say the new numbers.

### Failures

- Over 8 MiB at a site: "The answer is larger than 8 MiB. Ask for less."
  (site-host's words, shown on the call).
- A picture over the gateway's limits: the note above, in the tool message.
- A model without image input: no picture is sent; the line says the person
  sees it.

## 3. Repositories and codegen

specs, gateway, workbench, site-host and control. `inference-driver` gets
no code change (its contract text only). Regenerate the gateway and
Workbench and diff; expect description-only changes or none.

## 4. Tests that fail before

- gateway `tests/test_image_doors.py::test_a_tool_message_picture_moves_to_the_next_user_message`
  (today: 400 "images are supported only on user messages").
- gateway `tests/test_image_doors.py::test_older_tool_pictures_over_the_limit_become_notes`,
  one case per door (chat, Anthropic, Responses), and
  `test_a_persons_pictures_are_never_dropped`.
- workbench `tests/test_tool_content.py::test_a_vision_model_gets_the_tools_picture`
  and `test_a_text_model_gets_the_line_only`, and
  `test_only_the_8_newest_pictures_are_attached`.
- site-host `tests/test_host.py::test_a_tool_answer_up_to_8_mib_passes`;
  control `tests/test_sites.py::test_a_result_up_to_8_mib_is_accepted`.
- workbench `tests/test_tools.py::test_a_direct_mcp_picture_of_4_mib_is_kept`.

## 5. Acceptance (CI, Linux and Windows, about 4 minutes)

`specs/scripts/row29-tool-pictures-acceptance.py` on row 2's harness: a
root, an agent, the gateway, Workbench, a Job Site, a fixture MCP server
that returns a 4 MiB PNG, and the fixture backend reporting image input.
1. A direct MCP call and a Job Site call each return the picture; Workbench
   keeps it and the next model request carries it on a user message after
   the tool's note (read from the fixture backend's received request).
2. The same with the fixture backend reporting no image input: no picture
   in the request; the line says the person sees it.
3. Fourteen tool pictures in one chat: the request holds the newest 8 from
   Workbench; with `maxImagesPerRequest: 4`, the gateway attaches 4 and
   notes the rest.

## 6. Do not change

- Workbench `ToolContent.tsx` (row 31's branches change it; this row needs
  no page change) and the store migrations (row 70c).
- gateway `routing.py` and the queue files row 11 will change.

## 7. Size and risks

M, about 2 days, cross. Risks:
- **Bandwidth and memory.** Workbench sends at most 10 MiB of tool
  pictures (about 14 MB of base64) in one request, and reads them from
  disk per request.
- **A tool can now put a picture in front of the model.** A picture can
  carry instructions as text in its pixels, as a web page can. This is the
  same exposure a person's upload has; the reviewer should check that
  nothing marks a tool's picture as the person's.
- Raising the site cap lets a site send 8 MiB per job; the per-site job
  limit bounds it.
