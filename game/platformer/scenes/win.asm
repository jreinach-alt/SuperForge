; =============================================================================
; win scene — YOU WIN, and the six coins that got there
; =============================================================================
; One of the two endings, and they are SEPARATE SCENES rather than one
; parameterised card (game.toml says why): only the loss banks the coin count
; to SRAM, and only the title after a loss offers SELECT = CONTINUE. Folding
; them would put that difference in a runtime flag the scene manager already
; models as an id.
;
; Both are text over the same dusk colour the game is played against, so an
; ending reads as the same world with the world taken away — and both prove
; platformer_bg's and platformer_obj's teardown, because a sprite left in the
; OAM shadow or a camera still being committed would show up here through
; registers this scene never wrote.
.scope win
.include "engine_state_win.inc"   ; GENERATED — this scene's map

TXT_ATTR = (7 << 10) | (1 << 13)    ; BG3 palette 7, priority

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #<PLF_DUSK
    sta a:$2122
    lda #>PLF_DUSK
    sta a:$2122
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; colour 0: black $0000
    sta a:$2122
    sta a:$2122
    lda #$84                    ; colour 1: dark navy $1084
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: white $7FFF
    sta a:$2122
    lda #$7F
    sta a:$2122
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #$04
    sta a:$212C                 ; TM: BG3 only — the level is GONE, not hidden
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_verdict)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_verdict
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 10*32 + 12)
    jsr text_puts
    ; ---- what the run was worth -------------------------------------------
    ; `bank` is the global word the round wrote on its way out, and on a loss
    ; it is ALSO the save's payload — one number, one place, so the screen and
    ; the battery cannot disagree about it.
    lda #.loword(s_coins)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 13*32 + 11)
    jsr text_puts
    lda f:US_BANK_LONG
    ldx #(ES_V_TEXT_MAP + 13*32 + 17)
    jsr text_put_digit
    lda #.loword(s_press)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 17*32 + 10)
    jsr text_puts
    rts

; --- exit: nothing to tear down --------------------------------------------
exit:
    .a16
    .i16
    rts

; --- tick: START returns to the title, where a restart is legal -------------
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq :+
    sep #$20
    .a8
    lda #SCENE_TITLE
    jsr sm_request
    rep #$20
    .a16
:   .a16
    .i16
    rts

.segment "RODATA"
s_verdict: .byte "YOU WIN!", 0
s_coins:   .byte "COINS", 0
s_press:   .byte "PRESS START", 0
.segment "CODE"
.endscope
