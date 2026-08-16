; =============================================================================
; title scene — "THE ROOM" + PRESS START, and the visit counter
; =============================================================================
; Deliberately plain. Its job is to be a scene the lantern is
; NOT running in, so that returning here proves window_iris's disarm: if the
; window or the colour-math config leaked out of the room, this screen would
; be dimmed through registers it never wrote.
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
    ; ---- acoustics reset: without this, the title inherits whichever
    ; room's echo you exited
    ; through (START from the cavern left EVOL 70/EFB 96 running under the
    ; menu). The title is the boot baseline, so it queues the same dry
    ; ambience the song header establishes — reusing room_a_ambience keeps
    ; the export unchanged. Harmless at boot (a no-op re-statement of the
    ; header values, processed once Tad_Process runs).
    lda #SFX::room_a_ambience
    jsr Tad_QueueSoundEffect
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #$00                    ; backdrop = near-black $1000 (a cold dark)
    sta a:$2122
    lda #$10
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
    ldx #(ES_V_TEXT_MAP + 8*32 + 12)    ; row 8, col 12 (8 chars centred)
    jsr text_puts
    lda #.loword(s_press)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 16*32 + 10)   ; row 16, col 10
    jsr text_puts
    lda #.loword(s_visits)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 21*32 + 10)   ; row 21, col 10
    jsr text_puts
    lda f:US_VISITS_LONG                ; the surviving-global-state render
    ldx #(ES_V_TEXT_MAP + 21*32 + 17)
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
    lda #1                      ; scene id: room
    jsr sm_request
    rep #$20
    .a16
:   rts

.segment "RODATA"
s_logo:   .byte "THE ROOM", 0
s_press:  .byte "PRESS START", 0
s_visits: .byte "VISITS ", 0
.segment "CODE"
.endscope
