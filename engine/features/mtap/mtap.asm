; =============================================================================
; mtap.asm — a four-pad adapter in port 2: detection, players 3 and 4
; =============================================================================
; ES_MTAP_ON (detection result) and the P3/P4 triples ES_INP3_* / ES_INP4_*
; (2 B each, DP; the JOY1 bit layout, so the JOY_* bit names game code uses
; for pad 1 apply verbatim). docs/102 §2 is the hardware sequence with its
; fullsnes citations; this file follows it step for step.
;
; Per frame, in order: input_read (P1), input2_read (P2), mtap_read (P3, P4).

; The D7 guard's spin count (docs/102 D7). The automatic read begins no later
; than H=95.5 of the first VBlank line, i.e. <= 382 master cycles after the
; VBlank flag rises. One `dex`/`bne` pass is >= 30 mc even from FastROM (two
; fetches + one internal cycle per instruction), so 16 passes are >= 480 mc:
; past the latest start with margin, so the busy-wait that follows cannot
; mistake "not started yet" for "already finished".
MTAP_START_SPIN = 16

; --- mtap_init: boot init + detection -----------------------------------------
; CONTRACT mtap_init
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      ES_MTAP_ON = 1 when an adapter answered detection in port 2,
;             0 otherwise; the six P3/P4 words zeroed (the write-before-read
;             establishment — power-on DP is random, rule 5); WRIO = $FF
;             (every line released: slot select = slots 1/2); strobe low
;   clobbers: A, X, N, Z, C
;   assumes:  ONCE, from MAIN's boot block, with interrupts disabled and the
;             automatic joypad read OFF (NMITIMEN bit 0 clear — init.inc's
;             state, before MAIN arms $4200). Detection strobes and clocks
;             port 2 by hand, which would corrupt an automatic read in
;             flight (fullsnes: "reading $4016/7 or writing $4016 during this
;             time will also screw things up")
;   tail:     rts
;
; DETECTION (fullsnes, docs/102 §2): strobe high, 8 clocks of $4017 bit 1 ->
; byte A; strobe low, 8 more -> byte B; present iff A = $FF and B <> $FF. An
; adapter forces pin 5 high while the strobe is on; a plain pad never drives
; pin 5 at all (A = B = 0). B is pad data, and no pad holds all four d-pad
; directions, so B = $FF cannot be a real adapter. The two bytes are gathered
; IN the flag claim itself (A in the low byte, B in the high) and the claim is
; then overwritten with the verdict, so detection needs no scratch byte.
mtap_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mtap_init"
    stz z:ES_INP3_CUR
    stz z:ES_INP3_PREV
    stz z:ES_INP3_PRESS
    stz z:ES_INP4_CUR
    stz z:ES_INP4_PREV
    stz z:ES_INP4_PRESS
    stz z:ES_MTAP_ON                ; both detection bytes start at 0
    sep #$20
    .a8
    lda #$FF
    sta a:$4201                     ; WRIO: all lines HighZ — select slots 1/2
    lda #$01
    sta a:$4016                     ; strobe ON
    ldx #8
@det_a:
    .a8
    lda a:$4017
    lsr a
    lsr a                           ; C = bit 1 (port 2 pin 5)
    rol z:ES_MTAP_ON                ; byte A
    dex
    bne @det_a
    stz a:$4016                     ; strobe OFF (the auto-read needs it low)
    ldx #8
@det_b:
    .a8
    lda a:$4017
    lsr a
    lsr a
    rol z:ES_MTAP_ON + 1            ; byte B
    dex
    bne @det_b
    lda z:ES_MTAP_ON
    cmp #$FF
    bne @absent                     ; A <> $FF: nothing forced pin 5 high
    lda z:ES_MTAP_ON + 1
    cmp #$FF
    beq @absent                     ; B = $FF: pin 5 stuck high, not pad data
    rep #$20
    .a16
    lda #1
    sta z:ES_MTAP_ON
    rts
@absent:
    .a8
    rep #$20
    .a16
    stz z:ES_MTAP_ON
    rts

; --- mtap_read: latch this frame's P3 + P4 (call once per frame) --------------
; CONTRACT mtap_read
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MTAP_ON; with it set, $421E (the auto-read's JOY4 = slot 2)
;             and 16 clocks of $4017 bit 0 under WRIO.7 = 0 (slot 3)
;   out:      ES_INP3_* / ES_INP4_* on input_read's edge convention (cur, prev,
;             press = cur AND NOT prev). With no adapter, nothing is written:
;             the words keep mtap_init's zeros, so P3/P4 read nothing pressed
;   clobbers: A, X, N, Z, C (X only on the adapter path's D7 guard)
;   assumes:  ONCE per frame from the main thread, after the frame's automatic
;             read has STARTED (any time from the top of the frame until line
;             224; the guard below covers arriving in VBlank before it
;             starts). Must complete before the next VBlank — the manual
;             clocks would race that frame's automatic read. A mid-frame IRQ
;             that reads $2137 must not land inside the 16-clock window,
;             where WRIO.7 = 0 disables the H/V latch (docs/102 D9)
;   tail:     rts
;
; ORDER (fullsnes, docs/102 §2): slots 1/2 are already in $421A/$421E from the
; automatic read; THEN WRIO.7 = 0 selects slots 3/4 and 16 clocks of $4017
; bring slot 3 out of bit 0, first bit = B, so rotating each bit in from the
; right lands the word in the JOY1 layout; THEN WRIO.7 = 1 again, and nothing
; touches the port until the next frame's automatic read. The 1->0 edge
; latches the PPU H/V counters as a side effect (fullsnes; docs/102 D9).
mtap_read:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mtap_read"
    lda z:ES_MTAP_ON
    bne @present
    rts                             ; no adapter: the whole per-frame cost
@present:
    .a16
    sep #$20
    .a8
    ; ---- D7: never clock the port before the automatic read has run -------
    lda a:$4212                     ; HVBJOY: bit 7 VBlank, bit 0 auto-read busy
    bpl @wait_done                  ; active display: this frame's read is over
    lsr a
    bcs @wait_done                  ; busy: it has started, wait it out
    ldx #MTAP_START_SPIN            ; VBlank and idle: before it started or
@spin:                              ;   after it ended — wait past its latest
    .a8                             ;   start, then the busy-wait decides
    dex
    bne @spin
@wait_done:
    .a8
    lda a:$4212
    lsr a
    bcs @wait_done                  ; auto-read in progress
    ; ---- P3: slot 2, delivered by the automatic read to JOY4 ($421E) ------
    rep #$20
    .a16
    lda z:ES_INP3_CUR
    sta z:ES_INP3_PREV
    lda a:$421E
    sta z:ES_INP3_CUR
    lda z:ES_INP3_PREV
    eor #$FFFF
    and z:ES_INP3_CUR
    sta z:ES_INP3_PRESS
    ; ---- P4: slot 3, clocked by hand with the select line low -------------
    lda z:ES_INP4_CUR
    sta z:ES_INP4_PREV
    sep #$20
    .a8
    lda #$7F
    sta a:$4201                     ; WRIO.7 = 0: the adapter routes slots 3/4
    .repeat 8                       ; bits 1-8 (B Y Sel St U D L R): high byte.
    lda a:$4017                     ;   Unrolled: eight rotations replace all
    lsr a                           ;   eight bits, so no clear is needed, and
    rol z:ES_INP4_CUR + 1           ;   no loop counter is paid per clock
    .endrepeat
    .repeat 8                       ; bits 9-16 (A X L R + signature): low byte
    lda a:$4017
    lsr a
    rol z:ES_INP4_CUR
    .endrepeat
    lda #$FF
    sta a:$4201                     ; WRIO.7 = 1: slots 1/2 for the next frame's
                                    ;   automatic read; no access until then
    rep #$20
    .a16
    lda z:ES_INP4_PREV
    eor #$FFFF
    and z:ES_INP4_CUR
    sta z:ES_INP4_PRESS
    rts

; --- pad_btn / pad_btnp: the player-indexed query (btn / btnp) ---------------
; CONTRACT pad_btn
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = a button mask (JOY1 bit layout), X = player 0-3
;   out:      A = that player's HELD word AND the mask; Z set iff none of the
;             masked buttons is held. Any other X answers 0 (Z set)
;   clobbers: A, N, Z, C. X and Y are preserved
;   assumes:  this frame's input_read / input2_read / mtap_read have run
;   tail:     rts
pad_btn:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pad_btn"
    cpx #0
    beq @p1
    cpx #1
    beq @p2
    cpx #2
    beq @p3
    cpx #3
    beq @p4
    lda #0                          ; out of range: nothing is held
    rts
@p1:
    .a16
    and z:ES_INP_CUR
    rts
@p2:
    .a16
    and z:ES_INP2_CUR
    rts
@p3:
    .a16
    and z:ES_INP3_CUR
    rts
@p4:
    .a16
    and z:ES_INP4_CUR
    rts

; CONTRACT pad_btnp
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = a button mask, X = player 0-3
;   out:      A = that player's PRESSED-THIS-FRAME word AND the mask (the
;             rising edge: held now, not last frame); Z set iff none. Any
;             other X answers 0 (Z set)
;   clobbers: A, N, Z, C. X and Y are preserved
;   assumes:  this frame's input_read / input2_read / mtap_read have run
;   tail:     rts
pad_btnp:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pad_btnp"
    cpx #0
    beq @p1
    cpx #1
    beq @p2
    cpx #2
    beq @p3
    cpx #3
    beq @p4
    lda #0
    rts
@p1:
    .a16
    and z:ES_INP_PRESS
    rts
@p2:
    .a16
    and z:ES_INP2_PRESS
    rts
@p3:
    .a16
    and z:ES_INP3_PRESS
    rts
@p4:
    .a16
    and z:ES_INP4_PRESS
    rts
