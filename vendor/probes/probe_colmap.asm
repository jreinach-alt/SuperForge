; superforge col_map DESIGN REVIEW probe — the per-query cost of
; the candidate world-collision lookup, measured on cycle-accurate hardware.
;
; THIS IS NOT THE FEATURE. It is measurement scaffolding, the same shape as
; probe_vblank: a one-scene allocator-mapped ROM whose only job is to make a
; number measurable. Nothing in engine/ or game/ includes it, and it ships no
; feature.toml under engine/features/.
;
; Method: two arms, K iterations each, bracketed by a store to the `mark`
; byte. The host breakpoints on that WRAM address, reads MasterClock at each
; of the two hits, and subtracts:
;
;   cmd 1  loop of K col_map lookups   -> total_mc(K)
;   cmd 2  the IDENTICAL loop, lookup removed  -> overhead_mc(K)
;
;   per-query mc = (total_mc(K) - overhead_mc(K)) / K
;
; The control arm is what makes this a measurement rather than an estimate
; with a loop tax folded in: the two arms share the coordinate walk, the
; counter and the branch, so everything except the lookup cancels.
;
; The coordinate walk deliberately strides the world so successive queries
; land in DIFFERENT chunk banks and different rows — a walk that stayed in
; one 32 KB window would measure the cheap case only. The kernel is
; straight-line and branch-free, so cost is data-independent by construction;
; the stride is there to prove that rather than to assume it.
;
; All RAM/ROM addresses are allocator-emitted; hardware I/O ports are the
; only literals.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE COLMAP"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "engine_state_probe.inc"

.include "header.inc"
.include "init.inc"

.segment "CODE"

NMI_STUB:
    rti

NMI:
    rti

; ===========================================================================
; THE KERNEL UNDER MEASUREMENT — the real feature source, not a copy of it.
; ===========================================================================
; col_map.asm names only its six bound CM_* symbols plus its own ES_CM_HOT,
; which this probe's feature.toml declares under the same claim name.
; Including the shipped file rather than transcribing it is the point: a
; measured figure that describes a copy stops describing the feature the first
; time either drifts. Same reason the .incbin sites .assert their allocator
; placement.
;
; The binding is microzero's, deliberately: the published per-query cost has
; to describe the composition that ships, so the probe declares the same
; 512x512 world its feature.toml already declares the blob shape for. A probe
; that measured a different world would be measuring a different kernel.
CM_WORLD_W_LOG2      = 9                        ; 512 tiles wide
CM_WORLD_H_LOG2      = 9                        ; 512 tiles tall
CM_WORLD_BLOB        = ES_R_WORLD_MAP_T0_ADDR
CM_WORLD_BLOB_BANK   = ES_R_WORLD_MAP_T0_BANK
CM_WORLD_BLOB_CHUNKS = ES_R_WORLD_MAP_CHUNKS    ; DERIVED, not narrated
CM_FLAGS             = col_flags_bin            ; defined below, at the .incbin
.include "col_map.asm"

; ===========================================================================
MAIN:
    .a16
    .i16
    sep #$20
    .a8
    lda #0
    sta f:US_CMD_LONG
    sta f:US_MARK_LONG
    rep #$20
    .a16
    lda #0
    sta f:US_PARAM_LONG
    sta f:US_PARAM2_LONG        ; cmd 3 reads this at @arm_one before the host
                                ; has necessarily written it (Mesen
                                ; flagged $7E0204/5 as uninitialised
                                ; reads). Power-on RAM is random — CLAUDE.md
                                ; rule 5 applies to probe fixtures too.
    sta f:US_SEQ_LONG
    sta f:US_ACC_LONG
    stz z:CM_PX
    stz z:CM_PY
    stz z:CM_T0
    stz z:CM_T1
    sep #$20
    .a8
    stz z:CM_FLAG
    rep #$20
    .a16

@spin:
    .i16
    sep #$20
    .a8
    lda f:US_CMD_LONG
    cmp #1
    beq @arm_lookup
    cmp #2
    beq @arm_control
    cmp #3
    beq @arm_one
    bra @spin

; --- arm 3: a single query at (param, param2) ------------------------------
; The direct-query path the col_map tests drive. No timing, no loop: write a
; coordinate, step a frame, read the answer out of `acc`.
@arm_one:
    .a8
    .i16
    rep #$20
    .a16
    lda f:US_PARAM_LONG
    sta z:CM_PX
    lda f:US_PARAM2_LONG
    sta z:CM_PY
    jsr col_map_at              ; leaves A8; CM_FLAG holds the result
    rep #$20
    .a16
    and #255
    sta f:US_ACC_LONG
    ; WIDTH-RISK: @finish is annotated .a8 and the other two arms fall into it
    ; in A8. Arriving here in A16 made its `lda #0` -- assembled as the 2-byte
    ; A8 immediate -- execute as a 3-byte A16 immediate, swallowing the next
    ; opcode and derailing the CPU into garbage (observed: PC wandering
    ; $b592 -> $d652 -> $f71c while `acc` never updated). Narrow BEFORE the
    ; jump so every predecessor of @finish agrees on the width it declares.
    sep #$20
    .a8
    jmp @finish

; --- arm 1: K lookups ------------------------------------------------------
@arm_lookup:
    .a8
    .i16
    rep #$20
    .a16
    lda #0
    sta f:US_ACC_LONG
    lda f:US_PARAM_LONG
    tay                         ; Y = K
    lda #0
    sta z:CM_PX
    sta z:CM_PY
    sep #$20
    .a8
    lda #1
    sta f:US_MARK_LONG          ; <-- host breakpoint: timed region OPENS
@lk_loop:
    .i16
    rep #$20
    .a16
    jsr col_map_at              ; returns A8
    rep #$20
    .a16
    and #255
    clc
    adc f:US_ACC_LONG
    sta f:US_ACC_LONG           ; consume the result
    ; stride: +2053 px on x, +761 px on y. Both coprime with 4096, so the
    ; walk visits a fresh row and a fresh chunk bank essentially every step.
    lda z:CM_PX
    clc
    adc #2053
    and #4095
    sta z:CM_PX
    lda z:CM_PY
    clc
    adc #761
    and #4095
    sta z:CM_PY
    dey
    bne @lk_loop
    sep #$20
    .a8
    lda #2
    sta f:US_MARK_LONG          ; <-- host breakpoint: timed region CLOSES
    jmp @finish

; --- arm 2: the identical loop with the lookup removed ---------------------
@arm_control:
    .a8
    .i16
    rep #$20
    .a16
    lda #0
    sta f:US_ACC_LONG
    lda f:US_PARAM_LONG
    tay                         ; Y = K
    lda #0
    sta z:CM_PX
    sta z:CM_PY
    sep #$20
    .a8
    lda #1
    sta f:US_MARK_LONG          ; <-- host breakpoint: timed region OPENS
@ct_loop:
    .i16
    rep #$20
    .a16
    lda #0                      ; stand-in for the kernel's returned flag
    and #255
    clc
    adc f:US_ACC_LONG
    sta f:US_ACC_LONG
    lda z:CM_PX
    clc
    adc #2053
    and #4095
    sta z:CM_PX
    lda z:CM_PY
    clc
    adc #761
    and #4095
    sta z:CM_PY
    dey
    bne @ct_loop
    sep #$20
    .a8
    lda #2
    sta f:US_MARK_LONG          ; <-- host breakpoint: timed region CLOSES

@finish:
    .a8
    .i16
    lda #0
    sta f:US_CMD_LONG
    rep #$20
    .a16
    lda f:US_SEQ_LONG
    inc
    sta f:US_SEQ_LONG
    jmp @spin

; ===========================================================================
; ROM data. The world blob at world_rom's own bank tiling, and the candidate
; 256-byte flag LUT. Both .assert their linker placement against the emitted
; claim symbols — the .incbin convention from game/microzero/main.asm:79-96.
; ===========================================================================
.repeat ES_R_WORLD_MAP_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 1)
.ident(.sprintf("world_map_t%d", WI)):
    .incbin "world_map.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("world_map_t%d", WI)) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)), error, "world chunk bank drifted"
.assert .loword(.ident(.sprintf("world_map_t%d", WI))) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)), error, "world chunk addr drifted"
; The two asserts above tie each chunk's LABEL to its own emitted symbol —
; they say nothing about the chunks' relationship to EACH OTHER, and the
; kernel under measurement depends entirely on that relationship: col_map's
; `bank = T0_BANK + (ty >> CM_CHUNK_SHIFT)` and its single CM_WORLD_BLOB
; window base. col_map's BINDING CONTRACT names this as the includer's
; obligation, and this probe is an includer — the same two lines microzero
; carries at game/microzero/main.asm. Without them a re-packed blob would
; not stop the build here; it would publish a per-query cost measured
; against the wrong bank.
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)) = ES_R_WORLD_MAP_T0_BANK + WI, error, "world chunk banks are not consecutive — col_map's T0_BANK + index addressing would read the wrong bank"
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)) = ES_R_WORLD_MAP_T0_ADDR, error, "world chunks are not window-aligned alike — CM_WORLD_BLOB is one base for all of them"
.endrepeat

.segment "BANK9"
col_flags_bin:
    .incbin "col_flags.bin"
.assert ^col_flags_bin = ES_R_COL_FLAGS_BANK, error, "col_flags bank drifted"
.assert .loword(col_flags_bin) = ES_R_COL_FLAGS_ADDR, error, "col_flags addr drifted"

.segment "CODE"
