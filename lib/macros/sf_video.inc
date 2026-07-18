; =============================================================================
; sf_video.inc — minimal OBJ display setup (macro library)
; =============================================================================
; The thin "make a sprite visible" layer: load a sprite tile into OBJ VRAM and
; set an OBJ palette colour. The byte-level sprite rungs (A1/A2) verify OAM
; bytes but render a transparent/placeholder tile; these two macros give the
; sprite real pixels so a screenshot shows it.
;
; Both write PPU memory (VRAM / CGRAM) that is only writable during forced
; blank or VBlank — call them in setup, AFTER sf_coldstart (which leaves the
; screen force-blanked) and BEFORE init_ppu turns the screen on.
;
; Requires: init_ppu's OBJ name base = VRAM word $0000 (OBSEL $2101=$00), so
; tile N lives at VRAM word N*16 (4bpp 8x8 = 16 words = 32 bytes).
; =============================================================================

.ifndef SF_VIDEO_INC
SF_VIDEO_INC = 1

; -----------------------------------------------------------------------------
; sf_obj_color palette, slot, color15 — set one colour in an OBJ palette.
; -----------------------------------------------------------------------------
;   palette  OBJ palette 0..7. A sprite selects its palette via `spr`'s flags
;            (flags bits 3:1 = palette, i.e. flags = palette << 1).
;   slot     colour slot 0..15 within that palette. Slot 0 is transparent —
;            use 1..15 for visible pixels.
;   color15  15-bit BGR colour (e.g. $001F red, $03E0 green, $7C00 blue).
; Computes the CGRAM address (128 + palette*16 + slot) for you — the caller
; names (palette, slot), so there is no raw-CGRAM-index footgun. CGRAM is
; writable during forced blank / VBlank — call in setup before init_ppu turns
; the screen on.
; WIDTH-RISK: enters A16/I16 (safe-by-default), uses A8 for the byte writes,
; exits A16.
.macro sf_obj_color sf_pal, sf_slot, sf_color
    sep #$20
    .a8
    lda #(128 + (sf_pal) * 16 + (sf_slot))
    sta $2121                  ; CGADD — CGRAM word address
    lda #<(sf_color)
    sta $2122                  ; CGDATA low byte
    lda #>(sf_color)
    sta $2122                  ; CGDATA high byte
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_load_obj_tile tile_index, src — upload one 4bpp 8x8 tile (32 bytes).
; -----------------------------------------------------------------------------
;   tile_index   OBJ tile number; destination VRAM word = tile_index*16.
;   src          ROM label of 32 bytes (16 words) in SNES 4bpp planar format.
; CPU-side word writes (32 bytes is well under one scanline, safe under forced
; blank with NMI off during setup).
; WIDTH-RISK: enters A16/I16, toggles A8 for VMAIN, exits A16/I16.
.macro sf_load_obj_tile sf_tile, sf_src
    .local up
    sep #$20
    .a8
    lda #$80
    sta $2115                  ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #((sf_tile) * 16)
    sta $2116                  ; VMADD — destination word address
    ldx #$0000
up:
    lda f:sf_src, x            ; next source word (bank from the label)
    sta $2118                  ; VMDATA word (low->$2118, high->$2119), VMADD++
    inx
    inx
    cpx #$0020                 ; 32 bytes = 16 words
    bne up
.endmacro

; -----------------------------------------------------------------------------
; sf_load_obj_chr base_tile, src, nbytes — upload a CHR blob to OBJ VRAM.
; -----------------------------------------------------------------------------
;   base_tile  OBJ tile index the blob starts at — MUST be a multiple of 16.
;              png2snes sprite blobs are laid out on the hardware's 16-tile
;              VRAM rows (a 16x16+ sprite reads its lower tile rows at +16
;              tile numbers); a non-aligned base would shear every frame.
;              Enforced at assembly time.
;   src        ROM label of the blob (e.g. png2snes's <name>_chr)
;   nbytes     blob size in bytes (e.g. <name>_chr_bytes); must be even
; CPU-side word writes — call in setup under forced blank, BEFORE init_ppu /
; gfxmode turn the screen on and BEFORE NMI is enabled ($4200). A frame's OAM
; tile is then base_tile + <name>_f<N>.
; Clobbers A, X.
; WIDTH-RISK: enters any width; toggles A8 for VMAIN, exits A16/I16.
.macro sf_load_obj_chr sf_tile, sf_src, sf_nbytes
    .local up
    .assert ((sf_tile) .mod 16) = 0, error, "sf_load_obj_chr: base_tile must be a multiple of 16 (OBJ VRAM-row alignment)"
    .assert ((sf_nbytes) .mod 2) = 0, error, "sf_load_obj_chr: nbytes must be even (VRAM is word-addressed)"
    sep #$20
    .a8
    lda #$80
    sta $2115                  ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #((sf_tile) * 16)
    sta $2116                  ; VMADD — destination word address
    ldx #$0000
up:
    lda f:sf_src, x
    sta $2118                  ; VMDATA word, VMADD++
    inx
    inx
    cpx #(sf_nbytes)
    bne up
.endmacro

; -----------------------------------------------------------------------------
; sf_load_obj_pal palette, src — upload one full 16-color OBJ palette.
; -----------------------------------------------------------------------------
;   palette  OBJ palette 0..7 (CGRAM 128 + palette*16). A sprite selects it
;            via `spr` flags bits 3:1 (flags = palette << 1).
;   src      ROM label of 16 .word BGR15 colors (png2snes's <name>_pal).
; Entry 0 is the transparent slot — uploaded but never rendered. Call in
; setup under forced blank (CGRAM port rule, same as sf_obj_color).
; Clobbers A, X.
; WIDTH-RISK: enters any width; A8 for the CGDATA byte writes with I16 for
; the index; exits A16/I16.
.macro sf_load_obj_pal sf_pal, sf_src
    .local cgup
    sep #$20
    .a8
    rep #$10
    .i16
    lda #(128 + (sf_pal) * 16)
    sta $2121                  ; CGADD — CGRAM word address
    ldx #$0000
cgup:
    lda f:sf_src, x
    sta $2122                  ; CGDATA (low byte then high byte, auto-pair)
    inx
    cpx #$0020                 ; 16 colors x 2 bytes
    bne cgup
    rep #$20
    .a16
.endmacro

.endif ; SF_VIDEO_INC
