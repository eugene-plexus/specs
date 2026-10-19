# MR8 memory suggestions: the run of record

Design: `docs/design/workbench-memory-and-documents.md` (its header lists the calls made). The measurement
that set which models suggest by default is [`m-memory-measurement.md`](m-memory-measurement.md).

## Acceptance of record (real processes, two people and the owner)

`workbench/scripts/mr8-suggestions-acceptance.py`, on Amish_Station, 2026-10-18: a real Workbench, a real
gateway and inference-driver (the working trees with this slice's changes), llama.cpp b11719 on the 5090
with Qwen3.6-35B-A3B UD-Q4_K_M (window 16,384), a stub outside account, two recording proxies (what
Workbench sent the gateway, what reached the engine), Ada, Bo and the install's owner signed in, ports
8460-8469, every ambient `EUGENE_PLEXUS_*` variable cleared. **30 passed, 0 failed.**

```
0. PASS no ambient EUGENE_PLEXUS_* reaches a child; ports 8460-8469 free
1. PASS gateway routes mr8-local, mr8-outside; Ada, Bo, owner sign in; localities; window 16384
2. PASS nobody's default turns it on for a model that was not measured; Ada chose Suggest notes
3. PASS the real model answered; a suggestion call reached the gateway within 240 s of quiet
   PASS constrained (json_schema), no tools, not streamed
   PASS her words only: not the model's answer, not the fenced paste
   PASS the same request reached the engine, with its template told not to think
4. NOTE suggested: 'Wants answers in metric units.', 'Is a beekeeper in Oslo.'
   PASS each quotes her; none holds the password or the paste's payload; none is a note yet;
        a new chat is sent none of them
5. PASS Keep makes a note; Dismiss turns the other away; the kept note is in a new chat's system
        message at both hops; the store keeps no turned-away words (stems only), the log no words
6. PASS Bo's inbox and notes are empty; 404 on every one of Ada's ids (keep, dismiss, edit);
        his chat (learning off) made no suggestion call
7. PASS the owner, with ownerReadsChats on, gets 404 on Ada's suggestions and an inbox of their own
8. PASS the outside model's suggestion call holds her words and none of her notes
9. PASS Workbench's log holds no password, job or suggestion text, and says what the calls came to
10. PASS no owned port still listening
30 passed, 0 failed
```

## What the runs before it found

- **The driver did not tell llama.cpp to stop thinking.** The gateway forwards `reasoning_effort` only to
  a backend that lists it, and a llama.cpp backend did not; a fresh driver also did not yet know its
  backend was llama.cpp. Now the driver lists `reasoningEffort` for a backend `/props` says is llama.cpp,
  sends `none` as `chat_template_kwargs.enable_thinking: false`, reports every other effort as not
  honoured (named in the ignored-settings header), and asks `/props` before deciding when no poll has.
  Hosted APIs are never asked. Measured beside it: the Qwen models thought through the whole budget on
  31-100% of calls without it, 0% with it.
- **Two checks read too early or too widely**, and were changed to observe their subject: the window
  waits for the driver's probe (a miss is cached while the engine loads), and "Bo's chat made no call"
  looks for Bo's words rather than counting every call (Ada's later chats are read in that window).

## Unit and component checks

`workbench/tests/test_memory_suggest.py` (the rules, the review's cases), `test_memory_learn.py`
(the learner and routes against a fake gateway, two people), `web/src/components/MemorySuggestions.test.tsx`;
`inference-driver/tests/test_reasoning_and_local_samplers.py` (effort `none` to llama.cpp, other efforts
and other backends, a driver nobody polled). One adversarial review of the suggestion writer (2026-10-18):
ten findings, each fixed with a test; none open.
