; =============================================================================
; anim_test — run-gate for sf_anim (animation clock + H-flip facing)
; =============================================================================
; Animates REAL converted art: Arthur's 4-step idle (camelot pack, 32x32)
; plays at rate 8 at screen (100,100); facing flips every 64 frames via the
; documented H-flip idiom. OBSEL pair 3 (16/32) as in png2snes_sprite_test.
;
; Debug mirrors (for the pytest):
;   $7E:E010  current anim step index (0..3)
;   $7E:E012  current tile offset from sf_anim_tile
;   $7E:E014  facing (0 right / 1 left)
;
; Done-condition (emulator-verifiable):
;   - boots; OAM slot 0 tile cycles through base+{$00,$04,$08,$0C} IN ORDER
;     at ~8 frames per step (rendered sprite present at (100,100))
;   - OAM slot 0 attr bit 6 (H-flip) tracks the facing mirror
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_anim.inc"          ; sf_anim_step, sf_anim_tile
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"

ARTHUR_BASE = 0                 ; OBJ tiles 0-255 (16 frames @ 32x32)

ATICK  = $32                    ; animation clock (DP)
AFRAME = $34                    ; animation step index
FACING = $36                    ; 0 = right, 1 = left (H-flip)
FTIMER = $38                    ; facing flip timer
PTILE  = $3A                    ; computed OAM tile for spr
PFLAGS = $3C                    ; computed spr flags

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_obj_chr ARTHUR_BASE, arthur_chr, arthur_chr_bytes
    sf_load_obj_pal 0, arthur_pal

    jsr init_ppu

    ; OBSEL pair 3: small = 16x16, large = 32x32 (brief forced blank)
    sep #$20
    .a8
    lda #$80
    sta $2100
    lda #$60
    sta $2101
    lda #$0F
    sta $2100
    rep #$30
    .a16
    .i16

    stz ATICK
    stz AFRAME
    stz FACING
    stz FTIMER
    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- the animation clock: idle, 4 steps, one step per 8 frames ---
    sf_anim_step ATICK, AFRAME, #8, #arthur_anim_idle_len

    ; --- flip facing every 64 frames ---
    lda FTIMER
    inc a
    sta FTIMER
    cmp #64
    bcc no_flip
    stz FTIMER
    lda FACING
    eor #$0001
    sta FACING
no_flip:
    .a16

    ; --- current tile + the facing flags idiom from sf_anim.inc ---
    sf_anim_tile arthur_anim_idle, AFRAME
    clc
    adc #ARTHUR_BASE
    sta PTILE
    lda #$0080                  ; large (32x32 under pair 3)
    ldx FACING
    beq face_done
    ora #$0040                  ; facing left -> H-flip
face_done:
    .a16
    sta PFLAGS

    ; --- mirrors for the test ---
    ldx #$0000
    lda AFRAME
    sta f:$7E0000 + $E010, x
    lda PTILE
    sta f:$7E0000 + $E012, x
    lda FACING
    sta f:$7E0000 + $E014, x

    spr_clear
    spr PTILE, #100, #100, PFLAGS, #2
    sf_frame_end
    sf_debug_complete
    jmp game_loop

; --- converted art (committed png2snes output; regen-guarded by pytest) ---
.include "fixtures/png2snes/arthur_anim.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
