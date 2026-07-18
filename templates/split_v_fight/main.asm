; =============================================================================
; split_v_fight — SEAMLESS distance-driven fighting-game split (sf_split_v rail)
; =============================================================================
; A ground-level two-fighter arena whose camera separates SEAMLESSLY as the
; fighters part and re-merges just as seamlessly as they close — no pop, no
; shift. Rebuilt (from PR #221's trial) on the seamless core proven by
; templates/split_v_seamtrial:
;
;   * The centre window is ALWAYS on (never toggled, never forced-blanked).
;   * Separation is a CONTINUOUS camera divergence: cam_a = mid - spread,
;     cam_b = mid + spread, where `spread` is EASED from the fighter distance
;     (replacing the old binary MERGED/SPLIT state machine + sf_window_off
;     toggle + NEAR/FAR hysteresis). At spread=0 the two halves are pixel-
;     identical, so the ever-present seam is INVISIBLE.
;   * The divider is a VERTICAL BEVELED bar on BG3 whose band half-width
;     hw = spread>>4 is ZERO at merge (no stolen width) and ramps 0->3->7 px as
;     the fighters part. Vertical, not diagonal: a diagonal divider encodes the
;     verticality (airborne vs grounded) this ground-only game lacks.
;
; `spread` tracks the "ideal" divergence that keeps each fighter centred in its
; half: spread = clamp((dx - MERGE_DX)/2, 0, SPREAD_MAX), eased at SPR_STEP/frame
; toward that target, where dx = |fighter2 - fighter1|. Below MERGE_DX the target
; is 0 (fully merged, seamless single view). The fighters are OBJ (red left, blue
; right), each tracking its own half's camera.
;
; This is the camera director, not a combat engine: fighters just walk (P1/P2),
; clamped to the arena and kept from crossing.
;
; COMPOSITION (folded into lib/macros/sf_split_v.inc):
;   sf_split_v_bevel                          — one-time: BG3 beveled bar + palette
;                                               + tilemap + always-on window recipe.
;   sf_split_v_spread mid, spread, camA, camB — per-frame: diverge cameras + ramp
;                                               the band + scroll BG1/BG2.
;
; CONTROLS (default build):
;   P1 (port 0) D-pad Left/Right  -> walk fighter 1 (red, left)
;   P2 (port 1) D-pad Left/Right  -> walk fighter 2 (blue, right)
;   -DAUTODEMO : ignore input; the fighters march wall-to-wall THROUGH each other,
;                swapping sides and back, on their own (a self-running cross-over).
;   -DHOLD=n   : STATIC race-free build — fighters frozen symmetric at +-n px about
;                centre, `spread` eases to its fixed point (settles in ~SPREAD_MAX
;                frames). HOLD=0..64 -> merged; larger -> split. For framebuffer
;                proofs (freeze the swept variable, no capture-timing race).
;   -DNOWIN    : the no-split REFERENCE — window off + BG3 dropped from the main
;                screen, so a single camera fills the screen with no divider. At
;                HOLD=merge the windowed frame must pixel-match this reference
;                (the ground-truth proof that the split adds nothing at merge).
;
; Build:  make split_v_fight  (default) · build_split_v_fight.sh (-D variants)
; =============================================================================
; LDCFG: lorom_64k.cfg

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"
.include "buttons.inc"
.include "sf_window.inc"
.include "sf_frame.inc"
.include "sf_split_v.inc"
.include "engine_state.inc"

; --- DP scratch (hot-global region $40-$5F; the engine touches it only when
;     game code uses globals — this hand-written ROM does not) ---
FX1     = $40                   ; fighter 1 world X (16-bit)
FX2     = $42                   ; fighter 2 world X (16-bit)
FDIR    = $44                   ; auto-demo phase: 0=opening, 1=closing
CAMA    = $46                   ; camera A scroll (left half)
CAMB    = $48                   ; camera B scroll (right half)
MID     = $4A                   ; shared viewpoint = (FX1+FX2)/2 - 128
DX      = $4C                   ; |FX2 - FX1|
SPREADF = $4E                   ; camera spread, 8.8 fixed (eased)
SPREAD  = $50                   ; integer spread (0 .. SPREAD_MAX)
TARGET  = $52                   ; integer target spread this frame
TGTF    = $54                   ; target spread in 8.8
SX      = $56                   ; screen-X scratch (fighter placement)
T_MX    = $58
T_MY    = $5A
T_TILE  = $5C
FDWELL  = $5E                   ; auto-demo dwell countdown at each extreme

ARENA_MID = 128
ARENA_LO  = 24                  ; fighter clamp (left wall)
ARENA_HI  = 232                 ; fighter clamp (right wall)
WALK_SPD  = 2

SPREAD_MAX = 48                 ; full divergence (matches the seamtrial)
MERGE_DX   = 128                ; dx below which spread targets 0 (fully merged)
SPR_STEP   = $00C0              ; 0.75 px/frame ease (8.8) -> smooth divergence
DWELL      = 72                 ; auto-demo hold (~1.2 s) at each wall so the fully split
                                ; (swapped / unswapped) state settles + is visible in real time

GND_DIRT  = 24
FGT_Y     = 168                 ; fighter feet row (two 8x8 stacked = 8x16 tall)

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; --- stage tiles -> BG1 CHR ($2000) ---
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$30
    .a16
    .i16
    lda #$2010
    sta $2116
    ldx #$0000
@chr:
    lda f:solid_tiles, x
    sta $2118
    inx
    inx
    cpx #(4*32)
    bne @chr

    ; --- fighters as OBJ (tile 1 red, tile 2 blue) ---
    sf_load_obj_tile 1, fighter_red
    sf_load_obj_tile 2, fighter_blue
    sf_obj_color 0, 1, $001F    ; fighter 1 = red
    sf_obj_color 0, 2, $7C00    ; fighter 2 = blue

    sf_bg_color 0, 0, $7FFF     ; backdrop (unused — the divider is BG3, not backdrop)
    sf_bg_color 0, 1, $7F54     ; sky
    sf_bg_color 0, 2, $02E0     ; grass
    sf_bg_color 0, 3, $4A52     ; mountain
    sf_bg_color 0, 4, $1194     ; dirt

    jsr init_ppu
    gfxmode #1
    ; shared-CHR override: BG2 reads BG1's tilemap ($5800) + CHR ($2000)
    sep #$20
    .a8
    lda #$58
    sta $2108
    lda #$22
    sta $210B
    rep #$30
    .a16
    .i16

    ; --- fill BG1 tilemap once (shared by both cameras) ---
    stz T_MY
@row:
    .a16
    .i16
    stz T_MX
@col:
    .a16
    .i16
    ldx T_MX
    sep #$20
    .a8
    lda T_MY
    cmp f:hmap, x
    bcc @sky
    cmp #GND_DIRT
    bcs @dirt
    cpx #6
    bcc @grass
    cpx #13
    bcs @grass
    lda #3
    bra @settile
@grass:
    .a8
    lda #2
    bra @settile
@dirt:
    .a8
    lda #4
    bra @settile
@sky:
    .a8
    lda #1
@settile:
    .a8
    rep #$30
    .a16
    .i16
    and #$00FF
    sta T_TILE
    mset #1, T_MX, T_MY, T_TILE
    lda T_MX
    inc a
    sta T_MX
    cmp #32
    bne @col
    lda T_MY
    inc a
    sta T_MY
    cmp #32
    bne @row

    ; --- SEAMLESS divider: always-on centre window + beveled BG3 bar (setup) ---
    sf_split_v_bevel

.ifdef NOWIN
    ; --- no-split REFERENCE: window off + BG3 off the main screen, so one camera
    ;     fills the screen with no divider. The windowed merge frame must match. ---
    sf_window_off
    sep #$20
    .a8
    lda #$13                        ; TM: OBJ + BG1 + BG2 (drop BG3 -> no bar)
    sta SHADOW_TM
    rep #$30
    .a16
    .i16
.endif

    ; --- fighter start positions ---
.ifdef HOLD
    ; static build: freeze fighters symmetric at +-HOLD about centre; `spread`
    ; eases to its fixed point and stays there (race-free after ~SPREAD_MAX frames).
    ; A NEGATIVE HOLD places FX1 to the RIGHT of FX2 (a crossed / swapped state).
    lda #(ARENA_MID - HOLD)
    sta FX1
    lda #(ARENA_MID + HOLD)
    sta FX2
.elseif .defined(AUTODEMO)
    lda #ARENA_LO                   ; start at opposite walls (red left, blue right);
    sta FX1                         ; the demo then walks them THROUGH each other to
    lda #ARENA_HI                   ; show the seamless side-SWAP, and back
    sta FX2
.else
    lda #(ARENA_MID - 20)           ; start close together -> merged
    sta FX1
    lda #(ARENA_MID + 20)
    sta FX2
.endif
    stz FDIR
    stz SPREADF
    stz SPREAD
    lda #ARENA_MID
    sta CAMA
    sta CAMB

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

.ifdef HOLD
    ; static: fighters frozen — skip all movement (positions set once in RESET)
.elseif .defined(AUTODEMO)
    ; --- self-running CROSS-OVER: red (FX1) marches wall to wall while blue (FX2)
    ;     marches the opposite way, so they pass THROUGH each other at centre and
    ;     SWAP sides — demonstrating that the seamless split follows a side-switch
    ;     (split -> seamless merge at the crossing -> split with the halves swapped).
    ;     DWELL at each wall so the fully split state settles + is visible. FDIR:
    ;     0=red->right/blue->left  1=dwell  2=red->left/blue->right  3=dwell. ---
    lda FDIR
    beq @to_right               ; 0
    cmp #1
    beq @dwell_a                ; 1
    cmp #2
    beq @to_left               ; 2
    ; FDIR==3: dwell (blue-left), then march right again
    .a16
    .i16
    lda FDWELL
    beq @dwell_b_done
    dec a
    sta FDWELL
    bra @moved
@dwell_b_done:
    .a16
    .i16
    stz FDIR
    bra @moved
@to_right:
    .a16
    .i16
    lda FX1                     ; red -> right, blue -> left
    inc a
    sta FX1
    lda FX2
    dec a
    sta FX2
    lda FX1
    cmp #ARENA_HI               ; red reached the right wall (blue at the left wall)
    bcc @moved
    lda #1                      ; -> dwell (swapped: red right, blue left)
    sta FDIR
    lda #DWELL
    sta FDWELL
    bra @moved
@dwell_a:
    .a16
    .i16
    lda FDWELL
    beq @dwell_a_done
    dec a
    sta FDWELL
    bra @moved
@dwell_a_done:
    .a16
    .i16
    lda #2
    sta FDIR
    bra @moved
@to_left:
    .a16
    .i16
    lda FX1                     ; red -> left, blue -> right (back to original sides)
    dec a
    sta FX1
    lda FX2
    inc a
    sta FX2
    lda FX1
    cmp #(ARENA_LO+1)           ; red reached the left wall
    bcs @moved
    lda #3                      ; -> dwell (original: red left, blue right)
    sta FDIR
    lda #DWELL
    sta FDWELL
@moved:
    .a16
    .i16
.else
    ; --- interactive: P1 walks fighter 1, P2 walks fighter 2 ---
    btn #BTN_RIGHT, #0
    cmp #1
    bne :+
    lda FX1
    clc
    adc #WALK_SPD
    sta FX1
:   btn #BTN_LEFT, #0
    cmp #1
    bne :+
    lda FX1
    sec
    sbc #WALK_SPD
    sta FX1
:   btn #BTN_RIGHT, #1
    cmp #1
    bne :+
    lda FX2
    clc
    adc #WALK_SPD
    sta FX2
:   btn #BTN_LEFT, #1
    cmp #1
    bne :+
    lda FX2
    sec
    sbc #WALK_SPD
    sta FX2
:   ; --- INDEPENDENT arena clamp: each fighter is bounded to [ARENA_LO, ARENA_HI]
    ; with NO reference to the other, so crossing is ALLOWED (a fighter may walk past
    ; the other and switch sides — the split follows, see the OBJ placement below).
    ; Independent bounds also make the F-1 escape impossible by construction: neither
    ; FX can chase the other off the floor because neither is clamped relative to it. ---
    lda FX1                     ; clamp FX1 to [ARENA_LO, ARENA_HI]
    cmp #ARENA_LO
    bcs @f1_hi
    lda #ARENA_LO
@f1_hi:
    .a16
    cmp #(ARENA_HI+1)
    bcc @f1_store
    lda #ARENA_HI
@f1_store:
    .a16
    sta FX1
    lda FX2                     ; clamp FX2 to [ARENA_LO, ARENA_HI]
    cmp #ARENA_LO
    bcs @f2_hi
    lda #ARENA_LO
@f2_hi:
    .a16
    cmp #(ARENA_HI+1)
    bcc @f2_store
    lda #ARENA_HI
@f2_store:
    .a16
    sta FX2
.endif

    ; --- dx = |FX2 - FX1| ---
    lda FX2
    sec
    sbc FX1
    bpl @pos
    eor #$FFFF
    inc a
@pos:
    .a16
    sta DX

    ; --- mid = (FX1 + FX2)/2 - 128  (shared viewpoint: midpoint at screen centre) ---
    lda FX1
    clc
    adc FX2
    lsr a
    sec
    sbc #128
    sta MID

    ; --- target spread = clamp( (dx - MERGE_DX)/2 , 0, SPREAD_MAX ) ---
    ; below MERGE_DX -> 0 (fully merged); above -> the divergence that keeps each
    ; fighter centred in its half (derived: spread = dx/2 - 64 when MERGE_DX=128).
    lda DX
    sec
    sbc #MERGE_DX
    bpl @tgt_pos                ; dx >= MERGE_DX ?
    lda #0                      ; dx < MERGE_DX -> merged
    bra @have_target
@tgt_pos:
    .a16
    lsr a                       ; (dx - MERGE_DX)/2
    cmp #(SPREAD_MAX+1)
    bcc @have_target
    lda #SPREAD_MAX
@have_target:
    .a16
    .i16
    sta TARGET

    ; --- ease SPREADF (8.8) toward TARGET<<8 by SPR_STEP (rate-limited, smooth).
    ;     Runs every frame, incl. HOLD builds: with frozen fighters the target is
    ;     fixed, so SPREADF converges to it and stays (static, race-free frame). ---
    lda TARGET
    xba                         ; TARGET << 8 (into the high byte)
    and #$FF00
    sta TGTF
    lda SPREADF
    cmp TGTF
    beq @eased
    bcs @ease_down
    ; ease up: SPREADF += min(SPR_STEP, TGTF-SPREADF)
    clc
    adc #SPR_STEP
    cmp TGTF
    bcc @ease_store             ; still below target
    lda TGTF                    ; clamp up to target
    bra @ease_store
@ease_down:
    .a16
    lda SPREADF                 ; ease down: SPREADF -= min(SPR_STEP, SPREADF-TGTF)
    sec
    sbc #SPR_STEP
    bcc @clamp_down             ; SPREADF < SPR_STEP -> the subtract UNDERFLOWED (wrapped
                                ; past 0); clamp, else the wrapped huge value stores as spread
    cmp TGTF
    bcs @ease_store             ; still above target -> store the decremented value
@clamp_down:
    .a16
    lda TGTF                    ; clamp down to target (reached or overshot it)
@ease_store:
    .a16
    sta SPREADF
@eased:
    .a16
    .i16

    ; --- integer spread = SPREADF >> 8 ---
    lda SPREADF
    xba
    and #$00FF
    sta SPREAD

    ; --- seamless divergence: cameras + ramped band + scroll BG1/BG2 ---
    sf_split_v_spread MID, SPREAD, CAMA, CAMB

    ; --- draw the two fighters (8x16: two stacked 8x8), assigning each to the half
    ;     it is CURRENTLY on so a SIDE-SWAP is handled: cam_a frames the left half,
    ;     cam_b the right, so the LEFTMOST fighter (by world X) is drawn against CAMA
    ;     and the rightmost against CAMB — each keeping its own colour. When the two
    ;     cross, red simply moves into the right half and blue into the left, and
    ;     because dx->0 at the crossing (spread=0, merged) the swap is seamless. Each
    ;     fighter's screen X stays in [0,255] by construction (spread tracks dx/2-64),
    ;     so no OAM X9 handling is needed. ---
    spr_clear
    lda FX1
    cmp FX2
    bcc @red_left               ; FX1 < FX2 -> red is the LEFT fighter (block just below)
    beq @red_left               ; equal -> red on the left (arbitrary, they coincide)
    jmp @blue_left              ; FX1 > FX2 -> CROSSED: blue left, red right (jmp: too far to branch)
@red_left:
    .a16
    .i16
    lda FX1                     ; left half: red against CAMA
    sec
    sbc CAMA
    and #$00FF
    sta SX
    spr #1, SX, #(FGT_Y-8), #$00, #2
    spr #1, SX, #FGT_Y,     #$00, #2
    lda FX2                     ; right half: blue against CAMB
    sec
    sbc CAMB
    and #$00FF
    sta SX
    spr #2, SX, #(FGT_Y-8), #$00, #2
    spr #2, SX, #FGT_Y,     #$00, #2
    jmp @fighters_drawn         ; skip the crossed block (jmp: past two spr pairs)
@blue_left:
    .a16
    .i16
    lda FX2                     ; left half: blue against CAMA
    sec
    sbc CAMA
    and #$00FF
    sta SX
    spr #2, SX, #(FGT_Y-8), #$00, #2
    spr #2, SX, #FGT_Y,     #$00, #2
    lda FX1                     ; right half: red against CAMB
    sec
    sbc CAMB
    and #$00FF
    sta SX
    spr #1, SX, #(FGT_Y-8), #$00, #2
    spr #1, SX, #FGT_Y,     #$00, #2
@fighters_drawn:
    .a16
    .i16

    sf_frame_end
    jmp game_loop

; --- 4 solid stage tiles (sky/grass/mountain/dirt via colour index 1..4) ------
solid_tiles:
.repeat 4, I
    .repeat 8
        .byte (((I+1) & 1) <> 0) * $FF, ((((I+1) >> 1) & 1) <> 0) * $FF
    .endrepeat
    .repeat 8
        .byte ((((I+1) >> 2) & 1) <> 0) * $FF, ((((I+1) >> 3) & 1) <> 0) * $FF
    .endrepeat
.endrepeat
hmap:
    .byte 18,18,17,16,15,13,11, 9, 8, 8, 9,11,13,15,16,17
    .byte 17,16,15,14,14,15,16,17,17,16,15,15,16,17,18,18
fighter_red:                    ; solid index 1 (red via OBJ palette slot 1)
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
fighter_blue:                   ; solid index 2 (blue via OBJ palette slot 2)
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
