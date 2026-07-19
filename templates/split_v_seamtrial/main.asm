; =============================================================================
; split_v_seamtrial — SEAMLESS-collapse trial (the split_v_fight precursor)
; =============================================================================
; A trial rail. It proves the DBZ-style seamless separation on real PPU output,
; in isolation, so the composed fighting rail (templates/split_v_fight) can build
; on a mechanism already shown to work. The insight (confirmed against the SNESdev
; window docs): the
; window split is a SINGLE-PIXEL boundary with no inherent gap, so if the two
; camera views are IDENTICAL the ever-present split is invisible. Separation is
; therefore NOT a state you toggle — it is a continuous divergence:
;
;   window 1 (the split) is ALWAYS on, fixed at screen centre (x=128). Never
;   toggled, never forced-blanked.
;   camA = mid - spread ; camB = mid + spread   (both cameras of ONE stage)
;     spread = 0  -> camA == camB -> both halves pixel-identical -> INVISIBLE seam
;     spread > 0  -> the halves diverge; the seam smoothly emerges as a real
;                    content discontinuity (no pop, no shift, no redraw).
;   the divider LINE draws itself: band half-width hw = spread>>4, which is ZERO
;     at merge (no content masked -> no width stolen -> no "everything shifts over
;     by the line width" artifact) and grows only after the halves have parted.
;   the line is a BEVELED bar on BG3 (highlight edge / mid core / shadow edge) that
;     window 2 reveals only inside the band (BG3 masked OUTSIDE it, BG1/BG2 masked
;     INSIDE it), so it grows from zero width and is a crisp 3-D divider, not a flat
;     backdrop stripe. VERTICAL (not diagonal): a diagonal angle would imply the
;     vertical separation this ground-only game does not have.
;
; Self-running: `spread` sweeps 0 -> SPREAD_MAX -> 0 (triangle) so the collapse
; and the re-merge both play out on their own. No HDMA (straight centre split) —
; this isolates the seamless mechanism; a diagonal port would come later.
;
; Controls: none — autonomous. The default build sweeps `spread` on its own.
;   Compile-time knobs: -DHOLD=n freezes spread at n px (race-free framebuffer
;   proofs); -DNOWIN is the no-split reference (window off, single camera).
;
; File layout (top to bottom, matching the major ; === banners below):
;   INIT         RESET: stage tiles (BG1), the beveled BG3 divider, the always-on
;                split-window recipe, and the camera + sweep state.
;   MAIN LOOP    game_loop — the once-per-frame heartbeat: sweep spread, diverge
;                the two cameras, ramp the divider band, scroll the halves.
;   DATA         stage tiles, terrain height map, beveled-bar tiles (baked in ROM).
;   SUBROUTINES  engine modules (PPU init, input, DMA, sprite, BG) via .include.
;
; Frame loop: `game_loop` is the once-per-frame heartbeat — start reading there.
;
; Build: make split_v_seamtrial   (default 32K cfg; no HDMA engine)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SEAM V TRIAL"
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

; --- DP scratch (hot-global region $40-$5F; unused by the engine here) ---
SPREADF = $40                   ; camera spread, 8.8 fixed (0 .. SPREAD_MAX<<8)
SPREAD  = $42                   ; integer spread (0 .. SPREAD_MAX)
SDIR    = $44                   ; sweep phase: 0=opening, 1=closing
CAMA    = $46                   ; camera A scroll (left half)
CAMB    = $48                   ; camera B scroll (right half)
HW      = $4A                   ; live divider half-width (0 .. SPREAD_MAX>>4)
T_MX    = $50
T_MY    = $52
T_TILE  = $54

MID_CAM   = 96                  ; the shared viewpoint (fixed for the trial)
SPREAD_MAX = 48                 ; full divergence: camA=48, camB=144
SPR_STEP  = $00C0               ; 0.75 px/frame sweep (8.8) -> ~64 frames each way
SEAM      = 128                 ; the split column (screen centre)
HW_SETUP  = 4                   ; recipe-establishing half-width (overwritten/frame)
GND_DIRT  = 24

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

; =============================================================================
; INIT — one-time setup at RESET: stage tiles (BG1), the beveled BG3 divider,
;        the always-on split-window recipe, and the camera/sweep state. Runs
;        once; VRAM/CGRAM writes are safe because the engine boots under forced
;        blank until gfxmode turns the screen on.
; =============================================================================
RESET:
    sf_coldstart
    sf_engine_init

    ; --- stage tiles -> BG1 CHR ($2000) ---
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN (VRAM port mode): +1 word per high-byte write
    rep #$30
    .a16
    .i16
    lda #$2010
    sta $2116                   ; VMADD (VRAM word address): BG1 CHR, start at tile 1
    ldx #$0000
@chr:
    lda f:solid_tiles, x
    sta $2118                   ; VMDATA (VRAM data): write a CHR word; addr auto-advances
    inx
    inx
    cpx #(4*32)
    bne @chr

    ; --- beveled divider bar -> BG3 CHR at word $7000 (2bpp). NOT the gfxmode
    ;     default $A000: VRAM word addresses are 15-bit ($0000..$7FFF), so $A000
    ;     WRAPS to $2000 and lands on BG1's CHR. We relocate BG3 CHR to $7000
    ;     (free: BG1 map $5800, BG3 map $6000) and repoint BG34NBA after gfxmode. ---
    lda #$7000
    sta $2116
    ldx #$0000
@b3chr:
    lda f:bg3_bar_tiles, x
    sta $2118
    inx
    inx
    cpx #(3*8*2)                ; 3 tiles x 8 words
    bne @b3chr

    sf_bg_color 0, 0, $7FFF     ; backdrop (unused now — the line is BG3, not backdrop)
    sf_bg_color 0, 1, $7F54     ; sky
    sf_bg_color 0, 2, $02E0     ; grass
    sf_bg_color 0, 3, $4A52     ; mountain
    sf_bg_color 0, 4, $1194     ; dirt
    ; BG3 bevel palette (palette 2 -> CGRAM 8..11): dark / mid / light highlight
    sf_bg_color 0, 9,  $18C6    ; bevel dark  (shadow edge)
    sf_bg_color 0, 10, $4E73    ; bevel mid
    sf_bg_color 0, 11, $7FFF    ; bevel light (bright core)

    jsr init_ppu
    gfxmode #1
    ; shared-CHR override: BG2 reads BG1's tilemap ($5800) + CHR ($2000)
    sep #$20
    .a8
    lda #$58
    sta $2108                       ; BG2SC (BG2 tilemap addr): reuse BG1's map at word $5800
    lda #$22
    sta $210B                       ; BG12NBA (BG1/BG2 CHR base): both at word $2000
    lda #$07                        ; BG34NBA: BG3 CHR word $7000 (see upload note)
    sta $210C                       ; direct write, held (engine never re-commits it)
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

    ; --- beveled bar into BG3 tilemap. The engine's NMI DMAs all three shadow
    ;     tilemaps in ONE VBlank when dirty; three full 2KB maps overrun VBlank and
    ;     BG3 (last) is TRUNCATED partway (its tail hits active display, where VRAM
    ;     is write-blocked) -> the bar loses rows at the truncation point. The bar
    ;     is STATIC, so we do BOTH: (1) populate the BG3 shadow via mset #3 so the
    ;     NMI's partial DMA writes the BAR (not blanks) over the rows it covers,
    ;     and (2) write the FULL map ourselves under forced blank to cover the rows
    ;     the NMI truncates. Identical data both ways -> any truncation point is
    ;     covered. cols 15/16 = barL/barR (pal 2, CHR $7000). ---
    stz T_MY
@b3row:
    .a16
    .i16
    mset #3, #15, T_MY, #$0801       ; barL, tile1 | pal2<<10
    mset #3, #16, T_MY, #$0802       ; barR, tile2 | pal2<<10
    lda T_MY
    inc a
    sta T_MY
    cmp #32
    bne @b3row

    sep #$20
    .a8
    lda #$8F                        ; forced blank ON (brightness 15)
    sta $2100                       ; INIDISP (display control): blank PPU so VRAM writes land
    lda #$80                        ; VMAIN: +1 word after high-byte write
    sta $2115
    rep #$30
    .a16
    .i16
    lda #$6000
    sta $2116
    ldx #$0000
@b3map:
    txa
    and #$001F                      ; col = cell & 31
    cmp #15
    beq @b3mL
    cmp #16
    beq @b3mR
    lda #0
    bra @b3mW
@b3mL:
    .a16
    .i16
    lda #$0801                      ; barL, tile1 | pal2<<10
    bra @b3mW
@b3mR:
    .a16
    .i16
    lda #$0802                      ; barR, tile2 | pal2<<10
@b3mW:
    .a16
    .i16
    sta $2118
    inx
    cpx #1024
    bne @b3map
    sep #$20
    .a8
    lda #$0F                        ; forced blank OFF (brightness 15)
    sta $2100
    rep #$30
    .a16
    .i16

    ; --- the split recipe is set ONCE and NEVER toggled: window 1 splits at the
    ;     centre; window 2 gates the BEVELED BG3 BAR — BG1/BG2 masked INSIDE the
    ;     band (bar replaces them), BG3 masked OUTSIDE it (bar shows only in the
    ;     band). Band half-width ramps from 0, so the bar grows from nothing. ---
.ifdef NOWIN
    sf_window_off                   ; ground-truth: plain single camera, no split
.else
    sf_window1_edges #SEAM, #255
    sf_window2_edges #(SEAM-HW_SETUP), #(SEAM+HW_SETUP)
    sf_window_bg12 #$BA             ; BG1 win1-in|win2-in ; BG2 win1-out|win2-in
    sf_window_bg34 #$0C             ; BG3 win2-OUTSIDE (bar shown only inside band)
    sf_window_logic #$00            ; all-OR
    sf_window_mask_main #$07        ; mask BG1+BG2+BG3
.endif

    ; --- BG3 scroll is never touched in the loop; pin it to 0 so the beveled bar
    ;     tiles (cols 15/16) land at screen 120..135 (its shadow is otherwise
    ;     uninitialised garbage -> the bar would be mis-aligned). ---
    scroll #3, #0, #0

    ; --- start MERGED: spread 0 -> identical cameras -> invisible seam ---
    ; (-DHOLD=n holds spread STATIC at n for race-free framebuffer measurement.)
.ifdef HOLD
    lda #(HOLD*256)
    sta SPREADF
.else
    stz SPREADF
.endif
    stz SDIR
    lda #MID_CAM
    sta CAMA
    sta CAMB
    stz HW

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                       ; NMITIMEN: enable VBlank NMI + auto-joypad read
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: the once-per-frame heartbeat. sf_frame_begin waits for
;   VBlank; then the body sweeps `spread`, diverges the two cameras, ramps the
;   divider band from that spread, and scrolls the halves. No input is read —
;   the sweep drives everything (PER-FRAME UPDATE folded in below).
; =============================================================================
game_loop:
    sf_frame_begin

.ifndef HOLD
    ; --- sweep `spread` as a triangle 0 -> SPREAD_MAX -> 0 (8.8) ---
    lda SDIR
    bne @closing
    lda SPREADF                 ; opening: grow spread
    clc
    adc #SPR_STEP
    sta SPREADF
    cmp #(SPREAD_MAX*256)
    bcc @swept
    lda #(SPREAD_MAX*256)
    sta SPREADF
    lda #1
    sta SDIR
    bra @swept
@closing:
    .a16
    lda SPREADF                 ; closing: shrink spread
    cmp #SPR_STEP
    bcc @hitzero                ; would cross 0 -> clamp + reopen
    sec
    sbc #SPR_STEP
    sta SPREADF
    bra @swept
@hitzero:
    .a16
    stz SPREADF
    stz SDIR
@swept:
    .a16
    .i16
.endif ; HOLD

    ; --- integer spread = SPREADF >> 8 (high byte) ---
    lda SPREADF
    xba
    and #$00FF
    sta SPREAD

    ; --- collapsing cameras: camA = mid - spread ; camB = mid + spread.
    ;     spread==0 => camA==camB==mid => the two halves are identical. ---
    lda #MID_CAM
    sec
    sbc SPREAD
    and #$00FF
    sta CAMA
    lda #MID_CAM
    clc
    adc SPREAD
    and #$00FF
    sta CAMB

    ; --- divider half-width hw = spread >> 4 (0 at merge -> zero width stolen) ---
    lda SPREAD
    lsr a
    lsr a
    lsr a
    lsr a
    sta HW

    ; --- write the band edges from the LIVE hw (WH0/WH1 stay 128/255 from setup) ---
    lda HW
    beq @noband
    sep #$20
    .a8
    lda #SEAM                    ; band = [SEAM-hw, SEAM+hw]
    sec
    sbc HW
    sta SHADOW_WH2
    lda #SEAM
    clc
    adc HW
    sta SHADOW_WH3
    rep #$20
    .a16
    bra @bandset
@noband:
    .a16
    sep #$20
    .a8
    lda #1                       ; empty band (left>right => window inactive): no
    sta SHADOW_WH2               ; line pixel at all while merged
    lda #0
    sta SHADOW_WH3
    rep #$20
    .a16
@bandset:
    .a16
    .i16

    scroll #1, CAMA, #0
    scroll #2, CAMB, #0

    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — stage tiles, terrain height map, and the beveled-bar tiles (baked in ROM).
; =============================================================================

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

; --- BG3 beveled-bar tiles (2bpp, 8 words each; VRAM word format hi=plane1,lo=plane0)
;     tile0 blank; tile1 = bar LEFT half (screen 120..127); tile2 = bar RIGHT half
;     (screen 128..135). Cross-section is a bright core at x~128 fading to dark
;     edges (an energy-beam bevel); pixel value 1=dark 2=mid 3=light, all 8 rows
;     identical. Reveal is centred on the seam and widens symmetrically. ---
bg3_bar_tiles:
    .repeat 8
        .word $0000                 ; tile0: transparent
    .endrepeat
    .repeat 8
        .word $FFFE                 ; tile1 barL cols[3,3,3,3,3,3,3,2] p0=$FE p1=$FF
    .endrepeat
    .repeat 8
        .word $C03F                 ; tile2 barR cols[2,2,1,1,1,1,1,1] p0=$3F p1=$C0
    .endrepeat

; =============================================================================
; SUBROUTINES — engine modules (PPU init, input, DMA, sprite, BG) pulled in by
;   .include at the file end.
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
