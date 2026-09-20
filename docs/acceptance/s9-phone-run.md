# S9 phone, focus and motion — 2026-09-20

UI source `94d0ce3ca70bdf042f2803f1f06c3353e11c2ba8`; distribution
`53062088ac6522e4746ac5fcae26d331d5d85906`. Both installers carry this UI.
No API or backend changes.

Below 640px, Library puts the model list above the selected details, with a
bounded list and scrolling details. Desktop retains two columns. Playground's
composer and diagnostic panels stack; direct-mode fields fit the available
width. Diagnostics and request reports have bounded scroll regions. The shell
uses dynamic viewport height, and its controls wrap. Config and Preferences
also stack their label and input columns.

Keyboard focus has a shared visible ring in all themes. Reduced motion stops
decorative animations and transitions, including pseudo-elements, and disables
the animated jump to the latest chat message. Hints and badges use rem sizes,
so the existing font-size preference reaches them. Diagram coordinates and
SVG chart labels retain their viewBox units; the adjacent result table scales.

Verification:

- **743 UI tests passed**, plus ESLint, TypeScript, Prettier and production build.
- The motion test changes the preference while the conversation is mounted.
  Deliberately restoring smooth scrolling under reduced motion fails the test;
  restoring the implementation passes.
- System Chrome, packaged wheel served by a real disposable agent, gateway,
  library and driver. A real Qwen3-0.6B Q4_K_M model ran through llama.cpp b10948
  with `--device none --n-gpu-layers 0`, four CPU threads and 2048 context.
  No browser API interception or canned completion.
- **430px Home → Try it → streamed reply**, HTTP 200 and completed SSE stream.
  The reply remains in the conversation after Continue in the Playground.
- Playground composer and Send fit at 430px and 390px. At 390px, diagnostic
  panels stack and the direct gateway URL fits without squeezing the composer.
- Library's selection, detail heading and new-profile editor are reachable at
  390px; at 1440px the list and details remain side by side.
- Extra Large font persists through navigation. A formerly fixed 10px config
  hint becomes 12.5px. Home, Playground, Library and Config have no horizontal
  overflow in the checked main containers at 390px with that preference.
- Real Tab navigation produces a solid 2px focus ring in Plexus, Modern and
  Editorial. A live media-preference change stops the shipped decorative
  spinner CSS, including its pseudo-element. That spinner class currently has
  no product consumer, so the check attaches the existing class to the test
  document; it does not add an animation to the product.
- No browser page errors. Disposable processes stopped after the run.
- All **184 assets** match the production export, distribution and wheel byte
  for byte. Wheel SHA-256:
  `47300303e6c0e11db95892a5028395c5763a477196356a31a8df066e9b8d18bc`.

Reproduce with an isolated interpreter containing the Eugene components and
the new UI wheel, plus sibling UI Node dependencies:

```text
python scripts/s9-ui-acceptance.py --output <new-disposable-directory> --engine <llama-server-path> --model <small-chat-GGUF-path>
```

The output holds screenshots, `completion.sse`, `results.json`, logs and a
disposable session. Do not commit the session. Local evidence is under
`%TEMP%/ep-s9-browser-final`. The harness uses `s8-ui-acceptance.py`'s graceful
agent server wrapper and supervises the CPU engine separately.

These are Chrome viewport checks, not physical iOS/Android keyboard testing.
The installed Windows service, live GPU model and NAS configuration were not
changed. S10's download timing and moderated sessions remain separate evidence.
