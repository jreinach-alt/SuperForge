; =============================================================================
; sf_physics.inc — jump physics macros (macro library)
; =============================================================================
; Gravity + jump-arc for a tile-collision world: a per-frame vertical
; integrator (sf_physics_step) and a grounded-gated jump trigger (sf_jump),
; built over sf_solid_box so the SAME solid tiles that block walking are the
; floors and ceilings of the jump arc.
;
; Vertical state is 8.8 fixed-point (high byte = pixel 0..255, low byte =
; subpixel) so arcs are smooth at SNES frame rates; velocity is signed 8.8
; px/frame (negative = up). The integrator handles the WHOLE state cycle by
; construction — standing, take-off, ascent, head bump, apex, descent,
; landing snap, rest — so the caller writes no collision-response logic:
;
;   - standing: a 1px-below ground probe keeps `grounded`=1 STABLE every
;     frame (no flicker between snap frames), so jump gating just works
;   - landing: the box bottom snaps EXACTLY to the tile top (rest y is
;     pixel-exact and stable; no embedding, no hover)
;   - head bump: rising into a ceiling snaps below it and kills upward
;     velocity (the arc comes down early, like it should)
;   - fall speed clamps at SF_MAX_FALL (must stay <= 8 px/frame: the 8x8
;     box check covers the step, so the clamp is also the no-tunnel bound)
;
; Tuning (kit defaults; to override, define before .include'ing this file):
;   SF_GRAVITY  = $0040  (0.25 px/f^2)
;   SF_MAX_FALL = $0400  (4 px/f terminal fall)
;   SF_JUMP_VEL = $0480  (4.5 px/f take-off -> apex ~38 px above rest in
;                         ~18 frames with the default gravity)
;
; ONE-WAY PLATFORMS are built in: tiles flagged SF_FLAG_PLATFORM ($02, bit 1
; — sf_map.inc) land the box when its bottom edge CROSSES the tile top from
; above, support standing on top, and are transparent from below and from
; the sides (and never block walking — sf_solid_box only tests bit 0). No
; extra calls: flag the tiles, the integrator does the rest. (Drop-through
; on down+jump is NOT built in — gate your own sf_jump call for that.)
;
; VARIABLE-HEIGHT JUMP: call sf_jump_cut every frame the jump button is NOT
; held; releasing early caps the remaining ascent at SF_JUMP_CUT_VEL, so a
; tap hops and a hold clears the full arc:
;     btn #BTN_A  /  bne a_held  /  sf_jump_cut VY  /  a_held:
;
; PITS: sf_pit returns whether the player fell past a death line (bottomless
; gaps). Respond in the caller (respawn, lives, game over).
;
; Requires: sf_map.inc (sf_solid_box + col_map; flag your floor/ceiling
; tiles with SF_FLAG_SOLID, one-way tops with SF_FLAG_PLATFORM, and build
; the map with mset first). The world coordinate space is the 8.8 high
; byte, so y stays in 0..255 — one screen, which is the kit's world size.
;
; Scratch contract: sf_physics_step uses WRAM $053A-$053D (SF_PHYS_YB/RX,
; between sf_meta's scratch and the engine's DMA staging at $0540). Main
; thread only, consumed within the call.
; =============================================================================

.ifndef SF_PHYSICS_INC
SF_PHYSICS_INC = 1

.include "sf_map.inc"

SF_PHYS_YB = $053A              ; probe row scratch (word)
SF_PHYS_RX = $053C              ; right-corner x scratch (word)

.ifndef SF_GRAVITY
SF_GRAVITY  = $0040
.endif
.ifndef SF_MAX_FALL
SF_MAX_FALL = $0400
.endif
.ifndef SF_JUMP_VEL
SF_JUMP_VEL = $0480
.endif

; Override bounds (assemble-time): both speeds must stay <= 8 px/frame — the
; 8x8 box probe + the `& $FFF8` snaps only cover an 8px step. Faster falls
; embed in floors; faster take-offs can tunnel through ceilings.
.assert SF_MAX_FALL <= $0800, error, "SF_MAX_FALL > 8 px/frame breaks the landing snap / no-tunnel bound"
.assert SF_JUMP_VEL <= $0800, error, "SF_JUMP_VEL > 8 px/frame can tunnel through ceilings"

.ifndef SF_JUMP_CUT_VEL
SF_JUMP_CUT_VEL = $0100         ; ascent cap after an early release (1 px/f up)
.endif

; -----------------------------------------------------------------------------
; sf_jump vy, grounded — take off, if standing on ground.
; -----------------------------------------------------------------------------
;   vy        DP word: signed 8.8 vertical velocity
;   grounded  DP word: 1 = standing (set by sf_physics_step)
; If grounded: vy = -SF_JUMP_VEL and grounded = 0; otherwise does nothing (so
; you can't jump in mid-air — gate it on a PRESS with btnp, not btn, unless
; you want auto-rejump while held). Clobbers A.
; Idiom:  btnp #BTN_A  /  beq no_jump  /  sf_jump VY, GROUNDED  /  no_jump:
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_jump sf_vy, sf_grounded
    .local skip
    rep #$30
    .a16
    .i16
    lda sf_grounded
    beq skip
    lda #(($10000 - SF_JUMP_VEL) & $FFFF)   ; -SF_JUMP_VEL, two's complement
    sta sf_vy
    stz sf_grounded
skip:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_jump_cut vy — cap the ascent after an early button release.
; -----------------------------------------------------------------------------
;   vy  DP word: signed 8.8 velocity (the one sf_jump/sf_physics_step own)
; If rising faster than SF_JUMP_CUT_VEL, slows the ascent to it — the arc
; tops out early, so tap = short hop, hold = full jump. Idempotent: call it
; EVERY frame the jump button is up (the idiom in the header). Does nothing
; when falling or already slow. Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_jump_cut sf_vy
    .local jc_done
    rep #$30
    .a16
    .i16
    lda sf_vy
    bpl jc_done                 ; not rising
    cmp #(($10000 - SF_JUMP_CUT_VEL) & $FFFF)
    bcs jc_done                 ; already at/below the cap
    lda #(($10000 - SF_JUMP_CUT_VEL) & $FFFF)
    sta sf_vy
jc_done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_pit pyf, limit -> A — has the player fallen past the death line?
; -----------------------------------------------------------------------------
;   pyf    DP word: player y, 8.8 fixed
;   limit  verbatim (`#216`): the death row in pixels. Keep limit <= 248 —
;          with SF_MAX_FALL <= 8 every fall then lands in [limit, 255]
;          before the 8-bit pixel wraps back to the top.
; Returns A = 1 fell past / 0 fine. Check EVERY frame (after the physics
; step); respond in the caller — respawn / lose a life / game over.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_pit sf_pyf, sf_limit
    .local pit_hit, pit_done
    rep #$30
    .a16
    .i16
    lda sf_pyf
    xba
    and #$00FF
    cmp sf_limit
    bcs pit_hit
    lda #$0000
    bra pit_done
pit_hit:
    .a16
    lda #$0001
pit_done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_physics_step pyf, vy, px, newy, grounded — one frame of vertical physics.
; -----------------------------------------------------------------------------
;   pyf       DP word: player y, 8.8 fixed (high byte = the pixel you draw at)
;   vy        DP word: signed 8.8 velocity (sf_jump writes it)
;   px        DP word: player x in pixels (the X-axis is yours — walk first,
;             then call this; it reads px for the collision probes)
;   newy      DP word: scratch (pixel y handed to sf_solid_box)
;   grounded  DP word: out — 1 standing / 0 airborne
; Call once per frame, after horizontal movement, before drawing. Draw at the
; pixel: `lda pyf / xba / and #$00FF`. Initialize pyf = spawn_y * 256, vy = 0,
; grounded = 0 (the first step lands and sets it). Clobbers A, X, Y.
;
; Apex corner case: on the frame velocity crosses 0, the (sub-pixel) move
; still runs through the rising-branch ceiling check; in open air it is a
; no-op, and a ceiling exactly at apex height snaps the same way a bump does.
; Side-face contact while rising (drifting into a platform's side) resolves
; through the same bump snap — a downward correction of at most 7px — which
; is correct collision response, just worth knowing when tuning levels.
;
; WIDTH-RISK: asserts A16/I16 entry; all arithmetic A16; exits A16. The two
; sf_solid_box expansions inside are >127 bytes — control flow around them
; uses jmp trampolines (short branches only hop short blocks).
.macro sf_physics_step sf_pyf, sf_vy, sf_px, sf_newy, sf_grounded
    .local falling, integrate, noclamp, fall_clear
    .local stand, ow_check, ow_cross, ow_land, ow_none
    .local rising, rise_clear, done
    rep #$30
    .a16
    .i16
    lda sf_vy
    bpl falling
    jmp rising

falling:
    .a16
    ; --- ground probe: solid 1px below the current box? -> standing ---
    lda sf_pyf
    xba
    and #$00FF
    inc a
    sta sf_newy
    sf_solid_box sf_px, sf_newy
    beq :+                      ; no solid under the box
    jmp stand
:   ; --- one-way support: resting EXACTLY on a platform top? ---
    ; only possible when the box bottom edge sits on a tile boundary
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
    col_map #1, sf_px, SF_PHYS_YB, #1
    beq :+
    jmp stand
:   lda sf_px
    clc
    adc #7
    sta SF_PHYS_RX
    col_map #1, SF_PHYS_RX, SF_PHYS_YB, #1
    beq :+
    jmp stand
:   jmp integrate

stand:
    .a16
    stz sf_vy                   ; standing: rest, stable grounded flag
    lda #$0001
    sta sf_grounded
    lda sf_pyf
    and #$FF00                  ; pixel-exact rest (clear subpixel)
    sta sf_pyf
    jmp done

integrate:
    .a16
    ; --- gravity, clamped to terminal fall speed ---
    lda sf_vy
    clc
    adc #SF_GRAVITY
    cmp #SF_MAX_FALL
    bcc noclamp
    lda #SF_MAX_FALL
noclamp:
    .a16
    sta sf_vy
    ; --- tentative move, then probe the new pixel ---
    lda sf_pyf
    clc
    adc sf_vy
    pha                         ; WIDTH-RISK: stack balance — this PHA (A16,
                                ; 2 bytes) is matched by exactly one PLA on
                                ; EACH arm below; arms must net to zero
    xba
    and #$00FF
    sta sf_newy
    sf_solid_box sf_px, sf_newy
    beq fall_clear
    pla                         ; blocked: discard the tentative position
    lda sf_newy                 ; --- landing snap: box bottom -> tile top ---
    clc
    adc #7                      ; the box's bottom pixel
    and #$FFF8                  ; top of the solid tile row it entered
    sec
    sbc #8                      ; box top = tile top - box height
    xba                         ; pixel -> 8.8 (value <= $00FF, so xba = <<8)
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
    and #$FFF8                  ; that row's tile top
    sta SF_PHYS_RX              ; (borrow RX for the tile top a moment)
    lda sf_pyf                  ; OLD position (not yet overwritten)
    xba
    and #$00FF
    clc
    adc #8                      ; old bottom EDGE
    cmp SF_PHYS_RX
    beq ow_cross                ; was resting exactly on it
    bcc ow_cross                ; was fully above -> this step crosses the top
    jmp ow_none                 ; started at/below the top -> pass through

ow_cross:
    .a16
    col_map #1, sf_px, SF_PHYS_YB, #1
    beq :+
    jmp ow_land
:   lda sf_px
    clc
    adc #7
    sta SF_PHYS_RX
    col_map #1, SF_PHYS_RX, SF_PHYS_YB, #1
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
    pla                         ; commit the tentative position
    sta sf_pyf
    stz sf_grounded
    jmp done

rising:
    .a16
    stz sf_grounded
    lda sf_vy                   ; gravity (no clamp needed while negative)
    clc
    adc #SF_GRAVITY
    sta sf_vy
    lda sf_pyf
    clc
    adc sf_vy
    pha                         ; WIDTH-RISK: stack balance — same contract
                                ; as the falling arm: one PLA per arm
    xba
    and #$00FF
    sta sf_newy
    sf_solid_box sf_px, sf_newy
    beq rise_clear
    pla                         ; blocked: discard the tentative position
    lda sf_newy                 ; --- head bump: box top -> below the tile ---
    and #$FFF8                  ; the ceiling tile's row
    clc
    adc #8                      ; first clear row below it
    xba
    sta sf_pyf
    stz sf_vy                   ; kill the ascent — the arc comes down early
    jmp done
rise_clear:
    .a16
    pla
    sta sf_pyf
done:
    .a16
.endmacro

; =============================================================================
; --- WIDE-Y (16-bit world Y) variants — for levels TALLER than one screen ----
; =============================================================================
; The macros above store Y as 8.8 fixed-point: the high byte is the pixel and
; `xba / and #$00FF` caps it at 0..255 (ONE SCREEN — the kit's static world
; size). A STREAMING level several screens TALL needs a world-Y that exceeds
; 255, so these variants split the vertical state into:
;
;   pyf   16-bit world-Y INTEGER pixel (0..65535 — 1024px / 128 tiles fits)
;   pysub 16-bit subpixel accumulator (only the LOW byte is meaningful, 0..255)
;   vy    signed 8.8 velocity (UNCHANGED — same units as the 8.8 path, so
;         sf_jump / sf_jump_cut work on `vy` verbatim)
;
; Combined the vertical position is a signed 16.8 value `{pyf : pysub.lo}` and
; one frame's integration is a 24-bit += (sign-extended 8.8 vy). The collision
; response (landing snap, head bump, one-way platforms) is structurally
; IDENTICAL to sf_physics_step — only the integer width and the collision PROBE
; differ.
;
; COLLISION PROBE (the reusable seam): a STREAMING level's collision lives in a
; WORLD-SPACE table (not the resident tilemap col_map reads), so the probe is a
; caller-supplied SUBROUTINE label `sf_solidprobe`. Contract:
;   IN : reads `sf_px` (world X pixel) and `sf_newy` (world Y pixel) — the two
;        DP word operands the macro fills before each `jsr sf_solidprobe`.
;   OUT: A = 1 if an 8x8 box at world (px, newy) overlaps SOLID terrain, else 0.
;        A16/I16 in/out; may clobber A,X,Y (the macro re-derives its state after).
; This is the same shape as the engine's `jsr engine_col_map` seam — the macro
; owns the arc, the template owns "what is solid in MY world".
;
; ONE-WAY PLATFORMS: same model as the 8.8 path, but the platform probe is the
; SAME sf_solidprobe with a SEPARATE one-way label is NOT required — instead the
; probe is asked only for SOLID; one-way support is handled by a second caller
; label `sf_owprobe` (A=1 if a one-way PLATFORM top is under (px,newy)). Pass the
; same label twice if your world has no one-way platforms.
;
; BACKWARD COMPATIBILITY: this is a NEW entry point. sf_physics_step / sf_jump /
; sf_jump_cut / sf_pit above are byte-for-byte unchanged, so every existing
; template (platformer, jumper, stomper, scroll_run, patrol) builds identically.
;
; Init: pyf = spawn_y (INTEGER pixel, NOT <<8), pysub = 0, vy = 0, grounded = 0.
; Draw at pyf (it IS the integer pixel — no xba). Clobbers A, X, Y.
; -----------------------------------------------------------------------------

; sf_pit_world pyf, limit -> A — has the player fallen past a world death row?
;   pyf    DP word: 16-bit world-Y INTEGER pixel.
;   limit  verbatim death row in world pixels (e.g. #1000). A = 1 fell / 0 fine.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_pit_world sf_pyf, sf_limit
    .local pw_hit, pw_done
    rep #$30
    .a16
    .i16
    lda sf_pyf
    cmp sf_limit
    bcs pw_hit
    lda #$0000
    bra pw_done
pw_hit:
    .a16
    lda #$0001
pw_done:
    .a16
.endmacro

; sf_physics_step_world pyf, pysub, vy, px, newy, grounded, sf_solidprobe, sf_owprobe
; -----------------------------------------------------------------------------
; One frame of vertical physics with a 16-bit world Y. See the block header for
; the operand + probe contract. Mirrors sf_physics_step's branch structure
; (standing / take-off / ascent / head-bump / apex / descent / landing-snap /
; rest) over the 16.8 split position and the caller-supplied world probes.
;
; WIDTH-RISK: asserts A16/I16 entry; all arithmetic A16; exits A16. The two
; `jsr sf_solidprobe` / `jsr sf_owprobe` seams clobber A,X,Y — the macro reloads
; pyf/pysub from DP after each. No stack-balanced PHA across width toggles (the
; tentative position lives in DP scratch SF_PHYS_YB/RX, not on the stack).
; _sf_addpos_w pyf, pysub, vy — inline 16.8 integrator: {pyf:pysub.lo} +=
; sign_extend(vy). Commits pyf (integer pixel) + pysub (subpixel) AND mirrors
; the new integer pixel to SF_PHYS_YB so a BLOCKED arm can read the tentative
; pixel and re-snap pyf from it (the snap then overwrites the committed pyf —
; safe by construction). A16 in/out; clobbers A. Nested helper for
; sf_physics_step_world; inlined (no jsr) so there is no internal subroutine
; label to collide across expansions.
; WIDTH-RISK: A16 throughout; one PHA (2 bytes) matched by one PLA.
.macro _sf_addpos_w sf_pyf, sf_pysub, sf_vy
    .local apw_pos
    ; acc = (pysub & $00FF) + vy   -> low byte = new subpixel, high = pixel delta
    lda sf_pysub
    and #$00FF
    clc
    adc sf_vy
    pha                          ; WIDTH-RISK: A16 push (2 bytes); single PLA below
    and #$00FF
    sta sf_pysub                 ; new subpixel
    pla                          ; recover acc
    xba                          ; high byte (signed pixel delta) -> low
    and #$00FF
    cmp #$0080                   ; sign-extend the 8-bit delta to 16-bit
    bcc apw_pos
    ora #$FF00
apw_pos:
    .a16
    clc
    adc sf_pyf
    sta sf_pyf                   ; committed integer pixel
    sta SF_PHYS_YB               ; mirror for the blocked-arm snap
.endmacro

; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); all arithmetic A16;
; exits A16. The `jsr sf_solidprobe` / `jsr sf_owprobe` seams clobber A,X,Y —
; the macro reloads pyf/pysub from DP after each. The only PHA (inside the
; inlined _sf_addpos_w) is A16 and matched by one PLA; no width toggle spans it.
.macro sf_physics_step_world sf_pyf, sf_pysub, sf_vy, sf_px, sf_newy, sf_grounded, sf_solidprobe, sf_owprobe
    .local w_falling, w_integrate, w_noclamp, w_fall_clear
    .local w_stand, w_ow_cross, w_ow_land, w_ow_none
    .local w_rising, w_rise_clear, w_done
    rep #$30
    .a16
    .i16
    lda sf_vy
    bpl w_falling
    jmp w_rising

w_falling:
    .a16
    ; --- ground probe: solid 1px below the current box? -> standing ---
    lda sf_pyf
    inc a                        ; 1px below the box top (16-bit, no xba/mask)
    sta sf_newy
    jsr sf_solidprobe
    cmp #$0001
    bne :+
    jmp w_stand
:   ; --- one-way support: resting EXACTLY on a platform top? ---
    lda sf_pyf
    and #$0007
    beq :+
    jmp w_integrate              ; mid-tile: nothing one-way to stand on
:   lda sf_pyf
    clc
    adc #8                       ; the row just below the box = the tile top
    sta sf_newy
    jsr sf_owprobe
    cmp #$0001
    bne :+
    jmp w_stand
:   jmp w_integrate

w_stand:
    .a16
    stz sf_vy                    ; standing: rest, stable grounded flag
    stz sf_pysub                 ; pixel-exact rest (clear subpixel)
    lda #$0001
    sta sf_grounded
    jmp w_done

w_integrate:
    .a16
    ; --- gravity, clamped to terminal fall speed ---
    lda sf_vy
    clc
    adc #SF_GRAVITY
    cmp #SF_MAX_FALL
    bcc w_noclamp
    lda #SF_MAX_FALL
w_noclamp:
    .a16
    sta sf_vy
    ; --- tentative 16.8 move (commits {pyf:pysub}, mirrors SF_PHYS_YB) ---
    _sf_addpos_w sf_pyf, sf_pysub, sf_vy
    lda SF_PHYS_YB
    sta sf_newy
    jsr sf_solidprobe
    cmp #$0001
    bne w_fall_clear
    ; blocked: landing snap — box bottom -> tile top (overwrites the commit)
    lda sf_newy
    clc
    adc #7                       ; the box's bottom pixel
    and #$FFF8                   ; top of the solid tile row it entered
    sec
    sbc #8                       ; box top = tile top - box height
    sta sf_pyf
    stz sf_pysub
    stz sf_vy
    lda #$0001
    sta sf_grounded
    jmp w_done
w_fall_clear:
    .a16
    ; --- one-way platforms: land only when CROSSING a top from above ---
    ; sf_pyf already committed to the tentative pixel; recover OLD pixel as
    ; (committed - pixel_delta) is awkward, so use SF_PHYS_RX = new bottom edge
    ; and re-derive the crossing test from the committed (new) pyf vs. its tile.
    lda sf_newy                  ; new integer pixel (== committed pyf)
    clc
    adc #7                       ; the box's bottom pixel at the new position
    sta SF_PHYS_RX               ; new bottom edge (for the ow probe row)
    and #$FFF8                   ; that row's tile top
    sta SF_PHYS_YB               ; (borrow YB for the tile top)
    ; OLD bottom edge = (new bottom edge) - (pixels moved this frame). Pixels
    ; moved = vy>>8 rounded; but the integrator already advanced — instead test
    ; "did the box bottom land within [tile_top, tile_top+7] this step": a
    ; CROSS from above means new bottom edge is in the tile's top 8px AND we
    ; were above it last frame. We approximate "above last frame" as: the move
    ; was downward (vy>0, guaranteed on this falling/integrate arm) and the new
    ; bottom edge is at/just past the tile top.
    lda SF_PHYS_RX
    sec
    sbc SF_PHYS_YB               ; new_bottom - tile_top  (0..7 if just crossed)
    cmp #8
    bcs w_ow_none                ; bottom is >=8px past the top -> not a fresh cross
w_ow_cross:
    .a16
    lda SF_PHYS_RX               ; new bottom edge row -> probe Y
    sta sf_newy
    jsr sf_owprobe
    cmp #$0001
    bne w_ow_none
w_ow_land:
    .a16
    lda sf_newy                  ; same landing snap as a solid floor
    and #$FFF8                   ; (newy still holds the new bottom edge row)
    sec
    sbc #8                       ; box top = tile top - box height
    sta sf_pyf
    stz sf_pysub
    stz sf_vy
    lda #$0001
    sta sf_grounded
    jmp w_done

w_ow_none:
    .a16
    ; tentative position already committed by _sf_addpos_w; nothing to land on
    stz sf_grounded
    jmp w_done

w_rising:
    .a16
    stz sf_grounded
    lda sf_vy                    ; gravity (no clamp while negative)
    clc
    adc #SF_GRAVITY
    sta sf_vy
    _sf_addpos_w sf_pyf, sf_pysub, sf_vy
    lda SF_PHYS_YB
    sta sf_newy
    jsr sf_solidprobe
    cmp #$0001
    bne w_rise_clear
    ; head bump: box top -> below the tile (overwrites the commit)
    lda sf_newy
    and #$FFF8                   ; the ceiling tile's row
    clc
    adc #8                       ; first clear row below it
    sta sf_pyf
    stz sf_pysub
    stz sf_vy                    ; kill the ascent — the arc comes down early
    jmp w_done
w_rise_clear:
    .a16
    ; tentative position already committed by _sf_addpos_w
w_done:
    .a16
.endmacro

.endif ; SF_PHYSICS_INC
