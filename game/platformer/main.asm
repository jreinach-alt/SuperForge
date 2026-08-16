; =============================================================================
; platformer — the flagship rail. ROM skeleton.
; =============================================================================
; Every RAM/VRAM/CGRAM address, channel and register base comes from the
; allocator's emitted includes, and hardware I/O ports are the only literals
; (no_literals-gated).
;
; Scene code lives in .scope <scene_id> blocks so same-named claims in
; different scenes stay distinct symbols (see engine_state_<scene>.inc).
.p816
.smart

.define SF_HDR_TITLE "SUPER KIT QUEST"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
.include "platformer.inc"           ; the rail's geometry + state vocabulary
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
.include "save.asm"

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
; build/plf/allocation_report.txt. Each site .asserts its blob's linker
; bank/addr against the emitted symbols, so a reorder here (or a size change
; upstream) refuses the build rather than silently shifting every later blob.
; These blobs live in BANK2 because window 1 is the tad_export whole-window
; claim (the generated export demands a bank start and the 32 KB claim
; guarantees it).
.segment "BANK2"
plf_level_bin:
    .incbin "plf_level.bin"
.assert ^plf_level_bin = ES_R_PLF_LEVEL_ROM_BANK, error, "plf_level bank drifted from allocator claim"
.assert .loword(plf_level_bin) = ES_R_PLF_LEVEL_ROM_ADDR, error, "plf_level addr drifted from allocator claim"
plf_obj_chr_bin:
    .incbin "plf_obj_chr.bin"
.assert ^plf_obj_chr_bin = ES_R_PLF_OBJ_CHR_ROM_BANK, error, "plf_obj_chr bank drifted from allocator claim"
.assert .loword(plf_obj_chr_bin) = ES_R_PLF_OBJ_CHR_ROM_ADDR, error, "plf_obj_chr addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
crc16_lut_bin:
    .incbin "crc16_lut.bin"
.assert ^crc16_lut_bin = ES_R_CRC16_LUT_ROM_BANK, error, "crc16_lut_bin bank drifted from allocator claim"
.assert .loword(crc16_lut_bin) = ES_R_CRC16_LUT_ROM_ADDR, error, "crc16_lut_bin addr drifted from allocator claim"
plf_bg_chr_bin:
    .incbin "plf_bg_chr.bin"
.assert ^plf_bg_chr_bin = ES_R_PLF_BG_CHR_ROM_BANK, error, "plf_bg_chr bank drifted from allocator claim"
.assert .loword(plf_bg_chr_bin) = ES_R_PLF_BG_CHR_ROM_ADDR, error, "plf_bg_chr addr drifted from allocator claim"
plf_sky_bin:
    .incbin "plf_sky.bin"
.assert ^plf_sky_bin = ES_R_PLF_SKY_ROM_BANK, error, "plf_sky bank drifted from allocator claim"
.assert .loword(plf_sky_bin) = ES_R_PLF_SKY_ROM_ADDR, error, "plf_sky addr drifted from allocator claim"
plf_bg_pal_bin:
    .incbin "plf_bg_pal.bin"
.assert ^plf_bg_pal_bin = ES_R_PLF_BG_PAL_ROM_BANK, error, "plf_bg_pal bank drifted from allocator claim"
.assert .loword(plf_bg_pal_bin) = ES_R_PLF_BG_PAL_ROM_ADDR, error, "plf_bg_pal addr drifted from allocator claim"
plf_ghost_pal_bin:
    .incbin "plf_ghost_pal.bin"
.assert ^plf_ghost_pal_bin = ES_R_PLF_GHOST_PAL_ROM_BANK, error, "plf_ghost_pal bank drifted from allocator claim"
.assert .loword(plf_ghost_pal_bin) = ES_R_PLF_GHOST_PAL_ROM_ADDR, error, "plf_ghost_pal addr drifted from allocator claim"
plf_hero_pal_bin:
    .incbin "plf_hero_pal.bin"
.assert ^plf_hero_pal_bin = ES_R_PLF_HERO_PAL_ROM_BANK, error, "plf_hero_pal bank drifted from allocator claim"
.assert .loword(plf_hero_pal_bin) = ES_R_PLF_HERO_PAL_ROM_ADDR, error, "plf_hero_pal addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/title.asm"
.include "scenes/play.asm"
.include "scenes/over.asm"
.include "scenes/win.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Every writer here programs its own VMAIN/VMADD, so the order is free
; (AGENTS.md's established rule, and the reason the OAM DMA ahead of them
; cannot reach them).
;
; TWO OF THE FOUR ARE UNCONDITIONAL and two are gated on the scene.
; `text_vblank_commit` and the coin queue
; each carry their own count byte, whose empty state (0) is a legitimate value
; and whose init is a boot-time write — so calling them in a menu is a no-op by
; construction. The camera commit and the parallax rebuild are different: BG1's
; and BG2's scroll registers belong to the play scene alone, and a menu (which
; runs BG3 by itself and owns no BG1/BG2 register) must not have one written
; under it. scene_mgr sets `cur = next` BEFORE calling enter and holds NMI
; masked across the whole switch (`@switch`, exit through enter), so the first NMI that
; sees SCENE_PLAY is the first one after play::enter armed the camera shadow.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; every scene: commit the OAM shadow
    jsr text_vblank_commit      ; the HUD / banner cell staged this frame
    jsr play::plf_vblank_queue  ; a collected coin's tilemap cell
    lda z:ES_SM_CTL             ; cur scene id
    cmp #SCENE_PLAY
    bne @done
    jsr play::plf_vblank        ; BG1HOFS, and the two sky bands' HOFS table
@done:
    .a8
    .i16
    rts

; --- scene dispatch tables (manifest order: title=0 play=1 over=2 win=3) ----
sm_enter_tab:   .word title::enter, play::enter, over::enter, win::enter
sm_tick_tab:    .word title::tick,  play::tick,  over::tick,  win::tick
sm_exit_tab:    .word title::exit,  play::exit,  over::exit,  win::exit

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
    jsr play::plf_q_init        ; the coin queue's count byte — its VBlank
                                ;   reader runs in EVERY scene, so this is the
                                ;   write-before-read contract for it
    jsr oam_park_all            ; whole shadow written before its first DMA
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
    ; ---- game-lifetime user state (power-on WRAM is random: these stores ARE
    ; the write-before-read contract, rule 5) -------------------------------
    lda #0
    sta f:US_RUNS_LONG
    sta f:US_BANK_LONG
    sta f:US_CONTOK_LONG
    sta f:US_CONTPEND_LONG
    ; ---- enter the boot scene (id 0 = title) under forced blank -----------
    ldx #(SCENE_TITLE * 2)
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
