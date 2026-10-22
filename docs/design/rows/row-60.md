# Row 60: full interop conformance for apps inside Workbench

Lane WB. **High risk** (sandbox). Sources: G-later;
`workbench-ui-interoperability.md` (G5 built 2026-10-15: A2UI forms,
AG-UI, self-contained MCP Apps; "the separate-origin proxy and
network/device grants remain unsupported"), `workbench-ui-browser-v1.md`
(the shipped proxy is `opaque-offline`, `browserConformance: constrained`;
requested CSP domains, devices and a domain are refused),
`workbench-mcp-apps-v1.md` (sampling, elicitation, links, logging,
downloads and app-provided tools unsupported), `workbench-a2ui-v1.md`
(the 0.9.1 forms catalog).

## 1. What it delivers

- **MCP Apps that need the network or a device work,** with the person's
  permission: an app's UI may reach the domains its server declares
  (after "Allow maps.example.com for this app?") and, if it asks, the
  camera, microphone or location (each asked once per app).
- **Apps can ask the model and the person:** MCP sampling (the app asks
  the model a question, shown to the person, counted against their usage)
  and elicitation (the app asks the person for input with a form).
- **More of A2UI:** the components beyond forms in A2UI's published
  catalog (lists, cards, tabs, images, the chart components the catalog
  defines), rendered by Workbench's own components.
- Links, logging and downloads from apps, under the same sandbox rules.

## 2. Design

- **A separate origin without a new port.** App UIs are served from a
  second origin on Workbench's own port: the machine's other name (its IP
  address when Workbench is opened by name, or `apps.<name>` under the
  owner's domain when row 45c's wildcard exists). The LT2 leaf already
  names both. The app frame gets that origin with
  `allow-scripts allow-same-origin` inside it, so storage and network
  work, while Workbench's own origin (cookies, session) stays out of
  reach. Where no second name is available (plain HTTP on loopback), the
  current opaque offline proxy stays and the page says why.
- **Grants:** the app's declared CSP domains become a per-app, per-person
  grant stored in Workbench; the frame's CSP lists only granted domains.
  Device permissions use the frame's `allow` attribute, per grant.
  Revocable on the Tools page.
- **Sampling:** a request from the app goes through Workbench to the
  gateway as the person, with the model the person's chat uses, after an
  approval card showing the prompt (C5a's approval rules); results return
  to the app.
- **Elicitation:** rendered as an A2UI form card in the chat; the person's
  answer (or refusal) returns to the server.
- **A2UI:** the components in the published catalog version this row
  pins, each mapped to Workbench components; an unknown component shows
  its fallback text, as forms do now.

## 3. Repositories

workbench (`mcp_sandbox.py`, `mcp_apps.py`, the web app's frame, grants
and A2UI catalog), agent (the second name on Workbench's entry point;
LT2 names it already), specs (acceptance).

## 4. Tests that fail before

- workbench `test_mcp_sandbox.py::test_the_app_origin_differs_from_workbenchs`
  and `test_an_ungranted_domain_is_blocked_by_csp`.
- workbench `test_mcp_apps.py::test_sampling_waits_for_approval_and_counts_usage`,
  `test_elicitation_returns_the_persons_answer`.
- web: A2UI catalog components render; unknown ones fall back.

## 5. Acceptance (CI, Linux and Windows, Chromium, Firefox, WebKit)

A fixture MCP App that tries to read Workbench's cookies and storage
(refused), fetches a granted and an ungranted domain (one works), asks
for sampling and elicitation (both after the person's action). The
reviewer attacks the origin split (cookies, `postMessage` targets,
service workers), grants leaking across apps or people, and sampling
spending another person's usage.

## 6. Size and risks

L, about 5 days. One adversarial review. Risk: the sandbox is the
boundary between third-party UI and people's chats; the acceptance runs
the escape attempts in three browsers.

**Calls:** none.
