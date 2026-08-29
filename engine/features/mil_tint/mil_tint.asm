; =============================================================================
; mil_tint.asm — the colour window over the lift shaft, written once
; =============================================================================
; The blend itself is composed: the allocator emits CGWSEL and CGADSUB from
; this feature's [[claims.blend]] and the scene writes those two bytes. What is
; here is the half no claim class composes — WHERE the math applies, which is
; window 1's bounds, and WHAT is added, which is COLDATA.
;
; ONCE AT ENTER AND NEVER AGAIN. The shaft does not move horizontally, so the
; window's bounds are constants. That is the whole reason this effect is free
; on this rail; a shaft that panned would want WH0/WH1 per scanline and that is
; an HDMA channel.
;
; CPU-WRITTEN REGISTERS, DECLARED (mil_window): WH0 $2126, WH1 $2127,
; WOBJSEL $2125, WOBJLOG $212B, COLDATA $2132 (three writes, one per channel).

; COLDATA ($2132) is ONE port with a channel-select in the top three bits:
; bit 7 = blue, bit 6 = green, bit 5 = red, and the low five bits are the
; intensity. So a colour is three writes to the same address, and the allocator
; names the three halves COLDATA_R/G/B because they are independently ownable.
MIL_COL_R = 1 << 5
MIL_COL_G = 1 << 6
MIL_COL_B = 1 << 7

; WOBJSEL: ProcessWindowMaskSettings(value, 4) puts layer index 4 = OBJ and
; index 5 = the COLOUR window (SnesPpu.cpp:1487-1495). Bit 5 is "window 1
; active for layer 5", i.e. window 1 gates colour math. Nothing else is set:
; the OBJ mask window stays off, and so does window 2.
MIL_WOBJSEL_MATH_W1 = 1 << 5

; --- mil_tint_arm: the window's bounds and the added colour (scene enter) ---
; CONTRACT mil_tint_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      window 1 spanning the lift shaft's columns, gated onto the colour
;             window, and COLDATA holding this rail's blue
;   clobbers: A, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
mil_tint_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_tint_arm"
    sep #$20
    .a8
    ; ---- window 1: the shaft, in screen X ---------------------------------
    ; DERIVED FROM THE GENERATOR'S OWN COLUMN PLAN, not typed: the car's first
    ; column and its width are emitted, so moving the elevator moves the light
    ; with it.
    lda #(SMIL_CAR_COL * 8)
    sta a:$2126                     ; WH0 — window 1, left
    lda #(SMIL_CAR_COL * 8 + SMIL_SHAFT_COLS * 8 - 1)
    sta a:$2127                     ; WH1 — ...and right, inclusive
    lda #MIL_WOBJSEL_MATH_W1
    sta a:$2125                     ; WOBJSEL: window 1 gates COLOUR MATH
    stz a:$212B                     ; WOBJLOG: OR, for both its fields. One
                                    ;   window makes the logic moot and it is
                                    ;   written anyway — a register nobody
                                    ;   establishes holds what the last scene
                                    ;   left in it (rule 5's sibling)
    ; ---- the colour the blend adds ----------------------------------------
    lda #(MIL_COL_B | SMIL_TINT_B)
    sta a:$2132                     ; COLDATA, blue
    lda #(MIL_COL_G | SMIL_TINT_G)
    sta a:$2132                     ; ...green
    lda #(MIL_COL_R | SMIL_TINT_R)
    sta a:$2132                     ; ...and red
    rep #$20
    .a16
    rts
