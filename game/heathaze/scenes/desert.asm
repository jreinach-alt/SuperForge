; =============================================================================
; desert scene — the world, shimmering
; =============================================================================
; The scene the effect runs in. Everything visible here that is not in the
; title scene comes from ONE HDMA channel driving ONE register per scanline:
; `haze`'s `hzwarp` claim on BG1HOFS across lines 120..224.
;
; THE PER-FRAME WORK IS TWO ROUTINE CALLS AND ONE STORE. `hz_advance` moves
; the phase on by this frame's region-corrected step; `hz_nmi_commit` writes
; the channel's A1T high byte in VBlank. There is no table build, no VRAM
; write and no CPU cost during active display at all — the picture is bent by
; the PPU while it is being drawn.
;
; B TOGGLES THE SHIMMER, and it is not a convenience. A per-scanline
; displacement is only measurable against the same picture UNDISPLACED, so the
; flat state is this rail's control: the concept sheet's "before distortion /
; after heat haze" pair, on one binary, in one scene, with nothing else
; different between them.
;
; FLAT IS A TABLE, NOT A DISARM. hz_rom's 65th blob is a complete HDMA table
; whose every displacement is zero, so the channel stays armed and identically
; configured in both states and exactly one variable moves. Disarming the
; channel would change two things at once, and a two-variable comparison
; cannot attribute what it shows.
.scope desert
.include "engine_state_desert.inc"  ; GENERATED — this scene's map
.include "haze.asm"                 ; scene-scoped: its claims are this
                                    ;   scene's, so its symbols resolve here

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    jsr hz_arm_bg                   ; the world: CHR, map, palette group 0
    jsr hz_text_arm                 ; BG3: the font and a cleared tilemap
    jsr hz_display                  ; BGMODE, the layer bases, the offsets
    jsr hz_arm                      ; the warp channel, the seed, the phase
    stz z:US_FLAT                   ; shimmering on entry
    stz z:US_TSH_ACC                ; the timebase's carried fraction
    stz z:US_TSH
    sep #$20
    .a8
    lda #ES_V_HZ_CHR_NBA
    sta a:$210B                     ; BG12NBA — BG2's nibble is 0: this rail
                                    ;   has no BG2 layer, so no BG2 CHR base
                                    ;   exists to name and none is read (TS
                                    ;   composes $00 and TM's bg2 bit is clear)
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 1*32 + 3)
    lda #.loword(s_hint)
    jsr hz_puts
    ; ---- the composed screen/blend state ----------------------------------
    sep #$20
    .a8
    lda #ES_SCR_DESERT_TM
    sta a:$212C
    lda #ES_SCR_DESERT_TS
    sta a:$212D
    lda #ES_SCR_DESERT_CGWSEL
    sta a:$2130                     ; `blend_off`'s composed off state — this
    lda #ES_SCR_DESERT_CGADSUB      ;   scene arms no blend, and composing the
    sta a:$2131                     ;   off state is what stops it inheriting
                                    ;   one across an edge
    ; ---- arm the channel ---------------------------------------------------
    ; hz_arm filled the shadow slots; this is the enable bit, which that
    ; routine's contract says the CALLER supplies. The bit's number comes from
    ; the allocator, not from a hand-written 1.
    lda z:ES_SM_NMI+2
    ora #((1 << ES_H_HZWARP_CH) | (1 << ES_H_HZHORIZ_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) -----------------
; In/out: A16/I16, DB=0.
;
; TS_STEP IS EXPANDED ONCE, AT THE TOP, and its output is read by the one add
; that consumes it. The step is in WHOLE phases; the fraction it could not
; publish this frame is carried in the accumulator to the next, which is what
; makes a PAL run advance the same shimmer through the same 64 phases in the
; same wall-clock time as an NTSC one.
tick:
    .a16
    .i16
    TS_STEP z:US_TSH_ACC, HZ_PHASE_BASE
    sta z:US_TSH
    ; ---- the shimmer advances every frame, flat or not ---------------------
    ; UNCONDITIONALLY, and that is what makes the toggle a control: flattening
    ; the picture changes ONE thing (which table the channel reads) and leaves
    ; the animation's position alone, so un-flattening resumes rather than
    ; restarts.
    lda z:US_TSH
    jsr hz_advance
    ; ---- B: latch the flat control ----------------------------------------
    lda z:ES_INP_PRESS
    and #JOY_B
    beq @no_toggle
    lda z:US_FLAT
    eor #1
    sta z:US_FLAT
    jsr hz_show
@no_toggle:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    sep #$20
    .a8
    SM_SWITCH "DESERT", "TITLE"
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked.
;
; THE CHANNEL IS NOT DISARMED HERE, and that is the design rather than an
; omission: scene_mgr's enter contract clears HDMAEN across every switch, so
; the channel stops at the edge whatever this routine does. What does NOT stop
; is the VALUE the channel last wrote into BG1HOFS — which is why the title
; scene composes `hz_flat` and writes the port itself.
exit:
    .a16
    .i16
    rts

.segment "RODATA"
s_hint:  .byte "B FLAT   START TITLE", 0
.segment "CODE"
.endscope
