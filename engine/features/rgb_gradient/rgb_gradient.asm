; =============================================================================
; rgb_gradient.asm — static COLDATA depth wash over the Mode-7 floor band
; =============================================================================
; Three indirect HDMA channels (DMAP $40: indirect, mode 0 = 1 byte -> 1 reg)
; stream the claimed ROM gradient blob (grad_tabs: R|G|B plane tables x
; GRAD_LINES bytes, tools/gen_gradient.py) into COLDATA ($2132). Header tables
; live in this file (code bank, split_band-style); the data pointers walk the
; blob at the allocator-emitted base — the claim-site .asserts in race.asm tie
; the .incbin to these constants. Zero CPU, zero WRAM: armed once at enter,
; re-armed every armed VBlank from the scene_mgr shadow.
;
; The tables now span the WHOLE frame, one byte per scanline: the sky band
; above the seam and the floor band below it are both tinted, and the band
; split routes them to different layers for free (TM = BG2+BG3+OBJ above,
; BG1+OBJ below, while colour math targets BG1+BG2). Two repeat entries per
; plane cover the frame: a repeat entry's count byte is 128 | n and the largest
; usable n is 127 — 128 | 0 is "repeat, zero lines", a degenerate entry, not
; "repeat 128". (Measured: with 128 there the channel stopped advancing and
; every scanline rendered table byte 0.) So 127 + 97 = 224.
;
; Whether scanline 0 shows table byte 0 or the previous frame's last value
; depends on HDMA init timing — MEASURED, not assumed: see the sky-band test,
; which asserts the rendered sky against the declared table starting at the
; scanline the measurement establishes.
GRAD_LINES = 224                    ; gen_gradient TOTAL_LINES
GRAD_HEAD  = 127                    ; max lines one repeat entry can cover
GRAD_TAIL  = GRAD_LINES - GRAD_HEAD

; --- the three header tables (indirect: [count, ptr] ... [0]) ---------------
rg_tab_r:
    .byte 128 | GRAD_HEAD
    .word ES_R_GRAD_TABS_ADDR                       ; lines 0..127
    .byte 128 | GRAD_TAIL
    .word ES_R_GRAD_TABS_ADDR + GRAD_HEAD           ; lines 128..223
    .byte 0
rg_tab_g:
    .byte 128 | GRAD_HEAD
    .word ES_R_GRAD_TABS_ADDR + GRAD_LINES
    .byte 128 | GRAD_TAIL
    .word ES_R_GRAD_TABS_ADDR + GRAD_LINES + GRAD_HEAD
    .byte 0
rg_tab_b:
    .byte 128 | GRAD_HEAD
    .word ES_R_GRAD_TABS_ADDR + 2 * GRAD_LINES
    .byte 128 | GRAD_TAIL
    .word ES_R_GRAD_TABS_ADDR + 2 * GRAD_LINES + GRAD_HEAD
    .byte 0

; --- rg_arm: channel shadow slots + color-math config (scene enter) ---------
; CONTRACT rg_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the three channel shadow slots filled and the colour-math
;             config written
;   clobbers: A, X, N, Z
;   assumes:  forced blank — the scene_mgr enter contract. The caller ORs
;             the three ES_H_COL*_CH bits into the HDMAEN shadow
;             AFTERWARDS; this routine does not
;   tail:     rts
rg_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rg_arm"
    sep #$20
    .a8
    ; ---- CH colr: R plane ---------------------------------------------
    ldx #(ES_H_COLR_CH * 16)
    lda #ES_H_COLR_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 1 byte
    lda #ES_H_COLR_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: COLDATA (claims.hdma names the plane)
    lda #^rg_tab_r
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: header table bank (code)
    lda #ES_R_GRAD_TABS_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: gradient data bank
    rep #$20
    .a16
    lda #.loword(rg_tab_r)
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: header table addr
    sep #$20
    .a8
    ; ---- CH colg: G plane ---------------------------------------------
    ldx #(ES_H_COLG_CH * 16)
    lda #ES_H_COLG_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_COLG_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #^rg_tab_g
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_GRAD_TABS_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #.loword(rg_tab_g)
    sta f:ES_SM_HDMA_LONG+2, x
    sep #$20
    .a8
    ; ---- CH colb: B plane ---------------------------------------------
    ldx #(ES_H_COLB_CH * 16)
    lda #ES_H_COLB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_COLB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #^rg_tab_b
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_GRAD_TABS_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #.loword(rg_tab_b)
    sta f:ES_SM_HDMA_LONG+2, x
    ; ---- color math: ADD the fixed color to RG_MATH_LAYERS ------------
    ; WHICH LAYERS the ramp lands on is the SCENE's call, not this feature's,
    ; and it is the whole difference between a depth wash and a sky. The scene
    ; declares it immediately above its `.include` of this file; there is no
    ; default, because a silent default is exactly how the platformer inherited
    ; a wash on its terrain and shipped a teal sky.
    ;  1|2 = BG1 + BG2 — a wash ON the layers. microzero (the Mode-7 floor
    ;  plus the sky band) and breaker both want this: their band
    ;  split already separates the two, so one static value covers
    ;  both, and BG3/OBJ are deliberately absent so the HUD and the
    ;  car render untinted.
    ;  $20 = BACKDROP — the ramp IS the sky, showing through every
    ;  transparent cell, and the layers keep their authored colours. This is
    ;  what a rail with an OPEN sky wants.
    ; The claim that covers this write is `grad_math` (CGWSEL + CGADSUB); the
    ; VALUE is a look parameter, the way PLF_PLX_* are.
.ifndef RG_MATH_LAYERS
    .error "rgb_gradient: the scene must define RG_MATH_LAYERS (CGADSUB layer mask) before including this file"
.endif
    sep #$20
    .a8
    lda #0
    sta a:$2130                     ; CGWSEL: math always, fixed-color addend
    lda #RG_MATH_LAYERS
    sta a:$2131                     ; CGADSUB: add (full) to the declared layers
    rep #$20
    .a16
    rts

; --- rg_disarm: restore the boot color-math state (scene exit) --------------
; CONTRACT rg_disarm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      all three COLDATA planes reset to zero, and CGWSEL / CGADSUB
;             returned to the ppu_reset defaults
;   clobbers: A, N, Z
;   assumes:  forced blank, at scene exit. COLDATA holds whatever line the
;             disarm caught, so the reset is what stops a scene inheriting
;             a stray fixed colour
;   tail:     rts
;
; caught — reset all three planes to zero so no scene inherits a stray fixed
; color; CGWSEL/CGADSUB return to the ppu_reset defaults.
rg_disarm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rg_disarm"
    sep #$20
    .a8
    lda #(32 | 16)
    sta a:$2130                     ; CGWSEL: color math never (HW default)
    stz a:$2131                     ; CGADSUB: all layers off
    lda #(128 | 64 | 32)
    sta a:$2132                     ; COLDATA: all planes, intensity 0
    rep #$20
    .a16
    rts
