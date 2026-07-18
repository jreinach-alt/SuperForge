; =============================================================================
; sf_collision.inc — collision macros (macro library)
; =============================================================================
; AABB overlap testing over the engine's collision functions. The macro
; marshals its arguments into the API block and calls the engine fn directly
; (the macro is the wrapper — see sf_sprite.inc).
;
; Requires (linked into the ROM): engine/engine_state.inc (equates) and
; engine/collision_engine.asm (engine_col_box). engine_api.inc supplies the
; API block SSoT.
; =============================================================================

.ifndef SF_COLLISION_INC
SF_COLLISION_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; col_box  ax, ay, aw, ah,  bx, by, bw, bh  ->  A
; -----------------------------------------------------------------------------
; Axis-aligned bounding-box overlap test. Returns 1 in A if box A (left ax, top
; ay, width aw, height ah) overlaps box B, else 0. A box spans the half-open
; range [x, x+w); overlap is STRICT — boxes that merely touch edge-to-edge
; (A.right == B.left, i.e. 0px shared) return 0; they must share at least 1px.
; Coordinates are signed 16-bit pixels; w/h are sizes. Operands are passed
; verbatim, so each accepts an immediate (`#16`) or a memory variable
; (`player_x`).
; Clobbers A, X, Y.
; Idiom:  col_box player_x, player_y, #8, #8, dot_x, dot_y, #8, #8
;         beq  no_hit                          ; A==0 -> no overlap
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default). engine_col_box runs A16
; and returns A16 (1/0 in A).
.macro col_box ax, ay, aw, ah, bx, by, bw, bh
    rep #$30
    .a16
    .i16
    lda ax
    sta API_BLOCK_BASE + $00
    lda ay
    sta API_BLOCK_BASE + $04
    lda aw
    sta API_BLOCK_BASE + $08
    lda ah
    sta API_BLOCK_BASE + $0C
    lda bx
    sta API_BLOCK_BASE + $10
    lda by
    sta API_BLOCK_BASE + $14
    lda bw
    sta API_BLOCK_BASE + $18
    lda bh
    sta API_BLOCK_BASE + $1C
    jsr engine_col_box                 ; A = 1 (overlap) / 0
.endmacro

.endif ; SF_COLLISION_INC
