; =============================================================================
; boss — the scale-ramping static-affine debut: the boss IS the screen
; =============================================================================
; A Mode 7 boss duel: the boss face is the BG layer, scaled and rotated as one
; rigid image by a single uniform matrix; the player ship, the attack rain,
; the HP HUD and the player shots are sprites composited over it. The fight
; runs as a state machine — REVEAL (the boss grows in from far away) -> HOLD
; -> FIGHT (strafe, hold A to fire, dodge the rain, three phases) -> DYING
; (the capture beat) -> DEATH (the recede) or LOSE -> RESULT ->
; masked RESET -> loop.
;
; THE BAKED-TRACK MATRIX: every animated state's matrix comes from a track
; (bs_rom's ring/reveal/death blobs) through the shared m7_track player —
; there is no runtime trig, no multiply, no HDMA channel, and m7_affine's own
; scale-1.0 LUT is composed but never indexed at runtime (its shadow + NMI
; commit are what this rail reuses; m7_track's feature.toml records the
; contract).
;
; Controls:  D-pad left/right strafe · A (hold) fire.  With no input the rail
; runs its whole cycle autonomously — the rain's centre column hits a
; stationary player (the deterministic LOSE path) and the RESULT->RESET loop
; re-arms the reveal.
;
; NO AUDIO: this rail composes no audio feature at all. The TAD variant is
; boss_saucer's.

.p816
.smart

.define SF_HDR_TITLE "TITAN DUEL"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)
.include "boss.inc"                 ; the rail's own vocabulary

.segment "CODE"

; The vectors header.inc points at. NMI proper hands straight to the scene
; manager's core, which commits INIDISP and runs sm_nmi_hook once per armed
; VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition) -------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro the arena tick counts
                                    ;   its state steps with. INCLUDED BEFORE
                                    ;   THE SCENE — a ca65 macro must be
                                    ;   defined before the line that expands
                                    ;   it.

; --- the ROM claim sites ----------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build; the
; PRESENCE side is `make rom-unbacked` (docs/37).
;
; bs_map is 32,768 B — one WHOLE LoROM window — so it has bank 1 to itself
; and the single enter DMA cannot cross a bank boundary.
.segment "BANK1"
bs_map_bin:
    .incbin "bs_map.bin"
.assert ^bs_map_bin = ES_R_BS_MAP_BANK, error, "bs_map bank drifted from allocator claim"
.assert .loword(bs_map_bin) = ES_R_BS_MAP_ADDR, error, "bs_map addr drifted from allocator claim"

.segment "BANK2"
; The allocator packs by (-bytes, name): m7_lut (2,048) leads, then bs_ring
; (1,026), bs_sprite_chr (1,024), the two 246 B tracks (death < reveal), the
; two 32 B palettes (pal < sprite_pal). The .asserts make that agreement
; checkable rather than assumed.
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
bs_ring_bin:
    .incbin "bs_ring.bin"
.assert ^bs_ring_bin = ES_R_BS_RING_BANK, error, "bs_ring bank drifted from allocator claim"
.assert .loword(bs_ring_bin) = ES_R_BS_RING_ADDR, error, "bs_ring addr drifted from allocator claim"
bs_sprite_chr_bin:
    .incbin "bs_sprite_chr.bin"
.assert ^bs_sprite_chr_bin = ES_R_BS_SPRITE_CHR_BANK, error, "bs_sprite_chr bank drifted from allocator claim"
.assert .loword(bs_sprite_chr_bin) = ES_R_BS_SPRITE_CHR_ADDR, error, "bs_sprite_chr addr drifted from allocator claim"
bs_death_bin:
    .incbin "bs_death.bin"
.assert ^bs_death_bin = ES_R_BS_DEATH_BANK, error, "bs_death bank drifted from allocator claim"
.assert .loword(bs_death_bin) = ES_R_BS_DEATH_ADDR, error, "bs_death addr drifted from allocator claim"
bs_reveal_bin:
    .incbin "bs_reveal.bin"
.assert ^bs_reveal_bin = ES_R_BS_REVEAL_BANK, error, "bs_reveal bank drifted from allocator claim"
.assert .loword(bs_reveal_bin) = ES_R_BS_REVEAL_ADDR, error, "bs_reveal addr drifted from allocator claim"
bs_pal_bin:
    .incbin "bs_pal.bin"
.assert ^bs_pal_bin = ES_R_BS_PAL_BANK, error, "bs_pal bank drifted from allocator claim"
.assert .loword(bs_pal_bin) = ES_R_BS_PAL_ADDR, error, "bs_pal addr drifted from allocator claim"
bs_sprite_pal_bin:
    .incbin "bs_sprite_pal.bin"
.assert ^bs_sprite_pal_bin = ES_R_BS_SPRITE_PAL_BANK, error, "bs_sprite_pal bank drifted from allocator claim"
.assert .loword(bs_sprite_pal_bin) = ES_R_BS_SPRITE_PAL_ADDR, error, "bs_sprite_pal addr drifted from allocator claim"
.segment "CODE"

; --- pool (the mechanism; the arrays are bs_obj's claim) --------------------
.include "pool.asm"

; --- m7_affine (after the LUT blob its heading lookup reads) ----------------
; Composed for its DP shadow, its set_center and its NMI commit; this rail
; never calls m7a_set_heading at runtime (the tracks replace it), but the
; routine and its LUT stay — the claim is the feature's, and rom-unbacked
; holds the .incbin above to it.
.include "m7_affine.asm"

; --- m7_track (the matrix-track player; writes m7_affine's shadow) ---------
.include "m7_track.asm"

; --- the scene (carries its own scene-scoped features) ----------------------
.include "scenes/arena.asm"

; --- sm_nmi_hook: per-frame VBlank work -------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two commits, no ordering constraint between them: oam_nmi_dma pushes the
; sprite shadow the tick just rebuilt, and m7a_nmi_commit latches all eight
; Mode 7 ports together — so the matrix a frame renders with is exactly the
; one track entry its tick applied, tear-free. On this rail that pairing IS
; the reveal: scale and rotation arrive as one baked word pair per frame.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr m7a_nmi_commit          ; the eight Mode 7 ports, from the DP shadow
    rts

; --- scene dispatch tables (manifest order: arena=0) ------------------------
; AFTER the scene include: ca65 resolves a scope's members only once the
; scope has been seen.
sm_enter_tab:   .word arena::enter
sm_tick_tab:    .word arena::tick
sm_exit_tab:    .word arena::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) ------
    jsr sm_init
    jsr input_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- enter the boot scene (id 0 = arena) under forced blank -----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad -------------------------------------
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
    jsr sm_frame_sync
    bra @loop
