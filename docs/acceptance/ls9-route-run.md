# LS9: the best route for this machine

Design: [library-sources-and-engines.md §6.12](../design/library-sources-and-engines.md)
(B95-B100; Troy's B54 change).

The rule is the console's (`betterAfterPreparing` in
`ui/src/lib/eligibility.ts`); its record is the console's tests in CI and one
real run of its inputs on this machine.

## Real run of record

`scripts/ls9-route-real-run.py` on Amish_Station (RTX 5090, 94 GB of RAM),
2026-10-10: **5/5 PASS**. A throwaway agent on free loopback ports installed
llama.cpp itself (as Backends would), beside the Strata v0.1.39 install kept
from LS5's real run, over `D:\ls7-share` holding the real Qwen3.8-Flash-Next
IQ2_XS GGUF (two shards, about 68 GB). The Library's judge was asked as the
console asks it.

```
PASS  R1 the Library lists the real IQ2_XS GGUF
PASS  R2 llama.cpp installed here by the agent, and Strata installed
this node: vramFreeBytes 32,091,668,480 of 34,190,917,632; ramAvailableBytes 67,553,644,544 of 100,453,961,728
  llama_cpp: runs; fit split: runs with system memory as well: about 64.54 GiB at 8,192 tokens, 29.89 GiB free on the card
  strata: after_preparation; fit fits: Strata keeps its 35.5 GB of experts in RAM: it needs about 48 GB of RAM, and this machine has 94 GB
PASS  R3 llama.cpp runs it as it is, and its own fit says part of it runs from system memory here (or it does not fit)
PASS  R3 Strata runs it after preparing it, and setup's own table says it fits here (or its low-RAM mode)
PASS  R4 so the console recommends preparing for Strata on this machine
PASSED: 0 failing check(s)
```

Not in CI: it needs the 68 GB file and this machine's card.

## Console tests (in CI)

- `lib/eligibility.test.ts`: the rule as a table (split or no as is, fits or
  low-RAM after preparing: recommended; fits or tight as is, tight or no
  after preparing, a fit not estimated, an engine not installed: not), and
  the why in each engine's terms.
- `components/EligibilityDot.test.tsx`: the line beside the dot.
- `app/library/page.test.tsx`: the model page asks with preparing chosen,
  Strata's Prepare shown once, *Run now with llama.cpp* one choice away; no
  question when llama.cpp fits on the card.

## Sabotage

`scripts/ls9-sabotage.py`: **9 caught, 0 escaped** of 9, after one fix: *an
unestimated fit counts* escaped because an unestimated fit in the test
carried no verdict; a test now gives one that carries `split`, and the
re-run caught it. UI suite 1,843 passed; tsc, eslint and prettier clean.
