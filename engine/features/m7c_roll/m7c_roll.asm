; =============================================================================
; m7c_roll.asm — the chamber's vertical roll: surge, hold, reverse
; =============================================================================
; The rail's whole motion model, and it is NOT a rotation. The angle is
; constant; what moves is the camera's world Y, and the apparent rotation is
; that scroll seen through m7_barrel's static bow. So the per-frame cost is one
; 24-bit add and four DP stores — no matrix, no solve, no table rebuild.
;
; THE LEG CYCLE, which is also the test surface:
;  ROLLING NUM_HUMPS surges. Each rises by ACCEL toward a randomised peak,
;  touches it for one frame, then falls by DECEL (four times faster)
;  to a creep floor. At the dip the next surge starts.
;  HOLDING after the last surge: a dead stop for HOLD_FRAMES.
;  reverse the hold expires, the direction flips, a fresh leg begins — and
;  its peaks come from the OTHER LFSR, so the two directions do not
;  replay each other.
; Forward AND reverse AND idle, driven by the rail itself, deterministically.
;
; The feel constants live in game/mode7_chamber/world.inc beside the geometry.

; --- the roll's feel, in 8.8 px/frame ---------------------------------------
; Decimal, not hex: a bare $0400 lands inside a real WRAM claim and
; `no_literals` cannot tell it from a hand-narrated address.
ROLL_FIX      = 8                       ; the 8.8 fraction width
ROLL_ACCEL    = 2                       ; rise rate  (smooth "speed up")
ROLL_DECEL    = 8                       ; fall rate  (4x accel — "drop quickly")
ROLL_VFLOOR   = 1 << (ROLL_FIX - 2)     ; 0.25 px/frame creep between surges
ROLL_PEAK_MIN = 1 << ROLL_FIX           ; 1.0 px/frame minimum surge peak
ROLL_PEAK_MSK = (1 << 10) - 1           ; the peak's random span
ROLL_PEAK_CAP = 4 << ROLL_FIX           ; 4.0 px/frame — the hard cap
ROLL_HUMPS    = 3                       ; surges per leg
ROLL_HOLD     = 30                      ; ~0.5 s dead stop between legs (60 fps)
; The two LFSR seeds, decimal ($A357 and $1D8B).
; Arbitrary bit patterns rather than magnitudes, so there is no shift form that
; would say more than the number does.
ROLL_SEED_F   = 41815                   ; forward stream's variance pattern
ROLL_SEED_R   = 7563                    ; reverse stream's — a DIFFERENT one
; The Galois taps, written as the TAP POSITIONS rather than as $B400: bits 15,
; 13, 12 and 10 of the 16-bit register, which is the maximal-length polynomial
; x^16 + x^14 + x^13 + x^11 + 1 in Galois form.
ROLL_TAPS     = (1 << 15) | (1 << 13) | (1 << 12) | (1 << 10)

ROLL_VSGN = ES_ROLL_SCR + 0             ; the 24-bit add's sign-extension byte

; =============================================================================
; THE ROLL IN TWO REGIONS — which power of the frame ratio each number takes
; =============================================================================
; `tick_scale` publishes the measured ratio between the two machines' frames as
; a GAIN: a PAL frame lasts r = 1 + TS_GAIN_NUM/TS_GAIN_DEN = 1.2018039 NTSC
; frames. Nothing above is a published integer step of the kind `scroller`
; consumes, because the roll is a VELOCITY MODEL — docs/95 §5.2's class A,
; where "the sub-pixel accumulator absorbs the fraction". What converts is the
; four constants the velocity is built from, and the DIMENSION of each decides
; its exponent:
;
;   a VELOCITY is px per frame.  px/s is preserved by scaling it by r.
;     -> ROLL_VFLOOR, and the drawn surge peak (roll_gain, at runtime).
;   an ACCELERATION is px per frame PER FRAME.  px/s^2 is preserved by
;     scaling it by r SQUARED — one r for the velocity it produces and one for
;     the frame it produces it in. Getting this wrong is invisible in the
;     average speed (mean surge speed is (peak+floor)/2 and has no ACCEL in
;     it at all) and visible in the RHYTHM: the surge would last 20% longer.
;     -> ROLL_ACCEL, ROLL_DECEL.
;   a DWELL is a count of frames.  Real seconds are preserved by scaling it by
;     1/r: 30 NTSC frames and 25 PAL frames are both 0.4995 s.
;     -> ROLL_HOLD. This one is a JUDGMENT and the other direction was
;     measured: left at 30, the dead stop is 0.600 s on PAL against 0.499 s on
;     NTSC, the stopped share of a leg goes 2.33% -> 2.89%, and the rail
;     measures 0.994 instead of 0.999. It is scaled because it is part of the
;     MOTION CYCLE the observable integrates, not a game-feel window like an
;     invulnerability timer.
;
; TS_RGAIN is one application of r, rounded. ca65 evaluates in 32 bits, so the
; SQUARE is taken by applying it twice over a value pre-multiplied by
; TS_RSCALE — 2 and 8 are far too small to survive two integer roundings
; otherwise (2 -> 2 -> 2 instead of 2 -> 3).
;
; TICK: ok — this block is the region compensator's own derivation for this
;   rail. Naming the NTSC frame beside the PAL one is the subject of the
;   comment rather than a coupling in it, exactly as in tick_scale.asm.
.define TS_RGAIN(v)  ((((v) * (TS_GAIN_DEN + TS_GAIN_NUM)) + TS_GAIN_DEN / 2) / TS_GAIN_DEN)
; The ramp rates are already 8.8, so the square needs no extra headroom of its
; own: TS_RSCALE = 1 keeps 2048 * 300451 inside 32 bits with room over.
TS_RSCALE = 1
.assert ROLL_DECEL_88 * TS_RSCALE * (TS_GAIN_DEN + TS_GAIN_NUM) > 0, error, "m7c_roll: the region square overflows ca65's 32-bit expression arithmetic"

; THE TWO RAMP RATES ARE CARRIED AS 8.8 OF AN LSB, and the fraction is the
; whole reason. Rounded to whole LSBs the PAL rise rate is 3 against a true
; 2.889 — +3.8% — which does not move the average speed at all (mean surge
; speed is (peak + floor)/2 and contains no ACCEL) but shortens the surge by
; the same 3.8%, so the two machines walk out of phase with each other and a
; window that is not a whole number of legs reads the drift rather than the
; rate. MEASURED, before the fraction was carried: 1.00539 with the two
; halves at 88.4/129.7 PAL against 114.1/102.8 NTSC. `docs/95` §5.2's "no
; correct x5/6, only a rounding policy" is exactly this, and the accumulator
; is the kit's answer to it — the same answer TS_STEP gives an integer step.
ROLL_RATE_ONE   = 1 << ROLL_FIX         ; one whole LSB of velocity, in 8.8
ROLL_FRAC_MASK  = ROLL_RATE_ONE - 1
ROLL_ACCEL_88     = ROLL_ACCEL * ROLL_RATE_ONE
ROLL_DECEL_88     = ROLL_DECEL * ROLL_RATE_ONE
ROLL_ACCEL_88_PAL = (TS_RGAIN(TS_RGAIN(ROLL_ACCEL_88 * TS_RSCALE)) + TS_RSCALE / 2) / TS_RSCALE
ROLL_DECEL_88_PAL = (TS_RGAIN(TS_RGAIN(ROLL_DECEL_88 * TS_RSCALE)) + TS_RSCALE / 2) / TS_RSCALE
ROLL_VFLOOR_PAL = TS_RGAIN(ROLL_VFLOOR)
ROLL_HOLD_PAL   = (ROLL_HOLD * TS_GAIN_DEN + (TS_GAIN_DEN + TS_GAIN_NUM) / 2) / (TS_GAIN_DEN + TS_GAIN_NUM)

; The runtime peak conversion, as a 13/64 rational. The drawn peak is a
; RANDOM word, so it cannot be converted at build time — and a full multiply
; is not worth buying for a value that changes once every ~400 frames. 13/64 =
; 1.203125 against the true 1.2018039: +0.11%, which is inside the rounding
; the 8.8 velocity already carries.
ROLL_GAIN_MUL = 13                      ; 8 + 4 + 1, built out of two shifts
ROLL_GAIN_LOG = 6                       ; ...over 2^6
ROLL_GAIN_RND = 1 << (ROLL_GAIN_LOG - 1)

; =============================================================================
; roll_commit — the moving half of the camera origin, from posy
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; M7Y is where the camera is in the world; M7VOFS is where the screen's origin
; sits relative to it. Subtracting the picture's BOTTOM scanline pins the
; viewpoint to the last row — Y = D(SY)*(SY - CH_LINES) + M7Y — so the bottom
; of the screen is exactly the camera's own world row and everything above it
; recedes. No trigonometry, because there is no rotation.
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep in the body.
roll_commit:
    .a16
    .i16
    lda z:US_POSY+1                     ; the integer half of the 16.8 position
    sta z:MB_M7Y
    sec
    sbc #CH_LINES
    sta z:MB_VOFS
    rts

; =============================================================================
; ROLL_RAMP — one frame of a velocity ramp, with the fraction carried
; =============================================================================
; In/out: A16/I16. In: `rate` is an 8.8-of-an-LSB per-frame rate. Out: A = the
; WHOLE LSBs of velocity this frame owes, 0 or more. Clobbers A, US_R_FRAC and
; one stack word (one pha, one pla, both A16).
;
; On NTSC the rate is a whole number of LSBs (512 = 2, 2048 = 8), the carried
; fraction stays 0 for ever, and this publishes today's constant on every
; frame — which is why the NTSC picture cannot move. The same property
; TS_STEP has, for the same reason.
;
; ONE accumulator serves both arms. They are mutually exclusive within a frame
; and `roll_new_leg` clears it, so the most either can inherit from the other
; is the sub-LSB remainder of a single frame.
;
; WIDTH-RISK: none by construction — the body contains no sep/rep at all, so
; it cannot leak a width to either arm that expands it.
.macro ROLL_RAMP rate
    lda z:US_R_FRAC
    clc
    adc rate
    pha
    and #ROLL_FRAC_MASK
    sta z:US_R_FRAC                 ; the fraction carried into next frame
    pla
    xba                             ; high byte -> low: the whole LSBs
    and #ROLL_FRAC_MASK
.endmacro

; =============================================================================
; roll_region_init — the four numbers, in the units of the running console
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A. Called ONCE, from roll_init, before
; anything reads a word it writes.
;
; ONE region test, four words. The alternative — a test at each of the seven
; sites in the kernel — is seven chances to write the sense backwards, and it
; would put a branch on the per-frame path for a value that cannot change
; while the console is on.
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep in the body. `@pal` is reached
; A16 by branch and `@ntsc` A16 by fall-through.
roll_region_init:
    .a16
    .i16
    lda z:ES_RGN_PAL
    bne @pal
    lda #ROLL_ACCEL_88              ; NTSC: today's constants, to the LSB
    sta z:US_R_ACCEL
    lda #ROLL_DECEL_88
    sta z:US_R_DECEL
    lda #ROLL_VFLOOR
    sta z:US_R_VFLOOR
    lda #ROLL_HOLD
    sta z:US_R_HOLD
    rts
@pal:
    .a16
    .i16
    lda #ROLL_ACCEL_88_PAL          ; r^2 — an acceleration
    sta z:US_R_ACCEL
    lda #ROLL_DECEL_88_PAL          ; r^2
    sta z:US_R_DECEL
    lda #ROLL_VFLOOR_PAL            ; r   — a velocity
    sta z:US_R_VFLOOR
    lda #ROLL_HOLD_PAL              ; 1/r — a dwell in frames
    sta z:US_R_HOLD
    rts

; =============================================================================
; roll_gain — one runtime application of the frame ratio, as 13/64
; =============================================================================
; In: A16/I16, DB=0, A = an unsigned value below 5,041 (13*A must stay inside
; a word). Out: A = A * 1.203125, rounded. Clobbers A and US_GTMP.
;
; 13*A is (((A*2)+A)*4), which is why the multiplier is 13 and not some nearer
; rational: it is two shifts and two adds. The +32 before the shift is
; round-to-nearest rather than truncation — at a peak of 1.0 px/frame the
; difference is a whole LSB of velocity, and the surge's mean speed is
; (peak + floor)/2, so a truncated peak is a directly measurable bias.
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep, no branch, no label.
roll_gain:
    .a16
    .i16
    sta z:US_GTMP                   ; A
    asl a                           ; 2A
    clc
    adc z:US_GTMP                   ; 3A
    asl a                           ; 6A
    asl a                           ; 12A
    clc
    adc z:US_GTMP                   ; 13A
    clc
    adc #ROLL_GAIN_RND              ; round-to-nearest before the shift
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                           ; 13A / 64 = 0.203125 * A
    clc
    adc z:US_GTMP                   ; A + that = 1.203125 * A
    rts

; =============================================================================
; roll_draw_peak — the next surge's randomised peak, from THIS direction's LFSR
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; HCUR = min(PEAK_MIN + (dirRNG & PEAK_MSK), PEAK_CAP), stepping the LFSR that
; belongs to the CURRENT direction. Two streams, so a reverse leg's variance is
; its own rather than a replay of the forward leg's.
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep. Every local label is reached A16
; by branch AND by fall-through.
roll_draw_peak:
    .a16
    .i16
    lda z:US_DIR
    bne @rev
    lda z:US_RNG_F                      ; the forward stream
    lsr a
    bcc @f
    eor #ROLL_TAPS
@f:
    .a16
    sta z:US_RNG_F
    bra @have
@rev:
    .a16
    lda z:US_RNG_R                      ; the reverse stream — a DIFFERENT one
    lsr a
    bcc @r
    eor #ROLL_TAPS
@r:
    .a16
    sta z:US_RNG_R
@have:
    .a16
    and #ROLL_PEAK_MSK
    clc
    adc #ROLL_PEAK_MIN
    cmp #ROLL_PEAK_CAP
    bcc @store                          ; below the cap -> keep
    lda #ROLL_PEAK_CAP
@store:
    .a16
    sta z:US_HCUR
    ; THE PEAK IS DRAWN IN NTSC UNITS AND THEN CONVERTED, rather than the span
    ; being widened: the draw keeps the authored distribution — a uniform
    ; 1024-wide span from PEAK_MIN, clamped at PEAK_CAP — and one conversion
    ; moves the whole of it. A peak is a VELOCITY, so it takes r once.
    lda z:ES_RGN_PAL
    beq @done
    lda z:US_HCUR
    jsr roll_gain
    sta z:US_HCUR
@done:
    .a16
    .i16
    rts

; =============================================================================
; roll_new_leg — begin a fresh leg from a standstill
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
roll_new_leg:
    .a16
    .i16
    stz z:US_HUMP
    stz z:US_SUBPH                      ; rising
    stz z:US_VMAG                       ; from a dead stop
    stz z:US_RSTATE                     ; ROLLING
    stz z:US_R_FRAC                     ; ...and no ramp remainder carried in
    jsr roll_draw_peak
    rts

; =============================================================================
; roll_init — seed the machine and stamp the constant half of the origin
; =============================================================================
; In/out: A16/I16, DB=0, forced blank (scene enter). Clobbers A.
;
; Power-on DP is random and neither this feature nor the state declares an
; `[init] zero` for it: these stores ARE the write-before-read contract (rule
; 5), not defensive initialisation. A missing one shows as a chamber rolling at
; a speed nobody chose, or an LFSR stuck at zero (a Galois LFSR seeded 0 never
; leaves 0 — the surge peaks would be identical forever).
roll_init:
    .a16
    .i16
    lda #ROLL_SEED_F
    sta z:US_RNG_F
    lda #ROLL_SEED_R
    sta z:US_RNG_R
    stz z:US_DIR                        ; forward
    stz z:US_HOLD
    stz z:US_VEL
    ; The four region numbers FIRST: roll_new_leg draws a peak below and
    ; roll_tick reads the other three from the next frame onward, so they are
    ; written before anything reads one (rule 5).
    jsr roll_region_init
    ; posy = CH_START_Y with a zero fraction. The A16 stz clears the fraction
    ; byte and the integer's low byte; the store that follows overwrites the
    ; integer WORD at +1, so the fraction survives at zero.
    stz z:US_POSY
    lda #CH_START_Y
    sta z:US_POSY+1
    jsr roll_new_leg                    ; HUMP/SUBPH/VMAG/RSTATE + the first peak

    ; ---- the constant half of the camera origin --------------------------
    ; Horizontal position never changes on this rail — the roll is purely
    ; vertical — so M7X and M7HOFS are stamped here once and the NMI hook
    ; commits them unchanged every frame. HOFS = M7X - half the screen puts
    ; the pivot at screen centre.
    lda #CH_CAM_X
    sta z:MB_M7X
    sec
    sbc #CH_HALF_W
    sta z:MB_HOFS
    jsr roll_commit                     ; ...and the moving half, from posy
    rts

; =============================================================================
; roll_tick — one frame of the leg cycle
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; WIDTH-RISK: A16/I16 on entry and exit. The body DOES toggle — the
; sign-extension byte and the 24-bit add's high half are 8-bit — so every label
; below carries the width its arrivals actually have, and the routine restores
; A16 before its `rts`. @apply is reached A16 from three places (the HOLDING
; arm's two exits and the fall-through from @vel).
roll_tick:
    .a16
    .i16
    lda z:US_RSTATE
    beq @active

    ; ---- HOLDING: dead stop, count down, then reverse into a fresh leg ----
    stz z:US_VEL
    lda z:US_HOLD
    dec a
    sta z:US_HOLD
    beq @newleg
    jmp @apply                          ; JMP, not BRA: the two ramp arms below
                                        ;   grew past a relative branch's reach
                                        ;   when the fraction accumulator
                                        ;   landed in them
@newleg:
    .a16
    .i16
    lda z:US_DIR
    eor #1
    sta z:US_DIR                        ; flip direction
    jsr roll_new_leg                    ; peaks now come from the OTHER stream
    jmp @apply

@active:
    .a16
    lda z:US_SUBPH
    bne @fall
    ; ---- RISING: accelerate smoothly toward this surge's peak -------------
    ROLL_RAMP z:US_R_ACCEL              ; the rise rate of THIS console
    clc
    adc z:US_VMAG
    cmp z:US_HCUR
    bcc @setmag                         ; still below the peak -> keep rising
    lda z:US_HCUR                       ; the peak is TOUCHED, not held
    sta z:US_VMAG
    lda #1
    sta z:US_SUBPH                      ; -> falling
    bra @sign

@fall:
    .a16
    ; ---- FALLING: drop quickly toward the creep floor (DECEL > ACCEL) -----
    ROLL_RAMP z:US_R_DECEL              ; ...and its fall rate
    sta z:US_GTMP
    lda z:US_VMAG
    sec
    sbc z:US_GTMP
    bcc @dip                            ; underflowed 0 -> at the dip
    cmp z:US_R_VFLOOR
    bcc @dip                            ; below the creep floor -> at the dip
@setmag:
    .a16
    sta z:US_VMAG
    bra @sign

@dip:
    .a16
    ; ---- surge complete: next surge, or end the leg after NUM_HUMPS -------
    lda z:US_HUMP
    inc a
    sta z:US_HUMP
    cmp #ROLL_HUMPS
    bcc @nexthump
    stz z:US_VMAG                       ; all surges done -> dead stop + HOLD
    lda #1
    sta z:US_RSTATE
    lda z:US_R_HOLD                     ; 30 NTSC frames, 25 PAL: 0.4995 s
    sta z:US_HOLD
    bra @sign
@nexthump:
    .a16
    lda z:US_R_VFLOOR
    sta z:US_VMAG                       ; resume from the slow creep
    stz z:US_SUBPH                      ; rising again
    jsr roll_draw_peak                  ; a NEW peak — the variance

@sign:
    .a16
    ; ---- signed velocity = +VMAG forward, -VMAG reverse -------------------
    lda z:US_DIR
    beq @fwd
    lda #0
    sec
    sbc z:US_VMAG                       ; -VMAG (two's complement by subtraction)
    bra @vel
@fwd:
    .a16
    lda z:US_VMAG
@vel:
    .a16
    sta z:US_VEL

@apply:
    .a16
    ; ---- posy (16.8, 24-bit) += the signed 8.8 velocity ------------------
    ; The low word of posy is [fraction: integer low], so a single 16-bit add
    ; of the 8.8 velocity carries the fraction into the integer for free. The
    ; integer's HIGH byte then takes the carry plus a sign-extension byte,
    ; which is what makes a NEGATIVE velocity borrow correctly instead of
    ; adding 255 to the high byte.
    sep #$20
    .a8
    lda z:US_VEL+1                      ; the velocity's high byte carries the sign
    bpl @possgn
    lda #255
    bra @addsgn
@possgn:
    .a8
    lda #0
@addsgn:
    .a8
    sta z:ROLL_VSGN
    rep #$20
    .a16
    lda z:US_POSY                       ; fraction : integer low
    clc
    adc z:US_VEL
    sta z:US_POSY
    sep #$20
    .a8
    lda z:US_POSY+2                     ; integer high
    adc z:ROLL_VSGN                     ; + sign extension + the carry above
    sta z:US_POSY+2
    rep #$20
    .a16
    lda z:US_POSY+1                     ; the integer word
    and #CH_MAP_MASK                    ; wrap to the plane's period, BOTH ways
    sta z:US_POSY+1
    jsr roll_commit
    rts
