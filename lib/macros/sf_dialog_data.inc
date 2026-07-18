; =============================================================================
; sf_dialog_data.inc — dialog-panel CHR + routines (macro library, link partner)
; =============================================================================
; The EMITTED half of sf_dialog.inc: the 9 box CHR tiles (original art) and the
; panel-draw / panel-clear routines the macros JSR. Unlike the macro file, this
; file EMITS bytes + code — include it ONCE at the BOTTOM of main.asm, inside
; the CODE segment, next to the engine .asm includes and AFTER text_engine.asm
; (the panel composes WITH the kit text engine — see the sf_dialog.inc header):
;
;   .include "text_engine.asm"
;   .include "sf_text_data.inc"
;   .include "sf_dialog_data.inc"
;
; (If you forget it, the link fails naming sf_dialog_chr / _sf_dialog_draw_box —
; that's your cue.)
;
; THE BOX IS DRAWN INTO THE KIT'S BG3 SHADOW TILEMAP (SHADOW_BG3_TILEMAP,
; $7E:B200), exactly like the kit's `print` macro — the stock NMI commits the
; dirty BG3 shadow to VRAM next VBlank, so there is NO custom NMI, NO direct
; VRAM write, and NO forced-blank dance for the box. Every panel cell is an
; OPAQUE tile carrying the BG3 PRIORITY bit (bit 13 of the tile word), so under
; the kit boot's BGMODE=$09 (Mode 1, BG3 high priority) the panel composites
; ABOVE BG1/BG2 and above the OBJ sprites — the scene shows through only OUTSIDE
; the panel. (This is the C2 opacity contract the slice's golden test asserts,
; generalized off the slice's town-specific dialog_panel.inc.)
;
; The 9 CHR tiles form a 3x3 nine-patch: 4 corners, 4 edges, 1 body fill. The
; macro chooses, per cell, which of the 9 the position needs (corner / edge /
; fill) so any width>=2 x height>=2 box frames correctly. Tile 0 (the blank)
; is the kit's transparent BG3 cell — the panel never writes it inside its
; bounds, and sf_dialog_close restores the panel region to it.
;
; CHR placement: BG3 CHR base is word $2000 (kit gfxmode BG34NBA=$0A encodes
; base bits 0-2 = $2 -> $2000; the kit font is at $2500 = tile 160). The box
; occupies BG3 tiles SF_DLG_TILE_BASE..+8 (default 1..9 -> words $2008..$204F),
; clear of the kit font at tile 160. 2bpp, 16 bytes/tile.
; =============================================================================

.ifndef SF_DIALOG_DATA_INC
SF_DIALOG_DATA_INC = 1

.include "engine_state.inc"     ; SHADOW_BG3_TILEMAP, BG_TILEMAP_DIRTY (guarded)

; -----------------------------------------------------------------------------
; Tunables (override BEFORE including this file to relocate the box CHR/palette).
; -----------------------------------------------------------------------------
.ifndef SF_DLG_TILE_BASE
; BG3 and BG1 SHARE the CHR base region (kit BG12NBA BG1=$2000, BG34NBA BG3
; encodes base $2000). The kit font is at tile 160 ($2500+); BG1 game tiles are
; conventionally 0-79. The box defaults to tiles 144-152 (words $2480-$24C8),
; in the 80-159 gap between BG1 game tiles and the font — clear of BOTH. (If
; your game uses BG1 tiles past 143, relocate via this define.)
SF_DLG_TILE_BASE = 144         ; first BG3 CHR tile of the 9-tile nine-patch
.endif
.ifndef SF_DLG_PALETTE
SF_DLG_PALETTE   = 6            ; BG3 sub-palette (2bpp: CGRAM[pal*4 .. pal*4+3])
.endif

; Nine-patch tile ids (relative to SF_DLG_TILE_BASE).
SF_DLG_T_TL   = (SF_DLG_TILE_BASE + 0)  ; top-left corner
SF_DLG_T_TOP  = (SF_DLG_TILE_BASE + 1)  ; top edge
SF_DLG_T_TR   = (SF_DLG_TILE_BASE + 2)  ; top-right corner
SF_DLG_T_LEFT = (SF_DLG_TILE_BASE + 3)  ; left edge
SF_DLG_T_FILL = (SF_DLG_TILE_BASE + 4)  ; body fill
SF_DLG_T_RIGHT= (SF_DLG_TILE_BASE + 5)  ; right edge
SF_DLG_T_BL   = (SF_DLG_TILE_BASE + 6)  ; bottom-left corner
SF_DLG_T_BOT  = (SF_DLG_TILE_BASE + 7)  ; bottom edge
SF_DLG_T_BR   = (SF_DLG_TILE_BASE + 8)  ; bottom-right corner

; Tilemap attr high bits OR'd into every panel tile word:
;   bit13 ($2000) = BG3 priority (composite above BG1/BG2/OBJ under BGMODE $09)
;   bits10-12     = palette field (SF_DLG_PALETTE << 10)
SF_DLG_ATTR_W = ($2000 | (SF_DLG_PALETTE << 10))
; The kit transparent BG3 cell (tile 0, no attr) — what a closed panel shows.
SF_DLG_BLANK_W = $0000

; -----------------------------------------------------------------------------
; sf_dialog_chr — the 9-tile nine-patch, 2bpp (16 bytes/tile), ORIGINAL ART.
; -----------------------------------------------------------------------------
; Color budget (2bpp = 4 colors of the selected BG3 sub-palette):
;   idx 0 = transparent (appears only OUTSIDE the panel)
;   idx 1 = panel body fill (opaque background of the box)
;   idx 2 = frame / border line
;   idx 3 = (reserved; text glyphs print over the box in their own palette)
; Every BODY pixel of every tile is >=1, so no tile is transparent inside the
; panel (the C2 opacity contract). 2bpp byte layout: 8 rows x (bitplane0 byte,
; bitplane1 byte); pixel value = bit(bp1)<<1 | bit(bp0), MSB = leftmost pixel.
; A frame edge tile is fill (1) everywhere except the one border line of 2s.
; The exact bytes are GENERATED + verified (see docs/guides — fill=1 => bp0=$FF
; bp1=$00; border=2 => bp0=$00 bp1=$FF; a left border column makes bp0 bit7=0 &
; bp1 bit7=1, i.e. bp0=$7F bp1=$80). Do NOT hand-edit; regenerate if changing.
; -----------------------------------------------------------------------------
.export sf_dialog_chr
sf_dialog_chr:
    .byte $00,$FF, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80  ; +0 TL  corner
    .byte $00,$FF, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00  ; +1 TOP edge
    .byte $00,$FF, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01  ; +2 TR  corner
    .byte $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80  ; +3 LEFT edge
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00  ; +4 FILL body
    .byte $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01  ; +5 RIGHT edge
    .byte $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $7F,$80, $00,$FF  ; +6 BL  corner
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $00,$FF  ; +7 BOT edge
    .byte $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $FE,$01, $00,$FF  ; +8 BR  corner

SF_DLG_CHR_TILES = 9
SF_DLG_CHR_BYTES = (SF_DLG_CHR_TILES * 16)

; -----------------------------------------------------------------------------
; sf_dialog_default_pal — a default 4-color BG3 panel palette (15-bit BGR).
; -----------------------------------------------------------------------------
;   color 0 transparent (value ignored by the PPU for entry 0 of a BG palette
;           used as a tile color — but we never use idx0 inside the panel)
;   color 1 dark-blue panel body         color 2 light-blue border
;   color 3 white (unused by the box; text prints in its own palette)
; sf_dialog_init uploads these to CGRAM[SF_DLG_PALETTE*4 .. +3].
.export sf_dialog_default_pal
sf_dialog_default_pal:
    .word $0000     ; 0: transparent
    .word $2862     ; 1: dark blue body  (r2 g3 b10)
    .word $7BDE     ; 2: light blue border (r30 g30 b30-ish -> pale)
    .word $7FFF     ; 3: white

; =============================================================================
; _sf_dialog_set_shadow_rc — point X at the BG3 SHADOW tilemap byte for (r,c).
;   shadow_addr = SHADOW_BG3_TILEMAP + (row*32 + col)*2   (2 bytes/entry)
;   In:  A16 = row, Y16 = col.   Out: X16 = byte offset within bank $7E.
; Clobbers A. Entry/exit A16/I16. (No DB assumption — caller uses long stores.)
; WIDTH-RISK: A16/I16 entry+exit; no rep/sep, no tax across widths (tay/tax are
; all-16-bit here). Pure index math.
; =============================================================================
.a16
.i16
.proc _sf_dialog_set_shadow_rc
    ; row*32
    asl
    asl
    asl
    asl
    asl                         ; row*32
    sta a:_sf_dlg_scratch       ; stash row*32
    tya                         ; col
    clc
    adc a:_sf_dlg_scratch       ; row*32 + col   (entry index)
    asl                         ; *2 = byte offset
    clc
    adc #SHADOW_BG3_TILEMAP      ; + tilemap base (low 16, bank $7E)
    tax
    rts
.endproc

; =============================================================================
; _sf_dialog_draw_box — render the opaque nine-patch into the BG3 shadow.
;   In (read from _sf_dlg_* scratch, set by the macro):
;     _sf_dlg_col0  first column   _sf_dlg_row0  first row
;     _sf_dlg_w     width (cells)   _sf_dlg_h     height (cells)
;     _sf_dlg_wm1   width-1         _sf_dlg_hm1   height-1
;   For each cell, pick the nine-patch tile (corner/edge/fill) and write its
;   tile word (id | SF_DLG_ATTR_W) to SHADOW_BG3_TILEMAP, then set the BG3
;   dirty bit so the stock NMI commits it. w>=2, h>=2 required for a framed box
;   (the macro asserts >=2). Loop variables live in scratch (X/Y are reused for
;   the absolute-cell index math), so no fragile stack juggling.
; Entry/exit A16/I16. Clobbers A, X, Y + _sf_dlg_* scratch.
; WIDTH-RISK: A16/I16 entry+exit. A8 toggle ONLY for the final BG3-dirty byte
; OR (1 byte, balanced rep/sep). No tax/tay across a width change.
; =============================================================================
.a16
.i16
.proc _sf_dialog_draw_box
    stz a:_sf_dlg_ry            ; ry = row-in-panel 0..h-1
@row_loop:
    stz a:_sf_dlg_rx            ; rx = col-in-panel 0..w-1
@col_loop:
    ; ---- choose nine-patch tile for (ry, rx) into A ----
    lda a:_sf_dlg_ry
    bne @not_top
    ; top row: TL / TOP / TR
    lda a:_sf_dlg_rx
    bne @t_not_left
    lda #SF_DLG_T_TL
    bra @have_tile
@t_not_left:
    cmp a:_sf_dlg_wm1
    bne @t_mid
    lda #SF_DLG_T_TR
    bra @have_tile
@t_mid:
    lda #SF_DLG_T_TOP
    bra @have_tile
@not_top:
    lda a:_sf_dlg_ry
    cmp a:_sf_dlg_hm1
    bne @mid_row
    ; bottom row: BL / BOT / BR
    lda a:_sf_dlg_rx
    bne @b_not_left
    lda #SF_DLG_T_BL
    bra @have_tile
@b_not_left:
    cmp a:_sf_dlg_wm1
    bne @b_mid
    lda #SF_DLG_T_BR
    bra @have_tile
@b_mid:
    lda #SF_DLG_T_BOT
    bra @have_tile
@mid_row:
    ; middle row: LEFT / FILL / RIGHT
    lda a:_sf_dlg_rx
    bne @m_not_left
    lda #SF_DLG_T_LEFT
    bra @have_tile
@m_not_left:
    cmp a:_sf_dlg_wm1
    bne @m_fill
    lda #SF_DLG_T_RIGHT
    bra @have_tile
@m_fill:
    lda #SF_DLG_T_FILL
@have_tile:
    ora #SF_DLG_ATTR_W           ; tile id | priority | palette
    sta a:_sf_dlg_tileword

    ; ---- shadow byte offset for ABSOLUTE cell (row0+ry, col0+rx) ----
    lda a:_sf_dlg_rx
    clc
    adc a:_sf_dlg_col0
    tay                         ; Y = absolute col
    lda a:_sf_dlg_ry
    clc
    adc a:_sf_dlg_row0          ; A = absolute row
    jsr _sf_dialog_set_shadow_rc ; X = shadow byte offset (uses A=row, Y=col)
    lda a:_sf_dlg_tileword
    sta f:$7E0000, x            ; write the opaque tile word (bank $7E)

    ; ---- advance rx; wrap to next row. Backward branches over the long
    ;      nine-patch chain exceed the 8-bit branch range, so use the
    ;      invert-and-jmp trampoline (the kit README's documented idiom). ----
    lda a:_sf_dlg_rx
    inc a
    sta a:_sf_dlg_rx
    cmp a:_sf_dlg_w
    bcs @row_advance
    jmp @col_loop
@row_advance:
    lda a:_sf_dlg_ry
    inc a
    sta a:_sf_dlg_ry
    cmp a:_sf_dlg_h
    bcs @draw_done
    jmp @row_loop
@draw_done:
    ; ---- mark BG3 dirty so the stock NMI commits the shadow next VBlank ----
    sep #$20
    .a8
    lda BG_TILEMAP_DIRTY
    ora #$04                    ; bit2 = BG3
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; _sf_dialog_clear_box — restore the panel region of the BG3 shadow to the kit
; transparent blank (tile 0, no attr), so the scene is FULLY restored there.
; Same (col0,row0,w,h) scratch inputs as _sf_dialog_draw_box. Sets BG3 dirty.
; Entry/exit A16/I16. Clobbers A, X, Y + _sf_dlg_* scratch.
; WIDTH-RISK: A16/I16 entry+exit; A8 toggle only for the dirty byte (balanced).
; =============================================================================
.a16
.i16
.proc _sf_dialog_clear_box
    stz a:_sf_dlg_ry
@row_loop:
    stz a:_sf_dlg_rx
@col_loop:
    lda a:_sf_dlg_rx
    clc
    adc a:_sf_dlg_col0
    tay                         ; Y = absolute col
    lda a:_sf_dlg_ry
    clc
    adc a:_sf_dlg_row0          ; A = absolute row
    jsr _sf_dialog_set_shadow_rc
    lda #SF_DLG_BLANK_W
    sta f:$7E0000, x
    lda a:_sf_dlg_rx
    inc a
    sta a:_sf_dlg_rx
    cmp a:_sf_dlg_w
    bcc @col_loop
    lda a:_sf_dlg_ry
    inc a
    sta a:_sf_dlg_ry
    cmp a:_sf_dlg_h
    bcc @row_loop
    sep #$20
    .a8
    lda BG_TILEMAP_DIRTY
    ora #$04                    ; bit2 = BG3
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; Panel scratch (low WRAM, the kit macro-scratch band $0530-$053F is full, so
; the dialog claims $0540 has-conflict? No — dma_scheduler owns $0548+. Use the
; verified-free SPRITE-engine-disjoint hole? The kit reserves $0560-$056F for
; sprite scratch. We claim a private 16-byte block in the GAME-ARRAY region's
; documented macro tail. Per the sf_dialog.inc header these are transient,
; consumed within an open/close call — NOT persistent panel state (that is the
; caller-bound DP byte). Placed at $1DC0 (game-array region $1800-$1DFF, ABOVE
; the audio tail $1DE0; engine-free; lda/sta abs reachable from bank $00).
; -----------------------------------------------------------------------------
_sf_dlg_scratch  = $1DC0        ; 2 B: row*32 temp
_sf_dlg_tileword = $1DC2        ; 2 B: tile word being written
_sf_dlg_col0     = $1DC4        ; 2 B: panel first column
_sf_dlg_row0     = $1DC6        ; 2 B: panel first row
_sf_dlg_w        = $1DC8        ; 2 B: panel width (cells)
_sf_dlg_h        = $1DCA        ; 2 B: panel height (cells)
_sf_dlg_wm1      = $1DCC        ; 2 B: width-1  (right-edge compare)
_sf_dlg_hm1      = $1DCE        ; 2 B: height-1 (bottom-edge compare)
_sf_dlg_rx       = $1DD0        ; 2 B: col-in-panel loop var
_sf_dlg_ry       = $1DD2        ; 2 B: row-in-panel loop var

.endif ; SF_DIALOG_DATA_INC
