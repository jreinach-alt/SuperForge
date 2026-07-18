; =============================================================================
; showcase_meter.inc — the LIMIT METER + the $C000 arena mutex.
; =============================================================================
; "Surface the limits, in colour" (spec). THREE DISTINCT honest signals, each a
; small bar green -> yellow -> red, on the right edge of the top HUD strip:
;   C (cycle budget) : a coarse WEIGHTED cost estimate — sum of armed heavy-
;                      effect weights (armed HDMA channels + the arena owner)
;                      PLUS the page's cost-knob count. Approaches red as the
;                      frame's per-scanline + per-frame work climbs.
;   H (HDMA channels): popcount of NMI_HDMA_ENABLE (armed HDMA channels) — the
;                      6-channel (CH2-CH7) budget.
;   O (OAM sprites)  : the ACTUAL sprites placed this frame (SPRITE_COUNT after
;                      the field tick), the §2 32/line lesson read from reality
;                      (not a knob proxy).
; These are three INDEPENDENT axes: C blends the whole cost, H counts channels,
; O counts the rendered OAM. The bar COLOUR is its OBJ palette: pal 4 = green,
; pal 5 = yellow, pal 6 = red (entry 1 of each, uploaded by show_meter_init to
; CGRAM 192/208/224 +1). The level byte (0=green,1=yellow,2=red) is also
; exported in SHOW_METER_* so the test can read the threshold crossing.
;
; GENERICITY: this module references NO page (KN_*) symbol. Each page registers
; which knob feeds the cost/OAM proxy (its costknob arg); the ACTIVE mode's value
; is resolved into SHOW_A_COST_KNOB and read at runtime here. The arena-owner
; indicator glyph is rendered per-mode (the m*_arena_ind vtable entry).
;
; ARENA MUTEX: the $7E:C000 HDMA arena holds <=1 heavy effect (gradient OR
; parallax OR OPT). show_arena_request(owner) auto-disables the current owner
; before granting — never a crash, and SHOW_ARENA_OWNER reflects the survivor.
; The on-screen indicator (show_arena_indicator) shows the current owner glyph
; in the HUD band. Mode 1 exercises this with two contending heavy effects
; (gradient backdrop vs. parallax) so the mutex is live, not dead.
; =============================================================================

; meter levels
MET_GREEN  = 0
MET_YELLOW = 1
MET_RED    = 2
; meter OBJ palettes (entry 1 = the colour)
MET_PAL_G  = 4
MET_PAL_Y  = 5
MET_PAL_R  = 6
; arena owners
ARENA_NONE     = 0
ARENA_GRADIENT = 1
ARENA_PARALLAX = 2
ARENA_OPT      = 3

; --- Genericity: each page REGISTERS which knob index feeds the cost/OAM proxy
;     (the costknob arg of show_register_mode). The active mode's index is
;     resolved into SHOW_A_COST_KNOB (showcase_dispatch.inc) and read at runtime
;     below. The generic meter NEVER references a KN_* page symbol. ---

; Per-armed-HDMA-channel weight + arena-owner weight for the C (cycle) estimate.
MET_HDMA_WEIGHT  = 16            ; each armed channel ~ one heavy per-scanline cost
MET_ARENA_WEIGHT = 24            ; a held $C000 heavy effect (gradient/parallax/OPT)

; -----------------------------------------------------------------------------
; show_meter_init — upload the meter colours to OBJ pals 4/5/6 (CGRAM 192/208/
; 224, entry 1). Forced-blank/VBlank only — call in setup. Clobbers A, X.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the CGRAM byte writes; exits A16/I16.
.proc show_meter_init
    rep #$30
    .a16
    .i16
    ; OBJ pal 4 entry 1 = green ($03E0); CGRAM index = 128 + 4*16 + 1 = 193.
    sep #$20
    .a8
    lda #193
    sta $2121
    lda #$E0
    sta $2122
    lda #$03
    sta $2122                         ; green
    ; OBJ pal 5 entry 1 = yellow ($03FF); CGRAM index = 128 + 5*16 + 1 = 209.
    lda #209
    sta $2121
    lda #$FF
    sta $2122
    lda #$03
    sta $2122                         ; yellow
    ; OBJ pal 6 entry 1 = red ($001F); CGRAM index = 128 + 6*16 + 1 = 225.
    lda #225
    sta $2121
    lda #$1F
    sta $2122
    lda #$00
    sta $2122                         ; red
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; _met_level_oam — A = realized OAM count -> A = level (0 green/1 yellow/2 red).
; Thresholds vs the 128-sprite TOTAL budget (HUD band ~48 + field 0-80): <80
; green, <104 yellow, >=104 red (approaching the 128 ceiling + the 32/line risk).
; Default frame (HUD 48 + field 16 = 64) is green; a cranked field (-> ~128) goes
; red. The honest OAM signal — the actual sprites placed, not a knob proxy.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A8 entry/exit.
.proc _met_level_oam
    .a8
    cmp #80
    bcc @g
    cmp #104
    bcc @y
    lda #MET_RED
    rts
@y:
    lda #MET_YELLOW
    rts
@g:
    lda #MET_GREEN
    rts
.endproc

; -----------------------------------------------------------------------------
; show_meter_tick — compute the 3 DISTINCT levels (F10), store them, draw bars.
;   C (cycle)   = popcount(armed HDMA)*16 + (arena owner? 24) + cost-knob count
;   H (HDMA ch) = popcount(NMI_HDMA_ENABLE)
;   O (OAM)     = realized SPRITE_COUNT last frame (SHOW_OAM_USED, ACTUAL OAM)
; No KN_* page symbol is referenced — the page declares SHOW_COST_KNOB. The bars
; draw in the fixed meter band (OBJ 36-38, allocations §2).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr A16/I16; exits A16/I16.
.proc show_meter_tick
    rep #$30
    .a16
    .i16

    ; --- H level: popcount(NMI_HDMA_ENABLE) -> armed channel count ---
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE             ; armed-channel bitmask (DP abs)
    jsr _met_popcount               ; -> A = set-bit count (kept in A)
    sta f:SHOW_HUD_TMP             ; stash armed-channel count for C + H
    ; H thresholds: 0-2 ch green, 3-4 yellow, 5+ red
    cmp #3
    bcc @hg
    cmp #5
    bcc @hy
    lda #MET_RED
    bra @hstore
@hy:
    lda #MET_YELLOW
    bra @hstore
@hg:
    lda #MET_GREEN
@hstore:
    sta f:SHOW_METER_HDMA

    ; --- C level: a coarse WEIGHTED cycle-cost estimate (distinct from H/O) ---
    ; cost = armed_channels*MET_HDMA_WEIGHT + (arena held ? MET_ARENA_WEIGHT)
    ;        + cost-knob count. Saturating 8-bit add (clamp at 255).
    lda f:SHOW_HUD_TMP             ; armed-channel count
    ldx #MET_HDMA_WEIGHT
    jsr _met_mul8                  ; A = count * weight (saturating)
    sta f:SHOW_HUD_TMP2           ; running cost
    lda f:SHOW_ARENA_OWNER         ; a held $C000 heavy effect?
    beq @nocost_arena
    lda f:SHOW_HUD_TMP2
    clc
    adc #MET_ARENA_WEIGHT
    bcc @arena_ok
    lda #$FF                       ; saturate
@arena_ok:
    sta f:SHOW_HUD_TMP2
@nocost_arena:
    ; cost knob is the ACTIVE mode's registered index (runtime, not compile-time):
    ; build a zero-extended 16-bit X from the byte, then index the knob value.
    ; WIDTH-RISK: A8 in -> A16 to zero-extend the index into X (I16) -> back to A8
    ; for the byte add; SHOW_HUD_TMP2 is preserved across the width toggle.
    lda f:SHOW_A_COST_KNOB         ; active cost knob index (byte, A8)
    rep #$20
    .a16
    and #$00FF                     ; zero-extend the index (clean high byte)
    tax                            ; X = cost knob index (I16)
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL, x         ; active cost knob value (count proxy)
    clc
    adc f:SHOW_HUD_TMP2
    bcc @cost_ok
    lda #$FF                       ; saturate
@cost_ok:
    ; C thresholds: <64 green, <120 yellow, >=120 red (weighted-cost zones)
    cmp #64
    bcc @cg
    cmp #120
    bcc @cy
    lda #MET_RED
    bra @cstore
@cy:
    lda #MET_YELLOW
    bra @cstore
@cg:
    lda #MET_GREEN
@cstore:
    sta f:SHOW_METER_CYC

    ; --- O level: ACTUAL OAM sprites realized last frame (not a knob). Thresholds
    ;     are against the 128-sprite TOTAL budget (HUD band ~48 + field 0-80): the
    ;     fuller OAM, the closer to the per-line + total ceiling. ---
    lda f:SHOW_OAM_USED
    jsr _met_level_oam
    sta f:SHOW_METER_OAM

    rep #$20
    .a16
    ; maintain the heartbeat snapshot (diagnostic; the 60fps assertion is the
    ; test's ppu_frame_count check, not this byte).
    lda FRAME_COUNTER
    sta f:SHOW_LAST_HEART

    ; --- draw the 3 bars in the fixed meter band (OBJ 36-38) at x=216/224/232 ---
    sep #$20
    .a8
    lda #SHOW_OAM_METER_BASE
    rep #$20
    .a16
    sta SPRITE_COUNT               ; deterministic band base (allocations §2)
    sep #$20
    .a8
    lda f:SHOW_METER_CYC
    rep #$20
    .a16
    and #$00FF
    ldx #216
    jsr _met_draw_bar
    sep #$20
    .a8
    lda f:SHOW_METER_HDMA
    rep #$20
    .a16
    and #$00FF
    ldx #224
    jsr _met_draw_bar
    sep #$20
    .a8
    lda f:SHOW_METER_OAM
    rep #$20
    .a16
    and #$00FF
    ldx #232
    jsr _met_draw_bar
    rts
.endproc

; _met_mul8 — A8 = value, X = multiplier (small). Returns A8 = value*X, saturated
; at 255. Multiply-free (repeated add). WIDTH-RISK: A8/I16 entry/exit.
.proc _met_mul8
    .a8
    .i16
    sta f:SHOW_MOS_TMP            ; reuse mosaic scratch as the addend
    lda #0
@l:
    cpx #0
    beq @done
    clc
    adc f:SHOW_MOS_TMP
    bcc @noclamp
    lda #$FF                      ; saturate
    rts
@noclamp:
    dex
    bra @l
@done:
    rts
.endproc

; _met_draw_bar — A = level (0/1/2), X = pen X. Draw a BAR glyph in the level's
; colour palette at (X, 6). WIDTH-RISK: A16/I16 entry; A8 for byte stores; exits
; A16/I16 (engine_spr A16/I16).
.proc _met_draw_bar
    rep #$30
    .a16
    .i16
    ; palette = MET_PAL_G + level ; flags = pal<<1
    clc
    adc #MET_PAL_G
    asl                              ; pal<<1
    sta SF_SPR_FLAGS
    lda #SF_OBJG_BAR
    sta SF_SPR_TILE
    txa
    sta SF_SPR_X
    lda #6
    sta SF_SPR_Y
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    rts
.endproc

; _met_popcount — A8 in = byte ; A8 out = number of set bits (0..8).
; WIDTH-RISK: A8/I16 entry/exit.
.proc _met_popcount
    .a8
    .i16
    ldx #0                           ; count
    ldy #8                           ; bits
@l:
    lsr
    bcc @no
    inx
@no:
    dey
    bne @l
    txa                              ; A = count
    rts
.endproc

; -----------------------------------------------------------------------------
; show_arena_request — owner in A8; grant the $C000 arena to `owner`, auto-
; disabling the previous owner. Stores SHOW_ARENA_OWNER. The reusable mutex the
; heavy-effect pages call before arming gradient/parallax/OPT (S1 ships the
; mechanism + indicator; Mode 1 does not arm a heavy effect by default).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A8 entry; exits A16/I16.
.proc show_arena_request
    .a8
    .i16
    ; If a different owner currently holds it, tear that effect down first.
    pha                              ; save requested owner
    lda f:SHOW_ARENA_OWNER
    beq @grant                       ; none held -> just grant
    cmp 1, s                         ; same owner re-requesting? -> idempotent
    beq @grant
    ; A different heavy effect is being enabled -> disable the incumbent. The
    ; generic teardown is hdma_off (releases all held HDMA channels); the page's
    ; own re-arm path restores what it still wants. (S1: the indicator + the
    ; owner swap are what the test observes; no crash.)
    rep #$30
    .a16
    .i16
    jsr hdma_off
    sep #$20
    .a8
@grant:
    pla                              ; A = requested owner
    sta f:SHOW_ARENA_OWNER
    rep #$30
    .a16
    .i16
    rts
.endproc
