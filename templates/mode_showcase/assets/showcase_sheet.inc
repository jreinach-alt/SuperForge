; =============================================================================
; showcase_sheet.inc — the PARAM-SHEET (Start+Select): freeze + B/W full dump.
; =============================================================================
; Freezes the demo and renders a black/white text-only full-parameter dump (OBJ
; font, HUD pal 7 = white-on-black) that the user can screenshot to capture a
; whole config. Pages with </> and v/^ (6 slots, one slot per page; the page
; shows the slot label + its 5 param tags and values, all 30 reachable).
;
; Entered/left by show_sheet_toggle (Start+Select). While SHOW_FL_SHEET is set,
; demo_tick routes input to show_sheet_tick (no knob editing — the demo is
; frozen so the captured numbers are stable).
; =============================================================================

; -----------------------------------------------------------------------------
; show_sheet_toggle — flip SHOW_FL_SHEET (enter/leave the sheet).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; exits A16/I16.
.proc show_sheet_toggle
    rep #$30
    .a16
    .i16
    lda f:SHOW_FLAGS
    eor #SHOW_FL_SHEET
    sta f:SHOW_FLAGS
    and #SHOW_FL_SHEET
    beq @leave
    ; --- ENTER the sheet: black/white text-only. Hide the BG layers (TM = OBJ
    ;     only) so the dump is a clean B/W readout over the black backdrop, and
    ;     reset to page 0. SNAPSHOT the live TM first so LEAVE restores whatever
    ;     the page's mode set (F2: generic — no hardcoded Mode-1 TM). The NMI
    ;     commits SHADOW_TM each frame. ---
    sep #$20
    .a8
    lda #0
    sta f:SHOW_SHEET_PAGE
    lda SHADOW_TM                      ; snapshot the live (page's) TM
    sta f:SHOW_TM_SNAP
    lda #$10                          ; TM = OBJ only (BG1/2/3 hidden)
    sta SHADOW_TM
    rep #$20
    .a16
    sf_colormath_off                  ; clean black backdrop (no tint) for the dump
    rts
@leave:
    ; --- LEAVE the sheet: restore the page's BG layers from the snapshot (F2 —
    ;     generic over the mode; a Mode-3/4/7 page restores its own TM, not $17).
    sep #$20
    .a8
    lda f:SHOW_TM_SNAP
    sta SHADOW_TM
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; show_sheet_tick — service the frozen sheet: page with </> v/^, render the dump.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc show_sheet_tick
    rep #$30
    .a16
    .i16
    ; paging: RIGHT/UP -> next page ; LEFT/DOWN -> prev page (wrap 0..5)
    btnp #BTN_RIGHT
    bne @next
    btnp #BTN_UP
    bne @next
    btnp #BTN_LEFT
    bne @prev
    btnp #BTN_DOWN
    bne @prev
    ; L / R = select the active SRAM save slot (0..3); shown on the sheet.
    btnp #BTN_R
    beq @chk_l
    jsr show_slot_select_next
    bra @render
@chk_l:
    btnp #BTN_L
    beq @chk_save
    jsr show_slot_select_prev
    bra @render
@chk_save:
    ; A = save to the active SRAM slot ; B = recall the active slot
    btnp #BTN_A
    beq @chk_b
    jsr show_save_params
    bra @render
@chk_b:
    btnp #BTN_B
    beq @render
    jsr show_recall_params
    bra @render
@next:
    sep #$20
    .a8
    lda f:SHOW_SHEET_PAGE
    inc a
    cmp #SHOW_N_SLOTS
    bcc @nstore
    lda #0
@nstore:
    sta f:SHOW_SHEET_PAGE
    rep #$20
    .a16
    bra @render
@prev:
    sep #$20
    .a8
    lda f:SHOW_SHEET_PAGE
    bne @pdec
    lda #SHOW_N_SLOTS
@pdec:
    dec a
    sta f:SHOW_SHEET_PAGE
    rep #$20
    .a16
@render:
    jsr show_sheet_render
    rts
.endproc

; -----------------------------------------------------------------------------
; show_sheet_render — draw the current page: title "PARAM SHEET", "SLOT n NAME",
; then 5 rows of "TAG  VALUE". OBJ font, pal 7 (white), on the (still-on) screen.
; spr_clear first so the dump owns OAM slots 0.. and the demo's field is gone.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc show_sheet_render
    rep #$30
    .a16
    .i16
    spr_clear

    ; title
    sep #$20
    .a8
    lda #56
    sta f:SHOW_PEN_X
    lda #8
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    lda #.loword(sht_title)
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #^sht_title
    sta f:SHOW_STR_BANK
    rep #$20
    .a16
    jsr show_print_at

    ; "SLOT" label + page number + slot name
    sep #$20
    .a8
    lda #24
    sta f:SHOW_PEN_X
    lda #28
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    lda #.loword(sht_slot)
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #^sht_slot
    sta f:SHOW_STR_BANK
    rep #$20
    .a16
    jsr show_print_at
    ; page number after "SLOT "
    sep #$20
    .a8
    lda f:SHOW_SHEET_PAGE
    rep #$20
    .a16
    and #$00FF
    sta SF_OBJT_TMP
    sep #$20
    .a8
    lda #64
    sta SF_OBJT_X
    stz SF_OBJT_X+1
    lda #28
    sta SF_OBJT_Y
    stz SF_OBJT_Y+1
    lda #SF_OBJ_HUD_FLAGS
    sta SF_OBJT_FLAGS
    stz SF_OBJT_FLAGS+1
    rep #$20
    .a16
    jsr _sf_obj_num_run
    ; slot name
    sep #$20
    .a8
    lda f:SHOW_SHEET_PAGE
    rep #$20
    .a16
    and #$00FF
    tax
    jsr _show_slotname
    sep #$20
    .a8
    lda #112
    sta f:SHOW_PEN_X
    lda #28
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    jsr show_print_at

    ; 5 rows: TAG (x=32) + VALUE (x=120), y = 48 + r*14
    sep #$20
    .a8
    lda #0
    sta f:SHOW_HUD_P                  ; r = 0..4
    rep #$20
    .a16
@row:
    .a16
    .i16
    ; knob = page*5 + r
    sep #$20
    .a8
    lda f:SHOW_SHEET_PAGE
    rep #$20
    .a16
    and #$00FF
    sta f:SHOW_HUD_TMP2
    asl
    asl
    clc
    adc f:SHOW_HUD_TMP2             ; page*5
    sep #$20
    .a8
    clc
    adc f:SHOW_HUD_P                ; + r
    sta f:SHOW_HUD_KNOB
    rep #$20
    .a16

    ; row Y = 48 + r*14
    sep #$20
    .a8
    lda f:SHOW_HUD_P
    rep #$20
    .a16
    and #$00FF
    sta f:SHOW_HUD_TMP             ; r
    asl                            ; r*2
    sta f:SHOW_HUD_TMP2
    lda f:SHOW_HUD_TMP
    asl
    asl
    asl                            ; r*8
    clc
    adc f:SHOW_HUD_TMP2           ; r*8 + r*2... wait need r*14 = r*8+r*4+r*2
    sta f:SHOW_HUD_TMP2          ; r*10 so far (8+2)
    lda f:SHOW_HUD_TMP
    asl
    asl                            ; r*4
    clc
    adc f:SHOW_HUD_TMP2          ; r*14
    clc
    adc #48
    sep #$20
    .a8
    sta f:SHOW_PEN_Y
    rep #$20
    .a16

    ; tag at x=32
    sep #$20
    .a8
    lda #32
    sta f:SHOW_PEN_X
    lda f:SHOW_HUD_KNOB
    rep #$20
    .a16
    and #$00FF
    tax
    jsr _show_parmname
    jsr show_print_at

    ; value at x=120
    sep #$20
    .a8
    lda f:SHOW_HUD_KNOB
    rep #$20
    .a16
    and #$00FF
    tax
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL, x
    rep #$20
    .a16
    and #$00FF
    sta SF_OBJT_TMP
    sep #$20
    .a8
    lda #120
    sta SF_OBJT_X
    stz SF_OBJT_X+1
    lda f:SHOW_PEN_Y
    sta SF_OBJT_Y
    stz SF_OBJT_Y+1
    lda #SF_OBJ_HUD_FLAGS
    sta SF_OBJT_FLAGS
    stz SF_OBJT_FLAGS+1
    rep #$20
    .a16
    jsr _sf_obj_num_run

    ; advance r
    sep #$20
    .a8
    lda f:SHOW_HUD_P
    inc a
    sta f:SHOW_HUD_P
    cmp #SHOW_N_PARAMS
    bcs @done
    rep #$20
    .a16
    jmp @row
@done:
    rep #$20
    .a16

    ; --- Active SRAM SAVE slot indicator (F11): "SAVE n" top-right. L/R change n,
    ;     A saves to / B recalls the active slot. Surfaces which find the screen
    ;     will write/read. ---
    sep #$20
    .a8
    lda #160
    sta f:SHOW_PEN_X
    lda #8
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    lda #.loword(sht_save)
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #^sht_save
    sta f:SHOW_STR_BANK
    rep #$20
    .a16
    jsr show_print_at
    ; the slot digit after "SAVE "
    sep #$20
    .a8
    lda f:SHOW_SAVE_SLOT_SEL
    rep #$20
    .a16
    and #$00FF
    sta SF_OBJT_TMP
    sep #$20
    .a8
    lda #200
    sta SF_OBJT_X
    stz SF_OBJT_X+1
    lda #8
    sta SF_OBJT_Y
    stz SF_OBJT_Y+1
    lda #SF_OBJ_HUD_FLAGS
    sta SF_OBJT_FLAGS
    stz SF_OBJT_FLAGS+1
    rep #$20
    .a16
    jsr _sf_obj_num_run
    rts
.endproc

sht_title: .byte "PARAM SHEET", 0
sht_slot:  .byte "SLOT", 0
sht_save:  .byte "SAVE", 0
