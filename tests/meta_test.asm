; =============================================================================
; meta_test — run-gate for sf_meta_draw (multi-OBJ metasprites)
; =============================================================================
; Animates REAL converted art bigger than any hardware sprite: Brickhead's
; 48x48 attack (Four Seasons sprites pack), 6 parts per frame (one 32x32 +
; five 16x16), playing its 4 attack steps at rate 8 at screen (80,60).
; OBSEL pair 3 (16/32) per sf_meta.inc's hard requirement.
;
; A SECOND, static instance loads the same CHR at OBJ BASE 256 (the second
; name table) and draws frame 0 at X=479 (= -33 in 9-bit X): this exercises
; the two 9-bit paths a base-0 on-screen sprite never touches — tile bit 8
; -> the attribute name-select bit (audit-1 F-2) and X bit 8 -> the hi-table
; X9 bit (F-7). Its right edge pokes onto the left of the screen. (X=479
; keeps every part's x = 479+dx <= 511 inside the 9-bit range — bigger X
; would wrap parts to mid-screen — while showing content columns 33-41 of
; the box at screen x 0-14.)
; (Fixture note, audit-1 F-6: Brickhead's 48x48 Attack is this pack's real
; >32px-per-frame case; the dissection's "demon boss" sheets are composite
; 192x144 SHEETS of 24x24 frames, not big frames — the converter was
; spot-checked on them separately.)
;
; Debug mirrors: $7E:E010 = anim step index, $7E:E012 = parts-table address.
;
; Done-condition (emulator-verifiable):
;   - boots; OAM slots 0-5 hold the 6 parts at (80,60)+(dx,dy) per the
;     converter's table; hi-table size bits = large for part 0, small for
;     the rest
;   - the composited 48x48 region matches a PIL render of the SOURCE frame
;   - the anim cycles: part-0 tile steps $00,$04,$08,$0C in order
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_meta.inc"          ; sf_meta_draw (+ sf_sprite.inc)
.include "sf_anim.inc"          ; sf_anim_step, sf_anim_tile
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"

BRICK_BASE  = 0
BRICK_BASE2 = 256               ; second name table (tile bit 8 set)

BTICK  = $32                    ; animation clock (DP)
BFRAME = $34                    ; animation step index
MPTR   = $36                    ; current parts-table address (DP pointer)
MPTR2  = $38                    ; static instance's parts table (frame 0)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_obj_chr BRICK_BASE, brick_chr, brick_chr_bytes
    sf_load_obj_chr BRICK_BASE2, brick_chr, brick_chr_bytes
    sf_load_obj_pal 0, brick_pal

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

    stz BTICK
    stz BFRAME
    rep #$30
    .a16
    .i16
    lda #brick_f0_parts
    sta MPTR2
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

    sf_anim_step BTICK, BFRAME, #8, #brick_anim_Attack_len

    ; frame index -> parts-table address (the sf_meta.inc idiom)
    sf_anim_tile brick_anim_Attack, BFRAME      ; A = frame index (meta mode)
    asl a
    tax
    lda f:brick_parts_index, x
    sta MPTR

    ; mirrors for the test
    ldx #$0000
    lda BFRAME
    sta f:$7E0000 + $E010, x
    lda MPTR
    sta f:$7E0000 + $E012, x

    spr_clear
    sf_meta_draw MPTR, #80, #60, #BRICK_BASE, 0, #2
    ; static instance: base 256 (name bit) at X=479 (X9 set, left-edge peek)
    sf_meta_draw MPTR2, #479, #120, #BRICK_BASE2, 0, #2
    sf_frame_end
    sf_debug_complete
    jmp game_loop

; --- converted art (committed png2snes output; regen-guarded by pytest) ---
.include "fixtures/png2snes/brick_meta.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
