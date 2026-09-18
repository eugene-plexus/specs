# R2.4 — credentials proportionate to the job: the run

**2026-09-18. `scripts/r24-acceptance.sh`, 21 PASS live, zero failures, second
execution. `scripts/r24-sabotage.py`, 20 sabotages, 20 caught, 0 escaped** —
after two escaped on the first pass, and **both named a missing check rather
than a weak fix**. Roadmap:
[`../design/release-roadmap.md`](../design/release-roadmap.md) §3.4. Findings
closed: review §6.2 #12, §6.2 #15, §6.3 #33.

Repos: `control`, `agent`, `gateway`, plus `specs` (prose in two contract
documents). **No schema change, so no consumer regenerates and `ui` does not
move** — nothing here is a shape on the wire, only who may ask and what may be
asked for.

---

## 0. The shape of it

Three findings, one sentence: **a credential was wider than the job it was
doing.** Each is a different place the width shows.

| finding | who was trusted with what | what it buys an attacker |
| --- | --- | --- |
| §6.2 #12 | any `service:*` token could read the replication surface | the Argon2id salt and the passphrase verifier — an **offline** attack on the operator's passphrase |
| §6.2 #15 | a correctly signed worker could name any URL as its own address | the root probes it every poll and every console hop dials it **holding the operator's bearer** |
| §6.3 #33 | the admin Test button probed a typed URL holding `service:gateway` | a token every component in the install accepts, collected by typing an address into a form |

None of the three is an authentication defect. **Every one of them passes
authentication and then does too much**, which is why none could be fixed in a
signature path or a token decoder.

---

## 1. #12 — "a read" was one level where it needed two

`require_authorized` accepts operator **or any** `service:*` audience, and that
is right for `GET /v1/control/status` (an agent needs the epoch) and for
`GET /v1/nodes`. It was also the level on `GET /v1/control/snapshot` and
`GET /v1/control/log`, and those are not that kind of read: the snapshot carries
`sealedSigningKey`, `salt` and `passphraseVerifier`, and the log carries the
entries that wrote them.

A gateway, library or driver token holds no master key. Reading the salt and the
verifier hands its holder everything needed to grind the operator's passphrase
offline, at their leisure, off the box. The configured-but-locked window, a
restarted agent and a node whose agent never unlocked are all states where a
`service:*` token exists and a master key does not.

**The fix is a new level, not a new check.** `security.decode_token` gained
`accept_service_kinds`, and `dependencies.require_replica` is operator **or**
`service:control` — the audience a standby already presents, via
`node_service_token`. Two shapes were rejected on the way:

* **Operator-only** would have been simpler and would have cost failover. A
  standby follows at 3am with nobody logged in; replication that needed an
  operator session would fall behind whenever the operator was asleep. A
  sabotage puts that version back and the gate catches it.
* **`accept_any_service=True` beside the kind list** reads like a safety
  widening and is the defect verbatim. Also sabotaged, also caught.

**The review's own clause about the fix was wrong, and the roadmap said so
before this started:** revoke and rotate use `require_operator`, and control has
no exact-service dependency anywhere, so this was a new parameter plus a new
dependency rather than a reuse of something already there.

**The test that should have caught it encoded the defect as intent.**
`test_a_service_token_can_read_but_not_mutate` asserted a `service:gateway`
token gets 200 on status and on nodes, then went straight to the mutations — it
stopped one endpoint short of the door that mattered. It now carries the one
assertion that closes it, and
`test_a_service_token_that_is_not_the_standby_cannot_pull_key_material` is the
full gate beside it. **That test opens by reading the snapshot as the operator
and asserting the material is really there**, so the 401s below it are a refusal
of something rather than of an empty document.

---

## 2. #15 — the signature settles who, never which address

`PATCH /v1/nodes/{name}` is signed rather than bearer-authenticated, and that
half is sound: Ed25519 over a message covering the node's name, a strictly
increasing sequence, no bearer to survive a rotation. What nothing settled is
**which address** a correctly authenticated node may name. `is_loopback_host`
was the only filter, so `http://169.254.169.254/` was a valid answer — and after
that this root probes it every poll and `install_proxy` dials it carrying the
operator's own bearer.

Two rules now sit after the signature, and they fail differently on purpose.

**An address that can never be a node is a 400.** A scheme that is not http(s),
the bind wildcard, a multicast group, a link-local address (which is where every
cloud provider's instance-metadata service listens), a reserved range. The same
rule runs at `enrollNode` — **before the join token is consumed**, so a
malformed enrollment does not burn an operator-minted single-use credential on a
host whose agent is sitting at a prompt.

**A node may not put itself on the open internet: 409.** Classes are `loopback`,
`private` and `public`.

**The rule is *becoming public*, not *widening*, and the reproduction check is
what said so.** Written first as a rank comparison — `loopback` < `private` <
`public`, refuse anything that moves right — it refused `loopback → private`,
which is the **S5 Reach switch**: one click, on Home, on the commonest install
there is. That went red immediately, and the rule narrowed to the one transition
a homelab node never makes by itself. Private → private (a new DHCP lease) and
public → private (coming home onto the LAN) are both untouched. The wrong
version is now a sabotage of its own.

**`is_private` is the wrong predicate and this box's own fixtures prove it.**
`ipaddress.ip_address("100.64.0.7").is_private` is **False** on the Python both
installers provision, and 100.64.0.0/10 is where a tailnet address lives — so a
rule built on `is_private` would call a tailnet node public and refuse the Reach
switch on precisely the deployment this product is for. The classes are built
from the negation of `is_global`, which asks the question the rule is actually
about. A pinned test states both facts so neither can drift.

**And the same trap bit the fixtures.** The first version of the "moves onto the
open internet" check used `203.0.113.9` — TEST-NET-3, the documentation range —
which Python reports as `is_global: False` and `is_private: True`. The check went
red against a correct implementation: a fixture the detector cannot produce, the
recurring shape in this repo, caught here by writing the check first. Both facts
are asserted now, so the next person does not re-derive them.

**A bare hostname counts public**, because whoever resolves it is not this root.
That cost one existing fixture: `test_an_announcement_signed_by_the_wrong_node_is_refused`
enrolled a node at `100.64.0.7` and then announced `http://evil:8079`, whose
subject is the **signer**. Its address is now on the same side of the network, so
it is refused for one reason and proves it; the address rule has its own file.

**The remedy is named in the 409 and it is one that exists**: re-enrollment,
which needs an operator-minted join token and is therefore exactly the
confirmation the rule is asking for. It is the same remedy the pre-existing 401
names for a node that enrolled before nodes had signing identities, in the same
words — *its model files and runtimes are untouched by that.*

### 2.1 The second half, at the point of use

The console hop spends **the caller's own bearer**, by design — an enrolled node
holds the install's signing key, so the operator's token is one the root accepts,
and minting one instead would take back the property the hop was built for. That
design is unchanged. What changed is that `install_proxy` now refuses to dial a
registry entry that cannot be a node, before it spends anything.

Not redundant with the root's rule: **a registry written before this fix still
holds whatever it was told**, and the agent is the process that would spend the
credential. Two copies rather than a shared helper, per the standing rule that
components share schemas and not code — and they answer different questions
anyway, *may I write it down* versus *may I dial it*.

---

## 3. #33 — the probe spent a credential the operator never offered

`POST /v1/admin/drivers/probe` dials whatever the operator typed. That is the
feature — the per-URL Test button, the same affordance Sonarr and Radarr expose
next to each indexer — and the roadmap's call was explicit: **leave the
behaviour, make the credential proportionate.** It attached this install's
`service:gateway` token, which every component here accepts, so a URL in a form
was enough to collect one. The route is operator-gated, so this was never an open
relay; it is that an operator typing an address is not an operator deciding to
hand out a credential, and those are different acts.

The probe is anonymous now. **The consequence is a better answer, not a worse
one**: a driver that wants a key answers 401, and 401 means *the address
answered*. Reporting that as `reachable: false` sends an operator to check cables
and firewalls when their backend is up and simply wants a key. `_driver_health`
catches `httpx.HTTPStatusError` separately and reports `reachable: true` with the
reason; only a transport failure is `reachable: false`. Both halves are
sabotaged, both caught.

**The check is a wire, because the claim is about a header.** A real
`http.server` listener records what arrives, a real gateway with a real signing
key and a real `service:gateway` token probes it, and the assertion is that the
`Authorization` header was absent — plus that the token's own leading bytes
appear nowhere in what the listener saw.

---

## 4. The live run

`scripts/r24-acceptance.sh`, **21 PASS, zero failures, second execution.** A
real control root on :8183 and a real gateway on :8180, both isolated: every
ambient `EUGENE_PLEXUS_*` variable dropped, ports +100, a throwaway state
directory, teardown by pid. Never `pkill -f eugene_plexus_` — this box is a
worker node in the live install.

**The tokens are the install's own.** The run initializes the root with a real
passphrase, pulls the snapshot as the operator, derives the master key, opens
`sealedSigningKey` the way a standby would, and mints `service:gateway`,
`service:control` and an operator token from it. So a 401 in check 3 is a root
refusing a token it verified, not one it could not read.

What it proved, in order: the snapshot really carries the key material (check 2,
so the refusals are about something); `service:gateway` keeps status and nodes
and loses the snapshot and the log; `service:control` keeps both; a correctly
signed announcement of `http://169.254.169.254/` is 400 with the record unmoved;
the same node cannot reach `8.8.8.8` and the 409 names re-enrollment; loopback →
LAN and LAN → tailnet both still answer 200; the agent refuses the metadata
address before the hop; and the gateway's probe reaches a real listener with no
`Authorization` header at all.

**The first execution's one failure was the harness.** The readiness loop dials
the listener at `/` until it answers, and the listener counted those requests
too — `[null, null]` against an expected `[null]`. Both entries were `null`, so
the property held throughout; what was wrong was the instrument. The listener
records only `/v1/info` now, which is the path the probe uses and the only one
the check is about.

**What it could not prove**, stated rather than implied: a real standby
following a real active root across two hosts (that is m5/m7 territory and needs
two machines); a browser driving the Test button; and the 409's remedy end to
end — re-enrolling a node after a genuine address change is an operator action
nobody performed here.

---

## 5. The sabotage pass

`scripts/r24-sabotage.py`, **20 sabotages, 20 caught, 0 escaped.** Restores from
a copy taken before anything is touched, never `git checkout --`; opens with a
baseline assertion that all four gates pass unsabotaged. Four gates: `control`,
`agent` and `gateway` unit files, plus the live run.

**The first three entries are the findings themselves, driven against the live
processes** — a real root handing its snapshot to a real `service:gateway`
token, a real root recording a correctly signed announcement of the metadata
address, a real gateway putting a real service token on a real socket.

**Two escaped on the first pass, and each named a missing check.**

**(a) Removing the scheme check from the agent's point-of-use filter changed no
result.** The parametrized cases included `file:///etc/shadow`, which has **no
host** and so was refused by the next branch anyway — so none of the four cases
could tell whether the scheme was looked at. `gopher://10.0.0.1:8079/` is the
case that can: a scheme this agent does not speak, with a perfectly ordinary
host. Added; caught.

**(b) The order of the address check and the join-token consume was untested.**
Moving the check after `store.consume` looks identical from outside — same 400,
same body — and the difference only shows on the *second* attempt, when the
operator's single-use token turns out to be spent. A test that enrolls badly and
then re-presents the same token is the gate; it now exists.

**And the first version of sabotage (b) was itself a no-op**, which is why it
escaped a second time: it inserted a dead `reason = None` *after* the real check,
which still ran and still raised. A sabotage has to produce the defect, not
mention it. It swaps the two blocks now.

The remaining entries take each fix apart one property at a time: the log's half
of #12; `require_replica` widened and narrowed in both directions; `decode_token`
ignoring the kind list; the widening rule dropped; the rank-comparison version
that refuses the Reach switch; `is_private` in place of `is_global`; a hostname
counted private; link-local and scheme dropped on both sides; enrollment's check
removed; and the gateway's 401 branch, twice.

---

## 6. Not done, and named

* **The operator has no surface for a refused announcement.** A node that tried
  to move onto the open internet is refused, both logs say so, and the node then
  reads `reachable: false` with a *probe* error rather than the real reason. No
  `IssueKind` covers it and nothing on Home or Nodes prints it. Recorded rather
  than built: it wants a contract field, which this slice deliberately does not
  take.
* **Re-enrollment as the confirmation path is asserted in words, not walked.**
  The 409 names it; nobody in this run re-enrolled a node to confirm a genuine
  address change.
* **The probe still dials any address the operator types**, by the roadmap's own
  call. The credential is gone; the reachability is the feature.
* **No browser drove any of it.**
