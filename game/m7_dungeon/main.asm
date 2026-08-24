; =============================================================================
; m7_dungeon — the rotating Mode 7 dungeon floor
; =============================================================================
; A top-down dungeon crawler with TANK CONTROLS: the hero's facing always reads
; "up" because the hero never moves — he is pinned at the affine pivot, and the
; FLOOR rotates and scrolls underneath. Three slimes pace the corridors, glued
; to their world tiles through the matrix's transpose; walls block in world
; space, not on the rotated picture; the goal cell raises a banner.
;
; Built in three slices over one scene: the plane, then the cast on it, then the
; game.
;
; ONE SCENE, no edges, mirroring split_v_fight's shape (game.toml's header
; carries the reasoning, including the four features deliberately NOT composed
; and which allocator check would have refused each of them anyway).
;
; NO AUDIO. `tad_rom` is not in this game's globals, so there is no Tad_Init,
; no Tad_Process pump and no TAD object in the link — the rail's subject is the
; picture. Adding audio is a claim in game.toml plus the two calls, not a
; rework.

.p816
.smart

.define SF_HDR_TITLE "M7 DUNGEON"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
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

; --- engine features (the GLOBAL half of the composition game.toml declares) -
; m7_affine is global because later rails reuse it; m7dg_floor is scene-scoped
; and is therefore included inside `.scope dungeon`, next to the scene map whose
; symbols it reads.
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro the dungeon tick counts
                                    ;   its heading and patrol steps with.
                                    ;   INCLUDED BEFORE THE SCENE — a ca65
                                    ;   macro must be defined before the line
                                    ;   that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art.
;
; m7dg_map is 32,768 B — one WHOLE LoROM window — so it gets bank 1 to itself
; and the single DMA that uploads it cannot cross a bank boundary.
.segment "BANK1"
m7dg_map_bin:
    .incbin "m7dg_map.bin"
.assert ^m7dg_map_bin = ES_R_M7DG_MAP_BANK, error, "m7dg_map bank drifted from allocator claim"
.assert .loword(m7dg_map_bin) = ES_R_M7DG_MAP_ADDR, error, "m7dg_map addr drifted from allocator claim"

.segment "BANK2"
; The PACKED tile-id map col_map reads, and the tile-id -> flag table it
; indexes with what it finds. TWO blobs, because they are two different
; lookups: the map answers "which tile is at this world pixel", the table
; answers "is that tile solid". Neither is the interleaved plane above — that
; probe's `ty * W + tx` cannot index (m7dg_rom's feature.toml carries the full
; correction, including what the separate map costs in bytes).
;
; The map leads BANK2 because the allocator packs ROM by (-bytes, name) and at
; 16,384 B it is the largest claim in this window. The .asserts are what make
; that agreement checkable rather than assumed.
m7dg_tilemap_bin:
    .incbin "m7dg_tilemap.bin"
.assert ^m7dg_tilemap_bin = ES_R_M7DG_TILEMAP_BANK, error, "m7dg_tilemap bank drifted from allocator claim"
.assert .loword(m7dg_tilemap_bin) = ES_R_M7DG_TILEMAP_ADDR, error, "m7dg_tilemap addr drifted from allocator claim"
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
; The OBJ sheets and their palettes. The ORDER here is the allocator's, not a
; preference: place_rom packs by (-bytes, name), so the three 576 B sheets sort
; ahead of the three 32 B palettes and each group sorts alphabetically. The
; .asserts below are what makes that agreement checkable rather than assumed —
; a re-sort moves an address and the build stops with the claim named.
m7dg_enemy_chr_bin:
    .incbin "m7dg_enemy_chr.bin"
.assert ^m7dg_enemy_chr_bin = ES_R_M7DG_ENEMY_CHR_BANK, error, "m7dg_enemy_chr bank drifted from allocator claim"
.assert .loword(m7dg_enemy_chr_bin) = ES_R_M7DG_ENEMY_CHR_ADDR, error, "m7dg_enemy_chr addr drifted from allocator claim"
m7dg_hero_chr_bin:
    .incbin "m7dg_hero_chr.bin"
.assert ^m7dg_hero_chr_bin = ES_R_M7DG_HERO_CHR_BANK, error, "m7dg_hero_chr bank drifted from allocator claim"
.assert .loword(m7dg_hero_chr_bin) = ES_R_M7DG_HERO_CHR_ADDR, error, "m7dg_hero_chr addr drifted from allocator claim"
m7dg_win_chr_bin:
    .incbin "m7dg_win_chr.bin"
.assert ^m7dg_win_chr_bin = ES_R_M7DG_WIN_CHR_BANK, error, "m7dg_win_chr bank drifted from allocator claim"
.assert .loword(m7dg_win_chr_bin) = ES_R_M7DG_WIN_CHR_ADDR, error, "m7dg_win_chr addr drifted from allocator claim"
m7dg_flags_bin:
    .incbin "m7dg_flags.bin"
.assert ^m7dg_flags_bin = ES_R_M7DG_FLAGS_BANK, error, "m7dg_flags bank drifted from allocator claim"
.assert .loword(m7dg_flags_bin) = ES_R_M7DG_FLAGS_ADDR, error, "m7dg_flags addr drifted from allocator claim"
m7dg_enemy_pal_bin:
    .incbin "m7dg_enemy_pal.bin"
.assert ^m7dg_enemy_pal_bin = ES_R_M7DG_ENEMY_PAL_BANK, error, "m7dg_enemy_pal bank drifted from allocator claim"
.assert .loword(m7dg_enemy_pal_bin) = ES_R_M7DG_ENEMY_PAL_ADDR, error, "m7dg_enemy_pal addr drifted from allocator claim"
m7dg_hero_pal_bin:
    .incbin "m7dg_hero_pal.bin"
.assert ^m7dg_hero_pal_bin = ES_R_M7DG_HERO_PAL_BANK, error, "m7dg_hero_pal bank drifted from allocator claim"
.assert .loword(m7dg_hero_pal_bin) = ES_R_M7DG_HERO_PAL_ADDR, error, "m7dg_hero_pal addr drifted from allocator claim"
m7dg_win_pal_bin:
    .incbin "m7dg_win_pal.bin"
.assert ^m7dg_win_pal_bin = ES_R_M7DG_WIN_PAL_BANK, error, "m7dg_win_pal bank drifted from allocator claim"
.assert .loword(m7dg_win_pal_bin) = ES_R_M7DG_WIN_PAL_ADDR, error, "m7dg_win_pal addr drifted from allocator claim"
m7dg_pal_bin:
    .incbin "m7dg_pal.bin"
.assert ^m7dg_pal_bin = ES_R_M7DG_PAL_BANK, error, "m7dg_pal bank drifted from allocator claim"
.assert .loword(m7dg_pal_bin) = ES_R_M7DG_PAL_ADDR, error, "m7dg_pal addr drifted from allocator claim"
.segment "CODE"

; --- m7_affine (after the LUT blob its lookup reads) -----------------------
.include "m7_affine.asm"

; --- m7_project (world -> screen; reads m7_affine's shadow, so it follows it)
; Included at FILE scope and before the scene, which is what lets the scene's
; own feature alias its constants at assemble time rather than deferring them.
.include "m7_project.asm"

; --- the scene (carries its own map + its scene-scoped feature) ------------
.include "scenes/dungeon.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two commits, no ordering constraint between them: oam_nmi_dma pushes the
; sprite shadow the scene's tick has just rebuilt, and m7a_nmi_commit latches
; all eight Mode 7 registers together so the matrix cannot tear mid-frame.
;
; They ARE the same frame's answer, though, and that is the tick's doing: the
; sprites were projected through the very matrix this hook is about to commit
; (scenes/dungeon.asm's tick sets the heading before it draws), so a sprite and
; the floor tile it stands on are never one frame apart.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr m7a_nmi_commit          ; the eight Mode 7 ports, from the DP shadow
    rts

; --- scene dispatch tables (manifest order: dungeon=0) ---------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word dungeon::enter
sm_tick_tab:    .word dungeon::tick
sm_exit_tab:    .word dungeon::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = dungeon) under forced blank --------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
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
