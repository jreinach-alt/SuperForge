; =============================================================================
; sf_level.inc — scrolling-level macros (macro library)
; =============================================================================
; Levels WIDER than one screen (up to 512x224) with full collision, composing
; the camera (sf_camera.inc) with the physics world (sf_physics.inc). The
; trick — zero engine changes: BG1 switches to the hardware 64x32 tilemap,
; whose second screen lives at VRAM word $5C00 — exactly where the engine's
; BG2 tilemap plumbing already DMAs its shadow. So:
;
;   world columns  0..31  =  layer 1 (BG1 shadow -> VRAM $5800, page 0)
;   world columns 32..63  =  layer 2 (BG2 shadow -> VRAM $5C00, page 1)
;
; mset/col_map on layer 2 ARE the right half of the world. The BG2 *layer*
; is removed from the main screen (TM=$15: OBJ+BG3+BG1) — its shadow/DMA
; path runs anyway (the engine gates the DMA on the dirty bit, not the layer
; enable), acting purely as the page-1 transport. The whole level sits in
; VRAM, so there is NO streaming and no ring seam: sf_camera_follow's
; clamped scroll (0..world_w-256) just works, and the BG1 HOFS is 10 bits.
;
; Levels are ROM data: 28 rows x 64 tile-ID bytes (1792 bytes), top row
; first. END EVERY LEVEL with the length guard — a single miscounted row
; shears everything below it into a diagonal (the bytes have no row
; structure the assembler can check for you):
;     .assert * - my_level = 28 * 64, error, "level must be 28x64"
; Tile solidity comes from the SAME flag table as everywhere else —
; sf_tile_flags marks a tile ID solid for static maps AND levels.
;
; The world is 512x224: X is the full 16-bit pixel range 0..511, Y stays one
; screen (the 8.8 physics limit). Scroll only horizontally (cam_y fixed 0).
;
; Call order (after sf_coldstart / sf_engine_init / uploads / init_ppu):
;   gfxmode #1          ; engine init: 32x32 regs, shadows zeroed, dims set
;   sf_level_init       ; BG1 -> 64x32, BG2 layer off TM, under forced blank
;   sf_tile_flags 2, SF_FLAG_SOLID
;   sf_level_load my_level, TXV, TYV, TILEV   ; fill both halves via mset
;
; Requires: sf_bg.inc (gfxmode/mset), sf_map.inc (col_map + flag table),
; sf_camera.inc (sf_camera_follow — pass world_w=512), sf_physics.inc
; (tunables; the integrator here mirrors sf_physics_step).
; =============================================================================

.ifndef SF_LEVEL_INC
SF_LEVEL_INC = 1

.include "sf_bg.inc"
.include "sf_map.inc"
.include "sf_camera.inc"
.include "sf_physics.inc"

.ifndef SF_PATROL_SPEED
SF_PATROL_SPEED = 1             ; px/frame (same default + bound as sf_enemy.inc)
.endif
.assert SF_PATROL_SPEED <= 8, error, "SF_PATROL_SPEED > 8 px/frame outruns the wall/ledge probes"

; -----------------------------------------------------------------------------
; sf_level_init — switch BG1 to the 64x32 hardware tilemap; BG2 layer off.
; -----------------------------------------------------------------------------
; Call AFTER gfxmode (which writes the 32x32 BG1SC and turns the screen on).
; Briefly forces blank for the PPU-register writes, then restores the
; engine's INIDISP. TM goes to $15 (OBJ + BG3 + BG1) via the engine's
; SHADOW_TM so the NMI sustains it. Clobbers A.
; WIDTH-RISK: toggles A8 for the register writes; exits A16.
.macro sf_level_init
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; forced blank for the BG1SC write
    lda #$59
    sta $2107                   ; BG1SC: base word $5800, size 64x32
    lda #$15
    sta SHADOW_TM               ; OBJ + BG3 + BG1 (BG2 layer = page-1
    sta $212C                   ;   transport only, never displayed)
    lda SHADOW_INIDISP
    sta $2100                   ; restore display
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_level_load level, txv, tyv, tilev — fill the world from a ROM level map.
; -----------------------------------------------------------------------------
;   level   assemble-time label: 28 rows x 64 bytes of tile IDs (row 0 first)
;   txv, tyv, tilev   DP word scratch (consumed)
; msets every cell: world columns 0..31 -> layer 1, 32..63 -> layer 2 (the
; engine DMAs both shadows to the two hardware pages). Init-time only (~1800
; engine calls — fine before the frame loop starts). Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16; exits A16/I16. Internal loops use named
; .locals + jmp trampolines (mset expands >127 bytes).
.macro sf_level_load sf_level, sf_txv, sf_tyv, sf_tilev
    .local row_loop, col_loop, right_half, do_set, next_col, next_row, done_load
    rep #$30
    .a16
    .i16
    stz sf_tyv
row_loop:
    .a16
    stz sf_txv
col_loop:
    .a16
    ; tile = level[ty*64 + tx]
    lda sf_tyv
    asl
    asl
    asl
    asl
    asl
    asl                         ; ty * 64
    clc
    adc sf_txv
    tax
    lda f:sf_level, x
    and #$00FF
    sta sf_tilev
    ; left or right page?
    lda sf_txv
    cmp #32
    bcs right_half
    mset #1, sf_txv, sf_tyv, sf_tilev
    jmp next_col
right_half:
    .a16
    sec
    sbc #32
    sta sf_txv                  ; temporarily page-local for the mset
    mset #2, sf_txv, sf_tyv, sf_tilev
    rep #$20
    .a16
    lda sf_txv
    clc
    adc #32
    sta sf_txv                  ; restore world column
next_col:
    .a16
    lda sf_txv
    inc a
    sta sf_txv
    cmp #64
    bcs next_row
    jmp col_loop
next_row:
    .a16
    lda sf_tyv
    inc a
    sta sf_tyv
    cmp #28
    bcs done_load
    jmp row_loop
done_load:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_level_point x, y, lvar [, bit] -> A — test a flag bit at world point (x,y).
; -----------------------------------------------------------------------------
;   x       DP word: world pixel x 0..511 — CONSUMED (page-localized in place)
;   y       verbatim operand: pixel y
;   lvar    DP word scratch: receives the layer (1/2)
;   bit     optional verbatim flag-bit index (default #0 = SOLID; #1 =
;           PLATFORM; 2-7 yours — same convention as col_map)
; Splits the point across the two pages and runs col_map. Building block for
; sf_level_solid_box; useful alone for single-point probes (sensors, ledges,
; pickups, hazards).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16; exits A16 (0/1 in A).
.macro sf_level_point sf_x, sf_y, sf_lvar, sf_bit
    .local left_half, do_probe
    rep #$30
    .a16
    .i16
    lda sf_x
    cmp #256
    bcc left_half
    sec
    sbc #256
    sta sf_x
    lda #$0002
    sta sf_lvar
    bra do_probe
left_half:
    .a16
    lda #$0001
    sta sf_lvar
do_probe:
    .a16
.ifblank sf_bit
    col_map sf_lvar, sf_x, sf_y, #0
.else
    col_map sf_lvar, sf_x, sf_y, sf_bit
.endif
.endmacro

; -----------------------------------------------------------------------------
; sf_level_solid_box x, y, cornx, corny, lvar -> A — 8x8 box vs the world.
; -----------------------------------------------------------------------------
;   x, y    DP words: the box's top-left world position (NOT consumed)
;   cornx, corny, lvar   DP word scratch (consumed)
; The seam-aware sibling of sf_solid_box: all FOUR corners (+7 far edges),
; each corner page-split independently — a box straddling world x=256 probes
; both pages correctly. Returns 1 in A if any corner is solid. Clobbers
; A, X, Y. Scratch is shareable between actors (consumed within the call).
; WIDTH-RISK: asserts A16/I16; exits A16 (0/1 in A).
.macro sf_level_solid_box sf_x, sf_y, sf_cornx, sf_corny, sf_lvar
    .local c2, c3, c4, hit, done
    rep #$30
    .a16
    .i16
    ; corner (x, y)
    lda sf_x
    sta sf_cornx
    lda sf_y
    sta sf_corny
    sf_level_point sf_cornx, sf_corny, sf_lvar
    beq c2
    jmp hit
c2:
    .a16
    ; corner (x+7, y)
    lda sf_x
    clc
    adc #7
    sta sf_cornx
    lda sf_y
    sta sf_corny
    sf_level_point sf_cornx, sf_corny, sf_lvar
    beq c3
    jmp hit
c3:
    .a16
    ; corner (x, y+7)
    lda sf_x
    sta sf_cornx
    lda sf_y
    clc
    adc #7
    sta sf_corny
    sf_level_point sf_cornx, sf_corny, sf_lvar
    beq c4
    jmp hit
c4:
    .a16
    ; corner (x+7, y+7)
    lda sf_x
    clc
    adc #7
    sta sf_cornx
    lda sf_y
    clc
    adc #7
    sta sf_corny
    sf_level_point sf_cornx, sf_corny, sf_lvar
    beq done                    ; A already 0
    lda #$0001
    bra done
hit:
    .a16
    lda #$0001
done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_level_physics_step pyf, vy, px, newy, grounded, cornx, corny, lvar
; -----------------------------------------------------------------------------
; The level-world sibling of sf_physics_step (sf_physics.inc) — identical
; state cycle (stable grounded probe, landing snap, head bump, terminal
; clamp, ONE-WAY PLATFORMS via SF_FLAG_PLATFORM tiles; same tunables), with
; every probe seam-aware (sf_level_solid_box / page-split sf_level_point).
; Extra args are the three scratch words the probers consume. KEEP IN SYNC
; with sf_physics_step — same algorithm, different prober. Also uses the
; SF_PHYS_YB/RX scratch words ($053A-$053D, from sf_physics.inc).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16; exits A16. PHA/PLA stack contract identical
; to sf_physics_step (one PLA per arm).
.macro sf_level_physics_step sf_pyf, sf_vy, sf_px, sf_newy, sf_grounded, sf_cornx, sf_corny, sf_lvar
    .local falling, integrate, noclamp, fall_clear
    .local stand, ow_cross, ow_land, ow_none
    .local rising, rise_clear, done
    rep #$30
    .a16
    .i16
    lda sf_vy
    bpl falling
    jmp rising

falling:
    .a16
    lda sf_pyf
    xba
    and #$00FF
    inc a
    sta sf_newy
    sf_level_solid_box sf_px, sf_newy, sf_cornx, sf_corny, sf_lvar
    beq :+
    jmp stand
:   ; --- one-way support: resting EXACTLY on a platform top? (page-split) ---
    lda sf_pyf
    xba
    and #$0007
    beq :+
    jmp integrate               ; mid-tile: nothing one-way to stand on
:   lda sf_pyf
    xba
    and #$00FF
    clc
    adc #8                      ; the row just below the box = the tile top
    sta SF_PHYS_YB
    lda sf_px
    sta sf_cornx
    sf_level_point sf_cornx, SF_PHYS_YB, sf_lvar, #1
    beq :+
    jmp stand
:   lda sf_px
    clc
    adc #7
    sta sf_cornx
    sf_level_point sf_cornx, SF_PHYS_YB, sf_lvar, #1
    beq :+
    jmp stand
:   jmp integrate

stand:
    .a16
    stz sf_vy
    lda #$0001
    sta sf_grounded
    lda sf_pyf
    and #$FF00
    sta sf_pyf
    jmp done

integrate:
    .a16
    lda sf_vy
    clc
    adc #SF_GRAVITY
    cmp #SF_MAX_FALL
    bcc noclamp
    lda #SF_MAX_FALL
noclamp:
    .a16
    sta sf_vy
    lda sf_pyf
    clc
    adc sf_vy
    pha                         ; WIDTH-RISK: stack balance — one PLA per arm
    xba
    and #$00FF
    sta sf_newy
    sf_level_solid_box sf_px, sf_newy, sf_cornx, sf_corny, sf_lvar
    beq fall_clear
    pla
    lda sf_newy
    clc
    adc #7
    and #$FFF8
    sec
    sbc #8
    xba
    sta sf_pyf
    stz sf_vy
    lda #$0001
    sta sf_grounded
    jmp done
fall_clear:
    .a16
    ; --- one-way platforms: land only when CROSSING a top from above ---
    ; (tentative 8.8 position still on the stack on every path below)
    lda sf_newy
    clc
    adc #7                      ; the box's bottom pixel at the new position
    sta SF_PHYS_YB
    and #$FFF8
    sta SF_PHYS_RX              ; (borrow RX for the tile top a moment)
    lda sf_pyf                  ; OLD position (not yet overwritten)
    xba
    and #$00FF
    clc
    adc #8                      ; old bottom EDGE
    cmp SF_PHYS_RX
    beq ow_cross
    bcc ow_cross
    jmp ow_none                 ; started at/below the top -> pass through

ow_cross:
    .a16
    lda sf_px
    sta sf_cornx
    sf_level_point sf_cornx, SF_PHYS_YB, sf_lvar, #1
    beq :+
    jmp ow_land
:   lda sf_px
    clc
    adc #7
    sta sf_cornx
    sf_level_point sf_cornx, SF_PHYS_YB, sf_lvar, #1
    beq :+
    jmp ow_land
:   jmp ow_none

ow_land:
    .a16
    pla                         ; discard the tentative position
    lda sf_newy                 ; same landing snap as a solid floor
    clc
    adc #7
    and #$FFF8
    sec
    sbc #8
    xba
    sta sf_pyf
    stz sf_vy
    lda #$0001
    sta sf_grounded
    jmp done

ow_none:
    .a16
    pla
    sta sf_pyf
    stz sf_grounded
    jmp done

rising:
    .a16
    stz sf_grounded
    lda sf_vy
    clc
    adc #SF_GRAVITY
    sta sf_vy
    lda sf_pyf
    clc
    adc sf_vy
    pha                         ; WIDTH-RISK: stack balance — one PLA per arm
    xba
    and #$00FF
    sta sf_newy
    sf_level_solid_box sf_px, sf_newy, sf_cornx, sf_corny, sf_lvar
    beq rise_clear
    pla
    lda sf_newy
    and #$FFF8
    clc
    adc #8
    xba
    sta sf_pyf
    stz sf_vy
    jmp done
rise_clear:
    .a16
    pla
    sta sf_pyf
done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_level_patrol_step ex, ey, edir, newx, leadx, footy, lvar — seam-aware patrol.
; -----------------------------------------------------------------------------
; The level-world sibling of sf_patrol_step (sf_enemy.inc) — same contract
; (walk at SF_PATROL_SPEED, turn at walls AND at leading-corner ledges,
; never overhang), with the wall probe via sf_level_solid_box and the ledge
; probe via the page-split sf_level_point — so a beat can span the world's
; x=256 page seam (the gap the static-map sf_patrol_step has: it probes
; layer 1 only).
;   ex, ey, edir   DP words: enemy state (as sf_patrol_step)
;   newx           DP word scratch: the tentative x
;   leadx, footy   DP word scratch: ledge probe point (leadx CONSUMED by the
;                  page split; ALSO used as box-probe scratch before that)
;   lvar           DP word scratch: page-split layer
; Place ex on the terrain run; same inductive never-overhang guarantee.
; One call per enemy per frame; scratch shareable between enemies.
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; all arithmetic A16; exits A16.
; Contains sf_level_solid_box / sf_level_point expansions — control flow
; uses .local labels + jmp trampolines (ends caller cheap-local scope).
.macro sf_level_patrol_step sf_ex, sf_ey, sf_edir, sf_newx, sf_leadx, sf_footy, sf_lvar
    .local move_left, store_x, lead_left, lead_store, no_wall
    .local commit, turn, done
    rep #$30
    .a16
    .i16
    ; tentative x = ex +/- speed
    lda sf_edir
    beq move_left
    lda sf_ex
    clc
    adc #SF_PATROL_SPEED
    bra store_x
move_left:
    .a16
    lda sf_ex
    sec
    sbc #SF_PATROL_SPEED
store_x:
    .a16
    sta sf_newx
    ; wall ahead? (full box at the tentative position, both pages)
    sf_level_solid_box sf_newx, sf_ey, sf_leadx, sf_footy, sf_lvar
    beq no_wall
    jmp turn
no_wall:
    .a16
    ; leading bottom corner: front edge of the box, one row below the feet
    lda sf_edir
    beq lead_left
    lda sf_newx
    clc
    adc #7
    bra lead_store
lead_left:
    .a16
    lda sf_newx
lead_store:
    .a16
    sta sf_leadx
    lda sf_ey
    clc
    adc #8
    sta sf_footy
    ; ground under the leading corner? (page-split single-point probe)
    sf_level_point sf_leadx, sf_footy, sf_lvar
    bne commit                  ; ground present -> walk
    jmp turn                    ; ledge -> turn
commit:
    .a16
    lda sf_newx
    sta sf_ex
    bra done
turn:
    .a16
    lda sf_edir
    eor #$0001
    sta sf_edir
done:
    .a16
.endmacro

.endif ; SF_LEVEL_INC
