; =============================================================================
; window_iris.asm — the lantern: a per-scanline window that follows the player
; =============================================================================
; One active-display HDMA channel drives WH0+WH1 (window 1's left and right
; bound) from a WRAM table this file rebuilds every frame. Colour math is
; confined to the window's OUTSIDE, so the unlit part of the room darkens
; rather than the lit part brightening; BG2 is additionally CLIPPED to the
; window, so the decor is present inside the circle and absent outside it.
;
; THE REGISTER CONTRACT IS IN feature.toml, derived from Mesen2 source. Read
; it before changing any value here. Nothing in the build checks these numbers:
; no_literals treats $2100-$21FF as I/O ports and immediates below $100 as
; data, so a wrong field renders as "the effect silently does nothing" — the
; hardest class of bug to attribute.
;
; Table layout in the iris_tab claim (mode 1 = 2 data bytes per unit):
;  +0 $80|IRIS_SPLIT_A repeat entry, rows 0..126
;  +1 .. +254 127 x [WH0][WH1]
;  +255 $80|IRIS_SPLIT_B repeat entry, rows 127..223
;  +256 .. +449 97 x [WH0][WH1]
;  +450 $00 terminator
; The three structural bytes are written once by wi_arm. Two entries and not
; one because an HDMA repeat count is 7 bits: 224 lines does not fit in one.

IRIS_R        = 48                  ; lit radius, px — MUST match gen_iris_lut
IRIS_LUT_LEN  = 2 * IRIS_R + 1
IRIS_LINES    = 224                 ; visible scanlines
IRIS_SPLIT_A  = 127                 ; rows in the first repeat entry (max 127)
IRIS_SPLIT_B  = IRIS_LINES - IRIS_SPLIT_A
IRIS_DATA_A   = 1                   ; byte offset of the first entry's data
IRIS_DATA_B   = IRIS_DATA_A + 2 * IRIS_SPLIT_A + 1
IRIS_END      = IRIS_DATA_B + 2 * IRIS_SPLIT_B
.assert IRIS_SPLIT_A <= 127, error, "HDMA repeat count is 7 bits"
.assert IRIS_SPLIT_B <= 127, error, "HDMA repeat count is 7 bits"
.assert IRIS_END < ES_IRIS_TAB_SIZE, error, "iris table overruns its claim"
.assert 2 * IRIS_LUT_LEN = ES_R_IRIS_LUT_SIZE, error, "iris LUT size disagrees with the claim (16-bit words)"

; DP scratch (the iris_hot claim). Written before read, every frame.
IH_CX   = ES_IRIS_HOT + 0           ; window centre x, screen px
IH_CY   = ES_IRIS_HOT + 2           ; window centre y, scanline
IH_H    = ES_IRIS_HOT + 4           ; this row's half-width
IH_W    = ES_IRIS_HOT + 6           ; this row's packed [WH1][WH0] word
IH_DY   = ES_IRIS_HOT + 8           ; row - cy, biased by +IRIS_R
IH_LEFT = ES_IRIS_HOT + 10          ; rows remaining in this entry
; These two PERSIST across frames — see the claim comment in feature.toml.
; Wi_arm seeds them to $FFFF so the first tick of every scene always builds.
IH_LCX  = ES_IRIS_HOT + 12          ; centre x the table was last built for
IH_LCY  = ES_IRIS_HOT + 14          ; centre y  ''
IH_N    = ES_IRIS_HOT + 16          ; rows in the run being filled

; The "no lantern on this row" word. Little-endian, so the low byte lands in
; WH0 and the high byte in WH1: WH0 = $FF, WH1 = $00. Left > Right, which
; PixelNeedsMasking reads as an EMPTY area -> the whole row is "outside".
IRIS_ROW_OFF = $00FF

; --- wi_arm: table skeleton, window registers, HDMA shadow (scene enter) ---
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Caller ORs the ES_H_IRIS_CH bit into the HDMAEN shadow.
wi_arm:
    .a16
    .i16
    ; ---- invalidate the idle-skip cache ---------------------------------
    ; $FFFF is not a reachable centre, so the first wi_tick of this scene
    ; always rebuilds. Without this the persistent cache could hold power-on
    ; garbage that happens to match, and the lantern's first frame would show
    ; whatever random WRAM the table claim powered up with (rule 5).
    lda #$FFFF
    sta z:IH_LCX
    sta z:IH_LCY
    ; ---- the three structural bytes, written once ------------------------
    sep #$20
    .a8
    lda #(128 + IRIS_SPLIT_A)   ; 128 = the repeat bit
    sta a:ES_IRIS_TAB + 0
    lda #(128 + IRIS_SPLIT_B)
    sta a:ES_IRIS_TAB + IRIS_DATA_B - 1
    stz a:ES_IRIS_TAB + IRIS_END    ; terminator
    ; ---- window select: which targets the bounds cut ---------------------
    ; WOBJSEL bits 5-4 = the MATH window's window-1 field. 2 = active, not
    ; inverted -> the math window's AREA is inside [WH0, WH1].
    lda #$20
    sta a:$2125
    ; W12SEL bits 5-4 = BG2's window-1 field. 3 = active AND inverted -> the
    ; area BG2 is masked in is OUTSIDE [WH0, WH1], so the decor survives only
    ; inside the lantern. BG1's fields stay 0: it is dimmed, never clipped.
    lda #$30
    sta a:$2123
    ; TMW bit 1 = BG2. Without it the W12SEL field above is inert, because a
    ; layer's window count is forced to 0 when its TMW bit is clear
    ; (SnesPpu.cpp:980). The MATH window needs no TMW bit — it is read directly
    ; at :1278, which is why $2125 above stands alone.
    lda #$02
    sta a:$212E
    ; ---- colour math: subtract the fixed colour OUTSIDE the window --------
    ; CGWSEL bits 5-4 = 2 = prevent-inside -> math applies outside. Bit 1 = 0:
    ; the sub screen is the fixed colour, not a layer, so no TS.
    lda #$20
    sta a:$2130
    ; CGADSUB: bit 7 subtract, halve off, BG1 + BG2 + backdrop enabled. BG3
    ; (the caption) and OBJ (the hero) are deliberately absent — the light must
    ; not dim the thing carrying it.
    lda #$A3
    sta a:$2131
    ; COLDATA: all three plane-select bits (bit7 B, bit6 G, bit5 R = 224) plus
    ; the intensity subtracted from every unlit pixel. One write sets all three
    ; planes (SnesPpu.cpp:2214-2224 tests the bits independently).
    ;
    ; 6 and not 12: the room's floor is (9,8,7) and (13,12,10), so 12 saturates
    ; both to black and the unlit room disappears entirely. That renders as a
    ; blackout rather than as a lantern, and it also hides whether the subtract
    ; is working at all — a stuck-black screen and a correct subtract look
    ; identical. At 6 the unlit floor is (3,2,1) and (7,6,4): clearly dark,
    ; still legible, and visibly the SAME room.
    lda #(224 + 6)
    sta a:$2132
    ; ---- HDMA channel shadow (scene_mgr MVNs it to $4300 every frame) -----
    ldx #(ES_H_IRIS_CH * 16)
    lda #ES_H_IRIS_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: mode 1, direct
    lda #ES_H_IRIS_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: WH0 (mode 1 also drives WH1)
    lda #ES_IRIS_TAB_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the table's WRAM bank
    rep #$20
    .a16
    lda #ES_IRIS_TAB
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    rts

; --- wi_disarm: put the window and colour math back (scene exit) -----------
; In/out: A16/I16, DB=0, forced blank. Restores ppu_reset's boot values, so the
; next scene inherits the machine's defaults rather than this scene's lantern.
; A window left armed dims a scene that never wrote a window register, through
; registers it has no reason to look at.
wi_disarm:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$2123                     ; W12SEL:  no layer windowed
    stz a:$2125                     ; WOBJSEL: no OBJ/MATH window
    stz a:$212E                     ; TMW:     no main-screen masking
    lda #$30
    sta a:$2130                     ; CGWSEL:  prevent Always = math never
    stz a:$2131                     ; CGADSUB: all layers off
    lda #$E0
    sta a:$2132                     ; COLDATA: all planes, intensity 0
    rep #$20
    .a16
    rts

; --- wi_tick: rebuild the whole table from a centre (per frame) ------------
; In: A16/I16, DB=0. X = centre x (screen px), Y = centre y (scanline).
; Clobbers A, X, Y.
wi_tick:
    .a16
    .i16
    ; ---- idle skip: a stationary lantern needs no rebuild ----------------
    ; The table is a pure function of the centre, so if neither coordinate
    ; moved the 224 rows already in WRAM are exactly what this frame would
    ; write. Standing still used to pay full price.
    cpx z:IH_LCX
    bne @build
    cpy z:IH_LCY
    beq @done
@build:
    .a16
    .i16
    stx z:IH_LCX
    sty z:IH_LCY
    stx z:IH_CX
    sty z:IH_CY
    ; first entry: rows 0..IRIS_SPLIT_A-1
    lda #IRIS_R                     ; dy biased: row 0 -> 0 - cy + R
    sec
    sbc z:IH_CY
    sta z:IH_DY
    lda #IRIS_SPLIT_A
    sta z:IH_LEFT
    ldy #IRIS_DATA_A
    jsr wi_fill
    ; second entry: rows IRIS_SPLIT_A..223 — IH_DY already advanced to it
    lda #IRIS_SPLIT_B
    sta z:IH_LEFT
    ldy #IRIS_DATA_B
    jsr wi_fill
@done:
    .a16
    .i16
    rts

; --- wi_fill: write IH_LEFT rows of [WH0][WH1] starting at ES_IRIS_TAB+Y ---
; In: A16/I16, DB=0. Y = destination byte offset, IH_DY = the first row's
;  biased dy, IH_LEFT = row count. Advances IH_DY past the run.
; Clobbers A, X, Y.
;
; The table lives in the low-8 KB WRAM mirror, so `sta a:ES_IRIS_TAB, y` with
; DB=0 reaches it — the same addressing oam_sprites uses for its shadow.
; Destination stays in Y because STA abs,Y exists and the LUT read needs X
; (there is no long-indexed-by-Y addressing mode on this CPU). THREE RANGES,
; not one general row loop. The rows above and below the circle all take the
; SAME constant word, so they do not need the dy tracking, the range compare or
; the branch that the circle rows need — 127 of the 224 rows were paying ~42
; cycles to store a value known before the loop started.
;
; This splits the FILL, not the HDMA TABLE. Feature.toml argues at length
; against the compact-table form, and that argument still stands: variable
; ENTRY counts hit the 127-line repeat ceiling and need skip/split cases at
; exactly the screen edges. Here the table keeps its fixed 224-row shape and
; its two repeat entries, so there is no ceiling to hit — only the run lengths
; vary, each a min that degenerates safely to 0 or to the whole entry when the
; lantern is against an edge. The 224-row byte-exact oracle test still applies
; unchanged, which is what makes this safe to do.
;
; The circle run may STRADDLE the two entries; each entry clamps its own runs
; to what is left of it and IH_DY carries across, so the straddle needs no
; special case either.
wi_fill:
    .a16
    .i16
    ; ---- range 1: rows above the circle (dy < 0) -------------------------
    lda z:IH_DY
    bpl @circle                     ; dy >= 0: this entry starts at or below
    eor #$FFFF                      ; A = -dy (two's complement, dy < 0)
    inc a
    cmp z:IH_LEFT
    bcc :+
    lda z:IH_LEFT                   ; the whole entry is above the circle
:   jsr wi_run_off
@circle:
    .a16
    .i16
    ; ---- range 2: the circle's rows -------------------------------------
    lda z:IH_LEFT
    beq @out                        ; entry consumed by range 1
    lda z:IH_DY
    cmp #IRIS_LUT_LEN
    bcs @below                      ; already past the circle
    lda #IRIS_LUT_LEN
    sec
    sbc z:IH_DY
    cmp z:IH_LEFT
    bcc :+
    lda z:IH_LEFT                   ; circle runs past this entry's end
:   jsr wi_run_circle
@below:
    .a16
    .i16
    ; ---- range 3: rows below the circle --------------------------------
    lda z:IH_LEFT
    beq @out
    jsr wi_run_off
@out:
    .a16
    .i16
    rts

; --- wi_run_off: A rows of the constant "no lantern here" word ------------
; In: A16/I16, DB=0. A = row count (> 0). Y = destination byte offset. Advances
; Y by 2*A and IH_DY by A; subtracts A from IH_LEFT. Clobbers A, X, Y.
wi_run_off:
    .a16
    .i16
    jsr wi_advance                  ; consume the run in the bookkeeping
    ldx z:IH_N
    lda #IRIS_ROW_OFF               ; WH0 = $FF, WH1 = $00: empty area
@row:
    sta a:ES_IRIS_TAB, y            ; one 16-bit store writes WH0 then WH1
    iny
    iny
    dex
    bne @row
    rts

; --- wi_run_circle: A rows of the lit span, from the half-width LUT -------
; In: A16/I16, DB=0. A = row count (> 0). Y = destination byte offset.
;  Requires 0 <= IH_DY and IH_DY + A <= IRIS_LUT_LEN (wi_fill's clamps
;  establish both), so the LUT index cannot leave the blob.
; Same advance contract as wi_run_off. Clobbers A, X, Y.
wi_run_circle:
    .a16
    .i16
    jsr wi_advance
    lda z:IH_DY                     ; wi_advance moved DY past the run...
    sec
    sbc z:IH_N                      ; ...so back up to the run's first row
    asl                             ; 16-bit LUT: word index = 2 * dy
    tax
@row:
    .a16
    .i16
    ; 16-bit read, no sep/rep and no masking: gen_iris_lut.py writes the high
    ; byte as zero and asserts it, so the widened LUT lifts the whole width
    ; sandwich out of this loop.
    lda f:iris_lut_bin, x
    sta z:IH_H
    ; WH1 = min(cx + h, 255), parked in the high byte
    lda z:IH_CX
    clc
    adc z:IH_H
    cmp #256
    bcc :+
    lda #255
:   xba                             ; high byte was 0, so this is WH1 << 8
    sta z:IH_W
    ; WH0 = max(cx - h, 0)
    lda z:IH_CX
    sec
    sbc z:IH_H
    bpl :+
    lda #0
:   ora z:IH_W
    sta a:ES_IRIS_TAB, y            ; one 16-bit store writes WH0 then WH1
    inx
    inx
    iny
    iny
    dec z:IH_N
    bne @row
    rts

; --- wi_advance: shared bookkeeping for a run of A rows -------------------
; In: A16/I16. A = row count. Stores it in IH_N, adds it to IH_DY and subtracts
; it from IH_LEFT. Y is untouched (each run advances its own). Clobbers A.
wi_advance:
    .a16
    .i16
    sta z:IH_N
    clc
    adc z:IH_DY
    sta z:IH_DY
    lda z:IH_LEFT
    sec
    sbc z:IH_N
    sta z:IH_LEFT
    rts
