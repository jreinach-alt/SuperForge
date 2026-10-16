; =============================================================================
; brawler — the second OBJ name table
; =============================================================================
; "IRON KNIGHTS" — Arthur Pendragon versus Mordred: two animated multi-frame 32x32
; knights on a terrain floor with an HP / FOE / WINS text HUD. Move four-way in
; a shallow lane band, face your travel direction (OAM H-flip), swing a sword;
; Mordred walks toward you and hits back. Three landed swings bank a win and
; respawn him; losing all HP freezes on GAME OVER.
;
; ONE SCENE. This rail has no scene machine — one RESET, one game loop — so
; the dispatch tables have one entry each, there is no [[edge]], and `exit` is
; never called (hud_game's shape).
;
; NO AUDIO. Nothing here queues music or SFX, so audio/tad_rom are absent from
; globals.
.p816
.smart

.define SF_HDR_TITLE "IRON KNIGHTS"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "brawler.inc"              ; the rail's geometry + tuning
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.import sf_sfx_reset, sf_sfx_queue_c, sf_audio_tick
                                    ; engine/features/audio — the request
                                    ;   queue and the per-frame pump
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
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
.include "tick_scale.asm"           ; TS_STEP: the macro fight.asm's tick uses.
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
; build/br/allocation_report.txt. Each site .asserts its blob's linker
; bank/addr against the emitted symbols, so a reorder here (or a size change
; upstream) refuses the build rather than silently shifting every later blob.
; Window 1 = BANK1; this rail has no audio, so nothing reserves it first.
; THIS RAIL SPANS TWO WINDOWS NOW, and `audio` is why. The composition's rom
; claims came to 17,682 B before it — one window with room to spare. tad_rom's
; 16,384 B half-window takes the total to 34,066, so the allocator packs
; largest-first into window 1 until it is full and spills the SMALLEST blob,
; the font, into window 2. The link refused the build until the source said so
; (`font_bin bank drifted from allocator claim`), which is the .incbin asserts
; doing their job: the allocator's arithmetic and ld65's placement have to
; agree by name, not by luck.
.segment "BANK2"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"

.segment "BANK1"
br_art_chr_bin:
    .incbin "br_art_chr.bin"
.assert ^br_art_chr_bin = ES_R_BR_ART_CHR_BANK, error, "br_art_chr bank drifted from allocator claim"
.assert .loword(br_art_chr_bin) = ES_R_BR_ART_CHR_ADDR, error, "br_art_chr addr drifted from allocator claim"
br_mor_chr_bin:
    .incbin "br_mor_chr.bin"
.assert ^br_mor_chr_bin = ES_R_BR_MOR_CHR_BANK, error, "br_mor_chr bank drifted from allocator claim"
.assert .loword(br_mor_chr_bin) = ES_R_BR_MOR_CHR_ADDR, error, "br_mor_chr addr drifted from allocator claim"
br_bg_chr_bin:
    .incbin "br_bg_chr.bin"
.assert ^br_bg_chr_bin = ES_R_BR_BG_CHR_BANK, error, "br_bg_chr bank drifted from allocator claim"
.assert .loword(br_bg_chr_bin) = ES_R_BR_BG_CHR_ADDR, error, "br_bg_chr addr drifted from allocator claim"
br_bg_map_bin:
    .incbin "br_bg_map.bin"
.assert ^br_bg_map_bin = ES_R_BR_BG_MAP_BANK, error, "br_bg_map bank drifted from allocator claim"
.assert .loword(br_bg_map_bin) = ES_R_BR_BG_MAP_ADDR, error, "br_bg_map addr drifted from allocator claim"
br_anim_bin:
    .incbin "br_anim.bin"
.assert ^br_anim_bin = ES_R_BR_ANIM_BANK, error, "br_anim bank drifted from allocator claim"
.assert .loword(br_anim_bin) = ES_R_BR_ANIM_ADDR, error, "br_anim addr drifted from allocator claim"
br_art_pal_bin:
    .incbin "br_art_pal.bin"
.assert ^br_art_pal_bin = ES_R_BR_ART_PAL_BANK, error, "br_art_pal bank drifted from allocator claim"
.assert .loword(br_art_pal_bin) = ES_R_BR_ART_PAL_ADDR, error, "br_art_pal addr drifted from allocator claim"
br_bg_pal_bin:
    .incbin "br_bg_pal.bin"
.assert ^br_bg_pal_bin = ES_R_BR_BG_PAL_BANK, error, "br_bg_pal bank drifted from allocator claim"
.assert .loword(br_bg_pal_bin) = ES_R_BR_BG_PAL_ADDR, error, "br_bg_pal addr drifted from allocator claim"
br_mor_pal_bin:
    .incbin "br_mor_pal.bin"
.assert ^br_mor_pal_bin = ES_R_BR_MOR_PAL_BANK, error, "br_mor_pal bank drifted from allocator claim"
.assert .loword(br_mor_pal_bin) = ES_R_BR_MOR_PAL_ADDR, error, "br_mor_pal addr drifted from allocator claim"
br_anim_meta_bin:
    .incbin "br_anim_meta.bin"
.assert ^br_anim_meta_bin = ES_R_BR_ANIM_META_BANK, error, "br_anim_meta bank drifted from allocator claim"
.assert .loword(br_anim_meta_bin) = ES_R_BR_ANIM_META_ADDR, error, "br_anim_meta addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/fight.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two writers, order free — each programs its own VMAIN/VMADD (AGENTS.md's
; established rule). brawler_bg has no per-frame commit: its scroll is pinned
; once at enter (the arena does not scroll).
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow the tick staged
    jsr text_vblank_commit      ; one HUD counter run, or one GAME OVER cell
    rts

; --- scene dispatch tables (manifest order: fight=0) ------------------------
sm_enter_tab:   .word fight::enter
sm_tick_tab:    .word fight::tick
sm_exit_tab:    .word fight::exit

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
    ; ---- audio boot (TAD contract, tad-audio.inc): interrupts are DISABLED
    ; here by construction — init.inc leaves NMI off and $4200 is written only
    ; below — so the S-SMP is still in the IPL. Tad_Init runs ONCE per
    ; power-on; the song load is ASYNC and Tad_Process streams it during the
    ; frame loop.
    sep #$20
    .a8
    jsl Tad_Init
    jsr sf_sfx_reset                ; the ring holds power-on garbage
    ; STEREO: the song is PANNED (mid pulse left, arpeggio right) and TAD's
    ; default is MONO (tad-audio.inc:123), which collapses every channel to
    ; centre. The mode only takes effect at the next song load
    ; (tad-audio.inc:525), so it is set between Tad_Init and Tad_LoadSong.
    lda #TadAudioMode::STEREO
    sta Tad_audioMode
    lda #Song::drive_song           ; the action rails' song — assets/audio/README
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- enter the boot scene (id 0 = fight) under forced blank -----------
    ldx #(SCENE_FIGHT * 2)
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
    ; ---- audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids
    ; ISR calls).
    sep #$20
    .a8
    jsr sf_audio_tick               ; delivers one queued cue, then Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
