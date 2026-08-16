; =============================================================================
; platformer_stream — the two-axis streaming platformer
; =============================================================================
; A side-view level four screens wide AND tall, streamed over a 64x64 BG1 ring.
;
; ONE SCENE, and it is the only single-scene rail in the set — not an omission:
; a streaming rail has no title screen by design and boots straight into
; gameplay. `scene_mgr` is still composed, because every feature in the tree is
; written against its enter contract (forced blank, HDMAEN cleared, NMITIMEN
; zeroed across the switch) and its NMI hook. What this rail does not use is the
; phase machine: there is nowhere to go.
;
; =============================================================================
; THE COMPOSITION, COMPLETE
; =============================================================================
; Every feature this rail declares is now bound: `pfs_bg` owns the layer,
; `pfs_stream` owns the ring's contents on both axes, `pfs_logic` the player
; and the follow camera, `col_map` the world-space collision the physics reads,
; `rgb_gradient` the dusk ramp.
;
; ONE UPLOAD PATH FOR THE RING, and it is the streamer's. The scene's own
; enter-time fill is gone: `pfs_stream_arm` fills all 64x64 slots by calling
; the per-frame staging kernel 64 times under the enter forced blank, so the
; boot picture and every streamed picture are produced by the same code and a
; bug in the ring addressing cannot hide behind a correct boot frame.
;
; NO AUDIO. `tad_rom` is not in this game's globals — there is no Tad_Init, no
; Tad_Process pump and no TAD object in the link.

.p816
.smart

.define SF_HDR_TITLE "PLATFORMER STREAM"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "pfs_world.inc"            ; GENERATED — the level's geometry, emitted
                                    ;   beside the blobs so the ASM and the
                                    ;   bytes cannot disagree about the world
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP from its
; shadow and runs sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition game.toml declares) -
.include "scene_mgr.asm"
.include "input.asm"
.include "fade.asm"
.include "oam_sprites.asm"

; =============================================================================
; THE ROM CLAIM SITES
; =============================================================================
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; level — which for `pfs_flat` is a plausible-looking world streamed out of the
; neighbouring blob, with every other gate green.
;
; THE ORDER IS THE ALLOCATOR'S, not a preference: `place_rom` packs
; largest-first from window 1, so the two 32 KB tilemaps take a whole window
; each and everything small lands in window 3 behind the 16 KB collision blob.
; Read it off build/pfs/allocation_report.txt; the .asserts refuse any drift.
;
; NONE of these is `bank_tiled`. Every claim is a single chunk — the largest is
; exactly one 32,768 B LoROM window — so no consumer derives a bank as
; BASE + i and none owes the consecutive-banks assert that `mode7_stream` and
; `col_map`'s tiled blobs document.

; --- the level, COLUMN-major: col N's 128 words at N*256 --------------------
; The layout a streamed COLUMN reads contiguously. Exactly one window, which is
; what keeps a producer's source pointer from ever crossing a LoROM bank seam
; (on LoROM that is not a carry but a discontinuity: $01:FFFF -> $02:8000).
.segment "BANK1"
pfs_flat_bin:
    .incbin "pfs_flat.bin"
.assert ^pfs_flat_bin = ES_R_PFS_FLAT_BANK, error, "pfs_flat bank drifted from allocator claim"
.assert .loword(pfs_flat_bin) = ES_R_PFS_FLAT_ADDR, error, "pfs_flat addr drifted from allocator claim"

; --- the same level, ROW-major: row M's 128 words at M*256 ------------------
; The layout a streamed ROW reads contiguously — and the one the boot ring fill
; below uses, because the fill is 64 rows of 64 columns.
.segment "BANK2"
pfs_flat_row_bin:
    .incbin "pfs_flat_row.bin"
.assert ^pfs_flat_row_bin = ES_R_PFS_FLAT_ROW_BANK, error, "pfs_flat_row bank drifted from allocator claim"
.assert .loword(pfs_flat_row_bin) = ES_R_PFS_FLAT_ROW_ADDR, error, "pfs_flat_row addr drifted from allocator claim"

; --- everything else, in the window the packer put it in --------------------
.segment "BANK3"
pfs_col_bin:
    .incbin "pfs_col.bin"
.assert ^pfs_col_bin = ES_R_PFS_COL_BANK, error, "pfs_col bank drifted from allocator claim"
.assert .loword(pfs_col_bin) = ES_R_PFS_COL_ADDR, error, "pfs_col addr drifted from allocator claim"
pfs_hero_chr_bin:
    .incbin "pfs_hero_chr.bin"
.assert ^pfs_hero_chr_bin = ES_R_PFS_HERO_CHR_BANK, error, "pfs_hero_chr bank drifted from allocator claim"
.assert .loword(pfs_hero_chr_bin) = ES_R_PFS_HERO_CHR_ADDR, error, "pfs_hero_chr addr drifted from allocator claim"
pfs_chr_bin:
    .incbin "pfs_chr.bin"
.assert ^pfs_chr_bin = ES_R_PFS_CHR_BANK, error, "pfs_chr bank drifted from allocator claim"
.assert .loword(pfs_chr_bin) = ES_R_PFS_CHR_ADDR, error, "pfs_chr addr drifted from allocator claim"
pfs_flags_bin:
    .incbin "pfs_flags.bin"
.assert ^pfs_flags_bin = ES_R_PFS_FLAGS_BANK, error, "pfs_flags bank drifted from allocator claim"
.assert .loword(pfs_flags_bin) = ES_R_PFS_FLAGS_ADDR, error, "pfs_flags addr drifted from allocator claim"
pfs_hero_pal_bin:
    .incbin "pfs_hero_pal.bin"
.assert ^pfs_hero_pal_bin = ES_R_PFS_HERO_PAL_BANK, error, "pfs_hero_pal bank drifted from allocator claim"
.assert .loword(pfs_hero_pal_bin) = ES_R_PFS_HERO_PAL_ADDR, error, "pfs_hero_pal addr drifted from allocator claim"
pfs_pal_bin:
    .incbin "pfs_pal.bin"
.assert ^pfs_pal_bin = ES_R_PFS_PAL_BANK, error, "pfs_pal bank drifted from allocator claim"
.assert .loword(pfs_pal_bin) = ES_R_PFS_PAL_ADDR, error, "pfs_pal addr drifted from allocator claim"
; ...and `grad_tabs` follows immediately, from inside the scene scope: it is
; rgb_gradient's own claim and therefore a SCENE symbol, so its .incbin cannot
; live up here. scenes/play.asm re-opens BANK3 and the packer's order holds.

.segment "CODE"

; --- the scene (before the dispatch tables: ca65 resolves scopes backward) --
.include "scenes/play.asm"

; --- sm_nmi_hook: per-frame VBlank work ------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; UNCONDITIONAL, all three, and one scene is why: there is no other scene whose
; registers could be written under it — so `mode7_explore`'s scene-id gate on
; its own drain (its scene DP is reused by a second scene, and an armed count
; there would be the interior's state) has no counterpart to guard here. The
; OAM commit is `oam_sprites`' every-frame shadow DMA; the streaming drain
; empties whatever `pfs_stream_tick` staged; the camera commit publishes
; BG1HOFS/BG1VOFS from the DP words the streamer derived its resident window
; from.
;
; HOOK ORDER IS FREE, and that was CHECKED rather than assumed.
; `pfs_stream_nmi_dispatch` programs its own VMAIN ($2115) and both VMADD
; halves ($2116) per slot; `oam_nmi_dma` drives $2102/$2103/$4300-block OAM
; transfers and touches neither; `pfs_bg_nmi_commit` writes only $210D/$210E.
; So no writer here inherits another's port state. The order below is
; mode7_explore's for the same reason it has one there: none.
;
; DELIBERATELY SHORT. sm_nmi_core MVNs its 128-byte channel shadow to $4300
; AFTER the hook returns, so a hook that overruns VBlank lands that block during
; active display. The drain is two DMAs per staged slot and at most four slots
; — 512 B in 8 transfers, 8.6% of the rail's VBlank byte pin — which is why
; pfs_stream clamps the slot count per axis rather than chasing the camera.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    jsr play::pfs_stream_nmi_dispatch   ; drain the staged row/column slots
    jsr play::pfs_bg_nmi_commit     ; BG1HOFS/BG1VOFS from the camera words
    rts

; --- scene dispatch table (one scene: play = 0) ----------------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen.
;
; The tables are one entry wide and `sm_request` is never called — there is
; nowhere to go. They exist anyway because `sm_tick` indexes `sm_tick_tab` by
; the scene id in ES_SM_CTL on every frame, and because a rail that grows a
; title screen should add a row rather than invent a dispatcher.
SCENE_PLAY = 0

sm_enter_tab:   .word play::enter
sm_tick_tab:    .word play::tick
sm_exit_tab:    .word play::exit

; --- MAIN: boot ------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
;
; The dawn-in is set up by omission: sm_init zeroes ES_SM_NMI, whose +1 byte is
; the INIDISP shadow, so the first armed VBlank commits $00 — display ON,
; brightness 0 — and the scene's enter arms `fade`, whose tick walks the shadow
; 0 -> 15. Nothing here writes $2100 and nothing may: scene_mgr commits INIDISP
; from that shadow every armed frame, so a bare write would be reverted by the
; next VBlank (scene_mgr's enter-time-INIDISP hazard).
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all            ; the whole shadow written before its first DMA
                                ;   — power-on WRAM is random, and this is the
                                ;   write-before-read contract for it, not a
                                ;   to-be-safe fill (rule 5)
    ; `pfs_stream`'s `[init] zero` contract, AS CODE. `[init] zero` HAS NO GATE
    ; — the allocator emits it as a comment and nothing checks
    ; that anybody honoured it, which is how `mosaic` shipped declaring it with
    ; nothing behind it. Both claims are genuinely read-before-write (the first
    ; tick differences against LAST_TX/LAST_TY; the drain reads PFS_BUSY before
    ; anything writes it), so under Mesen's random power-on RAM an unzeroed
    ; PFS_BUSY parks the drain forever and an unzeroed count DMAs staging WRAM
    ; into the live ring on frame 1.
    jsr play::pfs_stream_init
    ; ---- enter the one scene, under forced blank -------------------------
    ldx #(SCENE_PLAY * 2)
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad, fade in from black -----------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    ; WIDTH-RISK: `fade_start_in` is an A8 routine (fade.asm:17 states the
    ; contract) and this call site is the only thing that can honour it — a
    ; cross-file caller/callee width contract is invisible to width-check in
    ; both directions (CLAUDE.md rule 6). Called in A16 its two-byte
    ; `lda #1` eats the following opcode as the immediate's high byte and
    ; execution walks off into the middle of an instruction; the ROM builds,
    ; the gate is clean, and the screen stays black. That is what this rail
    ; shipped for one build before the render was looked at.
    jsr fade_start_in
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
