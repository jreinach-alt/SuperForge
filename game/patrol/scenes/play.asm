; =============================================================================
; play scene — the whole game: dodge two patrolling enemies
; =============================================================================
; The whole game loop, re-expressed against the allocator's emitted symbols:
;
;   player horizontal (per-axis move-check) -> jump on a fresh A press ->
;   vertical physics -> one patrol step per enemy -> contact check (knockback
;   + HITS) -> draw all three actors -> stage the HUD if the counter changed.
;
; THE RAIL'S HEADLINE is PAT_STEP below: an enemy paces at 1 px/frame and turns
; for EITHER of two reasons — a solid wall ahead (the full tentative box), or NO
; ground under the LEADING bottom corner (a ledge check: turn the moment the
; front foot would step into air, so the enemy never overhangs its platform
; edge).
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; --- col_map's world binding ------------------------------------------------
; Declared at the COMPOSITION site (m7_dungeon's shape): col_map carries no
; default for any of its six symbols, and each missing one is a hard `.error`.
; The world is the SAME blob patrol_bg renders to the BG1 tilemap at enter —
; one source, two consumers, no drift (maze's shape).
;
; 32x32 tiles = a 256x256 px world: the level is one screen (32x28) padded to
; the power of two col_map's masks need; rows 28..31 are blank and
; below the ground. col_map is TOTAL over u16 by mask — the level's border
; walls are what keep every queried coordinate meaningful (bounds is level
; design, not a lookup concern — col_map/feature.toml's resolved limit).
CM_WORLD_W_LOG2      = 5
CM_WORLD_H_LOG2      = 5
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_PAT_MAP_SIZE, error, "col_map world size disagrees with the pat_map claim"
CM_WORLD_BLOB        = ::ES_R_PAT_MAP_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_PAT_MAP_BANK
; Derived from the allocator's own size, never narrated (docs/37 §5's
; discipline); at CHUNKS = 1 col_map takes its constant-bank branch. Growing
; the map past one window stops the build upstream (the m7_dungeon argument:
; the plain _SIZE/_ADDR/_BANK symbols cease to exist for a tiled claim).
CM_WORLD_BLOB_CHUNKS = (::ES_R_PAT_MAP_SIZE + 32767) / 32768
CM_FLAGS             = ::pat_flags_bin
.include "col_map.asm"

; The scene's own feature code, inside the scope: their claims are
; scene-scoped, so their asm has to see this scene's emitted symbols.
.include "patrol_bg.asm"
.include "patrol_obj.asm"

; =============================================================================
; THE TWO BASE RATES tick_scale SCALES (docs/96 §4, docs/97 §3)
; =============================================================================
; PAT_SPEED and PAT_PATROL_SPEED are still the two numbers to reach for when
; tuning how this rail feels; what changed is that they are now RATES rather
; than per-frame immediates. On NTSC TS_STEP publishes each to the pixel, so
; the picture cannot move.
TS_RUN_BASE   = PAT_SPEED * TS_ONE
TS_BEAT_BASE  = PAT_PATROL_SPEED * TS_ONE
;
; THE JUMP IS NOT HERE, and that is a stated limit rather than an oversight.
; PAT_GRAVITY, PAT_JUMP_VEL and PAT_MAX_FALL are a ballistic arc: preserving
; it in real time needs the take-off velocity times r AND gravity times r
; SQUARED, because the apex is v^2/2g and a single factor changes the SHAPE
; rather than the speed. tick_scale supplies exactly one gain, so r goes
; through TS_STEP and r^2 does not — and a second gain is surgery on a feature
; other rails compose. game.toml carries the full argument; the oracle's
; fall_y observable is the non-vacuity control that keeps it honest, reading
; the frame ratio in the same run where player_x and e1_x read parity.

; BG3 2bpp tile attr: palette 7 (claim pins CGRAM words 28..31), priority set
; so the HUD line draws over the actors where they overlap — BGMODE bit 3
; below puts BG3's priority-1 tiles above the sprites, which is what a HUD is.
TXT_ATTR = (7 << 10) | (1 << 13)

; =============================================================================
; MACROS (ca65 macros must be DEFINED before use; the subroutines they call
; resolve forward, so those stay below with the game logic)
; =============================================================================

; --- PAT_CORNER: probe one corner of the 8x8 box ----------------------------
; In: A16/I16, DB=0, US_PROBEX/US_PROBEY = the box's top-left. Out: A16 = the
; corner's solidity (0 = clear). Clobbers A, X, Y, CM_PX/CM_PY.
;
; WIDTH-RISK: col_map_at is a CROSS-FILE contract — entered A16/I16, it EXITS
; A8/I16 deliberately (the flag is a byte). The `rep #$20` here is a forced
; widening back to the caller's width and must not be dropped: an A8 `bne` in
; pat_solid_box would test one byte of a two-byte compare. width-check cannot
; see across the file boundary in either direction, so this marker carries it
; (m7_dungeon's FP_CORNER, the same contract).
.macro PAT_CORNER pc_ox, pc_oy
    lda z:US_PROBEX
    .if (pc_ox) > 0
    clc
    adc #pc_ox
    .endif
    sta z:CM_PX
    lda z:US_PROBEY
    .if (pc_oy) > 0
    clc
    adc #pc_oy
    .endif
    sta z:CM_PY
    jsr col_map_at
    rep #$20
    .a16
    and #PAT_FLAG_SOLID
.endmacro

; --- PAT_STEP: one frame of patrol for one enemy ---------------------------
; ex/edir are DP state words; ey is an ASSEMBLE-TIME constant (read-only).
; Expanded once per enemy, per frame; the pnewx/pleadx/pfooty scratch is shared
; between the expansions because it is consumed within each.
;
; Turn (direction flip, NO move) happens on EITHER: the tentative box
; overlapping a solid (wall ahead — the full 4-corner box probe), or the
; leading bottom corner's foot point having NO solid under it (ledge ahead —
; a single-point probe at the FRONT edge: newx+7 walking right, newx walking
; left). Otherwise the step commits. The probes are forward-only, so the
; never-overhang guarantee is inductive from a valid start position.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. The one `rep #$20` inside is the
; forced widening back from col_map_at's A8 exit (the same cross-file
; contract PAT_CORNER documents); no width toggle spans a push or a branch.
.macro PAT_STEP p_ex, p_ey, p_edir
    .local move_left, store_x, lead_left, lead_store, commit, turn, done
    ; ---- tentative x = ex +/- patrol speed --------------------------------
    lda z:p_edir
    beq move_left
    lda z:p_ex
    clc
    adc z:US_TSE
    bra store_x
move_left:
    .a16
    .i16
    lda z:p_ex
    sec
    sbc z:US_TSE
store_x:
    .a16
    .i16
    sta z:US_PNEWX
    ; ---- leading bottom corner: front edge, one row below the feet --------
    lda z:p_edir
    beq lead_left
    lda z:US_PNEWX
    clc
    adc #(PAT_BOX - 1)
    bra lead_store
lead_left:
    .a16
    .i16
    lda z:US_PNEWX
lead_store:
    .a16
    .i16
    sta z:US_PLEADX
    lda #(p_ey + PAT_BOX)
    sta z:US_PFOOTY
    ; ---- wall ahead? (full box at the tentative position) -----------------
    lda z:US_PNEWX
    sta z:US_PROBEX
    lda #p_ey
    sta z:US_PROBEY
    jsr pat_solid_box
    bne turn
    ; ---- ground under the leading corner? (single-point probe) ------------
    lda z:US_PLEADX
    sta z:CM_PX
    lda z:US_PFOOTY
    sta z:CM_PY
    jsr col_map_at              ; WIDTH-RISK: exits A8/I16 (cross-file
    rep #$20                    ; contract) — this rep is the forced widening
    .a16                        ; back and must not be dropped
    and #PAT_FLAG_SOLID
    bne commit                  ; ground present -> walk
    bra turn                    ; ledge -> turn
commit:
    .a16
    .i16
    lda z:US_PNEWX
    sta z:p_ex
    bra done
turn:
    .a16
    .i16
    lda z:p_edir
    eor #1
    sta z:p_edir
done:
    .a16
    .i16
.endmacro

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- CGRAM: the 4-colour text sub-palette (words 28..31) --------------
    ; The backdrop (word 0) is patrol_bg's pat_pal claim — black, uploaded by
    ; pat_bg_arm below. hud_game's glyph colours kept: the render tests count
    ; the white pixels.
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    ; $2122 is a byte port: two writes per colour, low then high (A8 only)
    stz a:$2122                 ; colour 0 (transparent slot): black $0000
    stz a:$2122
    lda #$52                    ; colour 1: dim slate $2952
    sta a:$2122
    lda #$29
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: WHITE $7FFF — the HUD colour
    sta a:$2122
    lda #$7F
    sta a:$2122
    ; ---- layer regs: BG3 (bg_text's scene_writes), BG1 + mode + enable ----
    ; (patrol_bg's scene_writes — the layer identity of a Mode 1 BG1+BG3
    ; scene is decided here, where the scene composes its features.)
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    lda #ES_V_PAT_MAP_V_SC_BASE
    sta a:$2107                 ; BG1SC: the level tilemap's base
    lda #ES_V_PAT_CHR_NBA
    sta a:$210B                 ; BG12NBA: BG1 chr nibble (BG2 unused = 0)
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #$15                    ; TM: BG1 + BG3 + OBJ — the three drawn layers
    sta a:$212C
    rep #$20
    .a16
    ; ---- font + text tilemap ----------------------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the level (CHR + palette + tilemap + scroll pin), the actors -----
    jsr pat_bg_arm
    jsr pat_obj_arm
    ; ---- game state. Power-on WRAM/DP is RANDOM (rule 5): these stores ARE
    ; the write-before-read contract for the state.toml words the tick READS
    ; before writing. The pure scratch (newx/newy/probex/probey and the
    ; patrol trio) is written before read inside every use by construction —
    ; the cm_hot argument — and zeroing it here would disarm the uninit
    ; detector's view of exactly the paths that promise that. --------------
    lda #PAT_SPAWN_X
    sta z:US_PX
    lda #PAT_SPAWN_Y << 8
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    lda #PAT_SPAWN_Y
    sta z:US_PYI                ; pat_obj_place below reads it before tick 1
    lda #PAT_E1_X0
    sta z:US_E1X
    lda #PAT_DIR_R
    sta z:US_E1DIR
    lda #PAT_E2_X0
    sta z:US_E2X
    lda #PAT_DIR_R
    sta z:US_E2DIR
    stz z:US_HITS
    stz z:US_DIRTY
    stz z:US_FRAMES
    stz z:US_TSR_ACC            ; the timebase's two carried fractions and the
    stz z:US_TSR                ;   two published steps: written before any of
    stz z:US_TSE_ACC            ;   them is read (enter's own place runs first)
    stz z:US_TSE
    ; ---- the HUD, printed under the blank where a whole string is legal ---
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_hits)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_hits
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + PAT_HUD_ROW * 32 + PAT_LABEL_C)
    jsr text_puts
    lda z:US_HITS               ; packed BCD 0000 -> four '0' glyphs
    ldx #(ES_V_TEXT_MAP + PAT_HUD_ROW * 32 + PAT_DIGITS_C)
    jsr text_put_hex4
    ; ---- first placement, so frame 1 draws the cast where it is -----------
    jsr pat_obj_place
    rts

; --- exit: re-park the sprites this scene armed -----------------------------
; In/out: A16/I16, DB=0. Never called — one scene, no edges — but the claim's
; contract is symmetric and a second scene would need it.
exit:
    .a16
    .i16
    jsr pat_obj_park
    rts

; --- tick: one frame (display active — no direct VRAM writes here) ----------
; In/out: A16/I16, DB=0. The order below is fixed.
tick:
    .a16
    .i16
    lda z:US_FRAMES
    inc a
    sta z:US_FRAMES             ; the free-running heartbeat
    ; ---- this frame's two region-correct steps, published once ------------
    ; The run is read by move_x's two arms and the beat by both PAT_STEP
    ; expansions, so both are computed here: once per frame per rate.
    TS_STEP z:US_TSR_ACC, TS_RUN_BASE
    sta z:US_TSR
    TS_STEP z:US_TSE_ACC, TS_BEAT_BASE
    sta z:US_TSE
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                ; the draw/probe pixel for this frame
    jsr move_x
    jsr do_jump
    jsr pat_physics
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                ; refresh after the vertical move
    ; ---- one patrol step per enemy (ey is an assemble-time constant) ------
    PAT_STEP US_E1X, PAT_E1_Y, US_E1DIR
    PAT_STEP US_E2X, PAT_E2_Y, US_E2DIR
    jsr do_contact
    jsr hud_refresh
    jmp pat_obj_place

; --- move_x: the d-pad, on HELD state ---------------------------------------
; In/out: A16/I16, DB=0. Per-axis move-check, as jumper: compute the tentative
; x (both directions tested independently, so holding both cancels), probe the
; 8x8 box at (newx, pyi), commit only when clear. Clobbers A, X, Y.
move_x:
    .a16
    .i16
    lda z:US_PX
    sta z:US_NEWX
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_NEWX
    clc
    adc z:US_TSR
    sta z:US_NEWX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_NEWX
    sec
    sbc z:US_TSR
    sta z:US_NEWX
@no_left:
    .a16
    .i16
    lda z:US_NEWX
    sta z:US_PROBEX
    lda z:US_PYI
    sta z:US_PROBEY
    jsr pat_solid_box
    bne @blocked                ; a wall ahead: the move is dropped
    lda z:US_NEWX
    sta z:US_PX
@blocked:
    .a16
    .i16
    rts

; --- do_jump: take off on a FRESH A press, if standing ---------------------
; In/out: A16/I16, DB=0. ES_INP_PRESS is the rising edge, so holding A does
; not auto-rejump — that is exactly why the press edge is what gates it.
; Clobbers A.
do_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    beq @done
    lda z:US_GROUNDED
    beq @done                   ; can't jump in mid-air
    lda #PAT_JUMP_UP
    sta z:US_VY                 ; -PAT_JUMP_VEL, two's complement
    stz z:US_GROUNDED
@done:
    .a16
    .i16
    rts

; --- pat_physics: one frame of vertical physics ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
;
; Four reachable arms: standing (a 1px-below probe keeps grounded stable),
; gravity clamped at terminal fall, the landing snap (box bottom -> tile top,
; pixel-exact rest), and the head bump (box top -> below the tile, ascent
; killed). One-way-platform arms are OMITTED: this rail flags no tile $02, so
; every one of those branches would reduce to "fall through to
; integrate/commit" — behaviourally identical, and the tests
; drive the whole cycle they replace (stand -> take-off -> ascent -> apex ->
; descent -> landing -> rest).
pat_physics:
    .a16
    .i16
    lda z:US_VY
    bpl @falling
    jmp phys_rising
@falling:
    .a16
    .i16
    ; ---- ground probe: solid 1px below the current box? -> standing -------
    lda z:US_PYF
    xba
    and #$00FF
    inc a
    sta z:US_PROBEY
    lda z:US_PX
    sta z:US_PROBEX
    jsr pat_solid_box
    beq @integrate
    ; ---- standing: rest, stable grounded flag -----------------------------
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    lda z:US_PYF
    and #$FF00                  ; pixel-exact rest (clear subpixel)
    sta z:US_PYF
    rts
@integrate:
    .a16
    .i16
    ; ---- gravity, clamped to terminal fall speed --------------------------
    lda z:US_VY
    clc
    adc #PAT_GRAVITY
    cmp #PAT_MAX_FALL
    bcc @noclamp
    lda #PAT_MAX_FALL
@noclamp:
    .a16
    .i16
    sta z:US_VY
    ; ---- tentative move, then probe the new pixel -------------------------
    lda z:US_PYF
    clc
    adc z:US_VY
    pha                         ; WIDTH-RISK: stack balance — this PHA (A16,
                                ; 2 bytes) is matched by exactly one PLA on
                                ; EACH arm below; no width toggle spans it
                                ; (pat_solid_box is internally balanced)
    xba
    and #$00FF
    sta z:US_PROBEY             ; the tentative pixel (survives the probe)
    lda z:US_PX
    sta z:US_PROBEX
    jsr pat_solid_box
    beq @fall_clear
    pla                         ; blocked: discard the tentative position
    lda z:US_PROBEY             ; ---- landing snap: box bottom -> tile top -
    clc
    adc #7                      ; the box's bottom pixel
    and #$FFF8                  ; top of the solid tile row it entered
    sec
    sbc #8                      ; box top = tile top - box height
    xba                         ; pixel -> 8.8 (value <= $00FF, so xba = <<8)
    sta z:US_PYF
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    rts
@fall_clear:
    .a16
    .i16
    pla                         ; commit the tentative position
    sta z:US_PYF
    stz z:US_GROUNDED
    rts
phys_rising:
    .a16
    .i16
    stz z:US_GROUNDED
    lda z:US_VY                 ; gravity (no clamp needed while negative)
    clc
    adc #PAT_GRAVITY
    sta z:US_VY
    lda z:US_PYF
    clc
    adc z:US_VY
    pha                         ; WIDTH-RISK: same contract as the falling arm
    xba
    and #$00FF
    sta z:US_PROBEY
    lda z:US_PX
    sta z:US_PROBEX
    jsr pat_solid_box
    beq @rise_clear
    pla                         ; blocked: discard the tentative position
    lda z:US_PROBEY             ; ---- head bump: box top -> below the tile -
    and #$FFF8                  ; the ceiling tile's row
    clc
    adc #8                      ; first clear row below it
    xba
    sta z:US_PYF
    stz z:US_VY                 ; kill the ascent — the arc comes down early
    rts
@rise_clear:
    .a16
    .i16
    pla
    sta z:US_PYF
    rts

; --- do_contact: either enemy overlapping the player -> knockback -----------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
;
; Strict AABB overlap of two 8x8 boxes — touching edge-to-edge (0 px shared) is
; NOT contact; they must share >= 1 px. At most one hit resolves per frame (E1
; checked first).
do_contact:
    .a16
    .i16
    lda z:US_E1X
    sta z:US_PROBEX
    lda #PAT_E1_Y
    sta z:US_PROBEY
    jsr pat_overlap
    bne @hit
    lda z:US_E2X
    sta z:US_PROBEX
    lda #PAT_E2_Y
    sta z:US_PROBEY
    jsr pat_overlap
    bne @hit
    rts
@hit:
    .a16
    .i16
    ; ---- knockback: respawn + count the hit -------------------------------
    lda #PAT_SPAWN_X
    sta z:US_PX
    lda #PAT_SPAWN_Y << 8
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    lda #PAT_SPAWN_Y
    sta z:US_PYI                ; this frame draws the respawned position
    ; HITS IS PACKED BCD: `sed` + a 16-bit adc gives four decimal
    ; digits and bg_text's hex4 nibble walk prints them as decimal for free.
    ; The 65816 CLEARS D on interrupt entry and rti restores it, so an NMI
    ; landing inside this window cannot inherit decimal mode.
    sed
    clc
    lda z:US_HITS
    adc #1                      ; one hit, in BCD
    sta z:US_HITS
    cld
    lda z:US_DIRTY
    ora #PAT_DIRTY_HITS
    sta z:US_DIRTY
    rts

; --- pat_overlap: player box vs (probex, probey) box ------------------------
; In: A16/I16, DB=0. US_PROBEX/US_PROBEY = the enemy's top-left. Out: A16 =
; 1 overlap / 0 none. Clobbers A.
;
; |dx| < 8 && |dy| < 8 — for two equal 8-px boxes this IS strict half-open
; overlap (platformer's gh_contact shape, minus the stomp discrimination: every
; patrol contact is a plain hurt).
pat_overlap:
    .a16
    .i16
    lda z:US_PX
    cmp z:US_PROBEX
    bcs @dx
    lda z:US_PROBEX
    sec
    sbc z:US_PX
    bra @have_dx
@dx:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc z:US_PROBEX
@have_dx:
    .a16
    .i16
    cmp #PAT_BOX
    bcs @none
    lda z:US_PYI
    cmp z:US_PROBEY
    bcs @dy
    lda z:US_PROBEY
    sec
    sbc z:US_PYI
    bra @have_dy
@dy:
    .a16
    .i16
    lda z:US_PYI
    sec
    sbc z:US_PROBEY
@have_dy:
    .a16
    .i16
    cmp #PAT_BOX
    bcs @none
    lda #1
    rts
@none:
    .a16
    .i16
    lda #0
    rts

; --- hud_refresh: stage the counter run, ONLY when the value changed --------
; In/out: A16/I16, DB=0. A running scene cannot write VRAM directly, so the
; four counter cells go through bg_text's VBlank queue; on a frame where
; US_DIRTY is clear this stages NOTHING and VRAM is not rewritten (hud_game's
; reprint-on-change pattern, measured on the destination's write counters).
hud_refresh:
    .a16
    .i16
    lda z:US_DIRTY
    and #PAT_DIRTY_HITS
    bne @stage
    rts
@stage:
    .a16
    .i16
    lda z:US_DIRTY
    eor #PAT_DIRTY_HITS
    sta z:US_DIRTY
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda z:US_HITS               ; packed BCD, so hex4's nibble walk prints
    ldx #(ES_V_TEXT_MAP + PAT_HUD_ROW * 32 + PAT_DIGITS_C)
    jmp text_queue_hex4         ; ...four DECIMAL digits

; --- pat_solid_box: is any corner of the 8x8 box on solid terrain? ----------
; In: A16/I16, DB=0. US_PROBEX/US_PROBEY = the box's top-left. Out: A16 = 1
; solid / 0 clear. Clobbers A, X, Y and CM_PX/CM_PY.
;
; All FOUR corners, far corners at +7 not +8 (the box spans 8 px, so a +8 probe
; reads the NEIGHBOURING tile and sticks the mover to walls), each masked with
; the SOLID bit — flag BIT 0 specifically, not "any flag" (maze's shape).
pat_solid_box:
    .a16
    .i16
    PAT_CORNER 0, 0
    bne @solid
    PAT_CORNER (::PAT_BOX - 1), 0
    bne @solid
    PAT_CORNER 0, (::PAT_BOX - 1)
    bne @solid
    PAT_CORNER (::PAT_BOX - 1), (::PAT_BOX - 1)
    bne @solid
    lda #0
    rts
@solid:
    .a16
    .i16
    lda #1
    rts

.segment "RODATA"
s_hits: .byte "HITS", 0
.segment "CODE"
.endscope
