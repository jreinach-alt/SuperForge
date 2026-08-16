; =============================================================================
; title scene — "ASTRO BARRAGE" + PRESS START, and the run counter
; =============================================================================
; Deliberately plain (bg_text + backdrop, the two cheapest features in the
; tree). It has a job beyond decoration: it is the scene the shooter is NOT
; running in, so returning here proves shmup_bg's and shmup_obj's teardown. A
; sprite left in the OAM shadow, or a BG1 scroll still being committed by the
; NMI hook, would show up here through registers this scene never wrote.
;
; It is ALSO where a restart passes through: scene_mgr refuses a
; self-transition, so GAME OVER -> START comes here and START goes back, which
; re-enters play::enter under forced blank where every screen a fresh round
; needs is legal to write.
.scope title
.include "engine_state_title.inc"   ; GENERATED — this scene's map

; BG3 2bpp tile attr: palette 7 (claim pins CGRAM words 28..31), priority set
TXT_ATTR = (7 << 10) | (1 << 13)

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    lda #0
    sta f:US_T_FRAMES_LONG
    ; ---- CGRAM: backdrop (word 0) + the 4-colour text sub-palette ---------
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #<SHM_SKY               ; the same night sky the shooter flies over
    sta a:$2122
    lda #>SHM_SKY
    sta a:$2122
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    ; $2122 is a byte port: two writes per colour, low then high (A8 only)
    lda #$00                    ; colour 0 (transparent slot): black $0000
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
    ; ---- BG3 regs: map base, chr base, mode, layer enable -----------------
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
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
    ldx #(ES_V_TEXT_MAP + 8*32 + 10)    ; row 8, col 10 (13 chars, centred)
    jsr text_puts
    lda #.loword(s_press)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 14*32 + 10)   ; row 14, col 10
    jsr text_puts
    lda #.loword(s_runs)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 20*32 + 10)   ; row 20, col 10
    jsr text_puts
    lda f:US_RUNS_LONG                  ; the surviving-global-state render
    ldx #(ES_V_TEXT_MAP + 20*32 + 15)
    jsr text_put_hex4
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
    lda #SCENE_PLAY
    jsr sm_request
    rep #$20
    .a16
:   rts

.segment "RODATA"
s_logo:  .byte "ASTRO BARRAGE", 0
s_press: .byte "PRESS START", 0
s_runs:  .byte "RUNS ", 0
.segment "CODE"
.endscope
