; =============================================================================
; sprg_obj.asm — the sprite_game actors: two 8x8 OBJs from one shared tile
; =============================================================================
; CHR + both palettes from the sprg_rom blobs; four OAM slots (player, dot, two
; pad) from this feature's claims. Both positions are written every frame from
; the play scene's px/py + dot_x/dot_y into the oam_sprites SHADOW — never into
; hardware OAM, which the engine's declared VBlank GP-DMA owns.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (sprg_obj/feature.toml's
; obj_obsel claim). Its VALUE comes from ES_V_OBJ_CHR_OBSEL_BASE.

OBJ_REGS = $4300 + ES_D_OBJ_UP_CH * 16

; The four entries, and the ONE hi-table byte they share. The hi table is the
; last 32 B of the shadow claim, so its base is derived from the emitted size —
; the same expression oam_sprites uses.
OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
OBJ_PLAYER  = ES_OAM_SHADOW + ES_O_PLAYER * 4
OBJ_DOT     = ES_OAM_SHADOW + ES_O_DOT * 4
OBJ_PAD0    = ES_OAM_SHADOW + (ES_O_HI_PAD + 0) * 4
OBJ_PAD1    = ES_OAM_SHADOW + (ES_O_HI_PAD + 1) * 4
OBJ_HI      = OBJ_HI_BASE + (ES_O_PLAYER / 4)

; THE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED. A hi-table
; byte covers four sprites (2 bits each: bit 0 = X9, bit 1 = size), so writing
; it as one byte is only correct while these four slots ARE that byte's four
; sprites. All three claims are pinned (`at = 0/1/2`), so this holds today; a
; future claim that reordered them would stop the build rather than silently
; write another feature's sprite flags.
.assert ES_O_PLAYER .MOD 4 = 0, error, "sprg_obj: player must start a hi-table byte"
.assert ES_O_DOT = ES_O_PLAYER + 1, error, "sprg_obj: dot must follow the player"
.assert ES_O_HI_PAD = ES_O_PLAYER + 2, error, "sprg_obj: the four slots must be consecutive"

; Both actors draw the obj_chr claim's ONE tile; they differ only in the OAM
; attr's palette-select bits — the rail's "two independently-coloured sprites
; over one tile" teaching, in two constants.
;  attr = %0011_0000: priority 3, OBJ palette 0, tile bit 8 clear (player)
;  attr = %0011_0010: priority 3, OBJ palette 1, tile bit 8 clear (dot)
OBJ_TILE_SHARED = 0
OBJ_ATTR_PLAYER = 48
OBJ_ATTR_DOT    = 50
OBJ_PARK_Y      = 240            ; Y = $F0 — off the bottom of the screen

; --- sprg_obj_arm: CHR + palettes + OBSEL + the resting entries (scene enter)
; CONTRACT sprg_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palettes, OBSEL and the resting entries
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
sprg_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sprg_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(sprg_obj_chr_bin)
    sta a:OBJ_REGS + 2              ; A1T
    lda #ES_R_SPRG_OBJ_CHR_ROM_SIZE
    sta a:OBJ_REGS + 5              ; DAS (single transfer, armed here — DAS is
                                    ; single-shot and this routine fires once)
    sep #$20
    .a8
    lda #^sprg_obj_chr_bin
    sta a:OBJ_REGS + 4              ; A1B
    lda #ES_D_OBJ_UP_DMAP
    sta a:OBJ_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_OBJ_UP_BBAD
    sta a:OBJ_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palettes 0 + 1 (CGRAM 128..159), one 64 B walk ---------------
    lda #ES_C_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:sprg_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SPRG_OBJ_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from the
    ; claim. Both actors are SMALL, so the hi table's size bits stay clear
    ; exactly as oam_park_all left them and sprg_obj_place writes X9s only.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tiles + attrs (the shared tile, two palettes), pads parked --------
    lda #OBJ_TILE_SHARED
    sta a:OBJ_PLAYER + 2
    sta a:OBJ_DOT + 2
    lda #OBJ_ATTR_PLAYER
    sta a:OBJ_PLAYER + 3
    lda #OBJ_ATTR_DOT
    sta a:OBJ_DOT + 3
    lda #OBJ_PARK_Y
    sta a:OBJ_PAD0 + 1
    sta a:OBJ_PAD1 + 1
    stz a:OBJ_HI                    ; all four small, X9s clear (sprg_obj_place
                                    ; rebuilds this byte every frame)
    rep #$20
    .a16
    rts

; --- sprg_obj_place: px/py + dot_x/dot_y -> the OAM shadow ------------------
; CONTRACT sprg_obj_place
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      px/py and dot_x/dot_y written into the OAM shadow
;   clobbers: A, N, Z, C
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED — and here that is a LIVE
; requirement, not defence: this rail has NO clamp, so the player genuinely
; crosses X = 256 (nine frames of held right from home) and a hi byte that
; assumed bit 8 clear would render him 256 px away the moment he left the
; screen edge. Player X9 -> bit 0, dot X9 -> bit 2 (branchless: the shifted bit
; is OR'd in A8). The two pad slots contribute 0 (parked, never moving) and the
; size bits stay 0: both actors are 8x8.
sprg_obj_place:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sprg_obj_place"
    lda z:US_PX
    sep #$20
    .a8
    sta a:OBJ_PLAYER + 0
    rep #$20
    .a16
    lda z:US_PY
    sep #$20
    .a8
    sta a:OBJ_PLAYER + 1
    rep #$20
    .a16
    lda z:US_DOT_X
    sep #$20
    .a8
    sta a:OBJ_DOT + 0
    rep #$20
    .a16
    lda z:US_DOT_Y
    sep #$20
    .a8
    sta a:OBJ_DOT + 1
    rep #$20
    .a16
    lda z:US_PX
    xba
    and #1                          ; bit 8 of player X -> slot 0's X9 (bit 0)
    sep #$20
    .a8
    sta a:OBJ_HI
    rep #$20
    .a16
    lda z:US_DOT_X
    xba
    and #1
    asl a
    asl a                           ; bit 8 of dot X -> slot 1's X9 (bit 2)
    sep #$20
    .a8
    ora a:OBJ_HI
    sta a:OBJ_HI
    rep #$20
    .a16
    rts

; --- sprg_obj_park: hide all four (scene exit) ------------------------------
; CONTRACT sprg_obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      all four slots hidden
;   clobbers: A, N, Z
;   assumes:  the scene that armed a slot re-parks it, so the next scene
;             inherits the boot contract rather than this scene's sprites
;   tail:     rts
;
; scene inherits the boot contract rather than this scene's sprites. This rail
; has one scene and never transitions, so nothing calls it today — it exists
; because the claim's contract is symmetric and a second scene would need it.
sprg_obj_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sprg_obj_park"
    sep #$20
    .a8
    lda #OBJ_PARK_Y
    sta a:OBJ_PLAYER + 1
    sta a:OBJ_DOT + 1
    sta a:OBJ_PAD0 + 1
    sta a:OBJ_PAD1 + 1
    stz a:OBJ_HI                    ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts
