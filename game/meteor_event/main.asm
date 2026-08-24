; =============================================================================
; meteor_event — the in-level cutscene that swaps Mode 1 <-> Mode 7
; =============================================================================
; A tiny Mode-1 platformer slice that becomes a set-piece and returns. You walk
; the player right across a flat green ground past two raised platforms; at the
; trigger the screen FREEZES, the visible BG platforms are CAPTURED as OBJ
; sprites pixel-aligned to where their tiles rendered, the BG is dropped from
; TM so only the captured sprites remain, and the game swaps to a static Mode-7
; meteor scene. A far-approach meteor sprite grows in from the top-left, hands
; over to the Mode-7 plane at the crossover, and the plane then GROWS IN PLACE
; about a pinned affine pivot while the screen origin slides it off the
; bottom-right and a red impact glow rises behind the captured sprites and
; recedes. Then it swaps back and control is released.
;
;   PLAY -> FREEZE -> CAPTURE -> [swap] -> SCENE -> [swap] -> PLAY
;
; THE BAKED-TRACK MATRIX: the whole Mode-7 phase's matrix comes from ONE baked
; track (met_rom's met_grow) through the shared m7_track player — no runtime
; trig, no multiply, no HDMA channel for the matrix. The angle is baked
; ABSOLUTELY because every entry into the ramp is from the known heading 0.
; what latches the eight ports tear-free.
;
; Controls: D-pad RIGHT walks the player right. During the cutscene input is
; GATED — the player does not move — and control returns when it ends.
;
; NO AUDIO: this rail composes no audio feature at all, exactly as `boss`
; measured for itself.

.p816
.smart

.define SF_HDR_TITLE "METEOR EVENT"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)
.include "meteor.inc"               ; the rail's own vocabulary

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
.include "tick_scale.asm"           ; TS_STEP: the macro both scenes count
                                    ;   their steps with. INCLUDED BEFORE THE
                                    ;   SCENES — a ca65 macro must be defined
                                    ;   before the line that expands it.

; --- the ROM claim sites ----------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build; the
; PRESENCE side is `make rom-unbacked` (docs/37).
;
; met_map is 32,768 B — one WHOLE LoROM window — so it has bank 1 to itself
; and the single enter DMA cannot cross a bank boundary.
.segment "BANK1"
met_map_bin:
    .incbin "met_map.bin"
.assert ^met_map_bin = ES_R_MET_MAP_BANK, error, "met_map bank drifted from allocator claim"
.assert .loword(met_map_bin) = ES_R_MET_MAP_ADDR, error, "met_map addr drifted from allocator claim"

.segment "BANK2"
; The allocator packs by (-bytes, name): met_obj_chr (3,072) leads, then
; m7_lut (2,048), met_grow (438), met_bg_chr (128), and the three 32 B
; palettes in name order (met_bg_pal < met_obj_pal < met_pal). The .asserts
; make that agreement checkable rather than assumed.
met_obj_chr_bin:
    .incbin "met_obj_chr.bin"
.assert ^met_obj_chr_bin = ES_R_MET_OBJ_CHR_BANK, error, "met_obj_chr bank drifted from allocator claim"
.assert .loword(met_obj_chr_bin) = ES_R_MET_OBJ_CHR_ADDR, error, "met_obj_chr addr drifted from allocator claim"
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
met_grow_bin:
    .incbin "met_grow.bin"
.assert ^met_grow_bin = ES_R_MET_GROW_BANK, error, "met_grow bank drifted from allocator claim"
.assert .loword(met_grow_bin) = ES_R_MET_GROW_ADDR, error, "met_grow addr drifted from allocator claim"
met_bg_chr_bin:
    .incbin "met_bg_chr.bin"
.assert ^met_bg_chr_bin = ES_R_MET_BG_CHR_BANK, error, "met_bg_chr bank drifted from allocator claim"
.assert .loword(met_bg_chr_bin) = ES_R_MET_BG_CHR_ADDR, error, "met_bg_chr addr drifted from allocator claim"
met_bg_pal_bin:
    .incbin "met_bg_pal.bin"
.assert ^met_bg_pal_bin = ES_R_MET_BG_PAL_BANK, error, "met_bg_pal bank drifted from allocator claim"
.assert .loword(met_bg_pal_bin) = ES_R_MET_BG_PAL_ADDR, error, "met_bg_pal addr drifted from allocator claim"
met_obj_pal_bin:
    .incbin "met_obj_pal.bin"
.assert ^met_obj_pal_bin = ES_R_MET_OBJ_PAL_BANK, error, "met_obj_pal bank drifted from allocator claim"
.assert .loword(met_obj_pal_bin) = ES_R_MET_OBJ_PAL_ADDR, error, "met_obj_pal addr drifted from allocator claim"
met_pal_bin:
    .incbin "met_pal.bin"
.assert ^met_pal_bin = ES_R_MET_PAL_BANK, error, "met_pal bank drifted from allocator claim"
.assert .loword(met_pal_bin) = ES_R_MET_PAL_ADDR, error, "met_pal addr drifted from allocator claim"
.segment "CODE"

; --- m7_affine (after the LUT blob its heading lookup reads) ----------------
; Composed for its DP shadow, its set_center and its NMI commit. This rail
; never calls m7a_set_heading at runtime — the track replaces it — but the
; routine and its LUT stay: the claim is the feature's, and rom-unbacked holds
; the .incbin above to it.
.include "m7_affine.asm"

; --- m7_track (the matrix-track player; writes m7_affine's shadow) ---------
.include "m7_track.asm"

; --- met_obj (GLOBAL: the cast spans the swap) ------------------------------
.include "met_obj.asm"

; --- the scenes (each carries its own scene-scoped features) ----------------
.include "scenes/level.asm"
.include "scenes/impact.asm"

; --- sm_nmi_hook: per-frame VBlank work -------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Two commits, no ordering constraint between them: oam_nmi_dma pushes the
; sprite shadow, and m7a_nmi_commit latches all eight Mode 7 ports together —
; so the matrix a frame renders with is exactly the one track entry its tick
; applied, tear-free.
;
; The second commit runs in BOTH scenes, and in the Mode-1 one it is what
; scrolls the level: $210D/$210E are BG1HOFS/BG1VOFS there and M7HOFS/M7VOFS
; in Mode 7 — one port under one name — so the camera rides the same shadow
; the meteor's slide does. The six Mode-7-only ports the commit also writes
; have no effect in Mode 1.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr m7a_nmi_commit          ; the eight Mode 7 / scroll ports, from the shadow
    rts

; --- scene dispatch tables (manifest order: level=0, impact=1) --------------
; AFTER the scene includes: ca65 resolves a scope's members only once the
; scope has been seen.
sm_enter_tab:   .word level::enter,  impact::enter
sm_tick_tab:    .word level::tick,   impact::tick
sm_exit_tab:    .word level::exit,   impact::exit

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
    jsr met_obj_arm             ; sheet + palette + OBSEL, then this rail's
                                ;   slots parked again (GLOBAL: the cast's CHR
                                ;   must stand in both scenes, so the arm is a
                                ;   boot step rather than a scene's enter)
    jsr level::game_init        ; every [global] state word, before any read
    ; ---- enter the boot scene (id 0 = level) under forced blank -----------
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
