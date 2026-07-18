; =============================================================================
; sf_sprite.inc — sprite macros (macro library, rung A1)
; =============================================================================
; The Action-realm sprite API. These macros place sprites into the engine's
; shadow OAM. The keystone calling convention is realized INLINE here: a macro
; marshals its arguments into the engine's API parameter block (DP $60+) and
; `jsr`s the engine function directly. The macro *is* the call site — there is
; no separate wrapper layer in this repo (the compiler-era _engine_wrap_*
; indirection is superseded; calling the engine directly keeps each ROM's link
; set to only the engine modules it actually uses).
;
; The sprite *render* path (shadow OAM -> hardware OAM via VBlank DMA) is the
; frame loop's job (rung A2). These macros produce engine_spr's direct output:
; the WRAM shadow OAM tables + SPRITE_COUNT + OAM_DIRTY.
;
; Requires (linked into the ROM): engine/engine_state.inc (equates) and
; engine/sprite_engine.asm (engine_spr, engine_spr_clear).
;
; Shadow OAM contract (what these macros produce; from sprite_engine.asm):
;   SHADOW_OAM_BASE $0300  128 x 4 bytes  (X-low, Y, tile, attr)
;   SHADOW_OAM_HI   $0500  128 x 2 bits   (X bit8, size select)
;   SPRITE_COUNT    $0130  active count
;   OAM_DIRTY       $0132  1 = shadow changed since last resolve
; =============================================================================

.ifndef SF_SPRITE_INC
SF_SPRITE_INC = 1

; Sprite API-block offsets (DP). These mirror sprite_engine.asm's SPR_API_*
; and are declared here so the macro is self-describing and the operands
; resolve as direct-page regardless of include order.
SF_SPR_TILE     = $60           ; tile index (low byte)
SF_SPR_X        = $64           ; X position (9-bit)
SF_SPR_Y        = $68           ; Y position (low byte)
SF_SPR_FLAGS    = $6C           ; attribute flags: size(7) Hflip(6) .. PPPn(3:0)
SF_SPR_PRI      = $70           ; BG priority (0-3)

; -----------------------------------------------------------------------------
; spr tile, x, y, flags, pri — place one sprite into the next shadow OAM slot.
; -----------------------------------------------------------------------------
;   tile   tile index 0-255
;   x      X position 0-511 (bit 8 -> hi-table X9, handled by the engine)
;   y      Y position 0-255
;   flags  bit7 = large-size select, bit6 = H-flip, bits3:0 = palette/name
;   pri    BG priority 0-3
;
; Operands are passed VERBATIM into a 16-bit load, so each accepts any ca65
; addressing form: an immediate (`#$42`, `#TILE`), a memory variable
; (`player_x`), or a DP slot. The caller supplies `#` for constants. This is
; the design's C3 form — the hand-written expansion is exactly these stores,
; and it lets the position be a runtime variable (needed from A2 onward).
;
; Leaves the engine's return (slot 0-127, or $FFFF if OAM is full) in A.
; Clobbers A, X, Y.
;
; OAM slot identity: slots are assigned in CALL ORDER after each spr_clear --
; first spr this frame = slot 0, next = slot 1, ... If you skip a draw (a
; dead enemy), later actors COMPACT into earlier slots. Tests reading OAM
; should identify actors by position (e.g. their fixed y), not slot number.
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default). engine_spr requires
; rep #$30 on entry and returns A16; this macro satisfies that contract for
; any caller width.
.macro spr sf_tile, sf_x, sf_y, sf_flags, sf_pri
    rep #$30
    .a16
    .i16
    lda sf_tile
    sta SF_SPR_TILE
    lda sf_x
    sta SF_SPR_X
    lda sf_y
    sta SF_SPR_Y
    lda sf_flags
    sta SF_SPR_FLAGS
    lda sf_pri
    sta SF_SPR_PRI
    jsr engine_spr              ; -> shadow OAM; slot # in A
.endmacro

; -----------------------------------------------------------------------------
; spr_clear — hide all 128 sprites (Y=$F0), reset SPRITE_COUNT, mark dirty.
; -----------------------------------------------------------------------------
; Call once per frame (or during setup) before placing sprites so stale slots
; are off-screen. Clobbers A, X.
;
; SLOT-ORDER CONTRACT: each `spr` after a `spr_clear` takes the next OAM slot,
; starting at 0 — so the 1st `spr` is hardware OAM slot 0 (bytes 0..3), the 2nd
; is slot 1 (bytes 4..7), and so on. Rely on this for "which sprite is which"
; (e.g. read OAM slot 0 for the player). The draw *order* is the slot order.
;
; WIDTH-RISK: engine_spr_clear sets its own widths internally and returns
; A16/I16; entering A16/I16 here keeps the contract explicit.
.macro spr_clear
    rep #$30
    .a16
    .i16
    jsr engine_spr_clear
.endmacro

.endif ; SF_SPRITE_INC
