; =============================================================================
; title scene — "SUPER KIT QUEST", and the continue offer
; =============================================================================
; Text over the dusk colour — bg_text + backdrop, which is the whole
; composition a scene with no BG feature needs. It has three jobs beyond
; decoration:
;
;   1. It is the scene the game is NOT running in, so returning here proves
;      platformer_bg's and platformer_obj's teardown. A sprite left in the OAM
;      shadow, or a camera still being committed by the NMI hook, shows up here
;      through registers this scene never wrote.
;   2. It is where a restart passes through: scene_mgr refuses a
;      self-transition, so an ending screen's START comes here and START goes
;      back, re-entering play::enter under forced blank where the level, the
;      sky and every counter are legal to write.
;   3. It is where the SAVE is asked about. cont_gate runs on EVERY title entry
;      and decides two things at once: whether SELECT does anything, and
;      whether the line offering it is on screen. Those are one decision, so
;      they are made in one place.
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
    ; ---- CGRAM: the dusk backdrop + the 4-colour text sub-palette ---------
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #<PLF_DUSK              ; the same dusk the game is played against
    sta a:$2122
    lda #>PLF_DUSK
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
    ldx #(ES_V_TEXT_MAP + 8*32 + 8)     ; row 8, col 8 (15 chars, centred)
    jsr text_puts
    lda #.loword(s_press)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 13*32 + 10)   ; row 13, col 10
    jsr text_puts
    lda #.loword(s_runs)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 20*32 + 12)   ; row 20, col 12
    jsr text_puts
    lda f:US_RUNS_LONG                  ; the surviving-global-state render
    ldx #(ES_V_TEXT_MAP + 20*32 + 17)
    jsr text_put_hex4
    jsr cont_gate
    rts

; --- cont_gate: does slot 0 hold a continuable run? -------------------------
; In/out: A16/I16, DB=0, forced blank (called from enter). Clobbers A, X, Y.
;
; US_CONTOK := 1 and the CONTINUE line prints iff `sv_exists` answers 1 for
; slot 0. That single call IS the whole gate: `sv_exists` verifies magic,
; version, payload length AND the CRC-16 over the header and payload before
; answering (save/feature.toml), so there is nothing left for the game to
; re-derive from raw SRAM bytes. A gate that re-reads the version and length
; words itself is a second copy of that logic, and the second copy is the one
; that goes stale.
;
; Any miss — virgin, corrupt, cleared, foreign version — leaves US_CONTOK at 0,
; so no line prints, SELECT is inert, and new-game semantics stand untouched.
; The continue PATH re-checks anyway (play::enter gates on sv_load's return
; code), so a half-restored state is impossible by construction rather than by
; care.
cont_gate:
    .a16
    .i16
    lda #0
    sta f:US_CONTOK_LONG
    sta z:SV_SLOT               ; slot 0 (A is still 0)
    jsr sv_exists
    beq @done
    lda #1
    sta f:US_CONTOK_LONG
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_cont)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_cont
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 16*32 + 8)    ; row 16, col 8 (16 chars, centred)
    jsr text_puts
@done:
    .a16
    .i16
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
    ; ---- SELECT: continue, offered only when cont_gate said so ------------
    lda z:ES_INP_PRESS
    and #JOY_SELECT
    beq @start
    lda f:US_CONTOK_LONG
    beq @start
    lda #1
    sta f:US_CONTPEND_LONG      ; play::enter consumes this
    bra @go
@start:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    lda #0
    sta f:US_CONTPEND_LONG      ; START is always a fresh run, save or no save
@go:
    .a16
    .i16
    sep #$20
    .a8
    lda #SCENE_PLAY
    jsr sm_request
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

.segment "RODATA"
s_logo:  .byte "SUPER KIT QUEST", 0
s_press: .byte "PRESS START", 0
s_runs:  .byte "RUNS ", 0
s_cont:  .byte "SELECT: CONTINUE", 0
.segment "CODE"
.endscope
