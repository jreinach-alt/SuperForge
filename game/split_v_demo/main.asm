; =============================================================================
; split_v_demo — the vertical window dual-view
; =============================================================================
; ONE shared scrolling stage rendered through TWO BG-layer cameras, each
; clipped to its half of the screen by the PPU window system. P1 drives the
; left camera, P2 the right, P1's shoulders sweep the seam, and A/B cycle the
; seam's SHAPE: straight, straight + per-half OBJ clip, or a static diagonal
; streamed per scanline from ROM. A white backdrop bar marks the divide (zero
; sprites, zero tiles) and a red marker stands in each half. This is the
; smallest useful demonstration of the primitive.
;
; ONE SCENE, no edges: one RESET, one loop, mirroring scroller / camera_follow
; / scroll_run. scene_mgr is composed for the INIDISP commit + frame sync;
; `demo` is its only destination.
;
; WHAT IS STATE HERE RATHER THAN A `-D` BUILD: the per-half OBJ clip and the
; diagonal seam. Compile-time variants would put three of the rail's four
; teachings out of reach of the shipping binary; as modes they are cycled both
; ways at runtime and a test can walk them. The fourth variant, `-DNO_WINDOW`,
; stays a compile-out — it is the non-vacuity CONTROL, and a control the code
; under test can write is not a control.

.p816
.smart

.define SF_HDR_TITLE "SPLIT V DEMO"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED (scroller's reasoning: one scene, and the
; feature files at top level resolve its symbols from file scope).
.include "engine_state_demo.inc"    ; GENERATED — the demo scene's map
.include "split_v_demo.inc"         ; controls + the rail's two tuning knobs
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI
; proper hands straight to the scene manager's core, which commits INIDISP
; and runs sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "input2.asm"
.include "oam_sprites.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37).
.segment "BANK1"
svd_stage_map_bin:
    .incbin "svd_stage_map.bin"
.assert ^svd_stage_map_bin = ES_R_SVD_STAGE_MAP_BANK, error, "svd_stage_map bank drifted from allocator claim"
.assert .loword(svd_stage_map_bin) = ES_R_SVD_STAGE_MAP_ADDR, error, "svd_stage_map addr drifted from allocator claim"
svd_diag_tab_bin:
    .incbin "svd_diag_tab.bin"
.assert ^svd_diag_tab_bin = ES_R_SVD_DIAG_TAB_BANK, error, "svd_diag_tab bank drifted from allocator claim"
.assert .loword(svd_diag_tab_bin) = ES_R_SVD_DIAG_TAB_ADDR, error, "svd_diag_tab addr drifted from allocator claim"
svd_stage_chr_bin:
    .incbin "svd_stage_chr.bin"
.assert ^svd_stage_chr_bin = ES_R_SVD_STAGE_CHR_BANK, error, "svd_stage_chr bank drifted from allocator claim"
.assert .loword(svd_stage_chr_bin) = ES_R_SVD_STAGE_CHR_ADDR, error, "svd_stage_chr addr drifted from allocator claim"
svd_obj_chr_bin:
    .incbin "svd_obj_chr.bin"
.assert ^svd_obj_chr_bin = ES_R_SVD_OBJ_CHR_BANK, error, "svd_obj_chr bank drifted from allocator claim"
.assert .loword(svd_obj_chr_bin) = ES_R_SVD_OBJ_CHR_ADDR, error, "svd_obj_chr addr drifted from allocator claim"
svd_obj_pal_bin:
    .incbin "svd_obj_pal.bin"
.assert ^svd_obj_pal_bin = ES_R_SVD_OBJ_PAL_BANK, error, "svd_obj_pal bank drifted from allocator claim"
.assert .loword(svd_obj_pal_bin) = ES_R_SVD_OBJ_PAL_ADDR, error, "svd_obj_pal addr drifted from allocator claim"
svd_stage_pal_bin:
    .incbin "svd_stage_pal.bin"
.assert ^svd_stage_pal_bin = ES_R_SVD_STAGE_PAL_BANK, error, "svd_stage_pal bank drifted from allocator claim"
.assert .loword(svd_stage_pal_bin) = ES_R_SVD_STAGE_PAL_ADDR, error, "svd_stage_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "svd_bg.asm"
.include "svd_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/demo.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; oam_nmi_dma commits the sprite shadow the tick staged; svd_nmi_commit
; publishes both cameras to BG1HOFS/BG2HOFS, rebuilds the straight seam table
; and applies the mode's window/channel state. The order is free — every
; writer here programs whatever it needs for itself, and neither touches the
; other's ports.
;
; The HDMA channel shadow svd_nmi_commit writes is MVN'd to $4300 by
; sm_nmi_core AFTER this hook returns, so a mode change made in this frame's
; hook is live for this frame's display.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    jsr svd_nmi_commit              ; cameras + seam + mode
    rts

; --- scene dispatch tables (manifest order: demo=0) ------------------------
sm_enter_tab:   .word demo::enter
sm_tick_tab:    .word demo::tick
sm_exit_tab:    .word demo::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr input2_init
    jsr fade_init
    jsr oam_park_all                ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = demo) under forced blank ------------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad -------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write:
    ; scene_mgr commits INIDISP in its NMI, so a direct write here would be
    ; overwritten on the first VBlank.
    ;
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate. Call it from A16
    ; and the CPU reads the following opcode byte as the immediate's high half
    ; — the ramp never arms and the ROM renders black with correct VRAM, CGRAM
    ; and OAM (rule 6's silent class through a CROSS-FILE contract, which
    ; width-lint cannot see; it cost split_v_fight a real debugging round).
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    .i16
    jsr input_read
    jsr input2_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
