; =============================================================================
; bg_text.asm — BG3 2bpp text engine (shared code; forced-blank writes only)
; =============================================================================
; DP block (global, from text_dp): ES_TXT_PTR (24-bit string ptr), ES_TXT_TMP
; (attr word: palette/priority bits OR'd into every tile). Spatial claims (font
; CHR base, tilemap base, palette words) are SCENE-scoped symbols the CALLER
; passes in — this code never names them.
;
; All routines: A16/I16 in/out, DB=0, FORCED BLANK asserted by the caller
; (scene enter). Nothing here touches the PPU outside forced blank.

; --- the VBlank text queue (ES_TXT_Q, from text_dp) -------------------------
; Every other routine in this file writes VRAM under forced blank. A RUNNING
; scene cannot do that, so live HUD cells (the race lap digit, the results
; tally) go through here: the tick stages up to TXT_Q_MAX consecutive tilemap
; cells, the NMI hook commits them during VBlank with CPU stores. No DMA
; channel, no VBlank byte budget — nothing to declare beyond the DP bytes.
; Staging twice in one frame keeps the LAST run.
TXT_Q_MAX   = 4                 ; words; the claim sizes the run (text_dp)
TXT_Q_DIRTY = ES_TXT_Q + 0      ; u8: 0 = nothing staged
TXT_Q_COUNT = ES_TXT_Q + 1      ; u8: words to commit, 1..TXT_Q_MAX
TXT_Q_VMADD = ES_TXT_Q + 2      ; u16: first VRAM word address
TXT_Q_WORDS = ES_TXT_Q + 4      ; TXT_Q_MAX x u16, consecutive cells

; --- text_queue_cell: stage ONE tilemap cell for the next VBlank ------------
; CONTRACT text_queue_cell
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the tile word (glyph index | attr bits), X = the VRAM
;             word address
;   out:      one tilemap cell staged for the next VBlank
;   clobbers: A, N, Z
;   assumes:  the MAIN thread only — text_vblank_commit is what writes
;             VRAM
;   tail:     rts
;
; In: A16 = tile word (glyph index | attr bits), X = VRAM word address. In/out:
; A16/I16, DB=0. Main thread only.
text_queue_cell:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_queue_cell"
    sta z:TXT_Q_WORDS
    stx z:TXT_Q_VMADD
    sep #$20
    .a8
    lda #1
    sta z:TXT_Q_COUNT
    sta z:TXT_Q_DIRTY
    rep #$20
    .a16
    rts

; --- text_queue_hex4: stage 4 hex digits of a value for the next VBlank -----
; CONTRACT text_queue_hex4
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the value, X = the VRAM word address of the first of
;             four consecutive cells, ES_TXT_TMP = the attr word
;   out:      four hex digits staged for the next VBlank — the
;             running-scene twin of text_put_hex4, same nibble walk and
;             same glyph map
;   clobbers: A, X, N, Z, C, V
;   assumes:  the MAIN thread only
;   tail:     rts
;
; The running-scene twin of text_put_hex4 (same nibble walk, same glyph map).
; In: A16 = value, X = VRAM word address of the first of 4 consecutive cells,
;  ES_TXT_TMP = attr word.
text_queue_hex4:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_queue_hex4"
    stx z:TXT_Q_VMADD
    sta z:ES_TXT_PTR            ; borrow the ptr slot as value scratch
    ldx #0
@digit:
    .a16
    asl z:ES_TXT_PTR            ; rotate the top nibble into the bottom
    rol
    asl z:ES_TXT_PTR
    rol
    asl z:ES_TXT_PTR
    rol
    asl z:ES_TXT_PTR
    rol
    and #15
    cmp #10
    bcc :+
    adc #6                      ; carry set: +7 total ('A' - '9' - 1)
:   .a16
    clc
    adc #('0' - ' ')            ; glyph index (space is tile 0)
    ora z:ES_TXT_TMP
    sta z:TXT_Q_WORDS, x
    inx
    inx
    cpx #(4 * 2)
    bcc @digit
    sep #$20
    .a8
    lda #4
    sta z:TXT_Q_COUNT
    sta z:TXT_Q_DIRTY
    rep #$20
    .a16
    rts

; --- text_vblank_commit: write the staged run (sm_nmi_hook) -----------------
; CONTRACT text_vblank_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the staged run written to VRAM. A no-op on frames nothing
;             was staged
;   clobbers: A, X, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. It sets VMAIN and VMADD ITSELF, because the
;             stream and OAM DMAs ahead of it in the hook leave both in
;             whatever state their last transfer wanted — VMAIN $80
;             auto-increments, so one VMADD covers the whole run
;   tail:     rts
;
; VMADD itself: the stream/OAM DMAs ahead of it in the hook leave both in
; whatever state their last transfer wanted. VMAIN $80 auto-increments, so
; consecutive cells need one VMADD for the whole run.
text_vblank_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "text_vblank_commit"
    lda z:TXT_Q_DIRTY
    beq @done
    stz z:TXT_Q_DIRTY
    lda #$80
    sta a:$2115                 ; VMAIN: word step after the high byte
    rep #$20
    .a16
    lda z:TXT_Q_VMADD
    sta a:$2116
    sep #$20
    .a8
    ldx #0                      ; byte index into the staged run
@word:
    .a8
    lda z:TXT_Q_WORDS, x
    sta a:$2118                 ; VMDATAL
    lda z:TXT_Q_WORDS + 1, x
    sta a:$2119                 ; VMDATAH — the write lands here
    inx
    inx
    dec z:TXT_Q_COUNT           ; consumed; the queue is re-staged per use
    bne @word
@done:
    .a8                         ; both paths are A8/I16 for the caller
    .i16
    rts

; --- text_upload_font: DMA the 96-glyph 2bpp font into a scene's CHR base ---
; In: X = VRAM word base (the scene's ES_V_TEXT_CHR), Y = source addr low16,
;  A = source bank (low byte). Uses DMA CH0 (free outside NMI by contract).
; GP-DMA register file addressed through the channel the font_up dma_init claim
; names — the channel number is declared, not assumed.
FNT_REGS = $4300 + ES_D_FONT_UP_CH * 16

; CONTRACT text_upload_font
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the CHR VRAM word base, Y = the byte count, A = the
;             source bank
;   out:      the font CHR uploaded
;   clobbers: A, N, Z
;   assumes:  forced blank: this writes the VRAM port
;   tail:     rts
text_upload_font:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_upload_font"
    sep #$20
    .a8
    sta a:FNT_REGS + 4                 ; A1B0 = font bank
    lda #$80
    sta a:$2115                 ; VMAIN: word step after $2119
    rep #$20
    .a16
    stx a:$2116                 ; VMADD = font CHR base
    sty a:FNT_REGS + 2                 ; A1T0
    lda #ES_R_FONT_BIN_SIZE
    sta a:FNT_REGS + 5                 ; DAS0 (96 tiles x 16 B)
    sep #$20
    .a8
    lda #ES_D_FONT_UP_DMAP
    sta a:FNT_REGS + 0                 ; DMAP0: A->B, 2-reg write-once
    lda #ES_D_FONT_UP_BBAD
    sta a:FNT_REGS + 1                 ; BBAD0: VMDATAL
    lda #(1 << ES_D_FONT_UP_CH)
    sta a:$420B                 ; fire
    rep #$20
    .a16
    rts

; --- text_clear_map: fill a tilemap with tile 0 (space) ---------------------
; CONTRACT text_clear_map
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the tilemap VRAM word base, Y = the word count (the
;             scene's _WORDS symbol), A = the attr word
;   out:      the whole tilemap filled with tile 0 (space) at that
;             attribute
;   clobbers: A, Y, N, Z
;   assumes:  forced blank: this writes the VRAM port
;   tail:     rts
;
; In: X = tilemap VRAM word base, Y = word count (the scene's _WORDS symbol),
;  A = attr word (palette bits; tile 0 = ' ').
text_clear_map:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_clear_map"
    sta z:ES_TXT_TMP            ; attr | tile(space=0)
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
    stx a:$2116
:   lda z:ES_TXT_TMP
    sta a:$2118                 ; VMDATA (word mode)
    dey
    bne :-
    rts

; --- text_puts: write an ASCII string as tiles at a VRAM word address --------
; CONTRACT text_puts
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the VRAM word address (base + row*32 + col, computed by
;             the caller from ITS OWN scene symbols), ES_TXT_PTR = a
;             24-bit address of a 0-terminated ASCII string ($20..$7F),
;             ES_TXT_TMP = the attr word
;   out:      the string written as tiles. Y comes back holding the string
;             LENGTH, and X is PRESERVED. Tile ids are relative to
;             BG34NBA's CHR base, which the SCENE sets to its own
;             ES_V_TEXT_CHR — glyph n IS tile n
;   clobbers: A, Y, N, Z, C, V
;   assumes:  forced blank: this writes the VRAM port
;   tail:     rts
;
; In: X = VRAM word addr (base + row*32 + col — caller computes from ITS
;  scene symbols), ES_TXT_PTR = 24-bit string address (0-terminated
;  ASCII $20..$7F), ES_TXT_TMP = attr word (palette bits, priority).
; Tile id = ascii - $20 + (font base word / 8)? NO — tile ids are relative to
; BG34NBA's CHR base, which the SCENE sets to its ES_V_TEXT_CHR. Glyph n IS
; tile n.
text_puts:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_puts"
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
    stx a:$2116
    ldy #0
@ch:
    sep #$20
    .a8
    lda [<ES_TXT_PTR], y
    beq @end
    rep #$20
    .a16
    and #127                    ; 7-bit ASCII
    sec
    sbc #' '                    ; glyph index (space -> tile 0)
    ora z:ES_TXT_TMP            ; attr bits
    sta a:$2118
    iny
    bra @ch
@end:
    .a8                         ; A8 via beq; the A16 fall-in re-reps harmlessly
    rep #$20
    .a16
    rts

; --- text_put_digit: one glyph for a value 0..15 ----------------------------
; CONTRACT text_put_digit
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the value 0..15, X = the VRAM word address, ES_TXT_TMP =
;             the attr word
;   out:      one glyph written
;   clobbers: A, N, Z, C, V
;   assumes:  forced blank: this writes the VRAM port
;   tail:     rts
;
; In: A16 = value (0..15), X = VRAM word addr, ES_TXT_TMP = attr word.
text_put_digit:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_put_digit"
    pha                         ; save value (A16: 2 bytes)
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
    stx a:$2116
    pla
    and #15
    cmp #10
    bcc :+
    adc #6                      ; carry set: +7 total ('A'-'9'-1 = 7)
:   clc
    adc #('0' - ' ')            ; '0' glyph index
    ora z:ES_TXT_TMP
    sta a:$2118
    rts

; --- text_put_hex4: 4 hex digits of a 16-bit value --------------------------
; CONTRACT text_put_hex4
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the value, X = the VRAM word address of four consecutive
;             cells, ES_TXT_TMP = the attr word
;   out:      four hex digits written
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank: this writes the VRAM port
;   tail:     rts
;
; In: A16 = value, X = VRAM word addr (4 consecutive cells), attr in TXT_TMP.
text_put_hex4:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "text_put_hex4"
    sta z:ES_TXT_PTR            ; borrow the ptr slot as value scratch
    ldy #4
@digit:
    .a16
    ; rotate the top nibble into the bottom
    asl z:ES_TXT_PTR
    rol
    asl z:ES_TXT_PTR
    rol
    asl z:ES_TXT_PTR
    rol
    asl z:ES_TXT_PTR
    rol
    and #15
    phy
    phx
    jsr text_put_digit
    plx
    ply
    inx                         ; next cell
    dey
    bne @digit
    rts
