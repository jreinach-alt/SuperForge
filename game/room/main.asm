; =============================================================================
; room — "the room". ROM skeleton.
; =============================================================================
; Every RAM/VRAM/CGRAM address and channel comes from the allocator's emitted
; includes; hardware I/O ports are the only literals (no_literals-gated).
; Scene code lives in .scope <scene_id> blocks so same-named claims in
; different scenes stay distinct symbols (see engine_state_<scene>.inc).
.p816
.smart

.define SF_HDR_TITLE "THE ROOM"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids for this
                                    ; game's export (assets/audio/export)
JOY_START = 1 << 12                 ; $4218 bit 12 — a bit POSITION.
                                    ; Written as a shift because the value
                                    ; 4096 is also this scene's text-CHR VRAM
                                    ; base, and a bare literal is read as an
                                    ; address by no_literals (correctly: it
                                    ; cannot know which one you meant).
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
.include "input2.asm"
.include "fade.asm"
.include "bg_text.asm"
.include "oam_sprites.asm"
.include "save.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro both room scenes use.
                                    ; INCLUDED BEFORE THE SCENES, and it must
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
    stz z:ES_TXT_Q + 0          ; VBlank cell queue: dirty flag + spare byte
    stz z:ES_TXT_Q + 2          ; ...staged VMADD
    stz z:ES_TXT_Q + 4          ; ...staged tile word
    rts

; --- global ROM blobs (allocator-claimed; .incbin order inside a segment ----
; must match the allocator's packing order — the .asserts refuse drift) ------
.segment "BANK2"
; ORDER IS NOT FREE: it must match the allocator's ROM packing (largest
; first from window 1) — see build/rm/allocation_report.txt. Each site
; .asserts its blob's linker bank/addr against the emitted symbols, so a
; reorder here (or a size change upstream) refuses the build rather than
; silently shifting every later blob. These blobs live in BANK2 because
; window 1 is the tad_export whole-window claim (AUDIO_DATA0 — the
; generated export demands a bank start and the 32 KB claim guarantees it).
bg1_map_bin:
    .incbin "bg1_map.bin"
.assert ^bg1_map_bin = ES_R_BG1_MAP_ROM_BANK, error, "bg1_map_bin bank drifted from allocator claim"
.assert .loword(bg1_map_bin) = ES_R_BG1_MAP_ROM_ADDR, error, "bg1_map_bin addr drifted from allocator claim"
bg2_map_bin:
    .incbin "bg2_map.bin"
.assert ^bg2_map_bin = ES_R_BG2_MAP_ROM_BANK, error, "bg2_map_bin bank drifted from allocator claim"
.assert .loword(bg2_map_bin) = ES_R_BG2_MAP_ROM_ADDR, error, "bg2_map_bin addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
hero_chr_bin:
    .incbin "hero_chr.bin"
.assert ^hero_chr_bin = ES_R_HERO_CHR_ROM_BANK, error, "hero_chr_bin bank drifted from allocator claim"
.assert .loword(hero_chr_bin) = ES_R_HERO_CHR_ROM_ADDR, error, "hero_chr_bin addr drifted from allocator claim"
bg1_chr_bin:
    .incbin "bg1_chr.bin"
.assert ^bg1_chr_bin = ES_R_BG1_CHR_ROM_BANK, error, "bg1_chr_bin bank drifted from allocator claim"
.assert .loword(bg1_chr_bin) = ES_R_BG1_CHR_ROM_ADDR, error, "bg1_chr_bin addr drifted from allocator claim"
bg2_chr_bin:
    .incbin "bg2_chr.bin"
.assert ^bg2_chr_bin = ES_R_BG2_CHR_ROM_BANK, error, "bg2_chr_bin bank drifted from allocator claim"
.assert .loword(bg2_chr_bin) = ES_R_BG2_CHR_ROM_ADDR, error, "bg2_chr_bin addr drifted from allocator claim"
crc16_lut_bin:
    .incbin "crc16_lut.bin"
.assert ^crc16_lut_bin = ES_R_CRC16_LUT_ROM_BANK, error, "crc16_lut_bin bank drifted from allocator claim"
.assert .loword(crc16_lut_bin) = ES_R_CRC16_LUT_ROM_ADDR, error, "crc16_lut_bin addr drifted from allocator claim"
iris_lut_bin:
    .incbin "iris_lut.bin"
.assert ^iris_lut_bin = ES_R_IRIS_LUT_BANK, error, "iris_lut_bin bank drifted from allocator claim"
.assert .loword(iris_lut_bin) = ES_R_IRIS_LUT_ADDR, error, "iris_lut_bin addr drifted from allocator claim"
bg1_pal_bin:
    .incbin "bg1_pal.bin"
.assert ^bg1_pal_bin = ES_R_BG1_PAL_ROM_BANK, error, "bg1_pal_bin bank drifted from allocator claim"
.assert .loword(bg1_pal_bin) = ES_R_BG1_PAL_ROM_ADDR, error, "bg1_pal_bin addr drifted from allocator claim"
bg2_pal_bin:
    .incbin "bg2_pal.bin"
.assert ^bg2_pal_bin = ES_R_BG2_PAL_ROM_BANK, error, "bg2_pal_bin bank drifted from allocator claim"
.assert .loword(bg2_pal_bin) = ES_R_BG2_PAL_ROM_ADDR, error, "bg2_pal_bin addr drifted from allocator claim"
hero_pal_bin:
    .incbin "hero_pal.bin"
.assert ^hero_pal_bin = ES_R_HERO_PAL_ROM_BANK, error, "hero_pal_bin bank drifted from allocator claim"
.assert .loword(hero_pal_bin) = ES_R_HERO_PAL_ROM_ADDR, error, "hero_pal_bin addr drifted from allocator claim"
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/title.asm"
.include "scenes/room.asm"
.include "scenes/room_b.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; every scene: commit the OAM shadow
    jsr text_vblank_commit      ; programs its own VMAIN/VMADD, so position
    rts                         ; here is free (AGENTS.md's established rule)

; --- scene dispatch tables (manifest order: title=0, room=1, room_b=2) ------
sm_enter_tab:   .word title::enter, room::enter, room_b::enter
sm_tick_tab:    .word title::tick,  room::tick,  room_b::tick
sm_exit_tab:    .word title::exit,  room::exit,  room_b::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr input2_init
    jsr fade_init
    jsr text_dp_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes — which is
                                ;   why it is here and not in either enter.
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- audio boot (TAD contract, tad-audio.inc): interrupts are DISABLED
    ; here by construction — init.inc leaves NMI off and $4200 is written
    ; only below — the S-SMP is still in the IPL, and the init chain above
    ; puts us well past the 40-scanline post-reset minimum (proven by the
    ; boot test's SPC-RAM byte compare, not assumed). Tad_Init runs ONCE per
    ; power-on; the song load is ASYNC — Tad_Process streams it during the
    ; title's frame loop and PLAY_SONG_IMMEDIATELY (the TAD default) starts
    ; it as soon as it lands. Rooms never call Tad_LoadSong again — the music
    ; persisting across a transition IS that absence, not a feature.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- game-lifetime user state (game logic owns these values) ----------
    ; "IT REMEMBERS": visits defaults to 0, then slot 0 is asked through the
    ; save feature's integrity gate. A VALID save's payload lands directly on
    ; visits ([<SV_PTR] copy — at most the SV_CAP=2 bytes the dest holds; a
    ; CRC-valid slot claiming more is rejected whole); no-save/corrupt returns
    ; $FFFF/$FFFE with the dest UNTOUCHED, so the 0 stands — no branch needed,
    ; the rejection semantics do the work. Every path leaves visits defined
    ; (power-on WRAM is random; the 0 store is the write-before-read
    ; contract). NMI is off here by construction (init.inc leaves it off;
    ; $4200 is written only below), so the SRAM reads cannot be preempted.
    lda #0
    sta f:US_VISITS_LONG
    sta z:SV_SLOT               ; slot 0 (A is still 0)
    lda #US_VISITS
    sta z:SV_PTR
    lda #2
    sta z:SV_CAP                ; dest capacity: the 2-byte visits
    sep #$20
    .a8
    lda #US_VISITS_BANK
    sta z:SV_PTR+2
    rep #$20
    .a16
    jsr sv_load
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
    jsr input2_read             ; pad 2 (the second hero); falls straight
                                ; through input_read's busy-wait
    jsr sm_tick
    jsr fade_tick
    ; ---- audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids
    ; ISR calls). During a scene transition's forced-blank stretch some
    ; frames are skipped — fine by design: the SPC runs autonomously and the
    ; queues are just processed late.
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
