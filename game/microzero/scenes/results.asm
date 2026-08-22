; =============================================================================
; results scene — the race tally, and the proof the globals survived it
; =============================================================================
; Runs in .scope results. Structurally a sibling of title (bg_text + backdrop,
; Mode 1, BG3 only), which is the point: its scene-scoped VRAM/CGRAM/state
; occupy the SAME bytes race just released, and the allocation report proves
; it. What it renders comes from the GLOBAL score/lives — the values that had
; to survive title -> race -> here.
;
; The tally counts up to the score while the scene RUNS, so its digits cannot
; be written under forced blank: they go through bg_text's VBlank cell queue
; (text_queue_hex4 -> the NMI hook's text_vblank_commit), the same path the
; race HUD's lap digit uses.
.scope results
.include "engine_state_results.inc"  ; GENERATED — this scene's map

TXT_ATTR   = (7 << 10) | (1 << 13)  ; palette 7, priority (as title/race)
TALLY_STEP = 5                      ; score units per frame
; ...and the same number as a RATE the timebase can scale, so the count-up
; takes the same real second on both machines. On NTSC TS_STEP publishes 5 to
; the unit and the carried fraction stays 0 for ever, so the digits step
; exactly as they always did.
TS_TALLY_BASE = TALLY_STEP * TS_ONE
TALLY_CELL = ES_V_TEXT_MAP + 12 * 32 + 18   ; the 4 live hex digits

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- scene init contract: this scene's user state ---------------------
    lda #0
    sta f:US_TALLY_LONG
    stz z:US_TST_ACC            ; the timebase's carried fraction and this
    stz z:US_TST                ;   frame's step: power-on DP is RANDOM
                                ;   (rule 5), so these stores ARE the
                                ;   write-before-read contract
    sep #$20
    .a8
    sta f:US_R_DONE_LONG
    ; ---- CGRAM: backdrop (word 0) + the 4-color text sub-palette ----------
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    lda #$00                    ; backdrop = near-black maroon: BGR555 $1000
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; color 0 (transparent slot): black
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
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
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
    lda #.loword(s_head)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_head
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 6*32 + 12)    ; row 6, col 12 (7 chars centered)
    jsr text_puts
    lda #.loword(s_score)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 12*32 + 12)   ; row 12, col 12
    jsr text_puts
    lda #.loword(s_lives)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 16*32 + 11)   ; row 16, col 11
    jsr text_puts
    ; the tally starts at zero and counts up in tick; lives is static here
    lda f:US_TALLY_LONG
    ldx #TALLY_CELL
    jsr text_put_hex4
    sep #$20
    .a8
    lda f:US_LIVES_LONG
    rep #$20
    .a16
    and #$000F
    ldx #(ES_V_TEXT_MAP + 16*32 + 17)
    jsr text_put_digit
    rts

; --- exit: nothing to tear down (next enter re-declares its whole look) -----
exit:
    .a16
    .i16
    rts

; --- tick: count the tally up, then START returns to title ------------------
; Display is ACTIVE here, so the digits go through the VBlank cell queue.
tick:
    .a16
    .i16
    ; ---- this frame's region-correct tally step, published once -----------
    TS_STEP z:US_TST_ACC, TS_TALLY_BASE
    sta z:US_TST
    sep #$20
    .a8
    lda f:US_R_DONE_LONG
    bne @wait_start
    rep #$20
    .a16
    ; ---- step the tally toward the score ----------------------------------
    lda f:US_TALLY_LONG
    clc
    adc z:US_TST
    cmp f:US_SCORE_LONG
    bcc @store                  ; still below: keep counting
    lda f:US_SCORE_LONG         ; caught up: clamp and latch done
    sta f:US_TALLY_LONG
    sep #$20
    .a8
    lda #1
    sta f:US_R_DONE_LONG
    rep #$20
    .a16
    bra @render
@store:
    .a16
    sta f:US_TALLY_LONG
@render:
    .a16
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda f:US_TALLY_LONG
    ldx #TALLY_CELL
    jsr text_queue_hex4         ; the NMI hook commits it this VBlank
    rts
@wait_start:
    .a8
    .i16
    rep #$20
    .a16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq :+
    sep #$20
    .a8
    lda #0                      ; scene id: title
    jsr sm_request
    rep #$20
    .a16
:   .a16
    rts

.segment "RODATA"
s_head:  .byte "RESULTS", 0
s_score: .byte "SCORE ", 0
s_lives: .byte "LIVES ", 0
.segment "CODE"
.endscope
