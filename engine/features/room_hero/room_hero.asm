; =============================================================================
; room_hero.asm — the room's 16x16 player sprite
; =============================================================================
; CHR + palette from the hero_rom blob; one OAM slot from the hero claim. The
; sprite is placed every frame from room_logic's px/py, into the oam_sprites
; shadow — never into hardware OAM, which the engine's declared VBlank GP-DMA
; owns.
;
; CPU-WRITTEN REGISTER, UNDECLARED: OBSEL $2101 (docs/09 §2.1 census row). Its
; VALUE comes from ES_V_HERO_CHR_OBSEL_BASE, so the address discipline holds
; and only the ownership is invisible.

RH_REGS = $4300 + ES_D_HERO_UP_CH * 16
RH_OAM  = ES_OAM_SHADOW + ES_O_HERO * 4         ; this slot's 4 entry bytes
; The hi table is the last 32 B of the shadow claim, so its base is derived
; from the emitted size — the same expression oam_sprites uses.
RH_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
RH_HI   = RH_HI_BASE + (ES_O_HERO / 4)          ; ...and its hi-table byte

; Hi-table layout: each byte covers 4 sprites, 2 bits each — bit 0 = X9, bit 1
; = size (0 = small, 1 = large per OBSEL). This sprite is LARGE.
RH_HI_SHIFT = (ES_O_HERO .MOD 4) * 2
RH_HI_SIZE  = 2 << RH_HI_SHIFT
RH_HI_X9    = 1 << RH_HI_SHIFT
; RH_HI_CLR is a clear-mask by SUBTRACTION rather than ~: the bits are
; disjoint, so $FF - bits is exactly the complement, and it stays an immediate
; < $100 (which no_literals reads as data, not as an address). It survives for
; the one site that clears and sets in the same pass (hero_arm); the two sites
; that only CLEAR now use `trb`, whose mask names the bits being cleared
; directly and so needs no complement at all — RH_HI_X9CLR went with them.
RH_HI_CLR   = $FF - (3 << RH_HI_SHIFT)

; The second hero (pad 2): the same equate family over the hero2
; claim's slot. Identical twin by construction — same CHR block, same OBJ
; palette 0 (so, like the bearer, he is colour-math-exempt and visible in the
; dark), his own OAM entry + hi-table bit pair.
RH2_OAM = ES_OAM_SHADOW + ES_O_HERO2 * 4
RH2_HI  = RH_HI_BASE + (ES_O_HERO2 / 4)
RH2_HI_SHIFT  = (ES_O_HERO2 .MOD 4) * 2
RH2_HI_SIZE   = 2 << RH2_HI_SHIFT
RH2_HI_X9     = 1 << RH2_HI_SHIFT
RH2_HI_CLR    = $FF - (3 << RH2_HI_SHIFT)

; --- hero_arm: CHR + palette + OBSEL + the resting OAM entry (scene enter) --
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
hero_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_HERO_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(hero_chr_bin)
    sta a:RH_REGS + 2               ; A1T
    lda #ES_R_HERO_CHR_ROM_SIZE
    sta a:RH_REGS + 5               ; DAS
    sep #$20
    .a8
    lda #^hero_chr_bin
    sta a:RH_REGS + 4               ; A1B
    lda #ES_D_HERO_UP_DMAP
    sta a:RH_REGS + 0               ; DMAP: A->B, 2 regs write-once
    lda #ES_D_HERO_UP_BBAD
    sta a:RH_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_HERO_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) ----------------------------------
    lda #ES_C_HERO_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:hero_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_HERO_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from
    ; the claim. Derived from Mesen2 SnesPpu.cpp:671-681:
    ; OamMode = OBSEL bits 5-7, and the size table is
    ;  mode 0 = 8/16 mode 1 = 8/32 mode 2 = 8/64 ...
    ; An earlier version wrote base+32 here = MODE 1, under a comment that
    ; claimed "8/16" — so the LARGE hero silently rendered 32x32, its lower
    ; half sampling the unclaimed VRAM gap words $200-$3FF (title-font residue)
    ; and its right half tiles 2-3. Latent while those pixels happened to sit
    ; outside every sampled test point; EXPOSED the moment pip art landed in
    ; tile 2 and appeared beside the hero's head. Mode 0 is the
    ; shape this room means: 16x16 heroes (hi-table size bit set), 8x8 pips
    ; (size bit clear).
    sep #$20
    .a8
    lda #ES_V_HERO_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- mark this slot LARGE in the hi table; X9 starts clear ------------
    lda a:RH_HI
    and #RH_HI_CLR
    ora #RH_HI_SIZE
    sta a:RH_HI
    ; ---- tile + attr: tile 0 of the claim's grid, OBJ palette 0, prio 2 ---
    stz a:RH_OAM + 2                ; tile index (low 8 bits) = 0
    lda #48                         ; attr: prio 2 (bits 5-4), palette 0
    sta a:RH_OAM + 3
    rep #$20
    .a16
    rts

; --- hero2_arm: the twin's resting OAM entry (scene enter) ------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Call AFTER hero_arm: CHR
; upload, palette and OBSEL are hero_arm's work and SHARED — this only marks
; the twin's slot LARGE and sets its tile + attr.
hero2_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda a:RH2_HI
    and #RH2_HI_CLR
    ora #RH2_HI_SIZE
    sta a:RH2_HI
    stz a:RH2_OAM + 2               ; tile 0 of the grid — the same hero art
    lda #48                         ; attr: prio 2, OBJ palette 0
    sta a:RH2_OAM + 3
    rep #$20
    .a16
    rts

; --- hero_place: write px/py into the OAM shadow ---------------------------
; In/out: A16/I16, DB=0. Called from the scene tick, every frame. Clobbers A.
;
; X9 IS SET FROM BIT 8 EVERY FRAME, both ways. The room clamps px to 8..232 so
; bit 8 is never set today — but an OAM X byte is 9 bits wide and a stale X9
; renders a sprite 256 px away, which is the failure this repo has a
; lessons_learned entry about. Deriving the bit rather than assuming it costs
; four instructions and removes the assumption.
hero_place:
    .a16
    .i16
    lda z:US_PX
    sep #$20
    .a8
    sta a:RH_OAM + 0                ; OAM X, low 8 bits
    rep #$20
    .a16
    lda z:US_PY
    sep #$20
    .a8
    sta a:RH_OAM + 1                ; OAM Y
    rep #$20
    .a16
    lda z:US_PX
    and #$0100                      ; bit 8 -> X9
    beq @x9_clear
    sep #$20
    .a8
    lda #RH_HI_X9
    tsb a:RH_HI                     ; test-and-set: the load/or/store this
                                    ;   replaces read the whole byte to change
                                    ;   one bit. Nothing below reads Z, which
                                    ;   `tsb` sets from A AND memory rather
                                    ;   than from the result.
    rep #$20
    .a16
    rts
@x9_clear:
    .a16
    .i16
    sep #$20
    .a8
    lda #RH_HI_X9
    trb a:RH_HI                     ; test-and-reset: the mask now names the
                                    ;   bit being cleared instead of the 7 bits
                                    ;   being kept (RH_HI_X9CLR was its
                                    ;   complement). Z unread below.
    rep #$20
    .a16
    rts

; --- hero2_place: write px2/py2 into the twin's OAM entry -------------------
; In/out: A16/I16, DB=0. Called from room_refresh every frame. Clobbers A. Same
; X9-derived-every-frame discipline as hero_place — the clamp keeps bit 8 clear
; today, and deriving it removes the assumption.
hero2_place:
    .a16
    .i16
    lda z:US_PX2
    sep #$20
    .a8
    sta a:RH2_OAM + 0               ; OAM X, low 8 bits
    rep #$20
    .a16
    lda z:US_PY2
    sep #$20
    .a8
    sta a:RH2_OAM + 1               ; OAM Y
    rep #$20
    .a16
    lda z:US_PX2
    and #$0100                      ; bit 8 -> X9
    beq @x9_clear
    sep #$20
    .a8
    lda #RH2_HI_X9
    tsb a:RH2_HI                    ; as hero_place, for the twin's slot
    rep #$20
    .a16
    rts
@x9_clear:
    .a16
    .i16
    sep #$20
    .a8
    lda #RH2_HI_X9
    trb a:RH2_HI                    ; as hero_place, for the twin's slot
    rep #$20
    .a16
    rts

; --- hero_park: hide the sprite again (scene exit) -------------------------
; In/out: A16/I16, DB=0. The scene that armed a slot re-parks it, so the next
; scene inherits the boot contract rather than this scene's sprite.
hero_park:
    .a16
    .i16
    sep #$20
    .a8
    lda #240
    sta a:RH_OAM + 1                ; Y = $F0: off-screen
    lda #(RH_HI_SIZE | RH_HI_X9)    ; small + X9 clear, as oam_park_all left it
    trb a:RH_HI                     ; ...and the mask says WHICH two bits, which
                                    ;   RH_HI_CLR ($FF minus them) did not
    rep #$20
    .a16
    rts

; --- hero2_park: hide the twin (scene exit) ---------------------------------
; In/out: A16/I16, DB=0.
hero2_park:
    .a16
    .i16
    sep #$20
    .a8
    lda #240
    sta a:RH2_OAM + 1               ; Y = $F0: off-screen
    lda #(RH2_HI_SIZE | RH2_HI_X9)  ; small + X9 clear, the boot-park state
    trb a:RH2_HI
    rep #$20
    .a16
    rts
