; =============================================================================
; bend_v_test — run-gate for the V-axis sf_tunnel_v / SF_CURVE_HORIZON (v1.2)
; =============================================================================
; The VERTICAL-axis (BGnVOFS) mirror of bend_test.asm. Where the H demo carries
; vertical stripes so a per-scanline HORIZONTAL shift is visible, this demo
; carries HORIZONTAL bands (8px-on/8px-off, 16px period) so a per-scanline
; VERTICAL shift is visible: every scanline gets a vertical offset =
;   horizon[(scanline + phase) & $FF] * amp / 128
; The HORIZON curve is a RECIPROCAL / 1-over-z perspective (v1.2-R): its
; per-scanline SLOPE is STEEPEST at the top (the far horizon) and saturates
; toward the bottom, so successive rows map to nearly the SAME source line just
; below the horizon (rows bunch DRAMATICALLY — compressed, >=4x) and spread wide
; toward the foreground — a barrel / perspective horizon. sf_bend_tick rolls
; the phase every frame so the ground flows toward the viewer (the marquee V
; tunnel).
;
; HORIZON FRAMING (v1.2-R R2): the demo reads as a HORIZON, not full-screen
; stripes — the top SKY_ROWS rows are SKY (tile 0 → sky-blue backdrop), then a
; bright HORIZON LINE (tile 2), then the perspective GROUND bands below. The
; HDMA curve compresses the whole BG but the compression is most dramatic right
; below the horizon line, exactly where a receding ground plane bunches.
;
; A flat BG would show the bands EVENLY spaced down the frame (constant period);
; the V bend must measurably VARY the band spacing per scanline (PRIMARY a), and
; the per-scanline pattern must ADVANCE between two screenshots N frames apart
; (PRIMARY b — the roll).
;
; CLEAN-RENDER NOTE (V-DONE): per-line BGnVOFS remaps source rows non-uniformly,
; so some source rows repeat / skip. With SOLID horizontal bands (no fine
; vertical detail within a band) the repeat/skip is invisible — there is no torn
; garbage, only the band EDGES move. That is the documented tile-art constraint
; for V-axis bends (see guides/hdma_bend_tunnel.md).
;
; Done-condition (emulator-verifiable, read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = allocated HDMA channel (3..7)
;   - $7E:E010 = frame heartbeat (advances)
;   - horizontal band spacing VARIES down the frame following the horizon curve
;   - the per-scanline displacement pattern advances between frames (roll)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_bend_v / sf_tunnel_v / sf_bend_tick
.include "engine_state.inc"

BG_GREEN  = $03E0               ; 15-bit BGR green band colour
BG_SKY    = $7000               ; 15-bit BGR sky blue (backdrop, CGRAM 0)
BG_HLINE  = $7FFF               ; 15-bit BGR white horizon line
BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A

SKY_ROWS  = 6                   ; top 6 tile rows (48px) = sky; row 6 = horizon
                                ; line; rows 7..27 = perspective ground bands

BEND_AMP   = 128               ; peak vertical squash. amp scale is |curve|*amp/128
                                ; (amp is a FULL BYTE, NOT capped at 15 — that is
                                ; only the gentle H range). 128 gives ~127px of
                                ; offset headroom so the reciprocal curve bunches
                                ; ground rows ~4x just below the horizon (the
                                ; dramatic barrel). The full 32-row ground fill
                                ; keeps the deep-pulled foreground clean (no wrap
                                ; gap). 127*128=16256 < 32767 → no signed overflow.
BEND_SPEED = 2                  ; phase roll per frame (the V tunnel advance)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; uploads under the coldstart forced blank (before screen-on)
    sf_load_bg_tile 1, bg_tile  ; BG1 CHR: tile 1 = SOLID colour index 1 (ground band)
    sf_load_bg_tile 2, hline_tile ; tile 2 = SOLID colour index 2 (horizon line)
    sf_bg_color 0, 0, BG_SKY    ; CGRAM 0 (universal backdrop) = sky blue → tile 0
    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green ground band
    sf_bg_color 0, 2, BG_HLINE  ; BG palette 0, slot 2 = white horizon line

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- HORIZON-FRAMED field (v1.2-R R2): per tilemap row my (0..31)
    ;       my <  SKY_ROWS      → tile 0  (transparent → sky-blue backdrop = SKY)
    ;       my == SKY_ROWS      → tile 2  (solid white = the HORIZON LINE)
    ;       my >  SKY_ROWS      → tile 1  (GROUND band tile: 4px green / 4px gap
    ;                             baked IN the tile → an 8px source period, so the
    ;                             perspective resolves MANY bands across the field
    ;                             — fine compressed bands at the horizon, spreading
    ;                             to wider foreground bands; solid 4px stripes so
    ;                             the per-line V remap shows only as moving EDGES,
    ;                             never torn interior detail).
    ;     The reciprocal curve bunches the ground rows hardest just below the
    ;     horizon line, so the framing reads as "horizon + receding ground". ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
    ; pick this row's tile by region (BG_TILE), then fill the whole row
    lda BG_MY
    cmp #SKY_ROWS
    bcc @sky                    ; my < SKY_ROWS → sky
    beq @hline                  ; my == SKY_ROWS → horizon line
    lda #1
    sta BG_TILE                 ; ground: the 4px-period band tile (every row)
    bra @fill
@sky:
    .a16
    .i16
    stz BG_TILE                 ; tile 0 → sky backdrop
    bra @fill
@hline:
    .a16
    .i16
    lda #2
    sta BG_TILE                 ; tile 2 → white horizon line
@fill:
    .a16
    .i16
@col:
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #32                      ; fill ALL 32 tilemap rows with ground bands below
                                 ; the horizon — so the large V offset, which pulls
                                 ; source rows from deep in the 256px tilemap into
                                 ; the foreground, always finds BAND content (no
                                 ; empty backdrop wrap-gap, no second horizon line)
    bne @row

    ; --- BG1 at world-zero scroll; the V bend is the only vertical motion ---
    scroll #1, #0, #0

    ; --- arm the ANIMATED horizon squash on BG1's VERTICAL axis (the marquee) ---
    sf_tunnel_v #SF_CURVE_HORIZON, #BEND_AMP, #BEND_SPEED
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the allocated channel for the test

    sf_debug_magic

    ; enable NMI + auto-joypad (same VBlank-edge handshake as bend_test.asm).
    sep #$20
    .a8
    lda $4210                   ; ack pending NMI (read-clear)
@wait_vblank_end:
    lda $4212                   ; HVBJOY
    bmi @wait_vblank_end        ; bit 7 = 1 → still in VBlank
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for NMI; latch input

    sf_bend_tick                ; roll the curve phase + rebuild the table

    ; --- frame heartbeat for the test ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; ground band tile (tile 1): a 4px GREEN / 4px gap split baked into the 8x8 tile
; → an 8px source band period (vs the old 16px tilemap-alternated period). The
; finer period lets the reciprocal perspective resolve MANY bands across the
; field. Rows 0-3 = colour index 1 (plane0=$FF), rows 4-7 = index 0 (transparent
; → sky backdrop shows through as the gap). Solid 4px stripes so the per-line V
; remap shows only as moving band EDGES, no interior detail to tear.
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00    ; rows 0-3: plane0=$FF (index 1 green)
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; rows 4-7: index 0 (gap)
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; planes 2-3 = 0
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; horizon-line tile (tile 2): every pixel colour index 2 → plane1=$FF on all 8
; rows (planes 0/2/3 = 0). A solid bright bar marking the horizon scanline.
hline_tile:
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF    ; rows 0-7: plane1=$FF (index 2)
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; planes 2-3 = 0
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
