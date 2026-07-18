; =============================================================================
; split_v_demo — minimal 2-player vertical dual-view (sf_split_v v1 demo rail)
; =============================================================================
; Proves the vertical left/right window dual-view primitive: ONE shared
; scrolling stage rendered through TWO BG-layer cameras, clipped to the two
; halves of the screen by the PPU window system. Player 1 (port 0) drives the
; LEFT camera, player 2 (port 1) the RIGHT camera; a straight vertical seam
; (centred, sweepable) divides the two views, drawn as a COLOURED BACKDROP BAR
; (zero sprites); a red player marker stands in each half.
; Minimal by design — it proves the primitive, not a game.
;
; STAGE (Mode 1, BG1 + BG2, one world): a side-on LANDSCAPE cross-section — sky
; over green hills with a grey mountain and a brown dirt base, from a 32-column
; height map. The stage is uploaded ONCE to BG1's CHR ($2000) + tilemap ($5800);
; BG2 is pointed at the SAME base (BG2SC=$58, BG12NBA=$22) so both cameras read
; one shared VRAM copy — only the scroll differs (BG1 = camera A, BG2 = camera
; B). This halves the VRAM of the naive two-copy layout.
;
; SEAM (zero OBJ): window 1 is the left/right split; window 2 is a thin band at
; the seam that masks BG1+BG2+BG3, so the BACKDROP (CGRAM 0, set white) shows
; through as the seam bar. No sprites, no HDMA — the whole frame is PPU-drawn.
;
; CONTROLS:
;   P1 D-pad Left/Right  -> camera A scroll (left half)
;   P2 D-pad Left/Right  -> camera B scroll (right half)
;   P1 L/R shoulders     -> move the seam (clamped to [SEAM_LO, SEAM_HI])
;
; COMPILE-TIME SWITCHES (the generic make rule can't pass -D):
;   -DNO_WINDOW=1  non-vacuity control: the window recipe is compiled out, so
;                  BG1 (camera A) fills the whole screen and the split COLLAPSES
;                  — the D1 two-region signature must be ABSENT.
;   -DOBJ_CLIP=1   confine OBJ to the left half: the P1 marker straddling the
;                  seam is clipped and the right-half P2 marker vanishes.
;   -DAUTODEMO=1   self-running (no controller): holds the seam fixed at centre
;                  (a steady 50/50 split) and pans the two cameras independently
;                  (A right, B left) — the classic split-screen look.
;
; Build:  make split_v_demo                 (default; window on, no OBJ clip)
;         bash templates/split_v_demo/build_split_v_variants.sh   (the -D ROMs)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"
.include "buttons.inc"
.include "sf_split_v.inc"
.include "sf_frame.inc"
.include "engine_state.inc"

; --- DP scratch (hot-global region $40-$4F; the engine touches it only when
;     game code uses globals — this hand-written ROM does not) ---
CAM_A    = $40                  ; 2 bytes: BG1 camera X (left)
CAM_B    = $42                  ; 2 bytes: BG2 camera X (right)
SEAM     = $44                  ; 2 bytes: current seam X
MKX      = $46                  ; 2 bytes: marker X scratch
T_MX     = $48                  ; 2 bytes: tilemap fill column
T_MY     = $4A                  ; 2 bytes: tilemap fill row
T_TILE   = $4C                  ; 2 bytes: tilemap fill tile word

CAM_A0   = 0                    ; camera A initial scroll
CAM_B0   = 192                  ; camera B initial scroll (frames the far side)
SEAM0    = 128                  ; initial seam (centre)
SEAM_LO  = 64
SEAM_HI  = 192
BAND_HW  = 6                    ; seam band half-width (backdrop bar = 2*HW px)
DIAG_BASE  = 72                 ; -DDIAGONAL: seam X at the top scanline
DIAG_SLOPE = $0080              ; -DDIAGONAL: 8.8 slope = 0.5 px/scanline (centres at mid-screen)
CAM_SPD  = 2                    ; camera scroll px/frame
GND_DIRT = 24                   ; rows >= this are dirt (base)
PLY_Y    = 176                  ; player-marker row (on the ground)
PLY_DX   = 40                   ; P2 marker offset from the seam (right half)

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
.ifdef DIAGONAL
    jsr hdma_alloc_init         ; the diagonal seam drives WH0/WH2/WH3 via HDMA
.endif

    ; --- upload the 4 landscape tiles ONCE to BG1 CHR ($2000) ---
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #$2010                  ; word $2000 + tile 1*16
    sta $2116
    ldx #$0000
@chr:
    lda f:solid_tiles, x
    sta $2118
    inx
    inx
    cpx #(4*32)
    bne @chr

    ; Palette: BACKDROP (CGRAM 0) = white -> the seam-bar colour. Slots 1..4 =
    ; sky / grass / mountain / dirt. (No stage colour is white or the marker red.)
    sf_bg_color 0, 0, $7FFF     ; backdrop / seam bar (white)
    sf_bg_color 0, 1, $7F54     ; sky (light blue)
    sf_bg_color 0, 2, $02E0     ; grass (green)
    sf_bg_color 0, 3, $4A52     ; mountain (grey)
    sf_bg_color 0, 4, $1194     ; dirt (brown)

    ; OBJ marker tile (red 8x8) + OBJ palette 0 slot 1 = red.
    sf_load_obj_tile 1, player_tile
    sf_obj_color 0, 1, $001F

    jsr init_ppu
    gfxmode #1                  ; Mode 1: BG1+BG2+BG3+OBJ

    ; --- SHARED-CHR OVERRIDE: point BG2 at BG1's tilemap ($5800) and CHR ($2000)
    ;     so both cameras read one VRAM copy (the engine gfxmode default puts BG2
    ;     at $5C00/$4000; the NMI never re-commits BG2SC/BG12NBA, so this holds). ---
    sep #$20
    .a8
    lda #$58
    sta $2108                   ; BG2SC = $58 (= BG1SC; shared tilemap)
    lda #$22
    sta $210B                   ; BG12NBA: BG1 CHR $2000, BG2 CHR $2000 (shared)
    rep #$30
    .a16
    .i16

    ; --- fill BG1 tilemap ONCE from the height map (BG2 reads the same map) ---
    ; col c -> ground top row hmap[c]; rows < top = sky; rows >= GND_DIRT = dirt;
    ; cols 6..12 above the dirt = mountain (grey); else grass.
    ; WIDTH-RISK: the inner cell calc toggles A8 (byte compares against the height
    ; map) then restores A16 before mset; branch targets annotated.
    stz T_MY
@row:
    .a16
    .i16
    stz T_MX
@col:
    .a16
    .i16
    ldx T_MX                    ; X = col
    sep #$20
    .a8
    lda T_MY                    ; A = row (0..31)
    cmp f:hmap, x               ; row - hmap[col]; C set if row >= ground top
    bcc @sky                    ; row above the ground -> sky
    cmp #GND_DIRT               ; (A still = row) ground: dirt at/below GND_DIRT
    bcs @dirt
    cpx #6                      ; mountain region cols 6..12
    bcc @grass
    cpx #13
    bcs @grass
    lda #3                      ; mountain (grey)
    bra @settile
@grass:
    .a8
    lda #2                      ; grass (green)
    bra @settile
@dirt:
    .a8
    lda #4                      ; dirt (brown)
    bra @settile
@sky:
    .a8
    lda #1                      ; sky (light blue)
@settile:
    .a8
    rep #$30
    .a16
    .i16
    and #$00FF
    sta T_TILE
    mset #1, T_MX, T_MY, T_TILE     ; ONLY BG1's map — BG2 shares it
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

    ; --- camera + seam state ---
    lda #CAM_A0
    sta CAM_A
    lda #CAM_B0
    sta CAM_B
    lda #SEAM0
    sta SEAM
    sf_split_v_cameras CAM_A, CAM_B

    ; --- the split + coloured seam (or, under -DNO_WINDOW, the single camera) ---
.ifdef NO_WINDOW
    sf_split_v_off              ; non-vacuity control: no window -> BG1 fills the screen
.elseif .defined(DIAGONAL)
    ; slanted coloured seam: WH0/WH2/WH3 HDMA'd per scanline (0.5 px/scanline)
    sf_split_v_diagonal DIAG_BASE, DIAG_SLOPE, BAND_HW, 0
.else
  .ifdef OBJ_CLIP
    sf_split_v_colorseam SEAM0, BAND_HW, 1     ; + per-half OBJ clipping
  .else
    sf_split_v_colorseam SEAM0, BAND_HW, 0
  .endif
.endif

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

.ifdef AUTODEMO
    ; --- self-running: seam FIXED at centre; pan the two cameras independently
    ;     (A right +1, B left -2) — the classic split-screen look. Input ignored. ---
    lda CAM_A
    inc a
    and #$00FF
    sta CAM_A
    lda CAM_B
    dec a
    dec a
    and #$00FF
    sta CAM_B
    jmp @commit
.endif

    ; --- camera A (BG1, left) <- P1 (port 0) D-pad ---
    btn #BTN_RIGHT, #0
    cmp #1
    bne :+
    lda CAM_A
    clc
    adc #CAM_SPD
    and #$00FF
    sta CAM_A
:   btn #BTN_LEFT, #0
    cmp #1
    bne :+
    lda CAM_A
    sec
    sbc #CAM_SPD
    and #$00FF
    sta CAM_A
:   ; --- camera B (BG2, right) <- P2 (port 1) D-pad ---
    btn #BTN_RIGHT, #1
    cmp #1
    bne :+
    lda CAM_B
    clc
    adc #CAM_SPD
    and #$00FF
    sta CAM_B
:   btn #BTN_LEFT, #1
    cmp #1
    bne :+
    lda CAM_B
    sec
    sbc #CAM_SPD
    and #$00FF
    sta CAM_B
:   ; --- seam <- P1 shoulders (clamped to [SEAM_LO, SEAM_HI]) ---
    btn #BTN_R, #0
    cmp #1
    bne :+
    lda SEAM
    cmp #SEAM_HI
    bcs :+
    inc a
    sta SEAM
:   btn #BTN_L, #0
    cmp #1
    bne :+
    lda SEAM
    cmp #(SEAM_LO+1)
    bcc :+
    dec a
    sta SEAM
:   ; --- commit cameras + seam ---
@commit:
    .a16
    .i16
    sf_split_v_cameras CAM_A, CAM_B
.ifndef NO_WINDOW
  .ifndef DIAGONAL                ; the diagonal seam owns WH0/WH2/WH3 via HDMA
    sf_split_v_move SEAM, BAND_HW
  .endif
.endif

    spr_clear
.ifndef NO_WINDOW
    ; --- player markers (red): P1 straddles the seam (the OBJ-clip subject),
    ;     P2 stands in the right half ---
    lda SEAM
    sec
    sbc #4
    sta MKX
    spr #1, MKX, #PLY_Y, #$00, #2      ; P1 marker, straddling the seam
    lda SEAM
    clc
    adc #PLY_DX
    sta MKX
    spr #1, MKX, #PLY_Y, #$00, #2      ; P2 marker, right half
.endif

    sf_frame_end
    jmp game_loop

; --- 4 solid 4bpp tiles, colour indices 1..4 (generated) --------------------
solid_tiles:
.repeat 4, I
    .repeat 8
        .byte (((I+1) & 1) <> 0) * $FF, ((((I+1) >> 1) & 1) <> 0) * $FF
    .endrepeat
    .repeat 8
        .byte ((((I+1) >> 2) & 1) <> 0) * $FF, ((((I+1) >> 3) & 1) <> 0) * $FF
    .endrepeat
.endrepeat

; --- height map: ground-top row per world column (0=top .. 31=bottom). A tall
;     central mountain (cols ~6-12) flanked by rolling hills — an asymmetric
;     silhouette so the two cameras frame visibly different vistas of one world.
hmap:
    .byte 18,18,17,16,15,13,11, 9, 8, 8, 9,11,13,15,16,17
    .byte 17,16,15,14,14,15,16,17,17,16,15,15,16,17,18,18

player_tile:                    ; solid index 1, 8x8 (red via OBJ palette slot 1)
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.ifdef DIAGONAL
.include "hdma_alloc.asm"        ; hdma_alloc_init / hdma_alloc (diagonal seam)
.include "hdma_engine.asm"       ; hdma_build_split_diag + _hdma_enable_channel
.endif
