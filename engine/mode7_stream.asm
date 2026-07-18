; =============================================================================
; mode7_stream.asm — reusable Mode 7 2-axis tilemap streaming (Streaming rail v2)
; =============================================================================
; Ports the proven overhead-racing 2-axis (row + column) Mode 7 streaming
; substrate into a reusable engine routine pair:
;
;   mode7_stream_init   set up streaming state for a world spawn tile (tx,ty).
;   mode7_stream_tick   per-frame main-thread service: diff the camera tile
;                       position vs the last-streamed position, read the
;                       leading-edge row(s)/column(s) out of the multi-bank
;                       FLAT ROM tilemap, and stage them in WRAM at the
;                       VRAM-WRAPPED position. The NMI VBlank dispatcher
;                       (mode7_stream_nmi.inc, hooked into nmi_handler.asm)
;                       DMAs the staged buffers into the Mode 7 VRAM tilemap.
;
; Position-space discipline (CLAUDE.md "Mode 7 VRAM Buffer Writes Must Be
; Position-Wrapped" + "Streaming Clamp Must Cover Max Speed"):
;   - World coords run 0..WORLD_T_TILES-1 (the WORLD is larger than 128).
;   - The VRAM Mode 7 tilemap stays 128x128; the PPU samples modulo 128.
;   - A streamed row/col is written at the WRAPPED VRAM position (coord & $7F),
;     NOT sequentially — so the hardware's auto-wrap picks it up.
;   - The per-frame clamp is M7S_MAX (8) >= the max tiles/frame at top camera
;     speed, so no row/col is ever skipped (no stale-strip corruption).
;   - Only the tilemap LOW bytes stream (DMA -> VMDATAL $2118); the Mode 7 CHR
;     (VRAM high bytes) is uploaded once at boot and never streams.
;
; Flat ROM tilemap addressing (PARAMETRIC over the world layout; serves both a
; 256-col/128-rows-per-bank world AND a 512-col/64-rows-per-bank world from the
; same engine — the bank shift + per-row stride are derived at assemble time
; from WORLD_ROWS_PER_BANK / WORLD_COLS_BYTES; see _m7s_flat_row_ptr):
;   bank   = (row >> log2(WORLD_ROWS_PER_BANK)) + WORLD_FLAT_BANK_BASE
;   offset = $8000 + (row & (WORLD_ROWS_PER_BANK-1)) * WORLD_COLS_BYTES
;   read   = lda [<ES_M7S_PTR], y    (Y = source column 0..WORLD_COLS_BYTES-1)
;
; Prerequisites (the including ROM provides, before this file):
;   .p816 / .smart, engine_state.inc, and the world constants from
;   world_stream.inc (WORLD_T_TILES, WORLD_WRAP_MASK, WORLD_ROWS_PER_BANK,
;   WORLD_COLS_BYTES, WORLD_FLAT_BANK_BASE) and a label `world_flat` is NOT
;   required — the tick computes the bank from the row, so the flat banks must
;   be linked at $bb:8000 with bb = WORLD_FLAT_BANK_BASE + (row>>7).
;
; DP / width contract: callers enter A16/I16, DB = $00 (main thread). The
; routines internally read flat ROM via long-indirect and write WRAM staging
; via long-absolute-indexed (DB-independent). They restore A16/I16 on exit.
; =============================================================================

; WIDTH-RISK: mode7_stream_init enters A16/I16 (main thread). Sets up streaming
; state, never toggles into A8 except in clearly-marked spans that restore A16.
; --- mode7_stream_init: arm streaming for spawn tile (X=tx, Y=ty) -----------
; In:  X = spawn tile X (world space), Y = spawn tile Y (world space). A16/I16.
; Out: M7S_CAM/LAST/COUNT initialized, M7S_ACTIVE=1. Buffers NOT pre-filled
;      (the boot seed upload covers the initial window; the tick fills deltas).
; Clobbers A, X, Y.
mode7_stream_init:
    .a16
    .i16
    phb                             ; save caller DB
    pea $7E7E
    plb                             ; DB = $7E (M7S_* state lives in bank $7E)
    plb
    txa
    and #WORLD_WRAP_MASK
    sta a:M7S_CAM_TX
    sta a:M7S_LAST_TX
    tya
    and #WORLD_WRAP_MASK
    sta a:M7S_CAM_TY
    sta a:M7S_LAST_TY
    lda #0
    sta a:M7S_ROW_COUNT
    sta a:M7S_COL_COUNT
    lda #1
    sta a:M7S_ACTIVE
    plb                             ; restore caller DB
    rts

; --- mode7_stream_set_cam: update camera tile pos from world pixel coords ----
; In:  X = camera X pixel (world space), Y = camera Y pixel. A16/I16.
; Out: M7S_CAM_TX/TY = (pixel >> 3) & WRAP. (The tick consumes these.)
; Clobbers A.
mode7_stream_set_cam:
    .a16
    .i16
    phb
    pea $7E7E
    plb
    plb                             ; DB = $7E
    txa
    lsr
    lsr
    lsr
    and #WORLD_WRAP_MASK
    sta a:M7S_CAM_TX
    tya
    lsr
    lsr
    lsr
    and #WORLD_WRAP_MASK
    sta a:M7S_CAM_TY
    plb
    rts

; =============================================================================
; mode7_stream_tick — per-frame main-thread streaming service.
; In:  A16/I16, DB = $00. M7S_CAM_TX/TY hold the current camera tile pos.
; Out: stages any newly-entered rows/cols into M7S_ROW_BUF/M7S_COL_BUF at the
;      wrapped VRAM positions; sets M7S_ROW_COUNT/M7S_COL_COUNT for the NMI.
; Clobbers A, X, Y, ES_M7S_PTR, ES_M7S_TMP.
; =============================================================================
mode7_stream_tick:
    .a16
    .i16
    phb                             ; save caller DB
    pea $7E7E
    plb
    plb                             ; DB = $7E for all M7S_* WRAM state access
    lda a:M7S_ACTIVE
    bne :+
    plb                             ; restore caller DB
    rts                             ; streaming disabled — no-op
:
    ; =====================================================================
    ; COLUMN streaming (X axis): if cam_tx != last_tx, stream the columns
    ; that just entered the leading edge of the 128-wide window.
    ; =====================================================================
    lda a:M7S_CAM_TX
    cmp a:M7S_LAST_TX
    beq @no_col
    ; wrapped delta = (cam_tx - last_tx) & WRAP. delta in [1..WORLD/2) => EAST,
    ; else WEST. Use WORLD/2 split on the wrap mask.
    sec
    sbc a:M7S_LAST_TX
    and #WORLD_WRAP_MASK
    cmp #(WORLD_T_TILES / 2)
    bcs @col_west
    ; --- EAST: clamp delta to M7S_MAX, step last_tx forward each iter -----
    cmp #(M7S_MAX + 1)
    bcc :+
    lda #M7S_MAX
:   sta a:M7S_COL_COUNT
    sta a:M7S_SCR_LOOP             ; loop remaining
    ldy #0                          ; Y = VADDR/buffer slot index (0,2,4,...)
@col_east_loop:
    ; step last_tx forward, leading column = last_tx + M7S_HALF
    lda a:M7S_LAST_TX
    inc
    and #WORLD_WRAP_MASK
    sta a:M7S_LAST_TX
    clc
    adc #(M7S_HALF - 1)   ; leading fwd edge = last + (HALF-1) = window bottom/right
    and #WORLD_WRAP_MASK            ; A = world column to stream
    jsr _m7s_stage_column           ; reads col A, stages into slot Y
    iny
    iny
    lda a:M7S_SCR_LOOP
    dec
    sta a:M7S_SCR_LOOP
    bne @col_east_loop
    bra @no_col
@col_west:
    ; --- WEST: delta = (last_tx - cam_tx) & WRAP, step last_tx back -------
    lda a:M7S_LAST_TX
    sec
    sbc a:M7S_CAM_TX
    and #WORLD_WRAP_MASK
    cmp #(M7S_MAX + 1)
    bcc :+
    lda #M7S_MAX
:   sta a:M7S_COL_COUNT
    sta a:M7S_SCR_LOOP
    ldy #0
@col_west_loop:
    lda a:M7S_LAST_TX
    dec
    and #WORLD_WRAP_MASK
    sta a:M7S_LAST_TX
    sec
    sbc #M7S_HALF             ; leading west column = last_tx - (HALF-1)   ; leading rev edge = last - HALF = window top/left
    and #WORLD_WRAP_MASK
    jsr _m7s_stage_column
    iny
    iny
    lda a:M7S_SCR_LOOP
    dec
    sta a:M7S_SCR_LOOP
    bne @col_west_loop
@no_col:
    ; =====================================================================
    ; ROW streaming (Y axis): if cam_ty != last_ty, stream the rows that
    ; just entered the leading edge of the 128-tall window.
    ; =====================================================================
    lda a:M7S_CAM_TY
    cmp a:M7S_LAST_TY
    beq @no_row
    sec
    sbc a:M7S_LAST_TY
    and #WORLD_WRAP_MASK
    cmp #(WORLD_T_TILES / 2)
    bcs @row_north
    ; --- SOUTH (moving down): step last_ty forward, lead = last_ty+HALF ---
    cmp #(M7S_MAX + 1)
    bcc :+
    lda #M7S_MAX
:   sta a:M7S_ROW_COUNT
    sta a:M7S_SCR_LOOP
    ldy #0
@row_south_loop:
    lda a:M7S_LAST_TY
    inc
    and #WORLD_WRAP_MASK
    sta a:M7S_LAST_TY
    clc
    adc #(M7S_HALF - 1)   ; leading fwd edge = last + (HALF-1) = window bottom/right
    and #WORLD_WRAP_MASK            ; A = world row to stream
    jsr _m7s_stage_row              ; reads row A, stages into slot Y
    iny
    iny
    lda a:M7S_SCR_LOOP
    dec
    sta a:M7S_SCR_LOOP
    bne @row_south_loop
    bra @no_row
@row_north:
    lda a:M7S_LAST_TY
    sec
    sbc a:M7S_CAM_TY
    and #WORLD_WRAP_MASK
    cmp #(M7S_MAX + 1)
    bcc :+
    lda #M7S_MAX
:   sta a:M7S_ROW_COUNT
    sta a:M7S_SCR_LOOP
    ldy #0
@row_north_loop:
    lda a:M7S_LAST_TY
    dec
    and #WORLD_WRAP_MASK
    sta a:M7S_LAST_TY
    sec
    sbc #M7S_HALF   ; leading rev edge = last - HALF = window top/left
    and #WORLD_WRAP_MASK
    jsr _m7s_stage_row
    iny
    iny
    lda a:M7S_SCR_LOOP
    dec
    sta a:M7S_SCR_LOOP
    bne @row_north_loop
@no_row:
    plb                             ; restore caller DB
    rts

; =============================================================================
; _m7s_stage_row — read world row A from flat ROM, stage 128 tile-ids into
; M7S_ROW_BUF slot Y at VRAM-wrapped column positions; record the row's VRAM
; word address into M7S_ROW_VADDR[Y].
; In:  A16/I16. A = world row (0..WORLD-1). Y = slot index (0,2,4,..14).
; Out: M7S_ROW_BUF + (Y*64) filled; M7S_ROW_VADDR,Y = (row & $7F) * 128.
; Clobbers A, X, ES_M7S_PTR, ES_M7S_TMP+? (uses stack to preserve Y).
; =============================================================================
_m7s_stage_row:
    .a16
    .i16
    ; --- record VRAM word address for this row: (row & $7F) * 128 ----------
    sta a:M7S_SCR_SRC               ; stash world row (reused below for ptr)
    sty a:M7S_SCR_SLOT              ; stash slot index (word, 0,2,..)
    and #$007F
    .repeat 7
        asl
    .endrepeat                      ; * 128 (row stride in VRAM words)
    ldx a:M7S_SCR_SLOT
    sta a:M7S_ROW_VADDR, x          ; VADDR[slot] = (row & $7F) * 128
    ; --- dest buffer base = M7S_ROW_BUF + slot*64 -------------------------
    lda a:M7S_SCR_SLOT
    .repeat 6
        asl
    .endrepeat                      ; slot * 64
    clc
    adc #M7S_ROW_BUF
    sta a:M7S_SCR_DSTBASE
    ; --- 24-bit flat-ROM pointer for this row ------------------------------
    lda a:M7S_SCR_SRC               ; world row
    jsr _m7s_flat_row_ptr           ; ES_M7S_PTR = ptr to row start
    ; --- source start column = (cam_tx - (HALF-1)) & WRAP -----------------
    lda a:M7S_CAM_TX
    sec
    sbc #M7S_HALF   ; window start = cam - HALF
    and #WORLD_WRAP_MASK
    sta a:M7S_SCR_SRC               ; current source column (counts up)
    ldx #128                        ; iteration counter
@row_fill:
    ; Y = current source column for the flat-ROM read
    ldy a:M7S_SCR_SRC
    sep #$20
    .a8
    lda [<ES_M7S_PTR], y            ; tile-id byte from flat ROM
    sta a:M7S_SCR_TILE              ; hold tile-id (A8 — low byte only)
    rep #$20
    .a16
    ; dest WRAM offset = dest_base + (src_col & $7F)
    lda a:M7S_SCR_SRC
    and #$007F
    clc
    adc a:M7S_SCR_DSTBASE
    phx                             ; save loop counter (I16 -> 2 bytes)
    tax                             ; X = dest WRAM offset
    sep #$20
    .a8
    lda a:M7S_SCR_TILE
    sta f:$7E0000, x                ; store to wrapped buffer position
    rep #$20
    .a16
    plx                             ; restore loop counter
    ; advance source column (wrap)
    lda a:M7S_SCR_SRC
    inc
    and #WORLD_WRAP_MASK
    sta a:M7S_SCR_SRC
    dex
    bne @row_fill
    rts

; =============================================================================
; _m7s_stage_column — read world column A from flat ROM (one tile per row, all
; rows), stage 128 tile-ids into M7S_COL_BUF slot Y at VRAM-wrapped row
; positions; record the column's VRAM word address into M7S_COL_VADDR[Y].
; In:  A16/I16. A = world column (0..WORLD-1). Y = slot index (0,2,..14).
; Out: M7S_COL_BUF + (Y*64) filled; M7S_COL_VADDR,Y = (col & $7F).
; Clobbers A, X, Y, ES_M7S_PTR, M7S_SCR_*.
; =============================================================================
_m7s_stage_column:
    .a16
    .i16
    sty a:M7S_SCR_SLOT              ; slot index (word)
    and #WORLD_WRAP_MASK
    sta a:M7S_SCR_FIXCOL            ; fixed source column for all reads
    ; --- record VRAM word address: col & $7F (column write base) -----------
    and #$007F
    ldx a:M7S_SCR_SLOT
    sta a:M7S_COL_VADDR, x          ; VADDR[slot] = col & $7F
    ; --- dest buffer base = M7S_COL_BUF + slot*64 -------------------------
    lda a:M7S_SCR_SLOT
    .repeat 6
        asl
    .endrepeat
    clc
    adc #M7S_COL_BUF
    sta a:M7S_SCR_DSTBASE
    ; --- start source row = (cam_ty - (HALF-1)) & WRAP --------------------
    lda a:M7S_CAM_TY
    sec
    sbc #M7S_HALF   ; window start = cam - HALF
    and #WORLD_WRAP_MASK
    sta a:M7S_SCR_SRC               ; current source row (counts up)
    ldx #128
@col_fill:
    ; flat-ROM pointer for the current row
    lda a:M7S_SCR_SRC
    jsr _m7s_flat_row_ptr           ; ES_M7S_PTR = ptr to that row
    ; read tile [ptr], fixed source column
    ldy a:M7S_SCR_FIXCOL
    sep #$20
    .a8
    lda [<ES_M7S_PTR], y
    sta a:M7S_SCR_TILE
    rep #$20
    .a16
    ; dest WRAM offset = dest_base + (row & $7F)
    lda a:M7S_SCR_SRC
    and #$007F
    clc
    adc a:M7S_SCR_DSTBASE
    phx                             ; save loop counter
    tax                             ; X = dest WRAM offset
    sep #$20
    .a8
    lda a:M7S_SCR_TILE
    sta f:$7E0000, x
    rep #$20
    .a16
    plx
    ; advance source row (wrap)
    lda a:M7S_SCR_SRC
    inc
    and #WORLD_WRAP_MASK
    sta a:M7S_SCR_SRC
    dex
    bne @col_fill
    rts

; =============================================================================
; _m7s_flat_row_ptr — build the 24-bit flat-ROM pointer for world row A.
;   bank   = (row >> log2(WORLD_ROWS_PER_BANK)) + WORLD_FLAT_BANK_BASE
;   offset = $8000 + (row & (WORLD_ROWS_PER_BANK-1)) * WORLD_COLS_BYTES
; In:  A16. A = world row (0..WORLD-1).
; Out: ES_M7S_PTR (3 bytes) = 24-bit pointer to the row's first tile byte.
; Clobbers A.
;
; PARAMETRIC over the world layout (cross-checked vs tests/phase12/
; mode7_racing_12_8d.asm FLAT_ROW_ADDR): the bank-shift count and the per-row
; byte-stride multiply are derived from WORLD_ROWS_PER_BANK / WORLD_COLS_BYTES
; at ASSEMBLE time, so the SAME engine serves a 256-col world (128 rows/bank,
; 256 B/row -> >>7, *256) and a 512-col world (64 rows/bank, 512 B/row ->
; >>6, *512). _M7S_BANKSHIFT = log2(rows/bank); the *N multiply is xba (*256)
; plus one asl per doubling above 256 (so *512 = xba+asl).
; =============================================================================

; --- assemble-time: bank-shift count = log2(WORLD_ROWS_PER_BANK), and the
;     extra-asl count = log2(WORLD_COLS_BYTES / 256). ca65 has no recursive
;     value function, but a ca65 EXPRESSION can derive log2 of an exact power
;     of two without a loop: for an exact power of two p, the count of set bits
;     below p equals log2(p). We compute both explicitly from the two field
;     constants (each is an exact power of two: rows/bank in {64,128}; the
;     col-stride doubling in {1,2}). Use a portable bit-walk via .repeat. -----
; _M7S_BANKSHIFT: how many lsr to map a row index to its bank.
.if WORLD_ROWS_PER_BANK = 128
    _M7S_BANKSHIFT = 7
.elseif WORLD_ROWS_PER_BANK = 64
    _M7S_BANKSHIFT = 6
.elseif WORLD_ROWS_PER_BANK = 256
    _M7S_BANKSHIFT = 8
.elseif WORLD_ROWS_PER_BANK = 32
    _M7S_BANKSHIFT = 5
.else
    .error "mode7_stream: unsupported WORLD_ROWS_PER_BANK (expected 32/64/128/256)"
.endif
; _M7S_COLSHIFT: extra asl beyond xba (xba = *256). *512 needs 1 more, etc.
.if WORLD_COLS_BYTES = 256
    _M7S_COLSHIFT = 0
.elseif WORLD_COLS_BYTES = 512
    _M7S_COLSHIFT = 1
.elseif WORLD_COLS_BYTES = 1024
    _M7S_COLSHIFT = 2
.else
    .error "mode7_stream: unsupported WORLD_COLS_BYTES (expected 256/512/1024)"
.endif

_m7s_flat_row_ptr:
    .a16
    pha                             ; save row
    ; bank byte = (row >> log2(rows/bank)) + base
    .repeat _M7S_BANKSHIFT
        lsr
    .endrepeat                      ; A = row >> log2(WORLD_ROWS_PER_BANK)
    clc
    adc #WORLD_FLAT_BANK_BASE
    sep #$20
    .a8
    sta f:ES_M7S_PTR+2              ; bank byte
    rep #$20
    .a16
    pla                             ; row
    and #(WORLD_ROWS_PER_BANK - 1)  ; row & (rows/bank - 1)
    xba                             ; * 256
    .repeat _M7S_COLSHIFT
        asl                         ; * (WORLD_COLS_BYTES/256) more (=*2 for 512)
    .endrepeat
    clc
    adc #$8000                      ; + LoROM bank base
    sta f:ES_M7S_PTR                ; lo16
    rts
