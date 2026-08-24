; =============================================================================
; shm_cam.asm — N flat Mode 7 cameras over one plane, on TWO HDMA channels
; =============================================================================
; THE WHOLE MECHANISM, in one place:
;
;  ch ES_H_SHMAB_CH DMAP $03 (mode 3, DIRECT) -> M7A/M7B
;  ch ES_H_SHMCD_CH DMAP $03 -> M7C/M7D
;  one WRAM table each, N entries of 5 bytes and a terminator:
;  AB: [lines, A_lo, A_hi, B_lo, B_hi] x N, [$00]
;  CD: [lines, C_lo, C_hi, D_lo, D_hi] x N, [$00]
;
; Mode 3 is write-two-registers-twice: one 4-byte unit is exactly [lo, hi] for
; each of two write-twice 16-bit registers, so BBAD $1B delivers a complete
; M7A+M7B pair and $1D a complete M7C+M7D one. Every DMAP, BBAD and channel
; number above comes from the allocator's emitted symbols.
;
; THE NON-REPEAT TRAP — the one property of this rail that lives in the TABLE
; rather than in the declaration. Each entry's count byte has BIT 7 CLEAR, so
; the DMA controller transfers its 4-byte unit ONCE at the band's first
; scanline and then holds silent for the remaining `lines - 1`. The write-twice
; latch keeps the value on the register for the whole span, which is what makes
; a band's matrix CONSTANT for ~nil cost: one HBlank write per channel per band
; per frame.
;
; With bit 7 SET (repeat) the controller would fetch a NEW 4-byte unit every
; scanline, walk off the end of an 11- or 16-byte table within four lines, and
; stream whatever follows it into M7A-M7D — the plane collapses. That failure
; is planted in tools/plants/split_h_matrix_demo.py (`shm-repeat-bit`) rather
; than argued, because "we set the bit correctly" is not evidence that anything
; would notice if we did not.
;
; THE BAND COUNT IS NOT DECLARED ANYWHERE. It is the number of SHM_BAND
; expansions the scene writes, which is why `split_h_matrix_demo` (2) and
; `split_h_persp3_demo` (3) share this feature unmodified. See feature.toml's
; header for the four measured properties that separate this from `sh2_cam`,
; whose band count IS declared. That finding came out of two allocator runs,
; not out of reasoning about the two features.
;
; THE PER-FRAME WORK, all of it: shm_zoom_step (scene tick, active display)
; one pad read, one clamped add shm_zoom_stamp (VBlank hook) TWO stores and
; with no button held the step is a read and two branches. A LIST, not a
; measured cycle figure — nothing here has been measured on the emulator, and
; the rail's claim ("N cameras cost what one costs") is about HBlank writes,
; which is a count of table entries and is exact.

; --- the table geometry -----------------------------------------------------
; 32 B apart so the offsets read as a table rather than as arithmetic. An entry
; is 5 bytes and each table needs a 1-byte terminator, so 32 B holds SIX bands
; — twice what row 12 asks for. DERIVED from the claim's own size rather than
; narrated, so a table that outgrows the claim stops the build here instead of
; scribbling over its neighbour.
SHM_ENTRY    = 5                            ; [count, lo, hi, lo, hi]
SHM_TBL_SPAN = ES_SHM_TBL_SIZE / 2          ; 32: one table's share of the claim
SHM_MAX_BAND = (SHM_TBL_SPAN - 1) / SHM_ENTRY
.assert SHM_MAX_BAND >= 3, error, "shm_cam: the wram claim no longer holds persp3's three bands"

SHM_TBL_AB      = ES_SHM_TBL + 0
SHM_TBL_CD      = ES_SHM_TBL + SHM_TBL_SPAN
SHM_TBL_AB_LONG = ES_SHM_TBL_LONG + 0
SHM_TBL_CD_LONG = ES_SHM_TBL_LONG + SHM_TBL_SPAN

; --- the live band's zoom state, inside the 8-byte dp claim -----------------
SHM_SCALE = ES_SHM_ZOOM + 0                 ; the live band's M7A/M7D, 8.8
SHM_OFF   = ES_SHM_ZOOM + 2                 ; its entry's byte offset (slot * 5)
SHM_LO    = ES_SHM_ZOOM + 4                 ; clamp floor
SHM_HI    = ES_SHM_ZOOM + 6                 ; clamp ceiling

; --- which channel of the scene_mgr shadow is which -------------------------
; The 128-byte shadow the NMI MVNs to $4300; 16 B of register file per channel.
SHM_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8

; --- the pad bits -----------------------------------------------------------
; $4218 delivers one 16-bit word: B Y Select Start Up Down Left Right in the
; HIGH byte, A X L R in the low. Written as SHIFTS rather than as $0100 and
; friends because `no_literals` cannot tell a bare $0100 from a hand-narrated
; WRAM address, and the shift form says which bit POSITION is meant.
SHM_JOY_RIGHT = 1 << 8
SHM_JOY_LEFT  = 1 << 9

; The zoom step, in 8.8. Four per frame held is ~1.6% of the 1.0 ceiling, so a
; sweep from the two-band rail's 0.25 to a collapsed 1.0 takes 48 frames — long
; enough that a test can stop part-way and read an intermediate period, short
; enough that the whole cycle fits one lockstep run.
SHM_ZOOM_STEP = 4

; =============================================================================
; SHM_BAND — stamp one band's constant matrix into both tables
; =============================================================================
; `slot` is the band index (0-based, in scanline order); `lines` its height in
; scanlines; `scale` its 8.8 zoom, which becomes BOTH M7A and M7D.
;
; A = D = scale, B = C = 0 is a flat top-down camera at angle 0: the matrix is
; a pure uniform scale, so one screen pixel steps `scale/256` world pixels and
; the world's 8-px checker renders at `8 * 256 / scale` screen pixels. That
; period is the band's whole visible identity.
;
; The count byte is written A8 so it is ONE byte; bit 7 stays clear, which is
; the NON-REPEAT reading (see the header). `lines` must therefore be 1..127 —
; asserted, because a 128-line band would silently become a repeat entry and
; collapse the plane, which is exactly the trap this rail teaches.
;
; WIDTH-RISK: entry A16/I16 and exit A16/I16. The body toggles A to 8 bits for
; the count byte and back, in a balanced sep/rep pair, and never touches the
; index width — so the expansion cannot leak a width into the caller on either
; axis. `stz` has no long addressing mode on the 65816, which is why the zero
; words go through A rather than through it.
.macro SHM_BAND slot, lines, scale
    .assert (lines) >= 1 && (lines) <= 127, error, "SHM_BAND: line count must be 1..127 — bit 7 is the HDMA REPEAT flag"
    .assert (slot) >= 0 && (slot) < SHM_MAX_BAND, error, "SHM_BAND: slot past the end of the shm_tbl claim"
    sep #$20
    .a8
    lda #(lines)
    sta f:SHM_TBL_AB_LONG + (slot) * SHM_ENTRY
    sta f:SHM_TBL_CD_LONG + (slot) * SHM_ENTRY
    rep #$20
    .a16
    lda #0
    sta f:SHM_TBL_AB_LONG + (slot) * SHM_ENTRY + 3      ; M7B = 0
    sta f:SHM_TBL_CD_LONG + (slot) * SHM_ENTRY + 1      ; M7C = 0
    lda #(scale)
    sta f:SHM_TBL_AB_LONG + (slot) * SHM_ENTRY + 1      ; M7A = scale
    sta f:SHM_TBL_CD_LONG + (slot) * SHM_ENTRY + 3      ; M7D = scale
.endmacro

; =============================================================================
; SHM_END — the terminator that ends both channels for the frame
; =============================================================================
; `slot` is the band count: the entry index one past the last SHM_BAND. A count
; byte of $00 ends the channel, after which the write-twice latch simply holds
; the last band's matrix — which is why the last band's `lines` may be short by
; a line or two without a visible seam at the bottom of the picture.
;
; WIDTH-RISK: entry A16, exit A16; balanced sep/rep, index width untouched.
.macro SHM_END slot
    .assert (slot) >= 1 && (slot) <= SHM_MAX_BAND, error, "SHM_END: band count past the end of the shm_tbl claim"
    sep #$20
    .a8
    lda #0
    sta f:SHM_TBL_AB_LONG + (slot) * SHM_ENTRY
    sta f:SHM_TBL_CD_LONG + (slot) * SHM_ENTRY
    rep #$20
    .a16
.endmacro

; --- shm_zero: the declared init contract, before any SHM_BAND -------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; ZERO THE WHOLE CLAIM FIRST. The bytes past each table's terminator are never
; stamped, but the DMA controller's terminator processing still fetches the
; bytes after the $00 — real hardware reads them, so they must not be power-on
; garbage (the uninit-read contract; sh2_cam's sh2_arm and mode7_persp's
; persp_arm open the same way for the same reason). The loop follows the
; claim's own emitted size rather than a copied constant.
shm_zero:
    .a16
    .i16
    lda #0
    ldx #(ES_SHM_TBL_SIZE - 2)
:   sta f:ES_SHM_TBL_LONG, x
    dex
    dex
    bpl :-
    rts

; --- shm_arm: stage both channels into the scene_mgr shadow ----------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X.
;
; Called AFTER the SHM_BAND expansions, because a channel whose table is not
; yet built is a channel that streams whatever the zero left behind. The caller
; ORs the two enable bits into the scene_mgr HDMAEN shadow after this returns.
;
; NO DASB. These are DIRECT channels: the table IS the data, so A1B/A1T alone
; locate every byte the channel will ever read. That absence is the second of
; the four properties separating this from `sh2_cam`, where DASB is per-channel
; and therefore forces one channel PAIR per band.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. The DMAP/BBAD/A1B bytes are stored
; A8 inside balanced sep/rep windows; the index width is never narrowed.
shm_arm:
    .a16
    .i16
    sep #$20
    .a8
    ldx #(ES_H_SHMAB_CH * SHM_SHDW_CH_SIZE)
    lda #ES_H_SHMAB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: direct, 2-regs-write-twice
    lda #ES_H_SHMAB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_SHM_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the table's bank ($7E)
    rep #$20
    .a16
    lda #SHM_TBL_AB
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: the AB table

    sep #$20
    .a8
    ldx #(ES_H_SHMCD_CH * SHM_SHDW_CH_SIZE)
    lda #ES_H_SHMCD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHMCD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_SHM_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHM_TBL_CD
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: the CD table
    rts

; --- shm_zoom_step: the pad moves the live band's camera -------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE LIVE BAND, MADE DRIVABLE. Animating the bottom band's scale on the frame
; counter would show the band is LIVE just as well — but a free-running
; animation can only be sampled, and a test that samples it cannot stop, hold
; still, or go back. Right steps the scale UP (the band
; zooms OUT — a shorter on-screen checker period), Left steps it DOWN, both
; clamped, so the state cycle a test drives is out / in / idle in either order
; and the picture is stationary whenever nothing is held.
;
; Right AND Left together is a deliberate no-op (+step then -step): the
; hardware can report both on a worn pad, and cancelling is the honest answer.
;
; RUNS IN THE TICK, NOT THE HOOK. It only touches DP; the two bytes that reach
; the HDMA table are shm_zoom_stamp's, in VBlank, where a half-written entry
; cannot tear.
;
; The clamps are checked against BOTH the carry (wrap past $0000/$FFFF) and the
; bound, because a 16-bit `sbc` that borrows leaves a huge unsigned value that
; compares ABOVE the floor — the bound test alone would let the band wrap to a
; scale of $FFFC instead of stopping at the floor.
shm_zoom_step:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #SHM_JOY_RIGHT
    beq @noright
    lda z:SHM_SCALE
    clc
    adc #SHM_ZOOM_STEP
    bcs @hi                         ; wrapped past $FFFF
    cmp z:SHM_HI
    bcc @putr                       ; still below the ceiling
@hi:
    .a16
    lda z:SHM_HI
@putr:
    .a16
    sta z:SHM_SCALE
@noright:
    .a16
    lda z:ES_INP_CUR
    bit #SHM_JOY_LEFT
    beq @noleft
    lda z:SHM_SCALE
    sec
    sbc #SHM_ZOOM_STEP
    bcc @lo                         ; borrowed: underflowed past $0000
    cmp z:SHM_LO
    bcs @putl                       ; still above the floor
@lo:
    .a16
    lda z:SHM_LO
@putl:
    .a16
    sta z:SHM_SCALE
@noleft:
    .a16
    rts

; --- shm_zoom_stamp: the live band's two matrix words, once per VBlank -----
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A, X.
;
; WIDTH-RISK: this is a CROSS-FILE contract. It is entered A8 (the NMI hook's
; width), widens for the two 16-bit stores, and MUST restore A8 before
; returning — the hook's next instruction is assembled A8. Width-check cannot
; see across the file boundary in either direction, so this marker carries it.
;
; IN VBLANK, and that is not incidental: the HDMA init fetch for the next frame
; reads this table at line 0, so a half-written entry here would be a torn
; frame. Two stores is the whole of it, so the VBlank window is enormous
; relative to the work and no guard is needed.
;
; UNCONDITIONAL, deliberately the worst case. Gating on "did the pad move"
; would make the rail's per-frame cost depend on input and make a held-still
; frame cheaper than the number the rail should be judged on. It is two stores.
;
; SHM_OFF is the LIVE band's entry offset, seeded by the scene: 1 * 5 on the
; two-band rail, 2 * 5 on the three-band one. It is what lets one feature serve
; both without knowing N.
shm_zoom_stamp:
    .a8
    .i16
    rep #$20
    .a16
    ldx z:SHM_OFF
    lda z:SHM_SCALE
    sta f:SHM_TBL_AB_LONG + 1, x    ; M7A of the live band
    sta f:SHM_TBL_CD_LONG + 3, x    ; M7D of the live band
    sep #$20
    .a8
    rts
