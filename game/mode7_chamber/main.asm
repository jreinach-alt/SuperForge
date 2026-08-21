; =============================================================================
; mode7_chamber — four per-scanline effects, one plane
; =============================================================================
; An ashlar stone floor bows into a barrel and rolls endlessly beneath a Mode 1
; band, darkened top and bottom by a brightness vignette. Nothing is played;
; the motion drives itself. Four cooperating HDMA effects over one Mode 7
; plane:
;
;   1. the ROLL      apparent rotation from a VERTICAL SCROLL with the angle
;                    held constant — a popsicle stick turning inside a length
;                    of pipe. M7B/M7C are zero on every line and the matrix is
;                    never rebuilt; what moves is the camera's world Y.
;   2. the BARREL    m7_barrel's M7A column, a raised-cosine bulge streamed per
;                    scanline. Pad Up/Down walks it between FLAT and the baked
;                    $0100 -> $0180 -> $0100 curve.
;   3. the SPLIT     split_band's BGMODE + TM at scanline 32 — a clean Mode 1
;                    strip above the Mode 7 floor.
;   4. the VIGNETTE  rgb_gradient's three COLDATA planes, 0 -> 8 -> 0 down the
;                    frame, added to BG1 + the backdrop.
;
; ONE SCENE, no edges. game.toml's header carries every feature deliberately
; NOT composed and the allocator check that would have refused each.
;
; THE CHANNEL PLUMBING IS NOT WRITTEN DOWN. The channel numbers, the DMAP and
; BBAD bytes, the table addresses and the ROM banks are all emitted by the
; allocator from five feature.toml declarations, and `no_literals` refuses the
; build if any of them is written down instead — no hand-picked WRAM scratch
; tables, no channel equates, no macro front door.
;
; AND THE CENTRAL MECHANISM IS BAKED, NOT SOLVED: an engine that SOLVED the
; matrix would have to OVERWRITE M7A per floor scanline after every perspective
; rebuild, because the barrel has to land after the solve. Here the column is
; ROM data streamed INDIRECT, so the bow is baked, indexed by a bow step, and
; the "overwrite" is a pointer.

.p816
.smart

.define SF_HDR_TITLE "BARREL CHAMBER"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. The generated header suggests wrapping it
; in `.scope <id>` for a multi-scene ROM so two scenes' symbols cannot collide;
; this rail has exactly one scene and every scene-scoped feature resolves its
; symbols from file scope, so a wrapper here would only hide them.
.include "engine_state_chamber.inc"  ; GENERATED — the chamber scene's map
.include "world.inc"                 ; geometry + feel constants (not addresses)
.include "header.inc"
.include "init.inc"                  ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "region.asm"                ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"            ; TS_GAIN_NUM/DEN: the measured frame
                                     ;   ratio m7c_roll builds its region
                                     ;   constants from. INCLUDED BEFORE
                                     ;   m7c_roll.asm, and it must be — the
                                     ;   equates below are evaluated where they
                                     ;   are written.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — and on this rail "art" includes the two matrix columns the HDMA
; channels feed straight into M7A and M7D, so the failure mode would be a
; floor with no bow and no horizon.
;
; THE ORDER OF THE WINDOWS IS THE ALLOCATOR'S, not a preference: place_rom
; packs free claims by (-bytes, name), so the 32,768 B map takes window 1 and
; everything else packs into window 2 behind the 3,456 B bow set. The sites
; here follow build/m7c/allocation_report.txt exactly, and the per-site
; .asserts are what would turn a re-sort into a build failure rather than into
; five blobs quietly reading each other's bytes.
;
; m7c_map is 32,768 B — one WHOLE LoROM window — so it gets a bank to itself
; and the single DMA that uploads it cannot cross a bank boundary.
.segment "BANK1"
m7c_map_bin:
    .incbin "m7c_map.bin"
.assert ^m7c_map_bin = ES_R_M7C_MAP_BANK, error, "m7c_map bank drifted from allocator claim"
.assert .loword(m7c_map_bin) = ES_R_M7C_MAP_ADDR, error, "m7c_map addr drifted from allocator claim"

; --- window 2: the two matrix columns, the palette, the vignette -----------
; The bow set and the perspective column land in the SAME window, which is not
; a coincidence and is load-bearing: DASB is per channel, and both sets fitting
; one window is what makes those two bytes static (m7_barrel.asm writes them
; once at scene enter rather than every VBlank). If a future edit grew the bow
; set past one window, the size .asserts in m7_barrel.asm fire before this
; arrangement can silently stop being true.
.segment "BANK2"
bow_a_bin:
    .incbin "bow_a.bin"
.assert ^bow_a_bin = ES_R_BOW_A_BANK, error, "bow_a bank drifted from allocator claim"
.assert .loword(bow_a_bin) = ES_R_BOW_A_ADDR, error, "bow_a addr drifted from allocator claim"
persp_d_bin:
    .incbin "persp_d.bin"
.assert ^persp_d_bin = ES_R_PERSP_D_BANK, error, "persp_d bank drifted from allocator claim"
.assert .loword(persp_d_bin) = ES_R_PERSP_D_ADDR, error, "persp_d addr drifted from allocator claim"
m7c_pal_bin:
    .incbin "m7c_pal.bin"
.assert ^m7c_pal_bin = ES_R_M7C_PAL_BANK, error, "m7c_pal bank drifted from allocator claim"
.assert .loword(m7c_pal_bin) = ES_R_M7C_PAL_ADDR, error, "m7c_pal addr drifted from allocator claim"
m7c_vign_bin:
    .incbin "m7c_vign.bin"
.assert ^m7c_vign_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(m7c_vign_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "m7c_floor.asm"
.include "m7_barrel.asm"
.include "split_band.asm"
.include "rgb_gradient.asm"
.include "m7c_roll.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/chamber.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; TWO CALLS, AND BOTH ARE COMMIT WINDOWS.
;   mb_commit_origin  the four write-twice origin ports from the DP shadow the
;                     roll advanced on the main thread. A write-twice spun
;                     across active display is the ValueLatch hazard, so it
;                     belongs here and nowhere else.
;   mb_tick           re-points the A column if the bow step moved. The HDMA
;                     init fetch for the next frame reads that index table at
;                     line 0, so a rewrite outside VBlank could tear.
;
; Nothing else is here and nothing else needs to be: the perspective column's
; pointers are static, both DASB bytes are static, and no OAM shadow exists
; (nothing draws).
sm_nmi_hook:
    .a8
    .i16
    jsr mb_commit_origin        ; A8 in, A8 out — its own width contract
    jsr mb_tick                 ; A8 in, A8 out — widens internally
    rts

; --- scene dispatch tables (manifest order: chamber=0) ---------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word chamber::enter
sm_tick_tab:    .word chamber::tick
sm_exit_tab:    .word chamber::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    jsr input_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    ; ---- enter the boot scene (id 0 = chamber) under forced blank --------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    ; Bit 0 is what makes the PPU latch $4218 every VBlank, and `input_read`
    ; waits out the busy window before reading it.
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI enable + auto-joypad
    rep #$20
    .a16
@loop:
    .a16
    .i16
    ; The pad is latched FIRST, immediately after sm_frame_sync returned from
    ; the VBlank the auto-read ran in; the scene tick is its only reader.
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
