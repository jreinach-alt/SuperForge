; =============================================================================
; met_obj.asm — the meteor_event rail's OBJ cast: arm, park, put
; =============================================================================
; Arming (once, at boot): one sprite sheet into OBJ VRAM, one OBJ palette into
; CGRAM, OBSEL, then every claimed slot parked. Bs_obj.asm's shape, with the
; arm hoisted out of a scene's `enter` because this feature is GLOBAL — its CHR
; and palette must be standing in BOTH scenes, and re-uploading them at each
; `enter` would re-upload identical bytes twice per event for nothing.
;
; Drawing: the scenes write slots through `met_put`. There is no per-frame
; rebuild of the whole table — SuperForge's OAM shadow is STATE, so the CAPTURE
; writes its blocks once and they stand through the scene transition, which is
; the property that lets the captured ground survive the swap at all.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED (mo_obj's discipline), and
; on this rail it actually FIRES: the sprite-phase meteor enters from off the
; top-LEFT with its centre at x 4, so a 32x32 frame's top-left x is negative
; and bit 8 of the 16-bit value is what puts it off the left edge instead of
; wrapping it to the right of the screen.
;
; Must NOT set .p816/.smart — included into a parent that already does.

; The boot-time GP-DMA register file, addressed through the channel the
; met_obj_up dma_init claim names — a declared resource, not a hard-coded 0.
MET_OBJ_REGS = $4300 + ES_D_MET_OBJ_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE.
MET_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; This feature's DP scratch (the met_draw claim), named.
MET_D_X    = 0                  ; 2 — the OAM x being placed (9-bit space)
MET_D_Y    = 2                  ; 2 — the OAM y being placed
MET_D_SIZE = 4                  ; 2 — the hi-table SIZE bit met_put ORs in:
                                ;  MET_LARGE for a 32x32 meteor frame, 0
                                ;  for the 16x16 cast (OBSEL size pair 3)
MET_D_TILE = 6                  ; 2 — tile|attr scratch for a computed tile

; Every slot this feature owns, as one contiguous byte range. The hi_pad claim
; sits immediately after `capture`, so the range ends at its end.
MET_SLOT_END = ES_O_HI_PAD + ES_O_HI_PAD_SPRITES

; ELEVEN whole hi-table bytes. Forty-four slots is exactly that, which is the
; reason the two pad slots are claimed — the byte has one owner and can be
; rebuilt whole (mo_obj's stale-size lesson).
MET_HI_BYTES = MET_SLOT_END / 4
.assert MET_SLOT_END = MET_HI_BYTES * 4, error, "met_obj's slot range must be a whole number of hi-table bytes"

; =============================================================================
; ARMING — once, at boot
; =============================================================================
; CONTRACT met_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the sheet, the palette, OBSEL and the park
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI off — init.inc's boot contract
;             rather than a scene's. Without these uploads the feature
;             renders COLOUR NOISE rather than nothing: OBJ VRAM and CGRAM
;             128.. are random at power-on (rule 5), and an entry pointing
;             at them is a perfectly valid sprite made of garbage
;   tail:     rts
;
; --- met_obj_arm: the sheet, the palette, OBSEL, the park ------------------
;
; WITHOUT these uploads this feature renders COLOUR NOISE rather than nothing:
; OBJ VRAM and CGRAM 128.. Are random at power-on (rule 5), and an OAM entry
; pointing at them is a perfectly valid sprite made of garbage.
;
; DAS is SINGLE-SHOT — consumed by the transfer — so it is armed here, for this
; transfer. One sheet, one arming site.
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 for byte-wide channel
; registers and PPU ports, `sep #$20` only — I-width never moves.
met_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "met_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    lda #^met_obj_chr_bin
    sta a:MET_OBJ_REGS + 4          ; A1B = source bank
    lda #ES_D_MET_OBJ_UP_DMAP
    sta a:MET_OBJ_REGS + 0          ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_MET_OBJ_UP_BBAD
    sta a:MET_OBJ_REGS + 1          ; BBAD: VMDATAL, so B+1 = VMDATAH
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the sheet's base word
    ldx #.loword(met_obj_chr_bin)
    stx a:MET_OBJ_REGS + 2          ; A1T
    ldy #ES_R_MET_OBJ_CHR_SIZE
    sty a:MET_OBJ_REGS + 5          ; DAS, armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_MET_OBJ_UP_CH)
    sta a:$420B                     ; fire (boot: the channel regs are free)

    ; ---- the palette: sixteen words at OBJ palette 0 ----------------------
    lda #ES_C_OBJ_PAL
    sta a:$2121                     ; CGADD = 128, the claim's contract
    rep #$20
    .a16
    ldx #0
@pal:
    .a16
    .i16
    lda f:met_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MET_OBJ_PAL_SIZE
    bcc @pal

    ; ---- OBSEL: size pair 3 (16x16 / 32x32) + the OBJ name base -----------
    ; The base byte is the ALLOCATOR's encoding of the obj_chr claim (pinned
    ; past the Mode 7 region met_floor holds in the other scene). Size pair 3
    ; is the pair this cast needs: the capture blocks, the player and the
    ; FIERY specks are 16x16 while the ROCKY crossover frames are 32x32.
    sep #$20
    .a8
    lda #(ES_V_OBJ_CHR_OBSEL_BASE | (3 << 5))
    sta a:$2101
    rep #$20
    .a16
    jsr met_park_all
    rts

; --- met_park_all: every slot this feature owns, off the bottom ------------
; In/out: A16/I16, DB=0. Clobbers A, X. Called at boot and again by
; `level::enter`, which is what DROPS the captured ground when the cutscene
; hands control back — the captured ground is dropped the moment the cutscene
; is over.
met_park_all:
    .a16
    .i16
    ldx #(ES_O_PLAYER * 4)
@loop:
    .a16
    .i16
    lda #(MET_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #(MET_SLOT_END * 4)
    bcc @loop
    jsr met_hi_clear
    rts

; --- met_hi_clear: the eleven hi-table bytes this feature owns -------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Clearing before a rebuild is what lets met_put OR its two bits in without
; inheriting a stale X9 or SIZE (mo_hi_clear's lesson: the direction that hurts
; is a 16x16 rendered 32x32, sampling the twelve tiles after it).
;
; WIDTH-RISK: toggles A8 for the byte stores and restores A16.
met_hi_clear:
    .a16
    .i16
    sep #$20
    .a8
    ldx #0
    ; NOTE the label name: width_lint does not scope ca65's cheap locals to
    ; their parent global, so a second `@loop` in this file would be read as
    ; one label with both an a16 and an a8 arrival — a false
    ; annotation-contradicts-arrival against met_park_all's loop above.
@hi:
    .a8
    .i16
    stz a:MET_HI_BASE, x
    inx
    cpx #MET_HI_BYTES
    bcc @hi
    rep #$20
    .a16
    rts

; =============================================================================
; DRAWING
; =============================================================================
; --- met_put: one OAM entry, plus its two hi-table bits --------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  ES_MET_DRAW+MET_D_X = the OAM x (9 bits; bit 8 becomes X9),
;  +MET_D_Y = y, +MET_D_SIZE = MET_LARGE or 0
; Out: X preserved. Clobbers A, Y.
;
; bs_put's body, mechanism for mechanism: entry bytes 2-3 in one store, y into
; byte 1, x's low eight into byte 0, then the two hi-table bits shifted to
; (slot & 3) * 2 and OR'd into a byte met_hi_clear zeroed.
;
; The OR is why a caller that rewrites one slot must clear the hi table first
; (or accept the previous frame's bits) — on this rail the only per-frame
; callers are the player and the meteor sprite, and their tick clears the table
; before the pass, while the capture writes its blocks once into a table the
; same clear had just zeroed.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one phx/plx pair and one
; pha/pla pair, every arm passes through both. A push taken in A16 and pulled
; in A8 drifts the stack one byte per sprite per frame.
met_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:ES_MET_DRAW + MET_D_Y
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 written next)
    sep #$20
    .a8
    lda z:ES_MET_DRAW + MET_D_X
    sta a:ES_OAM_SHADOW + 0, x      ; byte 0 = x's low eight bits
    rep #$20
    .a16
    ; ---- the hi-table field: 2 bits, at (slot & 3) * 2 --------------------
    phx
    txa
    .repeat 2
        lsr
    .endrepeat
    and #3
    tay                             ; Y = which field within the byte
    lda z:ES_MET_DRAW + MET_D_X
    xba
    and #1                          ; x bit 8 -> X9 (derived, never assumed)
    ora z:ES_MET_DRAW + MET_D_SIZE  ; | the size bit the caller selected
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
    tay
    pla
    sep #$20
    .a8
    ora a:MET_HI_BASE, y            ; OR, not store: the other slots share this
    sta a:MET_HI_BASE, y            ;   byte and met_hi_clear zeroed it once
    rep #$20
    .a16
    plx
    rts

; --- met_park_slot: one slot, off-screen -----------------------------------
; In: A16/I16, DB=0. X = the slot's byte offset. Out: X preserved; clobbers A.
met_park_slot:
    .a16
    .i16
    lda #(MET_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    rts
