; =============================================================================
; mode7_flight — free flight, and the altitude axis
; =============================================================================
; Free flight over a Mode 7 perspective floor. The D-pad turns, B throttles
; forward, Y reverses, release hovers, and L/R fly the airship down and up —
; and the altitude is the point: it drives the PERSPECTIVE SCALE, so climbing
; makes the ground recede and descending brings it up to meet you.
;
; THE MECHANISM, in one line: the per-scanline pose factors as
; S_a(k) * R(h), the two factors are baked (m7f_rom, ~28 KB, exact on both
; axes), and m7f_cam joins them per frame with the hardware multiplier into a
; double-buffered WRAM band table that two DIRECT HDMA channels stream. The
; whole derivation is in engine/features/m7f_cam/feature.toml.
;
; ONE SCENE, no edges — this rail is one continuous loop with no scene change,
; and a title screen would be surface with no showcase value.
;
; NO AUDIO: this rail composes no audio feature at all. `tad_rom` is therefore
; not in this game's globals and the link is one object.

.p816
.smart

.define SF_HDR_TITLE "SKY RUNNER"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"              ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)
.include "mode7_flight.inc"         ; the rail's own vocabulary

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition game.toml declares) -
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro the sky tick counts its
                                    ;   ONE shared tick with. INCLUDED BEFORE
                                    ;   THE SCENE — a ca65 macro must be
                                    ;   defined before the line that expands
                                    ;   it, and m7f_logic.asm is inside
                                    ;   scenes/sky.asm's scope.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — or, for the two FACTOR blobs, be joined into the band table as a pose.
;
; m7f_ground is 32,768 B — one WHOLE LoROM window — so it gets a bank to itself
; and the single DMA that uploads it cannot cross a bank boundary.
.segment "BANK1"
m7f_ground_bin:
    .incbin "m7f_ground.bin"
.assert ^m7f_ground_bin = ES_R_M7F_GROUND_BANK, error, "m7f_ground bank drifted from allocator claim"
.assert .loword(m7f_ground_bin) = ES_R_M7F_GROUND_ADDR, error, "m7f_ground addr drifted from allocator claim"

.segment "BANK2"
; THE TWO FACTORS. The order here is the allocator's, not a preference:
; place_rom packs by (-bytes, name), so the 25,920 B profile table sorts ahead
; of the 2,048 B trig and OBJ sheets and the three 32 B palettes. A re-sort
; moves an address and the build stops with the claim named.
;
; m7f_prof is 25,920 B and therefore fits ONE 32 KB window with 6,848 B spare —
; which is the property m7f_cam's addressing depends on, since `lda f:base,x`
; cannot cross a bank and a profile straddling one would stream a neighbouring
; altitude's bytes for the rest of the band.
m7f_prof_bin:
    .incbin "m7f_prof.bin"
.assert ^m7f_prof_bin = ES_R_M7F_PROF_BANK, error, "m7f_prof bank drifted from allocator claim"
.assert .loword(m7f_prof_bin) = ES_R_M7F_PROF_ADDR, error, "m7f_prof addr drifted from allocator claim"
m7f_obj_chr_bin:
    .incbin "m7f_obj_chr.bin"
.assert ^m7f_obj_chr_bin = ES_R_M7F_OBJ_CHR_BANK, error, "m7f_obj_chr bank drifted from allocator claim"
.assert .loword(m7f_obj_chr_bin) = ES_R_M7F_OBJ_CHR_ADDR, error, "m7f_obj_chr addr drifted from allocator claim"
m7f_trig_bin:
    .incbin "m7f_trig.bin"
.assert ^m7f_trig_bin = ES_R_M7F_TRIG_BANK, error, "m7f_trig bank drifted from allocator claim"
.assert .loword(m7f_trig_bin) = ES_R_M7F_TRIG_ADDR, error, "m7f_trig addr drifted from allocator claim"
m7f_pal_bin:
    .incbin "m7f_pal.bin"
.assert ^m7f_pal_bin = ES_R_M7F_PAL_BANK, error, "m7f_pal bank drifted from allocator claim"
.assert .loword(m7f_pal_bin) = ES_R_M7F_PAL_ADDR, error, "m7f_pal addr drifted from allocator claim"
m7f_shadow_pal_bin:
    .incbin "m7f_shadow_pal.bin"
.assert ^m7f_shadow_pal_bin = ES_R_M7F_SHADOW_PAL_BANK, error, "m7f_shadow_pal bank drifted from allocator claim"
.assert .loword(m7f_shadow_pal_bin) = ES_R_M7F_SHADOW_PAL_ADDR, error, "m7f_shadow_pal addr drifted from allocator claim"
m7f_ship_pal_bin:
    .incbin "m7f_ship_pal.bin"
.assert ^m7f_ship_pal_bin = ES_R_M7F_SHIP_PAL_BANK, error, "m7f_ship_pal bank drifted from allocator claim"
.assert .loword(m7f_ship_pal_bin) = ES_R_M7F_SHIP_PAL_ADDR, error, "m7f_ship_pal addr drifted from allocator claim"
; (`grad_tabs` is rgb_gradient's claim and rgb_gradient is SCENE-scoped, so its
; emitted symbols live in engine_state_sky.inc and its claim site has to sit
; inside the scene — scenes/sky.asm, the same shape race.asm uses.)
.segment "CODE"

; --- the scene (carries its own scene-scoped features) ---------------------
.include "scenes/sky.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; THREE commits now, and only one pair is ordered: `tod_commit` publishes the
; day/night snapshot offset that `sky_reanchor`'s fall-through into
; `fog_reanchor` reads, so it goes first. Run the other way round, a frame
; shows the previous step's ramp under this step's zenith — one frame of a
; colour that belongs to neither.
;
; oam_nmi_dma pushes the sprite shadow the tick has just rebuilt, and
; m7f_nmi_commit swaps the composed band table in and stamps the Mode 7 origin
; from the same state the tick composed against. Both are THIS frame's answer,
; which is what keeps the ship, its shadow and the floor from ever being one
; frame apart.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma
    jsr sky::m7f_nmi_commit
    jsr sky::tod_commit         ; the day/night clock: CGRAM word 0 + the ramp
    jsr sky::sky_reanchor       ; the TM split follows the moving horizon
    rts

; --- scene dispatch tables (manifest order: sky=0) -------------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word sky::enter
sm_tick_tab:    .word sky::tick
sm_exit_tab:    .word sky::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    jsr sm_init
    jsr input_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ldx #0
    jsr (sm_enter_tab, x)
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
