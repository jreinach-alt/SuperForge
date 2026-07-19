; =============================================================================
; mode7_chamber — Mode 7 "barrel chamber" effect demo (autonomous tech demo)
; =============================================================================
; An autonomous Mode 7 tech demo: a stone-textured floor bows into a barrel and
; rolls endlessly beneath a Mode 1 HUD band, darkened top and bottom by a
; brightness vignette. It is a showcase for four cooperating per-scanline HDMA
; effects layered over one Mode 7 plane — nothing is played, the motion drives
; itself. CLEAN-ROOM: the stone art is original placeholder art
; (assets/make_chamber.py); only the Mode 7 effect TECHNIQUE is recreated, never
; any commercial-game content. The register values (the barrel M7A table, the
; COLDATA vignette table, the BGMODE/TM split bytes) are factual hardware
; configuration.
;
; Controls:  none — autonomous demo. The roll drives itself from an LFSR; the
;            joypad is never read.
;
; File layout (major banners, top to bottom):
;   INIT         — upload the map / palette under forced blank, arm the four HDMA
;                  effects, turn Mode 7 on
;   MAIN LOOP    — game_loop: advance the roll (surge/hold/reverse), scroll posy
;   SUBROUTINES  — chamber_draw_peak, chamber_new_leg
;   DATA         — the barrel curve, vignette + palette tables, the map blob
;
; game_loop is the once-per-frame heartbeat — start reading there.
;
; THE EFFECT (the "pipe" motion model — apparent rotation from a vertical roll):
;   1. NO rotation. The chamber is a "popsicle stick in a PVC pipe": the angle is
;      held CONSTANT and the floor texture ROLLS vertically (posy scrolls); the
;      apparent rotation is that scroll through the static barrel bow, NOT an
;      affine matrix. The roll runs in LEGS, each ONE direction and made of
;      NUM_HUMPS (3) SURGES: the speed rises smoothly to a randomised peak (hard-
;      capped at PEAK_CAP), touches it momentarily, then drops QUICKLY
;      (DECEL > ACCEL) toward a slow creep — speed up / slow down, 3 times. After
;      the surges the leg stops dead, holds ~0.5 s, then REVERSES. Forward and
;      reverse legs draw their surge peaks from SEPARATE LFSR streams, so each
;      direction has its own variance pattern. posy is a 16.8 accumulator advanced
;      by the signed velocity each frame and wrapped to the 1024px periodic map
;      (M7SEL wrap), so the roll is seamless.
;   2. Per-scanline M7A barrel — sf_mode7_barrel arms the engine's per-scanline
;      hook; the $0100->$0180->$0100 curve bows the floor into a barrel (M7A
;      carries the bow while M7B/C/D hold the fixed orientation).
;   3. Dual-register mode-split — sf_mode7_modesplit drives BOTH $2105 (BGMODE
;      $09 Mode1 -> $07 Mode7) AND $212C (TM, HUD band -> floor) at scanline 32,
;      so the top band is a clean Mode 1 HUD strip above the Mode 7 floor.
;   4. COLDATA vignette — sf_mode7_vignette ramps $2132 0->8->0 (additive colour
;      math on) for depth: brightest through the middle, dark top/bottom.
;
; HDMA CHANNEL ALLOCATION (distinct channels, NO collision):
;   CH0,CH1  reserved (hdma_alloc_init: VBlank bulk DMA)
;   CH2      BGMODE $2105 split   (sf_mode7_modesplit, direct, non-M7-owned)
;   CH3      TM     $212C split   (sf_mode7_modesplit, direct, non-M7-owned)
;   CH4      COLDATA $2132 vignette (sf_mode7_vignette, direct, non-M7-owned)
;   CH5,CH6  Mode 7 matrix AB/CD  (mode7_init pins; M7A barrel in the A column)
;   CH7      free
;
; What the emulator checks (tests/test_mode7_chamber.py):
;   - boots ("SFDB"); heartbeat advances; posy oscillates (the undulation)
;   - the floor UNDULATES (posy rides the surge/hold cycle; the floor re-paints as
;     the texture travels up and down — no rotation matrix, angle held constant)
;   - the floor BOWS (per-scanline M7A varies top->mid->bottom — barrel)
;   - a Mode 1 HUD band sits above the Mode 7 floor (clean, no smear)
;   - the vignette: the mid band is brighter than the top/bottom
;
; Build:  make mode7_chamber
; LDCFG: lorom_64k.cfg
;   ^ Linker-config sentinel: 64KB image, the 32KB Mode 7 chamber-map blob fills
;     BANK1 (same pattern as the racer rail).
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "BARREL CHAMBER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_mode7.inc"         ; the Mode 7 perspective macro group + barrel hook
.include "sf_mode7_chamber.inc" ; the chamber front door (modesplit/vignette/barrel)
.include "sf_fx.inc"            ; colour math (additive — the vignette dependency)
.include "engine_state.inc"

; --- the chamber camera (floor fills line 32..224 under a 32-line HUD band) ---
PV_L0_CHAMBER     = 32          ; horizon = the mode-split line (HUD above, floor below)
PV_L1_CHAMBER     = 224
PV_S0_CHAMBER     = 320         ; far-scale (the chamber recedes)
PV_S1_CHAMBER     = 64          ; near-scale
; PV_SH: vertical texel height. 0 = "derive" (square aspect) — but that leaves the
;   rows as VERTICALLY WIDE as possible. A large SH squashes the rows vertically
;   (SA = SH / (PV_S0*(L1-L0)/256) = SH/240 here), packing far more horizontal
;   detail per screen — the chamber's dense narrow rows. Measured: detail
;   (visible rows) peaks ~SH 1440 (≈2x the baseline density); beyond that the
;   rows go sub-texel and just alias. This is THE "make the rows narrow" knob.
PV_SH_CHAMBER     = 1440
PV_INTERP_CHAMBER = 1           ; true per-scanline matrix (no averaging) — free
                                ;   here: the chamber rebuilds once at init only
PV_WRAP_CHAMBER   = 1
FOCUS_Y_CHAMBER   = 128         ; rotation origin mid-floor

; --- the mode-split bytes (configurable). The captured chamber uses
;     $2105 $09->$07 and $212C $14->$17; the demo keeps the captured BGMODE
;     bytes and uses a clean OBJ-only HUD band ($10) so the top strip shows the
;     backdrop (no BG3 tilemap to author) over the BG1 floor ($11) below. ---
BGM_TOP = $09                   ; Mode 1 + BG3 priority (the captured HUD band mode)
BGM_BOT = $07                   ; Mode 7 (the floor)
TM_TOP  = $10                   ; OBJ only -> the HUD band shows the backdrop, clean
TM_BOT  = $11                   ; BG1 + OBJ -> the Mode 7 floor
SPLIT_Y = PV_L0_CHAMBER         ; the HUD/floor split scanline (32)

; --- HDMA channels (distinct, no collision) ---
CH_BGM  = 2
CH_TM   = 3
CH_COL  = 4

; --- WRAM scratch for the direct-HDMA split/vignette tables (bank $7E) ---
BGM_TABLE   = $7E0000 + $2010   ; 5 bytes
TM_TABLE    = $7E0000 + $2018   ; 5 bytes
VIGN_TABLE  = $7E0000 + $2020   ; CHAMBER_VIGNETTE_LEN bytes

; --- the ROLL (the "pipe" motion: NO rotation; the floor texture rolls
;     vertically through the static barrel bow — apparent rotation is the scroll).
;     Each "leg" rolls ONE direction and contains NUM_HUMPS surges: the speed
;     rises smoothly to a randomised peak, momentarily touches it, then drops
;     QUICKLY (DECEL > ACCEL) toward a slow creep — speed up / slow down, 3 times.
;     After the surges the leg stops dead, HOLDs ~0.5 s, then REVERSES. Forward
;     and reverse legs draw surge peaks from SEPARATE LFSR streams, so each
;     direction has its own variance pattern. posy is a 16.8 accumulator advanced
;     by the signed velocity and wrapped to the 1024px periodic map. ---
ACCEL        = $0002            ; rise rate 8.8 (smooth "speed up")
DECEL        = $0008            ; fall rate 8.8 (4x accel — "drop quickly")
VFLOOR       = $0040            ; speed between surges (0.25 px/frame — keeps creeping)
PEAK_MIN     = $0100            ; min surge peak (1.0 px/frame)
PEAK_RNGMASK = $03FF            ; surge peak random span: PEAK_MIN + (dirRNG & this)
PEAK_CAP     = $0400            ; surge peak HARD CAP = 4.0 px/frame (the fastest a
                                ;   surge is allowed to roll)
NUM_HUMPS    = 3                ; surges per leg (speed up / slow down 3x per dir)
HOLD_FRAMES  = 30               ; ~0.5 s dead-stop pause between legs (60 fps)
RNG_SEED_F   = $A357            ; forward LFSR seed (the forward variance pattern)
RNG_SEED_R   = $1D8B            ; reverse LFSR seed (a DIFFERENT pattern per dir)
MAP_MASK     = $03FF            ; posy wraps to the 1024px (0..1023) periodic map

; --- spawn ---
START_X = 512                   ; chamber centre (horizontal position is fixed)
START_Y = 512

; --- game DP state (kit contract: $32-$5F) ---
C_POSX   = $32                  ; camera x word (integer px, constant)
POSYACC  = $34                  ; posy 16.8 accumulator: $34 frac8, $35-$36 int16
                                ;   (integer posy for the camera = word @ POSYACC+1)
VMAG     = $38                  ; word: unsigned 8.8 current speed magnitude
HCUR     = $3A                  ; word: current surge's target peak (8.8)
HUMP     = $3C                  ; word: surge index within the leg (0..NUM_HUMPS-1)
SUBPH    = $3E                  ; word: 0 = rising to the peak, 1 = falling
C_DIR    = $40                  ; word: $0000 = roll forward (+), $FFFF = reverse (-)
C_STATE  = $42                  ; word: 0 = ROLLING, 1 = HOLDING (dead stop)
C_HOLD   = $44                  ; word: hold-timer countdown (frames)
RNG_F    = $46                  ; word: forward-leg LFSR (its own variance pattern)
RNG_R    = $48                  ; word: reverse-leg LFSR (a different pattern)
C_VEL    = $4A                  ; word: signed 8.8 velocity applied THIS frame
C_VSGN   = $4C                  ; byte: scratch sign-extension for the 24-bit add

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y commit)

NMI_STUB:
    rti

; =============================================================================
; INIT — power-on setup: upload the map + palette under forced blank, turn Mode 7
; on, arm the four per-scanline HDMA effects, seed the roll, then screen + NMI on.
; =============================================================================
RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- chamber map upload (under the coldstart forced blank) ---
    sf_mode7_load_map chamber_map, #$8000

    ; chamber palette -> CGRAM 0.. (CGRAM idx 0 = stone backdrop)
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD (CGRAM address): start at colour 0
    ldx #$0000
cpal_loop:
    .a8
    lda f:chamber_pal, x
    sta $2122                   ; CGDATA (CGRAM data): write; low then high byte auto-pair
    inx
    cpx #(CHAMBER_PAL_COUNT * 2)
    bne cpal_loop
    rep #$30
    .a16
    .i16

    ; --- additive colour math so the per-scanline COLDATA vignette is VISIBLE
    ;     (the captured effect's documented dependency). Mode 1 = ADD, on the
    ;     backdrop + BG1 (#$21 = bit0 BG1 + bit5 backdrop); tint 0 so the NMI's
    ;     static COLDATA is black and the HDMA ramp owns the visible region. ---
    sf_colormath_on #1, #$21
    sf_colormath_tint #0, #0, #0

    ; --- Mode 7 on + the chamber camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0_CHAMBER, #PV_L1_CHAMBER, #PV_S0_CHAMBER, #PV_S1_CHAMBER, #PV_SH_CHAMBER, #PV_INTERP_CHAMBER, #PV_WRAP_CHAMBER
    sf_mode7_focus #FOCUS_Y_CHAMBER
    sf_mode7_flags #$00         ; WRAP the 1024px periodic map (seamless rolling)

    lda #START_X
    sta C_POSX
    ; posy 16.8 accumulator = START_Y (frac 0)
    stz POSYACC                 ; clears frac ($34) + int.lo ($35)
    lda #START_Y
    sta POSYACC+1               ; integer posy ($35-$36) = START_Y
    ; roll state: seed both LFSRs, start a forward leg (surges from a standstill)
    lda #RNG_SEED_F
    sta RNG_F
    lda #RNG_SEED_R
    sta RNG_R
    stz C_DIR                   ; forward
    stz C_STATE                 ; ROLLING
    stz C_HOLD
    jsr chamber_new_leg         ; HUMP/SUBPH/VMAG = 0; draw surge-0 peak
    stz C_VEL
    sf_mode7_cam C_POSX, POSYACC+1, #0   ; angle constant 0 (no rotation)

    sf_mode7_tick               ; first table build BEFORE screen-on

    ; --- arm the chamber effects (after sf_mode7_on; A16/I16) ---
    sf_mode7_barrel chamber_barrel
    sf_mode7_modesplit #BGM_TOP, #BGM_BOT, #TM_TOP, #TM_BOT, #SPLIT_Y, CH_BGM, CH_TM, BGM_TABLE, TM_TABLE
    sf_mode7_vignette chamber_vignette, CH_COL, VIGN_TABLE, #CHAMBER_VIGNETTE_LEN

    ; Force ONE full rebuild so mode7_barrel_apply stamps the barrel into the
    ; active AB buffer. With a CONSTANT angle the per-frame loop only re-anchors
    ; the origin (cheap M7X/M7Y via sf_mode7_cam -> M7_DIRTY_ORIGIN), and never
    ; sets M7_DIRTY_REBUILD — so pv_rebuild/barrel_apply run exactly ONCE, here,
    ; and the barrel persists (the double-buffer never flips again). This is why
    ; the undulation is cheap: the ~10k-cycle perspective rebuild runs only once.
    sep #$20
    .a8
    lda #$01
    sta M7_DIRTY_REBUILD
    rep #$20
    .a16
    sf_mode7_tick               ; full rebuild + barrel stamp into the active buffer

    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP (display control): brightness 15, blank off
    sta SHADOW_INIDISP          ; the NMI re-commits INIDISP from this shadow
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt enable): VBlank NMI + auto-joypad read
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop runs once per frame: step the roll state machine (surge /
; hold / reverse), apply the signed velocity to posy, re-anchor the Mode 7 origin.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin              ; wait for the NMI; latch input

    ; ---- the ROLL state machine (no rotation; posy scrolls the floor). HOLDING
    ;      = dead stop between legs. ROLLING = NUM_HUMPS surges: rise smoothly to a
    ;      random peak, touch it momentarily, then drop QUICKLY toward a creep.
    ;      C_VEL (signed 8.8) is the velocity applied this frame. All A16.
    lda C_STATE
    beq @roll_active
    ; --- HOLDING: dead stop; count down; then reverse + a fresh leg ---
    stz C_VEL
    dec C_HOLD
    bne @apply_posy
    lda C_DIR
    eor #$FFFF
    sta C_DIR                   ; flip direction
    jsr chamber_new_leg         ; surges now drawn from the new direction's LFSR
    bra @apply_posy
@roll_active:
    .a16
    lda SUBPH
    bne @roll_fall
    ; --- RISING: accelerate smoothly toward this surge's peak (HCUR) ---
    lda VMAG
    clc
    adc #ACCEL
    cmp HCUR
    bcc @roll_setmag            ; still below the peak -> keep rising
    lda HCUR                    ; clamp: the peak is reached only momentarily
    sta VMAG
    lda #$0001
    sta SUBPH                   ; -> falling
    bra @roll_sign
@roll_fall:
    .a16
    ; --- FALLING: drop QUICKLY toward the creep floor (DECEL > ACCEL) ---
    lda VMAG
    sec
    sbc #DECEL
    bcc @roll_dip               ; underflowed 0 -> at the dip between surges
    cmp #VFLOOR
    bcc @roll_dip               ; below the creep floor -> at the dip
@roll_setmag:
    .a16
    sta VMAG
    bra @roll_sign
@roll_dip:
    .a16
    ; surge complete -> start the next surge, or end the leg after NUM_HUMPS
    lda HUMP
    inc
    sta HUMP
    cmp #NUM_HUMPS
    bcc @roll_nexthump
    ; all surges done -> dead stop + HOLD (the HOLDING branch then reverses)
    stz VMAG
    lda #$0001
    sta C_STATE
    lda #HOLD_FRAMES
    sta C_HOLD
    bra @roll_sign
@roll_nexthump:
    .a16
    lda #VFLOOR
    sta VMAG                    ; resume from the slow creep
    stz SUBPH                   ; rising again
    jsr chamber_draw_peak       ; a NEW random peak for this surge (the variance)
@roll_sign:
    .a16
    ; signed velocity = +VMAG (forward) or -VMAG (reverse, C_DIR=$FFFF)
    lda C_DIR
    beq @roll_fwd
    lda VMAG
    eor #$FFFF
    inc                         ; -VMAG
    bra @roll_vel
@roll_fwd:
    .a16
    lda VMAG
@roll_vel:
    .a16
    sta C_VEL

@apply_posy:
    .a16
    ; sign-extension byte for the 24-bit (16.8) posy += signed 8.8 velocity
    sep #$20
    .a8
    lda C_VEL+1                 ; velocity high byte (carries the sign)
    bpl @posy_possgn
    lda #$FF
    bra @posy_addsgn
@posy_possgn:
    .a8
    lda #$00
@posy_addsgn:
    .a8
    sta C_VSGN
    rep #$20
    .a16
    lda POSYACC                 ; $34-$35 = frac : int.lo
    clc
    adc C_VEL                   ; += vfrac (low) and vint.lo (high), carry chains
    sta POSYACC
    sep #$20
    .a8
    lda POSYACC+2               ; $36 = int.hi
    adc C_VSGN                  ; + sign-extension + carry
    sta POSYACC+2
    rep #$20
    .a16
    lda POSYACC+1               ; integer posy (16-bit @ $35-$36)
    and #MAP_MASK               ; wrap to the 1024px periodic map (both directions)
    sta POSYACC+1

    sf_mode7_cam C_POSX, POSYACC+1, #0   ; angle constant 0 (no rotation)
    sf_mode7_tick               ; cheap origin re-anchor (M7X/M7Y); barrel persists

    ; ---- heartbeat + posy/velocity mirrors (test orchestration only — visual
    ;      assertions stay on rendered pixels) ----
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    lda POSYACC+1
    sta f:$7E0000 + $E014, x    ; integer posy mirror
    lda C_VEL
    sta f:$7E0000 + $E016, x    ; signed-8.8 velocity mirror (the roll rate)

    sf_frame_end
    jmp game_loop

; =============================================================================
; ============================== SUBROUTINES ==================================
; chamber_draw_peak (next surge's random peak) + chamber_new_leg (reset a leg).
; =============================================================================

; =============================================================================
; chamber_draw_peak — HCUR = clamp(PEAK_MIN + (dirRNG & PEAK_RNGMASK), PEAK_CAP),
; stepping the LFSR that belongs to the CURRENT direction. Forward and reverse
; have SEPARATE streams (RNG_F / RNG_R), so each direction evolves its own
; surge-peak variance pattern. 16-bit Galois LFSR, taps $B400.
; WIDTH-RISK: A16/I16 in and out; no width toggles.
; =============================================================================
chamber_draw_peak:
    .a16
    .i16
    lda C_DIR
    bne @dp_rev
    lda RNG_F                   ; forward stream
    lsr
    bcc @dp_f
    eor #$B400
@dp_f:
    .a16
    sta RNG_F
    bra @dp_have
@dp_rev:
    .a16
    lda RNG_R                   ; reverse stream
    lsr
    bcc @dp_r
    eor #$B400
@dp_r:
    .a16
    sta RNG_R
@dp_have:
    .a16
    and #PEAK_RNGMASK
    clc
    adc #PEAK_MIN
    cmp #PEAK_CAP
    bcc @dp_store               ; below the cap -> keep
    lda #PEAK_CAP               ; clamp to the 50%-reduced max
@dp_store:
    .a16
    sta HCUR
    rts

; =============================================================================
; chamber_new_leg — begin a fresh roll leg from a standstill: reset the surge
; counters and draw the first surge's peak (from the current direction's LFSR).
; WIDTH-RISK: A16/I16 in and out.
; =============================================================================
chamber_new_leg:
    .a16
    .i16
    stz HUMP
    stz SUBPH                   ; rising
    stz VMAG                    ; from a dead stop
    stz C_STATE                 ; ROLLING
    jsr chamber_draw_peak
    rts

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order, plus the
; DMA + colour-math engines the macros need.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
.include "palette_engine.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; =============================================================================
; DATA — first-party tables (factual hardware register values; see
; assets/make_chamber_tables.py): the barrel curve + the COLDATA vignette + the
; chamber palette, and below in BANK1, the 32KB Mode 7 chamber-map blob.
; =============================================================================
.segment "RODATA"
.include "assets/chamber_tables.inc"
.include "assets/chamber_palette.inc"

; --- the 32KB interleaved chamber-map blob (bank 1 of the 64KB image) ---
.segment "BANK1"
chamber_map:
    .incbin "assets/chamber_map.bin"
