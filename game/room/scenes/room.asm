; =============================================================================
; room scene — the playable slice: walk around a lit room
; =============================================================================
; Composition: room_bg (BG1 floor/walls + BG2 decor), bg_text (BG3 caption),
; room_hero (the OBJ), room_logic (movement), window_iris (the lantern).
;
; LAYER OWNERSHIP, asserted here and in room_bg/feature.toml because layer
; identity is not a resource the allocator models: this enter is the only
; writer of BGMODE, BG1SC, BG2SC, BG3SC, BG12NBA, BG34NBA and TM in this
; game's room scene.
.scope room
.include "engine_state_room.inc"    ; GENERATED — this scene's map

; BG3 2bpp tile attr for the caption (palette 7, priority)
ROOM_TXT_ATTR = (7 << 10) | (1 << 13)

; room-only engine feature code — INSIDE the scope: its claims are scene-scoped
.include "room_bg.asm"
.include "room_hero.asm"
.include "room_logic.asm"
.include "window_iris.asm"

; The walk's base rate, in the 8.8 unit TS_STEP takes. room_logic's RM_SPEED
; is still the one number to reach for when tuning how the lit room feels.
TS_WALK_BASE = RM_SPEED * TS_ONE

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- this visit, for the title to render on the way back --------------
    lda f:US_VISITS_LONG
    inc a
    sta f:US_VISITS_LONG
    ; ---- and persist it: slot 0 through the save feature.
    ; Enter runs under forced blank + NMI masked (scene_mgr contract), so
    ; the slot write cannot race anything; ~70 always-slow SRAM accesses
    ; (8 mc each) are enter-phase noise. Save-on-enter, not on a timer: the
    ; moment the number changes is the natural moment to write it.
    lda #0
    sta z:SV_SLOT               ; slot 0
    lda #2
    sta z:SV_LEN                ; the payload: visits u16
    lda #SV_FORMAT_VER
    sta z:SV_VER
    lda #US_VISITS
    sta z:SV_PTR
    sep #$20
    .a8
    lda #US_VISITS_BANK
    sta z:SV_PTR+2
    rep #$20
    .a16
    jsr sv_save
    ; ---- the room's own state ---------------------------------------------
    stz z:US_TS_ACC             ; the timebase's carried fraction, and this
    stz z:US_TS_STEP            ;   frame's step: written before either is read
    jsr rm_spawn
    ; ---- this room's acoustics: queue the ambience SFX. Tad_Process picks
    ; it up on the fade-in frames, so the echo re-shape happens under the
    ; transition, never on a settled visible frame.
    sep #$20
    .a8
    lda #SFX::room_a_ambience
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
    lda #$09                    ; BGMODE 1, BG3 priority high (the caption
                                ; sits above the room and is never dimmed)
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
    ; frame, so frame 0 shows the lantern rather than power-on garbage
    ; (rule 5: the HDMA channel reads this table before any tick runs)
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
; In/out: A16/I16, DB=0. Display is active: no VRAM writes here. The iris
; table is WRAM, and the HDMA channel reads it at the start of the NEXT
; frame, so rebuilding it mid-frame is safe by construction.
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
    ; ---- the east door: standing against the right wall and pressing into
    ; it crosses to the cavern (room_b). PRESS edge, not hold — the clamp
    ; keeps px parked at RM_HI_X while walking into the wall, and a held
    ; trigger would re-fire through the whole transition.
    lda z:US_PX
    cmp #RM_HI_X
    bcc @no_door
    lda z:ES_INP_PRESS
    and #JOY_RIGHT
    beq @no_door
    sep #$20
    .a8
    lda #2                      ; scene id: room_b
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
s_caption: .byte "A LANTERN IN A DARK ROOM", 0
.segment "CODE"
.endscope
