; =============================================================================
; room_b scene — the cavern: the same room, a different acoustic space
; =============================================================================
; A second room, deliberately the SAME composition as `room` — room_bg,
; bg_text, room_hero, room_logic, window_iris — because the whole point is that
; the rooms differ AUDIBLY: entering here fires room_b_ambience, which
; re-shapes the shared echo unit (EVOL 70 / EFB 96 against the
; program-constant 128 ms delay) while the music persists untouched. The
; caption is the only visual differentiation, so a screenshot still says which
; room the hero is in.
;
; LAYER OWNERSHIP: same statement as room.asm — this enter is the only writer
; of BGMODE, BG1SC, BG2SC, BG3SC, BG12NBA, BG34NBA and TM in this scene.
.scope room_b
.include "engine_state_room_b.inc"  ; GENERATED — this scene's map

; BG3 2bpp tile attr for the caption (palette 7, priority)
ROOM_TXT_ATTR = (7 << 10) | (1 << 13)

; scene-scoped copies of the room feature code — their claims are THIS
; scene's (engine_state_room_b.inc), distinct from room's
.include "room_bg.asm"
.include "room_hero.asm"
.include "room_logic.asm"
.include "window_iris.asm"

; The walk's base rate, in the 8.8 unit TS_STEP takes. room_logic's RM_SPEED
; is still the one number to reach for when tuning how the cavern feels.
TS_WALK_BASE = RM_SPEED * TS_ONE

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- the cavern's own state: spawn just inside the west door (the
    ; player walked east out of `room`, so continuity puts them here)
    stz z:US_TS_ACC             ; the timebase's carried fraction, and this
    stz z:US_TS_STEP            ;   frame's step: written before either is read
    jsr rm_spawn
    lda #(RM_LO + 2)
    sta z:US_PX
    ; ---- this room's acoustics: queue the ambience SFX. Tad_Process picks
    ; it up on the fade-in frames, so the echo re-shape happens under the
    ; transition, never on a settled visible frame.
    sep #$20
    .a8
    lda #SFX::room_b_ambience
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
    ; ---- BG1 + BG2: CHR, tilemaps, palettes, layer registers --------------
    jsr room_arm
    ; ---- the hero: CHR, palette, OBSEL, OAM slot --------------------------
    jsr hero_arm
    jsr hero2_arm               ; the twin: same CHR/palette, its own slot
    jsr hud_pips_arm            ; the visit pips (slots 0..7, PINNED so the
                                ;   row draws over both heroes)
    ; ---- BG3 caption ------------------------------------------------------
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; colour 0 (transparent slot)
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
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #ROOM_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    lda #ROOM_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_caption)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_caption
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 1*32 + 2)     ; row 1, col 2 — inside the wall
    jsr text_puts
    ; ---- the lantern: table skeleton, window + colour math, HDMA shadow ----
    jsr wi_arm
    ; ---- mode + layers: BG1 + BG2 + BG3 + OBJ -----------------------------
    sep #$20
    .a8
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #$17                    ; TM: BG1 + BG2 + BG3 + OBJ
    sta a:$212C
    ; ---- arm the iris channel in the HDMAEN shadow ------------------------
    lda z:ES_SM_NMI+2
    ora #(1 << ES_H_IRIS_CH)
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    ; ---- one full table + sprite placement BEFORE the first displayed
    ; frame (rule 5: the HDMA channel reads this table before any tick runs)
    jsr room_refresh
    rts

; --- exit: put the window, the colour math and the sprite back -------------
; In/out: A16/I16, DB=0, forced blank.
exit:
    .a16
    .i16
    jsr wi_disarm
    jsr hero_park
    jsr hero2_park
    jsr hud_pips_park
    rts

; --- tick: one frame -------------------------------------------------------
; In/out: A16/I16, DB=0. Display is active: no VRAM writes here.
tick:
    .a16
    .i16
    ; ---- this frame's region-correct walk step, published once -------------
    ; Read by RM_MOVE_PAD for both pads and both axes — one rate, so one
    ; answer per frame. On NTSC it is RM_SPEED to the pixel.
    TS_STEP z:US_TS_ACC, TS_WALK_BASE
    sta z:US_TS_STEP
    jsr rm_move
    jsr room_refresh
    ; ---- the west door: back to the room. PRESS edge at the left wall,
    ; mirroring room.asm's east door.
    lda z:US_PX
    cmp #(RM_LO + 1)
    bcs @no_door
    lda z:ES_INP_PRESS
    and #JOY_LEFT
    beq @no_door
    sep #$20
    .a8
    lda #1                      ; scene id: room
    jsr sm_request
    rep #$20
    .a16
@no_door:
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
:   rts

; --- room_refresh: put the hero and the lantern where the state says -------
; In/out: A16/I16, DB=0. Shared by enter and tick so the first displayed
; frame and every later one are produced by the same code.
room_refresh:
    .a16
    .i16
    jsr hero_place
    jsr hero2_place
    jsr rm_centre_x
    tax
    jsr rm_centre_y
    tay
    jsr wi_tick
    rts

.segment "RODATA"
s_caption: .byte "THE CAVERN ANSWERS BACK", 0
.segment "CODE"
.endscope
