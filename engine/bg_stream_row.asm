; =============================================================================
; bg_stream_row.asm — Mode-1 normal-BG BG1 VERTICAL (row) streaming producer.
; =============================================================================
; Streaming rail Mode 1 / Sprint S2a. The NET-NEW vertical axis that completes
; the 2-axis (horizontal column + vertical row) normal-BG streaming substrate.
; Sibling of engine/bg_stream.asm (the horizontal column producer): same
; cooperative-NMI protocol, same per-frame compute-and-queue shape, but for
; ROWS streamed off a ROW-MAJOR flat ROM tilemap.
;
; --- Geometry (64x64 BG1 tilemap, BG1SC=$5B) --------------------------------
; The BG1 tilemap is widened to 64x64 (4 sub-pages of 32x32) so there is ring
; room on BOTH axes. The 4 pages from base word $5800:
;     SC0 = $5800 (cols 0-31, rows 0-31)   SC1 = $5C00 (cols 32-63, rows 0-31)
;     SC2 = $6000 (cols 0-31, rows 32-63)  SC3 = $6400 (cols 32-63, rows 32-63)
; VRAM(col,row) = $5800 + (col>=32?$400:0) + (row>=32?$800:0)
;                       + (row&31)*32 + (col&31).
;
; --- The slot-rotation problem (and the staging-buffer answer) --------------
; A streamed ROW covers the 64 world columns currently in the HORIZONTAL ring
; window [FIRST_COL, FIRST_COL+63]. Those columns map to col SLOTS (col & $3F)
; that ROTATE as the camera pans horizontally — so a row's tiles do NOT land at
; contiguous VRAM addresses when FIRST_COL is not slot-aligned. Rather than
; split each row DMA into up-to-4 wrap-and-page sub-transfers, the producer
; STAGES the row into a 64-word WRAM buffer indexed by col slot
; (buf[world_col & $3F] = tile word) — wrap handled in the staging loop — then
; queues TWO page-aligned DMA sub-slots:
;   A: buffer slots 0..31  -> SC0/SC2 page (cols 0..31)
;   B: buffer slots 32..63 -> SC1/SC3 page (cols 32..63), buffer + 64 bytes
; each a 32-word stride-1 DMA. The NMI consumer drains with VMAIN=$80.
; A 2-entry staging DOUBLE-BUFFER lets up to 2 rows be in flight between the
; main-thread queue and the next VBlank drain.
;
; --- Source data (ROW-MAJOR flat ROM) ---------------------------------------
; Row M's BGW_ROW_BYTES bytes (one tile word per world column) live at off =
; M * BGW_ROW_BYTES. The staging loop reads world col C of row M at
; row_ptr + M*BGW_ROW_BYTES + C*2. STREAM_ROW_LEVEL_PTR holds the 24-bit base.
;
; --- Units contract ---------------------------------------------------------
; Level authored as 8px tile rows; STREAM_CAM_ROW = cam_y >> 3. BG1VOFS = cam_y.
;
; --- DP scratch convention --------------------------------------------------
; Reuses the $A5-$AE engine-scratch zone (same as the horizontal producer).
; The row routines run from sf_stream_tick AFTER the column tick completes,
; never nested with the column routines, so the scratch aliasing is safe.
; =============================================================================

.export bg_stream_row_init
.export bg_stream_row_tick

; The including ROM MUST define BGW_ROW_BYTES (row-major stride, = world width
; in tiles * 2) — supplied by the generated bg_stream_world.inc. We don't
; hardcode it so the producer works for any authored width.

; STREAM_BG1_VRAM_BASE / STREAM_BG1_HPAGE_OFF / STREAM_BG1_VPAGE_OFF are defined
; by engine/bg_stream.asm, which a 2-axis ROM always .includes BEFORE this file.
; (STREAM_BG1_HPAGE_OFF aliases STREAM_BG1_PAGE1_OFF = $0400 there.)
STREAM_BG1_HPAGE_OFF  = STREAM_BG1_PAGE1_OFF   ; cols 32-63 page offset (SC1/SC3)
STREAM_ROW_LOOK_AHEAD = 32         ; look-ahead in 8x8 tile rows (28 visible + 4)
STREAM_ROW_HALF_BYTES = 64         ; 32 col slots x 2 bytes per page half
STREAM_ROWS_BOOT      = 64         ; rows populated at boot (full vertical ring)

; --- bg_stream_row_init -----------------------------------------------------
; Inputs (caller fills on $00 page before JSR):
;   $25-$27  STREAM_ROW_LEVEL_PTR  (24-bit ROW-MAJOR ROM ptr)
;   $28-$29  STREAM_LEVEL_HEIGHT_T (16-bit tile height)
; Behavior: store ptr/height; reset cam_row=0, first_row=0, last_row=63,
; pending=0; mirror the column producer's allocated channel; then for rows
; 0..63 stage + per-half blocking DMA the full vertical ring. Caller holds
; forced blank. Entry A8/I16, exits A8/I16. Clobbers A, X, Y.
bg_stream_row_init:
    rep #$10
    .i16
    sep #$20
    .a8
    lda $25
    sta f:$7E0000 + STREAM_ROW_LEVEL_PTR + 0
    lda $26
    sta f:$7E0000 + STREAM_ROW_LEVEL_PTR + 1
    lda $27
    sta f:$7E0000 + STREAM_ROW_LEVEL_PTR + 2
    lda $28
    sta f:$7E0000 + STREAM_LEVEL_HEIGHT_T + 0
    lda $29
    sta f:$7E0000 + STREAM_LEVEL_HEIGHT_T + 1
    lda #$00
    sta f:$7E0000 + STREAM_CAM_ROW + 0
    sta f:$7E0000 + STREAM_CAM_ROW + 1
    sta f:$7E0000 + STREAM_FIRST_ROW + 0
    sta f:$7E0000 + STREAM_FIRST_ROW + 1
    sta f:$7E0000 + STREAM_ROW_PENDING
    sta f:$7E0000 + STREAM_ROW_STAGE_IDX
    lda #STREAM_ROWS_BOOT - 1
    sta f:$7E0000 + STREAM_LAST_ROW + 0
    lda #$00
    sta f:$7E0000 + STREAM_LAST_ROW + 1
    ; mirror channel allocation from the column producer
    lda f:$7E0000 + STREAM_ACTIVE
    sta f:$7E0000 + STREAM_ROW_ACTIVE
    bne @rinit_ok
    rts                         ; no channel — graceful degrade
@rinit_ok:
    .a8                         ; WIDTH-LINT: ok — branch target from BNE
    ; The full 64x64 VRAM ring (rows 0..63) is boot-filled by the COLUMN
    ; producer's 2-axis boot (engine/bg_stream.asm streaming_init, which under
    ; BG_STREAM_2AXIS emits the rows-32..63 sub-DMA per column). The row
    ; producer only sets up its tracker state here; vertical streaming happens
    ; per-frame via bg_stream_row_tick. (No row boot DMA needed — the column
    ; boot already covers the resident window.)
    rts

; --- _bsr_boot_dma_half — DMA both halves of the freshly-staged row at boot --
; Uses GP-DMA CH0. Row index in $A4, stage buffer base computed from
; STREAM_ROW_STAGE_IDX. Entry A8/I16, exits A8/I16. Clobbers A, X.
_bsr_boot_dma_half:
    .a8
    jsr _bsr_stage_base         ; $AA = buffer low16 (bank 0 mirror addressable)
    ; --- HALF A: VADDR = base + vpage + (row&31)*32 ; src = buf + 0 ---
    rep #$20
    .a16
    jsr _bsr_row_vaddr_a
    sta $A9                     ; cache half-A VADDR
    lda $AA                     ; src = buffer base
    jsr _bsr_boot_one_dma       ; DMA 32 words stride-1 ($A9 VADDR, A src low16)
    ; --- HALF B: VADDR = half-A + $400 ; src = buf + 64 ---
    rep #$20
    .a16
    lda $A9
    clc
    adc #STREAM_BG1_HPAGE_OFF
    sta $A9
    lda $AA
    clc
    adc #STREAM_ROW_HALF_BYTES
    jsr _bsr_boot_one_dma
    rts

; --- _bsr_boot_one_dma — one 32-word stride-1 CH0 DMA from WRAM to VRAM ------
; Inputs: $A9 = VADDR (VRAM word addr), A (A16) = source low16 (WRAM bank-0
; mirror). Fully self-contained: sets VMAIN/DMAP/BBAD/VMADD/src/DAS then fires.
; Entry A16, exits A8. Clobbers A.
_bsr_boot_one_dma:
    .a16
    sta $4302                   ; A1T low16 = source (bank 0 mirror)
    lda $A9
    sta $2116                   ; VMADD = VADDR
    lda #$0040
    sta $4305                   ; DAS = 64 bytes (32 words)
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: stride 1 word, inc after $2119
    lda #$01
    sta $4300                   ; DMAP: mode 1 (pair VMDATAL/H)
    lda #$18
    sta $4301                   ; BBAD: $2118 (VMDATAL)
    lda #$7E
    sta $4304                   ; A1B: source bank $7E (staging buffer in WRAM)
    lda #$01
    sta $420B                   ; trigger CH0
    rts

; --- bg_stream_row_tick -----------------------------------------------------
; Per-frame: stage + queue any newly entered leading (down) / trailing (up)
; rows. Each queued row = 2 sub-slots (A + B halves) reading from a freshly
; staged WRAM buffer. Entry A8/I16, exits A8/I16. Clobbers A, X, Y.
bg_stream_row_tick:
    rep #$10
    .i16
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_ROW_ACTIVE
    bne @rtick_alive
    rts
@rtick_alive:
    .a8                         ; WIDTH-LINT: ok — branch target from BNE
    ; Queue AT MOST ONE row per frame. The staging buffer holds the queued
    ; row's tiles until the NEXT VBlank drains it; queuing a second row the same
    ; frame would re-stage the (single) buffer before the NMI consumed the
    ; first, so the first row's DMA would read the second's data. One row/frame
    ; is sufficient: the scripted camera pans <= 1 tile-row/frame, and the
    ; vertical look-ahead absorbs the rest.
    jsr _bsr_compute_next_row
    rts

; --- _bsr_compute_next_row --------------------------------------------------
; Decide whether a new row needs streaming; if so STAGE it and emit TWO
; sub-slots into STREAM_ROW_PENDING_TBL. Returns carry SET if queued.
; Entry A8/I16, exits A8/I16. Clobbers A, X, Y, scratch $A5-$AE.
_bsr_compute_next_row:
    rep #$10
    .i16
    sep #$20
    .a8
    ; need room for 2 sub-slots
    lda f:$7E0000 + STREAM_ROW_PENDING
    cmp #STREAM_ROW_PENDING_MAX_SLOTS - 1
    bcc @rcn_room
    clc
    rts
@rcn_room:
    .a8                         ; WIDTH-LINT: ok — branch target from BCC
    ; FORWARD (down): last_row < cam_row + LOOK_AHEAD (capped at height-1)
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_CAM_ROW
    clc
    adc #STREAM_ROW_LOOK_AHEAD
    cmp f:$7E0000 + STREAM_LEVEL_HEIGHT_T
    bcc @rcn_in_range
    lda f:$7E0000 + STREAM_LEVEL_HEIGHT_T
    sec
    sbc #$0001
@rcn_in_range:
    .a16                        ; WIDTH-LINT: ok — A16 from rep
    sta $A5                     ; forward target
    lda f:$7E0000 + STREAM_LAST_ROW
    cmp $A5
    bcc @rcn_forward
    bra @rcn_reverse
@rcn_forward:
    .a16                        ; WIDTH-LINT: ok — branch target from BCC
    lda f:$7E0000 + STREAM_LAST_ROW
    inc a
    sta f:$7E0000 + STREAM_LAST_ROW
    sta $A4                     ; new world row
    lda f:$7E0000 + STREAM_FIRST_ROW
    inc a
    sta f:$7E0000 + STREAM_FIRST_ROW
    bra @rcn_emit
@rcn_reverse:
    .a16                        ; WIDTH-LINT: ok — branch target from BRA
    lda f:$7E0000 + STREAM_FIRST_ROW
    beq @rcn_up_to_date
    cmp f:$7E0000 + STREAM_CAM_ROW
    bcc @rcn_up_to_date
    beq @rcn_up_to_date
    dec a                       ; new row = first_row - 1
    sta f:$7E0000 + STREAM_FIRST_ROW
    sta $A4
    lda f:$7E0000 + STREAM_LAST_ROW
    dec a
    sta f:$7E0000 + STREAM_LAST_ROW
    bra @rcn_emit
@rcn_up_to_date:
    .a16                        ; WIDTH-LINT: ok — multi-path target
    sep #$20
    .a8
    clc
    rts
@rcn_emit:
    .a16                        ; WIDTH-LINT: ok — multi-path target
    sep #$20
    .a8
    ; --- STAGE the row into a WRAM staging buffer (wrap by col slot) ---
    jsr _bsr_stage_row          ; uses $A4 (row), reads FIRST_COL live
    ; stage base into $AA, then STASH it in $B6 immediately. The stage base is
    ; the DMA source low16 for BOTH sub-slots below, but $AA-$AB is fragile DP
    ; scratch (the $A8/$A9/$AA/$AB cluster is reused across _bsr_stage_row /
    ; _bsr_slot_x / _bsr_row_vaddr_a, and A16 stores into $A8/$A9 spill their
    ; high byte into $AA). Caching the base in $B6 (a DP byte no helper in this
    ; path touches) makes the queued sub-slot's SRC immune to that aliasing —
    ; this is the S2a deep/reverse corruption fix (the row never reached its
    ; ring slot because SRC pointed at engine state, not the staging buffer).
    rep #$20
    .a16
    jsr _bsr_stage_base
    lda $AA
    sta $B6                     ; STASH stage base (16-bit) — DMA source low16
    sep #$20
    .a8
    ; advance the staging double-buffer index for the next queued row
    lda f:$7E0000 + STREAM_ROW_STAGE_IDX
    inc a
    cmp #STREAM_ROW_STAGE_COUNT
    bcc @rcn_idx_ok
    lda #$00
@rcn_idx_ok:
    .a8                         ; WIDTH-LINT: ok — branch target from BCC
    sta f:$7E0000 + STREAM_ROW_STAGE_IDX

    ; --- emit sub-slot A: stage slots 0..31 -> SC0/SC2 page ---
    jsr _bsr_slot_x             ; X = pending*5
    .a16
    jsr _bsr_row_vaddr_a        ; A = VADDR half A
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 0, x
    lda $B6                     ; stage buffer low16 (stashed, alias-immune)
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 2, x
    sep #$20
    .a8
    lda #$00
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 4, x   ; bank 0 (WRAM mirror)
    lda f:$7E0000 + STREAM_ROW_PENDING
    inc a
    sta f:$7E0000 + STREAM_ROW_PENDING

    ; --- emit sub-slot B: stage slots 32..63 -> SC1/SC3 page ---
    jsr _bsr_slot_x             ; X = (new) pending*5
    .a16
    jsr _bsr_row_vaddr_a
    clc
    adc #STREAM_BG1_HPAGE_OFF
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 0, x
    lda $B6                     ; stage buffer low16 (stashed, alias-immune)
    clc
    adc #STREAM_ROW_HALF_BYTES
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 2, x
    sep #$20
    .a8
    lda #$00
    sta f:$7E0000 + STREAM_ROW_PENDING_TBL + 4, x
    lda f:$7E0000 + STREAM_ROW_PENDING
    inc a
    sta f:$7E0000 + STREAM_ROW_PENDING

    sec
    rts

; --- _bsr_stage_row — stage one world row's 64 visible cols into a WRAM buf --
; Inputs: $A4 = world row (16-bit). Reads STREAM_FIRST_COL live. Writes the 64
; tile words for world cols [FIRST_COL..FIRST_COL+63] into the staging buffer
; (current STREAM_ROW_STAGE_IDX), indexed by col slot (world_col & $3F).
; Source (row-major) = STREAM_ROW_LEVEL_PTR + row*BGW_ROW_BYTES + col*2.
; Entry A8/I16, exits A8/I16. Clobbers A, X, Y, scratch $A5-$AE.
_bsr_stage_row:
    .a8
    ; --- build 24-bit row base pointer into ES scratch $A5-$A7 (low/mid/bank).
    rep #$20
    .a16
    ; row * BGW_ROW_BYTES (low 16). BGW_ROW_BYTES is a power of two (256) for the
    ; canonical pipeline; use a generic multiply via repeated add is overkill —
    ; assert the pipeline width and shift. BGW_ROW_BYTES = 256 -> << 8.
    lda $A4
    xba                         ; row << 8 = row * 256 (low 16)
    and #$FF00
    clc
    adc f:$7E0000 + STREAM_ROW_LEVEL_PTR + 0
    sta $A5                     ; row base low16
    lda #$0000
    adc #$0000
    sta $A8                     ; carry from the add
    ; bank = ptr_bank + (row >> 8) + carry. row<128 so row>>8 = 0.
    lda $A4
    .repeat 8
    lsr
    .endrep
    clc
    adc $A8
    sep #$20
    .a8
    clc
    adc f:$7E0000 + STREAM_ROW_LEVEL_PTR + 2
    sta $A7                     ; row base bank
    ; Stage the 24-bit row-base pointer at $A5/$A6 (low16) + $A7 (bank) so the
    ; source can be read via [<$A5],y with Y = col*2 (Y carries the col byte
    ; offset, so bank crossing is handled by the 65816 indirect-long add).
    ; --- staging-buffer destination base into $AA (16-bit, bank-0 WRAM mirror).
    jsr _bsr_stage_base
    ; DB=$00 for the duration so DP-indirect stores ($B0) hit $00:07xx (= the
    ; bank-0 mirror of the $7E:07xx staging buffer). Main-thread DB is normally
    ; $00 already, but make it explicit for the indirect store.
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = $00
    rep #$30
    .a16
    .i16
    ; --- loop world cols FIRST_COL..FIRST_COL+63 (64 iterations) ---
    lda f:$7E0000 + STREAM_FIRST_COL
    sta $AC                     ; world col cursor
    ldx #64                     ; iteration counter (down)
@stage_loop:
    .a16                        ; WIDTH-LINT: ok — backward branch target
    .i16
    ; source byte offset within row = col*2 -> Y
    lda $AC
    asl
    tay                         ; Y = col*2
    lda [$A5], y                ; tile word from row-major ROM (24-bit indexed)
    pha                         ; stash tile word
    ; dest = buffer base + (col & $3F)*2
    lda $AC
    and #$003F
    asl                         ; slot*2
    clc
    adc $AA                     ; buffer base + slot*2
    sta $B0                     ; dest DP pointer
    pla                         ; tile word
    sta ($B0)                   ; store into staging buffer (DB=$00 -> $00:07xx)
    inc $AC                     ; next world col
    dex
    bne @stage_loop
    plb                         ; restore DB
    sep #$20
    .a8
    rts

; --- _bsr_stage_base — compute current staging-buffer base addr -> $AA -------
; $AA (16-bit) = STREAM_ROW_STAGE_BUFS + STREAM_ROW_STAGE_IDX * STREAM_ROW_STAGE_SZ.
; The address is in WRAM $7E:07xx, whose bank-0 mirror $00:07xx is DP-/abs-
; addressable, so DMA source bank 0 and DP-indirect stores both reach it.
; Entry any A-width (saves/restores via rep). Exits A8/I16-safe. Clobbers A.
_bsr_stage_base:
    php
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_ROW_STAGE_IDX
    and #$00FF
    .repeat 7
    asl                         ; idx * 128 (STREAM_ROW_STAGE_SZ)
    .endrep
    clc
    adc #STREAM_ROW_STAGE_BUFS
    sta $AA
    plp
    rts

; --- _bsr_row_vaddr_a — VADDR of half A (cols 0..31) for world row $A4 -------
; The VRAM destination is the RING SLOT rs = row & $3F (NOT the raw world row):
; both the vertical page select (SC0/SC1 vs SC2/SC3) and the in-page row offset
; derive from rs. (Earlier bug: the vpage check used the raw world row, so e.g.
; world row 90 -> rs 26 wrongly selected SC2 instead of SC0 -> a +16-row shift
; in the streamed region.)
; Returns A16 = STREAM_BG1_VRAM_BASE + (rs>=32?$800:0) + (rs&31)*32.
; Entry A16/I16, exits A16/I16. Clobbers A and scratch $AD ONLY.
; WIDTH-RISK / ALIASING (S2a deep/reverse corruption root cause): this routine
; MUST NOT touch $A9, $AA, or $AB. $AA is the live 16-bit stage-base pointer
; (set by _bsr_stage_base) that the emit caller reads via `lda $AA` IMMEDIATELY
; after calling us, to store the DMA source low16. The original code used $A9
; (in-page offset) and $AB (rs cache) as A16 scratch — but a 16-bit `sta $A9`
; spills its HIGH byte into $AA (clobbering the pointer's low byte), and $AB is
; literally $AA's high byte. Either silently corrupts the queued sub-slot's DMA
; source pointer -> the row DMA reads engine state ($00:07xx) instead of the
; staging buffer ($00:0760+), so the ring slot is never refreshed and the
; streamed row never appears (paired with the _bsr_slot_x A8 `and #$00FF`
; stale-B bug). So we use NO scratch in $A9-$AB: rs is held in $AD, and the
; in-page offset stays in the accumulator across the vpage add (carry-free).
_bsr_row_vaddr_a:
    .a16
    ; Base for this row = STREAM_BG1_VRAM_BASE, + VPAGE_OFF iff rs >= 32. Decide
    ; the page base FIRST (while rs is in A), cache it in $AD, then build the
    ; in-page offset in A and add the cached base. This keeps X intact (the emit
    ; caller still needs X = slot offset after this call) and never touches
    ; $A9/$AA/$AB.
    lda $A4
    and #$003F                  ; rs = row & $3F (ring slot)
    cmp #$0020
    bcc @rva_shallow            ; rs < 32 -> SC0/SC1 page (no vpage)
    ; rs >= 32: deep page. Cache page base = VRAM_BASE + VPAGE_OFF in $AD.
    lda #STREAM_BG1_VRAM_BASE + STREAM_BG1_VPAGE_OFF
    sta $AD
    bra @rva_offset
@rva_shallow:
    .a16                        ; WIDTH-LINT: ok — branch target from BCC
    lda #STREAM_BG1_VRAM_BASE
    sta $AD                     ; cache page base in $AD (no live pointer aliases)
@rva_offset:
    .a16                        ; WIDTH-LINT: ok — multi-path target
    ; in-page offset = (rs & 31) * 32, built in A (rs = row & $3F).
    lda $A4
    and #$001F                  ; rs & 31 (== (rs & 31) since rs = row & $3F)
    .repeat 5
    asl                         ; A = (rs & 31) * 32
    .endrep
    clc
    adc $AD                     ; A = page base + in-page offset
    rts

; --- _bsr_slot_x — current row-queue slot byte offset (pending*5) -> X -------
; Entry A8/I16, exits A16/I16 with X = STREAM_ROW_PENDING*5. Clobbers A.
_bsr_slot_x:
    .a8
    lda f:$7E0000 + STREAM_ROW_PENDING
    asl
    asl                         ; *4
    clc
    adc f:$7E0000 + STREAM_ROW_PENDING   ; *5
    ; WIDTH-RISK: A-high (B) holds stale bits from the long lda/adc above. The
    ; `and #$00FF` MUST run in A16 to clear the full 16-bit accumulator before
    ; the I16 `tax` — otherwise `tax` transfers (stale_B<<8 | pending*5) and the
    ; queue slot offset is garbage. (In A8, `and #$00FF` assembles as `29 FF`,
    ; a 1-byte immediate that only masks the low byte and leaves B dirty —
    ; CLAUDE.md "tax/tay crossing A/I width mismatches". This was the S2a
    ; reverse/deep-region corruption root cause.) So go A16 FIRST, then mask+tax.
    rep #$20
    .a16
    and #$00FF
    tax                         ; WIDTH-LINT: ok — A16, masked to byte before tax
    rts
