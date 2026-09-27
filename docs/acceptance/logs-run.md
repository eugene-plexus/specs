# Every machine's log from one console: the run

**2026-09-27.** Troy: *"Like a Docker environment, I should be able to read
all node logs from the UI. That will give us both better visibility into
debugging."* It came from Amish_Station an hour earlier: a model start
stopped "without error or explanation", and the one file that said why was
readable only by SYSTEM and Administrators.

Troy took all four calls as recommended:
1. every line stamped at receipt;
2. tokens and keys masked on the way out;
3. the updater's log included;
4. the fixed 10 MB × 5 per machine kept.

The same change fixes the defect the investigation found: **Start** on a
model whose load had failed did nothing.

**Results:**
- The live run (`scripts/logs-acceptance.sh`): **21 of 21, first execution**.
  With the Start defect put back, it fails the two checks that name it (§3).
- The sabotage pass (`scripts/logs-sabotage.py`): **28 of 28 caught, first pass**.
- The agent suite passes (1,396), and so does the UI suite (1,270).

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `4a89511` | `GET /v1/logs`, `GET /v1/logs/stream`, `LogLine`, `LogPage` |
| `agent` | `9bf6985` | the stamped stream, reading, following, masking; Start after a failed load |
| `control` | `40ec143` | regenerated |
| `ui` | `5506613`, dist `7f62539` | the Logs page, the Inference link |

---

## 1. What was built

- **One stream per machine, as before; now every line is stamped.** The
  agent's tee already wrote its own lines and every supervised child's to
  `logs/agent.log`. Each line now reads
  `2026-09-27T19:51:54.123Z [engine: qwen] text`: the time the agent
  received it, in UTC, and its source.
  - The agent's own lines are tagged `[agent]` and lose the local time the
    stamp replaces. The console keeps it.
  - Lines written before this change still read: their source from the
    prefix, and their time from an agent timestamp when they have one.
- **`GET /v1/logs`** returns the newest lines, oldest first, across the
  rotated files. It filters by source, text and time, and reads the files
  backwards, so a `tail` of 500 reads the end of one file and not all 60 MB.
- **`GET /v1/logs/stream`** follows the log over SSE. It sends a keep-alive
  every 15 s, and counts the lines a follower too far behind loses rather
  than growing without bound.
- **Masking:** JWTs, `sk-…`, `hf_…`, GitHub tokens, and anything after
  `Bearer ` become `[redacted]` on the way out. The file keeps them as
  written; §2 check 6 proves the mask is what hid them.
- **Access:** operator-only. No service credential opens it.
- **The updater's log** is a source served only when named. It has no stamps
  to place it among the rest.
- **The Logs page:**
  - **Where it is:** on the install root, every machine on one timeline, each
    line naming its machine; and on each machine under Agents, that machine
    alone.
  - **Controls:** Source, a text filter, how many lines, Follow, Download.
  - **Its follow never loses or repeats a line.** It opens before the
    history is read and holds what arrives, so a line written while the
    history is on its way appears once.
  - **A machine that does not answer** is named, in its own words.
- **Inference** links each model we supervise to its engine's lines:
  "what its engine said" when it stopped or crashed, "its log" otherwise.

**Start after a failed load.** A load that fails stops the runtime (R3.6)
and keeps its record, so its error stays readable. `is_running` and
`add_and_start` both read "has a record" as "running". So Start answered
*"already running; nothing to do"* and started nothing, and Restart was
the only way back. Now:
- `SupervisedProcess.supervising` says whether the supervision loop is still
  going;
- Start on an ended loop drops the record and plans afresh.

## 2. The live run

Two agents run on this box (M7's shape, ports +100). A holds control,
gateway and library; B is a worker that trusts the llama-server directory.
Both are enrolled, and everything is read from A's console.

| # | Check |
| --- | --- |
| 1 | Every port is free and no ambient `EUGENE_PLEXUS_*` variable is set; a Library folder holds a model file that cannot load |
| 2 | The UI is built from this tree, and the export carries `/logs` |
| 3 | Both agents are enrolled, with a session from each sign-in |
| 4 | A's own log: 265 lines, **every one stamped**; sources agent, control, gateway, library; the agent's lines carry the stamp and no second local time |
| 5 | B's log **through the node hop**: B's own 49 lines, source `agent` only, none of A's; 401 with no credential, at B and through the hop |
| 6 | A JWT-shaped string in a request to B comes back `[redacted]`, **while the file holds it as written** |
| 7 | A follow through the hop is open, and gets a line B writes after it opened |
| 8 | A model whose load fails: `crashed`; its engine's own lines by source from A's console (`llama_server: exiting due to model loading error`); **Start is a new attempt**, and the model really spawns again |
| 9 | The browser: all machines, one machine, the engine's lines, and a live line, 4 of 4 |

## 3. The reproduction

With `is_running` put back to "has a record", the same run fails:

```
FAIL  Start answered: {"scheduled":false,"delayMs":0,"message":"Engine runtime 'broken' was already running; nothing to do."}
FAIL  no second spawn: 2026-09-27T20:32:24.056784Z / 2026-09-27T20:32:24.056784Z
```

That is the defect as Troy met it, produced by a real llama-server failing on
a real bad file.

## 4. What the sabotage pass took

There was one change before it ran. In `read()`, `since` was checked twice:
in the filter, and in the early stop that makes it cheap. A sabotage of
either would have escaped, because the other still held. Only the early stop
is left: lines are stamped at receipt and read newest first, so the first
line older than `since` ends the scan.

## 5. Not proved

- **Amish_Station and the NAS container have not run it.** They get it with
  the next update. After that, this machine's log is readable from the NAS
  page.
- **A follow that falls behind** was only tested by a unit test with a queue
  of two.
- **Lines from before stamping** read without a time, except the agent's
  own. On an existing install they sort among the rest by where they are in
  the file.
