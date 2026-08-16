; =============================================================================
; racer — the channel-pressure rail
; =============================================================================
; ROM skeleton. Every RAM/VRAM/CGRAM address and channel comes from the
; allocator's emitted includes; hardware I/O ports are the only literals
; (no_literals-gated). The one scene lives in a `.scope` so its claims stay
; distinct symbols, matching every other rail's shape even though there is
; nothing here to be distinct FROM — a single-scene rail that skipped the
; scope would be the odd one out for a reader, and scene_mgr's dispatch tables
; want the qualified names anyway.
.p816
.smart

.define SF_HDR_TITLE "NITRO RACER"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "world.inc"                ; world geometry constants (not addresses)
.include "racer_move.inc"           ; GENERATED — heading LUT + physics equates
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
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
.include "mode7_floor.asm"
; split_band's binding contract — the five symbols it carries no default for.
; THIS RAIL'S TOP BAND HAS NO BG3: Mode 7 has one BG layer plus OBJ, so there
; is no text renderer to give a canvas to, and the sky band shows BG2
; (sky_band's ramp) + OBJ (the speed bar) alone. That is the third distinct
; binding of one splitter — microzero's $16/$11 enables BG3 it does have,
; split_h_demo's $04/$01 enables neither BG2 nor OBJ.
SB_LINES    = HUD_LINES         ; the seam: sky band rows 0..43
SB_MODE_TOP = $09               ; Mode 1, BG3 priority high
SB_MODE_BOT = $07               ; Mode 7 (the floor)
SB_TM_TOP   = $12               ; BG2 (sky_band's ramp) + OBJ (the speed bar)
SB_TM_BOT   = $11               ; BG1 (the Mode 7 floor) + OBJ (the kart)
.include "split_band.asm"
.include "oam_sprites.asm"

; --- global ROM blobs (allocator-claimed; the .asserts refuse drift) --------
; The `.repeat` counts are DERIVED (ES_R_<NAME>_CHUNKS) — a hand-written count
; is a build refusal, and microzero's main.asm carries the incident that rule
; was written from.
; ORDER AND SEGMENT ARE THE ALLOCATOR'S, NOT A CHOICE. The report puts
; tad_export in window 1 (it is PINNED there — vendor/rom's cfg maps
; AUDIO_DATA0 to ROM1 by name), so this rail's world chunks start at BANK2
; rather than microzero's BANK1, and everything after shifts with them. The
; `.assert`s below are what turn a wrong guess into a build refusal instead
; of a ROM that reads the neighbouring blob's bytes.
.repeat ES_R_POSES_AB_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 10)
.ident(.sprintf("poses_ab_t%d", PI)):
    .incbin "poses_ab.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_ab_t%d", PI)) = .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", PI)), error, "poses_ab chunk bank drifted"
.endrepeat
.repeat ES_R_POSES_CD_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 12)
.ident(.sprintf("poses_cd_t%d", PI)):
    .incbin "poses_cd.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_cd_t%d", PI)) = .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", PI)), error, "poses_cd chunk bank drifted"
.endrepeat

; The day-night keyframes lead this window: rc_grad walks them with ONE DASB
; bank and 16-bit pointer arithmetic, so the whole 5,376-byte set has to sit
; inside a single LoROM window at a known base (rc_grad.asm asserts the base;
; this is where the bytes land). The rest of the window follows in the
; allocator's packing order — a `.incbin` out of order fails the addr assert.
.segment "BANK14"
sky_keys_bin:
    .incbin "racer_sky_keys.bin"
.assert ^sky_keys_bin = ES_R_SKY_KEYS_BANK, error, "sky_keys bank drifted from allocator claim"
.assert .loword(sky_keys_bin) = ES_R_SKY_KEYS_ADDR, error, "sky_keys addr drifted from allocator claim"
kart_chr_bin:
    .incbin "racer_kart_chr.bin"
.assert ^kart_chr_bin = ES_R_KART_CHR_ROM_BANK, error, "kart_chr bank drifted from allocator claim"
.assert .loword(kart_chr_bin) = ES_R_KART_CHR_ROM_ADDR, error, "kart_chr addr drifted from allocator claim"
col_flags_bin:
    .incbin "col_flags.bin"
.assert ^col_flags_bin = ES_R_COL_FLAGS_BANK, error, "col_flags bank drifted from allocator claim"
.assert .loword(col_flags_bin) = ES_R_COL_FLAGS_ADDR, error, "col_flags addr drifted from allocator claim"
kart_pal_bin:
    .incbin "racer_kart_pal.bin"
.assert ^kart_pal_bin = ES_R_KART_PAL_ROM_BANK, error, "kart_pal bank drifted from allocator claim"
.assert .loword(kart_pal_bin) = ES_R_KART_PAL_ROM_ADDR, error, "kart_pal addr drifted from allocator claim"

; world map: bank-tiled chunks, 64 rows x 512 B each. THE BYTES ARE THIS
; RAIL'S OWN CIRCUIT (tools/gen_racer_assets.course_map) behind world_rom's
; claim — which world backs the claim is the game's binding, the same way
; race.asm binds WHICH world the streaming kernels read. The tile vocabulary
; is gen_m7_assets', so the shared floor CHR/palette and the DERIVED
; col_flags table serve this map unchanged.
.repeat ES_R_WORLD_MAP_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 2)
.ident(.sprintf("world_map_t%d", WI)):
    .incbin "racer_world_map.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("world_map_t%d", WI)) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)), error, "world chunk bank drifted"
.assert .loword(.ident(.sprintf("world_map_t%d", WI))) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)), error, "world chunk addr drifted"
; Both halves of the chunk obligation mode7_stream.asm and col_map.asm name in
; their BINDING CONTRACT blocks, discharged here for this rail: the banks must
; be CONSECUTIVE (every reader spells the address `T0_BANK + index`) and the
; chunks must sit at the SAME in-window offset (one base serves all of them).
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)) = ES_R_WORLD_MAP_T0_BANK + WI, error, "world chunk banks are not consecutive"
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)) = ES_R_WORLD_MAP_T0_ADDR, error, "world chunks are not window-aligned alike"
.endrepeat
.segment "CODE"

; --- the scene (before the dispatch tables: ca65 scopes resolve backward) ---
.include "scenes/race.asm"

; --- sm_nmi_hook: per-frame VBlank work (after the scene: scope refs resolve)
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow (kart + speed bar)
    jsr race::persp_commit_origin
    jsr race::stream_nmi_dispatch
    ; Pose retarget in VBlank: desired -> applied, index tables + DASB shadows
    ; re-stamped BEFORE the core's shadow MVN applies them. Steering writes the
    ; DESIRED heading on the main thread; retargeting is a VBlank act because
    ; the tables HDMA reads next frame must not change under it mid-frame.
    lda f:race::US_HEADING_AP_LONG
    cmp f:race::US_HEADING_LONG
    beq :+
    lda f:race::US_HEADING_LONG
    sta f:race::US_HEADING_AP_LONG
    rep #$20
    .a16
    and #63                     ; the A8 load left the high byte stale
    jsr race::persp_set_pose
    sep #$20
    .a8
:   .a8                         ; every path in (both branch arms + fall-through)
    .i16
    rts

; --- scene dispatch tables (manifest order: race=0) -------------------------
sm_enter_tab:   .word race::enter
sm_tick_tab:    .word race::tick
sm_exit_tab:    .word race::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- audio boot (TAD contract, tad-audio.inc): interrupts are DISABLED
    ; here by construction — init.inc leaves NMI off and $4200 is written only
    ; below — the S-SMP is still in the IPL, and the init chain above puts us
    ; past the 40-scanline post-reset minimum. Tad_Init runs ONCE per power-on;
    ; the song load is ASYNC and Tad_Process streams it during the opening
    ; frames. The music keeps playing THROUGH the pause — it is the one thing
    ; a freeze-frame must not freeze.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- enter the only scene under forced blank --------------------------
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
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    ; audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids ISR
    ; calls). It runs OUTSIDE the pause gate on purpose — a paused race keeps
    ; its music, which is what START promises: a freeze, not a stop.
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
