; =============================================================================
; palette_engine.asm — Palette Engine for SuperForge
; =============================================================================
; Manages shadow CGRAM buffer and provides pal/pal_get/pal_reset/color/pal_cycle
; API functions for palette manipulation.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
; Cross-ref: engine_state.inc, dma_scheduler.asm
; =============================================================================

; --- Palette engine state constants (guard against missing engine_state.inc) ---
.ifndef ES_CGRAM_DIRTY_LO
ES_CGRAM_DIRTY_LO    = $40
ES_CGRAM_DIRTY_HI    = $41
ES_CGRAM_DIRTY_FLAG  = $42
ES_PAL_CYCLE_COUNT   = $43
CGRAM_DIRTY_LO       = $0140
CGRAM_DIRTY_HI       = $0141
CGRAM_DIRTY_FLAG     = $0142
PAL_CYCLE_COUNT      = $0143
.endif

; --- BG engine state (guard against missing definitions) ---
; ES_GFXMODE was relocated to WRAM extended — see engine_state.inc.
.ifndef ES_BG_TILEMAP_DIRTY
ES_BG_TILEMAP_DIRTY  = $3C
ES_BG_SHADOW_DIRTY   = $3E
.endif

; --- Shadow CGRAM addresses (WRAM bank $7E) ---
.ifndef SHADOW_CGRAM
SHADOW_CGRAM        = $BA00
PAL_CYCLE_DESCS     = $BC00
PAL_ROM_DEFAULTS    = $BD00
.endif

; --- API parameter block addresses ---
.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif
.ifndef ENGINE_A0
ENGINE_A0       = $40
.endif

; --- Palette cycle descriptor offsets ---
PAL_DESC_ACTIVE     = 0
PAL_DESC_START      = 1
PAL_DESC_COUNT      = 2
PAL_DESC_SPEED      = 3
PAL_DESC_FRAMECNT   = 4
PAL_DESC_RESERVED   = 5
PAL_DESC_COLORS     = 6
PAL_DESC_SIZE       = 64
PAL_MAX_CYCLES      = 4

; Scratch for palette engine
PAL_SCRATCH         = $0560     ; 4 bytes scratch


; =============================================================================
; engine_pal — Set one palette color in shadow CGRAM
; =============================================================================
; Params: $60=index, $64=r, $68=g, $6C=b (all 0-31)
; Computes: color = (b<<10)|(g<<5)|r, stores in shadow CGRAM
; =============================================================================
engine_pal:
    rep #$30
    .a16
    .i16

    ; Compute color: (b<<10)|(g<<5)|r
    lda API_BLOCK_BASE + 12     ; b
    and #$001F
    .repeat 10
        asl
    .endrep
    sta PAL_SCRATCH

    lda API_BLOCK_BASE + 8      ; g
    and #$001F
    .repeat 5
        asl
    .endrep
    ora PAL_SCRATCH

    pha                         ; save partial color
    lda API_BLOCK_BASE + 4      ; r
    and #$001F
    tsx
    ora $01, x                  ; combine with partial on stack
    sta $01, x                  ; update stack value
    pla                         ; A = final color
    sta PAL_SCRATCH             ; save for store

    ; Calculate CGRAM offset = index * 2
    lda API_BLOCK_BASE + 0
    and #$00FF
    asl
    tax

    ; Set DB=$7E, store color
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16
    lda PAL_SCRATCH
    sta SHADOW_CGRAM, x
    plb                         ; restore DB

    ; Update dirty tracking
    sep #$20
    .a8
    lda CGRAM_DIRTY_FLAG
    bne @pal_update_range
    ; First dirty entry — set both LO and HI to this index
    lda API_BLOCK_BASE + 0
    sta CGRAM_DIRTY_LO
    sta CGRAM_DIRTY_HI
    bra @pal_set_flag

@pal_update_range:
    ; Update LO = min(LO, index)
    lda API_BLOCK_BASE + 0
    cmp CGRAM_DIRTY_LO
    bcs @pal_check_hi
    sta CGRAM_DIRTY_LO
@pal_check_hi:
    ; Update HI = max(HI, index)
    lda API_BLOCK_BASE + 0
    cmp CGRAM_DIRTY_HI
    bcc @pal_set_flag
    beq @pal_set_flag
    sta CGRAM_DIRTY_HI

@pal_set_flag:
    lda #$01
    sta CGRAM_DIRTY_FLAG
    rep #$20
    .a16
    rts


; =============================================================================
; engine_pal_get — Read palette color from shadow CGRAM
; =============================================================================
; Params: $60=index. Returns raw 15-bit color in ENGINE_A0.
; =============================================================================
engine_pal_get:
    rep #$30
    .a16
    .i16
    lda API_BLOCK_BASE + 0
    and #$00FF
    asl
    tax

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16
    lda SHADOW_CGRAM, x
    sta ENGINE_A0
    plb

    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_pal_reset — Copy ROM defaults backup to shadow CGRAM
; =============================================================================
engine_pal_reset:
    rep #$30
    .a16
    .i16

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ldx #$0000
@reset_loop:
    lda PAL_ROM_DEFAULTS, x
    sta SHADOW_CGRAM, x
    inx
    inx
    cpx #$0200
    bne @reset_loop

    plb

    sep #$20
    .a8
    stz CGRAM_DIRTY_LO
    lda #$FF
    sta CGRAM_DIRTY_HI
    lda #$01
    sta CGRAM_DIRTY_FLAG
    rep #$20
    .a16
    rts


; =============================================================================
; engine_color — Compute SNES color from r, g, b
; =============================================================================
; Params: $60=r, $64=g, $68=b. Returns in ENGINE_A0.
; =============================================================================
engine_color:
    rep #$30
    .a16
    .i16

    lda API_BLOCK_BASE + 8      ; b
    and #$001F
    .repeat 10
        asl
    .endrep
    sta ENGINE_A0

    lda API_BLOCK_BASE + 4      ; g
    and #$001F
    .repeat 5
        asl
    .endrep
    ora ENGINE_A0
    sta ENGINE_A0

    lda API_BLOCK_BASE + 0      ; r
    and #$001F
    ora ENGINE_A0
    sta ENGINE_A0

    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_pal_cycle — Start palette cycling or stop all
; =============================================================================
; Params: $60=start, $64=count, $68=speed
; If count=0 AND speed=0: stop all. Otherwise: set up cycling.
; =============================================================================
engine_pal_cycle:
    rep #$30
    .a16
    .i16

    ; Check stop-all condition
    lda API_BLOCK_BASE + 4      ; count
    ora API_BLOCK_BASE + 8      ; speed
    bne @pc_setup

    ; --- Stop all cycles ---
    sep #$20
    .a8
    stz PAL_CYCLE_COUNT
    phb
    lda #$7E
    pha
    plb
    ; Clear active flag on all 4 descriptors
    stz PAL_CYCLE_DESCS + (0 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    stz PAL_CYCLE_DESCS + (1 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    stz PAL_CYCLE_DESCS + (2 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    stz PAL_CYCLE_DESCS + (3 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    plb
    rep #$20
    .a16
    rts

@pc_setup:
    ; Set DB=$7E
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ; Search for existing descriptor with same start or empty slot
    ; Check descriptor 0
    sep #$20
    .a8
    lda PAL_CYCLE_DESCS + (0 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    beq @pc_use_0
    lda PAL_CYCLE_DESCS + (0 * PAL_DESC_SIZE) + PAL_DESC_START
    cmp API_BLOCK_BASE + 0
    beq @pc_use_0
    ; Check descriptor 1
    lda PAL_CYCLE_DESCS + (1 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    beq @pc_use_1
    lda PAL_CYCLE_DESCS + (1 * PAL_DESC_SIZE) + PAL_DESC_START
    cmp API_BLOCK_BASE + 0
    beq @pc_use_1
    ; Check descriptor 2
    lda PAL_CYCLE_DESCS + (2 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    beq @pc_use_2
    lda PAL_CYCLE_DESCS + (2 * PAL_DESC_SIZE) + PAL_DESC_START
    cmp API_BLOCK_BASE + 0
    beq @pc_use_2
    ; Check descriptor 3
    lda PAL_CYCLE_DESCS + (3 * PAL_DESC_SIZE) + PAL_DESC_ACTIVE
    beq @pc_use_3
    lda PAL_CYCLE_DESCS + (3 * PAL_DESC_SIZE) + PAL_DESC_START
    cmp API_BLOCK_BASE + 0
    beq @pc_use_3
    ; No slot available
    plb
    rep #$20
    .a16
    rts

@pc_use_0:
    rep #$20
    .a16
    ldx #(0 * PAL_DESC_SIZE)
    jmp @pc_fill
@pc_use_1:
    rep #$20
    .a16
    ldx #(1 * PAL_DESC_SIZE)
    jmp @pc_fill
@pc_use_2:
    rep #$20
    .a16
    ldx #(2 * PAL_DESC_SIZE)
    jmp @pc_fill
@pc_use_3:
    rep #$20
    .a16
    ldx #(3 * PAL_DESC_SIZE)
    ; fall through to @pc_fill

@pc_fill:
    ; X = descriptor base offset
    ; Check if was inactive (for count update)
    sep #$20
    .a8
    lda PAL_CYCLE_DESCS + PAL_DESC_ACTIVE, x
    pha                         ; push old active state (0=was inactive)

    ; Fill descriptor fields
    lda #$01
    sta PAL_CYCLE_DESCS + PAL_DESC_ACTIVE, x
    lda API_BLOCK_BASE + 0
    sta PAL_CYCLE_DESCS + PAL_DESC_START, x
    lda API_BLOCK_BASE + 4
    sta PAL_CYCLE_DESCS + PAL_DESC_COUNT, x
    lda API_BLOCK_BASE + 8
    sta PAL_CYCLE_DESCS + PAL_DESC_SPEED, x
    sta PAL_CYCLE_DESCS + PAL_DESC_FRAMECNT, x
    stz PAL_CYCLE_DESCS + PAL_DESC_RESERVED, x
    rep #$20
    .a16

    ; Copy current colors from shadow CGRAM to descriptor saved_colors
    ; src = SHADOW_CGRAM + start * 2, dest = descriptor + PAL_DESC_COLORS
    phx                         ; save descriptor offset
    lda API_BLOCK_BASE + 0
    and #$00FF
    asl
    tay                         ; Y = source offset in CGRAM

    ; dest = X + PAL_DESC_COLORS in PAL_CYCLE_DESCS
    txa
    clc
    adc #PAL_DESC_COLORS
    tax                         ; X = dest offset in PAL_CYCLE_DESCS

    lda API_BLOCK_BASE + 4
    and #$00FF
    asl
    sta PAL_SCRATCH             ; byte count to copy
    beq @pc_copy_done

    ; Copy loop using PAL_SCRATCH+2 as counter
    stz PAL_SCRATCH + 2         ; bytes copied = 0
@pc_copy_loop:
    lda SHADOW_CGRAM, y
    sta PAL_CYCLE_DESCS, x
    iny
    iny
    inx
    inx
    lda PAL_SCRATCH + 2
    clc
    adc #$0002
    sta PAL_SCRATCH + 2
    cmp PAL_SCRATCH
    bcc @pc_copy_loop

@pc_copy_done:
    plx                         ; restore descriptor offset

    ; Update cycle count if new activation
    sep #$20
    .a8
    pla                         ; get old active state from stack
    bne @pc_done                ; was already active, no count change
    inc PAL_CYCLE_COUNT
@pc_done:
    plb                         ; restore DB
    rep #$20
    .a16
    rts


; =============================================================================
; engine_pal_cycle_tick — Process one frame of palette cycling
; =============================================================================
; Called once per frame. For each active descriptor: decrement counter,
; when 0: rotate colors right, update shadow CGRAM, mark dirty.
; =============================================================================
engine_pal_cycle_tick:
    rep #$30
    .a16
    .i16

    ; Quick exit if no active cycles
    sep #$20
    .a8
    lda PAL_CYCLE_COUNT
    bne @tck_start
    rep #$20
    .a16
    rts

@tck_start:
    .a8                         ; A is 8-bit here (from sep #$20 before bne)
    ; Set DB=$7E
    phb
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ; Process all 4 descriptors
    ldx #(0 * PAL_DESC_SIZE)
    jsr _pal_tick_one
    ldx #(1 * PAL_DESC_SIZE)
    jsr _pal_tick_one
    ldx #(2 * PAL_DESC_SIZE)
    jsr _pal_tick_one
    ldx #(3 * PAL_DESC_SIZE)
    jsr _pal_tick_one

    plb                         ; restore DB
    rts


; =============================================================================
; _pal_tick_one — Tick a single descriptor (internal helper)
; =============================================================================
; X = descriptor byte offset. DB must be $7E.
; =============================================================================
_pal_tick_one:
    rep #$20
    .a16
    ; Check active
    sep #$20
    .a8
    lda PAL_CYCLE_DESCS + PAL_DESC_ACTIVE, x
    bne @pto_is_active
    jmp @pto_done               ; inactive: skip
@pto_is_active:

    ; Decrement frame counter
    lda PAL_CYCLE_DESCS + PAL_DESC_FRAMECNT, x
    dec
    sta PAL_CYCLE_DESCS + PAL_DESC_FRAMECNT, x
    beq @pto_do_rotate
    jmp @pto_done               ; counter not zero yet
@pto_do_rotate:

    ; --- Counter hit 0: rotate and reset ---
    lda PAL_CYCLE_DESCS + PAL_DESC_SPEED, x
    sta PAL_CYCLE_DESCS + PAL_DESC_FRAMECNT, x

    ; Calculate base = start_index * 2
    lda PAL_CYCLE_DESCS + PAL_DESC_START, x
    rep #$20
    .a16
    and #$00FF
    asl
    sta PAL_SCRATCH             ; base offset

    ; Get count
    sep #$20
    .a8
    lda PAL_CYCLE_DESCS + PAL_DESC_COUNT, x
    rep #$20
    .a16
    and #$00FF
    sta PAL_SCRATCH + 2         ; count

    ; Save X (descriptor offset), we need Y for color manipulation
    phx

    ; Calculate offset of last entry: base + (count-1)*2
    lda PAL_SCRATCH + 2         ; count
    dec
    asl                         ; (count-1)*2
    clc
    adc PAL_SCRATCH             ; base + (count-1)*2
    tay                         ; Y = last entry offset

    ; Save last color
    lda SHADOW_CGRAM, y
    pha                         ; save last_color on stack

    ; Shift all entries right by one (from last to second)
    ldx PAL_SCRATCH             ; X = base offset
@pto_shift:
    cpy PAL_SCRATCH             ; Y == base?
    beq @pto_shift_done
    dey
    dey
    lda SHADOW_CGRAM, y         ; load entry at Y
    iny
    iny
    sta SHADOW_CGRAM, y         ; store at Y+2
    dey
    dey
    bra @pto_shift

@pto_shift_done:
    ; Put saved last color in first position
    pla                         ; A = last_color
    ldx PAL_SCRATCH             ; X = base
    sta SHADOW_CGRAM, x

    ; Restore descriptor offset
    plx

    ; Mark dirty range
    sep #$20
    .a8
    lda PAL_CYCLE_DESCS + PAL_DESC_START, x
    ; Update LO
    pha
    lda CGRAM_DIRTY_FLAG
    beq @pto_first_dirty
    pla
    cmp CGRAM_DIRTY_LO
    bcs @pto_check_hi
    sta CGRAM_DIRTY_LO
    bra @pto_check_hi

@pto_first_dirty:
    pla
    sta CGRAM_DIRTY_LO
    ; Also set HI since first dirty
    clc
    adc PAL_CYCLE_DESCS + PAL_DESC_COUNT, x
    dec
    sta CGRAM_DIRTY_HI
    bra @pto_set_flag

@pto_check_hi:
    ; HI = max(HI, start + count - 1)
    lda PAL_CYCLE_DESCS + PAL_DESC_START, x
    clc
    adc PAL_CYCLE_DESCS + PAL_DESC_COUNT, x
    dec                         ; start + count - 1
    cmp CGRAM_DIRTY_HI
    bcc @pto_set_flag
    beq @pto_set_flag
    sta CGRAM_DIRTY_HI

@pto_set_flag:
    lda #$01
    sta CGRAM_DIRTY_FLAG

@pto_done:
    rep #$20
    .a16
    rts
