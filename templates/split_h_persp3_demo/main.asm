; =============================================================================
; split_h_persp3_demo — Archetype C-horiz: THREE stacked Mode-7 CAMERA bands
; =============================================================================
; The three-camera extension of split_h_matrix_demo — THREE vertically-stacked
; views of ONE flat top-down Mode-7 world, each band a DIFFERENT Mode-7 camera
; matrix (M7A-D) that changes at a seam scanline via HDMA. TWO seams, three
; distinct camera regions of one world.
;
; WHY FLAT (PRECOMPUTED) MATRIX BANDS AND NOT THREE LIVE PERSPECTIVE SOLVES:
;   The perspective rail (split_h_persp_demo) MEASURED that ONE live per-scanline
;   solve already costs ~87-138% of a 60fps CPU frame (tests/persp_cycles_test.asm
;   / test_persp_cycles.py). A second live solve does NOT fit by any incremental
;   route; a third is hopeless. The ONLY budget-viable path for EXTRA cameras is
;   FLAT per-band matrices: the sf_split_h_matrix_bands compiler emits NON-REPEAT
;   HDMA tables (2 HBlank writes/band/channel, ~nil CPU) that hold a CONSTANT
;   matrix per band. This demo is entirely HDMA-driven — the game loop just idles —
;   so THREE cameras cost the SAME as ONE and close 60fps trivially (no live solve).
;
;   TOP band    (lines 0..SEAM1-1): camera A — scale M7A=M7D=SCALE_A ($0100 = 1.0).
;               One screen px = one world px -> the 8x8-px checker at an 8-px period.
;   MIDDLE band (lines SEAM1..SEAM2-1): camera B — scale SCALE_B ($0040 = 0.25).
;               Each screen px steps 0.25 world px -> the checker 4x LARGER (32-px).
;   BOTTOM band (lines SEAM2..224): camera C — scale SCALE_C ($0080 = 0.5).
;               A THIRD distinct zoom -> a 16-px on-screen period. SAME map, CHR,
;               CGRAM; all three cameras share the low-32KB Mode-7 VRAM (word $0000):
;               NO extra VRAM vs a single Mode-7 view.
;
; The three on-screen checker periods (8 / 32 / 16 px) are the "three distinct
; cameras" signal (test C1); two clean single-scanline seams (test C2); temporal
; stability (test C3 — the scene is HDMA-static, NO double buffer to desync); one
; shared world in VRAM. -DONE_CAM collapses all three bands to camera A's scale ->
; ONE camera fills the screen -> the three-distinct-period assertion FAILS (C1 non-
; vacuity control).
;
; -----------------------------------------------------------------------------
; BYPASS, NOT COEXIST (the exclusivity rule — see lib/macros/sf_split_h.inc):
;   The engine's sf_mode7_perspective / pv_rebuild owns the per-scanline M7A-D HDMA
;   (a SINGLE-camera trapezoid); a per-band matrix must OWN M7A-D, so this rail does
;   the MINIMAL Mode-7 init (BGMODE=7, M7SEL, map upload, CGRAM, M7X/Y once under
;   forced blank) and drives M7A-D itself via sf_split_h_matrix_bands (2 allocator
;   channels, NON-REPEAT, DMAP $03). NON-REPEAT (count bit7=0) is REQUIRED: the
;   4-byte matrix unit transfers ONCE per band and HOLDS.
;
; ValueLatch guard: satisfied BY CONSTRUCTION — M7X/Y/M7SEL/M7HOFS/VOFS are set
;   ONCE under forced blank and never touched during active display; the matrix is
;   entirely HDMA-driven. No code-side write-twice can interleave.
;
; COMPILE-TIME SWITCHES (the generic make rule can't pass -D; the variant script
; passes them):
;   -DONE_CAM=1  NON-VACUITY control: all three bands use camera A's scale -> a
;                SINGLE camera fills the screen, the three-distinct-period
;                assertion (C1) MUST FAIL (all three periods small/equal).
;
; Build:  make split_h_persp3_demo
;         bash templates/split_h_persp3_demo/build_split_h_persp3_variants.sh
; LDCFG: lorom_64k.cfg   (64KB image; the 32KB Mode-7 checker-map fills BANK1.)
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0 (before engine .asm)
.include "engine_state.inc"
.include "sf_split_h.inc"       ; the split front door + the matrix-band macros

; --- band geometry (two seams -> three bands) --------------------------------
SEAM1      = 75                 ; first seam: top band = lines 0..SEAM1-1
SEAM2      = 150                ; second seam: middle band = SEAM1..SEAM2-1
B1_LINES   = SEAM1              ; top band line count    (75)
B2_LINES   = SEAM2 - SEAM1      ; middle band line count (75)
B3_LINES   = 224 - SEAM2        ; bottom band line count (74)

; --- camera matrix coefficients (8.8 fixed point) — three distinct scales -----
SCALE_A    = $0100              ; camera A: 1.0  -> 8-px on-screen checker period
SCALE_B    = $0040              ; camera B: 0.25 -> 32-px period (4x magnified)
SCALE_C    = $0080              ; camera C: 0.5  -> 16-px period (2x magnified)

; --- CGRAM colours (15-bit BGR) ----------------------------------------------
COLOR_BACKDROP    = $5400       ; muted blue-violet (color 0)
COLOR_DARK_GREEN  = $01E0       ; palette idx 1 (checker tile 0)
COLOR_LIGHT_GREEN = $03E0       ; palette idx 2 (checker tile 1)

; --- HDMA allocator effect tag -----------------------------------------------
FX_MATRIX  = $22

; --- WRAM state (kit debug region; $E000 magic + $E010 heartbeat are engine) --
G_MSK      = $7EE020            ; word: the 2-channel mask (for a later _off)

.segment "CODE"

; -----------------------------------------------------------------------------
; NMI — minimal custom handler. Re-arms $420C every VBlank so the matrix-band
; HDMA persists, bumps the heartbeat, acks NMI.
; WIDTH-RISK: NMI entry width unknown -> php/rep at top, plp at exit. A8/I16 body.
; -----------------------------------------------------------------------------
NMI:
    php
    rep #$30
    .a16
    .i16
    pha
    phx
    ; --- re-arm the matrix-band HDMA channels from NMI_HDMA_ENABLE mirror ---
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    sta $420C                   ; HDMAEN = the armed matrix-band channels
    rep #$20
    .a16
    ; --- heartbeat mirror at $7E:E010 (sequencing / 60fps liveness only) ---
    lda f:$7E0000 + $E010
    inc a
    sta f:$7E0000 + $E010
    ; ack NMI (read RDNMI); then restore.
    sep #$20
    .a8
    lda $4210                   ; RDNMI ack
    rep #$20
    .a16
    plx
    pla
    plp
    rti

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared to 0
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- upload the interleaved Mode-7 checker map to VRAM word $0000 (GP-DMA
    ;     ch0, under the coldstart forced blank). VMAIN=$80 (+1 word). ---
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after $2119
    rep #$20
    .a16
    stz $2116                   ; VMADD = $0000
    sep #$20
    .a8
    lda #$01
    sta $4300                   ; DMAP0: mode 1 (2 regs $2118/$2119), src+1
    lda #$18
    sta $4301                   ; BBAD0 = $18 -> $2118 (VMDATA low)
    rep #$20
    .a16
    lda #.loword(checker_map)
    sta $4302                   ; src low word
    sep #$20
    .a8
    lda #^checker_map
    sta $4304                   ; src bank
    rep #$20
    .a16
    lda #$8000                  ; 32768 bytes = the full interleaved map
    sta $4305
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; fire GP-DMA ch0

    ; --- CGRAM: backdrop + the two checker greens (under forced blank) ----------
    stz $2121                   ; CGADD = 0
    lda #<COLOR_BACKDROP
    sta $2122
    lda #>COLOR_BACKDROP
    sta $2122
    lda #<COLOR_DARK_GREEN
    sta $2122
    lda #>COLOR_DARK_GREEN
    sta $2122
    lda #<COLOR_LIGHT_GREEN
    sta $2122
    lda #>COLOR_LIGHT_GREEN
    sta $2122

    ; --- Mode-7 registers set ONCE under forced blank (ValueLatch guard-safe) ---
    lda #$07
    sta $2105                   ; BGMODE = 7
    lda #$01
    sta $212C                   ; TM = BG1 only (the Mode-7 plane) — one plane
    lda #$00
    sta $211A                   ; M7SEL = $00 (wrap the 1024px map; no fill)

    ; M7HOFS / M7VOFS ($210D/$210E) = 0 — write-twice, done ONCE here (shares the
    ; ValueLatch with the matrix; never written during active display).
    lda #$00
    sta $210D
    sta $210D                   ; M7HOFS = 0 (low, high)
    sta $210E
    sta $210E                   ; M7VOFS = 0

    ; M7X / M7Y ($211F/$2120) center = world (512,512), write-twice, ONCE here.
    lda #<512
    sta $211F
    lda #>512
    sta $211F                   ; M7X = 512
    lda #<512
    sta $2120
    lda #>512
    sta $2120                   ; M7Y = 512
    rep #$30
    .a16
    .i16

    ; --- arm the THREE-band matrix band through the allocator. The bandlist
    ;     compiler emits the two NON-REPEAT tables (AB + CD) from ONE
    ;     (count,M7A,M7B,M7C,M7D) list of THREE 5-tuples and binds them on 2
    ;     allocator channels (BBAD $1B/$1D, DMAP $03). Fail-soft if <2 free. ---
    lda #$0000
    sta f:G_MSK                 ; G_MSK is long WRAM ($7E:Exxx) — use f:
.ifndef ONE_CAM
    ; THREE bands: A=D=scale, B=C=0 (flat top-down at angle 0), count bit7=0.
    sf_split_h_matrix_bands tbl_ab, tbl_cd, FX_MATRIX, {B1_LINES, SCALE_A, $0000, $0000, SCALE_A, B2_LINES, SCALE_B, $0000, $0000, SCALE_B, B3_LINES, SCALE_C, $0000, $0000, SCALE_C}
.else
    ; NON-VACUITY control (-DONE_CAM): all three bands use camera A's scale ->
    ; one uniform camera fills the screen, the C1 three-period assertion FAILS.
    sf_split_h_matrix_bands tbl_ab, tbl_cd, FX_MATRIX, {B1_LINES, SCALE_A, $0000, $0000, SCALE_A, B2_LINES, SCALE_A, $0000, $0000, SCALE_A, B3_LINES, SCALE_A, $0000, $0000, SCALE_A}
.endif
    lda ENGINE_A0
    sta f:G_MSK                 ; the 2-channel mask (for a later sf_split_h_off)

    sf_debug_magic              ; "SFDB" at $7E:E000 (boot proof)

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    lda #$80
    sta $4200                   ; NMI on (no auto-joypad needed for this rail)
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    .a16
    .i16
    wai                         ; wait for NMI (frame boundary) — the matrix band
    jmp game_loop               ;   is entirely HDMA-driven; the loop just idles

; =============================================================================
; Engine link — the HDMA channel allocator (hdma_alloc_init / hdma_request /
; hdma_bind_direct). The matrix band routes through it.
; =============================================================================
.include "hdma_alloc.asm"

; =============================================================================
; The 32KB interleaved Mode-7 checker-map blob (bank 1 of the 64KB image).
; =============================================================================
.segment "BANK1"
checker_map:
    .incbin "assets/checker_map.bin"
