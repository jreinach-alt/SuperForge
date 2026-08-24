; =============================================================================
; sprite_game — the OBJ-only catch game ("DOT CHASER"). ROM skeleton.
; =============================================================================
; NOTHING HERE IS HAND-PLACED: every RAM/VRAM/CGRAM address, channel and
; register base comes from the allocator's emitted includes, and hardware I/O
; ports are the only literals (no_literals-gated).
;
; THE OAM_SPRITES ISOLATION TEST. This rail composes NO BG feature, no bg_text,
; no text_dp, no font_rom, and never touches a background: the picture is two
; 8x8 sprites over the backdrop colour and the score is a DP word with no HUD.
; So this main.asm is the tree's minimal OBJ composition: scene_mgr + input +
; fade + oam_sprites + one blob, one scene.
;
; ONE SCENE, NO AUDIO — the ROM boots into the chase and stays there, and
; queues no music and no SFX.
.p816
.smart

.define SF_HDR_TITLE "DOT CHASER"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "sprg.inc"                 ; the rail's geometry + vocabulary
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine feature runtimes (shared code, global symbols only) -------------
.include "scene_mgr.asm"
.include "input.asm"
.include "fade.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro play.asm's tick uses.
                                    ; INCLUDED BEFORE THE SCENE, and it must
                                    ; be — a ca65 macro has to be defined
                                    ; before the line that expands it.

; --- global ROM blobs -------------------------------------------------------
; ORDER IS NOT FREE: it must match the allocator's ROM packing (largest
; first) — see build/sprg/allocation_report.txt: pal (64 B) at $8000, then
; chr (32 B) at $8040. Each site .asserts its blob's linker bank/addr against
; the emitted symbols, so a reorder here (or a size change upstream) refuses
; the build rather than silently shifting every later blob. Window 1 = BANK1;
; this rail has no audio, so nothing reserves it first.
.segment "BANK1"
sprg_obj_pal_bin:
    .incbin "sprg_obj_pal.bin"
.assert ^sprg_obj_pal_bin = ES_R_SPRG_OBJ_PAL_ROM_BANK, error, "sprg_obj_pal bank drifted from allocator claim"
.assert .loword(sprg_obj_pal_bin) = ES_R_SPRG_OBJ_PAL_ROM_ADDR, error, "sprg_obj_pal addr drifted from allocator claim"
sprg_obj_chr_bin:
    .incbin "sprg_obj_chr.bin"
.assert ^sprg_obj_chr_bin = ES_R_SPRG_OBJ_CHR_ROM_BANK, error, "sprg_obj_chr bank drifted from allocator claim"
.assert .loword(sprg_obj_chr_bin) = ES_R_SPRG_OBJ_CHR_ROM_ADDR, error, "sprg_obj_chr addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE writer: the OAM shadow's declared GP-DMA. Nothing else in this game
; touches VRAM or CGRAM after enter — there is no text queue, no stream, no
; palette cycle. This is the smallest sm_nmi_hook in the tree, and that is
; the rail's composition statement, not an omission.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    rts

; --- scene dispatch tables (manifest order: play=0) -------------------------
sm_enter_tab:   .word play::enter
sm_tick_tab:    .word play::tick
sm_exit_tab:    .word play::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = play) under forced blank ------------
    ldx #(SCENE_PLAY * 2)
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad, fade in from black -----------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
