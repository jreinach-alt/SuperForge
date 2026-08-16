; =============================================================================
; split_h_2p_demo — two Mode 7 cameras, one world, one frame
; =============================================================================
; A HORIZONTAL split screen. The top 112 scanlines are camera 1's view of a
; wrapping checker plane, the bottom 112 are camera 2's, and the two cameras
; hold INDEPENDENT world positions that pan at different rates. Neither band
; runs a live perspective solve: each streams a ROM-resident per-scanline pose
; table straight through INDIRECT HDMA, so the whole per-frame work is TEN
; stores in VBlank — eight to re-stamp the two origin tables, two to advance the
; positions. That is what leaves budget for two cameras at 60 fps, and it is the
; entire claim of the rail. (A store COUNT, not a measured cycle figure — no
; cycle number is claimed here.)
;
; TWO PADS. Pad 1 steers camera 1, pad 2 steers camera 2: D-pad Left/Right
; steps that camera's heading one pose per frame HELD, B drives it forward
; 2 px/frame. `-D SH2_AUTOCAM` swaps the pads for an autonomous rotate+drive
; when a hands-off capture is wanted; the two are exclusive and sh2_cam's
; cam_input header says why.
;
; ONE SCENE, no edges, mirroring split_v_fight's and m7_dungeon's shape.
; game.toml's header carries every feature deliberately NOT composed and names
; the allocator check that would have refused each of them anyway.
;
; NOTHING BELOW IS HAND-PICKED. The channel numbers, the DMAP and BBAD bytes,
; the table addresses and the ROM banks are all emitted by the allocator from
; the three feature.toml declarations, and `no_literals` refuses the build if
; any of them is written down instead. A rail this dense in channels and banks
; is exactly the one where a hand-laid map is collision-free only until it
; isn't.

.p816
.smart

.define SF_HDR_TITLE "SPLIT H 2P"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. The generated header suggests wrapping it in
; `.scope <id>` for a multi-scene ROM so two scenes' symbols cannot collide;
; this rail has exactly one scene and both scene-scoped features resolve its
; symbols from file scope, so a wrapper here would only hide them.
.include "engine_state_split.inc"   ; GENERATED — the split scene's map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

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
.include "input2.asm"
.include "oam_sprites.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37): a claim with no .incbin here would
; reserve the window and let whatever the linker left there be read as art —
; and on this rail "art" includes the two pose tables the matrix channels feed
; straight into M7A-M7D, so the failure mode would be a floor with no horizon.
;
; sh2_map is 32,768 B — one WHOLE LoROM window — so it gets a bank to itself and
; the single DMA that uploads it cannot cross a bank boundary. BANK1 falls out
; of the rail being silent: `tad_rom` PINS window 1 (vendor/rom's linker cfg
; maps segment AUDIO_DATA0 to ROM1 by name), so a rail that composed audio
; would push this map to BANK2. Without it the map is the largest free claim
; and takes window 1. See game.toml's audio block for why the rail is silent.
.segment "BANK1"
sh2_map_bin:
    .incbin "sh2_map.bin"
.assert ^sh2_map_bin = ES_R_SH2_MAP_BANK, error, "sh2_map bank drifted from allocator claim"
.assert .loword(sh2_map_bin) = ES_R_SH2_MAP_ADDR, error, "sh2_map addr drifted from allocator claim"

; --- the 256-heading pose set: FOUR bank slices per channel ----------------
; Slice k holds headings 64k..64k+63 at 448 B each (28,672 B), and pose h is
; addressed at RUNTIME as
;
;     ptr  = <slice base loword> + (h & 63) * 448
;     bank = <slice 0's bank>    + (h >> 6)
;
; which is only true if every slice starts at its window's ORIGIN and the four
; slices are in CONSECUTIVE windows in order. Both are properties of the
; allocation, so both are .asserted here rather than assumed: the per-slice
; bank/addr asserts pin each one, and sh2_cam.asm's own asserts tie the
; +1-per-slice arithmetic and the shared loword to the emitted symbols.
;
; The ORDER of the windows is the allocator's, not a preference: place_rom
; packs free claims by (-bytes, name), so the map takes window 1 and the eight
; equal-sized slices take 2..9 in name order — AB before CD, s0..s3. The
; 4,096 B of slack left in the first slice's window is where the 1,024-byte
; move LUT and the 10-byte palette pack, which is why those two live in BANK2
; beside `ab_s0` rather than in a window of their own.
.segment "BANK2"
sh2_pose256_ab_s0_bin:
    .incbin "sh2_pose256_ab_s0.bin"
.assert ^sh2_pose256_ab_s0_bin = ES_R_SH2_POSE256_AB_S0_BANK, error, "sh2_pose256_ab_s0 bank drifted from allocator claim"
.assert .loword(sh2_pose256_ab_s0_bin) = ES_R_SH2_POSE256_AB_S0_ADDR, error, "sh2_pose256_ab_s0 addr drifted from allocator claim"
sh2_sp_chr_bin:
    .incbin "sh2_sp_chr.bin"
.assert ^sh2_sp_chr_bin = ES_R_SH2_SP_CHR_BANK, error, "sh2_sp_chr bank drifted from allocator claim"
.assert .loword(sh2_sp_chr_bin) = ES_R_SH2_SP_CHR_ADDR, error, "sh2_sp_chr addr drifted from allocator claim"
sh2_move256_bin:
    .incbin "sh2_move256.bin"
.assert ^sh2_move256_bin = ES_R_SH2_MOVE256_BANK, error, "sh2_move256 bank drifted from allocator claim"
.assert .loword(sh2_move256_bin) = ES_R_SH2_MOVE256_ADDR, error, "sh2_move256 addr drifted from allocator claim"
sh2_sp_sincos_bin:
    .incbin "sh2_sp_sincos.bin"
.assert ^sh2_sp_sincos_bin = ES_R_SH2_SP_SINCOS_BANK, error, "sh2_sp_sincos bank drifted from allocator claim"
.assert .loword(sh2_sp_sincos_bin) = ES_R_SH2_SP_SINCOS_ADDR, error, "sh2_sp_sincos addr drifted from allocator claim"

.segment "BANK3"
; ORDER IS THE ALLOCATOR'S, not a preference: place_rom packs the free
; claims by (-bytes, name), so the sites here follow build/sh2/allocation_report.txt
; exactly. Adding sh2_ents and sh2_way re-sorted this window, and the per-site
; .asserts are what turned that into a build failure rather than eight blobs
; quietly reading each other's bytes.
sh2_pose256_ab_s1_bin:
    .incbin "sh2_pose256_ab_s1.bin"
.assert ^sh2_pose256_ab_s1_bin = ES_R_SH2_POSE256_AB_S1_BANK, error, "sh2_pose256_ab_s1 bank drifted from allocator claim"
.assert .loword(sh2_pose256_ab_s1_bin) = ES_R_SH2_POSE256_AB_S1_ADDR, error, "sh2_pose256_ab_s1 addr drifted from allocator claim"
sh2_ents_bin:
    .incbin "sh2_ents.bin"
.assert ^sh2_ents_bin = ES_R_SH2_ENTS_BANK, error, "sh2_ents bank drifted from allocator claim"
.assert .loword(sh2_ents_bin) = ES_R_SH2_ENTS_ADDR, error, "sh2_ents addr drifted from allocator claim"
sh2_sp_vk_bin:
    .incbin "sh2_sp_vk.bin"
.assert ^sh2_sp_vk_bin = ES_R_SH2_SP_VK_BANK, error, "sh2_sp_vk bank drifted from allocator claim"
.assert .loword(sh2_sp_vk_bin) = ES_R_SH2_SP_VK_ADDR, error, "sh2_sp_vk addr drifted from allocator claim"
sh2_way_bin:
    .incbin "sh2_way.bin"
.assert ^sh2_way_bin = ES_R_SH2_WAY_BANK, error, "sh2_way bank drifted from allocator claim"
.assert .loword(sh2_way_bin) = ES_R_SH2_WAY_ADDR, error, "sh2_way addr drifted from allocator claim"
sh2_sp_recip_hi_bin:
    .incbin "sh2_sp_recip_hi.bin"
.assert ^sh2_sp_recip_hi_bin = ES_R_SH2_SP_RECIP_HI_BANK, error, "sh2_sp_recip_hi bank drifted from allocator claim"
.assert .loword(sh2_sp_recip_hi_bin) = ES_R_SH2_SP_RECIP_HI_ADDR, error, "sh2_sp_recip_hi addr drifted from allocator claim"
sh2_sp_recip_lo_bin:
    .incbin "sh2_sp_recip_lo.bin"
.assert ^sh2_sp_recip_lo_bin = ES_R_SH2_SP_RECIP_LO_BANK, error, "sh2_sp_recip_lo bank drifted from allocator claim"
.assert .loword(sh2_sp_recip_lo_bin) = ES_R_SH2_SP_RECIP_LO_ADDR, error, "sh2_sp_recip_lo addr drifted from allocator claim"
sh2_sp_tier_bin:
    .incbin "sh2_sp_tier.bin"
.assert ^sh2_sp_tier_bin = ES_R_SH2_SP_TIER_BANK, error, "sh2_sp_tier bank drifted from allocator claim"
.assert .loword(sh2_sp_tier_bin) = ES_R_SH2_SP_TIER_ADDR, error, "sh2_sp_tier addr drifted from allocator claim"
sh2_pal_bin:
    .incbin "sh2_pal.bin"
.assert ^sh2_pal_bin = ES_R_SH2_PAL_BANK, error, "sh2_pal bank drifted from allocator claim"
.assert .loword(sh2_pal_bin) = ES_R_SH2_PAL_ADDR, error, "sh2_pal addr drifted from allocator claim"
.segment "BANK4"
sh2_pose256_ab_s2_bin:
    .incbin "sh2_pose256_ab_s2.bin"
.assert ^sh2_pose256_ab_s2_bin = ES_R_SH2_POSE256_AB_S2_BANK, error, "sh2_pose256_ab_s2 bank drifted from allocator claim"
.assert .loword(sh2_pose256_ab_s2_bin) = ES_R_SH2_POSE256_AB_S2_ADDR, error, "sh2_pose256_ab_s2 addr drifted from allocator claim"

.segment "BANK5"
sh2_pose256_ab_s3_bin:
    .incbin "sh2_pose256_ab_s3.bin"
.assert ^sh2_pose256_ab_s3_bin = ES_R_SH2_POSE256_AB_S3_BANK, error, "sh2_pose256_ab_s3 bank drifted from allocator claim"
.assert .loword(sh2_pose256_ab_s3_bin) = ES_R_SH2_POSE256_AB_S3_ADDR, error, "sh2_pose256_ab_s3 addr drifted from allocator claim"

.segment "BANK6"
sh2_pose256_cd_s0_bin:
    .incbin "sh2_pose256_cd_s0.bin"
.assert ^sh2_pose256_cd_s0_bin = ES_R_SH2_POSE256_CD_S0_BANK, error, "sh2_pose256_cd_s0 bank drifted from allocator claim"
.assert .loword(sh2_pose256_cd_s0_bin) = ES_R_SH2_POSE256_CD_S0_ADDR, error, "sh2_pose256_cd_s0 addr drifted from allocator claim"

.segment "BANK7"
sh2_pose256_cd_s1_bin:
    .incbin "sh2_pose256_cd_s1.bin"
.assert ^sh2_pose256_cd_s1_bin = ES_R_SH2_POSE256_CD_S1_BANK, error, "sh2_pose256_cd_s1 bank drifted from allocator claim"
.assert .loword(sh2_pose256_cd_s1_bin) = ES_R_SH2_POSE256_CD_S1_ADDR, error, "sh2_pose256_cd_s1 addr drifted from allocator claim"

.segment "BANK8"
sh2_pose256_cd_s2_bin:
    .incbin "sh2_pose256_cd_s2.bin"
.assert ^sh2_pose256_cd_s2_bin = ES_R_SH2_POSE256_CD_S2_BANK, error, "sh2_pose256_cd_s2 bank drifted from allocator claim"
.assert .loword(sh2_pose256_cd_s2_bin) = ES_R_SH2_POSE256_CD_S2_ADDR, error, "sh2_pose256_cd_s2 addr drifted from allocator claim"

.segment "BANK9"
sh2_pose256_cd_s3_bin:
    .incbin "sh2_pose256_cd_s3.bin"
.assert ^sh2_pose256_cd_s3_bin = ES_R_SH2_POSE256_CD_S3_BANK, error, "sh2_pose256_cd_s3 bank drifted from allocator claim"
.assert .loword(sh2_pose256_cd_s3_bin) = ES_R_SH2_POSE256_CD_S3_ADDR, error, "sh2_pose256_cd_s3 addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
; ORDER IS A DEPENDENCY, not a preference: sh2_swarm resolves sh2_cam's camera
; DP and its move-LUT long address and m7_persp_project's mpp_mul8, and sh2_obj
; resolves sh2_swarm's entity-record layout and live count.
.include "sh2_floor.asm"
.include "sh2_cam.asm"
.include "m7_persp_project.asm"
.include "sh2_swarm.asm"
.include "sh2_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/split.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; A COMMIT WINDOW, AND ONLY A COMMIT WINDOW. Two calls, both cheap:
;
;   oam_nmi_dma  commits the OAM shadow the scene's tick built during the last
;                frame's ACTIVE DISPLAY. First, so the one DMA that must land
;                inside VBlank lands at its start.
;   cam_tick     stamps the two origin tables and the four pose pointers/banks
;                from the CURRENT state — the same state that shadow was
;                projected against — and only then advances. It runs here
;                because the HDMA init fetch for the next frame reads those
;                tables at line 0, so VBlank is the window in which a rewrite
;                cannot tear.
;
; THE CAST IS NOT PROJECTED HERE, and that is observed rather than preferred.
; It was tried: with the whole cast projected from this hook,
; sm_nmi_core's post-hook MVN of the 128-byte channel shadow into $4300 lands
; during ACTIVE DISPLAY and rewrites every channel's running HDMA state
; mid-frame — the floor speckles from that row down, with VRAM, the index
; tables and the shadow all reading back correct. Only four of the 24 markers
; fitted. The projection therefore runs in the scene TICK (scenes/split.asm),
; which is what cam_tick's stamp-then-advance order exists to make consistent:
; the tick projects the state the NEXT commit will stamp, so the sprites and
; the floor are always the same frame's.
;
; NO MEASURED CYCLE FIGURE, and none is claimed: the overrun above is an
; observation about a rendered frame, not a budget. A rail that wants to state
; headroom has to measure it.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; A8/I16, oam_sprites' contract
    jsr cam_tick                ; A8 in, A8 out — its own width contract
    rts

; --- scene dispatch tables (manifest order: split=0) -----------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow it.
sm_enter_tab:   .word split::enter
sm_tick_tab:    .word split::tick
sm_exit_tab:    .word split::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    jsr input_init
    jsr input2_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- NO AUDIO BOOT, deliberately -------------------------------------
    ; There is no `Tad_Init` / `Tad_LoadSong` here because this rail is silent:
    ; its per-frame cadence is one of the things it measures, and a driver tick
    ; every frame would perturb it. `audio` and `tad_rom` are therefore not
    ; composed and the two TAD objects are off the link. See game.toml.
    ; ---- enter the boot scene (id 0 = split) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI only ---------------------------------------------
    ; AUTO-JOYPAD ON: both pads drive a camera on this rail.
    ; Bit 0 is what makes the PPU latch $4218/$421A every
    ; VBlank, and `input_read` / `input2_read` wait out the busy window before
    ; reading them.
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI enable + auto-joypad
    rep #$20
    .a16
@loop:
    .a16
    .i16
    ; The pads are latched FIRST, immediately after sm_frame_sync returned from
    ; the VBlank the auto-read ran in — one wait on $4212 for both, and the
    ; scene tick's cam_advance is the only reader.
    jsr input_read
    jsr input2_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
