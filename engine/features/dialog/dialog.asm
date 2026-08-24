; =============================================================================
; dialog.asm — the opaque BG3 message window (scene-scoped)
; =============================================================================
; An OPAQUE nine-patch panel drawn over a RUNNING scene, with paged text
; flowing inside it, closing back to the scene it covered. The argument for why
; this is a feature and not a bg_text routine is in feature.toml; the short
; form is that a BG palette's index 0 is TRANSPARENT by hardware (so a box of
; font glyphs is not a box) and every bg_text entry point but the four-word
; txt_q writes VRAM under FORCED BLANK at scene enter (so nothing there can
; open a panel mid-scene).
;
; THE MODEL. One WRAM buffer holds the FULL 32-cell rows the panel spans — not
; the panel rectangle. A BG3 tilemap row is 32 consecutive words, so the whole
; span is one contiguous VRAM run and open / page-advance / close are each ONE
; DMA at any panel width. Staging writes the buffer; the NMI hook commits it.
; Nothing here touches VRAM outside VBlank.
;
; =============================================================================
; THE BINDING CONTRACT — seven symbols, includer-supplied, NO DEFAULTS
; =============================================================================
; col_map's shape, for col_map's reason: the schema has no vocabulary for "same
; feature, different scene geometry", and a silent default draws a panel in the
; wrong place over a real scene. Define these immediately above the `.include`.
;
;  DLG_COL DLG_ROW DLG_W DLG_H panel geometry, in BG3 CELLS
;  DLG_BG3_CHR the CHR base the scene programs into BG34NBA
;  (bg_text's ES_V_TEXT_CHR) — the reach assert
;  DLG_MAP the BG3 tilemap word base (ES_V_TEXT_MAP)
;  DLG_TEXT_ATTR the attr word glyphs carry (the scene's text
;  palette | priority). Tile 0 of the font page
;  is SPACE, so this word alone is also the
;  BLANK cell a closed panel restores.
;
; The panel's own attr is DERIVED from this feature's own cgram claim, so it
; cannot drift from where the palette was actually uploaded.
; =============================================================================

.ifndef DLG_COL
    .error "dialog: DLG_COL undefined -- the includer must bind the panel's left cell column (see dialog.asm's binding contract)"
.endif
.ifndef DLG_ROW
    .error "dialog: DLG_ROW undefined -- the includer must bind the panel's top cell row"
.endif
.ifndef DLG_W
    .error "dialog: DLG_W undefined -- the includer must bind the panel width in cells"
.endif
.ifndef DLG_H
    .error "dialog: DLG_H undefined -- the includer must bind the panel height in cells"
.endif
.ifndef DLG_BG3_CHR
    .error "dialog: DLG_BG3_CHR undefined -- the includer must bind the BG3 CHR base the scene programs (the reach assert needs it)"
.endif
.ifndef DLG_MAP
    .error "dialog: DLG_MAP undefined -- the includer must bind the BG3 tilemap word base"
.endif
.ifndef DLG_TEXT_ATTR
    .error "dialog: DLG_TEXT_ATTR undefined -- the includer must bind the attr word printed glyphs carry"
.endif

DLG_CELLS_PER_ROW = 32                  ; a BG3 tilemap row, in cells
DLG_SPAN_WORDS = DLG_H * DLG_CELLS_PER_ROW
DLG_SPAN_BYTES = DLG_SPAN_WORDS * 2
DLG_LINES = 3                           ; text lines per page (rows 1, 3, 5)
; _dlg_stage_page computes its page-table offset as `asl / adc / asl` = page x
; 6
; = page x DLG_LINES x 2, with the x3 OPEN-CODED as a shift-plus-add. That
; arithmetic silently stops matching this constant if it ever moves, so pin the
; two together here rather than leaving a comment to be believed.
.assert DLG_LINES = 3, error, "_dlg_stage_page's page-table stride is open-coded as x3 (asl/adc/asl); re-derive it before changing DLG_LINES"

;
; THE REACH ASSERT — docs/09 §5.1's gap, closed here as a BUILD GATE
;
; A BG layer has ONE base nibble but a 10-bit tile index, so a 2bpp layer
; reaches 1024 x 8 = 8192 words = two consecutive chr_align pages from its base
; (Mesen2 Core/SNES/SnesPpu.cpp:239-248). Chr_align_words = $1000 puts this
; feature's page on its own page, and §5.1's complaint is that "packing order
; decides it, and nothing checks the result" — its own worked failure being a
; claim exactly ONE TILE past reach. These three asserts are the check. A
; composition that packs the panel out of reach REFUSES THE BUILD naming this
; claim, instead of rendering whatever tiles happen to live there.
;
; The precondition a consuming scene must satisfy: every other kind="chr" claim
; in the scene is either OBJ (obj_chr_align_words = $2000, packed first) or
; LARGER than bg_text's font page, so this page lands immediately above it.
; Rpg_town's feature.toml states its side of that bargain.
.assert ES_V_DLG_CHR > DLG_BG3_CHR, error, "dialog: the panel's CHR page is BELOW the BG3 base -- BG3 tile indices count UPWARD from BG34NBA, so the panel is unreachable. See docs/09 §5.1; the scene's chr claim sizes decide the packing order."
.assert (ES_V_DLG_CHR - DLG_BG3_CHR) < 8192, error, "dialog: the panel's CHR page is past BG3's 1024-tile reach (2bpp: 8192 words). Another chr claim packed between it and the font page. See docs/09 §5.1."
.assert ((ES_V_DLG_CHR - DLG_BG3_CHR) & 7) = 0, error, "dialog: the panel's CHR page is not 8-word aligned relative to the BG3 base -- a 2bpp tile is 8 words, so no tile index addresses it."

DLG_TILE0 = (ES_V_DLG_CHR - DLG_BG3_CHR) / 8

; The panel's tile-word attr: this feature's own sub-palette, plus the BG3
; per-tile priority bit that lifts the box above BG1/BG2/OBJ under a BG3-high
; BGMODE. Derived, never bound — ES_C_DLG_PAL is where the palette really went.
DLG_ATTR = DLG_TILE0 | ((ES_C_DLG_PAL / 4) << 10) | (1 << 13)

; nine-patch order, as tools/gen_dialog_assets.py emits it
DLG_T_TL = 0
DLG_T_TOP = 1
DLG_T_TR = 2
DLG_T_LEFT = 3
DLG_T_FILL = 4
DLG_T_RIGHT = 5
DLG_T_BL = 6
DLG_T_BOT = 7
DLG_T_BR = 8

.assert DLG_W >= 2, error, "dialog: DLG_W must be >= 2 -- a nine-patch needs a left and a right edge"
.assert DLG_H >= DLG_LINES * 2 + 2, error, "dialog: DLG_H is too short for three text lines plus the frame"
.assert DLG_COL + DLG_W <= DLG_CELLS_PER_ROW, error, "dialog: the panel runs past the 32-cell tilemap row"
.assert DLG_SPAN_BYTES <= ES_DLG_BUF_SIZE, error, "dialog: DLG_H exceeds the dlg_buf claim -- raise the claim in feature.toml, do not write past it"
.assert (DLG_ROW + DLG_H) * DLG_CELLS_PER_ROW <= ES_V_TEXT_MAP_WORDS, error, "dialog: the panel's row span runs past the BG3 tilemap claim (docs/09 §5.1's tilemap half -- this feature writes bg_text's region)"

; --- dlg_ctl fields (feature.toml documents the layout) ---------------------
DLG_STATE = ES_DLG_CTL + 0
DLG_DIRTY = ES_DLG_CTL + 1
DLG_PAGE = ES_DLG_CTL + 2
DLG_PAGES = ES_DLG_CTL + 3
DLG_TAB = ES_DLG_CTL + 4
DLG_T0 = ES_DLG_CTL + 6
DLG_T1 = ES_DLG_CTL + 8

; The blob's 24-bit constants, derived from dlg_rom's emitted claim symbols —
; this feature `depends` on that blob, so it may name them, and deriving them
; is what lets dialog_upload take NO source arguments at all (an earlier form
; passed a bank + address and read through `f:$000000,x`, which no_literals
; refuses by name and is right to: a narrated bank is exactly the thing the
; allocator exists to emit).
DLG_PAL_LONG = (ES_R_DLG_PAL_BANK << 16) | ES_R_DLG_PAL_ADDR
DLG_REGS = $4300 + ES_H_DLGQ_CH * 16
DLG_UP_REGS = $4300 + ES_D_DLG_UP_CH * 16

; =============================================================================
; dialog_init — the routine behind `[init] zero`.
; =============================================================================
; CONTRACT dialog_init
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole ES_DLG_CTL claim zeroed. That is the establishment
;             `[init] zero` declares: mosaic shipped the same declaration
;             without a routine and the first ROM to compose it tripped
;             Mesen's uninitialised-read detector
;   clobbers: X, N, Z
;   assumes:  ONCE, from the boot block
;   tail:     rts
;
; `[init] zero` is emitted by the allocator as a COMMENT; no code falls out of
; it. `state` and `dirty` are READ BEFORE ANY WRITE (dialog_is_open and the NMI
; hook read them from boot onward, long before the first open) and nothing
; seeds them — that is what "closed" MEANS. Mosaic shipped this declaration
; without a routine and the first ROM to compose it tripped Mesen's
; uninitialised-read detector.
dialog_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_init"
    ldx #(ES_DLG_CTL_SIZE - 2)
:   stz z:ES_DLG_CTL, x
    dex
    dex
    bpl :-
    rts

; =============================================================================
; dialog_upload — the panel CHR + palette, at scene enter under FORCED BLANK.
; =============================================================================
; CONTRACT dialog_upload
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       NO ARGUMENTS. The source is this feature's own dlg_rom
;             dependency and its address comes from the emitted claim
;             symbols, not from a caller
;   out:      the panel CHR uploaded by GP-DMA on the channel the dlg_up
;             dma_init claim names, and the four palette words written by
;             CPU store — cheaper than arming a channel for eight bytes,
;             and what every BG feature here does
;   clobbers: A, X, N, Z, C
;   assumes:  scene enter, under FORCED BLANK. A8 is used only for the
;             byte-wide port writes and every toggle is balanced
;   tail:     rts
;
; NO ARGUMENTS: the source is this feature's own `dlg_rom` dependency and its
; address comes from the emitted claim symbols, not from a caller. The CHR goes
; by GP-DMA on the channel the dlg_up dma_init claim names; the four palette
; words go by CPU store, which is cheaper than arming a channel for eight bytes
; and is what every BG feature in the tree does.
dialog_upload:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_upload"
    sep #$20
    .a8
    lda #ES_R_DLG_CHR_BANK
    sta a:DLG_UP_REGS + 4           ; A1B
    lda #$80
    sta a:$2115                     ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_DLG_CHR
    sta a:$2116                     ; VMADD = the panel's own page
    lda #ES_R_DLG_CHR_ADDR
    sta a:DLG_UP_REGS + 2           ; A1T
    lda #ES_R_DLG_CHR_SIZE
    sta a:DLG_UP_REGS + 5           ; DAS — armed per transfer, one transfer
    sep #$20
    .a8
    lda #ES_D_DLG_UP_DMAP
    sta a:DLG_UP_REGS + 0
    lda #ES_D_DLG_UP_BBAD
    sta a:DLG_UP_REGS + 1           ; -> VMDATAL
    lda #(1 << ES_D_DLG_UP_CH)
    sta a:$420B                     ; fire
    ; ---- the four panel colours, CPU-side --------------------------------
    lda #ES_C_DLG_PAL
    sta a:$2121                     ; CGADD = this feature's claim base
    ldx #0
@pal:
    lda f:DLG_PAL_LONG, x
    sta a:$2122
    inx
    cpx #ES_R_DLG_PAL_SIZE
    bcc @pal
    rep #$20
    .a16
    rts

; =============================================================================
; dialog_open — open the panel on page 0 of a message.
; =============================================================================
; CONTRACT dialog_open
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the string table address, X (low byte) = the page count
;   out:      the box and page 0 staged into the buffer and the panel
;             marked dirty; the next VBlank commits it. Idempotent on an
;             already-open panel — it just restages
;   clobbers: A, X, Y, N, Z
;   assumes:  the main thread, not the hook — it stages, and
;             dialog_nmi_commit is what touches VRAM
;   tail:     rts
;
; In: A16 = the message's page table (a bank-0 ROM label: DLG_LINES word
;  pointers per page, in page order), X = page count (>= 1).
; Stages the box + page 0 into the buffer and marks it dirty; the next VBlank
; commits it. Idempotent on an already-open panel (it just restages).
dialog_open:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_open"
    sta z:DLG_TAB
    txa
    sep #$20
    .a8
    sta z:DLG_PAGES
    lda #1
    sta z:DLG_STATE
    stz z:DLG_PAGE
    rep #$20
    .a16
    jsr _dlg_stage_page
    rts

; =============================================================================
; dialog_advance — show the next page, or close after the last one.
; =============================================================================
; CONTRACT dialog_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      A = 1 if the panel is still open, 0 if this call closed it
;             (Z set). That is the text flow — open, page, page, close —
;             and the close is not a separate caller decision. A closed
;             panel returns 0 without restaging
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread. Advancing is a page step, not a typewriter
;             step
;   tail:     rts
;
; Out: A16 = 1 if the panel is still open, 0 if this call closed it (Z set).
; This is the "text flow": open -> page -> page -> close, and the close is not
; a separate caller decision. A closed panel returns 0 without restaging.
dialog_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_advance"
    sep #$20
    .a8
    lda z:DLG_STATE
    bne @open
    rep #$20
    .a16                            ; closed: nothing to advance
    lda #0
    rts
@open:
    .a8
    lda z:DLG_PAGE
    inc a
    cmp z:DLG_PAGES
    bcc @next
    rep #$20
    .a16
    jsr dialog_close
    lda #0
    rts
@next:
    .a8
    sta z:DLG_PAGE
    rep #$20
    .a16
    jsr _dlg_stage_page
    lda #1
    rts

; =============================================================================
; dialog_close — hide the panel and restore the scene behind it.
; =============================================================================
; CONTRACT dialog_close
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the panel closed and the window blanked, staged for the next
;             VBlank
;   clobbers: A, N, Z
;   assumes:  the main thread
;   tail:     rts
;
; Stages the whole row span as the scene's BLANK cell and marks it dirty. The
; user-visible invariant this exists for is "the scene behind the box comes
; back", and it is the whole span rather than the panel rectangle because the
; span is what open wrote (feature.toml states the consequence: a scene must
; not put static text in the panel's rows).
dialog_close:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_close"
    sep #$20
    .a8
    stz z:DLG_STATE
    rep #$20
    .a16
    jsr _dlg_stage_blank
    ; DIRTY IS SET LAST, AND THAT ORDERING IS THE CONTRACT. Dialog_nmi_commit
    ; fires on this flag and CLEARS it, so a flag raised before the buffer is
    ; whole lets an NMI landing in the window commit a PARTIAL span and clear
    ; the flag — the remainder never commits, leaving a half-erased panel.
    ; Callers run from the main loop with NMI enabled, so the window is real;
    ; setting the flag after the last stage write removes the obligation
    ; instead of documenting it.
    sep #$20
    .a8
    lda #1
    sta z:DLG_DIRTY
    rep #$20
    .a16
    rts

; =============================================================================
; dialog_is_open — Out: A16 = 0 (closed) / 1 (open), Z set when closed. In/out:
; CONTRACT dialog_is_open
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      A = 0 (closed) or 1 (open), Z set when closed — the state
;             byte alone, masked off the `dirty` byte above it
;   clobbers: A, N, Z
;   assumes:  nothing. It is a read
;   tail:     rts
dialog_is_open:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "dialog_is_open"
    lda z:ES_DLG_CTL
    and #255                        ; the state byte alone; `dirty` is above it
    rts

; =============================================================================
; dialog_nmi_commit — commit the staged span (call from sm_nmi_hook).
; =============================================================================
; CONTRACT dialog_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the staged span committed by ONE contiguous GP-DMA over the
;             dlgq channel's register file. A no-op on frames nothing was
;             staged
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. It sets its own VMAIN/VMADD because the OAM and
;             stream DMAs ahead of it leave both wherever their last
;             transfer wanted — which is what makes hook ORDER free here.
;             DAS is armed inside the routine even though exactly one
;             transfer fires, so a future second transfer cannot inherit a
;             stale count
;   tail:     rts
;
; One contiguous GP-DMA over the dlgq channel's register file. Sets its own
; VMAIN/VMADD because the OAM/stream DMAs ahead of it in the hook leave both in
; whatever state their last transfer wanted — which is what makes hook ORDER
; free here (AGENTS.md's established pattern).
;
; DAS is single-shot and this fires exactly ONE transfer, so there is no
; re-arm-per-slot loop to get wrong. It is armed inside the routine all the
; same, so it cannot be left behind by a future second transfer. In/out:
dialog_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "dialog_nmi_commit"
    lda z:DLG_DIRTY
    beq @done
    stz z:DLG_DIRTY
    lda #$80
    sta a:$2115                     ; VMAIN: word step after the $2119 write
    lda #ES_H_DLGQ_DMAP
    sta a:DLG_REGS + 0              ; DMAP: A->B, 2-reg write-once (declared)
    lda #ES_H_DLGQ_BBAD
    sta a:DLG_REGS + 1              ; BBAD: VMDATAL (declared)
    lda #ES_DLG_BUF_BANK
    sta a:DLG_REGS + 4              ; A1B: the buffer's WRAM bank
    rep #$20
    .a16
    lda #(DLG_MAP + DLG_ROW * DLG_CELLS_PER_ROW)
    sta a:$2116                     ; VMADD = the first cell of the row span
    lda #ES_DLG_BUF
    sta a:DLG_REGS + 2              ; A1T
    lda #DLG_SPAN_BYTES
    sta a:DLG_REGS + 5              ; DAS — armed here, per transfer
    sep #$20
    .a8
    lda #(1 << ES_H_DLGQ_CH)
    sta a:$420B                     ; fire
@done:
    .a8
    rts

; =============================================================================
; _dlg_stage_blank — fill the whole row span with the scene's blank cell.
; In/out: A16/I16, DB=0. Clobbers A, X.
; =============================================================================
.a16
.i16
_dlg_stage_blank:
    ldx #(DLG_SPAN_BYTES - 2)
    lda #DLG_TEXT_ATTR              ; tile 0 of the font page IS space
:   sta a:ES_DLG_BUF, x             ; DB=0 reaches the $7E mirror at $0000-$1FFF
    dex
    dex
    bpl :-
    rts

; =============================================================================
; _dlg_stage_page — blank, frame, then the current page's DLG_LINES lines.
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; =============================================================================
.a16
.i16
_dlg_stage_page:
    jsr _dlg_stage_blank
    jsr _dlg_stage_box
    sep #$20
    .a8
    lda z:DLG_PAGE
    rep #$20
    .a16
    and #255
    ; page table offset = page * DLG_LINES * 2
    sta z:DLG_T1
    asl
    clc
    adc z:DLG_T1                    ; x3 == x DLG_LINES
    asl                             ; x2 == word entries
    clc
    adc z:DLG_TAB
    tax                             ; X = &line0 pointer for this page
    ldy #0                          ; Y = line number 0..DLG_LINES-1
@line:
    phx
    phy
    lda a:0, x                      ; the line's string address (bank 0)
    tyx                             ; X = line number -> panel row 1 + 2*line
    jsr _dlg_stage_line
    ply
    plx
    inx
    inx
    iny
    cpy #DLG_LINES
    bcc @line
    ; DIRTY LAST — the whole page (box AND its text lines) is staged by here.
    ; See dialog_close for why the ordering is the contract: the commit clears
    ; the flag, so raising it before the text lines were staged let an NMI in
    ; the window publish a boxed page with no text in it.
    sep #$20
    .a8
    lda #1
    sta z:DLG_DIRTY
    rep #$20
    .a16
    rts

; =============================================================================
; _dlg_stage_box — write the nine-patch into cells [DLG_COL, DLG_COL+DLG_W).
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; =============================================================================
; The row arm is picked ONCE per row (top / middle / bottom) and the column arm
; once per cell — the smallest decision tree a nine-patch admits. It walks a
; WRAM buffer rather than a tilemap shadow, and every arm is a branch rather
; than a jmp trampoline, because these loops are short enough to stay in
; branch range.
.a16
.i16
_dlg_stage_box:
    ldy #0                          ; Y = panel row 0..DLG_H-1
@row:
    ; ---- choose this row's three tiles into DLG_T0 (left/mid/right base) ----
    tya
    bne @not_top
    lda #DLG_T_TL
    bra @have_row
@not_top:
    .a16
    cpy #(DLG_H - 1)
    bne @mid_row
    lda #DLG_T_BL
    bra @have_row
@mid_row:
    .a16
    lda #DLG_T_LEFT
@have_row:
    .a16
    sta z:DLG_T0                    ; T0 = the row's LEFT tile; +1 mid, +2 right
    ; ---- X = buffer byte offset of (row, DLG_COL) ----
    tya
    asl
    asl
    asl
    asl
    asl
    asl                             ; row * 64 bytes (32 cells x 2)
    clc
    adc #(DLG_COL * 2)
    tax
    phy
    ldy #0                          ; Y = cell 0..DLG_W-1
@cell:
    tya
    bne @not_left
    lda z:DLG_T0                    ; left edge
    bra @have_cell
@not_left:
    .a16
    cpy #(DLG_W - 1)
    bne @middle
    lda z:DLG_T0
    inc a
    inc a                           ; right edge
    bra @have_cell
@middle:
    .a16
    lda z:DLG_T0
    inc a                           ; mid
@have_cell:
    .a16
    ora #DLG_ATTR                   ; tile base | palette | priority
    sta a:ES_DLG_BUF, x
    inx
    inx
    iny
    cpy #DLG_W
    bcc @cell
    ply
    iny
    cpy #DLG_H
    bcc @row
    rts

; =============================================================================
; _dlg_stage_line — one NUL-terminated ASCII line, inset in the panel. In: A16
; = string address (bank 0), X = line number 0..DLG_LINES-1. Lines sit at
; panel rows 1, 3, 5 — one blank row between them, i.e. a 16-px line pitch
; expressed in cells. Glyph mapping is bg_text's, exactly: tile = (ascii &
; 127) - ' '. Clipped at the panel's right frame; a longer line is truncated,
; never wrapped past the frame into another feature's cells. In/out: A16/I16,
; DB=0. Clobbers A, X, Y.
; =============================================================================
.a16
.i16
_dlg_stage_line:
    sta z:DLG_T0                    ; the string pointer
    txa
    asl                             ; line -> panel row (1 + 2*line)
    inc a
    asl
    asl
    asl
    asl
    asl
    asl                             ; row * 64 bytes
    clc
    adc #((DLG_COL + 1) * 2)        ; inset one cell from the left frame
    tax
    ldy #0
@ch:
    cpy #(DLG_W - 2)                ; the interior width; the frame is not ours
    bcs @end
    sep #$20
    .a8
    lda (DLG_T0), y
    beq @end
    rep #$20
    .a16
    and #127                        ; 7-bit ASCII
    sec
    sbc #' '                        ; glyph index — space is tile 0
    ora #DLG_TEXT_ATTR
    sta a:ES_DLG_BUF, x
    inx
    inx
    iny
    bra @ch
@end:
    ; WIDTH-RISK: reached A8 from the `beq` (the NUL test) and A16 from the
    ; `bcs` (the clip test). A bare directive would ASSERT one arrival and lie
    ; about the other, so this is a forced narrowing — legal from either.
    sep #$20
    .a8
    rep #$20
    .a16
    rts
