; =============================================================================
; split_h_matrix_demo — TWO Mode 7 cameras for ~nil CPU
; =============================================================================
; Two vertically-stacked views of ONE flat top-down Mode 7 world. The top 112
; scanlines render it through a camera matrix at scale 1.0, the bottom 112
; through one at 0.25 — SAME map, SAME CHR, SAME CGRAM, same VRAM. The only
; difference between the bands is four bytes of matrix the HDMA lands at the
; seam, and the visible consequence is that the world's 8x8-px checker renders
; at an 8-px on-screen period on top and a 32-px one below.
;
; TWO HDMA CHANNELS, TWO HBLANK WRITES EACH PER FRAME. Each band's entry is a
; NON-REPEAT count, so its 4-byte matrix unit transfers once at the band's first
; scanline and HOLDS. That is the rail's whole claim — a second Mode 7 camera
; costs one more table entry, not one more solve — and it is why the sibling
; rail can afford a third band on the same two channels.
;
; ONE PAD, driving the one axis worth driving: D-pad Right/Left rewrites the
; BOTTOM band's scale word in the WRAM HDMA table each VBlank, so "patching an
; HDMA table live" becomes a state cycle a test can drive in both directions
; and hold still on.
;
; NOTHING HERE IS HAND-PLACED. There is no runtime HDMA channel allocator, no
; effect-tag registry and no hand-picked WRAM: the channel numbers, the DMAP and
; BBAD bytes, the table addresses and the ROM bank are all emitted by the
; allocator from the three feature.toml declarations, and `no_literals` refuses
; the build if any of them is written down instead.

.p816
.smart

.define SF_HDR_TITLE "SPLIT H MATRIX"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. This rail has exactly one scene and both
; scene-scoped features resolve its symbols from file scope, so a wrapper here
; would only hide them.
.include "engine_state_bands.inc"   ; GENERATED — the bands scene's map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

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

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37), and it is proven PER COMPOSITION — the
; sibling rail carries its own copies of these two sites for the same shared
; `shm_rom` feature.
;
; shm_map is 32,768 B — one WHOLE LoROM window — so it gets a bank to itself and
; the single DMA that uploads it cannot cross a bank boundary. It is the largest
; free claim, so place_rom (which packs by -bytes then name) gives it window 1.
.segment "BANK1"
shm_map_bin:
    .incbin "shm_map.bin"
.assert ^shm_map_bin = ES_R_SHM_MAP_BANK, error, "shm_map bank drifted from allocator claim"
.assert .loword(shm_map_bin) = ES_R_SHM_MAP_ADDR, error, "shm_map addr drifted from allocator claim"

.segment "BANK2"
shm_pal_bin:
    .incbin "shm_pal.bin"
.assert ^shm_pal_bin = ES_R_SHM_PAL_BANK, error, "shm_pal bank drifted from allocator claim"
.assert .loword(shm_pal_bin) = ES_R_SHM_PAL_ADDR, error, "shm_pal addr drifted from allocator claim"

.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "shm_floor.asm"
.include "shm_cam.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/bands.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE CALL, TWO STORES. shm_zoom_stamp writes the live band's M7A and M7D into
; the WRAM HDMA table. It runs here because the HDMA init fetch for the next
; frame reads that table at line 0, so VBlank is the window in which a rewrite
; cannot tear.
;
; Nothing else belongs here: the plane is static, the origin is written once
; under forced blank, and the other bands' entries never change after enter.
sm_nmi_hook:
    .a8
    .i16
    jsr shm_zoom_stamp              ; A8 in, A8 out — its own width contract
    rts

; --- scene dispatch tables (manifest order: bands=0) -----------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word bands::enter
sm_tick_tab:    .word bands::tick
sm_exit_tab:    .word bands::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    jsr input_init
    ; ---- enter the boot scene (id 0 = bands) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    ; Bit 0 is what makes the PPU latch $4218 every VBlank, and `input_read`
    ; waits out the busy window before reading it.
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI enable + auto-joypad
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
