; =============================================================================
; split_h_demo — the cockpit horizontal raster-band split
; =============================================================================
; A receding Mode-7 perspective floor in the LOWER band under a genuine BG3 tile
; instrument panel in the TOP band: HDMA rewrites BGMODE and TM at scanline 40,
; so lines 0..39 render as Mode 1 (BG3 alone) and lines 40..223 as Mode 7 (BG1,
; the floor) across one clean scanline seam. That is per-band BGMODE+TM under a
; live matrix rebuild — the `split_band` stress case.
;
; THE STRESS, precisely. `split_band` claims BGMODE and TM `band = "scene"` —
; frame-wide — and docs/09 calls it the sole active-phase owner of BGMODE. This
; rail runs that frame-wide claim beside mode7_persp's two INDIRECT matrix
; channels while the camera SPINS, so every VBlank re-points both pose pointers
; and both DASB banks: the matrix under the seam churns every frame and the seam
; itself must not move by one scanline. There is no live per-scanline matrix
; solve here — the churn is the re-point, which is what a game actually does
; when its camera turns.
;
; ONE SCENE, no edges: one RESET and one loop. scene_mgr is composed for the
; INIDISP commit, the HDMA shadow and frame sync.
;
; CONTROLS:
;   P1 Left / Right   spin the Mode-7 camera — the "split under load" stress.
;                     The BG3 readout tracks it.
;   P1 A              toggle the mode/TM split OFF and back ON.

.p816
.smart

.define SF_HDR_TITLE "SPLIT H DEMO"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED (scroller / scroll_run reasoning: one scene,
; and the feature files at top level resolve its symbols from file scope).
.include "engine_state_cockpit.inc"  ; GENERATED — the cockpit scene's map
.include "split_h_demo.inc"          ; the rail's geometry + band bindings
.include "header.inc"
.include "init.inc"                  ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine feature runtimes (the composition game.toml declares) ----------
.include "scene_mgr.asm"
.include "input.asm"
.include "fade.asm"
.include "bg_text.asm"
.include "mode7_floor.asm"
; split_band's five binding symbols come from split_h_demo.inc above — this
; rail is the SECOND binding of that generalised table (microzero is the first).
.include "split_band.asm"

; --- text_dp boot init (the text engine's global DP block) ------------------
; scroll_run's block verbatim: the claim is 3 B for the pointer, so the bank
; byte is stored alone.
text_dp_init:
    .a16
    .i16
    stz z:ES_TXT_PTR
    stz z:ES_TXT_TMP
    sep #$20
    .a8
    stz z:ES_TXT_PTR+2
    rep #$20
    .a16
    stz z:ES_TXT_Q + 0          ; VBlank cell queue: dirty flag + count
    stz z:ES_TXT_Q + 2          ; ...staged VMADD
    stz z:ES_TXT_Q + 4          ; ...staged tile words (TXT_Q_MAX = 4)
    stz z:ES_TXT_Q + 6
    stz z:ES_TXT_Q + 8
    stz z:ES_TXT_Q + 10
    rts

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between map and tree stops the build. The PRESENCE side is
; `make rom-unbacked` (docs/37).
.repeat ES_R_POSES_AB_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 9)
.ident(.sprintf("poses_ab_t%d", PI)):
    .incbin "shd_poses_ab.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_ab_t%d", PI)) = .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", PI)), error, "poses_ab chunk bank drifted"
.assert .loword(.ident(.sprintf("poses_ab_t%d", PI))) = .ident(.sprintf("ES_R_POSES_AB_T%d_ADDR", PI)), error, "poses_ab chunk addr drifted"
.assert .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", PI)) = ES_R_POSES_AB_T0_BANK + PI, error, "poses_ab banks are not consecutive — persp_set_pose's T0_BANK + (h >> 5) addressing would read the wrong bank"
.endrepeat
.repeat ES_R_POSES_CD_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 11)
.ident(.sprintf("poses_cd_t%d", PI)):
    .incbin "shd_poses_cd.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_cd_t%d", PI)) = .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", PI)), error, "poses_cd chunk bank drifted"
.assert .loword(.ident(.sprintf("poses_cd_t%d", PI))) = .ident(.sprintf("ES_R_POSES_CD_T%d_ADDR", PI)), error, "poses_cd chunk addr drifted"
.assert .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", PI)) = ES_R_POSES_CD_T0_BANK + PI, error, "poses_cd banks are not consecutive"
.endrepeat

.repeat ES_R_WORLD_MAP_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 1)
.ident(.sprintf("world_map_t%d", WI)):
    .incbin "world_map.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("world_map_t%d", WI)) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)), error, "world chunk bank drifted"
.assert .loword(.ident(.sprintf("world_map_t%d", WI))) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)), error, "world chunk addr drifted"
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)) = ES_R_WORLD_MAP_T0_BANK + WI, error, "world chunk banks are not consecutive — mode7_floor's seed upload uses T0_BANK + index"
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)) = ES_R_WORLD_MAP_T0_ADDR, error, "world chunks are not window-aligned alike"
.endrepeat

.segment "BANK13"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
floor_tiles_bin:
    .incbin "floor_tiles.bin"
.assert ^floor_tiles_bin = ES_R_FLOOR_TILES_BANK, error, "floor_tiles bank drifted from allocator claim"
.assert .loword(floor_tiles_bin) = ES_R_FLOOR_TILES_ADDR, error, "floor_tiles addr drifted from allocator claim"
floor_pal_bin:
    .incbin "floor_pal.bin"
.assert ^floor_pal_bin = ES_R_FLOOR_PAL_ROM_BANK, error, "floor_pal bank drifted from allocator claim"
.assert .loword(floor_pal_bin) = ES_R_FLOOR_PAL_ROM_ADDR, error, "floor_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features, then the scene -----------------------------
.include "scenes/cockpit.asm"

; --- sm_nmi_hook: per-frame VBlank work ------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; THE LIVE MATRIX REBUILD IS HERE, and this hook is the whole of it: when the
; desired heading differs from the applied one, both INDIRECT index tables get
; three fresh pointer words each and both DASB shadow bytes are re-stamped,
; BEFORE the core's shadow MVN applies them (race.asm's shape — the spec). Every
; held-input frame runs it, so the split's two channels are re-armed from a
; shadow whose neighbouring channels changed under them every single frame.
sm_nmi_hook:
    .a8
    .i16
    jsr cockpit::persp_commit_origin    ; M7X/M7Y/HOFS/VOFS from the DP shadows
    lda f:US_HEADING_LONG
    cmp f:US_HEADING_AP_LONG
    beq :+
    sta f:US_HEADING_AP_LONG
    rep #$20
    .a16
    and #HEAD_MASK              ; A8 load left the high byte stale — mask it
    jsr cockpit::persp_set_pose
    sep #$20
    .a8
:   .a8                         ; every path in (beq + fall-through)
    .i16
    jsr text_vblank_commit      ; the staged readout run, if any
    rts

; --- scene dispatch tables (manifest order: cockpit=0) ---------------------
sm_enter_tab:   .word cockpit::enter
sm_tick_tab:    .word cockpit::tick
sm_exit_tab:    .word cockpit::exit

; --- MAIN: boot ------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr text_dp_init
    ldx #0
    jsr (sm_enter_tab, x)
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write:
    ; scene_mgr commits INIDISP in its NMI. CALLED IN A8, DELIBERATELY —
    ; fade_start_in is `.a8` and its `lda #1` assembles as a ONE-byte
    ; immediate; calling from A16 makes the CPU eat the next opcode as the
    ; immediate's high half and the ramp never arms (split_v_fight paid a real
    ; debugging round for this; the comment is carried so no one pays a second).
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    .i16
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
