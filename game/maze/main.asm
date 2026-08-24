; =============================================================================
; maze — col_map against a hand-built map
; =============================================================================
; A red 8x8 player walks a grey walled room — a border wall plus two interior
; walls, all one solid-flagged tile — with the canonical per-axis move-check:
; tentative position, probe, keep the axis only if clear, so a diagonal push
; into a wall SLIDES instead of sticking — the smallest complete demo of tile
; collision in the tree.
;
; ONE SCENE, no edges. This rail has no scene machine at all — one RESET, one
; game loop. scene_mgr is composed anyway because it owns the INIDISP commit
; and the frame sync every rail's main loop is built on; `room` is simply its
; only destination.

.p816
.smart

.define SF_HDR_TITLE "LABYRINTH"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED (scroller's reasoning: one scene, and the
; scene's features resolve its symbols from file scope).
.include "engine_state_room.inc"    ; GENERATED — the room scene's map
.include "maze.inc"                 ; the rail's geometry + tuning
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

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro the scene's tick uses.
                                    ; INCLUDED BEFORE THE SCENE, and it must
                                    ; be — a ca65 macro has to be defined
                                    ; before the line that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — or in mz_room's case, be PROBED as collision.
.segment "BANK1"
mz_room_bin:
    .incbin "mz_room.bin"
.assert ^mz_room_bin = ES_R_MZ_ROOM_BANK, error, "mz_room bank drifted from allocator claim"
.assert .loword(mz_room_bin) = ES_R_MZ_ROOM_ADDR, error, "mz_room addr drifted from allocator claim"
mz_flags_bin:
    .incbin "mz_flags.bin"
.assert ^mz_flags_bin = ES_R_MZ_FLAGS_BANK, error, "mz_flags bank drifted from allocator claim"
.assert .loword(mz_flags_bin) = ES_R_MZ_FLAGS_ADDR, error, "mz_flags addr drifted from allocator claim"
mz_bg_chr_bin:
    .incbin "mz_bg_chr.bin"
.assert ^mz_bg_chr_bin = ES_R_MZ_BG_CHR_BANK, error, "mz_bg_chr bank drifted from allocator claim"
.assert .loword(mz_bg_chr_bin) = ES_R_MZ_BG_CHR_ADDR, error, "mz_bg_chr addr drifted from allocator claim"
mz_bg_pal_bin:
    .incbin "mz_bg_pal.bin"
.assert ^mz_bg_pal_bin = ES_R_MZ_BG_PAL_BANK, error, "mz_bg_pal bank drifted from allocator claim"
.assert .loword(mz_bg_pal_bin) = ES_R_MZ_BG_PAL_ADDR, error, "mz_bg_pal addr drifted from allocator claim"
mz_obj_chr_bin:
    .incbin "mz_obj_chr.bin"
.assert ^mz_obj_chr_bin = ES_R_MZ_OBJ_CHR_BANK, error, "mz_obj_chr bank drifted from allocator claim"
.assert .loword(mz_obj_chr_bin) = ES_R_MZ_OBJ_CHR_ADDR, error, "mz_obj_chr addr drifted from allocator claim"
mz_obj_pal_bin:
    .incbin "mz_obj_pal.bin"
.assert ^mz_obj_pal_bin = ES_R_MZ_OBJ_PAL_BANK, error, "mz_obj_pal bank drifted from allocator claim"
.assert .loword(mz_obj_pal_bin) = ES_R_MZ_OBJ_PAL_ADDR, error, "mz_obj_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "maze_bg.asm"

; --- the scene (binds col_map's world + maze_obj's position, then .scope) --
.include "scenes/room.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; One writer: oam_nmi_dma commits the sprite shadow the tick staged. The
; scroll is pinned at enter (maze_bg — the room does not scroll), so there is
; no per-frame BG commit on this rail.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    rts

; --- scene dispatch tables (manifest order: room=0) -----------------------
sm_enter_tab:   .word room::enter
sm_tick_tab:    .word room::tick
sm_exit_tab:    .word room::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr region_init                 ; the console's own region line, once. It
                                    ;   is game-lifetime state: a console does
                                    ;   not change region between scenes.
    jsr oam_park_all                ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = room) under forced blank -----------
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
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate — call it from A16
    ; and the CPU eats the next opcode byte as the immediate's high half, the
    ; ramp never arms, and the ROM renders black with correct VRAM/CGRAM/OAM.
    ; Rule 6's silent-corruption class through a CROSS-FILE caller/callee
    ; contract width-lint cannot see (CLAUDE.md rule 6); the comment is
    ; carried so it costs no one a second debugging round.
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
