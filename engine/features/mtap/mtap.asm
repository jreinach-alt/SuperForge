; =============================================================================
; mtap.asm — a four-pad adapter in port 2: detection, players 3 and 4
; =============================================================================
; ES_MTAP_ON (detection result) and the P3/P4 triples ES_INP3_* / ES_INP4_*
; (2 B each, DP; the JOY1 bit layout, so the JOY_* bit names game code uses
; for pad 1 apply verbatim). docs/102 §2 is the hardware sequence with its
; fullsnes citations; this file follows it step for step.
;
; Per frame, in order: input_read (P1), input2_read (P2), mtap_read (P3, P4).

; The D7 guard's line (docs/102 D7). The automatic read starts between H=32.5
; and H=95.5 of the FIRST VBlank line and runs 4224 master cycles (just over 3
; lines), so a caller that finds HVBJOY in VBlank with the read idle is either
; on that first line, before it started, or on a later line, after it ended —
; and the V counter tells the two apart without waiting. 225 is the first
; VBlank line with SETINI's overscan bit clear, on NTSC and PAL alike; no rail
; in this tree sets overscan (docs/94 R1 is unbuilt). A rail that does must
; revisit this constant.
MTAP_VBL_LINE = 225

; PER-PAD PRESENCE (docs/102 D10). A standard pad shifts out 16 bits and then
; "17th and up: Padding (always 1=Low) (or 0=High when no pad connected)"
; (fullsnes, Joypad bits; the ID table's "No controller connected" row says
; the same). So one clock past the 16th tells a pad from an empty port or an
; empty adapter slot. ES_MTAP_PADS holds the answer, bit n = player n+1.
MTAP_PAD_P1 = $01
MTAP_PAD_P2 = $02
MTAP_PAD_P3 = $04
MTAP_PAD_P4 = $08

; THE CENSUS PERIOD (adapter only): the countdown reloaded by a census's
; second half; it runs out — the next first half — on the 32nd call after
; it, so one census every MTAP_CENSUS_EVERY + 1 = 33 calls. Each census is
; two calls in a row (players 1-3, then player 4 — split so that neither
; call passes two scanlines, docs/102 §7.2), so presence is at most 33 calls
; stale. It counts CALLS, not time: it is a hot-plug
; sampling interval, not a game rate, and nothing on screen moves by it.
MTAP_CENSUS_EVERY = 32              ; census countdown (period = this + 1 calls)

; --- MTAP_P4_BUTTONS: slot 3's twelve buttons into ES_INP4_CUR ----------------
; WIDTH-RISK: entry A8 (asserted at every expansion), exit A8; no sep/rep, no
; labels. Expects WRIO.7 = 0 (slots 3/4 selected) and the auto-read over. Bits
; 1-8 (B Y Sel St U D L R) rotate into the high byte, 9-12 (A X L R) into the
; low byte, which is then shifted up to bits 7-4 (the JOY1 layout), bits 3-0
; coming out 0. Unrolled: eight rotations replace all eight bits, so no clear
; is needed, and no loop counter is paid per clock. Leaves slot 3 clocked 12
; times — the census adds its 13th-17th after this.
.macro MTAP_P4_BUTTONS
    SF_ASSERT_A 8, "MTAP_P4_BUTTONS"
    .repeat 8
    lda a:$4017
    lsr a
    rol z:ES_INP4_CUR + 1
    .endrepeat
    .repeat 4
    lda a:$4017
    lsr a
    rol z:ES_INP4_CUR
    .endrepeat
    lda z:ES_INP4_CUR               ; the low nibble up to bits 7-4 (last
    asl a                           ;   frame's nibble rotated out the top as
    asl a                           ;   this one came in)
    asl a
    asl a
    sta z:ES_INP4_CUR
.endmacro

; --- mtap_init: boot init + detection + the first census ----------------------
; CONTRACT mtap_init
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      ES_MTAP_ON = 1 when an adapter answered detection in port 2,
;             0 otherwise; the six P3/P4 words zeroed (the write-before-read
;             establishment — power-on DP is random, rule 5); ES_MTAP_PADS =
;             which pads answered the boot census (bit n = player n+1; P3/P4
;             only behind an adapter); ES_MTAP_TICK = a full census period,
;             players 1-3 next; WRIO = $FF (every line released: slot select
;             = slots 1/2); strobe low
;   clobbers: A, X, N, Z, C
;   assumes:  ONCE, from MAIN's boot block, with interrupts disabled and the
;             automatic joypad read OFF (NMITIMEN bit 0 clear — init.inc's
;             state, before MAIN arms $4200). Detection and the census strobe
;             and clock both ports by hand, which would corrupt an automatic
;             read in flight (fullsnes: "reading $4016/7 or writing $4016
;             during this time will also screw things up")
;   tail:     rts
;
; DETECTION (fullsnes, docs/102 §2): strobe high, 8 clocks of $4017 bit 1 ->
; byte A; strobe low, 8 more -> byte B; present iff A = $FF and B <> $FF. An
; adapter forces pin 5 high while the strobe is on; a plain pad never drives
; pin 5 at all (A = B = 0). B is pad data, and no pad holds all four d-pad
; directions, so B = $FF cannot be a real adapter. The two bytes are gathered
; IN the flag claim itself (A in the low byte, B in the high) and the claim is
; then overwritten with the verdict, so detection needs no scratch byte.
;
; THE BOOT CENSUS: a fresh strobe, 16 clocks of both ports, then the 17th —
; $4016 bit 0 is P1, $4017 bit 0 is P2 (port 2's pad or slot 1), $4017 bit 1
; is P3 (slot 2; a plain pad leaves pin 5 undriven, and the bit is masked off
; without an adapter anyway). With an adapter, WRIO.7 = 0 and 17 clocks of
; $4017 bit 0 give P4's (slot 3's) 17th bit.
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
    stz z:ES_MTAP_PADS              ; high byte stays 0 for good
    lda #MTAP_CENSUS_EVERY          ; low byte: the countdown; high byte 0:
    sta z:ES_MTAP_TICK              ;   players 1-3 are the next census half
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
    lda #1
    bra @verdict
@absent:
    .a8
    lda #0
@verdict:
    .a8
    sta z:ES_MTAP_ON
    stz z:ES_MTAP_ON + 1
    ; ---- the boot census --------------------------------------------------
    lda #$01
    sta a:$4016                     ; strobe ON: every pad, both ports, latched
    stz a:$4016                     ; strobe OFF
    ldx #16
@skip16:
    .a8
    lda a:$4016                     ; one clock of port 1...
    lda a:$4017                     ; ...and of port 2 (slots 1/2)
    dex
    bne @skip16
    lda a:$4017                     ; the 17th: bit 0 = P2, bit 1 = P3
    asl a
    and #(MTAP_PAD_P2 | MTAP_PAD_P3)
    sta z:ES_MTAP_PADS
    lda a:$4016                     ; the 17th: bit 0 = P1
    and #MTAP_PAD_P1
    tsb z:ES_MTAP_PADS
    lda z:ES_MTAP_ON
    bne @boot_p4
    lda #MTAP_PAD_P3                ; no adapter: nothing is player 3, whatever
    trb z:ES_MTAP_PADS              ;   drives pin 5
    bra @init_done
@boot_p4:
    .a8
    lda #$7F
    sta a:$4201                     ; WRIO.7 = 0: slots 3/4
    ldx #17
@clock17:
    .a8
    lda a:$4017                     ; ends holding slot 3's 17th in bit 0
    dex
    bne @clock17
    lsr a
    bcc @p4_gone
    lda #MTAP_PAD_P4
    tsb z:ES_MTAP_PADS
@p4_gone:
    .a8
    lda #$FF
    sta a:$4201                     ; WRIO.7 = 1: slots 1/2 for the auto-read
@init_done:
    .a8
    ; RE-LATCH every pad before leaving. The census left each line clocked
    ; past its 16th bit, and the rail's FIRST mtap_read can come before the
    ; first automatic read has strobed anything (MAIN arms NMITIMEN and goes
    ; straight into its loop, outside VBlank, where the guard reads "over"):
    ; slot 3 would then shift out padding 1s — every button held, one frame.
    ; Measured on four_pads: player 4's token flipped at boot. A fresh latch
    ; is what detection alone used to leave behind.
    lda #$01
    sta a:$4016                     ; strobe ON
    stz a:$4016                     ; strobe OFF (the auto-read needs it low)
    rep #$20
    .a16
    rts

; --- mtap_read: latch this frame's P3 + P4 (call once per frame) --------------
; CONTRACT mtap_read
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MTAP_ON; with it set, $421E (the auto-read's JOY4 = slot 2)
;             and 12 clocks of $4017 bit 0 under WRIO.7 = 0 (slot 3: its
;             twelve buttons; the 4-bit signature that follows is not
;             clocked, and P4's bits 3-0 read 0 — a standard pad's own value);
;             on a census call, one more clock of $4016 and $4017 (players
;             1-3's 17th bits) or five more of slot 3 (player 4's)
;   out:      ES_INP3_* / ES_INP4_* on input_read's edge convention (cur, prev,
;             press = cur AND NOT prev); ES_MTAP_PADS refreshed by a census
;             every MTAP_CENSUS_EVERY + 1 calls (players 1-3 on one, player 4
;             on the next). With no adapter, nothing is written: the words
;             keep mtap_init's zeros, so P3/P4 read nothing pressed, and
;             presence stays what the boot census found
;   clobbers: A, N, Z, C. X and Y are preserved
;   assumes:  the AUTOMATIC JOYPAD READ IS ENABLED (NMITIMEN bit 0 set):
;             with it off, a call on the first VBlank line waits forever for
;             a read that never starts (the guard below). ONCE per frame from
;             the main thread, after the frame's automatic read has STARTED
;             (any time from the top of the frame until line 224; the guard
;             covers arriving in VBlank before it starts — at a measured
;             4.6-4.8 scanlines, docs/102 §7.2). Must complete before the
;             next VBlank — the manual clocks would race that frame's
;             automatic read. A mid-frame IRQ that reads $2137 must not land
;             inside the clock window, where WRIO.7 = 0 disables the H/V
;             latch (docs/102 D9). Nothing else may clock $4016/$4017
;             between the automatic read and this call (a census reads the
;             17th bit)
;   tail:     rts
;
; ORDER (fullsnes, docs/102 §2): slots 1/2 are already in $421A/$421E from the
; automatic read; THEN WRIO.7 = 0 selects slots 3/4 and 12 clocks of $4017
; bring slot 3's buttons out of bit 0, first bit = B, so rotating each bit in
; from the right lands the word in the JOY1 layout ("read any number of bits",
; fullsnes); THEN WRIO.7 = 1 again, and nothing touches the port until the
; next frame's automatic read. The 1->0 edge latches the PPU H/V counters as a
; side effect (fullsnes; docs/102 D9). A census reads players 1-3's 17th bits
; BEFORE the select line drops (they are the next bit out of each line the
; automatic read left after 16), and player 4's after slot 3's 12th clock.
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
    bpl @read_over                  ; active display: this frame's read is over
    lsr a
    bcs @wait_done                  ; busy: it has started, wait it out
    lda a:$2137                     ; VBlank and idle: latch H/V (WRIO.7 is 1 —
    lda a:$213F                     ;   every exit of this file leaves it so),
    lda a:$213D                     ;   reset the read flip-flops (the tree's
    cmp #<MTAP_VBL_LINE             ;   convention: each reader resets its own),
    bne @read_over                  ;   V low byte. Past the first line: over
@wait_start:
    .a8
    lda a:$4212                     ; the first VBlank line, before the start:
    lsr a                           ;   wait for it to start...
    bcc @wait_start
@wait_done:
    .a8
    lda a:$4212
    lsr a
    bcs @wait_done                  ; ...and to finish
@read_over:
    .a8
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
    dec z:ES_MTAP_TICK              ; the census clock: the whole per-frame
    beq @census                     ;   cost of presence, one dec + one branch
@slot3:
    .a8
    lda #$7F
    sta a:$4201                     ; WRIO.7 = 0: the adapter routes slots 3/4
    MTAP_P4_BUTTONS                 ; slot 3's twelve buttons, A8 in and out
@release:
    .a8
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
@census:
    .a8
    lda z:ES_MTAP_TICK + 1          ; 0 = players 1-3 next; else player 4,
    bne @census_p4                  ;   and A is the countdown's reload
    ; ---- census, first half: players 1-3, one more clock of each line ------
    lda a:$4016                     ; 17th bit: bit 0 = P1
    lsr a                           ; C = P1
    lda a:$4017                     ; 17th bit: bit 0 = P2 (slot 1), 1 = P3
    rol a                           ; bit 0 = P1, 1 = P2, 2 = P3 (3-7: junk)
    eor z:ES_MTAP_PADS              ; the masked merge: bits 0-2 from this
    and #(MTAP_PAD_P1 | MTAP_PAD_P2 | MTAP_PAD_P3) ; census, the rest (player
    eor z:ES_MTAP_PADS              ;   4's bit, the other half's, and the
    sta z:ES_MTAP_PADS              ;   zero bits 4-7) kept as they were
    lda #1
    sta z:ES_MTAP_TICK              ; the next call is the second half...
    lda #MTAP_CENSUS_EVERY
    sta z:ES_MTAP_TICK + 1          ; ...and reloads the countdown from here
    jmp @slot3                      ; (out of a branch's reach)
@census_p4:
    .a8
    ; ---- census, second half: player 4, slot 3's 13th-17th clocks ---------
    sta z:ES_MTAP_TICK              ; A = MTAP_CENSUS_EVERY (the first half
    stz z:ES_MTAP_TICK + 1          ;   left it there); players 1-3 next time
    lda #$7F
    sta a:$4201                     ; WRIO.7 = 0: slots 3/4
    MTAP_P4_BUTTONS
    .repeat 4
    lda a:$4017                     ; bits 13-16: the ID nibble, not kept
    .endrepeat
    lda a:$4017                     ; bit 17: 1 = a pad in slot 3
    lsr a
    lda #MTAP_PAD_P4                ; (lda leaves C alone)
    bcs @p4_here
    trb z:ES_MTAP_PADS
    bra @p4_done
@p4_here:
    .a8
    tsb z:ES_MTAP_PADS
@p4_done:
    .a8
    ; @release's tail, inlined: a jump back to it costs this half the
    ; margin that keeps it under two scanlines (docs/102 §7.2)
    lda #$FF
    sta a:$4201                     ; WRIO.7 = 1: slots 1/2 for the next frame
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

; --- pad_here: is player X's pad connected? -----------------------------------
; CONTRACT pad_here
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = player 0-3; ES_MTAP_PADS
;   out:      A = that player's MTAP_PAD_Pn bit when its pad answered the last
;             census (its 17th bit read 1), else 0; Z set iff 0. Any other X
;             answers 0 (Z set)
;   clobbers: A, N, Z, C. X and Y are preserved
;   assumes:  mtap_init has run (the boot census). With an adapter, presence
;             is refreshed every MTAP_CENSUS_EVERY + 1 mtap_read calls; without
;             one it is the boot census's answer (the absent path stays a
;             flag test, docs/102 D10)
;   tail:     rts
pad_here:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pad_here"
    cpx #4
    bcs @nobody                     ; out of range: nobody is there
    lda f:mtap_pad_bit, x           ; a byte table read as a word: the high
    and z:ES_MTAP_PADS              ;   byte is the next entry, and the AND
    rts                             ;   clears it (ES_MTAP_PADS' is always 0)
@nobody:
    .a16
    lda #0
    rts
mtap_pad_bit:                       ; data, never executed: player -> its bit
    .byte MTAP_PAD_P1, MTAP_PAD_P2, MTAP_PAD_P3, MTAP_PAD_P4, 0
