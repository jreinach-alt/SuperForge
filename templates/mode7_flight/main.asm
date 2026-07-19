; =============================================================================
; mode7_flight — Mode 7 free-flight airship rail (perspective floor + altitude)
; =============================================================================
; The genre rail for FREE-FLIGHT over a Mode 7 perspective floor: pilot an
; airship across a fixed wrapping 128x128 ground plane where INPUT-CONTROLLED
; ALTITUDE drives the perspective scale (climb -> ground recedes; descend ->
; it approaches), with free movement (heading turn + throttle, NOT the racer's
; forward-lock) and an animated airship + altitude-scaled ground shadow OBJ.
;
; It shares the racer's Mode 7 spine (the sf_mode7 macro group + the stock engine
; NMI — NO custom VBlank code) and rebuilds the control layer for flight. The
; distinctive piece: re-deriving the near/far perspective scales from an altitude
; state var EVERY frame via sf_mode7_scale, so the ground recedes / approaches as
; you climb / descend.
;
; Controls:
;   D-pad LEFT / RIGHT  turn heading (rotate the Mode 7 angle)
;   B                   throttle forward along heading (signed 8.8 speed, capped)
;   (release)           coast/decelerate to hover (speed -> 0)
;   Y                   reverse thrust (speed goes negative; same integrator)
;   L shoulder          descend (altitude DOWN -> scale UP -> ground approaches)
;   R shoulder          climb   (altitude UP  -> scale DOWN -> ground recedes)
;
; File layout (major banners, top to bottom):
;   INIT         — upload the ground map / palettes / airship + shadow CHR under
;                  forced blank, turn Mode 7 on, arm the sky split
;   MAIN LOOP    — game_loop: turn, throttle, altitude, integrate, animate, draw
;   SUBROUTINES  — compute_scales (altitude -> scale), arm_sky_split (the sky band)
;   DATA         — the airship + shadow art, overworld palette, the ground blob
;
; game_loop is the once-per-frame heartbeat — start reading there.
;
; SIGNED SPEED: R_SPEED is a SIGNED 8.8 word, so reverse (Y) and hover fall out of
; the SAME sincos->smul16 integrator the racer uses — smul16 sign-handles, so a
; negative speed steps the camera backward for free.
;
; THE SKY: Mode 7 has one BG layer, so the band above the horizon would smear
; the ground upward. arm_sky_split (below) runs a 2-band TM HDMA on CH2 that
; turns BG1 off above the horizon, revealing the CGRAM[0] backdrop (the ground
; palette reserves index 0 as a sky blue).
;
; OBJ-OVER-MODE-7 (baked in below): the Mode 7 map fills VRAM words $0000-$3FFF,
; so OBSEL moves the OBJ name base to word $4000 ($62) and OBJ CHR uploads there.
;
; DESIGN LIMITS: no day/night, no terrain collision/crash, no streaming. The
; plane wraps (wrap=1) so free movement never hits a black edge, and altitude
; clamps at the floor (ground closest), so descending never crashes.
;
; Build:  make mode7_flight   (the generic templates rule reads the LDCFG sentinel)
; LDCFG: lorom_64k.cfg
;   ^ 64KB image: the 32KB Mode 7 ground-map blob fills BANK1.
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SKY VOYAGER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; the Mode 7 macro group (+ sf_mode7_scale)
.include "engine_state.inc"

; --- throttle tuning (assemble-time, signed 8.8) ---
.ifndef ACCEL
ACCEL = $0010                   ; 8.8: +0.0625 px/f per frame of B
.endif
.ifndef DECEL
DECEL = $0008                   ; 8.8: speed bleed per coast frame (toward hover)
.endif
.ifndef SPEED_CAP
SPEED_CAP = $0300               ; 8.8: 3 px/frame top forward speed
.endif
.ifndef SPEED_REV
SPEED_REV = $FE00               ; 8.8: -2 px/frame reverse cap (signed: -$0200)
.endif

; --- the flight-camera trapezoid (looking down from altitude) ---
; A high horizon band so the ground spreads out below; sky above. The s0/s1
; here are the BASE scale; the per-frame altitude derive overwrites them via
; sf_mode7_scale (they are only the mid-altitude starting point).
PV_L0_FLIGHT     = 64           ; horizon scanline (~29% down; sky band above)
PV_L1_FLIGHT     = 224          ; bottom scanline
PV_S0_FLIGHT     = 600          ; far-scale  base (mid-altitude)
PV_S1_FLIGHT     = 140          ; near-scale base (mid-altitude)
PV_SH_FLIGHT     = 0            ; derive vertical (no road squash)
PV_INTERP_FLIGHT = 2
PV_WRAP_FLIGHT   = 1            ; wrapping plane: free movement, no black edge
FOCUS_Y_FLIGHT   = 168          ; the flight rotation anchor

; --- altitude -> perspective scale (the distinctive piece) -------------------
; R_ALT is an 8-bit altitude 0..255 (MIN=ground closest, MAX=ground farthest).
; Each frame: s0 = S0_LOW + alt*(S0_HIGH-S0_LOW)/256 ; s1 likewise. Climb (alt
; up) -> bigger s0/s1 -> ground recedes; descend (alt down) -> smaller ->
; approaches. The measured endpoints (low 220/40, high 1180/280).
ALT_MIN  = 0                    ; floor of altitude (ground closest; clamp, no crash)
ALT_MAX  = 240                  ; ceiling of altitude (ground farthest)
ALT_STEP = 3                    ; altitude change per held L/R frame (smooth)
ALT_SPAWN = 120                 ; mid-altitude spawn
S0_LOW   = 220                  ; far-scale at ALT_MIN (ground close/big)
S0_HIGH  = 1180                 ; far-scale at alt 256 (ground far/small)
S1_LOW   = 40                   ; near-scale at ALT_MIN
S1_HIGH  = 280                  ; near-scale at alt 256
S0_SPAN  = S0_HIGH - S0_LOW     ; 960
S1_SPAN  = S1_HIGH - S1_LOW     ; 240

; --- spawn: over the overworld terrain, facing along the plane ---
SPAWN_X = 872                   ; over a detailed continent/coast tile cluster
SPAWN_Y = 512
SHIP_X  = 128 - 16              ; fixed-screen 32x32 airship: centered, ...
SHIP_Y  = 96                    ; ...above the focus scanline

; --- OBJ tile numbers (relative to the OBSEL name base) ---
; OAM tile numbers (relative to the OBSEL name base, tile 1024). Each 32x32
; frame starts on a 16-aligned VRAM-row boundary (sf_load_obj_chr requires it),
; so frames are 64 tiles apart.
SHIP_TILE_A   = 0               ; airship, propeller frame A
SHIP_TILE_B   = 64              ; airship, propeller frame B
SHADOW_TILE_BIG   = 128         ; ground-shadow, BIG 32x32 (airship LOW)
SHADOW_TILE_SMALL = 192         ; ground-shadow, SMALL 16x16 (airship HIGH)
PROP_RATE     = 8               ; frames between propeller flips (animation)
; shadow Y placement: screen-Y drops toward the horizon as altitude rises, so
; the shadow visibly separates from the airship when climbing.
SHADOW_X      = 128 - 16        ; centered under the airship (32x32 anchor)
SHADOW_Y_LOW  = 168            ; close under the ship when low
SHADOW_ALT_THRESH = 120         ; alt >= this -> small/high shadow, else big/low

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_Y     = $4000
JOY_B     = $8000
JOY_L     = $0020
JOY_R     = $0010

; --- sky TM-split (see arm_sky_split) ---
SKY_SPLIT_TABLE = $7E0000 + $2010
SKY_HORIZON     = PV_L0_FLIGHT

; --- game DP state (kit contract: $32-$5F) ---
R_POSX   = $32                  ; camera x, 16.16 (fraction word, integer word)
R_POSY   = $36                  ; camera y, 16.16
R_ANGLE  = $3A                  ; heading word (low byte = 0..255 turn)
R_SPEED  = $3C                  ; SIGNED 8.8 speed (B=fwd, Y=rev, release=hover)
R_SCRATCH = $3E                 ; per-frame OBJ tile-select scratch
R_ALT    = $40                  ; altitude 0..255 (L=descend, R=climb; clamped)
R_S0     = $42                  ; this frame's derived far-scale (u16)
R_S1     = $44                  ; this frame's derived near-scale (u16)
R_PROPT  = $46                  ; propeller animation timer
R_PROPF  = $48                  ; current propeller frame (0 = A, 1 = B)
R_TILE2  = $4A                  ; second OBJ (shadow) tile-select scratch

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y commit)

NMI_STUB:
    rti

; =============================================================================
; INIT — power-on setup: upload the ground map, palettes, and airship + shadow
; CHR under forced blank; turn Mode 7 on; arm the sky split; then screen + NMI on.
; =============================================================================
RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- ground upload (under the coldstart forced blank) ---
    sf_mode7_load_map ground_map, #$8000

    ; ground palette -> CGRAM 0.. (index 0 = sky for the TM-split backdrop).
    ; The overworld palette already reserves index 0 as a sky blue ($726C) via
    ; the converter's reserve_sky_backdrop (mirrors the racer's track sky slot),
    ; so arm_sky_split below reveals a real sky above the horizon.
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD (CGRAM address): start at colour 0
    ldx #$0000
gpal_loop:
    .a8
    lda f:ovw_pal, x
    sta $2122                   ; CGDATA (CGRAM data): write; low then high byte auto-pair
    inx
    cpx #(OVW_PAL_COUNT * 2)
    bne gpal_loop
    rep #$30
    .a16
    .i16

    ; --- airship + shadow sprite palettes -> OBJ palettes out of the Mode 7
    ; map's VRAM. OBSEL=$62 moves the OBJ name base to word $4000 (tile 1024);
    ; OAM tile numbers stay 0.. relative to that base.
    ; Airship palette is raw BGR555 bytes -> OBJ palette 0 (CGRAM word 128).
    sep #$20
    .a8
    rep #$10
    .i16
    lda #128
    sta $2121                   ; CGADD = 128 (OBJ palette 0)
    ldx #$0000
apal_loop:
    .a8
    lda f:airship_sprite_palette, x
    sta $2122                   ; CGDATA: stream the airship palette bytes
    inx
    cpx #AIRSHIP_SPR_PAL_SIZE
    bne apal_loop
    rep #$30
    .a16
    .i16
    ; ground-shadow art -> OBJ palette 1 (generated; a dark ellipse)
    sf_load_obj_pal 1, shadow_pal

    ; --- airship CHR: 2 propeller frames (straight-facing prop A = frame 0,
    ; prop B = frame 12), each a 32x32 OBJ. Each 512-byte frame is 4 blocks of
    ; 128 bytes (one tile-row of 4 tiles); the hardware 32x32 OBJ reads its 4
    ; rows 16 tiles apart, so upload each block at base + row*16. Prop A at
    ; relative tile 0 (top-left tile 1024), prop B at relative tile 4 (next 4
    ; columns, same VRAM rows). Animation flips the OAM tile between 0 and 4.
    sf_load_obj_chr 1024, airship_tile_data + 0, 128       ; A block0 (rel tile 0)
    sf_load_obj_chr 1040, airship_tile_data + 128, 128     ; A block1 (row+1)
    sf_load_obj_chr 1056, airship_tile_data + 256, 128     ; A block2 (row+2)
    sf_load_obj_chr 1072, airship_tile_data + 384, 128     ; A block3 (row+3)
    sf_load_obj_chr 1088, airship_tile_data + 6144 + 0, 128   ; B block0 (rel tile 64, frame12)
    sf_load_obj_chr 1104, airship_tile_data + 6144 + 128, 128 ; B block1
    sf_load_obj_chr 1120, airship_tile_data + 6144 + 256, 128 ; B block2
    sf_load_obj_chr 1136, airship_tile_data + 6144 + 384, 128 ; B block3
    ; --- ground-shadow CHR (block layout, like the airship): the BIG 32x32
    ; ellipse at relative tile 8 (rows 1032/1048/1064/1080) and the SMALL 16x16
    ; ellipse at relative tile 12 (rows 1036/1052). Altitude flips between them.
    sf_load_obj_chr 1152, shadow_big + 0, 128              ; big block0 (rel tile 128)
    sf_load_obj_chr 1168, shadow_big + 128, 128            ; big block1 (row+1)
    sf_load_obj_chr 1184, shadow_big + 256, 128            ; big block2 (row+2)
    sf_load_obj_chr 1200, shadow_big + 384, 128            ; big block3 (row+3)
    sf_load_obj_chr 1216, shadow_small + 0, 64             ; small block0 (rel tile 192)
    sf_load_obj_chr 1232, shadow_small + 64, 64            ; small block1 (row+1)

    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: name base word $4000, 16x16/32x32
    lda #$10
    sta SHADOW_TM               ; OBJ on; the NMI commits TM = $11 with BG1
    rep #$30
    .a16
    .i16

    ; --- Mode 7 on + the flight camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0_FLIGHT, #PV_L1_FLIGHT, #PV_S0_FLIGHT, #PV_S1_FLIGHT, #PV_SH_FLIGHT, #PV_INTERP_FLIGHT, #PV_WRAP_FLIGHT
    sf_mode7_focus #FOCUS_Y_FLIGHT

    lda #SPAWN_X
    sta R_POSX + 2              ; integer px
    stz R_POSX + 0             ; fraction = 0
    lda #SPAWN_Y
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_ANGLE
    stz R_SPEED                 ; hover at spawn
    lda #ALT_SPAWN
    sta R_ALT                   ; mid-altitude spawn
    lda #PROP_RATE
    sta R_PROPT
    stz R_PROPF                 ; propeller frame A
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE

    jsr compute_scales          ; derive s0/s1 from the spawn altitude
    sf_mode7_scale R_S0, R_S1   ; install them (flags rebuild)

    sf_mode7_tick               ; first table build BEFORE screen-on

    jsr arm_sky_split           ; CH2 TM-split: reveal the sky above the horizon

    spr_clear
    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP (display control): brightness 15, blank off
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt enable): VBlank NMI + auto-joypad read
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop runs once per frame: turn the heading, integrate the
; throttle, apply altitude -> scale, step the camera, animate the prop, draw.
; =============================================================================
game_loop:
    .a16
    sf_frame_begin              ; wait for the NMI; latch input

    ; ---------------- heading: LEFT/RIGHT rotate 1/256 turn per frame -------
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq fl_no_left
    lda R_ANGLE
    inc a
    and #$00FF
    sta R_ANGLE
fl_no_left:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq fl_no_right
    lda R_ANGLE
    dec a
    and #$00FF
    sta R_ANGLE
fl_no_right:
    .a16

    ; ---------------- throttle: B forward, Y reverse, release -> hover ------
    ; R_SPEED is SIGNED 8.8. B adds ACCEL up to +SPEED_CAP; Y subtracts ACCEL
    ; down to SPEED_REV; neither held -> bleed toward 0 (hover). The signed
    ; smul16 below then steps the camera forward (B) or backward (Y) for free.
    lda JOY1_CURRENT
    bit #JOY_B
    bne fl_fwd
    lda JOY1_CURRENT
    bit #JOY_Y
    bne fl_rev
    ; --- no throttle: coast toward hover (move R_SPEED toward 0) ---
    lda R_SPEED
    beq fl_speed_done           ; already hovering
    bmi fl_coast_neg
    ; positive speed: subtract DECEL, floor at 0
    sec
    sbc #DECEL
    bpl fl_speed_store          ; still >= 0
    lda #$0000
    bra fl_speed_store
fl_coast_neg:
    .a16
    ; negative speed: add DECEL, ceil at 0
    clc
    adc #DECEL
    bmi fl_speed_store          ; still < 0
    lda #$0000
    bra fl_speed_store
fl_fwd:
    .a16
    lda R_SPEED
    clc
    adc #ACCEL
    cmp #(SPEED_CAP + 1)
    bcc fl_speed_store          ; below cap (and positive)
    lda #SPEED_CAP
    bra fl_speed_store
fl_rev:
    .a16
    lda R_SPEED
    sec
    sbc #ACCEL
    ; clamp to SPEED_REV (signed): if A < SPEED_REV then A = SPEED_REV.
    ; both are negative; signed compare via SEC/SBC sign test.
    pha
    sec
    sbc #SPEED_REV              ; (A - SPEED_REV); negative => A < SPEED_REV
    bpl fl_rev_ok
    pla
    lda #SPEED_REV
    bra fl_speed_store
fl_rev_ok:
    .a16
    pla
fl_speed_store:
    .a16
    sta R_SPEED
fl_speed_done:
    .a16

    ; ---------------- altitude: L descend, R climb (clamped, no crash) ------
    ; R_ALT is 8-bit 0..255. L lowers it (ground approaches), R raises it
    ; (ground recedes), ALT_STEP per held frame, clamped [ALT_MIN, ALT_MAX].
    lda JOY1_CURRENT
    bit #JOY_R
    beq fl_no_climb
    lda R_ALT
    clc
    adc #ALT_STEP
    cmp #(ALT_MAX + 1)
    bcc fl_alt_store_hi
    lda #ALT_MAX                 ; clamp at the ceiling (ground farthest)
fl_alt_store_hi:
    .a16
    sta R_ALT
fl_no_climb:
    .a16
    lda JOY1_CURRENT
    bit #JOY_L
    beq fl_no_descend
    lda R_ALT
    sec
    sbc #ALT_STEP
    bcs fl_alt_chk_min          ; no borrow: result >= 0
    lda #ALT_MIN                 ; underflowed -> clamp at the floor
    bra fl_alt_store_lo
fl_alt_chk_min:
    .a16
    cmp #ALT_MIN
    bcs fl_alt_store_lo
    lda #ALT_MIN                 ; clamp at the floor (ground closest; no crash)
fl_alt_store_lo:
    .a16
    sta R_ALT
fl_no_descend:
    .a16
    ; derive s0/s1 from the (possibly changed) altitude and install them
    jsr compute_scales
    sf_mode7_scale R_S0, R_S1   ; flags M7_DIRTY_REBUILD (full rebuild this frame)

    ; ---------------- integrate: pos -= (sina, cosa) x speed ----------------
    ; The proven racing-camera pattern, unlocked: sincos resolves the heading,
    ; smul16 scales it by the SIGNED 8.8 speed into a 16.16 step, and the
    ; subtraction advances "toward the horizon" (forward) or backward when speed
    ; is negative. The integer word wraps to the 1024px map with `and #$03FF`.
    lda R_ANGLE
    and #$00FF
    jsr sincos                  ; sina/cosa <- signed 8.8 (engine mode7_math)

    sep #$10                    ; smul16 contract: .a16 .i8, DP=0, DB=0
    .i8
    lda a:sina
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16                  ; math_p = sina x speed (s32, 16.16)
    lda R_POSX + 0
    sec
    sbc a:math_p + 0
    sta R_POSX + 0              ; fraction word
    lda R_POSX + 2
    sbc a:math_p + 2
    and #$03FF                  ; wrap to the 1024px map
    sta R_POSX + 2             ; integer word

    lda a:cosa
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16
    lda R_POSY + 0
    sec
    sbc a:math_p + 0
    sta R_POSY + 0
    lda R_POSY + 2
    sbc a:math_p + 2
    and #$03FF
    sta R_POSY + 2
    rep #$30
    .a16
    .i16

    ; ---------------- camera + Mode 7 service --------------------------------
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE
    sf_mode7_tick

    ; ---------------- propeller animation: flip A<->B every PROP_RATE frames -
    lda R_PROPT
    dec a
    sta R_PROPT
    bne fl_prop_done
    lda #PROP_RATE
    sta R_PROPT
    lda R_PROPF
    eor #$0001
    sta R_PROPF                  ; toggle 0 <-> 1
fl_prop_done:
    .a16

    ; ---------------- draw: airship (slot 0, on top) + shadow (slot 1) -------
    spr_clear
    ; airship tile: A (prop 0) or B (prop 1)
    lda R_PROPF
    beq fl_use_a
    lda #SHIP_TILE_B
    bra fl_ship_put
fl_use_a:
    .a16
    lda #SHIP_TILE_A
fl_ship_put:
    .a16
    sta R_SCRATCH
    spr R_SCRATCH, #SHIP_X, #SHIP_Y, #$0080, #2   ; large (32x32), OBJ pal 0

    ; ground shadow: size + tile + screen-Y track altitude. Low altitude ->
    ; BIG 32x32 shadow close under the ship; high -> SMALL 16x16 lower toward
    ; the horizon. Screen-Y = SHADOW_Y_LOW + (alt >> 3) (drops as you climb).
    lda R_ALT
    lsr a
    lsr a
    lsr a
    clc
    adc #SHADOW_Y_LOW
    sta R_SCRATCH               ; shadow screen-Y
    lda R_ALT
    cmp #SHADOW_ALT_THRESH
    bcs fl_shadow_small
    ; --- BIG / low ---
    lda #SHADOW_TILE_BIG
    sta R_TILE2
    spr R_TILE2, #SHADOW_X, R_SCRATCH, #$0082, #2   ; large (32x32), OBJ pal 1
    bra fl_shadow_done
fl_shadow_small:
    .a16
    lda #SHADOW_TILE_SMALL
    sta R_TILE2
    spr R_TILE2, #SHADOW_X, R_SCRATCH, #$0002, #2   ; small (16x16), OBJ pal 1
fl_shadow_done:
    .a16

    ; ---------------- heartbeat + debug mirrors -----------------------------
    ; $E010 = frame heartbeat; $E018 = altitude (test orchestration only —
    ; visual assertions stay on rendered output). $E01A/$E01C mirror s0/s1.
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    lda R_ALT
    sta f:$7E0000 + $E018, x
    lda R_S0
    sta f:$7E0000 + $E01A, x
    lda R_S1
    sta f:$7E0000 + $E01C, x

    sf_frame_end                ; resolve sprites; signal the OAM DMA
    jmp game_loop

; =============================================================================
; ============================== SUBROUTINES ==================================
; compute_scales (altitude -> near/far scale) + arm_sky_split (the sky band).
; =============================================================================

; =============================================================================
; compute_scales — derive R_S0/R_S1 from R_ALT (call once per frame, A16/I16).
; =============================================================================
; s0 = S0_LOW + (alt * S0_SPAN) >> 8 ; s1 = S1_LOW + (alt * S1_SPAN) >> 8.
; alt is 0..255, the spans <= 960, so the product fits in 16 bits and the >>8
; (the product's high byte of the low word) is the interpolation. Uses umul16
; (a16/i8, math_a*math_b -> math_p u32). Higher alt -> bigger scale -> ground
; recedes.
; WIDTH-RISK: A16/I16 entry. umul16 wants .i8; we sep #$10 around it and restore
; .i16 on exit. A stays 16-bit throughout.
compute_scales:
    .a16
    .i16
    sep #$10                    ; umul16 contract: .a16 .i8
    .i8
    ; --- s0 ---
    lda R_ALT
    and #$00FF
    sta a:math_a
    lda #S0_SPAN
    sta a:math_b
    jsr umul16                  ; math_p = alt * S0_SPAN (u32)
    lda a:math_p + 1            ; bytes [1..2] = (product >> 8)
    clc
    adc #S0_LOW
    sta R_S0
    ; --- s1 ---
    lda R_ALT
    and #$00FF
    sta a:math_a
    lda #S1_SPAN
    sta a:math_b
    jsr umul16                  ; math_p = alt * S1_SPAN (u32)
    lda a:math_p + 1            ; bytes [1..2] = (product >> 8)
    clc
    adc #S1_LOW
    sta R_S1
    rep #$10                    ; restore I16
    .i16
    rts

; =============================================================================
; arm_sky_split — reveal the sky above the horizon (call once, A16/I16 entry).
; =============================================================================
; Mode 7 has a single BG layer (the perspective floor), so without help the
; ground tilemap smears upward past the horizon where a SKY belongs. The fix is
; a per-scanline TM split: turn BG1 OFF above the horizon so the CGRAM[0]
; backdrop (the ground palette reserves index 0 for a sky blue) shows, and keep
; BG1 ON below it for the floor. OBJ stays on in both bands so the airship still
; renders above the horizon. CH2 is the legacy idle-placeholder channel; we
; program its DMA registers directly and OR it into NMI_HDMA_ENABLE (the engine
; NMI re-arms $420C every VBlank but leaves CH2's config alone — it is not
; Mode-7-owned).
;
; WIDTH-RISK: entry A16/I16. Sets A8 for the byte writes to $43xx + the
; NMI_HDMA_ENABLE RMW, restores caller width via PLP. I16 unchanged.
arm_sky_split:
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ; --- build the 2-band TM table in WRAM ($7E:2010) ---
    ldx #$0000
    lda #(SKY_HORIZON)          ; lines 0..horizon-1, non-repeat (bit7=0)
    sta f:SKY_SPLIT_TABLE + 0, x
    lda #$10                    ; BG1 off, OBJ on (the sky backdrop)
    sta f:SKY_SPLIT_TABLE + 1, x
    lda #$01                    ; 1 line, non-repeat
    sta f:SKY_SPLIT_TABLE + 2, x
    lda #$11                    ; BG1 + OBJ (the Mode 7 floor)
    sta f:SKY_SPLIT_TABLE + 3, x
    lda #$00                    ; terminator (stz has no abs-long mode)
    sta f:SKY_SPLIT_TABLE + 4, x
    ; --- configure CH2 DMA registers directly (non-Mode-7-owned) ---
    lda #$00
    sta $4320                   ; DMAP2: A->B, absolute table, 1 byte -> 1 reg
    lda #$2C
    sta $4321                   ; BBAD2: $212C (TM)
    lda #<SKY_SPLIT_TABLE
    sta $4322                   ; A1T2L
    lda #>SKY_SPLIT_TABLE
    sta $4323                   ; A1T2H
    lda #^SKY_SPLIT_TABLE
    sta $4324                   ; A1B2 (bank $7E)
    ; --- arm CH2 in the NMI HDMA enable mask (additive; pv_rebuild ORs too) ---
    lda NMI_HDMA_ENABLE
    ora #$04
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
    rts

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order, plus the
; sprite + DMA engines sf_frame_end / spr require.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; =============================================================================
; DATA — committed assets. Ground is the kit-native RPG overworld map (continent
; + coastline) so the airship flies over land, not a racetrack; the airship is
; the sanctioned art reuse (data only, clean kit header); the shadow is
; first-party generated. The 32KB ground blob (BANK1) is below.
; =============================================================================
.include "assets/airship.inc"
.include "assets/shadow.inc"
.include "assets/overworld_palette.inc"

; --- the 32KB interleaved ground blob (bank 1 of the 64KB image) ---
.segment "BANK1"
ground_map:
    .incbin "assets/ground_map.bin"
