; =============================================================================
; svd_obj.asm — the two player markers, placed to be CUT
; =============================================================================
; One 8x8 red tile drawn twice. P1's marker sits at seam - 4, i.e. STRADDLING
; the seam; P2's stands PLY_DX px into the right half. Those two positions are
; chosen for the OBJ-clip mode:
; with WOBJSEL = window-1-inside and OBJ in TMW, the seam slices P1's marker
; and P2's disappears entirely.
;
; THAT IS A PICTURE-ONLY FACT. The OAM entries this file writes are
; byte-identical in every mode — the clip happens in the PPU's window logic,
; downstream of OAM — so an OAM assertion can never see it and only a rendered
; frame can. It is the rail's fourth teaching and the reason its tests read
; screenshot pixels on the seam scanlines.
;
; Both entries are re-staged into the oam_sprites SHADOW every frame from the
; scene tick, never into hardware OAM (which the engine's declared VBlank
; GP-DMA owns), so the staging path runs on every frame rather than only on
; frame 0.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (svd_obsel). Value from
; ES_V_OBJ_CHR_OBSEL_BASE.

SVD_OBJ_REGS = $4300 + ES_D_SVD_OBJ_UP_CH * 16

; The two entries and the hi-table byte they share. A hi byte covers FOUR
; sprites (2 bits each: X9 then size), which is why the claim set reserves four
; slots for two markers — the byte then has ONE owner and the draw can rebuild
; it from scratch instead of read-modify-writing around slots it does not hold.
SVD_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
SVD_OBJ_P1 = ES_OAM_SHADOW + ES_O_MARKER_P1 * 4
SVD_OBJ_P2 = ES_OAM_SHADOW + ES_O_MARKER_P2 * 4
SVD_OBJ_HI = SVD_OBJ_HI_BASE + (ES_O_MARKER_P1 / 4)

.assert ES_O_MARKER_P1 .MOD 4 = 0, error, "svd_obj: marker_p1 must start a hi-table byte"
.assert ES_O_MARKER_P2 = ES_O_MARKER_P1 + 1, error, "svd_obj: the two markers must share one hi-table byte"

; Tile 0 of the obj_chr claim's grid — the claim holds exactly one tile, so the
; id is 0 against a base the allocator chose.
; Attr = %0011_0000: priority 3, OBJ palette 0 (the marker is red through
; palette word 1, svd_rom's svd_obj_pal).
SVD_OBJ_TILE = 0
SVD_OBJ_ATTR = 48

SVD_PLY_Y  = 176                ; the marker row
SVD_P1_DX  = 4                  ; P1 sits at seam - 4: astride the seam
SVD_P2_DX  = 40                 ; P2 sits 40 px into the right half

; --- svd_obj_arm: CHR + palette + OBSEL + tile/attr (scene enter) -----------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Clobbers A, X.
svd_obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(svd_obj_chr_bin)
    sta a:SVD_OBJ_REGS + 2          ; A1T
    lda #ES_R_SVD_OBJ_CHR_SIZE
    sta a:SVD_OBJ_REGS + 5          ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^svd_obj_chr_bin
    sta a:SVD_OBJ_REGS + 4          ; A1B
    lda #ES_D_SVD_OBJ_UP_DMAP
    sta a:SVD_OBJ_REGS + 0          ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SVD_OBJ_UP_BBAD
    sta a:SVD_OBJ_REGS + 1          ; BBAD: VMDATAL
    lda #(1 << ES_D_SVD_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_MARKER_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:svd_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SVD_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8), OBJ chr base from the claim ------
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr: written once; only X is per-frame -------------------
    lda #SVD_OBJ_TILE
    sta a:SVD_OBJ_P1 + 2
    sta a:SVD_OBJ_P2 + 2
    lda #SVD_OBJ_ATTR
    sta a:SVD_OBJ_P1 + 3
    sta a:SVD_OBJ_P2 + 3
    lda #SVD_PLY_Y
    sta a:SVD_OBJ_P1 + 1
    sta a:SVD_OBJ_P2 + 1
    rep #$20
    .a16
    rts

; --- svd_obj_draw: stage both markers into the OAM shadow -------------------
; In/out: A16/I16, DB=0. Called from the scene's tick, EVERY frame. Clobbers A,
; X.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED: each marker's X9 is derived
; from bit 8 of its own screen x every frame. P2 at seam + 40 with the seam
; clamped to SEAM_HI = 192 reaches 232, so bit 8 stays clear on this rail —
; deriving it anyway is what keeps that arithmetic out of the code's
; assumptions (the stale-X9 lesson). Y and the tile/attr bytes are constants
; written once at arm — only X moves, and it moves because the SEAM moves.
svd_obj_draw:
    .a16
    .i16
    lda z:ES_SVD_CAM + 4
    sec
    sbc #SVD_P1_DX                  ; P1: astride the seam
    sep #$20
    .a8
    sta a:SVD_OBJ_P1                ; x, low 8 bits
    rep #$20
    .a16
    lda z:ES_SVD_CAM + 4
    clc
    adc #SVD_P2_DX                  ; P2: into the right half
    sep #$20
    .a8
    sta a:SVD_OBJ_P2
    rep #$20
    .a16
    ; ---- the shared hi byte: bit 0 = P1's X9, bit 2 = P2's X9 (two bits per
    ; sprite, X9 then size; sizes stay 0 and the two pad slots stay clear). The
    ; first store writes the WHOLE byte, so nothing stale survives; the second
    ; ORs P2's bit into a byte this feature wholly owns.
    lda z:ES_SVD_CAM + 4
    sec
    sbc #SVD_P1_DX
    xba                             ; bit 8 of x -> bit 0 of the low byte
    and #1
    sep #$20
    .a8
    sta a:SVD_OBJ_HI
    rep #$20
    .a16
    lda z:ES_SVD_CAM + 4
    clc
    adc #SVD_P2_DX
    xba
    and #1
    asl a
    asl a                           ; P2's X9 -> bit 2
    sep #$20
    .a8
    ora a:SVD_OBJ_HI
    sta a:SVD_OBJ_HI
    rep #$20
    .a16
    rts
