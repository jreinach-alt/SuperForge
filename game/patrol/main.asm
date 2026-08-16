; =============================================================================
; patrol — dodge patrolling enemies. ROM skeleton.
; =============================================================================
; The composition reference: sprites, BG terrain, text HUD, tile collision,
; jump physics, and enemy patrol, all in one game loop. Every address, channel
; and register base comes from the allocator's emitted includes.
;
; ONE SCENE (no scene machine), NO AUDIO (nothing queues music or SFX) —
; hud_game's and scroller's established shapes for both.
.p816
.smart

.define SF_HDR_TITLE "NIGHT PATROL"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "patrol.inc"               ; the rail's geometry + state vocabulary
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine feature runtimes (shared code, global symbols only) -------------
.include "scene_mgr.asm"
.include "input.asm"
.include "fade.asm"
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

; --- global ROM blobs -------------------------------------------------------
; ORDER IS NOT FREE: it must match the allocator's ROM packing (largest-first
; from window 1) — see build/pat/allocation_report.txt. Each site .asserts its
; blob's linker bank/addr against the emitted symbols, so a reorder here (or a
; size change upstream) refuses the build rather than silently shifting every
; later blob. Window 1 = BANK1; this rail has no audio, so nothing reserves it
; first.
.segment "BANK1"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
pat_map_bin:
    .incbin "pat_map.bin"
.assert ^pat_map_bin = ES_R_PAT_MAP_BANK, error, "pat_map bank drifted from allocator claim"
.assert .loword(pat_map_bin) = ES_R_PAT_MAP_ADDR, error, "pat_map addr drifted from allocator claim"
pat_flags_bin:
    .incbin "pat_flags.bin"
.assert ^pat_flags_bin = ES_R_PAT_FLAGS_BANK, error, "pat_flags bank drifted from allocator claim"
.assert .loword(pat_flags_bin) = ES_R_PAT_FLAGS_ADDR, error, "pat_flags addr drifted from allocator claim"
pat_bg_chr_bin:
    .incbin "pat_bg_chr.bin"
.assert ^pat_bg_chr_bin = ES_R_PAT_BG_CHR_BANK, error, "pat_bg_chr bank drifted from allocator claim"
.assert .loword(pat_bg_chr_bin) = ES_R_PAT_BG_CHR_ADDR, error, "pat_bg_chr addr drifted from allocator claim"
pat_obj_pal_bin:
    .incbin "pat_obj_pal.bin"
.assert ^pat_obj_pal_bin = ES_R_PAT_OBJ_PAL_BANK, error, "pat_obj_pal bank drifted from allocator claim"
.assert .loword(pat_obj_pal_bin) = ES_R_PAT_OBJ_PAL_ADDR, error, "pat_obj_pal addr drifted from allocator claim"
pat_bg_pal_bin:
    .incbin "pat_bg_pal.bin"
.assert ^pat_bg_pal_bin = ES_R_PAT_BG_PAL_BANK, error, "pat_bg_pal bank drifted from allocator claim"
.assert .loword(pat_bg_pal_bin) = ES_R_PAT_BG_PAL_ADDR, error, "pat_bg_pal addr drifted from allocator claim"
pat_obj_chr_bin:
    .incbin "pat_obj_chr.bin"
.assert ^pat_obj_chr_bin = ES_R_PAT_OBJ_CHR_BANK, error, "pat_obj_chr bank drifted from allocator claim"
.assert .loword(pat_obj_chr_bin) = ES_R_PAT_OBJ_CHR_ADDR, error, "pat_obj_chr addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two writers, and the ORDER IS FREE because each programs its own
; VMAIN/VMADD (AGENTS.md's established rule). No BG scroll commit on this
; rail: patrol_bg pins BG1HOFS/BG1VOFS once at enter (the level is one screen
; and never scrolls — maze's shape).
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr text_vblank_commit      ; the counter cells staged this frame, if any
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
    jsr text_dp_init
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
