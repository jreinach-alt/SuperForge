; =============================================================================
; split_v_obj.asm — the two fighters
; =============================================================================
; One 32x32 knight in OBJ VRAM, drawn twice: fighter 1 on OBJ palette 0 (red
; team), fighter 2 on palette 1 (blue). The team colour is what makes a
; side-swap legible, and doing it with palettes rather than a second CHR copy
; is why the vram claim is one sprite's worth.
;
; THE FEET ANCHOR IS 28, NOT 32. The art does not fill its 32x32 box: its
; lowest drawn row is 28 (tools/gen_split_v_assets.py derives and prints this).
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

; The size bit in the hi table. Each hi-table byte covers FOUR sprites, two
; bits each: bit0 of the field = X9, bit1 = size. OBSEL's pair 3 is small 16x16
; / large 32x32, so "large" is what makes these 32x32.
SV_OBJ_LARGE = $02

; The knight's first tile within the OBJ CHR page. OBSEL's name base already
; points at the claim, so this is an offset INTO it — tile 0 of our own page.
SV_KNIGHT_TILE = 0

; OBSEL's size-pair field, bits 7:5. Pair 3 = small 16x16 / large 32x32, which
; is the pair that HAS a 32x32 half for these fighters. Written as a shifted
; ordinal rather than the equivalent hex byte because no_literals reads a bare
; `$60` as a raw ADDRESS operand -- correctly, since it cannot know which
; literals are hardware field values. Naming the field says what it is.
SV_OBSEL_PAIR3 = 3 << 5

SV_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

SV_OBJ_REGS = $4300 + ES_D_SV_OBJ_UP_CH * 16

; --- sv_obj_up: the fighter CHR into OBJ VRAM ------------------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y. DAS is re-armed
; inside, per transfer -- one arming site, single-shot register.
sv_obj_up:
    .a16
    .i16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the claim'"'"'s base word
    ldx #.loword(sv_knight_chr_bin)
    stx a:SV_OBJ_REGS + 2           ; A1T
    ldy #ES_R_SV_KNIGHT_CHR_SIZE
    sty a:SV_OBJ_REGS + 5           ; DAS
    sep #$20
    .a8
    lda #^sv_knight_chr_bin
    sta a:SV_OBJ_REGS + 4           ; A1B
    lda #ES_D_SV_OBJ_UP_DMAP
    sta a:SV_OBJ_REGS + 0
    lda #ES_D_SV_OBJ_UP_BBAD
    sta a:SV_OBJ_REGS + 1
    lda #(1 << ES_D_SV_OBJ_UP_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    rts

; --- sv_obj_pal: one OBJ palette, CPU-side ---------------------------------
; Same inline shape as split_v_bg'"'"'s SV_PAL_UP and for the same reason: the
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
    sep #$20
    .a8
    ; OBSEL: size pair 3 (16x16 / 32x32) in bits 7:5, name base in bits 2:0.
    ; The base is the allocator's encoding of the obj_chr claim — this file
    ; never derives it from the VRAM word address itself.
    lda #(SV_OBSEL_PAIR3 | ES_V_OBJ_CHR_OBSEL_BASE)
    sta a:$2101
    rep #$20
    .a16
    rts

; --- sv_obj_put: one fighter's OAM entry, plus its two hi-table bits -------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  Y = the fighter's screen x (bit 8 becomes X9)
; Out: clobbers A, X, Y.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED. A fighter walks to both
; arena walls, and at the left wall its centred 32px box puts x below zero —
; which as a 16-bit value has bit 8 set. Drop X9 and the low byte wraps to a
; small positive number and the fighter reappears on the RIGHT of the screen,
; which on a rail whose whole subject is which-half-is-which would read as the
; split being broken rather than the sprite.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one pha/pla pair and one
; phx/plx pair, and every arm passes through both. A push taken in A16 and
; pulled in A8 would drift the stack by a byte per sprite per frame.
sv_obj_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda #SV_KNIGHT_Y
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
    tya
    xba
    and #1                          ; x bit 8 -> X9
    ora #SV_OBJ_LARGE               ; ...| the size bit: both fighters are 32x32
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
    ; The hi-table byte our four slots share is cleared once, here, so
    ; sv_obj_put can OR into it without inheriting last frame's X9 bits.
    sep #$20
    .a8
    stz a:SV_HI_BASE + (ES_O_FIGHTER1 / 4)
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
    ldy z:US_FX2
    jsr sv_obj_one                  ; blue, LEFT half
    jsr sv_cam_right
    lda #(SV_ATTR_PRIO | SV_ATTR_HFLIP | SV_PAL_RED)
    ldx #(ES_O_FIGHTER1 * 4)
    ldy z:US_FX1
    jsr sv_obj_one                  ; red, RIGHT half
    rts
@f1_left:
    .a16
    .i16
    jsr sv_cam_left
    lda #(SV_ATTR_PRIO | SV_PAL_RED)
    ldx #(ES_O_FIGHTER1 * 4)
    ldy z:US_FX1
    jsr sv_obj_one                  ; red, LEFT half
    jsr sv_cam_right
    lda #(SV_ATTR_PRIO | SV_ATTR_HFLIP | SV_PAL_BLUE)
    ldx #(ES_O_FIGHTER2 * 4)
    ldy z:US_FX2
    jsr sv_obj_one                  ; blue, RIGHT half
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
;  Y = the fighter's WORLD x.
; Out: clobbers A, X, Y.
;
; screen x = world x - camera - half the sprite box. The camera used is the one
; for the half this fighter is in, and BOTH cameras are the same shadow pair
; split_v_bg commits, so a fighter and its half can never disagree about where
; the world is.
;
; WIDTH-RISK: entered and left A16/I16 throughout; sv_obj_put is the only
; width-toggling callee and it restores A16 before returning.
sv_obj_one:
    .a16
    .i16
    pha                             ; the attr byte, while x is computed
    tya
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
    pla
    xba                             ; attr into the high byte
    ora #SV_KNIGHT_TILE             ; ...| the tile number in the low byte
    jsr sv_obj_put
    rts
