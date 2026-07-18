; =============================================================================
; dialog_test — run-gate for the sf_dialog opaque-panel macros
; =============================================================================
; Renders a BG1 scene (a solid green wall fill across the whole BG1 tilemap), a
; line of HUD text, and an opaque dialog panel toggled by the test harness:
;   - A pressed (edge) -> sf_dialog_open #4,#18,#24,#7 + a message line
;   - B pressed (edge) -> sf_dialog_close   (restore the scene under the panel)
; The panel must be OPAQUE (no green BG1 shows through inside it) and composite
; ABOVE BG1 (the panel + its text are BG3 priority tiles under BGMODE $09).
;
; Done-condition (emulator-verifiable, rendered output only):
;   - boots ($7E:E000 == "SFDB")
;   - BEFORE open: the panel region of the screen is GREEN (BG1 wall shows)
;   - AFTER A (open): the panel region is the panel-body color (NOT green) and
;     the border ring is the border color — the box is opaque + framed
;   - the message text renders (non-background pixels) inside the panel
;   - AFTER B (close): the panel region is GREEN again (scene fully restored)
;   - frame heartbeat at $7E:E010 advances; $7E:E012 mirrors the panel-open flag
;
; Debug region map ($7E:E000):
;   +$10  frame heartbeat (FRAME_COUNTER)
;   +$12  panel-open flag mirror (1 while open)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_text.inc"          ; sf_text_init, print
.include "sf_dialog.inc"        ; sf_dialog_init, sf_dialog_open, sf_dialog_close
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

JOY_A      = $0080              ; JOY1_PRESSED_LATCH bit (A button)
JOY_B      = $8000              ; JOY1_PRESSED_LATCH bit (B button)

; panel-open flag (game state, DP byte in the template range)
DLG_OPEN_FLAG = $32

; BG1 fill loop counters (game-array region, abs-reachable with DB=$00)
fill_x = $1800
fill_y = $1802

; panel geometry (cells)
PANEL_COL = 4
PANEL_ROW = 18
PANEL_W   = 24
PANEL_H   = 7

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

    ; --- font + dialog assets, all under the boot forced blank ---
    sf_text_init                ; kit font -> BG3 VRAM
    sf_dialog_init              ; box CHR + panel palette -> BG3 VRAM / CGRAM

    ; --- BG1 wall: a solid green tile filling the whole BG1 tilemap ---
    ; tile 1 = solid green; BG1 palette 0 color 1 = green.
    sf_load_bg_tile 1, green_tile
    sf_bg_color 0, 1, $03E0     ; BG1 pal0 color 1 = green (15-bit BGR)
    sf_bg_color 0, 0, $0000     ; backdrop black

    jsr init_ppu                ; screen ON, gfxmode-equivalent BG setup
    gfxmode #1                  ; Mode 1, BG3 priority — ZEROS BG3 shadow

    ; fill the visible BG1 with the green wall tile (32x28). mset takes memory/
    ; immediate operands (not CPU registers), so the row/col counters live in
    ; WRAM scratch words and are passed by address.
    rep #$30
    .a16
    .i16
    stz fill_y
@fill_row:
    stz fill_x
@fill_col:
    mset #1, fill_x, fill_y, #1 ; BG1 (layer 1), (fill_x,fill_y), tile 1
    lda fill_x
    inc a
    sta fill_x
    cmp #32
    bcc @fill_col
    lda fill_y
    inc a
    sta fill_y
    cmp #28
    bcc @fill_row

    ; a HUD line so the BG3 text layer is exercised independently of the panel
    print hud_msg, #8, #8

    stz DLG_OPEN_FLAG

    sf_debug_magic

    ; enable NMI + auto-joypad
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for NMI; latch input

    ; --- A edge -> open the panel; B edge -> close it ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq @no_a
    sf_dialog_open #PANEL_COL, #PANEL_ROW, #PANEL_W, #PANEL_H
    print dlg_msg, #((PANEL_COL + 2) * 8), #((PANEL_ROW + 2) * 8)
    lda #1
    sta DLG_OPEN_FLAG
@no_a:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_B
    beq @no_b
    sf_dialog_close
    stz DLG_OPEN_FLAG
@no_b:
    .a16

    ; --- mirrors: heartbeat + panel-open flag ---
    ldx #$0000
    lda FRAME_COUNTER
    sta f:$7E0000 + $E010, x
    lda DLG_OPEN_FLAG
    and #$00FF
    sta f:$7E0000 + $E012, x
    jmp game_loop

green_tile:
    ; 4bpp solid tile, all pixels = color index 1 (32 bytes).
    ; bitplane0 all $FF (low bit set), planes 1-3 zero -> every pixel = 1.
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00

hud_msg:
    .byte "DIALOG DEMO", 0
dlg_msg:
    .byte "HELLO ADVENTURER", 0

.include "ppu_init.inc"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
.include "sf_dialog_data.inc"
