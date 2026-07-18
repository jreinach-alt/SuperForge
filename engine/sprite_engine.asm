; =============================================================================
; sprite_engine.asm — Basic Sprite Engine (E07) for SuperForge
; =============================================================================
; Manages shadow OAM buffer and provides spr()/spr_clear()/spr_resolve() API.
;
; Shadow OAM layout (from engine_state.inc):
;   SHADOW_OAM_BASE ($0300): 512 bytes — 128 entries x 4 bytes (low table)
;   SHADOW_OAM_HI   ($0500):  32 bytes — 128 entries x 2 bits (high table)
;   SPRITE_COUNT     ($0130):   2 bytes — active sprite count
;   OAM_DIRTY        ($0132):   1 byte  — 1 = needs DMA transfer
;
; OAM low table entry (4 bytes, matching SNES hardware):
;   Byte 0: X position (low 8 bits)
;   Byte 1: Y position (8 bits)
;   Byte 2: Tile index (8 bits)
;   Byte 3: Attributes — V flip | H flip | Pri1 | Pri0 | Pal2 | Pal1 | Pal0 | Name
;
; OAM high table (2 bits per sprite):
;   Bit 0: X position bit 8
;   Bit 1: Size select (0=small, 1=large)
;
; API Parameter Block (absolute WRAM, DP=$0000):
;   engine_spr reads from SPR_API_* addresses.
;   Callers write parameters here (the API-block convention).
;   Test ROMs can write directly.
;
; Prerequisites: engine_state.inc included, .p816/.smart set.
; Cross-ref: engine_state.inc, dma_scheduler.asm (for spr_resolve)
; =============================================================================

; API parameter addresses for engine_spr (absolute WRAM)
; These sit in the API parameter block region (DP $60-$9F).
SPR_API_TILE    = $60       ; 2 bytes used (low byte = tile index 0-255)
SPR_API_X       = $64       ; 2 bytes used (9-bit X position)
SPR_API_Y       = $68       ; 2 bytes used (low byte = Y position)
SPR_API_FLAGS   = $6C       ; 2 bytes used (low byte = VH00_PPPn)
SPR_API_PRI     = $70       ; 2 bytes used (low byte = BG priority 0-3)

; Return value address (matches dispatch.asm A0 return slot)
SPR_API_RETURN  = $40       ; 4 bytes: return value

; Scratch variable for sprite engine
SPR_SCRATCH     = $0560     ; 2 bytes


; --- engine_spr ---
; Place a sprite in the next available shadow OAM slot.
;
; Parameters (read from API block):
;   SPR_API_TILE:  tile index (8-bit)
;   SPR_API_X:     X position (9-bit, 0-511)
;   SPR_API_Y:     Y position (8-bit)
;   SPR_API_FLAGS: attribute flags (VH00_PPPn)
;   SPR_API_PRI:   BG priority (0-3)
;
; Returns: A = sprite slot used (0-127), or $FFFF if full
; Clobbers: A, X, Y. Expects 16-bit AXY (rep #$30).
engine_spr:
    rep #$30
    .a16
    .i16

    ; Check if queue full
    lda SPRITE_COUNT
    cmp #128
    bcc @not_full
    lda #$FFFF
    rts

@not_full:
    ; Save slot number for return and high table update
    sta SPR_SCRATCH             ; sprite slot = current count

    ; Calculate OAM low table offset = slot * 4
    asl
    asl
    tax                         ; X = low table byte offset

    ; Write OAM entry bytes
    sep #$20
    .a8
    lda SPR_API_X               ; X position low 8 bits
    sta SHADOW_OAM_BASE + 0, x
    lda SPR_API_Y               ; Y position
    sta SHADOW_OAM_BASE + 1, x
    lda SPR_API_TILE            ; Tile index
    sta SHADOW_OAM_BASE + 2, x

    ; Construct attribute byte: _H_pr_pr_PPPn
    ; flags[7] = size select (goes to high table, not OAM attribute)
    ; flags[6] = H-flip, flags[3:0] = PPPn (palette + name)
    ; pri goes into OAM bits 5-4
    lda SPR_API_FLAGS
    and #$4F                    ; keep H-flip and PPPn, strip size (7) and pri (5-4)
    sta SHADOW_OAM_BASE + 3, x ; temp store attribute
    lda SPR_API_PRI
    and #$03
    asl
    asl
    asl
    asl                         ; shift priority to bits 5-4
    ora SHADOW_OAM_BASE + 3, x ; combine with flags
    sta SHADOW_OAM_BASE + 3, x ; write final attribute byte

    ; --- Update OAM high table ---
    ; Byte offset = slot >> 2, bit position = (slot & 3) * 2
    rep #$20
    .a16
    lda SPR_SCRATCH             ; sprite slot
    lsr
    lsr
    tay                         ; Y = high table byte offset

    lda SPR_SCRATCH
    and #$0003
    tax                         ; X = slot & 3 (index 0-3)

    ; Clear old bits for this sprite, then set X-high if needed
    sep #$20
    .a8
    lda SHADOW_OAM_HI, y
    and f:_hi_clear_mask, x     ; clear both bits for this sprite
    sta SHADOW_OAM_HI, y

    ; Check if X position bit 8 is set
    rep #$20
    .a16
    lda SPR_API_X
    and #$0100
    beq @x_low
    ; X bit 8 is set — OR in the X-high bit
    sep #$20
    .a8
    lda SHADOW_OAM_HI, y
    ora f:_hi_set_xhigh, x
    sta SHADOW_OAM_HI, y
@x_low:

    ; Check if size bit (flags bit 7) is set → large sprite
    sep #$20
    .a8
    lda SPR_API_FLAGS
    and #$80
    beq @size_small
    ; Large sprite — set size bit in high table
    lda SHADOW_OAM_HI, y
    ora f:_hi_set_size, x
    sta SHADOW_OAM_HI, y
@size_small:

    ; Increment sprite count
    rep #$20
    .a16
    inc SPRITE_COUNT

    ; Mark OAM as dirty
    sep #$20
    .a8
    lda #$01
    sta OAM_DIRTY

    ; Return sprite slot in A
    rep #$20
    .a16
    lda SPR_SCRATCH
    rts


; --- engine_spr_clear ---
; Hide all 128 sprites by setting Y=$F0 (off-screen).
; Reset sprite count to 0 and mark OAM dirty.
;
; Clobbers: A, X. No parameters.
engine_spr_clear:
    rep #$10
    .i16
    sep #$20
    .a8

    ; Set Y=$F0 for all 128 sprite slots
    lda #$F0
    ldx #$0000
@clear_loop:
    sta SHADOW_OAM_BASE + 1, x ; Y position byte = $F0
    inx
    inx
    inx
    inx                         ; next entry (4 bytes)
    cpx #$0200                  ; 128 * 4 = 512
    bne @clear_loop

    ; Clear high table (32 bytes) — size=0, X-high=0
    rep #$20
    .a16
    ldx #$0000
@clear_hi:
    stz SHADOW_OAM_HI, x
    inx
    inx
    cpx #$0020                  ; 32 bytes
    bne @clear_hi

    ; Reset sprite count
    stz SPRITE_COUNT

    ; Mark dirty
    sep #$20
    .a8
    lda #$01
    sta OAM_DIRTY

    rep #$20
    .a16
    rts


; --- engine_spr_resolve ---
; Called during the resolve phase (after _draw, before VBlank signal).
; Sorts sprites by mode, detects scanline overflow, applies flicker,
; hides unused sprite slots, and enqueues OAM DMA at priority 0.
;
; Clobbers: A, X, Y. Expects dma_scheduler.asm to be included.
engine_spr_resolve:
    rep #$30
    .a16
    .i16

    ; Check if OAM is dirty
    sep #$20
    .a8
    lda OAM_DIRTY
    bne @resolve_not_clean
    jmp @resolve_done           ; nothing to do
@resolve_not_clean:
    rep #$20
    .a16

    ; --- Sorting phase ---
    ; Check SPR_ORDER_MODE to determine sort strategy
    sep #$20
    .a8
    lda SPR_ORDER_MODE
    cmp #$02
    bcs @sort_done              ; mode 2 (stable) or invalid = no sorting
    rep #$20
    .a16

    ; Initialize sort index array: SPR_SORT_INDEX[i] = i
    lda SPRITE_COUNT
    beq @sort_done
    cmp #2
    bcc @sort_done              ; 0 or 1 sprites: nothing to sort

    jsr _spr_init_sort_arrays   ; Initialize index + keys arrays
    jsr _spr_insertion_sort     ; Sort SPR_SORT_INDEX by SPR_SORT_KEYS
    jsr _spr_remap_oam          ; Remap shadow OAM entries to sorted order
    bra @scanline_detect

@sort_done:
    rep #$30
    .a16
    .i16

@scanline_detect:
    ; --- Scanline overflow detection (opt-in, saves ~3,000 cycles when off) ---
    ; Check SPR_SCANLINE_DETECT_EN flag. Default OFF = skip detection entirely.
    ; Enable via spr_scanline_detect(1) or automatically when stat(8) is used.
    sep #$20
    .a8
    lda SPR_SCANLINE_DETECT_EN
    beq @skip_scanline_detect
    rep #$20
    .a16
    jsr _spr_scanline_overflow
    bra @oam_flicker
@skip_scanline_detect:
    rep #$20
    .a16
    ; Zero peak so flicker doesn't engage on stale data.
    ; SPR_SCANLINE_PEAK is WRAM extended; STZ has no long form.
    lda #$0000
    sta SPR_SCANLINE_PEAK

@oam_flicker:
    ; --- OAM Flicker ---
    sep #$20
    .a8
    lda SPR_FLICKER_ENABLE
    beq @no_flicker
    rep #$20
    .a16
    lda SPR_SCANLINE_PEAK
    cmp #32
    bcc @no_flicker_16
    ; Peak >= 32: increment flicker offset
    sep #$20
    .a8
    lda SPR_FLICKER_OFFSET
    inc
    cmp #128
    bcc @flicker_no_wrap
    lda #$00
@flicker_no_wrap:
    sta SPR_FLICKER_OFFSET
    rep #$20
    .a16
    jsr _spr_apply_flicker
    bra @hide_unused
@no_flicker:
    rep #$20
    .a16
@no_flicker_16:

@hide_unused:
    ; Hide unused slots: set Y=$F0 for slots [sprite_count..127]
    lda SPRITE_COUNT
    cmp #128
    bcs @skip_hide              ; all 128 used, nothing to hide

    ; Calculate starting offset = sprite_count * 4
    asl
    asl
    tax                         ; X = first unused slot offset

    sep #$20
    .a8
    lda #$F0
@hide_loop:
    sta SHADOW_OAM_BASE + 1, x ; Y = $F0
    inx
    inx
    inx
    inx
    cpx #$0200                  ; end of low table
    bne @hide_loop
    rep #$20
    .a16

@skip_hide:
    ; Enqueue OAM DMA transfer at priority 0
    sep #$20
    .a8
    lda #$00                    ; Priority 0 (highest -- never dropped)
    sta DMA_STAGE_PRIORITY
    lda #$00                    ; DMAP: one register, increment
    sta DMA_STAGE_DMAP
    lda #$04                    ; BBAD: $2104 (OAMDATA write port)
    sta DMA_STAGE_BBAD
    rep #$20
    .a16
    lda #SHADOW_OAM_BASE        ; Source: shadow OAM in WRAM
    sta DMA_STAGE_SRC_LO
    sep #$20
    .a8
    lda #$7E                    ; Source bank: $7E (WRAM)
    sta DMA_STAGE_SRC_BANK
    rep #$20
    .a16
    lda #SHADOW_OAM_TOTAL       ; Size: 544 bytes
    sta DMA_STAGE_SIZE
    jsr dma_queue_add

    ; Clear dirty flag
    sep #$20
    .a8
    stz OAM_DIRTY

@resolve_done:
    rep #$20
    .a16
    rts


; =============================================================================
; _spr_init_sort_arrays — Initialize sort index and key arrays
; =============================================================================
; Fills SPR_SORT_INDEX[i] = i for i in [0..sprite_count-1]
; Fills SPR_SORT_KEYS[i] based on SPR_ORDER_MODE:
;   Mode 0 (priority): key = OAM attribute byte bits 5-4 (priority field)
;   Mode 1 (y_sort):   key = OAM Y position byte
;
; Expects: 16-bit AXY, SPRITE_COUNT >= 2
; Clobbers: A, X, Y
; =============================================================================
_spr_init_sort_arrays:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E so absolute addressing reaches WRAM heap ($A000+)
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ldx #$0000                  ; X = sprite index
    lda SPRITE_COUNT
    sta SPR_SCRATCH             ; loop limit

@init_loop:
    cpx SPR_SCRATCH
    bcs @init_done

    ; SPR_SORT_INDEX[X] = X
    sep #$20
    .a8
    txa
    sta SPR_SORT_INDEX, x

    ; Determine key based on mode
    lda SPR_ORDER_MODE
    beq @key_priority

    ; Mode 1: Y-sort — key = OAM Y position
    ; OAM entry offset = X * 4, Y position at offset+1
    rep #$20
    .a16
    txa
    asl
    asl
    tay                         ; Y = OAM entry offset
    sep #$20
    .a8
    lda SHADOW_OAM_BASE + 1, y ; Y position byte
    sta SPR_SORT_KEYS, x
    bra @init_next

@key_priority:
    ; Mode 0: Priority sort — key = attribute bits 5-4
    rep #$20
    .a16
    txa
    asl
    asl
    tay                         ; Y = OAM entry offset
    sep #$20
    .a8
    lda SHADOW_OAM_BASE + 3, y ; attribute byte
    and #$30                    ; isolate bits 5-4 (priority)
    lsr
    lsr
    lsr
    lsr                         ; shift to bits 1-0 (value 0-3)
    sta SPR_SORT_KEYS, x

@init_next:
    rep #$20
    .a16
    inx
    bra @init_loop

@init_done:
    rep #$30
    .a16
    .i16
    plb                         ; restore DB
    rts


; =============================================================================
; _spr_insertion_sort — Sort SPR_SORT_INDEX by SPR_SORT_KEYS (ascending)
; =============================================================================
; Insertion sort: stable, O(n) for nearly-sorted data (typical for Y-sort).
; Operates on SPR_SORT_INDEX array, using SPR_SORT_KEYS for comparisons.
;
; Expects: 16-bit AXY, SPRITE_COUNT >= 2
; Clobbers: A, X, Y
;
; Scratch usage:
;   SPR_SCRATCH+0: 2 bytes (key of element being inserted)
;   $0562:         2 bytes (saved index value being inserted)
; =============================================================================
_SORT_KEY_TMP  = $0562          ; 2 bytes scratch for sort

_spr_insertion_sort:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E so absolute addressing reaches WRAM heap ($A000+)
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; Outer loop: i = 1 to sprite_count-1
    ldx #$0001                  ; X = i (starting at 1)

@outer:
    cpx SPRITE_COUNT
    bcs @sort_exit

    ; Load key[i] and index[i] — the element to insert
    sep #$20
    .a8
    lda SPR_SORT_KEYS, x
    rep #$20
    .a16
    and #$00FF
    sta SPR_SCRATCH             ; key to insert (zero-extended)

    sep #$20
    .a8
    lda SPR_SORT_INDEX, x
    sta _SORT_KEY_TMP           ; save index value

    ; Inner loop: j = i-1, shift elements right while key[j] > insert_key
    rep #$20
    .a16
    txa
    tay                         ; Y = j+1 (current position)
    dey                         ; Y = j (start scanning backward... but we need unsigned)
    ; Actually Y was X, dec gives j = i-1
    ; We use Y as the "current compare position"

@inner:
    ; Compare: SPR_SORT_KEYS[Y] > SPR_SCRATCH?
    sep #$20
    .a8
    lda SPR_SORT_KEYS, y
    rep #$20
    .a16
    and #$00FF
    cmp SPR_SCRATCH
    beq @insert                 ; equal = stable, don't shift
    bcc @insert                 ; key[j] <= insert_key: stop

    ; Shift: index[j+1] = index[j], key[j+1] = key[j]
    sep #$20
    .a8
    lda SPR_SORT_INDEX, y
    iny
    sta SPR_SORT_INDEX, y       ; index[j+1] = index[j]
    dey
    lda SPR_SORT_KEYS, y
    iny
    sta SPR_SORT_KEYS, y        ; key[j+1] = key[j]
    dey

    ; j--
    cpy #$0000
    beq @insert_at_zero
    dey
    rep #$20
    .a16
    bra @inner

@insert_at_zero:
    ; Insert at position 0: j was 0 and key[0] > insert_key
    ; The element at position 0 was already shifted to position 1
    sep #$20
    .a8
    lda _SORT_KEY_TMP
    sta SPR_SORT_INDEX           ; index[0] = saved value
    lda SPR_SCRATCH
    sta SPR_SORT_KEYS            ; key[0] = insert key
    rep #$20
    .a16
    inx
    bra @outer

@insert:
    ; Insert at position j+1
    rep #$20
    .a16
    iny                         ; Y = insertion position (j+1)
    sep #$20
    .a8
    lda _SORT_KEY_TMP
    sta SPR_SORT_INDEX, y       ; index[j+1] = saved value
    lda SPR_SCRATCH
    sta SPR_SORT_KEYS, y        ; key[j+1] = insert key
    rep #$20
    .a16
    inx
    bra @outer

@sort_exit:
    rep #$30
    .a16
    .i16
    plb                         ; restore DB
    rts


; =============================================================================
; _spr_remap_oam — Remap shadow OAM entries based on sorted index array
; =============================================================================
; For each position i in [0..sprite_count-1]:
;   Copy OAM entry from slot SPR_SORT_INDEX[i] to a temp buffer at slot i.
; Then copy the temp buffer back to shadow OAM.
;
; We use SPR_SCANLINE_COUNTS ($A100, 224 bytes) as temporary OAM storage
; since it is reused later for scanline detection. We need sprite_count*4 bytes
; for the low table remap (max 512 bytes). With only 224 bytes at SCANLINE_COUNTS,
; we do the remap in-place using the sort index:
;
; Actually, we use a cycle-optimized approach: copy from source OAM entries
; to the new positions directly, using the sort index as a read map.
; Since we may read from a slot that was already overwritten, we first copy
; the entire active OAM region to a temp area, then write back in sorted order.
;
; Temp area: $F000 (free heap above the debug region; nothing else claims
; $F000-$FFFF). We need at most 128*4 = 512 bytes for the low table copy.
;
; BUG FIX (knight_quest acceptance, 2026-06-11): this buffer previously
; lived at $A200/$A400 — INSIDE SHADOW_BG1_TILEMAP ($A200-$A9FF, see
; engine_state.inc). Every sorted resolve (SPR_ORDER_MODE 0/1, >= 2
; sprites) copied raw OAM entries over BG1 shadow tilemap rows 0-7, and
; the NMI DMA pushed them to VRAM. Invisible while the garbage words hit
; blank CHR tiles; visible as stray tiles at the screen top once a game
; defines CHR at those tile IDs (knight_quest's gem tile, id 4, rendered
; at screen (8,0) every frame until this fix).
;
; Expects: 16-bit AXY, SPRITE_COUNT >= 2
; Clobbers: A, X, Y
; =============================================================================
SPR_REMAP_TEMP      = $F000     ; 512 bytes temp storage for OAM remap
SPR_REMAP_TEMP_HI   = $F200     ; 32 bytes temp storage for OAM high table remap

_spr_remap_oam:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E so absolute addressing reaches WRAM heap ($A000+)
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; Step 1: Copy active OAM entries to temp area
    ; Copy sprite_count * 4 bytes from SHADOW_OAM_BASE to SPR_REMAP_TEMP
    lda SPRITE_COUNT
    asl
    asl
    sta SPR_SCRATCH             ; total bytes to copy
    tax                         ; X = byte count
    dex                         ; start from last byte (X = count - 1)
    ; Actually, let's use an ascending copy
    ldx #$0000
@copy_to_temp:
    cpx SPR_SCRATCH
    bcs @copy_temp_done
    lda SHADOW_OAM_BASE, x
    sta SPR_REMAP_TEMP, x
    inx
    inx
    bra @copy_to_temp
@copy_temp_done:

    ; Also copy the high table (32 bytes)
    ldx #$0000
@copy_hi_temp:
    cpx #$0020
    bcs @copy_hi_done
    lda SHADOW_OAM_HI, x
    sta SPR_REMAP_TEMP_HI, x
    inx
    inx
    bra @copy_hi_temp
@copy_hi_done:

    ; Step 2: Write back in sorted order
    ; For each destination slot i, read from source slot SPR_SORT_INDEX[i]
    ldx #$0000                  ; X = destination index (i)

@remap_loop:
    cpx SPRITE_COUNT
    bcc @remap_continue
    jmp @remap_done
@remap_continue:

    ; Get source slot: SPR_SORT_INDEX[X]
    sep #$20
    .a8
    lda SPR_SORT_INDEX, x
    rep #$20
    .a16
    and #$00FF
    ; source OAM offset = source_slot * 4
    asl
    asl
    tay                         ; Y = source offset in temp

    ; Destination OAM offset = X * 4
    phx                         ; save destination index
    txa
    asl
    asl
    tax                         ; X = destination offset in shadow OAM

    ; Copy 4 bytes: low table entry
    sep #$20
    .a8
    lda SPR_REMAP_TEMP + 0, y
    sta SHADOW_OAM_BASE + 0, x
    lda SPR_REMAP_TEMP + 1, y
    sta SHADOW_OAM_BASE + 1, x
    lda SPR_REMAP_TEMP + 2, y
    sta SHADOW_OAM_BASE + 2, x
    lda SPR_REMAP_TEMP + 3, y
    sta SHADOW_OAM_BASE + 3, x

    ; --- Remap high table bits ---
    ; Source high table: 2 bits at position (src_slot & 3) * 2 in byte (src_slot >> 2)
    ; Destination high table: 2 bits at position (dst_slot & 3) * 2 in byte (dst_slot >> 2)
    rep #$20
    .a16
    plx                         ; X = destination index (i)
    phx                         ; re-save

    ; Get source slot again
    sep #$20
    .a8
    lda SPR_SORT_INDEX, x
    rep #$20
    .a16
    and #$00FF
    pha                         ; save source slot on stack

    ; Read source 2-bit value
    lsr
    lsr
    tay                         ; Y = source byte offset (src_slot >> 2)
    pla                         ; A = source slot
    pha                         ; re-save
    and #$0003
    tax                         ; X = src_slot & 3
    sep #$20
    .a8
    lda SPR_REMAP_TEMP_HI, y   ; source high table byte
    ; Extract 2 bits at position X*2
    cpx #$0000
    beq @hi_src_extract
    cpx #$0001
    beq @hi_src_s2
    cpx #$0002
    beq @hi_src_s4
    ; X=3: shift right 6
    lsr
    lsr
@hi_src_s4:
    lsr
    lsr
@hi_src_s2:
    lsr
    lsr
@hi_src_extract:
    and #$03                    ; A = 2-bit value from source
    sta SPR_SCRATCH             ; save extracted bits

    ; Now write to destination position
    rep #$20
    .a16
    pla                         ; discard source slot
    plx                         ; X = destination index
    phx                         ; re-save again

    ; Destination byte = dst_slot >> 2, bit position = (dst_slot & 3) * 2
    txa
    lsr
    lsr
    tay                         ; Y = dest byte offset
    txa
    and #$0003
    tax                         ; X = dst_slot & 3

    sep #$20
    .a8
    ; Clear destination 2 bits
    lda SHADOW_OAM_HI, y
    and f:_hi_clear_mask, x     ; clear the 2 bits
    sta SHADOW_OAM_HI, y

    ; Shift source value to correct position
    lda SPR_SCRATCH             ; 2-bit value (0-3)
    cpx #$0000
    beq @hi_dst_done
    cpx #$0001
    beq @hi_dst_s2
    cpx #$0002
    beq @hi_dst_s4
    ; X=3: shift left 6
    asl
    asl
@hi_dst_s4:
    asl
    asl
@hi_dst_s2:
    asl
    asl
@hi_dst_done:
    ora SHADOW_OAM_HI, y       ; OR in the bits
    sta SHADOW_OAM_HI, y

    rep #$30
    .a16
    .i16
    plx                         ; X = destination index
    inx
    jmp @remap_loop

@remap_done:
    rep #$30
    .a16
    .i16
    plb                         ; restore DB
    rts


; =============================================================================
; _spr_scanline_overflow — Count sprites per scanline, track peak
; =============================================================================
; For each active sprite, increment counts for scanlines it occupies.
; 8x8 sprites: active on scanlines [Y .. Y+7] (wrapping not handled for
; off-screen sprites with Y >= $F0).
;
; Uses SPR_SCANLINE_COUNTS ($A100, 224 bytes) as per-scanline counter array.
;
; Expects: 16-bit AXY
; Clobbers: A, X, Y
; =============================================================================
_spr_scanline_overflow:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E so absolute addressing reaches WRAM heap ($A000+)
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; Clear scanline count array (224 bytes)
    ldx #$0000
    lda #$0000
@clear_scanline:
    sta SPR_SCANLINE_COUNTS, x
    inx
    inx
    cpx #$00E0                  ; 224 bytes
    bcc @clear_scanline

    ; For each active sprite, add 1 to scanlines [Y..Y+7]
    lda SPRITE_COUNT
    beq @scan_peak
    sta SPR_SCRATCH             ; loop limit

    ldx #$0000                  ; X = sprite index
@scan_sprite_loop:
    cpx SPR_SCRATCH
    bcs @scan_peak

    ; Get Y position of sprite X
    ; OAM offset = X * 4, Y at offset + 1
    txa
    asl
    asl
    tay                         ; Y = OAM offset
    sep #$20
    .a8
    lda SHADOW_OAM_BASE + 1, y ; Y position
    rep #$20
    .a16
    and #$00FF
    cmp #$E0                    ; Y >= 224 ($E0)? Sprite is off-screen
    bcs @scan_next_sprite

    ; Increment counts for scanlines [Y .. Y+7], clamped to 223
    tay                         ; Y = scanline start
    phx                         ; save sprite index
    ldx #$0008                  ; 8 scanlines for 8x8 sprite
@scan_line_loop:
    cpy #$00E0                  ; scanline >= 224?
    bcs @scan_line_done
    sep #$20
    .a8
    lda SPR_SCANLINE_COUNTS, y
    inc
    sta SPR_SCANLINE_COUNTS, y
    rep #$20
    .a16
    iny
    dex
    bne @scan_line_loop
@scan_line_done:
    plx                         ; restore sprite index

@scan_next_sprite:
    inx
    bra @scan_sprite_loop

@scan_peak:
    ; Find peak count across all 224 scanlines
    rep #$30
    .a16
    .i16
    ldx #$0000
    lda #$0000                  ; A = current peak (16-bit)
    sta SPR_SCRATCH             ; peak accumulator
@peak_loop:
    cpx #$00E0
    bcs @peak_done
    sep #$20
    .a8
    lda SPR_SCANLINE_COUNTS, x
    rep #$20
    .a16
    and #$00FF
    cmp SPR_SCRATCH
    bcc @peak_next
    sta SPR_SCRATCH             ; new peak
@peak_next:
    inx
    bra @peak_loop
@peak_done:
    lda SPR_SCRATCH
    sta SPR_SCANLINE_PEAK

    plb                         ; restore DB
    rts


; =============================================================================
; _spr_apply_flicker — Rotate OAM starting index for hardware flicker
; =============================================================================
; When writing sorted OAM to hardware, offset the starting OAM index
; by SPR_FLICKER_OFFSET. Sprites wrap around at index 127.
;
; This rotates the priority order in hardware OAM so that different sprites
; are dropped on different frames when there's scanline overflow.
;
; Implementation: Rotate the shadow OAM entries in-place.
; Copy all active entries to temp, then write back with rotation offset.
;
; Expects: 16-bit AXY, SPRITE_COUNT > 0
; Clobbers: A, X, Y
; =============================================================================
_spr_apply_flicker:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E so absolute addressing reaches WRAM heap ($A000+)
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    lda SPRITE_COUNT
    beq @flicker_exit
    sta SPR_SCRATCH             ; sprite count

    ; Copy active OAM low table entries to temp
    lda SPRITE_COUNT
    asl
    asl
    tax                         ; X = total bytes
    dex
    dex                         ; X = last word offset (for 16-bit copy)
@flk_copy_loop:
    lda SHADOW_OAM_BASE, x
    sta SPR_REMAP_TEMP, x
    dex
    dex
    bpl @flk_copy_loop

    ; Also copy high table
    ldx #$001E                  ; 32 bytes, copy as 16-bit words
@flk_hi_copy:
    lda SHADOW_OAM_HI, x
    sta SPR_REMAP_TEMP_HI, x
    dex
    dex
    bpl @flk_hi_copy

    ; Now write back rotated: dest slot i gets source slot (i + offset) % count
    sep #$20
    .a8
    lda SPR_FLICKER_OFFSET
    rep #$20
    .a16
    and #$00FF
    sta _SORT_KEY_TMP           ; flicker offset

    ldx #$0000                  ; X = destination index

@flk_rotate_loop:
    cpx SPR_SCRATCH
    bcs @flk_rotate_done

    ; source = (X + offset) % sprite_count
    txa
    clc
    adc _SORT_KEY_TMP           ; A = X + offset
    ; Modulo: if A >= sprite_count, subtract sprite_count
@flk_mod:
    cmp SPR_SCRATCH
    bcc @flk_mod_done
    sec
    sbc SPR_SCRATCH
    bra @flk_mod
@flk_mod_done:
    ; A = source index
    asl
    asl
    tay                         ; Y = source OAM offset

    ; Destination offset = X * 4
    phx
    txa
    asl
    asl
    tax                         ; X = dest OAM offset

    ; Copy 4 bytes
    sep #$20
    .a8
    lda SPR_REMAP_TEMP + 0, y
    sta SHADOW_OAM_BASE + 0, x
    lda SPR_REMAP_TEMP + 1, y
    sta SHADOW_OAM_BASE + 1, x
    lda SPR_REMAP_TEMP + 2, y
    sta SHADOW_OAM_BASE + 2, x
    lda SPR_REMAP_TEMP + 3, y
    sta SHADOW_OAM_BASE + 3, x
    rep #$20
    .a16

    plx
    inx
    bra @flk_rotate_loop

@flk_rotate_done:

@flicker_exit:
    rep #$30
    .a16
    .i16
    plb                         ; restore DB
    rts


; --- Lookup tables (ROM data) ---
; Must use long addressing (f:) since these are in the CODE segment.

_hi_clear_mask:
    .byte $FC, $F3, $CF, $3F   ; clear 2 bits at position 0, 2, 4, 6

_hi_set_xhigh:
    .byte $01, $04, $10, $40   ; set X-high bit at position 0, 2, 4, 6

_hi_set_size:
    .byte $02, $08, $20, $80   ; set size bit at position 1, 3, 5, 7
