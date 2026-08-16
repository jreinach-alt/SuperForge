; =============================================================================
; play scene — the whole game: jumper physics + patrol + stomp resolution
; =============================================================================
; The whole game loop, one frame per tick, in order: player horizontal -> jump
; -> the vertical integrator -> the two patrols (alive-gated) -> contact
; resolution (at most ONE contact per frame, enemy 1 checked first) -> the
; draw. Physics, patrol and stomp classification are all GAME-SIDE and written
; out below rather than called into the engine: none of the three is shared by
; a second rail yet, and a feature is what two compositions need.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; --- col_map's world binding ------------------------------------------------
; Declared at the COMPOSITION site (col_map carries no defaults); each name
; `::`-qualified because a deferred parent-scope lookup is not the constant
; expression col_map's assembly-time `.if` needs (m7_dungeon's derivation,
; verbatim). The world is 32x32 tiles, asserted against the blob's own emitted
; size rather than stated.
CM_WORLD_W_LOG2      = 5
CM_WORLD_H_LOG2      = 5
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_ST_WORLD_SIZE, error, "col_map world size disagrees with the st_world claim"
CM_WORLD_BLOB        = ::ES_R_ST_WORLD_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_ST_WORLD_BANK
; DERIVED from the claim's own size (1 at 1 KB against a 32 KB window):
; col_map takes its constant-bank branch and never adds a chunk index, so
; the multi-chunk bank-adjacency obligation does not arise (m7_dungeon's
; discharge note — every route to CHUNKS >= 2 is refused upstream).
CM_WORLD_BLOB_CHUNKS = (::ES_R_ST_WORLD_SIZE + 32767) / 32768
CM_FLAGS             = ::st_flags_bin
.include "col_map.asm"

; --- the scene's own feature code, inside the scope -------------------------
; (their claims are scene-scoped, so their asm has to see this scene's
; emitted symbols — hud_obj's placement note)
.include "stomper_bg.asm"
.include "stomper_obj.asm"

; BG3 2bpp tile attr: palette 7 (the text_pal claim pins CGRAM words 28..31),
; priority set so the HUD draws over anything it overlaps (hud_game's value).
TXT_ATTR = (7 << 10) | (1 << 13)

; =============================================================================
; ENTER — forced blank + NMI masked (scene_mgr contract)
; =============================================================================
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- CGRAM: the 4-colour text sub-palette (words 28..31) --------------
    ; Word 0 (backdrop) is st_pal's word 0, uploaded by st_arm below.
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    stz a:$2122                 ; colour 0 (transparent slot): black
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
    ; ---- BG3 regs (bg_text's scene_writes): map base, chr base, scroll ----
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    ; ---- the scene's base display (stomper_bg's scene_writes) -------------
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #ES_V_ST_MAP_SC_BASE
    sta a:$2107                 ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_ST_CHR_NBA
    sta a:$210B                 ; BG12NBA: BG1 chr page in the low nibble
    lda #$15                    ; TM: OBJ + BG3 + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    ; ---- font + text map --------------------------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the arena (CHR, palette, tilemap from the blob, scroll pin) ------
    jsr st_arm
    ; ---- the actors' CHR, palettes, OBSEL, static tile/attr ---------------
    jsr st_obj_arm
    ; ---- game state. Power-on DP is RANDOM (rule 5): these stores ARE the
    ; write-before-read contract for every word state.toml declares — except
    ; the probe/patrol scratch, which is write-before-read PER CALL and
    ; deliberately NOT zeroed here (zeroing would disarm the uninit-read
    ; detector on it — cm_hot's argument). ------------------------------
    lda #ST_SPAWN_X
    sta z:US_PX
    lda #(ST_SPAWN_Y << 8)
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    lda #ST_SPAWN_Y
    sta z:US_PYI
    lda #ST_E1_X0
    sta z:US_E1X
    lda #1
    sta z:US_E1DIR
    sta z:US_E1ALIVE
    lda #ST_E2_X0
    sta z:US_E2X
    lda #1
    sta z:US_E2DIR
    sta z:US_E2ALIVE
    lda #2
    sta z:US_FOES
    stz z:US_HURTS
    stz z:US_CLEARP
    stz z:US_BLINK
    ; ---- the HUD, printed under the blank where whole strings are legal ---
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_foes)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_foes
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + ST_HUD_ROW * 32 + ST_LABEL_C)
    jsr text_puts
    lda #.loword(s_count0)      ; "00002" — the boot count, printed as a
    sta z:ES_TXT_PTR            ;   fixed-width 5-digit field
    sep #$20
    .a8
    lda #^s_count0
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + ST_HUD_ROW * 32 + ST_DIGITS_C)
    jsr text_puts
    ; ---- the first staging, so frame 0 commits real entries ---------------
    jmp st_obj_draw

; --- exit: re-park the actors this scene armed ------------------------------
; In/out: A16/I16, DB=0. Never called — one scene, no edges — but the claim's
; contract is symmetric and a second scene would need it.
exit:
    .a16
    .i16
    jmp oam_park_all

; =============================================================================
; THE COLLISION PROBES — game-side wrappers over the composed col_map
; =============================================================================

; --- probe_solid: is the tile at world (CM_PX, CM_PY) solid? ----------------
; In: A16/I16, DB=0; CM_PX/CM_PY = the world pixel (caller writes both).
; Out: A16 = 1 solid / 0 clear (Z reflects it). Clobbers A, X, Y.
;
; col_map_at EXITS A8 — its stated contract, and the exact cross-file width
; hole CLAUDE.md rule 6 names (`col_map_at`'s callers): the `.a8` below is
; the annotation whose absence assembles a 3-byte A16 `and` and executes the
; stray byte as BRK. `jumper` measured that live. SOLID is flag bit 0
; (st_flags[2] = 1).
probe_solid:
    .a16
    .i16
    jsr col_map_at
    .a8                         ; col_map_at's stated exit width
    rep #$20
    .a16
    and #1                      ; bit 0, high byte cleared in the same mask
    rts

; --- st_solid_box: is any corner of an 8x8 box on solid terrain? ------------
; In: A16/I16, DB=0; US_BOXX/US_BOXY = the box's top-left pixel.
; Out: A16 = 1 any corner solid / 0 all clear (Z reflects it). Clobbers
; A, X, Y.
;
; The four corners are (x,y) (x+7,y) (x,y+7) (x+7,y+7): the box spans 8 pixels,
; so the far corners are +7, not +8 — a +8 probe reads the NEIGHBOURING tile
; and sticks the actor to walls. The move-check primitive: compute the
; tentative position, test it, revert if blocked.
st_solid_box:
    .a16
    .i16
    lda z:US_BOXX               ; corner (x, y)
    sta z:CM_PX
    lda z:US_BOXY
    sta z:CM_PY
    jsr probe_solid
    bne @hit
    lda z:US_BOXX               ; corner (x+7, y)
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BOXY
    sta z:CM_PY
    jsr probe_solid
    bne @hit
    lda z:US_BOXX               ; corner (x, y+7)
    sta z:CM_PX
    lda z:US_BOXY
    clc
    adc #7
    sta z:CM_PY
    jsr probe_solid
    bne @hit
    lda z:US_BOXX               ; corner (x+7, y+7)
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BOXY
    clc
    adc #7
    sta z:CM_PY
    jsr probe_solid
    bne @hit
    lda #0
    rts
@hit:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; THE PHYSICS — the vertical integrator
; =============================================================================
; --- phys_step: one frame of vertical physics -------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; SOLID PATHS ONLY: this rail flags every terrain tile SOLID and nothing
; PLATFORM, so a one-way/drop-through branch would be dead code and is not
; written (`jumper` makes the same call). Two shapes worth naming: the
; tentative 8.8 position lives in US_TENT rather than on a PHA/PLA stack across
; the width-toggling arms, and row-tops are lsr x3 / asl x3 rather than
; `and #$FFF8`.
;
; TWO LANDING PATHS, both live — measured, and load-bearing for the
; falsification pass:
;   STAND — falling with solid 1 px below the current box: grounded stays 1,
;     y snaps pixel-exact (subpixel cleared). Catches any approach arriving
;     at <= 1 px/frame at pixel adjacency (arc-top landings) and keeps rest
;     STABLE frame to frame — which is what gates the jump.
;   SNAP — the integrated move enters a solid: box bottom -> tile top.
;     Catches every faster fall (the <= 4 px/f clamp bounds the step, so the
;     snap never crosses more than one tile row).
phys_step:
    .a16
    .i16
    lda z:US_VY
    bpl @falling
    jmp phys_rising
@falling:
    .a16
    .i16
    ; ---- ground probe: solid 1 px below the current box? -> standing ------
    lda z:US_PYF
    xba
    and #$00FF
    inc a
    sta z:US_BOXY
    lda z:US_PX
    sta z:US_BOXX
    jsr st_solid_box
    beq @integrate
    stz z:US_VY                 ; standing: rest, stable grounded flag
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
    adc #ST_GRAVITY
    cmp #ST_MAX_FALL
    bcc @noclamp
    lda #ST_MAX_FALL
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
    sta z:US_NEWY
    sta z:US_BOXY
    lda z:US_PX
    sta z:US_BOXX
    jsr st_solid_box
    beq @fall_clear
    ; ---- landing snap: box bottom -> tile top -----------------------------
    lda z:US_NEWY
    clc
    adc #7                      ; the box's bottom pixel
    lsr
    lsr
    lsr
    asl
    asl
    asl                         ; top of the solid tile row it entered
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
    lda z:US_TENT               ; commit the tentative position
    sta z:US_PYF
    stz z:US_GROUNDED
    rts
phys_rising:
    .a16
    .i16
    stz z:US_GROUNDED
    lda z:US_VY                 ; gravity (no clamp needed while negative)
    clc
    adc #ST_GRAVITY
    sta z:US_VY
    lda z:US_PYF
    clc
    adc z:US_VY
    sta z:US_TENT
    xba
    and #$00FF
    sta z:US_NEWY
    sta z:US_BOXY
    lda z:US_PX
    sta z:US_BOXX
    jsr st_solid_box
    beq @rise_clear
    ; ---- head bump: box top -> below the tile; kill the ascent ------------
    lda z:US_NEWY
    lsr
    lsr
    lsr
    asl
    asl
    asl                         ; the ceiling tile's row
    clc
    adc #8                      ; first clear row below it
    xba
    sta z:US_PYF
    stz z:US_VY                 ; the arc comes down early, like it should
    rts
@rise_clear:
    .a16
    .i16
    lda z:US_TENT
    sta z:US_PYF
    rts

; =============================================================================
; THE ENEMY MACROS — patrol and stomp classification, per-enemy expansions
; =============================================================================
; Macros rather than record-indexed subroutines: one expansion per enemy over
; that enemy's own DP words is what lets the two enemies keep independent
; allocator-placed state with SHARED scratch, and it costs no indexing in the
; frame path. .local labels inside; NOTE for callers: an expansion ends any
; enclosing cheap-local `@` scope, which is why the tick's patrol/resolve
; blocks use real labels.

; --- patrol_step ex, edir, ey_const: one frame of patrol --------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y (the probes). Turn (direction
; flip, no move) on EITHER: wall ahead (tentative box overlaps solid) or
; ledge ahead (no solid under the leading bottom corner) — a ledge-aware
; patrol: an enemy placed on a run paces it end to end forever.
.macro patrol_step ex, edir, ey_const
    .local move_left, store_x, lead_left, lead_store, commit, turn, done
    .a16
    .i16
    lda z:edir                  ; tentative x = ex +/- speed
    beq move_left
    lda z:ex
    clc
    adc #ST_PATROL_SPEED
    bra store_x
move_left:
    .a16
    .i16
    lda z:ex
    sec
    sbc #ST_PATROL_SPEED
store_x:
    .a16
    .i16
    sta z:US_PNEWX
    lda z:edir                  ; leading bottom corner: the box's front edge
    beq lead_left
    lda z:US_PNEWX
    clc
    adc #7
    bra lead_store
lead_left:
    .a16
    .i16
    lda z:US_PNEWX
lead_store:
    .a16
    .i16
    sta z:US_PLEADX
    lda #(ey_const + 8)         ; the tile row under the feet
    sta z:US_PFOOTY
    lda z:US_PNEWX              ; wall ahead? (full box, tentative position)
    sta z:US_BOXX
    lda #ey_const
    sta z:US_BOXY
    jsr st_solid_box
    bne turn
    lda z:US_PLEADX             ; ground under the leading corner?
    sta z:CM_PX
    lda z:US_PFOOTY
    sta z:CM_PY
    jsr probe_solid
    beq turn                    ; ledge -> turn
commit:
    .a16
    .i16
    lda z:US_PNEWX
    sta z:ex
    bra done
turn:
    .a16
    .i16
    lda z:edir
    eor #1
    sta z:edir
done:
    .a16
    .i16
.endmacro

; --- stomp_check ex, ealive, ey_const -> A: classify player contact ---------
; In/out: A16/I16, DB=0. Clobbers A. Returns 0 = no contact (dead enemies
; are transparent) / 1 = STOMP (this macro kills the enemy and writes the
; bounce into US_VY — the next phys_step rises into the hop automatically) /
; 2 = HURT (respond in the caller).
;
; The classifier: overlap is the strict 8x8 AABB (boxes must share >= 1 px, so
; |dx| < 8 and |dy| < 8 — the compare-and-swap shape is the tree's inline-AABB
; idiom); then
;   vy = 0  -> HURT (standing: side contact)
;   vy < 0  -> HURT (rising: hit from below)
;   falling -> depth = (pyi + 8) - ey; depth > ST_STOMP_DEPTH -> HURT
;              (too deep: side contact mid-fall); else STOMP.
; MAX_FALL = 4 makes a falling first-touch land within 4 px, so depth 5
; covers every genuine landing — the two constants are a matched pair.
.macro stomp_check ex, ealive, ey_const
    .local alive, dx_ge, dx_ok, dy_chk, dy_ge, contact, hurt, none, done
    .a16
    .i16
    lda z:ealive
    bne alive
    jmp none
alive:
    .a16
    .i16
    lda z:US_PX                 ; |px - ex| < 8 ?
    cmp z:ex
    bcs dx_ge
    lda z:ex
    sec
    sbc z:US_PX
    bra dx_ok
dx_ge:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc z:ex
dx_ok:
    .a16
    .i16
    cmp #8
    bcc dy_chk
    jmp none
dy_chk:
    .a16
    .i16
    lda z:US_PYI                ; |pyi - ey| < 8 ?
    cmp #ey_const
    bcs dy_ge
    lda #ey_const
    sec
    sbc z:US_PYI
    bra contact
dy_ge:
    .a16
    .i16
    lda z:US_PYI
    sec
    sbc #ey_const
contact:
    .a16
    .i16
    cmp #8
    bcc :+
    jmp none
:   .a16
    lda z:US_VY
    beq hurt                    ; standing -> side contact
    bmi hurt                    ; rising -> hit from below
    lda z:US_PYI                ; falling: how deep into the enemy's top?
    clc
    adc #8                      ; the player's bottom edge (exclusive)
    sec
    sbc #ey_const
    cmp #(ST_STOMP_DEPTH + 1)
    bcs hurt                    ; too deep -> side contact mid-fall
    stz z:ealive                ; STOMP: kill + bounce
    lda #ST_BOUNCE_NEG
    sta z:US_VY
    lda #1
    bra done
hurt:
    .a16
    .i16
    lda #2
    bra done
none:
    .a16
    .i16
    lda #0
done:
    .a16
    .i16
.endmacro

; =============================================================================
; TICK — once per frame (display active — no direct VRAM writes here)
; =============================================================================
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    lda z:US_BLINK
    inc a
    sta z:US_BLINK              ; the free-running heartbeat
    jsr clear_pump              ; pending CLEAR letters, one cell per frame
    jsr move_player
    jsr do_jump
    jsr phys_step
    lda z:US_PYF                ; the drawn pixel, refreshed after physics
    xba
    and #$00FF
    sta z:US_PYI
    jsr run_patrols
    jsr resolve_contacts
    jmp st_obj_draw             ; re-stage every entry, every frame

; --- move_player: the d-pad on HELD state, solid-box move check -------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; Both directions tested independently (holding both cancels), then ONE box
; test at the tentative position — blocked keeps the old x, which is what makes
; the border columns and the low walls walls.
move_player:
    .a16
    .i16
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                ; refresh pyi before the horizontal probe
    lda z:US_PX
    sta z:US_NEWX
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_NEWX
    clc
    adc #ST_SPEED
    sta z:US_NEWX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_NEWX
    sec
    sbc #ST_SPEED
    sta z:US_NEWX
@no_left:
    .a16
    .i16
    lda z:US_NEWX
    sta z:US_BOXX
    lda z:US_PYI
    sta z:US_BOXY
    jsr st_solid_box
    bne @blocked
    lda z:US_NEWX
    sta z:US_PX
@blocked:
    .a16
    .i16
    rts

; --- do_jump: A on the RISING EDGE, gated on grounded ------------------------
; In/out: A16/I16, DB=0. Clobbers A. Fixed height: no jump-cut in this rail.
do_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    bne @edge
    rts
@edge:
    .a16
    .i16
    lda z:US_GROUNDED
    bne @go
    rts                         ; can't jump in mid-air
@go:
    .a16
    .i16
    lda #ST_JUMP_NEG            ; -ST_JUMP_VEL: 4.5 px/f take-off
    sta z:US_VY
    stz z:US_GROUNDED
    rts

; --- run_patrols: one patrol step per LIVE enemy ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Real labels, not `@` locals: a macro
; expansion ends any enclosing cheap-local scope, so the alive gates trampoline
; through named ones.
run_patrols:
    .a16
    .i16
    lda z:US_E1ALIVE
    bne rp_e1
    jmp rp_e1_done
rp_e1:
    .a16
    .i16
    patrol_step US_E1X, US_E1DIR, ST_E1_Y
rp_e1_done:
    .a16
    .i16
    lda z:US_E2ALIVE
    bne rp_e2
    jmp rp_e2_done
rp_e2:
    .a16
    .i16
    patrol_step US_E2X, US_E2DIR, ST_E2_Y
rp_e2_done:
    .a16
    .i16
    rts

; --- resolve_contacts: stomp or hurt, at most ONE contact per frame ---------
; In/out: A16/I16, DB=0. Clobbers A, X, Y (via the handlers). The check ORDER
; is the priority: enemy 1 first, and its result — if any — ends the frame's
; resolution, so a player wedged between both enemies resolves once and
; deterministically.
resolve_contacts:
    .a16
    .i16
    stomp_check US_E1X, US_E1ALIVE, ST_E1_Y
    cmp #1
    bne rc1
    jmp scored
rc1:
    .a16
    .i16
    cmp #2
    bne rc2
    jmp hurt_respawn
rc2:
    .a16
    .i16
    stomp_check US_E2X, US_E2ALIVE, ST_E2_Y
    cmp #1
    bne rc3
    jmp scored
rc3:
    .a16
    .i16
    cmp #2
    bne rc4
    jmp hurt_respawn
rc4:
    .a16
    .i16
    rts

; --- scored: a stomp landed — count down + reprint --------------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; The live cell is the counter's UNITS digit only (col ST_DIGITS_C + 4): the
; value is 0..2, so the "0000" prefix is static from enter and one
; text_queue_cell per stomp is the whole reprint (race_logic's lap-digit
; pattern). Both down starts the CLEAR pending print — the letters
; go out one per frame from the NEXT tick (clear_pump), because the queue
; holds ONE run per frame and this frame's run is the digit.
scored:
    .a16
    .i16
    lda z:US_FOES
    dec a
    sta z:US_FOES
    clc
    adc #('0' - ' ')            ; glyph index (space is tile 0)
    ora #TXT_ATTR
    ldx #(ES_V_TEXT_MAP + ST_HUD_ROW * 32 + ST_DIGITS_C + 4)
    jsr text_queue_cell
    lda z:US_FOES
    bne @done
    lda #ST_CLEAR_LEN           ; both down -> CLEAR, spread over five frames
    sta z:US_CLEARP
@done:
    .a16
    .i16
    rts

; --- hurt_respawn: knockback to spawn (the enemy survives) ------------------
; In/out: A16/I16, DB=0. Clobbers A.
hurt_respawn:
    .a16
    .i16
    lda #ST_SPAWN_X
    sta z:US_PX
    lda #(ST_SPAWN_Y << 8)
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    lda z:US_HURTS
    inc a
    sta z:US_HURTS
    lda z:US_PYF                ; pyi refresh: the draw reads it this frame
    xba
    and #$00FF
    sta z:US_PYI
    rts

; --- clear_pump: the pending CLEAR print, one cell per frame ----------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; "CLEAR" is five cells and bg_text's VBlank queue holds ONE run of up to
; four per frame — and the frame the second stomp lands already stages the
; FOES digit. So the win print is a five-tick pump: letter index
; (ST_CLEAR_LEN - clearp), queued from the tick AFTER the closing stomp,
; finishing five frames later (invisible at 60 fps, exact under the
; Machine). Runs BEFORE resolve_contacts in the tick, so the closing
; stomp's frame pumps nothing and the digit's run is never displaced.
clear_pump:
    .a16
    .i16
    lda z:US_CLEARP
    bne @pump
    rts
@pump:
    .a16
    .i16
    lda #ST_CLEAR_LEN
    sec
    sbc z:US_CLEARP             ; letter index 0..4
    tax
    sep #$20
    .a8
    lda f:s_clear, x            ; the ascii letter
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #' '                    ; glyph index
    ora #TXT_ATTR
    pha                         ; the tile word (A16 push, single pull below)
    txa
    clc
    adc #(ES_V_TEXT_MAP + ST_CLEAR_ROW * 32 + ST_CLEAR_C)
    tax                         ; X = this letter's VRAM cell
    pla
    jsr text_queue_cell
    lda z:US_CLEARP
    dec a
    sta z:US_CLEARP
    rts

.segment "RODATA"
s_foes:   .byte "FOES", 0
s_count0: .byte "00002", 0
s_clear:  .byte "CLEAR", 0
.segment "CODE"
.endscope
