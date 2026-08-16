; =============================================================================
; scroll_run — the page-seam world
; =============================================================================
; A 512px-wide level — two 256px BG pages on the hardware 64x32 tilemap — run
; and jump from the left edge to the gold goal pillar at the far right, over
; raised platforms and past solid pillars, with the camera following and
; clamping at both world edges. One platform straddles the page seam at world
; column 32. Reaching the goal prints GOAL on BG3 and freezes input — the
; compact demo of a world wider than one screen.
;
; ONE SCENE, no edges: one continuous run, mirroring scroller / hud_game /
; camera_follow / jumper. scene_mgr is composed for the INIDISP commit + frame
; sync; `run` is its only destination.

.p816
.smart

.define SF_HDR_TITLE "GOLD SPRINT"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED (scroller's reasoning: one scene, and the
; feature files at top level resolve its symbols from file scope).
.include "engine_state_run.inc"     ; GENERATED — the run scene's map
.include "scroll_run.inc"           ; the rail's geometry + feel tuning
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
.include "bg_text.asm"
.include "oam_sprites.asm"

; --- text_dp boot init (the text engine's global DP block) ------------------
text_dp_init:
    .a16
    .i16
    stz z:ES_TXT_PTR            ; bytes 0-1
    stz z:ES_TXT_TMP
    sep #$20
    .a8
    stz z:ES_TXT_PTR+2          ; bank byte alone — the claim is 3 B, and a
                                ; 16-bit store would stomp the neighbor claim
    rep #$20
    .a16
    stz z:ES_TXT_Q + 0          ; VBlank cell queue: dirty flag + count
    stz z:ES_TXT_Q + 2          ; ...staged VMADD
    stz z:ES_TXT_Q + 4          ; ...staged tile words (the run is re-staged
    stz z:ES_TXT_Q + 6          ;    per use; these four cover TXT_Q_MAX = 4)
    stz z:ES_TXT_Q + 8
    stz z:ES_TXT_Q + 10
    rts

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37).
.segment "BANK1"
sr_world_bin:
    .incbin "sr_world.bin"
.assert ^sr_world_bin = ES_R_SR_WORLD_BANK, error, "sr_world bank drifted from allocator claim"
.assert .loword(sr_world_bin) = ES_R_SR_WORLD_ADDR, error, "sr_world addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
sr_flags_bin:
    .incbin "sr_flags.bin"
.assert ^sr_flags_bin = ES_R_SR_FLAGS_BANK, error, "sr_flags bank drifted from allocator claim"
.assert .loword(sr_flags_bin) = ES_R_SR_FLAGS_ADDR, error, "sr_flags addr drifted from allocator claim"
sr_bg_chr_bin:
    .incbin "sr_bg_chr.bin"
.assert ^sr_bg_chr_bin = ES_R_SR_BG_CHR_BANK, error, "sr_bg_chr bank drifted from allocator claim"
.assert .loword(sr_bg_chr_bin) = ES_R_SR_BG_CHR_ADDR, error, "sr_bg_chr addr drifted from allocator claim"
sr_obj_chr_bin:
    .incbin "sr_obj_chr.bin"
.assert ^sr_obj_chr_bin = ES_R_SR_OBJ_CHR_BANK, error, "sr_obj_chr bank drifted from allocator claim"
.assert .loword(sr_obj_chr_bin) = ES_R_SR_OBJ_CHR_ADDR, error, "sr_obj_chr addr drifted from allocator claim"
sr_bg_pal_bin:
    .incbin "sr_bg_pal.bin"
.assert ^sr_bg_pal_bin = ES_R_SR_BG_PAL_BANK, error, "sr_bg_pal bank drifted from allocator claim"
.assert .loword(sr_bg_pal_bin) = ES_R_SR_BG_PAL_ADDR, error, "sr_bg_pal addr drifted from allocator claim"
sr_obj_pal_bin:
    .incbin "sr_obj_pal.bin"
.assert ^sr_obj_pal_bin = ES_R_SR_OBJ_PAL_BANK, error, "sr_obj_pal bank drifted from allocator claim"
.assert .loword(sr_obj_pal_bin) = ES_R_SR_OBJ_PAL_ADDR, error, "sr_obj_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "sr_bg.asm"
.include "sr_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/run.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Every writer programs its own VMADD where it needs one, so the order is
; free. oam_nmi_dma commits the sprite shadow the tick staged;
; sr_bg_nmi_commit publishes the follow camera to BG1HOFS/BG1VOFS;
; text_vblank_commit writes the GOAL run on the one frame the win staged it.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    jsr sr_bg_nmi_commit            ; the camera -> BG1HOFS/BG1VOFS
    jsr text_vblank_commit          ; the staged GOAL run, if any
    rts

; --- scene dispatch tables (manifest order: run=0) -------------------------
sm_enter_tab:   .word run::enter
sm_tick_tab:    .word run::tick
sm_exit_tab:    .word run::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr text_dp_init
    jsr oam_park_all                ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = run) under forced blank -------------
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
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and
    ; its `lda #1` therefore assembles as a ONE-byte immediate. Call it from
    ; A16 and the CPU reads the following opcode byte as the immediate's high
    ; half — the ramp never arms and the ROM renders black with correct VRAM,
    ; CGRAM and OAM (rule 6's silent class through a CROSS-FILE contract,
    ; which width-lint cannot see; it cost split_v_fight a real debugging
    ; round, and the comment is carried so it costs no one a second).
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
