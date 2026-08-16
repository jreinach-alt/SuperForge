; =============================================================================
; scenes/dungeon.asm — the Mode 7 plane, and the game played on it
; =============================================================================
; TANK CONTROLS. The hero's facing always reads "up" because the hero never
; moves: he is pinned at the affine pivot, and it is the FLOOR that rotates and
; scrolls underneath. LEFT/RIGHT turn the heading, B or UP throttles forward
; along it, Y or DOWN reverses, release coasts to a stop. Walls block, three
; slimes pace the corridors and knock you home on a touch, the goal cell raises
; a banner, START freezes everything but the picture.
;
; THE CAMERA, in three lines:
;
;   m7a_set_heading(US_HEADING)    the LUT entry -> the DP matrix shadow
;   m7a_set_center(pos)            the pivot     -> M7X/M7Y + the screen origin
;   (NMI) m7a_nmi_commit           the shadow    -> the eight ports, latched
;                                  together before scanline 0
;
; No trigonometry, no HDMA channel and no per-scanline table: at a fixed scale
; the matrix is a pure function of one byte, so all 256 answers are tabulated at
; build time (m7_affine's feature.toml carries the full argument). The ONE
; multiply the rail needs — a matrix coefficient times the speed, which is the
; 16.16 step — is m7_project's software shift-add.
;
; EVERYTHING BELOW THE INCLUDES IS THE GAME. Four traps in its handling are
; DELIBERATELY PRESERVED rather than quietly fixed, because the recorded route
; through this maze was driven against them and a reference render is worth
; nothing once the behaviour under it has changed. Which traps, and why each is
; kept, is stated at each site.
;
; The scene map is included INSIDE this scope, and so is the scene-scoped
; feature that reads it — m7dg_floor names ES_D_M7DG_UP_CH, ES_C_M7DG_PAL and
; ES_R_M7DG_PAL_SIZE, and those are dungeon's symbols, not the game's. The
; globals (ES_M7AFF, ES_R_M7DG_MAP_*, the blob labels) resolve outward through
; the enclosing file scope, exactly as the generated header describes.

.scope dungeon

.include "engine_state_dungeon.inc"  ; GENERATED — this scene's map
.include "m7dg_floor.asm"            ; scene-scoped feature: the plane's upload

; --- the pivot: the maze's START cell, derived the generator's own way -------
; The camera sits where the hero spawns — the pivot IS his world position — so
; the rail frames the same corner of the maze the ground-truth render does.
;
; The maze is a bounded ISLAND in a solid plane: it spans world tiles 6..~51 out
; of 128, and everything outside it is flat void. A pivot at the map's numeric
; middle (tile 64) is therefore off the maze entirely and renders a featureless
; checkerboard — correct Mode 7, and a picture that shows none of the rail.
;
; These five constants MIRROR tools/gen_m7_dungeon_assets.py's own cell algebra
; (ORIGIN_TX/TY=6, PITCH=CELL+WALL_T=5, WALL_T=2, CELL=3, and 'S' at cell 1,1);
; cell_world_center() computes exactly this expression there. Written as the
; algebra rather than as the 116 it evaluates to for the same reason the
; generator refuses a literal: the number is a consequence of the maze, and if
; the maze moves this follows it.
; TM's layer bits ($212C). Named rather than spelled as one hex byte so the
; two layers this scene composites are legible at the write site.
TM_BG1 = $01
TM_OBJ = $10

MAZE_ORIGIN_T = 6                       ; world tile of the maze's top-left wall
MAZE_WALL_T   = 2                       ; wall band thickness, in tiles
MAZE_CELL     = 3                       ; floor tiles per logical cell edge
MAZE_PITCH    = MAZE_CELL + MAZE_WALL_T ; world tiles per cell step
SPAWN_CX      = 1                       ; the 'S' cell, MAZE[1][1]
SPAWN_CY      = 1

; cell index -> the world PIXEL at that cell's centre. This is exactly the
; generator's cell_world_center(), as an expression the assembler evaluates:
; the cell's first floor tile, plus half the cell, times eight, plus half a
; tile. Every world position this rail names goes through it, so the pivot and
; the patrol seeds cannot drift apart if the maze moves.
.define CELL_PX(c)  ((MAZE_ORIGIN_T + (c) * MAZE_PITCH + MAZE_WALL_T + MAZE_CELL / 2) * 8 + 4)

DUNGEON_MID_X = CELL_PX(SPAWN_CX)
DUNGEON_MID_Y = CELL_PX(SPAWN_CY)

; --- the patrol seeds -------------------------------------------------------
; Three enemies, on navigable cell centres of the START->GOAL route, SPREAD by
; distance from the spawn so that culling is exercised rather than asserted.
; From the pivot at cell (1,1): the first is five tiles away and on screen at
; all 256 headings; the second is 179 px out and reaches the padded view only
; where the rotation swings it into a corner (headings 10 and 11, measured);
; the third is 256 px out, past the circumradius, and is pre-culled at every
; heading without a single multiply. Those distances are the SEEDS' — the
; enemies pace, so this table is where they start and US_ENE_POS is
; where they are.
;
; Read by m7dg_obj's obj_draw and seeded into the live patrol state at enter;
; defined HERE, above the include, because a forward reference from inside a
; scope is resolved against the ENCLOSING scope in ca65 and would not find a
; label this scope defines later.
enemy_world:
    .word CELL_PX(2), CELL_PX(1)        ; near start   — px (156,116)
    .word CELL_PX(5), CELL_PX(3)        ; mid path     — px (276,196)
    .word CELL_PX(6), CELL_PX(5)        ; before the goal — px (316,276)

; The cast's own scene-scoped feature. It follows enemy_world for the reason
; that table's comment gives, and it names this scene's ES_D_MDO_UP_*,
; ES_V_OBJ_CHR*, ES_C_*_PAL and ES_O_* symbols the same way m7dg_floor names
; the plane's.
;
; WHERE THE ENEMIES ARE is bound here rather than named in the feature: they
; PACE now, so the ROM table above is the spawn SEED and the live position is
; scene state. Binding the one symbol is what keeps the sprite and the wall
; test reading the same coordinate.
MDO_ENEMY_POS = US_ENE_POS
.include "m7dg_obj.asm"

; --- col_map's world binding ------------------------------------------------
; Declared at the COMPOSITION site, not in the feature: col_map carries no
; default for any of these, because a defaulted world size reads real ROM bytes
; at the wrong stride and returns a plausible flag. Each name is
; `::`-qualified — ca65 defers an unqualified parent-scope lookup, and a
; deferred symbol is not a constant expression, which col_map's assembly-time
; `.if CM_WORLD_BLOB_CHUNKS` needs it to be.
;
; THE WORLD IS 128x128 TILES, so both log2s are 7 — and that is asserted
; against the blob's own emitted size rather than stated, so a re-themed map of
; a different size stops the build here instead of reading the wrong stride.
CM_WORLD_W_LOG2      = 7
CM_WORLD_H_LOG2      = 7
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_M7DG_TILEMAP_SIZE, error, "col_map world size disagrees with the m7dg_tilemap claim"

; The PACKED tile-id map, not the interleaved plane: col_map's index is
; `ty * W + tx` over contiguous bytes.
CM_WORLD_BLOB        = ::ES_R_M7DG_TILEMAP_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_M7DG_TILEMAP_BANK
; DERIVED from the claim's own size, not narrated: at 16 KB against a 32 KB
; LoROM window this is 1, and the day the world grows past a window it becomes
; 2 without anyone editing a number. `32768` here is the window SIZE in bytes,
; which is silicon — the same value col_map.asm's own `rpc = 32768 / W` names.
CM_WORLD_BLOB_CHUNKS = (::ES_R_M7DG_TILEMAP_SIZE + 32767) / 32768
;
; HOW THIS RAIL DISCHARGES col_map's BANK-ADJACENCY OBLIGATION: it does not
; have one, and that is checkable rather than lucky. col_map's contract asks a
; MULTI-chunk includer to assert its chunk banks are consecutive (microzero
; and the cost probe both paste those two lines). At CHUNKS = 1 col_map takes
; its constant-bank branch and never adds a chunk index, so there is nothing
; to be consecutive.
;
; The obvious guard here — `.assert CM_WORLD_BLOB_CHUNKS = 1` — was written
; and then REMOVED, because it cannot fail in any build that assembles, and an
; assert that cannot fire reads as coverage without being any. Every route to
; CHUNKS >= 2 is already refused upstream of it, each measured:
;   * mark the claim `bank_tiled` -> the plain `ES_R_M7DG_TILEMAP_SIZE`/
;     `_ADDR`/`_BANK` symbols cease to exist (a tiled claim emits only
;     `_T<i>_*` + `_CHUNKS`), so the three CM_* bindings above and the size
;     assert below fail as undefined symbols, and `make rom-unbacked` fails
;     first anyway because the `.incbin` site in main.asm no longer credits
;     the renamed claims;
;   * grow it past a window and leave it a DMA source (the default) -> the
;     ALLOCATOR refuses: "40000 B exceeds the 32768 B LoROM DMA window and is
;     a DMA source ... Mark it bank_tiled (pre-chunked) or split the asset";
;   * grow it past a window with `dma_source = false` -> `place_rom` chunks it
;     anyway but suffixes nothing, emitting `ES_R_M7DG_TILEMAP_SIZE` TWICE
;     (32768, then 7232) — ca65 refuses the redefinition.
; So the guard is the undefined-symbol / duplicate-symbol error, which is this
; repo's stated design review, not a line of ASM. Grow the map and the build
; stops; it just stops one layer up from here.
CM_FLAGS             = ::m7dg_flags_bin
.include "col_map.asm"

; =============================================================================
; THE GAME'S OWN CONSTANTS
; =============================================================================
; The numbers, re-expressed as the algebra they are. `no_literals` refuses
; a bare 1023 (it lands inside an emitted WRAM claim and cannot be told apart
; from a hand-narrated address), and that refusal is doing real work here: the
; walkable plane is 1023 px because the world is 128 tiles of 8, which is
; col_map's own binding, so writing the derivation makes the two follow each
; other instead of agreeing by coincidence.

; --- the world ------------------------------------------------------------
WORLD_MAX = (1 << (CM_WORLD_W_LOG2 + 3)) - 1  ; 1023: the last walkable pixel
HERO_HALF = 4                                 ; the body is an 8 px box...
FP_NEAR   = (0 - HERO_HALF) & $FFFF           ; ...near edge  = centre - 4
                                              ; (masked to the word the `adc`
                                              ; immediate actually is: ca65
                                              ; refuses a negative there)
FP_FAR    = HERO_HALF - 1                     ; ...far  edge  = centre + 3
                                              ; NOT +HERO_HALF. A 4-corner probe
                                              ; at centre+4 spans NINE pixels and
                                              ; catches the wall one px early.

; --- the tank -------------------------------------------------------------
; Speed is SIGNED 8.8 px/frame. The cap is deliberately slow: the per-frame
; collision steps ONCE, so a hero faster than the 16 px wall band could cross it
; between two footprint probes and tunnel through.
TURN_STEP = 1                        ; heading units per held LEFT/RIGHT frame
ACCEL     = $10                      ; +1/16 px/frame per held throttle frame
DECEL     = ACCEL / 2                ; bled per coasting frame, toward rest
SPEED_CAP = ACCEL * 20               ; $0140 = +1.25 px/frame forward
SPEED_REV = (0 - SPEED_CAP) & $FFFF  ; ...and its negative, the reverse cap

; --- the pad --------------------------------------------------------------
; The auto-joypad word input_read latches into ES_INP_CUR ($4218's layout).
; Written as BIT POSITIONS, following room_logic.asm:27 — and not only for
; house style: `no_literals` reads a bare $0200 as an address, because it is
; one (it lands inside the OAM shadow's WRAM claim). A shift says "bit 9 of a
; hardware word", which is what these are.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11
JOY_START = 1 << 12
JOY_Y     = 1 << 14
JOY_B     = 1 << 15

; --- spawn, and the enemies that pace around it ---------------------------
; The spawn IS the affine pivot: the hero is pinned at screen centre, so the
; point the floor turns about and the point the hero stands on are one thing.
SPAWN_PX = DUNGEON_MID_X
SPAWN_PY = DUNGEON_MID_Y
ENEMY_COUNT  = ES_O_ENEMIES_SPRITES  ; DERIVED from the oam claim, not counted
PATROL_SPEED = 1                     ; world px/frame, one step per enemy
PATROL_AXIS_Y = 1                    ; the one enemy that paces N-S; the other
                                     ;   two pace E-W (a baked dispatch)

; --- contact --------------------------------------------------------------
; The threshold that is actually tested on each axis is 8 px, so 8 is what is
; written here, under the name the code means.
CONTACT_W       = 8                  ; |dx| < 8 AND |dy| < 8 on both axes
GRACE_FRAMES    = 40                 ; post-respawn frames with contact off
SPAWN_SANCTUARY = CONTACT_W          ; no hit while standing on the spawn tile
FLASH_LEVEL     = 1                  ; the brightness a hit snaps INIDISP to

; --- the goal, and its win card -------------------------------------------
; The 'G' cell of the generator's maze, through the same cell algebra the pivot
; and the patrol seeds use. GOAL_HALF is half the 24 px cell floor body.
GOAL_CX   = CELL_PX(7)
GOAL_CY   = CELL_PX(7)
GOAL_HALF = 12
WIN_GAP   = 2 * MDO_SIZE                     ; 32 px between the three stars
WIN_ROW_Y = 28                               ; the banner row, clear of the hero
WIN_ATTR  = MDO_PRIO | MDO_PAL_WIN
WIN_X0    = MDO_CX - MDO_HALF - WIN_GAP      ; the middle star's CENTRE lands on
WIN_X1    = MDO_CX - MDO_HALF                ;   screen centre; the outer two
WIN_X2    = MDO_CX - MDO_HALF + WIN_GAP      ;   sit a sprite-and-a-half either
                                             ;   side

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 9 colours + M7SEL
    jsr obj_arm                     ; 3 sprite sheets + 3 OBJ palettes + OBSEL

    ; ---- the world, seeded before the first NMI is ever armed -------------
    ; Power-on WRAM is random and m7_affine declares NO `[init] zero` for its
    ; shadow (feature.toml says so, and says why): what follows IS the
    ; write-before-read contract for all sixteen bytes of ES_M7AFF and for
    ; every byte of this scene's own state. Not defensive initialisation —
    ; rule 5. The per-frame scratch (US_STEP*, US_CAND_*, US_IDX) is absent on
    ; purpose: every one of those is written before it is read inside a single
    ; tick, and pre-filling them would hide the day that stops being true.
    stz z:US_HEADING                ; heading 0 = the identity matrix
    lda #SPAWN_PX                   ; the hero, on the maze's START cell
    sta z:US_POSX + 2               ;   16.16: integer px at +2...
    stz z:US_POSX + 0               ;   ...and no fraction yet
    lda #SPAWN_PY
    sta z:US_POSY + 2
    stz z:US_POSY + 0
    stz z:US_SPEED                  ; at rest, no throttle held
    stz z:US_HITS                   ; the director's latches. HITS and PAUSED
    stz z:US_GRACE                  ;   are what the tests read, so a random
    stz z:US_PAUSED                 ;   power-on value here would be a fail
    stz z:US_PREV_START             ;   that looks like a logic bug

    ; ---- the enemies: the ROM seeds become live state ---------------------
    ; A straight copy, because `enemy_world` and US_ENE_POS have the SAME
    ; interleaved (x, y) layout on purpose — that is also the layout
    ; m7dg_obj's MDO_ENEMY_POS binding walks, so one table shape serves the
    ; seed, the patrol and the projection. The count is the OAM claim's, so a
    ; fourth slime is a claim edit and not an edit here.
    .repeat ENEMY_COUNT * 2, ew
        lda f:enemy_world + ew * 2
        sta z:US_ENE_POS + ew * 2
    .endrepeat
    .repeat ENEMY_COUNT, ed
        lda #PATROL_SPEED           ; every enemy starts pacing FORWARD; the
        sta z:US_ENE_DIR + ed * 2   ;   first wall it meets reverses it
    .endrepeat

    ldx #DUNGEON_MID_X
    ldy #DUNGEON_MID_Y
    jsr ::m7a_set_center            ; pivot -> M7X/M7Y + the screen origin
    lda z:US_HEADING
    jsr ::m7a_set_heading           ; heading -> M7A..M7D

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on m7dg_floor's
    ; behalf (see that feature.toml's attribution note). M7SEL is the
    ; feature's own and floor_arm has already written it.
    ;
    ; TM CARRIES BOTH LAYERS, and it has to: it is ONE register with one owner,
    ; and turning OBJ on is not something m7dg_obj can do behind the scene's
    ; back. Leaving bit 4 clear is the exact shape of a bug that looks like a
    ; sprite bug — OAM correct, OBJ CHR correct, OBJ palette correct, hi table
    ; correct, and nothing on screen, because the main screen was never told
    ; to composite the layer.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #(TM_BG1 | TM_OBJ)          ; TM: the plane AND the cast
    sta a:$212C

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate; call it from A16 and
    ; the CPU eats the following opcode byte as that immediate's high half, the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders black
    ; with perfectly correct VRAM and CGRAM. That is rule 6's
    ; silent-corruption class arriving through a CROSS-FILE contract width-lint
    ; cannot see in either direction.
    ;
    ; A bare INIDISP write here would not do: scene_mgr commits INIDISP from its
    ; own NMI shadow, so it would be overwritten on the first VBlank.
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame -------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE ORDER IS LOAD-BEARING, twice over:
;
;   * m7a_set_heading comes BEFORE the integrate, not after. The step is
;     (sin, cos) x speed, and this port takes that sine and cosine out of the
;     matrix shadow instead of re-deriving them — the LUT already holds
;     M7A = cos(t) and M7B = sin(t) for exactly this heading. So the shadow has
;     to be THIS frame's before the step is computed. (Deriving the sine and
;     cosine separately from the angle would reach the same answer and pay for
;     the trigonometry twice.)
;
;   * obj_draw comes LAST, after the pivot has moved. It projects every enemy
;     through the shadow, and the NMI is about to commit that same shadow.
;     Draw first and every sprite is placed with LAST frame's camera while the
;     floor renders with this one's — a one-frame skid that reads as the cast
;     sliding across the floor rather than standing on it.
tick:
    .a16
    .i16
    jsr do_pause                    ; START toggles; A = the pause flag
    bne @render                     ; paused: the world and the cast freeze,
                                    ;   but the frame still draws and the NMI
                                    ;   still commits a valid matrix
    jsr do_turn                     ; LEFT/RIGHT -> US_HEADING
    lda z:US_HEADING
    jsr ::m7a_set_heading           ; ...and into the matrix shadow, which the
                                    ;   integrate below reads its sin/cos from
    jsr do_throttle                 ; B/UP forward, Y/DOWN reverse, else coast
    jsr do_integrate                ; (sin, cos) x speed -> this frame's step
    jsr move_x                      ; commit each axis SEPARATELY: that is the
    jsr move_y                      ;   slide (see move_y's header)
    ldx z:US_POSX + 2
    ldy z:US_POSY + 2
    jsr ::m7a_set_center            ; the camera follows the hero, exactly
    jsr do_patrol                   ; the enemies pace their corridors
    jsr do_contact                  ; ...and knock the hero home on a touch
@render:
    .a16
    .i16
    jsr obj_draw                    ; the hero at the pin, the cast through the
    jsr do_win_card                 ;   transpose, then the goal banner
    rts

; =============================================================================
; THE DIRECTOR — pause
; =============================================================================
; --- do_pause: START toggles the freeze, on the RISING edge ----------------
; In/out: A16/I16, DB=0. Out: A = US_PAUSED, Z set iff running. Clobbers A.
;
; The edge is latched against last frame's START bit rather than read from
; ES_INP_PRESS for one reason worth stating: `input2` is not in this
; ES_INP_PRESS for one reason worth stating: `input2` is not in this
; composition, and `input`'s own press word is the pad-wide edge — using it
; would be right, and a local latch keeps the pause edge legible next to the
; flag it drives. Holding START does nothing after the first frame either way,
; which is the property that matters.
do_pause:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_START                  ; A = this frame's START bit, or 0
    cmp z:US_PREV_START
    beq @done                       ; unchanged -> no edge to act on
    sta z:US_PREV_START
    cmp #JOY_START
    bne @done                       ; this was the RELEASE, not the press
    lda z:US_PAUSED
    eor #1
    sta z:US_PAUSED
@done:
    .a16
    .i16
    lda z:US_PAUSED                 ; the caller branches on this
    rts

; =============================================================================
; THE TANK — turn, throttle, integrate
; =============================================================================
; --- do_turn: LEFT/RIGHT rotate the heading one step per held frame --------
; In/out: A16/I16, DB=0. Clobbers A.
;
; LEFT and RIGHT produce OPPOSITE deltas, and the heading is masked to a byte
; so it wraps rather than growing: that mask is why the picture at h and h+256
; is bit-identical, which is the slice-1 test still standing.
do_turn:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_LEFT
    beq @no_left
    lda z:US_HEADING
    clc
    adc #TURN_STEP
    and #$00FF
    sta z:US_HEADING
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_RIGHT
    beq @no_right
    lda z:US_HEADING
    sec
    sbc #TURN_STEP
    and #$00FF
    sta z:US_HEADING
@no_right:
    .a16
    .i16
    rts

; --- do_throttle: B/UP forward, Y/DOWN reverse, release -> coast to rest ----
; In/out: A16/I16, DB=0. Clobbers A.
;
; TRAP REPRODUCED DELIBERATELY — it is a real asymmetry in how the rail drives:
; the forward clamp is an UNSIGNED `cmp #(SPEED_CAP + 1)`, so a NEGATIVE speed —
; every bit pattern from $8000 up — compares ABOVE the cap and snaps straight to
; +SPEED_CAP. Reverse-to-forward is therefore instantaneous, while
; forward-to-reverse ramps down through zero one ACCEL at a time. It is kept
; because the recorded route through this maze was driven against it, and
; because a rail whose bugs were quietly fixed is a rail whose reference render
; no longer means anything. The reverse clamp below is signed and does ramp —
; that difference between the two arms is the trap, stated.
do_throttle:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_B
    bne @fwd
    lda z:ES_INP_CUR
    bit #JOY_UP
    bne @fwd
    lda z:ES_INP_CUR
    bit #JOY_Y
    bne @rev
    lda z:ES_INP_CUR
    bit #JOY_DOWN
    bne @rev
    ; ---- nothing held: bleed toward rest, from whichever side ------------
    lda z:US_SPEED
    beq @done                       ; already at rest
    bmi @coast_neg
    sec
    sbc #DECEL
    bpl @store                      ; still moving forward
    lda #0                          ; ...or it just crossed zero: stop there
    bra @store
@coast_neg:
    .a16
    .i16
    clc
    adc #DECEL
    bmi @store                      ; still moving backward
    lda #0
    bra @store
@fwd:
    .a16
    .i16
    lda z:US_SPEED
    clc
    adc #ACCEL
    cmp #(SPEED_CAP + 1)            ; UNSIGNED — see the header. This is the
    bcc @store                      ;   trap, not an oversight.
    lda #SPEED_CAP
    bra @store
@rev:
    .a16
    .i16
    lda z:US_SPEED
    sec
    sbc #ACCEL
    ; Both operands are negative here, so the clamp is a SIGNED comparison
    ; done as a subtraction: (A - SPEED_REV) < 0 means A undershot the cap.
    pha
    sec
    sbc #SPEED_REV
    bpl @rev_ok
    pla                             ; discard the candidate...
    lda #SPEED_REV                  ; ...and take the cap
    bra @store
@rev_ok:
    .a16
    .i16
    pla                             ; the candidate was in range after all
@store:
    .a16
    .i16
    sta z:US_SPEED
@done:
    .a16
    .i16
    rts

; --- do_integrate: this frame's 16.16 step along the heading ---------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; A signed 1.7.8 matrix coefficient times a signed 8.8 speed is a signed 16.16
; displacement — the product's low word IS the fraction and its high word IS
; the integer, with no shifting anywhere. m7_project owns that multiply
; (m7p_mul), and the coefficients come out of the matrix shadow the heading
; above just selected: M7A is cos(t) and M7B is sin(t), which is precisely the
; (cos, sin) pair the step needs.
;
; The step is COMPUTED here and committed nowhere: move_x / move_y are what
; decide whether the world may actually move by it.
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
    rts

; =============================================================================
; COLLISION — candidate, test, commit, one axis at a time
; =============================================================================
; --- move_x: advance world x by the step, if the footprint there is clear --
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

; --- move_y: the same for y — and the asymmetry that IS the slide ----------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the candidate scratch.
;
; THE FOOTPRINT IS TESTED AT THE ALREADY-COMMITTED X, not at the x this frame
; started from. That is not an oversight in the ordering — it is the whole
; mechanism of the slide: drive diagonally into an axis-aligned wall and the
; blocked axis stops while the free one keeps advancing, because each axis is
; judged against the world the other one has already resolved. Test both axes
; against the pre-move position instead and a diagonal push dead-stops.
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

; --- clamp_world: A -> 0..WORLD_MAX, signed --------------------------------
; In/out: A16/I16. Touches no scratch.
; Underflow past zero clamps to 0; overshoot clamps to the last walkable pixel.
; The outer ring of this world is solid wall anyway, so the clamp is a guard on
; the ARITHMETIC, not a gameplay boundary.
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

; --- FP_CORNER: probe one corner of the footprint --------------------------
; In: A16/I16, DB=0, US_CAND_PX/PY = the body's centre. Out: A16, the flag byte
; (zero = floor). Clobbers A, X, Y.
;
; WIDTH-RISK: col_map_at is a CROSS-FILE contract — it is entered A16/I16 and
; EXITS A8/I16, deliberately, because the flag it returns is a byte. The
; `rep #$20` here is a forced widening back to the caller's width, and it must
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
; FOUR corners, not a centre point: a centre test lets the body's shoulder
; enter a cell the centre has not reached, and in 24 px corridors that reads as
; the hero clipping through wall edges. The far edge is centre + HERO_HALF - 1
; because the box spans HERO_HALF px either side of the centre PIXEL — eight
; pixels from centre-4 to centre+3 inclusive. Writing +HERO_HALF instead makes
; the box nine pixels wide and the hero stops one pixel short of every wall,
; which looks like a rendering offset rather than a collision bug.
footprint_solid:
    .a16
    .i16
    FP_CORNER FP_NEAR, FP_NEAR
    bne @solid
    FP_CORNER FP_FAR, FP_NEAR
    bne @solid
    FP_CORNER FP_NEAR, FP_FAR
    bne @solid
    FP_CORNER FP_FAR, FP_FAR
    bne @solid
    lda #0
    rts
@solid:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; THE CAST — patrol, contact
; =============================================================================
; --- do_patrol: one paced step per enemy, turning at walls -----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the candidate scratch.
;
; Each enemy paces ONE axis and its candidate step is tested with the SAME
; footprint routine the hero uses — the same probe, the same four corners, the
; same flag table. That shared test is why "what blocks you blocks them" needs
; no second rule: an enemy cannot walk through a wall the hero cannot, because
; there is only one wall predicate in the ROM.
;
; A blocked step REVERSES the direction and does not move that frame, so an
; enemy turns in place at the corridor end rather than jittering against it.
;
; X is re-derived after every footprint_solid call, deliberately: col_map_at
; clobbers X, and the loop index has to survive it.
do_patrol:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    lda z:US_IDX
    asl
    asl                             ; *4 — the (x, y) pair stride
    tax
    lda z:US_ENE_POS + 0, x
    sta z:US_CAND_PX
    lda z:US_ENE_POS + 2, x
    sta z:US_CAND_PY
    lda z:US_IDX
    asl                             ; *2 — the direction-table stride
    tax
    lda z:US_ENE_DIR, x             ; the signed step
    ldy z:US_IDX
    cpy #PATROL_AXIS_Y
    beq @axis_y
    ; ---- east-west: the candidate moves x, the footprint keeps y ---------
    clc
    adc z:US_CAND_PX
    sta z:US_CAND_PX
    jsr footprint_solid
    bne @reverse
    lda z:US_IDX
    asl
    asl
    tax
    lda z:US_CAND_PX
    sta z:US_ENE_POS + 0, x
    bra @next
@axis_y:
    .a16
    .i16
    ; ---- north-south ------------------------------------------------------
    clc
    adc z:US_CAND_PY
    sta z:US_CAND_PY
    jsr footprint_solid
    bne @reverse
    lda z:US_IDX
    asl
    asl
    tax
    lda z:US_CAND_PY
    sta z:US_ENE_POS + 2, x
    bra @next
@reverse:
    .a16
    .i16
    lda z:US_IDX
    asl
    tax
    lda #0
    sec
    sbc z:US_ENE_DIR, x             ; negate: pace back the way it came
    sta z:US_ENE_DIR, x
@next:
    .a16
    .i16
    lda z:US_IDX
    inc
    sta z:US_IDX
    cmp #ENEMY_COUNT
    bcc @loop
    rts

; --- do_contact: hero-enemy overlap, in WORLD space ------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; World space, not screen space, and that is the point: the picture rotates
; under the hero every frame, so a screen-space overlap test would make contact
; depend on which way the player happens to be facing. Two boxes overlap iff
; |dx| < CONTACT_W AND |dy| < CONTACT_W.
;
; TWO GATES BEFORE THE SCAN, both earning their place:
; a post-respawn GRACE window, and a SPAWN SANCTUARY. A knockback puts the hero
; back on the spawn tile, and one of the enemies paces the start corridor — so
; without them a hero who has just been hit, or who is simply standing still at
; the start, is ground down by a beat crossing the spawn. The sanctuary
; suppresses the HIT only: no enemy is moved, so what you see patrolling is
; exactly what would have hit you.
do_contact:
    .a16
    .i16
    lda z:US_GRACE
    beq @scan
    dec
    sta z:US_GRACE
    rts                             ; graced this frame — no contact at all
@scan:
    .a16
    .i16
    lda z:US_POSX + 2
    sec
    sbc #SPAWN_PX
    jsr abs16
    cmp #SPAWN_SANCTUARY
    bcs @scan_go                    ; driven off the spawn on x -> hittable
    lda z:US_POSY + 2
    sec
    sbc #SPAWN_PY
    jsr abs16
    cmp #SPAWN_SANCTUARY
    bcc @safe                       ; inside the sanctuary on BOTH axes
@scan_go:
    .a16
    .i16
    stz z:US_IDX
@loop:
    .a16
    .i16
    lda z:US_IDX
    asl
    asl
    tax                             ; X survives abs16 (it touches A only)
    lda z:US_POSX + 2
    sec
    sbc z:US_ENE_POS + 0, x
    jsr abs16
    cmp #CONTACT_W
    bcs @no                         ; clear on x -> no overlap, whatever y says
    lda z:US_POSY + 2
    sec
    sbc z:US_ENE_POS + 2, x
    jsr abs16
    cmp #CONTACT_W
    bcc @hit
@no:
    .a16
    .i16
    lda z:US_IDX
    inc
    sta z:US_IDX
    cmp #ENEMY_COUNT
    bcc @loop
@safe:
    .a16
    .i16
    rts
@hit:
    .a16
    .i16
    ; ---- knock the hero home, and say so ---------------------------------
    lda #SPAWN_PX
    sta z:US_POSX + 2
    stz z:US_POSX + 0
    lda #SPAWN_PY
    sta z:US_POSY + 2
    stz z:US_POSY + 0
    stz z:US_SPEED
    lda z:US_HITS
    inc
    sta z:US_HITS
    lda #GRACE_FRAMES
    sta z:US_GRACE                  ; ...and re-arm the window, so a beat
                                    ;   crossing the spawn cannot re-hit
    ; ---- the "ow": snap the screen dark, then pace it back up ------------
    ; The knockback teleports the hero to the spawn, which is INVISIBLE when he
    ; was already near it — so the flash is the actual feedback that a hit
    ; happened. `fade` owns the ramp and declares its two bytes as level + dir
    ; (its feature.toml); arming the direction is what fade_start_in does, and
    ; snapping the LEVEL is the half it has no entry point for. Written here
    ; rather than added to the feature on purpose: fade is a global every other
    ; rail links, and growing it would move ROMs this branch must leave pinned.
    sep #$20
    .a8
    lda #FLASH_LEVEL
    sta z:ES_FADE_CTL               ; INIDISP brightness, this frame
    jsr ::fade_start_in             ; ...ramping back to full, one level a frame
    rep #$20
    .a16
    rts

; --- abs16: A = |A|, signed 16-bit -----------------------------------------
; In/out: A16/I16. Clobbers A only — X and Y survive, which is what lets
; do_contact keep its per-enemy index across both axis tests.
abs16:
    .a16
    .i16
    bpl @done
    eor #$FFFF
    inc
@done:
    .a16
    .i16
    rts

; =============================================================================
; THE GOAL — the win card
; =============================================================================
; --- do_win_card: three stars at screen top, iff the hero stands on the goal
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; An OVERLAY, not a state machine: no input freeze, no scene edge, nothing the
; pause or collision behaviour has to know about. Reaching the goal draws it;
; leaving stops drawing it.
;
; The window test is UNSIGNED and one compare per axis. Subtracting the low
; corner makes a position BELOW it wrap high, so a single `cmp` against the
; body width rejects both ends — no signed pair, no branch either side.
;
; The slots are m7dg_obj's, and obj_draw has already cleared the hi-table byte
; they share this frame, so mdo_put may OR its two bits in. Parked when off the
; goal rather than left alone: an unwritten slot keeps whatever it last held.
do_win_card:
    .a16
    .i16
    lda z:US_POSX + 2
    sec
    sbc #(GOAL_CX - GOAL_HALF)
    cmp #(GOAL_HALF * 2)
    bcs @off
    lda z:US_POSY + 2
    sec
    sbc #(GOAL_CY - GOAL_HALF)
    cmp #(GOAL_HALF * 2)
    bcs @off
    lda #WIN_ROW_Y
    sta z:ES_MDO + MDO_Y            ; one row for all three
    lda #WIN_X0
    sta z:ES_MDO + MDO_X
    ldx #(ES_O_WIN * 4)
    lda #(MDO_WIN_TILE | (WIN_ATTR << 8))
    jsr mdo_put
    lda #WIN_X1
    sta z:ES_MDO + MDO_X
    ldx #((ES_O_WIN + 1) * 4)
    lda #(MDO_WIN_TILE | (WIN_ATTR << 8))
    jsr mdo_put
    lda #WIN_X2
    sta z:ES_MDO + MDO_X
    ldx #((ES_O_WIN + 2) * 4)
    lda #(MDO_WIN_TILE | (WIN_ATTR << 8))
    jsr mdo_put
    rts
@off:
    .a16
    .i16
    ldx #(ES_O_WIN * 4)
@park:
    .a16
    .i16
    jsr mdo_park_slot               ; preserves X
    inx
    inx
    inx
    inx
    cpx #((ES_O_WIN + ES_O_WIN_SPRITES) * 4)
    bcc @park
    rts

; --- exit: undo what enter armed ------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's "Scene routine contracts" header), and re-uploading
; 32 KB to prove a point costs a frame. What IS undone is the display state this
; scene turned on, so a successor scene inherits a blank main screen rather than
; a Mode 7 plane it never asked for. This slice has no edges, so nothing reaches
; here yet — it is the contract, kept honest.
exit:
    .a16
    .i16
    jsr obj_park                    ; the cast leaves with the scene: a
                                    ;   successor that draws no sprites at all
                                    ;   must not inherit this one's
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
