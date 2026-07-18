; =============================================================================
; showcase_mode0.inc — the Mode-0 "PLANES" page: four 4-color BG layers, live.
; =============================================================================
; The fan-out PILOT page (the first per-mode page authored after the Mode-1
; reference). Under the S1.5 DISPATCH layer it supplies UNIQUELY-NAMED (m0_*)
; contract symbols and registers them via show_register_mode 0, ... (at the foot
; of showcase_scene0.inc). The generic harness reaches them only through the
; per-mode vtables; nothing here uses fixed labels.
;   m0_param_tbl   — 30 x 4-byte descriptors (min,max,step,default), slot-major
;   m0_slot_name   — 6 slot-label string pointers
;   m0_parm_name   — 30 value-tag string pointers (<=3-glyph tags)
;   m0_apply       — push every knob to its PPU shadow (called per frame)
;   m0_demo_init   — enter Mode 0 + author 4 BG layers + arm preset 0
;   m0_field_tick  — procedural sprite field (in showcase_scene0.inc)
;   m0_arena_ind   — arena owner indicator glyph (no heavy effect by default)
;   m0_cost_knob   — meter cost/OAM proxy knob index (= M0K_FLD_CNT)
;
; The 6 slots (the Mode-0 knob surface — the REAL Mode-0 tunables):
;   0 PARX  : b1x b2x b3x b4x auto  (per-layer X scroll + parallax auto-drift)
;   1 PARY  : b1y b2y b3y b4y rate  (per-layer Y scroll + auto-drift rate)
;   2 LIGHT : brt e1  e2  e3  e4     (brightness + per-layer enable B1-B4)
;   3 PAL   : p1  p2  p3  p4  -      (per-layer palette/hue select 0..7)
;   4 FIELD : cnt spd siz spr pal    (sprite-field count/speed/size/spread/pal)
;   5 FRAME : prs ord bdk -   -      (structural preset + PRIORITY-SHUFFLE + bdk)
; =============================================================================

; --- slot/param symbolic indices (knob = slot*5 + param) ---------------------
M0K_B1X        = 0
M0K_B2X        = 1
M0K_B3X        = 2
M0K_B4X        = 3
M0K_AUTO       = 4     ; parallax auto-drift enable/speed (0=off,1..N=px/frame mul)
M0K_B1Y        = 5
M0K_B2Y        = 6
M0K_B3Y        = 7
M0K_B4Y        = 8
M0K_RATE       = 9     ; auto-drift base rate (spare-ish tuner)
M0K_LIGHT_BR   = 10    ; brightness (kept at index 10 = HUD/dispatch convention)
M0K_EN_B1      = 11
M0K_EN_B2      = 12
M0K_EN_B3      = 13
M0K_EN_B4      = 14
M0K_PAL_L1     = 15    ; per-layer hue select 0..7 (drives m0_layer_hue LUT)
M0K_PAL_L2     = 16
M0K_PAL_L3     = 17
M0K_PAL_L4     = 18
M0K_FLD_CNT    = 20
M0K_FLD_SPD    = 21
M0K_FLD_SIZ    = 22
M0K_FLD_SPR    = 23
M0K_FLD_PAL    = 24
M0K_PRESET     = 25    ; structural preset 0=stacked parallax / 1=4-quadrant
M0K_PRIORDER   = 26    ; PRIORITY-SHUFFLE: 0..3 plane order enum (headline knob)
M0K_BACKDROP   = 27    ; backdrop treatment 0=black / 1=solid (deep blue)

; --- Genericity hook the harness consumes (F1): the meter cost/OAM proxy is the
;     field-count knob on this page. ---
m0_cost_knob = M0K_FLD_CNT

; structural presets
PRESET_STACK   = 0    ; stacked multi-plane parallax (all 4 layers full-screen)
PRESET_QUAD    = 1    ; 4-quadrant layer isolation (one plane per screen quadrant)

; priority-shuffle order enum (M0K_PRIORDER) -> BGxSC permutation index.
; Each entry of m0_order_lut is the BG1/BG2/BG3/BG4 tilemap assignment that
; reorders which plane draws front-most. ORD 0 = 0123 (A front), 3 = 3210 (D
; front), with two intermediates.
PRIORDER_MAX   = 3

; backdrop colours (CGRAM 0 / fixed-colour) — black vs a deep blue
BACKDROP_BLUE  = $4800     ; 15-bit BGR deep blue

; HUD legibility (F-6): the top M0_HUD_DARK_ROWS tile rows of every BG tilemap
; (both presets) are written as transparent tile 0 so the dark backdrop backs the
; white OBJ-pal-7 HUD readout (slot label y=6, tags y=18, values y=28). Defined
; here (this file is .included BEFORE showcase_scene0.inc) so both files see it.
M0_HUD_DARK_ROWS  = 5                   ; top 5 tile rows (y 0..39) cover the readout
M0_HUD_DARK_TILES = M0_HUD_DARK_ROWS * 32

; -----------------------------------------------------------------------------
; m0_param_tbl — 30 descriptors (min, max, step, default), slot-major.
; -----------------------------------------------------------------------------
m0_param_tbl:
    ; slot 0 PARX (per-layer X scroll + auto-drift)
    .byte 0, 255, 4, 0     ; b1x  BG1 X
    .byte 0, 255, 4, 0     ; b2x  BG2 X
    .byte 0, 255, 4, 0     ; b3x  BG3 X
    .byte 0, 255, 4, 0     ; b4x  BG4 X
    .byte 0, 4,   1, 1     ; auto parallax auto-drift (0 off, 1..4 speed mult) def 1
    ; slot 1 PARY (per-layer Y scroll + rate)
    .byte 0, 255, 4, 0     ; b1y
    .byte 0, 255, 4, 0     ; b2y
    .byte 0, 255, 4, 0     ; b3y
    .byte 0, 255, 4, 0     ; b4y
    .byte 1, 8,   1, 2     ; rate auto-drift base rate (px every `rate` frames)
    ; slot 2 LIGHT (brightness + per-layer enable)
    .byte 0, 15,  1, 15    ; brt  brightness 0..15
    .byte 0, 1,   1, 1     ; e1   BG1 enable (def on)
    .byte 0, 1,   1, 1     ; e2   BG2 enable
    .byte 0, 1,   1, 1     ; e3   BG3 enable
    .byte 0, 1,   1, 1     ; e4   BG4 enable
    ; slot 3 PAL (per-layer hue select 0..7)
    .byte 0, 7,   1, 2     ; p1   BG1 hue (def 2 blue)
    .byte 0, 7,   1, 1     ; p2   BG2 hue (def 1 green)
    .byte 0, 7,   1, 0     ; p3   BG3 hue (def 0 red)
    .byte 0, 7,   1, 3     ; p4   BG4 hue (def 3 yellow)
    .byte 0, 1,   1, 0     ; (spare)
    ; slot 4 FIELD
    .byte 0, 80,  2, 16    ; cnt  count 0..80
    .byte 0, 15,  1, 3     ; spd  speed
    .byte 0, 1,   1, 0     ; siz  size
    .byte 0, 15,  1, 6     ; spr  spread
    .byte 4, 7,   1, 7     ; pal  palette 4..7 (def 7 HUD white)
    ; slot 5 FRAME (preset + priority-shuffle + backdrop)
    .byte 0, 1,   1, 0     ; prs  structural preset 0 stacked / 1 quadrant
    .byte 0, 3,   1, 0     ; ord  PRIORITY-SHUFFLE order enum 0..3
    .byte 0, 1,   1, 0     ; bdk  backdrop 0 black / 1 solid blue
    .byte 0, 1,   1, 0     ; (spare)
    .byte 0, 1,   1, 0     ; (spare)

; --- slot labels (<=6 glyphs) ---
m0_sl0: .byte "PARX", 0
m0_sl1: .byte "PARY", 0
m0_sl2: .byte "LIGHT", 0
m0_sl3: .byte "PAL", 0
m0_sl4: .byte "FIELD", 0
m0_sl5: .byte "FRAME", 0
m0_slot_name:
    .addr m0_sl0, m0_sl1, m0_sl2, m0_sl3, m0_sl4, m0_sl5

; --- per-param value tags (<=3 glyphs) ---
m0_pn_b1x: .byte "B1X", 0
m0_pn_b2x: .byte "B2X", 0
m0_pn_b3x: .byte "B3X", 0
m0_pn_b4x: .byte "B4X", 0
m0_pn_aut: .byte "AUT", 0
m0_pn_b1y: .byte "B1Y", 0
m0_pn_b2y: .byte "B2Y", 0
m0_pn_b3y: .byte "B3Y", 0
m0_pn_b4y: .byte "B4Y", 0
m0_pn_rat: .byte "RAT", 0
m0_pn_brt: .byte "BRT", 0
m0_pn_e1:  .byte "E1", 0
m0_pn_e2:  .byte "E2", 0
m0_pn_e3:  .byte "E3", 0
m0_pn_e4:  .byte "E4", 0
m0_pn_p1:  .byte "P1", 0
m0_pn_p2:  .byte "P2", 0
m0_pn_p3:  .byte "P3", 0
m0_pn_p4:  .byte "P4", 0
m0_pn_dash:.byte "-", 0
m0_pn_cnt: .byte "CNT", 0
m0_pn_spd: .byte "SPD", 0
m0_pn_siz: .byte "SIZ", 0
m0_pn_spr: .byte "SPR", 0
m0_pn_pal: .byte "PAL", 0
m0_pn_prs: .byte "PRS", 0
m0_pn_ord: .byte "ORD", 0
m0_pn_bdk: .byte "BDK", 0
m0_parm_name:
    .addr m0_pn_b1x, m0_pn_b2x, m0_pn_b3x, m0_pn_b4x, m0_pn_aut   ; slot 0
    .addr m0_pn_b1y, m0_pn_b2y, m0_pn_b3y, m0_pn_b4y, m0_pn_rat   ; slot 1
    .addr m0_pn_brt, m0_pn_e1, m0_pn_e2, m0_pn_e3, m0_pn_e4       ; slot 2
    .addr m0_pn_p1, m0_pn_p2, m0_pn_p3, m0_pn_p4, m0_pn_dash      ; slot 3
    .addr m0_pn_cnt, m0_pn_spd, m0_pn_siz, m0_pn_spr, m0_pn_pal   ; slot 4
    .addr m0_pn_prs, m0_pn_ord, m0_pn_bdk, m0_pn_dash, m0_pn_dash ; slot 5

; --- priority-shuffle BGxSC LUT: 4 orders x 4 BGs. Each byte is the BGxSC value
;     (tilemap word base / $400 << 2 => $00/$04/$08/$0C, 32x32). The four planes
;     live at tilemaps $0000(A)/$0400(B)/$0800(C)/$0C00(D). Permuting which
;     tilemap BG1 reads changes which plane is FRONT-most (BG1 highest priority
;     in Mode 0). Order 0 = A,B,C,D ; 3 = D,C,B,A. ----------------------------
m0_order_lut:
    .byte $00, $04, $08, $0C    ; ORD 0 : BG1=A BG2=B BG3=C BG4=D  (A front)
    .byte $04, $08, $0C, $00    ; ORD 1 : BG1=B BG2=C BG3=D BG4=A  (B front)
    .byte $08, $0C, $00, $04    ; ORD 2 : BG1=C BG2=D BG3=A BG4=B  (C front)
    .byte $0C, $08, $04, $00    ; ORD 3 : BG1=D BG2=C BG3=B BG4=A  (D front, rev)

; -----------------------------------------------------------------------------
; m0_nmi_off / m0_nmi_on — bracket a heavy multi-VRAM-write authoring window so
; the NMI cannot fire mid-write and reset $2116/VMADD (the NMI's tilemap/VWF/
; streaming DMAs all stomp VMADD). The fills here author 1-4K VRAM words which
; SPAN frames; without this the NMI corrupts the in-progress VMADD and the fill
; goes wrong from that point on. $4200 keeps bit0 (auto-joypad) set, toggling
; only bit7 (NMI enable). Always paired; always run under forced blank.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the $4200 byte; exits A16/I16.
.proc m0_nmi_off
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$01                          ; auto-joypad on, NMI OFF
    sta $4200
    rep #$20
    .a16
    rts
.endproc

; WIDTH-RISK: A16/I16 entry; A8 for the $4200 byte; exits A16/I16.
.proc m0_nmi_on
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$81                          ; auto-joypad on, NMI ON
    sta $4200
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; m0_demo_init — enter Mode 0, author the 4 BG layers, arm preset 0 (vtable
; entry). ALL VRAM/CGRAM writes under forced blank.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; toggles A8 around the VRAM/PPU byte writes; exits
; A16/I16 (jsr targets re-assert their own widths).
.proc m0_demo_init
    rep #$30
    .a16
    .i16
    ; Forced blank for the VRAM authoring + mode switch. CRITICAL: Mode 0 authors
    ; ~8K direct VRAM words (4 tilemaps + CHR) which SPAN MULTIPLE FRAMES, so the
    ; NMI WILL fire mid-init and commit SHADOW_INIDISP to $2100. We therefore set
    ; the SHADOW to forced-blank too, so the NMI keeps the screen blanked across
    ; the whole authoring window (else the screen turns on mid-init and the later
    ; VRAM writes are dropped). The final step restores the live brightness.
    sep #$20
    .a8
    lda #$80
    sta $2100                       ; forced blank (live)
    sta SHADOW_INIDISP              ; forced blank (NMI keeps it across frames)
    rep #$20
    .a16

    ; Re-seed the knob model to the page defaults on demo entry (deterministic).
    jsr show_param_init

    ; gfxmode(0) via the dispatcher — sets BGMODE=0, BG1-4 SC/NBA, TM=$1F. Author
    ; content AFTER it. (engine_gfxmode does NOT clear Mode-0 tilemaps — Mode 0
    ; uses the direct-VRAM author below, not the NMI shadow-tilemap pipeline.)
    lda #$0000
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    ; Author the four planes: shared CHR + 4 palette banks + 4 tilemaps (all
    ; under forced blank AND with the NMI disabled so its DMAs can't reset VMADD
    ; mid-fill — the fills span frames).
    jsr m0_nmi_off
    jsr m0_build_bg                 ; CHR word $1000 + 4 palette banks
    jsr m0_paint_tilemaps           ; fill BG1-4 tilemaps directly to VRAM
    jsr m0_nmi_on

    ; Seed the field model for a clean demo entry.
    jsr m0_field_init

    ; Apply preset 0 framing, then push all knobs once so the first rendered frame
    ; reflects the defaults.
    lda f:SHOW_KNOB_VAL + M0K_PRESET
    and #$00FF
    sta API_BLOCK_BASE + 0
    jsr m0_preset_apply
    jsr m0_apply                    ; page-local apply (not the dispatch wrapper)

    ; Seed the limit-meter heartbeat snapshot (avoid a false RED first frame).
    lda FRAME_COUNTER
    sta f:SHOW_LAST_HEART

    ; Lift forced blank — the LIGHT knob owns brightness from here (the NMI
    ; commits SHADOW_INIDISP), so write the live brightness now.
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP              ; NMI commits $2100
    sta $2100
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; m0_apply — push EVERY knob to its PPU shadow (once per demo frame). Reached via
; SHOW_APPLY[0]. Shadow-only per-frame path (NMI commits) EXCEPT the priority-
; shuffle + palette/backdrop re-author, which run on a knob EDGE under a brief
; forced-blank bracket (the same edge-gated heavy-op idiom as the arena mutex).
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 around direct shadow byte writes + edge ops;
; exits A16/I16.
.proc m0_apply
    rep #$30
    .a16
    .i16

    ; --- Slot 0/1 SCROLL: per-layer X/Y -> scroll shadows (+ auto-drift) ---
    jsr m0_scroll_apply

    ; --- Slot 2 LIGHT: brightness -> SHADOW_INIDISP; enables -> SHADOW_TM ---
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP             ; NMI commits $2100
    rep #$20
    .a16
    jsr m0_enable_apply           ; per-layer BG enable -> TM bits

    ; --- Slot 3 PAL: per-layer hue (edge-detected re-paint of palette banks) ---
    jsr m0_palette_apply

    ; --- Slot 5 PRS: structural preset (edge-detected re-frame: stacked<->quad) ---
    jsr m0_preset_edge

    ; --- Slot 5 ORD: PRIORITY-SHUFFLE (edge-detected BGxSC permutation) ---
    jsr m0_priority_apply

    ; --- Slot 5 BDK: backdrop treatment (edge-detected CGRAM-0 colour) ---
    jsr m0_backdrop_apply

    ; (Slot 4 FIELD is serviced by m0_field_tick from the demo tick, AFTER the HUD
    ;  has taken OAM 0-47.)
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_preset_edge — re-frame the scene when the PRS knob changes (edge-detected
; via SHOW_KNOB_AUX[M0K_PRESET]). The preset re-author (re-painting tilemaps under
; forced blank) is heavy, so it runs only on the change edge — the per-frame path
; otherwise does nothing here. Calls m0_preset_apply with the new preset id.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the edge check; exits A16/I16.
.proc m0_preset_edge
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_PRESET
    and #$01
    cmp f:SHOW_KNOB_AUX + M0K_PRESET   ; vs last applied preset
    beq @done
    sta f:SHOW_KNOB_AUX + M0K_PRESET
    rep #$20
    .a16
    and #$00FF
    sta API_BLOCK_BASE + 0             ; preset id
    jsr m0_preset_apply
    rep #$30
    .a16
    .i16
    rts
@done:
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_scroll_apply — per-layer X/Y scroll shadows; AUTO adds a frame-driven drift
; to each layer at a depth-staggered rate (layer 1 slow .. layer 4 fast) so the
; stacked preset reads as parallax. The drift is added on top of the knob base.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc m0_scroll_apply
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    ; auto-drift base = FRAME_COUNTER (1px/frame); per-layer depth multiplier
    ; gives BG1 slowest, BG4 fastest -> parallax. Only when AUTO != 0.
    lda f:SHOW_KNOB_VAL + M0K_AUTO
    and #$07
    sta f:SHOW_MOS_TMP             ; auto speed mult (0 = static)

    ; BG1 X = b1x + drift*1
    lda f:SHOW_KNOB_VAL + M0K_B1X
    ldx #1
    jsr m0_add_drift
    sta SHADOW_BG1HOFS
    stz SHADOW_BG1HOFS+1
    lda f:SHOW_KNOB_VAL + M0K_B1Y
    sta SHADOW_BG1VOFS
    stz SHADOW_BG1VOFS+1

    ; BG2 X = b2x + drift*2
    lda f:SHOW_KNOB_VAL + M0K_B2X
    ldx #2
    jsr m0_add_drift
    sta SHADOW_BG2HOFS
    stz SHADOW_BG2HOFS+1
    lda f:SHOW_KNOB_VAL + M0K_B2Y
    sta SHADOW_BG2VOFS
    stz SHADOW_BG2VOFS+1

    ; BG3 X = b3x + drift*3
    lda f:SHOW_KNOB_VAL + M0K_B3X
    ldx #3
    jsr m0_add_drift
    sta SHADOW_BG3HOFS
    stz SHADOW_BG3HOFS+1
    lda f:SHOW_KNOB_VAL + M0K_B3Y
    sta SHADOW_BG3VOFS
    stz SHADOW_BG3VOFS+1

    ; BG4 X = b4x + drift*4
    lda f:SHOW_KNOB_VAL + M0K_B4X
    ldx #4
    jsr m0_add_drift
    sta SHADOW_BG4HOFS
    stz SHADOW_BG4HOFS+1
    lda f:SHOW_KNOB_VAL + M0K_B4Y
    sta SHADOW_BG4VOFS
    stz SHADOW_BG4VOFS+1
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_add_drift — A8 = base scroll; X = depth (1..4). Returns A8 = base + drift,
; where drift = step added `depth` times and step = (FRAME_COUNTER * speed)>>1.
; Deeper layers (higher depth) drift faster => parallax. Wrap-safe 8-bit. speed
; is in SHOW_MOS_TMP (0 => no drift). Loop counts DOWN in X (dex/bne) so no
; long-addressed cpx is needed (cpx has no abs-long form).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A8/I16 entry; A8 throughout; X consumed as loop counter, Y as the
; speed counter; uses SHOW_FLD_TMP/TMP2 long scratch (no stack juggling across
; widths); exits A8 with result in A.
.proc m0_add_drift
    .a8
    .i16
    sta f:SHOW_FLD_TMP2            ; base scroll (stash; no cross-width stack use)
    lda f:SHOW_MOS_TMP            ; auto speed (0 => no drift)
    beq @nodrift
    ; step = (FRAME_COUNTER * speed) >> 1. speed 1..7 -> repeated add (Y counter).
    ; Y is a 16-bit index (I16); load the speed BYTE in A16 and zero-extend with
    ; `and #$00FF` BEFORE `tay`, so C-high (stale from the dispatch/scroll path)
    ; can NOT leak into the loop counter (width rule #6: A8/I16 tay copies the
    ; full 16-bit C; a nonzero high byte would run @smul up to 65k times).
    rep #$20
    .a16
    and #$00FF                       ; zero-extend speed (kill stale C-high)
    tay                              ; Y = speed (0..7, high byte = 0)
    sep #$20
    .a8
    lda #0
    clc
@smul:
    adc FRAME_COUNTER               ; += FRAME (speed times)
    dey
    bne @smul
    lsr                              ; >>1 (gentle drift)
    sta f:SHOW_FLD_TMP             ; step
    ; drift = step * depth (add step `depth` times; X = depth, counts down).
    lda #0
    clc
@dmul:
    adc f:SHOW_FLD_TMP             ; += step (depth times)
    dex
    bne @dmul
    ; A = drift ; + base (8-bit wrap)
    clc
    adc f:SHOW_FLD_TMP2
    rts
@nodrift:
    lda f:SHOW_FLD_TMP2            ; base only
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_enable_apply — per-layer BG enable knobs -> SHADOW_TM bits. TM bit0=BG1 ..
; bit3=BG4, bit4=OBJ (always on for the HUD). NMI commits $212C.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte assembly; exits A16/I16.
.proc m0_enable_apply
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$10                         ; OBJ always on (bit4) for the HUD
    sta f:SHOW_MOS_TMP
    lda f:SHOW_KNOB_VAL + M0K_EN_B1
    and #$01
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP               ; bit0 BG1
    lda f:SHOW_KNOB_VAL + M0K_EN_B2
    and #$01
    asl
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP               ; bit1 BG2
    lda f:SHOW_KNOB_VAL + M0K_EN_B3
    and #$01
    asl
    asl
    ora f:SHOW_MOS_TMP
    sta f:SHOW_MOS_TMP               ; bit2 BG3
    lda f:SHOW_KNOB_VAL + M0K_EN_B4
    and #$01
    asl
    asl
    asl
    ora f:SHOW_MOS_TMP
    sta SHADOW_TM                    ; bit3 BG4 ; NMI commits $212C
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_palette_apply — repaint the 4 BG palette banks when any PAL hue knob changes
; (edge-detected via SHOW_KNOB_AUX). CGRAM writes need forced blank, so on a
; change set forced blank, repaint, and lift it back to the live brightness. This
; is a rare (per-knob-change) event, not a per-frame write.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the edge check + INIDISP; exits A16/I16.
.proc m0_palette_apply
    rep #$30
    .a16
    .i16
    ; edge: compare a checksum of the 4 PAL knobs vs the cached aux byte.
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_PAL_L1
    clc
    adc f:SHOW_KNOB_VAL + M0K_PAL_L2
    clc
    adc f:SHOW_KNOB_VAL + M0K_PAL_L3
    clc
    adc f:SHOW_KNOB_VAL + M0K_PAL_L4
    cmp f:SHOW_KNOB_AUX + M0K_PAL_L1   ; prev checksum
    beq @done                         ; no change -> skip the heavy repaint
    sta f:SHOW_KNOB_AUX + M0K_PAL_L1   ; store new checksum
    ; forced blank, repaint banks, restore brightness. Set BOTH the live $2100
    ; AND SHADOW_INIDISP to $80 so an NMI firing mid-repaint can NOT un-blank the
    ; screen while CGRAM is being written (the NMI commits SHADOW_INIDISP each
    ; frame — page HIGH lesson).
    lda #$80
    sta $2100
    sta SHADOW_INIDISP
    rep #$20
    .a16
    jsr m0_paint_palettes
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP
    sta $2100
@done:
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_priority_apply — the PRIORITY-SHUFFLE knob (headline). On an ORD change,
; rewrite BG1SC/BG2SC/BG3SC/BG4SC ($2107-$210A) from m0_order_lut[ORD] so a
; DIFFERENT plane becomes front-most (BG1 = highest Mode-0 priority). BGxSC are
; PPU registers (forced-blank/VBlank only), so the permutation runs under a brief
; forced-blank bracket on the edge (rare event). SHOW_KNOB_AUX[M0K_PRIORDER]
; caches the last applied order.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the edge check + BGxSC writes; exits A16/I16.
.proc m0_priority_apply
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_PRIORDER
    and #$03
    cmp f:SHOW_KNOB_AUX + M0K_PRIORDER  ; vs last applied order
    beq @done
    sta f:SHOW_KNOB_AUX + M0K_PRIORDER  ; store new order
    ; X = order*4 (LUT row offset)
    asl
    asl
    rep #$20
    .a16
    and #$00FF
    tax                                ; X = LUT byte offset
    ; forced blank for the BGxSC writes. Set BOTH live $2100 AND SHADOW_INIDISP
    ; to $80 so an NMI mid-window can NOT un-blank the screen during the BGxSC
    ; rewrite (the NMI commits SHADOW_INIDISP each frame — page HIGH lesson).
    sep #$20
    .a8
    lda #$80
    sta $2100
    sta SHADOW_INIDISP
    lda f:m0_order_lut+0, x
    sta $2107                          ; BG1SC
    lda f:m0_order_lut+1, x
    sta $2108                          ; BG2SC
    lda f:m0_order_lut+2, x
    sta $2109                          ; BG3SC
    lda f:m0_order_lut+3, x
    sta $210A                          ; BG4SC
    ; restore brightness (lift forced blank)
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP
    sta $2100
@done:
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_backdrop_apply — backdrop treatment (BDK knob): CGRAM entry 0 (the backdrop
; colour shown where no BG pixel is opaque). 0 = black, 1 = deep blue. Edge-gated
; (CGRAM write needs forced blank). Cached in SHOW_KNOB_AUX[M0K_BACKDROP].
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the edge check + CGRAM write; exits A16/I16.
.proc m0_backdrop_apply
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + M0K_BACKDROP
    and #$01
    cmp f:SHOW_KNOB_AUX + M0K_BACKDROP
    beq @done
    sta f:SHOW_KNOB_AUX + M0K_BACKDROP
    ; forced blank, write CGRAM 0, restore brightness. Set BOTH live $2100 AND
    ; SHADOW_INIDISP to $80 so an NMI mid-window can NOT un-blank the screen while
    ; CGRAM 0 is being written (the NMI commits SHADOW_INIDISP — page HIGH lesson).
    lda #$80
    sta $2100
    sta SHADOW_INIDISP
    stz $2121                          ; CGADD 0
    lda f:SHOW_KNOB_VAL + M0K_BACKDROP
    and #$01
    beq @black
    ; deep blue backdrop
    lda #<BACKDROP_BLUE
    sta $2122
    lda #>BACKDROP_BLUE
    sta $2122
    bra @lift
@black:
    .a8
    stz $2122
    stz $2122
@lift:
    .a8
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP
    sta $2100
@done:
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; m0_preset_apply — re-frame the scene for the active structural preset.
; In: API_BLOCK_BASE+0 = preset id (0 stacked / 1 quadrant). Stores SHOW_PRESET.
; STACK: all 4 layers fill the screen (parallax). QUAD: each plane is confined to
; one screen quadrant via scroll so the user sees each plane in isolation — done
; by re-painting the tilemaps into quadrant bands under forced blank.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 internally; exits A16/I16.
.proc m0_preset_apply
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

    lda f:SHOW_PRESET
    and #$00FF
    cmp #PRESET_QUAD
    beq @quad
    ; --- STACK (0): full-screen planes. Re-author full-fill tilemaps (forced
    ;     blank + NMI off so VMADD isn't reset mid-fill) + auto-drift on. ---
    sep #$20
    .a8
    lda #$80
    sta $2100                          ; forced blank for the re-author
    rep #$20
    .a16
    jsr m0_nmi_off
    jsr m0_paint_tilemaps              ; full-screen fills
    jsr m0_nmi_on
    sep #$20
    .a8
    lda #1
    sta f:SHOW_KNOB_VAL + M0K_AUTO      ; auto-drift on (parallax motion)
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP
    sta $2100
    rep #$20
    .a16
    rts
@quad:
    ; --- QUAD (1): 4-quadrant isolation. Re-author each tilemap so its plane
    ;     only fills its own quadrant (rest blank) and stop auto-drift so each
    ;     plane sits still in its quadrant. ---
    sep #$20
    .a8
    lda #$80
    sta $2100                          ; forced blank
    rep #$20
    .a16
    jsr m0_nmi_off
    jsr m0_paint_quadrants
    jsr m0_nmi_on
    sep #$20
    .a8
    lda #0
    sta f:SHOW_KNOB_VAL + M0K_AUTO      ; static (each plane in its quadrant)
    stz SHADOW_BG1HOFS
    stz SHADOW_BG1HOFS+1
    stz SHADOW_BG2HOFS
    stz SHADOW_BG2HOFS+1
    stz SHADOW_BG3HOFS
    stz SHADOW_BG3HOFS+1
    stz SHADOW_BG4HOFS
    stz SHADOW_BG4HOFS+1
    lda f:SHOW_KNOB_VAL + M0K_LIGHT_BR
    and #$0F
    sta SHADOW_INIDISP
    sta $2100
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_paint_quadrants — re-author the four BG tilemaps so each plane is confined
; to one screen quadrant (the rest of that BG's tilemap = transparent tile 0).
; BG1 plane A -> top-left, BG2 plane B -> top-right, BG3 plane C -> bottom-left,
; BG4 plane D -> bottom-right. 32x32 tilemap; quadrant = 16x16 tiles. Under the
; forced blank set by the caller (m0_preset_apply).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for VMAIN; exits A16/I16.
.proc m0_paint_quadrants
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                          ; VMAIN inc after high
    rep #$20
    .a16

    ; All BGs use sub-palette 0 of their own Mode-0 palette region (attr pal = 0).
    ; BG1 plane A -> top-left quadrant (col<16, row<16)
    lda #$0000
    sta $2116
    lda #$0001                        ; tile 1, sub-palette 0
    ldx #0                             ; quadrant id 0 = TL
    jsr m0_fill_quadrant

    ; BG2 plane B -> top-right (col>=16, row<16)
    lda #$0400
    sta $2116
    lda #$0002
    ldx #1                             ; TR
    jsr m0_fill_quadrant

    ; BG3 plane C -> bottom-left (col<16, row>=16)
    lda #$0800
    sta $2116
    lda #$0003
    ldx #2                             ; BL
    jsr m0_fill_quadrant

    ; BG4 plane D -> bottom-right (col>=16, row>=16)
    lda #$0C00
    sta $2116
    lda #$0004
    ldx #3                             ; BR
    jsr m0_fill_quadrant
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_fill_quadrant — A16 = plane tilemap word, X = quadrant id (0 TL,1 TR,2 BL,
; 3 BR); write the plane tile where (row,col) is in the quadrant, else tile 0.
; 32x32 = 1024 entries; col = i & 31, row = i >> 5. Quadrant split at 16.
; qid bit0 = right half wanted, qid bit1 = bottom half wanted. Per tile we
; compute right(0/1) and bottom(0/1) flags and compare to the qid bits — no
; long-addressed stx/cpx (those have no abs-long form on the 65816).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry/throughout for the math; A8 only for the VRAM byte
; pair; Y holds the flat tile index across the loop; exits A16/I16. All quadrant
; math is done in A16 with explicit compares (no A8 carry-rotate games).
; q = (row>=16)*2 + (col>=16); write the plane tile where q == qid, else tile 0.
.proc m0_fill_quadrant
    rep #$30
    .a16
    .i16
    sta f:SHOW_HUD_TMP               ; plane word (16-bit)
    txa
    and #$0003
    sta f:SHOW_HUD_TMP2             ; qid (0..3), 16-bit store
    ldy #0                           ; Y = flat tile index 0..1023
@w:
    ; --- q starts at 0; add 1 if col>=16, add 2 if row>=16 ---
    ; q accumulator is a 2-byte long scratch (SHOW_FLD_TMP3, 2 B) — a 16-bit
    ; store into the 1-byte SHOW_NUM_V would alias SHOW_NUM_DV (show_num3 scratch).
    lda #0
    sta f:SHOW_FLD_TMP3            ; q accumulator (16-bit, 2-byte scratch)
    ; col = Y & 31
    tya
    and #$001F
    cmp #16
    bcc @col_done                    ; col<16 -> no +1
    lda f:SHOW_FLD_TMP3
    ora #$0001                       ; +1 (right)
    sta f:SHOW_FLD_TMP3
@col_done:
    ; row = Y >> 5
    tya
    lsr
    lsr
    lsr
    lsr
    lsr
    cmp #16
    bcc @row_done                    ; row<16 -> no +2
    lda f:SHOW_FLD_TMP3
    ora #$0002                       ; +2 (bottom)
    sta f:SHOW_FLD_TMP3
@row_done:
    ; LEGIBILITY (F-6): the top M0_HUD_DARK_TILES tiles (rows 0..4) stay blank in
    ; every quadrant so the dark backdrop backs the white HUD readout in preset B
    ; too (the priority shuffle rotates which plane owns TL/TR, so blank both).
    cpy #M0_HUD_DARK_TILES
    bcc @blank
    ; in quadrant if q == qid
    lda f:SHOW_FLD_TMP3
    cmp f:SHOW_HUD_TMP2
    bne @blank
    lda f:SHOW_HUD_TMP             ; plane word
    bra @put
@blank:
    .a16
    lda #$0000                       ; transparent tile 0
@put:
    .a16
    sep #$20
    .a8
    sta $2118                        ; tile low byte
    xba
    sta $2119                        ; attr high byte
    xba
    rep #$20
    .a16
    iny
    cpy #1024
    bcc @w
    rts
.endproc

; =============================================================================
; m0_arena_ind — Mode-0 holds NO heavy $C000 effect by default (parallax scroll
; is cheap; backdrop is a single CGRAM write, not an HDMA gradient), so there is
; no arena mutex to deconflict. Render the dash glyph (no owner) at the arena
; band (OBJ 39) so the HUD band stays consistent across modes.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr A16/I16; exits A16/I16.
.proc m0_arena_ind
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #SHOW_OAM_ARENA_BASE
    rep #$20
    .a16
    sta SPRITE_COUNT
    lda #SF_OBJG_DASH
    and #$00FF
    sta SF_SPR_TILE
    lda #200
    sta SF_SPR_X
    lda #6
    sta SF_SPR_Y
    lda #SF_OBJ_HUD_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    rts
.endproc
