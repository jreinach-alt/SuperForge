; =============================================================================
; aur_roll — the colour rolling through the tilemap's PALETTE FIELDS
; =============================================================================
; The whole animation, and the reason the rail is direct-colour. In an indexed
; 8bpp layer the tilemap entry's three palette bits are ignored outright
; (SnesPpu.cpp:1077); under direct colour they carry the LOW BIT OF EACH
; CHANNEL, so a map word is a per-tile COLOUR control.
;
; 143 tiles carry curtain and they fall in map rows AUR_ROLL_ROW0..+ROWS, so a
; phase IS that row range and playing the roll is DMA-ing the page the frame
; wants. All AUR_ROLL_PHASES of them are in ROM.
;
; THE PHASE IS CARRIED AS A BYTE OFFSET, not as an index. A page is 832 B and
; 832 is not a shift, so an index would need a multiply in the NMI hook every
; frame to reach its page; an offset needs an add, once, in the tick. The
; index is recoverable by dividing, which is what the tests do.
;
; NOTHING SCROLLS HERE, and that is a measurement rather than a preference.
; The sky's gradient survives 8bpp only as an ORDERED DITHER; slide
; neighbouring scanlines by different amounts and the dither's vertical
; coherence goes with them, so the gradient stops reading as texture and
; starts reading as static. The hardware would do the same — the dither is in
; the CHR and HDMA slides whole scanlines across it.

AUR_ROLL_REGS = $4300 + ES_D_AUR_ROLL_UP_CH * 16
AUR_ROLL_SPAN = AUR_ROLL_PHASES * AUR_ROLL_PAGE

; --- aur_roll_init ---------------------------------------------------------
; CONTRACT aur_roll_init
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      ES_AUR_PHASE and ES_AUR_HOLD zeroed
;   clobbers: N, Z
;   assumes:  enter-time. Power-on dp is RANDOM (rule 5), so this is the
;             write-before-read contract for both words
;   tail:     rts
aur_roll_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_roll_init"
    stz z:ES_AUR_PHASE
    stz z:ES_AUR_HOLD
    rts

; --- aur_roll_tick: step the page by the whole phases the scaler produced ---
; CONTRACT aur_roll_tick
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       A = WHOLE phases to advance this frame — TS_STEP's own output,
;             so the fraction is already carried by the scaler and a PAL
;             console covers the same wave in the same wall-clock time;
;             ES_AUR_HOLD nonzero freezes the roll
;   out:      ES_AUR_PHASE advanced by that many pages, wrapped at
;             AUR_ROLL_SPAN
;   clobbers: A, X, N, Z, C
;   assumes:  called once a frame from the main loop
;   tail:     rts
;
; THE FEATURE KEEPS NO ACCUMULATOR OF ITS OWN. TS_STEP already carries the
; fraction in the scene's `tsc_acc`, and a second accumulator downstream of it
; would be a second place for the same rate to drift.
aur_roll_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_roll_tick"
    ldx z:ES_AUR_HOLD
    bne @done
    tax
    beq @done                       ; no whole phase this frame
@step:
    .a16
    .i16
    lda z:ES_AUR_PHASE
    clc
    adc #AUR_ROLL_PAGE
    cmp #AUR_ROLL_SPAN
    bcc :+
    lda #0
:   sta z:ES_AUR_PHASE
    dex
    bne @step
@done:
    .a16
    .i16
    rts

; --- aur_roll_nmi: ONE transfer, the page the phase names -------------------
; CONTRACT aur_roll_nmi
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_AUR_PHASE — the byte offset of this frame's page
;   out:      map rows AUR_ROLL_ROW0..+ROWS-1 replaced in VRAM
;   clobbers: A, X, Y, N, Z, C, VMAIN, VMADD, DMA channel
;             ES_D_AUR_ROLL_UP_CH
;   assumes:  called from the NMI hook, inside VBlank. DAS is re-armed here,
;             per transfer, because the channel consumes it
;   tail:     rts
aur_roll_nmi:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "aur_roll_nmi"
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #(ES_V_AUR_MAP1 + AUR_ROLL_ROW0 * 32)
    sta a:$2116                     ; VMADD: the curtains' first map row
    lda z:ES_AUR_PHASE
    clc
    adc #.loword(aur_roll_bin)
    sta a:AUR_ROLL_REGS + 2         ; A1T
    ldx #AUR_ROLL_PAGE
    stx a:AUR_ROLL_REGS + 5         ; DAS — re-armed for THIS transfer
    sep #$20
    .a8
    lda #^aur_roll_bin
    sta a:AUR_ROLL_REGS + 4         ; A1B
    lda #ES_D_AUR_ROLL_UP_DMAP
    sta a:AUR_ROLL_REGS + 0         ; DMAP: A->B, 2 regs write-once
    lda #ES_D_AUR_ROLL_UP_BBAD
    sta a:AUR_ROLL_REGS + 1         ; BBAD: VMDATAL
    lda #(1 << ES_D_AUR_ROLL_UP_CH)
    sta a:$420B
    rts
