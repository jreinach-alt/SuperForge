; =============================================================================
; sf_bg.inc — background (tilemap) macros (macro library)
; =============================================================================
; Tilemap backgrounds over the engine's BG engine. Each macro marshals its
; arguments into the API block and calls the engine fn directly (the macro is
; the wrapper — see sf_sprite.inc). The BG pipeline mirrors sprites: macros
; write shadow state (shadow tilemap / shadow scroll), the NMI handler commits
; scroll to the PPU and DMAs the dirty tilemap to VRAM every frame.
;
; Requires (linked into the ROM): engine/engine_state.inc + engine/bg_engine.asm
; (+ the NMI handler + dma_scheduler for the commit/DMA path). engine_api.inc
; supplies the API block SSoT.
;
; Setup ordering (by construction — the BG is undefined otherwise):
;   1. sf_coldstart            (forced blank; clears CGRAM/VRAM so no garbage)
;   2. sf_load_bg_tile / sf_bg_color   (VRAM/CGRAM uploads — MUST be under the
;                              forced blank, i.e. before init_ppu/gfxmode turn
;                              the screen on)
;   3. jsr init_ppu           (engine PPU defaults: OAMADD/OBSEL/screen-on — for
;                              sprites; harmless for BG-only)
;   4. gfxmode #1              (enables BG1, sets its VRAM addresses, ZEROS the
;                              shadow tilemap, turns the screen on)
;   5. mset ...                (build the tilemap — AFTER gfxmode, or it's wiped)
;   6. enable NMI; loop calling scroll
; (Literal layer/mode args take `#` — verbatim operands; bare `1` is a load.)
; BG1 lives at tilemap VRAM word $5800 (32x32), CHR base word $2000.
; =============================================================================

.ifndef SF_BG_INC
SF_BG_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; gfxmode mode — set the BG graphics mode and enable the BG layers.
; -----------------------------------------------------------------------------
; Mode 1 (the supported mode) enables BG1/BG2/BG3 + OBJ, points BG1 at tilemap
; word $5800 / CHR word $2000, zeros the BG1 shadow tilemap, and turns the
; screen on. Call it AFTER your BG tile/palette uploads and BEFORE any mset.
; Operand verbatim — write the mode as an immediate (`gfxmode #1`); bare `1` is
; a memory read. Clobbers A, X, Y.
;
; Also sets the engine's tilemap dimensions (TILEMAP_WIDTH/HEIGHT_BG1-3 = 32)
; to match the 32x32 tilemaps it creates. The engine's col_map bounds-checks
; against these; they live in WRAM, which the coldstart zeroes — without this,
; every col_map query would be "out of bounds" and return 0 (the parent
; engine leaves them to compiler boot code the kit doesn't have).
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_gfxmode runs its
; own widths and returns A16; the dim writes toggle A8 and exit A16.
.macro gfxmode sf_mode
    rep #$30
    .a16
    .i16
    lda sf_mode
    sta API_BLOCK_BASE + $00
    jsr engine_gfxmode
    sep #$20
    .a8
    lda #32
    sta TILEMAP_WIDTH_BG1
    sta TILEMAP_HEIGHT_BG1
    sta TILEMAP_WIDTH_BG2
    sta TILEMAP_HEIGHT_BG2
    sta TILEMAP_WIDTH_BG3
    sta TILEMAP_HEIGHT_BG3
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; scroll layer, x, y — set a BG layer's pixel scroll position.
; -----------------------------------------------------------------------------
; layer 1-3; x/y are 16-bit pixel offsets. Writes the shadow scroll; the NMI
; commits it to the PPU ($210D..) every frame, so calling this in the game loop
; scrolls the layer. Operands verbatim (write `#1` for the layer literal).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_scroll runs its
; own widths and returns A16.
.macro scroll sf_layer, sf_x, sf_y
    rep #$30
    .a16
    .i16
    lda sf_layer
    sta API_BLOCK_BASE + $00
    lda sf_x
    sta API_BLOCK_BASE + $04
    lda sf_y
    sta API_BLOCK_BASE + $08
    jsr engine_scroll
.endmacro

; -----------------------------------------------------------------------------
; mset layer, mx, my, tile — set one tilemap cell.
; -----------------------------------------------------------------------------
; layer 1-3; mx/my are tile coords 0-31; tile is the 16-bit tilemap word
; (CHR index | palette<<10 | priority<<13 | Hflip<<14 | Vflip<<15). NOTE:
; callers that pass RAW TILE IDS (sf_level_load does) get palette 0 — to
; color tiles differently within palette 0, use distinct CHR color INDICES
; per tile; palette bits require full tilemap words (png2snes bg emits
; them). Writes the
; shadow tilemap (the NMI DMAs the dirty map to VRAM next frame). Operands
; verbatim (write `#1` for the layer literal). Clobbers A, X, Y — if you call
; this in an index loop, keep your loop counter in memory/DP (not X/Y).
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_mset runs its own
; widths and returns A16 with I16 PRESERVED (callers like sf_level_load rely
; on 16-bit index math across mset calls).
.macro mset sf_layer, sf_mx, sf_my, sf_tile
    rep #$30
    .a16
    .i16
    lda sf_layer
    sta API_BLOCK_BASE + $00
    lda sf_mx
    sta API_BLOCK_BASE + $04
    lda sf_my
    sta API_BLOCK_BASE + $08
    lda sf_tile
    sta API_BLOCK_BASE + $0C
    jsr engine_mset
.endmacro

; -----------------------------------------------------------------------------
; sf_load_bg_tile tile_index, src — upload one 4bpp 8x8 BG tile (32 bytes).
; -----------------------------------------------------------------------------
; Destination VRAM word = BG1 CHR base ($2000) + tile_index*16. src is a ROM
; label of 32 bytes (16 words) in SNES 4bpp planar format. CPU word writes;
; call under forced blank (before gfxmode/init_ppu turn the screen on).
; Tile indices 0-79 only when using the text layer (sf_text.inc): the font
; occupies words $2500-$27FF = BG1 tile indices 80-127 (shared CHR base).
; WIDTH-RISK: enters A16/I16, toggles A8 for VMAIN, exits A16/I16.
.macro sf_load_bg_tile sf_tile, sf_src
    .local up
    sep #$20
    .a8
    lda #$80
    sta $2115                  ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #($2000 + (sf_tile) * 16)
    sta $2116                  ; VMADD — BG1 CHR base + tile*16
    ldx #$0000
up:
    lda f:sf_src, x
    sta $2118                  ; VMDATA word, VMADD++
    inx
    inx
    cpx #$0020                 ; 32 bytes
    bne up
.endmacro

; -----------------------------------------------------------------------------
; sf_bg_color palette, slot, color15 — set one colour in a BG palette.
; -----------------------------------------------------------------------------
; BG palettes occupy CGRAM 0..127: entry = palette*16 + slot (palette 0..7,
; slot 0..15; slot 0 is transparent). color15 is 15-bit BGR. Same as
; sf_obj_color but the BG palette region (no +128). Call under forced blank.
; WIDTH-RISK: enters A16/I16 (safe-by-default), uses A8 for the byte writes,
; exits A16.
.macro sf_bg_color sf_pal, sf_slot, sf_color
    sep #$20
    .a8
    lda #((sf_pal) * 16 + (sf_slot))
    sta $2121                  ; CGADD
    lda #<(sf_color)
    sta $2122                  ; CGDATA low
    lda #>(sf_color)
    sta $2122                  ; CGDATA high
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_load_bg_chr base_tile, src, nbytes — upload a CHR blob to BG1 CHR VRAM.
; -----------------------------------------------------------------------------
;   base_tile  BG tile index the blob starts at (VRAM word $2000 + base*16).
;              png2snes bg map words bake the base in — pass the SAME value
;              you gave --base-tile (default 0).
;   src        ROM label of the blob (png2snes's <name>_chr)
;   nbytes     blob size in bytes (<name>_chr_bytes); must be even
; Keep base_tile + tiles <= 80 when the ROM also uses sf_text — the font owns
; BG1 tiles 80-127 (shared CHR base, see sf_text.inc). CPU word writes; call
; under forced blank, before init_ppu/gfxmode and before NMI enable.
; Clobbers A, X.
; WIDTH-RISK: enters any width; toggles A8 for VMAIN, exits A16/I16.
.macro sf_load_bg_chr sf_tile, sf_src, sf_nbytes
    .local up
    .assert ((sf_nbytes) .mod 2) = 0, error, "sf_load_bg_chr: nbytes must be even (VRAM is word-addressed)"
    sep #$20
    .a8
    lda #$80
    sta $2115                  ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #($2000 + (sf_tile) * 16)
    sta $2116                  ; VMADD — BG1 CHR base + tile*16
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
; sf_load_bg_pals first_pal, src, count — upload `count` 16-color BG palettes.
; -----------------------------------------------------------------------------
;   first_pal  first BG palette 0..7 (CGRAM word first_pal*16)
;   src        ROM label of count*16 .word BGR15 colors (png2snes <name>_pal)
;   count      number of palettes (png2snes's <name>_pal_count, 1..8)
; png2snes bg map words carry each tile's palette bits already — upload the
; palettes at first_pal 0 (the converter numbers from 0) and pass map words
; straight to mset. Call under forced blank.
; Clobbers A, X.
; WIDTH-RISK: enters any width; A8 for the CGDATA byte writes with I16 for
; the index; exits A16/I16.
.macro sf_load_bg_pals sf_pal, sf_src, sf_count
    .local cgup
    .assert ((sf_pal) + (sf_count)) <= 8, error, "sf_load_bg_pals: palettes overrun the 8 BG palettes"
    sep #$20
    .a8
    rep #$10
    .i16
    lda #((sf_pal) * 16)
    sta $2121                  ; CGADD
    ldx #$0000
cgup:
    lda f:sf_src, x
    sta $2122                  ; CGDATA (low byte then high byte, auto-pair)
    inx
    cpx #((sf_count) * 32)
    bne cgup
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_autoscroll_v layer, counter, speed — one frame of vertical autoscroll.
; -----------------------------------------------------------------------------
;   layer    BG layer, verbatim (`#1`)
;   counter  DP/memory word holding the scroll position (the game owns it;
;            zero it in setup)
;   speed    pixels per frame, verbatim (`#1`); positive = the world drifts
;            DOWN the screen (the shmup "flying up" direction — VOFS
;            decreases, and the tilemap wraps, so any speed loops forever)
; Call once per frame in the game loop. The NMI commits the scroll. For the
; opposite direction (top-down "walking down"), ADD to the counter yourself
; and call scroll directly.
; Clobbers A, X, Y (scroll's engine call).
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16 (scroll's
; contract).
.macro sf_autoscroll_v sf_layer, sf_counter, sf_speed
    rep #$30
    .a16
    .i16
    lda sf_counter
    sec
    sbc sf_speed
    sta sf_counter
    scroll sf_layer, #0, sf_counter
.endmacro

.endif ; SF_BG_INC
