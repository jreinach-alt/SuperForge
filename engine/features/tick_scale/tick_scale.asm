; =============================================================================
; tick_scale.asm — a region-correct unit of motion, for one consumer at a time
; =============================================================================
; ONE TICK PER FRAME. What changes between the two machines is not how often
; the logic runs but HOW FAR ONE STEP MOVES, and the fraction is carried
; between frames so the published pixels sum to the exact scaled distance
; instead of being re-quantised every frame. That carry is the whole mechanism:
; an integer scale has no correct answer at all on a step of 2 (docs/96 §4.4
; measured 0.83208 rounding down and 1.24812 rounding up), and the accumulator
; reaches 0.99919.
;
; ON NTSC EVERY CONSUMER PUBLISHES TODAY'S CONSTANT, EXACTLY. The base step is
; a whole number of units in 8.8, the scale is 1, and the accumulator's carried
; fraction stays 0 forever — so the NTSC picture cannot move. That is not an
; argument, it is what tools/tb_picture_diff.py reads off the pixels.
;
; -----------------------------------------------------------------------------
; THE UNIT
; -----------------------------------------------------------------------------
; A "step" is 8.8 fixed point: TS_ONE is one whole unit. A consumer whose step
; is 2 px per frame passes `2 * TS_ONE`. What TS_STEP returns is the WHOLE
; units to apply this frame — 2 on NTSC, and 2 or 3 on PAL in the pattern that
; averages 2.4036.
;
; Written as a shift rather than as 256: `no_literals` reads an operand's
; numeric tokens and cannot tell a scale factor from an address, and building
; every constant out of shifts and small factors keeps the arithmetic visible
; AND the gate satisfied (the prototype's own note, unchanged).
TS_ONE = 1 << 8

; -----------------------------------------------------------------------------
; THE RATIO, and why it is this rational and not 6/5
; -----------------------------------------------------------------------------
; The master-clock rates are read from Mesen2 `Core/SNES/SnesConsole.cpp:209`
; (`_masterClockRate = _region == ConsoleRegion::Pal ? 21281370 : 21477270`)
; and the frame lengths are measured by tools/rate_oracle.py in both regions:
;
;   NTSC   21,477,270 / 357,368 mc  =  60.09879 fps
;   PAL    21,281,370 / 425,568 mc  =  50.00714 fps
;   a PAL frame must therefore carry  60.09879 / 50.00714 = 1.2018039  of the
;   distance an NTSC frame carries.
;
; 6/5 = 1.2 is that number rounded, and docs/96 §4.4 measured the difference at
; 0.15% — `lump` runs exactly 6 ticks per 5 frames and lands at 0.99850 for
; that reason alone.
;
; The GAIN, not the ratio, is what is stored: PAL's step is the NTSC step PLUS
; 0.2018039 of it. That is arithmetically identical and it buys range —
; ca65 evaluates in 32 bits, so multiplying by the gain's numerator instead of
; the ratio's raises the largest base a build can scale from ~7.0 units/frame
; to ~166, which is the difference between "fits every rail in this tree" and
; "fits the two that compose it today". TS_BASE_MAX asserts the bound rather
; than leaving it to be discovered by a silently wrapped constant.
;
; TICK: ok — this equate pair IS the region compensator's own derivation, and
;   naming the NTSC frame beside the PAL one is the point of the file rather
;   than a coupling in it. The same override sat on the prototype's copy.
TS_GAIN_NUM = 50451             ; 0.2018039 as 50451 / 250000, exactly the
TS_GAIN_DEN = 250000            ;   reduced form of 201804 / 1000000
; A BOUND on what this feature can convert, not a rate anything is counted in:
; it exists so an over-large base refuses the build instead of wrapping
; silently, and its unit is "units of the caller's rate", whatever that turns
; out to be.
; TICK: ok — a conversion ceiling, not a clock.
TS_BASE_MAX = 42000             ; ~164 units per frame; keeps base * TS_GAIN_NUM
                                ;   inside ca65's 32-bit expression arithmetic

; -----------------------------------------------------------------------------
; TS_STEP — publish this frame's whole-unit step for ONE consumer
; -----------------------------------------------------------------------------
;   TS_STEP  <accumulator>, <base step in 8.8>
;
; CONTRACT TS_STEP
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       ts_acc — a dp operand the CALLER owns and declares, holding the
;             fraction carried out of last frame; ts_base — a build-time
;             constant expression, the NTSC step in 8.8
;   out:      A = the whole units to apply this frame; ts_acc = the new
;             carried fraction. The caller stores A where it wants and every
;             downstream add reads it — compute ONCE per frame per rate,
;             consume as many times as the frame needs
;   clobbers: A, N, Z, C, and one stack word (balanced: one pha, one pla,
;             both in A16)
;   assumes:  ES_RGN_PAL is already latched — region_init runs at boot, and
;             composing tick_scale without region is a build error rather
;             than a silent scale of 1
;   tail:     falls through to the caller — this is a macro, not a call
;
; It contains no sep/rep at all, so it cannot leak a width to its caller and
; needs no directive after it. THE ENTRY WIDTHS ARE NOT ASSERTED HERE, and
; that is a stated gap rather than an oversight: SF_ASSERT_WIDTH lives in
; `sf_asm.inc`, which is included per ROM by the rail's `main.asm`, and most
; of the rails expanding this macro do not include it yet. Putting the
; assertion in before they do would fail their builds on a missing macro. The
; assertion belongs here the moment that include is tree-wide; until then the
; contract above is a declaration a reader and the lint can both read, and
; the machine check is the caller-side one this macro does not yet get.
;
; WIDTH-RISK: none by construction, and that is deliberate. The prototype's
; equivalent toggled width around the $213F read; here the read is `region`'s
; and happens once at boot, so the per-frame path is pure A16.
;
; TICK: ok — this macro is the thing that REMOVES a frame coupling. Its "per
;   frame" is the unit it converts OUT of, not one it introduces.
.macro TS_STEP ts_acc, ts_base
    .local ts_ntsc_arm, ts_apply
    .assert (ts_base) > 0, error, "TS_STEP: the base step must be positive"
    .assert (ts_base) <= TS_BASE_MAX, error, "TS_STEP: base step too large — the build-time PAL scale would overflow ca65's 32-bit expression arithmetic (see TS_BASE_MAX)"
    lda z:ES_RGN_PAL
    beq ts_ntsc_arm
    ; The PAL step: the base plus the gain's share of it, ROUNDED rather than
    ; truncated (the +DEN/2). On a base of 2.0 both forms give 615/256 =
    ; 2.40234 against a true 2.403608 — a -0.056% floor that is the whole of
    ; what is left in docs/96's measured 0.99919.
    lda #((ts_base) + ((ts_base) * TS_GAIN_NUM + TS_GAIN_DEN / 2) / TS_GAIN_DEN)
    bra ts_apply
ts_ntsc_arm:
    .a16
    .i16
    lda #(ts_base)              ; NTSC: today's constant, to the unit
ts_apply:
    .a16
    .i16
    clc
    adc ts_acc                  ; + the fraction carried out of last frame
    pha
    and #TS_ONE - 1
    sta ts_acc                  ; the new carried fraction
    pla
    xba                         ; high byte -> low: the whole units
    and #TS_ONE - 1
.endmacro

; -----------------------------------------------------------------------------
; TS_SCALE / TS_SCALED — the same PAL arm, at BUILD time
; -----------------------------------------------------------------------------
;   TS_SCALE(v)          v scaled to a PAL frame, as an expression
;   TS_SCALED <name>, v  the same, DEFINED as a constant and bounds-checked
;
; TS_STEP applies exactly one r, at run time. Two shapes need one before the
; macro ever sees them, and both are build-time work:
;
;   * a per-frame-SQUARED quantity — a gravity, an acceleration ramp — takes r
;     TWICE, so the second one goes into the BASE;
;   * a constant that is ASSIGNED rather than accumulated — a terminal fall
;     speed, a take-off velocity, a cap a clamp writes — carries no fraction
;     and needs its r before it is ever stored.
;
; Ten consumers reached that point independently and each wrote the same
; expression out locally. This is the one copy. It is NOT a second copy of the
; ratio: TS_GAIN_NUM / TS_GAIN_DEN stay single-sourced above and this only
; applies them, with the `+ DEN/2` rounding kept identical to the run-time
; arm's so the two cannot disagree by a count.
;
; PREFER TS_SCALED. It carries the refusal TS_STEP gives its base — an
; over-large value stops the build with a reason instead of wrapping ca65's
; 32-bit expression arithmetic silently, which is the failure the local copies
; had no guard against and documented in prose on two rails instead. TS_SCALE
; is the bare expression, for the sites that embed the scaled value in a larger
; one (a magnitude negated back into two's complement, an .assert on a scaled
; bound); those carry their own asserts already.
;
; ca65 will not parse a define-macro invocation inside another one's argument
; list, so an r-SQUARED site is written as two steps and not as one nesting.
; (the parameter is `v`, not `x`: ca65 reads a bare `x` in a define's parameter
;  list as the index REGISTER and refuses the definition.)
;
; TICK: ok — this pair is the build-time half of the thing that REMOVES a frame
;   coupling. Its "per frame" is the unit it converts OUT of, not one it
;   introduces.
.define TS_SCALE(v) ((v) + ((v) * TS_GAIN_NUM + TS_GAIN_DEN / 2) / TS_GAIN_DEN)

; CONTRACT TS_SCALED
;   entry:    A? I?
;   exit:     A? I?
;   in:       v — a positive build-time constant, the NTSC value to scale
;   out:      `name` DEFINED as the PAL-scaled constant, bounds-checked
;   clobbers: nothing — this macro emits no bytes and touches no register
;   assumes:  v is a MAGNITUDE. A negative velocity is scaled as a magnitude
;             and negated afterwards, so the rounding lands on the number the
;             physics means; the assert below refuses the other spelling
;   tail:     falls through to the caller — this is a macro, not a call
;
; The UNKNOWN entry widths are the literal truth here, not a hedge: nothing
; this macro expands to reads or writes a register, so every arrival is legal
; and there is nothing for an assertion to check.
.macro TS_SCALED name, v
    .assert (v) > 0, error, "TS_SCALED: the value to scale must be positive — a negative velocity is scaled as a MAGNITUDE and negated afterwards, so the rounding lands on the number the physics means"
    .assert (v) <= TS_BASE_MAX, error, "TS_SCALED: value too large — v * TS_GAIN_NUM would overflow ca65's 32-bit expression arithmetic (see TS_BASE_MAX)"
    name = TS_SCALE(v)
.endmacro
