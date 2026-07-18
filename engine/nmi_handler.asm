; =============================================================================
; nmi_handler.asm — Full 8-Phase NMI Handler for SuperForge Engine
; =============================================================================
; Implements the VBlank interrupt handler per superforge_nmi_handler_v0.1.md.
;
; Phase 1: Register preservation (PHA/PHX/PHY/PHD/PHB, set DP=$0100)
; Phase 2: Acknowledge NMI (read $4210)
; Phase 3: DMA transfers (drain priority queue, budget tracking)
; Phase 4: PPU register writes (shadow → hardware)
; Phase 5: HDMA channel setup (stub for Phase 4+ features)
; Phase 6: Auto-joypad read (poll $4212, read $4218-$421B, edge detect)
; Phase 7: Frame counter, stats, nmi_done_flag
; Phase 8: Register restoration (PLB/PLD/PLY/PLX/PLA, RTI)
;
; DP=$0100 during NMI execution (ENGINE_STATE_BASE).
; All engine state variables accessed via DP-relative offsets (ES_* constants).
; DMA queue at absolute WRAM $0200 (32 entries x 8 bytes).
;
; Cross-ref: engine_state.inc, superforge_nmi_handler_v0.1.md
; =============================================================================

; Prerequisite: engine_state.inc must be included before this file.
; Prerequisite: .p816 and .smart must be set.
; This file is included inline after the NMI: label in the ROM source.
; It does NOT define its own segment or include dependencies.
    ; === Phase 1: Register Preservation ===
    rep #$30                    ; 3 MC — A/X/Y to 16-bit
    .a16
    .i16
    pha                         ; 4 MC — save A
    phx                         ; 4 MC — save X
    phy                         ; 4 MC — save Y
    phd                         ; 4 MC — save Direct Page
    phb                         ; 3 MC — save Data Bank (8-bit push)

    ; Set DP to engine state base for fast variable access
    pea ENGINE_STATE_BASE
    pld                         ; 5+4 MC — DP = $0100

    ; Set Data Bank to $00 for hardware register access ($2100-$421F)
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = $00
    rep #$20
    .a16

    ; === Phase 2: Acknowledge NMI ===
    ; Read RDNMI to clear NMI pending flag. Mandatory — skipping this
    ; prevents NMI from firing on subsequent frames.
    sep #$20
    .a8
    lda $4210                   ; Read RDNMI (clears NMI flag, bit 7 = VBlank)
    rep #$20
    .a16

    ; === Phase 3: DMA Transfers ===
    ; Check if main thread has prepared a DMA queue
    sep #$20
    .a8
    lda ES_DMA_QUEUE_READY      ; DP-relative ($0100 + $09)
    bne @queue_ready            ; Trampoline — the long-addressed STAT7 reset
    jmp @no_dma                 ; below pushed @no_dma past BEQ's -128..+127 range.
@queue_ready:
    stz ES_DMA_QUEUE_READY      ; Clear the ready flag
    rep #$20
    .a16

    ; Initialize budget tracking
    lda ES_DMA_BUDGET
    sta ES_BYTES_REMAINING
    ; STAT7_DROPS is WRAM extended ($7E:E102); STZ has no long form, so zero
    ; via LDA #0 + STA long. +6 cycles vs former DP STZ (diagnostic-only).
    lda #$0000
    sta STAT7_DROPS             ; Reset drop counter for this frame

    ; Load queue count and base pointer
    ldx ES_DMA_QUEUE_COUNT
    beq @dma_done               ; Skip if queue is empty
    ldy #$0000                  ; Y = queue read offset

@dma_loop:
    cpx #$0000
    beq @dma_done

    ; Read transfer size from queue entry (absolute addressing)
    ; Entry at DMA_QUEUE_BASE + Y
    lda DMA_QUEUE_BASE + DMA_ENT_SIZE, y

    ; Check: does this transfer fit in remaining budget?
    cmp ES_BYTES_REMAINING
    bcs @dma_check_critical     ; Transfer too large — check if critical

    ; Transfer fits — execute it
    bra @dma_execute

@dma_check_critical:
    ; Check priority: priorities 0-1 (OAM, CGRAM) are always transferred
    sep #$20
    .a8
    lda DMA_QUEUE_BASE + DMA_ENT_PRIORITY, y
    cmp #$02
    rep #$20
    .a16
    bcc @dma_execute            ; Priority < 2: always execute (OAM, CGRAM)

    ; Priority >= 2: drop this transfer. STAT7_DROPS is WRAM extended
    ; ($7E:E102); INC has no long form — emulate via LDA long / INC A /
    ; STA long. Adds ~6 cycles per dropped transfer vs the former INC DP.
    ; Y is preserved (queue read offset). A is dead until @dma_next re-
    ; loads the next entry's size, so no save needed.
    lda STAT7_DROPS
    inc a
    sta STAT7_DROPS
    bra @dma_next

@dma_execute:
    ; Configure GP-DMA channel 0 ($4300-$4307)
    ; Channel 0 is reserved for GP-DMA; channels 3-7 are for HDMA.
    ; Using the same channel for both GP-DMA and HDMA corrupts transfers.
    sep #$20
    .a8
    lda DMA_QUEUE_BASE + DMA_ENT_DMAP, y
    sta $4300                   ; DMAP0: transfer mode

    lda DMA_QUEUE_BASE + DMA_ENT_BBAD, y
    sta $4301                   ; BBAD0: PPU destination register

    rep #$20
    .a16
    lda DMA_QUEUE_BASE + DMA_ENT_SRC_LO, y
    sta $4302                   ; A1T0L/H: source address

    sep #$20
    .a8
    lda DMA_QUEUE_BASE + DMA_ENT_SRC_BANK, y
    sta $4304                   ; A1B0: source bank

    rep #$20
    .a16
    lda DMA_QUEUE_BASE + DMA_ENT_SIZE, y
    sta $4305                   ; DAS0L/H: transfer size

    ; Execute GP-DMA on channel 0
    sep #$20
    .a8
    lda #$01                    ; Enable channel 0 (bit 0)
    sta $420B                   ; MDMAEN: trigger DMA — CPU halts until done
    rep #$20
    .a16

    ; Subtract transferred bytes from budget
    lda ES_BYTES_REMAINING
    sec
    sbc DMA_QUEUE_BASE + DMA_ENT_SIZE, y
    sta ES_BYTES_REMAINING

@dma_next:
    ; Advance to next queue entry
    dex
    ; Advance Y by entry size (8 bytes)
    tya
    clc
    adc #DMA_QUEUE_ENTRY_SZ
    tay
    bra @dma_loop

@dma_done:
    ; Record stat(5) — remaining DMA budget. STAT5_DMA_REM is in WRAM extended
    ; ($7E:E100), so `sta STAT5_DMA_REM` assembles as STA long (+2 cycles vs
    ; the former DP access; diagnostic-only, not hot-path).
    lda ES_BYTES_REMAINING
    sta STAT5_DMA_REM

    ; Clear queue for next frame
    stz ES_DMA_QUEUE_COUNT
    jmp @tilemap_check

@no_dma:
    rep #$20
    .a16

    ; === Phase 3B: Tilemap DMA ===
    ; Transfer dirty shadow tilemaps (WRAM) to VRAM.
    ; BG_TILEMAP_DIRTY bitmask: bit0=BG1, bit1=BG2, bit2=BG3.
    ; Uses DMA channel 1 (channel 0 = GP-DMA queue, channels 3-7 = HDMA).
@tilemap_check:
    sep #$20
    .a8
    lda ES_BG_TILEMAP_DIRTY
    bne @tilemap_has_dirty
    jmp @tilemap_dma_done
@tilemap_has_dirty:

    ; Set VMAIN: word-access mode, increment after writing $2119 (high)
    lda #$80
    sta $2115                       ; VMAIN: increment mode = 1-word after high

    ; Configure DMA channel 1 for 2-byte VRAM word writes
    lda #$01                        ; DMAP: mode 01 (write $2118 then $2119, pair)
    sta $4310                       ; DMA1 parameters
    lda #$18                        ; BBAD: $2118 (VMDATAL)
    sta $4311                       ; DMA1 destination

    ; Check each layer
    lda ES_BG_TILEMAP_DIRTY

    bit #$01
    beq @tilemap_skip_bg1
    ; --- DMA BG1 shadow tilemap to VRAM ---
    rep #$20
    .a16
    lda #$5800                      ; VRAM word address for BG1 tilemap
    sta $2116                       ; VMADDL/H
    lda #SHADOW_BG1_TILEMAP
    sta $4312                       ; A1T1L/H: source address
    sep #$20
    .a8
    lda #$7E
    sta $4314                       ; A1B1: source bank
    rep #$20
    .a16
    lda #$0800                      ; 2048 bytes
    sta $4315                       ; DAS1L/H: transfer size
    sep #$20
    .a8
    lda #$02                        ; Enable channel 1
    sta $420B                       ; MDMAEN: trigger DMA
@tilemap_skip_bg1:
    .a8

    lda ES_BG_TILEMAP_DIRTY
    bit #$02
    beq @tilemap_skip_bg2
    ; --- DMA BG2 shadow tilemap to VRAM ---
    ; Phase 17 Sprint D-5 (Bug A): BG2 VRAM destination is no longer
    ; hardcoded to $5C00. The high byte comes from BG2_TILEMAP_VRAM_HI
    ; (set in init_ppu to $5C; streaming-mode boot overrides to $48 to
    ; avoid aliasing BG1's 64×32 page-1 region $5C00-$5FFF).
    ;
    ; WIDTH-RISK: A8 on entry. Compose VRAM word as two 8-bit writes to
    ; $2116/$2117 (low byte = $00, high byte = BG2_TILEMAP_VRAM_HI), then
    ; toggle A16 for the source-pointer / size writes. .a8/.a16 markers
    ; on every branch target / width transition.
    .a8
    stz $2116                       ; VMADDL = $00
    lda BG2_TILEMAP_VRAM_HI
    sta $2117                       ; VMADDH = vram_hi → VMADD = vram_hi*256
    rep #$20
    .a16
    lda #SHADOW_BG2_TILEMAP
    sta $4312
    sep #$20
    .a8
    lda #$7E
    sta $4314
    rep #$20
    .a16
    lda #$0800
    sta $4315
    sep #$20
    .a8
    lda #$02
    sta $420B
@tilemap_skip_bg2:
    .a8                             ; ; WIDTH-LINT: ok — branch target reached A8/I16

    lda ES_BG_TILEMAP_DIRTY
    bit #$04
    beq @tilemap_skip_bg3
    ; --- DMA BG3 shadow tilemap to VRAM ---
    rep #$20
    .a16
    lda #$6000                      ; VRAM word address for BG3 tilemap
    sta $2116
    lda #SHADOW_BG3_TILEMAP
    sta $4312
    sep #$20
    .a8
    lda #$7E
    sta $4314
    rep #$20
    .a16
    lda #$0800
    sta $4315
    sep #$20
    .a8
    lda #$02
    sta $420B
@tilemap_skip_bg3:
    .a8

    ; Clear dirty flags
    stz ES_BG_TILEMAP_DIRTY

@tilemap_dma_done:
    rep #$20
    .a16

    ; === Phase 3D: VWF tile-data DMA (Phase 16-8 step 3 VWF infrastructure) ===
    ; The VWF compositor (engine_print_vwf / engine_print_chars_vwf) writes
    ; rendered glyph bitplanes to WRAM at VWF_TILE_BUFFER ($7E:CD00..CE7F,
    ; 384 bytes = 24 tiles × 16 bytes) and sets VWF_DIRTY ($00:0587) when
    ; the buffer needs to reach VRAM. This hook drains that flag once per
    ; frame: when set, DMA the 384-byte buffer to VRAM word VWF_VRAM_BASE
    ; ($B100), then clear the flag.
    ;
    ; Channel 1 reuse: shares the tilemap-DMA channel (already configured
    ; for word VRAM writes by Phase 3B above when any tilemap was dirty,
    ; but Phase 3B may not have run on a VWF-only frame; we re-program
    ; DMAP+BBAD here unconditionally).
    ;
    ; Cycle cost: ~12 + DMA xfer time (384 bytes at 8 master-cycles each
    ; under FastROM = ~3,072 MC = ~858 CPU cycles equivalent). Comfortably
    ; fits in NTSC VBlank's ~30,000 master-cycle budget alongside the
    ; existing tilemap and streaming DMAs.
    ;
    ; WIDTH-RISK: enters at A16/I16 (after `rep #$20` above). All sep/rep
    ; transitions inside this block are paired with .a8/.a16 markers.
@vwf_dma_check:
    sep #$20
    .a8
    lda f:$000587               ; VWF_DIRTY at $00:0587 (DB=$00 here)
    bne @vwf_dma_run
    rep #$20
    .a16
    bra @vwf_dma_done

@vwf_dma_run:
    ; Configure DMA channel 1 for VRAM word writes: source $7E:CD00,
    ; dest $2118 (VMDATAL/H pair via DMAP mode 01), 384 bytes.
    rep #$20
    .a16
    lda #VWF_VRAM_BASE          ; $B100 — VRAM word target
    sta $2116                   ; VMADDL/H
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: increment after $2119
    lda #$01                    ; DMAP mode 01 = $2118 then $2119 word pair
    sta $4310
    lda #$18                    ; BBAD = $2118 (VMDATAL)
    sta $4311
    rep #$20
    .a16
    lda #VWF_TILE_BUFFER        ; $CD00 source low
    sta $4312
    sep #$20
    .a8
    lda #$7E                    ; source bank
    sta $4314
    rep #$20
    .a16
    lda #VWF_TILE_BUFFER_SIZE   ; 384 bytes
    sta $4315
    sep #$20
    .a8
    lda #$02                    ; enable channel 1
    sta $420B                   ; MDMAEN — fire DMA
    lda #$00                    ; clear VWF_DIRTY (stz has no long form)
    sta f:$000587
    rep #$20
    .a16
@vwf_dma_done:
    .a16                        ; ; WIDTH-LINT: ok — branch target reached A16 from both arms

    ; === Streaming column DMA — Mode-1 BG1 HORIZONTAL column drain ===
    ; *** ACTIVE (Streaming rail Mode 1) — the PRODUCER ships: engine/bg_stream.asm
    ;     (materialized into the kit; front door lib/macros/sf_stream.inc). This
    ;     block DMAs the columns the producer queues in STREAM_PENDING into BG1
    ;     VRAM each VBlank. It is the HORIZONTAL (column) axis; the VERTICAL (row)
    ;     axis ships too — engine/bg_stream_row.asm queues STREAM_ROW_PENDING,
    ;     drained by the row-DMA block under `.ifdef BG_STREAM_2AXIS` below. The
    ;     two axes TOGETHER are the proven normal-BG / Mode-1 2-axis streaming
    ;     substrate (64x64 BG1 @ BG1SC=$5B; S2a). The PLAYABLE rail built on it is
    ;     `templates/platformer_stream` (16-bit world-Y physics + world-space
    ;     collision; tests/test_platformer_stream.py + its oracle.json) and the
    ;     substrate is byte-proven both axes by tests/test_bg_stream2d.py — see
    ;     docs/guides/normal_bg_streaming.md. (NOT a foothold/partial anymore: the
    ;     "S2 will extend this with a vertical axis" note is DONE.) This is
    ;     Mode-1-tilemap-bound (BG1 ring) — do NOT drive a Mode 7 streaming world
    ;     from it; for 2-axis Mode 7 streaming (the `mode7_explore` rail) the
    ;     dispatch is engine/mode7_stream_nmi.inc under `.ifdef MODE7_STREAM_NMI`
    ;     (docs/guides/mode7_overworld_streaming.md).
    ;     A ROM that does not stream simply never sets STREAM_PENDING, so this
    ;     block is a cheap early-out (one byte compare) for non-streaming ROMs.
    ; The streaming engine (engine/bg_stream.asm) signals via
    ; STREAM_PENDING (count of queued slots, 0..STREAM_PENDING_MAX_SLOTS)
    ; in WRAM that one or more 64-byte BG1 tilemap columns need to be
    ; DMA'd into VRAM. STREAM_PENDING_TBL holds the per-slot VRAM word
    ; address + 24-bit ROM source pointer (5 bytes per slot, contiguous);
    ; STREAM_DMA_CHAN holds the allocated DMA channel (range 2..7,
    ; allocated by hdma_request at streaming_init time).
    ;
    ; Streaming-speed-cap experiment: the count semantics replaced the
    ; previous 0/1 flag. NMI drains every queued slot in sequence and
    ; resets STREAM_PENDING to 0 at the end so main thread can queue a
    ; fresh batch on the next frame. Each additional slot supports an
    ; extra ~8 px/frame of sustained scroll speed.
    ;
    ; Doing this DMA during VBlank instead of inline in main thread
    ; (Sprint B's approach) avoids the visible black band that
    ; forced-blank toggling caused when streaming fired.
    ;
    ; DB=$00 throughout NMI (set in Phase 1) → channel registers at
    ; $4300+chan*16 are reachable via abs,X with X=chan*16.
    ;
    ; WIDTH-RISK: this block enters at A16/I16 (set by the rep #$20
    ; above). It must exit at A16/I16 to match @phase4's precondition.
    ; Internal sep #$20 / rep #$20 transitions are explicitly annotated.
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_PENDING
    bne @stream_dispatch
    jmp @stream_done            ; Trampoline (long-jump out of range)
@stream_dispatch:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BNE

    ; VMAIN = $81: stride 32 words, increment after high byte ($2119).
    ; Required for pair-mode DMA (DMAP=$01) so the L+H byte pair lands
    ; at the same VRAM address before VMADD advances.
    lda #$81
    sta $2115

    ; --- Compute MDMAEN trigger bit (1 << chan), cache for loop ---
    ; Pre-compute once; the drain loop just stores this byte to $420B
    ; per slot.
    lda f:$7E0000 + STREAM_DMA_CHAN
    pha                         ; chan loop counter on stack (8-bit)
    lda #$01                    ; bit accumulator
    pha
@strm_chan_shift:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label
    lda 2, s
    beq @strm_chan_shift_done
    pla
    asl
    pha
    lda 2, s
    dec a
    sta 2, s
    bra @strm_chan_shift
@strm_chan_shift_done:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BEQ
    pla                         ; A = MDMAEN bit (1<<chan)
    sta f:$7E0000 + $062F       ; cache trigger bit in scratch ($062B-$062F
                                ; freed by the queue redesign — slot data
                                ; lives at STREAM_PENDING_TBL=$0660 now)
    pla                         ; discard chan counter on stack

    ; --- Compute chan_offset = chan * 16 → X ---
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_DMA_CHAN
    and #$00FF
    asl
    asl
    asl
    asl                         ; chan << 4
    tax                         ; X = chan_offset (e.g., 7*16=$70)

    ; Configure DMA channel registers ONCE (DMAP/BBAD don't change
    ; between slots — only VMADD + source + DAS per slot).
    ;
    ; DAS MUST be reset per-slot. After a DMA completes, DAS reads back
    ; as $0000 (finished marker). If we don't re-arm it, the next DMA
    ; on the same channel transfers 0 bytes (or, depending on hardware,
    ; 65536 bytes — neither is safe). The streaming-speed-cap experiment
    ; learned this the hard way: the original 1-slot design never had
    ; this latent issue because it only ever fired once per NMI; the
    ; multi-slot drain loop has to re-arm DAS each iteration.
    sep #$20
    .a8
    lda #$01                    ; DMAP: mode 01 (pair-mode VMDATAL/H)
    sta $4300, x
    lda #$18                    ; BBAD: $2118 (VMDATAL)
    sta $4301, x
    rep #$20
    .a16

    ; --- Switch DB=$7E for drain loop so we can use abs,Y addressing
    ; into STREAM_PENDING_TBL (long+Y is illegal in 65816). The B-bus
    ; channel registers ($4300+) are accessible regardless of DB
    ; because absolute,X with X holding chan_offset is bank-0 absolute.
    ; Wait — no, abs,X uses DB. So storing to $4300,X with DB=$7E
    ; would write $7E:4300, not $00:4300.
    ;
    ; Resolution: the channel-register stores ($4302/$4304/$420B/$2116)
    ; need DB=$00. Reads from STREAM_PENDING_TBL need either DB=$7E
    ; (so abs,Y reaches WRAM) or long-form (which forbids Y indexing).
    ; Compromise: pre-load each slot's 5 bytes from WRAM via long-form
    ; reads with explicit displacements (no indexing — unrolled per
    ; slot offset). Or use the [$dp] indirect long pattern.
    ;
    ; Simpler: copy the slot data into a small DP scratch area with
    ; indirect-long [DP] addressing, then use DP-indexed access (which
    ; uses bank 0 conceptually for D-page). The cleanest approach:
    ; just stage all 4 slots into DP scratch ($A0-$AF, the engine
    ; scratch range) once at loop entry, then loop with DP-indexed Y.

    ; Copy slot table (4 slots × 5 bytes = 20 bytes) into DP $30..$43.
    ; Wait — $30-$4F is the hot global tier; $A0-$AF (16 bytes) is
    ; engine scratch but only 16. Need 20.
    ;
    ; Use absolute-X reads from $7E:0660 (DB=$00 supports long form
    ; via "f:" prefix, and abs,X with X=slot_offset works because
    ; $7E:0660 is unreachable via abs,X under DB=$00 — that addresses
    ; $00:0660+X which IS WRAM bank-0 mirror of $7E. WRAM mirror!).
    ;
    ; Actually: bank $00 addresses $0000-$1FFF mirror $7E:$0000-$1FFF.
    ; So abs $0660 with DB=$00 reads $00:0660 which mirrors $7E:0660.
    ; That works! No DB switch needed.

    ; --- Drain loop: fire one DMA per queued slot ---
    ; Y indexes slot byte-offset in STREAM_PENDING_TBL (0, 5, 10, 15).
    ; X is already chan_offset; we need a separate index for the slot
    ; reads. Reuse Y for that. The slot-table base $0660 is in bank 0
    ; mirror of WRAM, so abs,Y works under DB=$00.
    ldy #$0000
    ; Loop entry already has DMA-config state from setup above:
    ;   DMAP/BBAD/DAS configured for chan, A16 (from sta $4305 above), I16.
    ; The loop body needs A16 for VMADD/source-low writes (16-bit) and
    ; toggles to A8 only for the source-bank + MDMAEN trigger bytes,
    ; then back to A16 before BNE so re-entry width matches the label.

@stream_drain:
    .a16                        ; WIDTH-RISK: backward branch target —
                                ; both fall-through (first iter) and BNE
                                ; loop must enter at A16/I16. Fixed in
                                ; the streaming-speed-cap experiment.
    ; Set VMADD from slot[Y].VADDR (abs,Y reaches $00:0660+Y mirror of
    ; $7E:0660 — WRAM bank-0 mirror).
    lda STREAM_PENDING_TBL + 0, y   ; VADDR (16-bit)
    sta $2116

    ; Source low/mid (16-bit).
    lda STREAM_PENDING_TBL + 2, y
    sta $4302, x

    ; DAS = 64 (re-arm; previous DMA decremented it to 0).
    lda #$0040
    sta $4305, x

    ; Source bank (8-bit).
    sep #$20
    .a8
    lda STREAM_PENDING_TBL + 4, y
    sta $4304, x

    ; Trigger DMA on this channel.
    lda f:$7E0000 + $062F       ; MDMAEN bit cached above
    sta $420B

    ; Decrement count first (1 byte), exit if zero.
    lda f:$7E0000 + STREAM_PENDING
    dec a
    sta f:$7E0000 + STREAM_PENDING
    beq @stream_drain_exit      ; count == 0 → all slots drained

    ; Advance Y to next slot at A16 and re-enter loop body with A16.
    rep #$20
    .a16
    tya
    clc
    adc #$0005                  ; +5 bytes per slot
    tay
    bra @stream_drain
@stream_drain_exit:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BEQ

    ; Queue drained. Fall through to @stream_done at A8/I16. The
    ; original @stream_done was reached at A8 from both paths
    ; (JMP early-bail and fall-through after PLA), and the next
    ; phase does its own rep #$20.

@stream_done:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label (jmp + fallthrough)

    ; === Streaming Sprint S2a: VERTICAL (ROW) DMA drain ===========================
    ; Sibling of the column drain above, for the NET-NEW vertical axis. Drains
    ; STREAM_ROW_PENDING queued ROW sub-slots into BG1 VRAM with VMAIN=$80
    ; (STRIDE-1: consecutive tilemap words across a row) — vs the column drain's
    ; VMAIN=$81 (stride-32). Same 5-byte slot layout (VADDR(2)+SRC(3)), same DMA
    ; channel (STREAM_DMA_CHAN), DAS re-armed per slot. A ROM that does not
    ; vertically stream never sets STREAM_ROW_PENDING, so this is a no-op there.
    ;
    ; WIDTH-RISK: enters A8/I16 (fall-through / column-drain exit). Internal
    ; sep/rep transitions annotated; MUST exit A8 so the trailing rep #$20
    ; below establishes A16 for @phase4 exactly as before.
    lda f:$7E0000 + STREAM_ROW_PENDING
    bne @rstream_dispatch
    jmp @rstream_done           ; trampoline (long jump out of branch range)
@rstream_dispatch:
    .a8                         ; WIDTH-LINT: ok — branch target from BNE

    ; VMAIN = $80: stride 1 word, increment after high byte ($2119). Pair-mode
    ; DMA (DMAP=$01) so the L+H pair lands before VMADD advances by 1.
    lda #$80
    sta $2115

    ; --- MDMAEN trigger bit (1 << chan), cached in $062F scratch ---
    lda f:$7E0000 + STREAM_DMA_CHAN
    pha
    lda #$01
    pha
@rstrm_chan_shift:
    .a8                         ; WIDTH-LINT: ok — multi-path label
    lda 2, s
    beq @rstrm_chan_shift_done
    pla
    asl
    pha
    lda 2, s
    dec a
    sta 2, s
    bra @rstrm_chan_shift
@rstrm_chan_shift_done:
    .a8                         ; WIDTH-LINT: ok — branch target from BEQ
    pla                         ; A = MDMAEN bit (1<<chan)
    sta f:$7E0000 + $062F       ; cache trigger bit (shared with column drain;
                                ;   column drain already finished)
    pla                         ; discard chan counter

    ; --- chan_offset = chan * 16 -> X ---
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_DMA_CHAN
    and #$00FF
    asl
    asl
    asl
    asl
    tax                         ; X = chan_offset

    ; Configure DMAP/BBAD once (constant across slots).
    sep #$20
    .a8
    lda #$01                    ; DMAP: mode 01 (pair VMDATAL/H)
    sta $4300, x
    lda #$18                    ; BBAD: $2118 (VMDATAL)
    sta $4301, x
    rep #$20
    .a16

    ; --- Drain loop: one DMA per queued row sub-slot. Y = slot byte offset. ---
    ; STREAM_ROW_PENDING_TBL=$0720 is in WRAM; $00:0720 mirrors $7E:0720 so
    ; abs,Y works under DB=$00 (same trick as the column drain).
    ldy #$0000
@rstream_drain:
    .a16                        ; WIDTH-RISK: backward branch target — both
                                ; fall-through and BNE re-entry must be A16/I16.
    lda STREAM_ROW_PENDING_TBL + 0, y   ; VADDR (16-bit)
    sta $2116
    lda STREAM_ROW_PENDING_TBL + 2, y   ; source low/mid (16-bit)
    sta $4302, x
    lda #$0040                          ; DAS = 64 bytes (32 words); re-arm
    sta $4305, x
    sep #$20
    .a8
    lda STREAM_ROW_PENDING_TBL + 4, y   ; source bank (8-bit)
    sta $4304, x
    lda f:$7E0000 + $062F               ; MDMAEN bit
    sta $420B                           ; trigger
    ; decrement count, exit when zero
    lda f:$7E0000 + STREAM_ROW_PENDING
    dec a
    sta f:$7E0000 + STREAM_ROW_PENDING
    beq @rstream_drain_exit
    rep #$20
    .a16
    tya
    clc
    adc #$0005                          ; +5 bytes per slot
    tay
    bra @rstream_drain
@rstream_drain_exit:
    .a8                         ; WIDTH-LINT: ok — branch target from BEQ

@rstream_done:
    .a8                         ; WIDTH-LINT: ok — multi-path label (jmp + fallthrough)
    rep #$20
    .a16

    ; === Phase 4: PPU Register Writes ===
@phase4:
    ; Copy shadow scroll registers to hardware PPU registers.
    ; PPU scroll registers require two 8-bit writes (low then high).
    sep #$20
    .a8

    ; BG1 horizontal scroll ($210D)
    lda ES_SHADOW_BG1HOFS
    sta $210D
    lda ES_SHADOW_BG1HOFS + 1
    sta $210D

    ; BG1 vertical scroll ($210E)
    lda ES_SHADOW_BG1VOFS
    sta $210E
    lda ES_SHADOW_BG1VOFS + 1
    sta $210E

    ; BG2 horizontal scroll ($210F)
    lda ES_SHADOW_BG2HOFS
    sta $210F
    lda ES_SHADOW_BG2HOFS + 1
    sta $210F

    ; BG2 vertical scroll ($2110)
    lda ES_SHADOW_BG2VOFS
    sta $2110
    lda ES_SHADOW_BG2VOFS + 1
    sta $2110

    ; BG3 horizontal scroll ($2111)
    lda ES_SHADOW_BG3HOFS
    sta $2111
    lda ES_SHADOW_BG3HOFS + 1
    sta $2111

    ; BG3 vertical scroll ($2112)
    lda ES_SHADOW_BG3VOFS
    sta $2112
    lda ES_SHADOW_BG3VOFS + 1
    sta $2112

    ; BG4 horizontal scroll ($2113) — Phase 17-1: Mode 0 BG4 layer.
    ; BG1-BG3 modes leave SHADOW_BG4* at zero so this is a no-op write.
    lda ES_SHADOW_BG4HOFS
    sta $2113
    lda ES_SHADOW_BG4HOFS + 1
    sta $2113

    ; BG4 vertical scroll ($2114)
    lda ES_SHADOW_BG4VOFS
    sta $2114
    lda ES_SHADOW_BG4VOFS + 1
    sta $2114

    ; BGMODE ($2105)
    lda ES_SHADOW_BGMODE
    sta $2105

    ; MOSAIC ($2106)
    lda ES_SHADOW_MOSAIC
    sta $2106

    ; Main screen designation TM ($212C)
    lda ES_SHADOW_TM
    sta $212C

    ; INIDISP ($2100) — brightness + forced blank control
    lda ES_SHADOW_INIDISP
    sta $2100

    ; Window masking registers (iris effect, clip)
    ; Default state is all zeros (windows disabled), so these are no-ops
    ; when no windowing effect is active. iris() and clip() set these;
    ; hdma_off() clears them.
    lda ES_SHADOW_W12SEL
    sta $2123                       ; W12SEL: Window 1/2 enable for BG1/BG2
    lda ES_SHADOW_W34SEL
    sta $2124                       ; W34SEL: Window 1/2 enable for BG3/BG4
    lda ES_SHADOW_WOBJSEL
    sta $2125                       ; WOBJSEL: Window 1/2 enable for OBJ/Color
    lda ES_SHADOW_WBGLOG
    sta $212A                       ; WBGLOG: BG window mask logic
    lda ES_SHADOW_WOBJLOG
    sta $212B                       ; WOBJLOG: OBJ/Color window mask logic
    lda ES_SHADOW_TMW
    sta $212E                       ; TMW: Main screen window mask designation
    lda ES_SHADOW_TSW
    sta $212F                       ; TSW: Sub screen window mask designation

    ; Window-POSITION registers WH0-WH3 ($2126-$2129) — the sf_window edges.
    ; WH0-3 are write-only (no PPU read-back), so SHADOW_WH0..WH3 (WRAM-extended
    ; $7E:E10A..E10D) are the SSoT committed here every frame. Default $00 edges
    ; are a no-op when no window is enabled. WIDTH-RISK: runs in A8 (the section
    ; entered A8 at the sep #$20 above); each shadow is a single byte. SHADOW_WHn
    ; are $7E:xxxx symbols, so `lda`/`sta` emit long-form (DB=$00 here).
    lda SHADOW_WH0
    sta $2126                       ; WH0: window 1 left edge
    lda SHADOW_WH1
    sta $2127                       ; WH1: window 1 right edge
    lda SHADOW_WH2
    sta $2128                       ; WH2: window 2 left edge
    lda SHADOW_WH3
    sta $2129                       ; WH3: window 2 right edge

    ; --- Color math registers (Phase 4, blend/tint support) ---
    ; These must be committed every frame so blend() and tint() take effect.
    ; $212D (TS): sub screen designation — which layers on sub screen
    lda ES_SHADOW_TS
    sta $212D                       ; TS: Sub screen designation

    ; $2130 (CGWSEL): color addition select (fixed color vs sub screen)
    lda ES_SHADOW_CGWSEL
    sta $2130                       ; CGWSEL: Color math control

    ; $2131 (CGADSUB): color math designation (add/sub, which layers, half)
    lda ES_SHADOW_CGADSUB
    sta $2131                       ; CGADSUB: Color math designation

    ; $2132 (COLDATA): fixed color — requires 3 channel-specific writes
    ; Each write selects one channel (R=bit5, G=bit6, B=bit7) + intensity (bits 0-4)
    lda ES_SHADOW_COLDATA_R
    and #$1F
    ora #$20                        ; bit 5 = red channel select
    sta $2132                       ; COLDATA: red channel

    lda ES_SHADOW_COLDATA_G
    and #$1F
    ora #$40                        ; bit 6 = green channel select
    sta $2132                       ; COLDATA: green channel

    lda ES_SHADOW_COLDATA_B
    and #$1F
    ora #$80                        ; bit 7 = blue channel select
    sta $2132                       ; COLDATA: blue channel

    ; --- Mode 7 VBlank register commit (M7SEL, center X/Y) ---
    .include "mode7_nmi.inc"

    ; --- Mode 7 2-axis tilemap streaming VBlank DMA (Streaming rail v2) ---
    ; Opt-in: only ROMs that define MODE7_STREAM_NMI (the Mode 7 streaming
    ; rail) pull this in; all other ROMs are unaffected. DMAs the staged
    ; row/col buffers into the Mode 7 VRAM tilemap low bytes. Entry/exit:
    ; DP=$0100, DB=$00, A16/I16 (matches the surrounding handler state).
.ifdef MODE7_STREAM_NMI
    .include "mode7_stream_nmi.inc"
.endif

    ; === Phase 5: HDMA Channel Setup ===
    ; Configure DMA channel registers for each active HDMA channel, then enable.
    ; Channel config is at ES_HDMA_CHn offsets, set by hdma_engine.asm.
    ; NMI DP=$0100, so ES_HDMA_CH3_DMAP at offset $52 maps to $0152.
    ; IMPORTANT: $420C must be written AFTER channel registers are configured,
    ; not before, to avoid one frame of HDMA with stale channel config.
    ;
    ; Phase 17-13 ownership gate: each per-channel commit checks BOTH
    ; the enable bit (in ES_HDMA_ENABLE_MASK) AND the ownership bit
    ; (in ES_M7_OWNED_MASK). The shadow→hardware copy fires only when
    ; the channel is enabled AND owned by Mode 7 (Brad's pv_rebuild
    ; writes to that channel's shadow). When a channel is enabled but
    ; NOT in M7_OWNED_MASK, it was programmed directly to hardware by
    ; some other effect (mode_bands_commit, gradient_rgb, wave, iris,
    ; scanline_scroll — all retrofitted in Steps 4-5). The NMI leaves
    ; that channel's hardware regs alone; only $420C re-arm at the
    ; bottom of this block applies. See docs/sprints/phase_17_13_*.md.
    lda ES_HDMA_ENABLE_MASK
    bne @hdma_setup
    ; Mask is 0 — disable all HDMA channels and skip config
    sta $420C                       ; HDMAEN = 0 (disables all)
    jmp @no_hdma
@hdma_setup:

    ; Configure channel 2 if enabled AND Mode-7-owned.
    ; (Phase 17-13: CH2 is reserved by hdma_alloc_init for GP-DMA so
    ; M7_OWNED_MASK never has bit $04 set today; the gate is correct
    ; for the future when Mode 7 might claim CH2 for a matrix variant.)
    bit #$04
    beq @skip_ch2
    lda ES_M7_OWNED_MASK
    bit #$04
    beq @skip_ch2
    lda ES_HDMA_CH2_DMAP
    sta $4320                       ; DMAP2
    lda ES_HDMA_CH2_BBAD
    sta $4321                       ; BBAD2
    lda ES_HDMA_CH2_TBL_LO
    sta $4322                       ; A1T2L
    lda ES_HDMA_CH2_TBL_HI
    sta $4323                       ; A1T2H
    lda #$7E
    sta $4324                       ; A1B2 (bank = $7E for WRAM)
@skip_ch2:

    ; Configure channel 3 if enabled AND Mode-7-owned.
    lda ES_HDMA_ENABLE_MASK
    bit #$08
    beq @skip_ch3
    lda ES_M7_OWNED_MASK
    bit #$08
    beq @skip_ch3
    lda ES_HDMA_CH3_DMAP
    sta $4330                       ; DMAP3
    lda ES_HDMA_CH3_BBAD
    sta $4331                       ; BBAD3
    lda ES_HDMA_CH3_TBL_LO
    sta $4332                       ; A1T3L
    lda ES_HDMA_CH3_TBL_HI
    sta $4333                       ; A1T3H
    lda #$7E
    sta $4334                       ; A1B3 (bank = $7E for WRAM)
@skip_ch3:

    ; Configure channel 4 if enabled AND Mode-7-owned.
    lda ES_HDMA_ENABLE_MASK
    bit #$10
    beq @skip_ch4
    lda ES_M7_OWNED_MASK
    bit #$10
    beq @skip_ch4
    lda ES_HDMA_CH4_DMAP
    sta $4340                       ; DMAP4
    lda ES_HDMA_CH4_BBAD
    sta $4341                       ; BBAD4
    lda ES_HDMA_CH4_TBL_LO
    sta $4342                       ; A1T4L
    lda ES_HDMA_CH4_TBL_HI
    sta $4343                       ; A1T4H
    lda #$7E
    sta $4344                       ; A1B4
@skip_ch4:

    ; Configure channel 5 if enabled AND Mode-7-owned.
    lda ES_HDMA_ENABLE_MASK
    bit #$20
    beq @skip_ch5
    lda ES_M7_OWNED_MASK
    bit #$20
    beq @skip_ch5
    lda ES_HDMA_CH5_DMAP
    sta $4350                       ; DMAP5
    lda ES_HDMA_CH5_BBAD
    sta $4351                       ; BBAD5
    lda ES_HDMA_CH5_TBL_LO
    sta $4352                       ; A1T5L
    lda ES_HDMA_CH5_TBL_HI
    sta $4353                       ; A1T5H
    lda #$7E
    sta $4354                       ; A1B5
@skip_ch5:

    ; Configure channel 6 if enabled AND Mode-7-owned.
    lda ES_HDMA_ENABLE_MASK
    bit #$40
    beq @skip_ch6
    lda ES_M7_OWNED_MASK
    bit #$40
    beq @skip_ch6
    lda ES_HDMA_CH6_DMAP
    sta $4360                       ; DMAP6
    lda ES_HDMA_CH6_BBAD
    sta $4361                       ; BBAD6
    lda ES_HDMA_CH6_TBL_LO
    sta $4362                       ; A1T6L
    lda ES_HDMA_CH6_TBL_HI
    sta $4363                       ; A1T6H
    lda #$7E
    sta $4364                       ; A1B6
@skip_ch6:

    ; Configure channel 7 if enabled AND Mode-7-owned.
    lda ES_HDMA_ENABLE_MASK
    bit #$80
    beq @skip_ch7
    lda ES_M7_OWNED_MASK
    bit #$80
    beq @skip_ch7
    lda ES_HDMA_CH7_DMAP
    sta $4370                       ; DMAP7
    lda ES_HDMA_CH7_BBAD
    sta $4371                       ; BBAD7
    lda ES_HDMA_CH7_TBL_LO
    sta $4372                       ; A1T7L
    lda ES_HDMA_CH7_TBL_HI
    sta $4373                       ; A1T7H
    lda #$7E
    sta $4374                       ; A1B7
@skip_ch7:

    ; Enable all active HDMA channels
    lda ES_HDMA_ENABLE_MASK
    sta $420C                       ; HDMAEN

@no_hdma:

    ; === Phase 6: Auto-Joypad Read ===
    ; Poll $4212 bit 0 until auto-joypad read completes.
    ; By this point, DMA Phase 3 has consumed enough time that the
    ; auto-read (~4,224 MC) is almost certainly done.
@wait_joypad:
    lda $4212                   ; HVBJOY
    and #$01                    ; Bit 0 = auto-joypad in progress
    bne @wait_joypad            ; Loop until complete

    ; Read controller 1 state
    rep #$20
    .a16
    lda $4218                   ; JOY1 (16-bit: both JOY1L and JOY1H)
    sta ES_JOY1_CURRENT

    ; Edge detection: new_pressed = (current XOR previous) AND current
    ; Uses ORA to accumulate rising edges across NMI cycles. This prevents
    ; lost button presses when game code overruns the frame boundary and
    ; NMI fires mid-execution. The frame lifecycle latches and clears
    ; JOY1_PRESSED at INPUT phase so game code reads a stable snapshot.
    eor ES_JOY1_PREVIOUS       ; A = bits that changed
    and ES_JOY1_CURRENT        ; A = bits that are now pressed (rising edge)
    ora ES_JOY1_PRESSED        ; Accumulate — don't lose presses on overrun
    sta ES_JOY1_PRESSED

    ; Store current as previous for next frame
    lda ES_JOY1_CURRENT
    sta ES_JOY1_PREVIOUS

    ; Read controller 2 state
    lda $421A                   ; JOY2 (16-bit)
    sta ES_JOY2_CURRENT

    eor ES_JOY2_PREVIOUS
    and ES_JOY2_CURRENT
    ora ES_JOY2_PRESSED        ; Accumulate P2 presses
    sta ES_JOY2_PRESSED

    lda ES_JOY2_CURRENT
    sta ES_JOY2_PREVIOUS

    ; === Phase 7: Frame Counter and Stats ===
    ; Increment global frame counter
    inc ES_FRAME_COUNTER

    ; Signal main thread that NMI processing is complete
    sep #$20
    .a8
    lda #$01
    sta ES_NMI_DONE_FLAG

    ; === Phase 8: Register Restoration ===
    rep #$30                    ; 16-bit A/X/Y for pulling
    .a16
    .i16
    plb                         ; Restore Data Bank
    pld                         ; Restore Direct Page
    ply                         ; Restore Y
    plx                         ; Restore X
    pla                         ; Restore A
    rti                         ; Return from interrupt (restores P, PC, PB)
