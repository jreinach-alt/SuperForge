; =============================================================================
; mode7_hdma_allocator.asm — Phase 17-13 Mode 7 HDMA channel ownership wrapper
; =============================================================================
; Wraps the 17-0a HDMA allocator primitives (hdma_alloc_bootstrap,
; hdma_release) with M7_OWNED_MASK bookkeeping. M7_OWNED_MASK is the
; single source of truth for "which HDMA channels does Mode 7 currently
; own?" — read by the engine NMI handler to gate per-channel shadow →
; hardware commits (engine/nmi_handler.asm Phase 5).
;
; The default Mode 7 channel set (CH5+CH6 = $60) matches Brad's
; M7_PV_HDMA_BITMASK = $60 in mode7_hdma.asm. If Brad's enabled-channel
; scope ever changes (it shouldn't — byte-exact CC BY 4.0), update both
; constants in lockstep.
;
; API:
;   mode7_hdma_alloc_request   — bootstrap-pin Mode 7's default channels +
;                                set M7_OWNED_MASK. Called from mode7_init.
;   mode7_hdma_alloc_release   — release Mode 7's default channels + clear
;                                M7_OWNED_MASK. Called from mode7_disable.
;   mode7_hdma_claim_extra     — additive pin + M7_OWNED_MASK |= mask.
;                                Used by engine_mode7_hud (CH3) and future
;                                16-3-3 (CH7 fog) / 16-3-5 (CH4 clouds).
;   mode7_hdma_release_extra   — additive release + M7_OWNED_MASK &= ~mask.
;                                Used by engine_mode7_hud_off.
;
; All entry points: A16/I16 on entry and exit, .smart-aware width
; annotations throughout. Callers' DB preserved by hdma_alloc_bootstrap /
; hdma_release.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc, engine/hdma_alloc.asm.
; =============================================================================

; Mirror of M7_PV_HDMA_BITMASK from engine/mode7_hdma.asm. Kept here so
; the wrapper file is self-describing and doesn't depend on Brad's
; include order. Update both files in lockstep if Brad's enabled-channel
; scope ever changes.
M7_HDMA_DEFAULT_MASK = $60      ; CH5+CH6 (Brad 16-0a scope)


; -----------------------------------------------------------------------------
; mode7_hdma_alloc_request — Pin the default Mode 7 channels.
;
; Bootstrap-pins CH5+CH6 in the allocator with effect_id =
; HDMA_EFFECT_MODE7_AB and sets M7_OWNED_MASK accordingly.
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. Toggles to A8 internally to
; write M7_OWNED_MASK byte. hdma_alloc_bootstrap saves/restores DB.
; -----------------------------------------------------------------------------
mode7_hdma_alloc_request:
    rep #$30
    .a16
    .i16
    lda #M7_HDMA_DEFAULT_MASK
    ldx #HDMA_EFFECT_MODE7_AB
    jsr hdma_alloc_bootstrap
    sep #$20
    .a8
    lda #M7_HDMA_DEFAULT_MASK
    sta M7_OWNED_MASK
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; mode7_hdma_alloc_release — Release the default Mode 7 channels.
;
; Releases CH5+CH6 in the allocator and clears their bits from
; M7_OWNED_MASK. Other Mode-7-owned channels (CH3 HUD, CH4 clouds,
; CH7 fog) are released by their own hud_off / sprint-specific paths.
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. A8 toggle bracketed.
; -----------------------------------------------------------------------------
mode7_hdma_alloc_release:
    rep #$30
    .a16
    .i16
    lda #M7_HDMA_DEFAULT_MASK
    jsr hdma_release
    sep #$20
    .a8
    lda M7_OWNED_MASK
    and #(.lobyte(~M7_HDMA_DEFAULT_MASK))
    sta M7_OWNED_MASK
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; mode7_hdma_claim_extra — Additively pin extra channels for Mode 7.
;
; Used when Mode 7 takes ownership of channels beyond the default
; matrix pair: CH3 BGMODE (Phase 17-11 HUD overlay), CH4 TM (16-3-5
; cloud parallax), CH7 COLDATA (16-3-3 horizon fog).
;
; Idempotent — re-claiming an already-pinned bit is a no-op
; (hdma_alloc_bootstrap OR's the mask).
;
; Entry: A16 = channel mask (low byte), X16 = effect_id (low byte).
; WIDTH-RISK: entry A16/I16; exit A16/I16. A8 toggle bracketed.
; -----------------------------------------------------------------------------
mode7_hdma_claim_extra:
    rep #$30
    .a16
    .i16
    pha                             ; save mask for OR into M7_OWNED_MASK
    jsr hdma_alloc_bootstrap        ; A=mask, X=effect_id (passes through)
    pla                             ; restore mask
    sep #$20
    .a8
    ora M7_OWNED_MASK
    sta M7_OWNED_MASK
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; mode7_hdma_release_extra — Release extra Mode-7-owned channels.
;
; Pair of mode7_hdma_claim_extra. Releases the masked channels in the
; allocator and clears their bits from M7_OWNED_MASK. Idempotent on
; already-released channels.
;
; Entry: A16 = channel mask (low byte) to release.
; WIDTH-RISK: entry A16/I16; exit A16/I16. A8 toggle bracketed.
; -----------------------------------------------------------------------------
mode7_hdma_release_extra:
    rep #$30
    .a16
    .i16
    pha                             ; save mask for AND-NOT into M7_OWNED_MASK
    jsr hdma_release                ; A=mask (passes through)
    pla                             ; restore mask
    sep #$20
    .a8
    eor #$FF                        ; ~mask (low byte)
    and M7_OWNED_MASK
    sta M7_OWNED_MASK
    rep #$20
    .a16
    rts
