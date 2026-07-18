; =============================================================================
; sf_map.inc — tile-collision macros (macro library)
; =============================================================================
; Terrain collision against the tilemap: mark tile IDs with flags (solid,
; hazard, ...) and query the map by pixel position. Built over the engine's
; col_map, which reads the SHADOW tilemap (the same data mset writes and the
; NMI commits) and a 256-entry per-layer flag table indexed by tile ID.
;
; The flag tables live in WRAM (FLAG_TABLE_BG1-3) — sf_coldstart zeroes them,
; so every tile starts flag-free (nothing solid) and you opt tiles IN with
; sf_tile_flags. gfxmode (sf_bg.inc) sets the tilemap dimensions col_map
; bounds-checks against; queries outside the 32x32 map return 0.
;
; Flag convention: bit 0 = SOLID (SF_FLAG_SOLID, what sf_solid_box tests).
; Bits 1-7 are yours (hazard, water, ice, ...) — test them with col_map.
;
; Requires (linked into the ROM): engine/engine_state.inc and
; engine/collision_engine.asm (engine_col_map). engine_api.inc supplies the
; API block SSoT. Build the map with mset (sf_bg.inc) BEFORE querying it.
; =============================================================================

.ifndef SF_MAP_INC
SF_MAP_INC = 1

.include "engine_api.inc"

SF_FLAG_SOLID    = $01          ; bit 0: solid terrain (sf_solid_box's bit)
SF_FLAG_PLATFORM = $02          ; bit 1: one-way (jump-through) platform —
                                ;   consumed by sf_physics_step: lands from
                                ;   above, passes from below/sides, never
                                ;   blocks walking. Flag a tile with $02
                                ;   ONLY (a $03 tile is solid and blocks).

; -----------------------------------------------------------------------------
; sf_tile_flags tile_id, flags — give a tile ID its collision flags.
; -----------------------------------------------------------------------------
;   tile_id  0-255 (assemble-time constant — the CHR index you pass to mset;
;            tilemap palette/priority bits are masked off by the engine)
;   flags    flag byte (assemble-time constant; bit 0 = SF_FLAG_SOLID)
; Writes FLAG_TABLE_BG1[tile_id] AND FLAG_TABLE_BG2[tile_id] — the engine
; keeps a flag table PER LAYER, and the kit's two game surfaces are BG1
; (static maps) and BG2 (the right half of a scrolling level, sf_level.inc);
; one call flags a tile for both so col_map agrees on either page. (BG3 is
; the text layer — never flagged.) Call in setup, after sf_coldstart (whose
; WRAM clear zeroes the tables). Clobbers A, X.
; WIDTH-RISK: forces I16 (for the ldx) and toggles A8 for the byte writes;
; exits A16/I16.
.macro sf_tile_flags sf_tile, sf_flags
    rep #$10
    .i16
    ldx #$0000
    sep #$20
    .a8
    lda #(sf_flags)
    sta f:$7E0000 + FLAG_TABLE_BG1 + (sf_tile), x
    sta f:$7E0000 + FLAG_TABLE_BG2 + (sf_tile), x
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; col_map layer, x, y, flag -> A — test one flag bit at a pixel position.
; -----------------------------------------------------------------------------
;   layer  1-3 (verbatim — write `#1`; BG1 is the kit's game layer)
;   x, y   pixel coordinates, 16-bit (verbatim operands — `PX` or `#100`)
;   flag   bit INDEX 0-7 to test, not a mask (verbatim — `#0` tests
;          SF_FLAG_SOLID's bit; a tile flagged `sf_tile_flags 4, $02` is
;          tested with `col_map #1, X, Y, #1` — bit index 1 = mask $02)
; Returns 1 in A if the flagged bit is set for the tile under (x, y), else 0
; (out-of-bounds and unflagged tiles read 0). Clobbers A, X, Y.
; Idiom:  col_map #1, PX, PY, #0  /  bne blocked
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_col_map expects
; A16/I16 and returns A16 (0/1 in A).
.macro col_map sf_layer, sf_x, sf_y, sf_flag
    rep #$30
    .a16
    .i16
    lda sf_x
    sta API_BLOCK_BASE + $00
    lda sf_y
    sta API_BLOCK_BASE + $04
    lda sf_layer
    sta API_BLOCK_BASE + $08
    lda sf_flag
    sta API_BLOCK_BASE + $0C
    jsr engine_col_map             ; A = 1 (flag set) / 0
.endmacro

; -----------------------------------------------------------------------------
; sf_solid_box x, y -> A — is any corner of an 8x8 box on solid terrain (BG1)?
; -----------------------------------------------------------------------------
;   x, y   the box's top-left pixel position (memory operands, verbatim)
; Tests SF_FLAG_SOLID at all FOUR corners (x,y) (x+7,y) (x,y+7) (x+7,y+7) —
; the box spans 8 pixels, so the far corners are +7, not +8 (a +8 probe reads
; the NEIGHBOURING tile and sticks you to walls). Returns 1 in A if any corner
; is solid, else 0. This is the move-check primitive: compute the tentative
; position, test it, revert if blocked (see the maze template).
; Clobbers A, X, Y. Idiom:  sf_solid_box NEWX, PY  /  bne blocked
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); all corner math is A16;
; exits A16 (0/1 in A).
.macro sf_solid_box sf_x, sf_y
    .local hit, done
    rep #$30
    .a16
    .i16
    ; corner (x, y)
    lda sf_x
    sta API_BLOCK_BASE + $00
    lda sf_y
    sta API_BLOCK_BASE + $04
    lda #$0001
    sta API_BLOCK_BASE + $08       ; layer 1 (the game BG)
    stz API_BLOCK_BASE + $0C       ; flag bit 0 = SF_FLAG_SOLID
    jsr engine_col_map
    bne hit
    ; corner (x+7, y)
    lda sf_x
    clc
    adc #7
    sta API_BLOCK_BASE + $00
    lda sf_y
    sta API_BLOCK_BASE + $04
    lda #$0001
    sta API_BLOCK_BASE + $08
    stz API_BLOCK_BASE + $0C
    jsr engine_col_map
    bne hit
    ; corner (x, y+7)
    lda sf_x
    sta API_BLOCK_BASE + $00
    lda sf_y
    clc
    adc #7
    sta API_BLOCK_BASE + $04
    lda #$0001
    sta API_BLOCK_BASE + $08
    stz API_BLOCK_BASE + $0C
    jsr engine_col_map
    bne hit
    ; corner (x+7, y+7)
    lda sf_x
    clc
    adc #7
    sta API_BLOCK_BASE + $00
    lda sf_y
    clc
    adc #7
    sta API_BLOCK_BASE + $04
    lda #$0001
    sta API_BLOCK_BASE + $08
    stz API_BLOCK_BASE + $0C
    jsr engine_col_map
    bne hit
    lda #$0000                     ; all four corners clear
    bra done
hit:
    .a16
    lda #$0001
done:
    .a16
.endmacro

.endif ; SF_MAP_INC
