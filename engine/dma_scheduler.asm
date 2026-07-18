; =============================================================================
; dma_scheduler.asm — DMA Scheduler (E06) for SuperForge Engine
; =============================================================================
; Main-thread API for managing the VBlank DMA transfer queue.
;
; The queue lives at DMA_QUEUE_BASE ($0200), holds up to 32 entries (8 bytes
; each), sorted by priority (0 = highest). The NMI handler (Phase 3) drains
; the queue during VBlank.
;
; Calling convention (main thread, DP=$0000, DB=$00):
;   dma_queue_add:  Fill DMA_STAGE_* variables, then JSR dma_queue_add.
;   dma_queue_clear: JSR dma_queue_clear (zeros count).
;   dma_queue_signal: JSR dma_queue_signal (sets ready flag for NMI).
;
; Staging area (WRAM, fill before calling dma_queue_add):
;   $0548  DMA_STAGE_PRIORITY   1 byte   Priority (0=highest, 5=lowest)
;   $0549  DMA_STAGE_DMAP       1 byte   DMA channel parameters
;   $054A  DMA_STAGE_BBAD       1 byte   PPU destination register
;   $054B  DMA_STAGE_SRC_LO     2 bytes  Source address low 16 bits
;   $054D  DMA_STAGE_SRC_BANK   1 byte   Source bank
;   $054E  DMA_STAGE_SIZE       2 bytes  Transfer size (bytes)
;
; Scratch (WRAM, internal use):
;   $0550-$0555  6 bytes used by dma_queue_add insertion sort
;
; Prerequisites: engine_state.inc included, .p816/.smart set.
; Cross-ref: engine_state.inc, nmi_handler.asm (Phase 3)
; =============================================================================

; Staging area for dma_queue_add (WRAM, above engine temps)
DMA_STAGE_PRIORITY  = $0548     ; 1 byte
DMA_STAGE_DMAP      = $0549     ; 1 byte
DMA_STAGE_BBAD      = $054A     ; 1 byte
DMA_STAGE_SRC_LO    = $054B     ; 2 bytes
DMA_STAGE_SRC_BANK  = $054D     ; 1 byte
DMA_STAGE_SIZE      = $054E     ; 2 bytes

; --- dma_queue_add ---
; Insert the entry in DMA_STAGE_* into the queue, sorted by priority.
; Priority 0 goes first, priority 5 goes last.
; If queue is full (32 entries), the entry is silently dropped.
;
; Clobbers: A, X, Y. Expects 16-bit A and 16-bit X/Y.
dma_queue_add:
    rep #$30
    .a16
    .i16

    ; Check if queue is full
    lda NMI_DMA_QUEUE_COUNT
    cmp #DMA_QUEUE_MAX
    bcc @not_full
    rts                         ; Queue full, silently drop
@not_full:

    ; Validate: DMA transfer must not cross a 64KB bank boundary.
    ; End address = src_lo + size - 1; if this wraps past $FFFF,
    ; the transfer would read from the wrong bank on real hardware.
    lda DMA_STAGE_SRC_LO        ; source address low 16 bits
    clc
    adc DMA_STAGE_SIZE          ; A = src_lo + size
    bcs @bank_cross             ; carry set means crossed $FFFF boundary
    bra @bank_ok
@bank_cross:
    rts                         ; Silently drop — transfer crosses bank boundary
@bank_ok:

    ; Find insertion point: scan from start, find first entry with
    ; priority > new entry's priority.
    sep #$20
    .a8
    lda DMA_STAGE_PRIORITY      ; New entry priority (8-bit)
    rep #$20
    .a16
    and #$00FF                  ; Zero-extend to 16-bit (high byte may be stale)
    sta @new_priority           ; Save for comparison

    ldx #$0000                  ; X = scan offset into queue
    lda NMI_DMA_QUEUE_COUNT
    beq @insert_at_x            ; Empty queue — insert at position 0

    ; Calculate end offset (count * 8)
    asl
    asl
    asl
    sta @end_offset

@scan_loop:
    cpx @end_offset
    bcs @insert_at_x            ; Reached end — insert here

    ; Compare priorities
    sep #$20
    .a8
    lda DMA_QUEUE_BASE + DMA_ENT_PRIORITY, x
    rep #$20
    .a16
    and #$00FF
    cmp @new_priority
    bcs @insert_at_x            ; Found entry with priority >= new → insert before it

    ; Advance to next entry
    txa
    clc
    adc #DMA_QUEUE_ENTRY_SZ
    tax
    bra @scan_loop

@insert_at_x:
    ; X = insertion offset. Shift entries from X to end right by 8 bytes.
    ; Shift from the end backward to avoid overwriting.
    lda NMI_DMA_QUEUE_COUNT
    asl
    asl
    asl
    tay                         ; Y = current end offset
    stx @insert_offset

@shift_loop:
    cpy @insert_offset
    beq @shift_done
    bcc @shift_done

    ; Copy entry at Y-8 to Y
    tya
    sec
    sbc #DMA_QUEUE_ENTRY_SZ
    tax                         ; X = source offset (Y - 8)

    ; Copy 8 bytes (4 x 16-bit words)
    lda DMA_QUEUE_BASE + 0, x
    sta DMA_QUEUE_BASE + 0, y
    lda DMA_QUEUE_BASE + 2, x
    sta DMA_QUEUE_BASE + 2, y
    lda DMA_QUEUE_BASE + 4, x
    sta DMA_QUEUE_BASE + 4, y
    lda DMA_QUEUE_BASE + 6, x
    sta DMA_QUEUE_BASE + 6, y

    ; Move Y back
    txa
    tay
    bra @shift_loop

@shift_done:
    ; Insert new entry at @insert_offset
    ldx @insert_offset

    ; Copy from staging area to queue
    sep #$20
    .a8
    lda DMA_STAGE_PRIORITY
    sta DMA_QUEUE_BASE + DMA_ENT_PRIORITY, x
    lda DMA_STAGE_DMAP
    sta DMA_QUEUE_BASE + DMA_ENT_DMAP, x
    lda DMA_STAGE_BBAD
    sta DMA_QUEUE_BASE + DMA_ENT_BBAD, x

    rep #$20
    .a16
    lda DMA_STAGE_SRC_LO
    sta DMA_QUEUE_BASE + DMA_ENT_SRC_LO, x

    sep #$20
    .a8
    lda DMA_STAGE_SRC_BANK
    sta DMA_QUEUE_BASE + DMA_ENT_SRC_BANK, x

    rep #$20
    .a16
    lda DMA_STAGE_SIZE
    sta DMA_QUEUE_BASE + DMA_ENT_SIZE, x

    ; Increment queue count
    inc NMI_DMA_QUEUE_COUNT

    rts

; Local variables (in ROM, read-only — ok since these are only used as scratch
; and are written before read in the same call frame)
; Actually, these need to be writable. Use WRAM.
@new_priority   = $0550         ; 2 bytes
@end_offset     = $0552         ; 2 bytes
@insert_offset  = $0554         ; 2 bytes


; --- dma_queue_clear ---
; Clear the DMA queue. Called at the start of each frame.
; Clobbers: A.
dma_queue_clear:
    rep #$20
    .a16
    stz NMI_DMA_QUEUE_COUNT
    rts


; --- dma_queue_signal ---
; Signal to the NMI handler that the queue is ready for processing.
; Call after all dma_queue_add calls for this frame.
; Clobbers: A.
dma_queue_signal:
    sep #$20
    .a8
    lda #$01
    sta NMI_DMA_READY
    rts
