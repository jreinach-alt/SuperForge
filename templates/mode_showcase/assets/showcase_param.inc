; =============================================================================
; showcase_param.inc — the GENERIC param model: init, slot router, knob clamp.
; =============================================================================
; The engine the per-mode pages reuse unchanged. It is TABLE-DRIVEN: the page
; supplies SHOW_PARAM_TBL (30 x 4 bytes: min,max,step,default, slot-major) and a
; show_apply hook; this module owns the param block in WRAM ($7E:E200) and the
; 6-slot / 5-pair control logic. Nothing here knows about Mode 1 specifically.
;
; PARAM TABLE (in ROM, supplied by the page — see showcase_mode1.inc):
;   SHOW_PARAM_TBL: 30 entries, [slot*5 + param], 4 bytes each:
;       +0 min   +1 max   +2 step   +3 default
;
; BUTTON-PAIR -> PARAM map (allocations / spec): the active slot's 5 params are
; the 5 button-pairs, dec/inc:
;   param 0  <  LEFT   / >  RIGHT
;   param 1  v  DOWN   / ^  UP
;   param 2  B         / A
;   param 3  Y         / X
;   param 4  L         / R
;
; All entry points are A16/I16 in/out (kit subroutine contract).
; WIDTH-RISK: each toggles A8 around the byte-wide param-block accesses (long
; addressing into $7E:E200) and restores A16 before rts.
;
; HUD OAM BUDGET (allocations §2 — the HARD, DETERMINISTIC band partition that
; every fan-out page inherits; the field forces base 48, so the whole HUD must
; fit in OBJ 0-47). Writers set SPRITE_COUNT to their band BASE so the bands are
; fixed, not auto-incrementing-from-0:
;   top readout   OBJ 0-35  : slot label (<=6 glyphs) + 5 x (tag <=3 + value 3)
;                             = 6 + 5*6 = 36 worst-case glyphs (slots 0-35)
;   limit meter   OBJ 36-38 : the 3 bars C/H/O
;   arena owner   OBJ 39    : the $C000 arena-mutex owner indicator glyph
;   bottom bar    OBJ 40-45 : the 6-slot option bar (one glyph per slot)
;   (spare)       OBJ 46-47 : headroom — never written by the harness
;   field         OBJ 48+   : show_field_tick forces SPRITE_COUNT=48 (separate)
; Contract maxima for a page: slot-label <= 6 glyphs, value-tag <= 3 glyphs,
; value <= 3 digits. Worst-frame total <= 46 <= 48. show_hud_budget_guard
; verifies SPRITE_COUNT <= 48 after the HUD band and records any overflow.
; =============================================================================
SHOW_OAM_TOP_BASE   = 0      ; top readout (label + params) base slot
SHOW_OAM_METER_BASE = 36     ; the 3 limit-meter bars
SHOW_OAM_ARENA_BASE = 39     ; the arena-owner indicator glyph
SHOW_OAM_BAR_BASE   = 40     ; the 6-slot bottom bar
SHOW_OAM_FIELD_BASE = 48     ; the sprite field (forced by show_field_tick)

; -----------------------------------------------------------------------------
; show_param_init — seed the param block from the ACTIVE mode's resolved table
; defaults, under forced blank (power-on RAM is garbage — allocations §1 mandates
; an explicit seed). PRESERVES SHOW_CUR_MODE across the zeroing (the menu owns
; the selected mode; this re-seed must not wipe it on demo entry — DISPATCH).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte stores; exits A16/I16.
.proc show_param_init
    rep #$30
    .a16
    .i16
    ; Save the selected mode — it lives inside the 256-byte block ($E23D) the
    ; loop below clears, but it is owned by the menu, not this seeder.
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    pha                             ; [1,s] = saved selected mode
    rep #$20
    .a16
    ; Zero the whole 256-byte block first (knob aux, flags, field, etc.).
    ldx #0
@zero:
    sep #$20
    .a8
    lda #0
    sta f:SHOW_BASE, x
    rep #$20
    .a16
    inx
    cpx #256
    bcc @zero
    ; Seed each of the 30 knobs to its table default (entry +3). Y = knob index
    ; (loop), X = table byte offset (knob*4) for the long-indexed table read
    ; (65816 long indexing is X-only). The default is copied through A.
    ldy #0                          ; Y = knob index 0..29
@seed:
    tya
    asl
    asl                             ; knob*4
    tax                             ; X = table byte offset
    sep #$20
    .a8
    lda f:SHOW_A_PARAM_TBL+3, x     ; default byte (ACTIVE mode's resolved table)
    pha
    rep #$20
    .a16
    tya
    tax                             ; X = knob index (long index for KNOB_VAL)
    sep #$20
    .a8
    pla                             ; default byte
    sta f:SHOW_KNOB_VAL, x          ; store at knob index
    rep #$20
    .a16
    iny
    cpy #(SHOW_N_SLOTS * SHOW_N_PARAMS)
    bcc @seed
    ; Active slot = 0; preset 0. Restore the menu-selected mode (saved above) —
    ; the zero loop cleared $E23D, but SHOW_CUR_MODE is the menu's, not ours.
    sep #$20
    .a8
    lda #0
    sta f:SHOW_ACTIVE_SLOT
    pla                             ; saved selected mode
    sta f:SHOW_CUR_MODE
    lda #0
    sta f:SHOW_PRESET
    ; --- F8: seed the read-before-write $E300+ harness bytes (power-on RAM is
    ;     garbage — never assume zero). These live OUTSIDE the $E200-$E2FF block
    ;     the loop above cleared, so seed them explicitly here under forced blank.
    lda #ARENA_NONE
    sta f:SHOW_ARENA_OWNER          ; arena mutex: no heavy effect held at boot
    lda #0
    sta f:SHOW_OAM_OVF              ; HUD OAM-budget overflow flag clear
    lda #0
    sta f:SHOW_SAVE_SLOT_SEL        ; active SRAM save slot = 0
    lda #0
    sta f:SHOW_OAM_USED            ; realized OAM count (meter O signal) seed
    lda #$17                        ; sane TM snapshot (matches the page default)
    sta f:SHOW_TM_SNAP             ; param-sheet TM restore snapshot
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; show_hud_budget_guard — F4: enforce the HUD OAM budget. The HUD top + meter +
; arena + bottom bar must all fit in OBJ 0-47 (the field forces base 48). If a
; page's labels/tags overflow past slot 48, those glyphs would be overwritten by
; the field — so clamp SPRITE_COUNT to 48 and record the overflow in SHOW_OAM_OVF
; (debug-readable; a test asserts it stays 0 for a compliant page). Call AFTER
; the HUD/meter/arena writers and BEFORE show_field_tick.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; exits A16/I16.
.proc show_hud_budget_guard
    rep #$30
    .a16
    .i16
    lda SPRITE_COUNT
    cmp #(SHOW_OAM_FIELD_BASE + 1)   ; > 48 ? (count is the NEXT free slot)
    bcc @ok                          ; <= 48 -> within budget
    ; overflow: a page exceeded the 0-47 HUD band. Flag it and clamp so the
    ; field band (48+) is never corrupted by stray HUD glyphs.
    sep #$20
    .a8
    lda #1
    sta f:SHOW_OAM_OVF
    rep #$20
    .a16
    lda #SHOW_OAM_FIELD_BASE
    sta SPRITE_COUNT
@ok:
    rts
.endproc

; -----------------------------------------------------------------------------
; show_slot_advance — Select: lit slot := (slot+1) mod 6.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte RMW; exits A16/I16.
.proc show_slot_advance
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_ACTIVE_SLOT
    inc a
    cmp #SHOW_N_SLOTS
    bcc @store
    lda #0
@store:
    sta f:SHOW_ACTIVE_SLOT
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; show_knob_router — read the 5 button-pairs and adjust the ACTIVE slot's params.
; -----------------------------------------------------------------------------
; Held-button (btn, not btnp) so a held direction ramps the value — the live
; tuning feel. Each pair: the "dec" button steps down by `step`, the "inc"
; button steps up by `step`, both clamped to [min,max]. param index = slot*5+p.
; WIDTH-RISK: A16/I16 entry; helpers run their own widths; exits A16/I16.
.proc show_knob_router
    rep #$30
    .a16
    .i16
    ; param 0: LEFT- / RIGHT+
    btn #BTN_LEFT
    beq @r0
    ldx #0
    jsr _knob_dec
@r0:
    btn #BTN_RIGHT
    beq @d1
    ldx #0
    jsr _knob_inc
@d1:
    ; param 1: DOWN- / UP+
    btn #BTN_DOWN
    beq @u1
    ldx #1
    jsr _knob_dec
@u1:
    btn #BTN_UP
    beq @b2
    ldx #1
    jsr _knob_inc
@b2:
    ; param 2: B- / A+
    btn #BTN_B
    beq @a2
    ldx #2
    jsr _knob_dec
@a2:
    btn #BTN_A
    beq @y3
    ldx #2
    jsr _knob_inc
@y3:
    ; param 3: Y- / X+
    btn #BTN_Y
    beq @x3
    ldx #3
    jsr _knob_dec
@x3:
    btn #BTN_X
    beq @l4
    ldx #3
    jsr _knob_inc
@l4:
    ; param 4: L- / R+
    btn #BTN_L
    beq @r4
    ldx #4
    jsr _knob_dec
@r4:
    btn #BTN_R
    beq @done
    ldx #4
    jsr _knob_inc
@done:
    rep #$30
    .a16
    .i16
    rts
.endproc

; -----------------------------------------------------------------------------
; _knob_setup — X = param-within-slot (0..4). Computes knob = active_slot*5+param,
; returns X = knob index (the long index for SHOW_KNOB_VAL), and copies the
; knob's min/max/step from SHOW_PARAM_TBL into SHOW_KMIN/KMAX/KSTEP. 65816 long
; indexing is X-only, so the inc/dec clamps read the cached scratch (not the
; table) — that is why this helper pre-loads them.
; -----------------------------------------------------------------------------
; WIDTH-RISK: I16/A16 entry; A8 internally; exits A8 with X = knob index.
.proc _knob_setup
    rep #$30
    .a16
    .i16
    phx                             ; [1,s] = param (16-bit, 0..4)
    sep #$20
    .a8
    lda f:SHOW_ACTIVE_SLOT
    rep #$20
    .a16
    and #$00FF                      ; A = slot
    pha                             ; [1,s] = slot ; [3,s] = param
    asl
    asl                             ; slot*4
    clc
    adc 1, s                        ; + slot = slot*5
    clc
    adc 3, s                        ; + param = knob index
    and #$00FF
    plx                             ; discard slot (balance pha)
    plx                             ; discard param (balance phx)
    tax                             ; X = knob index
    ; table offset = knob*4 -> cache min/max/step. Use the stack to hold knob
    ; while X becomes the table offset.
    phx                             ; [1,s] = knob index
    txa
    asl
    asl                             ; knob*4 = table offset
    tax                             ; X = table offset
    sep #$20
    .a8
    lda f:SHOW_A_PARAM_TBL+0, x     ; ACTIVE mode's resolved descriptor table
    sta f:SHOW_KMIN
    lda f:SHOW_A_PARAM_TBL+1, x
    sta f:SHOW_KMAX
    lda f:SHOW_A_PARAM_TBL+2, x
    sta f:SHOW_KSTEP
    rep #$20
    .a16
    plx                             ; X = knob index (for SHOW_KNOB_VAL,x)
    sep #$20
    .a8
    rts
.endproc

; -----------------------------------------------------------------------------
; _knob_inc / _knob_dec — X = param-within-slot (0..4); step the knob, clamp.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc _knob_inc
    rep #$30
    .a16
    .i16
    jsr _knob_setup                 ; X = knob index; SHOW_K* = min/max/step (A8)
    .a8
    lda f:SHOW_KNOB_VAL, x          ; current value
    clc
    adc f:SHOW_KSTEP                ; + step
    ; CRITICAL: the add can carry out of 8 bits (val+step > 255), wrapping the
    ; accumulator to a LOW byte. The following cmp loses that add-carry, so a
    ; wrapped value would wrongly pass `bcc @ok` (e.g. max=255 step=2: 254->0).
    ; Test the add-carry FIRST: a carry-out means we overflowed -> clamp to max.
    bcs @clampmax                   ; add overflowed 255 -> at/over the ceiling
    cmp f:SHOW_KMAX                 ; vs max
    beq @ok                         ; == max -> keep
    bcc @ok                         ; <  max -> keep
@clampmax:
    .a8
    lda f:SHOW_KMAX                ; clamp to max
@ok:
    .a8
    sta f:SHOW_KNOB_VAL, x
    rep #$20
    .a16
    rts
.endproc

; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc _knob_dec
    rep #$30
    .a16
    .i16
    jsr _knob_setup                 ; X = knob index; SHOW_K* set (A8)
    .a8
    lda f:SHOW_KNOB_VAL, x          ; current value
    sec
    sbc f:SHOW_KSTEP               ; - step
    bcc @floor                      ; underflow -> clamp to min
    cmp f:SHOW_KMIN                ; vs min
    bcs @ok                         ; >= min -> keep
@floor:
    .a8
    lda f:SHOW_KMIN               ; clamp to min
@ok:
    .a8
    sta f:SHOW_KNOB_VAL, x
    rep #$20
    .a16
    rts
.endproc
