; =============================================================================
; m7f_cam.asm — the altitude axis: two baked FACTORS joined per frame
; =============================================================================
; feature.toml carries the ruling and the refusals. This file carries the
; arithmetic, and all of it is one identity:
;
;  pose(h, a)[k] = S_a(k) * R(h)
;
;  A = S*cos B = S*sin C = -S*sin = -B D = S*cos = A
;
; TWO products per scanline, not four. C and D are a negate and a copy, which
; is the per-scanline form of the identity CD(h) == AB(h + POSES/4), verified
; byte-for-byte across the BAKED sets.
;
; --- THE UNITS, and why they are these ---------------------------------------
; m7f_rom bakes p = min(255, round(S/4)) one byte, stored p<<8
;  mag = min(255, round(256*|trig|)) one byte
; so P = p * mag = 64 * |A| and |A| = P >> 6.
;
; The quantisation is NOT a compromise chosen here. An 8-BIT per-scanline
; scale CLAMPS by construction: measured, the horizon coefficient saturates
; above s0 = 1020, i.e. above alt ~= 213 of 240, and `min(255, S/4)` clamps at
; S = 1020 EXACTLY. So the flat top at the top of the climb falls out of the
; representation rather than being a special case anyone has to remember.
;
; The 255 clamp on `mag` is REQUIRED, not cosmetic: round(256*|cos|) is 256 at
; the four cardinal headings, and both a byte operand and the 16-bit product
; (255*255 = 65025) need it below 256. It costs one part in 256 at exactly
; those four headings.
;
; --- THE INNER LOOP, and the three things that make it fit -------------------
;  1. ONE PROFILE READ PER LINE. The cos operand is `(p<<8) | cmag`; EORing it
;  with `cmag ^ smag` gives `(p<<8) | smag`, because both magnitudes live in
;  the low byte and p<<8 is untouched. So the sin operand is one 3-cycle EOR
;  off the cos one — no second ROM read, no second DP round trip.
;  2. ONE 16-BIT STORE STARTS A MULTIPLY. `sta $4202` in A16 writes $4202 (the
;  multiplicand) and then $4203 (the multiplier), and the multiply starts on
;  the $4203 write. Staging the operands as one word turns two stores into
;  one.
;  3. THE SIGNS ARE HOISTED OUT. cos and sin signs are constant for the frame,
;  so the loop exists in FOUR variants and the frame picks one. In-loop that
;  is worth 8 cycles a line against the branchless `eor mask / sec / sbc
;  mask` form.
;
; The multiplier needs 8 CPU cycles between the $4203 write and a valid $4216
; (race_logic.asm:244-248 spends four `nop`s on it). Both waits here are filled
; with real work — the operand stage and the index advances — so the join pays
; no idle cycles for latency.
;
; --- WHERE IT RUNS -----------------------------------------------------------
; In the scene TICK, during ACTIVE DISPLAY, into the BACK buffer. Not in the
; NMI hook: the composition is far larger than a VBlank, and it does not need
; to be there — `m7f_nmi_commit` re-points both channels at the finished buffer
; in one VBlank, which is what makes the swap atomic. The picture a frame shows
; is the table composed during the previous frame's active period; nothing in
; the rail recovers state from a frame NUMBER, so that phase is invisible.

; --- the band ---------------------------------------------------------------
; PV_L0_FLIGHT = 64, PV_L1_FLIGHT = 224: a high horizon, so the ground spreads
; out below and the sky band sits above it.
; --- THE MOVING HORIZON ------------------------------------------------------
; The band's BOTTOM is fixed at 224; its TOP moves with altitude, on the same
; shape a `l0 = base + height/2` horizon has, fitted to this rail's domain:
;
;  horizon(a) = 64 + 2*(a >> 2) band(a) = 224 - horizon(a)
;
; Deck: 160 lines from scanline 64 (29% sky). Ceiling: 120 lines from 104 (46%
; sky). So climbing visibly opens the sky up, which is the observation this
; answers — and it makes the frame CHEAPER, because a shorter band is fewer
; composed lines.
;
; DECK LEVEL IS TODAY'S EXACT GEOMETRY, BY CONSTRUCTION, and that is
; load-bearing rather than convenient: every number already measured on this
; rail was taken at the deck, so preserving a = 0 exactly keeps the worst case
; where it was instead of merely near it.
M7F_BAND_BOT  = 224                             ; fixed
M7F_BAND_TOP  = 64                              ; ...at the DECK
M7F_LINES     = M7F_BAND_BOT - M7F_BAND_TOP     ; 160 — the LONGEST band
M7F_SEG       = M7F_LINES / 2                   ; 80 — the LONGEST segment
M7F_BAND_STEP = 2                               ; scanlines per quantum
M7F_BAND_QUANT_LOG2 = 2                         ; ...one quantum per 4 alt idx
M7F_UNROLL    = 4                               ; gen_m7f_join.py's group size
M7F_HALF_W    = 128                             ; half the 256 px screen
M7F_FOCUS_Y   = 168                             ; FOCUS_Y_FLIGHT, the anchor row

; --- the two factor blobs' shapes, ASSERTED against the GENERATOR -----------
; This block used to say the build stopped here if gen_m7f_factors.py changed a
; stride or a level count, and it did not: the two asserts below check a
; PRODUCT against the allocator's claim size, and a layout refactor that keeps
; the product — 80 lines of 4 B instead of 160 of 2 — passes both while every
; offset the join reads moves. So the generator now emits its own layout beside
; the bytes (m7f_factors.inc) and this block pins it. Two kinds of check, and
; they are not the same question: the claim asserts are the ALLOCATOR contract
; (is the blob the size the declaration reserved), the format assert is the
; GENERATOR contract (is it still divided up the way this code reads it).
.include "m7f_factors.inc"                      ; GENERATED beside the blobs
.assert M7F_FACTORS_FORMAT = 1, error, "m7f_cam reads m7f_prof/m7f_trig at layout format 1 — gen_m7f_factors.py now emits a different record layout; re-read its header and re-derive the offsets in this file before bumping this number"

M7F_ALT_LEVELS  = 81                            ; {0,3,...,240}, measured
M7F_ALT_MAXIDX  = M7F_ALT_LEVELS - 1
M7F_ALT_SPAWN   = 40                            ; index of altitude 120
M7F_HEADINGS    = 256
M7F_HEAD_MASK   = M7F_HEADINGS - 1
M7F_PROF_STRIDE = M7F_LINES * 2                 ; 320 B per altitude
M7F_TRIG_STRIDE = 8                             ; cmag, smag, cneg, sneg

M7F_PROF_GUARD  = 8                             ; the join's read-ahead
.assert M7F_ALT_LEVELS * M7F_PROF_STRIDE + M7F_PROF_GUARD = ES_R_M7F_PROF_SIZE, error, "m7f_cam altitude model disagrees with the m7f_prof claim"
.assert M7F_HEADINGS * M7F_TRIG_STRIDE = ES_R_M7F_TRIG_SIZE, error, "m7f_cam heading model disagrees with the m7f_trig claim"
; ...and each narrated constant against the one the generator actually baked,
; which is what makes the format pin above sharp instead of ceremonial.
.assert M7F_LINES = M7F_FACTORS_LINES, error, "m7f_cam's band length disagrees with the baked profile's"
.assert M7F_ALT_LEVELS = M7F_FACTORS_ALT_LEVELS, error, "m7f_cam's altitude count disagrees with the baked profile's"
.assert M7F_ALT_SPAWN = M7F_FACTORS_ALT_SPAWN, error, "m7f_cam's spawn altitude index disagrees with the baked profile's"
.assert M7F_PROF_STRIDE = M7F_FACTORS_PROF_STRIDE, error, "m7f_cam's profile stride disagrees with the baked profile's"
.assert M7F_PROF_GUARD = M7F_FACTORS_PROF_GUARD, error, "m7f_cam's read-ahead guard disagrees with the baked profile's"
.assert M7F_HEADINGS = M7F_FACTORS_HEADINGS, error, "m7f_cam's heading count disagrees with the baked trig table's"
.assert M7F_TRIG_STRIDE = M7F_FACTORS_TRIG_STRIDE, error, "m7f_cam's trig record size disagrees with the baked trig table's"

M7F_PROF_LONG = (ES_R_M7F_PROF_BANK << 16) | ES_R_M7F_PROF_ADDR
M7F_TRIG_LONG = (ES_R_M7F_TRIG_BANK << 16) | ES_R_M7F_TRIG_ADDR

; --- the HDMA table layout, inside the one wram claim -----------------------
; THE SPLIT IS FORCED: an HDMA repeat count is SEVEN BITS, so a 160-line band
; cannot be one entry. 80 + 80 spends the two entries symmetrically and makes
; the join's two segment passes identical.
M7F_SKIP_CNT  = 0                               ; count byte: 64, non-repeat
M7F_SKIP_DAT  = 1                               ; its 4-byte unit (never seen)
M7F_CNT0      = 5                               ; count byte: $80|80
M7F_DAT0      = 6                               ; band lines 0..79
M7F_CNT1      = M7F_DAT0 + M7F_SEG * 4          ; 326
M7F_DAT1      = M7F_CNT1 + 1                    ; 327 — the MAX-band layout,
                                                ;  which is what the table is
                                                ;  SIZED from. The LIVE offset is
                                                ;  M7F_DAT1V and moves per frame.
M7F_TERM      = M7F_DAT1 + M7F_SEG * 4          ; 647
M7F_TBL_ONE   = M7F_TERM + 1                    ; 648 B per channel per buffer
M7F_BUF       = M7F_TBL_ONE * 2                 ; 1296 B per buffer (AB then CD)
M7F_HDMA_REPEAT = 128                           ; the repeat flag in a count byte

.assert M7F_BUF * 2 = ES_M7F_TBL_SIZE, error, "m7f_cam table layout disagrees with the m7f_tbl claim"
.assert M7F_SEG < M7F_HDMA_REPEAT, error, "an HDMA repeat count is 7 bits — a segment cannot exceed 127 lines"

; The two channels' bases WITHIN a buffer. The buffer selection rides in Y (`Y
; = back*M7F_BUF + <segment data offset> + line*4`), so one absolute base per
; channel serves both buffers and the inner loop needs no runtime pointer.
M7F_AB      = ES_M7F_TBL + 0
M7F_CD      = ES_M7F_TBL + M7F_TBL_ONE
M7F_AB_LONG = ES_M7F_TBL_LONG + 0
M7F_CD_LONG = ES_M7F_TBL_LONG + M7F_TBL_ONE
M7F_SHDW_CH = ES_SM_HDMA_SIZE / 8               ; 16 B of register file per channel

; What this feature needs of the placement the allocator handed it
; (vendor/rom/sf_asm.inc). The channels are DIRECT, so the table IS the data:
; m7f_arm_channels stamps A1B from `_BANK` once and every byte the two channels
; ever read is found by A1T walking from there. A1T is 16 bits and wraps WITHIN
; A1B, so a table straddling a bank seam would feed the second half of the band
; from the bank's own low bytes — a floor that renders, with the wrong geometry
; below the seam line. True today at $7E04A2 + 2592; asserted so a re-pack says
; so instead.
SF_ASSERT_NO_BANK_CROSS ES_M7F_TBL_LONG, ES_M7F_TBL_SIZE, "m7f_cam: the HDMA table crosses a bank — a direct channel's A1T wraps within A1B and the far half of the band would read the bank's low bytes"

; --- the pose state, inside the 14-byte dp claim ----------------------------
M7F_POSX    = ES_M7F_POSE + 0                   ; 16.16 world position
M7F_POSY    = ES_M7F_POSE + 4
M7F_HEAD    = ES_M7F_POSE + 8                   ; 0..255
M7F_ALTIDX  = ES_M7F_POSE + 10                  ; 0..80 — the INDEX, not the altitude
M7F_SPEED   = ES_M7F_POSE + 12                  ; SIGNED 8.8

; --- the join's scratch, inside the 14-byte dp claim ------------------------
M7F_CMAG    = ES_M7F_JOIN + 0
M7F_CSXOR   = ES_M7F_JOIN + 2
M7F_PTMP    = ES_M7F_JOIN + 4
M7F_XEND    = ES_M7F_JOIN + 6
M7F_BACK    = ES_M7F_JOIN + 8
M7F_XCUR    = ES_M7F_JOIN + 10
M7F_YCUR    = ES_M7F_JOIN + 12
M7F_XBASE   = ES_M7F_JOIN + 14                  ; the altitude's profile base
M7F_YBASE   = ES_M7F_JOIN + 16                  ; the back buffer's byte offset
M7F_PNEXT   = ES_M7F_JOIN + 18                  ; the NEXT line's staged cos
                                                ;  operand — the pipeline
M7F_DIRTY   = ES_M7F_JOIN + 20                  ; buffers still owing a compose
M7F_LASTH   = ES_M7F_JOIN + 22                  ; the pose the tables hold
M7F_LASTA   = ES_M7F_JOIN + 24
M7F_XGRP    = ES_M7F_JOIN + 26                  ; XEND minus one group: the
                                                ;  "do four whole lines
                                                ;  remain?" limit
M7F_NLINES  = ES_M7F_JOIN + 28                  ; this altitude's band length
M7F_SEGLEN  = ES_M7F_JOIN + 30                  ; ...and half of it
M7F_HORIZON = ES_M7F_JOIN + 32                  ; the band's first scanline
M7F_GEOOWED = ES_M7F_JOIN + 36                  ; buffers owing a RE-ANCHOR
M7F_DAT1V   = ES_M7F_JOIN + 34                  ; run 1's LIVE data offset.
                                                ;  Named apart from the static
                                                ;  M7F_DAT1 above, which is now
                                                ;  only the MAX-band layout the
                                                ;  table is SIZED from.

; --- the movement products' scratch, inside the 16-byte dp claim ------------
M7F_ABSSPD  = ES_M7F_MUL + 0                    ; |speed|
M7F_SPDNEG  = ES_M7F_MUL + 2                    ; 0 or 1
M7F_SPDLO8  = ES_M7F_MUL + 4                    ; |speed| low byte, << 8
M7F_SPDHI8  = ES_M7F_MUL + 6                    ; |speed| high byte, << 8
M7F_MAGTMP  = ES_M7F_MUL + 8                    ; the trig magnitude, re-used
M7F_P32     = ES_M7F_MUL + 10                   ; 4 B: the 16.16 step magnitude
M7F_STEPNEG = ES_M7F_MUL + 14                   ; 0 or 1

; --- the origin shadow, inside the 8-byte dp claim --------------------------
M7F_M7X     = ES_M7F_ORG + 0
M7F_M7Y     = ES_M7F_ORG + 2
M7F_HOFS    = ES_M7F_ORG + 4
M7F_VOFS    = ES_M7F_ORG + 6

; Every alias in the four blocks above is reached with `z:`, which is a FORCED
; direct-page mode — ca65 emits the two-byte form whatever the symbol's value
; turns out to be, so a claim placed or grown outside the page produces a store
; to the wrong byte of page zero rather than an assembler error. Two assertions
; per claim: the base is in the page, and the claim does not run out of it.
SF_ASSERT_DP ES_M7F_JOIN, "m7f_cam: the join scratch is outside the direct page"
SF_ASSERT_NO_PAGE_CROSS ES_M7F_JOIN, ES_M7F_JOIN_SIZE, "m7f_cam: the join scratch runs out of the direct page"
SF_ASSERT_DP ES_M7F_MUL, "m7f_cam: the movement scratch is outside the direct page"
SF_ASSERT_NO_PAGE_CROSS ES_M7F_MUL, ES_M7F_MUL_SIZE, "m7f_cam: the movement scratch runs out of the direct page"
SF_ASSERT_DP ES_M7F_POSE, "m7f_cam: the pose block is outside the direct page"
SF_ASSERT_NO_PAGE_CROSS ES_M7F_POSE, ES_M7F_POSE_SIZE, "m7f_cam: the pose block runs out of the direct page"
SF_ASSERT_DP ES_M7F_ORG, "m7f_cam: the origin shadow is outside the direct page"
SF_ASSERT_NO_PAGE_CROSS ES_M7F_ORG, ES_M7F_ORG_SIZE, "m7f_cam: the origin shadow runs out of the direct page"

; The world is the Mode 7 plane's own period, DERIVED from the map claim's size
; rather than narrated: the blob is 2 bytes per tile (tilemap even, CHR odd)
; over a square plane, so its size fixes the side. `no_literals` refuses a bare
; 1024 — it lands inside an emitted WRAM claim and cannot be told apart from a
; hand-narrated address — and that refusal does real work: writing the
; derivation is what makes the wrap FOLLOW the map instead of agreeing with it
; by coincidence.
M7F_MAP_T    = 128
M7F_TILE_PX  = 8
.assert 2 * M7F_MAP_T * M7F_MAP_T = ES_R_M7F_GROUND_SIZE, error, "m7f_cam world size disagrees with the m7f_ground claim"
M7F_WORLD_PX = M7F_MAP_T * M7F_TILE_PX          ; 1024 — the plane's period
M7F_WRAP     = M7F_WORLD_PX - 1                 ; the mask M7SEL's wrap makes exact

; =============================================================================
; M7F_LATCH — the join's own cost, latched from the PPU's H/V counters
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A. `ofs` is 0 for the START pair, 4 for the
; END one.
;
; THE INSTRUMENT SHIPS. It is not an `.ifdef` variant, and that is a decision
; rather than laziness: MesenRunner exposes NO cycle counter (the note is in
; tests/test_measure_rebuild.py's own docstring), so a cycle figure on this
; machine comes from an in-ROM SLHV latch ring — the CPU probe's technique
; (vendor/probes/probe_cpu_ref.asm's `CY_LATCH`) — and a figure measured on a
; SPECIAL build is a figure about a binary nobody ships. Latching in the
; shipping ROM means the rail's per-frame cost is a readable OUTPUT REGION of
; the artifact whose md5 this build record cites, re-measurable by anyone, and
; it is what tests/test_mode7_flight.py asserts the budget against.
;
; It costs about 40 cycles a frame — two latch pairs — against a join of many
; thousands, and the pair BRACKETS the join rather than enclosing itself: the
; start latch's own stores complete before the interval opens.
;
; Reading $2137 latches H and V; $213F resets the $213C/$213D read flip-flops
; first, so the two-read sequence returns low byte then high bit. These are
; READS of PPU ports, not writes, so no `[[claims.reg]]` covers them — the
; reg-ownership pass's write set is sta/stx/sty/stz plus the RMW family.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. The body narrows to A8 for the six
; byte-wide port reads and widens again before it ends, so the expansion is
; balanced and cannot leak a width into the caller. It touches only `sep #$20`
; / `rep #$20` — never `#$30` — so I-width tracking passes through untouched,
; which is what lets the call sites keep their long-indexed reads.
.macro M7F_LATCH ofs
    sep #$20
    .a8
    lda f:$00213F                   ; STAT78: reset the $213C/$213D flip-flops
    lda f:$002137                   ; SLHV: latch H and V
    lda f:$00213C                   ; OPHCT low 8 of the dot (4 mc/dot)
    sta f:ES_M7F_COST_LONG + ofs + 0
    lda f:$00213C                   ; OPHCT bit 0 = the ninth bit
    and #1
    sta f:ES_M7F_COST_LONG + ofs + 1
    lda f:$00213D                   ; OPVCT low 8 of the line (1364 mc/line)
    sta f:ES_M7F_COST_LONG + ofs + 2
    lda f:$00213D                   ; OPVCT bit 0
    and #1
    sta f:ES_M7F_COST_LONG + ofs + 3
    rep #$20
    .a16
.endmacro

; =============================================================================
; m7f_compose_timed — the change gate, then the join, bracketed
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y. What the scene tick calls.
;
; THE SKIP, AND WHY IT IS A COUNTDOWN RATHER THAN A FLAG. The obvious shape —
; "if the pose did not change, skip" — is WRONG under a double buffer, and
; wrong in a way that renders: the tick composes the BACK buffer, and on the
; frame after a change the back buffer is the OTHER one, which still holds the
; pose from two frames ago. A one-bit flag would skip it and the channels would
; stream that stale table on the very next swap. The picture would be right on
; alternate frames and a frame behind on the others — a 30 Hz judder that looks
; like a cadence problem rather than a logic one.
;
; So the gate counts BUFFERS OWED, not changes. A pose change marks BOTH
; buffers stale (`M7F_DIRTY = 2`); every frame that owes one composes and
; decrements. The skip engages only once BOTH buffers hold a table composed
; from the pose currently in force, which is exactly the condition under which
; skipping is invisible:
;
;  frame N pose changes -> DIRTY = 2, compose (owes 1). Swap: front is
;  this frame's table.
;  frame N+1 no change, owes 1 -> compose the OTHER buffer (owes 0).
;  frame N+2+ no change, owes 0 -> SKIP. Both buffers hold this pose, so
;  whichever the swap selects is correct.
;  frame M pose changes -> DIRTY = 2 and the compose happens in the SAME
;  frame, so there is no stale frame on the way out either.
;
; The latch pair BRACKETS THE GATE, not just the join, so a skip frame's cost
; is measurable at the same output region as a composing frame's — which is
; what makes "the skip engaged" an observation rather than an inference.
m7f_compose_timed:
    .a16
    .i16
    M7F_LATCH 0
    ; ---- did the pose move, and WHICH axis? --------------------------------
    ; THE TWO AXES DIRTY DIFFERENT THINGS, and that is the whole trick.
    ; Heading changes every coefficient but not the band's SHAPE; altitude
    ; changes both. So altitude owns a second owed-countdown for the geometry
    ; derive and the HDMA re-anchor, and a heading-only frame reuses the
    ; standing geometry instead of re-deriving and re-stamping control bytes
    ; that did not move. Same idiom as the data countdown one level up, and for
    ; the same reason: TWO buffers each need the stamp before it can stop.
    lda z:M7F_ALTIDX
    cmp z:M7F_LASTA
    beq @alt_same
    sta z:M7F_LASTA
    lda #2
    sta z:M7F_GEOOWED           ; both buffers owe a re-anchor
    sta z:M7F_DIRTY             ; ...and their data
@alt_same:
    .a16
    .i16
    lda z:M7F_HEAD
    cmp z:M7F_LASTH
    beq @gate
    sta z:M7F_LASTH
    lda #2                      ; a heading change dirties DATA only
    sta z:M7F_DIRTY
@gate:
    .a16
    .i16
    lda z:M7F_DIRTY
    beq @skip
    dec a
    sta z:M7F_DIRTY
    jsr m7f_compose
@skip:
    .a16
    .i16
    M7F_LATCH 4
    rts

; =============================================================================
; The four sign-variant segment routines — GENERATED
; =============================================================================
; `tools/gen_m7f_join.py` emits them into the rail's allocator map dir and this
; include pulls them in by name, which is `gen_move_lut.py`'s placement exactly
; (`move_lut.inc` into `$(MZ_MAP)`, `.include`d at
; game/microzero/scenes/race.asm:371). Emitted asm lives in build/, never in
; the tree.
;
; WHY GENERATED. The body is 4x unrolled and software-pipelined, and its only
; interesting property is a SCHEDULE: the multiplier needs 8 CPU cycles between
; the $4203 write and a valid $4216, and both windows per line are filled with
; work that has to happen anyway rather than with `nop`s. The generator COUNTS
; those cycles and refuses to emit an under-filled window — the allocator's
; refusal philosophy applied to instruction scheduling. Getting it wrong does
; not crash: the read returns the PREVIOUS product, the floor still renders,
; and only the whole-table oracle notices.
;
; In/out: A16/I16, DB = the table's bank. Reached ONLY through `jsr
; (m7f_seg_tab, x)`, so X and Y are handed over in DP — the dispatch needs X
; for the table index and the loop needs it for the profile. Each routine takes
; its entry state from M7F_XCUR / M7F_YCUR and leaves nothing behind.
.include "m7f_join.inc"

m7f_seg_tab:
    .word m7f_seg_pp            ; cos +, sin +
    .word m7f_seg_pn            ; cos +, sin -
    .word m7f_seg_np            ; cos -, sin +
    .word m7f_seg_nn            ; cos -, sin -

; =============================================================================
; m7f_compose — the whole per-frame join: heading + altitude -> the back buffer
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Runs in the scene TICK.
;
; Four blob reads, one variant dispatch, two segment calls. Everything constant
; for the frame is resolved here so the inner loop reads only the profile.
m7f_compose:
    .a16
    .i16
    ; ---- the heading factor: two operands and two sign masks ---------------
    lda z:M7F_HEAD
    and #M7F_HEAD_MASK
    asl a
    asl a
    asl a                       ; heading * 8, the trig blob's byte index
    tax
    lda f:M7F_TRIG_LONG + 0, x
    sta z:M7F_CMAG              ; cmag, in the low byte
    eor f:M7F_TRIG_LONG + 2, x  ; ...XOR smag: the inner loop's operand switch
    sta z:M7F_CSXOR

    ; ---- the band's geometry, ONLY when the altitude moved -----------------
    ; The four geometry words persist in DP, so a heading-only compose reads
    ; the standing values and pays nothing for them. Measured worth: this is
    ; off on every turning frame.
    lda z:M7F_GEOOWED
    bne :+
    jmp @geo_done
:
    dec a
    sta z:M7F_GEOOWED
    ; N = 160 - 2*(a >> 2); horizon = 224 - N; each run is N/2 lines.
    lda z:M7F_ALTIDX
    lsr a
    lsr a                       ; a >> 2
    asl a                       ; ...times M7F_BAND_STEP (2)
    sta z:M7F_HORIZON           ; scratch: the shrink, in scanlines
    lda #M7F_LINES
    sec
    sbc z:M7F_HORIZON
    sta z:M7F_NLINES            ; N
    lsr a
    sta z:M7F_SEGLEN            ; N/2 — each HDMA run
    lda #M7F_BAND_BOT
    sec
    sbc z:M7F_NLINES
    sta z:M7F_HORIZON           ; the band's first scanline
    ; run 1's data offset moves with N: it follows run 0's data and ITS count
    ; byte. THE TABLE LAYOUT IS DYNAMIC — everything after run 0 is
    ; f(altitude).
    lda z:M7F_SEGLEN
    asl a
    asl a
    clc
    adc #(M7F_DAT0 + 1)
    sta z:M7F_DAT1V

    jsr m7f_reanchor            ; the BACK buffer's control bytes
@geo_done:
    .a16
    .i16

    ; ---- the altitude factor: this frame's profile base --------------------
    ; index * 320 = (index << 8) + (index << 6). Not a shift, so it is written
    ; as the decomposition rather than as a multiply.
    lda z:M7F_ALTIDX
    xba                         ; index << 8  (index is 0..80, so the high byte
    and #$FF00                  ;             was zero and this is exact)
    sta z:M7F_XBASE
    lda z:M7F_ALTIDX
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; index << 6
    clc
    adc z:M7F_XBASE             ; index * 320 — the profile's byte offset
    sta z:M7F_XBASE

    ; ---- the back buffer's byte offset -------------------------------------
    lda z:M7F_BACK
    beq :+
    lda #M7F_BUF
    bra :++
:
    lda #0
:
    sta z:M7F_YBASE

    ; ---- pick the loop variant from the two sign masks ---------------------
    ; cneg/sneg are $0000 or $FFFF; bit 0 of each is the flag, and the table is
    ; indexed (cneg*2 + sneg) * 2.
    lda z:M7F_HEAD
    and #M7F_HEAD_MASK
    asl a
    asl a
    asl a
    tax
    lda f:M7F_TRIG_LONG + 4, x  ; cneg
    and #1
    asl a
    asl a                       ; cneg * 4
    sta z:M7F_PTMP
    lda f:M7F_TRIG_LONG + 6, x  ; sneg
    and #1
    asl a                       ; sneg * 2
    clc
    adc z:M7F_PTMP
    tax                         ; X = the variant's byte offset in m7f_seg_tab

    ; ---- DB = the table's own bank, so the stores are absolute,Y -----------
    ; Taken from the claim's emitted bank symbol rather than assumed: the
    ; allocator owns which WRAM bank this landed in.
    ;
    ; THE PUSH ORDER IS THE BUG THIS ROUTINE ALREADY PAID FOR. `phb` pushes ONE
    ; byte and `phx` under I16 pushes TWO, so pushing the variant BEFORE the
    ; bank and pulling it back after made `plx` read the bank byte plus half
    ; the variant — a garbage vector, an indirect JSR into it, and a table with
    ; one correct line and 159 wrong ones. Bank first, variant second, and the
    ; pulls mirror them: count push/pop BYTES per arm, never pushes. The
    ; pea/plb/plb form (vendor/rom/sf_asm.inc) does not change that reasoning:
    ; it pushes two bytes and pulls two, so it is stack-neutral across itself
    ; and the phb below it still owns exactly one byte.
    phb
    SF_SET_DB ES_M7F_TBL_BANK   ; 13 cycles / 5 bytes, at A16, A intact — the
                                ;   A8 window this used to open existed only to
                                ;   hold a bank byte in the accumulator
    phx                         ; the variant, for the second call

    ; ---- segment 0: band lines 0..79 ---------------------------------------
    ; Both segments take their entry X and Y from the bases above, so neither
    ; depends on how the other exited. The table offsets differ by more than
    ; the data length because a COUNT BYTE sits between the two runs.
    lda z:M7F_XBASE
    sta z:M7F_XCUR
    clc
    adc z:M7F_SEGLEN
    adc z:M7F_SEGLEN            ; + SEGLEN*2 bytes
    sta z:M7F_XEND              ; segment 0 stops after N/2 lines
    sec
    sbc #(M7F_UNROLL * 2)
    sta z:M7F_XGRP              ; ...and the group loop stops one group short
    lda z:M7F_YBASE
    clc
    adc #M7F_DAT0
    sta z:M7F_YCUR
    jsr (m7f_seg_tab, x)

    ; ---- segment 1: band lines 80..159 -------------------------------------
    lda z:M7F_XBASE
    clc
    adc z:M7F_SEGLEN
    adc z:M7F_SEGLEN
    sta z:M7F_XCUR              ; segment 1 starts where segment 0 stopped
    clc
    adc z:M7F_NLINES
    sta z:M7F_XEND              ; ...and runs the remaining N/2 lines
    sec
    sbc #(M7F_UNROLL * 2)
    sta z:M7F_XGRP
    lda z:M7F_YBASE
    clc
    adc z:M7F_DAT1V
    sta z:M7F_YCUR
    plx
    jsr (m7f_seg_tab, x)

    plb
    rts

; =============================================================================
; m7f_move — pos -= (sin, cos) * speed, in 16.16
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; IT LIVES HERE, NOT IN `m7f_logic`, AND THE REASON IS A CLAIM. The hardware
; multiplier is ONE resource under one name and it is WHOLE — one owner per
; scene — so a second feature declaring `ALU` in this scene is a contention the
; allocator refuses. `m7f_cam` owns it for the join; the four products a
; frame's movement needs therefore live with the owner, which is what keeps the
; claim TRUE rather than convenient.
;
; THE ARITHMETIC. Both factors are 8.8: the trig blob's magnitude is
; round(256*|trig|) and `speed` is SIGNED 8.8 (B forward, Y reverse, release
; hovers). Their product in units of 1/65536 px is exactly `mag * |speed|` — a
; 24-bit magnitude, which is a 16.16 step — and its sign is the trig sign XOR
; the speed's. The step is SUBTRACTED from the position, so "forward" advances
; toward the horizon.
;
; mag is 8-bit and |speed| is 16-bit, so each axis is TWO 8x8 products:
;  P = mag*spd_lo + ((mag*spd_hi) << 8)
; The four `nop`s are the multiplier's 8-cycle latency (race_logic.asm:245-248
; spends them the same way); four products a frame is not worth pipelining.
m7f_move:
    .a16
    .i16
    ; ---- |speed|, its sign, and the two pre-shifted operand halves --------
    lda z:M7F_SPEED
    bne :+
    rts                         ; hovering: no step, and no products at all
:
    .a16
    .i16
    bpl :+
    eor #$FFFF
    inc a                       ; |speed|
    ldy #1
    bra :++
:
    .a16
    .i16
    ldy #0
:
    .a16
    .i16
    sty z:M7F_SPDNEG
    sta z:M7F_ABSSPD
    and #$00FF
    xba
    sta z:M7F_SPDLO8            ; spd_lo << 8 — the operand word's high half
    lda z:M7F_ABSSPD
    and #$FF00
    sta z:M7F_SPDHI8            ; spd_hi << 8 (already positioned)

    ; ---- X axis: posx -= sin * speed --------------------------------------
    jsr m7f_trig_x
    lda f:M7F_TRIG_LONG + 2, x  ; smag
    jsr m7f_mul_mag
    jsr m7f_trig_x
    lda f:M7F_TRIG_LONG + 6, x  ; sneg
    eor z:M7F_SPDNEG
    and #1
    sta z:M7F_STEPNEG
    ldx #0                      ; the X axis's offset inside the pose claim
    jsr m7f_apply_step

    ; ---- Y axis: posy -= cos * speed --------------------------------------
    jsr m7f_trig_x
    lda f:M7F_TRIG_LONG + 0, x  ; cmag
    jsr m7f_mul_mag
    jsr m7f_trig_x
    lda f:M7F_TRIG_LONG + 4, x  ; cneg
    eor z:M7F_SPDNEG
    and #1
    sta z:M7F_STEPNEG
    ldx #(M7F_POSY - M7F_POSX)  ; ...and the Y axis's
    jsr m7f_apply_step
    rts

; --- m7f_trig_x: X = the trig blob byte index for the live heading ----------
; In/out: A16/I16, DB=0. Clobbers A, X.
m7f_trig_x:
    .a16
    .i16
    lda z:M7F_HEAD
    and #M7F_HEAD_MASK
    asl a
    asl a
    asl a
    tax
    rts

; --- m7f_mul_mag: A (an 8-bit magnitude) * |speed| -> M7F_P32 ---------------
; In/out: A16/I16, DB=0. Clobbers A, Y.
m7f_mul_mag:
    .a16
    .i16
    and #$00FF
    sta z:M7F_MAGTMP
    ora z:M7F_SPDLO8            ; (spd_lo << 8) | mag — one word, both operands
    sta f:$004202               ; $4202 = mag, $4203 = spd_lo: multiply starts
    ; THE MULTIPLIER'S 8 CYCLES, counted per instruction rather than counted by
    ; the reader. Four `nop`s spent 8 cycles in 4 bytes; this spends the same 8
    ; in 3. The densest padding this CPU has is a stack pair — `phb`/`plb` is 7
    ; cycles in 2 bytes — but 7 does not divide 8 and there is no one-cycle
    ; instruction to finish it, so the exact form is the `xba` pair (3 + 3,
    ; which puts A back where it was) plus one `nop`. A is dead here (the `lda`
    ; below reloads it) and so are the flags the pair touches; the carry, which
    ; the adc chain further down depends on, is not one of them.
    xba                         ; 3
    xba                         ; 3   — A restored
    nop                         ; 2   = 8
    lda f:$004216               ; mag * spd_lo
    sta z:M7F_P32 + 0
    stz z:M7F_P32 + 2
    lda z:M7F_MAGTMP
    ora z:M7F_SPDHI8            ; (spd_hi << 8) | mag
    sta f:$004202
    xba                         ; 3   — the same 8-cycle latency window as above
    xba                         ; 3
    nop                         ; 2   = 8
    lda f:$004216               ; mag * spd_hi — weighted 256
    tay                         ; keep it: both halves are needed
    and #$00FF
    xba                         ; its low byte, shifted UP into P32+1
    clc
    adc z:M7F_P32 + 0
    sta z:M7F_P32 + 0
    tya
    xba
    and #$00FF                  ; its high byte, shifted DOWN into P32+2
    adc z:M7F_P32 + 2           ; ...plus the carry out of the word below
    sta z:M7F_P32 + 2
    rts

; --- m7f_apply_step: pos[X] -= (+/-)M7F_P32, wrapped to the plane's period --
; In/out: A16/I16, DB=0. X = 0 for the X axis or 4 for the Y one; M7F_STEPNEG
; is 0 or 1. Clobbers A.
;
; The product is SUBTRACTED, so a NEGATIVE product adds. The integer word is
; masked to the world period — the same 1024 px M7SEL's screen-over wrap makes
; exact, derived from the map claim rather than narrated, so the position and
; the picture agree about where the world repeats.
m7f_apply_step:
    .a16
    .i16
    lda z:M7F_STEPNEG
    bne @add
    lda z:M7F_POSX + 0, x
    sec
    sbc z:M7F_P32 + 0
    sta z:M7F_POSX + 0, x
    lda z:M7F_POSX + 2, x
    sbc z:M7F_P32 + 2
    and #M7F_WRAP
    sta z:M7F_POSX + 2, x
    rts
@add:
    .a16
    .i16
    lda z:M7F_POSX + 0, x
    clc
    adc z:M7F_P32 + 0
    sta z:M7F_POSX + 0, x
    lda z:M7F_POSX + 2, x
    adc z:M7F_P32 + 2
    and #M7F_WRAP
    sta z:M7F_POSX + 2, x
    rts

; =============================================================================
; m7f_reanchor — the BACK buffer's control bytes, for this altitude's band
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X. Reads M7F_HORIZON / M7F_SEGLEN /
; M7F_DAT1V / M7F_BACK.
;
; THE BACK BUFFER ONLY, and that is the whole tear argument. HDMA reads a table
; PROGRESSIVELY down the frame, so rewriting a count byte in the LIVE table
; during active display would change the run lengths under a channel that is
; part-way through them. Writing only the buffer the tick is composing means a
; re-anchor is published by the same atomic swap the data is — and because an
; altitude change marks BOTH buffers owed (m7f_compose_timed's countdown), both
; get re-anchored over the same two frames the data does.
;
; Three of the four control bytes MOVE with altitude: run 1's count sits at
; M7F_DAT1V - 1 and the terminator at M7F_DAT1V + SEGLEN*4, both f(N). Only the
; skip count's position is fixed — its VALUE is the horizon.
m7f_reanchor:
    .a16
    .i16
    lda z:M7F_BACK
    beq :+
    ldx #M7F_BUF
    bra :++
:
    ldx #0
:
    sep #$20
    .a8
    lda z:M7F_HORIZON
    sta f:M7F_AB_LONG + M7F_SKIP_CNT, x     ; hold from line 0 to the horizon
    sta f:M7F_CD_LONG + M7F_SKIP_CNT, x
    lda z:M7F_SEGLEN
    ora #M7F_HDMA_REPEAT
    sta f:M7F_AB_LONG + M7F_CNT0, x         ; run 0: a new unit every scanline
    sta f:M7F_CD_LONG + M7F_CNT0, x
    rep #$20
    .a16
    ; run 1's count byte and the terminator both move with the band length.
    txa
    clc
    adc z:M7F_DAT1V
    tax                                     ; X = buffer + DAT1
    sep #$20
    .a8
    lda z:M7F_SEGLEN
    ora #M7F_HDMA_REPEAT
    sta f:M7F_AB_LONG - 1, x                ; run 1's count, just before its data
    sta f:M7F_CD_LONG - 1, x
    rep #$20
    .a16
    lda z:M7F_SEGLEN
    asl a
    asl a                                   ; SEGLEN * 4 data bytes
    sta z:M7F_PTMP
    txa
    clc
    adc z:M7F_PTMP
    tax
    sep #$20
    .a8
    lda #0
    sta f:M7F_AB_LONG, x                    ; the terminator, after run 1
    sta f:M7F_CD_LONG, x
    rep #$20
    .a16
    rts

; =============================================================================
; m7f_arm — build both buffers' table skeletons and stage both channels
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene enter). Clobbers A,
; X, Y. The caller seeds ES_M7F_POSE first, and ORs the two enable bits into
; the scene_mgr HDMAEN shadow after.
m7f_arm:
    .a16
    .i16
    ; ---- the declared init contract: zero the WHOLE claim first ------------
    ; The bytes past each terminator are never stamped, but the DMA controller
    ; still fetches table bytes after the $00 on real hardware, so they must
    ; not be power-on garbage (rule 5; sh2_cam's sh2_arm and mode7_persp's
    ; persp_arm both open this way for the same reason).
    lda #0
    ldx #(ES_M7F_TBL_SIZE - 2)
:   sta f:ES_M7F_TBL_LONG, x
    dex
    dex
    bpl :-

    ; ---- the control bytes are now PER-ALTITUDE ---------------------------
    ; There is no static skeleton to stamp any more: the skip count IS the
    ; horizon and both run counts are N/2, all functions of the seeded
    ; altitude. M7f_compose derives them and calls m7f_reanchor for the buffer
    ; it is about to fill, so composing both buffers below stamps both.

    ; ---- both buffers composed, so frame 1 shows a floor rather than the
    ;  zeroed skeleton the loop above left behind
    lda #2
    sta z:M7F_GEOOWED           ; both buffers owe their first stamp
    stz z:M7F_BACK
    jsr m7f_compose
    lda #1
    sta z:M7F_BACK
    jsr m7f_compose
    stz z:M7F_BACK

    ; Both buffers now hold the seeded pose's table, so the change gate starts
    ; owing NOTHING — and the pose it remembers is the one they were composed
    ; from. Seeding these three is rule 5: they are read before the first tick
    ; writes them.
    lda z:M7F_HEAD
    sta z:M7F_LASTH
    lda z:M7F_ALTIDX
    sta z:M7F_LASTA
    stz z:M7F_DIRTY

    jsr m7f_stamp_origin

    ; ---- the two channels, in the scene_mgr shadow the NMI MVNs to $4300 ---
    ; A DIRECT channel's table IS its data, so A1B/A1T alone locate every byte
    ; the channel will ever read — there is no DASB to stamp. DMAP and BBAD are
    ; the allocator's emitted encodings of the declaration; neither is
    ; narrated.
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #(ES_H_M7FAB_CH * M7F_SHDW_CH)
    lda #ES_H_M7FAB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_M7FAB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x              ; BBAD: M7A
    lda #ES_M7F_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x              ; A1B: the table's bank
    ldx #(ES_H_M7FCD_CH * M7F_SHDW_CH)
    lda #ES_H_M7FCD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_M7FCD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x              ; BBAD: M7C
    lda #ES_M7F_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    jsr m7f_point_channels                  ; A1T for both, at the FRONT buffer
    rts

; --- m7f_point_channels: aim both A1T words at the buffer NOT being composed -
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
m7f_point_channels:
    .a16
    .i16
    lda z:M7F_BACK
    beq :+
    lda #0                      ; back = 1 -> the finished front is buffer 0
    bra :++
:
    lda #M7F_BUF                ; back = 0 -> the finished front is buffer 1
:
    clc
    adc #M7F_AB
    ; The channel-shadow index rides in X, not Y: `sta long,Y` is not an
    ; addressing mode on this CPU — only `long,X` is — and reaching for the
    ; symmetry is an assembler error rather than a silent one.
    ldx #(ES_H_M7FAB_CH * M7F_SHDW_CH)
    sta f:ES_SM_HDMA_LONG+2, x  ; A1T: this frame's AB table
    clc
    adc #(M7F_CD - M7F_AB)
    ldx #(ES_H_M7FCD_CH * M7F_SHDW_CH)
    sta f:ES_SM_HDMA_LONG+2, x  ; A1T: this frame's CD table
    rts

; =============================================================================
; m7f_stamp_origin — the camera's world position -> the four origin words
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE WHOLE ORIGIN SOLVE, AND IT IS SUBTRACTION. The PPU computes
;
;  texel = M7 + Mat * (SX + HOFS - M7X, SY + VOFS - M7Y)
;
; so setting HOFS = M7X - 128 and VOFS = M7Y - FOCUS_Y makes the offset (SX -
; 128, SY - 168): the pose pivots about screen column 128 on the anchor row,
; and the camera's world position is exactly what renders there. No
; trigonometry, even with rotation — the per-scanline matrix carries all of it,
; and zeroing the matrix term at the pivot is what lets the heading change
; without touching the origin math (sh2_cam's cam_stamp records the same
; property for the same reason).
m7f_stamp_origin:
    .a16
    .i16
    lda z:M7F_POSX + 2          ; the integer word of the 16.16 position
    sta z:M7F_M7X
    sec
    sbc #M7F_HALF_W
    sta z:M7F_HOFS
    lda z:M7F_POSY + 2
    sta z:M7F_M7Y
    sec
    sbc #M7F_FOCUS_Y
    sta z:M7F_VOFS
    rts

; =============================================================================
; m7f_nmi_commit — the atomic swap + the origin, once per VBlank
; =============================================================================
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A, X, Y.
;
; WIDTH-RISK: this is a CROSS-FILE contract. It is entered A8 (the NMI hook's
; width), widens for its own 16-bit work, and MUST restore A8 before returning
; — the hook's next instruction is assembled A8. Width-check cannot see across
; a file boundary in either direction, so this marker carries it.
;
; TWO COMMITS, AND THE ORDER BETWEEN THEM DOES NOT MATTER; what matters is that
; both happen in the SAME VBlank. The channels are re-pointed at the buffer the
; tick just finished and the origin is stamped from the same state, so the
; matrix a frame renders with and the origin it renders about are one frame's
; answer. The A1T words land in the scene_mgr shadow, which sm_nmi_core MVNs to
; $4300 immediately after this returns — in time for the next frame's line-0
; HDMA init fetch.
m7f_nmi_commit:
    .a8
    .i16
    rep #$20
    .a16
    ; The tick has finished the back buffer, so it becomes the front one: flip
    ; first, then point — point_channels aims at whichever buffer `back` does
    ; NOT name.
    lda z:M7F_BACK
    eor #1
    sta z:M7F_BACK
    jsr m7f_point_channels
    jsr m7f_stamp_origin
    sep #$20
    .a8
    ; ---- the four origin registers, each written TWICE ---------------------
    ; A 16-BIT STORE WOULD BE WRONG HERE and silently so: `sta a:$211F` in A16
    ; writes $211F then $2120, i.e. M7X's low byte followed by M7Y's low byte.
    ; These are write-twice ports — the same address, twice — so the commit is
    ; A8 throughout.
    lda z:M7F_M7X + 0
    sta a:$211F
    lda z:M7F_M7X + 1
    sta a:$211F
    lda z:M7F_M7Y + 0
    sta a:$2120
    lda z:M7F_M7Y + 1
    sta a:$2120
    lda z:M7F_HOFS + 0
    sta a:$210D
    lda z:M7F_HOFS + 1
    sta a:$210D
    lda z:M7F_VOFS + 0
    sta a:$210E
    lda z:M7F_VOFS + 1
    sta a:$210E
    rts
