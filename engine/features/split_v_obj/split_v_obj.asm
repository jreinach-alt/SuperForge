; =============================================================================
; split_v_obj.asm — the two fighters, their animation, and the sprite HUD
; =============================================================================
; ONE frame set in OBJ VRAM, worn twice: fighter 1 on OBJ palette 0 (red team),
; fighter 2 on palette 1 (blue). The team colour is what makes a side-swap
; legible, and doing it with palettes rather than a second CHR copy is the only
; reason a twelve-frame set fits beside the stage at all.
;
; THE HUD IS SPRITES, AND THAT IS FORCED. bg_text claims BG3SC/BG34NBA and BG3
; here IS the divider, so this rail has no text layer: the life bars and the
; round-start count are 16x16 OBJs on a SECOND name table (see the gap
; derivation below), drawn from the same claim family as the fighters.
;
; THE FEET ANCHOR IS 28, NOT 32. The art does not fill its 32x32 box: its
; lowest drawn row is 28 (tools/gen_split_v_assets.py derives this from the
; pixels of EVERY frame in the set and refuses to emit if they disagree).
; Anchoring to the box height would hang both fighters four pixels above the
; grass on a flat floor, which reads as floating feet. Anchoring to the
; content bottom puts their soles on the surface.
;
; ...and the OAM y is one line ABOVE where the sprite draws: the PPU evaluates
; a scanline's sprites during the PREVIOUS line, so an OBJ renders one line
; below its OAM y. Both corrections are folded into SV_KNIGHT_Y once, here,
; rather than being rediscovered at each call site.

; Where the grass surface sits, in screen pixels. The stage map puts the grass
; row at tilemap row 22, and the arena does not scroll vertically, so this is a
; constant of the ART, not an address — no_literals has nothing to object to.
SV_FLOOR_ROW   = 22
SV_SURFACE_TOP = SV_FLOOR_ROW * 8       ; 176

; The knight's own content bottom inside its box (generator-derived; see the
; header). Change the art and this must change with it.
SV_KNIGHT_BOTTOM = 28

; OAM y for both fighters: soles on the surface, less the PPU's one-line
; evaluation offset.
SV_KNIGHT_Y = SV_SURFACE_TOP - SV_KNIGHT_BOTTOM - 1

; The knight is centred in its 32px box, so its x is the fighter's world x less
; half the box.
SV_KNIGHT_HALF = 16

; OAM attribute bits. Bit7 = V-flip, bit6 = H-flip, bits5:4 = priority, bits3:1
; = OBJ palette, bit0 = tile bit 8.
SV_ATTR_PRIO   = $30                    ; priority 3: in front of all BG
SV_ATTR_HFLIP  = $40
SV_PAL_RED     = $00                    ; OBJ palette 0
SV_PAL_BLUE    = $02                    ; OBJ palette 1 (bits3:1 = 1)
SV_PAL_BLADE   = $04                    ; OBJ palette 2 — the blade's own steel
                                        ;   and gold, on either team

; The size bit in the hi table. Each hi-table byte covers FOUR sprites, two
; bits each: bit0 of the field = X9, bit1 = size. OBSEL's pair 3 is small 16x16
; / large 32x32, so "large" is what makes these 32x32.
SV_OBJ_LARGE = $02

; ...and the way a CALLER asks for it. sv_obj_put's attribute argument is a
; byte, so bit 9 of the argument word carries the size out of band rather than
; costing a register or a claim. It is stripped before the attribute reaches
; OAM.
SV_SIZE_LARGE = 1 << 9

; The 9th TILE bit, in the OAM attribute. Set = this sprite's tiles come from
; the SECOND OBJ name table, which is where the HUD sheet lives.
SV_ATTR_NAME1 = 1 << 0

; OBSEL's size-pair field, bits 7:5. Pair 3 = small 16x16 / large 32x32, which
; is the pair that HAS a 32x32 half for these fighters. Written as a shifted
; ordinal rather than the equivalent hex byte because no_literals reads a bare
; `$60` as a raw ADDRESS operand -- correctly, since it cannot know which
; literals are hardware field values. Naming the field says what it is.
SV_OBSEL_PAIR3 = 3 << 5

; =============================================================================
; THE SECOND OBJ NAME TABLE, DERIVED FROM THE TWO EMITTED BASES
; =============================================================================
; OBSEL ($2101) is three fields: bits 0-2 the OBJ name base in 8 K-word steps
; (tiles 0..255), bits 3-4 a "name select" GAP in 4 K-word steps so that tiles
; 256..511 are fetched from base + (gap + 1) * $1000 words, and bits 5-7 the
; size pair. Mesen2 `SnesPpu.cpp:1899-1902` decodes it exactly that way
; (`OamBaseAddress = (value & 0x07) << 13`,
;  `OamAddressOffset = (((value & 0x18) >> 3) + 1) << 12`), and `:740` adds the
; offset only when the OAM attribute's bit 0 is set.
;
; The allocator gives both halves a base and CANNOT say more: `VramClaim.obj`
; is a bare bool, so nothing in the claim vocabulary says which claim is name
; table 0, and nothing checks that the pair lands a legal distance apart
; (brawler_obj's finding, unchanged). So the relationship is re-derived here
; from the two emitted symbols and ASSERTED — nothing below narrates an
; address, and a future packing that separates the halves by a distance OBSEL
; cannot express stops the build instead of drawing garbage.
SV_OBJ_SPAN = ES_V_HUD_CHR - ES_V_OBJ_CHR
SV_OBJ_GAP  = (SV_OBJ_SPAN >> 12) - 1
.assert SV_OBJ_SPAN >= (1 << 12), error, "split_v_obj: the HUD sheet is not ABOVE the fighter sheet by at least one name-select step — the allocator packed the two OBJ halves in an order OBSEL cannot express"
.assert SV_OBJ_SPAN = ((SV_OBJ_GAP + 1) << 12), error, "split_v_obj: the two OBJ CHR bases are not a whole number of 4 K-word name-select steps apart"
.assert SV_OBJ_GAP <= 3, error, "split_v_obj: the OBJ name-select gap needs more than the 2 bits OBSEL has (the halves are packed too far apart)"
.assert ES_V_OBJ_CHR = (ES_V_OBJ_CHR_OBSEL_BASE << 13), error, "split_v_obj: the fighter sheet's base is not expressible in OBSEL's 8 K-word base field"

SV_OBSEL = SV_OBSEL_PAIR3 | (SV_OBJ_GAP << 3) | ES_V_OBJ_CHR_OBSEL_BASE

; =============================================================================
; THE HUD SHEET'S SLOTS, mirroring gen_split_v_assets.hud_slot_base_tile
; =============================================================================
; A 16x16 sprite reads {N, N+1, N+16, N+17}, so two grid rows hold eight frames
; and slot N starts at (N / 8) * 32 + (N .MOD 8) * 2. The formula is restated
; rather than the eight answers pasted in, so a slot reorder in the generator
; moves these with it. All of it is TILE space, not address space.
SV_H_LIFE_FULL  = (0 / 8) * 32 + (0 .MOD 8) * 2
SV_H_LIFE_EMPTY = (1 / 8) * 32 + (1 .MOD 8) * 2
SV_H_D3         = (2 / 8) * 32 + (2 .MOD 8) * 2
SV_H_D2         = (3 / 8) * 32 + (3 .MOD 8) * 2
SV_H_D1         = (4 / 8) * 32 + (4 .MOD 8) * 2
SV_H_F          = (5 / 8) * 32 + (5 .MOD 8) * 2
SV_H_I          = (6 / 8) * 32 + (6 .MOD 8) * 2
SV_H_G          = (7 / 8) * 32 + (7 .MOD 8) * 2
SV_H_H          = (8 / 8) * 32 + (8 .MOD 8) * 2
SV_H_T          = (9 / 8) * 32 + (9 .MOD 8) * 2

SV_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; The hi-table bytes this feature rebuilds whole, one per four claimed sprites.
; The claims are pinned so that the twenty sprites fill exactly five of them
; from a byte boundary — asserted, not assumed (scroller_obj's argument).
.assert ES_O_FIGHTER1 .MOD 4 = 0, error, "split_v_obj: the sprite block must start a hi-table byte"
.assert (ES_O_COUNT_PAD + 3) .MOD 4 = 0, error, "split_v_obj: the sprite block must END on a hi-table byte, or the last byte has an owner this draw does not know about"
SV_HI_FIRST = ES_O_FIGHTER1 / 4
SV_HI_LAST  = (ES_O_COUNT_PAD + 3 - 1) / 4

SV_OBJ_REGS = $4300 + ES_D_SV_OBJ_UP_CH * 16

; --- sv_obj_up_dma: one VRAM upload. VMADD must already be set by the caller -
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count, A = source
;  bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer CONSUMES it — so it is armed HERE, once per
; call. There are two sheets to upload now, which is exactly the multi-transfer
; shape a once-outside-the-loop DAS write breaks silently: the first transfer
; moves its bytes and every later one moves none.
sv_obj_up_dma:
    .a16
    .i16
    stx a:SV_OBJ_REGS + 2           ; A1T
    sty a:SV_OBJ_REGS + 5           ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:SV_OBJ_REGS + 4           ; A1B — the bank byte the caller passed
    lda #ES_D_SV_OBJ_UP_DMAP
    sta a:SV_OBJ_REGS + 0
    lda #ES_D_SV_OBJ_UP_BBAD
    sta a:SV_OBJ_REGS + 1
    lda #(1 << ES_D_SV_OBJ_UP_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    rts

; --- sv_obj_up: both sheets, each into its own OBJ name table ---------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; TWO DESTINATIONS, TWO CLAIMS, NEITHER NARRATED AS AN OFFSET FROM THE OTHER.
; Both VMADDs are emitted symbols; the only thing derived from their difference
; is OBSEL's gap field, and that is asserted at the top of this file.
sv_obj_up:
    .a16
    .i16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the fighter sheet's claimed base
    ldx #.loword(sv_knight_chr_bin)
    ldy #ES_R_SV_KNIGHT_CHR_SIZE
    lda #^sv_knight_chr_bin
    jsr sv_obj_up_dma
    lda #ES_V_HUD_CHR
    sta a:$2116                     ; ...and the HUD sheet's
    ldx #.loword(sv_hud_chr_bin)
    ldy #ES_R_SV_HUD_CHR_SIZE
    lda #^sv_hud_chr_bin
    jsr sv_obj_up_dma
    rts

; --- sv_obj_pal: one OBJ palette, CPU-side ---------------------------------
; Same inline shape as split_v_bg's SV_PAL_UP and for the same reason: the
; loop bound is a different assemble-time constant per palette, so a shared
; routine would need a runtime count, which here is a CLAIM.
;
; WIDTH-RISK: entered A16/I16, toggles A8 per byte store, restores A16 before
; the loop test. X arrives zeroed and leaves at `size`.
.macro SV_OBJ_PAL_UP sv_at, sv_blob, sv_size
    .local loop
    sep #$20
    .a8
    lda #sv_at
    sta a:$2121                     ; CGADD
    rep #$20
    .a16
    ldx #0
loop:
    lda f:sv_blob, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #sv_size
    bcc loop
.endmacro

; --- sv_obj_arm: OBSEL + the fighter CHR and palettes, once, at scene enter -
; In/out: A16/I16, DB=0, forced blank (OBSEL is a forced-blank-only write).
; Clobbers A, X, Y.
;
; WITHOUT the two uploads below this feature renders COLOUR NOISE: OBJ VRAM and
; CGRAM 128.. Are random at power-on (rule 5), and OAM pointing at them is a
; perfectly valid sprite made of garbage. It looked exactly like a CHR-format
; bug on first boot.
sv_obj_arm:
    .a16
    .i16
    jsr sv_obj_up
    SV_OBJ_PAL_UP ES_C_KNIGHT_PAL_R, sv_knight_pal_r_bin, ES_R_SV_KNIGHT_PAL_R_SIZE
    SV_OBJ_PAL_UP ES_C_KNIGHT_PAL_B, sv_knight_pal_b_bin, ES_R_SV_KNIGHT_PAL_B_SIZE
    SV_OBJ_PAL_UP ES_C_BLADE_PAL, sv_blade_pal_bin, ES_R_SV_BLADE_PAL_SIZE
    sep #$20
    .a8
    ; OBSEL: size pair 3 (16x16 / 32x32) in bits 7:5, the name-select GAP in
    ; bits 4:3, the name base in bits 2:0. The base is the allocator's encoding
    ; of the obj_chr claim and the gap is derived from the two claims' emitted
    ; bases — this file never narrates either from a VRAM word address.
    lda #SV_OBSEL
    sta a:$2101
    rep #$20
    .a16
    rts

; --- sv_anim_tile: the current step's tile, out of the table blob -----------
; In: A16/I16, DB=0. A = anim state (ALSO the sv_anim stride index),
;  X = step index within that table. Out: A = the frame's first tile, high byte
;  cleared. Clobbers A, X, and US_TILE — which is the caller's own destination
;  for the result, so the scratch costs nothing.
;
; Naming each table at ASSEMBLE time is the obvious shape and forces a branch
; chain per call site, in the clock AND again in the draw. Here the six tables
; are one blob on a fixed stride and the state word indexes it (brawler's
; shape).
sv_anim_tile:
    .a16
    .i16
    .assert SV_ANIM_STRIDE = 4, error, "sv_anim_tile's shift chain assumes a 4-byte stride"
    asl a
    asl a                           ; state * SV_ANIM_STRIDE
    sta z:US_TILE                   ; the table's byte offset into the blob
    txa
    clc
    adc z:US_TILE                   ; + the step index
    tax
    lda f:sv_anim_bin, x            ; the byte entry (+1 stray high byte)
    and #$00FF
    rts

; --- sv_obj_put: one sprite's OAM entry, plus its two hi-table bits --------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  Y = the sprite's screen x (bit 8 becomes X9)
;  US_TILE = the OAM tile byte
;  US_ATTR = the OAM attribute byte, | SV_SIZE_LARGE for a 32x32 sprite
;  US_OY   = the sprite's screen y
; Out: clobbers A, Y and US_TILE. X survives (the phx/plx pair below).
;
; FIVE ARGUMENTS, THREE OF THEM IN DP, because there are now two sprite SIZES
; and two sprite HEIGHTS to place: the fighters leave the floor when they jump,
; and the HUD sits at a fixed screen row in the 16x16 half of the OBSEL pair.
; A y baked into this routine was right while every sprite stood on the same
; line and is exactly what a jump breaks.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED. A fighter walks to both
; arena walls, and at the left wall its centred 32px box puts x below zero —
; which as a 16-bit value has bit 8 set. Drop X9 and the low byte wraps to a
; small positive number and the fighter reappears on the RIGHT of the screen,
; which on a rail whose whole subject is which-half-is-which would read as the
; split being broken rather than the sprite.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — two pha/pla pairs and one
; phx/plx pair, and every arm passes through all of them. A push taken in A16
; and pulled in A8 would drift the stack by a byte per sprite per frame.
sv_obj_put:
    .a16
    .i16
    lda z:US_ATTR
    and #$00FF                      ; SV_SIZE_LARGE is bit 9: an argument to
                                    ; THIS routine, never an OAM attribute bit
    xba
    ora z:US_TILE
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:US_OY
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 cleared, next line)
    sep #$20
    .a8
    tya
    sta a:ES_OAM_SHADOW + 0, x      ; byte 0 = x's low eight bits
    rep #$20
    .a16
    ; ---- the hi-table field: 2 bits, at (slot & 3) * 2 ---------------------
    phx
    txa
    .repeat 2
        lsr
    .endrepeat
    and #3
    pha                             ; which field within the byte
    lda z:US_ATTR
    and #SV_SIZE_LARGE
    beq :+
    lda #SV_OBJ_LARGE               ; the caller asked for the pair's LARGE half
    bra :++
:   .a16
    .i16
    lda #0                          ; ...or its small one
:   .a16
    .i16
    sta z:US_TILE                   ; dead: the tile byte is already committed
    tya
    xba
    and #1                          ; x bit 8 -> X9
    ora z:US_TILE                   ; ...| the size bit chosen just above
    ply                             ; Y = field index (pushed in A16, pulled I16)
@shift:
    .a16
    .i16
    cpy #0
    beq @placed
    asl
    asl
    dey
    bra @shift
@placed:
    .a16
    .i16
    pha                             ; the positioned bits, while X is rebuilt
    txa
    .repeat 4
        lsr                         ; slot byte offset >> 4 = hi byte index
    .endrepeat
    tax
    pla
    sep #$20
    .a8
    ora a:SV_HI_BASE, x             ; OR, not store: the slots share this byte
    sta a:SV_HI_BASE, x             ;   and sv_obj_draw cleared it once
    rep #$20
    .a16
    plx
    rts

; --- sv_obj_draw: both fighters, every frame -------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE SIDE-SWAP IS RE-DECIDED EVERY FRAME, not tracked. Each fighter's screen
; position is derived against the camera of the half it is CURRENTLY in, and
; which half that is comes from comparing the two world x's right here. That is
; why a crossover needs no special case: the frame after they pass, the
; comparison flips and both fighters are drawn against the other camera.
; Tracking a "who is left" flag instead would need a fix-up on the crossing
; frame, and that fix-up is where a side-swap bug would live.
;
; Each fighter faces the centre, so the one on the left is H-flipped... And
; which one that is changes on a crossover too — hence the flip is picked from
; the same comparison, not baked into the fighter.
sv_obj_draw:
    .a16
    .i16
    ; The five hi-table bytes our twenty slots fill are cleared once, here, so
    ; sv_obj_put can OR into them without inheriting last frame's X9 or size
    ; bits. Cleared as a RANGE rather than by name: the count follows the
    ; claims, and the two asserts above pin the range to whole bytes.
    ldx #SV_HI_FIRST
    sep #$20
    .a8
@hi_clear:
    .a8
    .i16
    stz a:SV_HI_BASE, x
    inx
    cpx #(SV_HI_LAST + 1)
    bcc @hi_clear
    rep #$20
    .a16
    ; ---- who is on the left? ---------------------------------------------
    lda z:US_FX1
    cmp z:US_FX2
    bcc @f1_left
    ; fighter 2 is left: it faces right (no flip), fighter 1 faces left
    jsr sv_cam_left
    lda #(SV_ATTR_PRIO | SV_PAL_BLUE)
    ldx #(ES_O_FIGHTER2 * 4)
    ldy #2                          ; fighter 2's half of every state pair
    jsr sv_obj_one                  ; blue, LEFT half
    jsr sv_cam_right
    lda #(SV_ATTR_PRIO | SV_ATTR_HFLIP | SV_PAL_RED)
    ldx #(ES_O_FIGHTER1 * 4)
    ldy #0
    jsr sv_obj_one                  ; red, RIGHT half
    bra @hud
@f1_left:
    .a16
    .i16
    jsr sv_cam_left
    lda #(SV_ATTR_PRIO | SV_PAL_RED)
    ldx #(ES_O_FIGHTER1 * 4)
    ldy #0
    jsr sv_obj_one                  ; red, LEFT half
    jsr sv_cam_right
    lda #(SV_ATTR_PRIO | SV_ATTR_HFLIP | SV_PAL_BLUE)
    ldx #(ES_O_FIGHTER2 * 4)
    ldy #2
    jsr sv_obj_one                  ; blue, RIGHT half
@hud:
    .a16
    .i16
    ldy #0
    jsr sv_blade_draw               ; ...each fighter's blade, if it is swinging
    ldy #2
    jsr sv_blade_draw
    jsr sv_life_draw
    jsr sv_count_draw
    rts

; =============================================================================
; THE BLADE — excalibur_'s own swing, composited over its fighter
; =============================================================================
; The camelot character sheets carry NO attack pose (their READ ME maps the
; rows: idle / run / jump-idle / jump-run / turn / hit / death). The pack's
; design is that the WEAPON carries the attack — excalibur_.png ships the swing
; as its own 32x32 frames, drawn in the CHARACTER's box — so an attack here is
; a body pose plus a blade sprite at the same screen position, and the impact
; is the defender playing the character sheet's real `hit` row.
;
; DRAWN ONLY WHILE THE SWING RUNS, parked otherwise. A blade carried at rest
; would need a seventeenth frame in a name table that holds exactly sixteen —
; and a sword that appears for the swing and is gone again is the read the
; pack's own frames are drawn for.

; The blade's four frames follow the body's twelve on the same name table, so
; their first tiles come from the SAME layout rule (four frames per 64-tile
; group). Restated rather than pasted, as the HUD's slots are.
SV_BLADE_SLOT0 = 12
.assert SV_BLADE_SLOT0 = 12, error, "the blade's first slot no longer follows the body's twelve frames"

; SWG -> which of the four the blade is on, indexed by the swing's own
; countdown. A table rather than a division: SV_SWING_LEN is 20, which is not a
; shift, and the timing is a FEEL that wants tuning independently of the frame
; count. Index 0 is never read (swg 0 is not a swing) and is present so the
; countdown indexes the table directly.
;
; The strike frame is held across the whole ACTIVE window, so the frame a
; player sees when the hit lands is the full arc rather than whatever the
; timing happened to reach.
sv_blade_step:
    .byte 0
    .byte 0, 0                      ; swg 1..2   the blade back to vertical
    .byte 1, 1                      ; swg 3..4
    .byte 2, 2                      ; swg 5..6
    .byte 3, 3, 3, 3, 3, 3, 3, 3    ; swg 7..14  THE ACTIVE WINDOW: the full arc
    .byte 2, 2                      ; swg 15..16
    .byte 1, 1                      ; swg 17..18
    .byte 0, 0                      ; swg 19..20 the raise
sv_blade_step_end:
.assert (sv_blade_step_end - sv_blade_step) = SV_SWING_LEN + 1, error, "the blade's timing table does not cover the swing's countdown"
.assert SV_SWING_FIRST = 7 && SV_SWING_LAST = 14, error, "the swing's active window moved; the blade's timing table still holds the arc over 7..14"

; --- sv_blade_draw: one fighter's blade -----------------------------------
; In/out: A16/I16, DB=0. Y = the fighter's pair index (0 or 2). Clobbers A, X, Y.
;
; The blade rides the fighter's OWN screen position: sv_obj_one has just placed
; that fighter against its half's camera, and re-deriving the position here
; would let the two disagree for a frame. So the body's committed OAM entry is
; read back and the blade is placed on it — one producer, and the blade cannot
; slide off the hand.
sv_blade_draw:
    .a16
    .i16
    tyx
    lda z:US_SWG, x
    bne @swinging
    ; not swinging: park the blade, off the display and out of the hi byte
    lda #SV_PARK_Y32                ; the 32-tall constant: parking a 32x32
                                    ;   sprite at the 16x16 one wraps sixteen
                                    ;   of its rows onto scanlines 0..15
    sta z:US_OY
    stz z:US_TILE
    lda #(SV_ATTR_PRIO | SV_PAL_BLADE)
    sta z:US_ATTR
    bra @place
@swinging:
    .a16
    .i16
    tax                             ; X = the swing's countdown
    lda f:sv_blade_step, x          ; the byte entry (+1 stray high byte)
    and #$00FF
    asl a
    asl a                           ; ...one 32x32 frame is four tiles wide
    clc
    adc #(SV_BLADE_SLOT0 / 4 * 64)  ; the blade's own grid group
    sta z:US_TILE
    ; the body's committed entry gives the blade its y and its H-flip
    tya
    asl a
    sta z:US_SLOT                   ; pair index 0/2 -> OAM byte offset 0/4
    ldx z:US_SLOT
    lda a:ES_OAM_SHADOW + 0, x
    xba
    and #$00FF
    sta z:US_OY                     ; byte 1 of the entry = the body's y
    lda a:ES_OAM_SHADOW + 2, x
    xba
    and #$00FF
    and #SV_ATTR_HFLIP              ; ...and its facing, so the arc sweeps the
                                    ;    way the fighter is looking
    ora #(SV_ATTR_PRIO | SV_PAL_BLADE)
    sta z:US_ATTR
@place:
    .a16
    .i16
    lda #SV_SIZE_LARGE
    ora z:US_ATTR
    sta z:US_ATTR
    ; the body's x, low byte and X9 together, so the blade inherits the wrap
    tya
    asl a
    tax
    lda a:ES_OAM_SHADOW + 0, x
    and #$00FF
    sta z:US_SLOT
    phy
    tya
    lsr a
    tax                             ; X = the fighter's OAM SLOT, not its pair
                                    ;   index: its two hi bits sit at slot * 2,
                                    ;   so slots 0 and 1 are bits 0 and 2. Using
                                    ;   the pair index here shifts fighter 2's
                                    ;   read two bits too far and returns the
                                    ;   BLADE's own X9 from earlier this frame
    lda a:SV_HI_BASE + (ES_O_FIGHTER1 / 4)
    and #$00FF
@shift:
    .a16
    .i16
    cpx #0
    beq @have_x9
    lsr a
    lsr a
    dex
    bra @shift
@have_x9:
    .a16
    .i16
    and #$0001
    xba                             ; X9 back into bit 8 of the 9-bit x
    clc
    adc z:US_SLOT
    tay                             ; Y = the body's screen x, all nine bits
    pla                             ; the pair index (pushed in A16)
    asl a
    clc
    adc #(ES_O_BLADE * 4)
    tax                             ; X = the blade's slot byte offset
    jsr sv_obj_put
    rts

; --- sv_cam_left / sv_cam_right: select the half's camera ------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Derived from the SAME ES_SV_MID / ES_SV_SPREAD pair split_v_bg's VBlank
; commit uses for BG1HOFS / BG2HOFS. That shared origin is the whole reason a
; fighter cannot drift against its own half: if these were tracked separately
; the sprite and the background would disagree for one frame after every
; change, which reads as the fighter sliding on the floor.
sv_cam_left:
    .a16
    .i16
    lda z:ES_SV_MID
    sec
    sbc z:ES_SV_SPREAD
    and #$00FF                      ; the stage map is 256 px periodic
    sta z:ES_SV_OCAM
    rts

sv_cam_right:
    .a16
    .i16
    lda z:ES_SV_MID
    clc
    adc z:ES_SV_SPREAD
    and #$00FF
    sta z:ES_SV_OCAM
    rts

; --- sv_obj_one: place one fighter against the camera of its half ----------
; In: A16/I16, DB=0. A = attr byte (low 8 bits), X = slot byte offset,
;  Y = the fighter's INDEX into every state pair (0 or 2).
; Out: clobbers A, X, Y.
;
; screen x = world x - camera - half the sprite box. The camera used is the one
; for the half this fighter is in, and BOTH cameras are the same shadow pair
; split_v_bg commits, so a fighter and its half can never disagree about where
; the world is.
;
; THE TILE AND THE Y BOTH COME FROM STATE NOW. The tile is the animation
; table's current step, and the y is the floor line less the jump height's
; INTEGER part — so a fighter in the air is drawn in the air rather than
; sliding along the ground with an airborne pose.
;
; WIDTH-RISK: entered and left A16/I16 throughout; sv_obj_put is the only
; width-toggling callee and it restores A16 before returning.
sv_obj_one:
    .a16
    .i16
    sta z:US_ATTR                   ; the attribute, until sv_obj_put reads it
    lda #SV_SIZE_LARGE
    ora z:US_ATTR
    sta z:US_ATTR                   ; ...both fighters are the pair's LARGE half
    phx                             ; the slot byte offset, over the two lookups
    ; ---- the animation step's tile ---------------------------------------
    tyx                             ; X = this fighter's pair index
    phy                             ; ...saved, because X is about to hold the
                                    ;    STEP rather than the fighter
    lda z:US_AFR, x
    tay                             ; Y = the step within the table
    lda z:US_AST, x                 ; A = the table (the anim state)
    tyx                             ; X = the step: sv_anim_tile's arguments
    jsr sv_anim_tile
    sta z:US_TILE
    ply
    ; ---- y = the floor line, less the jump height's integer part ----------
    tyx
    lda z:US_JMP, x
    xba
    and #$00FF                      ; jump height in whole px (8.8 -> integer)
    sta z:US_OY
    lda #SV_KNIGHT_Y
    sec
    sbc z:US_OY
    and #$00FF                      ; a hop can never reach the top of the
                                    ; screen (SV_JUMP_V0 and SV_GRAV bound the
                                    ; apex well inside it), so this only guards
                                    ; the byte the OAM y actually is
    sta z:US_OY
    ; ---- screen x --------------------------------------------------------
    lda z:US_FX1, x                 ; the pair index selects the fighter's x,
                                    ; exactly as it selected its state above
    sec
    sbc z:ES_SV_OCAM                ; the camera of THIS fighter's half
    and #$00FF                      ; THE WORLD DELTA IS REDUCED MOD 256 FIRST.
                                    ; The stage is 256 px periodic, so a camera
                                    ; that has wrapped (cam 220, fighter at 28)
                                    ; gives a raw difference of -192 whose
                                    ; correct screen meaning is +64.
                                    ; Subtracting the sprite half-width BEFORE
                                    ; this reduction carries the wrap into bit
                                    ; 8, which the OBJ hardware reads as X9 --
                                    ; the sprite is then placed past the right
                                    ; edge and simply does not appear. That is
                                    ; exactly how the LEFT fighter went missing
                                    ; at full split while the right one
                                    ; rendered perfectly.
    sec
    sbc #SV_KNIGHT_HALF             ; centre the 32 px box on the fighter
    and #$01FF                      ; ...THEN to the OBJ's 9-bit space, where
                                    ; bit 8 is X9 and a small negative x means
                                    ; "half off the left edge", which is now
                                    ; the only thing bit 8 can mean here
    tay                             ; Y = screen x
    plx                             ; ...and X is the slot byte offset again
    jsr sv_obj_put
    rts

; =============================================================================
; THE SPRITE HUD — life bars and the round-start count
; =============================================================================
; There is no text layer on this rail (bg_text claims BG3SC/BG34NBA and BG3 IS
; the divider), so both of these are OBJs out of the second name table. They
; are drawn in SCREEN space, not world space: a life bar that scrolled with a
; camera would be a second thing to read the split against, and the split is
; what the picture is for.

; --- sv_life_draw: both bars, every frame ----------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; EVERY SEGMENT IS DRAWN EVERY FRAME, spent ones switching TILE rather than
; vanishing: a bar that loses cells reads as a shorter bar, not as damage. P1's
; bar fills from the left edge and P2's from the right, so damage eats INWARD
; on both and the two are mirror images at a glance.
sv_life_draw:
    .a16
    .i16
    ldy #0                          ; Y = segment index, 0..SV_HP_MAX-1
@seg:
    .a16
    .i16
    ; ---- fighter 1: segment Y outward from the LEFT edge ------------------
    jsr sv_life_step
    clc
    adc #SV_LIFE_X1
    ldx #0                          ; the pair index: fighter 1
    jsr sv_life_one
    ; ---- fighter 2: segment Y outward from the RIGHT edge -----------------
    jsr sv_life_step
    sta z:US_SLOT                   ; scratch, before the tile lookup wants it
    lda #SV_LIFE_X2
    sec
    sbc z:US_SLOT                   ; leftward, so damage eats INWARD on both
    ldx #2
    jsr sv_life_one
    iny
    cpy #SV_HP_MAX
    bcc @seg
    rts

; --- sv_life_step: the segment's own offset along its bar ------------------
; In/out: A16/I16, DB=0. Y = segment index. Out: A = Y * 16, the frame's own
; width, so the segments touch and the bar reads as one run. Clobbers A.
sv_life_step:
    .a16
    .i16
    tya
    .repeat 4
        asl a
    .endrepeat
    rts

; --- sv_life_one: one segment of one bar -----------------------------------
; In: A16/I16, DB=0. A = the segment's screen x, X = the fighter's pair index
;  (0 or 2), Y = the segment index. Out: X and Y survive; clobbers A, US_*.
;
; WIDTH-RISK: three pushes and three pulls, all in A16/I16, and they nest —
; [seg][pair][x] in, x out first because it is wanted first. Every arm passes
; through all six.
sv_life_one:
    .a16
    .i16
    phy                             ; the segment index, over sv_obj_put
    phx                             ; the pair index, over sv_obj_put
    pha                             ; ...and the screen x, over the tile choice
    jsr sv_life_tile                ; US_TILE = full or spent, for THIS segment
    ; slot = ES_O_LIFE + (pair index / 2) * SV_HP_MAX + segment
    .assert (1 << SV_HP_SHIFT) = SV_HP_MAX, error, "the life claim's per-fighter stride is not a power of two, so this shift cannot express it"
    txa
    lsr a                           ; pair index 0/2 -> fighter 0/1
    .repeat SV_HP_SHIFT
        asl a                       ; ...* SV_HP_MAX, its own half of the claim
    .endrepeat
    sta z:US_SLOT
    tya
    clc
    adc z:US_SLOT
    asl a
    asl a
    clc
    adc #(ES_O_LIFE * 4)
    sta z:US_SLOT                   ; the slot's BYTE offset in the shadow
    ; the team colour, from the same pair index the segment count came from
    lda #(SV_ATTR_PRIO | SV_PAL_RED | SV_ATTR_NAME1)
    cpx #0
    beq :+
    lda #(SV_ATTR_PRIO | SV_PAL_BLUE | SV_ATTR_NAME1)
:   .a16
    .i16
    sta z:US_ATTR
    lda #SV_LIFE_Y
    sta z:US_OY
    pla                             ; the screen x again
    tay
    ldx z:US_SLOT
    jsr sv_obj_put
    plx                             ; the pair index
    ply                             ; ...and the segment index
    rts

; --- sv_life_tile: is this segment still standing? -------------------------
; In: A16/I16, DB=0. X = the fighter's pair index (0 or 2), Y = segment index.
; Out: US_TILE = the full or the empty segment's tile. Clobbers A.
sv_life_tile:
    .a16
    .i16
    lda #SV_H_LIFE_FULL
    sta z:US_TILE
    tya
    cmp z:US_HP, x
    bcc :+                          ; segment index < hp: still standing
    lda #SV_H_LIFE_EMPTY
    sta z:US_TILE
:   .a16
    .i16
    rts

; --- sv_count_draw: the round-start count, or nothing ----------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE GLYPH IS DERIVED FROM THE ROUND TIMER, never kept beside it. A second
; word holding "which beat" is a word that can disagree with the clock that
; drives it, and the disagreement is invisible for exactly one frame — the one
; a capture lands on.
;
; Outside the countdown every claimed slot is PARKED rather than skipped: an
; entry left where last round put it is a perfectly valid sprite showing a
; stale glyph, and slots are pinned here precisely so a test can read one.
sv_count_draw:
    .a16
    .i16
    lda z:US_RSTATE
    cmp #SV_R_COUNT
    beq @live
    jmp sv_count_park
@live:
    .a16
    .i16
    ; beat = (rtimer - 1) / SV_COUNT_STEP, counting down 3, 2, 1, 0
    lda z:US_RTIMER
    dec a
    .repeat SV_COUNT_SHIFT
        lsr a
    .endrepeat
    bne @digit
    jmp sv_count_fight              ; beat 0: the word, not a digit
@digit:
    .a16
    .i16
    ; The three digits sit at consecutive HUD slots in count-DOWN order, so the
    ; beat indexes them directly rather than through a branch chain.
    .assert SV_H_D2 = SV_H_D3 + 2, error, "the countdown digits are no longer consecutive HUD slots"
    .assert SV_H_D1 = SV_H_D3 + 4, error, "the countdown digits are no longer consecutive HUD slots"
    eor #$FFFF
    inc a
    clc
    adc #3                          ; beat 3 -> 0, beat 1 -> 2
    asl a                           ; ...one HUD slot is two tiles
    clc
    adc #SV_H_D3
    sta z:US_TILE
    lda #(SV_ATTR_PRIO | SV_PAL_RED | SV_ATTR_NAME1)
    sta z:US_ATTR
    lda #SV_COUNT_Y
    sta z:US_OY
    ldx #(ES_O_COUNT * 4)
    ldy #SV_COUNT_DIGIT_X
    jsr sv_obj_put
    ldy #1                          ; the other four slots hold nothing
    jmp sv_count_park_from

; --- sv_count_fight: F I G H T, one sprite each ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
sv_count_fight:
    .a16
    .i16
    ldy #0
@letter:
    .a16
    .i16
    phy                             ; the letter index, over the placement
    tyx
    lda f:sv_count_word, x          ; the byte entry (+1 stray high byte)
    and #$00FF
    sta z:US_TILE                   ; ...the letter's HUD slot tile
    lda #(SV_ATTR_PRIO | SV_PAL_RED | SV_ATTR_NAME1)
    sta z:US_ATTR
    lda #SV_COUNT_Y
    sta z:US_OY
    tya
    asl a
    asl a
    clc
    adc #(ES_O_COUNT * 4)
    sta z:US_SLOT                   ; the slot's byte offset in the shadow
    tya
    .repeat 4
        asl a                       ; letter * 16 px: the frame's own width
    .endrepeat
    clc
    adc #SV_COUNT_WORD_X
    tay                             ; Y = screen x
    ldx z:US_SLOT
    jsr sv_obj_put
    ply
    iny
    cpy #SV_COUNT_LETTERS
    bcc @letter
    rts

; --- sv_count_park / sv_count_park_from: the count's slots, off screen -----
; In/out: A16/I16, DB=0. Y = the first slot to park. Clobbers A, X, Y.
;
; PARKED AT 240, NOT SKIPPED. A skipped slot keeps whatever the previous round
; left in it, which is a valid sprite showing a stale glyph. 240 puts a 16-tall
; sprite entirely below the 224-line display and exactly at OAM y's mod-256
; wrap — a 32-tall one parked there would poke 16 rows back onto scanlines
; 0..15 (brawler_obj's measured trap), which is why only the SMALL half of the
; pair is ever parked here.
.assert SV_PARK_Y + 16 <= 256, error, "a 16-tall sprite parked here wraps onto the visible lines"
.assert SV_PARK_Y32 + 32 <= 256, error, "a 32-tall sprite parked here wraps onto the visible lines"
.assert SV_PARK_Y32 >= 224, error, "the parked 32x32 sprite is inside the 224-line display"
sv_count_park:
    .a16
    .i16
    ldy #0
sv_count_park_from:
    .a16
    .i16
    lda #SV_PARK_Y
    sta z:US_OY
    stz z:US_TILE
    lda #(SV_ATTR_PRIO | SV_ATTR_NAME1)
    sta z:US_ATTR
@park:
    .a16
    .i16
    phy                             ; the slot index, over sv_obj_put
    tya
    asl a
    asl a
    clc
    adc #(ES_O_COUNT * 4)
    tax
    ldy #0                          ; x = 0, and X9 clear with it
    jsr sv_obj_put
    ply
    iny
    cpy #SV_COUNT_LETTERS
    bcc @park
    rts

; The word, as HUD slot tiles. A table rather than five stores: the letters'
; slots are not consecutive (the sheet wraps to its second grid row-group at
; slot 8), so an index-arithmetic form would have to encode the wrap.
sv_count_word:
    .byte SV_H_F, SV_H_I, SV_H_G, SV_H_H, SV_H_T
sv_count_word_end:
.assert (sv_count_word_end - sv_count_word) = SV_COUNT_LETTERS, error, "the countdown word's length disagrees with the slots claimed for it"
