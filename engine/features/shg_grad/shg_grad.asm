; =============================================================================
; shg_grad.asm — THE PAYLOAD: one freed channel, one COLDATA byte per scanline
; =============================================================================
;  ch ES_H_SHGGR_CH DMAP $00 (mode 0, DIRECT) -> COLDATA ($2132) whole frame
;  A 227-byte repeat-mode table in WRAM: [$80|112][112 vals][$80|112]
;  [112 vals][$00]. Repeat mode means "a NEW 1-byte unit every scanline,
;  112 times", so the two entries cover content lines 0..111 and 112..223
;  back to back. In the HDMAEN mask, armed via the sm_hdma shadow.
;
; THE ENCODINGS, DERIVED FROM THE VENDORED MESEN2 SOURCE before this file
; used them:
;
;  COLDATA $2132 bit7 = B plane, bit6 = G, bit5 = R, low 5 bits = the
;  intensity written into whichever planes are selected
;  (SnesPpu.cpp:2214-2225 — three independent `if(value &
;  0x80/0x40/0x20)` arms over one 5-bit field). Setting ALL
;  THREE plane bits in one write is therefore a legal grey
;  write, not a trick the hardware tolerates by accident:
;  R=G=B=v in ONE byte, which is what makes a per-line ramp
;  cost ONE channel where rgb_gradient's per-plane shape
;  costs three.
;  CGWSEL $2130 bits7-6 clip mode, bits5-4 prevent mode, bit1 =
;  ColorMathAddSubscreen, bit0 = DirectColorMode
;  (:2199-2205). ZERO is what this rail wants on every field:
;  never clip, never prevent, bit1 CLEAR so `otherPixel =
;  _state.FixedColor` unconditionally (:1354-1362) — the
;  fixed colour IS the second operand — and direct colour off
;
;  CGADSUB $2131 bits5-0 = the per-layer enable mask, bit6 = halve,
;  bit7 = subtract (:2207-2212), and layer bit 0 is BG1 —
;  `RenderTilemapMode7<0, 3, 3>` (:855) passes layerIndex 0
;  and the flag is `(ColorMathEnabled >> layerIndex) & 1`
;  (:1190). So bit 0 alone = ADD, FULL, BG1 ONLY.
;
; AND THE CONSEQUENCE THIS RAIL'S TESTS MEASURE, from the blend itself
; (:1372-1378): with subtract off and halve off,
;  rendered_blue = min(plane_blue + fixed_blue, 31)
; and shg_floor holds every plane_blue at 0 — so rendered blue IS the gradient,
; saturation unreachable (the ramp tops out at 223>>3 = 27). ONE HEDGE, carried
; rather than laundered: the BACKDROP is governed by CGADSUB bit 5 (:924),
; which is clear here, so backdrop pixels would read blue 0 instead of the
; gradient. M7SEL = 0 wraps the plane under every pixel, so no backdrop shows —
; the metric holds because of that, not in spite of it.
;
; Contract: template-wide DB=$00; every WRAM touch is long-addressed.

; --- the channel shadow (scene_mgr's 128-byte sm_hdma file) ------------------
SHG_GR_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8       ; 16 B of register file/channel

; --- the table's shape ------------------------------------------------------
; Repeat flag 128 | 112 lines: one NEW byte per scanline for a band's worth.
SHG_GR_LINES  = 112                             ; per entry (two entries)
SHG_GR_TOTAL  = SHG_GR_LINES * 2                ; 224 content lines
SHG_GR_HDR2   = 1 + SHG_GR_LINES                ; +113: entry 2's header byte
SHG_GR_TERM   = 2 + SHG_GR_TOTAL                ; +226: the terminator
.assert SHG_GR_TERM + 1 = ES_SHG_GTBL_SIZE, error, "shg_grad: the table shape does not fill its wram claim"

; The plane-select bits, as the bits they are (SnesPpu.cpp:2216-2224).
SHG_COLDATA_R   = 1 << 5
SHG_COLDATA_G   = 1 << 6
SHG_COLDATA_B   = 1 << 7
SHG_COLDATA_ALL = SHG_COLDATA_R | SHG_COLDATA_G | SHG_COLDATA_B

; The intensity ramp: value(line) = line >> SHG_GR_STEER, so 224 lines map to
; 0..27 of COLDATA's 5-bit field — a visibly graded wash that never saturates.
SHG_GR_STEER = 3

; Colour math: ADD (bit7 clear), FULL (bit6 clear), BG1 only (layer bit 0).
SHG_CGWSEL_FIXED = 0                            ; every field zero; see header
SHG_CGADSUB_ADD_BG1 = 1 << 0

; =============================================================================
; grad_arm — build the table, stage the channel, turn colour math on. In/out:
; A16/I16, DB=0, forced blank + NMI masked (scene enter). Clobbers A, X. The
; caller ORs ES_H_SHGGR_CH's bit into the scene_mgr HDMAEN shadow. Under
; -DSHG_NO_GRAD this routine is not compiled and the scene does not call it: no
; table, no channel bit, no colour math — the gradient's flip control.
; =============================================================================
grad_arm:
    .a16
    .i16
    jsr grad_build

    ; ---- channel shadow: DIRECT, one byte per line -------------------------
    ; No DAS staging: in DIRECT mode $4305/$4306 is the indirect ADDRESS
    ; register and the per-line unit size comes from DMAP's mode field, so the
    ; only per-frame state the shadow MVN must restore is A1T (which HDMA's own
    ; table walk advances) — the same reason sit_cam stages none for its
    ; INDIRECT matrix pair.
    sep #$20
    .a8
    ldx #(ES_H_SHGGR_CH * SHG_GR_SHDW_CH_SIZE)
    lda #ES_H_SHGGR_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP $00: A->B, 1 byte -> 1 register
    lda #ES_H_SHGGR_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: COLDATA
    lda #ES_SHG_GTBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the table's bank
    rep #$20
    .a16
    lda #ES_SHG_GTBL
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: the table

    ; ---- colour math ON: fixed-colour ADD, full, BG1 -----------------------
    sep #$20
    .a8
    lda #SHG_CGWSEL_FIXED
    sta a:$2130                     ; CGWSEL
    lda #SHG_CGADSUB_ADD_BG1
    sta a:$2131                     ; CGADSUB
    rep #$20
    .a16
    rts

; =============================================================================
; grad_disarm — colour math off (scene exit). The counterpart of grad_arm's two
; writes, and it lives HERE rather than in the scene so that BOTH writers of
; CGWSEL/CGADSUB are this feature's own asm — the writer-side gate's
; feature-strict tier then covers them and the claim needs no `scene_writes`
; hatch in either direction. Leaving colour math on would wash whatever scene
; came next; no edges exist on this rail, so this is the contract kept honest.
; In/out: A16/I16, DB=0 (the scene exit contract). Clobbers A. WIDTH-RISK:
; entry A16/I16; exits A16/I16 (sep/rep balanced).
; =============================================================================
grad_disarm:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$2131                     ; CGADSUB: no layer in colour math
    stz a:$2130                     ; CGWSEL: back to its power-of-scene zero
    rep #$20
    .a16
    rts

; =============================================================================
; grad_build — fill the 227-byte COLDATA table in WRAM.
;  [$80|112][v(0)..v(111)][$80|112][v(112)..v(223)][$00]
; value(line) = SHG_COLDATA_ALL | (line >> 3): all three planes, one write.
; Built at boot rather than shipped as a blob — 227 bytes an arithmetic loop
; authors exactly do not need a generator, an oracle or a provenance surface.
; POWER-ON FIDELITY (rule 5): every byte of the claim is written here — the two
; headers, both payloads and the terminator — so the DMA controller never walks
; a random byte. Nothing is zero-filled "to be safe"; the terminator is written
; because a terminator is what belongs there. In/out: A16/I16, DB=0. Clobbers
; A, X. WIDTH-RISK: entry A16/I16; the fill loop runs A8 with X live as a
; 16-bit index — `txa` in A8 takes X's LOW byte only, which is exact because X
; never exceeds 223 here (the cpx bound below is what makes that true, so do
; not raise it without widening the arithmetic). Exits A16/I16, sep/rep
; balanced.
; =============================================================================
grad_build:
    .a16
    .i16
    sep #$20
    .a8
    lda #(128 | SHG_GR_LINES)
    sta f:ES_SHG_GTBL_LONG + 0              ; entry 1 header: lines 0..111
    sta f:ES_SHG_GTBL_LONG + SHG_GR_HDR2    ; entry 2 header: lines 112..223
    lda #0
    sta f:ES_SHG_GTBL_LONG + SHG_GR_TERM    ; terminator
    ldx #0                                  ; X = content line 0..223
@fill:
    .a8
    txa                                     ; X's low byte (X <= 223 fits)
    lsr a
    lsr a
    lsr a                                   ; line >> 3 = 0..27
    ora #SHG_COLDATA_ALL                    ; R=G=B in one byte
    cpx #SHG_GR_LINES
    bcs @entry2
    sta f:ES_SHG_GTBL_LONG + 1, x           ; entry 1 payload
    bra @next
@entry2:
    .a8
    sta f:ES_SHG_GTBL_LONG + 2, x           ; entry 2 payload (skip its header)
@next:
    .a8
    inx
    cpx #SHG_GR_TOTAL
    bcc @fill
    rep #$20
    .a16
    rts
