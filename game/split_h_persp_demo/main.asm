; =============================================================================
; split_h_persp_demo — two PERSPECTIVE cameras, one world
; =============================================================================
; A HORIZONTAL split screen over a single wrapping checker plane. The top 112
; scanlines are camera A's full per-scanline trapezoid; the bottom 112 are
; camera B's — a DIFFERENT trapezoid, at a DIFFERENT world position, on a
; DIFFERENT animation axis. Neither band runs a live perspective solve: each
; streams a ROM-resident band-local pose straight through INDIRECT HDMA in
; REPEAT mode, so the whole per-frame work is FOUR stores in VBlank. (A store
; COUNT, not a measured cycle figure: no cycle measurement was taken.)
;
; Pad 1 carries both drivers on different axes — Left/Right steps camera A's
; heading, Up/Down steps camera B's zoom — which is what makes "two cameras
; animating independently" an assertion rather than a thing to watch. See
; game.toml for why both axes are pad-driven rather than free-running.
;
; ONE SCENE, no edges, mirroring split_h_2p_demo's, split_v_fight's and
; m7_dungeon's shape. game.toml's header carries every feature deliberately NOT
; composed and names the allocator check that would have refused each of them.
;
; NOTHING HERE IS HAND-PLACED. There is no runtime HDMA channel allocator, no
; hand-picked WRAM pose arena or band-table arena, and no boot-time solve: the
; channel numbers, the DMAP and BBAD bytes, the table addresses and the ROM
; banks are all emitted by the allocator from three feature.toml declarations,
; and `no_literals` refuses the build if any of them is written down instead.
;
; TWO LESSONS A LIVE-SOLVE VERSION OF THIS RAIL WOULD CARRY, and why neither is
; here: *why* the second camera must be precomputed, and the active-buffer
; apply-hook rule that keeps a live solve's double buffer from tearing, are both
; artefacts of one camera being solved at runtime. Here BOTH cameras are
; precomputed by construction — their poses are ROM, emitted at build time — so
; there is no solve to schedule, no second buffer, and no apply hook. Nothing in
; this ROM mirrors either lesson, deliberately.

.p816
.smart

.define SF_HDR_TITLE "SPLIT H PERSP"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. The generated header suggests wrapping it in
; `.scope <id>` for a multi-scene ROM so two scenes' symbols cannot collide;
; this rail has exactly one scene and both scene-scoped features resolve its
; symbols from file scope, so a wrapper here would only hide them.
.include "engine_state_persp.inc"   ; GENERATED — the persp scene's map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37): a claim with no .incbin here would
; reserve the window and let whatever the linker left there be read as art —
; and on this rail "art" includes the four pose tables the matrix channels feed
; straight into M7A-M7D, so the failure mode would be a floor with no horizon.
;
; THE ORDER OF THE WINDOWS IS THE ALLOCATOR'S, not a preference: place_rom packs
; free claims by (-bytes, name), so the 32,768 B map takes window 1 and the two
; 28,672 B pose sets take 2 and 3 in name order (A_ab before A_cd), each with
; its smaller zoom sibling packed into the slack behind it. The sites here
; follow build/shp/allocation_report.txt exactly, and the per-site .asserts are
; what would turn a re-sort into a build failure rather than into four blobs
; quietly reading each other's bytes.
;
; shp_map is 32,768 B — one WHOLE LoROM window — so it gets a bank to itself and
; the single DMA that uploads it cannot cross a bank boundary.
.segment "BANK1"
shp_map_bin:
    .incbin "shp_map.bin"
.assert ^shp_map_bin = ES_R_SHP_MAP_BANK, error, "shp_map bank drifted from allocator claim"
.assert .loword(shp_map_bin) = ES_R_SHP_MAP_ADDR, error, "shp_map addr drifted from allocator claim"

; --- the two pose sets, one bank per register pair -------------------------
; Camera A's 64-heading set and camera B's 8-zoom set for the SAME register
; pair land in the SAME window, which is not a coincidence and is load-bearing:
; DASB is per channel, so band 1's AB channel and band 2's AB channel each need
; a bank byte, and both sets fitting one window is what makes those bytes
; static (shp_cam.asm writes them once at scene enter rather than every
; VBlank). The 4,096 B of slack behind the heading set is exactly where the
; 3,584 B zoom set and the 10-byte palette pack.
;
; If a future edit grew either set past one window, the size .asserts in
; shp_cam.asm fire before this arrangement can silently stop being true.
.segment "BANK2"
shp_poseA_ab_bin:
    .incbin "shp_poseA_ab.bin"
.assert ^shp_poseA_ab_bin = ES_R_SHP_POSEA_AB_BANK, error, "shp_poseA_ab bank drifted from allocator claim"
.assert .loword(shp_poseA_ab_bin) = ES_R_SHP_POSEA_AB_ADDR, error, "shp_poseA_ab addr drifted from allocator claim"
shp_poseB_ab_bin:
    .incbin "shp_poseB_ab.bin"
.assert ^shp_poseB_ab_bin = ES_R_SHP_POSEB_AB_BANK, error, "shp_poseB_ab bank drifted from allocator claim"
.assert .loword(shp_poseB_ab_bin) = ES_R_SHP_POSEB_AB_ADDR, error, "shp_poseB_ab addr drifted from allocator claim"
shp_pal_bin:
    .incbin "shp_pal.bin"
.assert ^shp_pal_bin = ES_R_SHP_PAL_BANK, error, "shp_pal bank drifted from allocator claim"
.assert .loword(shp_pal_bin) = ES_R_SHP_PAL_ADDR, error, "shp_pal addr drifted from allocator claim"

.segment "BANK3"
shp_poseA_cd_bin:
    .incbin "shp_poseA_cd.bin"
.assert ^shp_poseA_cd_bin = ES_R_SHP_POSEA_CD_BANK, error, "shp_poseA_cd bank drifted from allocator claim"
.assert .loword(shp_poseA_cd_bin) = ES_R_SHP_POSEA_CD_ADDR, error, "shp_poseA_cd addr drifted from allocator claim"
shp_poseB_cd_bin:
    .incbin "shp_poseB_cd.bin"
.assert ^shp_poseB_cd_bin = ES_R_SHP_POSEB_CD_BANK, error, "shp_poseB_cd bank drifted from allocator claim"
.assert .loword(shp_poseB_cd_bin) = ES_R_SHP_POSEB_CD_ADDR, error, "shp_poseB_cd addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "shp_floor.asm"
.include "shp_cam.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/persp.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE CALL, AND IT IS A COMMIT WINDOW. cam_tick re-points band 1 at camera A's
; heading pose and band 2 at camera B's zoom pose. It runs here because the
; HDMA init fetch for the next frame reads those index tables at line 0, so
; VBlank is the window in which a rewrite cannot tear.
;
; Nothing else is in this hook and nothing else needs to be: the origin tables
; are static (these cameras do not move), the DASB bytes are static (each pose
; set is one LoROM window) and no OAM shadow exists (nothing draws).
sm_nmi_hook:
    .a8
    .i16
    jsr cam_tick                ; A8 in, A8 out — its own width contract
    rts

; --- scene dispatch tables (manifest order: persp=0) -----------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word persp::enter
sm_tick_tab:    .word persp::tick
sm_exit_tab:    .word persp::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    jsr input_init
    ; ---- enter the boot scene (id 0 = persp) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    ; Bit 0 is what makes the PPU latch $4218 every VBlank, and `input_read`
    ; waits out the busy window before reading it.
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI enable + auto-joypad
    rep #$20
    .a16
@loop:
    .a16
    .i16
    ; The pad is latched FIRST, immediately after sm_frame_sync returned from
    ; the VBlank the auto-read ran in; the scene tick is its only reader.
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
