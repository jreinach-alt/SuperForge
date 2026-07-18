; =============================================================================
; col_map_test — run-gate for the tile-collision macros (sf_map.inc)
; =============================================================================
; Builds a small map (a solid wall tile, an unflagged floor tile, a hazard
; tile with a non-solid flag bit), then queries it with col_map and
; sf_solid_box against hand-computed cases. Results land in the debug region
; for MesenRunner to read back.
;
; Map (tile cells; 1 cell = 8x8 px):
;   cell (5,5)  = tile 2  -> sf_tile_flags 2, SF_FLAG_SOLID   (wall)
;   cell (10,10)= tile 1  -> no flags                          (floor)
;   cell (12,5) = tile 3  -> sf_tile_flags 3, $02              (hazard, bit 1)
;
; Debug region map ($7E:E000):
;   +$10  col_map solid bit at wall px (40,40)        -> expect 1
;   +$12  col_map solid bit at empty px (80,80)... see +$14 — cell (10,10)
;         is the FLOOR tile: present but unflagged    -> expect 0
;   +$14  col_map solid bit at truly empty px (200,8) -> expect 0
;   +$16  col_map bit 1 at hazard px (96,40)          -> expect 1
;   +$18  col_map bit 0 at hazard px (96,40)          -> expect 0 (bit independence)
;   +$1A  col_map at out-of-bounds px (400,40)        -> expect 0
;   +$1C  sf_solid_box at (36,36): corner (43,43) is inside the wall -> expect 1
;   +$1E  sf_solid_box at (80,80): all corners clear  -> expect 0
;   +$20  sf_solid_box at (32,40): box spans px 32..39, wall starts at 40 —
;         edge-adjacent must NOT collide (+7 corner)  -> expect 0
;   +$22  TILEMAP_WIDTH_BG1 after gfxmode             -> expect 32 (byte)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset
.include "sf_map.inc"           ; col_map, sf_tile_flags, sf_solid_box
.include "engine_state.inc"

NEWX = $32                      ; scratch for the box-position operands
NEWY = $34

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    jsr init_ppu
    gfxmode #1                  ; zeros shadow tilemaps + sets 32x32 dims

    ; --- flags + map (after gfxmode — it wipes the shadow tilemaps) ---
    sf_tile_flags 2, SF_FLAG_SOLID
    sf_tile_flags 3, $02        ; hazard: bit 1 only (NOT solid)
    mset #1, #5, #5, #2         ; wall  at cell (5,5)   = px 40..47
    mset #1, #10, #10, #1       ; floor at cell (10,10) = px 80..87 (unflagged)
    mset #1, #12, #5, #3        ; hazard at cell (12,5) = px 96..103

    ; --- col_map queries ---
    col_map #1, #40, #40, #0    ; wall, solid bit
    ldx #$0000
    sta f:$7E0000 + $E010, x

    col_map #1, #80, #80, #0    ; floor tile: present but unflagged
    ldx #$0000
    sta f:$7E0000 + $E012, x

    col_map #1, #200, #8, #0    ; empty cell (tile 0)
    ldx #$0000
    sta f:$7E0000 + $E014, x

    col_map #1, #96, #40, #1    ; hazard, ITS bit
    ldx #$0000
    sta f:$7E0000 + $E016, x

    col_map #1, #96, #40, #0    ; hazard, solid bit -> clear
    ldx #$0000
    sta f:$7E0000 + $E018, x

    col_map #1, #400, #40, #0   ; out of bounds (tile_x 50 >= 32)
    ldx #$0000
    sta f:$7E0000 + $E01A, x

    ; --- sf_solid_box cases (memory operands, like real movement code) ---
    rep #$30
    .a16
    .i16
    lda #36
    sta NEWX
    sta NEWY
    sf_solid_box NEWX, NEWY     ; corners 36..43 straddle into the wall
    ldx #$0000
    sta f:$7E0000 + $E01C, x

    lda #80
    sta NEWX
    sta NEWY
    sf_solid_box NEWX, NEWY     ; floor cell: unflagged -> clear
    ldx #$0000
    sta f:$7E0000 + $E01E, x

    lda #32
    sta NEWX
    lda #40
    sta NEWY
    sf_solid_box NEWX, NEWY     ; spans px 32..39: edge-adjacent, NOT inside
    ldx #$0000
    sta f:$7E0000 + $E020, x

    ; --- the gfxmode dim fix took (col_map's bounds check depends on it) ---
    sep #$20
    .a8
    lda TILEMAP_WIDTH_BG1
    ldx #$0000
    sta f:$7E0000 + $E022, x
    rep #$20
    .a16

    sf_debug_magic
    sf_debug_complete
    stp

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "collision_engine.asm"
