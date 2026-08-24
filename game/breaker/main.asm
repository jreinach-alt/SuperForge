; =============================================================================
; breaker — the paddle-and-ball rail. ROM skeleton.
; =============================================================================
; Every RAM/VRAM/CGRAM address, channel and register base comes from the
; allocator's emitted includes, and hardware I/O ports are the only literals
; (no_literals-gated).
;
; Scene code lives in .scope <scene_id> blocks so same-named claims in
; different scenes stay distinct symbols (see engine_state_<scene>.inc).
.p816
.smart

.define SF_HDR_TITLE "BRICK BUSTER"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
.include "breaker.inc"              ; the rail's geometry + state vocabulary
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
.include "tick_scale.asm"           ; TS_STEP: the macro play.asm's update
                                    ; uses. INCLUDED BEFORE THE SCENES, and it
                                    ; must be — a ca65 macro has to be defined
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
    stz z:ES_TXT_Q + 4          ; ...staged tile word
    rts

; --- global ROM blobs -------------------------------------------------------
; ORDER IS NOT FREE: it must match the allocator's ROM packing — see
; build/brk/allocation_report.txt. Each site .asserts its blob's linker
; bank/addr against the emitted symbols, so a reorder here (or a size change
; upstream) refuses the build rather than silently shifting every later blob.
; These blobs live in BANK2 because window 1 is the tad_export whole-window
; claim (AUDIO_DATA0 — the generated export demands a bank start and the 32 KB
; claim guarantees it).
.segment "BANK2"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
brk_bg_chr_bin:
    .incbin "brk_bg_chr.bin"
.assert ^brk_bg_chr_bin = ES_R_BRK_BG_CHR_ROM_BANK, error, "brk_bg_chr bank drifted from allocator claim"
.assert .loword(brk_bg_chr_bin) = ES_R_BRK_BG_CHR_ROM_ADDR, error, "brk_bg_chr addr drifted from allocator claim"
brk_obj_chr_bin:
    .incbin "brk_obj_chr.bin"
.assert ^brk_obj_chr_bin = ES_R_BRK_OBJ_CHR_ROM_BANK, error, "brk_obj_chr bank drifted from allocator claim"
.assert .loword(brk_obj_chr_bin) = ES_R_BRK_OBJ_CHR_ROM_ADDR, error, "brk_obj_chr addr drifted from allocator claim"
brk_bg_pal_bin:
    .incbin "brk_bg_pal.bin"
.assert ^brk_bg_pal_bin = ES_R_BRK_BG_PAL_ROM_BANK, error, "brk_bg_pal bank drifted from allocator claim"
.assert .loword(brk_bg_pal_bin) = ES_R_BRK_BG_PAL_ROM_ADDR, error, "brk_bg_pal addr drifted from allocator claim"
brk_obj_pal_bin:
    .incbin "brk_obj_pal.bin"
.assert ^brk_obj_pal_bin = ES_R_BRK_OBJ_PAL_ROM_BANK, error, "brk_obj_pal bank drifted from allocator claim"
.assert .loword(brk_obj_pal_bin) = ES_R_BRK_OBJ_PAL_ROM_ADDR, error, "brk_obj_pal addr drifted from allocator claim"
brk_sky_chr_bin:
    .incbin "brk_sky_chr.bin"
.assert ^brk_sky_chr_bin = ES_R_BRK_SKY_CHR_ROM_BANK, error, "brk_sky_chr bank drifted from allocator claim"
.assert .loword(brk_sky_chr_bin) = ES_R_BRK_SKY_CHR_ROM_ADDR, error, "brk_sky_chr addr drifted from allocator claim"
brk_sky_pal_bin:
    .incbin "brk_sky_pal.bin"
.assert ^brk_sky_pal_bin = ES_R_BRK_SKY_PAL_ROM_BANK, error, "brk_sky_pal bank drifted from allocator claim"
.assert .loword(brk_sky_pal_bin) = ES_R_BRK_SKY_PAL_ROM_ADDR, error, "brk_sky_pal addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/title.asm"
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Every writer here programs its own VMAIN/VMADD, so the order is free
; (AGENTS.md's established rule, and the reason the OAM DMA ahead of them
; cannot reach them). play::brk_vblank_commit is scene-scoped and is called
; unconditionally: its own count byte is the guard, and every other scene
; leaves that byte at 0.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; every scene: commit the OAM shadow
    jsr text_vblank_commit      ; the HUD / message cell staged this frame
    jsr play::brk_vblank_commit ; the broken bricks staged this frame
    rts

; --- scene dispatch tables (manifest order: title=0, play=1) ----------------
sm_enter_tab:   .word title::enter, play::enter
sm_tick_tab:    .word title::tick,  play::tick
sm_exit_tab:    .word title::exit,  play::exit

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
    jsr play::brk_q_init        ; sm_nmi_hook commits this queue on EVERY
                                ; frame of EVERY scene, so its count byte
                                ; must be defined before the first NMI —
                                ; power-on WRAM is random (rule 5)
    ; ---- audio boot (TAD contract, tad-audio.inc): interrupts are DISABLED
    ; here by construction — init.inc leaves NMI off and $4200 is written only
    ; below — so the S-SMP is still in the IPL. Tad_Init runs ONCE per
    ; power-on; the song load is ASYNC and Tad_Process streams it during the
    ; title's frame loop.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- game-lifetime user state (power-on WRAM is random: this store IS
    ; the write-before-read contract, rule 5) -------------------------------
    lda #0
    sta f:US_ROUNDS_LONG
    ; ---- enter the boot scene (id 0 = title) under forced blank -----------
    ldx #0
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
    ; ---- audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids
    ; ISR calls).
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
