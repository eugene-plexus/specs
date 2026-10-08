# Workbench media screens, slice 1: Images — record

**2026-10-08. Built, run and pinned.** Design:
[`workbench-media-screens.md`](../design/workbench-media-screens.md), calls
M1–M9 (Troy took all eleven as recommended the same day). What building
found is §10a there.

| Repo | Commit |
|---|---|
| specs (contract) | `9e6125f` |
| gateway | `e7488dc` |
| workbench (`main`) | `09d2e62` |
| workbench (`dist`) | `eff62e2` |
| agent (catalogue) | `e1ea390` |

## The run of record

`scripts/c3-workbench-acceptance.py --browser --openrouter-live`, from
`agent/.venv`, against the working trees at the commits above. **47 of 47
passed.** Workbench was installed by the registry from the agent's own
catalogue entry, at the pinned `dist` archive `eff62e2`, from the console
on a second machine. This is the real catalogue install, not a custom
entry: the entry declares `localActions: false`.

The media checks use a second inference-driver, the real `openrouter`
provider, with its `baseUrl` set to the fixture. The fixture plays
OpenRouter's image API as P4 measured it:

- **flux** makes one image at a time, in PNG or JPEG, from up to four
  references;
- **mini** makes up to ten, and takes a quality.

Everything goes through Workbench's own API, as its page calls it.

| # | Check | Result |
|---|---|---|
| M1 | The Images screen lists the account's image models with the settings the gateway enforces, and where they run; the chat model is not among them | flux: `maxImages` 1, qualities `[]`, formats png/jpeg, up to 4 references; mini: 10 and four qualities; `locality: external`, provider OpenRouter |
| M2 | An image is made through the gateway, kept, and read back from its own bytes beside the size asked | asked 512x512, kept a 3×2 PNG, served by `images` in 15 ms |
| M3 | A setting the model does not take is refused in the gateway's words, naming the field, and nothing reaches the provider | `n: … makes at most 1 per request. … Nothing was sent.`, `param: n`; the fixture saw no request |
| M4 | An image brought into the bin edits the next one | it reached the provider as an `input_references` data URL |
| M5 | *Send to a chat* makes a copy the chat's model sees | the chat model answered `C3-SAW-IMAGE` |
| M6 | The owner reads Ada's images only while the business allows it, and never deletes them | before: 404 and 403; on: 4 results listed, the file 200, delete 404; off again: 404 |
| M7 | Delete removes the result's file from Workbench's data; the chat keeps its copy | the file was there, then deleted (204), then gone; the chat's copy is unchanged |
| M8 | The gateway records each image under the app's key | 2 `served` rows, both under `app:workbench@c3-node` |
| ML | A real OpenRouter image is made, kept, and its size read from its bytes | flux.2-klein-4b: a 512×512 JPEG, 140,692 bytes |

The earlier checks (1–27 and B1–B10: install, sign-in, chat, search, Stop,
two people, the owner's read-only chats, logs, revocation, uninstall, and
Chrome) all passed unchanged against the new Workbench and gateway.

**Spent:** one flux.2-klein-4b image at 512×512. At $0.014 per output
megapixel, that is about $0.004.

## Unit suites, the Chrome check and sabotage

- **Gateway:** 1,246 passed before the pin. The two new test modules pass:
  `test_image_doors.py` gained 2 tests, and `test_model_locality.py` is
  new.
- **Gateway sabotage: 7 of 7 caught**, using a scratch script in the
  design session's scratchpad.
  - The first pass escaped 2:
    - a slot that mixes a listed model with one whose API checks its own
      fields;
    - a chat model's `image_min_references`.
  - Both are tested now.
- **Workbench:**
  - pytest **217**, with Chrome included (`test_media_browser.py`). In
    Chrome, the check makes an image, closes the tab mid-request, finds it
    kept in a new tab, sends it to a chat, goes Back and deletes it;
  - vitest **173**;
  - ruff, format, mypy and `mypy --platform linux` are clean.
- **Workbench sabotage:** `scripts/check-media-sabotage.py`, 21 cases (3 in
  Chrome), **all caught**, but not in one pass. The first pass caught 18,
  escaped 1, and stopped at its 20th case:
  - **The escape was real.** A graceful restart marks a running request
    interrupted on shutdown (`aclose`), so the boot sweep was never
    exercised. A new test inserts a running row while Workbench is
    stopped, the way a crash leaves one. That case is now caught (1 of 1).
  - **The stop was the instrument's.** Its mutation left a TypeScript
    variable unused, which breaks the build instead of the behaviour.
    Rewritten, the three Chrome cases are caught (3 of 3).
- **The M checks were not sabotaged separately.** Each one reads code
  that the Workbench and gateway passes above did sabotage.

## Not run

- Deploying to Troy's install. His gateway lists no image model, so the
  Images screen there shows the empty state until he adds a provider
  account (`workbench-media-screens.md` §0).
- CI on the pushed commits (checked next session).
