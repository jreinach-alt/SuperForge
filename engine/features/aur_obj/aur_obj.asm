; =============================================================================
; aur_obj — three figures on the cliff edge, backs to us
; =============================================================================
; 16x32 sprites, which is OBSEL size pair 6. The PPU reads one as tiles N,
; N+1, N+16, N+17, N+32, N+33, N+48, N+49 off its 16-TILE-WIDE OBJ grid — the
; second row of a tall sprite is +16 tile numbers away, not +2 — so the page
; is four rows of that grid and the three figures interleave into it at N = 0,
; 2 and 4.
;
; THEY GET THEIR OWN SIXTEEN COLOURS. Sprites read CGRAM at
; `128 + (palette << 4) + colour` (SnesPpu.cpp:960), so nothing here is taken
; from BG2's palette, which is exactly full — and that is what lets the
; figures carry a cold rim down the edge the curtains light instead of being
; flat silhouettes.

AUR_OBJ_REGS = $4300 + ES_D_AUR_OBJ_UP_CH * 16

; OBSEL is three fields: the size PAIR, the name-select gap between the two
; OBJ halves, and the base of the first. Only the base is the allocator's —
; the pair is this rail's choice of sprite shape and the gap is zero because
; nothing here uses the second half.
AUR_OBJ_SIZE_PAIR = 6           ; 16x32 small / 32x64 large
AUR_OBJ_GAP = 0
AUR_OBSEL = (AUR_OBJ_SIZE_PAIR << 5) | (AUR_OBJ_GAP << 3) | ES_V_AUR_OBJ_CHR_OBSEL_BASE

; --- aur_obj_arm: OBSEL, the CHR page, and the three entries ----------------
; CONTRACT aur_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       nothing — every address is an allocator symbol
;   out:      OBSEL set; the OBJ CHR page uploaded; ES_OAM_SHADOW's first
;             three entries staged and their hi-table byte written
;   clobbers: A, X, Y, N, Z, C, OBSEL, VMAIN, VMADD, DMA channel
;             ES_D_AUR_OBJ_UP_CH
;   assumes:  FORCED BLANK, and that `oam_park_all` has already run — the
;             entries this does not write must be parked, and power-on OAM is
;             random (rule 5)
;   tail:     rts
aur_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_obj_arm"
    sep #$20
    .a8
    lda #AUR_OBSEL
    sta a:$2101                     ; OBSEL: size pair 6 (16x32 / 32x64)
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_AUR_OBJ_CHR
    sta a:$2116
    ldx #.loword(aur_obj_bin)
    stx a:AUR_OBJ_REGS + 2          ; A1T
    ldx #ES_R_AUR_OBJ_SIZE
    stx a:AUR_OBJ_REGS + 5          ; DAS
    sep #$20
    .a8
    lda #^aur_obj_bin
    sta a:AUR_OBJ_REGS + 4          ; A1B
    lda #ES_D_AUR_OBJ_UP_DMAP
    sta a:AUR_OBJ_REGS + 0
    lda #ES_D_AUR_OBJ_UP_BBAD
    sta a:AUR_OBJ_REGS + 1
    lda #(1 << ES_D_AUR_OBJ_UP_CH)
    sta a:$420B

    ; ---- the three entries, into the shadow oam_sprites DMAs every frame ---
    ldx #(ES_O_AUR_FIGS * 4)
    ldy #0
@fig:
    .a8
    .i16
    lda a:aur_fig_x, y
    sta a:ES_OAM_SHADOW + 0, x      ; X, low 8 bits
    lda #AUR_FIG_TOP
    sta a:ES_OAM_SHADOW + 1, x      ; Y
    lda a:aur_fig_tile, y
    sta a:ES_OAM_SHADOW + 2, x      ; the first of its eight tiles
    lda #$30
    sta a:ES_OAM_SHADOW + 3, x      ; priority 3, palette 0, tile bit 8 clear
    inx
    inx
    inx
    inx
    iny
    cpy #AUR_FIGS
    bcc @fig
    ; THE HI-TABLE BYTE IS WRITTEN, NOT ASSUMED. Two bits a sprite: X9 and
    ; SIZE. Every figure's X is under 256 and every one is the pair's SMALL
    ; size, so all eight bits are zero — but power-on OAM is random and
    ; "already zero" is exactly the assumption rule 5 forbids.
    stz a:ES_OAM_SHADOW + (ES_OAM_SHADOW_SIZE - 32) + (ES_O_AUR_FIGS / 4)
    rep #$20
    .a16
    rts

aur_fig_x:
    .byte AUR_FIG0_X, AUR_FIG1_X, AUR_FIG2_X
aur_fig_tile:
    .byte 0, 2, 4                   ; ...on the 16-wide grid, two tiles apart
