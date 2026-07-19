; =============================================================================
; split_h_matrix_demo — Archetype C-horiz: two stacked Mode-7 CAMERA bands
; =============================================================================
; The dedicated C-horiz rail for the sf_split_h primitive: TWO vertically-
; stacked views of ONE flat top-down Mode-7 world, each band rendered through a
; DIFFERENT Mode-7 camera matrix (M7A-D) that changes at the seam scanline via
; HDMA. Trial-proven, framebuffer-verified.
;
;   TOP band    (lines 1..SEAM-1): camera A — scale M7A=M7D=$0100 (1:1). One
;               screen px = one world px, so the 8x8-px world checker renders at
;               an 8-px on-screen period.
;   BOTTOM band (lines SEAM..224):  camera B — scale M7A=M7D=$0040 (0.25). Each
;               screen px steps 0.25 world px, so the checker renders 4x LARGER
;               (a 32-px on-screen period). SAME map, SAME CHR, SAME CGRAM —
;               only the matrix differs. Both cameras share the low-32KB Mode-7
;               VRAM (word $0000): NO extra VRAM vs a single Mode-7 view.
;
; The 8-vs-32 on-screen checker period is the measurable "two distinct cameras"
; signal (test M1). One clean single-scanline seam (test M2). One shared world
; in VRAM (test M3).
;
; -----------------------------------------------------------------------------
; BYPASS, NOT COEXIST (the exclusivity rule — see lib/macros/sf_split_h.inc):
;   The engine's sf_mode7_perspective / pv_rebuild owns the per-scanline M7A-D
;   HDMA on CH5/CH6 (a SINGLE-camera trapezoid). A per-band matrix cannot layer
;   on it — it must OWN the M7A-D HDMA. So this rail does the MINIMAL Mode-7 init
;   (BGMODE=7, M7SEL, map upload, CGRAM, M7X/Y once under forced blank) and does
;   NOT call the perspective renderer; the matrix band drives M7A-D itself via
;   sf_split_h_matrix_bands (two allocator channels, NON-REPEAT, DMAP $03).
;
; THE NON-REPEAT TRAP: each band's HDMA count byte has bit7 = 0 (NON-REPEAT) so
;   the 4-byte matrix unit transfers ONCE per band and HOLDS — 2 HBlank
;   writes/frame per channel, cheap. bit7 = 1 (REPEAT) would re-read a matrix
;   unit every scanline, walk off the short table, and collapse the plane to
;   tile 0. NON-REPEAT is REQUIRED for flat per-band cameras.
;
; ValueLatch guard: satisfied BY CONSTRUCTION — M7X/Y/M7SEL/M7HOFS/VOFS are set
;   ONCE under forced blank and never touched during active display; the matrix
;   is entirely HDMA-driven. No code-side write-twice can interleave.
;
; COMPILE-TIME SWITCHES (the generic make rule can't pass -D; the variant script
; passes them):
;   -DNO_MATRIX_SPLIT=1  NON-VACUITY control: the seam is compiled out — BOTH
;                        bands use camera A's scale for ALL lines -> a SINGLE
;                        camera fills the screen, the two-camera period-ratio
;                        assertion (M1) MUST FAIL (both periods small).
;   -DAUTODEMO=1         self-running: animate the BOTTOM band's camera scale on
;                        the frame counter (patch the bottom band's M7A/M7D in
;                        the WRAM-shadowed AB/CD tables each VBlank under the NMI)
;                        to show the band is LIVE. (Optional inspection aid.)
;
; Controls: none — autonomous. The two cameras are entirely HDMA-driven, so the
;   game loop just idles; there is no input to read.
;
; File layout (top to bottom, matching the major ; === banners below):
;   INIT         RESET: upload the Mode-7 checker map + CGRAM, set the Mode-7
;                registers once under forced blank, arm the two-band matrix HDMA.
;   MAIN LOOP    game_loop — idle (wai for NMI); the two bands are HDMA-driven.
;   SUBROUTINES  the -DAUTODEMO camera-animation helpers + the HDMA allocator.
;   DATA         the 32KB interleaved Mode-7 checker-map blob (BANK1).
;
; Frame loop: `game_loop` is the once-per-frame heartbeat — start reading there.
;
; Build:  make split_h_matrix_demo
;         bash templates/split_h_matrix_demo/build_split_h_matrix_variants.sh
; LDCFG: lorom_64k.cfg
;   ^ 64KB image; the 32KB Mode-7 checker-map blob fills BANK1.
;
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SPLIT H MATRIX"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0 (before engine .asm)
.include "engine_state.inc"
.include "sf_split_h.inc"       ; the split front door + the matrix-band macros

; --- band geometry -----------------------------------------------------------
SEAM       = 112                ; the seam scanline (top band = lines 1..SEAM-1)
TOP_LINES  = SEAM - 1           ; NON-REPEAT line count for the top band
BOT_LINES  = 224 - SEAM         ; NON-REPEAT line count for the bottom band

; --- camera matrix coefficients (8.8 fixed point) ----------------------------
SCALE_A    = $0100              ; camera A: 1.0 -> 8-px on-screen checker period
SCALE_B    = $0040              ; camera B: 0.25 -> 32-px period (4x magnified)

; --- CGRAM colours (15-bit BGR) ----------------------------------------------
COLOR_BACKDROP    = $5400       ; muted blue-violet (color 0)
COLOR_DARK_GREEN  = $01E0       ; palette idx 1 (checker tile 0)
COLOR_LIGHT_GREEN = $03E0       ; palette idx 2 (checker tile 1)

; --- HDMA allocator effect tag -----------------------------------------------
FX_MATRIX  = $21

; --- WRAM state (kit debug region; $E000 magic + $E010 heartbeat are engine) --
G_MSK      = $7EE020            ; word: the 2-channel mask (for a later _off)
G_PHASE    = $7EE024            ; word: -DAUTODEMO animation phase accumulator

.segment "CODE"

; -----------------------------------------------------------------------------
; NMI — minimal custom handler. Re-arms $420C every VBlank so the matrix-band
; HDMA persists, bumps the heartbeat, acks NMI. In -DAUTODEMO it also patches the
; bottom band's M7A/M7D scale in the shadow tables (under VBlank, guard-safe).
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
    ; --- heartbeat mirror at $7E:E010 (sequencing only) ---
    lda f:$7E0000 + $E010
    inc a
    sta f:$7E0000 + $E010
.ifdef AUTODEMO
    jsr autodemo_tick           ; animate the bottom band's camera (guard-safe)
.endif
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

; =============================================================================
; INIT — one-time setup at RESET: upload the Mode-7 checker map + CGRAM, set the
;        Mode-7 registers ONCE under forced blank (ValueLatch-safe), and arm the
;        two-band matrix HDMA through the channel allocator.
; =============================================================================
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
    sta $4302                   ; A1T0L (DMA0 src addr low/mid): checker_map
    sep #$20
    .a8
    lda #^checker_map
    sta $4304                   ; A1B0 (DMA0 src bank)
    rep #$20
    .a16
    lda #$8000                  ; 32768 bytes = the full interleaved map
    sta $4305                   ; DAS0 (DMA0 byte count): 16-bit, fills $4305/$4306
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; MDMAEN: fire general-purpose DMA channel 0

    ; --- CGRAM: backdrop + the two checker greens (under forced blank) ----------
    stz $2121                   ; CGADD = 0
    lda #<COLOR_BACKDROP
    sta $2122                   ; CGDATA (CGRAM data): write colour byte; index auto-advances
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

    ; --- arm the matrix band through the allocator (NOT hand-hardcoded channels).
    ;     The bandlist compiler emits the two NON-REPEAT tables (AB + CD) from one
    ;     (count,M7A,M7B,M7C,M7D) list and binds them on 2 allocator channels with
    ;     BBAD $1B/$1D + DMAP $03. Fail-soft if <2 channels free. ---
    lda #$0000
    sta f:G_MSK                 ; G_MSK/G_PHASE are long WRAM ($7E:Exxx) — use f:
    sta f:G_PHASE
.ifdef AUTODEMO
    ; -DAUTODEMO: copy the seed tables into WRAM (so the NMI can patch the bottom
    ; band's scale each frame) and arm the matrix band on the WRAM copies via the
    ; 2-table front door. NON-REPEAT, DMAP $03.
    jsr autodemo_seed_wram
    sf_split_h_matrix_band tbl_ab_ram, tbl_cd_ram, FX_MATRIX
.else
.ifndef NO_MATRIX_SPLIT
    ; TWO bands: top = camera A scale, bottom = camera B scale. A=D=scale, B=C=0
    ; (flat top-down at angle 0). count bit7=0 (NON-REPEAT).
    sf_split_h_matrix_bands tbl_ab, tbl_cd, FX_MATRIX, {TOP_LINES, SCALE_A, $0000, $0000, SCALE_A, BOT_LINES, SCALE_B, $0000, $0000, SCALE_B}
.else
    ; NON-VACUITY control (-DNO_MATRIX_SPLIT): BOTH bands use camera A's scale ->
    ; one uniform camera fills the screen, the M1 period-ratio assertion FAILS.
    sf_split_h_matrix_bands tbl_ab, tbl_cd, FX_MATRIX, {TOP_LINES, SCALE_A, $0000, $0000, SCALE_A, BOT_LINES, SCALE_A, $0000, $0000, SCALE_A}
.endif
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
    sta $4200                   ; NMITIMEN: NMI on (no auto-joypad needed for this rail)
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: idle. The two camera bands are entirely HDMA-driven, so
;   the loop just waits for each frame's NMI; all the per-frame work is the HDMA.
; =============================================================================
game_loop:
    .a16
    .i16
    wai                         ; wait for NMI (frame boundary) — the matrix band
    jmp game_loop               ;   is entirely HDMA-driven; the loop just idles

; =============================================================================
; SUBROUTINES — the -DAUTODEMO camera-animation helpers (below, conditional) and
;   the HDMA channel allocator (.include at the end). The matrix band routes
;   through the allocator; the autodemo helpers patch the WRAM matrix tables.
; =============================================================================

.ifdef AUTODEMO
; --- -DAUTODEMO WRAM table storage (debug region). Each table = 2 bands x 5B +
;     1B terminator = 11 bytes. tbl_ab_ram: [c0,A0,B0, c1,A1,B1, $00];
;     tbl_cd_ram: [c0,C0,D0, c1,C1,D1, $00]. Fixed low-WRAM so long,X writes
;     from the NMI reach them. ---
tbl_ab_ram = $7EE030            ; 11 bytes (long address, for the HDMA table ptr)
tbl_cd_ram = $7EE040            ; 11 bytes
AB_ABS     = tbl_ab_ram & $FFFF ; the low-16 bank-$7E offset (for DB=$7E abs stores)
CD_ABS     = tbl_cd_ram & $FFFF

; =============================================================================
; autodemo_seed_wram — write the two NON-REPEAT seed tables into WRAM at boot
; (under the coldstart forced blank). Camera A on top, camera B (animated) on the
; bottom. Entry stride = 1(count)+2(A/C word)+2(B/D word) = 5 bytes per band.
; WIDTH-RISK: entry A16/I16. A8 for the count bytes, A16 for the matrix words.
; =============================================================================
autodemo_seed_wram:
    .a16
    .i16
    ; Set DB=$7E so the tbl_*_ram ($7E:Exxx) stores use plain absolute addressing
    ; (stz has an absolute form; no long f: needed). AB_ABS/CD_ABS are the low-16
    ; bank-$7E offsets of the tables.
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    ; --- tbl_ab_ram: [TOP_LINES, SCALE_A,0,  BOT_LINES, SCALE_B,0,  $00] ---
    lda #TOP_LINES
    sta AB_ABS + 0
    rep #$20
    .a16
    lda #SCALE_A
    sta AB_ABS + 1              ; M7A top
    stz AB_ABS + 3             ; M7B top = 0
    sep #$20
    .a8
    lda #BOT_LINES
    sta AB_ABS + 5
    rep #$20
    .a16
    lda #SCALE_B
    sta AB_ABS + 6             ; M7A bottom (animated)
    stz AB_ABS + 8             ; M7B bottom = 0
    sep #$20
    .a8
    stz AB_ABS + 10            ; terminator (A8 -> 1-byte $00)
    ; --- tbl_cd_ram: [TOP_LINES, 0,SCALE_A,  BOT_LINES, 0,SCALE_B,  $00] ---
    lda #TOP_LINES
    sta CD_ABS + 0
    rep #$20
    .a16
    stz CD_ABS + 1            ; M7C top = 0
    lda #SCALE_A
    sta CD_ABS + 3            ; M7D top
    sep #$20
    .a8
    lda #BOT_LINES
    sta CD_ABS + 5
    rep #$20
    .a16
    stz CD_ABS + 6            ; M7C bottom = 0
    lda #SCALE_B
    sta CD_ABS + 8            ; M7D bottom (animated)
    sep #$20
    .a8
    stz CD_ABS + 10           ; terminator
    plb                         ; restore caller DB
    rep #$30
    .a16
    .i16
    rts

; =============================================================================
; autodemo_tick — animate the BOTTOM band's camera scale (M7A/M7D) on a slow
; sweep and rewrite it into the WRAM AB/CD tables. Called from the NMI (VBlank),
; so the write is guard-safe (no active-display code-side matrix write). Because
; the -DAUTODEMO build points the HDMA at these WRAM tables, patching the bottom
; band's M7A/M7D word makes the band visibly LIVE.
; WIDTH-RISK: entry A16/I16 (from the NMI). Stays A16 for the word patches.
; =============================================================================
autodemo_tick:
    .a16
    .i16
    lda f:$7E0000 + (G_PHASE & $FFFF)
    inc a
    and #$00FF
    sta f:$7E0000 + (G_PHASE & $FFFF)
    ; scale = $0040 + (phase & $3F) — sweep the bottom camera zoom over $40..$7F.
    and #$003F
    clc
    adc #$0040
    ; patch the bottom band's M7A (tbl_ab_ram + 6) and M7D (tbl_cd_ram + 8).
    sta f:tbl_ab_ram + 6        ; bottom band M7A word
    sta f:tbl_cd_ram + 8        ; bottom band M7D word
    rts
.endif

; --- engine link: the HDMA channel allocator (hdma_alloc_init / hdma_request /
;     hdma_bind_direct); the matrix band routes through it ---
.include "hdma_alloc.asm"

; =============================================================================
; DATA — the 32KB interleaved Mode-7 checker-map blob (bank 1 of the 64KB image).
; =============================================================================
.segment "BANK1"
checker_map:
    .incbin "assets/checker_map.bin"
