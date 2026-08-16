; =============================================================================
; scenes/sky.asm — the whole game: run, jump, and the physics that owns Y
; =============================================================================
; The whole game loop: horizontal tentative-move at the current pixel y
; (revert if solid), jump on a fresh A press (grounded-gated), then the physics
; step owns the whole vertical axis. The integrator is the `phys_step`
; subroutine below — SOLID paths only: this rail flags every tile SOLID, so
; one-way-platform branches would be dead code here and are left out; a rail
; that needs them adds them when it does.
;
; THE STATE CYCLE THE INTEGRATOR OWNS BY CONSTRUCTION (the property the tests
; drive end to end): standing — a 1px-below ground
; probe keeps `grounded` = 1 STABLE every frame; take-off — the jump's
; grounded gate; ascent — gravity eating the negative velocity; head bump —
; rising into a ceiling snaps BELOW it and kills the ascent; apex — the
; sign flip; descent — gravity clamped at terminal fall; landing snap — the
; box bottom lands EXACTLY on the tile top; rest — pixel-exact, no embed, no
; hover.

.scope sky

; --- col_map's world binding (composition site; m7_dungeon's shape) ---------
; Declared here, not in the feature: col_map carries no default for any of
; these. Each name is `::`-qualified — ca65 defers an unqualified
; parent-scope lookup, and a deferred symbol is not a constant expression,
; which col_map's assembly-time `.if CM_WORLD_BLOB_CHUNKS` needs it to be.
;
; THE WORLD IS 32x32 TILES (one screen), so both log2s are 5 — asserted
; against the blob's own emitted size rather than stated.
CM_WORLD_W_LOG2      = 5
CM_WORLD_H_LOG2      = 5
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_JR_WORLD_SIZE, error, "col_map world size disagrees with the jr_world claim"
CM_WORLD_BLOB        = ::ES_R_JR_WORLD_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_JR_WORLD_BANK
; DERIVED from the claim's own size: 1,024 B against a 32 KB LoROM window is
; 1, so col_map takes its constant-bank branch (m7_dungeon's discharge of the
; bank-adjacency obligation: at CHUNKS = 1 there is nothing to be consecutive,
; and every route to CHUNKS >= 2 is refused upstream — see that rail's note).
CM_WORLD_BLOB_CHUNKS = (::ES_R_JR_WORLD_SIZE + 32767) / 32768
CM_FLAGS             = ::jr_flags_bin
.include "col_map.asm"

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr jr_arm                      ; CHR, palette, the built map, the pinned
                                    ;   scroll (jumper_bg)
    jsr jr_obj_arm                  ; OBJ CHR, palette, OBSEL, tile + attr
    ; ---- the player spawns standing on the ground, mid-left ---------------
    ; (grounded starts 0 — the first falling step's ground probe lands it and
    ; sets the flag.)
    lda #JR_SPAWN_X
    sta z:US_PX
    lda #(JR_SPAWN_Y << 8)          ; rest on the ground row, 8.8
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    stz z:US_FRAMES
    lda #JR_SPAWN_Y
    sta z:US_PYI
    jsr jr_obj_draw                 ; stage the player BEFORE the first NMI,
                                    ;   so frame 0 commits a real entry
    ; ---- the scene's base display -----------------------------------------
    ; BGMODE, TM, BG1SC, BG12NBA: the scene_writes this scene owns on
    ; jumper_bg's behalf. Values from the allocator's emitted encodings.
    sep #$20
    .a8
    lda #1                          ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
    lda #ES_V_JR_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_JR_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #((1 << 4) | 1)             ; TM: OBJ + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick -------------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A, X, Y.
; The order is fixed: pixel-y mirror, horizontal, jump, physics, mirror again,
; draw.
tick:
    .a16
    .i16
    inc z:US_FRAMES
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                    ; pixel y for probes + drawing
    jsr move_horizontal
    jsr do_jump
    jsr phys_step
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                    ; the physics moved y; refresh the mirror
    jsr jr_obj_draw
    rts

; --- move_horizontal: tentative move at the CURRENT pixel y, revert if solid
; In/out: A16/I16, DB=0. Clobbers A, X, Y (the probe's).
; The maze rail's per-axis move-check, in shape: both directions apply before
; the one probe, so held Left+Right nets to zero by arithmetic, not by a branch.
move_horizontal:
    .a16
    .i16
    lda z:US_PX
    sta z:US_NEWX
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_NEWX
    clc
    adc #JR_SPEED
    sta z:US_NEWX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_NEWX
    sec
    sbc #JR_SPEED
    sta z:US_NEWX
@no_left:
    .a16
    .i16
    lda z:US_NEWX
    sta z:US_BX
    lda z:US_PYI
    sta z:US_BY
    jsr jr_solid_box
    bne @blocked                    ; any corner solid: stay put
    lda z:US_NEWX
    sta z:US_PX
@blocked:
    .a16
    .i16
    rts

; --- do_jump: take off on a FRESH A press, only from the ground -------------
; In/out: A16/I16, DB=0. Clobbers A.
; ES_INP_PRESS is the rising edge, so holding A does not auto-rejump; the
; grounded gate is why you cannot jump in mid-air. -JR_JUMP_VEL is the take-off
; velocity in two's complement.
do_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    beq @done
    lda z:US_GROUNDED
    beq @done
    lda #JR_NEG_JUMP_VEL
    sta z:US_VY
    stz z:US_GROUNDED
@done:
    .a16
    .i16
    rts

; --- phys_step: one frame of vertical physics ------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
;
; Two arms — falling: ground probe / integrate / landing snap; rising: gravity
; / head bump — with two deliberate expressions:
;   * the tentative 8.8 position lives in US_TENT rather than on the stack, so
;     there is no width-sensitive push/pull balance to audit (the platformer's
;     US_NEWY made the same trade);
;   * the row-top computation is `lsr x3 / asl x3` rather than `and #$FFF8`
;     (the platformer's row_top shape — the shifts say "this tile row's top"
;     and keep the mask constant out of the code).
;
; Apex corner case: the frame velocity crosses 0 still runs the rising-branch
; probe; in open air it is a no-op, and a ceiling exactly at apex height snaps
; like any bump.
phys_step:
    .a16
    .i16
    lda z:US_VY
    bpl @falling
    jmp @rising                     ; a trampoline: the rising arm is past
                                    ;   short-branch reach
@falling:
    .a16
    .i16
    ; ---- ground probe: solid 1px below the current box? -> standing -------
    lda z:US_PYF
    xba
    and #$00FF
    inc a
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr jr_solid_box
    beq @integrate
    ; ---- standing: rest, stable grounded flag -----------------------------
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    lda z:US_PYF
    and #$FF00                      ; pixel-exact rest (clear subpixel)
    sta z:US_PYF
    rts
@integrate:
    .a16
    .i16
    ; ---- gravity, clamped to terminal fall speed --------------------------
    lda z:US_VY
    clc
    adc #JR_GRAVITY
    cmp #JR_MAX_FALL
    bcc @noclamp
    lda #JR_MAX_FALL
@noclamp:
    .a16
    .i16
    sta z:US_VY
    ; ---- tentative move, then probe the new pixel -------------------------
    lda z:US_PYF
    clc
    adc z:US_VY
    sta z:US_TENT
    xba
    and #$00FF
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr jr_solid_box
    beq @fall_clear
    ; ---- blocked: landing snap — box bottom -> tile top -------------------
    lda z:US_BY
    clc
    adc #7                          ; the box's bottom pixel
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl                         ; top of the solid tile row it entered
    .endrepeat
    sec
    sbc #8                          ; box top = tile top - box height
    xba                             ; pixel -> 8.8 (value <= $00FF, so
                                    ;   xba is exactly << 8)
    sta z:US_PYF
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    rts
@fall_clear:
    .a16
    .i16
    lda z:US_TENT                   ; commit the tentative position
    sta z:US_PYF
    stz z:US_GROUNDED
    rts
@rising:
    .a16
    .i16
    stz z:US_GROUNDED
    lda z:US_VY                     ; gravity (no clamp needed while negative)
    clc
    adc #JR_GRAVITY
    sta z:US_VY
    lda z:US_PYF
    clc
    adc z:US_VY
    sta z:US_TENT
    xba
    and #$00FF
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr jr_solid_box
    beq @rise_clear
    ; ---- head bump: box top -> first clear row below the ceiling ----------
    lda z:US_BY
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl                         ; the ceiling tile's row
    .endrepeat
    clc
    adc #8                          ; first clear row below it
    xba
    sta z:US_PYF
    stz z:US_VY                     ; kill the ascent — the arc comes down
                                    ;   early, like it should
    rts
@rise_clear:
    .a16
    .i16
    lda z:US_TENT
    sta z:US_PYF
    rts

; --- jr_solid_box: is any corner of an 8x8 box at (US_BX, US_BY) solid? -----
; In: A16/I16, DB=0; US_BX/US_BY = the box's top-left pixel. Out: A16 = 1/0,
; Z reflecting it (callers use beq/bne). Clobbers A, X, Y (col_map_at's).
;
; Four corners: (x,y) (x+7,y) (x,y+7) (x+7,y+7) — the box spans 8 px, so the
; far corners are +7, not +8 (a +8 probe reads the NEIGHBOURING tile and sticks
; you to walls). Each probe is col_map's flag byte tested at bit 0, the SOLID
; bit.
;
; WIDTH-RISK: col_map_at EXITS A8 (its stated contract) — every probe return
; narrows, so each corner's 16-bit setup re-widens first. @hit is reached in
; A8 from all four probes.
jr_solid_box:
    .a16
    .i16
    ; corner (x, y)
    lda z:US_BX
    sta z:CM_PX
    lda z:US_BY
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract;
                                    ;   without this ca65 still tracks A16 and
                                    ;   `and #1` assembles 3-byte, the stray $00
                                    ;   executing as BRK (rule 6's silent class,
                                    ;   and its OWN named example: col_map_at's
                                    ;   callers are the cross-file width hole
                                    ;   the lint cannot see)
    and #1                          ; bit 0 = solid
    bne @hit
    rep #$20
    .a16
    ; corner (x+7, y)
    lda z:US_BX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BY
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract;
                                    ;   without this ca65 still tracks A16 and
                                    ;   `and #1` assembles 3-byte, the stray $00
                                    ;   executing as BRK (rule 6's silent class,
                                    ;   and its OWN named example: col_map_at's
                                    ;   callers are the cross-file width hole
                                    ;   the lint cannot see)
    and #1
    bne @hit
    rep #$20
    .a16
    ; corner (x, y+7)
    lda z:US_BX
    sta z:CM_PX
    lda z:US_BY
    clc
    adc #7
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract;
                                    ;   without this ca65 still tracks A16 and
                                    ;   `and #1` assembles 3-byte, the stray $00
                                    ;   executing as BRK (rule 6's silent class,
                                    ;   and its OWN named example: col_map_at's
                                    ;   callers are the cross-file width hole
                                    ;   the lint cannot see)
    and #1
    bne @hit
    rep #$20
    .a16
    ; corner (x+7, y+7)
    lda z:US_BX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BY
    clc
    adc #7
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract;
                                    ;   without this ca65 still tracks A16 and
                                    ;   `and #1` assembles 3-byte, the stray $00
                                    ;   executing as BRK (rule 6's silent class,
                                    ;   and its OWN named example: col_map_at's
                                    ;   callers are the cross-file width hole
                                    ;   the lint cannot see)
    and #1
    bne @hit
    rep #$20
    .a16
    lda #0                          ; all four corners clear (Z set)
    rts
@hit:
    .a8
    rep #$20
    .a16
    lda #1                          ; solid (Z clear)
    rts

; --- exit -------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. One scene, no edges —
; the handler satisfies scene_mgr's table and re-parks what this scene armed.
exit:
    .a16
    .i16
    jsr oam_park_all
    rts

.endscope
