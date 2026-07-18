; =============================================================================
; sf_enemy.inc — enemy patrol + stomp macros (macro library)
; =============================================================================
; Two surfaces: sf_patrol_step (autonomous pacing) and sf_stomp_check
; (stomp-style contact resolution — land on top to defeat, anything else
; hurts). Together they make enemies that walk their beats and can be
; stomped.
;
; Horizontal patrol for platform enemies: walk at SF_PATROL_SPEED, turn
; around at solid walls AND at ledge edges, so an enemy placed on a platform
; paces it end-to-end forever without falling off (the "red Koopa" patrol).
; Built over the tile-collision surface: walls use the same SF_FLAG_SOLID
; tiles that block the player; the ledge probe is a single-point col_map at
; the LEADING bottom corner (turn the moment the front foot would step into
; air — the enemy never overhangs the edge).
;
; Enemies are plain 8x8 integer-pixel actors: they stand ON terrain (you
; place ey = platform_top - 8) and don't need the physics integrator. Run
; one sf_patrol_step per enemy per frame, then draw with spr. For
; player-enemy contact, col_box the two boxes in your game loop (see the
; patrol template: contact -> respawn + a HITS counter).
;
; Tuning (kit default; to override, define before .include'ing this file):
;   SF_PATROL_SPEED = 1   (px/frame; must stay <= 8 — the box/corner probes
;                          cover one tile of step, same bound as physics)
;
; Requires: sf_map.inc (sf_solid_box, col_map; flag terrain SF_FLAG_SOLID
; and build the map with mset first).
; =============================================================================

.ifndef SF_ENEMY_INC
SF_ENEMY_INC = 1

.include "sf_map.inc"
.include "sf_collision.inc"     ; col_box (sf_stomp_check's overlap test)

.ifndef SF_PATROL_SPEED
SF_PATROL_SPEED = 1
.endif
.assert SF_PATROL_SPEED <= 8, error, "SF_PATROL_SPEED > 8 px/frame outruns the wall/ledge probes"

.ifndef SF_BOUNCE_VEL
SF_BOUNCE_VEL = $0300           ; stomp bounce: 3 px/f up (~17px hop)
.endif
.assert SF_BOUNCE_VEL <= $0800, error, "SF_BOUNCE_VEL > 8 px/frame can tunnel through ceilings"

; How deep (px) the player's bottom may be inside the enemy's top for the
; contact to count as a stomp. SF_MAX_FALL=4 means a falling player first
; touches within 4px, so 5 covers every landing; side/below contact runs
; deeper and classifies as hurt.
SF_STOMP_DEPTH = 5

; -----------------------------------------------------------------------------
; sf_patrol_step ex, ey, edir, newx, leadx, footy — one frame of patrol.
; -----------------------------------------------------------------------------
;   ex     DP word: enemy x (pixels) — committed only when the step is safe
;   ey     DP word: enemy y (pixels, top of the 8x8 box; on terrain = top-8)
;   edir   DP word: 0 = walking left, 1 = walking right (flips on turns)
;   newx   DP word: scratch (the tentative x)
;   leadx  DP word: scratch (leading bottom-corner x for the ledge probe)
;   footy  DP word: scratch (ey+8, the tile row under the feet)
; Turn (direction flip, no move) happens on EITHER: the tentative box
; overlapping a solid (wall ahead), or the leading corner's foot point
; having NO solid under it (ledge ahead). Otherwise the step commits.
; Place ex ON the terrain run being patrolled: the probes are forward-only
; (the trailing edge is never re-checked), so the never-overhang guarantee
; is inductive from a valid start position.
; Clobbers A, X, Y. One call per enemy per frame; each enemy needs its own
; ex/ey/edir (scratch can be shared between enemies — it's consumed within
; the call).
;
; WIDTH-RISK: asserts A16/I16 entry; all arithmetic A16; exits A16. Contains
; sf_solid_box + col_map expansions — internal control flow uses .local
; labels + jmp trampolines (and ends any caller cheap-local `@` scope; see
; lib/macros/README.md).
.macro sf_patrol_step sf_ex, sf_ey, sf_edir, sf_newx, sf_leadx, sf_footy
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
    ; wall ahead? (full box at the tentative position)
    sf_solid_box sf_newx, sf_ey
    beq no_wall
    jmp turn
no_wall:
    .a16
    ; ground under the leading corner? (single-point probe)
    col_map #1, sf_leadx, sf_footy, #0
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

; -----------------------------------------------------------------------------
; sf_stomp_check px, pyi, vy, ex, ey, ealive -> A — classify player contact.
; -----------------------------------------------------------------------------
;   px      DP word: player x (pixels)
;   pyi     DP word: player y (the integer draw pixel, NOT the 8.8 pyf)
;   vy      DP word: the player's signed 8.8 velocity (sf_physics owns it) —
;           WRITTEN on a stomp (bounce)
;   ex, ey  enemy position (verbatim operands; ey may be an immediate)
;   ealive  DP word: 1 = alive / 0 = dead — WRITTEN on a stomp
; Returns in A:
;   0 = no contact (also when the enemy is already dead — dead enemies are
;       transparent; gate their patrol + draw on ealive yourself)
;   1 = STOMP: the player was FALLING (vy > 0) and their bottom is within
;       SF_STOMP_DEPTH of the enemy's top. The macro kills the enemy
;       (ealive = 0) and bounces the player (vy = -SF_BOUNCE_VEL) — the next
;       sf_physics_step rises into the hop automatically.
;   2 = HURT: any other contact (side, standing, rising from below) —
;       respond in the caller (respawn, lives, knockback).
; Call AFTER sf_physics_step (pyi/vy reflect this frame), once per enemy.
; With multiple enemies, resolve at most one contact per frame (early-out on
; the first stomp/hurt, as the templates do) — check order is priority.
; Clobbers A, X, Y. Idiom:
;   sf_stomp_check PX, PYI, VY, E1X, #200, E1ALIVE
;   cmp #2 / beq took_hit  /  cmp #1 / beq scored_stomp
;
; WIDTH-RISK: asserts A16/I16 entry; all arithmetic A16; exits A16 with the
; result in A. Contains a col_box expansion — control flow uses .local
; labels + jmp trampolines (ends caller cheap-local `@` scope).
.macro sf_stomp_check sf_px, sf_pyi, sf_vy, sf_ex, sf_ey, sf_ealive
    .local alive, contact, hurt, none, done
    rep #$30
    .a16
    .i16
    lda sf_ealive
    bne alive
    jmp none
alive:
    .a16
    col_box sf_px, sf_pyi, #8, #8,  sf_ex, sf_ey, #8, #8
    bne contact
    jmp none
contact:
    .a16
    lda sf_vy
    beq hurt                    ; standing -> side contact
    bmi hurt                    ; rising -> hit from below
    lda sf_pyi                  ; falling: how deep into the enemy's top?
    clc
    adc #8                      ; player's bottom edge (exclusive)
    sec
    sbc sf_ey
    cmp #SF_STOMP_DEPTH + 1
    bcs hurt                    ; too deep -> side contact mid-fall
    stz sf_ealive               ; STOMP: kill + bounce
    lda #(($10000 - SF_BOUNCE_VEL) & $FFFF)
    sta sf_vy
    lda #$0001
    bra done
hurt:
    .a16
    lda #$0002
    bra done
none:
    .a16
    lda #$0000
done:
    .a16
.endmacro

.endif ; SF_ENEMY_INC
