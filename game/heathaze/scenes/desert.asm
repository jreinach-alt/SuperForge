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
    ; SEEDED AT THE THRESHOLD, not at zero: the first tick then queues the
    ; wind bed immediately instead of opening the scene on 1.4 s of still air
    ; while the counter fills. One initial value rather than a second queue
    ; site that would have to say the same thing.
    lda #HZ_WIND_PHASES
    sta z:US_WIND
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
    jsr hz_weather                  ; ...and the bed the same advance paces
    ; ---- B: latch the flat control ----------------------------------------
    lda z:ES_INP_PRESS
    and #JOY_B
    beq @no_toggle
    lda z:US_FLAT
    eor #1
    sta z:US_FLAT
    jsr hz_show
    ; THE CUE YOU HEAR, AND IT NEEDS NO LATCH. This arm is reached only on
    ; ES_INP_PRESS's B bit, which the `input` feature publishes as the RISING
    ; edge (cur & ~prev), so it runs at most once per press however long B is
    ; held. ES_INP_CUR is one token away and would sound on every held frame;
    ; that is the mistake this site invites and what
    ; tests/test_heathaze_audio.py's cadence case is aimed at.
    ;
    ; `select` rather than a sound of its own: the vocabulary already calls it
    ; "a confirm, a gate accepting" (assets/audio/README) and `racer` uses it
    ; for exactly this — a control toggling, not a thing happening in a world.
    ; The shimmer going flat is a SETTING changing.
    lda #SFX::select
    jsr hz_sfx
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

; --- hz_sfx: queue the sound effect named in A ------------------------------
; CONTRACT desert::hz_sfx
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the SFX:: id (its low byte; every id in the enum is < 256)
;   out:      the request held in the ring, or counted as a full-ring loss
;   clobbers: A, N, Z, C
;   tail:     rts
;
; WIDTH-RISK: sf_sfx_queue_c declares `entry: A8 I16 DB=0` and this rail's
; scene code is A16 throughout, so the sep/rep pair is load-bearing and lives
; HERE rather than at each of the two call sites — one place to be wrong
; instead of two. X and Y survive it (the centred entry point exists precisely
; so a pan does not have to be loaded into X), which is why neither caller
; saves an index around a cue.
hz_sfx:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_sfx"
    sep #$20
    .a8
    jsr sf_sfx_queue_c
    rep #$20
    .a16
    rts

; --- hz_weather: keep the wind bed alive -----------------------------------
; CONTRACT desert::hz_weather
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       US_TSH — this frame's region-corrected phase advance, already
;             computed by the tick's one TS_STEP
;   out:      US_WIND advanced; on the frame it crosses HZ_WIND_PHASES, that
;             many phases taken back off it and a `wind` request queued
;   clobbers: A, N, Z, C
;   tail:     rts
;
; A SOUND EFFECT IS A ONE-SHOT. `wind` is 212 SFX ticks of noise — 1.696 s at
; the driver's fixed 125 Hz sound-effect clock — and then it is over, so an
; AMBIENCE is something this routine makes out of it by asking again before
; the last one has finished. HZ_WIND_PHASES carries the arithmetic and the
; argument for the number.
;
; THE UNIT IS PHASES, WHICH IS WHY THERE IS NO SECOND TS_STEP HERE. US_TSH is
; already the scaled advance; accumulating it gives a counter that reaches the
; threshold in the same WALL-CLOCK time on PAL as on NTSC, for one add. A raw
; frame count would need its own accumulator and its own base and would then
; have to be kept in step with the one above it.
;
; SUBTRACT, DO NOT ZERO. The advance is 0 or 1 phase a frame at this rate so
; the two spellings agree today — but zeroing throws away the remainder, and a
; rail that later raised HZ_PHASE_BASE past one phase a frame would start
; losing a fraction of a gust every cycle with nothing to show for it.
hz_weather:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_weather"
    clc
    lda z:US_WIND
    adc z:US_TSH
    cmp #HZ_WIND_PHASES
    bcc @hold
    sbc #HZ_WIND_PHASES             ; carry is SET on this arm — cmp left it so
    sta z:US_WIND
    lda #SFX::wind
    jsr hz_sfx
    rts
@hold:
    .a16
    .i16
    sta z:US_WIND
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
