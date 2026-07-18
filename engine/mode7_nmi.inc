; =============================================================================
; mode7_nmi.inc — Mode 7 Register Commit During VBlank (Phase 16-0a)
; =============================================================================
; Included after Phase 4 PPU register writes in nmi_handler.asm.
; Only active when ES_M7_PV_ACTIVE is set.
;
; Writes Brad-port shadow state to hardware during VBlank:
;   - M7SEL ($211A): screen repeat / flip (from ES_M7_PV_M7SEL)
;   - M7X ($211F): rotation origin X (from ES_M7_PV_NMI_M7X, computed by pv_set_origin)
;   - M7Y ($2120): rotation origin Y (from ES_M7_PV_NMI_M7Y)
;
; Matrix parameters M7A-M7D ($211B-$211E) and scroll registers M7HOFS/M7VOFS
; ($210D/$210E) are driven by HDMA (per-scanline, configured by pv_rebuild)
; and by SHADOW_BG1HOFS/VOFS (main thread, written by pv_set_origin). This
; inc only writes the registers HDMA does NOT cover.
;
; Context:
;   - NMI handler has DP=$0100, DB=$00, A=8-bit at entry
;   - All ES_M7_PV_* offsets are DP-relative from ENGINE_STATE_BASE ($0100)
;   - This code falls through to @mode7_nmi_skip when Mode 7 is inactive
;
; Phase 16-0a change: old code wrote ES_M7_CENTER_X/Y (dropped symbols);
; this file now writes pv_set_origin's computed M7X/M7Y instead.
;
; Must NOT have .p816/.smart (included into parent NMI handler).
; Prerequisites: engine_state.inc included, .a8 mode active.
;
; Cross-ref: engine_state.inc (ES_M7_PV_* offsets), mode7_engine.asm,
;            mode7_hdma.asm (pv_set_origin computes nmi_m7x/m7y),
;            nmi_handler.asm (Phase 4)
; =============================================================================

    ; --- Mode 7 Brad-port VBlank Register Commit ---
    ; Check if Brad-port Mode 7 is active (ES_M7_PV_ACTIVE at DP offset $BA)
    lda ES_M7_PV_ACTIVE
    beq @mode7_nmi_skip

    ; Write M7SEL ($211A) — screen repeat and flip settings
    lda ES_M7_PV_M7SEL
    sta $211A

    ; Write rotation origin X ($211F) — write-twice register, low then high.
    ; Values written by pv_set_origin on the main thread during RESOLVE phase.
    lda ES_M7_PV_NMI_M7X
    sta $211F
    lda ES_M7_PV_NMI_M7X + 1
    sta $211F

    ; Write rotation origin Y ($2120) — write-twice register
    lda ES_M7_PV_NMI_M7Y
    sta $2120
    lda ES_M7_PV_NMI_M7Y + 1
    sta $2120

@mode7_nmi_skip:
