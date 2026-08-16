# 46 — The falsification harness (`make falsify`)

> Status: LIVE — `make falsify` — the plant contract, why a plant that no-ops used to read as a pass, and what the harness does NOT do

## 1. Why

AGENTS.md lists *"trusting a green test you have not tried to break"* as an
anti-pattern, and this repo does try: `tools/falsify_*.py` are hand-rolled
plant scripts, one per area. The ritual keeps failing in the **same** way,
and the failure is not that a plant does not fire — it is that **the plant
never reaches the thing under test, and nothing says so.**

Three instances in one round of work alone. The worst left its test **GREEN**:

> The plant swapped a file in with `shutil.copy2`, which **preserves mtime**.
> `make` saw nothing newer and skipped the rebuild. The test then ran against
> the OLD binary and passed — while the script's `assert old in src` guard sat
> there quietly confirming the source had been edited. The guard was true. The
> conclusion drawn from it was false. It was caught only by md5'ing the
> artifact by hand.

## 2. The distinction the harness exists to draw

| | meaning | response |
|---|---|---|
| **failure of the TEST** | the assertion cannot see this defect | strengthen the test |
| **failure of the PLANT** | the defect never reached the assertion | fix the plant |

These call for **opposite** responses, and a harness that conflates them turns
a broken plant into "the gate is fine". `tools/falsify.py` reports them in
separate sections and never lets one masquerade as the other.

## 3. The sequence — every step checked

```
0. baseline    build the artifact; record md5_before.
               A baseline that will not build cannot falsify anything.
1. snapshot    the target file's bytes, IN MEMORY.
               Restore is by copy, NEVER by `git checkout` — a git restore
               silently discards uncommitted work wrapped around the plant.
2. patch       `old` must be present. Absent -> PLANT-NOT-APPLIED.
3. REBUILD     and require md5(artifact) != md5_before.
               *** THE STEP THAT WAS MISSING EVERYWHERE. ***
               Unchanged -> PLANT-DID-NOT-REACH-ARTIFACT, and the tests are
               NOT RUN: a green result off a stale binary is worse than no
               result. Every write stamps mtime forward first, so the copy2
               case cannot recur; the md5 check is the backstop that does not
               depend on getting that right.
4. run         the named tests. Expected RED.
               Green -> TEST-BLIND, the finding this exercise is for.
5. restore     write the snapshot back, rebuild, require md5 == md5_before.
               Not returning -> RESTORE-INCOMPLETE, reported loudly, tree
               left dirty ON PURPOSE. A harness that hides a failed restore
               is worse than one that never restored.
```

`expect="build-fails"` covers gates that live in the assembler (a ca65
`.error`, an allocator refusal): the *rebuild* must fail and its output must
contain `build_names`. A build that fails on **something else** is
`PLANT-BUILD-FAILED-UNNAMED` — because "the build broke" does not demonstrate
that the gate saw anything, the same distinction
`tools/falsify_col_map.py` already drew.

## 4. Using it

```bash
make falsify                        # every plant set under tools/plants/
make falsify SET=col_map_kernel
make falsify ONLY=binding-CM_FLAGS
python3 tools/falsify.py --list
```

Exit 0 iff every selected plant **FIRED** and the tree restored **exactly**.

A plant set is a module under `tools/plants/` exposing `PLANTS: list[Plant]`.
`why=` is **required** by the constructor — a plant whose realism nobody
stated proves little, and the summary prints it beside every finding.

**`make falsify` is deliberately NOT in `make gates` and NOT in the push
set.** It plants defects into the working tree and rebuilds ROMs, so it costs
minutes and must not run beside a suite. Run it when you add a gate, when you
change an assertion a plant targets, and before you land.

## 5. What was carried over, and what was authored directly

**Read the inventory from the tool, not from here: `tools/falsify.py --list`.**
This section explains the two CATEGORIES; the population grows with every rail
that ships a plant set, and a number written down here ages fast. (It did: the
list below said "two sets" from the day it was written, which was true of the
*carried-over* pair and read as the whole of `tools/plants/`. By the time
anyone checked, the directory held **15 sets / 60 plants** and this paragraph
was the only place that still implied two. Restated as a rule rather than a
count.)

### 5.1 Carried over from a hand-rolled script — two, and only ever two

These are the sets that existed as standalone `tools/falsify_*.py` scripts
before the harness and were moved onto it:

- `col_map_binding` — col_map's six required binding symbols, `build-fails`,
  ca65 must **name** the missing symbol. From
  `tools/falsify_col_map_binding.py`.
- `col_map_kernel` — two kernel defects, `test-red`. From
  `tools/falsify_col_map.py`.

**The hand-rolled scripts stay.** `falsify_col_map.py` carries thirteen plants
and accumulated commentary worth more than the move — P12 and P13 in
particular record two assertions that were *measured green* against real
defects and then strengthened. Deleting that would trade evidence for tidiness.

`tools/falsify_m7s_binding.py` is a third hand-rolled script and has **no**
`tools/plants/` counterpart.

### 5.2 Authored directly as plant sets — everything else

The other thirteen were written as plant sets from the start, one per rail, as
part of that rail landing. That is now the default: a rail ships its plant set.

Enumerated at one point in time (`tools/falsify.py --list`, 15 sets / 60 plants
— the count is what ages, the shape does not):

| set | plants | what it plants |
|---|---|---|
| `racer` | 7 | day/night, off-road drag, kerb palette, the kerb-cycle *anti*-plant, pause, lean, the blue coldata plane |
| `m7x_rail` | 7 | stream blob bank, seed VMAIN, diagonal fall-through, town VRAM pin, swap-at-arm, town input level, post-return resync |
| `col_map_binding` | 6 | the six required binding symbols (`build-fails`) |
| `split_h_persp_demo` | 5 | repeat bit, band-2 camera streaming, origin folding, band-2 origin pin, zoom-floor clamp |
| `split_v_demo` | 4 | W12SEL band, camera-B folding, diagonal table repoint, OBJ-clip TMW bit |
| `split_h_matrix_demo` | 4 | repeat bit, live offset, both-channels-on-one-table, init contract |
| `split_h_demo` | 4 | top-band layer, band-table drift, toggle disarm, matrix repoint |
| `brawler` | 4 | name bit, OBSEL gap, hit latch, anim clock reset |
| `stomper_rail` | 3 | bounce, kill, slow-fall damage |
| `split_v_seamtrial` | 3 | triangle turn, bevel cross-section, viewpoint write |
| `split_h_persp3_demo` | 3 | third band, second seam, live slot |
| `scroll_run` | 3 | page-1 source, one-way stand, camera high clamp |
| `jumper_rail` | 3 | landing snap, terminal clamp, jump edge-gate |
| `sprite_game` | 2 | collision range, per-frame restaging |
| `col_map_kernel` | 2 | bank term, transposed axes |

## 6. What the harness does NOT do

1. **It does not know whether your plant is a REALISTIC defect.** A plant that
   breaks something no reasonable change would break proves little. That
   judgement stays with the author; `why=` is the place to state it.
2. **An artifact md5 that CHANGES proves the plant reached the build, not that
   it reached the code path the test exercises.** Step 4 is what covers that,
   and it is why a still-green test is reported as a finding rather than
   swallowed.
3. **It cannot restore an uncommitted edit made by another process** while it
   holds the tree. Do not run it beside a suite.
4. **It is not crash-atomic.** A SIGKILL mid-plant leaves planted text on
   disk; `git status` shows it and `git checkout -- <file>` fixes it — the
   same recovery `falsify_col_map.py` documents.
5. **It does not discover plants.** Somebody still has to think of the defect.

## 7. Verified

- 8/8 carried-over plants fired; `microzero.sfc` md5 restored exactly
  (`e45ddeabac4218cd71709da7b9fcc849`) after the binding set.
- `tests/test_falsify_harness.py` — 15 tests. Every verdict is reachable
  against a stubbed build, **plus one end-to-end run against the real
  `make toy`**: a comment-only edit to `engine/toy/main.asm` (a comment emits
  no bytes, so the ROM cannot move) must produce
  `PLANT-DID-NOT-REACH-ARTIFACT`. That is §1's bug in miniature, run on
  every suite.
