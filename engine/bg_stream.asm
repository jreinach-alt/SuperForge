; =============================================================================
; bg_stream.asm — Mode-1 normal-BG horizontal column-streaming PRODUCER.
; =============================================================================
; Streaming rail (Mode 1 platformer) / Sprint S1. This is the kit-resident
; PORT of the proven Phase-17 BG1 column-streaming producer
; (parent engine/streaming_engine.asm). It pairs with the kit's NMI consumer
; in engine/nmi_handler.asm (the STREAM_PENDING drain) to slide a window over
; a level WIDER than the 64-column BG1 hardware tilemap: columns ahead of the
; camera's leading edge are kept fresh by per-frame VBlank DMA into the
; position-wrapped ring slot (world_col & $3F). Reverse + idle handled too.
;
; Public front door (also reachable via lib/macros/sf_stream.inc):
;   bg_stream_init  — boot: bulk-DMA the first 64 columns to BG1 VRAM.
;                     Inputs on DP $20-$24 (24-bit level ptr + 16-bit width).
;   bg_stream_tick  — per-frame: queue leading/trailing columns for the NMI
;                     consumer to DMA. Caller sets STREAM_CAM_COL = cam_x>>3
;                     (8px tile columns) BEFORE each call.
;
; The internal routine bodies (streaming_init / streaming_update_bg1 /
; streaming_compute_next_col) are ported verbatim from the proven Phase-17
; producer; bg_stream_init / bg_stream_tick are thin aliases (label
; equates) so kit ROMs and S2 extend a stable, descriptively-named API.
; The per-routine WIDTH-RISK contracts below are preserved unchanged.
;
; Contract recap (matches the kit consumer + engine_state.inc STREAM_* block):
;   - BG1SC = $59 (64x32 tilemap @ VRAM word $5800-$5FFF), pair-mode word
;     writes, VMAIN stride-32, 64-byte columns.
;   - Level data ROM-resident, COLUMN-MAJOR: 32 tiles x 2 bytes per column;
;     produced by tools/level_pipeline_bg.py (flat, bank-aligned).
;   - STREAM_PENDING is a SLOT COUNT (0..STREAM_PENDING_MAX_SLOTS); the NMI
;     consumer re-arms DAS per slot (DAS is single-shot — CLAUDE.md).
;   - DMA channel allocated via hdma_request (graceful degrade if none free).
; =============================================================================
;
; --- Original header (parent streaming_engine.asm) -------------------------
; streaming_engine.asm — BG1 Tilemap Streaming Engine (Phase 17 Sprint A)
; =============================================================================
; Maintains a "sliding window" over a level wider than the 64-column hardware
; BG1 tilemap. Columns 8 tiles ahead of the camera's leading edge are kept
; fresh by per-frame VBlank DMA into the wrap zone of BG1 VRAM. Columns far
; behind are overwritten naturally when the wrap-zone modulo cycles.
;
; Scope (Sprint B redo):
;   - Engine routines, all main-thread (no NMI protocol).
;   - BG1 only. SHADOW_BG1_TILEMAP at $7E:A200 is mirrored to track the
;     visible 32-column window as the camera scrolls. Each streamed VRAM
;     column is paralleled by a write to the shadow at ring slot
;     (world_col & $1F). col_map reads the shadow unchanged.
;   - 64×32 hardware tilemap (BG1SC = $59) at VRAM word $5800-$5FFF.
;   - Level data is ROM-resident, column-major: 32 tiles × 2 bytes per column.
;
; Shadow contract (Sprint B final):
;   SHADOW_BG1_TILEMAP at $7E:A200 is a 32×32 ring mirror of the visible
;   window (NOT a 64×32 buffer like the hardware tilemap). For world
;   column N: shadow_slot = N & $1F, shadow_addr = $A200 + slot*2 + row*64.
;
;   Templates call col_map with raw world pixel coords:
;     col_map(world_x, world_y, 1, FLAG_BIT)
;   The engine handles the ring slot translation: when STREAM_ACTIVE != 0
;   (set by streaming_init), engine_col_map's BG1 path masks
;   tile_x &= $1F before bounds-check, so any world_x maps cleanly into
;   the ring shadow. No caller-side `world_col & $1F` is required.
;   See engine/collision_engine.asm @layer_bg1 for the wrap.
;
; Calling convention (main thread, DP=$0000, DB=$00):
;   streaming_init        — boot: bulk-DMA first 64 columns to BG1 VRAM.
;   streaming_update_bg1  — per-frame: stream next column to BG1 VRAM.
;
; Sprint C (issue #126) architecture: cooperative NMI signaling.
;   streaming_update_bg1 (main thread) computes the next column's
;   VRAM address + ROM source pointer, raises STREAM_PENDING = 1,
;   and mirrors the column into SHADOW_BG1_TILEMAP (WRAM only — no
;   PPU access). The engine NMI handler reads STREAM_PENDING during
;   VBlank, performs the column DMA into BG1 VRAM (where forced
;   blank is natural and bytes don't show), and clears the flag.
;   This restores the original Sprint A signaling pattern after
;   Sprint B's inline forced-blank DMA caused a visible black band
;   at y≈16-24 every time streaming fired (issue #126).
;
; VRAM layout (64×32 BG1 tilemap, BG1SC=$59):
;   Page 0 (cols 0-31): VRAM words $5800-$5BFF (1 KB)
;   Page 1 (cols 32-63): VRAM words $5C00-$5FFF (1 KB)
;   Wrap zone: same physical VRAM is reused for cols 64+, 128+, 192+, ...
;   For world column N: vram_slot = N & $3F (0-63).
;     If vram_slot < 32:  vram_addr = $5800 + vram_slot           (page 0, col `slot`)
;     Else:               vram_addr = $5C00 + (vram_slot - 32)    (page 1, col `slot-32`)
;   Each column is 32 words (64 bytes) at stride 32 (VMAIN = $01).
;
; Level data layout (ROM, column-major):
;   level[col=N][row=R] = 16-bit tile word at offset (N * 64 + R * 2).
;   Source bank may be any LoROM bank ($00-$3F or $80-$BF).
;   Each column DMA is 64 bytes; if a 64-byte column would cross a 64KB
;   bank boundary, splitting is the caller's problem (level data must be
;   bank-aligned). Our boot DMA covers 64 columns × 64 bytes = 4 KB which
;   fits comfortably in any LoROM 32 KB bank slot.
;
; Cross-ref: engine_state.inc (STREAM_* equates), tests/phase_streaming/
;            test_streaming_4096.asm (NMI consumer), CLAUDE.md (width-risk).
; =============================================================================

.p816
.smart

.include "engine_state.inc"

; --- API ---
.export streaming_init
.export streaming_update_bg1
.export streaming_compute_next_col

; Kit-clean public aliases (descriptive front-door names; the macro layer
; lib/macros/sf_stream.inc calls these). Defined as label equates AFTER the
; routines below (ca65 forward-refs resolve at link). Also .export'd so a
; multi-.o link (should a future kit ROM split bg_stream into its own unit)
; resolves the names; in the single-.o .include path the .export is a no-op.
.export bg_stream_init
.export bg_stream_tick

; --- External symbols (defined in engine/hdma_alloc.asm) ---
;
; Two link shapes are supported:
;   - SEPARATE compilation units (bg_stream.o + hdma_alloc.o linked together):
;     the streaming side needs an .import to resolve hdma_request at link time.
;   - SINGLE compilation unit (a ROM .include's BOTH files — the kit's default,
;     e.g. tests/bg_stream_test.asm): hdma_request is locally defined and
;     .export'd by hdma_alloc.asm; a second .import here would trigger
;     "symbol already defined". The HDMA_ALLOC_PROVIDED sentinel (set at the
;     top of hdma_alloc.asm) lets us detect that case and skip the .import.
;     The including ROM MUST .include hdma_alloc.asm BEFORE this file.
.ifndef HDMA_ALLOC_PROVIDED
.import hdma_request
.endif

; BG1 tilemap base in VRAM (word address). Test ROM must set BG1SC = $59
; (base $58 + 64×32 size bit) before calling streaming_init.
STREAM_BG1_VRAM_BASE = $5800
STREAM_BG1_PAGE1_OFF = $0400      ; page 1 (cols 32-63) = $0400 words into base
STREAM_BG1_VPAGE_OFF = $0800      ; vertical page (rows 32-63, SC2/SC3) — only
                                  ; used in 2-axis (64x64) mode (BG_STREAM_2AXIS)
STREAM_LOOK_AHEAD    = 40         ; look-ahead distance in 8×8 tile cols.
                                  ; = 32 (visible screen width in tile cols)
                                  ; + 8 (per-frame streaming cap headroom).
                                  ; Issue #125: the previous value of 8
                                  ; was an off-by-units bug — frame_lifecycle
                                  ; converted cam_x to metatile cols (/16)
                                  ; while STREAM_LAST_COL counted tile cols
                                  ; (/8), so streaming triggered far too late
                                  ; to keep up with the visible 32-col screen.
STREAM_COL_BYTES     = 64         ; 32 tiles × 2 bytes
STREAM_COLUMNS_BOOT  = 64         ; 64 columns populated at boot

; --- streaming_init ---
;
; Inputs (caller fills these on $00 page before JSR):
;   $20-$22  STREAM_LEVEL_DATA_PTR  (24-bit ROM ptr; copied to engine state)
;   $23-$24  STREAM_LEVEL_WIDTH_T   (16-bit; copied to engine state)
;
; Behavior:
;   - Stores caller-provided level pointer + width into engine state.
;   - Resets STREAM_CAM_COL = 0, STREAM_LAST_COL = 63.
;   - Sets STREAM_ACTIVE = 1, STREAM_PENDING = 0.
;   - Performs BLOCKING DMA of 4 KB (64 columns × 64 bytes) into BG1 VRAM
;     pages 0 and 1. The DMA uses VMAIN=$01 (stride 32, after $2118 low),
;     channel 0, two transfers (page 0 = cols 0-31, page 1 = cols 32-63).
;     Caller is responsible for ensuring forced-blank or NMI gating around
;     this call — the boot DMA halts the CPU for ~40 µs total.
;
; Entry width: A8/I16. Exits A8/I16. Clobbers A, X, Y.
;
; WIDTH-RISK: routine toggles A-width several times around DMA register
; configuration. Marked with .a8/.a16 at every transition. Establishes
; I16 explicitly on entry; caller's I-width is restored implicitly via
; rts since we never sep/rep #$10.
streaming_init:
    rep #$10                    ; force I16
    .i16
    sep #$20                    ; A8 entry
    .a8

    ; --- Copy 24-bit ROM ptr from $20 to STREAM_LEVEL_DATA_PTR ($0590) ---
    lda $20
    sta f:$7E0000 + STREAM_LEVEL_DATA_PTR + 0
    lda $21
    sta f:$7E0000 + STREAM_LEVEL_DATA_PTR + 1
    lda $22
    sta f:$7E0000 + STREAM_LEVEL_DATA_PTR + 2

    ; --- Copy 16-bit level width from $23-$24 ---
    lda $23
    sta f:$7E0000 + STREAM_LEVEL_WIDTH_T + 0
    lda $24
    sta f:$7E0000 + STREAM_LEVEL_WIDTH_T + 1

    ; --- Reset trackers: cam_col = 0, first_col = 0, last_col = 63, pending = 0 ---
    ; STREAM_ACTIVE is set later (only after hdma_request succeeds).
    ; Phase 17 Sprint D-9: STREAM_FIRST_COL added to support reverse-direction
    ; streaming (the ring's "lowest streamed col" pointer). Boot fills cols
    ; 0..63, so the invariant STREAM_LAST_COL - STREAM_FIRST_COL == 63
    ; holds from the first frame.
    lda #$00
    sta f:$7E0000 + STREAM_CAM_COL + 0
    sta f:$7E0000 + STREAM_CAM_COL + 1
    sta f:$7E0000 + STREAM_FIRST_COL + 0
    sta f:$7E0000 + STREAM_FIRST_COL + 1
    lda #STREAM_COLUMNS_BOOT - 1
    sta f:$7E0000 + STREAM_LAST_COL + 0
    lda #$00
    sta f:$7E0000 + STREAM_LAST_COL + 1
    sta f:$7E0000 + STREAM_ACTIVE         ; ACTIVE = 0 until allocator succeeds
    sta f:$7E0000 + STREAM_PENDING

    ; --- Phase 17 Sprint B (final): allocate one DMA channel ---
    ; hdma_request param: A16 = ($0001) = n_channels=1, priority=0, mode=0.
    ; Effect ID = HDMA_EFFECT_STREAMING ($09). Returns A16 = mask (0 = fail).
    ; WIDTH-RISK: hdma_request requires A16/I16 entry, returns A16/I16.
    ; We re-toggle to A8 immediately afterwards to match streaming_init's
    ; A8 working width.
    rep #$30
    .a16
    .i16
    lda #$0001                  ; n=1, prio=0, mode=0
    ldx #HDMA_EFFECT_STREAMING
    jsr hdma_request
    ; A16 = allocated mask (bits 2..7); 0 if no channel free.
    cmp #$0000
    beq @alloc_fail

    ; Find bit position (2..7) of the lowest set bit. mask is in bits 2..7
    ; only (allocator never grants CH0/CH1). Naive scan: shift A right
    ; until carry is set, counting iterations starting from channel 0.
    ; A16 still holds the mask from hdma_request.
    sep #$20
    .a8
    ldx #$0000                  ; channel counter (16-bit since I16)
@find_bit:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label
    lsr a                       ; shift A right; carry = LSB
    bcs @found
    inx
    cpx #$0008                  ; safety bound: channels 0..7
    bcc @find_bit
    ; Should be unreachable — we already checked mask != 0.
    bra @alloc_fail
@found:
    .a8                         ; ; WIDTH-LINT: ok — branch target reached A8/I16
    ; X = channel number (2..7).
    txa
    sta f:$7E0000 + STREAM_DMA_CHAN
    ; Streaming is now allocated and ready. Mark ACTIVE.
    lda #$01
    sta f:$7E0000 + STREAM_ACTIVE
    bra @alloc_done

@alloc_fail:
    .a16                        ; ; WIDTH-LINT: ok — reached A16/I16 path from BEQ
    ; Allocator returned 0 — no free channel. Graceful degrade: leave
    ; STREAM_ACTIVE = 0 and skip the boot DMA. Caller (template/scene)
    ; can detect this by reading STREAM_ACTIVE; engine_update_bg1 also
    ; checks STREAM_ACTIVE every frame and bails when 0.
    sep #$20
    .a8
    rts

@alloc_done:
    .a8                         ; ; WIDTH-LINT: ok — reached A8/I16 from @found

    ; --- Boot bulk DMA: populate first 64 columns of BG1 VRAM ---
    ; Approach: 64 separate column DMAs (one per column), each 64 bytes
    ; with VMAIN=$01 stride. Total ~64 × 75 = ~4800 cycles of DMA + ~32
    ; cycles of CPU overhead per column. This is forced-blank/init-time
    ; work; the test ROM holds INIDISP=$80 across this call.
    ;
    ; Why per-column (not bulk 4 KB): a column's 32 words are NOT
    ; contiguous in VRAM. Within a 32×32 page they're at stride 32
    ; (one word per tilemap row). A single 4 KB DMA with VMAIN=$01 would
    ; write 4096/2 = 2048 words at stride 32 — but VRAM wraps after the
    ; first column's 32-word write; we'd corrupt downstream pages.
    ;
    ; Per-column is the correct, hardware-aligned pattern.

    ; VMAIN = $81: increment after HIGH byte ($2119) write, stride 32
    ; words. In pair-mode DMA (DMAP=$01) we must increment after the
    ; high byte so the low+high pair of each tile word lands at the
    ; same VRAM address; otherwise VMADD shifts between byte writes
    ; and tiles get smeared one row.
    lda #$81
    sta $2115

    ; --- Phase 17 Sprint B (final): use allocated channel ---
    ; Compute reg_base = $4300 + STREAM_DMA_CHAN * 16. Stored in DP $A0
    ; (16-bit). Channel-specific register addresses are reached via
    ; absolute,X where X holds (STREAM_DMA_CHAN * 16).
    ;
    ; mdma_trigger_mask = 1 << STREAM_DMA_CHAN (8-bit), stored in DP $A2.
    ;
    ; WIDTH-RISK: A8 entry; we toggle to A16 to compute the offsets,
    ; then back to A8 for the per-DMA-trigger path. Both transitions
    ; carry .a8/.a16 markers below.
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_DMA_CHAN
    and #$00FF                  ; mask to byte (chan 0..7)
    asl
    asl
    asl
    asl                         ; chan << 4 = chan * 16
    sta $A0                     ; reg-base offset (0, 16, 32, ..., 112)
    tax                         ; X = reg-base offset (used as ABS,X index below)
    sep #$20
    .a8

    ; Compute MDMAEN trigger bitmask (1 << chan).
    ; Chan ∈ 2..7 → bit 2..7. Use a small loop. ldy doesn't take long
    ; addressing on 65816, so we read STREAM_DMA_CHAN via A first then tay.
    lda f:$7E0000 + STREAM_DMA_CHAN
    rep #$10
    .i16
    and #$00FF
    tay                         ; ; WIDTH-LINT: ok — A8/I16 tay; A and-masked to 0..7
    lda #$01                    ; bit accumulator
    cpy #$0000
    beq @mdma_done
@mdma_shift:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label
    asl
    dey
    bne @mdma_shift
@mdma_done:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BNE/BEQ
    sta $A2                     ; cached MDMAEN bit

    ; DMA channel config: A-bus → B-bus, increment, mode 1 (2-byte LH pair).
    ; $4300 + chan*16 + 0 = DMAP, +1 = BBAD.
    lda #$01                    ; DMAP: mode 01 (write $2118+$2119, pair, inc)
    sta $4300, x                ; channel-relative DMAP
    lda #$18                    ; BBAD: $2118 (VMDATAL)
    sta $4301, x

    ; --- Loop columns 0..63, do per-column DMA ---
    ; X holds (chan * 16) entering the loop; we save/restore it across
    ; the column counter usage by stashing in $A0. Inside the loop we
    ; use a separate I16 column counter (in Y to keep X free for the
    ; channel offset).
    ldy #$0000                  ; Y = column counter (0..63)
@boot_col_loop:
    .a8

    ; Compute VRAM address for this column.
    ;   slot = column (since columns < 64, no modulo needed at boot)
    ;   if slot < 32: vaddr = $5800 + slot
    ;   else:         vaddr = $5C00 + (slot - 32)
    cpy #32
    bcc @boot_page0
    ; Page 1: vaddr = $5C00 + (col - 32)
    rep #$20
    .a16
    tya
    clc
    adc #STREAM_BG1_VRAM_BASE + STREAM_BG1_PAGE1_OFF - 32
    sta $2116                   ; VMADDL/H
    sep #$20
    .a8
    bra @boot_set_src
@boot_page0:
    .a8                         ; ; WIDTH-LINT: ok — branch target from .a8 path
    ; Page 0: vaddr = $5800 + col
    rep #$20
    .a16
    tya
    clc
    adc #STREAM_BG1_VRAM_BASE
    sta $2116
    sep #$20
    .a8
@boot_set_src:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label
    ; Compute source = level_ptr + col * 64 (24-bit add). Compute into
    ; DP scratch $AA-$AC first (Engine scratch region per CLAUDE.md DP
    ; map; $20-$2F is reserved for engine A0-A7 register block). Then
    ; forward to DMA registers. The DP copy is also the input to
    ; _stream_shadow_write_col below.
    rep #$20
    .a16
    tya
.ifdef BG_STREAM_2AXIS
    ; 2-axis: 128-tall column-major level, COL_BYTES = 256 -> col << 8.
    .repeat 8
    asl
    .endrep
.else
    ; S1: 32-tall column-major level, COL_BYTES = 64 -> col << 6.
    .repeat 6
    asl
    .endrep
.endif
    clc
    adc f:$7E0000 + STREAM_LEVEL_DATA_PTR + 0
    sta $AA                     ; src ptr low 16
    ; X holds (chan*16); $4302 + X = A1Tn L/H for selected channel.
    ldx $A0                     ; restore X (Y was clobbered during arithmetic? No, only A.)
    sta $4302, x                ; A1TnL/H: source low 16
    sep #$20
    .a8
    ; High byte of source: col * 64 may overflow into bits 16+ for cols ≥ 1024,
    ; but at boot col ≤ 63 → col * 64 ≤ 4032, which fits in 16 bits. So we
    ; just copy the level_ptr's bank byte through, plus carry from the add.
    lda f:$7E0000 + STREAM_LEVEL_DATA_PTR + 2
    adc #$00                    ; +carry from prior 16-bit add
    sta $AC                     ; src ptr bank
    sta $4304, x                ; A1Bn: source bank

    ; Transfer size = 64 bytes
    rep #$20
    .a16
    lda #STREAM_COL_BYTES
    sta $4305, x                ; DASnL/H
    sep #$20
    .a8

    ; Trigger DMA on selected channel (rows 0..31 of this column -> SC0/SC1).
    lda $A2                     ; cached (1 << chan) bit
    sta $420B                   ; MDMAEN

.ifdef BG_STREAM_2AXIS
    ; --- 2-axis boot sub-DMA: rows 32..63 of this column -> SC2/SC3 page ---
    ; VADDR_B = VADDR_A + $800 ; src_B = src_A + 64 (column-major rows 32..63
    ; start 64 bytes into the 256-byte column). Same stride-32, 32 words.
    ; VADDR_A = $5800 + (col>=32 ? $400 : 0) + (col & 31)  [col = Y].
    rep #$20
    .a16
    tya
    and #$001F                  ; col & 31 (within-page col)
    sta $A8
    tya
    cmp #$0020
    bcc @boot_b_pg0
    lda $A8
    clc
    adc #STREAM_BG1_VRAM_BASE + STREAM_BG1_PAGE1_OFF + STREAM_BG1_VPAGE_OFF
    bra @boot_b_vaddr
@boot_b_pg0:
    .a16                        ; WIDTH-LINT: ok — branch target from BCC
    lda $A8
    clc
    adc #STREAM_BG1_VRAM_BASE + STREAM_BG1_VPAGE_OFF
@boot_b_vaddr:
    .a16                        ; WIDTH-LINT: ok — multi-path label
    sta $2116
    ldx $A0                     ; X = chan offset
    lda $AA
    clc
    adc #$0040                  ; src_A + 64 (rows 32..63)
    sta $4302, x
    lda #STREAM_COL_BYTES       ; DAS = 64 bytes (32 words)
    sta $4305, x
    sep #$20
    .a8
    lda $AC                     ; src bank (col<64 so no extra overflow)
    adc #$00
    sta $4304, x
    lda $A2
    sta $420B                   ; trigger rows-32..63 DMA
.endif

    ; --- Mirror this column into SHADOW_BG1_TILEMAP. ---
    ; Phase 17 Sprint D-5 Bug B: the SHADOW is now a 64×32 ring matching
    ; the BG1 hardware tilemap (BG1SC=$59). Boot mirrors all 64 cols
    ; (slot = col & $3F = col, since col < 64); cols 32..63 are no
    ; longer skipped. This closes the col_map [32..63] data hole that
    ; D-3 surfaced (see _stream_shadow_write_col header for full
    ; rationale).
    ;
    ; Pre-D-5: cols 32..63 were skipped because the 32-col ring would
    ; have overwritten cols 0..31. With the ring expanded to 64 cols
    ; the slot equals the world col exactly during boot.
    ;
    ; Shadow helper expects col in $A5 and src ptr in $AA-$AC (already
    ; populated above). Helper exits A8/I16 like its caller. The boot
    ; loop uses Y as the column counter (X holds the channel-base offset);
    ; the helper clobbers X and Y, so save Y across the call. (X gets
    ; restored from $A0 cache after the call.)
    rep #$20
    .a16
    tya
    sta $A5
    sep #$20
    .a8
    phy                         ; preserve Y (col counter) across helper
    jsr _stream_shadow_write_col
    ply                         ; restore col counter

    ; Advance column counter
    rep #$20
    .a16
    iny
    cpy #STREAM_COLUMNS_BOOT
    sep #$20
    .a8
    ; The 2-axis sub-DMA block lengthened the loop body past BCC's -128 reach,
    ; so use a long jump back (BCS skip + JMP).
    bcs @boot_col_done
    jmp @boot_col_loop
@boot_col_done:
    .a8                         ; WIDTH-LINT: ok — branch target from BCS

    rts


; --- streaming_compute_next_col ---
;
; Compute-only helper: decides whether a new column needs streaming, and
; if so, advances STREAM_LAST_COL and populates STREAM_PENDING_VADDR +
; STREAM_PENDING_SRC. Does NOT fire any DMA. STREAM_PENDING is not set.
;
; Inputs:
;   STREAM_CAM_COL, STREAM_LAST_COL, STREAM_LEVEL_WIDTH_T,
;   STREAM_LEVEL_DATA_PTR.
;   STREAM_PENDING (1 byte) — if non-zero, returns early (caller's signal
;   that a prior compute is "still in flight"; preserved from cooperative-NMI
;   era for test compatibility).
;
; Outputs:
;   - Carry CLEAR: nothing to stream (or pending). State unchanged.
;   - Carry SET:   STREAM_LAST_COL incremented; STREAM_PENDING_VADDR +
;                  STREAM_PENDING_SRC populated for the new column.
;
; Entry width: A8/I16. Exits A8/I16. Clobbers A, X, Y, scratch $A5-$A9.
;
; WIDTH-RISK: this routine has multiple branches that converge at exit
; labels. All branch targets carry .a8/.a16 annotations matching CPU
; runtime width. Forces I16 on entry to match the engine's calling
; convention.
;
; DP scratch convention: $A0-$AF is "Engine scratch" (Direct Page register-file
; map). $20-$2F is the engine A0-A7 parameter-passing block (the API block used
; by engine function calls such as engine_scroll). Streaming scratch lives at
; $A5-$AE (declared as ES_BG_STREAM_COL et al. in engine_state.inc) precisely
; to avoid colliding with that API block.
streaming_compute_next_col:
    rep #$10                    ; force I16
    .i16
    sep #$20                    ; A8 entry
    .a8

    ; STREAM_PENDING is now a slot count (0..STREAM_PENDING_MAX_SLOTS).
    ; If the queue is FULL, bail with carry clear — caller's frame budget
    ; for queueing has been used up; NMI must drain before the next
    ; round. If not full, we're free to compute another column into the
    ; next slot.
    lda f:$7E0000 + STREAM_PENDING
    cmp #STREAM_PENDING_MAX_SLOTS
    bcc @check_target           ; count < MAX → room for another slot
    clc
    rts                         ; count >= MAX → queue full

@check_target:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BCC
    ; Phase 17 Sprint D-9: bidirectional streaming.
    ; The ring window is [FIRST_COL, LAST_COL] with the invariant
    ; LAST_COL - FIRST_COL == 63. We need to ensure the visible+lookahead
    ; window [cam_col, cam_col + LOOK_AHEAD - 1] is fully contained in
    ; that ring window, and rebuild ring slots if either edge has moved
    ; outside it.
    ;
    ; Two trigger conditions, checked in order:
    ;   1. FORWARD: LAST_COL < cam_col + LOOK_AHEAD
    ;      → stream LAST_COL+1; LAST_COL++; FIRST_COL++.
    ;   2. REVERSE: cam_col < FIRST_COL
    ;      → stream FIRST_COL-1; FIRST_COL--; LAST_COL--.
    ; Each call queues at most one column. The caller's loop in
    ; streaming_update_bg1 keeps calling until carry-clear (up-to-date
    ; or queue full).
    ;
    ; Forward takes precedence: if the player suddenly reverses near
    ; level start, we'd rather keep the look-ahead populated than chase
    ; trailing edges. Reverse only fires when the forward edge is
    ; already covered.

    ; --- FORWARD trigger ---
    ; Compute forward target = cam_col + LOOK_AHEAD, capped at width-1.
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_CAM_COL
    clc
    adc #STREAM_LOOK_AHEAD
    ; Target may exceed level width — cap at width-1 to avoid streaming
    ; past the level boundary (would read garbage from ROM).
    cmp f:$7E0000 + STREAM_LEVEL_WIDTH_T
    bcc @target_in_range
    ; target >= width: cap at width-1
    lda f:$7E0000 + STREAM_LEVEL_WIDTH_T
    sec
    sbc #$0001
@target_in_range:
    .a16                        ; ; WIDTH-LINT: ok — A16 from rep above
    sta $A5                     ; cache forward target in DP scratch

    ; Compare last_col to forward target.
    lda f:$7E0000 + STREAM_LAST_COL
    cmp $A5
    bcc @do_forward             ; last_col < target → forward stream
    ; Forward edge is up-to-date. Try reverse.
    bra @check_reverse

@do_forward:
    .a16                        ; ; WIDTH-LINT: ok — branch target from BCC
    ; Advance last_col by 1; new col = last_col+1.
    lda f:$7E0000 + STREAM_LAST_COL
    inc a
    sta f:$7E0000 + STREAM_LAST_COL
    sta $A6                     ; cache new column index in DP
    ; Maintain invariant: FIRST_COL = LAST_COL - 63 → FIRST_COL++.
    lda f:$7E0000 + STREAM_FIRST_COL
    inc a
    sta f:$7E0000 + STREAM_FIRST_COL
    bra @emit_slot

@check_reverse:
    .a16                        ; ; WIDTH-LINT: ok — branch target from BRA
    ; --- REVERSE trigger ---
    ; If cam_col < FIRST_COL, the visible window has moved past the ring's
    ; left edge. Stream FIRST_COL-1 to repopulate the trailing slot.
    ; FIRST_COL=0 is the absolute minimum (level data starts there).
    lda f:$7E0000 + STREAM_FIRST_COL
    beq @up_to_date             ; FIRST_COL == 0 → can't stream further left
    cmp f:$7E0000 + STREAM_CAM_COL
    bcc @up_to_date             ; FIRST_COL < cam_col → in range
    beq @up_to_date             ; FIRST_COL == cam_col → in range
    ; FIRST_COL > cam_col: stream FIRST_COL-1.
    dec a                       ; A = FIRST_COL - 1 (new col)
    sta f:$7E0000 + STREAM_FIRST_COL
    sta $A6                     ; cache new column index in DP
    ; Maintain invariant: LAST_COL = FIRST_COL + 63 → LAST_COL--.
    lda f:$7E0000 + STREAM_LAST_COL
    dec a
    sta f:$7E0000 + STREAM_LAST_COL
    bra @emit_slot

@up_to_date:
    .a16                        ; ; WIDTH-LINT: ok — multi-path branch target
    sep #$20
    .a8
    clc
    rts                         ; nothing to do (carry clear)

@emit_slot:
    .a16                        ; ; WIDTH-LINT: ok — multi-path branch target
    ; $A6 holds the new world col to emit (set by @do_forward or
    ; @check_reverse). Fall through to slot computation.

    ; --- Compute slot byte-offset = STREAM_PENDING * 5 → X.
    ; Indexed addressing into STREAM_PENDING_TBL stores VADDR/SRC at
    ; tbl[count*5 + 0..4]. We then increment STREAM_PENDING at the end
    ; of the routine to publish the new slot to NMI.
    ; STREAM_PENDING is 0..3 here (we bailed at MAX above), so 5*N is
    ; 0,5,10,15 — well within 8-bit X.
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_PENDING
    asl
    asl                         ; A = count * 4
    clc
    adc f:$7E0000 + STREAM_PENDING
    rep #$10
    .i16
    and #$00FF                  ; clear stale C-high bits before tax
    tax                         ; ; WIDTH-LINT: ok — A masked to byte before tax
    rep #$20
    .a16

    ; Compute VRAM address: slot = col & $3F.
    ;   if slot < 32: vaddr = $5800 + slot
    ;   else:         vaddr = $5C00 + (slot - 32)
    lda $A6                     ; reload col (still in $A6 from above)
    and #$003F
    sta $A8                     ; cache slot
    cmp #$0020
    bcc @cmp_page0
    ; Page 1
    sec
    sbc #$0020
    clc
    adc #STREAM_BG1_VRAM_BASE + STREAM_BG1_PAGE1_OFF
    sta f:$7E0000 + STREAM_PENDING_TBL + 0, x
    bra @cmp_compute_src
@cmp_page0:
    .a16                        ; ; WIDTH-LINT: ok — branch target from BCC
    clc
    adc #STREAM_BG1_VRAM_BASE
    sta f:$7E0000 + STREAM_PENDING_TBL + 0, x

@cmp_compute_src:
    .a16                        ; ; WIDTH-LINT: ok — multi-path label
    ; Compute source = level_ptr + col * COL_BYTES as a true 24-bit add.
    ; S1 (single-axis, 32-tall level): COL_BYTES = 64 (col << 6).
    ; S2a (BG_STREAM_2AXIS, 128-tall level): COL_BYTES = 256 (col << 8); a
    ; column then ALSO needs a second sub-slot for rows 32..63 (VADDR += $800,
    ; SRC += 64) because the 64x64 tilemap puts rows 32..63 in pages SC2/SC3.
    ; Two contributions to the bank byte:
    ;   1. (col * COL_BYTES) overflows 16 bits → bank += (col >> (16-shift)).
    ;   2. ((col*COL_BYTES & $FFFF) + ptr_lo16) overflows 16 bits → bank += 1.
    lda $A6                     ; col
.ifdef BG_STREAM_2AXIS
    .repeat 8
    asl                         ; col << 8 = col * 256 (128-tall column-major)
    .endrep
.else
    .repeat 6
    asl                         ; col << 6 = col * 64 (32-tall column-major)
    .endrep
.endif
    clc
    adc f:$7E0000 + STREAM_LEVEL_DATA_PTR + 0
.ifdef BG_STREAM_2AXIS
    ; --- 2-axis vertical-scroll awareness (S2a reverse-Y composition fix) ------
    ; A streamed column must fill the RESIDENT vertical window rows
    ; [STREAM_FIRST_ROW .. STREAM_FIRST_ROW+63], NOT world rows 0..63. Without
    ; this offset, reverse-X (LEFT) traversal while cam_y is deep overwrote the
    ; deep VRAM page (rows 32..63 sub-slot) with column-major world rows 0..63,
    ; destroying the row producer's content — the reverse-Y (UP) deep-region
    ; corruption. Source base += STREAM_FIRST_ROW * 2 (column-major row stride is
    ; 2 bytes). Sub-slot A then streams rows first_row..first_row+31 to the
    ; shallow page and sub-slot B (SRC += 64 below) rows first_row+32..+63 to the
    ; deep page. NOTE: the 2-sub-slot page split assumes the ring is NOT rotated
    ; vertically, i.e. STREAM_FIRST_ROW is 32-aligned (first_row & $1F == 0) — the
    ; scripted camera holds first_row at 0 (RIGHT) and 64 (LEFT), both aligned.
    ; A non-32-aligned first_row would need a 3-segment rotated split (future).
    ; The col*256+ptr add above may have set carry; fold it into $A9 FIRST so
    ; this row-offset add can carry independently, then sum both bank carries.
    sta $A9                     ; A9 = col*256 + ptr_lo16 (low16, carry pending)
    lda #$0000
    adc #$0000                  ; A = carry from the col*256+ptr add (0 or 1)
    sta $A8                     ; A8 = bank carry #1
    lda f:$7E0000 + STREAM_FIRST_ROW
    asl                         ; first_row * 2 (column-major row byte stride)
    clc
    adc $A9                     ; + (col*256 + ptr_lo16)
    sta f:$7E0000 + STREAM_PENDING_TBL + 2, x
    ; bank carry #2 from the row-offset add; total stashed carry = A8 + this.
    lda #$0000
    adc #$0000                  ; carry from the row-offset add
    clc
    adc $A8                     ; + bank carry #1
    sta $A9                     ; stashed 16-bit carry (0..2)
    bra @cmp_src_bank
.endif
    sta f:$7E0000 + STREAM_PENDING_TBL + 2, x

    ; Capture carry from the 16-bit add. Subsequent ADC for the bank
    ; would otherwise lose it (see Phase 17 audit pre-Sprint B finding #1).
    lda #$0000
    adc #$0000                  ; A = (C ? 1 : 0); leaves C=0 on exit
    sta $A9                     ; stashed 16-bit carry (max 1)
@cmp_src_bank:
    .a16                        ; WIDTH-LINT: ok — multi-path label (BG_STREAM_2AXIS bra + fallthrough)

    ; Bank adjustment = (col >> (16 - shift)) + stashed_carry.
    lda $A6                     ; reload col
.ifdef BG_STREAM_2AXIS
    .repeat 8
    lsr                         ; col >> 8 (col*256 overflow into bank)
    .endrep
.else
    .repeat 10
    lsr                         ; col >> 10 (col*64 overflow into bank)
    .endrep
.endif
    clc
    adc $A9                     ; A = overflow + carry
    sep #$20
    .a8
    sta $A7                     ; bank adjustment
    lda f:$7E0000 + STREAM_LEVEL_DATA_PTR + 2
    clc
    adc $A7                     ; ptr_bank + adjustment
    sta f:$7E0000 + STREAM_PENDING_TBL + 4, x

    ; Publish the new slot (sub-slot A in 2-axis mode): increment STREAM_PENDING.
    lda f:$7E0000 + STREAM_PENDING
    inc a
    sta f:$7E0000 + STREAM_PENDING

.ifdef BG_STREAM_2AXIS
    ; --- Sub-slot B: rows 32..63 of this column (pages SC2/SC3) -------------
    ; VADDR_B = VADDR_A + $800 ; SRC_B = SRC_A + 64. Reuse slot A's freshly
    ; written VADDR/SRC (at the prior X offset) as the basis. Recompute the
    ; new slot X = STREAM_PENDING * 5 first.
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_PENDING
    asl
    asl
    clc
    adc f:$7E0000 + STREAM_PENDING
    and #$00FF
    tax                         ; WIDTH-LINT: ok — A masked to byte before tax
    rep #$20
    .a16
    ; VADDR_B = (prior slot's VADDR_A) + $800. The prior slot is at X-5.
    lda f:$7E0000 + STREAM_PENDING_TBL - 5 + 0, x
    clc
    adc #STREAM_BG1_VPAGE_OFF
    sta f:$7E0000 + STREAM_PENDING_TBL + 0, x
    ; SRC_B low16 = SRC_A_low16 + 64 (rows 32..63 start 64 bytes into column).
    lda f:$7E0000 + STREAM_PENDING_TBL - 5 + 2, x
    clc
    adc #$0040
    sta f:$7E0000 + STREAM_PENDING_TBL + 2, x
    lda #$0000
    adc #$0000                  ; carry into bank
    sep #$20
    .a8
    clc
    adc f:$7E0000 + STREAM_PENDING_TBL - 5 + 4, x   ; + SRC_A bank
    sta f:$7E0000 + STREAM_PENDING_TBL + 4, x
    ; publish sub-slot B
    lda f:$7E0000 + STREAM_PENDING
    inc a
    sta f:$7E0000 + STREAM_PENDING
.endif

    ; Signal "computed" by setting carry.
    sec
    rts


; --- streaming_update_bg1 ---
;
; Inputs (caller maintains these in engine state before each frame):
;   STREAM_CAM_COL  — current camera column index (cam_x / 16)
;
; Behavior (Sprint C — issue #126):
;   - If STREAM_PENDING is already set (signal still queued from a
;     previous call that NMI hasn't drained yet), return early.
;   - Compute target = STREAM_CAM_COL + STREAM_LOOK_AHEAD.
;   - If STREAM_LAST_COL >= target, return (nothing to stream).
;   - Otherwise: advance STREAM_LAST_COL by 1, compute the VRAM word
;     address (= STREAM_BG1_VRAM_BASE + (last_col & $3F), with page-1
;     adjustment), compute the 24-bit ROM source address, raise
;     STREAM_PENDING = 1, and mirror the column into SHADOW_BG1_TILEMAP
;     for col_map. The engine NMI handler picks up STREAM_PENDING at
;     VBlank, performs the column DMA into BG1 VRAM, and clears the
;     flag. This avoids the forced-blank black band that the inline
;     Sprint B redo caused (issue #126).
;
; Look-ahead = 8 tiles (locked per brief). We queue at most ONE column per
; call. At 8 px/frame stress, the camera crosses one 16-px column boundary
; every 2 frames; one column queued per frame is 2× more than needed.
; If the brief's stress test exposes a deadline miss, the orchestrator
; will be informed via NEEDS-DIRECTION before we silently retune.
;
; Entry width: A8/I16. Exits A8/I16. Clobbers A, X, Y.
;
; WIDTH-RISK: this routine has multiple branches that converge at exit
; labels. All branch targets carry .a8/.a16 annotations matching CPU
; runtime width. Forces I16 on entry to match the engine's calling
; convention.
streaming_update_bg1:
    rep #$10                    ; force I16
    .i16
    sep #$20                    ; A8 entry
    .a8

    ; Phase 17 Sprint B (final): if streaming_init's allocator request
    ; failed, STREAM_ACTIVE is 0 and there is no allocated channel. Bail
    ; out cleanly — no DMA fires, no engine corruption.
    lda f:$7E0000 + STREAM_ACTIVE
    bne @stream_alive
    rts

@stream_alive:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BNE

    ; Streaming-speed-cap experiment: queue up to STREAM_PENDING_MAX_SLOTS
    ; columns per call. Each iteration calls streaming_compute_next_col
    ; (which advances STREAM_LAST_COL, writes the slot, increments
    ; STREAM_PENDING) and mirrors the new column into SHADOW_BG1_TILEMAP.
    ; The loop exits early if compute returns "nothing to stream"
    ; (carry clear: target reached, queue full, or up-to-date).
    ;
    ; This is the only mechanism by which the queue grows. NMI drains
    ; the entire queue in VBlank (one DMA per slot, in order) and resets
    ; STREAM_PENDING = 0; on the next frame, the queue is empty again
    ; and we can fill it from scratch.
@queue_loop:
    .a8                         ; ; WIDTH-LINT: ok — multi-path label (loop body)
    jsr streaming_compute_next_col
    bcs @did_queue              ; carry set → queued; mirror into shadow
    rts                         ; carry clear → done (target reached or queue full)

@did_queue:
    .a8                         ; ; WIDTH-LINT: ok — branch target from BCS

    ; --- Mirror this column into SHADOW_BG1_TILEMAP. ---
    ; This is a pure WRAM-to-WRAM copy that does NOT touch the PPU; it
    ; is safe to perform here in main thread. col_map and other shadow
    ; consumers need this updated before the next frame.
    ;
    ; Inputs to helper: $A5 = col index, $AA-$AC = 24-bit ROM source ptr.
    ; The src ptr lives in slot[count-1] of STREAM_PENDING_TBL because
    ; compute already incremented count after writing the slot.
    ;
    ; Phase 17 Sprint D-9: bidirectional streaming. The just-streamed
    ; world col is in $A6 (set by streaming_compute_next_col in both
    ; the forward and reverse paths). Forward streaming = LAST_COL
    ; after the increment; reverse streaming = FIRST_COL after the
    ; decrement. We can NOT blindly read STREAM_LAST_COL here — that
    ; was correct pre-D-9 (forward only) but is WRONG post-D-9 for
    ; reverse motion (reverse just decremented LAST_COL to maintain
    ; the invariant, so STREAM_LAST_COL points at the col that fell
    ; OFF the right edge, not the col just emitted). Reading $A6 picks
    ; up the correct world col regardless of direction.
    rep #$20
    .a16
    lda $A6
    sta $A5                     ; helper expects col in $A5

    ; X = (count - 1) * 5 — offset of just-written slot in TBL.
    ; (count - 1) is 0..3 since compute just incremented count to 1..4.
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_PENDING
    and #$00FF
    dec a                       ; count - 1, range 0..3
    sta $AE                     ; tmp = count-1
    asl
    asl                         ; (count-1) * 4
    clc
    adc $AE                     ; (count-1)*5
    and #$00FF
    tax                         ; ; WIDTH-LINT: ok — A masked to byte before tax

    ; Load src low/mid + bank from slot[count-1] into $AA/$AC.
    lda f:$7E0000 + STREAM_PENDING_TBL + 2, x   ; src lo+mid
    sta $AA
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_PENDING_TBL + 4, x   ; src bank
    sta $AC

    jsr _stream_shadow_write_col

    ; Loop back to attempt queueing another column. compute_next_col
    ; will bail (carry clear) when target is reached or queue is full.
    sep #$20                    ; ensure A8 for loop top (compute expects A8)
    .a8
    rep #$10
    .i16
    bra @queue_loop


; --- _stream_shadow_write_col ---
;
; Mirror one column of level data from ROM to SHADOW_BG1_TILEMAP. Used by
; both `streaming_init` (per-column boot loop, cols 0..63) and
; `streaming_update_bg1` (per-frame stream advance).
;
; The shadow contract (Phase 17 Sprint D-5 — Bug B fix):
;   SHADOW_BG1_TILEMAP at $7E:A200 is a 64×32 ring mirror matching the
;   BG1 hardware tilemap layout (BG1SC=$59). For world column N:
;     shadow_slot = N & $3F, byte_offset = slot*2 + row*128.
;   The shadow is now 4 KB ($A200-$B1FF), reusing bytes that previously
;   belonged to SHADOW_BG2_TILEMAP. Streaming-mode ROMs MUST keep BG2
;   static (no mset(2,...)) — this is enforced by convention, not
;   compile-time check.
;
;   Pre-D-5 the SHADOW was a 32-col ring (slot = col & $1F), causing
;   col_map to return stale boot data for any query at world tile col
;   in [32..63] — see docs/dx_paper_cuts.md "Phase 17 Sprint D-3" for
;   the full diagnosis.
;
;   col_map's BG1 path uses tile_y*128 + tile_x*2 as the shadow byte
;   offset (TILEMAP_WIDTH_BG1=64 in streaming mode → row stride 128).
;
; Inputs (caller fills before JSR):
;   $A5-$A6      world_col (16-bit). Shadow slot = col & $3F.
;   $AA-$AC      24-bit ROM source pointer for this column's data
;                (32 contiguous tile words, 64 bytes total).
;
; DP scratch convention: $A0-$AF is "Engine scratch" per CLAUDE.md
; (Direct Page register-file map).
;
; Behavior:
;   - shadow_base_byte = (col & $3F) * 2 → X (range 0..126).
;   - For row 0..31: read tile word from [src + row*2], write to
;     SHADOW_BG1_TILEMAP + row*128 + X.
;   - Loop is unrolled 32× to fit the cycle budget. Each iteration is
;     7 cyc (lda [dp],Y) + 5 cyc (sta abs,X with DB=$7E) + 4 cyc (iny iny)
;     = 16 cyc. Total: 32 × 16 = 512 cyc body + ~30 setup ≈ 580 cyc.
;
; Entry width: A8/I16. Exits A8/I16. Clobbers A, X, Y. Preserves DB.
;
; WIDTH-RISK: enters A8/I16, switches to A16 for the body (16-bit word
; loads/stores), and switches back to A8 before RTS. I-width stays I16
; throughout. The unrolled body is straight-line with no branches.
_stream_shadow_write_col:
    ; Compute shadow base offset: (col & $3F) * 2 → X (range 0..126).
    ; Phase 17 Sprint D-5 Bug B: was `& $1F` (32-col ring); now `& $3F`
    ; matching the 64-col BG1 hardware tilemap and 4 KB SHADOW.
    rep #$20
    .a16
    lda $A5
    and #$003F
    asl                         ; A = (col & $3F) * 2
    tax                         ; ; WIDTH-LINT: ok — A masked & shifted, both A16/I16
                                ; X = shadow byte offset

    ; Set DB = $7E so shadow writes can use 5-cyc abs,X form (vs 6-cyc
    ; long abs,X). ROM reads still use 7-cyc [dp],Y (DB-independent).
    sep #$20
    .a8
    phb                         ; preserve caller's DB
    lda #$7E
    pha
    plb                         ; DB = $7E

    rep #$20
    .a16

    ; Y = ROM source word offset; advances by 2 per unrolled iteration.
    ldy #$0000

    ; Unrolled 32-row loop. Each iteration with DB=$7E:
    ;   lda [$AA], y                           ; 7 cyc
    ;   sta SHADOW_BG1_TILEMAP + (ROW*128), x  ; 5 cyc (abs,X)
    ;   iny iny                                ; 4 cyc
    ; Total: 32 × 16 = 512 cyc + ~50 setup + JSR/RTS ≈ 580 cyc helper.
    ;
    ; Phase 17 Sprint D-5 Bug B: row stride bumped from 64 → 128 to
    ; match the 64-col SHADOW (was 32-col).
    .repeat 32, ROW
    lda [$AA], y
    sta SHADOW_BG1_TILEMAP + (ROW * 128), x
    iny
    iny
    .endrep

    ; Restore caller's DB and A8 width per entry contract.
    sep #$20
    .a8
    plb
    rts


; =============================================================================
; Kit-clean public aliases. These are label equates onto the proven routines
; so the descriptive names front the same code (zero duplication, zero cycle
; cost). The macro layer (sf_stream.inc) and S2 use these; the legacy names
; remain exported for the parent regression tests.
;   bg_stream_init  == streaming_init        (boot bulk DMA + DP $20-$24 in)
;   bg_stream_tick  == streaming_update_bg1  (per-frame queue tick)
; =============================================================================
bg_stream_init = streaming_init
bg_stream_tick = streaming_update_bg1
