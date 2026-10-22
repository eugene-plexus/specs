# Row 71: model roles

Lane LIB, cross-component, low-to-medium risk (no auth change). Size M. Source: Troy's answer to MODEL-JOBS (2026-10-21): "if we can tag engines with task roles, then each permission group (company) can have their own routing rules for each type of role."

## 1. What it delivers

- **The owner gives models roles.** On a model's page in the console: "Roles: Chat, Reads pages", as chips the owner adds or removes. A "Model roles" page under Routing shows the same data the other way round: one line per role, with its models in order.
- **Apps ask for a role, not a model name.** A request for model `role:reads-pages` goes to the first model with that role that can answer, then the next (the same fallback as a model slot today).
- **Row 30's page reading is the first user.** Workbench asks for `role:reads-pages`. Other features move onto roles in their own rows.
- **A role with no model says so:** "No model has the role Reads pages. Give one that role under Routing > Model roles." A link goes there.
- **Row 37 adds per-group routing by role.** This row keeps one list per role for the whole install.

## 2. The design

### A role is a model slot with a reserved name

The gateway already has model slots (`modelSlots`): a name a client asks for, and the models to try in order. A role is a slot named `role:<role>`.
- Nothing new routes requests: `role:reads-pages` resolves through the slot code that resolves `coder` today, with its failover and its refusals.
- Row 37's per-group routing becomes a per-group override of the same slot.

**The roles (`ModelRole`, a named enum in `components/common.yaml`).** Each has a label and the capability a model needs to hold it:

| Role | Label | A model needs |
|---|---|---|
| `chat` | Chat | chat |
| `agentic` | Agentic (tools and code) | chat with tool calling |
| `vision` | Sees images | chat with image input |
| `reads-pages` | Reads pages (OCR) | chat with image input |
| `image` | Makes images | image generation |
| `speech-to-text` | Hears speech | transcription |
| `text-to-speech` | Speaks | speech |
| `music` | Makes music | audio generation |
| `embeddings` | Embeddings | embeddings |
| `rerank` | Reranks | rerank |
| `decision` | Decisions (yes/no) | a decision backend |

- **The list is closed** so a typo cannot make a role nobody asks for. A new role is a contract change.
- **The capability check warns; it does not block.** A model whose capability is unknown can still be given a role, with a warning (Troy's rule: never block what is untested; an observed failure is shown).

### Gateway (`specs/openapi/gateway.yaml`, gateway)

- `modelSlots` accepts `role:<ModelRole>` names. A slot named `role:` plus anything else is refused at PATCH with the list of roles.
- `GET /v1/models` lists each role that has a model, as `role:<name>`, with `x_eugene_plexus.role` (the role and its label). A role with no model is not listed.
- A request for a role with no model: 404 `model_not_found` with the sentence in section 1.
- New `GET /v1/roles`: every role, its label, its required capability, its models in order, and for each model whether it has the capability (yes, no, unknown). The console reads it.

### Console (ui)

- **Routing > Model roles:** one line per role. Add a model (a picker that lists models with the capability first, the others after a divider marked "capability unknown" or "lacks it"), reorder, remove. It saves the gateway's `modelSlots` through `PATCH /v1/config`, keeping every other slot.
- **A model's page:** "Roles" chips. Adding a role appends the model to the end of that role's list.
- Both views edit the same `modelSlots` entries, so they never disagree.

### Workbench

- The model pickers in Settings (the decision model, the embedder, the model that keeps notes) list matching roles first: "Use the install's Embeddings model (role)". An existing explicit choice stays as it is. This row changes no setting by itself.
- Row 30 sends page reading to `role:reads-pages`.

### Library

- No change. Roles live in routing, not on the model file, so one file served by two profiles can hold different roles.

## 3. Repositories and codegen

- **specs:** `openapi/components/common.yaml` (`ModelRole`), `openapi/gateway.yaml` (`/v1/roles`, the slot rule, the models listing).
- **gateway:** the slot validation, `/v1/roles`, the models listing, the 404.
- **ui:** the Model roles page, the chips on a model's page.
- **workbench:** the pickers list roles.
- Regenerate every consumer and diff to measure the radius.

## 4. Tests that fail before the change

- gateway `test_model_slots.py::test_a_role_slot_routes_like_any_slot` and `test_an_unknown_role_name_is_refused_with_the_list`.
- gateway `test_roles_api.py::test_roles_list_every_role_with_its_models_and_capability`.
- gateway `test_inference.py::test_a_role_with_no_model_says_where_to_set_it`.
- ui `ModelRoles.test.tsx`: adding a model to Reads pages saves `role:reads-pages` and keeps the other slots.
- workbench: the embedder picker lists "Use the install's Embeddings model (role)" first.

## 5. Acceptance

Not high risk. CI unit and integration tests, plus the specs branch integration (gateway, ui, workbench change together).

## 6. Do not change

- gateway `admission.py`, `budget.py` (row 11); the slot resolution itself (reuse it).
- library `scanner.py`, `fingerprint.py`, `scan_manager.py` (rows 17, 22).
- ui `ConfigField.tsx` (row 62), `ResourceTree.tsx`, `SettingsSearch.tsx` (row 33, merged; extend only).

## 7. Size, split, risks

**Size:** M. Branch `r71-model-roles`: **71a** contract and gateway; **71b** console; **71c** Workbench pickers.

**Risks:**
- Roles in `modelSlots` share a list with the owner's own slots. A save from an older console that does not know roles keeps them, because it PATCHes the whole list it read.
- Apps outside Eugene see `role:*` names in `/v1/models`. That is the point: Open WebUI can then offer "role:chat" as a model.

**Calls:** none open. MODEL-JOBS is answered; the role list above is the default built (P4) and can grow.
