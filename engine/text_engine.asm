; =============================================================================
; text_engine.asm — Text Renderer (print, font tile init)
; =============================================================================
; Renders null-terminated ASCII strings to shadow BG tilemaps using pre-loaded
; font tiles. Characters 0x20 (space) through 0x7F (DEL) are supported.
;
; Provides two engine functions:
;   engine_print      — ID 20: print(str_ptr, x, y, color, layer)
;   engine_print_init — Initialize font base tile and loaded flag
;
; Font system:
;   96 tiles for printable ASCII (0x20-0x7F), 2bpp format, 16 bytes/tile.
;   VRAM location: $C800 in Mode 1 partition.
;   BG3 character base at $A000 (from BG34NBA=$0A).
;   Default font_base_tile = ($C800 - $A000) / 16 = 160.
;
; API parameter block (DP-relative at $60):
;   engine_print: +0=str_ptr(4B), +4=x(4B), +8=y(4B), +12=color(4B), +16=layer(4B)
;
; Shadow tilemaps (WRAM bank $7E, accessed via DB=$7E):
;   SHADOW_BG1_TILEMAP ($A200): 2048 bytes (32x32 x 2 bytes)
;   SHADOW_BG2_TILEMAP ($AA00): 2048 bytes
;   SHADOW_BG3_TILEMAP ($B200): 2048 bytes
;
; Prerequisites: engine_state.inc included, .p816/.smart set by parent.
; Do NOT add .p816/.smart — this file is included into a parent.
; Cross-ref: engine_state.inc, bg_engine.asm
; =============================================================================

; API parameter addresses (DP-relative)
; ENGINE_A0 = $40, API_BLOCK_BASE = $60 (defined elsewhere or here as fallback)
.ifndef ENGINE_A0
ENGINE_A0       = $40
.endif
.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif

; Text engine scratch (WRAM, after BG engine scratch $0576-$0579)
TEXT_SCRATCH_TX     = $057A     ; 2 bytes: current tile X position
TEXT_SCRATCH_TY     = $057C     ; 2 bytes: current tile Y position
TEXT_SCRATCH_BASE   = $057E     ; 2 bytes: shadow tilemap base address
TEXT_SCRATCH_COLOR  = $0580     ; 2 bytes: color << 10 (precomputed palette bits)
TEXT_SCRATCH_STRPTR = $0582     ; 2 bytes: current string pointer (low 16 bits)
TEXT_SCRATCH_STRBNK = $0584     ; 1 byte:  current string pointer bank byte
                                ;          (Phase 16-8 step 3 fix: was hardcoded
                                ;           bank $00 in the f:$000000,x reads
                                ;           below; broke when RODATA spilled
                                ;           into bank $02 under the 128 KB cfg)

; DP scratch slot for the indirect-long pointer used by the main string-read
; loop. Main thread runs with DP=$0000, so `[$A0]` reads a 24-bit pointer at
; $00:00A0..$00:00A2. The $A0-$AF range is the engine-scratch region in
; the main-thread DP layout (see CLAUDE.md "Memory Map" — Direct Page row).
; Aliasing with the NMI-DP-relative ES_HDMA_CH2_BBAD=$A0 is benign: main
; thread runs with DP=$0000, NMI handler runs with DP=$0100, the two never
; touch the same physical address through the same DP register simultaneously.
;
; SSoT: the formal cross-reference is ES_TEXT_SCRATCH_LONGPTR in
; engine/engine_state.inc (see "Main-thread transient scratch zone"). This
; local alias preserves the existing symbol name used throughout the file
; while keeping the canonical declaration in engine_state.inc for the
; zp_lint linter.
TEXT_SCRATCH_LONGPTR = ES_TEXT_SCRATCH_LONGPTR  ; $A0 — see engine_state.inc


; =============================================================================
; engine_print_init — Initialize font system defaults
; =============================================================================
; Sets FONT_BASE_TILE to 160 (font at VRAM $C800, BG3 char base at $A000).
; Sets FONT_LOADED = 1, VWF_ACTIVE = 0.
;
; Call once during initialization, before any engine_print calls.
;
; Clobbers: A. Expects 16-bit A on entry, returns in 16-bit A mode.
; =============================================================================
engine_print_init:
    rep #$20
    .a16
    lda #160                    ; ($C800 - $A000) / 16 = 160
    sta FONT_BASE_TILE
    sep #$20
    .a8
    lda #$01
    sta FONT_LOADED
    stz VWF_ACTIVE              ; default to monospace
    stz VWF_DIRTY               ; no pending VWF DMA
    rep #$20
    .a16
    rts


; =============================================================================
; engine_font_select — Select active font by ID
; =============================================================================
; Engine function ID 68: font(id)
;
; Reads font manifest table in WRAM ($7E:0F10), validates font ID,
; updates FONT_BASE_TILE and VWF_ACTIVE based on selected font's metadata.
;
; Input: API_BLOCK_BASE+0 = font_id (0-3)
; Output: Updates FONT_BASE_TILE, VWF_ACTIVE, font WRAM metadata
; Clobbers: A, X. Expects 16-bit AXY on entry.
; =============================================================================
engine_font_select:
    rep #$30
    .a16
    .i16

    ; Read font ID from API block, clamp to 0-3
    lda API_BLOCK_BASE + 0      ; font_id
    and #$0003                  ; clamp to valid range

    ; Store active font ID
    sta WFT_ACTIVE_FONT_ID

    ; Compute manifest table offset: id * 12
    ; id * 12 = id * 8 + id * 4
    asl
    asl                         ; A = id * 4
    tax                         ; X = id * 4
    asl                         ; A = id * 8
    stx $00                     ; temp = id * 4
    clc
    adc $00                     ; A = id * 8 + id * 4 = id * 12
    tax                         ; X = manifest entry offset

    ; Read base_tile from manifest entry (offset +2)
    ; Font manifest is in WRAM $0F10+, accessible via absolute addressing (DB=$00)
    lda FONT_MANIFEST_BASE + FM_BASE_TILE, x
    sta FONT_BASE_TILE
    sta WFT_ACTIVE_BASE_TILE

    ; Read flags byte and set VWF_ACTIVE (offset +1)
    sep #$20
    .a8
    lda FONT_MANIFEST_BASE + FM_FLAGS, x
    and #$01                    ; bit 0 = has_width_table
    sta VWF_ACTIVE

    ; If VWF font, load width table pointer into WRAM control block
    beq @font_select_done

    ; Store width table ROM pointer
    rep #$20
    .a16
    lda FONT_MANIFEST_BASE + FM_WIDTH_TBL_ADDR, x
    sta WFT_WIDTH_TABLE_LO
    sep #$20
    .a8
    lda FONT_MANIFEST_BASE + FM_WIDTH_TBL_BANK, x
    sta WFT_WIDTH_TABLE_BK

    ; Reset VWF cursor for next print call.
    ; Phase 16-8 step 3 VWF infrastructure (2026-05-09): WFT_VWF_CURSOR_X
    ; was reclaimed (dead — engine_print_vwf uses local VWF_SCRATCH_PIXEL_X
    ; instead). Only the live tile counter is reset here. See audit BUG-7.
    rep #$20
    .a16
    stz WFT_VWF_TILE_COUNT

@font_select_done:
    rep #$20
    .a16
    rts


; =============================================================================
; engine_print — Render string to shadow BG tilemap
; =============================================================================
; Parameters (API block, 32-bit each, low 16 used):
;   API_BLOCK_BASE + 0  = str_ptr (WRAM/ROM address in bank $00, low 16 bits)
;   API_BLOCK_BASE + 4  = x (pixel coordinate)
;   API_BLOCK_BASE + 8  = y (pixel coordinate)
;   API_BLOCK_BASE + 12 = color (palette index 0-7)
;   API_BLOCK_BASE + 16 = layer (1-3, default 3 for BG3 text overlay)
;
; Algorithm:
;   tx = x >> 3 (pixel to tile column)
;   ty = y >> 3 (pixel to tile row)
;   For each char in string until null:
;     if char < $20 or char > $7F: skip
;     tile_index = FONT_BASE_TILE + (char - $20)
;     tile_word = tile_index | (color << 10)
;     shadow_addr = tilemap_base + (ty * 64) + (tx * 2)
;     write tile_word at shadow_addr (DB=$7E)
;     tx += 1; if tx >= 32: break
;   Mark layer dirty in BG_TILEMAP_DIRTY.
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_print:
    rep #$30
    .a16
    .i16

    ; --- Check VWF mode (D13: auto-dispatch) ---
    sep #$20
    .a8
    lda VWF_ACTIVE              ; 0=monospace, 1=VWF
    rep #$20
    .a16
    beq @mono_path              ; skip VWF dispatch if monospace
    jmp engine_print_vwf        ; branch to VWF path
@mono_path:

    ; --- Convert pixel coords to tile coords ---
    lda API_BLOCK_BASE + 4      ; x (pixels)
    lsr
    lsr
    lsr                         ; x >> 3 = tile X
    sta TEXT_SCRATCH_TX

    lda API_BLOCK_BASE + 8      ; y (pixels)
    lsr
    lsr
    lsr                         ; y >> 3 = tile Y
    sta TEXT_SCRATCH_TY

    ; --- Precompute color bits (palette << 10) ---
    lda API_BLOCK_BASE + 12     ; color (0-7)
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; color << 10
    sta TEXT_SCRATCH_COLOR

    ; --- Determine shadow tilemap base from layer ---
    lda API_BLOCK_BASE + 16     ; layer (1-3)
    jsr _txt_get_tilemap_base
    sta TEXT_SCRATCH_BASE

    ; --- Save string pointer (low 16 bits + bank byte) ---
    ; Phase 16-8 step 3 fix: with the 128 KB linker cfg, RODATA lives in
    ; bank $02; the previous `lda f:$000000,x` hardcoded bank $00 and
    ; silently fetched garbage. We now read the bank from the API block
    ; high half (caller emits ^_str_X into +2) AND fall back to a
    ; build-emitted `_string_pool_bank` byte if +2 is zero (legacy
    ; call sites that haven't been recompiled).
    lda API_BLOCK_BASE + 0      ; str_ptr (low 16 bits)
    sta TEXT_SCRATCH_STRPTR
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2      ; str_ptr bank byte (caller-supplied)
    bne @print_have_bank
    lda f:_string_pool_bank     ; fallback: build-emitted pool bank
@print_have_bank:
    sta TEXT_SCRATCH_STRBNK
    rep #$20
    .a16

    ; --- Set DB=$7E for WRAM access to shadow tilemaps ---
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; --- Set up DP scratch indirect-long pointer for string reads ---
    ; [TEXT_SCRATCH_LONGPTR] is $A0-$A2 in main-thread DP. Bank byte stays
    ; constant for the whole string; only the low 16 bits advance.
    lda TEXT_SCRATCH_STRPTR
    sta <TEXT_SCRATCH_LONGPTR
    sep #$20
    .a8
    lda TEXT_SCRATCH_STRBNK
    sta <TEXT_SCRATCH_LONGPTR + 2
    rep #$20
    .a16

    ; --- Main character loop ---
@print_loop:
    ; Read next character from string via indirect long.
    ; The pointer's low word advances each iteration; bank stays put.
    sep #$20
    .a8
    lda [<TEXT_SCRATCH_LONGPTR] ; read byte from any bank (24-bit ptr)
    rep #$20
    .a16
    and #$00FF                  ; zero-extend to 16-bit

    ; Check for null terminator
    beq @print_done

    ; Advance string pointer for next iteration. Both the WRAM scratch
    ; (kept consistent with prior tests that read it) and the DP pointer
    ; used by [DP] indirect long need to step in lock-step.
    ldx TEXT_SCRATCH_STRPTR
    inx
    stx TEXT_SCRATCH_STRPTR
    stx <TEXT_SCRATCH_LONGPTR   ; bank byte at <TEXT_SCRATCH_LONGPTR+2 unchanged

    ; Check character range: must be $20-$7F
    cmp #$0020
    bcc @print_loop             ; char < $20: skip
    cmp #$0080
    bcs @print_loop             ; char >= $80: skip

    ; --- Compute tile index = FONT_BASE_TILE + (char - $20) ---
    sec
    sbc #$0020                  ; A = char - $20
    clc
    adc FONT_BASE_TILE          ; A = FONT_BASE_TILE + (char - $20)

    ; --- Combine with palette bits ---
    ora TEXT_SCRATCH_COLOR       ; A = tile_index | (color << 10)
    tay                         ; Y = tile word to write

    ; --- Compute tilemap address = base + (ty * 64) + (tx * 2) ---
    lda TEXT_SCRATCH_TY
    asl
    asl
    asl
    asl
    asl
    asl                         ; A = ty * 64
    clc
    adc TEXT_SCRATCH_BASE        ; A = tilemap_base + ty*64
    pha                         ; save partial address on stack
    lda TEXT_SCRATCH_TX
    asl                         ; A = tx * 2
    clc
    adc $01,S                   ; A = tilemap_base + ty*64 + tx*2
    plx                         ; clean stack (discard saved value)
    tax                         ; X = absolute WRAM address within bank $7E

    ; --- Store tile word at shadow tilemap ---
    tya                         ; A = tile word
    sta a:$0000,x               ; write to WRAM (DB=$7E, so effective addr = $7E:xxxx)

    ; --- Advance tile X, check bounds ---
    ldx TEXT_SCRATCH_TX
    inx
    stx TEXT_SCRATCH_TX
    cpx #$0020                  ; tx >= 32?
    bcc @print_loop             ; no: continue
    ; fall through to done if we hit the edge

@print_done:
    plb                         ; restore DB

    ; --- Mark layer dirty in BG_TILEMAP_DIRTY ---
    lda API_BLOCK_BASE + 16     ; layer (1-3)
    dec                         ; 0-based index
    tax
    sep #$20
    .a8
    lda f:_txt_dirty_bits,x     ; look up dirty bit mask
    ora BG_TILEMAP_DIRTY        ; combine with existing dirty flags
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16

    rts


; =============================================================================
; _txt_get_tilemap_base — Get shadow tilemap base address for a layer
; =============================================================================
; Input:  A = layer number (1-3)
; Output: A = WRAM base address ($A200, $AA00, or $B200)
; Clobbers: X
; =============================================================================
_txt_get_tilemap_base:
    dec                         ; convert 1-based to 0-based (0-2)
    asl                         ; word index
    tax
    lda f:_txt_tilemap_bases,x
    rts

; Lookup table: tilemap base addresses per layer
_txt_tilemap_bases:
    .word SHADOW_BG1_TILEMAP    ; layer 1 -> $A200
    .word SHADOW_BG2_TILEMAP    ; layer 2 -> $AA00
    .word SHADOW_BG3_TILEMAP    ; layer 3 -> $B200

; Lookup table: dirty bit masks per layer (0-indexed)
_txt_dirty_bits:
    .byte $01                   ; layer 1 -> bit 0
    .byte $02                   ; layer 2 -> bit 1
    .byte $04                   ; layer 3 -> bit 2


; =============================================================================
; engine_print_vwf — Variable-Width Font Renderer
; =============================================================================
; Renders proportional text by bit-shifting glyph bitmaps into a WRAM tile
; buffer, which is then DMA'd to VRAM during the next VBlank.
;
; Called from engine_print when VWF_ACTIVE == 1 (D13 auto-dispatch).
;
; Parameters (same as engine_print, via API block):
;   API_BLOCK_BASE + 0  = str_ptr (WRAM/ROM address, bank $00)
;   API_BLOCK_BASE + 4  = x (pixel coordinate)
;   API_BLOCK_BASE + 8  = y (pixel coordinate)
;   API_BLOCK_BASE + 12 = color (palette index 0-7)
;   API_BLOCK_BASE + 16 = layer (1-3)
;
; Algorithm:
;   For each character, reads glyph width from width table, bit-shifts the
;   glyph's 2bpp tile data into the VWF WRAM buffer at the current pixel
;   offset, then writes VWF tile indices to the shadow tilemap.
;
; VWF scratch (WRAM scratch area $0520-$0527, safe when DB=$00 or DB=$7E).
;
; Phase 16-8 step 3 dismiss-teleport bug fix (2026-05-09): RELOCATED from
; $0588-$058F. The original allocation aliased ALL of TILEMAP_WIDTH_BG1
; ($0588), TILEMAP_WIDTH_BG2 ($0589), TILEMAP_WIDTH_BG3 ($058A),
; TILEMAP_HEIGHT_BG1 ($058B), TILEMAP_HEIGHT_BG2 ($058C), and
; TILEMAP_HEIGHT_BG3 ($058D). Every VWF render call corrupted these
; live engine-state globals — the symptom that surfaced was the platformer
; dialog dismiss leaving the player teleporting into the sky on the next
; frame's collision check (col_map computed byte offsets against the
; corrupted TILEMAP_WIDTH_BG1, missed the platform tile, and let the player
; fall). $0520-$053F is a 32-byte unaliased scratch hole — verified by
; grep against engine_state.inc + every .asm file in engine/ and
; every engine source. See the parent notes "Phase 16-8 step 3 dismiss-
; teleport bug" for the full mechanism + why earlier sprints' partial
; relocations of TEXT_SCRATCH_NLEFT and VWF_DIRTY missed this collision.
VWF_SCRATCH_PIXEL_X  = $0520    ; 2 bytes: current pixel X offset within buffer
VWF_SCRATCH_BUF_START = $0522   ; 2 bytes: WRAM addr of first tile in buffer
VWF_SCRATCH_TILE_START = $0524  ; 2 bytes: starting tile index in VWF buffer
VWF_SCRATCH_TILES_USED = $0526  ; 2 bytes: tiles used by this print call
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_print_vwf:
    rep #$30
    .a16
    .i16

    ; --- Phase 16-8 step 3 VWF infrastructure (2026-05-09) ---
    ; The body below is now SHARED with engine_print_chars_vwf via the
    ; TEXT_SCRATCH_NLEFT counter. engine_print_vwf is the unbounded entry
    ; (sets NLEFT to $FFFF — effectively never exhausts), and
    ; engine_print_chars_vwf is the bounded entry (sets NLEFT to the
    ; user's `n` cap before jumping here).
    lda #$FFFF
    sta TEXT_SCRATCH_NLEFT      ; unbounded — render every char until null

_vwf_shared_body_entry:
    ; --- Get current buffer cursor (tiles rendered this frame) ---
    lda WFT_VWF_TILE_COUNT
    sta VWF_SCRATCH_TILE_START

    ; Check buffer overflow (24 tiles max)
    cmp #VWF_MAX_TILES
    bcc @vwf_ok
    rts                         ; buffer full, silently drop
@vwf_ok:

    ; Compute WRAM buffer start address: VWF_TILE_BUFFER + tile_start * 16
    asl
    asl
    asl
    asl                         ; A = tile_start * 16
    clc
    adc #VWF_TILE_BUFFER
    sta VWF_SCRATCH_BUF_START

    ; --- Convert pixel coords to tile coords for tilemap ---
    lda API_BLOCK_BASE + 4      ; x (pixels)
    lsr
    lsr
    lsr                         ; x >> 3 = tile X
    sta TEXT_SCRATCH_TX

    lda API_BLOCK_BASE + 8      ; y (pixels)
    lsr
    lsr
    lsr                         ; y >> 3 = tile Y
    sta TEXT_SCRATCH_TY

    ; --- Precompute color bits ---
    lda API_BLOCK_BASE + 12     ; color (0-7)
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; color << 10
    sta TEXT_SCRATCH_COLOR

    ; --- Determine shadow tilemap base from layer ---
    lda API_BLOCK_BASE + 16
    jsr _txt_get_tilemap_base
    sta TEXT_SCRATCH_BASE

    ; --- Save string pointer (low 16 + bank) ---
    ; Phase 16-8 step 3 fix: same multi-bank string-pool support as the
    ; mono path above. See the comment block at engine_print's @print_loop.
    lda API_BLOCK_BASE + 0
    sta TEXT_SCRATCH_STRPTR
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2      ; bank byte from caller
    bne @vwf_have_bank
    lda f:_string_pool_bank     ; fallback: build-emitted pool bank
@vwf_have_bank:
    sta TEXT_SCRATCH_STRBNK
    rep #$20
    .a16

    ; --- Initialize counters ---
    stz VWF_SCRATCH_PIXEL_X
    stz VWF_SCRATCH_TILES_USED

    ; --- Set up 24-bit width table pointer at DP $00-$02 ---
    lda WFT_WIDTH_TABLE_LO
    sta $00
    sep #$20
    .a8
    lda WFT_WIDTH_TABLE_BK
    sta $02
    rep #$20
    .a16

    ; --- Set up 24-bit tile data pointer at DP $03-$05 ---
    ; Read from manifest for active font.
    ;
    ; Phase 16-8 step 3 VWF infrastructure (2026-05-09): the original
    ; multiply-by-12 had dead `sta $07` in A16 mode that wrote 16-bit
    ; A across $07-$08, corrupting $08 (which the source-pointer setup
    ; needed clean before the per-char loop reset it). Worse, the next
    ; `lda $06` then re-read $06-$07 as 16-bit, picking up the corrupted
    ; high byte from $07, and the resulting X was way off (id=1 → X=$300C
    ; instead of 12). Manifest reads landed on garbage, the source
    ; pointer pointed somewhere random, and the bitmap merge silently
    ; landed in WRAM unrelated to VWF_TILE_BUFFER. All TILE_COUNT /
    ; tilemap-entry / VWF_DIRTY accounting still completed because they
    ; don't depend on the source data — that's why the dialog tests
    ; (which only assert on those side effects) passed despite the
    ; pipeline being completely broken at the bitmap-data level.
    ;
    ; The fix below mirrors the engine_print_chars_vwf clone (added by
    ; commit 7933c95) which uses the correct id*3 + asl-twice pattern.
    lda WFT_ACTIVE_FONT_ID
    and #$0003
    sta $06                     ; $06-$07 = id (16-bit; $07 = 0)
    lda $06                     ; A = id
    asl                         ; A = id*2
    clc
    adc $06                     ; A = id*3
    asl                         ; A = id*6
    asl                         ; A = id*12
    tax
    lda FONT_MANIFEST_BASE + FM_TILE_DATA_ADDR, x
    sta $03
    sep #$20
    .a8
    lda FONT_MANIFEST_BASE + FM_TILE_DATA_BANK, x
    sta $05
    rep #$20
    .a16

    ; --- Set up DP scratch indirect-long string pointer ---
    ; Same DP slot as the mono path. The width-table pointer at $00 and the
    ; tile-data pointer at $03 are independent. Phase 16-8 step 3 fix: gets
    ; the bank byte from API_BLOCK_BASE+2 (caller-supplied) or
    ; _string_pool_bank (build-emitted), so RODATA in bank $02+ works.
    lda TEXT_SCRATCH_STRPTR
    sta <TEXT_SCRATCH_LONGPTR
    sep #$20
    .a8
    lda TEXT_SCRATCH_STRBNK
    sta <TEXT_SCRATCH_LONGPTR + 2
    rep #$20
    .a16

    ; --- Clear VWF buffer for this call (DB=$7E needed for $CD00+) ---
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ldx VWF_SCRATCH_BUF_START
    lda #VWF_MAX_TILES
    sec
    sbc VWF_SCRATCH_TILE_START
    asl
    asl
    asl
    asl                         ; bytes to clear = tiles * 16
    tay
@vwf_clr:
    dey
    dey
    bmi @vwf_clr_end
    lda #$0000
    sta a:$0000,x
    inx
    inx
    bra @vwf_clr
@vwf_clr_end:

    ; --- Main character loop (DB=$7E) ---
@vwf_loop:
    sep #$20
    .a8
    lda [<TEXT_SCRATCH_LONGPTR] ; read char from string pool (any bank)
    rep #$20
    .a16
    and #$00FF
    bne @vwf_not_null           ; skip if not null terminator
    jmp @vwf_done
@vwf_not_null:

    ; Advance pointer (both WRAM scratch and DP indirect-long scratch).
    ldx TEXT_SCRATCH_STRPTR
    inx
    stx TEXT_SCRATCH_STRPTR
    stx <TEXT_SCRATCH_LONGPTR

    ; Range check
    cmp #$0020
    bcc @vwf_loop
    cmp #$0080
    bcs @vwf_loop

    ; Compute glyph index
    sec
    sbc #$0020                  ; glyph_index (0-95)
    tay                         ; Y = glyph_index

    ; Read width from width table via indirect long: lda [$00],y
    sep #$20
    .a8
    lda [$00],y                 ; width byte (DP $00-$02 = 24-bit ptr)
    sta $06                     ; $06 = glyph width
    rep #$20
    .a16
    lda $06
    and #$00FF
    sta $06                     ; $06 = glyph width (16-bit)

    ; --- Compute source tile data address ---
    ; src = tile_data_base + glyph_index * 16
    ; Y still = glyph_index
    tya
    asl
    asl
    asl
    asl                         ; A = glyph_index * 16
    clc
    adc $03                     ; + tile_data_addr_lo
    sta $08                     ; $08-$09 = source addr lo
    sep #$20
    .a8
    lda $05                     ; tile_data bank
    sta $0A                     ; $0A = source bank
    rep #$20
    .a16

    ; --- Bit offset and destination tile ---
    lda VWF_SCRATCH_PIXEL_X
    and #$0007
    sta $0B                     ; $0B = bit_offset (0-7)

    lda VWF_SCRATCH_PIXEL_X
    lsr
    lsr
    lsr                         ; dst_tile_rel = pixel_x >> 3
    asl
    asl
    asl
    asl                         ; * 16 = byte offset
    clc
    adc VWF_SCRATCH_BUF_START
    sta $0D                     ; $0D = dest WRAM addr for current tile

    ; --- Process 8 rows (2bpp: 2 bytes per row = 16 bytes) ---
    ldy #$0000                  ; Y = row byte offset (0,2,4,...14)
@vwf_row:
    cpy #$0010
    bcc @vwf_row_cont
    jmp @vwf_row_end
@vwf_row_cont:

    ; Read source bitplanes
    sep #$20
    .a8
    lda [$08],y                 ; bp0 from ROM (indirect long)
    sta $10
    phy
    iny
    lda [$08],y                 ; bp1
    sta $11
    ply

    ; Shift right by bit_offset
    ldx $0B                     ; bit_offset (widened to 16-bit but only low byte used)
    beq @vwf_noshft

    ; bp_lo = bp_src >> offset, bp_hi = bp_src << (8 - offset)
    lda $10
    sta $12                     ; bp0_lo = bp0_src
    lda $11
    sta $14                     ; bp1_lo = bp1_src
    lda $10
    sta $13                     ; bp0_hi = bp0_src (will shift left)
    lda $11
    sta $15                     ; bp1_hi = bp1_src

    ; Shift lo bytes right
@vwf_shr:
    lsr $12
    lsr $14
    dex
    bne @vwf_shr

    ; Shift hi bytes left by (8 - bit_offset)
    ; FIX-FROM-LINT-FINDING (width_lint cleanup pass): the address build
    ; at line 565..575 leaves A-high = $CD (high byte of VWF_SCRATCH_BUF_START
    ; = $CD00 + tile_offset; survives sep #$20 since sep preserves B). The
    ; following tax in A8/I16 transfers B|A to X, so without an explicit
    ; A-high clear the loop counter would be $CDxx and `dex / bne @vwf_shl`
    ; would iterate ~52,000 times instead of 1..7. The bug never manifested
    ; in CI because no test ROM exercises engine_print_vwf with bit_offset
    ; > 0 (test_font_select only checks the VWF_ACTIVE flag, not actual
    ; VWF rendering with multi-char proportional output).
    lda #8
    sec
    sbc $0B                     ; A-low = (8 - bit_offset) = 1..7; A-high stale
    rep #$20
    .a16
    and #$00FF                  ; clear stale A-high; X-high must be 0 for dex
    sep #$20
    .a8
    ; WIDTH-RISK: A8/I16 tax — A-high cleared above; X = (8 - bit_offset).
    tax
@vwf_shl:
    asl $13
    asl $15
    dex
    bne @vwf_shl
    bra @vwf_merge

@vwf_noshft:
    lda $10
    sta $12                     ; bp0_lo = bp0_src
    lda $11
    sta $14                     ; bp1_lo = bp1_src
    stz $13                     ; bp0_hi = 0
    stz $15                     ; bp1_hi = 0

@vwf_merge:
    ; OR lo bytes into current dest tile
    rep #$20
    .a16
    lda $0D                     ; dest WRAM addr
    clc
    adc $01,s                   ; + row offset Y (on stack from earlier? no, Y is still in Y)
    ; Actually, we need row byte offset. Y is still the row offset.
    phy                         ; save Y for use
    tya                         ; A = row byte offset
    clc
    adc $0D                     ; + dest tile base
    tax                         ; X = dest addr + row_offset
    sep #$20
    .a8

    lda $12
    ora a:$0000,x
    sta a:$0000,x               ; bp0_lo into current tile
    lda $14
    ora a:$0001,x
    sta a:$0001,x               ; bp1_lo

    ; Overflow to next tile if bit_offset > 0
    lda $0B                     ; bit_offset
    beq @vwf_noovf
    rep #$20
    .a16
    txa
    clc
    adc #16                     ; next tile
    tax
    ; Bounds check
    cpx #VWF_TILE_BUFFER + VWF_TILE_BUFFER_SIZE
    bcs @vwf_noovf_16
    sep #$20
    .a8
    lda $13
    ora a:$0000,x
    sta a:$0000,x
    lda $15
    ora a:$0001,x
    sta a:$0001,x
    bra @vwf_noovf
@vwf_noovf_16:
    sep #$20
    .a8
@vwf_noovf:
    rep #$20
    .a16
    ply                         ; restore row offset
    iny
    iny
    jmp @vwf_row

@vwf_row_end:
    ; --- Advance cursor by glyph width ---
    lda VWF_SCRATCH_PIXEL_X
    clc
    adc $06                     ; + glyph width
    sta VWF_SCRATCH_PIXEL_X

    ; Update tiles used: (pixel_x + 7) / 8
    clc
    adc #7
    lsr
    lsr
    lsr
    sta VWF_SCRATCH_TILES_USED

    ; --- N-cap (Phase 16-8 step 3 VWF infrastructure refactor) ---
    ; Decrement remaining-char counter and exit when zero. The unbounded
    ; entry (engine_print_vwf) initializes NLEFT to $FFFF so this never
    ; reaches 0 except via underflow at $FFFF iterations — and the null
    ; terminator in the source string will exit far earlier in practice.
    ; The bounded entry (engine_print_chars_vwf) initializes NLEFT to the
    ; caller's `n` cap so the loop bails after exactly that many printable
    ; chars. Non-printable bytes are skipped earlier in the loop without
    ; consuming the budget.
    ldx TEXT_SCRATCH_NLEFT
    dex
    stx TEXT_SCRATCH_NLEFT
    beq @vwf_loop_done           ; n exhausted
    jmp @vwf_loop                ; n > 0: keep going (jmp — too far for bne)
@vwf_loop_done:
    ; Fall through to @vwf_done (n cap reached).

@vwf_done:
    ; --- Write VWF tile indices to shadow tilemap ---
    lda VWF_SCRATCH_TILES_USED
    beq @vwf_exit

    ; Update global tile count
    clc
    adc VWF_SCRATCH_TILE_START
    sta WFT_VWF_TILE_COUNT

    ; Compute tilemap address: base + ty*64 + tx*2
    lda TEXT_SCRATCH_TY
    asl
    asl
    asl
    asl
    asl
    asl                         ; ty * 64
    clc
    adc TEXT_SCRATCH_BASE
    clc
    lda TEXT_SCRATCH_TX
    asl                         ; tx * 2
    clc
    adc TEXT_SCRATCH_TY
    asl
    asl
    asl
    asl
    asl
    asl                         ; recompute ty * 64 (simpler than stack juggling)
    ; Rethink: just compute it properly
    lda TEXT_SCRATCH_TY
    asl
    asl
    asl
    asl
    asl
    asl                         ; ty * 64
    clc
    adc TEXT_SCRATCH_TX
    adc TEXT_SCRATCH_TX          ; + tx * 2
    clc
    adc TEXT_SCRATCH_BASE
    tax                         ; X = tilemap start address

    ; Write tile index entries
    lda VWF_SCRATCH_TILE_START
    clc
    adc #VWF_VRAM_BASE_TILE
    sta $06                     ; current VWF tile index
    ldy #$0000
@vwf_tm_loop:
    cpy VWF_SCRATCH_TILES_USED
    bcs @vwf_tm_done
    lda $06
    ora TEXT_SCRATCH_COLOR
    sta a:$0000,x               ; write to shadow tilemap (DB=$7E)
    inx
    inx
    inc $06
    iny
    bra @vwf_tm_loop

@vwf_tm_done:
    plb                         ; restore DB

    ; Set VWF dirty flag
    sep #$20
    .a8
    lda #$01
    sta VWF_DIRTY
    rep #$20
    .a16

    ; Mark layer dirty
    lda API_BLOCK_BASE + 16
    dec
    tax
    sep #$20
    .a8
    lda f:_txt_dirty_bits,x
    ora BG_TILEMAP_DIRTY
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts

@vwf_exit:
    plb                         ; restore DB
    rts


; =============================================================================
; engine_print_chars — Render the FIRST N characters of a string
; =============================================================================
; Engine function ID 95: print_chars(str, x, y, color, layer, n).
;
; Same algorithm as engine_print's mono path, but the loop stops after
; `n` printable characters have been emitted (or earlier on a null
; terminator, or earlier on tile-X >= 32, whichever fires first). Used by
; the platformer dialog state machine (Phase 16-8 step 3 fix-up) to do
; per-character reveal without needing string indexing in game code.
;
; Non-printable bytes (< $20 or >= $80) are silently dropped — they do
; NOT consume reveal budget. This matches engine_print's range-check
; behavior so the rendered output is identical when n covers the whole
; string.
;
; API block:
;   API_BLOCK_BASE + 0  = str_ptr (low 16 bits)
;   API_BLOCK_BASE + 4  = x (pixel coordinate)
;   API_BLOCK_BASE + 8  = y (pixel coordinate)
;   API_BLOCK_BASE + 12 = color (palette index 0-7)
;   API_BLOCK_BASE + 16 = layer (1-3)
;   API_BLOCK_BASE + 20 = n (max chars to render; 0 = nothing rendered)
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================

; Scratch: remaining-character counter for engine_print_chars. Lives in
; the same WRAM scratch region as the rest of the text engine; not used
; by engine_print itself, so the two paths can coexist without aliasing.
TEXT_SCRATCH_NLEFT = $0586       ; 2 bytes: chars remaining to render

engine_print_chars:
    rep #$30
    .a16
    .i16

    ; --- Check VWF mode (D13: auto-dispatch). Phase 16-8 step 3 VWF fix
    ; (2026-05-09): the original engine_print_chars was copy-pasted from
    ; engine_print's MONO body and never wired up to the VWF path, so a
    ; reveal call with font(1) selected (VWF_ACTIVE=1) was rendering as
    ; monospace tile-grid output. This branch mirrors the dispatch at the
    ; top of engine_print and routes to engine_print_chars_vwf when VWF is
    ; active. The existing mono body falls through unchanged. ---
    sep #$20
    .a8
    lda VWF_ACTIVE              ; 0=monospace, 1=VWF
    rep #$20
    .a16
    beq @pc_mono_path           ; clear: keep mono path
    jmp engine_print_chars_vwf  ; set: route to VWF body
@pc_mono_path:

    ; --- Convert pixel coords to tile coords ---
    lda API_BLOCK_BASE + 4      ; x (pixels)
    lsr
    lsr
    lsr                         ; x >> 3
    sta TEXT_SCRATCH_TX

    lda API_BLOCK_BASE + 8      ; y (pixels)
    lsr
    lsr
    lsr                         ; y >> 3
    sta TEXT_SCRATCH_TY

    ; --- Precompute color bits (palette << 10) ---
    lda API_BLOCK_BASE + 12
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; color << 10
    sta TEXT_SCRATCH_COLOR

    ; --- Determine shadow tilemap base from layer ---
    lda API_BLOCK_BASE + 16
    jsr _txt_get_tilemap_base
    sta TEXT_SCRATCH_BASE

    ; --- Save string pointer (low 16 + bank) ---
    lda API_BLOCK_BASE + 0
    sta TEXT_SCRATCH_STRPTR
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2      ; bank byte from caller
    bne @pc_have_bank
    lda f:_string_pool_bank     ; fallback: build-emitted pool bank
@pc_have_bank:
    sta TEXT_SCRATCH_STRBNK
    rep #$20
    .a16

    ; --- Save char-count cap ---
    lda API_BLOCK_BASE + 20     ; n (max chars to render)
    sta TEXT_SCRATCH_NLEFT
    bne @pc_have_chars
    jmp @pc_done_norestore      ; n == 0: nothing to do (jmp — too far for bne)
@pc_have_chars:

    ; --- Set DB=$7E for WRAM access to shadow tilemaps ---
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; --- Set up DP scratch indirect-long pointer for string reads ---
    lda TEXT_SCRATCH_STRPTR
    sta <TEXT_SCRATCH_LONGPTR
    sep #$20
    .a8
    lda TEXT_SCRATCH_STRBNK
    sta <TEXT_SCRATCH_LONGPTR + 2
    rep #$20
    .a16

@pc_loop:
    ; Read next character via indirect long (any bank).
    sep #$20
    .a8
    lda [<TEXT_SCRATCH_LONGPTR]
    rep #$20
    .a16
    and #$00FF

    ; Null terminator → done early.
    beq @pc_done

    ; Advance pointer regardless of printability (so we step over invalid
    ; bytes the same way engine_print does).
    ldx TEXT_SCRATCH_STRPTR
    inx
    stx TEXT_SCRATCH_STRPTR
    stx <TEXT_SCRATCH_LONGPTR

    ; Range check.
    cmp #$0020
    bcc @pc_loop                ; non-printable: skip (does NOT decrement nleft)
    cmp #$0080
    bcs @pc_loop                ; >= $80: skip

    ; --- Compute tile index = FONT_BASE_TILE + (char - $20) ---
    sec
    sbc #$0020
    clc
    adc FONT_BASE_TILE

    ; Combine with palette bits.
    ora TEXT_SCRATCH_COLOR
    tay                         ; Y = tile word

    ; Compute tilemap address: base + ty*64 + tx*2.
    lda TEXT_SCRATCH_TY
    asl
    asl
    asl
    asl
    asl
    asl                         ; ty * 64
    clc
    adc TEXT_SCRATCH_BASE
    pha
    lda TEXT_SCRATCH_TX
    asl                         ; tx * 2
    clc
    adc $01,S
    plx                         ; clean stack
    tax

    ; Store tile word.
    tya
    sta a:$0000,x

    ; Advance tile X, check bounds.
    ldx TEXT_SCRATCH_TX
    inx
    stx TEXT_SCRATCH_TX
    cpx #$0020                  ; tx >= 32?
    bcs @pc_done                ; right edge — stop

    ; Decrement remaining-char counter.
    ldx TEXT_SCRATCH_NLEFT
    dex
    stx TEXT_SCRATCH_NLEFT
    bne @pc_loop                ; n > 0: keep going

@pc_done:
    plb                         ; restore DB

    ; Mark layer dirty.
    lda API_BLOCK_BASE + 16
    dec
    tax
    sep #$20
    .a8
    lda f:_txt_dirty_bits,x
    ora BG_TILEMAP_DIRTY
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts

@pc_done_norestore:
    ; n == 0 path: still mark layer dirty for consistency? No — nothing
    ; was written, so no dirty bit needed. Just return.
    rts



; =============================================================================
; engine_print_chars_vwf — VWF-aware variant of engine_print_chars
; =============================================================================
; Phase 16-8 step 3 VWF infrastructure refactor (2026-05-09).
;
; The original engine_print_chars_vwf (added by commit 7933c95) was a 95%
; copy of engine_print_vwf with an N-cap counter and slightly different
; label names. The VWF infrastructure sprint unified the two: the shared
; render body lives at engine_print_vwf _vwf_shared_body_entry, and this
; entry is now a thin wrapper that loads the caller's `n` cap into
; TEXT_SCRATCH_NLEFT before jumping into the shared body.
;
; The body's character loop decrements NLEFT after each printable char
; and exits when it reaches zero. engine_print_vwf initializes NLEFT to
; $FFFF (effectively unbounded — exits via null terminator first).
;
; API block (identical to engine_print_chars):
;   API_BLOCK_BASE + 0  = str_ptr (low 16 bits) + 2 = bank byte
;   API_BLOCK_BASE + 4  = x (pixel coordinate)
;   API_BLOCK_BASE + 8  = y (pixel coordinate)
;   API_BLOCK_BASE + 12 = color (palette index 0-7)
;   API_BLOCK_BASE + 16 = layer (1-3)
;   API_BLOCK_BASE + 20 = n (max chars to render; 0 = nothing rendered)
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_print_chars_vwf:
    rep #$30
    .a16
    .i16

    ; --- Save char-count cap. Bail early if n == 0. ---
    lda API_BLOCK_BASE + 20     ; n (max chars to render)
    sta TEXT_SCRATCH_NLEFT
    bne @vwfc_have_chars
    rts                         ; n == 0: nothing to do
@vwfc_have_chars:
    ; Drop into the shared body. NLEFT is now set; engine_print_vwf's
    ; loop will decrement it after each char and exit at zero.
    jmp _vwf_shared_body_entry



; =============================================================================
; engine_bg3_clear_rows — Zero a horizontal strip of BG3 SHADOW tilemap
; =============================================================================
; Engine function ID 96: bg3_clear_rows(tile_y_start, tile_y_end).
;
; Writes $0000 to all 32 column entries of BG3 SHADOW for tile rows
; [tile_y_start, tile_y_end). The Phase 16-8 step 3 dialog uses this on
; the dismiss-frame to clear the 3-line dialog text + frame border.
;
; API block:
;   API_BLOCK_BASE + 0 = tile_y_start (inclusive)
;   API_BLOCK_BASE + 4 = tile_y_end   (exclusive)
;
; Marks BG3 dirty so the NMI tilemap commit picks up the cleared rows.
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_bg3_clear_rows:
    rep #$30
    .a16
    .i16

    ; Address = SHADOW_BG3_TILEMAP + tile_y_start * 64.
    lda API_BLOCK_BASE + 0      ; tile_y_start
    asl
    asl
    asl
    asl
    asl
    asl                         ; * 64
    clc
    adc #SHADOW_BG3_TILEMAP
    tax                         ; X = start WRAM offset

    ; Byte count = (tile_y_end - tile_y_start) * 64.
    lda API_BLOCK_BASE + 4      ; tile_y_end
    sec
    sbc API_BLOCK_BASE + 0      ; n_rows
    asl
    asl
    asl
    asl
    asl
    asl                         ; * 64 = byte count
    tay                         ; Y = remaining bytes to write

    beq @bg3clr_done            ; nothing to do

    ; Set DB=$7E to hit WRAM.
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ; Loop: write $0000 (= tile 0 + palette 0 + no priority) per word.
    lda #$0000
@bg3clr_loop:
    sta a:$0000,x
    inx
    inx
    dey
    dey
    bne @bg3clr_loop

    plb                         ; restore DB

    ; Mark BG3 dirty.
    sep #$20
    .a8
    lda #$04                    ; bit 2 = BG3
    ora BG_TILEMAP_DIRTY
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16

@bg3clr_done:
    rts
