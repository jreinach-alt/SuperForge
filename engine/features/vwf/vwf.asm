; =============================================================================
; vwf.asm — variable-width font renderer for BG3 (scene-scoped)
; =============================================================================
; Composites glyphs of differing pixel widths into a WRAM tile canvas by
; bit-shifting each to the current sub-tile pen position, then DMAs the dirtied
; span into text_chr's page during VBlank. Bg_text writes one tile per
; character; this writes one tile per 8 pixels of RENDERED text.
;
; Claims: vwf_canvas (wram, dma source) · vwf_pen (dp) · vwfq (hdma, vblank)
;  + claims.dma. Destination tiles are a sub-range of text_chr's claim,
;  asserted below. Source face is vwf_rom's two blobs.
;
; No layer/mode PPU register is written here — BG3SC/BG34NBA are the scene's,
; set at enter. The only PPU writes are $2115/$2116 addressing the region the
; vwfq claim's VMDATAL/VMDATAH already declare (09 §2.1's covered side).

; --- the sub-range contract, derived from emitted symbols and ASSERTED -------
; text_chr owns the whole BG3 CHR page. Bg_text takes tiles 0..VWF_TILE0-1 (a
; glyph's index IS its tile id — text_puts depends on that) and vwf takes
; VWF_TILE0 upward. Both numbers are DERIVED, not written: VWF_TILE0 comes from
; the font blob's declared size so it cannot drift from the glyph count
; font_rom actually ships, and the strip count comes from the canvas claim's
; size so the canvas and the window can never disagree.
VWF_TILE_BYTES  = 16                                    ; 2bpp: 8 rows x 2 planes
VWF_TILE_WORDS  = 8
VWF_TILE0       = ES_R_FONT_BIN_SIZE / VWF_TILE_BYTES   ; 96 fixed-width glyphs
; ... Minus the spill-guard tile the canvas claim's comment describes: a glyph
; at pen x touches tiles x/8 and x/8+1, so the window's last tile spills one
; further and the guard absorbs it unuploaded.
VWF_STRIP_TILES = ES_VWF_CANVAS_SIZE / VWF_TILE_BYTES - 1   ; 14 = 112 px
VWF_CHR_WORD0   = ES_V_TEXT_CHR + VWF_TILE0 * VWF_TILE_WORDS

; The gate that makes the sub-range a build-time refusal rather than prose: if
; text_chr's claim ever stops covering both renderers, this fails the build.
.assert (VWF_TILE0 + VWF_STRIP_TILES) * VWF_TILE_WORDS <= ES_V_TEXT_CHR_WORDS, error, "vwf strips overrun text_chr's claim - grow tiles= in text_chr/feature.toml"
; A BG layer reaches tilemapData & $3FF tiles from its base (Mesen2
; SnesPpu.cpp:239-248), so a strip tile beyond 1023 would be unaddressable.
.assert (VWF_TILE0 + VWF_STRIP_TILES) <= 1024, error, "vwf strip tiles outside BG3's 10-bit tile index"
; ...and the LOWER bound, which the two above cannot give. The asserts above
; bound the pair's TOP against text_chr's claim; nothing there stops VWF_TILE0
; from falling BELOW the highest tile id bg_text emits, which would put HUD
; glyphs inside the strips with the claim still satisfied (fewer total tiles).
; The bound is text_puts' own arithmetic, not a written 96: it masks the byte
; with #127 and subtracts #' ', so the largest tile id it can emit is 127 - '
; ', and the strips must start one past that. A face shipping fewer glyphs than
; the printable ASCII range now refuses the build instead of colliding
; silently.
.assert VWF_TILE0 >= 127 - ' ' + 1, error, "vwf strips start below the highest tile id bg_text's text_puts emits - the font blob is short of the printable ASCII range"

; --- the vwf_pen DP block ---------------------------------------------------
VWF_PEN_X    = ES_VWF_PEN + 0    ; u16: pen, in pixels from the window's left
VWF_DIRTY    = ES_VWF_PEN + 2    ; u8:  0 = nothing staged for the next VBlank
VWF_DIRTY_LO = ES_VWF_PEN + 3    ; u8:  first dirty strip tile (window-relative)
VWF_DIRTY_HI = ES_VWF_PEN + 4    ; u8:  last dirty strip tile (inclusive)
VWF_STR      = ES_VWF_PEN + 5    ; 24-bit source string pointer
VWF_IDX      = ES_VWF_PEN + 8    ; u8:  reveal cursor into the string
VWF_STATE    = ES_VWF_PEN + 9    ; u8:  0 = idle, 1 = revealing, 2 = complete
; The rest are 16-bit ON PURPOSE. The compositor's row loop runs in A16/I16, so
; an 8-bit field here would make `dec z:` a 16-bit decrement and `ldx z:` a
; 16-bit load — both reaching into the neighbouring field. Silent, and exactly
; the class CLAUDE.md rule 6 exists for.
VWF_ACC      = ES_VWF_PEN + 10   ; u16: shift accumulator, hi:lo = the two tiles
VWF_SHIFT    = ES_VWF_PEN + 12   ; u16: sub-tile shift 0..7 of the glyph in flight
VWF_TOFF     = ES_VWF_PEN + 14   ; u16: canvas byte offset of the row in flight
VWF_ROWS     = ES_VWF_PEN + 16   ; u16: row countdown
VWF_ADV      = ES_VWF_PEN + 18   ; u16: the glyph's advance in pixels
VWF_GOFF     = ES_VWF_PEN + 20   ; u16: mask byte index into vwf_glyphs_bin.
                                 ; Held in DP rather than Y because the 65816
                                 ; has no long,y addressing mode — only long,x
                                 ; — and X is needed for the shift counter and
                                 ; the canvas offset inside the same loop.

; --- vwf_begin_line: blank the window and reset the pen ----------------------
; The line clear is NOT defensive zeroing — it is the reveal model's second
; half. Opening a message must blank the window or it renders over the previous
; message's tail, and the canvas is OR-accumulated so compositing into stale
; bytes yields stale ink. Doing it here rather than as [init] zero is what
; makes write-before-read true by construction (see feature.toml). In: A16/I16,
; DB=0. Main thread only (stages, never writes VRAM).
vwf_begin_line:
    .a16
    .i16
    ldx #(ES_VWF_CANVAS_SIZE - 2)
@clr:
    .a16
    .i16
    stz a:ES_VWF_CANVAS, x      ; DB=0 reaches the $7E mirror at $0000-$1FFF
    dex
    dex
    bpl @clr
    stz z:VWF_PEN_X
    sep #$20
    .a8
    stz z:VWF_IDX
    stz z:VWF_DIRTY_LO
    lda #(VWF_STRIP_TILES - 1)
    sta z:VWF_DIRTY_HI          ; the clear dirties the WHOLE window
    lda #1
    sta z:VWF_DIRTY
    sta z:VWF_STATE             ; 1 = revealing
    rep #$20
    .a16
    rts

; --- vwf_nmi_commit: DMA the dirty strip span into text_chr's page -----------
; The upload path, chosen from a MEASUREMENT rather than a default — see
; feature.toml's [claims.dma] comment and the audit record One contiguous span,
; so a typewriter tick and a whole-window clear are the same transfer with a
; different DAS: one declaration covers both.
;
; Uses the vblank-phase channel's $43xx file directly; the NMI core re-arms
; every channel from the scene_mgr shadow after the hook, so time-sharing ch2
; with rgb_gradient's active COLDATA_G claim is safe by construction. Sets its
; own VMAIN/VMADD because the stream/OAM DMAs ahead of it in the hook leave
; both in whatever state their last transfer wanted.
;
; DAS is single-shot and this fires exactly one transfer, so there is no
; re-arm-per-slot loop to get wrong here (the trap mode7_stream documents). In:
; A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A/X. No-op when nothing was
; staged.
VWF_REGS = $4300 + ES_H_VWFQ_CH * 16

vwf_nmi_commit:
    .a8
    .i16
    lda z:VWF_DIRTY
    beq @done
    stz z:VWF_DIRTY
    lda #$80
    sta a:$2115                 ; VMAIN: word step after the $2119 write
    lda #ES_H_VWFQ_DMAP
    sta a:VWF_REGS + 0          ; DMAP: A->B, 2-reg write-once (declared)
    lda #ES_H_VWFQ_BBAD
    sta a:VWF_REGS + 1          ; BBAD: VMDATAL (declared)
    lda #ES_VWF_CANVAS_BANK
    sta a:VWF_REGS + 4          ; A1B: the canvas's WRAM bank
    ; DAS = (hi - lo + 1) tiles x 16 B
    lda z:VWF_DIRTY_HI
    sec
    sbc z:VWF_DIRTY_LO
    inc                         ; span is inclusive: 1..VWF_STRIP_TILES tiles
    rep #$20
    .a16
    and #$00FF                  ; WIDTH-RISK: the A8 sbc/inc left C-high stale;
                                ; without this the x16 below shifts garbage in
    asl
    asl
    asl
    asl                         ; x VWF_TILE_BYTES
    sta a:VWF_REGS + 5          ; DAS
    sep #$20
    .a8
    lda z:VWF_DIRTY_LO
    rep #$20
    .a16
    and #$00FF                  ; WIDTH-RISK: same — A8 load, 16-bit arithmetic
    tax                         ; X = first dirty strip tile
    asl
    asl
    asl
    asl                         ; x VWF_TILE_BYTES -> canvas byte offset
    clc
    adc #ES_VWF_CANVAS
    sta a:VWF_REGS + 2          ; A1T
    txa
    asl
    asl
    asl                         ; x VWF_TILE_WORDS -> VRAM word offset
    clc
    adc #VWF_CHR_WORD0
    sta a:$2116                 ; VMADD: this span's first strip tile
    sep #$20
    .a8
    lda #(1 << ES_H_VWFQ_CH)
    sta a:$420B                 ; MDMAEN: fire
    ; Empty the span so the next tick stages its own. The inverted sentinel (lo
    ; > hi) is never read while DIRTY = 0, and vwf_stage_tile's min/max
    ; restores a valid span on the first glyph after this.
    lda #VWF_STRIP_TILES
    sta z:VWF_DIRTY_LO
    stz z:VWF_DIRTY_HI
@done:
    .a8                         ; both paths are A8/I16 for the caller
    .i16
    rts

; --- vwf_stage_tile: extend the dirty span to cover tile A and its spill ----
; The span is always contiguous — a glyph cannot skip a tile — so min/max over
; the touched tiles is the whole bookkeeping, and one transfer always covers
; it. The spill neighbour is clamped to the window's last tile: the guard tile
; is written by the compositor but never uploaded. In: A8 = strip tile index.
; In/out: A8/I16, DB=0. Clobbers A.
vwf_stage_tile:
    .a8
    .i16
    cmp z:VWF_DIRTY_LO
    bcs :+
    sta z:VWF_DIRTY_LO
:   .a8
    inc                         ; the spill neighbour
    cmp #VWF_STRIP_TILES
    bcc :+
    lda #(VWF_STRIP_TILES - 1)  ; clamp: the guard tile is never uploaded
:   .a8
    cmp z:VWF_DIRTY_HI
    bcc :+
    sta z:VWF_DIRTY_HI
:   .a8
    lda #1
    sta z:VWF_DIRTY
    rts

; --- vwf_put_glyph: composite one glyph at the pen, then advance the pen -----
; THE feature. A glyph's 1bpp left-aligned rows are shifted to the pen's
; sub-tile position and OR-ed into the canvas, so the next glyph starts at pen
; + its predecessor's ADVANCE rather than at the next tile boundary. That
; difference is the whole of VWF, and it is what the rendered test measures.
;
; Geometry, per row: the glyph's column 0 must land at pixel column (pen & 7)
; of the pen's tile. Reading the pair (pen tile, next tile) as one 16-bit
; window, window column p is bit (15 - p), and the mask's column c is bit (7 -
; c), so the placed value is simply mask << (8 - (pen & 7)) — i.e. `xba` then
; `lsr` (pen & 7) times. High byte lands in the pen's tile, low byte in its
; neighbour, which is why the canvas carries a spill-guard tile.
;
; Both bitplanes get the same byte (BP0 == BP1), matching gen_font.py's
; convention, so VWF ink lands on colour 3 of bg_text's text_pal — no CGRAM
; claim of its own.
;
; In: A16 = ASCII char ($20..$7F). In/out: A16/I16, DB=0. Clobbers A/X/Y. Main
; thread only: it writes WRAM and stages, it never touches VRAM.
vwf_put_glyph:
    .a16
    .i16
    and #$007F
    sec
    sbc #' '                    ; glyph index 0..95 (space = 0, as font_rom)
    tax
    sep #$20
    .a8
    lda f:vwf_widths_bin, x     ; the face's advance for this glyph
    rep #$20
    .a16
    and #$00FF                  ; WIDTH-RISK: A8 load left C-high stale
    sta z:VWF_ADV
    txa
    asl
    asl
    asl                         ; glyph index x 8 rows
    sta z:VWF_GOFF              ; mask byte index (see the DP block on long,y)
    lda z:VWF_PEN_X
    and #$0007
    sta z:VWF_SHIFT             ; sub-tile shift, constant for the whole glyph
    lda z:VWF_PEN_X
    and #$FFF8
    asl                         ; (pen/8) x 16 = the pen tile's canvas offset
    sta z:VWF_TOFF
    lda #VWF_TILE_BYTES / 2     ; 8 rows
    sta z:VWF_ROWS
@row:
    .a16
    .i16
    ldx z:VWF_GOFF
    sep #$20
    .a8
    lda f:vwf_glyphs_bin, x     ; this row's 1bpp mask, already left-aligned
    rep #$20
    .a16
    and #$00FF                  ; WIDTH-RISK: A8 load left C-high stale
    beq @next                   ; blank row: nothing to OR in
    xba                         ; mask << 8: column 0 at bit 15
    ldx z:VWF_SHIFT             ; I16 load of a 16-bit field — see the DP block
    beq @placed
@shift:
    .a16
    .i16
    lsr                         ; slide right to the pen's sub-tile column
    dex
    bne @shift
@placed:
    .a16
    .i16
    sta z:VWF_ACC
    ldx z:VWF_TOFF
    sep #$20
    .a8
    lda z:VWF_ACC + 1           ; high byte -> the pen's own tile
    beq :+
    ora a:ES_VWF_CANVAS, x
    sta a:ES_VWF_CANVAS, x                          ; BP0
    sta a:ES_VWF_CANVAS + 1, x                      ; BP1 == BP0 -> colour 3
:   .a8
    lda z:VWF_ACC               ; low byte -> the spill tile
    beq :+
    ora a:ES_VWF_CANVAS + VWF_TILE_BYTES, x
    sta a:ES_VWF_CANVAS + VWF_TILE_BYTES, x
    sta a:ES_VWF_CANVAS + VWF_TILE_BYTES + 1, x
:   .a8
    rep #$20
    .a16
@next:
    .a16
    .i16
    inc z:VWF_GOFF              ; next mask row
    inc z:VWF_TOFF
    inc z:VWF_TOFF              ; next row is +2 bytes inside the tile
    dec z:VWF_ROWS
    bne @row
    ; --- stage the touched tiles, then advance the pen by the FACE's width ---
    lda z:VWF_PEN_X
    lsr
    lsr
    lsr                         ; the pen's tile index
    sep #$20
    .a8
    jsr vwf_stage_tile
    rep #$20
    .a16
    lda z:VWF_PEN_X
    clc
    adc z:VWF_ADV               ; proportional advance — NOT 8
    sta z:VWF_PEN_X
    rts

VWF_WINDOW_PX = VWF_STRIP_TILES * 8         ; 112 px of composited text

; --- vwf_map_row: point a tilemap row's cells at the strip tiles -------------
; Written ONCE at scene enter under forced blank, like every other bg_text VRAM
; write. After this the strips are live: changing what the row displays is
; changing CHR, never the tilemap — which is why a typewriter tick costs one
; contiguous CHR span and no tilemap traffic at all. In: X = tilemap word
; address of the row's first cell, A16 = attr word. In/out: A16/I16, DB=0.
; FORCED BLANK asserted by the caller.
vwf_map_row:
    .a16
    .i16
    sta z:VWF_ACC               ; attr; nothing is being composited at enter
    sep #$20
    .a8
    lda #$80
    sta a:$2115                 ; VMAIN: word step after the $2119 write
    rep #$20
    .a16
    stx a:$2116                 ; VMADD = the row's first cell
    ldx #0
@cell:
    .a16
    .i16
    txa
    clc
    adc #VWF_TILE0              ; strip tiles start after bg_text's 96 glyphs
    ora z:VWF_ACC
    sta a:$2118                 ; word write: tile id | attr
    inx
    cpx #VWF_STRIP_TILES
    bcc @cell
    rts

; --- vwf_open: point at a 0-terminated string and blank the window -----------
; In: A16 = string address low16, Y = bank in the low byte. In/out: A16/I16,
; DB=0.
vwf_open:
    .a16
    .i16
    sta z:VWF_STR
    tya
    sep #$20
    .a8
    sta z:VWF_STR + 2           ; bank byte alone: a 16-bit store would stomp
                                ; VWF_IDX next door
    rep #$20
    .a16
    jmp vwf_begin_line          ; clears the window, resets the pen, stages all

; --- vwf_tick: reveal one more glyph ----------------------------------------
; The reveal RATE is the game's to choose (how often it calls this), so the
; worst-case dirty span stays the one-glyph case the claim is sized for. A
; glyph is composited only while the pen is still inside the window; the
; canvas's spill-guard tile absorbs the last glyph's overhang unuploaded.
; In/out: A16/I16, DB=0. Clobbers A/X/Y. No-op unless revealing.
vwf_tick:
    .a16
    .i16
    sep #$20
    .a8
    lda z:VWF_STATE
    cmp #1                      ; 1 = revealing
    bne @done
    lda z:VWF_IDX
    rep #$20
    .a16
    and #$00FF                  ; WIDTH-RISK: A8 load left C-high stale
    tay                         ; Y = reveal cursor
    lda z:VWF_PEN_X
    cmp #VWF_WINDOW_PX
    bcs @complete               ; window full
    sep #$20
    .a8
    lda [<VWF_STR], y           ; bank byte honoured: 24-bit indirect
    beq @complete               ; 0-terminated
    rep #$20
    .a16
    and #$00FF
    jsr vwf_put_glyph
    sep #$20
    .a8
    inc z:VWF_IDX
    rep #$20
    .a16
    rts
@complete:
    .i16
    sep #$20
    .a8
    lda #2                      ; 2 = complete; the row holds what it shows
    sta z:VWF_STATE
@done:
    .a8
    .i16
    rep #$20
    .a16
    rts
