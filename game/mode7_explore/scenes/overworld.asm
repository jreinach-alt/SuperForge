; =============================================================================
; scenes/overworld.asm — the streaming Mode 7 world, and the walk on it
; =============================================================================
; A 512x512-tile world — sixteen times the area the Mode 7 VRAM window holds —
; streamed in around an avatar who never leaves screen centre. The D-pad walks
; her on the tile grid; water and mountains refuse; the picture dawns in from
; black.
;
; THE CAMERA, in three lines:
;
;   m7a_set_heading(0)         ONCE, at enter. Heading 0's LUT entry IS the
;                              identity matrix, so this rail never rotates and
;                              the per-frame re-commit is eight constant stores.
;   m7a_set_center(pivot)      per frame. The pivot -> M7X/M7Y and the screen
;                              origin, which under Mode 7 IS BG1HOFS/BG1VOFS.
;   (NMI) m7a_nmi_commit       the shadow -> the eight ports, latched together
;                              before scanline 0.
;
; No trigonometry, no HDMA channel for the matrix and no per-scanline table:
; the one channel this rail spends is the streamer's VBlank GP-DMA.
;
; THE SCENE-SCOPED FEATURES ARE INCLUDED INSIDE THIS SCOPE, next to the scene
; map whose symbols they read — m7x_floor names ES_D_M7X_UP_*, ES_C_M7X_PAL and
; ES_R_M7X_SEED_SIZE; m7x_obj names ES_V_OBJ_CHR* and ES_O_*; mode7_stream and
; col_map name their own scene claims. Those are `overworld`'s symbols, not the
; game's. The globals (ES_M7AFF, ES_INP_CUR, the ES_R_M7X_* claims, the blob
; labels) resolve outward through the enclosing file scope.

.scope overworld

.include "engine_state_overworld.inc"  ; GENERATED — this scene's map
.include "m7x_world.inc"               ; GENERATED — the world's vocabulary:
                                       ;   geometry, spawn, clamp, terrain
                                       ;   classes, tile ids, the avatar's
                                       ;   tile grid. EQUATES ONLY, no data.

; TM's layer bits ($212C). Named rather than spelled as one hex byte so the two
; layers this scene composites are legible at the write site.
TM_BG1 = $01
TM_OBJ = $10

; --- the plane -------------------------------------------------------------
.include "m7x_floor.asm"

; --- the avatar ------------------------------------------------------------
; TWO BINDINGS, both the GAME's state, both `.error` with no default. Binding
; them rather than letting the feature name US_* directly is what keeps the
; sprite and the walk machine reading ONE variable: a feature that latched its
; own facing would drift from the one the collision test turned.
MXO_FACING = US_FACING
MXO_WALK   = US_STEP_REMAIN
.include "m7x_obj.asm"

; --- the streamer ----------------------------------------------------------
; mode7_stream's blob binding, declared at the COMPOSITION site because the
; blob is the game's and not the feature's (the feature carries no
; default for any of the three, so a missing one is a named `.error`).
;
; The `::` is LOAD-BEARING: ca65 DEFERS an unqualified parent-scope lookup, and
; a deferred symbol is not a constant expression — which M7S_CHUNKS must be,
; because it reaches a `.repeat` count inside this scope.
M7S_WORLD_WIN = ::ES_R_M7X_MAP_T0_ADDR
M7S_BLOB_BANK = ::ES_R_M7X_MAP_T0_BANK
M7S_CHUNKS    = ::ES_R_M7X_MAP_CHUNKS   ; DERIVED from the claim, not narrated
; ...and the three that are bound BY NAME rather than by contract
; (mode7_stream.asm's header says so, and says the generalisation was left for
; the rail that needs a different world WIDTH). Both rails on the
; table are 512 tiles wide, so this rail is not that rail — but the values come
; from the generator's own emitted constants rather than being transcribed, so
; a re-themed world of a different size fails the assert below instead of
; streaming at the wrong stride.
WORLD_COLS_BYTES = M7X_COLS_BYTES
CAM0_TX = M7X_SPAWN_TX
CAM0_TY = M7X_SPAWN_TY
.assert WORLD_COLS_BYTES = M7X_WORLD_T, error, "mode7_stream: the row stride disagrees with the world's tile width"
.include "mode7_stream.asm"

; --- collision -------------------------------------------------------------
; col_map's SIX binding symbols, likewise declared here and likewise without a
; default in the feature: a defaulted world size reads real ROM
; bytes at the wrong stride and returns a plausible flag.
;
; THE WORLD IS 512x512 TILES, so both log2s are 9 — and that is ASSERTED
; against the generator's own emitted geometry rather than stated, so a
; re-themed map of a different size stops the build here instead of reading the
; wrong stride.
CM_WORLD_W_LOG2 = 9
CM_WORLD_H_LOG2 = 9
.assert (1 << CM_WORLD_W_LOG2) = M7X_WORLD_T, error, "col_map world width disagrees with the generated world geometry"
.assert (1 << CM_WORLD_H_LOG2) = M7X_WORLD_T, error, "col_map world height disagrees with the generated world geometry"

; THE SAME BLOB THE STREAMER WALKS. That is the economy of this rail and it is
; deliberate: what you see and what blocks you are one 256 KB table, LUT'd
; through a 256-byte tile-id -> terrain-class map, rather than a second
; byte-per-world-tile array that can drift from the picture (and would not fit
; in a 512 KB ROM beside this one).
CM_WORLD_BLOB        = ::ES_R_M7X_MAP_T0_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_M7X_MAP_T0_BANK
CM_WORLD_BLOB_CHUNKS = ::ES_R_M7X_MAP_CHUNKS
CM_FLAGS             = ::m7x_terr_bin
.include "col_map.asm"

; --- the game --------------------------------------------------------------
; Last, because it calls into all three of the above.
.include "m7x_logic.asm"

; =============================================================================
; THE SCENE
; =============================================================================
; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
;
; ORDER IS LOAD-BEARING in one place: mxl_arm seeds the camera AND ES_M7ORG, and
; stream_arm's tile tracking must start in sync with the window the seed just
; uploaded. Both are derived from the same spawn tile — the generator's
; M7X_SPAWN_TX/TY, which is also what build_seed centred the seed on — so the
; three agree by construction rather than by three transcriptions of 258.
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved seed + 12 colours + M7SEL
    jsr obj_arm                     ; the avatar sheet + OBJ palette + OBSEL
    jsr mxl_arm                     ; the camera, at spawn, into ES_M7ORG too
    lda #0
    jsr ::m7a_set_heading           ; heading 0 = the IDENTITY matrix. Once, and
                                    ;   never again: this rail does not rotate,
                                    ;   which is why m7_affine costs it nothing
                                    ;   but the VBlank re-commit of a constant.
    jsr stream_arm                  ; tile tracking, in sync with the seed
    jsr mxo_draw                    ; frame 0 already has her on screen

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the `scene_writes` this scene owns on m7x_floor's
    ; behalf (see that feature.toml's attribution note). M7SEL is the feature's
    ; own and floor_arm has already written it.
    ;
    ; TM CARRIES BOTH LAYERS, and it has to: it is ONE register with one owner,
    ; and turning OBJ on is not something m7x_obj can do behind the scene's
    ; back. Leaving bit 4 clear is the exact shape of a bug that looks like a
    ; sprite bug — OAM correct, OBJ CHR correct, palette correct, hi table
    ; correct, and nothing on screen, because the main screen was never told to
    ; composite the layer.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #(TM_BG1 | TM_OBJ)          ; TM: the world AND the avatar
    sta a:$212C

    ; ---- the dawn-in -------------------------------------------------------
    ; sm_init left the INIDISP shadow at $00 — display ON at brightness 0, which
    ; is black with the PPU running rather than forced blank. This arms `fade`,
    ; whose per-frame tick then walks that shadow up to 15 and the NMI commits
    ; it. Nothing here writes $2100: scene_mgr commits INIDISP from the shadow
    ; every armed frame, so a bare write would be reverted by the next VBlank.
    ;
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate; call it from A16 and
    ; the CPU eats the following opcode byte as that immediate's high half, the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders black
    ; with perfectly correct VRAM and CGRAM. It
    ; is rule 6's silent-corruption class arriving through a CROSS-FILE contract
    ; width-lint cannot see in either direction.
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE ORDER IS LOAD-BEARING, twice over:
;
;   * mxl_apply_camera comes BETWEEN the walk and the stream. stream_tick reads
;     the camera out of ES_M7ORG, so the origin must be THIS frame's before the
;     leading edge is worked out. Stream first and the window is always one
;     frame behind the picture — which at 1 px/frame is invisible until it is
;     not, and then it is a torn column at a tile boundary.
;   * mxo_draw comes LAST. It reads the slide countdown for its walk bob, and
;     the countdown is what mxl_tick just decremented.
;
; FROZEN WHILE A WIPE IS IN FLIGHT. The freeze is one of the three uses
; mosaic's header names, and it covers the whole tick rather than just the
; input: the camera must not move (the streamer would chase it into a Mode 7
; window that is about to stop being displayed) and the avatar must not be
; redrawn (she is parked for the dissolve — OBJ has no hardware mosaic).
tick:
    .a16
    .i16
    sep #$20
    .a8
    jsr ::mosaic_active             ; A = the state byte, Z set when idle
    cmp #::MOS_OUT                  ; 1 = dissolving AWAY, 2 = dissolving in
    rep #$20
    .a16
    beq @dissolving_out
    sep #$20
    .a8
    jsr ::mosaic_active
    rep #$20
    .a16
    beq @live
    rts                             ; the IN ramp: frozen, and she is already
                                    ;   drawn — the return swap placed her at
                                    ;   the pivot before the first bright frame
@dissolving_out:
    .a16
    .i16
    ; OBJ has no hardware mosaic, so park her while the plane dissolves away.
    ; See the town scene's identical branch for why this is here and not at the
    ; arm site, and m7x_town's town_park for why a park and not a TM drop.
    jsr obj_park
    rts
@live:
    .a16
    .i16
    ; WAS A SLIDE IN FLIGHT? The town trigger fires on a LANDING and only on a
    ; landing — never at rest — and that is what makes the return survivable:
    ; the return puts her back standing ON the demo house, and a check that
    ; asked "am I on it" rather than "did I just arrive on it" would warp her
    ; straight back in, forever.
    lda z:US_STEP_ACTIVE
    pha
    jsr mxl_tick                    ; advance a slide, or start one
    jsr mxl_apply_camera            ; -> ES_M7ORG and the affine shadow
    jsr stream_tick                 ; the leading edge, staged into WRAM slots
    jsr mxo_draw                    ; the avatar at the pin
    pla
    beq @done                       ; nothing was in flight -> nothing landed
    lda z:US_STEP_ACTIVE
    bne @done                       ; still sliding
    jsr check_town_entry
@done:
    .a16
    .i16
    rts

; --- check_town_entry: did that step land her on the enterable house? -------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and col_map's probe words.
;
; EXACTLY ONE TILE IN THE WORLD TRIGGERS THIS. The demo house at
; (M7X_DEMO_HOUSE_TX, M7X_DEMO_HOUSE_TY) carries TERR_TOWN_ENTER; the 190
; decorative lattice houses carry TERR_TOWN, one class below it. That
; distinction is the generator's and it exists for exactly this: a streaming
; sweep crossing a lattice house must never warp. The generator asserts the
; count is one — see tools/gen_mode7_explore_assets.py's invariant 1.
;
; The lookup is `col_map`'s, the same probe the walk already uses to decide
; whether a step is legal, so "what you see", "what blocks you" and "what warps
; you" are one 256 KB table LUT'd through one 256-byte terrain map.
check_town_entry:
    .a16
    .i16
    lda z:US_CAM_PX
    and #$FFF8                      ; the camera is grid-aligned at rest; mask
    sta z:CM_PX                     ;   rather than shift-and-shift-back
    lda z:US_CAM_PY
    and #$FFF8
    sta z:CM_PY
    ; WIDTH-RISK: col_map_at is a CROSS-FILE contract — entered A16/I16 and
    ; EXITING A8/I16, because the flag it returns is a byte. The `rep #$20`
    ; below is a forced widening back to this routine's width and must not be
    ; dropped; width-check cannot see across the file boundary in either
    ; direction, so this marker is what carries it. Same contract, same marker,
    ; as m7x_logic's own call site.
    jsr col_map_at
    rep #$20
    .a16
    and #$00FF                      ; A = the terrain class, zero-extended
    cmp #M7X_TERR_TOWN_ENTER
    beq @enter
    rts
@enter:
    .a16
    .i16
    ; ---- snapshot what has to outlive the visit --------------------------
    ; SCENE DP IS REUSED ACROSS SCENES, so the camera below is space the town
    ; scene owns while she is indoors. These three globals are the whole of
    ; "back out to the overworld at the same spot" (state.toml's [global] block
    ; carries the argument).
    lda z:US_CAM_PX
    sta z:US_OVW_CAM_PX
    lda z:US_CAM_PY
    sta z:US_OVW_CAM_PY
    lda z:US_FACING
    sta z:US_OVW_FACING
    ; ---- arm the wipe ----------------------------------------------------
    ; She is NOT parked here: the tick's OUT branch does it from the next frame,
    ; so the frame the dissolve starts on still has her standing on the house.
    ; NOTHING IS REQUESTED HERE. The swap request is raised by the callback, at
    ; peak black, twenty frames from now — see mxx_blank_to_town's header for
    ; the bug that taught this rail the difference.
    sep #$20
    .a8
    lda #TM_BG1                     ; the affected-BG nibble for $2106: BG1 only
    ldx #.loword(::mxx_blank_to_town)   ; the swap callback — see its header
    jsr ::mosaic_arm
    rep #$20
    .a16
    rts

; --- resume: the blank-phase half of the wipe BACK OUT of the town ----------
; In/out: A16/I16, DB=0. Called from main.asm's mxx_swap_service with forced
; blank on screen and NMI masked. Clobbers A, X, Y.
;
; NOT `enter`, and the difference is the point of the whole slice. `enter`
; uploads the 32 KB seed centred on SPAWN and arms the streamer's tracking from
; the spawn tile; this puts her back where she left. What it has to re-establish
; is exactly what the visit destroyed — CGRAM 0..11 and M7SEL (floor_restage),
; and the streamer's tracking (stream_resync, because that state is scene DP the
; interior reused). The Mode 7 image itself is untouched: the interior wrote
; upper VRAM, so the window is byte-identical to how it was left and there is
; nothing to re-stream.
resume:
    .a16
    .i16
    ; ---- the saved spot --------------------------------------------------
    lda z:US_OVW_CAM_PX
    sta z:US_CAM_PX
    lda z:US_OVW_CAM_PY
    sta z:US_CAM_PY
    lda z:US_OVW_FACING
    sta z:US_FACING
    ; ---- at rest, and the slide state is scene DP the town reused ---------
    stz z:US_STEP_ACTIVE
    stz z:US_STEP_REMAIN
    stz z:US_STEP_DX
    stz z:US_STEP_DY
    jsr floor_restage               ; CGRAM 0..11 + M7SEL, both clobbered indoors
    jsr mxl_apply_camera            ; ES_M7ORG + the affine shadow, at the spot
    jsr stream_resync               ; tracking re-seeded from the restored camera
    jsr mxo_draw                    ; on screen for the FIRST frame of the IN ramp
    ; ---- the scene's base display, exactly as enter leaves it -------------
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #(TM_BG1 | TM_OBJ)          ; TM: the world AND the avatar
    sta a:$212C
    rep #$20
    .a16
    rts

; --- stream_resync: re-seed the streamer's tracking at an arbitrary camera --
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; `stream_arm` does this at ENTER, from the bound CAM0_TX/CAM0_TY spawn
; constants — which is right when the seed upload has just centred the window
; there, and wrong here, where the window is wherever she left it. The invariant
; the streamer needs is only that LAST equals CAM and the pending counts are
; zero: the VRAM window already holds the 128x128 around this camera, so there
; is no leading edge owed and the next step stages one column or row as usual.
;
; WHY THIS IS HERE AND NOT AN ENTRY POINT IN mode7_stream.asm. That file is
; INCLUDED by microzero as well, and adding a routine to it moves that rail's
; pinned ROM md5 for bytes only this rail would ever call. The fields below are
; the feature's own documented DP aliases (ST_CAM_TX .. ST_COL_CNT, mode7_stream
; .asm's "DP field aliases" block) and they are in scope because the feature is
; included INSIDE this scene's scope — the same shape as the game writing
; scene_mgr's INIDISP shadow, which `fade` and `mosaic` both do for the same
; reason. If a second rail ever needs a mid-life re-seed, promote it: that is
; the moment the routine earns its place in the feature.
stream_resync:
    .a16
    .i16
    ldx #(ES_STREAM_HOT_SIZE - 2)
:   stz z:ES_STREAM_HOT, x          ; counts, kernel locals and tracking, cleared
    dex
    dex
    bpl :-
    sep #$20
    .a8
    stz z:ES_STREAM_NMI             ; nothing staged for the next VBlank...
    stz z:ES_STREAM_NMI + 1
    rep #$20
    .a16
    lda z:US_CAM_PX
    .repeat 3
        lsr                         ; px -> tile (MXL_TILE_PX = 8)
    .endrepeat
    sta z:ST_CAM_TX
    sta z:ST_LAST_TX                ; ...and LAST == CAM, so nothing is owed
    lda z:US_CAM_PY
    .repeat 3
        lsr
    .endrepeat
    sta z:ST_CAM_TY
    sta z:ST_LAST_TY
    rts

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's contract), and re-uploading 32 KB to prove a
; point costs a frame. What IS undone is the display state this scene turned on,
; so a successor scene inherits a blank main screen rather than a Mode 7 plane
; it never asked for. This slice has no edges, so nothing reaches here yet — it
; is the contract, kept honest, and it is what the town slice will enter.
exit:
    .a16
    .i16
    jsr obj_park                    ; the avatar leaves with the scene
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
