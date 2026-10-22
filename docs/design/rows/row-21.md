# Row 21: the model author's sampling as the default

Lane LIB · low risk · size S-M. Repos: library, gateway, ui. Contract: `library.yaml`.

## 1. What it delivers

- When neither the request nor the default profile sets temperature, top-p, top-k or min-p, the gateway sends the values the model's author wrote into the file.
- The author's values come from GGUF `general.sampling.*`. New in this row: they also come from a safetensors model's `generation_config.json`.
- A value the profile sets wins. A profile can also turn the author's values off.
- The profile editor and the model page show each value in effect and where it came from.

## 2. The design

For each parameter, the gateway takes the first value that exists, in this order:

1. the request;
2. the default profile;
3. the model's author, unless the default profile turns that off (new);
4. the gateway's default;
5. nothing, so the engine's own default applies.

The gateway still decides and sends every value; the Library only reports what the author wrote (`feedback_orchestrator_owns_llm_params`).

**Contract (`library.yaml`).**

- `ModelProfileSpec.authorSampling`: a boolean, default true. A profile with no value reads as true, so stored profiles need no migration (storage stays at version 2).
- `ModelProfileSpec.topK` and `ModelProfileSpec.minP`.
- `RecommendedSampling.minP`, and `RecommendedSampling.source`: an enum, `RecommendedSamplingSource` (`gguf | generation_config`).
- `RecommendedSampling`'s description changes from "never applied" to "applied by the gateway as defaults".
- `SafetensorsDetail.recommendedSampling`.

**Library.**

- A new `formats/generation_config.py` reads `temperature`, `top_p`, `top_k` and `min_p`.
- It reads them only when `do_sample` is true. When it is false, the author asked for greedy decoding, and nothing is applied.
- `scan_manager.py` runs it after the scan.
- An out-of-range value is dropped, with a warning: "The file's temperature 5 is outside 0-2, so it is not used."
- `routes/profiles.py` and `profile_storage.py` keep the new fields.

**Gateway.**

- `profiles.py` `_read` already fetches the model. For each key it now takes:
  - the default profile's value, or
  - when there is none, the author's value, as long as there is no default profile or its `authorSampling` is not false.
- It returns `maxTokens`, `temperature`, `topP`, `topK` and `minP`.
- `routes/inference.py` changes in three lines:
  - two in `_to_generate_request`, which takes `topK` and `minP` from those defaults;
  - one in `prepare_candidate`, which copies them.
- A filled value is not in `callerSettings`, so a backend that cannot honour it drops it rather than refusing the request.
- A cloud backend has no model path, so nothing changes for it.
- When the Library cannot be read, the gateway falls back as R8 does: cached defaults while they are not too old, then its own. The log names which source was used.

**UI.**

- `ProfileEditor.tsx`:
  - a switch: "Use the model author's sampling where this profile sets none";
  - a field left blank says what applies instead, for example "not set: the model author's 0.6", "not set: the gateway's 0.7" or "not set: not sent; the engine's default applies";
  - new topK and minP fields.
- The Library facts row: "sampling · temperature 0.6, top-p 0.95, top-k 20 · the model author's · used when a request and the default profile set none". When the author's values are not used, it says why:
  - "not used: the default profile turns it off"
  - "the author asks for greedy decoding; not used"

**Defaults (P4, called out): on.** After the upgrade, local models whose files state sampling answer differently wherever the default profile sets none. Nothing is deleted or exposed.

## 3. Repositories and files

| Repo | Files |
|---|---|
| specs | `openapi/library.yaml` |
| library | new `formats/generation_config.py`; `scan_manager.py`, `profile_storage.py`, `routes/profiles.py` |
| gateway | `profiles.py`; `routes/inference.py` (3 lines) |
| ui | `ProfileEditor.tsx`, `src/app/library/page.tsx` |

Regenerate the library, gateway and ui code from the contract.

## 4. Test that fails before the change

`gateway/tests/test_profile_defaults.py::test_author_sampling_fills_what_the_profile_leaves`

- **Setup:** the model has author values `{temperature 0.6, topK 20}`; its default profile sets `topP 0.9`.
- **Expected:** `{temperature 0.6, topP 0.9, topK 20}`.
- **Today:** `{topP 0.9}`.

Also `test_author_sampling_off_keeps_gateway_default`, and in the library, `test_greedy_config_is_not_applied`.

## 6. Do not change

- **`gateway/.../routes/inference.py` belongs to row 55 (GW).** This row's three lines there need the lead to set the order. If that is not possible, ship temperature and top-p through `profiles.py` alone now, and top-k and min-p later.
- `library/scanner.py` (17), `formats/gguf.py` (18, 68), `gateway/decisions.py` (1, 12), `gateway/routing.py` (11, 14, 37, 61).
- `gateway/profiles.py` is also row 48's, which comes later in this lane.

## 7. Size, risks, open questions

**Size S-M.**

**Risk:** some local models answer differently after the upgrade. The author's values are what the model was tuned with, and the profile switch undoes the change for one model.

**Questions:**

1. Should the author's values apply when a model has no profile? **Recommend yes:** most people never save one.
2. Should the author's repeat penalty apply too? **Recommend not now:** the gateway carries no repeat penalty, and row 19 owns repetition.

## Calls answered by Troy (2026-10-21)

- **R21-DEFAULT: Choice 1.** Use the author's sampling settings by default, with a switch on the profile page.
