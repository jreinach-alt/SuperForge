; =============================================================================
; m7f_obj.asm — the airship, and the shadow that is this rail's altimeter
; =============================================================================
; TWO SPRITES, both at a FIXED screen position: the ship never moves on screen,
; the world moves under it. What changes is the propeller frames (a two-frame
; flip on an 8-frame clock, BOTH ENGINES, in anti-phase — the art carries the
; phase, tools/gen_m7f_assets.py) and — the part that matters — the SHADOW,
; whose drawn diameter, tile, hardware size bit and screen Y all track the
; altitude down a FIVE-RUNG LADDER:
;
;  low a 26 px ellipse in a 32x32 box, close under the ship
;  high a 6 px one in a 16x16 box, far down the screen toward the horizon
;
; That is the rail's only altitude readout. BGMODE 7 has exactly one layer and
; the plane is using it, so there is no tilemap to write a HUD into; rs_obj's
; header reaches the same conclusion for the same reason. It also means the
; shadow is a TEST SURFACE rather than decoration — "the ship climbed" is
; observable in OAM as a size bit, a tile number and a Y coordinate that move
; together, and on the PICTURE as an ellipse that narrows in five readable
; steps, which is what tests/test_mode7_flight.py reads.
;
; FIVE RUNGS OUT OF TWO HARDWARE SIZES. OBSEL carries ONE size pair for the
; whole frame and this rail spent it on (16, 32) — see obj_arm — so no sixth
; hardware size is buyable at any price. Apparent size is not the box, it is
; the ART inside the box, so the ladder is two ellipses drawn in the 32 box and
; three in the 16 one, and the step a player reads is the ellipse.

; --- the placement constants ------------------------------------------------
; CENTRED, NOT OFFSET. A sprite's screen x is its LEFT EDGE, so an object is
; centred on the 256 px screen at 128 - box/2 — which is a function of the BOX
; and not a constant. One constant served both boxes here until the ladder
; landed, and the 16 px shadow drew at 112..127: centred on column 120, eight
; pixels left of the airship it belonged to. Every rung now carries its own x,
; derived from its box in m7f_shadow_tab below.
M7F_SCREEN_CX    = 128
M7F_SHIP_BOX     = 32
M7F_SHIP_X       = M7F_SCREEN_CX - M7F_SHIP_BOX / 2
M7F_SHIP_Y       = 96
M7F_PROP_RATE    = 8                    ; frames between propeller flips

; The shadow's CENTRE locus: the screen row its ellipse is centred on at the
; floor of the climb. A rung's OAM y is this minus half its own box, so the
; centre walks one continuous line down the screen as the ladder steps and the
; shadow does not jump when the box changes.
M7F_SHADOW_CY    = 184

; --- the sheet's objects, at their first tile in the 16-wide grid ------------
; Rows 0-3 are the 32x32 floor and it is full: a 32x32 object needs four
; consecutive grid rows, so the sheet holds exactly four of them.
M7F_SHIP_TILE_A     = 0
M7F_SHIP_TILE_B     = 4
M7F_SHADOW_TILE_0   = 8                 ; 32 box, 26 px ellipse — the lowest
M7F_SHADOW_TILE_1   = 12                ; 32 box, 20 px
; Rows 4-5 are the 16x16 floor: eight slots, five used and three spare.
M7F_CLOUD_TILE_A    = 64
M7F_CLOUD_TILE_B    = 66
M7F_SHADOW_TILE_2   = 68                ; 16 box, 14 px
M7F_SHADOW_TILE_3   = 70                ; 16 box, 10 px
M7F_SHADOW_TILE_4   = 72                ; 16 box, 6 px — the highest

; --- OAM attribute bytes ----------------------------------------------------
; vhoopppN: priority in bits 4-5, palette in bits 1-3. The ship takes priority
; 3 and OBJ palette 0; the shadow priority 2 and palette 1. Written as SHIFTS
; because the hex form says nothing about which field is which.
M7F_ATTR_SHIP   = (3 << 4) | (0 << 1)
M7F_ATTR_SHADOW = (2 << 4) | (1 << 1)
; Palette 2 (the cloud_pal claim's CGRAM 160) and PRIORITY 0, which is the one
; OBJ priority the Mode 7 plane draws OVER. That is the cloud reveal: see the
; cloud section below for the mechanism and for what it replaced.
M7F_ATTR_CLOUD  = (0 << 4) | (2 << 1)

; The hi table's size bit for a slot is bit 1 of that slot's 2-bit field; bit 0
; is X9. The airship and every shadow rung sit inside 112..143, so X9 is 0 for
; the life of the ROM and only the size bits are ever set.
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
; CONTRACT m7f_obj::obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the sheet, the two palettes, OBSEL and the parked pad
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
;
; X, Y.
obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_arm"
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

; --- the shadow ladder ------------------------------------------------------
; THE RUNGS ARE DATA, not a branch chain, because every rung answers the same
; four questions and a chain would answer them in four places. One 4-byte row
; per rung, LOWEST ALTITUDE FIRST:
;
;   +0 tile        the rung's first tile in the sheet's 16-wide grid
;   +1 size bit    the shadow's bit in the hi-table byte: set for a 32 box
;   +2 screen x    128 - box/2 — CENTRED, and the reason this is a per-rung
;                  field at all (see the placement constants above)
;   +3 screen y    M7F_SHADOW_CY - box/2, the base the altitude drop adds to,
;                  so the ELLIPSE'S CENTRE walks one continuous line down the
;                  screen and does not jump 8 px when the box changes
;
; The stride is four, so ONE shift turns the rung number into the row offset,
; and each pair of fields comes out of the table as a single 16-bit load laid
; out the way OAM wants it — +2/+3 IS the entry's first word.
M7F_SHADOW_STEPS = 5

m7f_shadow_tab:
    .byte M7F_SHADOW_TILE_0, M7F_HI_SHADOW_LARGE
    .byte M7F_SCREEN_CX - 16, M7F_SHADOW_CY - 16
    .byte M7F_SHADOW_TILE_1, M7F_HI_SHADOW_LARGE
    .byte M7F_SCREEN_CX - 16, M7F_SHADOW_CY - 16
    .byte M7F_SHADOW_TILE_2, 0
    .byte M7F_SCREEN_CX - 8,  M7F_SHADOW_CY - 8
    .byte M7F_SHADOW_TILE_3, 0
    .byte M7F_SCREEN_CX - 8,  M7F_SHADOW_CY - 8
    .byte M7F_SHADOW_TILE_4, 0
    .byte M7F_SCREEN_CX - 8,  M7F_SHADOW_CY - 8

; The altitude INDEX at which each rung gives way to the next — four boundaries
; for five rungs, evenly spaced over the 0..80 axis (m7f_cam/feature.toml on why
; the index is what gets stored). Words, so the scan compares in A16 against
; M7F_ALTIDX without narrowing.
m7f_shadow_thr:
    .word 16, 32, 48, 64

; --- obj_draw: both sprites, from the live altitude and propeller frame -----
; CONTRACT m7f_obj::obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both sprites staged from the live altitude and propeller
;             frame
;   clobbers: A, X, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; state step, so the shadow reads the altitude this frame settled on.
;
; THE SHADOW'S FOUR PROPERTIES MOVE TOGETHER, and that is the design rather
; than four coincidences: screen Y = (the rung's base) + (alt >> 3) drops
; toward the horizon as the ship climbs, while the tile, the size bit and the
; screen x step down the ladder with it. A test that reads only one of them
; would pass on a build where the other three were frozen.
obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_draw"
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

    ; ---- which rung: the number of thresholds the altitude has passed ------
    lda z:M7F_ALTIDX
    ldx #0
@rung:
    .a16
    .i16
    cmp a:m7f_shadow_thr, x
    bcc @rung_found
    inx
    inx
    cpx #((M7F_SHADOW_STEPS - 1) * 2)
    bcc @rung
@rung_found:
    .a16
    .i16
    txa
    asl a
    tax                             ; X = rung * 4 — the row, 4 bytes wide

    ; ---- the shadow's screen y: alt = idx * 3, then the rung's own base ----
    lda z:M7F_ALTIDX
    asl a
    clc
    adc z:M7F_ALTIDX                ; idx * 3 = the altitude on the 0..240
                                    ; scale
    lsr a
    lsr a
    lsr a                           ; alt >> 3 — the drop toward the horizon
    xba
    and #$FF00                      ; ...into the high byte, where OAM's y is
    clc
    adc a:m7f_shadow_tab + 2, x     ; + (this rung's y base << 8 | its x)
    sta a:M7F_OAM_SHADOW + 0        ; bytes 0,1: the centred x and the drop

    ; ---- the tile, and the size bit that has to agree with it -------------
    lda a:m7f_shadow_tab + 0, x
    and #$00FF
    ora #(M7F_ATTR_SHADOW << 8)
    sta a:M7F_OAM_SHADOW + 2

    ; The hi byte is WRITTEN, not OR-ed: this feature owns all four slots the
    ; byte covers (slots 2 and 3 are its parked pad) and no sprite in it ever
    ; reaches x = 256, so no X9 bit needs preserving. Rebuilding it whole is
    ; what makes the size bit track the altitude in BOTH directions — an OR
    ; would latch the large box on for the rest of the flight.
    lda a:m7f_shadow_tab + 0, x
    xba
    and #$00FF                      ; the rung's size bit, alone
    ora #M7F_HI_SHIP_LARGE          ; ...beside the airship's, which never moves
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
; THE HORIZON OCCLUDES THEM, and that is the whole of the reveal. The four
; slots are at FIXED screen Y and are drawn EVERY frame; what changes with
; altitude is how much of each one the ground is in front of. They carry OBJ
; priority 0, and in BGMODE 7 that is the one OBJ priority the plane draws
; over: Mesen2's SnesPpu.cpp RenderMode7() gives the four OBJ priorities the
; ranks {2, 4, 6, 7} and then renders BG1 at rank 3, so priority 0 sits UNDER
; the plane and priorities 1-3 sit over it (the airship's 3 and the shadow's 2
; are why those two stay on top). Above the horizon m7f_floor's TM split turns
; BG1 off entirely, so there is nothing in front of the cloud and it draws
; against the backdrop. The boundary between the two is the horizon line
; itself, to the scanline, for free.
;
; So a climb lowers the split and a cloud emerges from behind the ground ROW BY
; ROW. What this replaced was a CULL: a cloud whose 16 px box reached the
; band's first scanline was parked offscreen, so it went from nothing to a
; whole cloud in ONE frame. Measured on the shipping build before the change:
; between altitude index 32 and 36 the cloud-coloured pixel count on the
; rendered frame stepped 344 -> 458, ten rows of cloud arriving at once.
;
; THE TWO REJECTED MECHANISMS, and why:
;  * OBJ WINDOWING (WOBJSEL/WOBJLOG + TMW). It clips sprites, but the window
;  edges are X coordinates: making one clip at a horizontal LINE means
;  HDMA-ing WH0/WH1 per scanline, which is a seventh HDMA channel on a rail
;  that holds six, plus a table to rebuild every time the horizon moves,
;  plus four new register claims. It buys nothing the plane already in front
;  of the cloud does not.
;  * A PER-ROW ART REVEAL (successive frames each showing more of the shape).
;  No new register, but N frames per shape of CHR — and the shadow ladder in
;  this same sheet is already spending the tiles.
M7F_CLOUD_N     = 4
M7F_CLOUD_H     = 16                    ; the sprite box, and the wrap margin
M7F_CLOUD_WIND  = $0020                 ; 8.8: 1/8 px per frame
; ...and the same drift for a PAL frame. A wind is a VELOCITY, so it takes the
; frame ratio once; 8.8 is fine enough that the conversion is a build-time
; constant and the rounding is 1/256 px per frame.
; TICK: ok — the twin exists so the drift per REAL second is the same number
;   on both machines. It is the removal of a frame coupling, not one.
M7F_CLOUD_WIND_PAL = (((M7F_CLOUD_WIND * (TS_GAIN_DEN + TS_GAIN_NUM)) + TS_GAIN_DEN / 2) / TS_GAIN_DEN)
M7F_CLOUD_PAR   = 2                     ; px per heading unit
M7F_CLOUD_SPAN  = 256 + M7F_CLOUD_H     ; the wrap period: on at -16, off at 256
M7F_CLOUD_HEADM = $00FF                 ; the heading axis is 256 units round
M7F_CLOUD_SIGN  = $0080                 ; ...so a delta above this is negative

M7F_OAM_CLOUD   = ES_OAM_SHADOW + ES_O_CLOUDS * 4
M7F_OAM_HI1     = ES_OAM_SHADOW + OAM_LOW_BYTES + 1   ; slots 4..7's hi byte
M7F_CLOUD_X     = ES_M7F_CLOUD + 0      ; 8.8 drift accumulator
M7F_CLOUD_LASTH = ES_M7F_CLOUD + 2      ; the heading the delta is measured from
M7F_CLOUD_TMP   = ES_M7F_CLOUD + 4      ; the frame's parallax step, then x
M7F_CLOUD_HI    = ES_M7F_CLOUD + 6      ; the hi byte, built as it goes
.assert ES_O_CLOUDS = 4, error, "the clouds left the second hi-table byte, which cloud_draw rebuilds whole"
.assert ES_O_CLOUDS_SPRITES = M7F_CLOUD_N, error, "the cloud slot count disagrees with the claim"

; One FOUR-BYTE row per cloud, so ONE index walks both this table and the OAM
; entries: [x offset within the wrap period][screen y][tile]. Spread DOWN the
; sky band across the whole 40 scanlines the horizon travels, so the ground
; uncovers them one at a time as the ship climbs, and spread across x so four
; sprites do not read as a row. The rows are 22 apart and the box is 16, so no
; two clouds ever share a scanline — which keeps a sky row flat enough for the
; horizon reader in tests/test_mode7_flight.py, and keeps the lowest cloud's
; box clear of the airship's (y 96..128).
m7f_cloud_tab:
    .word 0
    .byte 12, M7F_CLOUD_TILE_A
    .word 74
    .byte 34, M7F_CLOUD_TILE_B
    .word 150
    .byte 56, M7F_CLOUD_TILE_A
    .word 208
    .byte 78, M7F_CLOUD_TILE_B

; --- cloud_arm: seed the accumulator and the heading reference --------------
; CONTRACT cloud_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the drift accumulator and the heading reference seeded —
;             both words written here because power-on DP is random (rule
;             5)
;   clobbers: A, N, Z
;   assumes:  forced blank, at scene enter
;   tail:     rts
;
; written before `cloud_draw` reads either, and the heading reference is seeded
; from the LIVE heading so the first frame's delta is zero rather than a jump
; from whatever power-on left there.
cloud_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cloud_arm"
    stz z:M7F_CLOUD_X
    lda z:M7F_HEAD
    sta z:M7F_CLOUD_LASTH
    rts

; --- obj_region_rates: the cloud drift, in the running console's units ------
; CONTRACT obj_region_rates
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the cloud drift rate published in the running console's
;             units
;   clobbers: A, X, N, Z
;   assumes:  ONCE, from the scene's `enter`, before the first tick reads
;             it
;   tail:     rts
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep. `@pal` is reached A16 by branch
; and the store below A16 from both arms.
obj_region_rates:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_region_rates"
    lda #M7F_CLOUD_WIND
    ldx z:ES_RGN_PAL
    beq :+
    lda #M7F_CLOUD_WIND_PAL
:
    .a16
    .i16
    sta z:US_R_WIND
    rts

; --- cloud_tick: the two motions, into one accumulator ----------------------
; CONTRACT cloud_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the two motions folded into one accumulator
;   clobbers: A, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one, after the state step
;   tail:     rts
;
; step, so the heading delta is this frame's turn.
cloud_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cloud_tick"
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
    adc z:US_R_WIND             ; wind forward, at THIS console's drift...
    sec
    sbc z:M7F_CLOUD_TMP         ; ...parallax back. The sign IS the illusion.
    sta z:M7F_CLOUD_X
    rts

; --- cloud_draw: four slots, the ground in front of them --------------------
; CONTRACT cloud_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      four cloud slots staged, the ground in front of them
;   clobbers: A, Y, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
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
    SF_ASSERT_WIDTH 16, 16, "cloud_draw"
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
    lda #1
    tsb z:M7F_CLOUD_HI          ; this cloud's X9 into bit 0 — test-and-set
                                ;   rather than load/or/store. Z is set from A
                                ;   AND memory, not from the result; the label
                                ;   below is reached from a `beq` that has
                                ;   already branched and nothing there reads it
:
    .a16
    .i16
    ; ---- the row, unconditionally: the PLANE decides what is seen of it ----
    ; No cull. The cloud carries OBJ priority 0, so every row of it that falls
    ; below the horizon is covered by BG1 and every row above it is not — see
    ; this section's header for the rank arithmetic that makes that true.
    sep #$20
    .a8
    lda a:m7f_cloud_tab + 2, y
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
; CONTRACT obj_prop_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the two-frame propeller clock stepped
;   clobbers: A, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; THE DIVIDER IS UNTOUCHED AND THE CLOCK IS WHAT MOVES. M7F_PROP_RATE is a
; small integer with no correct x1.2018 — docs/95 §5.2's class C — so it stays
; the eight the sheet was authored against, and the clock counts down by THIS
; FRAME'S TICKS instead of by one. On NTSC US_TS_TICK is exactly 1 every frame,
; so this is `dec a` to the cycle in behaviour.
;
; AND THE OVERSHOOT IS CARRIED rather than the reload being a constant: a
; 2-tick PAL frame can cross zero by one, and dropping that one is a bias
; nothing upstream can see. `adc` of the rate to a 0 or -1 leaves 8 or 7, which
; is the reload the original did plus the remainder.
obj_prop_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_prop_tick"
    lda z:US_PROP_T
    sec
    sbc z:US_TS_TICK
    beq @flip                   ; landed exactly on the flip
    bcc @flip                   ; ...or crossed it, by one
    sta z:US_PROP_T
    rts
@flip:
    .a16
    .i16
    clc
    adc #M7F_PROP_RATE          ; the divider, plus whatever was overshot
    sta z:US_PROP_T
    lda z:US_PROP_F
    eor #1
    sta z:US_PROP_F
    rts
