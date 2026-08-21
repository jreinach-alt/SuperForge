; =============================================================================
; split_h_irq_grad_demo — THE APPLIED SEAM-IRQ CASE: a freed channel, spent
; =============================================================================
; A horizontal split of one wrapping checker plane: the top 112 scanlines are
; camera 1's view (COOL stripe), the bottom 112 camera 2's (WARM stripe, one
; 256-px stripe east). Both bands stream ONE fixed-angle pose through two
; whole-frame INDIRECT matrix channels; band 2's four origin registers arrive
; by a V-count IRQ at internal scanline 112 firing two pre-armed GP-DMA
; channels in the trailing HBlank, not by an origin HDMA pair.
;
; `seam_irq_trial` proved that mechanism renders byte-identically to
; the classic origin pair. THIS rail spends what it frees: the two channels
; that leave the HDMAEN mask pay for a per-scanline COLDATA gradient over the
; whole frame — fixed-colour ADD on BG1, one byte per line, on ONE channel via
; the plane-select trick. And both cameras MOVE, at different speeds, so the
; origin the IRQ delivers is a live per-frame value rather than a constant.
;
; Five channels claimed of eight; THREE in the HDMAEN mask (matrix pair +
; gradient), three free — and that census is the allocator's own report line
; rather than a comment anyone has to keep true by hand.
;
; CONTROLS (variant ROMs, each registered so the build actually makes them):
;   -DSHG_NO_GRAD      the gradient's FLIP control: no table, no channel bit,
;                      no colour math. The rendered blue channel must go flat.
;                      Also the subject side of the gold comparison below,
;                      because a gradient row would differ trivially.
;   -DSHG_HDMA_ORIGIN  the GOLD control: the classic origin channel pair
;                      through the same claims. Implies -DSHG_NO_GRAD (it has
;                      no freed channel to spend), so it is compared against
;                      the -DSHG_NO_GRAD build — and the two must render
;                      BYTE-IDENTICAL with the cameras in motion.
;
; ZERO INPUT, by design: both cameras pan on their own, at different speeds.
; The -D ROMs are COMPARISON builds — each removes one mechanism so the frame
; shows what that mechanism contributed — not alternative ways to drive it.
;
; TWO CONTROLS DELIBERATELY NOT BUILT, each with its reason:
;   -DFREEZE          a STILL cross-ROM comparison needs a freeze to be
;                     well-defined. Here `Machine` lands on an ABSOLUTE frame by
;                     construction and both builds run the same tick, so the
;                     MOVING comparison is well-defined and STRONGER (a frozen
;                     gold cannot see a stamper that drops a live value). The
;                     define survives as a one-line switch in shg_cam.asm for
;                     a future bisect; no ROM, no registration sites.
;   -DIRQ_INTERLEAVE  the write-twice ValueLatch tear control. A falsify plant
;                     does the same job at ZERO registration cost and does it
;                     harder — it requires named tests to go RED. It is
;                     `stage-byte-interleave` in
;                     tools/plants/split_h_irq_grad_demo.py.
;
; NOTHING HERE IS HAND-PLACED. There is no runtime HDMA channel allocator, no
; fixed argument block and no hand-picked WRAM: channel numbers, DMAP/BBAD
; bytes, table addresses, ROM banks and the debug counters all come from the
; allocator's emitted symbols, and `no_literals` refuses the build if any is
; written down instead.

.p816
.smart

; The gold control has no freed channel to spend, so it cannot carry the
; gradient: -DSHG_HDMA_ORIGIN implies -DSHG_NO_GRAD.
.ifdef SHG_HDMA_ORIGIN
.ifndef SHG_NO_GRAD
SHG_NO_GRAD = 1
.endif
.endif

.define SF_HDR_TITLE "SEAM IRQ GRADIENT"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "engine_state_split.inc"   ; GENERATED — the split scene's map
                                    ; (unscoped: one scene, file-scope symbols)

.ifndef SHG_HDMA_ORIGIN
SF_IRQ_VECTOR = shg_seam_irq        ; the $FFEE opt-in (vendor/rom/header.inc)
                                    ; — MUST precede the include; the forward
                                    ; label ref is fine. The control build
                                    ; exercises the NMI_STUB default.
.endif
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank,
                                    ; SEI — IRQ stays masked until MAIN's cli

.segment "CODE"

; The vectors header.inc points at. NMI hands straight to the scene manager's
; core; the seam IRQ vector is shg_cam's handler via SF_IRQ_VECTOR above.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition) ------------------
.include "scene_mgr.asm"
.include "fade.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the emitted claim; the
; PRESENCE side is `make rom-unbacked` (docs/37). The blobs are the sh2
; generator's oracle-gated output, shared with `split_h_2p_demo`: the map and
; the poses1 pair ARE that rail's assets, linked here rather than regenerated.
; There is deliberately no palette blob: shg_floor writes its five blue-zero
; words by CPU, and that is a metric decision rather than an economy
; (shg_floor.asm).
.segment "BANK1"
shg_map_bin:
    .incbin "sh2_map.bin"
.assert ^shg_map_bin = ES_R_SHG_MAP_BANK, error, "shg_map bank drifted from allocator claim"
.assert .loword(shg_map_bin) = ES_R_SHG_MAP_ADDR, error, "shg_map addr drifted from allocator claim"

.segment "BANK2"
; ORDER IS THE ALLOCATOR'S (place_rom packs by (-bytes, name)); the per-site
; .asserts turn a re-sort into a build failure rather than blobs quietly
; reading each other's bytes.
shg_pose_ab_bin:
    .incbin "sh2_pose1_ab.bin"
.assert ^shg_pose_ab_bin = ES_R_SHG_POSE_AB_BANK, error, "shg_pose_ab bank drifted from allocator claim"
.assert .loword(shg_pose_ab_bin) = ES_R_SHG_POSE_AB_ADDR, error, "shg_pose_ab addr drifted from allocator claim"
shg_pose_cd_bin:
    .incbin "sh2_pose1_cd.bin"
.assert ^shg_pose_cd_bin = ES_R_SHG_POSE_CD_BANK, error, "shg_pose_cd bank drifted from allocator claim"
.assert .loword(shg_pose_cd_bin) = ES_R_SHG_POSE_CD_ADDR, error, "shg_pose_cd addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "irq.asm"
.include "shg_floor.asm"
.include "shg_cam.asm"
.ifndef SHG_NO_GRAD
.include "shg_grad.asm"
.endif

; --- the scene ------------------------------------------------------------
.include "scenes/split.asm"

; --- sm_nmi_hook: per-frame VBlank work ------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
; ONE call: cam_vblank re-establishes band 1's origin registers (the seam fire
; replaced them mid-frame) and re-stages the band-2 bytes from the positions
; the tick advanced. The seam pair's A1T/DAS re-arm is NOT here — sm_nmi_core's
; own shadow MVN runs after this hook returns, and that MVN is the re-arm path
; (shg_cam.asm's header; the DAS-is-single-shot lesson). The gradient needs
; nothing per frame: its table is static and its channel is a plain HDMA one.
sm_nmi_hook:
    .a8
    .i16
    jsr cam_vblank                  ; A8 in, A8 out — its own width contract
    rts

; --- scene dispatch tables (manifest order: split=0) -----------------------
; AFTER the scene include: ca65 resolves a scope's members only once the scope
; has been seen.
sm_enter_tab:   .word split::enter
sm_tick_tab:    .word split::tick
sm_exit_tab:    .word split::exit

; --- MAIN: boot ------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off, I set.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    ; ---- enter the boot scene (id 0 = split) under forced blank -----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- the ARM SEQUENCE (irq.asm's contract): timer -> enable -> unmask -
    ; Timer first (a stale VTIME under a live enable can latch an arbitrary
    ; line); enable through NMITIMEN under sm_display's scene_writes; cli LAST
    ; — an armed line under SEI makes every wai fall through (~28k wakes/s
    ; measured; Mesen2 SnesCpu.Shared.h:336-341). NEVER in scene enter:
    ; scene_mgr rewrites NMITIMEN to $81 AFTER enter returns
    ; (`@switch`'s $81 restore) and strips the V-IRQ bit.
.ifndef SHG_HDMA_ORIGIN
    lda #SHG_VTIME
    jsr irq_arm_v                   ; VTIME = the seam
.endif
    sep #$20
    .a8
.ifndef SHG_HDMA_ORIGIN
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
; inlined because the counter is the H1 measurement and scene_mgr's own routine
; cannot carry rail instrumentation. With the
; seam IRQ armed, wai returns ~2x per frame (the seam wake + the NMI wake); the
; gate sends the seam wake back to sleep, so the tick's position advance and
; the hook's table writes never interleave with a mid-frame wake. Keep
; textually in step with scene_mgr's `sm_frame_sync`.
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
    lda f:SHG_CNT_WAKE_LONG
    inc a
    sta f:SHG_CNT_WAKE_LONG         ; raw wake counter — the H1 evidence
    sep #$20
    .a8
    lda z:ES_SM_NMI
    bne @sleep                      ; still armed: the wake was the seam IRQ
    rep #$20
    .a16
    bra @loop
