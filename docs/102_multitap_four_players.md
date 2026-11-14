# 102 — Four players: a four-pad adapter in port 2

> Status: PREFLIGHT + LANDING NOTE for the `claude/multitap-4p` lane. §1–§6 were
> written before any engine code (CLAUDE.md "decompose, then build"); §7 is
> filled in as the work lands and records what was measured.
>
> Vocabulary: "the tap" is a four-pad adapter of the kind fullsnes calls the
> MP5 ("Five Player Adaptor", `docs/reference/fullsnes.txt` L3405 in the
> owner's reference tree). This file names no product.

## 0. What this is

`engine/features/mtap` — a global, opt-in feature — detects a tap in
controller port 2 once at boot and, while one is present, reads **players 3
and 4** every frame with the same edge convention `input` / `input2` use for
players 1 and 2. It also supplies `pad_btn` / `pad_btnp`, the
player-indexed "is this button held / newly pressed" query (player 0–3, any
other index answers 0), and `pad_here`, the player-indexed "is this pad
connected" query, answered from a per-pad presence census (D10). `game/four_pads`
is the demo: four players, four sprites, each moved by its own pad, with a
lamp per player that is lit while that pad holds a button and absent — lamp
and token both — while that pad is not connected: P1 and P2 in their ports,
P3 and P4 behind the adapter, each on its own.

A rail that does not compose `mtap` is **byte-identical to what it was**.

## 1. The brief, mapped onto this tree

The brief was written against the older SuperForge lineage (local `main`,
`5eb101cd`: `engine/nmi_handler.asm`, `engine/engine_state.inc`, the Lua
compiler, `btn`/`btnp` engine IDs 3/4, `tutorials/`). **`origin/main` is a
different repository** — `git merge-base main origin/main` is empty — and it is
the lineage every active workstream here (`claude/forge-gt*`, `game/forge_gt`)
is built on, so it is the base (`aee087f0`). The mapping:

| brief | this tree |
|---|---|
| `engine/nmi_handler.asm` reads `$4218`/`$421A` | `engine/features/input` / `input2`, each a global feature with a DP triple, read once per frame from the rail's main loop |
| state "in work RAM, declared in `engine_state.inc`" | claims in `engine/features/mtap/feature.toml`; the allocator places them (see D4) |
| `btn(b, p)` / `btnp(b, p)`, compiler range validation | there is no Lua and no compiler: `pad_btn` / `pad_btnp` ASM routines, player index range-checked at run time (D8) |
| Lua demo, tutorial/template | an ASM rail, `game/four_pads` (lesson 04's shape, forked from `sprite_game`) |
| `infrastructure/test_harness/mesen_runner.py` | `vendor/mesen_runner.py` (config) + `vendor/machine.py` (the lockstep driver every new test uses) |
| `docs/reference/` input page | this file + `docs/09` §3/§3.1 rows + the capability envelope row |
| commit the rebuilt `.sfc` | `build/` is untracked here by design (`.gitignore`); the render is taken from a fresh build of the committed tree |

## 2. The hardware sequence (fullsnes, owner's tree, line numbers cited)

**Ports.** `$4016` write bit 0 = OUT0, the joypad strobe/latch, both ports
(L2970-2977). `$4016` read = port 1 data; `$4017` read bit 0 = port 2 pin 4,
bit 1 = port 2 pin 5, bits 2-4 always 1; reading generates the port's clock
pulse (L2986-2994). `$4016`/`$4017` accesses take the slow 12-master-cycle
bus (L111-113). `$4201` WRIO bit 7 = port 2 pin 6, open collector, power-on
`$FF` (L117, L2996-3001).

**Detection** (L3432-3445), port 2 is n=1:

    [4016h].Bit0=1                    ;strobe on (forces the tap's bit 1 = 1)
    read 8 bits from [4017h].Bit1 -> A
    [4016h].Bit0=0                    ;strobe off
    read 8 bits from [4017h].Bit1 -> B
    present iff A = $FF and B != $FF  (B is pad data: no pad can hold all
                                       four d-pad directions)

A plain pad does not drive pin 5, so A = B = $00 (L3440).

**Per-frame read** (L3412-3426). Auto-joypad has already strobed every pad
and clocked 16 bits from each pin: with WRIO.7 = 1 the tap routes its slots 1
and 2 to pins 4 and 5, so **`$421A` = tap slot 1, `$421E` = tap slot 2**
("Player 3 data will obviously show up in JOY4", L3422). Then:

    [4201h].Bit7=0                    ;select slots 3/4
    read 16 bits from [4017h].Bit0    ;slot 3 (bit 1 would be slot 4)
    [4201h].Bit7=1                    ;select slots 1/2 again — for next frame
    no further access this frame      ;let the slow 0->1 edge settle (L3421)

Slots 1/2 must be read before 3/4 (L3426-3430), which the auto-read already
guarantees.

**Auto-read timing** (L2955-2962): starts between H=32.5 and H=95.5 of the
first VBlank line and runs 4224 master cycles; `$4212` bit 0 is set for that
window. Reading or clocking the ports inside it corrupts both.

**Side effect on the PPU counters** (L1365-1369): a 1->0 edge on WRIO.7
latches the H/V counters, and `$2137` only latches while WRIO.7 is 1. See D9.

### Player numbering (decided, D3)

| player | `pad_btn` index | source | harness override index |
|---|---|---|---|
| P1 | 0 | port 1, `$4218` (`input`) | 0 |
| P2 | 1 | port 2 / tap slot 1, `$421A` (`input2`) | 1 |
| P3 | 2 | tap slot 2, `$421E` (`mtap`) | 2 |
| P4 | 3 | tap slot 3, manual `$4017` bit 0 under WRIO.7 = 0 (`mtap`) | 3 |

Tap slot 4 (`$4017` bit 1) is not read: four players is the scope. The
harness column is the `Machine.advance` position (`padN` = N-1); Mesen's
own override index differs only when port 1 is empty, and the harness maps
it (§7.4, audit-2 N1).

## 3. Acceptance criteria and test IDs

| id | criterion | surface read |
|---|---|---|
| MT-H1 | the harness can put a tap in port 2 and drive slots 1-4; the default (no tap) config is unchanged | ROM-side WRAM of the hardware read, both configs |
| MT-1 | tap present -> `ES_MTAP_ON` set; absent -> clear | DP flag, booted both ways |
| MT-2 | each of P1-P4's buttons lands in that player's cur/press words, and only there | DP words, one pad at a time, every button bit |
| MT-3 | edge detection: press = cur AND NOT prev, held press is one frame | DP press words across a hold |
| MT-4 | no tap: P3/P4 read nothing even with overrides latched on slots 2-3 | DP words |
| MT-5 | P1/P2 identical with and without a tap (the `input`/`input2` words) | DP words, both configs |
| MT-6 | `pad_btn` / `pad_btnp` answer per player 0-3 and 0 for 4+ | the demo's lamp/sprite OAM and a probe of the routine's result |
| MT-7 | WRIO.7 is back to 1 after the read | the slot routing of the NEXT frame's automatic read: P4 held alone must not appear in P2's or P3's word (WRIO.7 left low would route slots 3/4 to `$421A`/`$421E`), then P2/P3 held must land in their own words — DP words. (The H/V-latch side effect, D9, is not what the test reads) |
| MT-8 | per-frame cost measured at both call timings; absent path is a flag test; a call after the automatic read < 2 scanlines (2,728 mc) on EVERY call, census calls included; a call at the top of VBlank waits the read out and is bounded | master clock at exec breakpoints, `four_pads` and `mtap_probe` |
| MT-9 | per-pad presence: `ES_MTAP_PADS` / `pad_here` name exactly the connected pads for every port/slot combination the harness drives (36), at boot and after the periodic census; the census re-reads once a period in two halves; without the adapter it is the boot census only | DP word + the probe's recorded `pad_here` answers; a poked word and its restoration call by call |
| FP-1 | demo: each sprite moves only with its own pad, both directions per axis | OAM low table |
| FP-2 | demo: a player's token and lamp exist only while its own pad is connected (seven port/slot configurations), the lamp lit while it holds a button | OAM tile/Y, screenshot pixels (full adapter, and a mixed one: P1, P2, P4) |
| FP-3 | demo: CHR/palette uploads are the blob, byte for byte | VRAM / CGRAM |

## 4. Resource claims

* **DP (feature `mtap`)**: `mtap_on` 2 B; `inp3_cur`/`inp3_prev`/`inp3_press`
  2 B each; `inp4_cur`/`inp4_prev`/`inp4_press` 2 B each; `mtap_pads` 2 B
  (presence, D10) and `mtap_tick` 2 B (the census clock) — 18 B, global.
* **Registers**: one `[[claims.reg]]` naming `JOYSER` (`$4016`, span
  `$4016-$4017`) and `WRIO` (`$4201`) — two names added to
  `REGISTER_FOOTPRINT`. Only `mtap` writes either port in the live tree
  (verified by grep: zero `$4016`/`$4201` write sites before this lane).
* **Address window**: `$4016-$4017` added to the substrate's `io_allowed`.
* **`$4201` contract**: WRIO is `$FF` at every exit of `mtap_init` and
  `mtap_read`; bit 7 is 0 only inside `mtap_read`'s clock window (12 clocks;
  17 on a player-4 census call) and `mtap_init`'s boot census.

## 5. Gaps and decisions (recommendation taken where reversible)

**D1. Base.** origin/main vs local main — unrelated histories. *Taken*:
origin/main; the old lineage has nothing under `game/`, `allocator/`, and the
fold target named by the brief's out-of-scope list (`game/forge_gt/`) exists
only on origin/main's lineage. Reversible only by redoing the lane.

**D2. Feature shape.** (a) more claims on `input`; (b) one sibling feature
`mtap` that depends on `input` + `input2`; (c) two features. *Taken: (b).*
`input2/feature.toml` already states why claims on `input` re-pin
`microzero`; P3/P4 only exist behind a tap, so their state and the detection
are one feature, and `pad_btn` needs all four players' words, hence the
`depends`.

**D3. Which tap slots are P3/P4.** Slots 2 and 3, the first two the auto-read
and the cheapest manual read reach (table above).

**D4. Where the state lives.** The brief says work RAM because DP was full in
the old engine. Here the allocator packs DP per composition and refuses an
over-budget one, and `input`/`input2` keep their words in DP so game code
reads every player with one `lda z:`. *Taken: DP*, 14 B, paid only by rails
that compose `mtap`. (Alternative: a `wram` claim — placement is not
guaranteed in the low mirror, so every read becomes a long.)

**D5. The gate surface for `$4016`/`$4017`/`$4201`.** `no_literals` refuses
`$4016`/`$4017` (outside `io_allowed`) and reports `$4201` as an unnamed port.
Options: (a) `REG-LINT: ok` overrides; (b) widen `io_allowed` and name the
ports in `REGISTER_FOOTPRINT` so `mtap` *declares* them. *Taken: (b)* — the
gate's own refusal text prescribes it ("Add the name to REGISTER_FOOTPRINT
first, then declare it"), and (a) would mark an owned port "deliberately
unowned". Consequence: the reg gate's unnamed-port fixture used `$4201` as its
example; it moves to `$420D` (MEMSEL — still unnamed, no live writer in the
scanned tree).

**D6. Detection timing.** Boot only, before NMITIMEN arms the auto-read
(`mtap_init` asserts that contract). Hot-plugging the tap is not supported;
slots behind a detected tap that hold no pad read as nothing pressed (and
`pad_here` says they are empty, D10). **Untested (audit-1 F8):** fullsnes'
second condition, `B ≠ $FF` — "pin 5 stuck high is not an adapter" — is in
the code (`mtap_init`, `beq @absent` after `cmp #$FF` on byte B) but no
harness device presents B = $FF, so no test can see it: an audit plant that
removed it left every test green. It stands on fullsnes alone.

**D7. The auto-read race.** Measured in the harness spike (§7.1): a manual
read that starts in VBlank before the auto-read has begun corrupts every
pad behind the tap. `mtap_read` therefore checks `$4212` first: out of
VBlank the read is over (one `bpl`); busy, it waits for the end; in VBlank
and idle it latches the V counter (`$2137`, `$213F`, `$213D`) — on the first
VBlank line (225) the read has not started yet and it waits for the start
and then the end; on any later line it is over (it lasts 4224 mc, just over
three lines). *First built as a fixed ~480 mc spin* and measured paying it
every frame on `four_pads` (whose main thread always resumes in VBlank after
the read), so the V-counter test replaced it (§7.2). Stated limit: 225 is
the first VBlank line with SETINI overscan clear; no rail sets overscan
(docs/94 R1 is unbuilt). Second stated limit (audit-1 F5): **the automatic
joypad read must be enabled** — with NMITIMEN bit 0 clear, a call on line 225
waits in `@wait_start` for a read that never starts, forever. `mtap_read`'s
contract says so; the wait is not bounded (a bound would cost every waiting
call a counter, and the only caller that can arrive there is one that has
broken the contract).

The cost of the guard's waiting path is the feature's WORST case, not its
typical one: a caller that arrives on line 225 pays the whole automatic read
(4224 mc) plus its start on top of the work — measured 6,274-6,886 mc,
4.6-5.0 lines, on `mtap_probe` (§7.2).

**D8. btn/btnp.** `pad_btn` / `pad_btnp`: A16 = button mask, X = player
0-3; returns A = word AND mask (Z set when none); any other X returns 0. No
compiler exists to validate the index at build time, so the check is at run
time.

**D9. WRIO.7 and the H/V latch.** The select edge latches the counters as a
side effect, and a `$2137` read inside the 12-clock window would not latch.
The D7 guard also latches and reads them itself (resetting the flip-flops
first, the tree's convention); every reader in the tree latches its own.
`mtap_read` runs in the main thread at the top of the frame; a rail that
also reads `$2137` from a mid-frame IRQ (`shg_cam`, `sit_cam`) must not
compose `mtap` with a seam inside that window. Stated, not enforced — no
claim class describes "port 2 pin 6 is a select line". `four_pads` composes
no IRQ.

**D10. Per-pad presence.** *Corrected 2026-11-13 (audit-1 F1).* The first
version of this decision said fullsnes does not document what a standard
pad returns after its 16th bit, and dropped per-pad presence on that
premise. **That was wrong.** fullsnes documents it twice: the Joypad bit
table, "17th and up — Padding (always 1=Low) (or 0=High when no pad
connected)" (owner's tree L3181), and the controller-ID table, "0000.00000000
No controller connected / 0000.11111111 Normal Joypad" (L3021-3022). This
lane's own Level-0 harness test already asserted the trailing 1s. *Built*:

* **The bit.** One clock past the 16th: 1 = a pad, 0 = nothing there. Port 1
  is `$4016` bit 0; port 2's pin 4 (a plain pad or slot 1) and pin 5 (slot 2)
  are `$4017` bits 0/1; slot 3 is `$4017` bit 0 under WRIO.7 = 0. The
  harness answers fullsnes for every combination of empty port 1, empty port
  2, and empty adapter slots (`test_mtap_harness.py`, Level 0, 36 configs).
* **When it is read — the cost decision.** The owner's standing rule is that
  this CPU cannot afford new per-frame work, so presence is a CENSUS, not a
  per-frame read. `mtap_init` takes it at boot (a fresh strobe, 17 clocks of
  every line; auto-read still off) and re-latches every pad before leaving.
  With an adapter, `mtap_read` re-takes it once every 33 calls (the
  countdown `MTAP_CENSUS_EVERY` = 32 runs out on the 32nd call after a
  census's second half, and that half is the one extra call), split over two
  consecutive calls — players 1-3 on one (one more
  clock of `$4016` and of `$4017`, read before the select line drops), player
  4 on the next (slot 3's 13th-17th clocks after its 12 buttons) — because
  both halves on one call measured over two scanlines. The per-frame price
  is the census clock alone: one `dec` and one branch, **54 mc** (§7.2).
* **Without an adapter, presence is the boot census only.** The absent path
  stays the flag test it was (the brief: "no adapter → frame cost
  unchanged"), so a pad plugged into port 1 or 2 after power-on is not seen
  as connected until reset (its buttons still read — presence gates nothing
  in `mtap`). Tested as stated: a word overwritten after boot stays
  overwritten. A rail that wants hot-plug without the adapter would pay the
  census clock on the absent path too (~60 mc/frame) — not taken.
* **With an adapter, hot-plug is seen within 33 calls** (a pad unplugged or
  plugged into a port or slot; hot-plugging the ADAPTER itself is still
  unsupported, D6).
* **API.** `ES_MTAP_PADS` (bit n = player n+1, `MTAP_PAD_P1..P4`) and
  `pad_here` (X = player 0-3 → A = that player's bit or 0, Z set iff absent;
  out-of-range players answer 0). The demo draws a player's token and lamp
  only while `pad_here` says so.

**D11. P4 clocks 12 bits, not 16** (17 on a player-4 census call, D10).
fullsnes: "read any number of bits".
Bits 13-16 of a standard pad are its signature, always 0 (fullsnes' JOY
table); the next frame's automatic read strobes every slot, so the unread
four need no clocking. P4's bits 3-0 therefore read 0, a standard pad's own
value. Measured saving: four clocks, ~250 mc (2,450 -> 2,202). A device that
uses those bits (a mouse) is on fullsnes' prohibited-behind-the-adapter list.

**D12. The engine's own probe.** `pad_btn` with an out-of-range player can
only be observed from a caller that passes one, and the demo never does. So
`tests/fixtures/mtap_probe` composes the input stack ALONE (allocator-placed,
`make mtap-probe`), calls `mtap_read` at the very top of VBlank (the D7
race, on purpose) and records `pad_btn` / `pad_btnp` for players 5..0.

## 6. Order of work

1. Harness: tap config + four-pad drive in `Machine`, proven on a probe.
2. Gates: `io_allowed`, `REGISTER_FOOTPRINT`, fixture retarget.
3. `mtap`: detection (step), then P3, then P4, then `pad_btn`.
4. `four_pads`: skeleton boot, sprites, movement, lamps.
5. Tests, fault plants, cost measurement, registration, docs.

## 7. Measured (filled in as it landed)

### 7.1 Harness spike (pre-engine, a scratch ROM)

* `SnesConfig.Port2.Type = 4` is Mesen's `Multitap` in the shipped core:
  `HasControlDevice(4)` answers true after the load, and
  `GetAvailableInputOverrides` reports indices 0-4 live (0-1 without a tap).
* `SetInputOverrides(i)`: 0 = port 1; 1-4 = tap slots 1-4 in order —
  measured: index 1 -> `$421A`, 2 -> `$421E`, 3 -> manual `$4017` bit 0 under
  WRIO.7=0, 4 -> manual `$4017` bit 1. An empty slot (`Port2SubPorts[i].Type =
  0`) drops its index from the available set and reads 0.
* Detection on the emulator: tap present A=$FF B=$00; absent A=$00 B=$00.
* The D7 race, reproduced: the first spike started its manual read as soon as
  VBlank began and got `$421A`=`$007F` with nothing pressed and the slot-3
  word shifted — corrupted. Waiting for the auto-read to start, then finish,
  made every slot read exactly what was latched.

### 7.2 Cost (`tests/test_mtap_cost.py`, the shipped binaries)

Exec breakpoints bracketing the one `jsr mtap_read` (its label and the
instruction after it) through each ROM's labelled twin (`make fp-labels`,
`make mtap-probe`), master cycles, jsr + rts included. NTSC line = 1,364 mc.
72 calls each — more than two census periods, so both census halves are in
every sample.

**The call's cost depends on where in the frame it is made**, and both
numbers are the feature's:

| configuration | call timing | min | max | scanlines (max) |
|---|---|---|---|---|
| no adapter | any (`four_pads`) | 136 | 136 | 0.10 |
| adapter, first build (fixed D7 spin, 16 clocks) | after the auto-read (`four_pads`) | 2,976 | 2,976 | 2.18 |
| adapter, V-counter D7 guard, 16 clocks | after the auto-read | 2,450 | 2,450 | 1.80 |
| adapter, V-counter guard, 12 clocks (before presence) | after the auto-read | 2,202 | 2,202 | 1.61 |
| adapter, before presence — audit-1's measurement | **top of VBlank** (`mtap_probe`) | 6,220 | 6,528 | 4.79 |
| **adapter, as landed (presence census)** | **after the auto-read** (`four_pads`) | **2,256** | **2,626** | **1.93** |
| **adapter, as landed** | **top of VBlank** (`mtap_probe`, the worst case) | **6,274** | **6,886** | **5.05** |

The landed after-the-read histogram is 66 × 2,256 (a plain call: the 2,202
work + the census clock's 54), 3 × 2,594 (the players 1-3 census half) and
3 × 2,626 (the player 4 half). One census, both halves on one call, measured
2,666 + the first half's ~380 over two lines — hence the split (D10). The
average over a period is ~2,286 mc: presence costs ~84 mc/frame averaged,
54 of it the census clock.

**Demo timing vs the worst case.** `four_pads`' main loop resumes from an NMI
body that outlasts the automatic read, so every call arrives after it and
the D7 guard never waits (120/120 frames in audit-1). A rail whose loop can
arrive on the first VBlank line before the read starts — a short NMI body,
or none, which is `mtap_probe` on purpose — pays the guard's wait: the whole
read (4224 mc) plus its start (up to H=95.5, 382 mc) on top of the work,
**4.6-5.0 lines**. Most of that is idle spin the caller would otherwise pay
somewhere else (it cannot read any pad before the read is over), but it is
the per-frame cost such a rail sees. The probe's histogram spreads over
6,274-6,582 for plain calls (the read's start moves in 256-mc steps, fullsnes)
and 6,612-6,886 on census calls (6,612-6,854 the players 1-3 half, 6,644-6,886
the player 4 half). Those ranges are a SAMPLE, not a bound: remediation-2
re-measured 1,320 calls (40 census periods, each call classified by
`ES_MTAP_TICK` at its entry breakpoint) and saw them exactly, in three runs out
of four; the 72-call test sample and audit-2's 140 calls had shown plain calls
only up to 6,516 and 6,582. The bound is the test's 7,334 below. (The fourth
run also recorded three plain-call deltas outside every class — 410, 5,024 and
6,522 mc, the first two below the work's own floor. Audit-3 explained them:
`MesenRunner.run_to_break` sometimes stops at a PC that is neither mark, and
the cost test used to close a pair on any stop that was not the begin mark,
cutting the call short. Over 6,000 lockstep frames on each ROM every pad read
correctly in its frame, so no call skipped the read. The test now closes a
pair only on the end mark (audit-3 N7).)

The floor is the clocking: one `lda a:$4017` / `lsr a` / `rol z:` per bit is
~88 mc from bank-0 (SlowROM-speed) code, ~1,060 mc for twelve bits; P3's word
and both edges are ~450 more. A rail whose code ran from the FastROM mirror
would pay roughly a quarter less on every fetch; no rail here does. Rails that
do not compose `mtap` pay nothing — there is no call.

The tests assert: the absent path under 200 mc; a call after the automatic
read under two scanlines (2,728 mc, the brief's ceiling) on EVERY call, with
at least four census calls in the sample; a call at the top of VBlank above
the read's own 4224 mc (it waited — the guard-skipped plant drops it to
~2,256) and under 2,728 + 4,224 + 382 = 7,334 mc. The after-the-read worst,
1.93 lines, is under two but not "well under" — reported, not rounded.
PAL is not measured for `mtap_read` (the clocks are bus cycles, the same on
both; the guard's wait is one automatic read on either).

### 7.3 A finding about `input_read`, not fixed here

The probe's first run without an adapter lost a held A on P1: its loop called
`input_read` at the top of VBlank, before the automatic read had started,
and `input_read` only spins while the read is BUSY — so it read `$4218` as
the read began. Every rail in the tree calls `input_read` after
`sm_frame_sync`, i.e. after the NMI handler's work, which is far longer than
the 382 mc window, so no rail is exposed; the contract line "it must not run
inside the window auto-joypad itself owns" is what keeps it so. `mtap_read`'s
D7 guard is the stronger form of the same wait and could be shared. Left as a
stated limit (out of this lane's scope; `input` is composed by the pinned
`microzero`).

**Follow-up (audit-1 F3, deferred).** The race is real (fullsnes: reads of
`$4218-$421F` during the automatic read "will read back incorrect values";
the probe reproduced a lost button) and latent (every rail syncs on an armed
NMI whose body outlasts the window). Two things are owed, neither here: share
`mtap_read`'s V-counter guard with `input_read` (and `input2_read`), which
re-pins `microzero`, so it needs its own lane; and note the hazard in
`mtap`'s per-frame order, which names `input_read, input2_read, mtap_read` —
the exposed order for a caller that can arrive before the read starts.

**A second instance of the same class, found while remediating F1.** A rail's
FIRST `mtap_read` can come before the first automatic read has ever run
(`four_pads`' MAIN arms NMITIMEN and enters its loop outside VBlank, where the
guard reads "over"): the read then takes whatever state boot left the ports
in. With the boot census leaving slot 3 clocked past its 16th bit, that was
padding 1s — player 4 "held every button" for one frame and its token
flipped at boot (caught by `test_four_pads.py`). Fixed by re-latching every
pad at the end of `mtap_init`, which restores what detection alone used to
leave. The same first-call read of `$421E` (P3) returns whatever the register
holds before any automatic read — 0 on Mesen; fullsnes does not say for
hardware. Stated, not fixed.

### 7.4 Tests

| module | cases | ROM | surface |
|---|---|---|---|
| `tests/test_mtap_harness.py` | 85 | `tests/fixtures/mtap_harness/probe_mtap.asm` (Level 0: no engine code) | WRAM result block of a hand-run detection + read, the 17th bit of every line included, for 36 port/slot configurations; and, for the same 36, which line answers when ONE `padN` is held at a time (audit-2 N1) |
| `tests/test_mtap.py` | 51 | `make mtap-probe` | `mtap`'s DP words (presence included); `pad_btn`/`pad_btnp`/`pad_here` answers |
| `tests/test_four_pads.py` | 26 | `make four_pads` | OBJ VRAM, CGRAM 128-191, OAM, screenshot pixels |
| `tests/test_mtap_cost.py` | 3 | `make fp-labels`, `make mtap-probe` | master clock at exec breakpoints, both call timings |

Falsification: `make falsify SET=mtap` — eleven plants: the six of the first
landing (D7 guard skipped, WRIO left low, P3 edge from the level, absent path
falling through, `pad_btn`'s range answer dropped, the demo's lamp ignoring
its pad) and five for presence (the boot census dropping P4's bit, the
periodic census never running, the census's first half clobbering P4's bit,
the boot re-latch dropped, the demo ignoring `pad_here`); the D7-guard plant
also names the worst-case cost case. Each FIRED with the artifact md5 moved
and restored. The harness was planted by hand: the adapter's controller type
set to a plain pad (first landing: 6 of its 9 cases red), and an empty slot
configured as a pad (remediation: the empty-slot cases red), and the
port-1-empty index mapping dropped (`Machine._latch` latching the raw index:
remediation-2, 16 of the 36 one-index-at-a-time cases red — every
configuration with port 1 empty and at least one device behind port 2), each
restored byte-identical.

**The harness's pad indices are port positions (audit-2 N1).** Mesen counts
an empty port 1 out of its input-override indices: with `port1=PORT_EMPTY`
its index 0 reaches port 2 / slot 1 and 1-3 reach slots 2-4, while an empty
port 2 or adapter slot shifts nothing (measured for all 36 configurations).
`mesen_runner.override_index` maps the harness's fixed positions onto it and
`Machine._latch` latches through it, so `pad1` is always port 1 (nothing,
when it is empty), `pad2` always port 2 / slot 1, `pad3`-`pad5` slots 2-4, and
the input log's entries are by the same positions. With port 1 present the
mapping is the identity — the default path makes exactly the calls it made.
`MesenRunner.set_input` has no port-1 knob (its loads always put a pad in
port 1), so its indices were never shifted.

**Follow-ups, not this lane (audit-2):** N5 —
`tests/test_dma_init_forced_blank.py`'s
`test_every_observed_fire_matches_a_declared_claim` builds its failure message
with `sorted(unknown)` / `k[0]` over a set that can hold `None` (a fire whose
MDMAEN mask names other than one channel), so the assertion's own diagnosis
is lost to a `TypeError`; pre-existing. N6 — `tools/falsify.py`'s `run_plant`
restores and md5-checks only the plant's declared artifact, while
`test_mtap_cost.py`'s fixture rebuilds both `four_pads` and `mtap_probe`: a
cost-test plant declaring one leaves the other built from the planted source
(declare both, or rebuild every target a named module's fixture builds).
