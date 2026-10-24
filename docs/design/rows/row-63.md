# Row 63: Strata: the speed projection, and several GPUs

Lane ENG. Low risk (an experimental engine). Sources: agent#14 ("After
v0.2: reverse LS5's B49 for Strata (vision, the speed projection, several
GPUs)"), B49 in `library-sources-and-engines.md` (approved for v0.2 only),
`strata-engine.md` (vision's image preparation built 2026-10-17; "Multi-GPU
preparation still requires separate integration work"), agent
`engines/strata.py` and `strata_prepare.py`.

## 1. What it delivers

- **Several GPUs for Strata.** A Strata model can be prepared and run
  across two or more cards with the layer split upstream's setup supports;
  today preparation picks one card (`main_gpu()`) and the adapter refuses
  `layer_split`.
- **The speed projection, as the person's choice.** Preparation passes
  `--experimental-speed-projection off` today. The profile offers it,
  labelled experimental, with upstream's own description of what it does
  and what it costs.
- Vision (the third item of agent#14) is done (`strata-engine.md`,
  2026-10-17) and is not in this row.

## 2. Design

- **Step 1, read upstream at the pinned commit** (`6f32ec07…`, v0.1.39):
  what the speed projection does (its flags, what it changes in the
  answer, measured speed-ups if upstream gives any), and how `layer_split`
  is set and fitted. Written into `strata-engine.md`. If the projection
  changes the model's answers (not only speed), the setting says so in its
  first line.
- **Several GPUs:** the adapter accepts `layer_split` (validated against
  the cards present, by UUID from row 43 where built); fit sums the cards
  in the split (`strata_card()` and `setup_fit` learn a card list);
  preparation passes the split to upstream's setup.
- **The projection:** a profile setting `speedProjection` (off default,
  on), passed to preparation and launch with upstream's flag; the runtime
  reports it in its effective launch.

## 3. Repositories

agent (`strata.py`, `strata_prepare.py`, `strata_models.py`), library (fit
for a card list if the fit lives there), ui (the two settings), specs
(the doc; the adapter's GUI schema if contract-held).

## 4. Tests that fail before

- agent `test_strata.py::test_layer_split_is_accepted_and_validated`
  (today: "unsupported config features").
- agent `test_strata_prepare.py::test_the_projection_follows_the_setting`
  (today: always `off`).
- agent `test_strata.py::test_fit_sums_the_cards_in_the_split`.

## 5. Acceptance

Unit and planning tests in CI (the adapter's argv and preparation steps
with a stub upstream). A real run needs two GPUs and Strata's preparation;
not a roadmap item (Troy, 2026-10-21).

## 6. Size and risks

M, about 2 days. Risk: upstream is young; the pinned commit decides, and
the doc records what was read there.

**Calls:** none.
