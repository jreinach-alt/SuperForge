; =============================================================================
; split_v_fight — SEAMLESS distance-driven fighting-game split (sf_split_v rail)
; =============================================================================
; A ground-level two-fighter arena whose camera separates SEAMLESSLY as the
; fighters part and re-merges just as seamlessly as they close — no pop, no
; shift. Built on the seamless-split core proven by templates/split_v_seamtrial:
;
;   * The centre window is ALWAYS on (never toggled, never forced-blanked).
;   * Separation is a CONTINUOUS camera divergence: cam_a = mid - spread,
;     cam_b = mid + spread, where `spread` is EASED from the fighter distance
;     (replacing the old binary MERGED/SPLIT state machine + sf_window_off
;     toggle + NEAR/FAR hysteresis). At spread=0 the two halves are pixel-
;     identical, so the ever-present seam is INVISIBLE.
;   * The divider is a VERTICAL BEVELED bar on BG3 whose band half-width
;     hw = spread>>4 is ZERO at merge (no stolen width) and ramps the band
;     0->3->5 px wide as the fighters part. In-arena hw caps at 2: the fighters
;     clamp to [24,232] so dx maxes at 208 -> spread 40 -> hw 2 (a 5 px band); the
;     SPREAD_MAX=48 that would give hw 3 / a 7 px band needs dx>=224, which the
;     arena walls prevent. Vertical, not diagonal: a diagonal divider encodes the
;     verticality (airborne vs grounded) this ground-only game lacks.
;
; `spread` tracks the "ideal" divergence that keeps each fighter centred in its
; half: spread = clamp((dx - MERGE_DX)/2, 0, SPREAD_MAX), eased at SPR_STEP/frame
; toward that target, where dx = |fighter2 - fighter1|. Below MERGE_DX the target
; is 0 (fully merged, seamless single view). The fighters are OBJ (red left, blue
; right), each tracking its own half's camera.
;
; This is the camera director, not a combat engine: fighters just walk (P1/P2),
; clamped to the arena but FREE TO CROSS — a fighter may walk past the other and
; switch sides, and the seamless split follows the swap (that crossover is the
; showcase, not a guarded-against edge case; see the OBJ placement near the end).
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
; FILE LAYOUT (top to bottom, matching the major ; === banners below):
;   INIT             RESET: stage CHR + shared tilemap, fighters (OBJ), the
;                    seamless bevel divider, camera + demo state.
;   MAIN LOOP        game_loop — the once-per-frame heartbeat. It folds in:
;     INPUT            walk the fighters (P1/P2) or drive the autodemo cross-over
;     PER-FRAME UPDATE dx -> eased spread -> diverge cameras + ramp the divider band
;     DRAW             place the two fighters, each against its half's camera
;   DATA             stage CHR/palette (assets/stage.inc), fighter sprite bitmaps.
;   SUBROUTINES      engine modules (PPU init, input, DMA, sprite, BG) pulled in
;                    by .include at the file end.
;
; FRAME LOOP: `game_loop` is the once-per-frame heartbeat — start reading there.
;
; Build:  make split_v_fight  (default) · build_split_v_fight.sh (-D variants)
; =============================================================================
; LDCFG: lorom_tad.cfg
;   ^ Linker-config sentinel: the TAD-audio link shape (audio data banks for the
;     music + SFX). The generic build/%.sfc rule reads this; a *_tad*.cfg name
;     also links the TAD driver objects + adds the audio include path, so no
;     Makefile edit is needed. (Was lorom_64k.cfg — this rail fits in one bank;
;     the swap is purely to gain the audio banks.)

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SPLIT SCREEN DUEL"
SF_HDR_TITLE_SET = 1
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
.include "tad-audio.inc"        ; TAD driver ca65 API (the vendored audio driver)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids for the shipped song set
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music / sf_sfx
.include "sf_fx.inc"            ; sf_bright_fade / sf_bright_fade_tick (boot fade-in)

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
T_MX    = $58                   ; tilemap-fill cursor: column being written (0..31)
T_MY    = $5A                   ; tilemap-fill cursor: row being written (0..31)
T_TILE  = $5C                   ; tilemap-fill scratch: the tile index chosen for a cell
XPREV   = $5C                   ; loop-phase reuse of the RESET-only T_TILE slot: the
                                ; previous frame's fighter side-bit (0=red left, 1=crossed),
                                ; for the crossover-clash SFX edge-detect. Safe: $40-$5F is
                                ; this ROM's private DP and T_TILE is untouched after RESET.
FDWELL  = $5E                   ; auto-demo dwell countdown at each extreme

ARENA_MID = 128                 ; arena centre in world px (also the screen centre / seam)
ARENA_LO  = 24                  ; fighter clamp (left wall), world px
ARENA_HI  = 232                 ; fighter clamp (right wall), world px
WALK_SPD  = 2                   ; fighter walk speed, px/frame (see SPR_STEP coupling below)

SPREAD_MAX = 48                 ; full camera divergence, px (matches split_v_seamtrial)
MERGE_DX   = 128                ; dx (px) below which spread targets 0 (fully merged)
SPR_STEP   = $00C0              ; 0.75 px/frame spread ease (8.8) -> smooth divergence.
                                ; COUPLED to WALK_SPD: the target moves at ~WALK_SPD/frame
                                ; (dx changes 2*WALK_SPD as both walk), so SPR_STEP must be
                                ; >= ~WALK_SPD or the divider visibly lags the fighters;
                                ; raise it if you speed the fighters up.
FADE_FRAMES = 16                ; boot fade-in length (~0.27 s). NON-GATING: it finishes
                                ; long before any test samples pixels (autodemo's first
                                ; grab is ~frame 44, the static builds ~frame 134), so the
                                ; brightness ramp never dims a frame under assertion. A
                                ; title card WOULD strand those grabs, hence a fade instead.
DWELL      = 72                 ; auto-demo hold (~1.2 s) at each wall so the fully split
                                ; (swapped / unswapped) state settles + is visible in real time

FLOOR_ROW = 22                  ; tilemap row (of 32) of the grass surface — px 176.
                                ; The fighters' feet rest on it (see KNIGHT_Y).
KNIGHT_Y    = 148               ; OBJ Y of the 32x32 knight so its feet (content
                                ; row 28) rest on the grass surface at px 176
KNIGHT_HALF = 16                ; half the 32px OBJ box — the sprite is CENTRED on
                                ; the fighter's world X (FX), so it never wraps at
                                ; the right wall and frames each half symmetrically
; fighter OAM flags: bit7 = 32x32 (OBSEL pair 3), bit6 = H-flip (face the centre),
; bits3:1 = OBJ palette (0 = red team, 1 = blue team)
FL_RED_L  = $80                 ; red on the LEFT half  — faces right (no flip), pal 0
FL_RED_R  = $C0                 ; red on the RIGHT half — faces left (H-flip),  pal 0
FL_BLU_L  = $82                 ; blue on the LEFT half  — faces right,          pal 1
FL_BLU_R  = $C2                 ; blue on the RIGHT half — faces left (H-flip),  pal 1

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

; =============================================================================
; INIT — one-time setup at RESET: stage graphics, fighters, the bevel divider,
;        and the camera/demo state. Runs once; PPU/VRAM writes are safe because
;        the engine boots under forced blank until gfxmode turns the screen on.
; =============================================================================
RESET:
    sf_coldstart
    sf_engine_init
    sf_audio_init               ; boot the S-SMP + TAD driver ONCE (async loader handshake)

    ; --- stage graphics (Four Seasons grass/dirt) -> BG1 CHR (tiles 0..8) ---
    ; tile 0 is the pack's blank (transparent) -> the sky rows reveal the CGRAM-0
    ; backdrop; tiles 1-8 are the grass-topped-dirt column (see assets/stage.inc).
    sf_load_bg_chr 0, stage_chr, stage_chr_bytes

    ; --- fighters: ONE camelot knight (assets/knight.inc, 32x32) drawn twice with
    ;     a P1/P2 OBJ-palette swap for team identity. Both team palettes are
    ;     authored BAND-SAFE (no white, no dark-neutral grey), so a fighter
    ;     crossing the centre divider probe band never trips the S2/S4/S7 bevel
    ;     colour checks (the knight's native palette is dark-neutral — unused). ---
    sf_load_obj_chr 0, knight_chr, knight_chr_bytes
    sf_load_obj_pal 0, knight_red_pal    ; OBJ palette 0 = red team (fighter 1)
    sf_load_obj_pal 1, knight_blue_pal   ; OBJ palette 1 = blue team (fighter 2)
.ifdef UNSAFE_TEAM
    ; NON-VACUITY PROOF build: paint the red team's dominant tone WHITE. At the
    ; crossing the fighters sit in the centre probe band, so this must FAIL the
    ; seamless-merge probe (S7 min-core-when-close, S4 min-shadow near merge) —
    ; proving those probes stay live against a fighter in the band.
    sf_obj_color 0, 1, $7FFF             ; white on OBJ pal 0 slot 1 (65 px of the knight)
.endif

    ; --- stage palette. CGRAM 0 = the sky backdrop (revealed through the
    ;     transparent sky tiles); 1..7 = the Four Seasons stage colours, mirroring
    ;     assets/stage.inc's stage_pal[1..7]. CGRAM 8-11 is the BG3 bevel palette
    ;     and is DELIBERATELY not written here. idx1 is a band-safety recolour:
    ;     the pack's outline is $14A6 = a dark NEUTRAL grey that would read as the
    ;     divider's shadow tone to the S2 bevel probe; $0CA9 is the same value
    ;     warmed off-neutral (|R-G| >= 24), visually a dark-brown outline. ---
.ifdef UNSAFE_STAGE
    ; NON-VACUITY PROOF build (not shipped in a variant): the naive reskin that
    ; ignores divider-band safety — a WHITE sky backdrop and the pack's dark-
    ; NEUTRAL outline. Both intrude into the S2/S4/S7 centre-band probes, so this
    ; build must FAIL the merge asserts (_bar_core(merge)==0, _bar_shadow(merge)==0).
    sf_bg_color 0, 0, $7FFF     ; white sky -> trips the highlight-core probe at merge
    sf_bg_color 0, 1, $14A6     ; the pack's dark-neutral outline -> trips the shadow probe
.else
    sf_bg_color 0, 0, $6E64     ; sky-blue backdrop (not white, not neutral)
    sf_bg_color 0, 1, $0CA9     ; outline (band-safe recolour of the pack's $14A6)
.endif
    sf_bg_color 0, 2, $1D0E     ; dirt shadow
    sf_bg_color 0, 3, $1DE3     ; grass dark
    sf_bg_color 0, 4, $21D7     ; dirt mid
    sf_bg_color 0, 5, $1B0B     ; grass bright
    sf_bg_color 0, 6, $329B     ; dirt light
    sf_bg_color 0, 7, $2373     ; grass light

    jsr init_ppu
    gfxmode #1
    ; shared-CHR override (+ OBJ size) under a brief forced blank: point BG2 at
    ; BG1's tilemap ($5800) + CHR ($2000) so both halves render the SAME stage from
    ; one copy (the split is purely camera scroll), and set OBSEL to the 32x32 pair
    ; for the knight fighters (OBSEL is a forced-blank-only write).
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; INIDISP: forced blank so OBSEL can change safely
    lda #$58
    sta $2108                   ; BG2SC (BG2 tilemap base/size): map at VRAM word $5800
    lda #$22
    sta $210B                   ; BG12NBA (BG1/BG2 CHR base): BG2 CHR at $2000 (shares BG1's)
    lda #$60
    sta $2101                   ; OBSEL: OBJ size pair 3 (small 16x16 / large 32x32)
    lda #$0F
    sta $2100                   ; INIDISP: end forced blank (full brightness)
    rep #$30
    .a16
    .i16

    ; --- fill BG1 tilemap once (shared by both cameras): a flat grass-topped
    ;     dirt floor under an open sky. Rows above FLOOR_ROW are the transparent
    ;     tile 0 (the CGRAM-0 sky backdrop shows through); FLOOR_ROW is the grass
    ;     surface, +1 the subsoil, deeper rows the dirt body. Column parity picks
    ;     the left/right half of each 16px source block (even col = left tile). ---
    stz T_MY
@row:
    .a16
    .i16
    stz T_MX
@col:
    .a16
    .i16
    lda T_MY
    cmp #FLOOR_ROW
    bcc @sky                    ; above the floor -> transparent sky (tile 0)
    beq @grass                  ; the grass surface -> tiles 1/2
    cmp #(FLOOR_ROW+1)
    beq @subsoil                ; just below the grass -> tiles 3/4
    lda #7                      ; deeper -> the dirt body (tiles 7/8)
    bra @parity
@sky:
    .a16
    .i16
    stz T_TILE
    bra @settile
@grass:
    .a16
    .i16
    lda #1
    bra @parity
@subsoil:
    .a16
    .i16
    lda #3
@parity:
    .a16
    .i16
    ; A = the block's left tile; odd columns take the right half (base+1).
    sta T_TILE
    lda T_MX
    and #$0001
    clc
    adc T_TILE
    sta T_TILE
@settile:
    .a16
    .i16
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
    stz XPREV                       ; fighters start uncrossed (FX1 left) -> side-bit 0
    lda #ARENA_MID
    sta CAMA
    sta CAMB

    ; --- start the arena music (async: it streams over the sf_audio_ticks below) ---
    sf_music #Song::chords

    ; --- boot fade-in: cut to black, then ramp to full brightness over FADE_FRAMES
    ;     (INIDISP only — no DMA, so it can't disturb the split's per-frame tilemap
    ;     commit). Non-gating: it finishes before any test grabs a frame. ---
    sf_bright_fade #0, #0           ; cut to black
    sf_bright_fade #15, #FADE_FRAMES ; ramp up to full over ~0.27 s

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                       ; NMITIMEN: enable VBlank NMI (bit7) + auto-joypad read
                                    ; (bit0) — the frame interrupt now drives game_loop
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: the once-per-frame heartbeat. sf_frame_begin waits for
;   VBlank + latches input; the body reads input, updates the spread/cameras, and
;   draws the fighters; sf_frame_end commits the frame. Start reading HERE.
; =============================================================================
game_loop:
    sf_frame_begin
    sf_audio_tick               ; pump TAD every frame (streams the song load + SFX queue)
    sf_bright_fade_tick         ; step the boot fade-in (idle once it reaches full)

    ; =========================================================================
    ; INPUT — move the fighters this frame: read the two controllers (default),
    ;   run the scripted cross-over (AUTODEMO), or hold them frozen (HOLD).
    ; =========================================================================
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
    ; Independent bounds also make an off-arena escape impossible by construction:
    ; neither fighter can be chased off the floor, because neither is clamped RELATIVE
    ; to the other (a relative clamp lets the chaser drag the bounded fighter past a
    ; wall — here the two clamps are decoupled, so each simply stops at its own wall). ---
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

    ; =========================================================================
    ; PER-FRAME UPDATE — turn the two fighter positions into the split geometry:
    ;   dx = |FX2-FX1| -> target spread -> eased spread -> diverge the two cameras
    ;   and ramp the divider band (sf_split_v_spread). This is the camera director.
    ; =========================================================================
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
    ; NOTE: the band half-width is hw = spread>>4, so for spread 1..15 the cameras
    ; ALREADY diverge (up to +-15 px) while hw is still 0 -> an EMPTY divider band.
    ; The seam is then a bare content step of up to 2*15=30 px at centre with no bar
    ; to mask it; the bevel only appears once spread reaches 16 (hw 1). It's
    ; invisible in this flat art but would read as a pop on detailed stages — start
    ; the band earlier (bias hw, or floor spread at 16 before it engages) if it bites.
    sf_split_v_spread MID, SPREAD, CAMA, CAMB

    ; --- crossover clash: fire a hit SFX the frame the two fighters SWAP order
    ;     (they pass THROUGH each other at centre). Cheap edge-detect — the current
    ;     side-bit (0 = red left, 1 = crossed) vs XPREV — no combat state, just a
    ;     compare; the whole cost is a handful of cycles per frame. ---
    lda FX1
    cmp FX2                     ; C=1 iff FX1 >= FX2 (red now on the right -> crossed)
    lda #0
    rol a                      ; A = side-bit (carry -> bit 0): 0 uncrossed, 1 crossed
    cmp XPREV
    beq @no_swap               ; side unchanged -> no clash this frame
    sta XPREV                  ; latch the new side BEFORE the SFX (sf_sfx clobbers A)
    sf_sfx #SFX::player_hurt    ; the clash as the two fighters cross over
@no_swap:
    .a16
    .i16

    ; =========================================================================
    ; DRAW — place the two fighters as OBJ, each against its half's camera so a
    ;   side-swap is handled by re-picking which fighter goes with which camera.
    ; =========================================================================
    ; --- draw the two fighters (one 32x32 knight each), assigning each to the half
    ;     it is CURRENTLY on so a SIDE-SWAP is handled: cam_a frames the left half,
    ;     cam_b the right, so the LEFTMOST fighter (by world X) is drawn against CAMA
    ;     and the rightmost against CAMB — each keeping its team palette (red = pal 0,
    ;     blue = pal 1) and FACING the centre (the inner fighter H-flips). When the
    ;     two cross, red moves into the right half and blue into the left, and because
    ;     dx->0 at the crossing (spread=0, merged) the swap is seamless. The 32px box
    ;     is CENTRED on the fighter's world X (SX = FX - cam - KNIGHT_HALF), so it
    ;     stays within [0,255] at both walls — no OAM X9 handling is needed. ---
    spr_clear
    lda FX1
    cmp FX2
    bcc @red_left               ; FX1 < FX2 -> red is the LEFT fighter (block just below)
    beq @red_left               ; equal -> red on the left (arbitrary, they coincide)
    jmp @blue_left              ; FX1 > FX2 -> CROSSED: blue left, red right (jmp: too far to branch)
@red_left:
    .a16
    .i16
    lda FX1                     ; left half: red against CAMA, facing right
    sec
    sbc CAMA
    sec
    sbc #KNIGHT_HALF
    and #$00FF
    sta SX
    spr #knight_f0, SX, #KNIGHT_Y, #FL_RED_L, #2
    lda FX2                     ; right half: blue against CAMB, facing left
    sec
    sbc CAMB
    sec
    sbc #KNIGHT_HALF
    and #$00FF
    sta SX
    spr #knight_f0, SX, #KNIGHT_Y, #FL_BLU_R, #2
    jmp @fighters_drawn         ; skip the crossed block (jmp: past the swapped pair)
@blue_left:
    .a16
    .i16
    lda FX2                     ; left half: blue against CAMA, facing right
    sec
    sbc CAMA
    sec
    sbc #KNIGHT_HALF
    and #$00FF
    sta SX
    spr #knight_f0, SX, #KNIGHT_Y, #FL_BLU_L, #2
    lda FX1                     ; right half: red against CAMB, facing left
    sec
    sbc CAMB
    sec
    sbc #KNIGHT_HALF
    and #$00FF
    sta SX
    spr #knight_f0, SX, #KNIGHT_Y, #FL_RED_R, #2
@fighters_drawn:
    .a16
    .i16

    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — stage graphics, fighter sprite + team palettes (all baked into ROM).
; =============================================================================
; Stage CHR + palette + map constants: a grass-topped-dirt column converted from
; the Four Seasons Platformer Tileset via tools/png2snes.py (provenance + the
; band-safety recolour note are in the .inc header). Only stage_chr + the
; stage_pal words are used here; the flat-floor tilemap is built by the fill loop
; in RESET, not from stage_map.
.include "stage.inc"

; Fighter CHR: one 32x32 camelot knight (Arthur), band-agnostic on OBJ VRAM.
.include "knight.inc"

; The two TEAM palettes — a P1/P2 OBJ-palette swap over the shared knight CHR.
; They are authored (not from the pack): each maps the knight's shading to a red
; or blue ramp and is BAND-SAFE by construction — no colour reaches white
; (all channels > 230) or dark-neutral grey (all < 90 AND near-neutral), so a
; fighter overlapping the centre divider probe band never trips the S2/S4/S7
; bevel colour checks. The "team" tone (idx1/3/4, the dominant body area) is a
; strong red / blue (R or B > 150, other two < 80) for reliable side detection;
; the crown (5/6) stays gold and the face (7) stays skin on both teams.
knight_red_pal:                 ; OBJ palette 0 — red team (fighter 1)
    .word $0000, $14B4, $14EC, $18D9, $211C, $1E9C, $331E, $4ADD
    .word $675E, $0000, $0000, $0000, $0000, $0000, $0000, $0000
knight_blue_pal:                ; OBJ palette 1 — blue team (fighter 2)
    .word $0000, $50A5, $30E5, $64C6, $7108, $1E9C, $331E, $4ADD
    .word $7B59, $0000, $0000, $0000, $0000, $0000, $0000, $0000

; =============================================================================
; SUBROUTINES — engine modules (PPU init, input, DMA, sprite, BG, audio bridge)
;   pulled in here. tad_bridge.asm defines the tad_* entry points sf_audio.inc
;   calls; the TAD driver + song blob are linked as separate objects (see the
;   LDCFG sentinel + build_split_v_fight.sh).
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "tad_bridge.asm"
.include "bright_fade_engine.asm"   ; engine_bright_fade stepper for the boot fade-in
