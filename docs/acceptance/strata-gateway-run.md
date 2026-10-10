# Strata through the gateway, and saying why when a driver cannot be reached

Found on Troy's live install, 2026-10-10, right after LS10. Strata was
prepared and *ready* on Amish_Station, and the Inference page showed three
things that would panic someone new:

- *Partial view. gateway: No driver in the topology is reachable.
  qwen3-8-flash-next-iq2-xs-driver=http://192.168.16.75:8093/ ()*
- the Strata runtime's own driver on a row of its own, *external backend ·
  runs on its own · no model reported · unknown to gateway*, with a Remove
  that would have broken it;
- *Showing huihui-…-driver on Amish_Station* for a backend just removed,
  and a Strata note saying fit is unknown and preparation unsupported, both
  untrue since LS5 and LS6.

Underneath were two real faults.

1. **No Strata driver had ever worked.** The agent fronts every Strata
   runtime with an `inference-driver` on provider `strata_local`. That
   provider's registry entry gave its engine no `default_base_url`, which
   the engine requires, so every Strata driver came up degraded:
   `OpenAiCompatibleHttpEngine.from_config() missing 1 required
   keyword-only argument: 'default_base_url'` (read off the live driver's
   `/healthz`). Nothing reached Strata through the gateway, and so nothing
   reached it from the Playground or Workbench. Every Strata test built the
   engine directly, and the LS5 real run measured Strata at its own port. No
   acceptance had a gateway in front of Strata.
2. **The firewall rule did not follow new drivers.** The Windows rule
   *Eugene Plexus* allowed 8079 and 8091, the ports listening when Troy
   allowed it. Strata's driver listened on 8093, so the NAS's gateway timed
   out connecting, and httpx's timeout carries an empty message: `()`.

## What changed

- **inference-driver.**
  - `strata_local` gives its engine its base URL from the runtime, by
    name.
  - A test checks every provider in the registry: each argument its
    engine's `from_config` requires must be given (a regression test,
    sabotaged).
  - A degraded driver's `/v1/info` carries `degraded`: why it serves
    nothing (contract specs `d94bf68`).
- **gateway.**
  - An unreachable driver's reason is never empty. A connect timeout names
    the address, the port and the firewall; a refusal names the driver's
    own words.
  - A degraded driver is reported with its reason.
  - `/v1/admin/drivers` lists every driver whatever it answered. It was a
    503 when none was reachable, and the console lost every reason and every
    companion's runtime with it.
- **agent.** Once the person has allowed Eugene through the firewall (the
  rule exists), the agent keeps the rule's ports to exactly what the install
  listens on off loopback (Troy's call). This is Windows only, and only
  elevated, which a service install always is. A rule the person never
  allowed is never made.
- **ui.**
  - A companion driver is its runtime's row even when the gateway's list is
    missing.
  - An unreachable or degraded driver's reason is in words on the row.
  - Removing the selected backend moves the page to its machine, and a link
    to something no longer listed says so.
  - Strata's note says what is true now.
  - An engine that cannot be installed here says why, in words.

## Acceptance of record

`scripts/ls5-preparation-acceptance.py`, extended: the agent now also spawns
a gateway, and the stand-in Strata answers `/v1/chat/completions`. It ran on
Amish_Station, 2026-10-10: **23/23 PASS**. That is LS5's and LS10's 21, plus:

```
PASS  W1 the gateway reaches the Strata runtime's companion driver, which reports no error
PASS  W2 a chat through the gateway is answered by Strata
```

On ubuntu CI at specs `3752b8f`, W2 failed once with a 503 *still coming
up: … (starting)*. The chat came 50 ms after the agent said `ready`. It met
the gateway's routing snapshot, which can be one refresh behind, and the
gateway re-reads only a snapshot at least 1 s old. W2 now waits on that
snapshot itself (`/v1/admin/routing`: the Strata driver eligible for the
model) before it chats. W1 alone could not show this, because a driver is
reachable while its runtime is still starting. The rerun here: 23/23.

## Unit tests

- inference-driver: `tests/test_provider_registry.py` (16), and two in
  `tests/test_info.py` (`degraded`).
- gateway: `tests/test_routing.py` (an unreachable driver's reason for each
  kind of failure, a refusal in the driver's words), and
  `tests/test_admin_and_config.py` (all unreachable, empty, degraded).
- agent: `tests/test_firewall_follow.py` (7).
- ui: `lib/inferenceRows.test.ts` (the placed companion) and
  `app/inference/page.test.tsx` (the reasons on the row, the stale
  selection, Remove moving to the machine).

## Sabotage

`scripts/strata-gateway-sabotage.py`: **14 caught, 0 escaped**. The 14
cover every gate (driver, gateway, agent, ui and the acceptance). Each gate
passed at baseline and again after the restore.

Full suites before landing: inference-driver 1065 passed, gateway 1276,
agent 2189, ui 1871 (151 files).

## Pinned

- agent `5666b39`
- gateway `e4a3ac4`
- inference-driver `d63c5c1`
- ui `dist` `a484c26` (built from ui `2464d6f`)

## The live run (owed)

Once Edge has these, update the NAS container first, then Amish_Station.
On Amish_Station, the agent's log should then say *firewall rule follows
this install's listeners*, and the rule should allow 8093. Inference should
show the Strata row with no error, and the Playground should chat with it.
