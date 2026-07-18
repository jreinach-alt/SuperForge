; =============================================================================
; showcase_hud.inc — the OBJ-HUD readout (composes brick B1, sf_obj_text).
; =============================================================================
; GENERIC over the ACTIVE mode's SHOW_A_SLOT_NAME / SHOW_A_PARM_NAME (resolved
; from the per-mode vtables on demo entry) + SHOW_KNOB_VAL.
;   TOP strip (rows ~4-16, OAM slots 0..): active slot label + the 5 param tags
;                                          and their live values.
;   BOTTOM strip (row ~210, OAM slots ..47): the 6-slot bar, active slot lit
;                                          (drawn brighter / with a marker).
; Call show_hud_render once per demo frame, AFTER spr_clear (slots start at 0)
; and BEFORE the field tick (which takes slots 48..).
;
; The dynamic label/tag printing dereferences the page's pointer tables and
; feeds sf_obj_text's run helper directly (sf_obj_print itself only takes a bare
; assemble-time label, so this module supplies show_print_ptr for runtime ptrs).
; =============================================================================

; -----------------------------------------------------------------------------
; show_print_ptr — print a NUL string whose 24-bit pointer is in A(lo16)/Y(bank),
; at pen (SF_OBJT_X already set by caller) — actually we take x,y in scratch.
; Simpler API: show_print_at — A = lo16 ptr, X = bank byte, pen from SHOW_PEN_*.
; -----------------------------------------------------------------------------
; In:  SHOW_PEN_X / SHOW_PEN_Y = pen; SHOW_STR_LO/SHOW_STR_BANK = far ptr.
; Uses sf_obj_text's _sf_obj_print_run (slots in call order from SPRITE_COUNT).
; WIDTH-RISK: A16/I16 entry; A8 for the bank byte; exits A16/I16.
.proc show_print_at
    rep #$30
    .a16
    .i16
    lda f:SHOW_STR_LO
    sta SF_OBJT_STRPTR              ; low 16 of the far pointer
    sep #$20
    .a8
    lda f:SHOW_STR_BANK
    sta SF_OBJT_STRPTR+2           ; bank byte
    rep #$20
    .a16
    lda f:SHOW_PEN_X
    and #$00FF
    sta SF_OBJT_X
    lda f:SHOW_PEN_Y
    and #$00FF
    sta SF_OBJT_Y
    lda #SF_OBJ_HUD_FLAGS
    sta SF_OBJT_FLAGS
    jsr _sf_obj_print_run
    rts
.endproc

; -----------------------------------------------------------------------------
; show_num3 — A = value 0..255; draw 3 zero-padded decimal glyphs at pen
; (SHOW_NUM_X, SHOW_NUM_Y), OBJ pal 7, in call order from SPRITE_COUNT. Compact
; (3 glyphs vs sf_obj_num's 5) so the HUD readout fits the OAM 0-47 band.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the digit math; engine_spr A16/I16; exits
; A16/I16. Division by repeated subtraction (no MUL/DIV).
.proc show_num3
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    and #$FF
    sta f:SHOW_NUM_V                  ; remaining value
    ; hundreds digit
    ldx #100
    jsr _sn3_digit                   ; emit (value/100), value %= 100
    ; tens digit
    ldx #10
    jsr _sn3_digit
    ; units digit
    ldx #1
    jsr _sn3_digit
    rep #$30
    .a16
    .i16
    rts
.endproc

; _sn3_digit — A8/I16: emit one digit = SHOW_NUM_V / X (X=100/10/1), update
; SHOW_NUM_V %= X, advance the pen by 8. Places one glyph via engine_spr.
; WIDTH-RISK: A8/I16 entry; engine_spr needs A16/I16 (bracketed); exits A8/I16.
.proc _sn3_digit
    .a8
    .i16
    txa                               ; place value (100/10/1, low byte) -> A8
    sta f:SHOW_NUM_DV                 ; stash for the compare (STX has no long form)
    ldy #0                            ; digit count
@sub:
    lda f:SHOW_NUM_V
    cmp f:SHOW_NUM_DV
    bcc @emit                         ; value < place -> done
    sec
    sbc f:SHOW_NUM_DV
    sta f:SHOW_NUM_V
    iny
    bra @sub
@emit:
    ; glyph tile = SF_OBJG_0 + digit
    tya
    clc
    adc #SF_OBJG_0
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_TILE
    sep #$20
    .a8
    lda f:SHOW_NUM_X
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_X
    sep #$20
    .a8
    lda f:SHOW_NUM_Y
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_Y
    lda #SF_OBJ_HUD_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    ; advance pen X += 8
    sep #$20
    .a8
    lda f:SHOW_NUM_X
    clc
    adc #8
    sta f:SHOW_NUM_X
    rts                              ; A8/I16
.endproc

; -----------------------------------------------------------------------------
; _show_load_strptr — A = knob/slot index; load the page table entry (an .addr
; word in ROM bank $00) into SHOW_STR_LO/SHOW_STR_BANK. tbl chosen by carry-in:
; this helper is specialised below into _slotname / _parmname.
; -----------------------------------------------------------------------------
; _slotname: X = slot 0..5 -> SHOW_STR_* = SHOW_SLOT_NAME[X].
; WIDTH-RISK: A16/I16; exits A16/I16.
.proc _show_slotname
    rep #$30
    .a16
    .i16
    txa
    asl                              ; *2 (.addr = 2 bytes)
    tax
    lda f:SHOW_A_SLOT_NAME, x        ; lo16 ptr (ACTIVE mode's resolved table)
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #SHOW_PAGE_BANK              ; page string data links into ROM bank $00
    sta f:SHOW_STR_BANK
    rep #$20
    .a16
    rts
.endproc

; _parmname: X = knob 0..29 -> SHOW_STR_* = SHOW_PARM_NAME[X].
; WIDTH-RISK: A16/I16; exits A16/I16.
.proc _show_parmname
    rep #$30
    .a16
    .i16
    txa
    asl
    tax
    lda f:SHOW_A_PARM_NAME, x        ; ACTIVE mode's resolved param-tag ptr table
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #SHOW_PAGE_BANK              ; page string data links into ROM bank $00
    sta f:SHOW_STR_BANK
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; show_hud_render — the full readout (top label+values, bottom slot bar).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte math; exits A16/I16.
.proc show_hud_render
    rep #$30
    .a16
    .i16

    ; --- TOP: active slot label at (8, 6) ---
    sep #$20
    .a8
    lda f:SHOW_ACTIVE_SLOT
    rep #$20
    .a16
    and #$00FF
    tax                              ; X = slot
    jsr _show_slotname
    sep #$20
    .a8
    lda #16                           ; F14: x>=16 so the leftmost glyph isn't clipped
    sta f:SHOW_PEN_X
    lda #6
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    jsr show_print_at

    ; --- TOP: 5 param tags (row y=18) + values (row y=28) at X = 8 + p*48 ---
    sep #$20
    .a8
    lda #0
    sta f:SHOW_HUD_P                  ; p = 0..4 (loop counter, long scratch)
    rep #$20
    .a16
@pv:
    .a16
    .i16
    ; knob = active_slot*5 + p
    sep #$20
    .a8
    lda f:SHOW_ACTIVE_SLOT
    rep #$20
    .a16
    and #$00FF
    sta f:SHOW_HUD_TMP2              ; slot
    asl
    asl
    clc
    adc f:SHOW_HUD_TMP2             ; slot*5
    sep #$20
    .a8
    clc
    adc f:SHOW_HUD_P                ; + p = knob index
    sta f:SHOW_HUD_KNOB
    rep #$20
    .a16

    ; pen X = 8 + p*48 (p<=4 -> X<=200, on-screen)
    sep #$20
    .a8
    lda f:SHOW_HUD_P
    rep #$20
    .a16
    and #$00FF
    sta f:SHOW_HUD_TMP             ; p
    asl
    asl
    asl
    asl                            ; p*16
    sta f:SHOW_HUD_TMP2
    lda f:SHOW_HUD_TMP
    asl
    asl
    asl
    asl
    asl                           ; p*32
    clc
    adc f:SHOW_HUD_TMP2          ; p*48
    clc
    adc #16                      ; + 16 (F14: clear of the left overscan edge)
    sep #$20
    .a8
    sta f:SHOW_PEN_X
    lda #18
    sta f:SHOW_PEN_Y
    rep #$20
    .a16

    ; print the tag at (penX, 18)
    sep #$20
    .a8
    lda f:SHOW_HUD_KNOB
    rep #$20
    .a16
    and #$00FF
    tax                          ; X = knob index
    jsr _show_parmname
    jsr show_print_at

    ; print the value (3 digits, values are 0..255) at (penX, 28). 3 digits keeps
    ; the whole HUD readout inside the OAM 0-47 band (allocations §2).
    sep #$20
    .a8
    lda f:SHOW_HUD_KNOB
    rep #$20
    .a16
    and #$00FF
    tax
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL, x        ; value byte
    rep #$20
    .a16
    and #$00FF
    pha                          ; value -> show_num3 arg
    sep #$20
    .a8
    lda f:SHOW_PEN_X
    sta f:SHOW_NUM_X
    lda #28
    sta f:SHOW_NUM_Y
    rep #$20
    .a16
    pla
    jsr show_num3                ; A = value (0..255) -> 3 glyphs at pen

    ; advance p; loop while p < SHOW_N_PARAMS (compare + branch with no width
    ; toggle between them so the carry survives)
    sep #$20
    .a8
    lda f:SHOW_HUD_P
    inc a
    sta f:SHOW_HUD_P
    cmp #SHOW_N_PARAMS
    bcs @pv_done
    rep #$20
    .a16
    jmp @pv
@pv_done:
    rep #$20
    .a16
    jsr show_hud_bar               ; the bottom 6-slot bar
    rts
.endproc

; -----------------------------------------------------------------------------
; show_hud_bar — the BOTTOM 6-slot option bar at y=210. Each slot is a digit
; 0..5; the ACTIVE slot is drawn as the solid BAR glyph (lit). These land in OAM
; slots after the top strip but before the field — well within the §2 bottom
; band (rows >=208) so they never share a scanline with the field.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr runs A16/I16; X is the
; loop index (phx/plx around engine_spr); exits A16/I16.
.proc show_hud_bar
    rep #$30
    .a16
    .i16
    ; Deterministic band: the bottom bar owns OBJ 40-45 (allocations §2). Set the
    ; OAM base so the bar lands in its fixed band regardless of how many glyphs
    ; the top readout used (the meter + arena indicator own 36-39, drawn later).
    lda #SHOW_OAM_BAR_BASE
    sta SPRITE_COUNT
    ldx #0                            ; slot index 0..5
@bar:
    cpx #SHOW_N_SLOTS
    bcs @done
    ; pen X = 88 + slot*12 (centred-ish), Y = 210
    txa
    asl
    asl                               ; slot*4
    sta f:SHOW_HUD_TMP
    txa
    asl
    asl
    asl                               ; slot*8
    clc
    adc f:SHOW_HUD_TMP               ; slot*12
    clc
    adc #88
    sta SF_SPR_X
    lda #210
    sta SF_SPR_Y
    ; tile: active slot -> BAR glyph (lit); else digit '0'+slot
    sep #$20
    .a8
    txa
    cmp f:SHOW_ACTIVE_SLOT
    bne @digit
    lda #SF_OBJG_BAR                  ; active -> solid bar (lit)
    bra @put
@digit:
    txa
    clc
    adc #SF_OBJG_0                    ; '0'+slot
@put:
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_TILE
    lda #SF_OBJ_HUD_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    phx
    jsr engine_spr
    plx
    inx
    bra @bar
@done:
    rep #$30
    .a16
    .i16
    rts
.endproc
