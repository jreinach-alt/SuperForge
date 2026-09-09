; =============================================================================
; m7_oshoot — the rotating Mode 7 arena shooter
; =============================================================================
; A top-down run-and-gun on a spinning Mode 7 ground plane. The D-pad picks one
; of eight compass headings and WALKS the world along it; the floor rotates so
; the facing reads "up" and the pivot is re-pinned to the player EVERY FRAME, so
; he stays centred while the arena turns and slides beneath him. Timed waves of
; chasers spawn on a world ring and close in; A fires along the facing. The
; chasers and the bullets live at world positions and are projected onto the
; spinning floor through the render matrix's TRANSPOSE, so they stay glued to
; the tile they stand on. All of the gameplay — movement, wall collision,
; bullet-vs-chaser, hero-vs-chaser — runs in WORLD space and never reads the
; matrix, so none of it depends on which way the picture happens to be facing.
;
; ONE SCENE, no edges — m7_dungeon's shape, and this rail shares it
; (game.toml's header carries the features deliberately NOT composed and which
; allocator check would have refused each of them anyway).
;
; NO AUDIO. `tad_rom` is not in this game's globals, there is no Tad_Init and no
; Tad_Process pump, and the link is one object.

.p816
.smart

.define SF_HDR_TITLE "SPIN GUNNER"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.import sf_sfx_reset, sf_sfx_queue_c, sf_audio_tick
                                    ; engine/features/audio — the request
                                    ;   queue and the per-frame pump
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)
.include "m7_oshoot.inc"            ; the rail's own vocabulary

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition game.toml declares) -
; m7_affine and m7_project are global because later rails already
; reuse them; mo_floor and mo_obj are scene-scoped and are therefore included
; inside `.scope arena`, next to the scene code whose symbols they read.
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro the arena tick counts
                                    ;   its heading and chase steps with.
                                    ;   INCLUDED BEFORE THE SCENE — a ca65
                                    ;   macro must be defined before the line
                                    ;   that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37): a claim with no .incbin here would
; reserve the window and let whatever the linker left there be read as art.
;
; THREE WINDOWS, AND `audio` IS WHY IT IS NOT TWO. tad_export's 16,384 B
; half-window takes the top of window 1, and the allocator packs by
; (-bytes, name): mo_tilemap (16,384) is the only other claim that fits beside
; it, mo_map at 32,768 needs a WHOLE window and takes window 2, and everything
; else follows into window 3. ld65 refused this build by name (`mo_map bank
; drifted from allocator claim`) until the segments said so, which is the
; placement asserts doing exactly what they exist for.
;
; Window 1: the PACKED tile-id map col_map reads, beside the audio export —
; at 16,384 B each, the two exactly fill it.
.segment "BANK1"
mo_tilemap_bin:
    .incbin "mo_tilemap.bin"
.assert ^mo_tilemap_bin = ES_R_MO_TILEMAP_BANK, error, "mo_tilemap bank drifted from allocator claim"
.assert .loword(mo_tilemap_bin) = ES_R_MO_TILEMAP_ADDR, error, "mo_tilemap addr drifted from allocator claim"

.segment "BANK2"
; Window 2: mo_map, 32,768 B, a WHOLE window to itself — which is what keeps
; the single DMA that uploads it from crossing a bank boundary.
mo_map_bin:
    .incbin "mo_map.bin"
.assert ^mo_map_bin = ES_R_MO_MAP_BANK, error, "mo_map bank drifted from allocator claim"
.assert .loword(mo_map_bin) = ES_R_MO_MAP_ADDR, error, "mo_map addr drifted from allocator claim"
.segment "BANK3"
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
; The OBJ sheets and their palettes. The ORDER here is the allocator's, not a
; preference: place_rom packs by (-bytes, name), so the two 576 B sheets sort
; ahead of the 256 B flag table and the three 32 B palettes, and each group
; sorts alphabetically. A re-sort moves an address and the build stops with the
; claim named.
mo_enemy_chr_bin:
    .incbin "mo_enemy_chr.bin"
.assert ^mo_enemy_chr_bin = ES_R_MO_ENEMY_CHR_BANK, error, "mo_enemy_chr bank drifted from allocator claim"
.assert .loword(mo_enemy_chr_bin) = ES_R_MO_ENEMY_CHR_ADDR, error, "mo_enemy_chr addr drifted from allocator claim"
mo_hero_chr_bin:
    .incbin "mo_hero_chr.bin"
.assert ^mo_hero_chr_bin = ES_R_MO_HERO_CHR_BANK, error, "mo_hero_chr bank drifted from allocator claim"
.assert .loword(mo_hero_chr_bin) = ES_R_MO_HERO_CHR_ADDR, error, "mo_hero_chr addr drifted from allocator claim"
mo_flags_bin:
    .incbin "mo_flags.bin"
.assert ^mo_flags_bin = ES_R_MO_FLAGS_BANK, error, "mo_flags bank drifted from allocator claim"
.assert .loword(mo_flags_bin) = ES_R_MO_FLAGS_ADDR, error, "mo_flags addr drifted from allocator claim"
mo_bullet_pal_bin:
    .incbin "mo_bullet_pal.bin"
.assert ^mo_bullet_pal_bin = ES_R_MO_BULLET_PAL_BANK, error, "mo_bullet_pal bank drifted from allocator claim"
.assert .loword(mo_bullet_pal_bin) = ES_R_MO_BULLET_PAL_ADDR, error, "mo_bullet_pal addr drifted from allocator claim"
mo_enemy_pal_bin:
    .incbin "mo_enemy_pal.bin"
.assert ^mo_enemy_pal_bin = ES_R_MO_ENEMY_PAL_BANK, error, "mo_enemy_pal bank drifted from allocator claim"
.assert .loword(mo_enemy_pal_bin) = ES_R_MO_ENEMY_PAL_ADDR, error, "mo_enemy_pal addr drifted from allocator claim"
mo_hero_pal_bin:
    .incbin "mo_hero_pal.bin"
.assert ^mo_hero_pal_bin = ES_R_MO_HERO_PAL_BANK, error, "mo_hero_pal bank drifted from allocator claim"
.assert .loword(mo_hero_pal_bin) = ES_R_MO_HERO_PAL_ADDR, error, "mo_hero_pal addr drifted from allocator claim"
mo_score_pal_bin:
    .incbin "mo_score_pal.bin"
.assert ^mo_score_pal_bin = ES_R_MO_SCORE_PAL_BANK, error, "mo_score_pal bank drifted from allocator claim"
.assert .loword(mo_score_pal_bin) = ES_R_MO_SCORE_PAL_ADDR, error, "mo_score_pal addr drifted from allocator claim"
mo_pal_bin:
    .incbin "mo_pal.bin"
.assert ^mo_pal_bin = ES_R_MO_PAL_BANK, error, "mo_pal bank drifted from allocator claim"
.assert .loword(mo_pal_bin) = ES_R_MO_PAL_ADDR, error, "mo_pal addr drifted from allocator claim"
.segment "CODE"

; --- pool (the mechanism; the consumer's arrays are mo_obj's claim) ---------
.include "pool.asm"

; --- m7_affine (after the LUT blob its lookup reads) -----------------------
.include "m7_affine.asm"

; --- m7_project (world -> screen; reads m7_affine's shadow, so it follows it)
; Included at FILE scope and before the scene, which is what lets the scene's
; own feature alias its constants at assemble time rather than deferring them.
.include "m7_project.asm"

; --- the scene (carries its own scene-scoped features) ---------------------
.include "scenes/arena.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two commits, no ordering constraint between them: oam_nmi_dma pushes the
; sprite shadow the scene's tick has just rebuilt, and m7a_nmi_commit latches
; all eight Mode 7 registers together so the matrix cannot tear mid-frame.
;
; THEY ARE THE SAME FRAME'S ANSWER, and on this rail that is worth more than it
; was on m7_dungeon. There the pivot moved only on a knockback; here it moves
; every frame, so "the matrix the sprites were projected through" and "the
; matrix the floor renders with" are a fresh pair each frame. The tick sets both
; the heading and the centre before it draws, and this hook latches exactly what
; the tick decided — so a chaser and the floor tile it stands on are never one
; frame apart.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr m7a_nmi_commit          ; the eight Mode 7 ports, from the DP shadow
    rts

; --- scene dispatch tables (manifest order: arena=0) -----------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word arena::enter
sm_tick_tab:    .word arena::tick
sm_exit_tab:    .word arena::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr fade_init
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
    ; ---- enter the boot scene (id 0 = arena) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    rep #$20
    .a16
@loop:
    .a16
    .i16
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
