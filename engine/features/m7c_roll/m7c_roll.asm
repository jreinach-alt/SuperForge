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
    bne @apply
    lda z:US_DIR
    eor #1
    sta z:US_DIR                        ; flip direction
    jsr roll_new_leg                    ; peaks now come from the OTHER stream
    bra @apply

@active:
    .a16
    lda z:US_SUBPH
    bne @fall
    ; ---- RISING: accelerate smoothly toward this surge's peak -------------
    lda z:US_VMAG
    clc
    adc #ROLL_ACCEL
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
    lda z:US_VMAG
    sec
    sbc #ROLL_DECEL
    bcc @dip                            ; underflowed 0 -> at the dip
    cmp #ROLL_VFLOOR
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
    lda #ROLL_HOLD
    sta z:US_HOLD
    bra @sign
@nexthump:
    .a16
    lda #ROLL_VFLOOR
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
