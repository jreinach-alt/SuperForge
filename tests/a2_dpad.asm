; =============================================================================
; a2_dpad.asm — macro library rung A2: move a sprite with the d-pad
; =============================================================================
; The end-to-end keystone proof. It runs a real 60fps game loop driven entirely
; by macros: read the controller (btn), update a position, draw a sprite, and
; let the frame loop push the shadow OAM to HARDWARE OAM over VBlank DMA. The
; gate verifies the rendered output (SnesSpriteRam) MOVES in response to
; injected input — the direct, indirect-evidence-compliant proof of
; "move it with the d-pad."
;
; Structure:
;   RESET -> sf_coldstart        (boot + WRAM clear)
;         -> sf_engine_init      (DMA budget, queue ptr, sync flags, counters)
;         -> jsr init_ppu        (Mode 1 + OBJ + OAMADD=0 + screen on)
;         -> spawn player at (120,100); sf_debug_magic (boot marker)
;         -> enable NMI + auto-joypad ($4200 = $81)
;   game_loop:
;         sf_frame_begin         (wait VBlank + DMA drain, latch input)
;           btn #BTN_RIGHT/LEFT/DOWN/UP -> adjust player_x/y by PLAYER_SPEED
;           spr_clear ; spr #TILE, player_x, player_y, #0, #2
;         sf_frame_end           (resolve OAM + signal -> next NMI DMAs to HW)
;         bra game_loop
;
; Build (from repo root):
;   ca65 --cpu 65816 -I infrastructure/rom_template -I asm_repo_staging/lib/macros \
;        -I engine asm_repo_staging/tests/a2_dpad.asm -o a2.o
;   ld65 -C infrastructure/rom_template/lorom.cfg a2.o -o a2.sfc
;
; Verify (MesenRunner): boot -> SnesSpriteRam[0..1] near (120,100); inject
; Right N frames -> slot-0 X increases; inject Left N frames -> X decreases.
; =============================================================================

.p816
.smart

.include "header.inc"

; --- macro library ---
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end

; --- engine equates ---
.include "engine_state.inc"

; --- game state (DP scratch; main-thread DP=$0000, untouched by the engine) ---
PLAYER_X     = $32              ; 16-bit X position
PLAYER_Y     = $34              ; 16-bit Y position
PLAYER_TILE  = $20             ; arbitrary OBJ tile index
PLAYER_SPEED = 2

.segment "CODE"

; The real VBlank handler IS the NMI vector body (sets NMI_DONE_FLAG, drains
; the OAM DMA queue, reads auto-joypad into JOY1_CURRENT).
NMI:
.include "nmi_handler.asm"

; Stub for the unused COP/BRK/ABORT/IRQ vectors.
NMI_STUB:
    rti

RESET:
    sf_coldstart                ; native bring-up + WRAM clear
    sf_engine_init              ; engine state: budget, queue, flags, counters
    jsr init_ppu                ; Mode 1 + OBJ + OAMADD=0 + screen on

    ; spawn the player
    rep #$30
    .a16
    .i16
    lda #120
    sta PLAYER_X
    lda #100
    sta PLAYER_Y

    spr_clear                   ; all slots off-screen before the first draw
    sf_debug_magic              ; "SFDB" -> $7E:E000 (boot marker)

    ; enable NMI + auto-joypad
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- update: move with the d-pad ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PLAYER_X
    clc
    adc #PLAYER_SPEED
    sta PLAYER_X
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PLAYER_X
    sec
    sbc #PLAYER_SPEED
    sta PLAYER_X
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda PLAYER_Y
    clc
    adc #PLAYER_SPEED
    sta PLAYER_Y
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda PLAYER_Y
    sec
    sbc #PLAYER_SPEED
    sta PLAYER_Y
@no_up:

    ; --- draw: one sprite at the player position ---
    spr_clear
    spr #PLAYER_TILE, PLAYER_X, PLAYER_Y, #$00, #2

    sf_frame_end
    jmp game_loop               ; loop body exceeds bra's +/-127 range

; --- engine code linked into the ROM ---
.include "ppu_init.inc"         ; init_ppu
.include "input_handler.asm"    ; engine_btn / engine_btnp + bitmask table
.include "dma_scheduler.asm"    ; dma_queue_add / dma_queue_signal + DMA_STAGE_*
.include "sprite_engine.asm"    ; engine_spr / engine_spr_clear / engine_spr_resolve
