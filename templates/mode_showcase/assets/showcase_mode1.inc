; =============================================================================
; showcase_mode1.inc — the Mode-1 PROVING GROUND: knob table + apply + presets.
; =============================================================================
; This is the FIRST per-mode page (the S1 proof + the fan-out template). Under
; the S1.5 DISPATCH layer it supplies UNIQUELY-NAMED (m1_*) contract symbols and
; registers them via show_register_mode 1, ... (at the foot of this file). The
; generic harness reaches them only through the per-mode vtables; nothing here
; uses the old fixed labels (show_demo_init / SHOW_PARAM_TBL / ...).
;   m1_param_tbl   — 30 x 4-byte descriptors (min,max,step,default), slot-major
;   m1_slot_name   — 6 slot-label string pointers
;   m1_parm_name   — 30 value-tag string pointers (4-glyph tags)
;   m1_apply       — push every knob to its PPU shadow (called per frame)
;   m1_demo_init   — enter Mode 1 + author BG/field content + arm preset 0
;   m1_field_tick  — the procedural sprite field (in showcase_scene1.inc)
;   m1_arena_ind   — the $C000 arena owner indicator glyph
;   m1_cost_knob   — the meter cost/OAM proxy knob index (= KN_FLD_CNT)
;
; The 6 slots (the Mode-1 knob surface):
;   0 CMATH : op  R   G   B   LYR   (color-math op + COLDATA fixed colour + mask)
;   1 MOSAIC: size B1  B2  B3  B4    (mosaic pixel size + per-BG enable)
;   2 LIGHT : brite (screen brightness) + spares
;   3 SCROLL: b1x b1y b2x b2y bg3p   (BG scroll + BG3-priority toggle)
;   4 FIELD : cnt spd siz spr pal    (sprite-field count/speed/size/spread/pal)
;   5 PRESET: prs (structural preset 0..2) + spares
; =============================================================================

; --- slot/param symbolic indices (knob = slot*5 + param) ---------------------
KN_CMATH_OP   = 0
KN_CMATH_R    = 1
KN_CMATH_G    = 2
KN_CMATH_B    = 3
KN_CMATH_LYR  = 4
KN_MOS_SIZE   = 5
KN_LIGHT_BR   = 10
KN_SCR_B1X    = 15
KN_SCR_B1Y    = 16
KN_SCR_B2X    = 17
KN_SCR_B2Y    = 18
KN_SCR_BG3P   = 19
KN_FLD_CNT    = 20
KN_FLD_SPD    = 21
KN_FLD_SIZ    = 22
KN_FLD_SPR    = 23
KN_FLD_PAL    = 24
KN_PRESET     = 25
KN_GRAD_EN    = 26    ; gradient-backdrop enable (heavy $C000-arena effect A)
KN_PLX_EN     = 27    ; parallax-bands  enable (heavy $C000-arena effect B)

; --- Genericity hooks the harness consumes (F1) -----------------------------
; The limit meter's cost/OAM proxy is the FIELD COUNT knob on this page. A page
; with a different (or no) sprite-count knob registers its own index. The generic
; meter never references KN_* — it reads the ACTIVE mode's resolved cost knob.
m1_cost_knob = KN_FLD_CNT

; structural presets
PRESET_GLASS  = 0     ; translucency lab (color-math add on the field/BG2)
PRESET_SPLIT  = 1     ; BG3 priority split
PRESET_SPOT   = 2     ; window spotlight (sf_window iris)

; -----------------------------------------------------------------------------
; m1_param_tbl — 30 descriptors (min, max, step, default), slot-major.
; -----------------------------------------------------------------------------
m1_param_tbl:
    ; slot 0 CMATH
    .byte 0, 4,  1, 1      ; op    0..4 (0 off,1 add,2 sub,3 hadd,4 hsub) def add
    .byte 0, 31, 1, 16     ; R     0..31
    .byte 0, 31, 1, 8      ; G
    .byte 0, 31, 1, 24     ; B
    .byte 0, 63, 1, 32     ; LYR   CGADSUB mask (def $20 = backdrop)
    ; slot 1 MOSAIC
    .byte 0, 15, 1, 0      ; size  0..15
    .byte 0, 1,  1, 1      ; B1 enable
    .byte 0, 1,  1, 0      ; B2
    .byte 0, 1,  1, 0      ; B3
    .byte 0, 1,  1, 0      ; B4
    ; slot 2 LIGHT
    .byte 0, 15, 1, 15     ; brightness 0..15
    .byte 0, 1,  1, 0      ; (spare)
    .byte 0, 1,  1, 0      ; (spare)
    .byte 0, 1,  1, 0      ; (spare)
    .byte 0, 1,  1, 0      ; (spare)
    ; slot 3 SCROLL
    .byte 0, 255, 2, 0     ; BG1 X
    .byte 0, 255, 2, 0     ; BG1 Y
    .byte 0, 255, 2, 0     ; BG2 X
    .byte 0, 255, 2, 0     ; BG2 Y
    .byte 0, 1,   1, 1     ; BG3 priority (BGMODE bit3) def on
    ; slot 4 FIELD
    .byte 0, 80, 2, 16     ; count 0..80
    .byte 0, 15, 1, 3      ; speed
    .byte 0, 1,  1, 0      ; size (0=8x8,1=16x16 via OBSEL... here a phase mult)
    .byte 0, 15, 1, 6      ; spread
    .byte 4, 7,  1, 7      ; palette 4..7 (def 7 = HUD white; meter owns 4/5/6)
    ; slot 5 PRESET — also the two HEAVY $C000-arena effect enables (mutex demo)
    .byte 0, 2,  1, 0      ; param0 PRS structural preset 0..2
    .byte 0, 1,  1, 0      ; param1 GRD gradient-backdrop enable (arena heavy A)
    .byte 0, 1,  1, 0      ; param2 PLX parallax-bands  enable (arena heavy B)
    .byte 0, 1,  1, 0      ; param3 (spare)
    .byte 0, 1,  1, 0      ; param4 (spare)

; --- slot labels (<=8 glyphs) ---
sl_n0: .byte "CMATH", 0
sl_n1: .byte "MOSAIC", 0
sl_n2: .byte "LIGHT", 0
sl_n3: .byte "SCROLL", 0
sl_n4: .byte "FIELD", 0
sl_n5: .byte "PRESET", 0
m1_slot_name:
    .addr sl_n0, sl_n1, sl_n2, sl_n3, sl_n4, sl_n5

; --- per-param value tags (<=4 glyphs) ---
pn_op:  .byte "OP", 0
pn_r:   .byte "R", 0
pn_g:   .byte "G", 0
pn_b:   .byte "B", 0
pn_lyr: .byte "LYR", 0
pn_sz:  .byte "SZ", 0
pn_b1:  .byte "B1", 0
pn_b2:  .byte "B2", 0
pn_b3:  .byte "B3", 0
pn_b4:  .byte "B4", 0
pn_br:  .byte "BR", 0
pn_sp:  .byte "-", 0
pn_x:   .byte "X", 0
pn_y:   .byte "Y", 0
pn_2x:  .byte "2X", 0
pn_2y:  .byte "2Y", 0
pn_p3:  .byte "BG3", 0
pn_cnt: .byte "CNT", 0
pn_spd: .byte "SPD", 0
pn_fsz: .byte "SIZ", 0
pn_spr: .byte "SPR", 0
pn_pal: .byte "PAL", 0
pn_prs: .byte "PRS", 0
pn_grd: .byte "GRD", 0
pn_plx: .byte "PLX", 0
m1_parm_name:
    .addr pn_op, pn_r, pn_g, pn_b, pn_lyr        ; slot 0
    .addr pn_sz, pn_b1, pn_b2, pn_b3, pn_b4      ; slot 1
    .addr pn_br, pn_sp, pn_sp, pn_sp, pn_sp      ; slot 2
    .addr pn_x, pn_y, pn_2x, pn_2y, pn_p3        ; slot 3
    .addr pn_cnt, pn_spd, pn_fsz, pn_spr, pn_pal ; slot 4
    .addr pn_prs, pn_grd, pn_plx, pn_sp, pn_sp   ; slot 5

; =============================================================================
; m1_demo_init — enter Mode 1, author BG content, arm preset 0 (vtable entry).
; =============================================================================
; WIDTH-RISK: A16/I16 entry; toggles A8 around the VRAM/PPU byte writes; exits
; A16/I16 (jsr targets re-assert their own widths).
.proc m1_demo_init
    rep #$30
    .a16
    .i16
    ; Forced blank for the VRAM authoring + mode switch.
    sep #$20
    .a8
    lda #$80
    sta $2100                       ; forced blank
    rep #$20
    .a16

    ; Re-seed the knob model to the page defaults on every demo entry — a fresh
    ; demo starts from a known state (and keeps tests deterministic). A recalled
    ; SRAM config is applied later, inside the demo's param sheet.
    jsr show_param_init

    jsr show_build_bg               ; BG1/BG3 chr + palettes (showcase_scene1.inc)

    ; gfxmode(1) via the dispatcher — sets BGMODE/BG bases/TM, CLEARS the shadow
    ; tilemaps. Author content AFTER it.
    lda #$0001
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    jsr show_paint_tilemaps         ; fill BG1/BG3 shadow tilemaps + mark dirty

    ; Seed the field model for a clean demo entry.
    jsr show_field_init

    ; Apply once so the first rendered frame reflects the defaults; then the
    ; preset hook frames the scene. Screen comes back on at the chosen bright.
    lda f:SHOW_KNOB_VAL + KN_PRESET
    and #$00FF
    sta API_BLOCK_BASE + 0          ; pass preset id
    jsr show_preset_apply
    jsr m1_apply                    ; page-local apply (not the dispatch wrapper)

    ; Seed the limit-meter heartbeat snapshot so the first demo frame's delta is
    ; sane (not a huge stale-counter artifact -> false RED).
    lda FRAME_COUNTER
    sta f:SHOW_LAST_HEART

    ; Lift forced blank — the LIGHT knob owns brightness from here (INIDISP
    ; shadow committed by the NMI), so write the live brightness now.
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP              ; NMI commits $2100
    sta $2100
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; m1_apply — push EVERY knob to its PPU shadow (called once per demo frame).
; The dispatch layer reaches this via SHOW_APPLY[1]; it is the page's translation
; layer.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; the sf_* macros + helpers run their own widths;
; A8 around direct shadow byte writes; exits A16/I16.
.proc m1_apply
    rep #$30
    .a16
    .i16

    ; --- Slot 0 CMATH: op -> sf_colormath_on/off; R/G/B -> tint; LYR -> mask ---
    lda f:SHOW_KNOB_VAL + KN_CMATH_OP
    and #$00FF
    bne @cm_on
    sf_colormath_off
    bra @cm_done
@cm_on:
    ; op is 1..4 already the engine mode codes (1 add,2 sub,3 hadd,4 hsub)
    lda f:SHOW_KNOB_VAL + KN_CMATH_OP
    and #$00FF
    sta API_BLOCK_BASE + $00        ; sf_colormath_on mode
    lda f:SHOW_KNOB_VAL + KN_CMATH_LYR
    and #$00FF
    sta API_BLOCK_BASE + $04        ; layers mask
    jsr engine_color_math_on
    ; tint
    lda f:SHOW_KNOB_VAL + KN_CMATH_R
    and #$00FF
    sta API_BLOCK_BASE + $00
    lda f:SHOW_KNOB_VAL + KN_CMATH_G
    and #$00FF
    sta API_BLOCK_BASE + $04
    lda f:SHOW_KNOB_VAL + KN_CMATH_B
    and #$00FF
    sta API_BLOCK_BASE + $08
    jsr engine_color_math_tint
@cm_done:

    ; --- Slot 1 MOSAIC: size (high nibble) + per-BG enable (low nibble) ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_MOS_SIZE
    and #$0F
    asl
    asl
    asl
    asl                              ; size -> bits 7-4
    sta f:SHOW_MOS_TMP               ; long scratch
    lda f:SHOW_KNOB_VAL + (KN_MOS_SIZE+1)   ; B1
    and #$01
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP
    lda f:SHOW_KNOB_VAL + (KN_MOS_SIZE+2)   ; B2
    and #$01
    asl
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP
    lda f:SHOW_KNOB_VAL + (KN_MOS_SIZE+3)   ; B3
    and #$01
    asl
    asl
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP
    lda f:SHOW_KNOB_VAL + (KN_MOS_SIZE+4)   ; B4
    and #$01
    asl
    asl
    asl
    ora f:SHOW_MOS_TMP
    sta SHADOW_MOSAIC                 ; NMI commits $2106 (bank-0 abs, DBR=0)
    rep #$20
    .a16

    ; --- Slot 2 LIGHT: brightness -> SHADOW_INIDISP (keep forced-blank bit clear) ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_LIGHT_BR
    and #$0F                          ; 0..15, bit7 (blank) stays clear
    sta SHADOW_INIDISP               ; NMI commits $2100
    rep #$20
    .a16

    ; --- Slot 3 SCROLL: BG1/BG2 X/Y -> scroll shadows; BG3 priority -> BGMODE ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_SCR_B1X
    sta SHADOW_BG1HOFS
    stz SHADOW_BG1HOFS+1
    lda f:SHOW_KNOB_VAL + KN_SCR_B1Y
    sta SHADOW_BG1VOFS
    stz SHADOW_BG1VOFS+1
    lda f:SHOW_KNOB_VAL + KN_SCR_B2X
    sta SHADOW_BG2HOFS
    stz SHADOW_BG2HOFS+1
    lda f:SHOW_KNOB_VAL + KN_SCR_B2Y
    sta SHADOW_BG2VOFS
    stz SHADOW_BG2VOFS+1
    ; BG3 priority: BGMODE bit3 (Mode 1 = $01; +$08 when BG3 high-priority)
    lda f:SHOW_KNOB_VAL + KN_SCR_BG3P
    and #$01
    beq @bg3lo
    lda #$09                          ; Mode 1 + BG3 priority
    bra @bg3w
@bg3lo:
    lda #$01                          ; Mode 1, BG3 normal priority
@bg3w:
    sta SHADOW_BGMODE                 ; NMI commits $2105
    rep #$20
    .a16

    ; --- Slot 5 GRD/PLX: the two heavy $C000-arena effects (mutex demo, F5) ---
    jsr show_arena_apply

    ; (Slot 4 FIELD is serviced by show_field_tick from the demo tick, AFTER the
    ;  HUD has taken OAM slots 0-47 — see main.asm demo_tick ordering / §2 bands.)
    rts
.endproc

; =============================================================================
; show_arena_apply — the $C000 arena MUTEX in action (F5). Two heavy effects
; (GRD gradient backdrop, PLX parallax bands) contend for the single $C000 HDMA
; arena. Enabling one while the other owns the arena auto-disables the prior
; owner (show_arena_request -> hdma_off) and clears its enable knob so the HUD +
; the rendered frame both reflect the swap. SHOW_ARENA_OWNER tracks the survivor;
; m1_arena_ind renders it on-screen. Edge-detected via SHOW_KNOB_AUX.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 internally; exits A16/I16.
.proc show_arena_apply
    rep #$30
    .a16
    .i16
    ; --- GRD rising edge? (prev aux 0 -> cur 1) ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_GRAD_EN
    and #$01
    cmp f:SHOW_KNOB_AUX + KN_GRAD_EN     ; vs previous-frame value
    beq @grd_noedge
    ; value changed — store new prev, act only on the 0->1 rising edge
    sta f:SHOW_KNOB_AUX + KN_GRAD_EN
    cmp #1
    bne @grd_off_edge
    ; GRD turned ON -> request the arena (auto-disables incumbent PLX)
    lda #ARENA_GRADIENT
    jsr show_arena_request
    sep #$20
    .a8
    lda #0
    sta f:SHOW_KNOB_VAL + KN_PLX_EN      ; loser: PLX disabled, HUD reflects it
    sta f:SHOW_KNOB_AUX + KN_PLX_EN
    bra @arm
@grd_off_edge:
    ; GRD turned OFF while it owned the arena -> release it
    sep #$20
    .a8
    lda f:SHOW_ARENA_OWNER
    cmp #ARENA_GRADIENT
    bne @grd_noedge
    rep #$30
    .a16
    .i16
    jsr hdma_off
    sep #$20
    .a8
    lda #ARENA_NONE
    sta f:SHOW_ARENA_OWNER
@grd_noedge:
    rep #$20
    .a16

    ; --- PLX rising edge? ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + KN_PLX_EN
    and #$01
    cmp f:SHOW_KNOB_AUX + KN_PLX_EN
    beq @plx_noedge
    sta f:SHOW_KNOB_AUX + KN_PLX_EN
    cmp #1
    bne @plx_off_edge
    lda #ARENA_PARALLAX
    jsr show_arena_request
    sep #$20
    .a8
    lda #0
    sta f:SHOW_KNOB_VAL + KN_GRAD_EN     ; loser: GRD disabled
    sta f:SHOW_KNOB_AUX + KN_GRAD_EN
    bra @arm
@plx_off_edge:
    sep #$20
    .a8
    lda f:SHOW_ARENA_OWNER
    cmp #ARENA_PARALLAX
    bne @plx_noedge
    rep #$30
    .a16
    .i16
    jsr hdma_off
    sep #$20
    .a8
    lda #ARENA_NONE
    sta f:SHOW_ARENA_OWNER
@plx_noedge:
    rep #$30
    .a16
    .i16
    rts

@arm:
    ; Arm the effect that now owns the arena (SHOW_ARENA_OWNER set by request).
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_ARENA_OWNER
    cmp #ARENA_GRADIENT
    beq @arm_grad
    cmp #ARENA_PARALLAX
    beq @arm_plx
    rep #$30
    .a16
    .i16
    rts
@arm_grad:
    rep #$30
    .a16
    .i16
    ; a vertical RGB gradient backdrop (top deep-blue -> bottom warm) in $C000
    sf_gradient_rgb #2, #4, #20,  #24, #12, #2
    rts
@arm_plx:
    rep #$30
    .a16
    .i16
    ; 2-band parallax on BG2 (top scrolls slow, bottom fast) — also $C000 arena
    sf_parallax_bands #2, #112, #96, #200
    rts
.endproc

; =============================================================================
; m1_arena_ind — render the $C000 arena-mutex owner glyph in the HUD band (OBJ
; slot 39, allocations §2). '-' = none, G = gradient, P = parallax. The dispatch
; layer reaches this via SHOW_ARENA_IND[1]. This is the on-screen indicator the
; spec/F5 require so the mutex is OUTPUT-visible, not just a WRAM byte.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr A16/I16; exits A16/I16.
.proc m1_arena_ind
    rep #$30
    .a16
    .i16
    ; deterministic band: the indicator owns OBJ slot 39
    sep #$20
    .a8
    lda #SHOW_OAM_ARENA_BASE
    rep #$20
    .a16
    sta SPRITE_COUNT
    ; glyph tile by owner
    sep #$20
    .a8
    lda f:SHOW_ARENA_OWNER
    cmp #ARENA_GRADIENT
    beq @g
    cmp #ARENA_PARALLAX
    beq @p
    ; none -> a dash
    lda #SF_OBJG_DASH
    bra @put
@g:
    lda #SF_OBJG_G
    bra @put
@p:
    lda #SF_OBJG_P
@put:
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_TILE
    lda #200                          ; x just left of the meter bars
    sta SF_SPR_X
    lda #6
    sta SF_SPR_Y
    lda #SF_OBJ_HUD_FLAGS             ; HUD pal 7 (white)
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    rts
.endproc

; =============================================================================
; show_preset_apply — re-frame the scene for the active structural preset.
; In: API_BLOCK_BASE+0 = preset id (0..2). Stores SHOW_PRESET.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 internally; exits A16/I16.
.proc show_preset_apply
    rep #$30
    .a16
    .i16
    lda API_BLOCK_BASE + 0
    and #$00FF
    sep #$20
    .a8
    sta f:SHOW_PRESET
    rep #$20
    .a16

    ; All presets first clear the window (only SPOT arms it).
    sf_window_off

    lda f:SHOW_PRESET
    and #$00FF
    cmp #PRESET_SPOT
    beq @spot
    cmp #PRESET_SPLIT
    beq @split
    ; --- GLASS (0): translucency lab — default color-math add already armed by
    ;     the knobs. Nothing structural to add beyond the cleared window. ---
    rts
@split:
    ; --- BG3 priority split: force the BG3-priority knob ON so the split shows ---
    sep #$20
    .a8
    lda #1
    sta f:SHOW_KNOB_VAL + KN_SCR_BG3P
    rep #$20
    .a16
    rts
@spot:
    ; --- Window spotlight: an iris masking BG1 OUTSIDE a centre band. ---
    sf_window1_edges #96, #160       ; centre vertical band
    sf_window_bg12 #SF_WIN1_OUTSIDE  ; BG1 win1 = outside
    sf_window_mask_main #SF_WIN_BG1  ; mask BG1 in the final (outside) area
    rts
.endproc
