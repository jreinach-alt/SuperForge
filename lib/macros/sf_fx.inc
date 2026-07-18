; =============================================================================
; sf_fx.inc — look-&-feel macros (macro library)
; =============================================================================
; The front door over the engine's look-&-feel builders: HDMA effects
; (parallax, gradients), color math, brightness fades, palette cycling.
; S6 groups:
;
;   PARALLAX (over hdma_engine.asm parallax bands)
;     sf_parallax_bands layer, y_split, ratio_top, ratio_bot   — arm/retune
;     sf_parallax_tick                                          — per-frame
;
;   BEND / TUNNEL (over hdma_engine.asm hdma_build_hofs_curve)
;     sf_bend           curve, amp          — arm a STATIC H bend (BGnHOFS)
;     sf_tunnel         curve, amp, speed   — arm an ANIMATED H bend (rolling)
;     sf_bend_v         curve, amp          — arm a STATIC V bend (BGnVOFS, v1.2)
;     sf_tunnel_v       curve, amp, speed   — arm an ANIMATED V bend (BGnVOFS)
;     sf_bend_phase     delta               — set/replace roll speed (0=freeze)
;     sf_bend_tick                          — per-frame service (roll + rebuild)
;     sf_bend_off                           — release the channel (hdma_off path)
;     curve selectors: SF_CURVE_SINE | SF_CURVE_PARABOLA | SF_CURVE_HORIZON
;       (_v + SF_CURVE_HORIZON = the barrel/horizon row-squash; phase/tick/off
;        are shared, axis-agnostic — confirm with sf_bend_tick on either axis)
;
;   RGB GRADIENT (over hdma_color_engine.asm COLDATA gradients)
;     sf_gradient_rgb   tr, tg, tb, br, bg, bb   — 2-stop gradient, arm
;     sf_gradient_stops addr, count              — N-stop gradient, arm
;     sf_gradient_ease  type                     — easing curve 0-3
;     sf_gradient_phase delta                    — 8.8 animation speed (0=off)
;     sf_gradient_update                         — force in-place rebuild
;     sf_gradient_tick                           — per-frame animation service
;
;   COLOR MATH (over colormath_engine.asm shadow CGWSEL/CGADSUB/COLDATA)
;     sf_colormath_on   mode, layers   — enable (1=ADD 2=SUB 3/4=HALF variants)
;     sf_colormath_off                 — disable (zero CGWSEL/CGADSUB)
;     sf_colormath_tint r, g, b        — set the fixed color (0-31 each)
;
;   BRIGHTNESS FADE (over bright_fade_engine.asm SHADOW_INIDISP stepper)
;     sf_bright_fade target, frames    — arm a fade (frames=0 → instant)
;     sf_bright_fade_tick              — per-frame stepper (the game loop call)
;
;   PALETTE CYCLE (over palette_engine.asm SHADOW_CGRAM rotation)
;     sf_pal            index, r, g, b   — set one shadow-CGRAM color (the feed)
;     sf_pal_cycle      start, count, speed — arm a cycle (up to 4 active)
;     sf_pal_cycle_stop                  — stop ALL cycles (colors hold)
;     sf_pal_cycle_tick                  — per-frame rotate + CGRAM commit
;
; THE ARCHITECTURE IN 3 LINES (who commits what):
;   1. Main thread (these macros): stage parameters in the engine's WRAM
;      scratch, JSR the proven engine builders. Builders program the HDMA
;      channel hardware registers ($43n0+) DIRECTLY and build the per-band /
;      per-scanline tables in WRAM bank $7E.
;   2. The engine NMI handler re-arms $420C (HDMAEN) from NMI_HDMA_ENABLE
;      every VBlank and leaves these channels' $43n0 registers alone (they
;      are not Mode-7-owned). A kit ROM needs NO custom VBlank code — the
;      stock engine/nmi_handler.asm covers the whole commit path.
;   3. HDMA itself feeds BGnHOFS (parallax) / COLDATA $2132 (gradient) per
;      scanline during active display — zero CPU cost.
;
; ENGINE LINK PARTNERS — include in THIS ORDER inside the CODE segment
; (hdma_engine provides the channel wrapper + shared helpers the color
; engine JSRs into; hdma_color_engine pulls gradient_ease_lut.inc itself):
;
;   .include "engine_state.inc"        ; (top of file, equates only)
;   ...
;   .segment "CODE"
;   NMI:
;   .include "nmi_handler.asm"         ; stock NMI: $420C re-arm + shadows
;   ...
;   .include "hdma_alloc.asm"          ; channel allocator. Call
;                                      ;   `jsr hdma_alloc_init` once after
;                                      ;   sf_engine_init (reserves CH0/CH1)
;   .include "hdma_engine.asm"         ; parallax bands + hdma_alloc wrapper
;                                      ;   + _hdma_enable_channel
;   .include "hdma_color_engine.asm"   ; RGB gradients (MUST follow
;                                      ;   hdma_engine.asm; includes
;                                      ;   gradient_ease_lut.inc itself)
;
; The three non-HDMA groups are order-independent (no cross-JSRs) — include
; whichever the ROM uses, anywhere in the CODE segment:
;
;   .include "colormath_engine.asm"    ; sf_colormath_* — shadow-only writes;
;                                      ;   the stock NMI commits CGWSEL/
;                                      ;   CGADSUB/COLDATA every VBlank.
;                                      ;   No other deps.
;   .include "bright_fade_engine.asm"  ; sf_bright_fade — SHADOW_INIDISP
;                                      ;   stepper; NMI commits $2100 every
;                                      ;   VBlank. No other deps.
;   .include "palette_engine.asm"      ; sf_pal / sf_pal_cycle — needs
;                                      ;   dma_scheduler.asm linked for the
;                                      ;   tick's CGRAM commit (every kit ROM
;                                      ;   already includes it: the NMI queue
;                                      ;   drain is part of the frame spine).
;
; PARALLAX CONTRACT (the world-X feed + the freeze rule):
;   The band builder reads world-X from the target layer's SHADOW_BGnHOFS at
;   table-build time. Feed it with the BG group's `scroll` macro, then tick:
;       scroll #2, WORLD_X, #0          ; world-X into SHADOW_BG2HOFS
;       sf_parallax_tick                ; rebuild the 2-band HOFS table
;   Band math (ratio = ONE FRACTION BYTE, n/256 — the engine multiplies by
;   the ratio's LOW BYTE only, so the range is 0..255/256 and 1.0 is NOT
;   expressible; engine-verified — $0100 wraps to ratio 0):
;       scanlines 0 .. y_split-1   HOFS = world_x * ratio_top >> 8
;       scanlines y_split .. 224   HOFS = world_x * ratio_bot >> 8
;   For a full-speed (1.0) layer, don't band it: scroll the gameplay layer
;   directly with `scroll` and put the bands on the BACKGROUND layer (the
;   flagship pattern: BG1 foreground at 1.0, BG2 banded at <1.0).
;   y_split must be 1..128 (it is an HDMA non-repeat count byte).
;   TO FREEZE (dialog/pause): stop advancing world-X. NEVER set the ratios
;   to 0 — HOFS = world_x*0 = 0 TELEPORTS the layer to its world-zero scroll
;   position instead of freezing it (the documented spec-trap). With world-X
;   unchanged the rebuilt table is identical frame-to-frame: pixels don't move.
;   Cost: ~150 cycles/frame (3 band entries via the HDMA non-repeat-pause
;   pattern — the write-twice BGnHOFS latch holds each value through the
;   band's idle lines), not a 225-entry per-scanline fill.
;
; GRADIENT CONTRACT:
;   Intensities are 5-bit (0-31) per COLDATA channel. The gradient drives the
;   PPU FIXED COLOR ($2132) per scanline on 3 HDMA channels — it is visible
;   only through color math. Minimal dusk-sky setup (NMI commits these
;   shadows every VBlank):
;       lda #$00
;       sta SHADOW_CGWSEL               ; fixed color is the addend
;       lda #$20
;       sta SHADOW_CGADSUB              ; add on the backdrop
;   Screen pixel = backdrop + fixed(scanline) = the ramp, row by row.
;   Stop arrays (sf_gradient_stops): 6 bytes per stop in bank-$7E WRAM
;   (low WRAM $0000-$1FFF is mirrored there — the game-array region works):
;       +0 scanline (16-bit, ascending, first=0 recommended)
;       +2 red  +3 green  +4 blue  (0-31 each)   +5 pad
;   count = 2..16. Animation: sf_gradient_phase #speed (8.8 phase/frame)
;   + sf_gradient_tick once per frame; phase shifts the eased ramp.
;
; BEND / TUNNEL CONTRACT (per-scanline BGnHOFS curve distortion):
;   The sanctioned per-scanline horizontal-curve path — a normal-BG raster
;   bend (NOT Mode 7). One HDMA channel rewrites the target layer's BGnHOFS
;   every scanline from a curve LUT, so a flat BG bends. Two v1 curves:
;       SF_CURVE_SINE     — undulating wave / heat-haze; ROLLS into a forward
;                           tunnel under an animated phase (the marquee effect)
;       SF_CURVE_PARABOLA — a STATIC curved horizon, symmetric about screen
;                           centre (scanline 112): top & bottom edges displaced,
;                           flat through the middle
;   Per scanline: offset = curve[(scanline + phase) & $FF] * amp / 128.
;       amp   peak displacement, 0..15 px (the HW-multiply scale; amp 15 ≈ 14px)
;   STATIC bend:   sf_bend SF_CURVE_PARABOLA, #12   (arm once; no tick needed —
;                  with speed 0 the table never changes)
;   ANIMATED tunnel: sf_tunnel SF_CURVE_SINE, #12, #2   (arm) then
;                  sf_bend_tick once per frame in the loop — phase += speed,
;                  the table is rebuilt, the wave rolls. sf_bend_phase #0
;                  FREEZES the roll (table holds); a nonzero delta resumes it.
;   Cost: ~225-line per-frame rebuild while animated (one HW multiply + a few
;   writes per scanline) — see docs/guides/hdma_bend_tunnel.md for the MEASURED
;   per-frame cost. A static bend pays it ONCE at arm time (no tick). Release
;   with sf_bend_off (routes through the engine hdma_off path, frees the
;   channel + clears tracking). The BG needs a vertical reference feature
;   (e.g. vertical stripes) for the horizontal displacement to be visible.
;
; COLOR MATH CONTRACT (shadow-only — nothing to tick):
;   The engine writes SHADOW_CGWSEL/CGADSUB/COLDATA_* and the stock NMI
;   commits all of them every VBlank — a change takes effect next frame with
;   zero integration work. sf_colormath_on sets CGWSEL = $02 (addend = sub
;   screen); the kit leaves SHADOW_TS = 0 (no sub-screen layers), so every
;   pixel falls back to the FIXED COLOR as the addend — sf_colormath_tint IS
;   the addend everywhere. layers is the CGADSUB mask, bit0..5 = BG1, BG2,
;   BG3, BG4, OBJ, backdrop (#$20 = backdrop only — the tint/dusk pattern).
;   on (mode+layers) and tint (r,g,b) are orthogonal: re-tint without
;   re-enabling ("change the fog color" is one call).
;
; BRIGHT FADE CONTRACT (the one group with a per-frame tick to wire):
;   engine_bright_fade arms a paced fade of SHADOW_INIDISP bits 3-0 (the
;   forced-blank bit $80 is preserved every step); the NMI commits $2100
;   every VBlank. Call sf_bright_fade_tick ONCE PER FRAME in the game loop
;   (anywhere between sf_frame_begin and sf_frame_end — the sf_audio_tick
;   precedent). Inactive tick cost ~10 cycles; safe to leave in permanently.
;   DESIGN NOTE — explicit tick, NOT an .ifdef auto-wire into sf_frame_end:
;   chosen for symmetry with sf_audio_tick / sf_parallax_tick /
;   sf_gradient_tick (one visible per-frame service convention, no hidden
;   coupling, no conditional-assembly variant of the frame spine to test).
;   Tradeoff: the author must remember the tick — the macro README's group
;   row and this header both carry the rule.
;   BOOT VALUE: the standard kit boot (sf_coldstart → init_ppu) leaves
;   SHADOW_INIDISP = $0F (screen on, full brightness), so a fade-down starts
;   from 15 by construction. A ROM that never calls init_ppu has
;   SHADOW_INIDISP = 0 (coldstart WRAM clear) — i.e. already-dark; arm
;   sf_bright_fade #15, #N to fade IN from black after a scene load.
;   Re-arming mid-fade is safe: the engine re-paces from the CURRENT
;   brightness toward the new target. Fade is monotonic and lands exactly on
;   target on its final frame.
;
; PALETTE CYCLE CONTRACT (the SHADOW_CGRAM commit bridge):
;   The engine rotates colors inside SHADOW_CGRAM ($7E:BA00) and tracks a
;   dirty entry range — it does NOT touch hardware CGRAM. The kit uploads
;   palettes directly via $2121/$2122 at boot and has no per-frame
;   shadow→CGRAM path, so sf_pal_cycle_tick IS the bridge: it runs the
;   rotation, then, when the dirty flag is set, queues a priority-1 GP-DMA
;   of the DIRTY RANGE ONLY (SHADOW_CGRAM+lo*2 → $2122, CGADD = lo) for the
;   next VBlank drain and clears the flag.
;   WHY dirty-range, not full-512: colors uploaded directly (sf_bg_color /
;   sf_load_bg_pals / sf_obj_color) never live in SHADOW_CGRAM — a full-512
;   commit would wipe them to black on the first rotation. Committing only
;   the dirty range leaves direct-uploaded colors intact by construction.
;   SETUP CONTRACT: every entry in a cycled range MUST be fed through sf_pal
;   (it writes the shadow AND marks it dirty; the first tick commits it to
;   hardware CGRAM — entries 0 in hardware until then). Never sf_bg_color a
;   cycled entry: the next rotation would overwrite it from the shadow.
;   ORDERING: call sf_pal_cycle_tick BEFORE sf_frame_end — the queued entry
;   must be in the DMA queue when dma_queue_signal releases the NMI drain.
;   The tick sets CGADD ($2121) at queue time; it survives to the VBlank
;   drain (nothing else in the kit writes $2121 after boot).
;   Cycle args: start = first CGRAM entry, count = entries (rotate right:
;   entry i → i+1, last → first), speed = frames per step. Up to 4
;   concurrent cycles (distinct start indices). sf_pal_cycle_stop freezes
;   ALL cycles; colors hold their current rotation (no snap-back).
;   Cost: tick fast-exits ~30 cycles with no active cycle; on a rotation
;   frame, rotate (~20 cycles/entry) + DMA staging (~120 cycles) + 2 bytes
;   of VBlank DMA budget per dirty entry.
;
; RESULTS: arming macros return A = first allocated channel (3..7) or $FFFF
; on failure (no free channel, bad stop count, or Mode 7 active — the
; gradient builders refuse to arm while M7_PV_ACTIVE=1: COLDATA tables and
; Mode 7 HDMA share both channels and the $C000+ table region).
;
; RESOURCES (engine-claimed):
;   Channels: parallax = 1 HDMA channel; gradient = 3 (typically CH3-CH5);
;   bend/tunnel = 1 HDMA channel.
;   DP scratch (transient, engine cache area): $B0-$B7 table pointers.
;   WRAM: band/gradient tables at $7E:C000-$C54B (overlaps the standard HDMA
;   table region — one effect family per channel slot); parallax state at
;   $7E:E0D0-$E0DF; gradient scratch at $0630-$0656 (low WRAM); bend/tunnel
;   cold state at $7E:E0B0-$E0B7 (CURVE/AMP/LAYER/CHAN), animation phase/speed
;   reuse the wave DP slots $66/$68.
;   Color math: shadows in engine state $0144-$0149. Bright fade: state in
;   engine state DP $36-$39. Palette cycle: SHADOW_CGRAM $7E:BA00-$BBFF,
;   descriptors $7E:BC00-$BCFF, PAL_SCRATCH $0560-$0563, dirty tracking
;   $0140-$0142; the tick consumes 1 GP-DMA queue entry on rotation frames.
;
; ARMING ORDER / CHANNEL BUDGET (composition contracts — both failure modes
; are SILENT visual corruption; the templates prove the working order):
;   1. GRADIENT BEFORE PARALLAX. The gradient builder writes its three
;      COLDATA tables at FIXED WRAM addresses $C000/$C1C4/$C388 (it assumes
;      it owns CH3-CH5), while sf_parallax_bands places its table by
;      ALLOCATED CHANNEL SLOT. Gradient-first → it gets CH3-CH5 and parallax
;      lands on a later slot (CH6/$CC00, clear of $C000-$C54B). Parallax-
;      first puts the parallax table in CH3's slot $C000 — the first
;      sf_parallax_tick rebuild stomps the red gradient table. Working
;      example: templates/platformer/main.asm.
;   2. MODE 7 + GRADIENT: PRE-PIN CH5/CH6, ARM BEFORE sf_mode7_on. The
;      gradient arm builders refuse while M7_PV_ACTIVE=1 (see RESULTS) —
;      arm the gradient first, then retune at runtime via sf_gradient_update
;      (in-place rebuild, guard-free). AND the allocator's bootstrap pin
;      does NOT conflict-check Mode 7's CH5/CH6: `jsr
;      mode7_hdma_alloc_request` (idempotent) BEFORE arming the gradient,
;      or first-fit can hand the gradient CH5 and the NMI's Mode 7 commit
;      overwrites it every VBlank. Working example: templates/racer/main.asm.
;
; TEARDOWN (engine gap, documented): hdma_off() disables and releases ALL
; HDMA effects but does NOT clear the parallax channel-tracking slot
; (PARALLAX_BANDS_CHAN) — after hdma_off, re-arming via sf_parallax_bands
; would re-use a stale channel number whose enable bit is gone. There is no
; per-effect parallax teardown in the engine. For S6-shape ROMs, arm
; parallax once at scene setup and leave it armed.
; =============================================================================

.ifndef SF_FX_INC
SF_FX_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_parallax_bands layer, y_split, ratio_top, ratio_bot — arm / retune.
; -----------------------------------------------------------------------------
;   layer      BG layer 1-3 (verbatim 16-bit operand — #imm or DP/abs word)
;   y_split    transition scanline 1..128
;   ratio_top  scroll ratio fraction byte (0..255 = n/256; see the header —
;              1.0 is not expressible) for scanlines 0..y_split-1
;   ratio_bot  same, for scanlines y_split..224
; First call allocates an HDMA channel, programs its $43n0 registers
; (DMAP=$02 write-twice → BGnHOFS) and builds the band table; later calls
; (retune) re-use the channel and just rebuild. Reads world-X from
; SHADOW_BGnHOFS — set the scroll shadow (scroll macro) BEFORE arming.
; Result: A = channel (3..7) or $FFFF on alloc failure. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); the engine builder
; toggles A8 around hardware writes internally and exits A16/I16.
.macro sf_parallax_bands sf_layer, sf_ysplit, sf_rtop, sf_rbot
    rep #$30
    .a16
    .i16
    lda sf_layer
    sta f:PARALLAX_BANDS_LAYER
    lda sf_ysplit
    sta f:PARALLAX_BANDS_YSPLIT
    lda sf_rtop
    sta f:PARALLAX_BANDS_RATIO_TOP
    lda sf_rbot
    sta f:PARALLAX_BANDS_RATIO_BOT
    jsr hdma_build_parallax_bands
.endmacro

; -----------------------------------------------------------------------------
; sf_parallax_tick — the per-frame parallax service call (put it in your loop).
; -----------------------------------------------------------------------------
; Rebuilds the band table from the cached ratios + the CURRENT SHADOW_BGnHOFS
; (call it after your scroll update). No-op when parallax is not armed.
; ~150 cycles/frame armed. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine update re-asserts rep #$30
; itself and exits A16/I16.
.macro sf_parallax_tick
    rep #$30
    .a16
    .i16
    jsr hdma_update_parallax_bands
.endmacro

; =============================================================================
; BEND / TUNNEL — per-scanline BGnHOFS curve distortion (engine hofs_curve)
; =============================================================================
; Curve selectors for sf_bend / sf_tunnel (the HDMA_BEND_CURVE id; the engine
; branches sine vs parabola on this value).
SF_CURVE_SINE     = 0
SF_CURVE_PARABOLA = 1
; v1.2: a monotonic one-sided compression ramp for the V-axis barrel/horizon
; squash (rows bunch toward the bottom/horizon). Reads as a real horizon, not a
; symmetric bow. Intended for sf_bend_v / sf_tunnel_v (BGnVOFS); usable on H too.
SF_CURVE_HORIZON  = 2

; -----------------------------------------------------------------------------
; sf_bend curve, amp [, layer] — arm a STATIC per-scanline curve bend.
; -----------------------------------------------------------------------------
;   curve  SF_CURVE_SINE | SF_CURVE_PARABOLA (verbatim 16-bit operand)
;   amp    peak displacement 0..15 px (verbatim 16-bit operand, low byte used)
;   layer  BG layer 1/2/3 (verbatim 16-bit operand; OPTIONAL — defaults to BG1).
;          The engine derives BBAD per layer (1→$0D BG1HOFS, 2→$0F, 3→$11), so
;          you can bend any normal BG and leave the others to scroll freely.
; Allocates one HDMA channel, programs it (DMAP=$02 → BG{layer}HOFS), builds the
; per-scanline table ONCE at phase 0. No tick needed — a static bend's table
; never changes (parabola = a fixed curved horizon; sine = a frozen ripple).
; To roll it later, set a speed with sf_bend_phase and add sf_bend_tick to the
; loop (or arm with sf_tunnel up front).
; Result: A = channel (3..7) or $FFFF on alloc failure. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine builder toggles A8 around the
; hardware writes internally and exits A16/I16.
.macro sf_bend sf_curve, sf_amp, sf_layer
    rep #$30
    .a16
    .i16
    lda sf_curve
    sta f:HDMA_BEND_CURVE
    lda sf_amp
    sta f:HDMA_BEND_AMP
.ifblank sf_layer
    lda #1                          ; default: BG1 (the kit bend layer)
.else
    lda sf_layer
.endif
    sta f:HDMA_BEND_LAYER
    lda #0                          ; axis 0 = H (BGnHOFS) — the classic bend
    sta f:HDMA_BEND_AXIS
    stz HDMA_WAVE_PHASE             ; static: phase 0
    stz HDMA_WAVE_SPEED             ; static: no roll
    jsr hdma_build_hofs_curve
.endmacro

; -----------------------------------------------------------------------------
; sf_tunnel curve, amp, speed [, layer] — arm an ANIMATED (rolling) bend.
; -----------------------------------------------------------------------------
;   curve  SF_CURVE_SINE | SF_CURVE_PARABOLA (verbatim 16-bit operand)
;   amp    peak displacement 0..15 px (verbatim 16-bit operand, low byte used)
;   speed  phase increment per frame (verbatim 16-bit operand). The roll is a
;          WRAPPING 16-bit add (phase += speed) and the curve is sampled at
;          (scanline + phase) & $FF, so:
;            POSITIVE speed (e.g. #2)      → the pattern rolls DOWNWARD (the
;                                            marquee forward tunnel).
;            NEGATIVE speed (two's-comp,   → the pattern rolls UPWARD; the
;            e.g. #$FFFE = −2)               reverse tunnel. The wrap makes a
;                                            negative phase delta well-defined.
;   layer  BG layer 1/2/3 (verbatim 16-bit operand; OPTIONAL — defaults to BG1).
; Same arm as sf_bend but seeds the roll speed, so the curve advances every
; frame you call sf_bend_tick. Result: A = channel (3..7) or $FFFF. Clobbers
; A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; engine builder toggles A8 internally,
; exits A16/I16.
.macro sf_tunnel sf_curve, sf_amp, sf_speed, sf_layer
    rep #$30
    .a16
    .i16
    lda sf_curve
    sta f:HDMA_BEND_CURVE
    lda sf_amp
    sta f:HDMA_BEND_AMP
.ifblank sf_layer
    lda #1                          ; default: BG1
.else
    lda sf_layer
.endif
    sta f:HDMA_BEND_LAYER
    lda #0                          ; axis 0 = H (BGnHOFS) — the classic tunnel
    sta f:HDMA_BEND_AXIS
    stz HDMA_WAVE_PHASE
    lda sf_speed
    sta HDMA_WAVE_SPEED             ; seed the per-frame roll (signed: see above)
    jsr hdma_build_hofs_curve
.endmacro

; -----------------------------------------------------------------------------
; sf_bend_v curve, amp [, layer] — arm a STATIC per-scanline VERTICAL bend.
; -----------------------------------------------------------------------------
; The V-axis (BGnVOFS) mirror of sf_bend: a per-scanline VERTICAL offset that
; squashes a flat horizontal-band field toward a horizon (the barrel/horizon
; compression). Identical to sf_bend except it sets HDMA_BEND_AXIS=1, so the
; engine programs the channel against BG{layer}VOFS (V register = H+1) instead
; of BG{layer}HOFS. Use SF_CURVE_HORIZON for a real one-sided horizon squash
; (SINE/PARABOLA also work — they bow the field symmetrically).
;   curve  SF_CURVE_HORIZON | SF_CURVE_SINE | SF_CURVE_PARABOLA
;   amp    peak displacement, FULL BYTE 0..255 (scale is |curve|*amp/128 px, so
;          amp 128 ≈ 127px of squash). NOT capped at 15 — the V horizon squash
;          uses a large amp (the H bend's gentle range is just a usage convention).
;   layer  BG layer 1/2/3 (OPTIONAL — defaults to BG1)
; Result: A = channel (3..7) or $FFFF. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine builder toggles A8 internally
; and exits A16/I16.
.macro sf_bend_v sf_curve, sf_amp, sf_layer
    rep #$30
    .a16
    .i16
    lda sf_curve
    sta f:HDMA_BEND_CURVE
    lda sf_amp
    sta f:HDMA_BEND_AMP
.ifblank sf_layer
    lda #1                          ; default: BG1
.else
    lda sf_layer
.endif
    sta f:HDMA_BEND_LAYER
    lda #1                          ; axis 1 = V (BGnVOFS) — the barrel/horizon
    sta f:HDMA_BEND_AXIS
    stz HDMA_WAVE_PHASE             ; static: phase 0
    stz HDMA_WAVE_SPEED             ; static: no roll
    jsr hdma_build_hofs_curve
.endmacro

; -----------------------------------------------------------------------------
; sf_tunnel_v curve, amp, speed [, layer] — arm an ANIMATED VERTICAL bend.
; -----------------------------------------------------------------------------
; The V-axis (BGnVOFS) mirror of sf_tunnel: the same vertical row-squash, rolled
; per frame (the field flows up/down under the barrel). Sets HDMA_BEND_AXIS=1.
;   curve  SF_CURVE_HORIZON | SF_CURVE_SINE | SF_CURVE_PARABOLA
;   amp    peak displacement, FULL BYTE 0..255 (scale is |curve|*amp/128 px, so
;          amp 128 ≈ 127px of squash). NOT capped at 15 — the V horizon squash
;          uses a large amp (the H bend's gentle range is just a usage convention).
;   speed  phase increment per frame (verbatim 16-bit operand; NEGATIVE two's-
;          complement, e.g. #$FFFE, reverses the roll — see sf_tunnel).
;   layer  BG layer 1/2/3 (OPTIONAL — defaults to BG1)
; Result: A = channel (3..7) or $FFFF. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; engine builder toggles A8 internally,
; exits A16/I16.
.macro sf_tunnel_v sf_curve, sf_amp, sf_speed, sf_layer
    rep #$30
    .a16
    .i16
    lda sf_curve
    sta f:HDMA_BEND_CURVE
    lda sf_amp
    sta f:HDMA_BEND_AMP
.ifblank sf_layer
    lda #1                          ; default: BG1
.else
    lda sf_layer
.endif
    sta f:HDMA_BEND_LAYER
    lda #1                          ; axis 1 = V (BGnVOFS)
    sta f:HDMA_BEND_AXIS
    stz HDMA_WAVE_PHASE
    lda sf_speed
    sta HDMA_WAVE_SPEED             ; seed the per-frame roll (signed: see above)
    jsr hdma_build_hofs_curve
.endmacro

; -----------------------------------------------------------------------------
; sf_bend_phase delta — set / replace the bend roll speed.
; -----------------------------------------------------------------------------
;   delta  phase increment per frame (verbatim 16-bit operand). 0 FREEZES the
;          roll (sf_bend_tick keeps rebuilding an identical table — pixels
;          hold); a POSITIVE delta rolls the curve DOWNWARD; a NEGATIVE
;          (two's-complement, e.g. #$FFFE = −2) delta rolls it UPWARD (the
;          reverse direction — the phase advance is a wrapping 16-bit add, so a
;          negative increment is well-defined). Pair with sf_bend_tick in the
;          loop — the phase only advances there.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; no width toggle; exits A16/I16.
.macro sf_bend_phase sf_delta
    rep #$30
    .a16
    .i16
    lda sf_delta
    sta HDMA_WAVE_SPEED
.endmacro

; -----------------------------------------------------------------------------
; sf_bend_tick — the per-frame bend / tunnel service call (put it in your loop).
; -----------------------------------------------------------------------------
; Advances the curve phase by the sf_tunnel / sf_bend_phase speed and updates
; the roll. The engine auto-picks the cheapest path each frame:
;   - PURE ROLL (the bent layer's SHADOW_BGnHOFS == 0): the E-SLIDE pointer-slide
;     fast-path — advance only the HDMA source pointer into a once-baked table,
;     no per-scanline writes (~0.4% of a frame). Reverses under a negative speed.
;   - PANNING (SHADOW_BGnHOFS != 0, i.e. you `scroll` the bent layer): the
;     optimized refill — rebuild composing base_scroll + curve per line (~21%).
; No-op when no bend is armed (safe to leave in the loop permanently); a
; harmless freeze when speed = 0. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine update re-asserts rep #$30
; itself and exits A16/I16.
.macro sf_bend_tick
    rep #$30
    .a16
    .i16
    jsr hdma_update_hofs_curve
.endmacro

; -----------------------------------------------------------------------------
; sf_bend_off — release the bend / tunnel channel.
; -----------------------------------------------------------------------------
; Routes through the engine hdma_off path: frees the HDMA channel, clears
; NMI_HDMA_ENABLE, and zeroes HDMA_BEND_CHAN so sf_bend_tick becomes a no-op.
; Note: hdma_off tears down ALL active HDMA effects (gradient/parallax/bend) —
; the kit's one-effect-family convention. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine routine toggles A8 internally
; and exits A16/I16.
.macro sf_bend_off
    rep #$30
    .a16
    .i16
    jsr hdma_off
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_rgb tr, tg, tb, br, bg, bb — arm a 2-stop RGB gradient.
; -----------------------------------------------------------------------------
;   tr,tg,tb   top color intensities (0-31 each, verbatim 16-bit operands)
;   br,bg,bb   bottom color intensities (0-31 each)
; Allocates 3 HDMA channels (one per COLDATA color channel), builds three
; 225-entry tables interpolating top→bottom down the frame, enables them.
; Re-calling re-arms from scratch (releases the previous gradient first).
; Refused while Mode 7 is active. See the file header for the color-math
; setup that makes the fixed color visible.
; Result: A = first channel or $FFFF on failure. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine builder toggles widths
; internally and exits A16/I16.
.macro sf_gradient_rgb sf_tr, sf_tg, sf_tb, sf_br, sf_bgn, sf_bb
    rep #$30
    .a16
    .i16
    lda sf_tr
    sta HDMA_GRAD_RGB_TOP_R
    lda sf_tg
    sta HDMA_GRAD_RGB_TOP_G
    lda sf_tb
    sta HDMA_GRAD_RGB_TOP_B
    lda sf_br
    sta HDMA_GRAD_RGB_BOT_R
    lda sf_bgn
    sta HDMA_GRAD_RGB_BOT_G
    lda sf_bb
    sta HDMA_GRAD_RGB_BOT_B
    jsr hdma_build_gradient_rgb
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_stops addr, count — arm an N-stop RGB gradient.
; -----------------------------------------------------------------------------
;   addr   16-bit bank-$7E word address of the stop array (verbatim operand;
;          for a table in low WRAM / the game-array region pass its address,
;          e.g. #$1800 — low WRAM is mirrored into bank $7E)
;   count  number of stops, 2..16 (verbatim 16-bit operand, low byte used)
; Stop format (6 bytes each): see the file header. Allocates 3 channels,
; interpolates each adjacent stop pair, applies the active easing curve.
; Result: A = first channel or $FFFF (alloc failure, count out of range, or
; Mode 7 active). Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the count + flag byte stores,
; back to A16 before the JSR; engine exits A16/I16.
.macro sf_gradient_stops sf_addr, sf_count
    rep #$30
    .a16
    .i16
    lda sf_addr
    sta HDMA_GRAD_STOP_ADDR
    lda sf_count
    sep #$20
    .a8
    sta HDMA_GRAD_STOP_COUNT
    lda HDMA_GRAD_RGB_FLAGS
    ora #$02                        ; bit 1 = multi-stop mode
    sta HDMA_GRAD_RGB_FLAGS
    rep #$20
    .a16
    jsr hdma_build_gradient_stops
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_ease type — select the gradient easing curve.
; -----------------------------------------------------------------------------
;   type  0 = linear, 1 = ease-in, 2 = ease-out, 3 = smoothstep (verbatim
;         16-bit operand, low 2 bits used)
; Takes effect on the NEXT build/rebuild (arm, sf_gradient_update, or an
; animation step) — call it before arming, or follow with sf_gradient_update.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the byte store; exits A16/I16.
.macro sf_gradient_ease sf_type
    rep #$30
    .a16
    .i16
    lda sf_type
    sep #$20
    .a8
    and #$03                        ; clamp to 0-3
    sta HDMA_GRAD_RGB_EASING
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_phase delta — set the gradient animation speed.
; -----------------------------------------------------------------------------
;   delta  8.8 phase increment per frame (verbatim 16-bit operand). 0 stops
;          the animation; nonzero starts it. Pair with sf_gradient_tick in
;          the game loop — the phase only advances there.
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the flag-byte read-modify-write
; (the gp_enable label is reached from both the bne and the fall-through,
; both A8); exits A16/I16.
.macro sf_gradient_phase sf_delta
    .local gp_enable
    rep #$30
    .a16
    .i16
    lda sf_delta
    sta HDMA_GRAD_SPEED
    sep #$20
    .a8
    lda HDMA_GRAD_RGB_FLAGS
    ora #$01                        ; bit 0 = animated
    ldx HDMA_GRAD_SPEED
    bne gp_enable
    and #$FE                        ; clear bit 0 if speed = 0
gp_enable:
    .a8
    sta HDMA_GRAD_RGB_FLAGS
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_update — force an in-place gradient rebuild now.
; -----------------------------------------------------------------------------
; Rebuilds the three COLDATA tables from the current top/bot colors (or stop
; array), easing curve, and phase — no channel reallocation. No-op when no
; gradient is armed. Use after sf_gradient_ease or after editing a stop
; array in place. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine rebuild re-asserts rep #$30
; itself and exits A16/I16.
.macro sf_gradient_update
    rep #$30
    .a16
    .i16
    jsr hdma_gradient_rgb_rebuild
.endmacro

; -----------------------------------------------------------------------------
; sf_gradient_tick — the per-frame gradient animation service call.
; -----------------------------------------------------------------------------
; Advances the animation phase by the sf_gradient_phase speed and rebuilds
; the tables when the quantized phase changes. No-op when no gradient is
; armed or animation is off — safe to leave in the loop permanently.
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the engine update re-asserts rep #$30
; itself and exits A16/I16.
.macro sf_gradient_tick
    rep #$30
    .a16
    .i16
    jsr hdma_update_gradient_rgb
.endmacro

; -----------------------------------------------------------------------------
; sf_colormath_on mode, layers — enable color math (shadow-only; NMI commits).
; -----------------------------------------------------------------------------
;   mode    1=ADD, 2=SUB, 3=HALF_ADD, 4=HALF_SUB (verbatim 16-bit operand)
;   layers  CGADSUB layer mask, bit0..5 = BG1,BG2,BG3,BG4,OBJ,backdrop
;           (#$20 = backdrop only — the tint/dusk flagship pattern)
; Writes SHADOW_CGWSEL ($02: addend = sub screen, which falls back to the
; FIXED COLOR everywhere while SHADOW_TS = 0 — the kit default) and
; SHADOW_CGADSUB; the stock NMI commits both every VBlank, so this takes
; effect next frame with no tick. Pair with sf_colormath_tint for the color.
; Engine link partner: colormath_engine.asm (engine_color_math_on).
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); the engine toggles A8
; for the shadow byte writes internally and exits A16/I16.
.macro sf_colormath_on sf_mode, sf_layers
    rep #$30
    .a16
    .i16
    lda sf_mode
    sta API_BLOCK_BASE + $00
    lda sf_layers
    sta API_BLOCK_BASE + $04
    jsr engine_color_math_on
.endmacro

; -----------------------------------------------------------------------------
; sf_colormath_off — disable color math (zero SHADOW_CGWSEL/CGADSUB).
; -----------------------------------------------------------------------------
; The NMI commits the zeroed shadows next VBlank — the screen reverts to the
; un-mathed pixels on the following frame. The fixed color (tint) shadows are
; left untouched: a later sf_colormath_on resumes with the same tint.
; Engine link partner: colormath_engine.asm (engine_color_math_off).
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; engine toggles A8 internally, exits
; A16/I16.
.macro sf_colormath_off
    rep #$30
    .a16
    .i16
    jsr engine_color_math_off
.endmacro

; -----------------------------------------------------------------------------
; sf_colormath_tint r, g, b — set the fixed color ($2132 source).
; -----------------------------------------------------------------------------
;   r, g, b  channel intensities 0-31 (verbatim 16-bit operands; engine masks
;            each to 5 bits)
; Writes SHADOW_COLDATA_R/G/B; the NMI commits all three channels every
; VBlank. Orthogonal to sf_colormath_on — re-tint without re-enabling.
; Visible only while color math is ON for some layer (and, for the
; full-screen scanline ramp version of this, see sf_gradient_rgb).
; Engine link partner: colormath_engine.asm (engine_color_math_tint).
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; engine toggles A8 internally, exits
; A16/I16.
.macro sf_colormath_tint sf_r, sf_g, sf_b
    rep #$30
    .a16
    .i16
    lda sf_r
    sta API_BLOCK_BASE + $00
    lda sf_g
    sta API_BLOCK_BASE + $04
    lda sf_b
    sta API_BLOCK_BASE + $08
    jsr engine_color_math_tint
.endmacro

; -----------------------------------------------------------------------------
; sf_bright_fade target, frames — arm a paced screen-brightness fade.
; -----------------------------------------------------------------------------
;   target  brightness 0..15 (verbatim 16-bit operand, low nibble used)
;   frames  fade length in frames 1..255 (verbatim; #0 = set instantly)
; Arms the engine stepper over SHADOW_INIDISP bits 3-0 (forced-blank bit $80
; preserved every step; NMI commits $2100 each VBlank). Drive it with
; sf_bright_fade_tick once per frame — without the tick nothing moves.
; Monotonic toward target; lands exactly on target on the final frame.
; Re-arming mid-fade re-paces from the current brightness. Boot value: the
; standard kit boot (init_ppu) leaves SHADOW_INIDISP = $0F, so fade-downs
; start from full brightness by construction (see the file header).
; Engine link partner: bright_fade_engine.asm (engine_bright_fade).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; engine_bright_fade is A16/I16
; entry+exit and toggles A8 internally for the engine-state byte fields.
.macro sf_bright_fade sf_target, sf_frames
    rep #$30
    .a16
    .i16
    ldx sf_frames
    lda sf_target
    jsr engine_bright_fade
.endmacro

; -----------------------------------------------------------------------------
; sf_bright_fade_tick — the per-frame fade service call (put it in your loop).
; -----------------------------------------------------------------------------
; Advances an armed fade by one frame; ~10-cycle fast exit when no fade is
; active — safe to leave in the loop permanently (the sf_audio_tick
; convention; see the file header for why this is an explicit call rather
; than an auto-wire into sf_frame_end). Call it anywhere between
; sf_frame_begin and sf_frame_end. Clobbers A, X, Y.
; WIDTH-RISK: enters any width; bright_fade_step requires A8/I16 (the parent
; SIGNAL-phase call contract — the sep/rep is handled here so callers don't
; care); exits A16/I16.
.macro sf_bright_fade_tick
    sep #$20
    .a8
    rep #$10
    .i16
    jsr bright_fade_step
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_pal index, r, g, b — set one color in SHADOW_CGRAM (the cycle feed).
; -----------------------------------------------------------------------------
;   index    CGRAM entry 0-255 (verbatim 16-bit operand, low byte used)
;   r, g, b  channel intensities 0-31 (verbatim; engine packs BGR15)
; Writes the shadow entry and marks it dirty; the next sf_pal_cycle_tick
; commits the dirty range to hardware CGRAM via the NMI DMA queue. This is
; the REQUIRED feed for any entry in a cycled range (see the file header's
; setup contract) — direct uploads (sf_bg_color) don't reach the shadow and
; would be overwritten by the first rotation.
; Engine link partner: palette_engine.asm (engine_pal).
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; engine toggles A8/DB internally and
; exits A16/I16 with DB restored.
.macro sf_pal sf_index, sf_r, sf_g, sf_b
    rep #$30
    .a16
    .i16
    lda sf_index
    sta API_BLOCK_BASE + $00
    lda sf_r
    sta API_BLOCK_BASE + $04
    lda sf_g
    sta API_BLOCK_BASE + $08
    lda sf_b
    sta API_BLOCK_BASE + $0C
    jsr engine_pal
.endmacro

; -----------------------------------------------------------------------------
; sf_pal_cycle start, count, speed — arm a palette cycle.
; -----------------------------------------------------------------------------
;   start  first CGRAM entry of the rotated range (verbatim 16-bit operand)
;   count  entries in the range, 2+ (rotate right: entry i → i+1, last→first)
;   speed  frames per rotation step (1 = every frame)
; Up to 4 concurrent cycles (distinct starts; re-arming the same start
; retunes that cycle). The rotation runs inside sf_pal_cycle_tick — arm,
; feed the range with sf_pal, then tick every frame. The airship day-night
; pattern: cycle the sky/water entries at speed 8-16.
; Engine link partner: palette_engine.asm (engine_pal_cycle; needs
; dma_scheduler.asm linked for the tick's commit).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; engine toggles A8/DB internally and
; exits A16/I16 with DB restored.
.macro sf_pal_cycle sf_start, sf_count, sf_speed
    rep #$30
    .a16
    .i16
    lda sf_start
    sta API_BLOCK_BASE + $00
    lda sf_count
    sta API_BLOCK_BASE + $04
    lda sf_speed
    sta API_BLOCK_BASE + $08
    jsr engine_pal_cycle
.endmacro

; -----------------------------------------------------------------------------
; sf_pal_cycle_stop — stop ALL palette cycles (colors hold, no snap-back).
; -----------------------------------------------------------------------------
; Clears every cycle descriptor (the engine's count=0 + speed=0 stop-all
; form). CGRAM keeps whatever rotation was on screen — restore the original
; colors with sf_pal if a scene needs them back. Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; engine toggles A8/DB internally and
; exits A16/I16 with DB restored.
.macro sf_pal_cycle_stop
    rep #$30
    .a16
    .i16
    stz API_BLOCK_BASE + $00
    stz API_BLOCK_BASE + $04
    stz API_BLOCK_BASE + $08
    jsr engine_pal_cycle
.endmacro

; -----------------------------------------------------------------------------
; sf_pal_cycle_tick — per-frame rotate + the SHADOW_CGRAM→CGRAM commit bridge.
; -----------------------------------------------------------------------------
; Runs the engine rotation, then — when the dirty flag is set (a rotation
; fired this frame, or sf_pal touched the shadow) — queues a priority-1
; GP-DMA of the dirty range only (SHADOW_CGRAM + lo*2 → $2122, size
; (hi-lo+1)*2 bytes) and sets CGADD = lo for the VBlank drain. See the file
; header for why dirty-range (not full-512) and the tick-BEFORE-sf_frame_end
; ordering rule. Fast exit ~30 cycles when no cycle is active and nothing is
; dirty — safe to leave in the loop permanently. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the staging byte stores + the
; CGADD write, A16 for the address/size math (the pha/pla pair is all-A16 —
; stack balanced 2/2); pct_clean is reached from the A16 beq and the A16
; fall-through (both paths A16/I16); exits A16/I16.
.macro sf_pal_cycle_tick
    .local pct_clean
    rep #$30
    .a16
    .i16
    jsr engine_pal_cycle_tick           ; rotate active cycles (A16/I16 in/out)

    ; --- commit bridge: dirty shadow range → hardware CGRAM next VBlank ---
    lda CGRAM_DIRTY_FLAG                ; 16-bit read; high byte is the
    and #$00FF                          ;   neighbouring PAL_CYCLE_COUNT — mask
    beq pct_clean                       ; clean — nothing to commit
    sep #$20
    .a8
    stz CGRAM_DIRTY_FLAG
    lda #$01
    sta DMA_STAGE_PRIORITY              ; priority 1 (right behind OAM)
    stz DMA_STAGE_DMAP                  ; DMAP $00: one register, increment src
    lda #$22
    sta DMA_STAGE_BBAD                  ; dest $2122 (CGDATA)
    lda #$7E
    sta DMA_STAGE_SRC_BANK              ; SHADOW_CGRAM lives in WRAM bank $7E
    lda CGRAM_DIRTY_LO
    sta $2121                           ; CGADD = first dirty entry; survives
                                        ;   to the drain (nothing else writes
                                        ;   $2121 after boot)
    rep #$20
    .a16
    and #$00FF                          ; A = dirty lo (high byte was stale)
    asl                                 ; lo * 2 = byte offset
    pha                                 ; keep for the size math (A16: 2 bytes)
    clc
    adc #SHADOW_CGRAM
    sta DMA_STAGE_SRC_LO                ; src = $7E:BA00 + lo*2
    lda CGRAM_DIRTY_HI
    and #$00FF
    inc a                               ; hi + 1 (16-bit: full range 0..255 safe)
    asl                                 ; (hi+1) * 2
    sec
    sbc 1, s                            ; − lo*2 → size = (hi−lo+1)*2 bytes
    sta DMA_STAGE_SIZE
    pla                                 ; balance the pha (A16: 2 bytes)
    jsr dma_queue_add                   ; needs A16/I16 — we are
pct_clean:
    .a16
    .i16
.endmacro

.endif ; SF_FX_INC
