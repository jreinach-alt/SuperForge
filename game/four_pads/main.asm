; =============================================================================
; four_pads — four players on four pads (docs/102). ROM skeleton.
; =============================================================================
; NOTHING HERE IS HAND-PLACED: every RAM/VRAM/CGRAM address, channel and
; register base comes from the allocator's emitted includes, and hardware I/O
; ports are the only literals (no_literals-gated). Forked from sprite_game's
; skeleton: the OBJ-only composition, minus audio, plus the input stack.
.p816
.smart

.define SF_HDR_TITLE "FOUR PADS"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED from the linker config (vendor/rom/header.inc).
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "fp.inc"                   ; the rail's geometry + vocabulary
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
.include "input2.asm"
.include "mtap.asm"
.include "fade.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP — defined before the scene that
                                    ;   expands it (a ca65 macro must be)

; --- global ROM blobs -------------------------------------------------------
; ORDER IS NOT FREE: it must match the allocator's ROM packing (largest
; first) — build/fp/allocation_report.txt: pal (128 B) then chr (96 B). Each
; site .asserts its blob's bank/addr against the emitted symbols, so a reorder
; refuses the build rather than shifting every later blob.
.segment "BANK1"
fp_obj_pal_bin:
    .incbin "fp_obj_pal.bin"
.assert ^fp_obj_pal_bin = ES_R_FP_OBJ_PAL_ROM_BANK, error, "fp_obj_pal bank drifted from allocator claim"
.assert .loword(fp_obj_pal_bin) = ES_R_FP_OBJ_PAL_ROM_ADDR, error, "fp_obj_pal addr drifted from allocator claim"
fp_obj_chr_bin:
    .incbin "fp_obj_chr.bin"
.assert ^fp_obj_chr_bin = ES_R_FP_OBJ_CHR_ROM_BANK, error, "fp_obj_chr bank drifted from allocator claim"
.assert .loword(fp_obj_chr_bin) = ES_R_FP_OBJ_CHR_ROM_ADDR, error, "fp_obj_chr addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
; ONE writer: the OAM shadow's declared GP-DMA.
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
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off — and the
; automatic joypad read OFF, which is mtap_init's precondition (detection
; clocks port 2 by hand). It therefore runs BEFORE $4200 is armed below.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr input2_init
    jsr mtap_init               ; + detects the adapter (auto-read still off)
    jsr fade_init
    jsr region_init             ; the console's own region line, once
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
fp_main_loop:
    .a16
    jsr input_read              ; P1
    jsr input2_read             ; P2 (port 2's pad, or the adapter's slot 1)
fp_pads_begin:                  ; the cost measurement's two marks (labelled
    jsr mtap_read               ;   twin, tests/test_mtap_cost.py): P3 + P4
fp_pads_end:
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra fp_main_loop
