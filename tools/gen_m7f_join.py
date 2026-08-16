#!/usr/bin/env python3
"""gen_m7f_join.py — mode7_flight: the per-scanline join loop, EMITTED.

Emits `m7f_join.inc`: the four sign-variant segment routines of `m7f_cam`'s
band join, 4x unrolled and software-pipelined, with the multiplier's latency
windows filled by real work rather than by `nop`s.

WHY A GENERATOR AND NOT HAND-WRITTEN ASM. The unrolled body is four
near-identical 19-instruction lines x four sign quadrants = ~300 instructions
whose ONLY interesting property is a SCHEDULE: the 65816's hardware multiplier
needs 8 CPU cycles between the write to $4203 and a valid $4216, and this loop
fills both of its windows per line with work that has to happen anyway. Written
by hand, that schedule is a comment somebody has to re-verify after every edit —
and the failure mode of getting it wrong is a SILENTLY WRONG COEFFICIENT, not a
crash: the read returns the previous product, the floor still renders, and only
the whole-table oracle notices.

So the schedule is MACHINE-ASSERTED here instead. `emit_line` counts the CPU
cycles of the instructions it interleaves into each window and REFUSES to emit
a file whose windows are under-filled (`ScheduleError`). That is the
allocator-refusal philosophy applied to instruction scheduling: an infeasible
schedule stops the build rather than shipping a plausible picture.

**A HAND EDIT TO THE EMITTED FILE IS NOT THE MAINTENANCE PATH.** It lands in
`build/`, is regenerated on every build, and is gitignored with the rest of
`build/`. Change the schedule here.

PLACEMENT PRECEDENT: `tools/gen_move_lut.py` emits `move_lut.inc` into the
rail's allocator map dir (`$(MZ_MAP)`, i.e. `build/mz/`) and
`game/microzero/scenes/race.asm:371` `.include`s it by name, with that dir
already on the ca65 include path. Emitted asm lives in `build/`, never in the
tree. `gen_mode7_explore_assets.py` does the same into `$(BUILD)/assets`.

--- THE SCHEDULE, in one place --------------------------------------------

Per scanline the join needs TWO products -- S*cos and S*sin -- because C = -B
and D = A are a negate and a copy. Each product is one 16-bit store to $4202
(which writes $4202 AND $4203, staging both operands and starting the multiply
in one instruction) and one 16-bit read of $4216. Between them, 8 CPU cycles:

  window 1  eor CSXOR ; sta PTMP                          = 8 cycles
            the sin operand, derived from the cos one by a single EOR because
            both magnitudes live in the low byte and p<<8 is untouched

  window 2  lda PROF+next ; ora CMAG ; sta PNEXT          = 14 cycles
            the NEXT line's cos operand, staged a line early. This is the
            pipelining: the next line then opens with a 4-cycle DP load
            instead of a 6-cycle long read plus a 4-cycle ORA.

--- WHAT THE UNROLL BUYS (measured) --

  loop test  cpx dp + bcc = 7 cycles, paid once per FOUR lines instead of once
             per line
  indices    inx x2 + iny x4 = 12 cycles per line become one 16-cycle advance
             per group. Those cycles were the old body's latency filler, which
             is why the pipelining above has to replace them with real work
             rather than with nops.

Deterministic: pure text assembly from the constants below -- byte-identical on
re-run, which the rebuild proof and `make falsify`'s md5 arm rest on.

Usage: gen_m7f_join.py OUTDIR
"""
from __future__ import annotations

import sys
from pathlib import Path

UNROLL = 4                      # lines per group
MUL_LATENCY = 8                 # CPU cycles between the $4203 write and $4216
                                #   (race_logic.asm:245-248 spends four `nop`s
                                #   on exactly this)

# --- the instruction cost table ---------------------------------------------
# CPU cycles at A16/I16 with DP page-aligned (D = $0000, which substrate.toml
# pins). Only the instructions this generator emits are listed; asking for one
# that is not here is a KeyError rather than a silent zero.
CYCLES = {
    "lda_dp": 4, "sta_dp": 4, "ora_dp": 4, "eor_dp": 4, "cpx_dp": 4,
    "lda_long_x": 6, "lda_long": 6, "sta_long": 6,
    "sta_abs_y": 6,
    "lsr_a": 2, "eor_imm": 3, "inc_a": 2, "adc_imm": 3,
    "clc": 2, "txa": 2, "tax": 2, "tya": 2, "tay": 2,
    # The unrolled group is ~300 bytes, which is beyond a short branch's
    # +-127 — ca65 says so as a Range error rather than silently. So the loop
    # close is an INVERTED short branch over a `jmp`, which costs 2 cycles
    # more per GROUP (i.e. half a cycle per line) and reaches anywhere in the
    # bank. Counted here rather than assumed.
    "bcs_not_taken": 2, "jmp_abs": 3,
}

SHIFT = 6                       # |A| = (p * mag) >> 6 -- see gen_m7f_factors


class ScheduleError(RuntimeError):
    """A multiplier-latency window is under-filled. Refuse to emit."""


def _win(name, ops, need=MUL_LATENCY):
    """Sum a window's cycles and REFUSE if it is short of the latency."""
    total = sum(CYCLES[o] for o in ops)
    if total < need:
        raise ScheduleError(
            f"{name}: the multiplier needs {need} CPU cycles between the "
            f"$4203 write and a valid $4216; this window fills only {total} "
            f"({' + '.join(f'{o}={CYCLES[o]}' for o in ops)}). A short window "
            f"reads the PREVIOUS product: the floor still renders and only the "
            f"whole-table oracle notices. Add work to the window or reorder "
            f"the line -- do not pad with `nop`, which is the cost this "
            f"pipelining exists to remove.")
    return total


def emit_line(k: int, cneg: int, sneg: int) -> tuple[list[str], int]:
    """One scanline of the unrolled group. Returns (asm lines, cycle count).

    `k` is the line's index within the group: it fixes the profile and table
    offsets, so no index register moves inside the group.
    """
    po, to = k * 2, k * 4               # profile byte offset, table byte offset
    nxt = (k + 1) * 2                   # the NEXT line's profile offset --
                                        #   at k = UNROLL-1 this reaches one
                                        #   past the group, which is exactly
                                        #   what the group advance makes line 0
    a = [f"    ; ---- line {k} " + "-" * 52]
    cyc = 0

    # the cos operand was staged by the previous line (or the prologue)
    a += ["    lda z:M7F_PNEXT"]
    cyc += CYCLES["lda_dp"]
    a += ["    sta f:$004202               ; $4202 = cmag, $4203 = p: COS"]
    cyc += CYCLES["sta_long"]

    # --- window 1: derive and park the sin operand --------------------------
    w1 = ["eor_dp", "sta_dp"]
    _win(f"line {k} window 1 (cos product)", w1)
    a += ["    eor z:M7F_CSXOR             ; -> (p<<8) | smag, for free",
          "    sta z:M7F_PTMP"]
    cyc += sum(CYCLES[o] for o in w1)

    a += ["    lda f:$004216               ; P = p * cmag = 64 * |A|"]
    cyc += CYCLES["lda_long"]
    a += ["    lsr a"] * SHIFT
    cyc += SHIFT * CYCLES["lsr_a"]
    a[-1] = "    lsr a                       ; |A|"
    if cneg:
        a += ["    eor #$FFFF", "    inc a                       ; A = -|A|"]
        cyc += CYCLES["eor_imm"] + CYCLES["inc_a"]
    a += [f"    sta a:M7F_AB + {to} + 0, y",
          f"    sta a:M7F_CD + {to} + 2, y  ; M7D = A (the identity, as a store)"]
    cyc += 2 * CYCLES["sta_abs_y"]

    a += ["    lda z:M7F_PTMP",
          "    sta f:$004202               ; SIN"]
    cyc += CYCLES["lda_dp"] + CYCLES["sta_long"]

    # --- window 2: stage the NEXT line's cos operand ------------------------
    w2 = ["lda_long_x", "ora_dp", "sta_dp"]
    _win(f"line {k} window 2 (sin product)", w2)
    a += [f"    lda f:M7F_PROF_LONG + {nxt}, x",
          "    ora z:M7F_CMAG",
          "    sta z:M7F_PNEXT             ; the next line opens on a DP load"]
    cyc += sum(CYCLES[o] for o in w2)

    a += ["    lda f:$004216               ; P = p * smag = 64 * |B|"]
    cyc += CYCLES["lda_long"]
    a += ["    lsr a"] * SHIFT
    cyc += SHIFT * CYCLES["lsr_a"]
    a[-1] = "    lsr a                       ; |B|"
    # the sin sign costs NOTHING: B and -B are both needed (M7B takes B, M7C
    # takes -B), so a negative sin only swaps which slot each lands in.
    first, second = (f"M7F_CD + {to} + 0", f"M7F_AB + {to} + 2") if sneg else \
                    (f"M7F_AB + {to} + 2", f"M7F_CD + {to} + 0")
    a += [f"    sta a:{first}, y",
          "    eor #$FFFF",
          "    inc a",
          f"    sta a:{second}, y"]
    cyc += 2 * CYCLES["sta_abs_y"] + CYCLES["eor_imm"] + CYCLES["inc_a"]
    return a, cyc


def emit_variant(name: str, cneg: int, sneg: int) -> tuple[list[str], float]:
    """One sign quadrant: a 4x unrolled group loop plus a 1-LINE TAIL.

    THE TAIL IS MANDATORY, NOT AN OPTIMISATION LEFTOVER. Under the moving
    horizon a segment is N/2 lines with N/2 in [60, 80] — not a
    multiple of 4. Forcing it to be one would quantise the horizon to 8-line
    jumps, six positions across the whole climb, which is exactly the
    "the sky doesn't change as you ascend" observation this package exists to
    fix. So the group loop runs while four whole lines remain and the tail
    finishes the rest, one line at a time.

    THE TAIL'S LATENCY WINDOWS ARE ASSERTED LIKE ANY GROUP'S — `emit_line` is
    the same function, so a tail is not an exemption from the schedule check.
    """
    a = [f"{name}:", "    .a16", "    .i16",
         "    ldx z:M7F_XCUR",
         "    ldy z:M7F_YCUR",
         "    ; PROLOGUE: prime the pipeline. Every line opens on M7F_PNEXT,",
         "    ; which the PREVIOUS line staged inside its sin window; the first",
         "    ; line of the segment has no previous line, so it is staged here.",
         "    lda f:M7F_PROF_LONG + 0, x",
         "    ora z:M7F_CMAG",
         "    sta z:M7F_PNEXT",
         "    ; M7F_XGRP is XEND minus one group, so this asks 'do four whole",
         "    ; lines remain?' — the short branch reaches the group two bytes",
         "    ; ahead; the far jump is the one that needs a `jmp`.",
         "    cpx z:M7F_XGRP",
         "    bcc @group",
         "    jmp @tail_entry",
         "@group:"]
    group = 0
    for k in range(UNROLL):
        lines, cyc = emit_line(k, cneg, sneg)
        a += lines
        group += cyc
    a += ["    ; ---- the group advance, paid once per four lines -----------",
          "    txa", "    clc", f"    adc #{UNROLL * 2}", "    tax",
          "    tya", "    clc", f"    adc #{UNROLL * 4}", "    tay",
          "    cpx z:M7F_XGRP",
          "    bcs @tail_entry             ; fewer than four lines left",
          "    jmp @group                  ; the group is beyond a short branch",
          "@tail_entry:",
          "    cpx z:M7F_XEND",
          "    bcs @done",
          "@tail:"]
    group += (CYCLES["txa"] + CYCLES["clc"] + CYCLES["adc_imm"] + CYCLES["tax"]
              + CYCLES["tya"] + CYCLES["clc"] + CYCLES["adc_imm"] + CYCLES["tay"]
              + CYCLES["cpx_dp"] + CYCLES["bcs_not_taken"] + CYCLES["jmp_abs"])
    tail_lines, _ = emit_line(0, cneg, sneg)      # SAME emitter, SAME asserts
    a += tail_lines
    a += ["    ; ---- the tail advance, one line at a time ------------------",
          "    inx", "    inx",
          "    iny", "    iny", "    iny", "    iny",
          "    cpx z:M7F_XEND",
          "    bcc @tail",
          "@done:",
          "    rts", ""]
    return a, group / UNROLL


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.splitlines()[-1], file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    variants = [("m7f_seg_pp", 0, 0), ("m7f_seg_pn", 0, 1),
                ("m7f_seg_np", 1, 0), ("m7f_seg_nn", 1, 1)]
    body, per_line = [], {}
    for name, cn, sn in variants:
        a, cyc = emit_variant(name, cn, sn)
        body += a
        per_line[name] = cyc

    hdr = [
        "; ==========================================================================",
        "; m7f_join.inc — GENERATED by tools/gen_m7f_join.py. DO NOT EDIT.",
        "; ==========================================================================",
        "; The four sign-variant segment routines of m7f_cam's band join, 4x",
        "; unrolled and software-pipelined. A HAND EDIT HERE IS NOT THE MAINTENANCE",
        "; PATH: this file lands in build/, is regenerated on every build, and is",
        "; gitignored with the rest of build/. Change tools/gen_m7f_join.py.",
        ";",
        "; THE SCHEDULE IS MACHINE-ASSERTED. The generator counts the CPU cycles it",
        "; interleaves into each of the multiplier's two latency windows per line",
        f"; and REFUSES to emit a file whose windows fill fewer than {MUL_LATENCY}",
        "; cycles — the allocator-refusal philosophy applied to instruction",
        "; scheduling. A short window reads the PREVIOUS product: the floor still",
        "; renders and only the whole-table oracle notices, which is exactly the",
        "; class of defect a build-time refusal should own.",
        ";",
        "; WIDTH: every routine is entered A16/I16 through `jsr (m7f_seg_tab, x)`",
        "; and exits the same; NO sep/rep appears anywhere in the emitted body, so",
        "; nothing can leak a width into the caller on either axis.",
        ";",
        f"; Schedule, per line: window 1 = 8 cycles (eor + sta), window 2 = 14",
        f"; cycles (the next line's staged cos operand). Modelled cost per line:",
    ] + [f";   {n}: {c:.2f} CPU cycles" for n, c in per_line.items()] + [
        ";",
        "; The model is a MODEL. The number that decides anything is the SLHV latch",
        "; in the shipping rail (m7f_cost)",
        "",
    ]
    (out / "m7f_join.inc").write_text("\n".join(hdr + body) + "\n")
    print(f"m7f_join.inc: {UNROLL}x unrolled, 4 sign variants, "
          f"{min(per_line.values()):.2f}-{max(per_line.values()):.2f} "
          f"modelled cycles/line; both latency windows asserted >= {MUL_LATENCY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
