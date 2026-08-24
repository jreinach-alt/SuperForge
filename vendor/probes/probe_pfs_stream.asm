; superforge pfs_stream MECHANISM probe — the 2-axis normal-BG
; 64x64 ring streamer, proven and measured on cycle-accurate hardware.
;
; THIS IS NOT THE FEATURE. It is scaffolding, the same shape as probe_colmap:
; a one-scene allocator-mapped ROM whose only job is to make the mechanism
; observable. Nothing in engine/ or game/ includes it.
;
; WHY IT EXISTS AT ALL, given the rail is being built alongside it: the rail
; and the streamer were written in PARALLEL, so the streamer needed a way to
; be proven that did not wait on a BG feature, a physics feature, a scene or a
; game.toml. What this ROM binds is the two level blobs and a 64x64 VRAM ring,
; and what it drives is the camera — which is the whole of the streamer's
; interface. The rail then composes the same kernel with a picture around it.
;
; THE ASSERTION SURFACE IS BG1 VRAM, NOT A VARIABLE. `tests/test_pfs_stream.py`
; reads the ring's tilemap WORDS back out of VRAM and compares them to the
; authored level, tile for tile, through the PPU's own four-page addressing.
; Nothing here reports "streaming happened" — a camera variable advances every
; frame whether the streamer works or not, and that exact proxy shipped twice
; on the predecessor project (its issue #125).
;
; The probe deliberately does NOT configure a BG layer. The tilemap is the
; output region; a layer would only add a second owner for BGMODE/TM
; and the picture is the rail's job.
;
; All RAM/ROM addresses are allocator-emitted; hardware I/O ports are the only
; literals.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE PFSSTRM"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "engine_state_probe.inc"

.include "header.inc"
.include "init.inc"
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

NMI_STUB:
    rti

; ---------------------------------------------------------------------------
; The VBlank drain, in its real position: an interrupt handler.
; ---------------------------------------------------------------------------
; Running the drain from a genuine NMI rather than from the main loop is the
; point of the probe — it is what makes the DMA land inside a real VBlank
; window and what exercises the tick/drain interleave the PFS_BUSY guard
; exists for. `pfs_stream_nmi_dispatch` is written against the sm_nmi_hook
; contract (A8/I16, DB=0), so this stub establishes exactly that.
;
; WIDTH-RISK: an NMI arrives in whatever width the interrupted code was using
; — including mid-MVN, where the staging kernel has left DB = $7E. So the
; handler forces A16/I16 before pushing (so every push/pull is 2 bytes and the
; pairs balance), sets DB = 0 and DP = 0 for the callee, and restores all of
; it. `rti` then restores P, and with it the interrupted code's widths.
NMI:
    rep #$30
    .a16
    .i16
    pha
    phx
    phy
    phd
    phb
    lda #0
    tcd                             ; DP = 0, the drain's DP aliases' basis
    sep #$20
    .a8
    lda #0
    pha
    plb                             ; DB = 0 (an interrupted MVN left it $7E)
    jsr pfs_stream_nmi_dispatch
    rep #$30
    .a16
    .i16
    plb
    pld
    ply
    plx
    pla
    rti

; ===========================================================================
; THE KERNEL UNDER TEST — the real feature source, not a copy of it.
; ===========================================================================
; pfs_stream.asm names only its five bound PFS_* symbols plus its own
; allocator-emitted claims, which this probe's feature.toml declares under the
; same names. Including the shipped file rather than transcribing it is the
; point: a measured figure — or a passing test — that describes a copy stops
; describing the feature the first time either drifts.
;
; The binding is the rail's, deliberately: the same two one-window blobs in
; the same two orders. A probe that bound a different world would be proving a
; different kernel.
PFS_COL_WIN  = ES_R_PFS_FLAT_ADDR           ; column-major, one 32 KB window
PFS_COL_BANK = ES_R_PFS_FLAT_BANK
PFS_ROW_WIN  = ES_R_PFS_FLAT_ROW_ADDR       ; row-major, ditto
PFS_ROW_BANK = ES_R_PFS_FLAT_ROW_BANK
PFS_MAP_BASE = ES_V_PFS_MAP                 ; the ring's VRAM word base
.include "pfs_stream.asm"

; cmd 7's synthetic line pattern. It lives OUT here rather than beside the
; arm that uses it because a global symbol definition CLOSES ca65's cheap-local
; scope: defined between MAIN and @arm_bench it silently orphans every `@label`
; after it ("Symbol '@arm_bench' is undefined").
;
; Word k of the synthetic source line is (PFS_SYNTH_HI + k) << 8 | (PFS_SYNTH_LO
; + k): 128 distinct NON-ZERO high bytes and 128 distinct low bytes, each pair
; different from the other. Distinct-per-word is what makes a line staged or
; drained one word out a mismatch in EVERY word rather than a coincidence in
; most; high != low is what makes a byte-swapped word a mismatch too.
PFS_SYNTH_HI = 64                   ; +k -> $40..$BF, the tilemap HIGH byte
PFS_SYNTH_LO = 1                    ; +k -> $01..$80, the tile id

; ===========================================================================
MAIN:
    .a16
    .i16
    ; --- the control block, and ONLY the control block ----------------------
    ; ES_PFS_HOT and ES_PFS_NMI are deliberately NOT touched here. They are
    ; `pfs_stream_init`'s contract, power-on RAM is random under Mesen's
    ; default regime, and cmd 1 + T0 in the test read them back to prove the
    ; init is real code rather than a declaration. Zeroing them here would
    ; hand the test the answer.
    lda #0
    sta f:US_PARAM_LONG
    sta f:US_PARAM2_LONG
    sta f:US_SEQ_LONG
    sta f:US_ACC_LONG
    sep #$20
    .a8
    lda #0                          ; STZ has no long addressing mode
    sta f:US_CMD_LONG
    sta f:US_MARK_LONG
    rep #$20
    .a16

; WIDTH-RISK: reached in A16 (fall-through from MAIN, and the `jmp` from
; @finish) AND in A8 (the `bra` at the end of the dispatch chain). A bare
; annotation here would be a lie in one direction or the other, so the label
; RESYNCS instead — sep + directive is a forced narrowing, legal from any
; arrival.
@spin:
    sep #$20
    .a8
    .i16
    lda f:US_CMD_LONG
    cmp #1
    beq @arm_init
    cmp #2
    beq @arm_ring
    cmp #3
    beq @arm_frame
    ; the two bench arms sit past a `beq`'s reach, so they go through a
    ; `jmp` — an inverted branch over an absolute jump, not a re-ordering
    cmp #6
    bne @not_hold
    jmp @arm_hold
@not_hold:
    .a8
    .i16
    cmp #4
    bne @not_bench
    jmp @arm_bench
@not_bench:
    .a8
    .i16
    cmp #5
    bne @not_control
    jmp @arm_control
@not_control:
    .a8
    .i16
    cmp #7
    bne @not_synth
    jmp @arm_synth
@not_synth:
    .a8
    .i16
    bra @spin

; --- cmd 1: the [init] zero contract, on its own ---------------------------
; No camera, no arm, no drain: just the routine, so the host can read the
; declared bytes and see whether anything actually zeroed them.
@arm_init:
    .a8
    .i16
    rep #$20
    .a16
    jsr pfs_stream_init
    sep #$20
    .a8
    jmp @finish

; --- cmd 2: scene enter — init, camera, arm the whole ring ------------------
; The rail's enter shape: forced blank AND NMI masked across the fill (forced
; blank alone does not mask NMI — $4200 bit 7 does, and an NMI that ran the
; drain mid-fill would reprogram VMADD under the loop). Display and NMI come
; on together at the end.
@arm_ring:
    .a8
    .i16
    stz a:$4200                     ; NMITIMEN: mask NMI for the fill
    lda a:$4210                     ; ack any NMI already pending (read-clear)
    lda #$80
    sta a:$2100                     ; INIDISP: forced blank
    rep #$20
    .a16
    jsr pfs_stream_init
    lda f:US_PARAM_LONG             ; camera world pixel X
    ldx #0
    ldy #0
    pha
    lda f:US_PARAM2_LONG            ; camera world pixel Y
    tax
    pla
    jsr pfs_stream_set_cam
    jsr pfs_stream_arm
    sep #$20
    .a8
    lda #$0F
    sta a:$2100                     ; INIDISP: display on, full brightness
    lda #$80
    sta a:$4200                     ; NMITIMEN: NMI on — the drain is live
    jmp @finish

; --- cmd 3: ONE game frame — move the camera, tick, wait for the drain ------
; The tick stages on the main thread; the NMI drains. `wai` is what makes the
; command's completion mean "a VBlank has passed since the staging", so the
; host never reads VRAM that the DMA has not reached yet.
@arm_frame:
    .a8
    .i16
    rep #$20
    .a16
    lda f:US_PARAM_LONG
    pha
    lda f:US_PARAM2_LONG
    tax
    pla
    jsr pfs_stream_set_cam
    jsr pfs_stream_tick
    wai                             ; ...the VBlank that drains what we staged
    sep #$20
    .a8
    jmp @finish

; --- cmd 6: stage a frame and make the drain DEFER --------------------------
; The PFS_BUSY guard is the one piece of pfs_stream that only matters on a
; timing edge — an NMI landing between a slot's buffer fill and the `inc` that
; publishes it — and a host cannot schedule that edge. So this arm MANUFACTURES
; the condition instead: it ticks normally, then re-raises the flag the tick
; just lowered and lets a VBlank pass. Every drain from here on sees a stage
; "in flight" and defers, leaving the staged slots pending and VRAM holding the
; previous window. The host clears the flag and watches them go out.
;
; What that buys is a real assertion on both halves of the guard: that a
; deferred drain writes NOTHING (rather than draining a half-published slot
; table), and that the pending slots are not LOST — the counters survive
; because the tick does not reset them, only the drain does.
@arm_hold:
    .a8
    .i16
    rep #$20
    .a16
    lda f:US_PARAM_LONG
    pha
    lda f:US_PARAM2_LONG
    tax
    pla
    jsr pfs_stream_set_cam
    jsr pfs_stream_tick             ; ...stages, and lowers PFS_BUSY on exit
    sep #$20
    .a8
    lda #1
    sta z:PFS_BUSY                  ; re-raise: "a stage is still in flight"
    wai                             ; a whole VBlank passes with it up
    jmp @finish

; --- cmd 7: a staged line whose tilemap words have NON-ZERO HIGH BYTES ------
; THE ONE THING THE LEVEL CANNOT ASK. A normal-BG tilemap entry is a WORD —
; tile id low, palette/priority/flip high — which is why `pfss` and `pfs_fill`
; declare mode 1 and both VMDATA ports, and why the VMAIN bytes set bit 7 so
; the VRAM address advances after the $2119 (high) write rather than the $2118
; (low) one. The authored level makes NONE of that observable: it authors
; palette group 0, so every one of its 16,384 tilemap words has a high byte of
; zero, and a stream that wrote only low bytes — or wrote high bytes one word
; out — produces a ring byte-identical to a correct one. a review proved it by
; planting: clearing PFS_VMAIN_ROW's bit 7, a real word-port defect, passed all
; nine tests.
;
; THE HIGH BYTE HAS TWO CARRIERS AND THIS ARM MUST DRIVE BOTH. A tilemap word
; reaches VRAM through the STAGING (the two-span MVN out of a ROM blob into the
; slot buffer) and then through the DRAIN (the two page DMAs out of that buffer
; through the word port). The first version of this arm staged a real line and
; then REWROTE each staged word's high byte before releasing the drain — which
; proved the drain and, precisely because the rewrite happened after the kernel
; returned, said nothing about the staging. a follow-up review measured that rather than
; arguing it: a plant making `_pfs_copy_line` mask every staged word to & $00FF
; — a streamer that throws away palette group, priority and flip on every tile
; — passed 11/11 here and 23/23 on the rail (
; R1). So the rewrite is gone. Nothing below writes the slot buffer; the KERNEL
; copies the high bytes there, out of a source that has them.
;
; WHY THE SOURCE HAS TO BE A THIRD BINDING, and it is not a shortcut. The
; staging path's source pointer is `PFS_COL_WIN + (K0 & 127) * 256` in bank
; PFS_COL_BANK — 128 world lines covering exactly the 32,768 B window, with K0
; masked. So NO value of the staging path's inputs can make pfs_stage_col read
; a byte outside the bound blob, and every byte inside it is level data with a
; zero high byte. The only way to hand the copy engine a non-zero high byte is
; to point it at a different source — which is exactly what an INCLUDER does
; for the two real blobs, via a (window, bank) pair. This arm performs that
; same binding a third time: it stages normally (so the meta, the dest pair,
; the VMAIN byte, the slot base and the source-pointer arithmetic are all the
; kernel's), then re-points K1/K6 — the two values `pfs_stage_col` itself
; computes and `_pfs_copy_line` documents as its inputs — at a probe-authored
; 128-word line, and re-runs the SHIPPED `_pfs_copy_line` over the same slot
; with the same span start. The two-span cut, the position-wrapping and the MVN
; are the feature's own; only the blob is the probe's.
;
; WHAT THAT LEAVES UNCOVERED, stated rather than glossed: the ~6 instructions
; of `pfs_stage_col` / `pfs_stage_row` that turn K0 into K1 and pick the MVN
; stub. Those select WHICH line out of WHICH blob, and a wrong choice is wrong
; TILE IDS everywhere — which T1-T6 read out of VRAM against the authored
; level. They cannot be high-byte-specific: they compute a pointer, not data.
;
; Deliberately NOT done by changing the level: the two blobs are byte-checked
; against the committed reference fixtures, and that identity is the strongest
; independent oracle in the work item. Deliberately not a `rom` claim either — the
; fixture is 256 B of pattern whose whole job is to be READ ALONGSIDE the
; assertion that checks it, and `.byte` beside the arm shows the pattern where
; a generated `.bin` would hide it. It costs the allocator nothing: no claim
; value moves, and the linker places it in ROM0 with the code.
;
; US_PARAM = the world line; US_PARAM2 = 0 for a column, non-zero for a row.
; Requires cmd 2 first (LAST_TX/LAST_TY are the staging windows).
@arm_synth:
    .a8
    .i16
    lda #1
    sta z:PFS_BUSY                  ; staging outside the tick: hold the drain
    rep #$20                        ; off a half-published slot table, the same
    .a16                            ; contract @arm_bench honours
    stz z:PFS_COL_CNT               ; A16: both counts — this line takes slot 0
    lda f:US_PARAM_LONG
    and #(PFS_TILES - 1)
    sta z:PFS_K0
    lda f:US_PARAM2_LONG
    beq @synth_col
    jsr pfs_stage_row
    lda z:PFS_LAST_TX               ; a ROW's varying axis is the COLUMNS...
    bra @synth_rebind
@synth_col:
    .a16
    .i16
    jsr pfs_stage_col
    lda z:PFS_LAST_TY               ; ...and a COLUMN's is the ROWS
; Re-bind the source and re-run the kernel's own copy. A = the varying axis'
; LAST, from which the span start is derived EXACTLY as the stage routine
; derives it — same w0, so the synthetic line lands in the same 64 slots the
; real one just did, and the drain's meta still describes it.
@synth_rebind:
    .a16
    .i16
    sec
    sbc #PFS_BACK
    and #(PFS_TILES - 1)            ; w0: the window the ring actually holds
    pha
    lda #.loword(pfs_synth_line)
    sta z:PFS_K1                    ; source line base — the synthetic "blob"
    lda #.loword(_pfs_mvn_synth)
    sta z:PFS_K6                    ; ...and the MVN stub carrying its bank
    pla
    jsr _pfs_copy_line              ; THE SHIPPED COPY. K4 (the slot base) is
                                    ; still the one pfs_stage_* set: neither it
                                    ; nor _pfs_copy_line's own K2/K3 scratch is
                                    ; touched above.
    sep #$20
    .a8
    stz z:PFS_BUSY
    wai                             ; ...the VBlank that drains slot 0
    jmp @finish

; --- cmd 4: the timed staging loop ------------------------------------------
; K staged columns, bracketed by `mark`. The column index and the OTHER axis'
; window both stride by odd amounts, so successive stages take different
; two-span splits — a loop that stayed slot-aligned would measure the cheap
; case only. LAST_TY is restored afterwards and the counters are cleared, so
; the ring in VRAM is untouched by the measurement (staging writes WRAM only).
;
; PFS_BUSY is raised for the whole loop. Without it an NMI would drain a
; half-staged slot table into the live ring — the very interleave the guard
; exists for, and the bench is the one place in this ROM that stages outside
; `pfs_stream_tick`.
@arm_bench:
    .a8
    .i16
    lda #1
    sta z:PFS_BUSY
    rep #$20
    .a16
    lda z:PFS_LAST_TY
    sta f:US_ACC_LONG               ; stash: the bench walks it
    lda f:US_PARAM_LONG
    sta z:PFS_K5                    ; the counter lives in DP, NOT in Y:
                                    ; pfs_stage_col documents "Clobbers A, X,
                                    ; Y" and means it (MVN alone eats both
                                    ; index registers). The control arm keeps
                                    ; its counter in the same place so the
                                    ; two loops still cancel.
    stz z:PFS_K0
    sep #$20
    .a8
    lda #1
    sta f:US_MARK_LONG              ; <-- host breakpoint: timed region OPENS
@bench_loop:
    .a8
    .i16
    rep #$20
    .a16
    stz z:PFS_COL_CNT               ; A16: both counters — always slot 0
    jsr pfs_stage_col
    lda z:PFS_K0
    clc
    adc #7                          ; a fresh column, coprime with 128
    and #(PFS_TILES - 1)
    sta z:PFS_K0
    lda z:PFS_LAST_TY
    clc
    adc #13                         ; a fresh two-span split, coprime with 64
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TY
    lda z:PFS_K5
    dec
    sta z:PFS_K5
    beq @bench_end
    sep #$20
    .a8
    bra @bench_loop
@bench_end:
    .a16
    .i16
    sep #$20
    .a8
    lda #2
    sta f:US_MARK_LONG              ; <-- host breakpoint: timed region CLOSES
    rep #$20
    .a16
    lda f:US_ACC_LONG
    sta z:PFS_LAST_TY               ; ...the ring's real window, restored
    stz z:PFS_COL_CNT               ; nothing pending: the bench staged into
                                    ; WRAM only and its slots are not the
                                    ; ring's
    sep #$20
    .a8
    stz z:PFS_BUSY
    jmp @finish

; --- cmd 5: the identical loop with the staging removed ---------------------
; The control arm. Both loops share the counter, the two strides, the masks
; and the branch, so everything except `jsr pfs_stage_col` cancels in the
; subtraction — which is what makes this a measurement rather than an estimate
; with a loop tax folded in.
@arm_control:
    .a8
    .i16
    lda #1
    sta z:PFS_BUSY
    rep #$20
    .a16
    lda z:PFS_LAST_TY
    sta f:US_ACC_LONG
    lda f:US_PARAM_LONG
    sta z:PFS_K5                    ; the counter lives in DP, NOT in Y:
                                    ; pfs_stage_col documents "Clobbers A, X,
                                    ; Y" and means it (MVN alone eats both
                                    ; index registers). The control arm keeps
                                    ; its counter in the same place so the
                                    ; two loops still cancel.
    stz z:PFS_K0
    sep #$20
    .a8
    lda #1
    sta f:US_MARK_LONG
@ctl_loop:
    .a8
    .i16
    rep #$20
    .a16
    stz z:PFS_COL_CNT
    lda z:PFS_K0
    clc
    adc #7
    and #(PFS_TILES - 1)
    sta z:PFS_K0
    lda z:PFS_LAST_TY
    clc
    adc #13
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TY
    lda z:PFS_K5
    dec
    sta z:PFS_K5
    beq @ctl_end
    sep #$20
    .a8
    bra @ctl_loop
@ctl_end:
    .a16
    .i16
    sep #$20
    .a8
    lda #2
    sta f:US_MARK_LONG
    rep #$20
    .a16
    lda f:US_ACC_LONG
    sta z:PFS_LAST_TY
    stz z:PFS_COL_CNT
    sep #$20
    .a8
    stz z:PFS_BUSY
    jmp @finish

; WIDTH-RISK: every arm above narrows to A8 before jumping here, and @finish
; declares A8. The col_map probe shipped the opposite once: an arm reaching an
; A8-annotated @finish in A16 turned its `lda #0` into a 3-byte immediate that
; swallowed the next opcode and derailed the CPU into garbage. Narrow BEFORE
; the jump so every predecessor agrees with the width the label declares.
@finish:
    .a8
    .i16
    lda #0                          ; STZ has no long addressing mode
    sta f:US_CMD_LONG
    rep #$20
    .a16
    lda f:US_SEQ_LONG
    inc
    sta f:US_SEQ_LONG
    jmp @spin

; ===========================================================================
; ROM data — the level, twice, at the allocator's own placement.
; ===========================================================================
; Both blobs .assert their linker placement against the emitted claim symbols
; (the .incbin convention from game/microzero/main.asm), and each is exactly
; one 32 KB LoROM window by construction, which is what lets pfs_stream read a
; whole column or row without its source pointer ever crossing a bank seam.
; `make rom-unbacked` checks these claims have bytes at all.
; THE WORLD-SIZE ASSERT IS THE INCLUDER'S, and this is an includer. pfs_stream
; bakes 128x128 (two `xba` line-base multiplies = a 128-word row stride) but is
; handed only an ADDR and a BANK per blob, so it cannot check the assumption
; itself — a blob of some other world size would be read with the wrong stride
; and stream a plausible-looking wrong level. The claim size is in scope HERE,
; so the refusal lives here. (This file's header used to claim its own
; asserts did this; they check its claim sizes only.)
.segment "BANK1"
pfs_flat_bin:
    .incbin "pfs_flat.bin"
.assert ^pfs_flat_bin = ES_R_PFS_FLAT_BANK, error, "pfs_flat bank drifted"
.assert .loword(pfs_flat_bin) = ES_R_PFS_FLAT_ADDR, error, "pfs_flat addr drifted"
.assert ES_R_PFS_FLAT_SIZE = PFS_TILES * PFS_TILES * 2, error, "pfs_flat is not a 128x128 word world — pfs_stream bakes that stride"

.segment "BANK2"
pfs_flat_row_bin:
    .incbin "pfs_flat_row.bin"
.assert ^pfs_flat_row_bin = ES_R_PFS_FLAT_ROW_BANK, error, "pfs_flat_row bank drifted"
.assert .loword(pfs_flat_row_bin) = ES_R_PFS_FLAT_ROW_ADDR, error, "pfs_flat_row addr drifted"
.assert ES_R_PFS_FLAT_ROW_SIZE = PFS_TILES * PFS_TILES * 2, error, "pfs_flat_row is not a 128x128 word world — pfs_stream bakes that stride"

.segment "CODE"

; ===========================================================================
; cmd 7's synthetic source line — the third binding.
; ===========================================================================
; ONE world line's worth of tilemap words, 128 of them, every one with a
; non-zero HIGH byte. The level cannot supply this (it authors palette group 0
; throughout) and the bound blobs have no room for it (each is exactly one
; 32 KB window, all 128 lines of it level data), so cmd 7 binds this instead —
; see @arm_synth for why that is the honest way in rather than a way around.
;
; A LINE IS 128 WORDS, NOT 64, because `_pfs_copy_line`'s span cursor is a
; WORLD index masked `and #(PFS_TILES - 1)` and its source address is
; `K1 + K2 * 2`. It reads 64 of these per call, starting at w0 and wrapping
; through the table's end — which is the same wrap the real blobs' 128-word
; runs take, so this fixture exercises the two-span cut identically.
;
; This table is deliberately reachable ONLY through K1/K6: nothing else in the
; ROM reads it, and no claim names it. It sits in ROM0 beside the code, which
; is where `_pfs_mvn_col` / `_pfs_mvn_row` already live.
pfs_synth_line:
    .repeat PFS_TILES, k
        .byte PFS_SYNTH_LO + k, PFS_SYNTH_HI + k   ; little-endian word k
    .endrepeat
pfs_synth_line_end:
.assert (pfs_synth_line_end - pfs_synth_line) = PFS_TILES * 2, error, "the synthetic line is not 128 words — _pfs_copy_line's span cursor would read past it"

; The MVN stub for the synthetic blob's bank, in `_pfs_mvn_col`'s own shape:
; ca65 encodes MVN operands DST-BANK-FIRST, and the bank comes from the label
; rather than being written down, so the linker's placement decides it.
_pfs_mvn_synth:
    .byte $54, ES_PFS_SLOTS_BANK, ^pfs_synth_line
    rts
