; =============================================================================
; mil_obj.asm — the rider, occluded by the car he is inside
; =============================================================================
; THE OCCLUSION IS THE PRIORITY ORDER AND NOTHING ELSE. Mode 4 renders
; BG2lo(1) OBJ0(2) BG1lo(3) OBJ1(4) BG2hi(5) OBJ2(6) BG1hi(7) OBJ3(8), and a
; sprite is drawn only where the pixel already there scores LOWER:
; `(_mainScreenFlags[x] & 0x0F) < spritePrio` (SnesPpu.cpp:958). At OBJ
; priority 0 the rider scores 2 — under BG1's 3, over BG2's 1 — so the car's
; opaque shell hides him and the hole cut where its glass is shows him. The
; occlusion rides up the shaft with the car because it IS the car.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (mil_obsel), at scene enter.

MIL_OBJ_REGS = $4300 + ES_D_MIL_OBJ_UP_CH * 16
; THE ORDER INSIDE THE CLAIM IS A MECHANISM, NOT A LAYOUT. The leaves and the
; player are BOTH priority 1 in the lobby, and mode 4 gives them the same
; score — so what separates them is OAM index. Mesen writes a sprite's pixels
; with an unconditional overwrite (SnesPpu.cpp:772-776) and fetches from the
; last sprite found on the line BACKWARDS (:660), so the LOWEST index is
; written last and wins. The leaves therefore come first and the player last,
; and that one fact is what makes both lift transitions need no special case:
; the doors close OVER him as he boards, and they part to REVEAL him when he
; arrives, because he is simply behind them the whole time.
MIL_LEAF_FIRST  = ES_O_MIL_RIDER
MIL_LEAF_CELLS  = SMIL_DOOR_BAYS * 2 * SMIL_LEAF_ROWS
MIL_RIDER_INDEX = ES_O_MIL_RIDER + MIL_LEAF_CELLS
MIL_RIDER_OAM = ES_OAM_SHADOW + MIL_RIDER_INDEX * 4
.assert MIL_RIDER_INDEX < ES_O_MIL_RIDER + ES_O_MIL_RIDER_SPRITES, error, "mil_obj: the claim does not cover the rider behind the leaves"
MIL_RIDER_HI  = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32 + (MIL_RIDER_INDEX / 4)
MIL_HI_FIRST  = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32 + (ES_O_MIL_RIDER / 4)
MIL_HI_BYTES  = ES_O_MIL_RIDER_SPRITES / 4     ; the claim, in hi-table bytes
.assert ES_O_MIL_RIDER_SPRITES .MOD 4 = 0, error, "mil_obj: the claim must end on a hi-table byte"

; Every sprite this feature owns is 32x32 — the rider and every leaf cell — so
; every 2-bit field it writes is `size, no X9`: bit1 set, bit0 clear, four to a
; byte. X9 is clear BY THE GEOMETRY and not by hope, and these asserts are what
; say so: X9 is a sprite's LEFT edge crossing 256, so what has to stay below it
; is the walk clamp and the right-hand bay's far leaf at full travel. The
; second pair is a different claim — that an OPEN bay is wholly on screen — and
; it is separate because a leaf half off the right edge needs no X9 bit and is
; still a composition defect.
MIL_HI_ALL_LARGE = $AA
.assert SMIL_WALK_MAX < 256, error, "mil_obj: the walk clamp lets the player past X9"
.assert SMIL_DOOR_B * 8 + SMIL_LEAF_BOX + SMIL_DOOR_TRAVEL < 256, error, "mil_obj: the far leaf's origin reaches past X9"
.assert SMIL_WALK_MAX + SMIL_RIDER_BOX <= 256, error, "mil_obj: the player walks off the right edge"
.assert SMIL_DOOR_B * 8 + SMIL_LEAF_BOX + SMIL_DOOR_TRAVEL + SMIL_LEAF_BOX <= 256, error, "mil_obj: an open right-hand bay clips the right edge"

; THE SIZE BIT LIVES IN THE HI TABLE, four sprites to a byte, so an entry that
; does not start one would need a read-modify-write against three neighbours
; this feature does not own.
.assert ES_O_MIL_RIDER .MOD 4 = 0, error, "mil_obj: the rider must start a hi-table byte"

; OBSEL: bits 0-2 the OBJ name base in 8K-WORD steps, bits 5-7 the size pair.
; Pair 3 is small 16x16 / large 32x32, and the rider is large.
MIL_OBSEL_PAIR3 = 3 << 5

; The size bit in the hi table: bit0 of a sprite's 2-bit field is X9, bit1 is
; SIZE (Mesen2 SnesPpu.cpp:679 decodes it exactly this way). Pair 3 makes
; `large` 32x32, so one OAM entry draws the whole rider.
MIL_RIDER_SIZE_LARGE = 1 << 1

; OAM attr byte: PRIORITY 0 and OBJ palette 0. Priority 0 is not a default here
; and not a small choice — it is the entire occlusion mechanism. Mode 4 scores
; it 2, BG1's normal tiles 3, and a sprite draws only where what is already
; there scores lower, so the car's shell hides the rider and its glass does not.
; smt_obj's knight uses priority 3 for the opposite reason: he has to be in
; front of everything.
MIL_RIDER_ATTR = (0 << 4)

; ...and the base has to BE expressible in that 8K-word field. That is a
; property of where the allocator put the claim, so it is asserted against the
; emitted symbol rather than assumed — the alternative is an OBJ page silently
; read from somewhere else.
.assert ES_V_MIL_OBJ_CHR = (ES_V_MIL_OBJ_CHR_OBSEL_BASE << 13), error, "mil_obj: the rider's CHR base is not expressible in OBSEL's 8K-word field"

; --- mil_obj_arm: CHR, palette, OBSEL (scene enter) ------------------------
; CONTRACT mil_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the rider's CHR in its OBJ page, OBJ palette 0 written, OBSEL set
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
mil_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MIL_OBJ_CHR
    sta a:$2116
    ldx #.loword(mil_obj_bin)
    sty a:MIL_OBJ_REGS + 5          ; (DAS re-armed below; Y is set first so
    ldy #ES_R_MIL_OBJ_SIZE          ;  the store order reads with the claim)
    stx a:MIL_OBJ_REGS + 2
    sty a:MIL_OBJ_REGS + 5          ; DAS — armed for THIS transfer
    sep #$20
    .a8
    lda #^mil_obj_bin
    sta a:MIL_OBJ_REGS + 4
    lda #ES_D_MIL_OBJ_UP_DMAP
    sta a:MIL_OBJ_REGS + 0
    lda #ES_D_MIL_OBJ_UP_BBAD
    sta a:MIL_OBJ_REGS + 1
    lda #(1 << ES_D_MIL_OBJ_UP_CH)
    sta a:$420B
    ; ---- OBJ palette 0, at the claim's own base ---------------------------
    lda #ES_C_MIL_OBJ_PAL
    sta a:$2121                     ; CGADD = 128
    rep #$20
    .a16
    ldx #0
@pal:
    .a16
    .i16
    lda f:mil_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MIL_OBJ_PAL_SIZE
    bcc @pal
    ; ---- OBSEL: the 32x32 size pair, and the claim's own base -------------
    sep #$20
    .a8
    lda #(MIL_OBSEL_PAIR3 | ES_V_MIL_OBJ_CHR_OBSEL_BASE)
    sta a:$2101
    rep #$20
    .a16
    rts

; --- mil_rider_stage: put the rider where the car's glass is ---------------
; CONTRACT mil_rider_stage
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MIL_CAR — the car's displacement up the shaft, in pixels
;             ES_MIL_CAM — the camera, because the car's column carries it
;             ES_MIL_PHASE — which idle cell
;   out:      the rider's shadow-OAM entry written, or PARKED when the glass is
;             off screen, and ES_MIL_RIDER_Y published with the row he was
;             staged at (or SMIL_PARK_Y when parked)
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread; writes the OAM SHADOW, which oam_nmi_dma commits
;   tail:     rts
;
; THE CAR'S SCREEN ROW IS DERIVED, NOT TRACKED. The PPU puts map row R of a
; displaced column at screen row R*8 - word, and the car's word is
; camera + displacement — so the glass is at
;     SMIL_CAR_ROW*8 - (cam + car) + SMIL_WIN_Y
; and there is no second copy of the car's position to drift from the first.
; That is the same join `smt_cam_shown` exists for, made structural instead.
;
; WIDTH-RISK: A16 throughout; the OAM byte writes narrow explicitly. The Y
; comparison is SIGNED — the car climbs off the top of the screen and its glass
; row goes negative, which an unsigned test reads as far below the picture and
; leaves the rider drawn across the bottom of it.
mil_rider_stage:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_rider_stage"
    lda #(SMIL_CAR_ROW * 8 + SMIL_WIN_Y)
    sec
    sbc z:ES_MIL_CAM
    sec
    sbc z:ES_MIL_CAR                ; ...the glass's screen row
    sta z:ES_MIL_RIDER_Y
    ; ---- off the top or off the bottom: park -----------------------------
    ; ONE UNSIGNED COMPARE FOR BOTH ENDS, after biasing by the sprite box. The
    ; car climbs off the TOP, so the glass row goes negative — and a negative
    ; row plus the box either lands inside the band (still partly on screen,
    ; draw it) or wraps enormous (gone, park it). A signed pair of tests would
    ; need negative immediates, which is a hex mask, which is a raw address
    ; operand the moment it is written down.
    clc
    adc #SMIL_RIDER_BOX
    bmi @park                       ; STILL negative after the bias: the car is
                                    ;   fully above the picture. Tested as a
                                    ;   SIGN and not as a magnitude, because a
                                    ;   16-bit add wraps SMALL — glass row -20
                                    ;   biased by 32 is 12, not 65548 — so a
                                    ;   `cmp` alone reads far-above-the-screen
                                    ;   as just-below-the-top
    cmp #SMIL_RIDER_VIS_SPAN
    bcs @park
    ; ---- his X: the car's column, plus the glass, centred on the box -----
    lda #(SMIL_CAR_COL * 8 + SMIL_WIN_X + SMIL_WIN_W / 2 - SMIL_RIDER_BOX / 2 + SMIL_RIDER_DX)
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 0         ; X, low 8
    lda z:ES_MIL_RIDER_Y
    sec
    sbc #SMIL_RIDER_RAISE           ; ...the art's own offset inside the glass.
                                    ;   A SUBTRACTION, because the offset is
                                    ;   upward and a negative immediate is a
                                    ;   hex mask the no-literals gate refuses
    sta a:MIL_RIDER_OAM + 1         ; Y
    rep #$20
    .a16
    ; ---- which idle cell, from the PHASE and not from a frame count ------
    lda z:ES_MIL_PHASE
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #(SMIL_RIDER_FRAMES - 1)
    .repeat 2
    asl a                           ; ...one 32x32 cell is 4 tiles across
    .endrepeat
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 2         ; tile, low 8
    lda #MIL_RIDER_ATTR             ; PRIORITY 0 — the whole point: it scores 2
    sta a:MIL_RIDER_OAM + 3         ;   and loses to BG1's 3 (SnesPpu.cpp:958)
    lda #MIL_RIDER_SIZE_LARGE       ; ...and the size bit for a 32x32 sprite
    sta a:MIL_RIDER_HI              ; whole byte: the three parked neighbours'
                                    ;   fields are zero and stay zero
    rep #$20
    .a16
    rts
@park:
    .a16
    .i16
    lda #SMIL_PARK_Y
    sta z:ES_MIL_RIDER_Y
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 1         ; Y off the bottom: the documented park
    rep #$20
    .a16
    rts

; =============================================================================
; THE LOBBY SIDE — the same sheet, the same OAM, a different room
; =============================================================================
MIL_LEAF_OAM = ES_OAM_SHADOW + MIL_LEAF_FIRST * 4
MIL_HFLIP    = 1 << 6
MIL_LEAF_ATTR = (1 << 4) | (1 << 1)     ; PRIORITY 1 and OBJ PALETTE 1.
                                        ; Priority 1 scores 4 in mode 4, over
                                        ; BG1's normal 3, so the leaves close
                                        ; IN FRONT of the bay drawn behind
                                        ; them. The rider's priority 0 is the
                                        ; opposite choice for the opposite
                                        ; reason.

; ...AND THE PLAYER IS PRIORITY 1 IN THIS ROOM, which is not a second opinion
; about the same sprite — it is the same rule reaching the opposite answer
; because the layer behind him is a different thing. In the hall he is inside
; a car whose BG1 shell MUST cover him everywhere but the glass, so he scores
; 2 and loses to BG1's 3. In the lobby the thing behind him is a painted wall
; that must not cover him anywhere, so he scores 4 and wins. Staging him here
; with MIL_RIDER_ATTR draws him correctly and puts him behind the masonry,
; which is a sprite that is present in OAM, correct in every field, and
; invisible on screen.
MIL_LOBBY_ATTR = (1 << 4)               ; priority 1, OBJ palette 0 (the rider)

; --- mil_lobby_walk: one frame of the player on the lobby floor -------------
; CONTRACT mil_lobby_walk
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_INP_CUR — left/right/up; ES_MIL_BOARD, ES_MIL_BAY
;   out:      ES_MIL_PX advanced and clamped, ES_MIL_FACE and ES_MIL_STEP
;             updated; ES_MIL_BOARD advanced when he commits to a bay or
;             reaches its centre
;   clobbers: A, X, N, Z, C
;   assumes:  the main thread
;   tail:     rts
;
; TICK: ok -- ES_MIL_STEP accumulates PIXELS WALKED and the walk cell is
;   indexed by it, so the legs move with the ground. Nothing counts frames.
;
; HE ONLY HAS THE CONTROLS WHILE HE IS FREE. Walking into a bay and stepping
; out of one are the same walk under different ownership, which is why they are
; the same routine and not a second one — the destination is a number either
; way, and the only difference is who supplies it.
mil_lobby_walk:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_lobby_walk"
    lda z:ES_MIL_BOARD
    beq @free
    cmp #SMIL_BOARD_IN
    beq @walk_in
    rts                             ; aboard, or alighting: the doors have him
; ---- he is walking into the bay he called -----------------------------------
@walk_in:
    .a16
    .i16
    ldx z:ES_MIL_BAY
    lda f:mil_bay_x, x
    clc
    adc #SMIL_BOARD_DEST            ; ...the px that centres him in the opening
    cmp z:ES_MIL_PX
    beq @arrived
    bcc @in_left                    ; the bay is to his LEFT
    lda z:ES_MIL_PX                 ; ...to his right
    clc
    adc #SMIL_WALK_STEP
    stz z:ES_MIL_FACE
    bra @in_store
@in_left:
    .a16
    .i16
    lda z:ES_MIL_PX
    sec
    sbc #SMIL_WALK_STEP
    ldx #MIL_HFLIP
    stx z:ES_MIL_FACE
@in_store:
    .a16
    .i16
    sta z:ES_MIL_PX
    bra @stepped
@arrived:
    .a16
    .i16
    lda #SMIL_BOARD_ABOARD          ; centred: the doors close over him
    sta z:ES_MIL_BOARD
    rts
; ---- free: he has the controls ---------------------------------------------
@free:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @not_up
    jsr mil_try_board               ; UP at a bay that stands open boards it
@not_up:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @not_right
    lda z:ES_MIL_PX
    cmp #SMIL_WALK_MAX
    bcs @done
    clc
    adc #SMIL_WALK_STEP
    sta z:ES_MIL_PX
    stz z:ES_MIL_FACE
    bra @stepped
@not_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @done
    lda z:ES_MIL_PX
    cmp #(SMIL_WALK_MIN + SMIL_WALK_STEP)
    bcc @done
    sec
    sbc #SMIL_WALK_STEP
    sta z:ES_MIL_PX
    lda #MIL_HFLIP
    sta z:ES_MIL_FACE
@stepped:
    .a16
    .i16
    lda z:ES_MIL_STEP
    clc
    adc #SMIL_WALK_STEP
    sta z:ES_MIL_STEP
@done:
    .a16
    .i16
    rts

; --- mil_try_board: UP at an OPEN bay commits him to the ride ---------------
; CONTRACT mil_try_board
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      ES_MIL_BAY and ES_MIL_BOARD set if a bay stands fully open and
;             he is in reach of it; untouched otherwise
;   clobbers: A, X, N, Z, C
;   assumes:  the main thread, ES_MIL_BOARD = SMIL_BOARD_FREE
;   tail:     rts
;
; FULLY OPEN, not merely opening. The proximity rule already opened the bay he
; is standing at, so the travel reaching DOOR_TRAVEL is the door's own way of
; saying it is ready — and testing it means a press during the slide waits for
; the leaves instead of walking him through them.
mil_try_board:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_try_board"
    ldx #0
@bay:
    .a16
    .i16
    lda z:ES_MIL_DOOR, x
    cmp #SMIL_DOOR_TRAVEL
    bcc @next
    lda #SMIL_BOARD_IN
    sta z:ES_MIL_BOARD
    stx z:ES_MIL_BAY
    rts
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SMIL_DOOR_BAYS * 2)
    bcc @bay
    rts

; --- mil_lobby_stage: the player and the four lift leaves -------------------
; CONTRACT mil_lobby_stage
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      five shadow-OAM entries written: the player at ES_MIL_PX on the
;             lobby floor, and each bay's two leaves parted by its own travel
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread; writes the OAM SHADOW
;   tail:     rts
;
; ONE LEAF GRAPHIC, FOUR ENTRIES. The right-hand leaf of each bay is the same
; tile set with the OAM H-flip bit set, which is why the pair costs one 32x32
; cell instead of two.
mil_lobby_stage:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_lobby_stage"
    jsr mil_lobby_hi                ; the size bits, every frame: three stores
                                    ;   against an ordering obligation on enter
    ; ---- the player -------------------------------------------------------
    lda z:ES_MIL_PX
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 0         ; X
    lda #SMIL_WALK_Y
    sta a:MIL_RIDER_OAM + 1         ; Y — the floor, and it is a constant
    rep #$20
    .a16
    lda z:ES_INP_CUR
    and #(JOY_LEFT | JOY_RIGHT)
    beq @idle
    lda z:ES_MIL_STEP               ; ...walking: the cell follows the GROUND
    lsr a
    lsr a
    lsr a
    and #(SMIL_RIDER_WALK_N - 1)
    clc
    adc #SMIL_RIDER_WALK0
    bra @cell
@idle:
    .a16
    .i16
    lda z:ES_MIL_PHASE
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #(SMIL_RIDER_IDLE_N - 1)
    clc
    adc #SMIL_RIDER_IDLE0
@cell:
    .a16
    .i16
    jsr mil_slot_tile               ; a slot index -> its tile in the grid
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 2
    lda z:ES_MIL_FACE
    ora #MIL_LOBBY_ATTR             ; ...in FRONT of the wall — see the note
    sta a:MIL_RIDER_OAM + 3         ;   on the constant
    rep #$20
    .a16
    ; ---- the leaves: two sides a bay, a stack of cells a side --------------------------------------------------------
    ldx #0                          ; X counts bays, Y indexes their OAM
    ldy #0
@bay:
    .a16
    .i16
    lda f:mil_bay_x, x
    sec
    sbc z:ES_MIL_DOOR, x            ; the near leaf, retracted left
    jsr mil_put_leaf
    lda f:mil_bay_x, x
    clc
    adc #SMIL_LEAF_BOX
    clc
    adc z:ES_MIL_DOOR, x            ; ...and the far leaf, right, H-flipped
    ora #(MIL_HFLIP << 8)           ; (carried in the high byte to mil_put_leaf)
    jsr mil_put_leaf
    inx
    inx
    cpx #(SMIL_DOOR_BAYS * 2)
    bcc @bay
    rts

; --- mil_put_leaf: one leaf's STACK of cells at Y, advancing Y --------------
; CONTRACT mil_put_leaf
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the leaf's screen X in the low byte, the H-flip bit in the
;             high byte; Y = the first cell's OAM byte offset
;   out:      SMIL_LEAF_ROWS entries written down the opening, Y advanced past
;             them
;   clobbers: A, N, Z
;   assumes:  the main thread
;   tail:     rts
;
; A 64 px opening is TWO 32x32 cells, not one sprite: this rail's OBSEL pair is
; 32x32/64x64 and a leaf is 32 wide, so the box tall enough to cover the
; opening is twice as wide as the bay it is closing. The stack is invisible
; because `leaf_pixels` is drawn on a vertical period that divides 32 — the
; same tile index serves every cell, so the second row costs four OAM bytes
; and no CHR.
;
; The count is `.repeat`ed rather than looped because it is a constant the
; generator emits: both index registers are already carrying the bay and the
; OAM cursor, and a third counter in scratch would be state standing in for
; a number the assembler already knows.
mil_put_leaf:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_put_leaf"
    sta z:ES_MIL_NMI_SCRATCH + 6    ; enter-time and main-thread: the NMI's row
                                    ;   walker does not run in the lobby
    sep #$20
    .a8
.repeat SMIL_LEAF_ROWS, k
    lda z:ES_MIL_NMI_SCRATCH + 6
    sta a:MIL_LEAF_OAM, y           ; X, low 8 — the same for the whole stack
    lda #(SMIL_DOOR_Y + k * SMIL_LEAF_BOX)
    sta a:MIL_LEAF_OAM + 1, y       ; Y — this cell's row down the opening
    lda #SMIL_LEAF_TILE
    sta a:MIL_LEAF_OAM + 2, y
    lda z:ES_MIL_NMI_SCRATCH + 7    ; ...the flip bit the caller passed high
    ora #MIL_LEAF_ATTR
    sta a:MIL_LEAF_OAM + 3, y
    rep #$20
    .a16
    tya
    clc
    adc #4
    tay
    sep #$20
    .a8
.endrepeat
    rep #$20
    .a16
    rts

; --- mil_lobby_hi: the size bits for every sprite this feature owns ---------
; CONTRACT mil_lobby_hi
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      MIL_HI_BYTES hi-table bytes written whole
;   clobbers: A, X, N, Z
;   assumes:  scene enter
;   tail:     rts
;
; WHOLE BYTES, NOT A READ-MODIFY-WRITE. The claim starts and ends on a
; hi-table byte precisely so this feature can write its own bytes without
; touching a neighbour's two bits, and the `.assert` above is what holds the
; allocator to it.
mil_lobby_hi:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_lobby_hi"
    sep #$20
    .a8
    ldx #0
@byte:
    .a8
    .i16
    lda #MIL_HI_ALL_LARGE
    sta a:MIL_HI_FIRST, x
    inx
    cpx #MIL_HI_BYTES
    bcc @byte
    rep #$20
    .a16
    rts

; --- mil_leaves_park: the lobby's leaves, put away ---------------------------
; CONTRACT mil_leaves_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every leaf cell parked off-screen and its size bit cleared
;   clobbers: A, X, N, Z
;   assumes:  scene enter
;   tail:     rts
;
; The hall does not draw leaves, but OAM IS NOT SCENE STATE — the shadow
; carries whatever the last scene left in it across the edge, and a lobby that
; left its bays open would hang four lit doors in the middle of a mill. Boot's
; `oam_park_all` cannot cover this: it runs once, before either scene.
;
; The park is Y=$F0 AND the size bit cleared, which are not redundant. $F0 is
; 240, and a 32x32 sprite parked there wraps 16 rows onto the top of the
; screen — the same defect the rider's SMIL_PARK_Y exists to avoid. Cleared to
; 16x16 the entry ends at 256 and shows nothing.
mil_leaves_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_leaves_park"
    sep #$20
    .a8
    ldx #0
@leaf:
    .a8
    .i16
    lda #240
    sta a:MIL_LEAF_OAM + 1, x       ; Y off the bottom
    inx
    inx
    inx
    inx
    cpx #(MIL_LEAF_CELLS * 4)
    bcc @leaf
    ldx #0
@hi:
    .a8
    .i16
    stz a:MIL_HI_FIRST, x           ; every leaf cell back to 16x16, so a park
    inx                             ;   at Y=240 ends at 256 instead of wrapping
    cpx #(MIL_LEAF_CELLS / 4)       ;   16 rows onto the top of the screen
    bcc @hi
    lda #MIL_RIDER_SIZE_LARGE       ; ...and the rider's own byte, which the
    sta a:MIL_RIDER_HI              ;   leaves do not share
    rep #$20
    .a16
    rts

; --- mil_slot_tile: an animation slot -> its tile index ---------------------
; CONTRACT mil_slot_tile
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the slot index
;   out:      A = the tile index that slot starts at
;   clobbers: N, Z, C
;   assumes:  nothing
;   tail:     rts
;
; THE NAME TABLE IS A 16-WIDE GRID AND FOUR 32x32 CELLS FILL A ROW, so slot*4
; is the base only while slot < 4. At slot 4 it lands on tile 16 — row 1 of the
; FIRST cell — and the fifth frame reads the first one's second row. Sixty-four
; tiles is one group of four cells; the base is a group address plus a column
; in it. The generator writes the blob with the same formula.
mil_slot_tile:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_slot_tile"
    pha
    and #(SMIL_RIDER_GROUP - 1)     ; the column within the group
    asl a
    asl a
    sta z:ES_MIL_NMI_SCRATCH + 6
    pla
    .repeat 2
    lsr a                           ; ...and which group
    .endrepeat
    .repeat 6
    asl a                           ; 64 tiles a group
    .endrepeat
    clc
    adc z:ES_MIL_NMI_SCRATCH + 6
    rts

.segment "RODATA"
; The bays' left edges, in screen X. Derived from the generator's own column
; plan, so moving a lift bay moves its leaves with it.
mil_bay_x:
    .word SMIL_DOOR_A * 8, SMIL_DOOR_B * 8
.segment "CODE"
