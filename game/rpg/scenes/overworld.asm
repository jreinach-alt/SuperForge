; =============================================================================
; scenes/overworld.asm — the Mode 7 world, and the walk across it
; =============================================================================
; A 128x128-tile designed world on the Mode 7 plane, seen in perspective from a
; camera the avatar rides. The D-pad moves ONE TILE per press, animated as a
; TILE_PX-pixel slide the frame's own published step is spent on — one pixel a
; frame on NTSC, 1.2018 on PAL, so the tile takes the same real time on both
; machines (game.toml's region note derives it); a press into a blocked tile is
; rejected by a `col_map` probe of the PARALLEL flat tilemap, so nothing reads
; VRAM back.
; The town gate is a blocked tile carrying F_TOWN: walk into it and the mosaic
; wipe carries you to the interior.
;
; THE SKY IS THE BACKDROP. `split_band` runs BGMODE 1 with TM = OBJ only above
; scanline SB_LINES and BGMODE 7 with TM = BG1 + OBJ below it, so the lines
; above the horizon show CGRAM word 0 — which rpg_floor's palette claim owns and
; paints sky blue, and which no floor tile may use (the generator asserts it).
; The sky costs no layer and no channel of its own: it is what is left when a
; band enables nothing.
;
; The scene-scoped features are included INSIDE this scope, because each names
; symbols that belong to this scene: rpg_floor's upload channel and palette
; base, rpg_obj's OBJ page (floored at word $4000 here by the Mode 7 region and
; at 0 in the town), mode7_persp's index tables, col_map's hot block.

.scope overworld

.include "engine_state_overworld.inc"   ; GENERATED — this scene's map
.include "rpg_floor.asm"
.include "rpg_obj.asm"
.include "mode7_persp.asm"

; --- col_map's binding contract: six symbols, no defaults -------------------
; The world is 128x128 TILES = a 1024-px torus, so col_map's `and #(CM_W-1)`
; mask IS this world's own wrap, so its totality is exactly right here. (A
; world whose size is not the mask's period is the case to be careful with —
; there the mask silently folds far coordinates onto near ones.) `::`-qualified
; because
; ca65 defers an unqualified parent-scope lookup from inside a scope.
CM_WORLD_W_LOG2 = ::WORLD_TILES_LOG2
CM_WORLD_H_LOG2 = ::WORLD_TILES_LOG2
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_COL_WORLD_SIZE, error, "col_map world size disagrees with the col_world claim"
CM_WORLD_BLOB = ::ES_R_COL_WORLD_ADDR
CM_WORLD_BLOB_BANK = ::ES_R_COL_WORLD_BANK
; DERIVED, not narrated. One chunk here (16 KB < a 32 KB window), which takes
; col_map's constant-bank branch and owes no chunk-consecutiveness assert —
; there are no per-chunk symbols to assert about, because this is a plain `rom`
; claim. m7_dungeon's scene is the precedent for the derivation.
CM_WORLD_BLOB_CHUNKS = (::ES_R_COL_WORLD_SIZE + 32767) / 32768
CM_FLAGS = ::rpg_flags_bin
.include "col_map.asm"

WORLD_MASK = (1 << (::WORLD_TILES_LOG2 + 3)) - 1    ; 1023: the torus wrap
TILE_MASK = (1 << ::WORLD_TILES_LOG2) - 1           ; 127
AVATAR_X = ::SCREEN_MID_X - 8                       ; a 16x16 sprite, centred on
AVATAR_Y = ::PIVOT_LINE - 8                         ;   the affine pivot

; --- enter: the boot path ---------------------------------------------------
; In/out: A16/I16, DB=0, forced blank (scene_mgr's enter contract).
enter:
    .a16
    .i16
    jsr resume
    sep #$20
    .a8
    jsr ::fade_start_in             ; the dawn-in. fade_start_in is `.a8`.
    rep #$20
    .a16
    rts

; --- resume: everything the picture needs, from cold or after a wipe --------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; The 32 KB Mode 7 region is re-uploaded on EVERY entry, which is the honest
; cost of a rail whose town writes low VRAM. The alternative — putting the
; interior in upper VRAM so the plane survives, as mode7_explore does — buys a
; faster return and costs the town its own CHR page, which is where `dialog`'s
; page has to fit.
resume:
    .a16
    .i16
    jsr rpgf_arm                    ; the plane: 32 KB region + palette + M7SEL
    jsr rpgo_arm                    ; OBJ CHR + palette + OBSEL
    jsr persp_arm                   ; index tables + the two channel shadows
    lda #0
    jsr persp_set_pose              ; ONE heading: this world does not rotate.
                                    ;   Pose 0 is the identity heading, which is
                                    ;   the same argument mode7_explore makes
                                    ;   for composing m7_affine at heading 0.
    jsr arm_split                   ; BGMODE/TM per band -> the sky
    jsr apply_camera                ; the origin shadows, from the saved tile
    jsr draw_avatar
    sep #$20
    .a8
    lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH) | (1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    sta z:ES_SM_NMI + 2             ; HDMAEN shadow (the NMI applies it)
    lda #::SB_MODE_BOT
    sta a:$2105                     ; BGMODE seed — split_band's `sb_mode_seed`
    lda #::SB_TM_BOT
    sta a:$212C                     ; TM seed; the HDMA table owns both per line
    rep #$20
    .a16
    rts

; --- arm_split: the band tables into the scene_mgr HDMA shadow --------------
; In/out: A16/I16, DB=0. Clobbers A, X.
arm_split:
    .a16
    .i16
    sep #$20
    .a8
    ldx #(ES_H_BGM_CH * 16)
    lda #ES_H_BGM_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, 1 byte
    lda #ES_H_BGM_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD: BGMODE
    lda #^sb_bgmode_tab
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B
    rep #$20
    .a16
    lda #.loword(sb_bgmode_tab)
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T
    sep #$20
    .a8
    ldx #(ES_H_TMI_CH * 16)
    lda #ES_H_TMI_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: indirect, 1 byte
    lda #ES_H_TMI_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD: TM
    lda #^sb_tm_tab
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: index-table bank
    sta f:ES_SM_HDMA_LONG + 7, x    ; DASB: data bank (the same bank)
    rep #$20
    .a16
    lda #.loword(sb_tm_tab)
    sta f:ES_SM_HDMA_LONG + 2, x
    rts

; --- apply_camera: the tile position -> the four origin shadows -------------
; In/out: A16/I16, DB=0. Clobbers A.
; The camera world pixel is the player's tile x 8. ES_M7ORG is mode7_persp's DP
; claim and this scene composes it, so the name is in scope here and nowhere
; else — which is also why the NMI's commit of it is gated on the scene id.
apply_camera:
    .a16
    .i16
    lda z:::RPG_CAM_TX
    asl
    asl
    asl                             ; tile -> world px
    sta z:ES_M7ORG + 0              ; M7X
    sec
    sbc #::SCREEN_MID_X
    sta z:ES_M7ORG + 4              ; BG1HOFS (M7HOFS)
    lda z:::RPG_CAM_TY
    asl
    asl
    asl
    sta z:ES_M7ORG + 2              ; M7Y
    sec
    sbc #::PIVOT_LINE
    sta z:ES_M7ORG + 6              ; BG1VOFS (M7VOFS)
    rts

; --- commit_origin: the NMI-side half, called from sm_nmi_hook --------------
; In/out: A8/I16, DB=0. Gated on the scene id by the hook — ES_M7ORG is SCENE
; DP and the town reuses those bytes.
commit_origin:
    .a8
    .i16
    jsr persp_commit_origin
    rts

; --- tick: one overworld frame ----------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; FROZEN WHILE A WIPE IS IN FLIGHT, in both directions: entering, the picture is
; being dissolved into and a held press would walk before you can see; leaving,
; the step that armed the exit is the last one that counts. On the OUT phase the
; avatar is also parked, because OBJ has NO HARDWARE MOSAIC — $2106 pixelates BG
; layers only, so an unparked sprite floats un-dissolved over a dissolving
; world. mosaic cannot do that itself (TM has one owner per scene and it is
; split_band here, driving TM per scanline), so it is the stated caller
; contract.
tick:
    .a16
    .i16
    sep #$20
    .a8
    jsr ::mosaic_active             ; A = the state byte, Z set when idle
    cmp #::MOS_OUT
    rep #$20
    .a16
    beq @dissolving_out
    sep #$20
    .a8
    jsr ::mosaic_active
    rep #$20
    .a16
    beq @live
    rts                             ; the IN ramp: frozen, already drawn
@dissolving_out:
    .a16
    .i16
    jsr rpgo_park
    rts
@live:
    .a16
    .i16
    jsr walk_tick
    jsr draw_avatar
    rts

; --- walk_tick: spend this frame's pixel budget on the grid walk ------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE FRAME'S BUDGET IS SPENT WHOLE. `TS_STEP` publishes the whole pixels this
; frame carries — exactly one on NTSC, one or two on PAL in the pattern that
; averages 1.2018 — and this lays them down, crossing into the NEXT tile if the
; current one lands with pixels still in hand. That crossing is the only place
; the deciding frame is free, and it is what puts the walk's real-time rate on
; parity rather than 2.5% short: game.toml's region note derives it and gives
; the measurement.
;
; ON NTSC THE CROSSING CANNOT HAPPEN, which is why the picture does not move.
; The budget is one pixel and a tile is eight, so a frame inside a slide always
; ends inside it or exactly on the boundary with nothing left over — the
; deciding frame is never merged and the walk is the same nine frames per tile
; it always was, store for store.
walk_tick:
    .a16
    .i16
    TS_STEP z:US_TS_ACC, TS_ONE     ; one pixel per NTSC frame
    beq @done                       ; unreachable at this base — the carry is
                                    ;   always below one whole unit, so the sum
                                    ;   never is — and the spend loop below
                                    ;   must not run for ever if that ever
                                    ;   stops being true
    sta z:US_TS_STEP
    sep #$20
    .a8
    lda z:::RPG_STEP_PX
    rep #$20
    .a16
    and #255
    beq @decide_only
@spend:
    .a16
    .i16
    ; move = min(this frame's remaining budget, the pixels left to the tile)
    sep #$20
    .a8
    lda z:::RPG_STEP_PX
    rep #$20
    .a16
    and #255
    cmp z:US_TS_STEP
    bcc @have                       ; the tile lands first
    lda z:US_TS_STEP                ; the budget runs out first
@have:
    .a16
    .i16
    sta z:::RPG_T0                  ; the move. TRANSIENT and consumed before
                                    ;   the jsr below, which is what that slot's
                                    ;   contract asks — rpg_town and rpg_obj own
                                    ;   it the same way and neither is reachable
                                    ;   from here.
    tax                             ; ...and the travel count for advance_px
    lda z:US_TS_STEP
    sec
    sbc z:::RPG_T0
    sta z:US_TS_STEP                ; the budget left after this move
    sep #$20
    .a8
    lda z:::RPG_STEP_PX
    sec
    sbc z:::RPG_T0                  ; A8 reads T0's LOW byte, and a move is at
                                    ;   most TILE_PX, so that byte is all of it
    sta z:::RPG_STEP_PX
    rep #$20
    .a16
    jsr advance_px                  ; X pixels of the armed slide
    lda z:US_TS_STEP
    beq @done                       ; the frame's budget is spent
    ; Budget left over means the slide ARRIVED — step_px is 0 — so this frame
    ; decides as well as walks, and the rest of the budget goes on the new tile.
    jsr read_step
    sep #$20
    .a8
    lda z:::RPG_STEP_PX
    rep #$20
    .a16
    and #255
    bne @spend                      ; a tile was armed: lay the remainder down
@done:
    .a16
    .i16
    rts
@decide_only:
    .a16
    .i16
    jsr read_step                   ; the deciding frame: it arms and moves
    rts                             ;   nothing, and its budget lapses — on
                                    ;   both machines alike, which is why the
                                    ;   ratio comes out on the whole cycle

; --- advance_px: lay N pixels of the armed slide onto the camera origin -----
; In: X = the pixels to travel, at least 1. In/out: A16/I16, DB=0. Clobbers
; A, X. The body is what `advance_step` was — the same add, the same torus mask
; and the same two derived scroll words — run once per PIXEL now rather than
; once per frame, because how many pixels a frame carries is the region's
; answer and no longer a constant this scene can assume.
advance_px:
    .a16
    .i16
@px:
    .a16
    .i16
    lda z:ES_M7ORG + 0
    clc
    adc z:::RPG_STEP_DX
    and #WORLD_MASK                 ; the 1024-px torus, the same wrap col_map's
    sta z:ES_M7ORG + 0              ;   mask makes on the collision side
    sec
    sbc #::SCREEN_MID_X
    sta z:ES_M7ORG + 4
    lda z:ES_M7ORG + 2
    clc
    adc z:::RPG_STEP_DY
    and #WORLD_MASK
    sta z:ES_M7ORG + 2
    sec
    sbc #::PIVOT_LINE
    sta z:ES_M7ORG + 6
    dex
    bne @px
    rts

; --- read_step: a held direction -> one tile of movement --------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Cardinal only, one at a time, in a
; fixed priority so a diagonal press picks an axis instead of moving twice.
read_step:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #::JOY_LEFT
    beq @not_left
    ldx #65535
    ldy #0
    jmp try_step
@not_left:
    .a16
    .i16
    bit #::JOY_RIGHT
    beq @not_right
    ldx #1
    ldy #0
    jmp try_step
@not_right:
    .a16
    .i16
    bit #::JOY_UP
    beq @not_up
    ldx #0
    ldy #65535
    jmp try_step
@not_up:
    .a16
    .i16
    bit #::JOY_DOWN
    beq @none
    ldx #0
    ldy #1
    jmp try_step
@none:
    .a16
    .i16
    rts

; --- try_step: probe the destination tile, then commit or reject ------------
; In: X = signed tile dx, Y = signed tile dy. In/out A16/I16, DB=0.
; Clobbers A, X, Y.
;
; The probe is `col_map`'s: two u16 world PIXELS in, one flag byte out, TOTAL —
; every input maps onto a real tile because the kernel masks, so there is no
; bounds branch to get wrong and no sentinel a caller can forget to check.
try_step:
    .a16
    .i16
    stx z:::RPG_STEP_DX             ; a +-1 TILE delta is also the +-1 PX
    sty z:::RPG_STEP_DY             ;   DIRECTION the slide lays down TILE_PX
                                    ;   times, however many frames that takes
    txa
    clc
    adc z:::RPG_CAM_TX
    and #TILE_MASK
    asl
    asl
    asl
    clc
    adc #4                          ; probe the destination tile's CENTRE
    sta z:CM_PX
    tya
    clc
    adc z:::RPG_CAM_TY
    and #TILE_MASK
    asl
    asl
    asl
    clc
    adc #4
    sta z:CM_PY
    jsr col_map_at                  ; Out: A8 = the flag byte. X and Y are
                                    ;   clobbered, which is why the deltas were
                                    ;   parked in DP above rather than held.
    rep #$20
    .a16
    and #255                        ; WIDTH-RISK: col_map_at exits A8, so the
                                    ;   C-high byte is stale — mask before any
                                    ;   16-bit test of the flag
    bit #::F_TOWN
    bne @gate
    bit #::F_BLOCK
    bne @blocked
    ; ---- walkable: commit the destination tile and arm the slide ----------
    lda z:::RPG_STEP_DX
    clc
    adc z:::RPG_CAM_TX
    and #TILE_MASK
    sta z:::RPG_CAM_TX
    lda z:::RPG_STEP_DY
    clc
    adc z:::RPG_CAM_TY
    and #TILE_MASK
    sta z:::RPG_CAM_TY
    sep #$20
    .a8
    lda #::TILE_PX                  ; the DISTANCE to the tile just committed —
    sta z:::RPG_STEP_PX             ;   a duration would have to know the region
    rep #$20
    .a16
    rts
@blocked:
    .a16
    .i16
    rts                             ; the deltas are stale but STEP_PX is 0, and
                                    ;   walk_tick only lays pixels while it is
                                    ;   not
@gate:
    .a16
    .i16
    ; The town gate is BLOCKED as well as flagged, so the avatar stops in front
    ; of it and the last frame before the dissolve shows it standing there. The
    ; swap REQUEST is raised by the callback at peak black, not here.
    sep #$20
    .a8
    lda #::TM_BG1                   ; the affected-BG nibble for $2106
    ldx #.loword(::rpg_blank_to_town)
    jsr ::mosaic_arm
    rep #$20
    .a16
    rts

; --- draw_avatar: the player, pinned at the affine pivot --------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; The avatar does not move on screen — the WORLD moves under it — so its screen
; position is a constant and its X9 is clear by construction. The hi-table byte
; is still rebuilt WHOLE rather than assumed (rpg_obj's contract).
draw_avatar:
    .a16
    .i16
    lda #AVATAR_X
    ldx #AVATAR_Y
    ldy #0
    jsr rpgo_place
    lda #AVATAR_X
    ldx #0                          ; actor 1 is unused here and stays parked
    jsr rpgo_hi
    sep #$20
    .a8
    lda #240
    sta a:ES_OAM_SHADOW + 5         ; actor 1 parked below the screen
    rep #$20
    .a16
    rts

; --- exit: the scene_mgr contract, kept honest ------------------------------
; NOTHING REACHES HERE on this rail — the transition is rpg_swap_service, not
; `sm_request` — but the table is indexed by scene id and a missing entry would
; be a hole the day someone adds a title screen.
exit:
    .a16
    .i16
    jsr rpgo_park
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz z:ES_SM_NMI + 2             ; HDMAEN shadow: the bands disarmed
    rep #$20
    .a16
    rts

.endscope
