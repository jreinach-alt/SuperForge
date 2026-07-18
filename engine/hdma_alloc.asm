; =============================================================================
; hdma_alloc.asm — Phase 17-0A HDMA Channel Allocator (runtime)
; =============================================================================
; Request-based HDMA channel allocator. Complements the compile-time resolver
; in toolchain/hdma_alloc.py: scenes that declare `[scene.effects]` in
; superforge.toml get a per-scene `<scene>_hdma_alloc.inc` that pre-initializes
; HDMA_ALLOC_MASK via hdma_alloc_bootstrap. Runtime hdma_request is reserved
; for effects that dynamically opt in/out within a scene.
;
; CH0 + CH1 are reserved for VBlank bulk-DMA (engine/dma_scheduler.asm). They
; are marked as allocated during hdma_alloc_init. The allocator only hands
; out CH2..CH7 (6 channels).
;
; Inherits the Phase 16 grandfathered defaults (M7_HDMA_CH_AB / M7_HDMA_CH_CD
; = CH5/CH6). Scenes using grandfathered literals call hdma_alloc_bootstrap
; with the Phase 16 default mask to keep allocator books consistent.
;
; API:
;   hdma_alloc_init        — zero allocator state; reserve CH0/CH1
;   hdma_alloc_bootstrap   — mark a known-good mask as allocated
;   hdma_request           — allocate N free channels for an effect
;   hdma_release           — release channels held by an effect
;
; Cross-ref: docs/sprints/phase_17_bg_modes.md §17-0a (BM-005..009),
;            docs/sprints/phase_17_allocations.md §5,
;            engine/engine_state.inc §Phase 17-0a: HDMA Channel Allocator State.
; =============================================================================

; Prerequisites: engine_state.inc symbols available, .p816/.smart in scope.
;
; Phase 17 Sprint B (final): this file is also assembled standalone for
; the streaming build (engine/streaming_engine.asm links hdma_alloc.o
; separately). Setting .p816/.smart is idempotent; engine_state.inc
; carries its own include guard so re-inclusion is harmless.
.p816
.smart
.include "engine_state.inc"

HDMA_ALLOC_PROVIDED = 1

.ifndef ENGINE_A0
ENGINE_A0 = $40
.endif

; --- API exports (Phase 17 Sprint B final) ---
; Make the allocator entry points linker-visible so external compilation
; units (notably engine/streaming_engine.asm under PHASE17_SPRINT_A_DEPS)
; can call hdma_request without forcing the file into a `.include` chain.
; In-tree consumers that .include this file directly are unaffected —
; .export is a no-op when the symbol is also locally defined.
.export hdma_alloc_init
.export hdma_alloc_bootstrap
.export hdma_request
.export hdma_release
.export hdma_bind_direct

; Allocator working scratch. Phase 17-0b1 relocates to the engine-state
; block ($01D8-$01DC) after the state bytes at $01D0-$01D7. Original
; $C810+ conflicted with HDMA_TABLE_CH5 = $C800 when a Phase 4 effect
; allocated CH5 and built its table on top of the allocator state.
HDMA_ALLOC_REQ_NEEDED = $01D8    ; 1 B, n_channels remaining in request
HDMA_ALLOC_REQ_EFFECT = $01D9    ; 1 B, effect_id for in-flight request
HDMA_ALLOC_REQ_CAND   = $01DA    ; 1 B, candidate mask being built
HDMA_ALLOC_REQ_PRIO   = $01DB    ; 1 B, priority (stored for future preemption)
HDMA_ALLOC_REQ_MODE   = $01DC    ; 1 B, mode_pref (stored for debug/future)


.segment "CODE"

; -----------------------------------------------------------------------------
; hdma_alloc_init — zero allocator state; reserve CH0 + CH1.
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. DB pushed, set to $7E, restored.
; Clobbers: A, X.
; -----------------------------------------------------------------------------
hdma_alloc_init:
    rep #$30
    .a16
    .i16

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E

    stz HDMA_ALLOC_MASK
    stz HDMA_ALLOC_HIGH_WATER
    ldx #0
@clr:
    stz HDMA_ALLOC_EFFECT_TBL, x
    inx
    cpx #6
    bcc @clr

    ; Reserve CH0 + CH1.
    lda #$03
    sta HDMA_ALLOC_MASK

    plb
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; hdma_bind_direct — bind an allocated channel to a PPU register for a direct
; 1-byte -> 1-register HDMA and arm it (the split-mode channel<->register-BBAD
; registry: splits route their tables through hdma_request + this bind instead
; of hand-hardcoded $43xx programming, closing the channel-collision class).
;
; Input (A16, I16, DB=$00 required):
;   A16 low  = single-bit channel mask (as returned by hdma_request; exactly one
;              of bits 2..7 set). The channel index is derived from the bit.
;   X16 low  = BBAD — the destination PPU register low byte (e.g. $05 for $2105
;              BGMODE, $2C for $212C TM, $32 for $2132 COLDATA).
;   API_BLOCK_BASE+0 = table address low byte
;   API_BLOCK_BASE+1 = table address high byte
;   API_BLOCK_BASE+2 = table bank byte
;   API_BLOCK_BASE+3 = DMAP transfer-mode byte (the DMAPn value). $00 = the
;              default 1-byte -> 1-register direct split (BGMODE/TM/COLDATA/…).
;              $03 = write-2-registers-twice (the Mode-7 MATRIX-band mode: one
;              HDMA channel streams [lo,hi,lo,hi] into a register PAIR, e.g. BBAD
;              $1B feeds M7A ($211B)+M7B ($211C); BBAD $1D feeds M7C+M7D). Any
;              valid $43x0 DMAP is accepted — the byte is written verbatim.
;              CALLERS OF THE 1-BYTE SPLIT MUST WRITE $00 HERE (sf_split_h_arm
;              does): the byte is NOT auto-cleared, so a stale slot would pick a
;              wrong transfer mode. This is the ONLY behavioural change vs. the
;              prior hardcoded-$00 form.
;
; Behaviour: derives channel index `ch` from the single set bit, then programs
;   $4300+ch*$10 = API_BLOCK_BASE+3  (DMAPn transfer mode — $00 default direct)
;   $4301+ch*$10 = BBAD
;   $4302/3/4    = table addr lo / hi / bank
; and ORs the channel mask into NMI_HDMA_ENABLE (additive — the engine NMI
; re-arms $420C from that mask every VBlank). Does NOT verify the channel was
; actually allocated (caller passes the hdma_request mask).
;
; Why DB=$00 works with no DB switch: the $43xx DMA registers are bank-$00 I/O,
; and NMI_HDMA_ENABLE ($0108) lives in mirrored low WRAM ($00:0108 == $7E:0108),
; so an absolute (DB-relative) access with DB=$00 reaches both without a switch.
;
; WIDTH-RISK: entry A16/I16; exits A16/I16. Toggles to A8 for the byte
; register/table writes and the NMI_HDMA_ENABLE RMW, then restores A16 (I16
; held throughout). No DB switch — DB=$00 required and preserved.
; Clobbers: A, X, Y.
; -----------------------------------------------------------------------------
hdma_bind_direct:
    rep #$30
    .a16
    .i16

    ; --- capture inputs: A16 = channel mask, X16 = BBAD. Save BOTH to scratch
    ;     BEFORE the finder clobbers A (the mask must survive as REQ_CAND). ---
    and #$00FF                  ; isolate the mask low byte (input mask)
    sta HDMA_ALLOC_REQ_CAND     ; scratch: the requested channel mask
    txa                         ; X = BBAD -> A
    and #$00FF
    sta HDMA_ALLOC_REQ_MODE     ; scratch: BBAD low byte (0..$FF)

    ; --- derive the channel base offset ch*$10 into Y (Y = $20..$70 for CH2..7)
    ;     from the single-bit channel mask (REQ_CAND). Walk from CH2 (bit $04,
    ;     base $20): shift the candidate bit left (A) and step the base +$10 (X)
    ;     in lock-step until the candidate matches the input mask. X carries the
    ;     base so the accumulator is free for the bit compare. Malformed mask
    ;     (not exactly one of bits 2..7) -> no-op rts. ---
    ldx #$0020                  ; candidate channel base ($4300 + $20 = CH2)
    lda #$0004                  ; candidate bit = CH2
@bd_find:
    .a16
    .i16
    cmp HDMA_ALLOC_REQ_CAND
    beq @bd_found               ; candidate bit == input mask -> X = ch*$10
    asl                         ; next channel bit (CH3, CH4, ...)
    pha                         ; base += $10: add via A, restore the bit after
    txa
    clc
    adc #$0010
    tax
    pla
    cmp #$0100                  ; past CH7 bit ($80 << 1)? -> malformed mask
    bcc @bd_find
    rts                         ; not a single CH2..7 bit — no-op
@bd_found:
    .a16
    .i16
    txy                         ; Y = ch*$10 for the $43xx,y stores
    ; --- program the channel's DMA registers via ($4300 + ch*$10), Y-indexed.
    ;     Y = ch*$10 ($20..$70); $4300,y addresses DMAPn, $4301,y BBADn, etc. ---
    sep #$20
    .a8
    lda API_BLOCK_BASE + 3      ; DMAPn transfer mode ($00 direct 1-byte->1-reg;
    sta $4300, y                ;   $03 = matrix-band 2-reg-twice — caller sets it)
    lda HDMA_ALLOC_REQ_MODE     ; BBAD low byte
    sta $4301, y                ; BBADn
    lda API_BLOCK_BASE + 0
    sta $4302, y                ; A1TnL — table address low
    lda API_BLOCK_BASE + 1
    sta $4303, y                ; A1TnH — table address high
    lda API_BLOCK_BASE + 2
    sta $4304, y                ; A1Bn  — table bank
    ; --- arm the channel (additive) in NMI_HDMA_ENABLE (abs, DB=$00 mirror) ---
    lda HDMA_ALLOC_REQ_CAND     ; the channel mask (single bit)
    ora NMI_HDMA_ENABLE
    sta NMI_HDMA_ENABLE
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; hdma_alloc_bootstrap — pre-claim a mask as allocated.
;
; Input (A16, I16):
;   A16 low byte = channel bitmask to claim
;   X16 low byte = effect_id to tag each claimed channel with
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. Clobbers A, X, Y.
; -----------------------------------------------------------------------------
hdma_alloc_bootstrap:
    rep #$30
    .a16
    .i16

    phb                             ; stack: [caller DB]
    sep #$20
    .a8
    pha                             ; stack: [caller DB, mask]
    lda #$7E
    pha                             ; stack: [caller DB, mask, $7E]
    plb                             ; DB=$7E; stack: [caller DB, mask]
    ; After this sequence: mask at 1,s, caller DB at 2,s.

    ; OR mask into HDMA_ALLOC_MASK.
    lda 1, s
    ora HDMA_ALLOC_MASK
    sta HDMA_ALLOC_MASK

    ; Tag each newly-claimed channel (bits 2..7) with effect_id.
    txa                             ; effect_id into A
    sta HDMA_ALLOC_REQ_EFFECT

    ldx #0
    ldy #$04                        ; CH2 bit
@bs_scan:
    tya
    and 1, s                        ; mask byte
    beq @bs_skip
    lda HDMA_ALLOC_REQ_EFFECT
    sta HDMA_ALLOC_EFFECT_TBL, x
@bs_skip:
    inx
    tya
    asl
    ; WIDTH-LINT: ok — A8 tay; Y is used only as a mask (Y-low ANDed with stack
    ; byte at line 122). Y-high never read, so any stale C-high is harmless.
    tay
    cpx #6
    bcc @bs_scan

    jsr hdma_alloc_update_high_water

    pla                             ; discard mask byte
    plb                             ; restore caller DB
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; hdma_request — allocate N free HDMA channels for an effect.
;
; Input (A16, I16, DP=$0000):
;   A16: A[3:0]   = n_channels (1..6)
;        A[6:4]   = priority (0..2) — stored; no runtime enforcement
;        A[11:7]  = mode_pref (0..4, HDMA_MODE_*) — stored for debug/future
;        A[15:12] = reserved (write 0)
;   X16: X[7:0]   = effect_id ($01..$FE)
;
; Output:
;   A16       = allocated channel bitmask (0 if failed)
;   ENGINE_A0 = same
;   C flag    = 0 success, 1 failure
;
; Failure (A=0, C=1): n_channels == 0 or > 6; effect_id == $00 or $FF;
; fewer than n_channels free bits in HDMA_ALLOC_MASK.
;
; Greedy first-fit: walks CH2..CH7 low-to-high; picks first N unset bits.
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. Toggles to A8 internally; DB
; pushed, set to $7E, restored.
; Clobbers: A, X, Y.
; -----------------------------------------------------------------------------
hdma_request:
    rep #$30
    .a16
    .i16

    ; Push the full A16 param word and effect_id onto the stack FIRST so
    ; they survive the DB switch. Stack layout after pushes:
    ;   SP+4  = param A16 (2 bytes, low at SP+4)
    ;   SP+2  = effect_id X16 (2 bytes, low at SP+2)
    ;   SP+0  = caller DB (1 byte, after phb)
    pha
    phx

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E ; stack now [caller DB] ...

    ; Unpack n_channels (param A low byte, bits 0..3).
    lda 4, s                        ; param A low
    and #$0F
    sta HDMA_ALLOC_REQ_NEEDED

    ; Unpack priority (param A low byte, bits 4..6).
    lda 4, s
    lsr
    lsr
    lsr
    lsr
    and #$07
    sta HDMA_ALLOC_REQ_PRIO

    ; Unpack mode_pref (param A high byte, bits 0..4 = high bits 7..11 of A16).
    lda 5, s                        ; param A high
    and #$1F
    sta HDMA_ALLOC_REQ_MODE

    ; effect_id (stacked X low byte).
    lda 2, s
    sta HDMA_ALLOC_REQ_EFFECT

    stz HDMA_ALLOC_REQ_CAND

    ; --- Validate ---
    lda HDMA_ALLOC_REQ_NEEDED
    beq @fail
    cmp #$07
    bcs @fail

    lda HDMA_ALLOC_REQ_EFFECT
    beq @fail
    cmp #$FF
    beq @fail

    ; --- Scan CH2..CH7 for free bits ---
    ldx #0                          ; effect_tbl index (0=CH2..5=CH7)
    ldy #$04                        ; CH2 bit mask
@scan:
    tya
    and HDMA_ALLOC_MASK
    bne @next                       ; busy
    tya
    ora HDMA_ALLOC_REQ_CAND
    sta HDMA_ALLOC_REQ_CAND
    lda HDMA_ALLOC_REQ_EFFECT
    sta HDMA_ALLOC_EFFECT_TBL, x
    dec HDMA_ALLOC_REQ_NEEDED
    beq @ok
@next:
    inx
    tya
    asl
    ; WIDTH-LINT: ok — A8 tay; Y is the channel mask, used only as Y-low for
    ; the AND at @scan / @rev / @rel_scan. Y-high never indexed.
    tay
    cpx #6
    bcc @scan

    ; Exhausted channels without satisfying request — rollback partial writes.
    jsr @revert_effect_tbl
    bra @fail

@ok:
    lda HDMA_ALLOC_REQ_CAND
    ora HDMA_ALLOC_MASK
    sta HDMA_ALLOC_MASK

    jsr hdma_alloc_update_high_water

    lda HDMA_ALLOC_REQ_CAND
    sta ENGINE_A0
    stz ENGINE_A0 + 1

    plb                             ; restore caller DB
    rep #$30
    .a16
    .i16
    plx                             ; discard stacked effect_id
    pla                             ; discard stacked param
    lda ENGINE_A0
    clc
    rts

@fail:
    stz ENGINE_A0
    stz ENGINE_A0 + 1

    plb
    rep #$30
    .a16
    .i16
    plx
    pla
    lda #$0000
    sec
    rts


; Internal rollback — clear HDMA_ALLOC_EFFECT_TBL entries matching REQ_CAND.
; DB=$7E, A8, I16 required.
@revert_effect_tbl:
    .a8
    .i16
    ldx #0
    ldy #$04
@rev:
    tya
    and HDMA_ALLOC_REQ_CAND
    beq @rev_skip
    stz HDMA_ALLOC_EFFECT_TBL, x
@rev_skip:
    inx
    tya
    asl
    ; WIDTH-LINT: ok — A8 tay; Y is the channel mask, used only as Y-low for
    ; the AND at @rev. Y-high never indexed.
    tay
    cpx #6
    bcc @rev
    rts


; -----------------------------------------------------------------------------
; hdma_alloc_update_high_water — bump HIGH_WATER if the popcount of the mask
; (excluding CH0/CH1 system reservations) exceeds the stored value.
;
; Expects: DB=$7E, A8, I16. Exits in same state. Clobbers A, X.
; -----------------------------------------------------------------------------
hdma_alloc_update_high_water:
    .a8
    .i16
    lda HDMA_ALLOC_MASK
    and #$FC                        ; mask off CH0/CH1
    beq @uhw_done
    ldx #0
@pc:
    lsr
    bcc @pc_skip
    inx
@pc_skip:
    cmp #0
    bne @pc
    txa
    cmp HDMA_ALLOC_HIGH_WATER
    bcc @uhw_done
    sta HDMA_ALLOC_HIGH_WATER
@uhw_done:
    rts


; -----------------------------------------------------------------------------
; hdma_release — release channels held by an effect.
;
; Input (A16, I16):
;   A16 low byte = bitmask to release (bits 0/1 auto-masked — system-reserved)
;
; Output:
;   A16       = HDMA_ALLOC_MASK after release
;   ENGINE_A0 = same
;
; Does NOT verify ownership. Caller passes the mask from hdma_request.
;
; WIDTH-RISK: entry A16/I16; exit A16/I16. A8 toggles bracketed; DB pushed,
; set to $7E, restored.
; Clobbers: A, X, Y.
; -----------------------------------------------------------------------------
hdma_release:
    rep #$30
    .a16
    .i16

    phb                             ; stack: [caller DB]
    sep #$20
    .a8
    pha                             ; stack: [caller DB, mask]
    lda #$7E
    pha                             ; stack: [caller DB, mask, $7E]
    plb                             ; DB=$7E; stack: [caller DB, mask]
    ; After this sequence: mask at 1,s, caller DB at 2,s.

    lda 1, s
    and #$FC                        ; drop CH0/CH1
    sta 1, s                        ; normalized mask

    ldx #0
    ldy #$04
@rel_scan:
    tya
    and 1, s
    beq @rel_skip
    stz HDMA_ALLOC_EFFECT_TBL, x
@rel_skip:
    inx
    tya
    asl
    ; WIDTH-LINT: ok — A8 tay; Y is the channel mask, used only as Y-low for
    ; the AND at @rel_scan. Y-high never indexed.
    tay
    cpx #6
    bcc @rel_scan

    ; Clear bits from HDMA_ALLOC_MASK.
    lda 1, s
    eor #$FF
    and HDMA_ALLOC_MASK
    sta HDMA_ALLOC_MASK

    sta ENGINE_A0
    stz ENGINE_A0 + 1

    pla                             ; discard mask byte
    plb                             ; restore caller DB
    rep #$20
    .a16
    lda ENGINE_A0
    rts
