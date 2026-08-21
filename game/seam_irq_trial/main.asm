; =============================================================================
; seam_irq_trial — the SCANLINE-IRQ DEBUT: band 2's Mode 7 origin by seam IRQ
; =============================================================================
; A horizontal split of one wrapping checker plane: the top 112 scanlines are
; camera 1's view (COOL stripe), the bottom 112 camera 2's (WARM stripe, one
; 256-px stripe east). Both bands stream ONE fixed-angle pose through two
; whole-frame INDIRECT matrix channels; the ONLY thing that changes at the
; seam is the four origin bytes — and on this build they arrive by a V-count
; IRQ at internal scanline 112 firing two pre-armed GP-DMA channels in the
; trailing HBlank, not by an origin HDMA pair. The H1 (wai double-wake) and
; H2 (seam write window) proofs run INSIDE the engine spine — scene_mgr's
; NMI, the frame handshake, the sm_hdma shadow MVN — which is the rail's real
; deliverable: proved against a bare-metal closure they would be true only of
; that closure.
;
; CONTROLS (variant ROMs):
;   -DSIT_HDMA_ORIGIN  the GOLD control: the classic origin channel pair
;                      through the same claims — default vs control
;                      framebuffer BYTE-IDENTICAL on an absolute frame.
;   -DSIT_MISTIME      the NON-VACUITY control: VTIME=60 — the same fire in
;                      scanline 60's HBlank, so content lines 60..111 render
;                      warm and the SAME metric flips.
;
; ZERO INPUT, by design: the trial is autonomous, and the -D ROMs are
; CONTROLS, not pilots — nothing here is meant to be steered.
;
; NOTHING BELOW IS HAND-PICKED. Channel numbers, DMAP/BBAD bytes, table
; addresses, ROM banks and the debug counters all come from the allocator's
; emitted symbols, and `no_literals` refuses the build if any is written down
; instead. A trial whose subject is timing cannot also be carrying a hand-laid
; WRAM map that only its author knows is collision-free.

.p816
.smart

.define SF_HDR_TITLE "SEAM IRQ TRIAL"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "engine_state_seam.inc"    ; GENERATED — the seam scene's map
                                    ; (unscoped: one scene, file-scope symbols)

.ifndef SIT_HDMA_ORIGIN
SF_IRQ_VECTOR = sit_seam_irq        ; the $FFEE opt-in (vendor/rom/header.inc)
                                    ; — MUST precede the include; the forward
                                    ; label ref is fine. The control build
                                    ; exercises the NMI_STUB default.
.endif
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank,
                                    ; SEI — IRQ stays masked until MAIN's cli

.segment "CODE"

; The vectors header.inc points at. NMI hands straight to the scene manager's
; core; the seam IRQ vector is sit_cam's handler via SF_IRQ_VECTOR above.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition) ------------------
.include "scene_mgr.asm"
.include "fade.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the emitted claim;
; the PRESENCE side is `make rom-unbacked` (docs/37). The blobs are the sh2
; generator's oracle-gated output, shared byte-for-byte with split_h_2p_demo:
; two rails measuring the same seam should not be measuring two maps.
.segment "BANK1"
sit_map_bin:
    .incbin "sh2_map.bin"
.assert ^sit_map_bin = ES_R_SIT_MAP_BANK, error, "sit_map bank drifted from allocator claim"
.assert .loword(sit_map_bin) = ES_R_SIT_MAP_ADDR, error, "sit_map addr drifted from allocator claim"

.segment "BANK2"
; ORDER IS THE ALLOCATOR'S (place_rom packs by (-bytes, name)); the per-site
; .asserts turn a re-sort into a build failure rather than blobs quietly
; reading each other's bytes.
sit_pose_ab_bin:
    .incbin "sh2_pose1_ab.bin"
.assert ^sit_pose_ab_bin = ES_R_SIT_POSE_AB_BANK, error, "sit_pose_ab bank drifted from allocator claim"
.assert .loword(sit_pose_ab_bin) = ES_R_SIT_POSE_AB_ADDR, error, "sit_pose_ab addr drifted from allocator claim"
sit_pose_cd_bin:
    .incbin "sh2_pose1_cd.bin"
.assert ^sit_pose_cd_bin = ES_R_SIT_POSE_CD_BANK, error, "sit_pose_cd bank drifted from allocator claim"
.assert .loword(sit_pose_cd_bin) = ES_R_SIT_POSE_CD_ADDR, error, "sit_pose_cd addr drifted from allocator claim"
sit_pal_bin:
    .incbin "sh2_pal.bin"
.assert ^sit_pal_bin = ES_R_SIT_PAL_BANK, error, "sit_pal bank drifted from allocator claim"
.assert .loword(sit_pal_bin) = ES_R_SIT_PAL_ADDR, error, "sit_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "irq.asm"
.include "sit_floor.asm"
.include "sit_cam.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/seam.asm"

; --- sm_nmi_hook: per-frame VBlank work ------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
; ONE call: sit_vblank re-establishes band 1's origin registers (the seam
; fire replaced them mid-frame) and re-stamps the staged band-2 bytes. The
; seam pair's A1T/DAS re-arm is NOT here — sm_nmi_core's own shadow MVN runs
; after this hook returns, and that MVN is the re-arm path (sit_cam.asm's
; header; the DAS-is-single-shot lesson riding the engine's mechanism).
sm_nmi_hook:
    .a8
    .i16
    jsr sit_vblank                  ; A8 in, A8 out — its own width contract
    rts

; --- scene dispatch tables (manifest order: seam=0) ------------------------
; AFTER the scene include: ca65 resolves a scope's members only once the
; scope has been seen.
sm_enter_tab:   .word seam::enter
sm_tick_tab:    .word seam::tick
sm_exit_tab:    .word seam::exit

; --- MAIN: boot ------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off, I set.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    ; ---- enter the boot scene (id 0 = seam) under forced blank ------------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- the ARM SEQUENCE (irq.asm's contract): timer -> enable -> unmask -
    ; Timer first (a stale VTIME under a live enable can latch an arbitrary
    ; line); enable through NMITIMEN under sm_display's scene_writes; cli
    ; LAST — an armed line under SEI makes every wai fall through (~28k
    ; wakes/s measured; SnesCpu.Shared.h:336-341).
.ifndef SIT_HDMA_ORIGIN
    lda #SIT_VTIME
    jsr irq_arm_v                   ; VTIME = the seam (or 60 under MISTIME)
.endif
    sep #$20
    .a8
.ifndef SIT_HDMA_ORIGIN
    lda #((1 << 7) | (1 << 5))      ; NMITIMEN: NMI + V-count IRQ
.else
    lda #(1 << 7)                   ; the control: NMI only, stub vector
.endif
    sta a:$4200
    rep #$20
    .a16
    cli                             ; coldstart SEI ends HERE, armed

; --- the frame loop: gated wai + the H1 wake counter -----------------------
; This IS sm_frame_sync's handshake (arm ES_SM_NMI, sleep until the NMI
; consumed it) with the raw-wake counter added between wai and the gate —
; inlined because the counter is the H1 measurement and scene_mgr's own
; routine cannot carry one rail's instrumentation. With the
; seam IRQ armed, wai returns ~2x per frame (the seam wake + the NMI wake);
; the gate sends the seam wake back to sleep, so table writes stay in the
; VBlank window. Keep textually in step with scene_mgr's `sm_frame_sync`.
@loop:
    .a16
    .i16
    jsr sm_tick
    jsr fade_tick
    sep #$20
    .a8
    lda #1
    sta z:ES_SM_NMI                 ; arm: the NMI consumes exactly one frame
@sleep:
    .a8
    wai                             ; wakes on the seam IRQ AND on NMI
    rep #$20
    .a16
    lda f:SIT_CNT_WAKE_LONG
    inc a
    sta f:SIT_CNT_WAKE_LONG         ; raw wake counter — the H1 evidence
    sep #$20
    .a8
    lda z:ES_SM_NMI
    bne @sleep                      ; still armed: the wake was the seam IRQ
    rep #$20
    .a16
    bra @loop
