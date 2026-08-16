; =============================================================================
; rpg_obj.asm — the rpg rail's actors in OAM (scene-scoped)
; =============================================================================
; Two 16x16 actors: slot 0 the avatar, slot 1 a villager. Both scenes compose
; this, because in BOTH the sprite MOVES from a tile coordinate — unlike
; mode7_explore, whose overworld avatar is pinned at the affine pivot.
;
; THE 16x16 TILE LAYOUT IS THE PPU's, NOT OURS. A 16x16 OBJ reads tiles {N,
; N+1, N+16, N+17} — the second row is +16 slots, never +2 — so the OBJ CHR
; page is a 16-WIDE GRID and the two actors take slots 0 and 2 of its first
; row. Tools/gen_rpg_assets.py lays the blob out that way; get it wrong and the
; sprite's bottom half is somebody else's art.
;
; THE HI-TABLE BYTE IS REBUILT WHOLE, never read-modify-written. One byte
; covers four sprites (2 bits each: bit 0 = X9, bit 1 = size), and this feature
; claims the whole quad so it can own that byte outright. A stale X9 renders an
; actor 256 px away, which is the failure this shape removes rather than
; guards.
RPGO_REGS = $4300 + ES_D_RPGO_UP_CH * 16
RPGO_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
RPGO_HI_BYTE = RPGO_HI_BASE + (ES_O_ACTORS / 4)
RPGO_PARK_Y = 240                   ; below the 224-line screen
RPGO_PAL_LONG = (ES_R_OBJ_PAL_BANK << 16) | ES_R_OBJ_PAL_ADDR

.assert (ES_O_ACTORS & 3) = 0, error, "rpg_obj: the actor claim must start on a hi-table quad boundary, or the byte this feature rebuilds is shared"

; --- rpgo_arm: OBJ CHR + palette + OBSEL, at scene enter under forced blank --
; In/out: A16/I16, DB=0. Clobbers A, X. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16.
.a16
.i16
rpgo_arm:
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word step after $2119
    lda #ES_R_OBJ_CHR_BANK
    sta a:RPGO_REGS + 4             ; A1B
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the claim's own page
    lda #ES_R_OBJ_CHR_ADDR
    sta a:RPGO_REGS + 2             ; A1T
    lda #ES_R_OBJ_CHR_SIZE
    sta a:RPGO_REGS + 5             ; DAS — armed here, one transfer
    sep #$20
    .a8
    lda #ES_D_RPGO_UP_DMAP
    sta a:RPGO_REGS + 0
    lda #ES_D_RPGO_UP_BBAD
    sta a:RPGO_REGS + 1
    lda #(1 << ES_D_RPGO_UP_CH)
    sta a:$420B                     ; fire
    ; ---- the 16 OBJ colours ----------------------------------------------
    lda #ES_C_OBJ_PAL
    sta a:$2121                     ; CGADD = the claim base (CGRAM 128)
    ldx #0
@pal:
    lda f:RPGO_PAL_LONG, x
    sta a:$2122
    inx
    cpx #ES_R_OBJ_PAL_SIZE
    bcc @pal
    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + this claim's OBJ name base ----
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    rts

; --- rpgo_place: one actor at a screen pixel position -----------------------
; In: A16 = screen x (may be negative or > 255: X9 comes out of bit 8),
;  X = screen y, Y = actor index (0 or 1).
; In/out: A16/I16, DB=0. Clobbers A, X, Y. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16; the A8 window that writes the four shadow bytes is balanced.
.a16
.i16
rpgo_place:
    pha                             ; screen x  (A16 push: 2 bytes)
    phx                             ; screen y  (I16 push: 2 bytes)
    tya
    asl
    asl
    tax                             ; X = actor * 4 = the shadow byte offset.
                                    ;  X, not Y: the two coordinates come back
                                    ;  off the stack in A, and an earlier form
                                    ;  held the offset in Y, pushed Y, and then
                                    ;  INDEXED with the RESTORED actor index —
                                    ;  which wrote actor 1's attr over actor
                                    ;  0's
                                    ;  tile. The emulator found it: OAM entry 0
                                    ;  read tile $00 attr $02 (palette 1, all
                                    ;  zeros) and both actors were invisible.
    tya
    asl                             ; A = actor * 2 = the CHR slot: the two 16x16
                                    ;  sprites live at slots 0 and 2 of the OBJ
                                    ;  page's 16-wide grid
    sep #$20
    .a8
    sta a:ES_OAM_SHADOW + 2, x      ; byte 2: tile
    lda #48                         ; byte 3: priority 3 (bits 5-4), palette 0
                                    ;  (bits 3-1), tile bit 8 clear (bit 0)
    sta a:ES_OAM_SHADOW + 3, x
    rep #$20
    .a16
    pla                             ; screen y
    sep #$20
    .a8
    sta a:ES_OAM_SHADOW + 1, x
    rep #$20
    .a16
    pla                             ; screen x (low 8; X9 is rpgo_hi's)
    sep #$20
    .a8
    sta a:ES_OAM_SHADOW + 0, x
    rep #$20
    .a16
    rts

; --- rpgo_hi: rebuild the actors' hi-table byte from their own x ------------
; In: A16 = actor 0's screen x, X = actor 1's screen x (both 16-bit signed).
; Both actors are LARGE (16x16), so the size bit is set for both; X9 comes from
; bit 8 of each x. Written WHOLE — see the header. In/out: A16/I16, DB=0.
; Clobbers A, X. WIDTH-RISK: exported. Entry A16/I16, exit A16/I16.
.a16
.i16
rpgo_hi:
    and #256                        ; actor 0's X9
    beq :+
    lda #1
    bra :++
:   .a16
    lda #0
:   .a16
    ora #2                          ; actor 0 is LARGE
    sta z:ES_RPG_HOT + 14
    txa
    and #256                        ; actor 1's X9
    beq :+
    lda #4
    bra :++
:   .a16
    lda #0
:   .a16
    ora #8                          ; actor 1 is LARGE
    ora z:ES_RPG_HOT + 14
    sep #$20
    .a8
    sta a:RPGO_HI_BYTE              ; slots 2-3 stay small + X9 clear: parked
    rep #$20
    .a16
    rts

; --- rpgo_park: put both actors below the screen ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16.
.a16
.i16
rpgo_park:
    sep #$20
    .a8
    lda #RPGO_PARK_Y
    sta a:ES_OAM_SHADOW + 1
    sta a:ES_OAM_SHADOW + 5
    rep #$20
    .a16
    rts
