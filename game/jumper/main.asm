; =============================================================================
; jumper — jump physics ("SKY HOPPER")
; =============================================================================
; A red player with gravity: run left/right with the d-pad, jump with A. Solid
; ground along the bottom, three floating platforms at rising heights (each
; reachable from the one below), and a low overhang to bonk your head on.
;
; ONE SCENE, no edges. This rail has no scene machine — one RESET, one game
; loop. scene_mgr is composed for the INIDISP commit + frame sync;
; `sky` is its only destination.

.p816
.smart

.define SF_HDR_TITLE "SKY HOPPER"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED (one scene; the features resolve its
; symbols from file scope — scroller's reasoning, unchanged).
.include "engine_state_sky.inc"     ; GENERATED — the sky scene's map
.include "jumper.inc"               ; the rail's geometry + feel tuning
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at.
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
.include "tick_scale.asm"           ; TS_STEP: the macro sky.asm's tick uses.
                                    ; INCLUDED BEFORE THE SCENE, and it must
                                    ; be -- a ca65 macro has to be defined
                                    ; before the line that expands it, and the
                                    ; scene's region-scaled constants are built
                                    ; from TS_GAIN_NUM/TS_GAIN_DEN, which this
                                    ; file is the only source of.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim (drift direction); `make rom-unbacked` checks presence
; (docs/37). Order matches the packer's largest-first placement in window 1.
.segment "BANK1"
jr_world_bin:
    .incbin "jr_world.bin"
.assert ^jr_world_bin = ES_R_JR_WORLD_BANK, error, "jr_world bank drifted from allocator claim"
.assert .loword(jr_world_bin) = ES_R_JR_WORLD_ADDR, error, "jr_world addr drifted from allocator claim"
jr_flags_bin:
    .incbin "jr_flags.bin"
.assert ^jr_flags_bin = ES_R_JR_FLAGS_BANK, error, "jr_flags bank drifted from allocator claim"
.assert .loword(jr_flags_bin) = ES_R_JR_FLAGS_ADDR, error, "jr_flags addr drifted from allocator claim"
jr_bg_chr_bin:
    .incbin "jr_bg_chr.bin"
.assert ^jr_bg_chr_bin = ES_R_JR_BG_CHR_BANK, error, "jr_bg_chr bank drifted from allocator claim"
.assert .loword(jr_bg_chr_bin) = ES_R_JR_BG_CHR_ADDR, error, "jr_bg_chr addr drifted from allocator claim"
jr_obj_chr_bin:
    .incbin "jr_obj_chr.bin"
.assert ^jr_obj_chr_bin = ES_R_JR_OBJ_CHR_BANK, error, "jr_obj_chr bank drifted from allocator claim"
.assert .loword(jr_obj_chr_bin) = ES_R_JR_OBJ_CHR_ADDR, error, "jr_obj_chr addr drifted from allocator claim"
jr_bg_pal_bin:
    .incbin "jr_bg_pal.bin"
.assert ^jr_bg_pal_bin = ES_R_JR_BG_PAL_BANK, error, "jr_bg_pal bank drifted from allocator claim"
.assert .loword(jr_bg_pal_bin) = ES_R_JR_BG_PAL_ADDR, error, "jr_bg_pal addr drifted from allocator claim"
jr_obj_pal_bin:
    .incbin "jr_obj_pal.bin"
.assert ^jr_obj_pal_bin = ES_R_JR_OBJ_PAL_BANK, error, "jr_obj_pal bank drifted from allocator claim"
.assert .loword(jr_obj_pal_bin) = ES_R_JR_OBJ_PAL_ADDR, error, "jr_obj_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "jumper_bg.asm"
.include "jumper_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/sky.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE writer: oam_nmi_dma commits the sprite shadow the tick staged. There is
; no scroll commit — jumper_bg pins the latches once at enter and nothing
; ever changes them.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    rts

; --- scene dispatch tables (manifest order: sky=0) -------------------------
sm_enter_tab:   .word sky::enter
sm_tick_tab:    .word sky::tick
sm_exit_tab:    .word sky::exit

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
    ; ---- enter the boot scene (id 0 = sky) under forced blank -------------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad -------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write —
    ; scene_mgr commits INIDISP in its NMI. CALLED IN A8, DELIBERATELY:
    ; fade_start_in is `.a8` and its `lda #1` assembles one-byte; an A16
    ; caller would swallow the next opcode byte as the immediate's high half
    ; (the cross-file width contract width-lint cannot see — CLAUDE.md rule 6;
    ; scroller's main.asm carries the full account).
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
