; =============================================================================
; sf_irq.inc — opt-in scanline (V-count) IRQ support (macro library)
; =============================================================================
; The kit is NMI-only by default. This layer adds the OPT-IN path for a
; mid-frame V-count IRQ — the seam-write mechanism proven by the
; seam_irq_trial rail (byte-identical to an HDMA-origin control):
;
;   1. VECTOR — define `SF_IRQ_VECTOR = my_handler` BEFORE `.include
;      "header.inc"` (forward reference is fine). Default stays NMI_STUB;
;      existing ROMs are byte-identical.
;   2. ENABLE — NMITIMEN ($4200) is WRITE-ONLY and SHARED (bit 7 NMI, bits
;      5/4 V/H-count IRQ, bit 0 auto-joypad). ALL writers go through the
;      SHADOW_NMITIMEN compose shadow (engine_state.inc, coldstart-cleared
;      to 0) via sf_nmitimen_or / sf_nmitimen_and — never blind-store $4200.
;   3. UNMASK — the coldstart SEI masks IRQ; sf_irq_arm ends with CLI.
;      An armed-but-masked IRQ line also makes every `wai` fall through
;      immediately (measured: ~28k wakes/s) — arm late, arm unmasked.
;
; THE WAI-GATE CONTRACT (H1 — load-bearing for every consumer): with a
; mid-frame IRQ armed, `wai` wakes at the seam as WELL as at NMI (measured
; ~2 wakes/frame). A loop that does its VBlank table writes right after a
; bare `wai` will write MID-FRAME after the IRQ wake. Gate the loop on the
; NMI counter instead — sleep until it actually advanced:
;
;       lda f:$7E0000 + $E010       ; NMI counter (or your frame flag)
;       sta f:$7E0000 + PREV_NMI
;   @sleep:
;       wai
;       lda f:$7E0000 + $E010
;       cmp f:$7E0000 + PREV_NMI
;       beq @sleep                  ; woke on the seam IRQ -> sleep again
;       ; --- VBlank window: table writes are safe here ---
;
; HANDLER RULES (seam_irq_trial's measured discipline):
;   * End in RTI; ack by reading TIMEUP ($4211) — the IRQ line stays
;     asserted (and re-fires / spins wai) until the ack.
;   * Preserve everything you touch (rep #$20 / pha ... rep #$20 / pla —
;     hardware saved P; rti restores it).
;   * Registers written from the handler must respect the ValueLatch guard:
;     write-twice pairs only inside a blanking window. The proven shape:
;     pre-arm general-DMA channels (mode $03 keeps per-register lo/hi order
;     through the shared Mode-7 ValueLatch), spin on the HBlank flag
;     ($4212 bit 6, `bit` + `bvc`), then ONE MDMAEN write — the per-line
;     HDMA event pauses the CPU first, so the fire never overlaps HDMA.
;   * VTIME counts INTERNAL scanlines and content line L draws during
;     internal scanline L+1 — for a band seam at content line S, arm
;     VTIME = S (NOT S-1; one-line-early fire corrupts content line S-1).
;
; H+V note: an H+V trigger (bit $10 + HTIME) gains nothing once the handler
; spin-gates on the HBlank flag (measured identical), and WITHOUT the gate
; it risks firing MDMAEN into the dot-274..276 zone where general-DMA start
; meets the HDMA trigger. Ship V-only + the spin gate.
; =============================================================================

.ifndef SF_IRQ_INC
SF_IRQ_INC = 1

; -----------------------------------------------------------------------------
; sf_nmitimen_or bits — OR bits into the NMITIMEN shadow and store it.
; -----------------------------------------------------------------------------
; The ONLY sanctioned way to raise $4200 bits (NMI $80, V-IRQ $20, H-IRQ $10,
; auto-joypad $01). Long-addressed shadow: no DB assumption.
; WIDTH-RISK: enters A16/I16 (kit safe-default), A8 inside, exits A16.
.macro sf_nmitimen_or sf_bits
    sep #$20
    .a8
    lda f:$7E0000 + SHADOW_NMITIMEN
    ora #(sf_bits)
    sta f:$7E0000 + SHADOW_NMITIMEN
    sta $4200
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_nmitimen_and mask — AND the NMITIMEN shadow with a mask and store it.
; -----------------------------------------------------------------------------
; Clear bits with the INVERTED mask (e.g. sf_nmitimen_and $DF drops V-IRQ).
; WIDTH-RISK: enters A16/I16, A8 inside, exits A16.
.macro sf_nmitimen_and sf_mask
    sep #$20
    .a8
    lda f:$7E0000 + SHADOW_NMITIMEN
    and #(sf_mask)
    sta f:$7E0000 + SHADOW_NMITIMEN
    sta $4200
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_irq_arm_v vtime — arm the V-count IRQ at an INTERNAL scanline + unmask.
; -----------------------------------------------------------------------------
;   vtime   internal scanline (0..261). For a band seam at content line S,
;           pass S (content line S-1 draws during internal scanline S; the
;           handler's writes land in its trailing HBlank).
; Composes bit $20 through the shadow (NMI/auto-joypad bits preserved) and
; executes CLI. Call at boot AFTER the handler's data is staged, typically
; right after (or before) the NMI enable — order between them is free.
; WIDTH-RISK: enters A16/I16, toggles A8/A16 inside, exits A16.
.macro sf_irq_arm_v sf_vtime
    rep #$20
    .a16
    lda #(sf_vtime)
    sta $4209                   ; VTIME lo+hi ($4209/$420A)
    sf_nmitimen_or $20
    cli
.endmacro

; -----------------------------------------------------------------------------
; sf_irq_disarm — drop both IRQ-enable bits (V $20 + H $10) via the shadow.
; -----------------------------------------------------------------------------
; NMI/auto-joypad bits are preserved. Reads TIMEUP once so a pending level
; is acked (a still-asserted line would spin every wai).
; WIDTH-RISK: enters A16/I16, A8 inside, exits A16.
.macro sf_irq_disarm
    sf_nmitimen_and $CF
    sep #$20
    .a8
    lda $4211                   ; ack any pending TIMEUP level
    rep #$20
    .a16
.endmacro

.endif
