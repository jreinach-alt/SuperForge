; =============================================================================
; parallax_test — run-gate for sf_parallax_bands / sf_parallax_tick
; =============================================================================
; BG1 carries wide vertical stripes (32px on / 32px off — 64px period, so a
; screenshot shift is unambiguous up to 63px). Parallax splits the screen at
; scanline 112: the top band scrolls at ratio 0.25, the bottom band at 0.75,
; from one shared world-X. Holding RIGHT advances world-X 2px/frame; released,
; world-X stops — and the USER-VISIBLE FREEZE INVARIANT is that the rendered
; pixels stop moving in BOTH bands (the ratios are NOT zeroed; the table is
; rebuilt every frame from the unchanged world-X).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = allocated HDMA channel (3..7)
;   - holding RIGHT: top-band pixels shift by (world_x*0.25) px, bottom-band
;     pixels by (world_x*0.75) px — observably different rates (screenshots)
;   - released: consecutive frames are pixel-identical in both bands
;   - $7E:E010 mirrors world-X every frame (exact displacement ground truth)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_parallax_bands, sf_parallax_tick
.include "engine_state.inc"

BG_GREEN  = $03E0               ; 15-bit BGR green
BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A
WORLD_X   = $4C                 ; the shared parallax world-X

JOY_RIGHT = $0100               ; JOY1_CURRENT bit layout

PLX_YSPLIT    = 112             ; band boundary scanline
PLX_RATIO_TOP = $0040           ; 0.25 (64/256 — ratio = fraction byte n/256)
PLX_RATIO_BOT = $00C0           ; 0.75 (192/256)

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
    sf_load_bg_tile 1, bg_tile  ; BG1 CHR: tile 1 = solid colour index 1
    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- wide vertical stripes: tile = (mx >> 2) & 1 → 64px period.
    ;     24 rows (192 px), not the full 28: the engine's one-shot initial
    ;     tilemap DMA is never retried (the dirty bit clears after ONE
    ;     transfer), and the first NMI after $4200-enable can fire mid-VBlank
    ;     — a full 28-row 2KB transfer then overruns the VRAM write window
    ;     and the PPU silently drops the tail rows. 24 rows fits the window
    ;     even on a truncated first VBlank, and the bands sample well inside
    ;     192 px anyway ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    lsr
    lsr
    and #$0001                  ; 4 tiles on / 4 tiles off
    sta BG_TILE
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #24
    bne @row

    ; --- arm parallax on BG1 (world-X shadow is 0 from the coldstart) ---
    stz WORLD_X
    scroll #1, WORLD_X, #0      ; SHADOW_BG1HOFS = world-X feed
    sf_parallax_bands #1, #PLX_YSPLIT, #PLX_RATIO_TOP, #PLX_RATIO_BOT
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the allocated channel for the test

    sf_debug_magic

    ; enable NMI + auto-joypad — at a defined point in the frame. Enabling
    ; NMI while VBlank is already in progress fires the first NMI mid-VBlank
    ; and the 2KB initial tilemap DMA overruns the VRAM write window (the
    ; PPU drops the tail rows — silent truncation). Ack any pending NMI,
    ; wait for active display, then enable: the first NMI lands on a VBlank
    ; leading edge with the full window.
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

    ; --- RIGHT held → world-X += 2; released → world-X frozen ---
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq @no_advance
    lda WORLD_X
    inc a
    inc a
    sta WORLD_X
@no_advance:

    scroll #1, WORLD_X, #0      ; feed the shadow the bands derive from
    sf_parallax_tick            ; rebuild the 2-band HOFS table

    ; --- world-X ground truth for the test ---
    lda WORLD_X
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; one solid 8x8 4bpp tile (all colour index 1)
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
