# Row 44: move a conversation's cache before planned maintenance

Lane ENG, after rows 13 (checked updates and the drain) and 15 (the prompt
cache on disk, DI2). **High risk** (people's conversations cross the
network). Source: DI2b in `deepinfer-lessons.md` §"Later: move a machine's
conversations before maintenance" (Troy, 2026-10-20), which this row
builds as written, with two changes since: LT1 (TLS between machines) now
exists, so the copy is encrypted; and row 50's machine-port tunnel shows
the transport.

## 1. What it delivers

When the owner drains a machine (row 13's drain, "Take offline for
maintenance"), the conversations its runtimes hold are saved (row 15),
the ones worth moving are copied to replicas on other machines and
restored there, and their next turns continue without rereading the whole
prompt. The rest reread, as today.

## 2. Design (DI2b's shape)

1. **Save:** the drain saves each conversation's slot (row 15's save).
2. **Choose:** the gateway picks each conversation's new replica among
   those with the same model file, engine build and cache type (row 15's
   key), and moves a conversation only when its estimated copy time
   (file size ÷ the measured link speed) beats its estimated reread time
   on the target (row 14's prefill fit). Most recently used first; a time
   budget for the whole drain (default 2 minutes).
3. **Copy:** the source agent sends the slot file to the target agent over
   the machine port (LT1's TLS, pinned; the target's node token), in 16 MiB
   chunks with a SHA-256 check (LS10's pattern), into the target's private
   cache folder.
4. **Restore and repoint:** the target's driver restores it into an idle
   slot on the next turn (row 15's restore); the gateway's affinity table
   moves the conversation to the target.
5. **Cleanup:** the source deletes its copy after the move; the target's
   copy expires under row 15's rules.

**Measure first** (DI2b's list): whether a slot file restores on another
machine with the same build (and across GPU vendors), and copy plus
restore time against a reread on the fastest link here. If restores do
not carry across machines, the row stops at the measurement and says so.

## 3. Repositories

agent (send and receive over the machine port), inference-driver (save,
restore, the list of slots), gateway (choosing, affinity), specs (the
transfer route in `agent.yaml`; acceptance).

## 4. Tests that fail before

- agent `test_cache_transfer.py::test_a_slot_file_crosses_the_machine_port_checked`
  and `test_a_mismatched_key_is_refused_by_the_target`.
- gateway `test_drain_moves.py::test_only_conversations_cheaper_to_copy_move`
  and `test_affinity_moves_to_the_target`.

## 5. Acceptance (CI, Linux, about 5 minutes)

Two agents with the real llama.cpp CPU build and the tiny model: a
conversation is held on A, A is drained, the slot moves to B, the next
turn on B reports cached tokens (no full reread), and a packet capture
shows only TLS between the machines. **Sabotage:** skip the key check;
a file from another build must then be loaded and the run must fail.

**The reviewer should attack:** a conversation's file reaching a machine
its person's requests never go to, files left behind on the source,
copies outliving row 15's expiry, and the drain's time budget.

## 6. Size and risks

L, about 3 days, after rows 13 and 15. One adversarial review. Risk:
conversations on the network (encrypted, pinned, to replicas of the same
model only, deleted at the source).

**Calls:** none (DI-C4's privacy review covers row 15 and this row).
