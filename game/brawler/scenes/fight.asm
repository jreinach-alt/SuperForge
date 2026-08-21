; =============================================================================
; fight scene — the whole game: lane movement, chase AI, and the timed hitbox
; =============================================================================
; The whole game loop, one frame per tick, in a fixed order: the player's
; attack-or-move block -> the enemy's respawn/stun/chase block + his anim clock
; -> the swing hitbox -> contact -> the player's anim clock -> the HUD -> the
; draw. The animation, facing and box-overlap helpers are game-side, below.
.scope fight
.include "engine_state_fight.inc"   ; GENERATED — this scene's map

; --- the scene's own feature code, inside the scope -------------------------
; (their claims are scene-scoped, so their asm has to see this scene's emitted
; symbols — hud_obj's placement note)
.include "brawler_bg.asm"
.include "brawler_obj.asm"

; BG3 2bpp tile attr: palette 7 (the text_pal claim pins CGRAM words 28..31),
; priority set so the HUD draws over anything it overlaps (hud_game's value).
TXT_ATTR = (7 << 10) | (1 << 13)

; Cell addresses, derived once from the geometry in brawler.inc.
BR_CELL_HP    = ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_HP_VAL_C
BR_CELL_FOE   = ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_FOE_VAL_C
BR_CELL_WINS  = ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_WINS_VAL_C
BR_CELL_OVER  = ES_V_TEXT_MAP + BR_OVER_ROW * BR_MAP_W + BR_OVER_C

; =============================================================================
; THE THREE BASE RATES tick_scale SCALES (docs/96 §4)
; =============================================================================
; Each is a per-frame delta in the 8.8 unit TS_STEP takes, built from the
; rail's own tuning constants so brawler.inc stays the one place a designer
; edits. What changed is that BR_WALK_SPEED and BR_ENEMY_SPEED are now RATES
; rather than per-frame immediates: on NTSC the published step is the constant
; to the pixel, on PAL it is the constant times 1.2018 with the fraction
; carried.
TS_WALK_BASE  = BR_WALK_SPEED * TS_ONE
TS_ENEMY_BASE = BR_ENEMY_SPEED * TS_ONE
; One animation unit. The DIVIDER in br_anim_meta is untouched — scaling a
; small integer divider is docs/95 §5.2's class C and has no correct answer —
; so what is scaled is the amount the clock advances by.
TS_ANIM_BASE  = TS_ONE

; =============================================================================
; BR_ANIM_STEP — one actor's animation clock, one frame
; =============================================================================
; The RATE and LENGTH are read from br_anim_meta rather than pasted in as macro
; operands, so the numbers that bound the wrap live beside the frames they
; bound. Advance when tick >= rate; wrap the step index at len.
;
; THE RESET DISCIPLINE IS THE CALLER'S, and it is the rail's stated lesson:
; every anim-state change zeroes BOTH the tick and the frame, or a 4-step
; table gets indexed at step 7 by a stale 8-step counter and reads past its
; end. Every `sta z:US_ASTATE` in this file is followed by that pair.
;
; WIDTH-RISK: A16/I16 in AND out — this macro contains no sep/rep at all, so
; it cannot leak a width to its caller. Clobbers A, X, US_TILE, US_ATTR (draw
; scratch, dead until the draw runs later in the same tick).
.macro BR_ANIM_STEP brs_state, brs_tick, brs_frame
    .local brs_wrap, brs_done
    .assert BR_META_STRIDE = 2, error, "BR_ANIM_STEP's single 16-bit meta read assumes a 2-byte stride"
    lda brs_state
    asl a                           ; state * BR_META_STRIDE
    tax
    lda f:br_anim_meta_bin, x       ; one 16-bit read: len in low, rate in high
    and #$00FF
    sta z:US_TILE                   ; the table's length
    lda f:br_anim_meta_bin, x
    xba
    and #$00FF
    sta z:US_ATTR                   ; ...and its frame-rate divider
    ; THE CLOCK ADVANCES BY US_TSA, NOT BY ONE. That is the whole of this
    ; rail's answer to docs/95 §5.2's class C: a frame-rate divider is a small
    ; integer with no correct x5/6, so the divider is left alone and what the
    ; clock ADVANCES BY is scaled instead — 1 unit per NTSC frame, 1.2018 per
    ; PAL frame, the fraction carried by tick_scale. On NTSC US_TSA is exactly
    ; 1 every frame, so this is `inc a` to the cycle in behaviour.
    lda brs_tick
    clc
    adc z:US_TSA
    sta brs_tick
    cmp z:US_ATTR
    bcc brs_done                    ; not time for the next step yet
    ; CARRY THE OVERSHOOT rather than zeroing. On NTSC the clock arrives at
    ; the divider EXACTLY (it steps by 1 from 0 and the caller resets it on
    ; every state change), so tick - rate = 0 and this is `stz` in behaviour;
    ; on PAL a 2-unit frame can cross the divider by one, and dropping that
    ; one is a bias the accumulator upstream cannot see.
    sec
    sbc z:US_ATTR
    sta brs_tick
    lda brs_frame
    inc a
    cmp z:US_TILE
    bcc brs_wrap
    lda #0                          ; past the end: back to step 0
brs_wrap:
    .a16
    .i16
    sta brs_frame
brs_done:
    .a16
    .i16
.endmacro

; =============================================================================
; br_box — the AABB overlap test
; =============================================================================
; SuperForge has col_map (tile probes) and nothing box-vs-box, so the routine
; lives here, with eight DP argument SLOTS every caller writes before the jsr
; (stomper's st_solid_box shape, one level up).
;
; Boxes span the half-open range [x, x+w). Overlap is STRICT: boxes that merely
; touch edge to edge share 0 px and do not overlap. The separation tests are
; done as SIGN-OF-DIFFERENCE, which is what makes the test correct when a
; coordinate is negative — the swing's hitbox reaches x = px - 12, and px can
; be as low as BR_ARENA_L.
;
; In/out: A16/I16, DB=0. Out: A = 1 and Z clear on overlap; A = 0 and Z set
; otherwise. Clobbers A.
br_box:
    .a16
    .i16
    lda z:US_BBX
    clc
    adc z:US_BBW
    sec
    sbc z:US_BAX                    ; (bx + bw) - ax
    beq @miss                       ; equal = touching = no overlap
    bmi @miss                       ; negative = ax is past b's right edge
    lda z:US_BAX
    clc
    adc z:US_BAW
    sec
    sbc z:US_BBX                    ; (ax + aw) - bx
    beq @miss
    bmi @miss
    lda z:US_BBY
    clc
    adc z:US_BBH
    sec
    sbc z:US_BAY                    ; (by + bh) - ay
    beq @miss
    bmi @miss
    lda z:US_BAY
    clc
    adc z:US_BAH
    sec
    sbc z:US_BBY                    ; (ay + ah) - by
    beq @miss
    bmi @miss
    lda #1
    rts
@miss:
    .a16
    .i16
    lda #0
    rts

; =============================================================================
; ENTER — forced blank + NMI masked (scene_mgr contract)
; =============================================================================
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- CGRAM: the 4-colour text sub-palette (words 28..31) --------------
    ; ALL FOUR words are written. The font's glyph strokes author colour index
    ; 3, and a scene that wrote only the two it "obviously" needs would leave
    ; word 31 holding power-on RNG — green under one seed, something else under
    ; another (the scroll_run catch). Word 0 of the BG group is
    ; br_bg_pal's, uploaded by br_arm below.
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    stz a:$2122                 ; colour 0 (transparent slot): black
    stz a:$2122
    lda #$52                    ; colour 1: dim slate $2952
    sta a:$2122
    lda #$29
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: WHITE $7FFF — the HUD colour
    sta a:$2122
    lda #$7F
    sta a:$2122
    ; ---- BG3 regs (bg_text's scene_writes): map base, chr base, scroll ----
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    ; ---- the scene's base display (brawler_bg's scene_writes) ------------
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #ES_V_BR_MAP_SC_BASE
    sta a:$2107                 ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_BR_CHR_NBA
    sta a:$210B                 ; BG12NBA: BG1 chr page in the low nibble
    lda #$15                    ; TM: OBJ + BG3 + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    ; ---- font + text map --------------------------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the floor (CHR, palette, tilemap from the patch, scroll pin) ----
    jsr br_arm
    ; ---- both knights' CHR, both palettes, OBSEL -------------------------
    jsr br_obj_arm
    ; ---- game state. Power-on DP is RANDOM (rule 5): these stores ARE the
    ; write-before-read contract for every word state.toml declares — except
    ; the br_box argument slots and the floor-build scratch, which are
    ; write-before-read PER CALL and deliberately NOT zeroed here (zeroing
    ; would disarm the uninit-read detector on them — cm_hot's argument).
    lda #BR_SPAWN_PX
    sta z:US_PX
    lda #BR_SPAWN_PY
    sta z:US_PY
    stz z:US_FACING             ; Arthur spawns facing right
    stz z:US_ASTATE             ; ...idle...
    stz z:US_ATICK
    stz z:US_AFRAME
    stz z:US_ATTACKT            ; ...and not swinging
    lda #BR_SPAWN_EX
    sta z:US_EX
    lda #BR_SPAWN_EY
    sta z:US_EY
    lda #1
    sta z:US_EFACE              ; Mordred spawns to Arthur's right, facing him
    stz z:US_ETICK
    stz z:US_EFRAME
    stz z:US_EMOV
    lda #BR_ST_E_IDLE           ; his anim state, before the first draw reads
    sta z:US_ESTATE             ;   it — the enter draw runs BEFORE any tick
                                ;   has chosen a table (the uninit detector
                                ;   named this one; rule 5)
    lda #BR_PLAYER_HP
    sta z:US_HP
    lda #BR_FOE_HP
    sta z:US_FOE
    stz z:US_WINS
    stz z:US_PINV
    stz z:US_ESTUN
    stz z:US_ERESP
    stz z:US_AHIT
    stz z:US_GAMEOVER
    ; The timebase's six words. The accumulators start empty and the three
    ; published steps are written before anything reads them — the tick
    ; republishes all three at its top, but the enter draw runs first.
    stz z:US_TSP_ACC
    stz z:US_TSP
    stz z:US_TSE_ACC
    stz z:US_TSE
    stz z:US_TSA_ACC
    stz z:US_TSA
    stz z:US_HUDP
    stz z:US_OVERP
    stz z:US_BLINK
    ; ---- the HUD, printed under the blank where whole strings are legal ---
    lda #TXT_ATTR
    sta z:ES_TXT_TMP            ; every later text call reads this; nothing
                                ;   else writes it, so it is set once
    lda #.loword(s_hp)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_hp
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_HP_LABEL_C)
    jsr text_puts
    lda #.loword(s_foe)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_FOE_LABEL_C)
    jsr text_puts
    lda #.loword(s_wins)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + BR_HUD_ROW * BR_MAP_W + BR_WINS_LABEL_C)
    jsr text_puts
    ; ---- the three counters at their boot values (forced-blank twin) -----
    lda z:US_HP
    ldx #BR_CELL_HP
    jsr text_put_hex4
    lda z:US_FOE
    ldx #BR_CELL_FOE
    jsr text_put_hex4
    lda z:US_WINS
    ldx #BR_CELL_WINS
    jsr text_put_hex4
    ; ---- stage frame 0's OAM so the first commit carries real knights -----
    jsr br_obj_draw
    rts

; =============================================================================
; EXIT — never called: one scene, no edges
; =============================================================================
exit:
    .a16
    .i16
    rts

; =============================================================================
; TICK — one frame
; =============================================================================
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    ; The free-running heartbeat: nothing reads it in the ROM, and a test does
    ; — it separates "the tick is running" from "the tick is stuck".
    lda z:US_BLINK
    inc a
    sta z:US_BLINK

    ; ---- this frame's three region-correct steps, published once ----------
    ; BEFORE the gameover test, deliberately: the freeze still draws and a
    ; later state may still clock, and a step word that stops being republished
    ; is a stale word waiting to be read. Three macro expansions, no branches
    ; taken on NTSC beyond the flag test — each publishes today's constant to
    ; the unit when ES_RGN_PAL is clear.
    TS_STEP z:US_TSP_ACC, TS_WALK_BASE
    sta z:US_TSP
    TS_STEP z:US_TSE_ACC, TS_ENEMY_BASE
    sta z:US_TSE
    TS_STEP z:US_TSA_ACC, TS_ANIM_BASE
    sta z:US_TSA

    lda z:US_GAMEOVER
    beq @alive
    jmp tick_text               ; frozen: input is skipped, the text pump and
                                ;   the draw still run every frame
@alive:
    .a16
    .i16
    jsr player_step
    jsr enemy_step
    jsr swing_check
    jsr contact_check
    ; ---- the player's anim clock, in whatever state he ended the frame ----
    BR_ANIM_STEP z:US_ASTATE, z:US_ATICK, z:US_AFRAME
; A scope-level label, not a cheap `@one`: BR_ANIM_STEP's `.local` labels sit
; between the jmp and here, and a non-cheap label ends the cheap-label scope.
tick_text:
    .a16
    .i16
    jsr hud_pump
    jsr br_obj_draw
    rts

; =============================================================================
; player_step — the attack-or-move block
; =============================================================================
; A swing runs to completion and locks out movement; otherwise A starts one and
; the D-pad moves. In/out: A16/I16, DB=0. Clobbers A, X.
player_step:
    .a16
    .i16
    lda z:US_ATTACKT
    beq @not_attacking
    dec a
    sta z:US_ATTACKT
    bne @done                   ; still swinging: no movement this frame
    lda #BR_ST_IDLE             ; swing over -> idle, clocks reset (the state-
    sta z:US_ASTATE             ;   change discipline BR_ANIM_STEP relies on)
    stz z:US_ATICK
    stz z:US_AFRAME
@done:
    .a16
    .i16
    rts
@not_attacking:
    .a16
    .i16
    lda z:ES_INP_PRESS          ; btnp: the RISING edge only
    and #JOY_A
    beq @move
    lda #BR_ATTACK_LEN
    sta z:US_ATTACKT
    lda #BR_ST_ATTACK
    sta z:US_ASTATE
    stz z:US_ATICK
    stz z:US_AFRAME
    stz z:US_AHIT               ; a new swing re-arms the one-hit latch
    rts
@move:
    .a16
    .i16
    ; EMOV does double duty: "the player moved" here, "the enemy moved" in
    ; enemy_step. The two uses never overlap in a frame.
    stz z:US_EMOV
    ; ---- right ----
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX
    clc
    adc z:US_TSP
    cmp #BR_ARENA_R
    bcc :+
    lda #BR_ARENA_R
:   .a16
    .i16
    sta z:US_PX
    stz z:US_FACING             ; travel right -> face right
    lda #1
    sta z:US_EMOV
@no_right:
    .a16
    .i16
    ; ---- left ----
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX
    sec
    sbc z:US_TSP                ; safe: px >= ARENA_L and the published
                                ;   step is <= BR_WALK_SPEED + 1 <= 8
    cmp #BR_ARENA_L
    bcs :+
    lda #BR_ARENA_L
:   .a16
    .i16
    sta z:US_PX
    lda #1
    sta z:US_FACING             ; travel left -> face left (the H-flip)
    sta z:US_EMOV
@no_left:
    .a16
    .i16
    ; ---- down ----
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_PY
    clc
    adc z:US_TSP
    cmp #BR_LANE_BOT
    bcc :+
    lda #BR_LANE_BOT
:   .a16
    .i16
    sta z:US_PY
    lda #1
    sta z:US_EMOV
@no_down:
    .a16
    .i16
    ; ---- up ----
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_PY
    sec
    sbc z:US_TSP
    cmp #BR_LANE_TOP
    bcs :+
    lda #BR_LANE_TOP
:   .a16
    .i16
    sta z:US_PY
    lda #1
    sta z:US_EMOV
@no_up:
    .a16
    .i16
    ; ---- anim state from movement; clocks reset only on a CHANGE ---------
    lda z:US_EMOV
    beq @want_idle
    lda z:US_ASTATE
    cmp #BR_ST_RUN
    beq @done2
    lda #BR_ST_RUN
    bra @set_state
@want_idle:
    .a16
    .i16
    lda z:US_ASTATE
    cmp #BR_ST_IDLE
    beq @done2
    lda #BR_ST_IDLE
@set_state:
    .a16
    .i16
    sta z:US_ASTATE
    stz z:US_ATICK
    stz z:US_AFRAME
@done2:
    .a16
    .i16
    rts

; =============================================================================
; enemy_step — respawn clock / stun / chase, then Mordred's anim clock
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X.
enemy_step:
    .a16
    .i16
    lda z:US_ERESP
    beq @active
    dec a
    sta z:US_ERESP
    bne @gone                   ; still gone this frame
    ; ---- the countdown just expired: respawn at the right edge, full hp --
    lda #BR_ARENA_R
    sta z:US_EX
    lda #BR_SPAWN_EY
    sta z:US_EY
    lda #BR_FOE_HP
    sta z:US_FOE
    lda #BR_HUD_PUMP
    sta z:US_HUDP               ; FOE went back up: the HUD has to say so
@gone:
    .a16
    .i16
    rts                         ; BOTH respawn arms return WITHOUT running the
                                ;   clock, deliberately: he is parked
                                ;   off-screen, so the clock would only advance
                                ;   him to a different step for his return, off
                                ;   a STALE emov nothing wrote while he was gone
@active:
    .a16
    .i16
    lda z:US_ESTUN
    beq @chase
    dec a
    sta z:US_ESTUN
    stz z:US_EMOV               ; stunned: he stands (the idle table)
    bra @anim
@chase:
    .a16
    .i16
    stz z:US_EMOV
    ; ---- face + walk toward the player, axis by axis ---------------------
    lda z:US_EX
    cmp z:US_PX
    beq @no_x
    bcc @go_right
    lda #1
    sta z:US_EFACE              ; the player is to his left
    lda z:US_EX
    sec
    sbc z:US_TSE
    sta z:US_EX
    lda #1
    sta z:US_EMOV
    bra @no_x
@go_right:
    .a16
    .i16
    stz z:US_EFACE
    lda z:US_EX
    clc
    adc z:US_TSE
    sta z:US_EX
    lda #1
    sta z:US_EMOV
@no_x:
    .a16
    .i16
    lda z:US_EY
    cmp z:US_PY
    beq @no_y
    bcc @go_down
    lda z:US_EY
    sec
    sbc z:US_TSE
    sta z:US_EY
    lda #1
    sta z:US_EMOV
    bra @no_y
@go_down:
    .a16
    .i16
    lda z:US_EY
    clc
    adc z:US_TSE
    sta z:US_EY
    lda #1
    sta z:US_EMOV
@no_y:
    .a16
    .i16
@anim:
    .a16
    .i16
    ; ONE CLOCK for both of Mordred's tables. His run table is 8 steps but is
    ; stepped at length 4 — run uses steps 0-3 of 8, and keeping one clock
    ; length avoids a reset on every stun flicker. br_anim_meta carries that
    ; forced length, so the state index can flip between idle and run mid-cycle
    ; without the clock ever being reset.
    lda z:US_EMOV
    beq @idle_clock
    lda #BR_ST_E_RUN
    bra @clock
@idle_clock:
    .a16
    .i16
    lda #BR_ST_E_IDLE
@clock:
    .a16
    .i16
    sta z:US_ESTATE             ; his anim state, read by the clock AND by the
                                ;   draw — one word, so the two cannot disagree
    BR_ANIM_STEP z:US_ESTATE, z:US_ETICK, z:US_EFRAME
    rts

; =============================================================================
; swing_check — the timed attack hitbox
; =============================================================================
; The hitbox is a 16x16 box in FRONT of Arthur, live only on swing frames
; 4..12, and it lands ONE hit per swing (latched). That triple — a window, a
; placement that follows facing, and a latch — is the whole "active frames"
; combat pattern this rail exists to teach.
; In/out: A16/I16, DB=0. Clobbers A, X.
; The five gates exit through a bail RIGHT HERE rather than branching to the
; routine's tail: the eight argument stores plus the box test put the tail well
; past a relative branch's 128-byte reach. A jmp trampoline would clear the
; same wall; a near bail is the same fix without the indirection.
swing_check:
    .a16
    .i16
    lda z:US_ATTACKT
    beq @bail                   ; not swinging
    cmp #BR_HIT_FIRST
    bcc @bail                   ; the window has closed
    cmp #(BR_HIT_LAST + 1)
    bcs @bail                   ; ...or has not opened yet
    lda z:US_AHIT
    bne @bail                   ; this swing already landed
    lda z:US_ERESP
    beq @live                   ; nobody to hit
@bail:
    .a16
    .i16
    rts
@live:
    .a16
    .i16
    ; ---- place the hitbox in front of Arthur -----------------------------
    lda z:US_FACING
    bne @left
    lda z:US_PX
    clc
    adc #BR_HIT_AHEAD
    bra @store
@left:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc #BR_HIT_BEHIND          ; CAN GO NEGATIVE at the left clamp — which is
                                ;   why br_box compares by sign of difference
@store:
    .a16
    .i16
    sta z:US_HX
    lda z:US_PY
    clc
    adc #BR_HIT_DY
    sta z:US_HY
    ; ---- hitbox vs Mordred's body ----------------------------------------
    lda z:US_HX
    sta z:US_BAX
    lda z:US_HY
    sta z:US_BAY
    lda #BR_HIT_W
    sta z:US_BAW
    lda #BR_HIT_H
    sta z:US_BAH
    lda z:US_EX
    sta z:US_BBX
    lda z:US_EY
    sta z:US_BBY
    lda #BR_BODY_W
    sta z:US_BBW
    lda #BR_BODY_H
    sta z:US_BBH
    jsr br_box
    beq @none
    ; ---- landed: latch, stagger him, take a point off ---------------------
    lda #1
    sta z:US_AHIT
    lda #BR_STUN_T
    sta z:US_ESTUN
    lda #BR_HUD_PUMP
    sta z:US_HUDP
    lda z:US_FOE
    dec a
    sta z:US_FOE
    bne @none
    ; ---- KO: bank the win, schedule the respawn --------------------------
    lda z:US_WINS
    inc a
    sta z:US_WINS
    lda #BR_RESPAWN_T
    sta z:US_ERESP
@none:
    .a16
    .i16
    rts

; =============================================================================
; contact_check — walking into Mordred hurts
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X.
contact_check:
    .a16
    .i16
    lda z:US_PINV
    beq @check
    dec a
    sta z:US_PINV               ; i-frames: immune, and they tick down
    rts
@check:
    .a16
    .i16
    lda z:US_ERESP
    beq @live                   ; nobody to walk into
    rts                         ; a near bail: the tail is past branch reach
@live:
    .a16
    .i16
    lda z:US_PX
    sta z:US_BAX
    lda z:US_PY
    sta z:US_BAY
    lda #BR_TOUCH_W             ; tighter than the 32x32 sprite, both sides, so
    sta z:US_BAW                ;   the bodies must really meet
    lda #BR_TOUCH_H
    sta z:US_BAH
    lda z:US_EX
    sta z:US_BBX
    lda z:US_EY
    sta z:US_BBY
    lda #BR_TOUCH_W
    sta z:US_BBW
    lda #BR_TOUCH_H
    sta z:US_BBH
    jsr br_box
    beq @done
    ; ---- hit: a point of HP, i-frames, and a shove away from him ---------
    lda z:US_HP
    dec a
    sta z:US_HP
    lda #BR_HUD_PUMP
    sta z:US_HUDP
    lda #BR_INV_T
    sta z:US_PINV
    lda z:US_PX
    cmp z:US_EX
    bcc @knock_left
    lda z:US_PX
    clc
    adc #BR_KNOCKBACK
    cmp #BR_ARENA_R
    bcc @knock_store
    lda #BR_ARENA_R
    bra @knock_store
@knock_left:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc #BR_KNOCKBACK
    cmp #BR_ARENA_L
    bcs @knock_store
    lda #BR_ARENA_L
@knock_store:
    .a16
    .i16
    sta z:US_PX
    lda z:US_HP
    bne @done
    ; ---- KO'd: the lockout, and the GAME OVER print starts pumping -------
    lda #1
    sta z:US_GAMEOVER
    lda #BR_OVER_LEN
    sta z:US_OVERP
@done:
    .a16
    .i16
    rts

; =============================================================================
; hud_pump — one text-queue run per frame
; =============================================================================
; bg_text's VBlank queue holds ONE run of up to TXT_Q_MAX = 4 consecutive
; cells per frame, and this rail has three counters at three columns plus a
; nine-letter banner. So the writes take turns:
;
;   * ANY counter change sets hudp = 3, and the next three frames reprint HP,
;     FOE and WINS in that order (one 4-cell hex run each). A single dirty FLAG
;     would not do: a KO changes FOE and WINS in the SAME frame, so the pump
;     has to be a countdown over all three rather than a "which one" bit.
;   * "GAME OVER" pumps one cell per frame for nine frames, and only once the
;     counter pump has drained — the KO frame's HP change owns the queue first.
;     Invisible at 60 fps, exact under the Machine.
;
; In/out: A16/I16, DB=0. Clobbers A, X.
hud_pump:
    .a16
    .i16
    lda z:US_HUDP
    bne @counters
    jmp over_pump
@counters:
    .a16
    .i16
    dec a
    sta z:US_HUDP               ; 3 -> 2 (HP), 2 -> 1 (FOE), 1 -> 0 (WINS)
    bne @not_wins
    lda z:US_WINS
    ldx #BR_CELL_WINS
    bra @put
@not_wins:
    .a16
    .i16
    cmp #1
    bne @hp
    lda z:US_FOE
    ldx #BR_CELL_FOE
    bra @put
@hp:
    .a16
    .i16
    lda z:US_HP
    ldx #BR_CELL_HP
@put:
    .a16
    .i16
    jsr text_queue_hex4         ; 4 cells = exactly one full queue run
    rts

; --- over_pump: one letter of "GAME OVER" per frame -------------------------
over_pump:
    .a16
    .i16
    lda z:US_OVERP
    bne @pump
    rts
@pump:
    .a16
    .i16
    lda #BR_OVER_LEN
    sec
    sbc z:US_OVERP              ; letter index 0..8, left to right
    tax
    sep #$20
    .a8
    lda f:s_over, x             ; the ascii letter
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #' '                    ; glyph index (space is tile 0)
    ora #TXT_ATTR
    pha                         ; the tile word (A16 push, single pull below)
    txa
    clc
    adc #BR_CELL_OVER
    tax                         ; X = this letter's VRAM cell
    pla
    jsr text_queue_cell
    lda z:US_OVERP
    dec a
    sta z:US_OVERP
    rts

; =============================================================================
; strings
; =============================================================================
s_hp:   .byte "HP", 0
s_foe:  .byte "FOE", 0
s_wins: .byte "WINS", 0
s_over: .byte "GAME OVER"
s_over_end:
        .byte 0
.assert (s_over_end - s_over) = BR_OVER_LEN, error, "the GAME OVER pump length disagrees with the string it pumps"

.endscope
