; =============================================================================
; m7f_floor.asm — the overworld plane, its palette, and the sky above it
; =============================================================================
; Two jobs, both settled at scene enter: upload the 32 KB interleaved Mode 7
; image (one DMA), and arm the one-channel TM split that turns BG1 OFF above
; the horizon so the BACKDROP shows through as sky.
;
; The blob labels (`m7f_ground_bin`, `m7f_pal_bin`) are the game's `.incbin`
; claim sites in main.asm — the feature names them, the game backs them, and
; `make rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the m7f_up
; dma_init claim names — a declared resource, not a hard-coded 0.
M7F_FLOOR_REGS = $4300 + ES_D_M7F_UP_CH * 16

; The sky table lives inside its own 5-byte wram claim.
M7F_SKY_TBL      = ES_M7F_SKY_TBL
M7F_SKY_TBL_LONG = ES_M7F_SKY_TBL_LONG

; --- the sky ramp + horizon fog: the shape tools/gen_m7f_gradient.py bakes ---
; These four numbers ARE that generator's, and the two sides are held together
; from both ends: the .assert below refuses a layout that outgrew the claim,
; and tests/test_mode7_flight.py drives the generator itself as the oracle for
; the rendered pixels, so a drift in either shows as a wrong colour rather than
; as a silent re-spelling.
M7F_GRAD_RAMP   = 40                            ; sky ramp lines, above the horizon
M7F_GRAD_FOG    = 15                            ; fog fade lines, below it
M7F_GRAD_STRIDE = M7F_GRAD_RAMP + M7F_GRAD_FOG  ; one snapshot, one plane
M7F_GRAD_SNAP0  = 1                             ; past the shared plane|0 byte
M7F_GRAD_PLANE  = 224                           ; grad_tabs is 3 x this
M7F_GRAD_SNAPS  = 4                             ; day/night snapshots
M7F_GRAD_DAY    = 1                             ; ...and the one the rail boots on
.assert M7F_GRAD_SNAP0 + M7F_GRAD_SNAPS * M7F_GRAD_STRIDE <= M7F_GRAD_PLANE, error, "m7f gradient snapshots outgrew rgb_gradient's grad_tabs plane region"
.assert 3 * M7F_GRAD_PLANE = ES_R_GRAD_TABS_SIZE, error, "m7f gradient plane stride disagrees with the grad_tabs claim"

; The HDMA count byte's repeat bit: set = a NEW unit every scanline, clear =
; transfer once and hold. Written as the bit rather than as $80 for the reason
; the TM values below are written as shifts.
M7F_HDMA_REP = 1 << 7

; --- the cursor: three 10-byte header tables + the live snapshot's offset ----
M7F_FOG       = ES_M7F_FOG
M7F_FOG_LONG  = ES_M7F_FOG_LONG
M7F_FOG_ENT   = 10                              ; one plane's header table
M7F_FOGE_HOLD_N = 0                             ; count: line 0 -> the ramp
M7F_FOGE_HOLD_P = 1                             ; ptr:   the plane's zenith byte
M7F_FOGE_RAMP_N = 3
M7F_FOGE_RAMP_P = 4
M7F_FOGE_FOG_N  = 6
M7F_FOGE_FOG_P  = 7
M7F_FOGE_END    = 9                             ; the terminator
; The cursor is a WRAM claim, not a DP one, so every touch below is long — `z:`
; would be a forced-DP mode the assembler refuses outright, which is the loud
; version of the failure and the reason nothing here is guessed.
M7F_GRAD_OFS  = ES_M7F_FOG_LONG + 3 * M7F_FOG_ENT   ; the snapshot's byte offset
.assert 3 * M7F_FOG_ENT + 2 <= ES_M7F_FOG_SIZE, error, "the fog cursor outgrew its wram claim"

; --- the day/night clock, and the table it indexes ---------------
; These are tools/gen_m7f_gradient.py's numbers, and the .asserts below refuse
; a table that disagrees with them in either direction.
M7F_CLOCK       = ES_M7F_CLOCK_LONG
M7F_TODROW      = ES_M7F_CLOCK_LONG + 2         ; the palette row last written
M7F_TOD_ROW     = 2                             ; the snapshot's byte offset
M7F_TODPAL_FLOOR = 16                           ; CGRAM 0..15, one run
M7F_TODPAL_CLOUD = 16                           ; ...then OBJ palette 2, whole
M7F_TODPAL_ROW  = 2 * (M7F_TODPAL_FLOOR + M7F_TODPAL_CLOUD)
M7F_TOD_STEPS   = 64                            ; rows in the table
M7F_TOD_SEG_STEPS = M7F_TOD_STEPS / M7F_GRAD_SNAPS      ; ...16 per segment
M7F_TOD_SHIFT   = 10                            ; step = phase >> 10
M7F_TOD_STEP    = 1 << M7F_TOD_SHIFT            ; phase units per step
M7F_TOD_RATE    = 32                            ; phase units per armed VBlank
M7F_TOD_LONG    = (ES_R_M7F_TOD_BANK << 16) | ES_R_M7F_TOD_ADDR
M7F_TODPAL_LONG = (ES_R_M7F_TODPAL_BANK << 16) | ES_R_M7F_TODPAL_ADDR
.assert M7F_TOD_STEPS * M7F_TOD_ROW = ES_R_M7F_TOD_SIZE, error, "the day/night table disagrees with the m7f_tod claim"
.assert M7F_TOD_STEPS * M7F_TODPAL_ROW = ES_R_M7F_TODPAL_SIZE, error, "the day/night palette table disagrees with the m7f_todpal claim"
; THE ROW STRIDE MUST BE A POWER OF TWO. `tod_commit` reaches its row with a
; shift and a mask, and that is a division by the stride only on a bit
; boundary. The first build with a 20-word row (40 bytes) silently served a
; NEIGHBOURING row's colours — a plausible sunset belonging to no snapshot.
.assert (M7F_TODPAL_ROW & (M7F_TODPAL_ROW - 1)) = 0, error, "the day/night palette row is not a power of two, so tod_commit's masked index is not a division"
.assert M7F_TOD_STEPS * M7F_TOD_STEP = $10000, error, "the day/night phase does not cover exactly one cycle"
.assert M7F_TOD_SHIFT = 10, error, "tod_commit reaches its rows by shifting the phase, which assumes step = phase >> 10"

; TM bit assignments. Written as SHIFTS rather than as $10/$11: `no_literals`
; cannot tell a bare $11 from a hand-narrated address, and the shift says which
; hardware bit is meant, which the hex does not.
M7F_TM_BG1 = 1 << 0
M7F_TM_OBJ = 1 << 4

; --- floor_arm: the whole plane + the sky split (scene enter) ---------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones, and
; tools/gen_m7f_assets.py emits the blob already in that layout. DMA mode 1
; writes B, B+1, B, B+1 ... — with BBAD = VMDATAL that is $2118, $2119, $2118,
; $2119, exactly the interleave. So the whole plane is one transfer of 32,768
; bytes with no unpacking pass.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is
; written, by one word. With the default $00 it would advance after the LOW
; byte and every high byte would overwrite the wrong word.
;
; DAS is single-shot (consumed by the transfer), so it is armed HERE, for THIS
; transfer. There is one transfer and therefore one arming site; the rule bites
; when a loop fires several and only the first moves bytes.
floor_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^m7f_ground_bin
    sta a:M7F_FLOOR_REGS + 4        ; A1B = source bank
    lda #ES_D_M7F_UP_DMAP
    sta a:M7F_FLOOR_REGS + 0        ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_M7F_UP_BBAD
    sta a:M7F_FLOOR_REGS + 1        ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(m7f_ground_bin)
    stx a:M7F_FLOOR_REGS + 2        ; A1T
    ldy #ES_R_M7F_GROUND_SIZE
    sty a:M7F_FLOOR_REGS + 5        ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_M7F_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: sixteen absolute CGRAM indices, CPU-written ----------
    ; Sixteen words is thirty-two stores; a DMA would cost more to set up than
    ; to run. CGADD auto-increments, so this build takes low byte then high
    ; byte per word and walks itself.
    ;
    ; WORD 0 IS THE SKY. In Mode 7 an 8bpp pixel value IS an absolute CGRAM
    ; index, so index 0 is both a palette entry and the backdrop the split
    ; below reveals; the generator asserts no floor CHR byte is 0, so nothing
    ; can punch a sky-coloured hole in the ground.
    sep #$20
    .a8
    lda #ES_C_M7F_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:m7f_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7F_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: screen-over WRAP. The map is 128x128 tiles and the PPU samples
    ; it modulo 128, so the world tiles infinitely at 1024 px — the property
    ; that lets free flight never reach a black edge. M7f_cam derives the same
    ; 1024 from the map claim's own size, so the picture and the position wrap
    ; agree without either being told about the other.
    ;
    ; (BGMODE is the scene's `scene_writes`, TM is the scene's SEED; see this
    ; feature's feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16

    jsr sky_arm
    jsr fog_arm
    jsr tod_arm
    rts

; --- tod_arm: start the day/night clock at the boot snapshot ----------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A.
;
; The phase that PUTS the clock on the boot snapshot rather than zero, so the
; first frame's sky is the one CGRAM[0] was baked as (the `day` zenith) and the
; two generators' agreement is true at frame 1 as well as on average. Zero
; would start the cycle at dawn against a day-coloured backdrop for the eight
; frames before the first step lands — a rule-5-shaped inconsistency, visible
; as a one-off flash.
tod_arm:
    .a16
    .i16
    lda #(M7F_GRAD_DAY * M7F_TOD_SEG_STEPS * M7F_TOD_STEP)
    sta f:M7F_CLOCK
    ; The gate's "last row written" starts one PAST the last real row, so the
    ; first VBlank always writes the palette. Rule 5, and the
    ; uninitialised-read detector is what named it: `tod_commit` COMPARES this
    ; word before anything writes it, and power-on WRAM is random — one boot in
    ; 2,048 would match the live row and skip the first palette upload. A
    ; derived sentinel rather than $FFFF so it cannot collide with a row if the
    ; table ever grows.
    lda #(M7F_TOD_STEPS * M7F_TODPAL_ROW)
    sta f:M7F_TODROW
    rts

; --- fog_arm: hand the three COLDATA channels THIS rail's cursor ------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X.
;
; ORDERING CONTRACT, and it is the one way this can silently fail: `rg_arm`
; writes the same two shadow fields (A1T, A1B) with its own static tables, so
; it MUST run first. The scene's enter calls `rg_arm` immediately before
; `floor_arm`, and the comment there says why. Armed the other way round the
; channels stream rgb_gradient's fixed-seam table, the picture still shows a
; sky ramp, and only the fog's position gives it away — which is why the test
; that covers this reads the rendered fog rows against the LIVE horizon rather
; than checking that a gradient exists.
;
; DASB is NOT rewritten: the data these tables point into IS `grad_tabs`, so
; `rg_arm`'s `ES_R_GRAD_TABS_BANK` is already the right bank. Only the cursor
; moves, which is the whole claim in m7f_floor/feature.toml.
;
; WIDTH-RISK: A16 in, A16 out. The macro narrows to A8 for the single A1B byte
; and widens again, touching `#$20` only, so I-width tracking passes through
; and the three expansions cannot leak a width into each other.
.macro M7F_FOG_BIND ch, ent
    ldx #(ch * M7F_SHDW_CH)
    lda #(M7F_FOG + ent)
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T -> this plane's header table
    sep #$20
    .a8
    lda #ES_M7F_FOG_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B -> the WRAM bank that table lives in
    rep #$20
    .a16
.endmacro

fog_arm:
    .a16
    .i16
    lda #(M7F_GRAD_DAY * M7F_GRAD_STRIDE)
    sta f:M7F_GRAD_OFS              ; the snapshot the rail boots on
    M7F_FOG_BIND ES_H_COLR_CH, 0 * M7F_FOG_ENT
    M7F_FOG_BIND ES_H_COLG_CH, 1 * M7F_FOG_ENT
    M7F_FOG_BIND ES_H_COLB_CH, 2 * M7F_FOG_ENT
    sep #$20
    .a8
    jsr fog_reanchor                ; every header byte written before arming
    rep #$20
    .a16
    rts

; --- sky_arm: the two-band TM split, on one HDMA channel --------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X.
;
; Mode 0 is one-register-one-byte, so each entry carries a single TM value:
;
;  [64, OBJ][1, BG1|OBJ][$00]
;
; Both counts are NON-repeat, which is the opposite reading of the same byte:
; 64 means "transfer the unit once, then idle 63 lines", and 1 means "transfer
; once" — after which the terminator ends the channel and TM simply HOLDS the
; floor value to the bottom of the frame. So lines 0..63 render the backdrop
; (BG1 off) with sprites over it, and lines 64..223 render the Mode 7 floor.
;
; THE COUNT IS `m7f_cam`'s LIVE M7F_HORIZON, not a constant: under the moving
; horizon the band's first scanline is f(altitude), and the sky ends
; exactly where the composed band begins. Taking the number from one place is
; what makes that true rather than coincidental — a second constant here would
; drift from the band by two scanlines per altitude quantum and show as a strip
; of backdrop above the floor, or a strip of floor above the sky.
sky_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda z:M7F_HORIZON
    sta f:M7F_SKY_TBL_LONG + 0      ; lines 0..horizon-1, non-repeat
    lda #M7F_TM_OBJ
    sta f:M7F_SKY_TBL_LONG + 1      ; BG1 off: the backdrop IS the sky
    lda #1
    sta f:M7F_SKY_TBL_LONG + 2      ; one line, non-repeat...
    lda #(M7F_TM_BG1 | M7F_TM_OBJ)
    sta f:M7F_SKY_TBL_LONG + 3      ; ...then TM holds the floor to the bottom
    lda #0
    sta f:M7F_SKY_TBL_LONG + 4      ; terminator

    ; ---- the channel, in the scene_mgr shadow the NMI MVNs to $4300 --------
    rep #$10
    .i16
    ldx #(ES_H_M7F_SKY_CH * M7F_SHDW_CH)
    lda #ES_H_M7F_SKY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: direct, 1 reg 1 byte
    lda #ES_H_M7F_SKY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: TM
    lda #ES_M7F_SKY_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B
    rep #$20
    .a16
    lda #M7F_SKY_TBL
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    rts

; --- sky_reanchor: re-point the split at the live horizon, IN VBLANK --------
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A.
;
; IN VBLANK, and that is the whole tear argument. The sky table is SINGLE
; buffered (five bytes), and HDMA reads its count byte at the top of the frame;
; rewriting it during active display would move the split under a channel
; part-way through it. The matrix tables solve the same problem by writing only
; the back buffer and riding the atomic swap — five bytes do not justify a
; second buffer, so this one takes the other route and writes where no channel
; is reading.
;
; Unconditional: comparing against the last value would cost more than the
; single store it guards.
; --- tod_commit: advance the day/night clock, IN VBLANK --------------------
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A, X.
;
; IN VBLANK for a hardware reason of its own, not just the sky table's: this
; writes CGRAM, and the CGRAM port is only safely writable during VBlank or
; forced blank (rule 4). It is also why the interpolation is a TABLE — the
; multiplier belongs to m7f_cam.
;
; RUNS BEFORE `sky_reanchor`, because the snapshot offset it publishes is what
; `fog_reanchor` reads two calls later; main.asm's hook orders them and says
; so. A frame in the other order shows the previous step's ramp against this
; step's zenith, which is one frame of a colour that belongs to neither.
;
; The row index is `(phase >> 8) & $00FC` rather than `(phase >> 10) * 4`: the
; two are the same number, the first spells the row stride into the mask
; instead of paying a multiply for it, and >> 8 is one `xba`.
; (the `.assert` for that assumption sits with the other table asserts above)
tod_commit:
    .a8
    .i16
    rep #$20
    .a16
    lda f:M7F_CLOCK
    clc
    adc #M7F_TOD_RATE
    sta f:M7F_CLOCK             ; 16-bit: wraps through the cycle by itself
    ; ---- has the STEP changed? ----------------------------------------------
    ; The rows below are 34 bytes of port writes and they only ever differ
    ; between steps, which are 32 frames apart — so 31 frames in 32 this
    ; routine is a compare and a branch. VBlank is the scarcest window on the
    ; rail and the gate costs one word of the claim.
    lsr a
    lsr a
    lsr a
    lsr a                       ; phase >> 4: the palette row, x64
    and #((M7F_TOD_STEPS - 1) * M7F_TODPAL_ROW)
    cmp f:M7F_TODROW
    beq @done
    sta f:M7F_TODROW
    tax
    ; ---- the sixteen CGRAM words: the sky's zenith, then the floor ----------
    ; ONE run of this build. CGADD auto-increments through the whole palette,
    ; so word 0 and words 1..15 are the same loop and the claim's base is
    ; written once. CGRAM is only safely writable here (rule 4) — which is the
    ; reason this routine is in the hook at all.
    sep #$20
    .a8
    lda #ES_C_M7F_PAL           ; the m7f_pal claim's base
    sta a:$2121                 ; CGADD
    ldy #0
@pal:
    .a8
    .i16
    lda f:M7F_TODPAL_LONG, x
    sta a:$2122
    inx
    iny
    cpy #(2 * M7F_TODPAL_FLOOR)
    bcc @pal
    ; ---- the clouds' four words: a SECOND run, at OBJ palette 2's base -----
    ; CGADD auto-increments, and CGRAM 16..159 belongs to other claims, so the
    ; port is re-seated rather than walked across them. The rows are laid out
    ; floor-then-cloud so this is one continuous read of ROM either way.
    lda #ES_C_CLOUD_PAL
    sta a:$2121
@cpal:
    .a8
    .i16
    lda f:M7F_TODPAL_LONG, x
    sta a:$2122
    inx
    iny
    cpy #M7F_TODPAL_ROW
    bcc @cpal
    ; ---- the snapshot's ramp: what fog_reanchor will point the cursor at ----
    rep #$20
    .a16
    lda f:M7F_TODROW
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                       ; the 64-byte palette row -> the 2-byte tod row
    tax
    lda f:M7F_TOD_LONG, x
    sta f:M7F_GRAD_OFS
@done:
    .a16
    .i16
    sep #$20
    .a8
    rts

sky_reanchor:
    .a8
    .i16
    lda z:M7F_HORIZON
    sta f:M7F_SKY_TBL_LONG + 0
    ; FALLS THROUGH, deliberately. The split and the fog are two readings of
    ; ONE number, and a build where they can disagree is the tear this piece
    ; exists to prevent — so they are re-anchored by the same call, from the
    ; same M7F_HORIZON, in the same VBlank.

; --- fog_reanchor: the three COLDATA header tables, at the live horizon -----
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A, X, Y.
;
; IN VBLANK, for the sky table's reason and one more. HDMA latches each
; channel's A1T at the top of the frame and walks the header table as the
; picture draws, so a table rewritten during active display moves the fog under
; a channel part-way down it. Thirty bytes do not justify a second buffer, so
; this takes the same route the five-byte split does and writes where no
; channel is reading.
;
; UNCONDITIONAL, rather than gated on the altitude's owed-countdown. The gate
; would save about 90 cycles of VBlank on a level frame and would add a second
; place where the fog's anchor and the band's can disagree; the countdown
; exists because the BAND TABLE is double buffered, and this table is not.
fog_reanchor:
    .a8
    .i16
    ldx #0                          ; the header byte offset: 0, 10, 20
    ldy #0                          ; ...and the plane's data base: 0, 224, 448
@plane:
    .a8
    .i16
    ; ---- the three count bytes and the terminator --------------------------
    lda z:M7F_HORIZON
    sec
    sbc #M7F_GRAD_RAMP
    sta f:M7F_FOG_LONG + M7F_FOGE_HOLD_N, x     ; hold the zenith to the ramp
    lda #(M7F_HDMA_REP | M7F_GRAD_RAMP)
    sta f:M7F_FOG_LONG + M7F_FOGE_RAMP_N, x     ; a new byte per sky line
    lda #(M7F_HDMA_REP | M7F_GRAD_FOG)
    sta f:M7F_FOG_LONG + M7F_FOGE_FOG_N, x      ; ...and per fog line
    lda #0
    sta f:M7F_FOG_LONG + M7F_FOGE_END, x        ; terminator: the fade ends on 0
    ; ---- the three data pointers, all inside grad_tabs ---------------------
    rep #$20
    .a16
    tya
    clc
    adc #ES_R_GRAD_TABS_ADDR
    sta f:M7F_FOG_LONG + M7F_FOGE_HOLD_P, x     ; -> this plane's zenith byte
    clc
    adc #M7F_GRAD_SNAP0
    clc
    adc f:M7F_GRAD_OFS
    sta f:M7F_FOG_LONG + M7F_FOGE_RAMP_P, x     ; -> the snapshot's sky ramp
    clc
    adc #M7F_GRAD_RAMP
    sta f:M7F_FOG_LONG + M7F_FOGE_FOG_P, x      ; -> ...and its fog fade
    ; ---- next plane --------------------------------------------------------
    tya
    clc
    adc #M7F_GRAD_PLANE
    tay
    txa
    clc
    adc #M7F_FOG_ENT
    tax
    sep #$20
    .a8
    cpx #(3 * M7F_FOG_ENT)
    bcs :+
    jmp @plane
:   .a8
    .i16
    rts
