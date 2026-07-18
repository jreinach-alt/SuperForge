; =============================================================================
; collision_engine.asm — Phase 4A.5 Collision Detection Engine
; =============================================================================
; Provides AABB overlap (col_box), point-in-box (col_point), and tile flag
; lookup (col_map) for game code via the engine-call convention.
;
; All collision math uses raw 16-bit integer coordinates (low 16 bits of each
; 4-byte API block parameter slot). Comparisons are signed for col_box /
; col_point, unsigned for col_map. col_map's tile coords are derived from
; pixel coords by `pixel >> 3` and bounds-checked against TILEMAP_WIDTH /
; HEIGHT_BG{n} (1 byte each, 0..255 tiles per axis).
;
; col_map history: prior to the engine col_map 768 sprint
; (docs/sprints/engine_col_map_768_investigation.md) col_map read its
; parameters as 8.8 fixed-point, capping queryable world coords at 256 px and
; hardcoding row stride to ×32. The current implementation reads raw 16-bit
; ints (matching col_box / col_point) and computes row stride dynamically
; from TILEMAP_WIDTH_BG{n} via SNES hardware multiply, supporting 32-, 64-,
; and 128-wide tilemaps.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
;
; Cross-ref: engine_state.inc, superforge_spec_v0.3.md §col_box/col_point/col_map
; =============================================================================

; =============================================================================
; engine_col_box — AABB overlap test
; =============================================================================
; Params (via API block, 4 bytes each, integer value = low word at +$00):
;   API_BLOCK_BASE + $00: x1 (box A left)
;   API_BLOCK_BASE + $04: y1 (box A top)
;   API_BLOCK_BASE + $08: w1 (box A width)
;   API_BLOCK_BASE + $0C: h1 (box A height)
;   API_BLOCK_BASE + $10: x2 (box B left)
;   API_BLOCK_BASE + $14: y2 (box B top)
;   API_BLOCK_BASE + $18: w2 (box B width)
;   API_BLOCK_BASE + $1C: h2 (box B height)
;
; Returns: 1 (true) if boxes overlap, 0 (false) if not.
;
; Algorithm (AABB separation test):
;   if x1 >= x2 + w2 then no overlap
;   if x2 >= x1 + w1 then no overlap
;   if y1 >= y2 + h2 then no overlap
;   if y2 >= y1 + h1 then no overlap
;   else overlap
;
; Uses integer value (low word) of each 4-byte param slot.
; ~60-80 cycles for the comparison logic.
; =============================================================================
.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif

engine_col_box:
    .a16
    .i16
    ; Read integer values (low word at +$00 within each 4-byte param slot)
    ; x1=+$00, y1=+$04, w1=+$08, h1=+$0C, x2=+$10, y2=+$14, w2=+$18, h2=+$1C

    ; Test 1: x1 >= x2 + w2 → no overlap
    ; Signed comparison via subtraction: (x2+w2) - x1 <= 0 means no overlap
    lda API_BLOCK_BASE + $10        ; x2
    clc
    adc API_BLOCK_BASE + $18        ; + w2
    sec
    sbc API_BLOCK_BASE + $00        ; (x2+w2) - x1
    beq @no_overlap                 ; equal = touching = no overlap
    bmi @no_overlap                 ; negative = x1 > x2+w2

    ; Test 2: x2 >= x1 + w1 → no overlap
    lda API_BLOCK_BASE + $00        ; x1
    clc
    adc API_BLOCK_BASE + $08        ; + w1
    sec
    sbc API_BLOCK_BASE + $10        ; (x1+w1) - x2
    beq @no_overlap
    bmi @no_overlap

    ; Test 3: y1 >= y2 + h2 → no overlap
    lda API_BLOCK_BASE + $14        ; y2
    clc
    adc API_BLOCK_BASE + $1C        ; + h2
    sec
    sbc API_BLOCK_BASE + $04        ; (y2+h2) - y1
    beq @no_overlap
    bmi @no_overlap

    ; Test 4: y2 >= y1 + h1 → no overlap
    lda API_BLOCK_BASE + $04        ; y1
    clc
    adc API_BLOCK_BASE + $0C        ; + h1
    sec
    sbc API_BLOCK_BASE + $14        ; (y1+h1) - y2
    beq @no_overlap
    bmi @no_overlap

    ; All tests passed → overlap!
    lda #$0001
    rts

@no_overlap:
    lda #$0000
    rts


; =============================================================================
; engine_col_point — Point-in-box test
; =============================================================================
; Params (via API block, integer value = low word at +$00 of each slot):
;   API_BLOCK_BASE + $00: px (point x)
;   API_BLOCK_BASE + $04: py (point y)
;   API_BLOCK_BASE + $08: bx (box left)
;   API_BLOCK_BASE + $0C: by (box top)
;   API_BLOCK_BASE + $10: bw (box width)
;   API_BLOCK_BASE + $14: bh (box height)
;
; Returns: 1 if point inside box, 0 if outside.
; Left/top edges inclusive, right/bottom edges exclusive.
;
; Algorithm:
;   if px < bx then false
;   if px >= bx + bw then false
;   if py < by then false
;   if py >= by + bh then false
;   else true
; =============================================================================
engine_col_point:
    .a16
    .i16

    ; Test 1: px < bx → outside
    lda API_BLOCK_BASE + $00        ; px
    sec
    sbc API_BLOCK_BASE + $08        ; px - bx
    bmi @point_outside              ; px < bx

    ; Test 2: px >= bx + bw → outside
    lda API_BLOCK_BASE + $08        ; bx
    clc
    adc API_BLOCK_BASE + $10        ; bx + bw
    sec
    sbc API_BLOCK_BASE + $00        ; (bx+bw) - px
    beq @point_outside              ; px == bx+bw (right edge exclusive)
    bmi @point_outside              ; px > bx+bw

    ; Test 3: py < by → outside
    lda API_BLOCK_BASE + $04        ; py
    sec
    sbc API_BLOCK_BASE + $0C        ; py - by
    bmi @point_outside              ; py < by

    ; Test 4: py >= by + bh → outside
    lda API_BLOCK_BASE + $0C        ; by
    clc
    adc API_BLOCK_BASE + $14        ; by + bh
    sec
    sbc API_BLOCK_BASE + $04        ; (by+bh) - py
    beq @point_outside              ; py == by+bh (bottom edge exclusive)
    bmi @point_outside              ; py > by+bh

    ; All tests passed → inside!
    lda #$0001
    rts

@point_outside:
    lda #$0000
    rts


; =============================================================================
; engine_col_map — Tile flag lookup for terrain collision
; =============================================================================
; Params (via API block, raw 16-bit integer values — same convention as
; col_box / col_point):
;   API_BLOCK_BASE + $00: x (world pixel X, 0..8191)
;   API_BLOCK_BASE + $04: y (world pixel Y, 0..8191)
;   API_BLOCK_BASE + $08: layer (1, 2, or 3)
;   API_BLOCK_BASE + $0C: flag (0..7, bit index to test)
;
; Returns: 1 if the specified flag bit is set at the tile position, 0 otherwise.
;          Out-of-bounds positions (tile_x ≥ TILEMAP_WIDTH_BGn or tile_y ≥
;          TILEMAP_HEIGHT_BGn) return 0. Invalid layers return 0.
;
; Algorithm:
;   1. Convert world coords to tile coords: tile = pixel >> 3 (8 px / tile).
;      Under raw 16-bit pixel inputs the tile coord can reach 13 bits — but
;      tilemap dims (1 byte each) cap practical reach at 0..255 tiles per
;      axis. Out-of-bounds returns 0.
;   2. Bounds check against TILEMAP_WIDTH_BGn / TILEMAP_HEIGHT_BGn.
;   3. Compute byte offset into the layer's shadow tilemap. Row stride is
;      derived from TILEMAP_WIDTH_BGn (supports 32, 64, 128 wide tilemaps).
;   4. Read tile word from shadow, mask to 10-bit tile ID.
;   5. Look up flag byte at FLAG_TABLE_BGn[tile_id & $FF]. (Tile IDs ≥256
;      wrap into the low 8 bits of the index — templates must keep distinct
;      flagged tile IDs ≤255 to avoid collisions.)
;   6. Test the requested bit.
;
; History: prior to the 768-px-platformer engine sprint, x/y/layer/flag were
; read as 8.8 fixed-point (using `xba`/`and #$00FF` to extract the integer
; byte). That capped queryable world coords at 256 px per axis and forced
; templates to encode integers as `pixel * 256`. The current contract reads
; raw 16-bit ints, matching col_box/col_point.
;
; Cycle cost: ~30-45 cycles (depends on tilemap width branch).
; =============================================================================
engine_col_map:
    .a16
    .i16

    ; --- Extract tile coordinates from raw 16-bit pixel coords ---
    ; tile = pixel >> 3 (8 px per tile). Result fits in 13 bits.
    lda API_BLOCK_BASE + $00        ; x (16-bit pixel)
    lsr                             ; / 2
    lsr                             ; / 4
    lsr                             ; / 8 → tile_x (0..8191)
    pha                             ; save tile_x on stack

    lda API_BLOCK_BASE + $04        ; y (16-bit pixel)
    lsr
    lsr
    lsr                             ; tile_y
    pha                             ; save tile_y on stack

    ; --- Determine layer and select flag table + tilemap ---
    lda API_BLOCK_BASE + $08        ; layer (raw 16-bit int)

    cmp #$0001
    bne @not_bg1
    jmp @layer_bg1
@not_bg1:
    .a16
    cmp #$0002
    bne @not_bg2
    jmp @layer_bg2
@not_bg2:
    .a16
    cmp #$0003
    bne @not_bg3
    jmp @layer_bg3
@not_bg3:
    .a16

    ; Invalid layer → return 0
    pla                             ; discard tile_y
    pla                             ; discard tile_x
    lda #$0000
    rts

; -----------------------------------------------------------------------------
; Per-layer blocks below share the same shape:
;   1. Pull tile_y from stack, bounds-check vs TILEMAP_HEIGHT_BGn (zero-extended
;      to 16-bit so tile_y ≥ 256 is rejected).
;   2. Peek tile_x, bounds-check vs TILEMAP_WIDTH_BGn.
;   3. Compute byte offset = tile_y × (TILEMAP_WIDTH_BGn × 2) + tile_x × 2 via
;      SNES hardware multiply. Width × 2 stays ≤ 256 for all supported widths
;      (32, 64, 128) so the 8-bit×8-bit multiply works. Per layer the row
;      stride is computed dynamically — no hardcoded ×32 anymore.
;   4. Read tile word from SHADOW_BGn_TILEMAP, mask $03FF.
;   5. Index FLAG_TABLE_BGn[tile_id & $FF] for the flag byte.
;
; WIDTH-RISK: each layer block enters A16/I16 and exits via @test_flag_bit
; with A16. The hardware-multiply path uses brief A8 windows around $4202
; / $4203 stores; each is paired with `.a8` and bracketed by `rep #$20` /
; `.a16` on exit. OOB exits go through @out_of_bounds_a8 (A8) or
; @out_of_bounds_pop{1,2} (A16); branches keep the entry width consistent.
; -----------------------------------------------------------------------------

@layer_bg1:
    .a16
    .i16

    ; --- Sprint B (Phase 17 streaming integration), updated D-5 (Bug B) ---
    ; When STREAM_ACTIVE != 0 the BG1 streaming engine maintains
    ; SHADOW_BG1_TILEMAP as a 64-col ring mirror keyed by
    ; (world_col & $3F). col_map must wrap tile_x into that ring
    ; instead of bounds-failing at the 64-col edge. We rewrite tile_x
    ; on the stack here (before any bounds check) so all downstream
    ; logic sees a value in 0..63 — bounds-check vs TILEMAP_WIDTH_BG1
    ; (=64 in streaming mode) then passes trivially, and the
    ; byte-offset compute targets the correct ring slot.
    ; Static (non-streaming) callers leave STREAM_ACTIVE = 0 and see
    ; the original behavior unchanged.
    ;
    ; D-3 finding (now closed by D-5 Bug B fix): pre-D-5 the SHADOW was
    ; 32×32 with mask `& $1F`. Any query at world tile col [32..63]
    ; aliased back to slot [0..31] which still held boot-time col 0..31
    ; data (the streaming engine only forward-streamed cols 64+, never
    ; populating 32..63). Net effect: col_map returned wrong data for
    ; the cadence_3 (tx=38) and rest (tx=48) platforms. With the
    ; SHADOW now a 64-col ring, the streaming-init boot mirrors all 64
    ; cols and `& $3F` lands queries at the correct shadow slot.
    ;
    ; WIDTH-RISK: brief sep #$20 / rep #$20 toggle before main bounds
    ; checks. All branch targets carry .a8/.a16 annotations matching
    ; runtime.
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_ACTIVE
    beq @bg1_no_stream_wrap
    rep #$20
    .a16
    lda $03, s                      ; peek tile_x (under tile_y on stack)
    and #$003F                      ; ring slot 0..63 (Phase 17 Sprint D-5)
    sta $03, s                      ; rewrite tile_x in place
    sep #$20
    .a8
@bg1_no_stream_wrap:
    .a8                              ; ; WIDTH-LINT: ok — branch target reached A8/I16
    rep #$20
    .a16

    ; Bounds check — tile_y vs TILEMAP_HEIGHT_BG1
    pla                             ; tile_y (16-bit)
    cmp #$0100                      ; if tile_y >= 256, definitely OOB
    bcc :+
    jmp @out_of_bounds_pop1
:
    sep #$20
    .a8
    cmp TILEMAP_HEIGHT_BG1
    bcc :+
    jmp @out_of_bounds_pop1_a8      ; tile_y_lo >= height → OOB
:
    rep #$20
    .a16
    pha                             ; re-save tile_y

    ; Bounds check — tile_x vs TILEMAP_WIDTH_BG1
    lda $03, s                      ; peek tile_x (below tile_y on stack)
    cmp #$0100
    bcc :+
    jmp @out_of_bounds_pop2
:
    sep #$20
    .a8
    cmp TILEMAP_WIDTH_BG1
    bcc :+
    jmp @out_of_bounds_pop2_a8      ; tile_x_lo >= width → OOB
:
    rep #$20
    .a16

    ; Compute tilemap byte offset:
    ;   row_bytes = TILEMAP_WIDTH_BG1 × 2 (8-bit × 8-bit, ≤256)
    ;   offset    = tile_y × row_bytes + tile_x × 2
    ; Use SNES hardware multiply at $4202/$4203/$4216 (8-bit × 8-bit → 16).
    pla                             ; tile_y (16-bit)
    sep #$20
    .a8
    sta a:$4202                     ; WRMPYA = tile_y_lo (tile_y < 256, hi=0)
    lda TILEMAP_WIDTH_BG1
    asl                             ; A = width × 2 (row stride in bytes)
    sta a:$4203                     ; WRMPYB = row stride; multiply starts
    ; ~8 cycles for the multiply to settle; the next read provides the delay.
    rep #$20
    .a16
    lda a:$4216                     ; A = tile_y × row_bytes (16-bit product)
    sta $A0                        ; temp: row byte offset

    pla                             ; tile_x (16-bit, low 8 bits significant)
    and #$00FF
    asl                             ; tile_x × 2 (2 bytes per shadow entry)
    clc
    adc $A0                         ; + row offset

    ; Read tile ID from BG1 shadow tilemap.
    tax                             ; WIDTH-LINT: ok — A and X both A16/I16; X is the tilemap byte offset (≤16 KB)
    lda f:$7E0000 + SHADOW_BG1_TILEMAP, x
    and #$03FF                      ; mask to 10-bit tile ID

    ; Flag table is 256 bytes per layer — wrap tile IDs ≥ 256 into low byte.
    and #$00FF
    tax                             ; WIDTH-LINT: ok — A is masked to $00FF before tax (zero-extended)

    ; Look up flag byte
    sep #$20
    .a8
    lda f:$7E0000 + FLAG_TABLE_BG1, x
    rep #$20
    .a16
    and #$00FF                      ; zero-extend flag byte
    jmp @test_flag_bit

@layer_bg2:
    .a16
    .i16
    pla                             ; tile_y
    cmp #$0100
    bcc :+
    jmp @out_of_bounds_pop1
:
    sep #$20
    .a8
    cmp TILEMAP_HEIGHT_BG2
    bcc :+
    jmp @out_of_bounds_pop1_a8
:
    rep #$20
    .a16
    pha

    lda $03, s
    cmp #$0100
    bcc :+
    jmp @out_of_bounds_pop2
:
    sep #$20
    .a8
    cmp TILEMAP_WIDTH_BG2
    bcc :+
    jmp @out_of_bounds_pop2_a8
:
    rep #$20
    .a16

    pla                             ; tile_y
    sep #$20
    .a8
    sta a:$4202
    lda TILEMAP_WIDTH_BG2
    asl
    sta a:$4203
    rep #$20
    .a16
    lda a:$4216
    sta $A0

    pla
    and #$00FF
    asl
    clc
    adc $A0

    tax                             ; WIDTH-LINT: ok — A and X both A16/I16
    lda f:$7E0000 + SHADOW_BG2_TILEMAP, x
    and #$03FF
    and #$00FF
    tax                             ; WIDTH-LINT: ok — A masked to $00FF before tax

    sep #$20
    .a8
    lda f:$7E0000 + FLAG_TABLE_BG2, x
    rep #$20
    .a16
    and #$00FF
    jmp @test_flag_bit

@layer_bg3:
    .a16
    .i16
    pla                             ; tile_y
    cmp #$0100
    bcc :+
    jmp @out_of_bounds_pop1
:
    sep #$20
    .a8
    cmp TILEMAP_HEIGHT_BG3
    bcc :+
    jmp @out_of_bounds_pop1_a8
:
    rep #$20
    .a16
    pha

    lda $03, s
    cmp #$0100
    bcc :+
    jmp @out_of_bounds_pop2
:
    sep #$20
    .a8
    cmp TILEMAP_WIDTH_BG3
    bcc :+
    jmp @out_of_bounds_pop2_a8
:
    rep #$20
    .a16

    pla
    sep #$20
    .a8
    sta a:$4202
    lda TILEMAP_WIDTH_BG3
    asl
    sta a:$4203
    rep #$20
    .a16
    lda a:$4216
    sta $A0

    pla
    and #$00FF
    asl
    clc
    adc $A0

    tax                             ; WIDTH-LINT: ok — A and X both A16/I16
    lda f:$7E0000 + SHADOW_BG3_TILEMAP, x
    and #$03FF
    and #$00FF
    tax                             ; WIDTH-LINT: ok — A masked to $00FF before tax

    sep #$20
    .a8
    lda f:$7E0000 + FLAG_TABLE_BG3, x
    rep #$20
    .a16
    and #$00FF
    jmp @test_flag_bit

; OOB exits — A8 entry path needs to restore A16 before the shared pop-and-rts
; sequence, or stack discipline diverges. WIDTH-RISK: split entry widths.
@out_of_bounds_pop2_a8:
    .a8
    rep #$20
    .a16
    bra @out_of_bounds_pop2
@out_of_bounds_pop1_a8:
    .a8
    rep #$20
    .a16
    bra @out_of_bounds_pop1

@out_of_bounds_pop2:
    .a16
    pla                             ; discard tile_y
@out_of_bounds_pop1:
    .a16
    pla                             ; discard tile_x
    lda #$0000
    rts

@test_flag_bit:
    ; A = flag byte (low 8 bits, high byte zero), test the requested bit.
    ; flag param (API_BLOCK_BASE + $0C) is the raw 16-bit bit index 0-7.
    .a16
    sta $A0                        ; save flag byte
    lda API_BLOCK_BASE + $0C        ; flag bit index (raw int)
    and #$0007                      ; clamp to 0-7
    tax                             ; WIDTH-LINT: ok — A masked to $0007 before tax

    lda $A0                         ; flag byte
    ; Shift right by X to get the target bit into bit 0
    cpx #$0000
    beq @shift_done
@shift_loop:
    .a16
    lsr
    dex
    bne @shift_loop
@shift_done:
    .a16
    and #$0001                      ; isolate bit 0
    rts
