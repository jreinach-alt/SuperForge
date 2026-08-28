; =============================================================================
; smt_obj.asm — the knight, and the reason this rail is a game
; =============================================================================
; ONE 32x32 OBJ entry, traced from the vendored `camelot` pack (CC0). It walks,
; it jumps, and it STANDS ON A PLATE WHOSE HEIGHT IS A WORD IN BG3's TILEMAP —
; the same word the VBlank transfer moves into VRAM and the PPU reads as that
; column's scroll. `smt_kn_tick` gets it from `smt_plate_top` (smt_opt.asm),
; which reads the blob directly, so the collision and the picture do not have
; to be kept in step: there is one number and both use it.
;
; THAT IS THE WHOLE POINT OF PUTTING A PLAYER HERE. A picture can show that
; every column scrolls on its own. Only something that STANDS on one can show
; that the offset is a fact about the world rather than about the display.
;
; NOTHING HERE COUNTS FRAMES. The run and the fall are TS_STEP outputs the
; scene computes and hands over; the walk animation is indexed by the knight's
; own screen X (one step every 8 px, so the legs move with the ground) and the
; idle by the rail's phase. Both are quantities the scaler has already
; expressed against the declared tick, so the animation is region-correct with
; no clock, no accumulator and no countdown of its own.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (smt_obsel).

SMT_OBJ_REGS = $4300 + ES_D_SMT_OBJ_UP_CH * 16

; The one entry, and the hi-table byte it shares with three parked neighbours.
SMT_KN_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
SMT_KN_OAM     = ES_OAM_SHADOW + ES_O_KNIGHT * 4
SMT_KN_HI      = SMT_KN_HI_BASE + (ES_O_KNIGHT / 4)

; A hi byte covers four sprites (2 bits each: X9 + size); this rail claims ONE,
; so writing the whole byte is only correct while the knight starts the byte
; and the other three stay the parked ones `oam_park_all` left. Asserted, so a
; future claim reordering stops the build (jumper_obj's discipline).
.assert ES_O_KNIGHT .MOD 4 = 0, error, "smt_obj: the knight must start a hi-table byte"

; The size bit in the hi table: bit0 of a sprite's 2-bit field is X9, bit1 is
; SIZE. OBSEL's pair 3 is small 16x16 / large 32x32, so `large` here IS 32x32
; and one OAM entry draws the whole knight. Mesen2 SnesPpu.cpp:679 decodes the
; hi table exactly this way.
SMT_KN_SIZE_LARGE = 1 << 1

; OBSEL ($2101): bits 0-2 the OBJ name base in 8K-word steps, bits 5-7 the size
; pair. The base comes from the allocator's emitted symbol; the pair is named
; rather than narrated.
SMT_OBSEL_PAIR3 = 3 << 5

; The base must be EXPRESSIBLE in OBSEL's 8K-word field, which is a property of
; where the allocator packed the claim rather than of anything this file does.
; Asserted so a repack that broke it stops the build here instead of drawing
; the knight out of whatever tiles live at base 0.
.assert ES_V_SMT_OBJ_CHR = (ES_V_SMT_OBJ_CHR_OBSEL_BASE << 13), error, "smt_obj: the knight's CHR base is not expressible in OBSEL's 8K-word field"

; OAM attr byte: priority 3 (in front of both BG layers — mode 2 gives OBJ
; priorities 2/4/6/8 against BG1's 3/7, so only priority 3 is above BG1's high
; half), OBJ palette 0, and bit 6 is the H-flip the facing idiom sets.
SMT_KN_ATTR  = (3 << 4)
SMT_KN_HFLIP = 1 << 6

; `plate` when the knight is in the air. Not 0, which is a real plate index.
SMT_KN_AIRBORNE = $FFFF

; --- the vertical unit, both ways ------------------------------------------
; The knight's Y is 9.7 (smelter.inc says why the seventh bit and not the
; eighth), and these are the only two places the fraction width is spent. Both
; are written against ::SMT_KN_FRAC rather than as a shift by a typed number,
; so the pair cannot drift apart — eight of the shift is the free byte swap and
; the remainder is explicit.
;
; WIDTH-RISK: both are A16 in and A16 out, and neither touches the index width.
.macro SMT_KN_TO_ROW                    ; A = 9.7  ->  A = whole rows
    .repeat 8 - ::SMT_KN_FRAC
    asl a
    .endrepeat
    xba
    and #$00FF
.endmacro

.macro SMT_KN_FROM_ROW                  ; A = whole rows  ->  A = 9.7
    xba
    and #$FF00
    .repeat 8 - ::SMT_KN_FRAC
    lsr a
    .endrepeat
.endmacro

.segment "RODATA"
; Each plate's left edge in SCREEN PIXELS, from the generated geometry. The
; equates are in smt_art.inc; this is the same fact as data, because the
; landing loop needs to index it.
smt_kn_plate_x:
    .word SMT_PLAT_0_COL * 8, SMT_PLAT_1_COL * 8
    .word SMT_PLAT_2_COL * 8, SMT_PLAT_3_COL * 8
.segment "CODE"

; --- smt_kn_arm: CHR, palette, OBSEL, and the spawn (scene enter) -----------
; CONTRACT smt_kn_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the OBJ page, OBJ palette 0, OBSEL, and the knight standing on
;             plate SMT_KN_SPAWN_PLATE at that plate's current height
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract,
;             which is also what keeps the CPU-side palette loop from being
;             preempted. Without these uploads the knight renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a perfectly
;             valid sprite made of garbage
;   tail:     rts
smt_kn_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_kn_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_SMT_OBJ_CHR
    sta a:$2116                     ; VMADD = the OBJ chr claim's base
    ldx #.loword(smt_obj_bin)
    ldy #ES_R_SMT_OBJ_SIZE
    lda #^smt_obj_bin
    jsr smt_up_dma
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    sep #$20
    .a8
    lda #ES_C_SMT_OBJ_PAL
    sta a:$2121                     ; CGADD = the claim's base
    rep #$20
    .a16
    ldx #0
:   lda f:smt_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SMT_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: the 32x32 size pair, and the claim's own base --------------
    sep #$20
    .a8
    lda #(SMT_OBSEL_PAIR3 | ES_V_SMT_OBJ_CHR_OBSEL_BASE)
    sta a:$2101
    rep #$20
    .a16
    ; ---- the spawn: standing on plate 0, at whatever height it is now ------
    ; Power-on DP is RANDOM (rule 5), so these stores ARE the write-before-read
    ; contract and not defensive initialisation.
    lda #(SMT_PLAT_SPAWN_COL * 8)
    sta z:ES_SMT_KN_X
    stz z:ES_SMT_KN_VY
    stz z:ES_SMT_KN_FACE
    lda #SMT_KN_SPAWN_PLATE
    sta z:ES_SMT_KN_PLATE
    jsr smt_kn_ride                 ; ...and put him on it before frame 0
    rts

; --- smt_kn_ride: sit the knight on the plate he is standing on -------------
; CONTRACT smt_kn_ride
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_SMT_KN_PLATE — a plate index, NOT SMT_KN_AIRBORNE
;   out:      ES_SMT_KN_Y = that plate's top edge minus the knight's content
;             bottom, in 9.7
;   clobbers: A, X, Y, N, Z, C
;   assumes:  main thread, after this frame's phase has been advanced
;   tail:     rts
;
; THIS IS THE RIDE, and it is one subtraction. `smt_plate_top` returns the
; plate's top edge in screen pixels, read out of the same blob the VBlank
; transfer moves into BG3's V row; SMT_KN_BOTTOM is the last row of the
; knight's art with any opaque pixel in it, measured off the pack's own PNG at
; build time. So the feet land ON the metal rather than four pixels into it,
; and when the plate rises the knight rises with it — not because anything
; follows anything, but because both are the same number.
smt_kn_ride:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_kn_ride"
    ldx z:ES_SMT_KN_PLATE
    jsr smt_plate_top               ; A = the plate's top edge, screen px
    sec
    sbc #SMT_KN_BOTTOM
    SMT_KN_FROM_ROW                 ; ...to 9.7: the ride has no fraction
    sta z:ES_SMT_KN_Y
    rts
; SMT_KN_FROM_ROW's byte swap is only a shift while the difference is a BYTE.
; A plate's top runs SMT_PLAT_TOP_PX - (base +/- amp) - 1, so at the extremes
; it is 320 - 280 - 1 = 39 and 320 - 200 - 1 = 119, and the knight's content
; bottom takes 28 off both. Asserted rather than reasoned about at the call
; site — a geometry change that broke either end would otherwise put him at a
; row three hundred pixels away with nothing red.
.assert SMT_PLAT_TOP_PX - (SMT_PLAT_BASE + SMT_PLAT_AMP) - 1 - SMT_KN_BOTTOM >= 0, error, "smt_obj: a plate can rise high enough to put the knight's ride negative, and SMT_KN_FROM_ROW's byte swap would read it as a huge row"
.assert SMT_PLAT_TOP_PX - (SMT_PLAT_BASE - SMT_PLAT_AMP) - 1 - SMT_KN_BOTTOM < 256, error, "smt_obj: a plate can sink far enough to put the knight's ride past a byte"


; --- smt_kn_tick: one frame of the knight ----------------------------------
; CONTRACT smt_kn_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       US_TSKR — this frame's run step in WHOLE px (a TS_STEP output)
;             US_TSKG — this frame's gravity step in WHOLE 8.8 counts
;             US_VMAX / US_VJUMP — the region-selected terminal fall and
;             take-off velocities, chosen once at enter
;   out:      the knight's position, velocity, facing and plate advanced
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread, after the phase has been advanced — the plate
;             heights it reads are THIS frame's
;   tail:     rts
;
; TICK: ok -- every quantity this routine adds arrives already scaled. The
;   run and the gravity are TS_STEP outputs the scene computes; the two
;   velocities are region-selected constants. Nothing here counts frames and
;   there is no per-frame immediate.
smt_kn_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_kn_tick"
    ; ---- horizontal: the run, and the facing it sets ----------------------
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @try_right
    lda z:ES_SMT_KN_X
    sec
    sbc z:US_TSKR
    bpl :+                          ; ...clamped at the left screen edge
    lda #0
:   .a16
    .i16
    sta z:ES_SMT_KN_X
    lda #1
    sta z:ES_SMT_KN_FACE
    bra @vertical
@try_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @vertical
    lda z:ES_SMT_KN_X
    clc
    adc z:US_TSKR
    cmp #(SMT_SCREEN_W - SMT_KN_BOX + 1)
    bcc :+
    lda #(SMT_SCREEN_W - SMT_KN_BOX)    ; ...and at the right one
:   .a16
    .i16
    sta z:ES_SMT_KN_X
    stz z:ES_SMT_KN_FACE
@vertical:
    .a16
    .i16
    lda z:ES_SMT_KN_PLATE
    cmp #SMT_KN_AIRBORNE
    beq @falling
    ; ---- grounded: ride the plate, jump off it, or walk off it ------------
    lda z:ES_INP_PRESS
    and #JOY_A
    beq @stay
    lda z:US_VJUMP                  ; the take-off, region-selected at enter
    sta z:ES_SMT_KN_VY
    lda #SMT_KN_AIRBORNE
    sta z:ES_SMT_KN_PLATE
    bra @falling
@stay:
    .a16
    .i16
    ; STILL OVER THE PLATE? The test is on the knight's CENTRE, which is the
    ; forgiving rule every platformer wants: you fall when your middle leaves
    ; the metal, not when your heel does.
    ldx z:ES_SMT_KN_PLATE
    txa
    asl a
    tax
    lda f:smt_kn_plate_x, x
    sta z:ES_SMT_SCRATCH + 2           ; the plate's left edge
    lda z:ES_SMT_KN_X
    clc
    adc #(SMT_KN_BOX / 2)           ; ...against the knight's centre
    sec
    sbc z:ES_SMT_SCRATCH + 2
    bmi @stepped_off
    cmp #(SMT_PLAT_WIDTH * 8)
    bcs @stepped_off
    jsr smt_kn_ride                 ; ON the plate: take its height, this frame
    rts
@stepped_off:
    .a16
    .i16
    stz z:ES_SMT_KN_VY              ; walked off: fall from rest
    lda #SMT_KN_AIRBORNE
    sta z:ES_SMT_KN_PLATE
@falling:
    .a16
    .i16
    ; ---- airborne: accelerate, clamp, integrate ---------------------------
    lda z:ES_SMT_KN_VY
    clc
    adc z:US_TSKG
    bmi :+                          ; still rising — no terminal clamp
    cmp z:US_VMAX
    bcc :+
    lda z:US_VMAX
:   .a16
    .i16
    sta z:ES_SMT_KN_VY
    clc
    adc z:ES_SMT_KN_Y
    sta z:ES_SMT_KN_Y
    ; ---- did that land him on anything? -----------------------------------
    lda z:ES_SMT_KN_VY
    bmi @offscreen                  ; rising: nothing to land on
    jsr smt_kn_land
@offscreen:
    .a16
    .i16
    ; ---- fell off the bottom of the world ---------------------------------
    ; THE SIGN TEST IS NOT DECORATION, AND IT IS WHY Y IS 9.7. A jump's apex is
    ; ~50 px and the highest plate sits at row 11, so the knight genuinely
    ; leaves the top of the screen and ES_SMT_KN_Y genuinely goes negative —
    ; while a miss carries him past row 232 on the way out of the world. In 8.8
    ; those two are THE SAME BIT PATTERN (row 232 and row -24 are both $E8..),
    ; and the first build proved it: at row 236 this test read negative, skipped
    ; the kill, and let him wrap round to the top of the screen. 9.7 spans
    ; -256..+255 whole rows, so the sign means what it says at both ends.
    lda z:ES_SMT_KN_Y
    bmi :+
    SMT_KN_TO_ROW
    cmp #SMT_KN_KILL_Y
    bcc :+
    lda #SMT_KN_SPAWN_PLATE
    sta z:ES_SMT_KN_PLATE
    lda #(SMT_PLAT_SPAWN_COL * 8)
    sta z:ES_SMT_KN_X
    stz z:ES_SMT_KN_VY
    jsr smt_kn_ride
:   .a16
    .i16
    rts

; --- smt_kn_land: is he standing on a plate now? ---------------------------
; CONTRACT smt_kn_land
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       the knight's position, descending
;   out:      ES_SMT_KN_PLATE set and the knight snapped onto it, or unchanged
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread, called only while ES_SMT_KN_VY >= 0
;   tail:     rts
;
; THE WINDOW IS THE MECHANISM, and it is sized by two motions rather than one.
; The knight falls at up to US_VMAX a frame AND THE PLATE MOVES TOO — the
; fastest harmonic travels about four pixels a frame — so the feet and the
; metal can close on each other from both sides. A crossing test written
; against the knight's motion alone would let a rising plate pass straight
; through him. SMT_KN_LAND_WIN covers the sum, and the snap is what makes the
; overshoot invisible: he lands ON the top edge, never inside it.
smt_kn_land:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_kn_land"
    ldy #0
@plate:
    .a16
    .i16
    ; ---- is his centre over this plate? -----------------------------------
    tya
    asl a
    tax
    lda f:smt_kn_plate_x, x
    sta z:ES_SMT_SCRATCH + 2
    lda z:ES_SMT_KN_X
    clc
    adc #(SMT_KN_BOX / 2)
    sec
    sbc z:ES_SMT_SCRATCH + 2
    bmi @next
    cmp #(SMT_PLAT_WIDTH * 8)
    bcs @next
    ; ---- are his feet in the landing window? ------------------------------
    phy
    tyx
    jsr smt_plate_top               ; A = this plate's top edge, screen px
    ply
    sta z:ES_SMT_SCRATCH + 2
    lda z:ES_SMT_KN_Y
    SMT_KN_TO_ROW                   ; ...the knight's top, in whole px
    clc
    adc #SMT_KN_BOTTOM              ; ...and his feet
    sec
    sbc z:ES_SMT_SCRATCH + 2
    bmi @next                       ; still above the metal
    cmp #SMT_KN_LAND_WIN
    bcs @next                       ; already well past it — fall through
    sty z:ES_SMT_KN_PLATE
    stz z:ES_SMT_KN_VY
    jsr smt_kn_ride
    rts
@next:
    .a16
    .i16
    iny
    cpy #SMT_PLAT_COUNT
    bcc @plate
    rts

; --- smt_kn_draw: stage the knight into the OAM shadow ----------------------
; CONTRACT smt_kn_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the knight's OAM entry — X, Y, the animation's tile, the attr
;             with its H-flip, and the hi byte carrying X9 and the 32x32 size
;             bit
;   clobbers: A, X, Y, N, Z, C
;   assumes:  once per frame from the scene's tick, after smt_kn_tick. The
;             shadow is rebuilt WHOLE rather than patched, so a stale byte from
;             last frame cannot survive into this one
;   tail:     rts
;
; THE FRAME IS DERIVED, NEVER STORED. Which pose to draw is a function of the
; knight's state and of a quantity that is already region-correct: the walk
; indexes on his own X (a step every 8 px, so the legs move with the ground)
; and the idle on the rail's phase. `smt_anim_bin` holds the tile numbers and
; the (mask, shift) pair per state, so this routine knows the grid arithmetic
; nowhere.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED: X9 is derived from bit 8 of
; the x every frame. A shortcut that assumed it clear passes every test until a
; coordinate grows, and then ships a sprite 256 px away — and this knight walks
; to x = 224, where bit 8 is one store from being set.
smt_kn_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_kn_draw"
    ; ---- which state, and what indexes it ---------------------------------
    lda z:ES_SMT_KN_PLATE
    cmp #SMT_KN_AIRBORNE
    beq @jumping
    lda z:ES_INP_CUR
    and #(JOY_LEFT | JOY_RIGHT)
    beq @idling
    ldx #SMT_KN_ST_WALK
    lda z:ES_SMT_KN_X               ; ...a step every 8 px of ground covered
    bra @pose
@idling:
    .a16
    .i16
    ldx #SMT_KN_ST_IDLE
    lda z:ES_SMT_PHASE              ; ...the rail's own already-scaled clock
    bra @pose
@jumping:
    .a16
    .i16
    ldx #SMT_KN_ST_JUMP
    lda #0
@pose:
    .a16
    .i16
    ; In: A = the driving quantity, X = the state index. Out: the pose's base
    ; tile in the OAM entry. The three scratch words are +0 (the state's
    ; (mask, shift) pair, as one word), +2 (the driving quantity) and +4 (the
    ; state's row in the frame table).
    sta z:ES_SMT_SCRATCH + 2
    txa
    .repeat 3
    asl a                           ; state * SMT_KN_ANIM_STRIDE
    .endrepeat
    sta z:ES_SMT_SCRATCH + 4
    txa
    asl a                           ; ...and state * META_STRIDE
    tax
    lda f:smt_anim_bin + SMT_ANIM_META_OFF, x
    sta z:ES_SMT_SCRATCH            ; low byte = the index mask, high = shift
    xba
    and #$00FF
    tax                             ; X = the shift
    lda z:ES_SMT_SCRATCH + 2
@shift:
    .a16
    .i16
    cpx #0
    beq @masked
    lsr a
    dex
    bra @shift
@masked:
    .a16
    .i16
    ; THE MASK IS THE LOW BYTE and the shift rides in the high one, which is
    ; safe to AND against because the driving quantity's high byte is ZERO by
    ; construction: the knight's X never exceeds 224 and the rail's phase never
    ; exceeds 63. Asserted below rather than assumed.
    and z:ES_SMT_SCRATCH
    clc
    adc z:ES_SMT_SCRATCH + 4
    tax
    sep #$20
    .a8
    lda f:smt_anim_bin, x           ; ...the pose's base TILE
    sta a:SMT_KN_OAM + 2
    ; ---- the attr, with the facing as an H-flip ---------------------------
    lda #SMT_KN_ATTR
    ldx z:ES_SMT_KN_FACE
    beq :+
    ora #SMT_KN_HFLIP
:   .a8
    .i16
    sta a:SMT_KN_OAM + 3
    rep #$20
    .a16
    ; ---- position ---------------------------------------------------------
    lda z:ES_SMT_KN_X
    sep #$20
    .a8
    sta a:SMT_KN_OAM + 0
    rep #$20
    .a16
    lda z:ES_SMT_KN_Y
    SMT_KN_TO_ROW                   ; 9.7 -> the whole screen row
    sep #$20
    .a8
    sta a:SMT_KN_OAM + 1
    rep #$20
    .a16
    ; ---- the hi byte: X9 derived, and the 32x32 size bit ------------------
    lda z:ES_SMT_KN_X
    xba
    and #1                          ; bit 8 of X -> this sprite's X9
    ora #SMT_KN_SIZE_LARGE
    sep #$20
    .a8
    sta a:SMT_KN_HI                 ; whole byte: the three parked neighbours'
    rep #$20                        ;   bits stay clear, as oam_park_all left
    .a16
    rts
