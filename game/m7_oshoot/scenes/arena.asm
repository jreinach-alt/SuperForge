; =============================================================================
; scenes/arena.asm — the whole game: aim, walk, collide, spawn, fire, project
; =============================================================================
; ONE scope holding this scene's map, its two scene-scoped features, col_map's
; binding, and the tick. The rail's driver lives here rather than in a
; `role = "game_logic"` feature: this rail shares m7_dungeon's shape, whose
; whole tick is its scene asm, and there is no second consumer for any of it.
;
; THE ORDER IN tick IS LOAD-BEARING and the reasons are recorded at the call
; sites. The short form: the heading goes into the matrix shadow BEFORE the step
; is integrated (the step reads sin/cos out of that shadow), the pivot is
; re-pinned BEFORE anything is projected (this rail's pivot moves every frame),
; and the draw comes LAST.

.scope arena

.include "engine_state_arena.inc"    ; GENERATED — this scene's map
.include "mo_floor.asm"              ; scene-scoped feature: the plane's upload
.include "mo_obj.asm"                ; scene-scoped feature: the cast + the pools

; --- the scene's base display ----------------------------------------------
; BGMODE 7 is the affine plane and BG1 is the only layer it has; TM carries BOTH
; the plane and the cast, and it has to — it is ONE register with one owner, and
; turning OBJ on is not something mo_obj can do behind the scene's back. Leaving
; bit 4 clear is the exact shape of a bug that looks like a sprite bug: OAM
; correct, OBJ CHR correct, palette correct, hi table correct, and nothing on
; screen, because the main screen was never told to composite the layer.
TM_BG1 = $01
TM_OBJ = $10

; --- col_map's world binding ------------------------------------------------
; Declared at the COMPOSITION site, not in the feature: col_map carries no
; default for any of its six symbols, so a missing one is an assembly-time error
; naming it. They are `=` equates rather than deferred references
; because a deferred symbol is not a constant expression, which col_map's
; assembly-time `.if` on these needs it to be. The `::` on the two log2
; bindings is load-bearing for the same reason and is not decoration: an
; unqualified name that is not yet defined IN THIS SCOPE is a forward
; reference to a scope-local symbol, not a lookup in the parent, so
; col_map's `.if CM_H < CM_ROWS_PER_CHK` sees a non-constant and the build
; stops four lines deep inside the feature with `Constant expression
; expected` and no mention of the binding that caused it.
;
; SEVEN, not the 9 a 4096-px world binds. "col_map is total over its torus by
; construction" describes the BINDING, not the feature: col_map.asm masks
; `and #(CM_H - 1)` and `and #(CM_W - 1)`, both derived from these two symbols.
; At 7 the torus is
; 1024 px, which is exactly MO_WORLD_MAX + 1 and exactly the wrap the Mode 7
; hardware applies to a 128x128 plane. The picture and the probe agree about
; where the world repeats because they are told the same number.
CM_WORLD_W_LOG2      = ::MO_WORLD_LOG2
CM_WORLD_H_LOG2      = ::MO_WORLD_LOG2
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_MO_TILEMAP_SIZE, error, "col_map world size disagrees with the mo_tilemap claim"

; The PACKED tile-id map, not the interleaved plane: col_map's index is
; `ty * W + tx` over contiguous bytes, and the plane has a CHR byte between
; every pair of them.
CM_WORLD_BLOB        = ::ES_R_MO_TILEMAP_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_MO_TILEMAP_BANK

; 16,384 B is HALF a LoROM window, so it is one chunk. The divisor is 32,768
; because that is the window size, which is silicon — the same value
; col_map.asm's own `rpc = 32768 / W` names.
CM_WORLD_BLOB_CHUNKS = (::ES_R_MO_TILEMAP_SIZE + 32767) / 32768

; At CHUNKS = 1 col_map takes its single-chunk path and never crosses a bank, so
; this rail has no bank-adjacency obligation to discharge. That is checkable
; rather than lucky: the expression above is derived from the claim's own SIZE,
; so a map that grew past a window would change the count and take col_map's
; multi-chunk path, whose own `.error`s state what it then needs.
CM_FLAGS             = ::mo_flags_bin
.include "col_map.asm"

; --- the arena --------------------------------------------------------------
; MO_WORLD_MAX is derived from col_map's own binding above, so writing the
; derivation keeps the two from drifting rather than restating 1023.
WORLD_MAX = (1 << (CM_WORLD_W_LOG2 + ::MO_TILE_LOG2)) - 1

; =============================================================================
; enter — the plane, the cast's sheets, the world, and the first matrix
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 10 colours + M7SEL
    jsr obj_arm                     ; 2 sheets + 3 OBJ palettes + OBSEL + both pools

    ; ---- the world, seeded before the first NMI is ever armed -------------
    ; Power-on WRAM is random and m7_affine declares NO `[init] zero` for its
    ; shadow (its feature.toml says so, and says why): what follows IS the
    ; write-before-read contract for all sixteen bytes of ES_M7AFF and for every
    ; byte of this scene's own persistent state. Not defensive initialisation —
    ; rule 5. The per-frame scratch (US_STEP*, US_CAND_*, US_IDX) is absent on
    ; purpose: every one is written before it is read inside a single tick, and
    ; pre-filling them would hide the day that stops being true.
    stz z:US_HEADING                ; heading 0 = facing up, the identity matrix
    lda #MO_SPAWN_PX                ; the hero, on the arena's centre cell
    sta z:US_POSX + 2               ;   16.16: integer px at +2...
    stz z:US_POSX + 0               ;   ...and no fraction yet
    lda #MO_SPAWN_PY
    sta z:US_POSY + 2
    stz z:US_POSY + 0
    stz z:US_SPEED                  ; at rest at spawn — the facing persists.
    stz z:US_STRAFE                 ;   Both are re-written every tick before
                                    ;   they are read, so these two stores are
                                    ;   the frame-0 case rather than an init
    stz z:US_HITS                   ; the director's latches. These are what the
    stz z:US_GRACE                  ;   tests read, so a random power-on value
    stz z:US_KILLS                  ;   here would be a fail that looks like a
    stz z:US_SCORE                  ;   logic bug
    stz z:US_SPAWN_IX
    stz z:US_CHASE_T                ; the chase's parity counter — persistent, so
                                    ;   it is seeded here and not in the tick
    lda #MO_SPAWN_PERIOD
    sta z:US_SPAWN_T                ; the first wave beat is a full period away

    ldx #MO_SPAWN_PX
    ldy #MO_SPAWN_PY
    jsr ::m7a_set_center            ; pivot -> M7X/M7Y + the screen origin
    lda z:US_HEADING
    jsr ::m7a_set_heading           ; heading -> M7A..M7D

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on mo_floor's behalf
    ; (see that feature.toml's attribution note). M7SEL is the feature's own and
    ; floor_arm has already written it.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #(TM_BG1 | TM_OBJ)          ; TM: the plane AND the cast
    sta a:$212C

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate; call it from A16 and the CPU
    ; eats the following opcode byte as that immediate's high half, the ramp
    ; never arms, INIDISP stays at brightness 0, and the ROM renders black with
    ; perfectly correct VRAM and CGRAM. That is
    ; rule 6's silent-corruption class arriving through a CROSS-FILE contract
    ; width-lint cannot see in either direction.
    ;
    ; A bare INIDISP write here would not do: scene_mgr commits INIDISP from its
    ; own NMI shadow, so it would be overwritten on the first VBlank.
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; =============================================================================
; exit — nothing to unwind
; =============================================================================
; One scene, no edges: the only way out of this scene is power-off. The entry
; point exists because scene_mgr's dispatch table has three columns.
exit:
    .a16
    .i16
    rts

; =============================================================================
; tick — one game frame
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
tick:
    .a16
    .i16
    jsr do_turn                     ; LEFT/RIGHT -> US_HEADING, continuously
    jsr do_throttle                 ; UP/DOWN    -> US_SPEED  (along the facing)
    jsr do_strafe                   ; L/R        -> US_STRAFE (across it)
    lda z:US_HEADING
    jsr ::m7a_set_heading           ; ...and into the matrix shadow, which the
                                    ;   integrate below reads its sin/cos from.
                                    ;   STILL BEFORE the integrate, and still for
                                    ;   the same reason: the step must be taken
                                    ;   along the heading the floor is about to
                                    ;   render with, or a turning player walks a
                                    ;   frame behind his own picture.
    jsr do_integrate                ; (sin,cos) x (speed, strafe) -> this frame's
                                    ;   step
    lda z:US_SPEED
    ora z:US_STRAFE
    beq @pinned                     ; nothing asked for: the facing persists, the
                                    ;   world does not move (stand-and-shoot)
    jsr move_x                      ; commit each axis SEPARATELY: that is the
    jsr move_y                      ;   slide (see move_y's header)
@pinned:
    .a16
    .i16
    ldx z:US_POSX + 2
    ldy z:US_POSY + 2
    jsr ::m7a_set_center            ; THE MOVING PIVOT — re-pinned every frame,
                                    ;   which is what keeps the hero at screen
                                    ;   centre while the arena turns AND slides.
                                    ;   It must precede every projection this
                                    ;   frame: m7p_project reads the pivot out of
                                    ;   ES_M7AFF on every call and caches nothing.
    jsr do_fire                     ; A's rising edge -> one bolt along the facing
    jsr do_bullets                  ; advance every live bolt, TTL, free at range
    jsr do_waves                    ; the beat that spawns a chaser on the ring
    jsr do_chase                    ; every live chaser steps toward the player
    jsr do_bullet_hit               ; bolt x chaser, in WORLD space
    jsr do_contact                  ; chaser x hero -> knockback
    jsr do_deaths                   ; tick every dying chaser's flash; free the
                                    ;   slots whose flash has run out
    jsr do_census                   ; the two pool_count observables
    jsr obj_draw                    ; the hero at the pin, both pools through the
                                    ;   transpose. LAST, after the pivot moved.
    jsr do_death_flash              ; ...then the two passes that UN-draw and
    jsr do_hit_blink                ;   RE-TINT what obj_draw just placed: a
                                    ;   dying chaser in the score band, and the
                                    ;   one frame in eight of the grace window
                                    ;   where the hero is NOT emitted
    jsr do_score_draw               ; the three HUD digits, last of all
    rts

; =============================================================================
; do_turn — LEFT/RIGHT rotate the heading one step per held frame
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; A continuous heading, restored onto a rail that once quantised it.
; LEFT and RIGHT produce OPPOSITE deltas and the heading is masked
; to a byte so it WRAPS rather than growing — that mask is why the picture at h
; and h+256 is bit-identical, and it is what makes all 256 LUT entries reachable
; by holding one button rather than 8 of them by pressing a compass direction.
;
; THE SIGN. This rail's convention is `DX = -sin, DY = -cos`, which puts UP at
; heading 0 and walks ANTICLOCKWISE, so an INCREASING heading turns the facing
; anticlockwise in world terms and therefore rotates the floor clockwise under a
; screen-fixed hero — which is what "I pressed LEFT and the world swung right"
; means to a player. Hence LEFT adds. Verified on the emulator against the
; rendered floor, not derived here and trusted.
;
; What is GONE, and gone rather than bypassed: `do_aim`, the UDLR bitfield it
; built, the `dir8_angle` table it indexed, and `US_MOVING`. A path that can
; still snap the heading is a regression waiting to return.
do_turn:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_LEFT
    beq @no_left
    lda z:US_HEADING
    clc
    adc #MO_TURN_STEP
    and #$00FF
    sta z:US_HEADING
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_RIGHT
    beq @no_right
    lda z:US_HEADING
    sec
    sbc #MO_TURN_STEP
    and #$00FF
    sta z:US_HEADING
@no_right:
    .a16
    .i16
    rts

; =============================================================================
; do_throttle — UP drives forward along the facing, DOWN reverses
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; SET, not ramped (m7_oshoot.inc carries the arithmetic). The
; variable, its width, its sign convention and its consumer are m7_dungeon's —
; do_integrate does `ldy z:US_SPEED` exactly as that rail does — so what changed
; is the curve and nothing else.
;
; "Forward" here is a magnitude along whatever the heading is; the DIRECTION is
; entirely the matrix's, which is the property that makes UP mean screen-up at
; every one of the 256 headings instead of at eight of them.
do_throttle:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_UP
    beq @not_fwd
    lda #MO_MOVE_SPEED
    sta z:US_SPEED
    rts
@not_fwd:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_DOWN
    beq @idle
    lda #MO_MOVE_REV
    sta z:US_SPEED
    rts
@idle:
    .a16
    .i16
    stz z:US_SPEED                  ; released: stop. The FACING persists — that
    rts                             ;   is still stand-and-shoot, it is just no
                                    ;   longer entangled with which way you point

; =============================================================================
; do_strafe — the shoulders slide sideways WITHOUT turning
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; The heading is not read and not written here, and that is the whole point: a
; strafe is additive rather than ambiguous — it gives a way to dodge sideways
; without the d-pad's meaning changing, which is what stops a tank-controlled
; run-and-gun feeling sluggish. It is the easiest thing here to drop: delete
; this routine, its call, and the two strafe terms in do_integrate.
do_strafe:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_R
    beq @not_right
    lda #MO_STRAFE_SPEED
    sta z:US_STRAFE
    rts
@not_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MO_JOY_L
    beq @idle
    lda #MO_STRAFE_LEFT
    sta z:US_STRAFE
    rts
@idle:
    .a16
    .i16
    stz z:US_STRAFE
    rts

; =============================================================================
; do_integrate — this frame's 16.16 step along the heading
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; A signed 1.7.8 matrix coefficient times a signed 8.8 speed is a signed 16.16
; displacement — the product's low word IS the fraction and its high word IS the
; integer, with no shifting anywhere. m7_project owns that multiply (m7p_mul),
; and the coefficients come out of the matrix shadow the heading above just
; selected: M7A is cos(t) and M7B is sin(t), which is precisely the (cos, sin)
; pair the step needs.
;
; The step is COMPUTED here unconditionally and committed nowhere: move_x /
; move_y decide whether the world may actually move by it, and the tick calls
; them only when the pad is asking for motion. Computing it on idle frames costs
; two multiplies and buys a property — the step is always THIS frame's facing, so
; the frame a direction is first pressed already moves.
;
; THE STRAFE TERMS. Screen-right at heading t is (cos t, -sin t): at t = 0 the
; matrix is the identity, forward is (0,-1) = screen-up, and (cos 0, -sin 0) =
; (1,0) = world +x, which IS screen-right there. Carrying that through the
; `pos -= step` convention, a strafe of s adds (-s*cos t, +s*sin t) to the step:
;
;     STEPX = sin(t)*speed - cos(t)*strafe
;     STEPY = cos(t)*speed + sin(t)*strafe
;
; Both contributions land in ONE step, so a strafe goes through the same
; one-axis-at-a-time collision a walk does and slides along a pillar identically.
; They are SKIPPED when US_STRAFE is zero — the common case — which keeps the
; idle and walking frames at the two multiplies they always cost.
do_integrate:
    .a16
    .i16
    lda z:ES_M7AFF + 2              ; sin(heading) -> the x displacement
    ldy z:US_SPEED
    jsr ::m7p_mul
    lda z:ES_M7P + M7P_ACC + 0
    sta z:US_STEPX + 0
    lda z:ES_M7P + M7P_ACC + 2
    sta z:US_STEPX + 2
    lda z:ES_M7AFF + 0              ; cos(heading) -> the y displacement
    ldy z:US_SPEED
    jsr ::m7p_mul
    lda z:ES_M7P + M7P_ACC + 0
    sta z:US_STEPY + 0
    lda z:ES_M7P + M7P_ACC + 2
    sta z:US_STEPY + 2
    lda z:US_STRAFE
    bne @lateral
    rts                             ; no shoulder held: the two terms are zero
@lateral:
    .a16
    .i16
    lda z:ES_M7AFF + 0              ; cos(heading) * strafe, SUBTRACTED from x
    ldy z:US_STRAFE
    jsr ::m7p_mul
    lda z:US_STEPX + 0
    sec
    sbc z:ES_M7P + M7P_ACC + 0
    sta z:US_STEPX + 0
    lda z:US_STEPX + 2
    sbc z:ES_M7P + M7P_ACC + 2      ; 32-bit borrow chain: the low word set C
    sta z:US_STEPX + 2
    lda z:ES_M7AFF + 2              ; sin(heading) * strafe, ADDED to y
    ldy z:US_STRAFE
    jsr ::m7p_mul
    lda z:US_STEPY + 0
    clc
    adc z:ES_M7P + M7P_ACC + 0
    sta z:US_STEPY + 0
    lda z:US_STEPY + 2
    adc z:ES_M7P + M7P_ACC + 2
    sta z:US_STEPY + 2
    rts

; =============================================================================
; COLLISION — candidate, test, commit, one axis at a time
; =============================================================================
; --- move_x: advance world x by the step, if the footprint there is clear ---
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the candidate scratch.
;
; The world moves by `pos -= step`, which is what puts the FLOOR under a hero
; who never leaves screen centre. The candidate is clamped BEFORE it is probed,
; and that clamp is what makes col_map's totality safe here: the probe has no
; bounds check and no sentinel, and it needs none, because this rail decides
; where to ask before it asks.
move_x:
    .a16
    .i16
    lda z:US_POSX + 0
    sec
    sbc z:US_STEPX + 0
    sta z:US_CAND_FR
    lda z:US_POSX + 2
    sbc z:US_STEPX + 2
    jsr clamp_world
    sta z:US_CAND_PX
    lda z:US_POSY + 2               ; ...at the CURRENT y: this axis alone
    sta z:US_CAND_PY
    jsr footprint_solid
    bne @blocked
    lda z:US_CAND_FR
    sta z:US_POSX + 0
    lda z:US_CAND_PX
    sta z:US_POSX + 2
@blocked:
    .a16
    .i16
    rts

; --- move_y: the same for y — and the asymmetry that IS the slide -----------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the candidate scratch.
;
; THE FOOTPRINT IS TESTED AT THE ALREADY-COMMITTED X, not at the x this frame
; started from. That is not an oversight in the ordering — it is the whole
; mechanism of the slide: walk diagonally into an axis-aligned wall and the
; blocked axis stops while the free one keeps advancing, because each axis is
; judged against the world the other one has already resolved. Test both axes
; against the pre-move position instead and a diagonal push dead-stops, which on
; a rail with a pillar lattice every six tiles is the difference between weaving
; and getting stuck on every corner.
move_y:
    .a16
    .i16
    lda z:US_POSY + 0
    sec
    sbc z:US_STEPY + 0
    sta z:US_CAND_FR
    lda z:US_POSY + 2
    sbc z:US_STEPY + 2
    jsr clamp_world
    sta z:US_CAND_PY
    lda z:US_POSX + 2               ; x is already resolved for this frame
    sta z:US_CAND_PX
    jsr footprint_solid
    bne @blocked
    lda z:US_CAND_FR
    sta z:US_POSY + 0
    lda z:US_CAND_PY
    sta z:US_POSY + 2
@blocked:
    .a16
    .i16
    rts

; --- clamp_world: A -> 0..WORLD_MAX, signed ---------------------------------
; In/out: A16/I16. Touches no scratch.
;
; The arena's outer ring is solid wall anyway, so the clamp is a guard on the
; ARITHMETIC — it is what stops a candidate that underflowed past zero being
; probed as a huge unsigned coordinate — not a gameplay boundary.
clamp_world:
    .a16
    .i16
    bpl @not_neg
    lda #0
    rts
@not_neg:
    .a16
    .i16
    cmp #(WORLD_MAX + 1)
    bcc @done
    lda #WORLD_MAX
@done:
    .a16
    .i16
    rts

; --- FP_CORNER: probe one corner of the footprint ---------------------------
; In: A16/I16, DB=0, US_CAND_PX/PY = the body's centre. Out: A16, the flag byte
; (zero = floor). Clobbers A, X, Y.
;
; WIDTH-RISK: col_map_at is a CROSS-FILE contract — it is entered A16/I16 and
; EXITS A8/I16, deliberately, because the flag it returns is a byte. The
; `rep #$20` here is a forced widening back to the caller's width and it must
; not be dropped: an A8 `bne` in footprint_solid below would test one byte of a
; two-byte compare and read a blocked corner as clear. width-check cannot see
; across the file boundary in either direction, so this marker carries it.
.macro FP_CORNER fp_ox, fp_oy
    lda z:US_CAND_PX
    clc
    adc #fp_ox
    sta z:CM_PX
    lda z:US_CAND_PY
    clc
    adc #fp_oy
    sta z:CM_PY
    jsr col_map_at
    rep #$20
    .a16
    and #$00FF
.endmacro

; --- footprint_solid: is the body at (US_CAND_PX, US_CAND_PY) inside a wall?
; In/out: A16/I16, DB=0. Out: A = 0 if all four corners are floor, 1 otherwise.
; Clobbers A, X, Y.
;
; FOUR corners, not a centre point: a centre test lets the body's shoulder enter
; a cell the centre has not reached, and against a lattice of 3x3 pillars that
; reads as the hero clipping through their edges.
footprint_solid:
    .a16
    .i16
    FP_CORNER MO_FP_NEAR, MO_FP_NEAR
    bne @solid
    FP_CORNER MO_FP_FAR, MO_FP_NEAR
    bne @solid
    FP_CORNER MO_FP_NEAR, MO_FP_FAR
    bne @solid
    FP_CORNER MO_FP_FAR, MO_FP_FAR
    bne @solid
    lda #0
    rts
@solid:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; THE BOLTS — fire, travel, expire
; =============================================================================
; --- do_fire: A's rising edge spawns one bolt along the facing --------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE SIGN IS THE TRAP: forward for the hero is `pos -= (sin, cos) * speed`;
; a bolt's velocity is a delta ADDED to its position each frame, so it is the
; NEGATED product. Getting it wrong fires bolts backward. The two conventions
; meet here and nowhere else.
;
; A FULL POOL SWALLOWS THE PRESS — `pool_spawn` answers POOL_FULL and the `bmi`
; drops the shot. That is the
; documented idiom: X on the full path is 0 here rather than 2*n, which the
; branch-on-A never sees (pool.asm's porting delta (d)).
;
; WIDTH-RISK: A16/I16 entry AND exit. POOL_BIND requires A16 and leaves it;
; pool_spawn and m7p_mul hold the same contract on both sides and contain no
; sep/rep. The slot offset is parked in US_IDX rather than X because m7p_mul
; clobbers X and Y (its own header says so).
do_fire:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #MO_JOY_A
    beq @done                       ; not a fresh press
    POOL_BIND ES_MO_ACTORS_LONG + MO_BUL_ALIVE
    ldx #MO_BUL_N
    jsr pool_spawn                  ; X = the claimed slot's byte offset
    bmi @done                       ; the pool is full: swallow the shot
    stx z:US_IDX                    ; park it: the multiplies below clobber X
    ; ---- the bolt starts where the hero is --------------------------------
    lda z:US_POSX + 2
    sta f:ES_MO_ACTORS_LONG + MO_BUL_WX, x
    lda z:US_POSY + 2
    sta f:ES_MO_ACTORS_LONG + MO_BUL_WY, x
    lda #MO_BUL_LIFE
    sta f:ES_MO_ACTORS_LONG + MO_BUL_TTL, x
    ; ---- ...and travels along the facing, NEGATED -------------------------
    ; The coefficients come out of the matrix shadow this tick already set, so
    ; the bolt leaves along the heading the floor is rendering — the same
    ; source do_integrate reads for the hero's own step.
    lda z:ES_M7AFF + 2              ; sin(heading)
    ldy #MO_BUL_SPEED
    jsr ::m7p_mul
    lda z:ES_M7P + M7P_ACC + 2      ; the integer px/frame of the x step
    eor #$FFFF
    inc a                           ; negate -> forward
    ldx z:US_IDX
    sta f:ES_MO_ACTORS_LONG + MO_BUL_VX, x
    lda z:ES_M7AFF + 0              ; cos(heading)
    ldy #MO_BUL_SPEED
    jsr ::m7p_mul
    lda z:ES_M7P + M7P_ACC + 2
    eor #$FFFF
    inc a
    ldx z:US_IDX
    sta f:ES_MO_ACTORS_LONG + MO_BUL_VY, x
@done:
    .a16
    .i16
    rts

; --- do_bullets: advance every live bolt; free the ones that ran out -------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; The TTL is the range: MO_BUL_SPEED x MO_BUL_LIFE = 270 world px, which is
; further than m7_project's pre-cull radius (193), so a bolt is already
; invisible for the last stretch of its life. That is intentional — it is what
; stops a bolt vanishing at the screen edge while it is still able to hit.
;
; THE FREE IS THE POOL'S, not a `stz`: `pool_kill` is the routine, X carries the
; cursor and comes back unchanged, which is exactly what this loop needs.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND requires A16 and
; leaves it; pool_kill holds the same contract and PRESERVES X (it does not
; preserve A — pool.asm's porting delta (b) — so nothing here carries a value in
; A across the call).
do_bullets:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_BUL_ALIVE, x
    beq @next
    lda f:ES_MO_ACTORS_LONG + MO_BUL_WX, x
    clc
    adc f:ES_MO_ACTORS_LONG + MO_BUL_VX, x
    sta f:ES_MO_ACTORS_LONG + MO_BUL_WX, x
    lda f:ES_MO_ACTORS_LONG + MO_BUL_WY, x
    clc
    adc f:ES_MO_ACTORS_LONG + MO_BUL_VY, x
    sta f:ES_MO_ACTORS_LONG + MO_BUL_WY, x
    lda f:ES_MO_ACTORS_LONG + MO_BUL_TTL, x
    dec a
    sta f:ES_MO_ACTORS_LONG + MO_BUL_TTL, x
    bne @next
    POOL_BIND ES_MO_ACTORS_LONG + MO_BUL_ALIVE
    ldx z:US_IDX
    jsr pool_kill                   ; out of range: the slot goes back
@next:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a                           ; +2: the pool's byte stride
    sta z:US_IDX
    cmp #(2 * MO_BUL_N)
    bcc @loop
    rts

; =============================================================================
; THE CHASERS — the wave beat, and the chase
; =============================================================================
; --- do_waves: one beat of the spawner -------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; A countdown, and on zero one chaser claimed from the pool and placed at a RING
; offset around the player — so it pops in from off-screen and walks toward him,
; rather than materialising in front of his face. The cursor cycles the eight
; compass offsets so successive waves arrive from different sides.
;
; The ring radius (120 px) sits inside m7_project's pre-cull radius (193) but
; outside the visible half-width (144 padded), which is what makes "pops in"
; true rather than approximate: the spawn is projected, culled by the SCREEN
; test rather than the circumradius, and becomes visible as it closes.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND requires A16 and
; leaves it; pool_spawn holds the same contract on both sides.
do_waves:
    .a16
    .i16
    lda z:US_SPAWN_T
    dec a
    sta z:US_SPAWN_T
    bne @done                       ; not this frame
    lda #MO_SPAWN_PERIOD
    sta z:US_SPAWN_T                ; re-arm before anything can fail
    POOL_BIND ES_MO_ACTORS_LONG + MO_ENE_ALIVE
    ldx #MO_ENE_N
    jsr pool_spawn
    bmi @done                       ; the field is full: skip this beat
    stx z:US_IDX                    ; the claimed slot's byte offset
    lda z:US_SPAWN_IX
    asl                             ; *4 — two words per ring entry
    asl
    tax
    lda f:ring_off + 0, x           ; the ring's dx
    clc
    adc z:US_POSX + 2
    pha
    lda f:ring_off + 2, x           ; ...and dy
    clc
    adc z:US_POSY + 2
    ldx z:US_IDX
    sta f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    pla
    sta f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    lda #0                          ; a fresh chaser is not dying. pool_init
    sta f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x   ;   clears only the ALIVE array,
                                    ;   so this parallel field is power-on random
                                    ;   until a spawn writes it — rule 5's
                                    ;   write-before-read, discharged here.
                                    ;   `lda #0` + `sta` rather than `stz`: the
                                    ;   65816's STZ has no absolute-long-indexed
                                    ;   addressing mode, only DP/DP,X/abs/abs,X.
    ; ---- the cursor walks the ring, mod MO_RING_N -------------------------
    lda z:US_SPAWN_IX
    inc a
    cmp #MO_RING_N
    bcc @store_ix
    lda #0
@store_ix:
    .a16
    .i16
    sta z:US_SPAWN_IX
@done:
    .a16
    .i16
    rts

; --- do_chase: every live chaser steps toward the player --------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; One pixel per axis per frame, by the sign of the delta. The chasers FLOAT —
; they pass over the pillars, deliberately: a chaser that collided with the
; lattice could be boxed into a cell and stop being a threat, and only the
; player and the bolts are meant to care about cover.
;
; This runs in WORLD space and never reads the matrix, which is the rail's
; headline: what the picture is doing has no effect on where anyone is.
do_chase:
    .a16
    .i16
    ; ---- the half-rate gate: step on even frames only ---------------------
    ; The one tuning number here that is measured rather than inherited, and
    ; m7_oshoot.inc carries the arithmetic. In one line: at one px per axis per
    ; frame a chaser is FASTER than the hero on every heading but a cardinal,
    ; where it is slower by 0.25 px/frame — too little to clear the 12 px
    ; contact box inside a 40-frame grace. So the grace could never create
    ; separation and contact re-fired the frame it expired, forever. Stepping
    ; every other frame puts the hero ahead on every heading.
    ;
    ; The counter is free-running and read only for its parity, so it needs no
    ; wrap: US_CHASE_T rolls over at $FFFF -> $0000, and both are even.
    lda z:US_CHASE_T
    inc a
    sta z:US_CHASE_T
    lsr                             ; bit 0 -> C, and A is dead after this
    bcc @step
    rts                             ; odd frame — every chaser holds its ground
@step:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_ENE_ALIVE, x
    beq @next
    lda f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    bne @next                       ; DYING: it stops where the bolt found it.
                                    ;   That stillness is half of what makes the
                                    ;   death read as a death rather than as the
                                    ;   thing wandering off
    ; ---- x: chaser_x += sign(player_x - chaser_x) -------------------------
    lda z:US_POSX + 2
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    beq @y                          ; aligned on this axis
    bpl @x_pos
    lda f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    sec
    sbc #MO_ENE_SPEED
    bra @x_store
@x_pos:
    .a16
    .i16
    lda f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    clc
    adc #MO_ENE_SPEED
@x_store:
    .a16
    .i16
    sta f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
@y:
    .a16
    .i16
    lda z:US_POSY + 2
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    beq @next
    bpl @y_pos
    lda f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    sec
    sbc #MO_ENE_SPEED
    bra @y_store
@y_pos:
    .a16
    .i16
    lda f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    clc
    adc #MO_ENE_SPEED
@y_store:
    .a16
    .i16
    sta f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
@next:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a
    sta z:US_IDX
    cmp #(2 * MO_ENE_N)
    bcc @loop
    rts

; =============================================================================
; THE TWO COLLISIONS — both in WORLD space, neither reads the matrix
; =============================================================================
; --- do_bullet_hit: bolt x chaser --------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; A nested half-open AABB on world coordinates: overlap iff |dx| < MO_BULHIT_W
; AND |dy| < MO_BULHIT_W. Because it is world-space it is ROTATION-INVARIANT —
; the same bolt hits the same chaser at every heading, which is the property the
; rail exists to show and the one a screen-space test would destroy.
;
; ON A HIT BOTH SLOTS ARE FREED and the bolt is spent, so one bolt kills at most
; one chaser. THE ALLOCATE -> ACTIVE -> FREE -> REUSE CYCLE RUNS HERE: this is
; the path that returns a slot early, and the next `do_fire` claims it back.
;
; The bolt's world position is cached into US_CAND_PX/PY across the inner loop.
; That scratch is a call frame the collision pass finished with earlier in this
; same tick (move_x / move_y ran before the pivot pin), so reusing it costs
; nothing and claims nothing.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. abs16, POOL_BIND and pool_kill
; all hold the same contract; pool_kill does NOT preserve A (porting delta (b)),
; so the two kills below re-load X from DP rather than carrying anything in A.
do_bullet_hit:
    .a16
    .i16
    stz z:US_IDX
@b_loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_BUL_ALIVE, x
    bne @b_live
    jmp @b_next
@b_live:
    .a16
    .i16
    lda f:ES_MO_ACTORS_LONG + MO_BUL_WX, x
    sta z:US_CAND_PX
    lda f:ES_MO_ACTORS_LONG + MO_BUL_WY, x
    sta z:US_CAND_PY
    stz z:US_IDX2
@e_loop:
    .a16
    .i16
    ldx z:US_IDX2
    lda f:ES_MO_ACTORS_LONG + MO_ENE_ALIVE, x
    beq @e_next
    lda f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    bne @e_next                     ; a corpse absorbs nothing: a second bolt
                                    ;   flies through and stays live for a
                                    ;   chaser that can still be killed
    lda z:US_CAND_PX
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    jsr abs16
    cmp #MO_BULHIT_W
    bcs @e_next                     ; clear on x -> no overlap, whatever y says
    ldx z:US_IDX2
    lda z:US_CAND_PY
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    jsr abs16
    cmp #MO_BULHIT_W
    bcs @e_next
    ; ---- HIT: the bolt goes back, the chaser starts DYING ------------------
    ; The chaser's slot is NOT freed here. It is marked dying,
    ; which stops it chasing, stops it hurting the hero, stops it being re-killed
    ; and re-tints it — and do_deaths frees it when the flash has run out. The
    ; allocate -> active -> free -> REUSE cycle is unchanged; only the moment of
    ; the free moved, by MO_DEATH_FRAMES.
    ldx z:US_IDX2
    lda #MO_DEATH_FRAMES
    sta f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    POOL_BIND ES_MO_ACTORS_LONG + MO_BUL_ALIVE
    ldx z:US_IDX
    jsr pool_kill
    lda z:US_KILLS
    inc a
    sta z:US_KILLS                  ; monotonic, for the ROM's whole life
    lda z:US_SCORE                  ; ...and the SCORE, which a contact resets
    cmp #MO_SCORE_MAX
    bcs @scored                     ; clamped: three digits can always show it,
    inc a                           ;   and a wrap to 000 would read as the
    sta z:US_SCORE                  ;   reset that only a contact may mean
@scored:
    .a16
    .i16
    jmp @b_next                     ; the bolt is spent
@e_next:
    .a16
    .i16
    lda z:US_IDX2
    inc a
    inc a
    sta z:US_IDX2
    cmp #(2 * MO_ENE_N)
    bcs @b_next
    jmp @e_loop
@b_next:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a
    sta z:US_IDX
    cmp #(2 * MO_BUL_N)
    bcs @b_done
    jmp @b_loop
@b_done:
    .a16
    .i16
    rts

; --- do_contact: chaser x hero -----------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; World space again, and for the same reason: the picture rotates under the hero
; every frame, so a screen-space overlap would make contact depend on which way
; the player happens to be facing.
;
; A GRACE WINDOW guards the respawn. A knockback puts the hero back on the arena
; centre and the chasers converge there, so without it a hero who has just been
; hit is ground down by whatever was already closing on the spawn. The grace
; suppresses the HIT only — no chaser is moved, so what you see chasing is
; exactly what would have hit you.
;
; One hit per frame: the first overlap knocks back and returns.
do_contact:
    .a16
    .i16
    lda z:US_GRACE
    beq @scan
    dec a
    sta z:US_GRACE
    rts                             ; graced this frame — no contact at all
@scan:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_ENE_ALIVE, x
    beq @no
    lda f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    bne @no                         ; a corpse cannot hit you. Without this a
                                    ;   chaser killed ON TOP of the hero would
                                    ;   still take the score it just paid for
    lda z:US_POSX + 2
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WX, x
    jsr abs16
    cmp #MO_CONTACT_W
    bcs @no
    ldx z:US_IDX
    lda z:US_POSY + 2
    sec
    sbc f:ES_MO_ACTORS_LONG + MO_ENE_WY, x
    jsr abs16
    cmp #MO_CONTACT_W
    bcc @hit
@no:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a
    sta z:US_IDX
    cmp #(2 * MO_ENE_N)
    bcc @loop
    rts
@hit:
    .a16
    .i16
    ; ---- knock the hero home, and say so ---------------------------------
    lda #MO_SPAWN_PX
    sta z:US_POSX + 2
    stz z:US_POSX + 0
    lda #MO_SPAWN_PY
    sta z:US_POSY + 2
    stz z:US_POSY + 0
    stz z:US_SPEED                  ; the knockback halts the walk; the FACING is
    stz z:US_STRAFE                 ;   preserved, so you are still aiming. Both
                                    ;   are recomputed next tick from the pad —
                                    ;   these stores are what stops the rest of
                                    ;   THIS tick moving the hero back off spawn
    lda z:US_HITS
    inc a
    sta z:US_HITS
    stz z:US_SCORE                  ; ...AND THE SCORE GOES. That is the stake
                                    ;   the knockback already moves
                                    ;   the world out from under you and blinks,
                                    ;   but neither costs you anything you were
                                    ;   accumulating, so there was no reason to
                                    ;   avoid contact beyond mild annoyance. The
                                    ;   counterplay is real rather than nominal —
                                    ;   the half-rate chase is what makes
                                    ;   the grace window escapable at every
                                    ;   heading, so a lost score is a mistake
                                    ;   rather than a dice roll. US_KILLS is NOT
                                    ;   reset: it stays monotonic so the
                                    ;   pool-cycle observables keep their meaning.
    lda #MO_GRACE_FRAMES
    sta z:US_GRACE                  ; ...which is ALSO the blink phase the cue
                                    ;   reads. THE "OW" IS LOCALISED: it is the
                                    ;   hero's own sprite flickering, drawn in
                                    ;   do_hit_blink, and nothing here touches a
                                    ;   PPU brightness register.
                                    ;
                                    ; This used to snap ES_FADE_CTL (INIDISP
                                    ; brightness) to 1 and re-arm fade_start_in.
                                    ; The reasoning was sound — the hero is
                                    ; screen-fixed, so the teleport is invisible
                                    ; on him and needs SOME cue — but the remedy
                                    ; was a full-screen flash to near-black on
                                    ; every contact. With contact re-firing each
                                    ; time the grace expired (see MO_CHASE_HALF)
                                    ; that ran at ~1.5 Hz forever: the scene
                                    ; constantly flipped to black and faded back
                                    ; in, with 27% of frames dimmed and 8% of
                                    ; them near-black. A whole-screen strobe at
                                    ; that rate is also a photosensitivity
                                    ; hazard, so no tuning of it was acceptable
                                    ; — the cue had to stop being full-screen.
                                    ; The cue is now entirely on the sprite;
                                    ; nothing here writes INIDISP at all.
    rts

; --- do_hit_blink: the invulnerability flicker — THE hit cue -----------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Runs AFTER obj_draw, and un-draws rather than pre-empting, which is the whole
; reason it can live in the scene: obj_draw is mo_obj's, it places the hero
; unconditionally at the pin, and the decision of whether the hero is VISIBLE is
; the game's — it is a function of US_GRACE, which is this scene's own declared
; state. Gating inside obj_draw would make a scene-scoped feature read the
; game's `[scene.*]` block, the inversion state.toml's header argues against.
; The cost is one mo_put whose bytes are overwritten, on one frame in eight of a
; 40-frame window — a few dozen cycles per hit, against an interface change to a
; feature and a dependency pointing the wrong way.
;
; WHY THE HERO AND NOT THE SCREEN. He is SCREEN-FIXED: m7a_set_center re-pins
; the pivot to his world position every frame, so the knockback teleports the
; FLOOR out from under him and his own OAM entry never moves. Something has to
; say "that was damage" or the teleport reads as the world glitching. The
; earlier cue here was INIDISP brightness — a full-screen snap to near-black
; on every contact — which read as the scene constantly flipping to black, and
; which at ~1.5 Hz is a photosensitivity hazard as well as a bad
; read. A blink on a 16x16 sprite is the genre's own answer: localised to 0.4% of
; the screen, unambiguous (nothing else in this rail blinks), and it says the
; second half — "and you are briefly safe" — which a screen flash cannot.
;
; The residue, stated: the parked frame keeps the hi-table bits mo_put already
; OR'd in (X9 = 0, size = 1). It cannot show — MO_PARK_Y is 240 and a 16 px
; sprite there spans 240..255, entirely below the 224-line screen — and X9 is
; rebuilt whole every frame by mo_hi_clear, so the stale-X9 class this feature
; is written against is not reachable through it.
do_hit_blink:
    .a16
    .i16
    lda z:US_GRACE
    beq @done                       ; not graced — the hero draws as normal
    and #MO_BLINK_MASK
    bne @done                       ; the lit half of the phase
    ldx #(ES_O_HERO * 4)
    jsr mo_park_slot                ; the dark half — not emitted this frame
@done:
    .a16
    .i16
    rts

; =============================================================================
; THE DEATH FLASH — a kill that cannot be mistaken for a despawn
; =============================================================================
; --- do_deaths: age every dying chaser; free the ones that are done ---------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; A bolt hit sets MO_ENE_DYING instead of freeing the slot, so the chaser stays
; ALIVE-but-dying for MO_DEATH_FRAMES: it stops chasing, cannot hurt the hero,
; cannot be re-killed, and draws in the score band while it flashes. This is the
; countdown, and the free at the end of it.
;
; WHY IT IS NOT A DESPAWN. The chaser dies WHERE IT WAS STANDING and says so for
; 0.4 s. A slot that simply vanished between two frames — which is what a bolt's
; TTL expiry does, deliberately, four routines up — is indistinguishable from one
; that walked off. The difference has to be VISIBLE; this is
; the mechanism, and the two are side by side in the same ROM so a test can
; assert on the contrast rather than on one of them alone.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND requires A16 and
; leaves it; pool_kill holds the same contract and PRESERVES X but not A.
do_deaths:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_ENE_ALIVE, x
    beq @next                       ; a free slot has no death to age
    lda f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    beq @next                       ; ...and neither does a live one
    dec a
    sta f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    bne @next                       ; still flashing
    POOL_BIND ES_MO_ACTORS_LONG + MO_ENE_ALIVE
    ldx z:US_IDX
    jsr pool_kill                   ; the flash is over: the slot goes back, and
                                    ;   the next wave beat can claim it
@next:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a
    sta z:US_IDX
    cmp #(2 * MO_ENE_N)
    bcc @loop
    rts

; --- do_death_flash: re-tint the dying, and blink them ----------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Runs AFTER obj_draw and OVERWRITES what it placed, on exactly do_hit_blink's
; argument: obj_draw is mo_obj's and it places every live chaser identically,
; while "is this one dying, and is this its lit frame" is the GAME's question —
; it is a function of this scene's own pool field. Gating inside MO_DRAW_POOL
; would make a scene-scoped feature branch on game state.
;
; TWO CUES, not one. The attribute byte moves to the score's palette band, so the
; corpse is a colour nothing else on screen can be; and it blinks on the same
; 4-frame phase the hero's hit cue uses, so "something just happened here" reads
; the same way in both directions. The cost is one byte store plus, on half the
; frames, one park, for at most six slots.
;
; WIDTH-RISK: toggles A8 for the single attribute-byte store and restores A16
; before the loop test. `sep #$20` only — I-width must not leak, X is the cursor.
do_death_flash:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    ldx z:US_IDX
    lda f:ES_MO_ACTORS_LONG + MO_ENE_ALIVE, x
    beq @next
    lda f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x
    beq @next
    and #MO_DEATH_BLINK
    beq @dark                       ; the dark half of the phase
    txa
    asl                             ; cursor * 2 = the slot within the range...
    clc
    adc #(ES_O_ENEMIES * 4)         ; ...and its byte offset in the shadow
    tax
    sep #$20
    .a8
    lda #(MO_PRIO | MO_PAL_SCORE)
    sta a:ES_OAM_SHADOW + 3, x      ; byte 3 = the attribute: the score's band
    rep #$20
    .a16
    bra @next
@dark:
    .a16
    .i16
    txa
    asl
    clc
    adc #(ES_O_ENEMIES * 4)
    tax
    jsr mo_park_slot                ; not emitted this frame — the flicker half
@next:
    .a16
    .i16
    lda z:US_IDX
    inc a
    inc a
    sta z:US_IDX
    cmp #(2 * MO_ENE_N)
    bcc @loop
    rts

; =============================================================================
; THE SCORE — three digits, drawn from US_SCORE every frame
; =============================================================================
; --- do_score_draw: US_SCORE -> the three HUD slots -------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Repeated subtraction rather than a divide: the 65816 has no divide, the value
; is clamped to 999, and three subtract loops that each run at most nine times
; cost well under a hundred cycles. A table of 1000 entries would cost 3 KB of
; the ROM budget to save that.
;
; DRAWN EVERY FRAME, not on change. The OAM shadow is rebuilt from scratch each
; frame by obj_draw's hi-clear and park loops, so "only redraw when it moves"
; would need the digits to survive a clear they do not survive — and three
; mo_put calls is cheaper than the flag that would decide to skip them.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep here. mo_score_digit toggles A8
; inside mo_put and restores A16; it clobbers X, which is why the digit index is
; re-loaded rather than carried.
do_score_draw:
    .a16
    .i16
    lda z:US_SCORE
    ldy #0                          ; Y = the hundreds digit
@hundreds:
    .a16
    .i16
    cmp #100
    bcc @tens
    sec
    sbc #100
    iny
    bra @hundreds
@tens:
    .a16
    .i16
    sta z:US_CAND_FR                ; park the remainder: X and Y are both spoken
    tya                             ;   for and mo_score_digit clobbers A too
    ldx #0
    jsr mo_score_digit
    lda z:US_CAND_FR
    ldy #0
@tens_loop:
    .a16
    .i16
    cmp #10
    bcc @units
    sec
    sbc #10
    iny
    bra @tens_loop
@units:
    .a16
    .i16
    sta z:US_CAND_FR
    tya
    ldx #1
    jsr mo_score_digit
    lda z:US_CAND_FR
    ldx #2
    jsr mo_score_digit
    rts

; --- abs16: A = |A|, signed 16-bit ------------------------------------------
; In/out: A16/I16. Clobbers A only — X and Y survive, which is what lets the two
; scans above keep their cursors across both axis tests.
abs16:
    .a16
    .i16
    bpl @done
    eor #$FFFF
    inc a
@done:
    .a16
    .i16
    rts

; =============================================================================
; THE CENSUS — the two pool_count observables
; =============================================================================
; --- do_census: publish both live counts, once per frame --------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; The two live counts are published into this rail's own declared state once per
; frame. BOTH are published, because the chaser count is the one word that shows
; the whole allocate -> active -> free -> reuse cycle: it climbs on a wave beat
; and falls when a bolt lands.
;
; READ-ONLY OBSERVABLES. Nothing in this rail branches on either word, which is
; what makes the census render-neutral and what makes the counts safe to assert
; on: a test reading them cannot be reading something the game reacted to.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND requires A16 and
; leaves it; `pool_count` holds the same contract on both sides.
do_census:
    .a16
    .i16
    POOL_BIND ES_MO_ACTORS_LONG + MO_BUL_ALIVE
    ldx #MO_BUL_N
    jsr pool_count
    sta f:US_SHOTS_LIVE_LONG
    POOL_BIND ES_MO_ACTORS_LONG + MO_ENE_ALIVE
    ldx #MO_ENE_N
    jsr pool_count
    sta f:US_CHASERS_LIVE_LONG
    rts

; =============================================================================
; DATA — the wave ring
; =============================================================================
; Eight offsets from the player, one per compass point, ~120 world px out: far
; enough that a spawn is off-screen (the visible half-width is 128) and close
; enough to stay inside m7_project's pre-cull radius, so a chaser is projected
; and culled by the SCREEN test from the moment it exists. Signed, two's
; complement.
ring_off:
    .word      0, $FF88            ; N   (   0, -120)
    .word     85, $FFAB            ; NE  ( +85,  -85)
    .word    120,     0            ; E   (+120,    0)
    .word     85,    85            ; SE  ( +85,  +85)
    .word      0,   120            ; S   (   0, +120)
    .word  $FFAB,    85            ; SW  ( -85,  +85)
    .word  $FF88,     0            ; W   (-120,    0)
    .word  $FFAB, $FFAB            ; NW  ( -85,  -85)

; =============================================================================
; DELETED — the eight-way heading table
; =============================================================================
; `dir8_angle` stood here: sixteen words indexed by a UDLR bitfield, mapping each
; d-pad combination to one of eight compass headings that US_HEADING was SNAPPED
; to. It, `do_aim`, `US_DIR_BITS` and `US_MOVING` are all gone.
;
; The table is recorded as deleted rather than silently dropped because the shape
; of the defect matters: it was not a tuning value, it was a QUANTISER, and it
; produced both halves of the reported defect — a 45 degree jolt on every
; direction change (32 of the LUT's 256 units in one frame) and a d-pad whose
; meaning moved with the view (the button chose a WORLD heading, and the view had
; just rotated). Removing rather than bypassing is deliberate: a path that can
; still snap the heading is a regression waiting to return.
;
; The engine was never the limit. m7_affine tabulates 256 headings at 1.4 degrees
; apiece; the game layer chose 8 of them.

.endscope
