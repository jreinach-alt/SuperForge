#!/usr/bin/env python3
"""Derive probe_cpu_ref.asm from vendor/probe_ref/src/probe_scene_ref.asm.

The CPU probe measures the worst-case frame of the mini racing reference ON
THE REFERENCE SCENE ITSELF, rather than on a synthetic replica that could
silently under-model the real path. This script copies the vendored source
(read-only; never edited in place) and applies a minimal, exactly-anchored
instrumentation patch:

  1. H/V latch rings: SLHV-latched (V,H) pairs at work-start/work-end and
     NMI-entry/NMI-exit, 256-frame rings in high WRAM, computed host-side
     (fullsnes: OPHCT dots are 4 master clocks; OPVCT lines are 1364) —
     ~4 mc resolution with zero in-ROM arithmetic.
  2. CY_STEP: a free-running stream_decompress_row bench (a ticks-per-frame
     instrument) for the Mode 7 streaming step cost.

Scenario input (steady / diagonal / turning) is driven LIVE by the tests
through MesenRunner input injection — there is no forced-input build.

Anchors are matched EXACTLY ONCE or the derivation fails — a reference drift
breaks the build loudly instead of silently mis-patching. Run:

    python3 vendor/probes/make_probe_cpu.py    (from the repo root)

The derived file is committed; re-run only to re-derive after the vendored
scene changes. The probe is measurement scaffolding, not shipping code: the
no-literals gate does NOT apply to it, and no engine or game code links it.
"""
from pathlib import Path
import sys

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
# The scene lives in the frozen vendored snapshot (vendor/probe_ref/README.md)
# — this repo builds with nothing beside it on disk.
SRC = SUPERFORGE / "vendor" / "probe_ref" / "src" / "probe_scene_ref.asm"
DST = SUPERFORGE / "vendor" / "probes" / "probe_cpu_ref.asm"

HEADER = """\
; =============================================================================
; probe_cpu_ref.asm — superforge CPU-budget probe (GENERATED)
; =============================================================================
; DERIVED from vendor/probe_ref/src/probe_scene_ref.asm by
; make_probe_cpu.py — do NOT edit by hand; re-derive instead.
; The base scene is the proven mini racing reference. This copy adds only:
; H/V latch rings and a CY_STEP streaming bench (scenario input comes live
; from the test harness). Search for "CY-PROBE" for insertions.
;
; CONTAINS THIRD-PARTY CONTENT — CC BY 4.0, ATTRIBUTION REQUIRED. The `pv_*`
; perspective routines below, and the two files they use, are derived from
; `dizworld.s` (c) Brad Smith (rainwarrior), https://rainwarrior.ca —
; https://creativecommons.org/licenses/by/4.0/. A ROM built from this file
; (build/probe_cpu.sfc, build/probe_cpu_step.sfc) must credit Brad Smith.
; See NOTICE and docs/92_provenance_audit.md. The base file carries the
; same notice; it is restated here because this is the file that assembles.
; =============================================================================

"""

CY_DEFS = """
; ---- CY-PROBE: superforge instrument state (high WRAM, above DEBUG) ----
CY_WORK_IDX   = DEBUG_BASE + $7F0   ; $E7F0: work-ring index byte
CY_NMI_IDX    = DEBUG_BASE + $7F1   ; $E7F1: NMI-ring index byte
CY_STEP_ITERS = DEBUG_BASE + $7F4   ; $E7F4: 32-bit CY_STEP iteration count
CY_WORK_RING  = DEBUG_BASE + $800   ; $E800: 256 x 8 B (start HHVV + end HHVV)
CY_NMI_RING   = DEBUG_BASE + $1000  ; $F000: 256 x 8 B

; Latch H/V via SLHV and store 4 bytes (Hlo,Hhi,Vlo,Vhi) at ring[idx*8+ofs].
; advance=1 bumps the ring index (call on the END latch of a pair).
; restore_i: the call site's I width (8 or 16) — restored explicitly at exit.
; Every call site runs A8; the macro exits A8 with .a8 annotated so the
; RUNTIME width and ca65's .smart tracking agree at the seam.
; WIDTH-RISK: a php/plp wrapper here desynced ca65's immediate sizing from
; the runtime width (plp is invisible to .smart) and crashed the NMI — the
; explicit restore below is the fix, not a style choice.
; Clobbers NVZC (call sites have no live flags); preserves A, X, DB, D.
.macro CY_LATCH ring, idxaddr, ofs, advance, restore_i
    rep #$30
    .a16
    .i16
    pha
    phx
    lda f:$7E0000 + idxaddr
    and #$00FF
    asl a
    asl a
    asl a
    tax                             ; X = idx * 8
    sep #$20
    .a8
    lda f:$00213F                   ; STAT78 read: reset 213C/D flip-flops
    lda f:$002137                   ; SLHV: latch H/V
    lda f:$00213C                   ; OPHCT 1st: low 8 of dot (4 mc/dot)
    sta f:$7E0000 + ring + ofs + 0, x
    lda f:$00213C                   ; OPHCT 2nd: bit0 = high (rest open bus)
    and #$01
    sta f:$7E0000 + ring + ofs + 1, x
    lda f:$00213D                   ; OPVCT 1st: low 8 of line (1364 mc/line)
    sta f:$7E0000 + ring + ofs + 2, x
    lda f:$00213D                   ; OPVCT 2nd: bit0 = high (rest open bus)
    and #$01
    sta f:$7E0000 + ring + ofs + 3, x
    .if advance
    lda f:$7E0000 + idxaddr
    inc a
    sta f:$7E0000 + idxaddr         ; byte wraps: 256-entry ring
    .endif
    rep #$30
    .a16
    .i16
    plx
    pla
    sep #$20
    .a8                             ; every call site is A8
    .if restore_i = 8
    sep #$10
    .i8
    .else
    rep #$10
    .i16
    .endif
.endmacro
"""

PATCHES = [
    # 0. instrument defs after the DEBUG constant block
    ("DEBUG_DECOMP_COL = DEBUG_BASE + $110 ; 128B: decompressed test column\n",
     "after", CY_DEFS),

    # 1. zero the instrument state right after the SFDB magic init
    ("    sta f:$7E0000 + DEBUG_MAGIC + 2\n",
     "after", """
    ; CY-PROBE: init instrument state (power-on RAM is random)
    sep #$20
    .a8
    lda #0
    sta f:$7E0000 + CY_WORK_IDX
    sta f:$7E0000 + CY_NMI_IDX
    rep #$20
    .a16
    lda #0
    sta f:$7E0000 + CY_STEP_ITERS
    sta f:$7E0000 + CY_STEP_ITERS + 2
"""),

    # 2. CY_STEP free-run bench, immediately at the game-loop head
    ("@game_loop:\n",
     "after", """    ; CY-PROBE: CY_STEP builds bypass the game entirely and free-run the
    ; Mode 7 stream row staging (kit ticks/frames instrument: NMI counts
    ; frames via nmi_count while this loop counts iterations).
    .ifdef CY_STEP
    .a8
@cy_step_loop:
    rep #$30
    .a16
    .i16
    lda f:$7E0000 + CY_STEP_ITERS
    inc a
    sta f:$7E0000 + CY_STEP_ITERS
    bne @cy_step_no_hi
    lda f:$7E0000 + CY_STEP_ITERS + 2
    inc a
    sta f:$7E0000 + CY_STEP_ITERS + 2
@cy_step_no_hi:
    lda z:stream_cam_ty         ; a real row near the camera
    and #$01FF
    sta z:temp+0
    sep #$20
    .a8
    ldy #STREAM_ROW_BUF
    jsr stream_decompress_row   ; the treadmill step being measured
    jmp @cy_step_loop
    .endif
"""),

    # 3. work-window START latch: after the frame-lock wait, before undo_fog
    ("@wait_nmi:\n    lda z:nmi_ready\n    bne @wait_nmi\n",
     "after", """
    ; CY-PROBE: work-window start (covers undo_fog .. apply_fog inclusive)
    CY_LATCH CY_WORK_RING, CY_WORK_IDX, 0, 0, 16
"""),

    # 4. work-window END latch: after apply_fog_band, before looping
    ("    jsr apply_fog_band\n\n    jmp @game_loop\n",
     "replace", """    jsr apply_fog_band

    ; CY-PROBE: work-window end (advances the work ring)
    CY_LATCH CY_WORK_RING, CY_WORK_IDX, 4, 1, 16

    jmp @game_loop
"""),

    # 5. NMI entry latch (both update and skip paths — one entry per frame)
    ("    plb                     ; DB = 0 for HW register access\n",
     "after", """
    ; CY-PROBE: NMI-window start
    CY_LATCH CY_NMI_RING, CY_NMI_IDX, 0, 0, 8
"""),

    # 6. NMI exit latch (after the NMI acknowledge read)
    ("    ; Acknowledge NMI\n    lda a:$4210\n",
     "after", """
    ; CY-PROBE: NMI-window end (advances the NMI ring)
    CY_LATCH CY_NMI_RING, CY_NMI_IDX, 4, 1, 8
"""),
]


def main() -> int:
    text = SRC.read_text()
    for anchor, mode, insertion in PATCHES:
        n = text.count(anchor)
        if n != 1:
            print(f"ANCHOR DRIFT: {n} matches (need exactly 1) for:\n{anchor!r}",
                  file=sys.stderr)
            return 1
        if mode == "after":
            text = text.replace(anchor, anchor + insertion)
        else:
            text = text.replace(anchor, insertion)
    DST.write_text(HEADER + text)
    print(f"derived {DST.relative_to(SUPERFORGE)} from "
          f"{SRC.relative_to(SUPERFORGE.parent)} ({len(PATCHES)} patches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
