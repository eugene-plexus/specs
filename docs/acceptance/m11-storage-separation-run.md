# M11 — compute/storage separation, on one box

**2026-09-13. `scripts/m11-acceptance.sh`, 53 checks, zero failures,
first execution.** Agent `be17d9e`, library `4925e9c`, contracts
`df930bd`. Design:
[`m11-compute-storage-separation.md`](../design/m11-compute-storage-separation.md).

Two agents on this Windows box, the shape `m7-acceptance.sh` proved:
agent A (`node-a`, `:8179`) spawning the control root, the gateway and
the library; agent B (`node-b`, `:8184`) spawning the runtime and
declaring **no library**. Both advertised the box's LAN address
(`192.168.16.75`) rather than loopback, because the install-wide lookup
refuses to dial a loopback registry entry — correctly — and check 10
needs B to reach A's agent by the address the registry holds. The
library's one root held a copy of a real 1.8 GB GGUF; B's "mount" was a
second directory holding a hard link to the same bytes. Every port +100
from the install defaults and every ambient `EUGENE_PLEXUS_*` variable
dropped first, so the operator's own worker agent on this machine was
neither collided with nor impersonated.

## What was proved, in order

**A path this host does not have is refused before anything spawns.**
`POST control /v1/runtimes {node: node-b, spec}` with `modelPath:
/srv/models/Qwen3-1.7B-Q8_0.gguf` — POSIX-shaped, a path that exists
nowhere on this box and that Windows' `abspath` would read as
`C:\srv\models\…`, a different path rather than a missing one — came
back **502 relaying the node's 422**:

```
refuse: /srv/models/Qwen3-1.7B-Q8_0.gguf is not on node-b. Nothing exists at
/srv/models/Qwen3-1.7B-Q8_0.gguf. If these files live on another machine --
the library's own model directory, say -- mount that share here and add a
mapping from the directory as the library spells it to where it is mounted
here: Config -> Agent @ node-b -> Model directory mappings. Or pass
?force=true to launch anyway.
```

B declared no runtime and no companion driver for it. The dry run said
the same, structured: `decision: refuse`, `fit: unknown`,
`location.exists: false`, `location.mapping: null`. Before M11 this
declaration was accepted (measured on 2026-09-13 against the agent's own
test app: 201, a companion, `admit on faith`), and the engine died at
spawn on a file it could not open.

**One mapping makes the same declaration launch, and the engine opens
the mapped path.** `PATCH node-b /v1/config {pathMappings: [{from:
/srv/models, to: C:\…\node-b\mnt\models}]}` applied; a mapping with a
relative `from` was rejected with the reason. The identical declaration
was then **201**. `Runtime.modelPath` stayed
`/srv/models/Qwen3-1.7B-Q8_0.gguf` — the declaration, untouched — and
`Runtime.localPath` read `C:\…\node-b\mnt\models\Qwen3-1.7B-Q8_0.gguf`.
The engine went `ready`, its `argv` named the mapped path after
`--model` and nowhere named the declaration, the gateway listed the
alias with one ready backend, and a completion through the gateway
answered `OK` with `x_eugene_plexus.runtime: qwen-mapped`. That is §3 of
the design on one host: component-wise prefix match, POSIX `from` to
Windows `to` with the remainder re-joined on this host's separator, and
persistence of the declared path.

**The runtime → library join survives.** A second mapping, from the
library's own root (`C:\…\nas\models`, Windows-shaped) to the mount, and
a declaration of the library's own `path` for the model (`autoStart:
false` — the join, not the GPU, was under test): 201,
`Runtime.modelPath` the library's spelling, `Runtime.localPath` under
the mount, and **`GET library /v1/models?path=<Runtime.modelPath>`
found the entry**. Persisting the translated path would have broken
that lookup, and with it the metadata basis below.

**A worker with no library reaches the install's.** The dry run on
`node-b` for the library's path answered `basis: metadata` — B has no
library in its topology, found the owning node through the control
root exactly as the console hop does, and reached A's library through
`http://192.168.16.75:8179/api/proxy/library` with a `service:agent`
token it minted — and `location.sizeMatchesLibrary: true`, both sides
1,834,426,016 bytes. Before M11, every admission on a worker was
`file_size` and nothing said so.

**The Test button checks a mapping against real files.**
`POST node-b /v1/config/test` with the library-root mapping as an
override: `ok: true`, summary *"1 of 1 library model under
C:\…\nas\models reachable at C:\…\node-b\mnt\models; sizes match"*. The
same call with a `to` that does not exist: `ok: false`, error naming
the directory that is not there.

**The directory listing, on both components.** `GET /v1/directories`
on the library and on B: the starting points include `Home` and carry
no `path`; a real directory lists its one subdirectory with `host`
(`Amish_Station` — this box's hostname, the same on both because they
are the same machine) and `parent`; `hidden` is absent unless asked for;
a missing directory is 404, a file is 400, and **no token is 401** on a
component whose every other read takes a service token.

**Teardown by pid; no `llama-server` from this run survived.**

## Second execution, 2026-09-13 (later): no `controlUrl` anywhere

**55 checks, zero failures, first attempt** with gateway `687f770`
(derives the control root; contracts `5f6cd3f`). The one difference
from the run above is what the script *stopped* doing: it no longer
writes `controlUrl` into agent A's `gateway.yaml`, which every
multi-host script since M7 had done by hand while nothing in the
product set it. Two checks replace the hand-write:

- **Before anyone enrolled**, `GET gateway /v1/admin/routing` reported
  `control_root.source: agent` with `url: http://127.0.0.1:8183/` —
  the gateway had read the `control` component out of its own agent's
  topology on its first refresh, with `gateway.yaml` naming no root.
- **After both nodes enrolled**, the same view read `source: agent,
  reachable: true, nodes: 2`, and node-b's runtime was routable through
  A's gateway exactly as in the first run: `ready_backends=1`, then a
  completion served by `qwen-mapped`. Between the two, A's agent had
  enrolled and the derivation had switched from the topology's
  component to the node's own `controlUrl` — read on every refresh,
  no restart.

Everything else in this record held unchanged: the refusal, the
mapping, the argv, the join, the metadata basis through the install,
the Test button, both directory listings, the teardown.

## What this run does not cover

- **That the mapping was necessary.** Both agents can open the
  library's own path on one box, so the run shows the mapped path *was*
  opened (argv, `localPath`), not that nothing else could have been. The
  necessity half is visible only on the live two-machine install: mount
  the NAS share on `Amish_Station`, add `/models → <mount>` under
  Config → Agent @ Amish_Station, and launch from the root's console.
  That is Troy's to run; the share is his.
- **A read-only or lazily mounted share, and a Linux `to`.** The
  resolver's Linux direction is unit-tested (the separator is a
  parameter, so the same matrix runs on CI's Linux and on this desk),
  not live-tested.
- **The UI.** Every call the Config page, the picker, the mapping editor
  and the launch panel make was exercised over HTTP here with the exact
  parameters the code sends, and the components are unit-tested against
  those bodies; no browser drove them.
- **Two workers, or a `from` whose library host is a different operating
  system from this one in the live direction** (a Linux library naming
  files for a Windows engine is the live install's shape and is what
  check 7's POSIX `from` reproduced; the reverse is unit-tested only).

## Numbers

| | |
| --- | --- |
| checks | 53 pass, 0 fail, 0 notes |
| model | Qwen3-1.7B-Q8_0.gguf, 1,834,426,016 bytes, copied once, hard-linked once |
| engine ready after the mapped launch | within the 120 s budget (not timed) |
| completion | `OK`, served by `qwen-mapped` |
| admission on B for the library's path | `admit`, `fits`, `metadata`, sizes equal |
