; =============================================================================
; mode7_stream.asm — leading-edge tilemap streaming
; =============================================================================
; Main-thread tick walks the camera's tile-delta (wrap-aware, clamp 8/axis, NO
; snap-to-cam) and stages position-wrapped 128-B slices into WRAM slots; the
; NMI hook drains the slots as multi-queue GP-DMA on the vblank-phase channel
; (VMAIN $00 rows / $02 cols, DAS re-armed per slot). Kernels:
;  rows — span-decomposed MVN, <=2 spans (source 512-wrap and dest 128-wrap
;  always cut together: both boundaries are col-multiples of 128)
;  cols — 8x-unrolled strided copy per 64-row bank span (spans cut at
;  64-multiples, which also covers every dest 128-wrap; group starts
;  are 8-aligned so the widest tap offset still fits the window)
; The structure is a VBlank dispatcher over a small API (clamp discipline,
; wrapped positions); the inner loops are the interesting part.
;
; The reference bar: [measured.stream] row_stage_mc = 68578. These kernels are
; measured frame-anchored — see the movement/bench tests.

;
; =============================================================================
; THE BINDING CONTRACT — three symbols, supplied by the includer, no defaults
; =============================================================================
; This file used to name `ES_R_WORLD_MAP_*` in four places, which welded it to
; microzero's blob: a second rail streaming its OWN world could not include it,
; and `depends = ["world_rom", "mode7_floor"]` dragged a 256 KB map plus
; microzero's floor palette into any composition that tried. `schemas.py` has
; no vocabulary for "same feature, different blob" — no parameterised
; `depends`, no template instantiation — so the binding is `col_map.asm`'s
; shape, which is itself `rgb_gradient.asm`'s: symbols the includer defines
; immediately above its
; `.include`, each missing one a hard `.error` naming it, and NO DEFAULT.
; rgb_gradient records why a default is refused — "a silent default is exactly
; how the platformer inherited a wash on its terrain and shipped a teal sky" —
; and it holds harder here: a defaulted blob streams the WRONG ROM bytes into
; the Mode 7 window and the result is a plausible-looking world.
;
;  M7S_WORLD_WIN the blob's ES_R_<NAME>_T0_ADDR — the $8000 LoROM window
;  base every chunk fills (all chunks share it)
;  M7S_BLOB_BANK the blob's ES_R_<NAME>_T0_BANK — chunk 0's bank. Chunk i
;  is BANK + i; see the consecutive-banks note below.
;  M7S_CHUNKS the blob's DERIVED ES_R_<NAME>_CHUNKS — never a narrated
;  count (a narrated `.repeat` count is its own refusal in
;  the rom-backing gate, docs/37 §5 limit 1)
;
; AND ONE OBLIGATION THAT IS NOT A SYMBOL — assert the chunk banks are
; CONSECUTIVE. `M7S_BLOB_BANK + CI` (the MVN stub table) and `adc
; #M7S_BLOB_BANK` + `(wr >> 6)` (stream_stage_col) both read chunk i out of
; bank BASE+i, and `M7S_WORLD_WIN` assumes every chunk sits at the SAME
; in-window offset. Neither is promised by `RomClaim.bank_tiled`, whose only
; stated meaning is "pre-chunked so every chunk fits one bank window"
; (schemas.py) — measured, not assumed: driving the real `place_rom` over
; synthetic claim sets produces NON-consecutive banks for 3 of 4 shapes,
; including two ragged `bank_tiled` blobs with no pin at all. If it stops
; holding, this file reads a plausible-looking wrong 32 KB of ROM into the Mode
; 7 window and nothing says so. It cannot live HERE — the contract deliberately
; withholds the blob's name, so this file cannot spell the per-chunk symbols,
; and a `%s` template to reach them is refused outright
; (no_literals::scan_blanket_rom_template, see below). It belongs beside the
; blob's `.incbin`, the one place that can name them all. Paste, with <BLOB>
; your blob's claim name — the `%d` template is legal HERE because the includer
; names the blob literally:
;
;  .repeat ES_R_<BLOB>_CHUNKS, WI
;  .assert .ident(.sprintf("ES_R_<BLOB>_T%d_BANK", WI)) = ES_R_<BLOB>_T0_BANK +
;  WI, error, "<blob> chunk banks are not consecutive — mode7_stream's T0_BANK
;  + index addressing would read the wrong bank"
;  .assert .ident(.sprintf("ES_R_<BLOB>_T%d_ADDR", WI)) = ES_R_<BLOB>_T0_ADDR,
;  error, "<blob> chunks are not window-aligned alike — M7S_WORLD_WIN is one
;  base for all of them"
;  .endrepeat
;
; microzero discharges this at game/microzero/ beside its world_map `.incbin`.
; A blob small enough to be ONE chunk is trivially adjacent and needs neither
; line.
;
; `depends` is therefore `[]`: mode7_stream depends on whatever the GAME binds,
; and the game composes both the streaming kernels and its blob. Losing the
; allocator's `depends` check is not losing the check — it is replaced by an
; assembly-time one, and this repo already treats that as the stronger signal.
; The blob's own `rom` claim is still gated independently by `make
; rom-unbacked`, and the seed upload that this file's tracking assumes
; (stream_arm) is the game's floor feature, not this one's — microzero binds
; `mode7_floor`, another rail binds its own.
;
; WHY THE CHUNK BANKS ARE ARITHMETIC AND NOT `.ident(.sprintf(...))`.
; The obvious parameterisation of the MVN stub table is a blob-NAME string:
; `.ident(.sprintf("ES_R_%s_T%d_BANK", M7S_BLOB, CI))`. It assembles — but
; `allocator/no_literals.py::scan_blanket_rom_template` REFUSES any
; `ES_R_...%s` template, per-file and unconditionally: `%s` is a name FRAGMENT
; and compiles to `\w+`, so the reference stops naming one claim and credits a
; whole CLASS of them, silently, without moving a number in the census.
; Measured, both halves — `ES_R_%s_T%d_BANK` compiles to `^ES_R_\w+_T\d+_BANK$`
; and credits every BANK_TILED claim's chunks (a scalar `ES_R_FONT_BIN_BANK`
; has no `_T<digits>_BANK` tail and does NOT match); the pass's own docstring
; illustrates the credits-EVERYTHING case with the different form
; `ES_R_%s_BANK`. Earlier text here said the brief's form "credits every rom
; claim ... Turns the backing check off for the whole ROM" — overstated, and
; corrected per. The conclusion is untouched: the refusal is textual on `%s`
; and fires either way, which the form above did when run through no_literals —
; `1 blanket rom template(s)`. So the name cannot enter this file, and the stub
; table derives chunk i's bank as `M7S_BLOB_BANK + CI` instead. That is not a
; new assumption: stream_stage_col below already computes its span bank as
; `T0_BANK + (wr >> 6)`, as does mode7_floor.asm:118. The assumption is now
; STATED, and asserted where the chunk symbols legitimately live — beside the
; `.incbin` in the game's main.asm, which is the only place that can see them
; all.
;
; STILL IMPLICIT, deliberately (see this change report): the world's WIDTH.
; `WORLD_COLS_BYTES` (the row stride), `CAM0_TX`/`CAM0_TY` (the enter camera)
; and the folded `& 63` / `>> 6` / `& 511` constants below are the game's
; world.inc, bound by name rather than by contract. Col_map generalised the
; identical arithmetic to any W; doing the same here is a strictly larger
; change and both rails on the table are 512 tiles wide, so it is left for the
; rail that needs a different W.
;
; (the declared max speed lives in tools/gen_move_lut.py — 48 px/frame;
; the clamp-8 staging below covers its worst 6 tiles/frame/axis)

; --- the binding, checked before anything else ------------------------------
; One `.error` per symbol, naming that symbol, so an incomplete binding says
; WHICH one is missing rather than failing on a downstream range error. The
; `.ifndef` form is rgb_gradient.asm's and col_map.asm's; no branch supplies a
; default.
.ifndef M7S_WORLD_WIN
    .error "mode7_stream: the includer must define M7S_WORLD_WIN (the world tilemap blob's ES_R_<name>_T0_ADDR) before including this file"
.endif
.ifndef M7S_BLOB_BANK
    .error "mode7_stream: the includer must define M7S_BLOB_BANK (the world tilemap blob's ES_R_<name>_T0_BANK) before including this file"
.endif
.ifndef M7S_CHUNKS
    .error "mode7_stream: the includer must define M7S_CHUNKS (the world tilemap blob's derived ES_R_<name>_CHUNKS) before including this file"
.endif

WORLD_WIN = M7S_WORLD_WIN           ; the $8000 LoROM window every chunk fills
STREAM_WRAM = ES_STREAM_COLS_LONG - ES_STREAM_COLS  ; $7E0000, symbol-derived
MZS_REGS = $4300 + ES_H_MZS_CH * 16  ; the vblank channel's DMA register file

; Both arming sites below write DMAP from the same `lda #$00` that programs
; VMAIN, saving a load in the per-frame path. That reuse is only valid while
; the declared DMAP really is zero, so assert it rather than trusting the
; comment: declare `indirect` or a non-zero mode for the mzs claim and this
; refuses the build, pointing at the two sites that must then load the symbol.
; Same shape as the .incbin claim-site asserts in race.asm.
.assert ES_H_MZS_DMAP = 0, error, "mzs DMAP is no longer 0 — the shared lda with VMAIN at mzs_arm_row/col must become an explicit lda #ES_H_MZS_DMAP"

; --- DP field aliases (ES_STREAM_HOT layout, feature.toml) ------------------
ST_CAM_TX  = ES_STREAM_HOT + 0      ; camera tile x (0..511)
ST_CAM_TY  = ES_STREAM_HOT + 2
ST_LAST_TX = ES_STREAM_HOT + 4      ; last staged-through tile position
ST_LAST_TY = ES_STREAM_HOT + 6
ST_ROW_CNT = ES_STREAM_HOT + 8      ; pending row slots (u8, 0..8)
ST_COL_CNT = ES_STREAM_HOT + 9      ; pending col slots (u8, 0..8)
ST_K0      = ES_STREAM_HOT + 10     ; kernel locals (MVN owns A/X/Y)
ST_K1      = ES_STREAM_HOT + 12
ST_K2      = ES_STREAM_HOT + 14
ST_K3      = ES_STREAM_HOT + 16
ST_K4      = ES_STREAM_HOT + 18
ST_K5      = ES_STREAM_HOT + 20

; --- stream_arm: init contract + tile tracking from the enter camera --------
; In/out: A16/I16, DB=0 (scene enter contract). The seed upload already covers
; the whole 128x128 window around CAM0; tracking starts in sync.
stream_arm:
    .a16
    .i16
    ldx #(ES_STREAM_HOT_SIZE - 2)
:   stz z:ES_STREAM_HOT, x
    dex
    dex
    bpl :-
    sep #$20
    .a8
    stz z:ES_STREAM_NMI
    stz z:ES_STREAM_NMI + 1
    rep #$20
    .a16
    lda #CAM0_TX
    sta z:ST_CAM_TX
    sta z:ST_LAST_TX
    lda #CAM0_TY
    sta z:ST_CAM_TY
    sta z:ST_LAST_TY
    rts

; --- stream_tick: camera delta -> staged slots (race tick, after movement) --
; In/out: A16/I16, DB=0. Reads the M7ORG pixel shadows; walks LAST toward CAM
; one tile at a time, staging each entering edge. Clamp: stops when a frame's
; slots are full — NEVER snaps LAST to CAM (the skipped-tile class).
stream_tick:
    .a16
    .i16
    lda z:ES_M7ORG + 0              ; M7X px
    lsr
    lsr
    lsr
    and #511
    sta z:ST_CAM_TX
    lda z:ES_M7ORG + 2              ; M7Y px
    lsr
    lsr
    lsr
    and #511
    sta z:ST_CAM_TY
@walk_ty:
    .a16
    lda z:ST_CAM_TY
    sec
    sbc z:ST_LAST_TY
    and #511
    beq @ty_done
    lda z:ST_ROW_CNT
    and #255
    cmp #8
    bcs @ty_done                    ; slots full — rest next frame (no snap)
    lda z:ST_CAM_TY
    sec
    sbc z:ST_LAST_TY
    and #511
    cmp #256
    bcs @ty_step_up
    ; step +1: entering edge = new bottom row (last+1+63 = last+64)
    lda z:ST_LAST_TY
    inc
    and #511
    sta z:ST_LAST_TY
    clc
    adc #63
    and #511
    bra @ty_stage
@ty_step_up:
    .a16
    ; step -1: entering edge = new top row (last-1-64 = last-65)
    lda z:ST_LAST_TY
    dec
    and #511
    sta z:ST_LAST_TY
    sec
    sbc #64
    and #511
@ty_stage:
    .a16
    sta z:ST_K0                     ; world row to stage
    jsr stream_stage_row
    bra @walk_ty
@ty_done:
    .a16
@walk_tx:
    lda z:ST_CAM_TX
    sec
    sbc z:ST_LAST_TX
    and #511
    beq @tx_done
    lda z:ST_COL_CNT
    and #255
    cmp #8
    bcs @tx_done
    lda z:ST_CAM_TX
    sec
    sbc z:ST_LAST_TX
    and #511
    cmp #256
    bcs @tx_step_left
    lda z:ST_LAST_TX
    inc
    and #511
    sta z:ST_LAST_TX
    clc
    adc #63
    and #511
    bra @tx_stage
@tx_step_left:
    .a16
    lda z:ST_LAST_TX
    dec
    and #511
    sta z:ST_LAST_TX
    sec
    sbc #64
    and #511
@tx_stage:
    .a16
    sta z:ST_K0                     ; world col to stage
    jsr stream_stage_col
    bra @walk_tx
@tx_done:
    .a16
    rts

; --- stream_stage_row: K0 = world row r -> row slot [ST_ROW_CNT] ------------
; Fills the slot buffer with world_row[r][cam_tx-64 .. Cam_tx+64) at
; position-wrapped dest indices (wc & 127), <=2 MVN spans; writes the slot's
; VMADD word; bumps ST_ROW_CNT. In/out: A16/I16, DB=0. Locals: K0 stub addr (r
; consumed first), K1 wc, K2 remaining, K3 dst base, K4 src row base, K5 span.
stream_stage_row:
    .a16
    .i16
    ; meta[row_cnt] = (r & 127) * 128 (Mode 7 tilemap word address)
    lda z:ST_ROW_CNT
    and #255
    asl
    tax
    lda z:ST_K0
    and #127
    xba
    lsr
    sta a:ES_STREAM_META, x
    ; K3 = dest slot base = STREAM_ROWS + row_cnt * 128
    lda z:ST_ROW_CNT
    and #255
    xba
    lsr
    clc
    adc #ES_STREAM_ROWS
    sta z:ST_K3
    ; K4 = source row base = WORLD_WIN + (r & 63) * 512
    lda z:ST_K0
    and #63
    xba
    asl
    clc
    adc #WORLD_WIN
    sta z:ST_K4
    ; K0 = MVN stub address for chunk (r >> 6) — 4 B per stub
    lda z:ST_K0
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr                             ; r >> 6 = chunk 0..7
    asl
    asl                             ; * 4 = stub offset
    clc
    adc #.loword(stream_mvn_stubs)
    sta z:ST_K0
    ; K1 = wc = window start world col; K2 = bytes remaining
    lda z:ST_CAM_TX
    sec
    sbc #64
    and #511
    sta z:ST_K1
    lda #128
    sta z:ST_K2
@row_span:
    .a16
    ; K5 = span = min(128 - (wc & 127), remaining)
    lda z:ST_K1
    and #127
    eor #127
    inc                             ; 128 - (wc & 127)
    cmp z:ST_K2
    bcc :+
    lda z:ST_K2
:   sta z:ST_K5
    ; X = src = row base + wc; Y = dst = slot base + (wc & 127)
    lda z:ST_K4
    clc
    adc z:ST_K1
    tax
    lda z:ST_K1
    and #127
    clc
    adc z:ST_K3
    tay
    lda z:ST_K5
    dec                             ; MVN moves A+1 bytes
    phb
    jsr stream_do_mvn               ; jmp (ST_K0) -> per-bank MVN + rts
    plb                             ; DB back to 0 (MVN left it at $7E)
    ; wc = (wc + span) & 511; remaining -= span
    lda z:ST_K1
    clc
    adc z:ST_K5
    and #511
    sta z:ST_K1
    lda z:ST_K2
    sec
    sbc z:ST_K5
    sta z:ST_K2
    bne @row_span
    sep #$20
    .a8
    inc z:ST_ROW_CNT
    rep #$20
    .a16
    rts

; WIDTH-RISK: MVN uses the full 16-bit C register regardless of M width plus
; the I16 index registers; every stub is entered A16/I16 from stage_row and
; leaves DB = $7E (the caller wraps the jsr in phb/plb).
stream_do_mvn:
    .a16
    .i16
    jmp (ST_K0)

; one 4-byte stub per world chunk bank: MVN dst=$7E, src=chunk bank, rts. Ca65
; encodes MVN operands dst-bank-first (the scene_mgr quirk note). The count is
; the blob's DERIVED chunk symbol, never a narrated literal; the source bank is
; chunk 0's + the index, which the includer asserts against the blob's own
; per-chunk symbols (see THE BINDING CONTRACT above).
stream_mvn_stubs:
.repeat M7S_CHUNKS, CI
    .byte $54, $7E, M7S_BLOB_BANK + CI
    rts
.endrepeat

; --- stream_stage_col: K0 = world col c -> col slot [ST_COL_CNT] ------------
; Fills the slot with world[cam_ty-64 .. Cam_ty+64)[c] at dest indices (wr &
; 127); spans cut at 64-row bank boundaries (which also cover every dest
; 128-wrap); inner loop 8x-unrolled. In/out: A16/I16, DB=0 (each span
; temporarily sets DB = chunk bank).
; Locals: K0 world col c (kept), K1 wr, K2 rows remaining, K3 dst base, K4 span
; rows.
stream_stage_col:
    .a16
    .i16
    ; meta[8 + col_cnt] = c & 127 (VRAM col word addr; walk starts row 0)
    lda z:ST_COL_CNT
    and #255
    asl
    tax
    lda z:ST_K0
    and #127
    sta a:ES_STREAM_META + 16, x
    ; K3 = dest slot base = STREAM_COLS + col_cnt * 128
    lda z:ST_COL_CNT
    and #255
    xba
    lsr
    clc
    adc #ES_STREAM_COLS
    sta z:ST_K3
    ; K1 = wr = window start world row; K2 = rows remaining
    lda z:ST_CAM_TY
    sec
    sbc #64
    and #511
    sta z:ST_K1
    lda #128
    sta z:ST_K2
@col_span:
    .a16
    ; K4 = span = min(64 - (wr & 63), remaining)
    lda z:ST_K1
    and #63
    eor #63
    inc
    cmp z:ST_K2
    bcc :+
    lda z:ST_K2
:   sta z:ST_K4
    ; Y = in-bank source cursor = (wr & 63) * 512 + c
    lda z:ST_K1
    and #63
    xba
    asl
    clc
    adc z:ST_K0
    tay
    ; X = dest cursor = slot base + (wr & 127)
    lda z:ST_K1
    and #127
    clc
    adc z:ST_K3
    tax
    ; DB = chunk bank (T0 bank + (wr >> 6))
    lda z:ST_K1
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    sep #$20
    .a8
    clc
    adc #M7S_BLOB_BANK
    pha
    plb                             ; DB = chunk bank for the span
@col_head:
    ; ---- head: per-byte until the source row is 8-aligned ----------------
    rep #$20
    .a16
    lda z:ST_K4
    bne :+
    jmp @col_span_end               ; span exhausted (beq is out of range)
:   lda z:ST_K1
    and #7
    beq @col_groups
    sep #$20
    .a8
    lda a:WORLD_WIN, y
    sta f:STREAM_WRAM + 0, x
    rep #$20
    .a16
    tya
    clc
    adc #WORLD_COLS_BYTES
    tay
    inx
    inc z:ST_K1                     ; wr += 1 (mod-512 masked at span end)
    dec z:ST_K4
    dec z:ST_K2
    bra @col_head
@col_groups:
    .a16
    ; ---- 8x-unrolled groups while the span has >= 8 rows -----------------
    lda z:ST_K4
    cmp #8
    bcc @col_tail
    sep #$20
    .a8
    lda a:WORLD_WIN + 0 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 0, x
    lda a:WORLD_WIN + 1 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 1, x
    lda a:WORLD_WIN + 2 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 2, x
    lda a:WORLD_WIN + 3 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 3, x
    lda a:WORLD_WIN + 4 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 4, x
    lda a:WORLD_WIN + 5 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 5, x
    lda a:WORLD_WIN + 6 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 6, x
    lda a:WORLD_WIN + 7 * WORLD_COLS_BYTES, y
    sta f:STREAM_WRAM + 7, x
    rep #$20
    .a16
    tya
    clc
    adc #(8 * WORLD_COLS_BYTES)
    tay
    txa
    clc
    adc #8
    tax
    lda z:ST_K1
    clc
    adc #8
    sta z:ST_K1
    lda z:ST_K4
    sec
    sbc #8
    sta z:ST_K4
    lda z:ST_K2
    sec
    sbc #8
    sta z:ST_K2
    bra @col_groups
@col_tail:
    .a16
    ; ---- tail: per-byte for the span's last (span & 7) rows --------------
    lda z:ST_K4
    beq @col_span_end
    sep #$20
    .a8
    lda a:WORLD_WIN, y
    sta f:STREAM_WRAM + 0, x
    rep #$20
    .a16
    tya
    clc
    adc #WORLD_COLS_BYTES
    tay
    inx
    inc z:ST_K1
    dec z:ST_K4
    dec z:ST_K2
    bra @col_tail
@col_span_end:
    .a16
    ; restore DB = 0, wrap wr, continue while rows remain
    sep #$20
    .a8
    lda #0
    pha
    plb
    rep #$20
    .a16
    lda z:ST_K1
    and #511
    sta z:ST_K1
    lda z:ST_K2
    beq @col_all_done
    jmp @col_span                   ; next span (bne is out of range)
@col_all_done:
    .a16
    sep #$20
    .a8
    inc z:ST_COL_CNT
    rep #$20
    .a16
    rts

; --- stream_nmi_dispatch: drain staged slots as multi-queue GP-DMA ----------
; In: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A/X/Y + ES_STREAM_NMI. Uses
; the vblank-phase channel's $43xx regs directly — the NMI core re-arms every
; channel from the scene_mgr shadow after the hook, so time-sharing with an
; active-phase channel is safe by construction.
stream_nmi_dispatch:
    .a8
    .i16
    lda z:ST_ROW_CNT
    beq @rows_done
    sta z:ES_STREAM_NMI
    lda #$00
    sta a:$2115                     ; VMAIN: +1 word after low-byte write
    ; CHANNEL-LINT: ok — the A above is deliberately shared with DMAP to save a
    ; load in the NMI dispatcher, and `.assert ES_H_MZS_DMAP = 0` at the top of
    ; this file fails the BUILD if the declared encoding ever stops being $00.
    sta a:MZS_REGS + 0    ; DMAP: mode 0, A->B (== ES_H_MZS_DMAP, asserted)
    lda #ES_H_MZS_BBAD
    sta a:MZS_REGS + 1    ; BBAD: VMDATAL
    lda #ES_STREAM_ROWS_BANK
    sta a:MZS_REGS + 4    ; A1B
    ldx #0                          ; meta byte index
    ldy #ES_STREAM_ROWS             ; A-bus cursor
@row_slot:
    .a8
    rep #$20
    .a16
    lda a:ES_STREAM_META, x
    sta a:$2116                     ; VMADD
    tya
    sta a:MZS_REGS + 2    ; A1T
    lda #128
    sta a:MZS_REGS + 5    ; DAS — re-armed EVERY slot
    sep #$20
    .a8
    lda #(1 << ES_H_MZS_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    tya
    clc
    adc #128
    tay
    sep #$20
    .a8
    inx
    inx
    dec z:ES_STREAM_NMI
    bne @row_slot
    stz z:ST_ROW_CNT
@rows_done:
    .a8
    lda z:ST_COL_CNT
    beq @cols_done
    sta z:ES_STREAM_NMI
    lda #$02
    sta a:$2115                     ; VMAIN: +128 words (column walk)
    lda #ES_H_MZS_DMAP              ; (== $00; the row path above shares its A)
    sta a:MZS_REGS + 0
    lda #ES_H_MZS_BBAD
    sta a:MZS_REGS + 1
    lda #ES_STREAM_COLS_BANK
    sta a:MZS_REGS + 4
    ldx #16                         ; col meta starts at word 8
    ldy #ES_STREAM_COLS
@col_slot:
    .a8
    rep #$20
    .a16
    lda a:ES_STREAM_META, x
    sta a:$2116
    tya
    sta a:MZS_REGS + 2
    lda #128
    sta a:MZS_REGS + 5
    sep #$20
    .a8
    lda #(1 << ES_H_MZS_CH)
    sta a:$420B
    rep #$20
    .a16
    tya
    clc
    adc #128
    tay
    sep #$20
    .a8
    inx
    inx
    dec z:ES_STREAM_NMI
    bne @col_slot
    stz z:ST_COL_CNT
@cols_done:
    .a8
    rts
