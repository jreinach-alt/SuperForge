; =============================================================================
; sf_meta.inc — metasprite draw (macro library)
; =============================================================================
; Draws actors LARGER than one hardware sprite (up to 64x64) from the
; multi-part tables `tools/png2snes.py sprite --meta` emits: per frame a
; parts table (count, then per part: tile-offset word, dx, dy, large flag),
; plus `<name>_parts_index` mapping frame -> table address.
;
; HARD REQUIREMENT: OBSEL size pair 3 ($2101 = $60 — 16x16 small / 32x32
; large). The converter tiles every box into those two part sizes. Set it
; after init_ppu under a brief forced blank (see tests/meta_test.asm).
;
; The 9-bit OAM tile is handled BY CONSTRUCTION: part offsets can exceed 255,
; and the macro routes tile bit 8 into the OAM attribute's name-select bit
; (spr flags bit 0) — no caller has to know that lesson.
;
; OAM SLOT BUDGET: a metasprite consumes one OAM slot PER PART, and the part
; count VARIES per frame (empty 16x16 regions are skipped at convert time).
; That breaks the stable-slot idiom for anything drawn AFTER it — draw
; metasprites LAST in the frame, after all fixed-slot actors.
;
; Animating: keep a frame word + tick word (sf_anim.inc); meta anim tables
; hold FRAME INDICES — look the parts table address up per frame:
;
;       sf_anim_step  BTICK, BFRAME, #8, #brick_anim_Attack_len
;       sf_anim_tile  brick_anim_Attack, BFRAME    ; A = frame index
;       asl a
;       tax
;       lda f:brick_parts_index, x                 ; -> parts table address
;       sta MPTR                                   ; (a DP word you own)
;       sf_meta_draw  MPTR, BX, BY, #BRICK_BASE, 1, #2
;
; Scratch contract: uses WRAM $0536-$0539 (SF_META_CUR/CNT — between
; sf_text's SF_DEC_BUF ($0530-$0535) and the engine's DMA staging area at
; $0540; both neighbors verified). Not reentrant; main-thread only.
;
; Requires (linked): engine/sprite_engine.asm (engine_spr) +
; engine/engine_state.inc. sf_sprite.inc supplies the API-block offsets.
; =============================================================================

.ifndef SF_META_INC
SF_META_INC = 1

.include "sf_sprite.inc"        ; SF_SPR_* API-block offsets (+ spr/spr_clear)

SF_META_CUR = $0536             ; parts-table cursor (word)
SF_META_CNT = $0538             ; parts remaining (word)

; -----------------------------------------------------------------------------
; sf_meta_draw ptr, x, y, base, pal, pri — draw one metasprite frame.
; -----------------------------------------------------------------------------
;   ptr   a DP WORD holding the frame's parts-table address (from
;         <name>_parts_index; (dp),y addressing — must live in direct page)
;   x, y  actor top-left, verbatim operands (DP words or immediates)
;   base  the sf_load_obj_chr base tile, verbatim (`#BRICK_BASE`)
;   pal   OBJ palette 0-7 — assemble-time CONSTANT (folded into the flags)
;   pri   BG priority, verbatim (`#2`)
; Emits one engine_spr call per part (slots in call order, like spr).
; Clobbers A, X, Y + SF_META_CUR/CNT.
;
; WIDTH-RISK: asserts A16/I16 entry and stays A16/I16 the whole loop — the
; table's byte fields are read with WORD loads and masked (dx|dy as a pair,
; large with a stray high byte), so there is no sep/rep inside the loop.
; engine_spr is rep #$30 in / A16 out. PHA/PLA balanced within each pass.
.macro sf_meta_draw sf_ptr, sf_x, sf_y, sf_base, sf_pal, sf_pri
    .local mp_loop, mp_small, mp_done
    rep #$30
    .a16
    .i16
    lda (sf_ptr)                ; offset 0: count byte (+ stray high byte)
    and #$00FF
    sta SF_META_CNT
    beq mp_done
    ldy #$0001                  ; cursor: first part record
    sty SF_META_CUR
mp_loop:
    .a16
    ldy SF_META_CUR
    lda (sf_ptr), y             ; tile-offset word
    clc
    adc sf_base
    sta SF_SPR_TILE             ; engine takes the low 8 bits as the OAM tile
    xba
    and #$0001                  ; tile bit 8 -> name-select (flags bit 0)
    ora #((sf_pal) << 1)        ; + palette bits 3:1
    sta SF_SPR_FLAGS
    iny
    iny
    lda (sf_ptr), y             ; dx | dy<<8
    pha
    and #$00FF
    clc
    adc sf_x
    sta SF_SPR_X
    pla
    xba
    and #$00FF
    clc
    adc sf_y
    sta SF_SPR_Y
    iny
    iny
    lda (sf_ptr), y             ; large flag (+ stray high byte)
    and #$00FF
    beq mp_small
    lda SF_SPR_FLAGS
    ora #$0080                  ; large size select (32x32 under pair 3)
    sta SF_SPR_FLAGS
mp_small:
    .a16
    iny                         ; -> next part record
    sty SF_META_CUR
    lda sf_pri
    sta SF_SPR_PRI
    jsr engine_spr              ; A16 out; clobbers A, X, Y
    lda SF_META_CNT
    dec a
    sta SF_META_CNT
    beq mp_done
    jmp mp_loop
mp_done:
    .a16
.endmacro

.endif ; SF_META_INC
