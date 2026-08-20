; =============================================================================
; boss_saucer — the SCALING boss: a lunging flying saucer, a beam, and a theme
; =============================================================================
; The static-affine boss shape again — the saucer IS the Mode 7 BG layer,
; scaled as one rigid image by a single uniform matrix, with the gunship, the
; beam column, the HP HUD and the player's shots composited over it as
; sprites — but here SCALING is the headline motion. The saucer LUNGES at the
; camera (the matrix zooms it from a far speck to a screen-filling disc) and
; at the apex fires a vertical BEAM down a column locked to where the player
; was standing. Strafe out of the column during the telegraph; hold A to shoot
; the saucer down; mind your 3 HP.
;
; THE FIRST REUSE OF `m7_track`. Every animated
; state's matrix comes from a BAKED track through the shared player — the
; reveal, BOTH halves of every lunge, the hold's idle spin, and the death
; recede — so there is no runtime trig, no multiply and no HDMA channel, and
; m7_affine's own scale-1.0 LUT is composed but never indexed at runtime (its
; shadow + NMI commit are what this rail reuses). Nothing in m7_track, pool,
; m7_affine or audio is touched.
;
; NO RING-CAPTURE BEAT, and that is measured: this fight holds its heading at
; 0 throughout — rotation is OFF in the fight, because scaling IS the motion —
; so the death recede enters from the known angle 0 and its baked start matches
; exactly. The boss rail's capture beat exists for a fight that rotates freely;
; this one does not.
;
; AUDIO IS COMPOSED, NOT CLAIMED (AGENTS.md's occupant pattern). `Tad_Init`
; runs once here in the boot block with NMI off by construction; `Tad_Process`
; runs once per frame from the MAIN LOOP and OUTSIDE the pause gate, because a
; paused fight keeps its music. Scenes queue SFX through the `Tad_*` API and
; claim nothing.
;
; Controls:  D-pad left/right strafe · A (hold) fire · START pause.  With no
; input the rail runs its whole cycle autonomously — the beam locks onto a
; stationary gunship every lunge, which is the deterministic LOSE path, and
; the RESULT->RESET loop re-arms the reveal.

.p816
.smart

.define SF_HDR_TITLE "SAUCER DOWN"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "saucer.inc"               ; the rail's own vocabulary

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

; --- the ROM claim sites ----------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build; the
; PRESENCE side is `make rom-unbacked` (docs/37).
;
; THE WINDOW ASSIGNMENT IS THE ALLOCATOR'S, NOT A CHOICE. `tad_export` is
; PINNED to window 1 (vendor/rom's cfg maps AUDIO_DATA0 to ROM1 by name), so
; sau_map — 32,768 B, one WHOLE window, which is what keeps its single enter
; DMA from crossing a bank boundary — takes window 2, and everything else
; packs largest-first into window 3. The .asserts make that agreement
; checkable rather than assumed.
.segment "BANK2"
sau_map_bin:
    .incbin "sau_map.bin"
.assert ^sau_map_bin = ES_R_SAU_MAP_BANK, error, "sau_map bank drifted from allocator claim"
.assert .loword(sau_map_bin) = ES_R_SAU_MAP_ADDR, error, "sau_map addr drifted from allocator claim"

.segment "BANK3"
; Packing order by (-bytes, name): m7_lut (2,048) leads, then sau_sprite_chr
; (1,536), sau_ring (1,026), the two 246 B ramps (death < reveal), the two
; 186 B lunge halves (appr < retr), then sau_sprite_pal (64 B — TWO OBJ
; palettes since the star field got its own) and last sau_pal (32 B). The two
; palettes used to be a 32/32 tie broken by name; they are ordered by SIZE
; now, and the .asserts below are what turned that into a build failure
; instead of two blobs quietly swapping places.
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
sau_sprite_chr_bin:
    .incbin "sau_sprite_chr.bin"
.assert ^sau_sprite_chr_bin = ES_R_SAU_SPRITE_CHR_BANK, error, "sau_sprite_chr bank drifted from allocator claim"
.assert .loword(sau_sprite_chr_bin) = ES_R_SAU_SPRITE_CHR_ADDR, error, "sau_sprite_chr addr drifted from allocator claim"
sau_ring_bin:
    .incbin "sau_ring.bin"
.assert ^sau_ring_bin = ES_R_SAU_RING_BANK, error, "sau_ring bank drifted from allocator claim"
.assert .loword(sau_ring_bin) = ES_R_SAU_RING_ADDR, error, "sau_ring addr drifted from allocator claim"
sau_death_bin:
    .incbin "sau_death.bin"
.assert ^sau_death_bin = ES_R_SAU_DEATH_BANK, error, "sau_death bank drifted from allocator claim"
.assert .loword(sau_death_bin) = ES_R_SAU_DEATH_ADDR, error, "sau_death addr drifted from allocator claim"
sau_reveal_bin:
    .incbin "sau_reveal.bin"
.assert ^sau_reveal_bin = ES_R_SAU_REVEAL_BANK, error, "sau_reveal bank drifted from allocator claim"
.assert .loword(sau_reveal_bin) = ES_R_SAU_REVEAL_ADDR, error, "sau_reveal addr drifted from allocator claim"
sau_appr_bin:
    .incbin "sau_appr.bin"
.assert ^sau_appr_bin = ES_R_SAU_APPR_BANK, error, "sau_appr bank drifted from allocator claim"
.assert .loword(sau_appr_bin) = ES_R_SAU_APPR_ADDR, error, "sau_appr addr drifted from allocator claim"
sau_retr_bin:
    .incbin "sau_retr.bin"
.assert ^sau_retr_bin = ES_R_SAU_RETR_BANK, error, "sau_retr bank drifted from allocator claim"
.assert .loword(sau_retr_bin) = ES_R_SAU_RETR_ADDR, error, "sau_retr addr drifted from allocator claim"
sau_sprite_pal_bin:
    .incbin "sau_sprite_pal.bin"
.assert ^sau_sprite_pal_bin = ES_R_SAU_SPRITE_PAL_BANK, error, "sau_sprite_pal bank drifted from allocator claim"
.assert .loword(sau_sprite_pal_bin) = ES_R_SAU_SPRITE_PAL_ADDR, error, "sau_sprite_pal addr drifted from allocator claim"
sau_pal_bin:
    .incbin "sau_pal.bin"
.assert ^sau_pal_bin = ES_R_SAU_PAL_BANK, error, "sau_pal bank drifted from allocator claim"
.assert .loword(sau_pal_bin) = ES_R_SAU_PAL_ADDR, error, "sau_pal addr drifted from allocator claim"
.segment "CODE"

; --- pool (the mechanism; the arrays are sau_obj's claim) -------------------
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
; the lunge: a whole dive arrives as one baked word pair per frame while the
; beam's sprites arrive in the same VBlank.
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
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- audio boot (TAD contract, tad-audio.inc): interrupts are DISABLED
    ; here by construction — init.inc leaves NMI off and $4200 is written only
    ; below — the S-SMP is still in the IPL, and the init chain above puts us
    ; past the 40-scanline post-reset minimum. Tad_Init runs ONCE per power-on
    ; (re-calling hardlocks), which is why the rail's own soft reset is a
    ; masked battle re-init and never a re-boot; the song load is ASYNC and
    ; Tad_Process streams it during the reveal.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
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
    ; audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids ISR
    ; calls). OUTSIDE the pause gate on purpose — the gate lives inside
    ; arena::tick, so a paused fight still pumps the driver and still plays.
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
