; =============================================================================
; camera_follow — the camera/world-space split
; =============================================================================
; A red player moved with the d-pad through a 512x448 world over a repeating
; checkerboard. The camera centres the player and scrolls BG1 to follow, but
; CLAMPS at the world edges — there the player walks toward the screen edge
; instead. A focused demo of the follow-camera primitive and of drawing an
; actor at world - camera.
;
; ONE SCENE, no edges. This rail has no scene machine at all — one RESET, one
; game loop — so a title screen would be surface its subject does not have.
; scene_mgr is composed anyway because it owns the INIDISP commit and the frame
; sync every rail's main loop is built on; `world` is simply its only
; destination.

.p816
.smart

.define SF_HDR_TITLE "OPEN RANGE"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. The generated header suggests wrapping it
; in `.scope <id>` for a multi-scene ROM so two scenes' symbols cannot
; collide; this rail has exactly one scene, and both cf_bg and cf_obj resolve
; its symbols from file scope, so a wrapper here would only hide them from the
; features that need them.
.include "engine_state_world.inc"   ; GENERATED — the world scene's map
.include "cf.inc"                   ; the rail's geometry + tuning
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI
; proper hands straight to the scene manager's core, which commits INIDISP and
; runs sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art.
.segment "BANK1"
cf_bg_chr_bin:
    .incbin "cf_bg_chr.bin"
.assert ^cf_bg_chr_bin = ES_R_CF_BG_CHR_BANK, error, "cf_bg_chr bank drifted from allocator claim"
.assert .loword(cf_bg_chr_bin) = ES_R_CF_BG_CHR_ADDR, error, "cf_bg_chr addr drifted from allocator claim"
cf_bg_pal_bin:
    .incbin "cf_bg_pal.bin"
.assert ^cf_bg_pal_bin = ES_R_CF_BG_PAL_BANK, error, "cf_bg_pal bank drifted from allocator claim"
.assert .loword(cf_bg_pal_bin) = ES_R_CF_BG_PAL_ADDR, error, "cf_bg_pal addr drifted from allocator claim"
cf_obj_chr_bin:
    .incbin "cf_obj_chr.bin"
.assert ^cf_obj_chr_bin = ES_R_CF_OBJ_CHR_BANK, error, "cf_obj_chr bank drifted from allocator claim"
.assert .loword(cf_obj_chr_bin) = ES_R_CF_OBJ_CHR_ADDR, error, "cf_obj_chr addr drifted from allocator claim"
cf_obj_pal_bin:
    .incbin "cf_obj_pal.bin"
.assert ^cf_obj_pal_bin = ES_R_CF_OBJ_PAL_BANK, error, "cf_obj_pal bank drifted from allocator claim"
.assert .loword(cf_obj_pal_bin) = ES_R_CF_OBJ_PAL_ADDR, error, "cf_obj_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "cf_bg.asm"
.include "cf_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/world.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Every writer programs its own VMADD where it needs one, so the order is
; free. oam_nmi_dma commits the sprite shadow the tick staged;
; cf_bg_nmi_commit publishes the follow camera to BG1HOFS/BG1VOFS.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    jsr cf_bg_nmi_commit            ; the camera -> BG1HOFS/BG1VOFS
    rts

; --- scene dispatch tables (manifest order: world=0) -----------------------
sm_enter_tab:   .word world::enter
sm_tick_tab:    .word world::tick
sm_exit_tab:    .word world::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all                ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = world) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
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
    ; half — the ramp never arms, INIDISP stays at brightness 0, and the ROM
    ; renders black with correct VRAM, CGRAM and OAM. That is rule 6's
    ; silent-corruption class arriving through a CROSS-FILE caller/callee
    ; contract, which width-lint cannot see in either direction (CLAUDE.md
    ; rule 6, "the single-file limit remains"). It cost split_v_fight a real
    ; debugging round; the comment is carried so it costs no one a second.
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
