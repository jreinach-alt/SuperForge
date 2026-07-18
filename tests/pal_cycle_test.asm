; =============================================================================
; pal_cycle_test — run-gate for sf_pal / sf_pal_cycle / _stop / _tick
; =============================================================================
; BG1 carries four 64px vertical strips, each a solid tile of color index
; 1..4. CGRAM entries 1-4 are fed through sf_pal (RED, GREEN, BLUE, WHITE —
; the shadow path, per the file-header setup contract) and cycled with
; sf_pal_cycle #1, #4, #8 (rotate right every 8 frames). sf_pal_cycle_tick
; runs every frame BEFORE sf_frame_end (the documented ordering), bridging
; the SHADOW_CGRAM rotation to hardware CGRAM via the dirty-range GP-DMA.
; Pressing A (edge) stops all cycles — the colors must freeze in place.
;
; Done-condition (emulator-verifiable, rendered pixels only):
;   - boots ($7E:E000 == "SFDB"); frame heartbeat at $7E:E010 advances
;   - the 4 strips always show the 4 distinct colors as a cyclic rotation
;     of (RED, GREEN, BLUE, WHITE)
;   - the rendered color AT THE SAME SCREEN POSITION changes over time
;   - after A (stop): the same positions hold their colors (frozen)
;   - $7E:E014 mirrors the ROM state (1=cycling, 0=stopped)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_fx.inc"            ; sf_pal / sf_pal_cycle macro group
.include "engine_state.inc"

BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A

JOY_A     = $0080               ; JOY1_PRESSED_LATCH bit (A button)
CYC_SPEED = 8                   ; frames per rotation step

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

    ; --- BG1 CHR under the coldstart forced blank: tiles 1-4 = solid color
    ;     indices 1-4 ---
    sf_load_bg_tile 1, tile_idx1
    sf_load_bg_tile 2, tile_idx2
    sf_load_bg_tile 3, tile_idx3
    sf_load_bg_tile 4, tile_idx4

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- four 64px vertical strips: tile = (mx >> 3) + 1, rows 0-23
    ;     (192 px — inside the one-shot initial tilemap DMA budget, and the
    ;     strips sample well inside it) ---
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
    lsr
    inc a                       ; (mx >> 3) + 1 → tiles 1..4
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

    ; --- feed the cycled range through the SHADOW path (sf_pal marks the
    ;     range dirty; the first tick commits it to hardware CGRAM) ---
    sf_pal #1, #31, #0,  #0     ; entry 1 = RED
    sf_pal #2, #0,  #31, #0     ; entry 2 = GREEN
    sf_pal #3, #0,  #0,  #31    ; entry 3 = BLUE
    sf_pal #4, #31, #31, #31    ; entry 4 = WHITE

    ; --- arm the cycle: entries 1-4, rotate right every 8 frames ---
    sf_pal_cycle #1, #4, #CYC_SPEED

    ; state mirror: 1 = cycling
    lda #$0001
    ldx #$0000
    sta f:$7E0000 + $E014, x

    sf_debug_magic

    ; enable NMI + auto-joypad at a defined point in the frame (the
    ; parallax_test pattern: a first NMI mid-VBlank truncates the 1.5KB
    ; initial tilemap DMA — ack pending, wait for active display, enable).
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

    ; --- A edge → stop all cycles (colors must freeze on screen) ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq @no_stop
    sf_pal_cycle_stop
    lda #$0000
    ldx #$0000
    sta f:$7E0000 + $E014, x    ; state mirror: 0 = stopped
@no_stop:
    .a16
    sf_pal_cycle_tick           ; rotate + dirty-range CGRAM commit — MUST
                                ; run before sf_frame_end (ordering contract)

    ; --- heartbeat ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x

    sf_frame_end                ; spr resolve + dma_queue_signal (drains the
                                ; tick's CGRAM entry next VBlank)
    jmp game_loop

; --- four solid 8x8 4bpp tiles, all pixels = color index 1, 2, 3, 4 ---
; 4bpp row format: 16 bytes plane0/plane1 interleaved, then 16 bytes plane2/3.
tile_idx1:                      ; index 1 = plane0 set
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
tile_idx2:                      ; index 2 = plane1 set
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
tile_idx3:                      ; index 3 = planes 0+1 set
    .byte $FF,$FF, $FF,$FF, $FF,$FF, $FF,$FF
    .byte $FF,$FF, $FF,$FF, $FF,$FF, $FF,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
tile_idx4:                      ; index 4 = plane2 set
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "palette_engine.asm"
