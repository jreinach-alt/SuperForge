; =============================================================================
; sf_mosaic_transition.inc — mosaic scene-wipe (macro library)
; =============================================================================
; A turnkey scene-transition WIPE for ANY kit template: arm it around a scene
; swap and it hides the swap behind a symmetric mosaic + darkness DISSOLVE —
; the outgoing scene pixelates to black, the caller's swap runs at peak (under
; forced blank), the incoming scene de-pixelates back to full brightness.
; Generalized from the RPG slice's Mode 7<->Mode 1 wipe (S4): the slice baked
; the wipe into its own NMI + hard-coded the two specific scenes; this macro is
; a STEPPER (arm + per-frame tick, like sf_bright_fade / sf_bright_fade_tick),
; drives the engine's SHADOW registers (no custom NMI), and takes the
; mid-transition scene swap as a CALLER-SUPPLIED routine — so it wipes between
; ANY two scenes.
;
; WHAT IT DOES, FRAME BY FRAME (the dissolve, locked size = 15 - brightness):
;   OUT (SF_MT_OUT_FRAMES): brightness 15->0 along a quarter-cosine ease;
;     mosaic size 0->15 (size = 15 - brightness, complementary every frame);
;     OBJ dropped (sprites have no HW mosaic). At the darkest frame the caller's
;     swap routine runs — a black frame, so no flash — then OBJ is re-dropped.
;   IN  (SF_MT_IN_FRAMES): the NEW scene brightens 0->15 along a quarter-sine
;     ease; mosaic 15->0; on the final frame mosaic clears, brightness pins to
;     full, and OBJ is restored.
;
; CAPTURE TIMING — WHEN IS THE SCREEN AT PEAK BLACK / WHEN DOES THE SWAP FIRE?
; (cite — COLDSTART_GAPS.md GAP-5: an adapter's first black-frame capture landed
;  mid-dim because this offset was undocumented.) Counting ticks from the _arm
;  call (tick #1 is the first frame AFTER arm):
;   - Peak black + the caller's swap routine both fire on the LAST OUT tick, i.e.
;     ~SF_MT_OUT_FRAMES ticks after arm (default SF_MT_OUT_FRAMES = 20, so the
;     swap frame is ~arm+20; the deepest-black window spans roughly the last few
;     OUT ticks, ~arm+16..arm+24 for the default ease). Capture your black-frame
;     screenshot there.
;   - The IN de-pixelate then runs SF_MT_IN_FRAMES ticks (default 15); the wipe
;     goes idle (sf_mosaic_transition_active == 0) at ~arm + OUT_FRAMES +
;     IN_FRAMES (~arm+35 for the defaults). Capture the settled new scene there.
;  FLAKE WARNING: a SINGLE-frame snapshot at a fixed offset is JITTERY — emulator
;  frame-park drift of ±1-2 frames slides the capture between full-black and
;  mid-dim run-to-run. Either (a) SAMPLE THE WHOLE peak window and take the
;  darkest centre pixel, or (b) use a WIDE pixel tolerance on the black assert.
;  The rpg oracle does (b): templates/rpg/oracle.json's black-frame scenario
;  uses tolerance:24 (and reaches the window by accumulating drive frames), which
;  is the blessed pattern — copy it rather than chasing an exact frame number.
;  (Deterministic captures still use frame-step, never wall-clock — see the kit
;  rule in docs/troubleshooting.md.)
;
; SHADOW-DRIVEN (the kit idiom — no custom VBlank code): the tick writes
; SHADOW_MOSAIC ($2106 shadow), SHADOW_INIDISP's brightness nibble ($2100
; shadow, forced-blank bit preserved), and SHADOW_TM ($212C shadow, the OBJ
; drop/restore); the STOCK engine NMI commits all three every VBlank. Contrast
; sf_bright_fade, which animates ONLY the INIDISP brightness; this wipe couples
; brightness + mosaic + OBJ into one dissolve.
;
; MODE 7 HDMA-TM CAVEAT (cite — audit-1 r3-rpg-template, deliverable 3): the
; SHADOW_TM OBJ-drop only hides sprites if the engine NMI's static $212C write is
; the LAST word on TM. When the active scene drives TM per-scanline via an HDMA
; channel (the Mode 7 main-screen split: sky band vs floor band on $212C), that
; HDMA OVERRIDES the SHADOW_TM OBJ bit every scanline — so the SHADOW_TM drop is
; defeated and the player/actor sprites stay visible THROUGH the dissolve, while
; the BG floor pixelates around them (a torn wipe). A Mode 7 (or any HDMA-TM)
; scene MUST therefore CULL ITS OWN ACTOR OAM at the source for the duration of
; the wipe — park the avatar + NPC OAM at Y>=$F0 (e.g. spr_clear) while
; sf_mosaic_transition_active is set, and restore them when it goes idle. The rpg
; template does exactly this (its overworld culls OAM during the OW->town wipe).
; A non-HDMA-TM scene (plain Mode 1, static $212C) needs no such cull — the
; SHADOW_TM drop suffices there.
;
; THE CALLER'S SWAP ROUTINE (the generalization point): a RTS-terminated CODE
; routine that does the actual scene reconfiguration — typically wrapped in the
; kit forced-blank bracket so the long VRAM/CGRAM rebuild is hidden:
;
;     my_swap:
;         sf_blank_enter              ; force blank + mask NMI (sf_scene_mode.inc)
;             sf_mode7_off            ; ... tear down the old scene ...
;             gfxmode #1              ; ... build the new scene ...
;             sf_blank_enter          ; (re-raise after gfxmode turns screen on)
;             sf_load_bg_chr ...      ; ... uploads under blank ...
;         sf_blank_exit               ; drop blank, re-enable NMI
;         rts
;
; The wipe calls my_swap once, at peak darkness. Pass #0 as the swap label for
; a pure flash/fade with no scene change (e.g. a damage flash).
;
; INPUT GATING (cite — kit docs/troubleshooting.md "btnp edge after
; transition"): gate player input while a wipe is in flight — read
; sf_mosaic_transition_active and skip your input dispatch when set, so the
; player can't move/act during the dissolve. The first post-swap frame's input
; edge can be stale; sample fresh edges only after the wipe goes idle.
;
; POWER-ON GOTCHA (cite — CLAUDE.md "Power-On Fidelity"): the swap routine MUST
; fully initialize the new scene's VRAM/CGRAM/OAM (under its forced blank) — the
; wipe only dissolves what the swap programs. A scene that reads uninitialized
; VRAM is broken on real hardware even though the dissolve looks fine.
;
; REQUIRES (linked into the ROM):
;   - the stock engine NMI commit path: engine_state.inc + nmi_handler.asm
;     (commits SHADOW_MOSAIC / SHADOW_INIDISP / SHADOW_TM every VBlank), and
;   - sf_mosaic_transition_data.inc (the curves + the stepper), included ONCE at
;     the BOTTOM of main.asm in CODE.
;   - (typically) sf_scene_mode.inc for the swap routine's forced-blank bracket.
;
; CLOBBER CONTRACT: arm clobbers A; tick clobbers A, X (+ the caller's swap
; routine's clobbers on the swap frame). State lives in $7E:1DD4-$1DD9
; (persistent across the wipe). Expects DB=$00 (the kit standard).
; =============================================================================

.ifndef SF_MOSAIC_TRANSITION_INC
SF_MOSAIC_TRANSITION_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_mosaic_transition_arm bg_mask, swap_label — start a mosaic scene wipe.
; -----------------------------------------------------------------------------
;   bg_mask     the $2106 affected-BG nibble (verbatim 8/16-bit operand, low
;               nibble used): $01 = BG1, $02 = BG2, $03 = BG1+BG2, $07 = +BG3.
;               Every BG the OUTGOING + INCOMING scenes display should be set so
;               the whole picture pixelates (the slice uses $03 for a Mode 7
;               ground + BG2 sky, $01 for a Mode 1 map).
;   swap_label  a BARE CODE label of an RTS-terminated swap routine (or #0 for
;               none). Called once at peak darkness. The macro stores its 16-bit
;               address; the routine must live in the same ROM bank as the
;               stepper (the kit's single-bank CODE for 32-64KB ROMs).
; Arms the OUT phase: state=OUT, timer=OUT_FRAMES, drops OBJ immediately (so the
; sprites are gone the instant the dissolve begins). Drive it with
; sf_mosaic_transition_tick each frame. Re-arming mid-wipe restarts cleanly.
; Clobbers A.
; WIDTH-RISK: enters any width; A8 for the state-byte stores; exits A16/I16.
.macro sf_mosaic_transition_arm sf_bg_mask, sf_swap
    rep #$30
    .a16
    .i16
    ; store the swap pointer (16-bit CODE address; #0 = none)
.ifblank sf_swap
    stz a:_sf_mt_swap_ptr
.else
    lda #.loword(sf_swap)
    sta a:_sf_mt_swap_ptr
.endif
    sep #$20
    .a8
    lda sf_bg_mask
    and #$0F
    sta a:_sf_mt_bg_mask
    lda #SF_MT_OUT
    sta a:_sf_mt_state
    lda #SF_MT_OUT_FRAMES
    sta a:_sf_mt_timer
    lda #$0F
    sta a:_sf_mt_bright         ; OUT starts at full brightness
    ; drop OBJ immediately (no un-pixelated sprites during the dissolve)
    lda #$00
    jsr _sf_mosaic_obj_set
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_mosaic_transition_tick — the per-frame wipe service call (put it in your
; loop). Advances the dissolve one frame; on the swap frame it JSRs the armed
; swap routine. No-op (~12-cycle fast exit) when idle — safe to leave in the
; loop permanently (the sf_bright_fade_tick convention). Call ONCE PER FRAME,
; between sf_frame_begin and sf_frame_end. Clobbers A, X (+ the swap routine's
; clobbers on the swap frame).
; WIDTH-RISK: enters any width; _sf_mosaic_step requires A8/I16 (its phase
; bodies toggle A16 only to build a clean curve index, then restore A8); the
; sep/rep is handled here so callers don't care; exits A16/I16.
.macro sf_mosaic_transition_tick
    sep #$20
    .a8
    rep #$10
    .i16
    jsr _sf_mosaic_step
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_mosaic_transition_active — A = nonzero while a wipe is in flight, 0 idle.
; -----------------------------------------------------------------------------
; Read this to GATE PLAYER INPUT during the dissolve (skip your input dispatch
; when nonzero) — the slice's input-gating pattern. The flag is the state-machine
; byte (OUT=1 / IN=2 while running, IDLE=0). Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the byte read; exits A16/I16 with the
; result in A (high byte cleared).
.macro sf_mosaic_transition_active
    rep #$30
    .a16
    .i16
    lda a:_sf_mt_state
    and #$00FF
.endmacro

.endif ; SF_MOSAIC_TRANSITION_INC
