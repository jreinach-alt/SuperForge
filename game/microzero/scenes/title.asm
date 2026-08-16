; =============================================================================
; title scene — "MICROZERO" + PRESS START + the surviving global state line
; =============================================================================
; Runs in .scope title: scene symbols (ES_V_TEXT_CHR, ES_V_TEXT_MAP, ES_C_*,
; US_T_FRAMES) resolve to THIS scene's allocator map; globals resolve through
; the enclosing scope.
.scope title
.include "engine_state_title.inc"   ; GENERATED — this scene's map

; BG3 2bpp tile attr: palette 7 (claim pins CGRAM words 28..31), priority set
TXT_ATTR = (7 << 10) | (1 << 13)

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- scene init contract: this scene's user state ---------------------
    lda #0
    sta f:US_T_FRAMES_LONG
    ; ---- out of lives? start a fresh run. Reading a GLOBAL to
    ; decide, then rendering the result below, is the surviving-state proof
    ; in its strongest form: the loop's outcome changes what this scene draws.
    sep #$20
    .a8
    lda f:US_LIVES_LONG
    bne :+
    lda #LIVES_START
    sta f:US_LIVES_LONG
    rep #$20
    .a16
    lda #0
    sta f:US_SCORE_LONG
    sep #$20
    .a8
:   rep #$20
    .a16
    ; ---- CGRAM: backdrop (word 0) + the 4-color text sub-palette ----------
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #$A0                    ; backdrop = deep blue: BGR555 $28A0
    sta a:$2122
    lda #$28
    sta a:$2122
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    ; $2122 is a byte port: two writes per color, low then high (A8 only)
    lda #$00                    ; color 0 (transparent slot): black $0000
    sta a:$2122
    sta a:$2122
    lda #$84                    ; color 1: dark navy $1084
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; color 2: mid gray $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; color 3: white $7FFF
    sta a:$2122
    lda #$7F
    sta a:$2122
    ; ---- BG3 regs: map base, chr base, mode, layer enable -----------------
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #$04
    sta a:$212C                 ; TM: BG3 only
    rep #$20
    .a16
    ; ---- font + tilemap ---------------------------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- strings ----------------------------------------------------------
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_logo)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_logo
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 6*32 + 11)    ; row 6, col 11 (9 chars centered)
    jsr text_puts
    lda #.loword(s_press)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 14*32 + 10)   ; row 14, col 10
    jsr text_puts
    lda #.loword(s_score)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 20*32 + 6)    ; row 20, col 6
    jsr text_puts
    lda #.loword(s_lives)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 20*32 + 17)   ; row 20, col 17
    jsr text_puts
    ; score value (hex4) + lives digit — the surviving-global-state render
    lda f:US_SCORE_LONG
    ldx #(ES_V_TEXT_MAP + 20*32 + 12)
    jsr text_put_hex4
    sep #$20
    .a8
    lda f:US_LIVES_LONG
    rep #$20
    .a16
    and #$000F
    ldx #(ES_V_TEXT_MAP + 20*32 + 23)
    jsr text_put_digit
    rts

; --- exit: nothing to tear down (next enter re-declares its whole look) -----
exit:
    .a16
    .i16
    rts

; --- tick: one frame (display active — no VRAM writes here) -----------------
tick:
    .a16
    .i16
    lda f:US_T_FRAMES_LONG
    inc a
    sta f:US_T_FRAMES_LONG
    lda z:ES_INP_PRESS
    and #JOY_START
    beq :+
    sep #$20
    .a8
    lda #1                      ; scene id: race
    jsr sm_request
    rep #$20
    .a16
:   rts

.segment "RODATA"
s_logo:  .byte "MICROZERO", 0
s_press: .byte "PRESS START", 0
s_score: .byte "SCORE ", 0
s_lives: .byte "LIVES ", 0
.segment "CODE"
.endscope
