; =============================================================================
; stomper — enemy resolution on top of jumper physics ("STOMP SQUAD")
; =============================================================================
; Two magenta patrollers pace fixed beats over a grey arena; landing on one
; from above defeats it (sprite culled, the player bounces ~17 px); any other
; contact knocks the player back to spawn. "FOES 00002" ticks down per stomp;
; both down prints CLEAR and the game keeps running.
;
; ONE SCENE, no scene machine beyond it — one RESET, one loop — so the dispatch
; tables have one entry each, there is no [[edge]], and `exit` is never called
; (hud_game's shape).
;
; NO AUDIO. Nothing queues music or SFX, so audio/tad_rom are absent from
; globals.
.p816
.smart

.define SF_HDR_TITLE "STOMP SQUAD"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "stomper.inc"              ; the rail's geometry + tuning
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
; ORDER IS NOT FREE: it must match the allocator's ROM packing — see
; build/st/allocation_report.txt. Each site .asserts its blob's linker
; bank/addr against the emitted symbols, so a reorder here (or a size change
; upstream) refuses the build rather than silently shifting every later blob.
; Window 1 = BANK1; this rail has no audio, so nothing reserves it first.
.segment "BANK1"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
st_world_bin:
    .incbin "st_world.bin"
.assert ^st_world_bin = ES_R_ST_WORLD_BANK, error, "st_world bank drifted from allocator claim"
.assert .loword(st_world_bin) = ES_R_ST_WORLD_ADDR, error, "st_world addr drifted from allocator claim"
st_flags_bin:
    .incbin "st_flags.bin"
.assert ^st_flags_bin = ES_R_ST_FLAGS_BANK, error, "st_flags bank drifted from allocator claim"
.assert .loword(st_flags_bin) = ES_R_ST_FLAGS_ADDR, error, "st_flags addr drifted from allocator claim"
st_bg_chr_bin:
    .incbin "st_bg_chr.bin"
.assert ^st_bg_chr_bin = ES_R_ST_BG_CHR_BANK, error, "st_bg_chr bank drifted from allocator claim"
.assert .loword(st_bg_chr_bin) = ES_R_ST_BG_CHR_ADDR, error, "st_bg_chr addr drifted from allocator claim"
st_obj_chr_bin:
    .incbin "st_obj_chr.bin"
.assert ^st_obj_chr_bin = ES_R_ST_OBJ_CHR_BANK, error, "st_obj_chr bank drifted from allocator claim"
.assert .loword(st_obj_chr_bin) = ES_R_ST_OBJ_CHR_ADDR, error, "st_obj_chr addr drifted from allocator claim"
st_obj_pal_bin:
    .incbin "st_obj_pal.bin"
.assert ^st_obj_pal_bin = ES_R_ST_OBJ_PAL_BANK, error, "st_obj_pal bank drifted from allocator claim"
.assert .loword(st_obj_pal_bin) = ES_R_ST_OBJ_PAL_ADDR, error, "st_obj_pal addr drifted from allocator claim"
st_bg_pal_bin:
    .incbin "st_bg_pal.bin"
.assert ^st_bg_pal_bin = ES_R_ST_BG_PAL_BANK, error, "st_bg_pal bank drifted from allocator claim"
.assert .loword(st_bg_pal_bin) = ES_R_ST_BG_PAL_ADDR, error, "st_bg_pal addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two writers, order free — each programs its own VMAIN/VMADD (AGENTS.md's
; established rule). stomper_bg has no per-frame commit: its scroll is pinned
; once at enter (the arena does not scroll).
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow the tick staged
    jsr text_vblank_commit      ; the FOES digit / CLEAR cell, if staged
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
    jsr fade_start_in           ; called in A8, deliberately — fade_start_in
                                ;   is .a8 and its `lda #1` is a one-byte
                                ;   immediate (the cross-file width contract
                                ;   scroller's main.asm documents)
    rep #$20
    .a16
@loop:
    .a16
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
