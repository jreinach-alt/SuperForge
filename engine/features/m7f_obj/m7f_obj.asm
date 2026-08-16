; =============================================================================
; m7f_obj.asm — the airship, and the shadow that is this rail's altimeter
; =============================================================================
; TWO SPRITES, both at a FIXED screen position: the ship never moves on screen,
; the world moves under it. What changes is the propeller frame (a two-frame
; flip on an 8-frame clock) and — the part that matters — the SHADOW, whose
; size, tile and screen Y all track the altitude:
;
;  low BIG 32x32 shadow, close under the ship
;  high SMALL 16x16 shadow, further down the screen toward the horizon
;
; That is the rail's only altitude readout. BGMODE 7 has exactly one layer and
; the plane is using it, so there is no tilemap to write a HUD into; rs_obj's
; header reaches the same conclusion for the same reason. It also means the
; shadow is a TEST SURFACE rather than decoration — "the ship climbed" is
; observable in OAM as a size bit, a tile number and a Y coordinate that move
; together, which is what tests/test_mode7_flight.py reads.

; --- the placement constants ------------------------------------------------
; The ship is centred on a 256 px screen: 128 - 16 puts the 32 px sprite's
; LEFT edge half a sprite left of centre.
M7F_SHIP_X       = 128 - 16
M7F_SHIP_Y       = 96
M7F_SHADOW_X     = 128 - 16
M7F_SHADOW_Y_LOW = 168                  ; screen Y at the floor of the climb
M7F_PROP_RATE    = 8                    ; frames between propeller flips

; The altitude at which the shadow switches size — index 40 of 80, i.e. 120 on
; the underlying 0..240 scale. See m7f_cam/feature.toml on why the index is
; what gets stored.
M7F_SHADOW_THRESH_IDX = 40

; --- the sheet's four objects, at their column offsets in the 16-wide grid ---
M7F_SHIP_TILE_A     = 0
M7F_SHIP_TILE_B     = 4
M7F_SHADOW_TILE_BIG = 8
M7F_SHADOW_TILE_SML = 12
; The two cloud shapes, in the slots the 32x32 objects leave behind: the small
; shadow occupies 12,13,28,29 of its column, so 14,15,30,31 sit free beside it,
; and row 2 column 12 is free entirely. Tools/gen_m7f_assets.py blits them.
M7F_CLOUD_TILE_A    = 14
M7F_CLOUD_TILE_B    = 44

; --- OAM attribute bytes ----------------------------------------------------
; vhoopppN: priority in bits 4-5, palette in bits 1-3. The ship takes priority
; 3 and OBJ palette 0; the shadow priority 2 and palette 1. Written as SHIFTS
; because the hex form says nothing about which field is which.
M7F_ATTR_SHIP   = (3 << 4) | (0 << 1)
M7F_ATTR_SHADOW = (2 << 4) | (1 << 1)
; Palette 2 (the cloud_pal claim's CGRAM 160) and priority 1 — under the
; airship's 3, which is what puts a cloud behind the ship it is far behind.
M7F_ATTR_CLOUD  = (2 << 4) | (2 << 1)

; The hi table's size bit for a slot is bit 1 of that slot's 2-bit field; bit 0
; is X9. Both sprites sit at x = 112, so X9 is 0 for the life of the ROM and
; only the size bits are ever set.
M7F_HI_SHIP_LARGE   = 1 << 1            ; slot 0's size bit
M7F_HI_SHADOW_LARGE = 1 << 3            ; slot 1's size bit

OAM_LOW_BYTES  = ES_OAM_SHADOW_SIZE - 32
M7F_OAM_SHIP   = ES_OAM_SHADOW + ES_O_SHIP * 4
M7F_OAM_SHADOW = ES_OAM_SHADOW + ES_O_SHADOW * 4
M7F_OAM_HI0    = ES_OAM_SHADOW + OAM_LOW_BYTES  ; the byte covering slots 0..3

; The enter-time GP-DMA register file, addressed through the channel the
; m7f_obj_up dma_init claim names — a declared resource, not a hard-coded 0.
M7F_OBJ_REGS = $4300 + ES_D_M7F_OBJ_UP_CH * 16

; --- obj_arm: the sheet, the two palettes, OBSEL, the parked pad ------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene enter). Clobbers A,
; X, Y.
obj_arm:
    .a16
    .i16
    ; ---- the OBJ CHR sheet: one DMA ---------------------------------------
    ; DAS is single-shot, consumed by the transfer, so it is armed HERE for
    ; THIS transfer — one transfer, one arming site.
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    lda #^m7f_obj_chr_bin
    sta a:M7F_OBJ_REGS + 4
    lda #ES_D_M7F_OBJ_UP_DMAP
    sta a:M7F_OBJ_REGS + 0
    lda #ES_D_M7F_OBJ_UP_BBAD
    sta a:M7F_OBJ_REGS + 1          ; BBAD: VMDATAL
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR                ; the allocator's word address for the sheet
    sta a:$2116                      ; VMADD
    ldx #.loword(m7f_obj_chr_bin)
    stx a:M7F_OBJ_REGS + 2
    ldy #ES_R_M7F_OBJ_CHR_SIZE
    sty a:M7F_OBJ_REGS + 5           ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_M7F_OBJ_UP_CH)
    sta a:$420B
    rep #$20
    .a16

    ; ---- the two OBJ palettes ---------------------------------------------
    lda #ES_C_SHIP_PAL
    ldx #0
    jsr obj_pal_ship
    lda #ES_C_SHADOW_PAL
    jsr obj_pal_shadow

    ; ---- OBSEL: size pair 3 (16x16 / 32x32) + the OBJ name base -----------
    ; The pair is forced by the cast: the airship and the low shadow are 32x32
    ; and the high shadow is 16x16, so (16, 32) is the only pair that holds all
    ; three. The base is the ALLOCATOR's — the scene's `mode7` claim pins VRAM
    ; words $0000-$3FFF and the allocator floors every OBJ CHR claim above it,
    ; so the byte is derived from the claim rather than hand-spelled.
    sep #$20
    .a8
    lda #((3 << 5) | ES_V_OBJ_CHR_OBSEL_BASE)
    sta a:$2101                     ; OBSEL
    rep #$20
    .a16

    ; ---- the pad slots, parked for the ROM's life -------------------------
    ; Slots 2 and 3 exist so the FIRST hi-table byte has one owner. Parking
    ; them off-screen is rule 5: power-on OAM is random and `oam_park_all` has
    ; already run, but this feature owns these two and says so.
    ldx #(ES_O_HI_PAD * 4)
:   lda #$F000                      ; y = $F0, x = 0 — off the bottom
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) * 4)
    bcc :-
    rts

; --- obj_pal_ship / obj_pal_shadow: sixteen words each ----------------------
; In/out: A16/I16, DB=0. A = the CGRAM word index to start at. Clobbers A, X.
; Two entry points rather than a parameterised one because the SOURCE blob
; differs and `.incbin` labels are assemble-time constants, not values.
obj_pal_ship:
    .a16
    .i16
    sep #$20
    .a8
    sta a:$2121                     ; CGADD
    rep #$20
    .a16
    ldx #0
:   lda f:m7f_ship_pal_bin, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7F_SHIP_PAL_SIZE
    bcc :-
    rts

obj_pal_shadow:
    .a16
    .i16
    sep #$20
    .a8
    sta a:$2121
    rep #$20
    .a16
    ldx #0
:   lda f:m7f_shadow_pal_bin, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7F_SHADOW_PAL_SIZE
    bcc :-
    rts

; --- obj_draw: both sprites, from the live altitude and propeller frame -----
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Called from the scene tick, AFTER
; the state step, so the shadow reads the altitude this frame settled on.
;
; THE SHADOW'S THREE PROPERTIES MOVE TOGETHER, and that is the design rather
; than three coincidences: screen Y = SHADOW_Y_LOW + (alt >> 3) drops toward
; the horizon as the ship climbs, while the size and tile switch at the halfway
; altitude. A test that reads only one of the three would pass on a build where
; the other two were frozen.
obj_draw:
    .a16
    .i16
    ; ---- the airship: fixed position, propeller frame from the clock -------
    lda z:US_PROP_F
    beq :+
    lda #M7F_SHIP_TILE_B
    bra :++
:
    lda #M7F_SHIP_TILE_A
:
    ora #(M7F_ATTR_SHIP << 8)
    sta a:M7F_OAM_SHIP + 2          ; bytes 2,3: tile and attr in one store
    lda #((M7F_SHIP_Y << 8) | M7F_SHIP_X)
    sta a:M7F_OAM_SHIP + 0          ; bytes 0,1: x low and y in one store

    ; ---- the shadow: alt = idx * 3, then screen Y = LOW + (alt >> 3) -------
    lda z:M7F_ALTIDX
    asl a
    clc
    adc z:M7F_ALTIDX                ; idx * 3 = the altitude on the 0..240
                                    ; scale
    lsr a
    lsr a
    lsr a                           ; alt >> 3
    clc
    adc #M7F_SHADOW_Y_LOW
    xba
    and #$FF00
    ora #M7F_SHADOW_X
    sta a:M7F_OAM_SHADOW + 0        ; bytes 0,1: x low and the derived y

    lda z:M7F_ALTIDX
    cmp #M7F_SHADOW_THRESH_IDX
    bcs @high
    ; --- low: the BIG 32x32 shadow, close under the ship -------------------
    lda #(M7F_SHADOW_TILE_BIG | (M7F_ATTR_SHADOW << 8))
    sta a:M7F_OAM_SHADOW + 2
    lda #(M7F_HI_SHIP_LARGE | M7F_HI_SHADOW_LARGE)
    bra @hi_put
@high:
    .a16
    .i16
    ; --- high: the SMALL 16x16 shadow --------------------------------------
    lda #(M7F_SHADOW_TILE_SML | (M7F_ATTR_SHADOW << 8))
    sta a:M7F_OAM_SHADOW + 2
    lda #M7F_HI_SHIP_LARGE
@hi_put:
    .a16
    .i16
    ; The hi byte is WRITTEN, not OR-ed: this feature owns all four slots the
    ; byte covers (slots 2 and 3 are its parked pad), and both sprites sit at
    ; x = 112, so no X9 bit ever needs preserving. Rebuilding it whole is what
    ; makes the size bits track the altitude in BOTH directions — an OR would
    ; latch the big shadow on for the rest of the flight.
    sep #$20
    .a8
    sta a:M7F_OAM_HI0
    rep #$20
    .a16
    rts

; =============================================================================
; The clouds (piece B') — drift, rotation parallax, and the moving-horizon cull
; =============================================================================
; FOUR sprites in the sky band, on TWO motions. The usual way to do this is a
; BG2 cloud layer whose BG2HOFS takes a wind term and a heading term summed
; together. Here the layer is four OAM slots instead, so the same two terms
; land in one 8.8 accumulator and every cloud reads it at its own
; offset:
;
;  WIND a constant 8.8 step every frame. Slow — M7F_CLOUD_WIND/256 px a
;  frame — because a cloud that crosses the screen in seconds reads
;  as a bug rather than as weather.
;  PARALLAX the HEADING DELTA, SUBTRACTED, so clouds slide OPPOSITE the turn.
;  That sign is the whole illusion: turn right and the world swings
;  left, and clouds that swung right with it would read as painted on
;  the canopy. M7F_CLOUD_PAR is px per heading unit, so one full
;  256-unit revolution sweeps them 512 px — two screens.
;
; The four slots are at FIXED screen Y and are CULLED against the LIVE horizon:
; a cloud whose box would reach the band's first scanline is parked offscreen
; rather than drawn over the ground. The horizon moves 40 scanlines with
; altitude, so the sky carries three clouds at the deck and all four at the
; ceiling — the cull is what makes climbing reveal SKY rather than reveal
; clouds sitting on the terrain.
M7F_CLOUD_N     = 4
M7F_CLOUD_H     = 16                    ; the sprite box, for the cull
M7F_CLOUD_WIND  = $0020                 ; 8.8: 1/8 px per frame
M7F_CLOUD_PAR   = 2                     ; px per heading unit
M7F_CLOUD_SPAN  = 256 + M7F_CLOUD_H     ; the wrap period: on at -16, off at 256
M7F_CLOUD_HEADM = $00FF                 ; the heading axis is 256 units round
M7F_CLOUD_SIGN  = $0080                 ; ...so a delta above this is negative
M7F_CLOUD_PARK  = $F0                   ; the park row oam_park_all uses

M7F_OAM_CLOUD   = ES_OAM_SHADOW + ES_O_CLOUDS * 4
M7F_OAM_HI1     = ES_OAM_SHADOW + OAM_LOW_BYTES + 1   ; slots 4..7's hi byte
M7F_CLOUD_X     = ES_M7F_CLOUD + 0      ; 8.8 drift accumulator
M7F_CLOUD_LASTH = ES_M7F_CLOUD + 2      ; the heading the delta is measured from
M7F_CLOUD_TMP   = ES_M7F_CLOUD + 4      ; the frame's parallax step, then x
M7F_CLOUD_HI    = ES_M7F_CLOUD + 6      ; the hi byte, built as it goes
.assert ES_O_CLOUDS = 4, error, "the clouds left the second hi-table byte, which cloud_draw rebuilds whole"
.assert ES_O_CLOUDS_SPRITES = M7F_CLOUD_N, error, "the cloud slot count disagrees with the claim"

; One FOUR-BYTE row per cloud, so ONE index walks both this table and the OAM
; entries: [x offset within the wrap period][screen y][tile]. Spread down the
; sky band so the cull takes them one at a time as the horizon climbs, and
; spread across x so four sprites do not read as a row.
m7f_cloud_tab:
    .word 0
    .byte 14, M7F_CLOUD_TILE_A
    .word 74
    .byte 30, M7F_CLOUD_TILE_B
    .word 150
    .byte 46, M7F_CLOUD_TILE_A
    .word 208
    .byte 62, M7F_CLOUD_TILE_B

; --- cloud_arm: seed the accumulator and the heading reference --------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A. Rule 5: both words are
; written before `cloud_draw` reads either, and the heading reference is seeded
; from the LIVE heading so the first frame's delta is zero rather than a jump
; from whatever power-on left there.
cloud_arm:
    .a16
    .i16
    stz z:M7F_CLOUD_X
    lda z:M7F_HEAD
    sta z:M7F_CLOUD_LASTH
    rts

; --- cloud_tick: the two motions, into one accumulator ----------------------
; In/out: A16/I16, DB=0. Clobbers A. Called from the scene tick AFTER the state
; step, so the heading delta is this frame's turn.
cloud_tick:
    .a16
    .i16
    lda z:M7F_HEAD
    sec
    sbc z:M7F_CLOUD_LASTH
    and #M7F_CLOUD_HEADM        ; 0..255: the turn as an unsigned arc
    cmp #M7F_CLOUD_SIGN
    bcc :+
    sec
    sbc #(M7F_CLOUD_HEADM + 1)  ; ...taken the short way round, now signed
:
    .a16
    .i16
    ; delta * M7F_CLOUD_PAR, in 8.8 — nine shifts, because this feature does
    ; NOT own the hardware multiplier (m7f_cam's `m7f_alu` claim is WHOLE, one
    ; owner per scene) and the constant is a power of two anyway.
    .assert M7F_CLOUD_PAR = 2, error, "the nine shifts below are PAR * 256"
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta z:M7F_CLOUD_TMP
    lda z:M7F_HEAD
    sta z:M7F_CLOUD_LASTH
    lda z:M7F_CLOUD_X
    clc
    adc #M7F_CLOUD_WIND         ; wind forward...
    sec
    sbc z:M7F_CLOUD_TMP         ; ...parallax back. The sign IS the illusion.
    sta z:M7F_CLOUD_X
    rts

; --- cloud_draw: four slots, culled against the LIVE horizon ----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; WALKED BACKWARDS, from cloud 3 to cloud 0, and that is what lets the hi byte
; be built with a shift instead of a per-cloud mask table: each pass shifts the
; byte left two and drops the current cloud's X9 into bit 0, so cloud 0 ends in
; bits 0-1 where the hardware wants it. The byte is WRITTEN, not OR-ed, for
; `obj_draw`'s reason — this feature owns all four slots it covers. Every cloud
; is SMALL (16x16 under OBSEL size pair 3), so the size bits stay clear and the
; byte carries only X9 — which the clouds DO need, because the wrap period runs
; from -16 and one is always half off an edge.
cloud_draw:
    .a16
    .i16
    stz z:M7F_CLOUD_HI
    ldy #((M7F_CLOUD_N - 1) * 4)
@one:
    .a16
    .i16
    ; ---- x = (drift + this cloud's offset) mod the wrap period, minus 16 ---
    lda z:M7F_CLOUD_X
    xba
    and #$00FF                  ; the accumulator's integer half
    clc
    adc a:m7f_cloud_tab + 0, y
@wrap:
    .a16
    .i16
    cmp #M7F_CLOUD_SPAN
    bcc :+
    sec
    sbc #M7F_CLOUD_SPAN
    bra @wrap
:
    .a16
    .i16
    sec
    sbc #M7F_CLOUD_H            ; the period starts at -16, so one enters left
    and #$01FF                  ; nine bits: the PPU reads $1F0 as -16
    sta z:M7F_CLOUD_TMP
    ; ---- the hi byte: shift up two, drop this cloud's X9 into bit 0 --------
    lda z:M7F_CLOUD_HI
    asl a
    asl a
    sta z:M7F_CLOUD_HI
    lda z:M7F_CLOUD_TMP
    and #$0100
    beq :+
    lda z:M7F_CLOUD_HI
    ora #1
    sta z:M7F_CLOUD_HI
:
    .a16
    .i16
    ; ---- the cull, against the LIVE horizon --------------------------------
    sep #$20
    .a8
    lda a:m7f_cloud_tab + 2, y
    clc
    adc #M7F_CLOUD_H
    cmp z:M7F_HORIZON
    bcc :+
    lda #M7F_CLOUD_PARK         ; the box reaches the floor: park it offscreen
    bra @yput
:
    .a8
    .i16
    lda a:m7f_cloud_tab + 2, y
@yput:
    .a8
    .i16
    sta a:M7F_OAM_CLOUD + 1, y  ; byte 1: screen y
    lda z:M7F_CLOUD_TMP
    sta a:M7F_OAM_CLOUD + 0, y  ; byte 0: x, low eight bits
    lda a:m7f_cloud_tab + 3, y
    sta a:M7F_OAM_CLOUD + 2, y  ; byte 2: tile
    lda #M7F_ATTR_CLOUD
    sta a:M7F_OAM_CLOUD + 3, y  ; byte 3: attr
    rep #$20
    .a16
    tya
    sec
    sbc #4
    tay
    bpl @one
    sep #$20
    .a8
    lda z:M7F_CLOUD_HI
    sta a:M7F_OAM_HI1
    rep #$20
    .a16
    rts

; --- obj_prop_tick: the two-frame propeller clock ---------------------------
; In/out: A16/I16, DB=0. Clobbers A.
obj_prop_tick:
    .a16
    .i16
    lda z:US_PROP_T
    dec a
    sta z:US_PROP_T
    bne :+
    lda #M7F_PROP_RATE
    sta z:US_PROP_T
    lda z:US_PROP_F
    eor #1
    sta z:US_PROP_F
:
    .a16
    rts
