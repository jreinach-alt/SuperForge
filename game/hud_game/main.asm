; =============================================================================
; hud_game — a movable sprite with a live text HUD. ROM skeleton.
; =============================================================================
; Every RAM/VRAM/CGRAM address, channel and register base comes from the
; allocator's emitted includes, and hardware I/O ports are the only literals
; (no_literals-gated).
;
; ONE SCENE. This rail has no title screen and no round that ends: it boots
; into the game and stays there. So the dispatch tables below have one entry
; each, there is no `[[edge]]`, and `exit` is never called. Everything else is
; the established main.asm shape.
;
; NO AUDIO. Nothing here queues music or SFX, so `audio`/`tad_rom` are absent
; from globals and there is no Tad_Init / Tad_Process.
.p816
.smart

.define SF_HDR_TITLE "SCORE CHASER"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "hud.inc"                  ; the rail's geometry + state vocabulary
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
.include "bg_text.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro play.asm's tick uses.
                                    ; INCLUDED BEFORE THE SCENE, and it must
                                    ; be — a ca65 macro has to be defined
                                    ; before the line that expands it.

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
; build/hud/allocation_report.txt. Each site .asserts its blob's linker
; bank/addr against the emitted symbols, so a reorder here (or a size change
; upstream) refuses the build rather than silently shifting every later blob.
; Window 1 = BANK1; this rail has no audio, so nothing reserves it first.
.segment "BANK1"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
hud_obj_chr_bin:
    .incbin "hud_obj_chr.bin"
.assert ^hud_obj_chr_bin = ES_R_HUD_OBJ_CHR_ROM_BANK, error, "hud_obj_chr bank drifted from allocator claim"
.assert .loword(hud_obj_chr_bin) = ES_R_HUD_OBJ_CHR_ROM_ADDR, error, "hud_obj_chr addr drifted from allocator claim"
hud_obj_pal_bin:
    .incbin "hud_obj_pal.bin"
.assert ^hud_obj_pal_bin = ES_R_HUD_OBJ_PAL_ROM_BANK, error, "hud_obj_pal bank drifted from allocator claim"
.assert .loword(hud_obj_pal_bin) = ES_R_HUD_OBJ_PAL_ROM_ADDR, error, "hud_obj_pal addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two writers, and the ORDER IS FREE because each programs its own VMAIN/VMADD
; (AGENTS.md's established rule — text_vblank_commit sets both itself, which is
; what makes the OAM DMA ahead of it unable to reach it). No scene test around
; either: this game has one scene, so both are unconditionally correct.
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
