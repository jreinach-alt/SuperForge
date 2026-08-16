; =============================================================================
; met_glow.asm — the red impact glow: an eight-band COLDATA ramp on one channel
; =============================================================================
; Three routines over one HDMA channel and a seventeen-byte WRAM table:
;
;  glow_arm scene enter build the table at intensity 0, program the
;  channel's shadow slot, colour math OFF
;  glow_set per frame A = quantised intensity 0..31 -> rebuild the
;  table; the CALLER gates on the value having
;  changed (see below)
;  glow_disarm scene exit colour math back to the boot state
;
; THE TABLE IS THE HDMA NON-REPEAT PAUSE SHAPE. A mode-0 entry whose count byte
; is $01..$80 with bit 7 CLEAR transfers ONE byte at the entry's first line and
; then idles for the remaining N-1 lines; COLDATA holds its value across the
; idle lines. So eight entries of 28 lines each paint an eight-step
; top-to-bottom ramp over the 224 active scanlines in seventeen bytes, and a
; rebuild is eight stores rather than the 224 a per-line table would need
; (AGENTS.md's cycle note: a 225-iteration fill is ~3,700 cycles per active
; channel per frame — enough, rebuilt unconditionally every frame, to run a
; whole scene at about a third speed).
;
; EVERY DATA BYTE CARRIES THE PLANE-SELECT BIT. $2132 is one port for three
; planes: bits 5/6/7 say which of R/G/B the low five bits apply to. The claim
; is COLDATA_R, so every byte here is (32 | level) and the G and B planes are
; left for another owner — which is what makes the plane-scoped claim a true
; statement rather than a naming convention.
;
; WHY THE RAMP IS TOP-BLACK -> BOTTOM-RED. The red has to concentrate in the
; LOWER band, because the glow is an IMPACT below the frame: the meteor is
; sliding off the bottom-right when it rises. Band i therefore gets level * (i
; + 1) / 8, so band 7 (the bottom 28 lines) is the full intensity and band 0 is
; a fraction of it.
;
; Must NOT set .p816/.smart — included into a parent that already does.

; --- glow_arm: the table, the channel slot, colour math off ----------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Clobbers A, X, Y. The CALLER ORs (1 << ES_H_GLOW_CH) into the HDMAEN shadow.
;
; WIDTH-RISK: A16/I16 entry AND exit; `sep #$20` only, I-width never moves.
glow_arm:
    .a16
    .i16
    lda #0
    jsr glow_set                    ; every one of the 17 bytes, before the
                                    ;  channel can ever read one (rule 5)
    sep #$20
    .a8
    ldx #(ES_H_GLOW_CH * 16)
    lda #ES_H_GLOW_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: A->B, mode 0, direct
    lda #ES_H_GLOW_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD: COLDATA (the claim names the plane)
    lda #ES_GLOW_TAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: the table's WRAM bank
    rep #$20
    .a16
    lda #ES_GLOW_TAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T: the table's address

    ; ---- colour math OFF until the glow first rises -----------------------
    ; The gradient is armed at boot with bottom red = 0, and the math is only
    ; turned on when the intensity first leaves zero: the channel streams a
    ; black ramp from enter, and CGADSUB stays clear so it adds to nothing
    ; until glow_math_on.
    jsr glow_math_off
    rts

; --- glow_set: rebuild the eight band entries for intensity A --------------
; In: A16/I16, DB=0. A = intensity 0..31 (the bottom band's level). Out:
; A16/I16. Clobbers A, X, Y.
;
; band i (0 = top) gets level * (i + 1) / 8, accumulated rather than
; multiplied: the running sum adds level once per band and the byte written is
; (sum >> 3). Integer division by eight, so band 7 is exactly `level` and the
; ramp is monotone by construction.
;
; The caller GATES this on the quantised intensity having changed. That gate
; is what keeps the rebuild off most frames, and it lives in the scene, beside
; the state that knows the previous value.
glow_set:
    .a16
    .i16
    and #MET_GLOW_MAX               ; five bits is all COLDATA has
    sta z:ES_MET_DRAW + MET_D_TILE  ; the per-band step == the intensity
    stz z:ES_MET_DRAW + MET_D_X     ; the running sum
    ldx #0                          ; byte cursor into the table
    ldy #0                          ; band counter
@band:
    .a16
    .i16
    lda z:ES_MET_DRAW + MET_D_X
    clc
    adc z:ES_MET_DRAW + MET_D_TILE
    sta z:ES_MET_DRAW + MET_D_X     ; sum = level * (band + 1)
    .repeat 3
        lsr                         ; / 8 -> this band's level
    .endrepeat
    ora #MET_COLDATA_R              ; the R plane-select bit, every byte
    xba
    ora #MET_GLOW_LINES             ; the count byte, in the low half
    ; A is now (data << 8) | count — the entry's two bytes, little-endian, in
    ; one store.
    sta a:ES_GLOW_TAB, x
    inx
    inx
    iny
    cpy #MET_GLOW_BANDS
    bcc @band
    sep #$20
    .a8
    stz a:ES_GLOW_TAB, x            ; the terminator
    rep #$20
    .a16
    rts

.assert MET_GLOW_BANDS * 2 + 1 = ES_GLOW_TAB_SIZE, error, "met_glow: the band table does not fill the glow_tab claim"
.assert MET_GLOW_BANDS * MET_GLOW_LINES = 224, error, "met_glow: the bands do not tile the 224 active scanlines"

; --- glow_math_on: ADD the fixed colour to backdrop + BG1 ------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; The layer mask: bit 0 = BG1 (the Mode 7 plane) and bit 5 = BACKDROP, with
; bit 4 (OBJ) DELIBERATELY CLEAR so the captured green ground and the white
; player are not stained red. That exclusion is the visible half of the effect
; — the glow rises BEHIND the captured sprites — and it is one bit.
;
; WIDTH-RISK: toggles A8 for the two byte stores and restores A16.
glow_math_on:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$2130                     ; CGWSEL: math always, fixed-colour addend
    lda #((1 << 5) | 1)             ; CGADSUB: backdrop + BG1, add, no halve
    sta a:$2131
    rep #$20
    .a16
    rts

; --- glow_math_off: no layers take the addend ------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
glow_math_off:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$2131                     ; CGADSUB: all layers off
    rep #$20
    .a16
    rts

; --- glow_disarm: the boot colour-math state (scene exit) ------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A.
;
; COLDATA holds whatever line the disarm caught, so all three planes are reset
; to zero: the next scene must not inherit a stray fixed colour. CGWSEL and
; CGADSUB go back to the ppu_reset defaults (rg_disarm's shape, and its
; reason).
glow_disarm:
    .a16
    .i16
    sep #$20
    .a8
    lda #(32 | 16)
    sta a:$2130                     ; CGWSEL: colour math never (HW default)
    stz a:$2131                     ; CGADSUB: all layers off
    lda #(128 | 64 | 32)
    sta a:$2132                     ; COLDATA: all planes, intensity 0
    rep #$20
    .a16
    rts
