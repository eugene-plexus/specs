# Workbench media screens, slice 3: Video, as a work order — record

**2026-10-08. Built, run and pinned.** Design:
[`workbench-media-screens.md`](../design/workbench-media-screens.md) §5,
§6.4 and call M11. What building found is §10c there. Slices 1 and 2 are
[`workbench-media-images-run.md`](workbench-media-images-run.md) and
[`workbench-media-speech-run.md`](workbench-media-speech-run.md).

| Repo | Commit |
|---|---|
| specs (contract) | `eb9a1f2` |
| inference-driver | `2b1850b` |
| gateway | `6780d6c` (listing, cost), `d9e2226` (a test) |
| workbench (`main`) | `91c8b37` |
| workbench (`dist`) | `d1db51c` |
| agent (catalogue) | `6628f10` |

The UI's generated types change with the contract, but the console uses
neither field, so the UI is not re-pinned.

## The run of record

`scripts/c3-workbench-acceptance.py --browser --openrouter-live`, from
`agent/.venv`, against the working trees at the commits above. **65 of 65
passed.** Workbench was installed by the registry from the agent's own
catalogue entry, at the pinned `dist` archive `d1db51c` (agent-account
isolation), from the console on a second machine.

The video checks use the same fixture account as the image and audio
checks: the real `openrouter` provider, its `baseUrl` the fixture. The
fixture plays OpenRouter's video API as P5 measured it:

- `GET /videos/models` lists `acme/grok-video` with grok's lengths (1–15 s),
  four of its sizes, a first frame and its `pricing_skus`, as OpenRouter
  listed them on 2026-10-08;
- a job is accepted `pending` (the gateway says `queued`, progress 0,
  `prompt: null`), stays so for 7 s, then is `completed` (progress 100)
  with `usage.cost` 0.05; `[long]` in a prompt holds it 20 s;
- the content is a real 1 s H.264 clip, 160×90, so Chrome plays it and
  what came back differs from the 854×480 asked.

| # | Check | Result |
|---|---|---|
| V1 | The Video screen lists the model's lengths, sizes and first frame, and the price OpenRouter lists, read into dollars for the sizes it prices | 1–15 s; four sizes; first frame; 480p $0.05 a second for `854x480` and `480x854`, 720p $0.07, an input image $0.002 |
| V2 | A video job runs on Workbench's server, is polled through the gateway until done, and its MP4 is kept with what the provider billed | the provider got `duration: 1`, `size: 854x480`; polled 4 times (3 by Workbench, 1 by the gateway's content check); kept byte-identical as `video/mp4`; `costUsd` 0.05 |
| V3 | A length no listing makes is refused in the gateway's words, naming the field, and nothing reaches the provider | 99 s: *"… does not make 99 s; it makes 1, 2, … 15 … Nothing was sent."*, `param: seconds`; the fixture saw nothing |
| V4 | An image from the bin reaches the provider as the video's first frame | one `frame_images` entry, `first_frame`, a PNG `data:` URL |
| **V5** | **After a crash, the next start polls the running job again and keeps its video; nothing is sent twice** | a job submitted with the app's key; Workbench stopped by the agent; a `running` row holding the handle written while it was down; started again: polled 6 times, kept, no second submit |
| V6 | Stop ends a running job and its polling | `stopped`; 6 polls at Stop and 6 after 12 s |
| V7 | The gateway records the video jobs under the app's key, and no other | `videos` rows, `served`, `app:workbench@c3-node` |
| VL | A real OpenRouter video, 1 s at 480p, is priced from the listing before it is sent, made, kept as an MP4, and its billed cost kept | grok-imagine-video: the listing priced 480p at $0.05 a second, for its 7 sizes of that class; done after 5 polls; 165,595 bytes, `ftyp`; **billed $0.05** |
| B12 | The Video screen asks first, with the price from the listing, then says how long the job has run | *1 s at 480p. About $0.05, billed to OpenRouter.*, then *Working, 0 s so far …* |
| B13 | The finished video plays in Work orders, with what came back beside what was asked and what was billed | *Asked 1 s at 854 × 480, got 1.0 s at 160 × 90*; *The provider billed $0.05 for this.* |

**V5 writes the row while Workbench is down**, as a crash leaves it. A
graceful stop now keeps a job with a handle `running` too (§10c), so it
would reach the same boot path, but only the written row proves the path
without relying on the shutdown. Workbench's own test suite covers both.

The earlier checks (1–27, M1–M8, ML, S1–S7, SL and B1–B10) all passed
unchanged against the new Workbench, gateway and driver.

**Spent:** grok-imagine-video, 1 s at 480p, **$0.05** as billed; one
flux.2-klein-4b image at 512×512 (about $0.004); one kokoro clip and one
whisper transcription, a fraction of a cent. P5's video budget now stands
at about **$0.90 of $10**.

An unpaid dry run (`--source` the Workbench working tree, `--browser`,
no live calls) passed 63 of 63 before `dist` was built. It was there to
debug the new checks, and is not a second record.

## The other CI acceptances

- **Every script that specs CI's jobs run passed locally before the pins,**
  26 in all, from `agent/.venv` against the working trees above.
  - Not in that count: c3 (the run above), the Windows service smoke, Job
    Sites (Linux only), and the shell and Pester checks.
  - p2 18, p3 27, p4 15, **p5 8** and p6 9 checks passed, and p8's 15.
    The SDK halves ran from a scratch venv with `openai` and `anthropic`,
    as CI installs them; `agent/.venv` has neither.
  - c2 passed 42 of 42; r7 signing 13 of 13, rotation 8 of 8; row3
    (`--lan`) 27.
  - r8 profile, a3, a5, a6, a6b, the a7 recovery checks, run operations,
    the S10 checks and starter check, the release inputs and artifacts
    checks, the platform checks and the A8 summary all passed.
  - The sabotage checks caught every case: r8 profile 10, the R7 launch
    boundary 15, the R6 benchmark 6.

## Unit suites, the Chrome check and sabotage

- **inference-driver `2b1850b`:** pytest 981 (5 skipped); ruff, format,
  mypy (Windows and Linux) clean. CI green.
- **gateway `6780d6c`:** pytest 1,251 (1 skipped); static checks clean.
  CI green. `d9e2226` adds one test; the video tests pass 24 of 24.
- **Workbench `91c8b37`:**
  - pytest 233 without Chrome; with Chrome, the four media and scene
    checks pass, the new `test_media_video_browser.py` among them (it
    asks first, sees the job run with the working scene, plays the video,
    sends a first frame brought in, and fills the form from *Edit and
    send*);
  - vitest 196;
  - ruff, format, mypy (both platforms), eslint, prettier and `tsc` clean.
- **Sabotage: 39 of 39 caught.**
  - Driver and gateway, a scratch script: **13 of 13**. One gateway test
    was added first (`d9e2226`), because no test held a price line's
    `first_frame` or `audio`.
  - Workbench, `check-media-sabotage.py --only video`: **26 of 26**, two
    in Chrome. The first pass caught 25: *a first frame is not priced*
    escaped because `toBeCloseTo(0.052)` holds to two places, where $0.05
    passes. The instrument now holds to six, and the case was caught on a
    rerun with the two other price cases.
  - Every file was restored from exact bytes, and the restored baselines
    passed.

## Not run

- Deploying to Troy's install. Its gateway lists no video model, so the
  Video tab does not show there, and the media area shows the empty state
  until he adds a provider account (`workbench-media-screens.md` §0).
## CI

- Agent `6628f10`, gateway `6780d6c`, inference-driver `2b1850b` and
  specs `eb9a1f2`: green.
- **Workbench `91c8b37` failed one step, `ruff format --check`, on
  `scripts/check-media-sabotage.py`.** Its video cases were added after
  the local format check. `97e59f1` formats it. That file is a
  development script, so nothing that ships changed and `dist` `d1db51c`
  (built from `91c8b37`) stands. Every other job passed, the page's
  build and tests among them.
- **specs `c8ef763`** (the pins): CI, A4 macOS and the container image
  green. Workbench `97e59f1`: green.
