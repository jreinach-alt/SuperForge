; =============================================================================
; sf_dialog.inc — turnkey OPAQUE dialog panel (macro library)
; =============================================================================
; A drop-in dialog box for ANY kit template: open an opaque, bordered window on
; the text layer, print one or more lines into it, close it to restore the
; scene. Generalized from the RPG vertical slice's town dialog (S3) — the slice
; hard-coded a 26x6 bottom panel, town-specific VRAM addresses, and an NPC
; line-table; this macro takes position + size + a string and is tied to NO
; scene. Route every "show a message box" ask here — do NOT hand-roll a box out
; of text glyphs (the slice's original ASCII-box defect; an opaque box needs
; opaque CHR, which is what this provides).
;
; HOW IT COMPOSES (the kit BG3 text layer, reused — no new layer, no new NMI):
;   The kit's `print` (sf_text.inc) already renders to BG3 with the per-tile
;   PRIORITY bit, and the kit boot's BGMODE=$09 (Mode 1, BG3 high priority)
;   lifts priority-flagged BG3 above BG1/BG2/OBJ. This macro draws its OPAQUE
;   box into the SAME BG3 shadow tilemap (SHADOW_BG3_TILEMAP, $7E:B200) with the
;   same priority bit, so the box composites above the scene, and `print` text
;   composites above the box — all on BG3, all committed by the STOCK engine NMI
;   (which DMAs the dirty BG3 shadow to VRAM every VBlank). No custom VBlank
;   code, no direct VRAM writes from the open/close path.
;
; OPACITY CONTRACT (why a box, not glyphs): every panel cell is an opaque tile
; (idx>=1 of the panel palette) carrying the BG3 priority bit, so NO scene
; pixels show through inside the panel. Index 0 (the kit transparent BG3 cell)
; appears only outside the box. The box is a 3x3 nine-patch (corners/edges/fill)
; so any width>=2 x height>=2 frames correctly.
;
; REQUIRES (linked into the ROM):
;   - the kit text path: engine_state.inc + bg_engine.asm + text_engine.asm +
;     nmi_handler.asm + dma_scheduler.asm + sf_text.inc + sf_text_data.inc
;     (the box reuses the BG3 shadow + the stock NMI commit those provide), and
;   - sf_dialog_data.inc (the box CHR + draw/clear routines), included ONCE at
;     the BOTTOM of main.asm in CODE, after sf_text_data.inc.
;
; SETUP ORDERING (by construction):
;   1. sf_coldstart                 (forced blank; clears VRAM/CGRAM)
;   2. sf_text_init                 (kit font upload, under forced blank)
;   3. sf_dialog_init               (box CHR + panel palette upload — ALSO under
;                                    forced blank, before init_ppu/gfxmode turn
;                                    the screen on)
;   4. jsr init_ppu / gfxmode #1    (gfxmode ZEROS the BG3 shadow tilemap)
;   5. enable NMI
;   6. sf_dialog_open / print / sf_dialog_close   (mid-game-loop — safe; small
;      WRAM shadow writes, committed next VBlank)
;
; INPUT-EDGE GOTCHA (cite — kit docs/troubleshooting.md "btnp edge after
; transition"): a panel is normally opened on a button press and closed on the
; next press. Read the press EDGE (btnp / the pressed-latch), not the level, or
; the same held button that opened the panel closes it the very next frame. If
; the dialog open/close lives across a SCENE TRANSITION, the first post-swap
; frame's edge latch can be stale — gate the open on a fresh edge sampled AFTER
; the swap settles (R1's troubleshooting entry has the full pattern).
;
; POWER-ON GOTCHA (cite — CLAUDE.md "Power-On Fidelity"): the panel CHR/palette
; and the BG3 shadow region you draw into must be INITIALIZED before display.
; sf_dialog_init uploads the CHR + palette; gfxmode zeros the BG3 shadow at
; boot. Never assume the shadow is zero without gfxmode having run (step 4).
;
; PALETTE / COLOR: the box uses BG3 sub-palette SF_DLG_PALETTE (default 6); the
; kit font default palette is 7 (white), so box and text coexist (each tile
; word carries its own palette field). Override SF_DLG_PALETTE / SF_DLG_TILE_BASE
; BEFORE including sf_dialog_data.inc to relocate. Supply your own 4-color panel
; palette by uploading to CGRAM[SF_DLG_PALETTE*4..+3] after sf_dialog_init, or
; edit sf_dialog_default_pal.
;
; CLOBBER CONTRACT: all macros clobber A, X, Y + the dialog scratch
; ($7E:1DC0-$1DD3, transient — consumed within the call) + (for the box draw)
; BG_TILEMAP_DIRTY's BG3 bit. They expect DB=$00 (the kit standard). The
; scratch lives in the game-array region tail, ABOVE the audio tail $1DE0, and
; is NOT persistent panel state — track "is the panel open?" in your own
; game variable (a DP byte) if your input logic needs it (the slice used one).
; =============================================================================

.ifndef SF_DIALOG_INC
SF_DIALOG_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_dialog_init — upload the box CHR to BG3 VRAM + the default panel palette.
; -----------------------------------------------------------------------------
; Uploads the 9 nine-patch tiles (2bpp, 144 bytes) to BG3 CHR word
; $2000 + SF_DLG_TILE_BASE*8, and the 4-color default panel palette to
; CGRAM[SF_DLG_PALETTE*4]. Call under FORCED BLANK (after sf_coldstart /
; sf_text_init, before init_ppu/gfxmode turn the screen on) — these are CPU-side
; VRAM/CGRAM port writes and NMI is off during the kit boot window.
; Clobbers A, X, Y.
; WIDTH-RISK: enters any width; toggles A8 for VMAIN + the CGRAM byte writes,
; A16 for the VMADD/word streaming; exits A16/I16.
.macro sf_dialog_init
    .local up_chr, up_pal
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    ; BG3 CHR base = word $2000 (BG34NBA=$0A encodes base bits 0-2 = $2 ->
    ; $2<<12 = $2000; the kit font lands at $2500 = tile 160). The box tiles go
    ; at $2000 + tile_base*8 words (2bpp = 8 words/tile), clear of the font.
    lda #($2000 + (SF_DLG_TILE_BASE * 8))
    sta $2116                   ; VMADD
    ldx #$0000
up_chr:
    lda f:sf_dialog_chr, x      ; 16-bit word from the CHR table
    sta $2118                   ; VMDATA word, VMADD++
    inx
    inx
    cpx #SF_DLG_CHR_BYTES       ; 9 tiles x 16 bytes
    bcc up_chr
    ; ---- panel palette -> CGRAM[SF_DLG_PALETTE*4] (4 colors x 2 bytes) ----
    sep #$20
    .a8
    lda #(SF_DLG_PALETTE * 4)
    sta $2121                   ; CGADD
    rep #$30
    .a16
    .i16
    ldx #$0000
up_pal:
    lda f:sf_dialog_default_pal, x
    sep #$20
    .a8
    sta $2122                   ; low byte
    xba
    sta $2122                   ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #8                      ; 4 colors x 2 bytes
    bcc up_pal
.endmacro

; -----------------------------------------------------------------------------
; sf_dialog_open col, row, w, h — draw an opaque bordered panel on BG3.
; -----------------------------------------------------------------------------
;   col, row   top-left CELL coordinates on the 32x32 BG3 grid (verbatim 16-bit
;              operands — `#3`, `#21`). BG3 is not scrolled, so cell (c,r) maps
;              to screen pixel (c*8, r*8). On-screen: col 0..31, row 0..27.
;   w, h       panel size in CELLS (verbatim; w>=2, h>=2 — asserted). The frame
;              occupies the outer ring; the interior (w-2 x h-2 cells) is body
;              fill where text prints.
; Draws the nine-patch into the BG3 shadow + sets the BG3 dirty bit; the stock
; NMI commits it next VBlank. After this, `print str, #(col+1)*8, #(row+1)*8`
; renders text inset inside the frame (or use sf_dialog_open_text). The opened
; geometry is remembered so sf_dialog_close needs no arguments. Clobbers A, X, Y
; + the dialog scratch.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); _sf_dialog_draw_box runs
; its own widths (A8 only for the dirty byte) and returns A16/I16.
.macro sf_dialog_open sf_col, sf_row, sf_w, sf_h
    rep #$30
    .a16
    .i16
    lda sf_col
    sta a:_sf_dlg_col0
    lda sf_row
    sta a:_sf_dlg_row0
    lda sf_w
    sta a:_sf_dlg_w
    dec a
    sta a:_sf_dlg_wm1           ; width-1
    lda sf_h
    sta a:_sf_dlg_h
    dec a
    sta a:_sf_dlg_hm1           ; height-1
    jsr _sf_dialog_draw_box
.endmacro

; -----------------------------------------------------------------------------
; sf_dialog_open_text col, row, w, h, str — box + one centered-inset text line.
; -----------------------------------------------------------------------------
; Convenience: draws the panel (sf_dialog_open) then prints `str` (a bare ROM
; label of NUL-terminated ASCII, like the kit `print`) inset 1 cell from the
; top-left frame, in the kit's default white text palette. For multi-line or
; custom placement, call sf_dialog_open then `print` yourself. Clobbers A, X, Y
; + the dialog scratch + DP $A0-$A2 (engine text scratch).
; WIDTH-RISK: asserts A16/I16 entry; both sub-macros return A16/I16.
.macro sf_dialog_open_text sf_col, sf_row, sf_w, sf_h, sf_str
    sf_dialog_open sf_col, sf_row, sf_w, sf_h
    ; text inset 1 cell from the top-left frame; cell->pixel = cell*8.
    print sf_str, #(((sf_col) + 1) * 8), #(((sf_row) + 1) * 8)
.endmacro

; -----------------------------------------------------------------------------
; sf_dialog_close — hide the last-opened panel; restore the scene there.
; -----------------------------------------------------------------------------
; Clears the panel region of the BG3 shadow back to the kit transparent blank
; (tile 0), using the geometry remembered by the last sf_dialog_open, and sets
; the BG3 dirty bit so the NMI commits it. The scene behind the panel is fully
; restored at that region. Any text you `print`ed inside the panel is part of
; that region and is cleared with it. Clobbers A, X, Y + the dialog scratch.
; WIDTH-RISK: asserts A16/I16 entry; _sf_dialog_clear_box returns A16/I16.
.macro sf_dialog_close
    rep #$30
    .a16
    .i16
    jsr _sf_dialog_clear_box
.endmacro

.endif ; SF_DIALOG_INC
