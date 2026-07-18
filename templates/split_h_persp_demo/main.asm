; =============================================================================
; split_h_persp_demo — Archetype C-horiz PERSPECTIVE: two stacked per-scanline
;                      Mode-7 CAMERA bands, BOTH ANIMATING INDEPENDENTLY
; =============================================================================
; The perspective sibling of split_h_matrix_demo (which holds a CONSTANT matrix
; per band). This rail renders TWO genuinely-different PERSPECTIVE views of ONE
; flat top-down Mode-7 world, stacked at a clean single-scanline seam, each band
; a full per-scanline REPEAT-mode trapezoid — the 2-player top/bottom racer
; pattern (two live cameras over one shared world). BOTH bands animate on their
; own driver:
;
;   TOP band    (lines PV_L0..SEAM-1): camera A — the LIVE engine perspective
;               renderer (sf_mode7_perspective / sf_mode7_tick). It AUTO-ROTATES
;               (angle drifts every frame) so the top floor visibly spins.
;   BOTTOM band (lines SEAM..PV_L1):   camera B — a SECOND perspective camera.
;               It ZOOM-LOOPS through KPOSES precomputed near-scale (S1) poses,
;               spliced over band-2 every frame. A DIFFERENT far-scale + a
;               looping near-scale -> a MEASURABLY different, MOVING on-screen
;               texel period. SAME map, CHR, CGRAM; both cameras share the
;               low-32KB Mode-7 VRAM (word $0000): NO extra VRAM.
;
; -----------------------------------------------------------------------------
; WHY CAMERA B IS PRECOMPUTED (the budget + double-buffer decision) ------------
; The engine per-scanline matrix HDMA table is DOUBLE-BUFFERED; pv_rebuild FLIPS
; it every rebuild (mode7_hdma.asm, "Step 1 — flip the double buffer"), then
; emits camera A into the now-active buffer. A camera's WORLD POSITION feeds the
; GLOBAL M7X/M7Y origin (pv_set_origin), NOT the per-scanline matrix, so a splice
; can only make band-2 a distinct camera by SCALE and ANGLE. Making camera B a
; LIVE second solve would need a SECOND full pv_rebuild per frame (~2x the ~10k-
; cycle solve — the docs put one pv_rebuild at ~1/3 of the 28-37k frame budget),
; AND a second pv_rebuild flips the buffer a second time, so both bands would end
; up written into the SAME physical buffer HDMA is displaying THIS frame -> a torn
; back-buffer. So camera B is animated via PRECOMPUTED per-pose band-2 tables
; (the spec's documented substitute for the vendor's serial math coprocessor
; used by stock racing carts): K poses
; are solved ONCE at boot (under forced blank, no frame budget) into WRAM, and the
; per-frame apply-hook splices the CURRENT pose's band-2 into the ACTIVE buffer.
;
; THE APPLY-HOOK RULE (this is the flicker fix — READ THIS) --------------------
; The splice MUST target the ACTIVE buffer: pv_hdma_ab0/cd0 + pv_buffer_x, stamped
; every rebuild frame — exactly the mode7_barrel_apply pattern. mode7_band_splice
; (engine) consults pv_buffer and re-applies into the freshly-flipped active buffer
; every frame, so both bands stay coherent even though pv_rebuild double-flips.
; An EARLIER implementation spliced band-2 into a FIXED buffer from the main loop:
; on the ~30 Hz of frames where pv_rebuild had flipped to the OTHER buffer, band-2
; reverted to camera A -> a 30 Hz flicker. A single settled-frame test is BLIND to
; that alternation (it lands on whichever phase the frame count hits). The
; -DFIXED_BUFFER_SPLICE control below reinstates that bug; the temporal-stability
; test (12 consecutive deterministic frames) is what catches it.
;
; ValueLatch GUARD — satisfied BY CONSTRUCTION and PROVEN load-bearing by
;   -DLATCH_VIOLATION: all code-side write-twice pairs to shared-latch regs
;   (M7X/Y, M7HOFS/VOFS == BG1HOFS/VOFS, M7SEL) happen ONLY in VBlank/forced blank.
;   During active display ONLY the CH5/CH6 matrix HDMA runs.
;
; COMPILE-TIME SWITCHES (the generic make rule can't pass -D; the variant script
; passes them — see build_split_h_persp_variants.sh):
;   -DNO_SEAM=1              P4 non-vacuity: skip the band-2 splice -> BOTH bands
;                           show camera A -> the "two bands differ" assertion FAILS.
;   -DLATCH_VIOLATION=1      P5 negative control: a code-side write-twice to a
;                           shared-latch register during active display -> tear.
;   -DFREEZE=1               freeze camera A (angle held at 0): a deterministic
;                           still TOP band. Camera B keeps zoom-looping (it is the
;                           independent second camera) unless -DHOLD_B is also set.
;   -DHOLD_B=1               freeze camera B at pose 0 (deterministic still BOTTOM
;                           band). Camera A keeps auto-rotating unless -DFREEZE.
;   -DFIXED_BUFFER_SPLICE=1  reinstate the BUGGY fixed-buffer splice (buffer 0
;                           always, ignoring pv_buffer) -> the 30 Hz flicker
;                           returns. Combined with -DFREEZE -DHOLD_B this is the
;                           P3 temporal-stability NEGATIVE control.
;
; Build:  make split_h_persp_demo
;         bash templates/split_h_persp_demo/build_split_h_persp_variants.sh
; LDCFG: lorom_64k.cfg  (64KB image; the 32KB Mode-7 checker-map fills BANK1.)
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_mode7.inc"         ; the Mode 7 perspective macro group
.include "sf_split_h.inc"       ; sf_split_h_persp_capture / _splice
.include "engine_state.inc"

; --- band geometry -----------------------------------------------------------
SEAM       = 112                ; seam scanline; top [PV_L0..SEAM), bottom [SEAM..PV_L1)
PV_L0      = 0                  ; perspective horizon at the top edge — camera A's
                                ; floor recedes cleanly to row 0 (no frozen above-
                                ; horizon "head": rows above PV_L0 render the floor
                                ; matrix FROZEN at the horizon value = a flat face-on
                                ; strip). BAND2_OFF=(SEAM-PV_L0)*4 auto-updates to
                                ; SEAM*4 so camera B still lands exactly at SEAM.
PV_L1      = 224
FOCUS_Y    = 168

; --- HORIZON KNOB (ITEM B) ---------------------------------------------------
; Two horizon behaviours, selected at build time:
;   DEFAULT (floor-to-edge): PV_L0 = 0 — camera A's floor recedes cleanly to the
;     top screen edge (row 0). No sky; the Mode-7 plane fills every scanline.
;   -DSKY_HORIZON: a TM ($212C) HDMA band turns the Mode-7 floor (BG1) OFF for the
;     first SKY_H scanlines so the CGRAM[0] backdrop shows through as a SKY band
;     above the horizon (the racer's arm_sky_split technique). The floor begins at
;     scanline SKY_H. The TM table is $00/$01 — OBJ stays OFF in both bands (this
;     demo initialises no OAM; see arm_sky_split). This changes ONLY the top band's
;     appearance (a backdrop-coloured sky strip); the perspective solve, the seam,
;     and camera B are unchanged. SKY_H (48) stays below the camera-A sample rows
;     (TOP_ROWS 60..100) so the two-camera signal is intact under the sky.
.ifdef SKY_HORIZON
SKY_H      = 48                 ; sky band = lines 0..SKY_H-1 (backdrop); floor SKY_H..
FX_SKY     = $00C3              ; sky-split allocator effect tag (distinct from $00C2)
.endif

BAND2_ROWS  = PV_L1 - SEAM              ; 112 bottom-band scanlines
BAND2_BYTES = BAND2_ROWS * 4            ; 4 bytes/scanline in the final buffer
BAND2_OFF   = (SEAM - PV_L0) * 4        ; band-2 byte offset within the AB/CD buffer

; --- camera A perspective params (the LIVE, auto-rotating top-band renderer) --
A_S0       = 320
A_S1       = 96
A_SH       = 512
; camera A LIVE interpolation resolution (the SHIPPED optimization). interp4 =
; quarter-scanline res: pv_rebuild solves the full per-scanline matrix every 4th
; scanline and interpolates the 3 between. MEASURED on the free-running cycles ROM
; (tests/persp_cycles_test.asm): a full-floor (0..224) solve is ~492k mc = ~138%
; of one 60fps CPU frame at interp1, ~309k mc = ~87% at interp4 (HDMA off; ~93%
; with the rail's CH5|CH6 per-scanline REPEAT HDMA stealing cycles). interp2
; (~104%) does not fit; the rail SHIPS interp4 — the SOLVE fits one frame.
; CADENCE (honest, per the PR #223 independent review, finding M1): the
; INTEGRATED demo loop = solve + the band-2 matrix splice (~85k mc = ~24% of a
; frame) + the origin restamp, totalling ~110-120% — and the sf_frame handshake
; quantizes ANY overrun to a whole extra frame, so the game loop closes every
; 2nd frame = 30 Hz pose MOTION (interp1 was also 30 Hz by the same
; quantization, not the ~43fps an earlier draft claimed). The DISPLAY holds
; 60 fps regardless: HDMA re-streams the committed double buffer every frame.
; In-situ loop-rate gate: test_split_h_persp_demo.py::
; test_cadence_true_60fps_in_situ (xfail at HEAD; goes loudly XPASS when the
; band-1-only rebuild follow-up lands). Solve-budget gate: test_persp_cycles.py::
; test_rail_solve_fits_one_frame. Build -DA_INTERP=1 for the interp1 comparison ROM.
.ifndef A_INTERP
A_INTERP   = 4
.endif
A_WRAP     = 1
A_POSX     = 512
A_POSY     = 512

; --- camera B perspective params (a DISTINCT far-scale + a zoom-looping near-
;     scale S1). Same map/CHR/CGRAM. ------------------------------------------
B_S0       = 512
B_SH       = 512
B_INTERP   = 1
B_WRAP     = 1
; camera B WORLD POSITION (the NEW axis). At angle 0 the perspective origin
; solve gives M7X == posx exactly, so posx == the sampled world column. Camera A
; sits at world X 512 (world tile 64 = the COOL/blue stripe centre); camera B is
; panned +256 world px to world X 768 (world tile 96 = the WARM/red stripe centre)
; so band-2 samples a DIFFERENT, red-coloured world region — an independent world
; position, framebuffer-visible in the RED channel (orthogonal to the checker
; period signal). -DSAME_CENTER folds camera B's centre back onto camera A's.
B_POSX     = 768
B_POSY     = 512

; camera B zoom loop: KPOSES near-scale (S1) poses. Bigger S1 -> ground recedes
; more -> tighter on-screen texel period. The loop steps S1 across these values
; so band-2 visibly "dollies" (its texel period changes) frame group to group.
KPOSES     = 8
POSE_STRIDE = BAND2_BYTES * 2           ; one pose = its AB table then its CD table

; --- CGRAM colours (15-bit BGR %0bbbbbgggggrrrrr) ----------------------------
; idx0 backdrop; idx1/2 = COOL checker (blue/green, red channel ~0 — the original
; period-signal colours); idx3/4 = WARM checker (pure RED shades, blue+green ~0
; so they read 0 in the green+blue luminance signature but light up the RED
; channel — the orthogonal WORLD-POSITION signal the camera-pos tests read).
; The WARM shades are the COOL shades + a RED tint, so the green+blue luminance
; (checker/period) signature is IDENTICAL in both stripes — every pre-existing
; test reads the same G+B pattern regardless of which stripe a camera views — and
; the ONLY difference is the red channel (the orthogonal world-position signal):
;   cool dark  $0140 (0,80,0)      warm dark  $014A (80,80,0)     [+red]
;   cool light $7FE0 (0,248,248)   warm light $7FFF (248,248,248) [+red]
; mean red: cool stripe ~0, warm stripe ~164 -> a large, position-only margin.
COLOR_BACKDROP  = $5400
COLOR_DARK      = $0140         ; idx1 cool dark  (green,      R=0)
COLOR_LIGHT     = $7FE0         ; idx2 cool light (cyan-white, R=0)
COLOR_WARM_DARK = $014A         ; idx3 warm dark  (= dark + red,  R~80)
COLOR_WARM_LIGHT= $7FFF         ; idx4 warm light (= light + red, R~248 / white)

; --- WRAM precomputed camera-B pose tables -----------------------------------
; KPOSES * (AB 448 B + CD 448 B) at $7E:C000 (free WRAM: engine heap ends by
; $B0FF, the debug region starts at $E000; $C000-$DFFF is 8 KB free). K=8 uses
; $C000..$DC00.
CAMB_BASE  = $7EC000

CAMB_AB0 = CAMB_BASE + 0 * POSE_STRIDE
CAMB_CD0 = CAMB_AB0 + BAND2_BYTES
CAMB_AB1 = CAMB_BASE + 1 * POSE_STRIDE
CAMB_CD1 = CAMB_AB1 + BAND2_BYTES
CAMB_AB2 = CAMB_BASE + 2 * POSE_STRIDE
CAMB_CD2 = CAMB_AB2 + BAND2_BYTES
CAMB_AB3 = CAMB_BASE + 3 * POSE_STRIDE
CAMB_CD3 = CAMB_AB3 + BAND2_BYTES
CAMB_AB4 = CAMB_BASE + 4 * POSE_STRIDE
CAMB_CD4 = CAMB_AB4 + BAND2_BYTES
CAMB_AB5 = CAMB_BASE + 5 * POSE_STRIDE
CAMB_CD5 = CAMB_AB5 + BAND2_BYTES
CAMB_AB6 = CAMB_BASE + 6 * POSE_STRIDE
CAMB_CD6 = CAMB_AB6 + BAND2_BYTES
CAMB_AB7 = CAMB_BASE + 7 * POSE_STRIDE
CAMB_CD7 = CAMB_AB7 + BAND2_BYTES

; --- camera-B independent-position state (poses end at $DC00; $DC00+ is free) --
; CENTER_TABLE: the CH2 per-band M7X/M7Y HDMA table (DMAP $03 = write-2-regs-twice
; into $211F/$2120). NON-REPEAT 2-band shape, band-1 = camera A's LIVE centre
; (restamped every frame from the engine's computed M7X/M7Y so it tracks camera A's
; rotation), band-2 = camera B's captured centre (a DIFFERENT world position):
;   .byte SEAM              ; band-1: lines 0..SEAM-1 hold camera A's centre
;   .word Xa, Ya           ; M7X=Xa, M7Y=Ya   (Xa low,hi then Ya low,hi = 4 bytes)
;   .byte 1                ; the seam line writes camera B's centre …
;   .word Xb, Yb           ; … and the $00 terminator HOLDS it for band-2
;   .byte 0
; A genuine world pan needs the full Mode-7 ORIGIN moved per band: BOTH the
; centre (M7X/M7Y $211F/$2120) AND the scroll (M7HOFS/M7VOFS $210D/$210E). The
; engine origin solve (pv_set_origin) always sets them together — scroll =
; centre - screen-half — and they cancel in the matrix term, leaving a rigid
; world translation. Splicing ONLY the centre shifts the sampled texel by just
; (1 - M7A)·Δ per scanline (≈0 in the near band) — framebuffer-proven insufficient
; in the cold-start trial. So the capability is TWO 1-channel splices:
;   CH2  M7X/M7Y   ($211F, DMAP $03 -> M7X + M7Y)   the rotation/scale centre
;   CH3  M7HOFS/M7VOFS ($210D, DMAP $03 -> HOFS + VOFS)  the world scroll
; CH2/CH3 are the channels the perspective renderer never enables/owns (pv_rebuild
; owns CH5/CH6, mask $60; CH0/CH1 are allocator-reserved).
CAMB_CENTER_TABLE = $7EDC00     ; 11 bytes: the CH2 M7X/M7Y band table (WRAM)
CT_XA  = CAMB_CENTER_TABLE + 1  ; band-1 M7X word slot (restamped per frame)
CT_YA  = CAMB_CENTER_TABLE + 3  ; band-1 M7Y word slot
CT_XB  = CAMB_CENTER_TABLE + 6  ; band-2 M7X word slot (camera B, set once)
CT_YB  = CAMB_CENTER_TABLE + 8  ; band-2 M7Y word slot
CAMB_SCROLL_TABLE = $7EDC20     ; 11 bytes: the CH3 M7HOFS/M7VOFS band table
CS_HA  = CAMB_SCROLL_TABLE + 1  ; band-1 M7HOFS word slot (restamped per frame)
CS_VA  = CAMB_SCROLL_TABLE + 3  ; band-1 M7VOFS word slot
CS_HB  = CAMB_SCROLL_TABLE + 6  ; band-2 M7HOFS word slot (camera B, set once)
CS_VB  = CAMB_SCROLL_TABLE + 8  ; band-2 M7VOFS word slot
CAMB_M7X  = $7EDC10             ; word: camera B's captured M7X (world pos anchor)
CAMB_M7Y  = $7EDC12             ; word: camera B's captured M7Y
CAMB_HOFS = $7EDC14             ; word: camera B's captured M7HOFS (= M7X - 128)
CAMB_VOFS = $7EDC16             ; word: camera B's captured M7VOFS (= M7Y - L1)
SKY_TABLE = $7EDC30             ; 5 bytes: the -DSKY_HORIZON TM ($212C) band table

; --- game DP scratch ($3A-$3B is documented-free in engine_state.inc) ---------
G_ANGLE    = $3A                ; word: camera A angle (low byte 0..255)

; -----------------------------------------------------------------------------
; capture_pose s1_val, ab_addr, cd_addr — set camera B near-scale S1, rebuild
; (fills the active buffer with camera B pose), then capture band-2 [SEAM..L1)
; into the pose's WRAM tables. Boot-only (forced blank). Entry/exit A16/I16.
; -----------------------------------------------------------------------------
.macro capture_pose s1_val, ab_addr, cd_addr
    sf_mode7_scale #B_S0, #s1_val
    sf_mode7_tick
    sf_split_h_persp_capture SEAM, ab_addr, cd_addr
.endmacro

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y VBlank commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- upload the interleaved Mode-7 checker map to VRAM word $0000 ---
    sf_mode7_load_map checker_map, #$8000

    ; --- CGRAM: backdrop + the two checker colours (under forced blank) ---
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    lda #<COLOR_BACKDROP
    sta $2122
    lda #>COLOR_BACKDROP
    sta $2122
    lda #<COLOR_DARK
    sta $2122
    lda #>COLOR_DARK
    sta $2122
    lda #<COLOR_LIGHT
    sta $2122
    lda #>COLOR_LIGHT
    sta $2122
    lda #<COLOR_WARM_DARK
    sta $2122
    lda #>COLOR_WARM_DARK
    sta $2122
    lda #<COLOR_WARM_LIGHT
    sta $2122
    lda #>COLOR_WARM_LIGHT
    sta $2122
    rep #$30
    .a16
    .i16

    ; --- Mode 7 on + perspective + focus ---
    sf_mode7_on
    sf_mode7_flags #$00

    ; =========================================================================
    ; STEP 1 — precompute camera B's KPOSES band-2 poses into WRAM (ONCE, under
    ; forced blank). For each pose k: set near-scale S1_k, tick (pv_rebuild fills
    ; the active buffer with camera B pose k across the whole floor), then capture
    ; band-2 [SEAM..L1) AB+CD into that pose's WRAM tables. NO frame budget here.
    ; =========================================================================
    sf_mode7_perspective #PV_L0, #PV_L1, #B_S0, #176, #B_SH, #B_INTERP, #B_WRAP
    sf_mode7_focus #FOCUS_Y
    sf_mode7_cam #B_POSX, #B_POSY, #0

    ; near-scale (S1) poses: pose 0 = 176 is the proven-distinct value the
    ; still-build P1 / seam / clean tests sample; the loop steps up by 24 so the
    ; bottom band visibly "dollies" (tighter texel period) as it advances.
    capture_pose 176, CAMB_AB0, CAMB_CD0

    ; --- capture camera B's WORLD-POSITION origin ONCE, right after its first
    ; tick (capture_pose 176 ran sf_mode7_tick -> mode7_set_origin, since
    ; sf_mode7_cam set the dirty-origin flag). nmi_m7x/m7y + SHADOW_BG1HOFS/VOFS
    ; now hold camera B's centre + scroll; stash for the per-band splice tables.
    ; (Done HERE, not via an extra tick, so the pose-precompute buffer parity is
    ; untouched.) ---
    lda M7_PV_NMI_M7X
    sta f:CAMB_M7X
    lda M7_PV_NMI_M7Y
    sta f:CAMB_M7Y
    lda SHADOW_BG1HOFS              ; camera B's M7HOFS (= M7X - 128)
    sta f:CAMB_HOFS
    lda SHADOW_BG1VOFS              ; camera B's M7VOFS (= M7Y - L1)
    sta f:CAMB_VOFS

    capture_pose 200, CAMB_AB1, CAMB_CD1
    capture_pose 224, CAMB_AB2, CAMB_CD2
    capture_pose 248, CAMB_AB3, CAMB_CD3
    capture_pose 272, CAMB_AB4, CAMB_CD4
    capture_pose 296, CAMB_AB5, CAMB_CD5
    capture_pose 320, CAMB_AB6, CAMB_CD6
    capture_pose 344, CAMB_AB7, CAMB_CD7

    ; =========================================================================
    ; STEP 2 — set camera A as the live renderer. From now on every frame
    ; sf_mode7_tick rebuilds camera A across the WHOLE floor (flipping the double
    ; buffer); the apply-hook then re-splices the current camera-B pose over band-2.
    ; =========================================================================
    sf_mode7_perspective #PV_L0, #PV_L1, #A_S0, #A_S1, #A_SH, #A_INTERP, #A_WRAP
    sf_mode7_focus #FOCUS_Y
    sf_mode7_cam #A_POSX, #A_POSY, #0
    sf_mode7_tick               ; first camera-A table build BEFORE screen-on
.ifndef NO_SEAM
    lda #0                      ; pose 0 for the first displayed frame
    jsr splice_camb_pose
    jsr center_setup            ; build + arm the CH2 M7X/M7Y band centre splice
    jsr center_update           ; band-1 = camera A centre for the first frame
.endif

.ifdef SKY_HORIZON
    jsr arm_sky_split           ; ITEM B: TM band -> sky backdrop above the horizon
.endif

    sf_debug_magic              ; "SFDB" at $7E:E000 (boot proof)

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin              ; wait for NMI; latch input

    ; --- camera A angle: auto-rotate (4 units/frame) unless -DFREEZE ----------
.ifdef FREEZE
    stz G_ANGLE                 ; frozen: angle 0 (deterministic still top band)
.else
    lda FRAME_COUNTER
    asl a
    asl a                       ; 4 units/frame -> full turn every 64 frames
    and #$00FF
    sta G_ANGLE
.endif
    sf_mode7_cam #A_POSX, #A_POSY, G_ANGLE

    ; Force a full rebuild EVERY frame so the double buffer flips every frame and
    ; the splice must re-apply into the freshly-flipped active buffer — the worst
    ; case the temporal-stability test needs to exercise.
    sep #$20
    .a8
    lda #$01
    sta M7_DIRTY_REBUILD
    rep #$20
    .a16
    sf_mode7_tick

.ifndef NO_SEAM
    ; --- camera B pose: zoom-loop (advance every 8 frames) unless -DHOLD_B -----
.ifdef HOLD_B
    lda #0
.else
    lda FRAME_COUNTER
    lsr a
    lsr a
    lsr a                       ; /8 -> pose changes every 8 frames
    and #$0007
.endif
    jsr splice_camb_pose        ; re-apply the current camera-B pose over band-2
    jsr center_update           ; restamp band-1's centre (tracks camera A rotation)
.endif

.ifdef LATCH_VIOLATION
    ; ---------------------------------------------------------------------
    ; P5 NEGATIVE CONTROL: a code-side write-twice to a shared-latch register
    ; DURING ACTIVE DISPLAY, while the per-scanline CH5/CH6 matrix HDMA streams.
    ; WIDTH-RISK: A16 entry; A8 for the write-twice burst; back to A16.
    sep #$20
    .a8
    ldx #$0A00
@latch_spin:
    .a8
    stz $210D                   ; M7HOFS low  (write 1 of 2 — arms the latch)
    stz $210D                   ; M7HOFS high (write 2 of 2)
    stz $210E                   ; M7VOFS low
    stz $210E                   ; M7VOFS high
    dex
    bne @latch_spin
    rep #$20
    .a16
.endif

    ; --- heartbeat mirror ($7E:E010) — SEQUENCING screenshots + liveness ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x

    sf_frame_end
    jmp game_loop

; =============================================================================
; splice_camb_pose — re-apply camera B's pose (A = pose index 0..KPOSES-1) over
; band-2 of the ACTIVE buffer. Marshals the pose's WRAM AB/CD table pointers +
; seam into the engine API block, then either the ACTIVE-buffer engine hook
; (mode7_band_splice — the correct, flicker-free path) or, under
; -DFIXED_BUFFER_SPLICE, the demo-local fixed-buffer splice (the flicker bug).
; WIDTH-RISK: entry A16/I16. A8 only for the API bank + seam bytes. Exits A16/I16.
; Clobbers A, X, Y.
; =============================================================================
splice_camb_pose:
    .a16
    .i16
    and #$0007                  ; mask pose to 0..7 (KPOSES = 8)
    asl a                       ; pose * 2 -> word index into the pointer tables
    tax
    lda a:camb_ab_ptrs, x
    sta API_BLOCK_BASE + 0      ; source AB table low word
    lda a:camb_cd_ptrs, x
    sta API_BLOCK_BASE + 4      ; source CD table low word
    sep #$20
    .a8
    lda #$7E
    sta API_BLOCK_BASE + 2      ; source AB table bank (WRAM $7E)
    sta API_BLOCK_BASE + 6      ; source CD table bank
    lda #SEAM
    sta API_BLOCK_BASE + 8      ; seam scanline (u8)
    rep #$20
    .a16
.ifdef FIXED_BUFFER_SPLICE
    jsr fixed_splice_demo       ; BUGGY: always buffer 0 -> 30 Hz flicker
.else
    jsr mode7_band_splice       ; CORRECT: active buffer (pv_buffer_x) -> stable
.endif
    rts

.ifdef FIXED_BUFFER_SPLICE
; =============================================================================
; fixed_splice_demo — the REINSTATED BUG (P3 negative control). Identical to the
; engine mode7_band_splice EXCEPT the destination is the FIXED buffer 0
; (pv_hdma_ab0/cd0, no pv_buffer_x): it does NOT follow pv_rebuild's double-buffer
; flip. On frames where pv_rebuild flipped to buffer 1, buffer 1's band-2 still
; holds camera A -> the 30 Hz desync flicker. Reuses the engine's tested copy
; loop (splice_copy_band) so the ONLY difference from the correct path is the
; fixed-vs-active destination — i.e. the copy math is not a confound.
; WIDTH-RISK: entry A16/I16; A8 only for the count/bank bytes; exits A16/I16.
; =============================================================================
fixed_splice_demo:
    .a16
    .i16
    ; --- AB pass: src = API AB far ptr -> dst = $7E:pv_hdma_ab0 + BAND2_OFF ---
    sep #$20
    .a8
    lda #BAND2_ROWS
    sta z:pv_temp + 2             ; scanline count consumed by splice_copy_band
    rep #$20
    .a16
    lda API_BLOCK_BASE + 0
    sta z:math_a + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2
    sta z:math_a + 2
    rep #$20
    .a16
    lda #(.loword(pv_hdma_ab0) + BAND2_OFF)
    sta z:math_b + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_b + 2           ; FIXED buffer 0 (no pv_buffer_x) — the bug
    rep #$20
    .a16
    jsr splice_copy_band
    ; --- CD pass ---
    sep #$20
    .a8
    lda #BAND2_ROWS
    sta z:pv_temp + 2
    rep #$20
    .a16
    lda API_BLOCK_BASE + 4
    sta z:math_a + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 6
    sta z:math_a + 2
    rep #$20
    .a16
    lda #(.loword(pv_hdma_cd0) + BAND2_OFF)
    sta z:math_b + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_b + 2
    rep #$20
    .a16
    jsr splice_copy_band
    rts
.endif

; =============================================================================
; center_setup — build the CH2 per-band M7X/M7Y HDMA table + arm CH2 (boot-only).
; =============================================================================
; The band M7X/M7Y CENTRE splice is what gives band-2 an INDEPENDENT WORLD
; POSITION (the matrix splice alone only changes band-2's scale/angle — position
; feeds the GLOBAL M7X/M7Y origin, which both bands otherwise share). CH2/CH3
; are free for the splice: pv_rebuild's HARDWARE channels are CH5/CH6 only
; (M7_OWNED_MASK = $60 — the NMI ownership gate). pv_rebuild also writes CH3
; (BGMODE) / CH4 (TM) / CH7 (COLDATA) SHADOW configs into engine state, but
; those channels are not in M7_OWNED_MASK, so the NMI never commits them to
; hardware and this template's boot-time direct CH2/CH3 programming persists.
; CH0/CH1 are allocator-reserved. DMAP $03 = write-2-registers-twice:
; one channel streams the 4-byte [Xlo,Xhi,Ylo,Yhi] unit into M7X ($211F) + M7Y
; ($2120). The table is NON-REPEAT (bit7=0): the unit is written ONCE per band and
; HELD — 2 HBlank transfers/frame, ~nil budget. The ValueLatch guard holds BY
; CONSTRUCTION: M7X/M7Y are written by CODE only in VBlank (the engine NMI commit)
; / forced blank; the CH2 splice fires only in active display, and every HDMA
; channel transfer is atomic per scanline (complete write-twice pairs), so the
; M7A-D/M7X/Y shared latch is never left half-written across channels.
; WIDTH-RISK: entry A16/I16. Sets DB=$00 for hdma_request/hdma_bind_direct (their
; contract) and restores caller DB. A8 only for the count/bank/DMAP bytes.
; Clobbers A, X, Y.
center_setup:
    .a16
    .i16
    ; --- static shape of BOTH band tables: counts + terminator ---
    sep #$20
    .a8
    lda #SEAM
    sta f:CAMB_CENTER_TABLE + 0     ; band-1 line count (NON-REPEAT, bit7 = 0)
    sta f:CAMB_SCROLL_TABLE + 0
    lda #1
    sta f:CAMB_CENTER_TABLE + 5     ; seam line writes band-2 value (1 line)
    sta f:CAMB_SCROLL_TABLE + 5
    lda #0
    sta f:CAMB_CENTER_TABLE + 10    ; terminator: band-2 value HELD to L1
    sta f:CAMB_SCROLL_TABLE + 10
    rep #$20
    .a16
    ; --- band-2 = camera B's captured origin (centre + scroll), set once ---
    lda f:CAMB_M7X
    sta f:CT_XB
    lda f:CAMB_M7Y
    sta f:CT_YB
    lda f:CAMB_HOFS
    sta f:CS_HB
    lda f:CAMB_VOFS
    sta f:CS_VB
    ; --- arm CH2 (M7X/M7Y) + CH3 (M7HOFS/M7VOFS) via the allocator; DB=$00 ---
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb                             ; DB = $00 (hdma_request/bind contract)
    rep #$30
    .a16
    .i16
    lda #$0002                      ; request 2 channels (CH2 + CH3)
    ldx #$00C2                      ; effect tag (arbitrary, distinct)
    jsr hdma_request                ; -> ENGINE_A0 = 2-bit channel mask, C=1 on fail
    bcs @center_armed               ; allocator short -> no-op
    ; isolate the LOW channel bit (CH2 -> centre) and HIGH bit (CH3 -> scroll).
    ; API_BLOCK_BASE+16 = full 2-bit mask (survives both binds — hdma_bind_direct
    ; reads only API_BLOCK_BASE+0..+3).
    lda ENGINE_A0
    sta API_BLOCK_BASE + 16         ; stash full 2-bit mask
    eor #$FFFF
    inc a
    and ENGINE_A0                   ; A = lowest set bit = CH2 (centre channel)
    sta API_BLOCK_BASE + 20         ; stash CH2 bit (hdma_bind_direct clobbers Y/A/X)
    ; --- bind CH2: M7X/M7Y ($211F), DMAP $03, CENTER_TABLE ---
    lda #.loword(CAMB_CENTER_TABLE)
    sta API_BLOCK_BASE + 0
    sep #$20
    .a8
    lda #^CAMB_CENTER_TABLE
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3          ; DMAP $03 = write-2-regs-twice (M7X + M7Y)
    rep #$20
    .a16
    lda API_BLOCK_BASE + 20         ; A16 = CH2 channel bit
    ldx #$001F                      ; BBAD $1F ($211F M7X -> continues to $2120 M7Y)
    jsr hdma_bind_direct
    ; --- bind CH3: M7HOFS/M7VOFS ($210D), DMAP $03, SCROLL_TABLE ---
    lda #.loword(CAMB_SCROLL_TABLE)
    sta API_BLOCK_BASE + 0
    sep #$20
    .a8
    lda #^CAMB_SCROLL_TABLE
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3          ; DMAP $03 = write-2-regs-twice (M7HOFS + M7VOFS)
    rep #$20
    .a16
    lda API_BLOCK_BASE + 20         ; CH2 bit
    eor API_BLOCK_BASE + 16         ; A = full 2-bit mask XOR CH2 bit = CH3 bit
    ldx #$000D                      ; BBAD $0D ($210D M7HOFS -> continues to $210E)
    jsr hdma_bind_direct
@center_armed:
    plb                             ; restore caller DB
    rts

; =============================================================================
; center_update — restamp band-1's M7X/M7Y (camera A's LIVE centre) each frame.
; =============================================================================
; Keeps band-1's HDMA centre equal to camera A's engine-computed M7X/M7Y so band-1
; tracks camera A's rotation (the NMI commits the SAME value globally, so line-0
; HDMA is a coherent re-write, not a fight). Band-2's centre stays camera B's
; captured value (set in center_setup) — UNLESS -DSAME_CENTER, which folds band-2
; back onto camera A: same channel, same mechanism, band-2 shares camera A's world
; position -> band-2 is the SAME world region (only scale differs) -> the C1
; "different world content" assertion FAILS. That is the non-vacuity control.
; Call every frame AFTER sf_mode7_tick (which recomputes nmi_m7x/m7y for camera A).
; WIDTH-RISK: entry/exit A16/I16. Clobbers A.
center_update:
    .a16
    .i16
    lda M7_PV_NMI_M7X
    sta f:CT_XA                     ; band-1 centre = camera A M7X
    lda M7_PV_NMI_M7Y
    sta f:CT_YA
    lda SHADOW_BG1HOFS
    sta f:CS_HA                     ; band-1 scroll = camera A M7HOFS
    lda SHADOW_BG1VOFS
    sta f:CS_VA
.ifdef SAME_CENTER
    ; non-vacuity control: fold camera B's whole origin onto camera A.
    lda M7_PV_NMI_M7X
    sta f:CT_XB
    lda M7_PV_NMI_M7Y
    sta f:CT_YB
    lda SHADOW_BG1HOFS
    sta f:CS_HB
    lda SHADOW_BG1VOFS
    sta f:CS_VB
.endif
    rts

.ifdef SKY_HORIZON
; =============================================================================
; arm_sky_split — ITEM B: reveal a SKY band above the horizon (-DSKY_HORIZON).
; =============================================================================
; Builds a 3-entry TM ($212C) HDMA band table in WRAM and arms it on an allocator-
; chosen channel (NOT hardcoded CH2 — that is the origin-splice channel here, so
; unlike the generic sf_mode7_sky_split macro this routine takes a FREE channel
; from hdma_request, same pattern as center_setup). The table turns the Mode-7
; floor (BG1) OFF for lines 0..SKY_H-1 so the CGRAM[0] backdrop shows through as
; sky, and ON from line SKY_H (the horizon). OBJ stays OFF in both bands (TM
; $00/$01 — see the table-note below; this demo initialises no OAM). This adds
; ONE HDMA channel; the matrix + origin-splice channels are untouched.
;   [SKY_H, $00]   lines 0..SKY_H-1 -> TM=$00 (all layers off): the sky backdrop
;   [1,     $01]   line SKY_H       -> TM=$01 (BG1 only): the Mode-7 floor begins
;   [0]            terminator       -> TM holds $01 to the screen bottom
; TM band-1 is $00 (NOT the racer macro's $10 "OBJ on"): this demo initialises no
; OBJ/OAM, so leaving OBJ off keeps the power-on-random OAM from painting garbage
; sprites into the sky (the base Mode-7 TM here is BG1-only). A rail WITH sprites
; would use $10/$11 to keep a HUD/avatar above the horizon.
; ValueLatch: $212C is NOT a Mode-7 shared-latch register; the table is HDMA-only
; and set once under forced blank. Boot-only.
; WIDTH-RISK: entry A16/I16. Sets DB=$00 for hdma_request/hdma_bind_direct (their
; contract) and restores caller DB. A8 only for the table + DMAP bytes. Clobbers
; A, X, Y.
arm_sky_split:
    .a16
    .i16
    ; --- build the 3-entry TM band table in WRAM (SKY_TABLE, 5 bytes) ---
    sep #$20
    .a8
    lda #SKY_H
    sta f:SKY_TABLE + 0         ; band-1 line count (NON-REPEAT, bit7 = 0)
    lda #$00
    sta f:SKY_TABLE + 1         ; TM = all layers off (the sky backdrop band)
    lda #$01
    sta f:SKY_TABLE + 2         ; 1 line: the horizon line turns the floor on
    lda #$01
    sta f:SKY_TABLE + 3         ; TM = BG1 only (the Mode-7 floor begins)
    lda #$00
    sta f:SKY_TABLE + 4         ; terminator: TM holds $01 for the rest of the frame
    rep #$20
    .a16
    ; --- allocate 1 channel + bind it to $212C (TM), DMAP $00 (1 byte -> 1 reg) ---
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = $00 (hdma_request/bind contract)
    rep #$30
    .a16
    .i16
    lda #$0001                  ; request 1 channel
    ldx #FX_SKY                 ; effect tag
    jsr hdma_request            ; -> ENGINE_A0 = channel bit, C=1 on fail
    bcs @sky_armed              ; allocator short -> no-op (fail-soft)
    lda #.loword(SKY_TABLE)
    sta API_BLOCK_BASE + 0      ; table address low word (+0 low, +1 high)
    sep #$20
    .a8
    lda #^SKY_TABLE
    sta API_BLOCK_BASE + 2      ; table bank
    lda #$00
    sta API_BLOCK_BASE + 3      ; DMAP $00 = 1 byte -> 1 register direct split
    rep #$20
    .a16
    lda ENGINE_A0               ; A16 = the allocated channel bit
    ldx #$002C                  ; BBAD $2C ($212C TM)
    jsr hdma_bind_direct
@sky_armed:
    plb                         ; restore caller DB
    rts
.endif

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "input_handler.asm"

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

; --- camera-B pose table pointers (low words; all in WRAM bank $7E) ----------
camb_ab_ptrs:
    .word .loword(CAMB_AB0), .loword(CAMB_AB1), .loword(CAMB_AB2), .loword(CAMB_AB3)
    .word .loword(CAMB_AB4), .loword(CAMB_AB5), .loword(CAMB_AB6), .loword(CAMB_AB7)
camb_cd_ptrs:
    .word .loword(CAMB_CD0), .loword(CAMB_CD1), .loword(CAMB_CD2), .loword(CAMB_CD3)
    .word .loword(CAMB_CD4), .loword(CAMB_CD5), .loword(CAMB_CD6), .loword(CAMB_CD7)

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- the 32KB interleaved Mode-7 checker-map blob (bank 1 of the 64KB image) ---
.segment "BANK1"
checker_map:
    .incbin "assets/checker_map.bin"
