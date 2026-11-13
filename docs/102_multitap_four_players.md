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
other index answers 0). `game/four_pads` is the demo: four players, four
sprites, each moved by its own pad, with a lamp per player that is lit while
that pad holds a button and absent while that pad is not connected.

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

Tap slot 4 (`$4017` bit 1) is not read: four players is the scope.

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
| MT-7 | WRIO.7 is back to 1 after the read (the H/V latch works) | `$2137`-latched counter changes after the read (see §7) |
| MT-8 | per-frame cost measured both ways; absent path is a flag test; present path < 2 scanlines (2,728 mc) | master clock at exec breakpoints |
| FP-1 | demo: each sprite moves only with its own pad, both directions per axis | OAM low table |
| FP-2 | demo: lamps show connection (P3/P4 absent without a tap) and pressed state | OAM tile/Y, screenshot |
| FP-3 | demo: CHR/palette uploads are the blob, byte for byte | VRAM / CGRAM |

## 4. Resource claims

* **DP (feature `mtap`)**: `mtap_on` 2 B; `inp3_cur`/`inp3_prev`/`inp3_press`
  2 B each; `inp4_cur`/`inp4_prev`/`inp4_press` 2 B each — 14 B, global.
* **Registers**: one `[[claims.reg]]` naming `JOYSER` (`$4016`, span
  `$4016-$4017`) and `WRIO` (`$4201`) — two names added to
  `REGISTER_FOOTPRINT`. Only `mtap` writes either port in the live tree
  (verified by grep: zero `$4016`/`$4201` write sites before this lane).
* **Address window**: `$4016-$4017` added to the substrate's `io_allowed`.
* **`$4201` contract**: WRIO is `$FF` at every exit of `mtap_init` and
  `mtap_read`; bit 7 is 0 only inside `mtap_read`'s 16-clock window.

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
slots behind a detected tap that hold no pad read as nothing pressed.

**D7. The auto-read race.** Measured in the harness spike (§7.1): a manual
read that starts in VBlank before the auto-read has begun corrupts every
pad behind the tap. `mtap_read` therefore, when it finds itself in VBlank
with `$4212` bit 0 clear, waits past the latest auto-read start (H=95.5 of
line 225) before spinning on bit 0. Out of VBlank the auto-read is over and
the guard costs one `bpl`.

**D8. btn/btnp.** `pad_btn` / `pad_btnp`: A16 = button mask, X = player
0-3; returns A = word AND mask (Z set when none); any other X returns 0. No
compiler exists to validate the index at build time, so the check is at run
time.

**D9. WRIO.7 and the H/V latch.** The select edge latches the counters as a
side effect, and a `$2137` read inside the 16-clock window would not latch.
`mtap_read` runs in the main thread at the top of the frame; a rail that
also reads `$2137` from a mid-frame IRQ (`shg_cam`, `sit_cam`) must not
compose `mtap` with a seam inside that window. Stated, not enforced — no
claim class describes "port 2 pin 6 is a select line". `four_pads` composes
no IRQ.

**D10. Per-pad presence.** Mesen models an empty tap slot (§7.1), but
fullsnes does not document what a standard pad returns after its 16th bit,
so a presence bit would rest on an undocumented behaviour. *Not built*: the
demo's "connected" is tap-level (P3/P4 lamps exist only with a tap).

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
