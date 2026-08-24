; =============================================================================
; patrol_obj.asm — the three actors: red player + two magenta patrollers
; =============================================================================
; One shared 8x8 tile, three OAM entries pinned at 0..2, two OBJ palettes (0 =
; player red, 1 = enemy magenta — selected by the attr byte, $00 vs $02).
; Positions are written every frame from the play scene's state into the
; oam_sprites SHADOW — never into hardware OAM, which the engine's declared
; VBlank GP-DMA owns.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (feature.toml's pobj_obsel). Its
; VALUE comes from ES_V_POBJ_CHR_OBSEL_BASE.

POBJ_REGS = $4300 + ES_D_POBJ_UP_CH * 16

; The four entries, and the ONE hi-table byte they share. The hi table is the
; last 32 B of the shadow claim, so its base is derived from the emitted size —
; the same expression oam_sprites uses.
POBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
POBJ_PLAYER  = ES_OAM_SHADOW + ES_O_PLAYER * 4
POBJ_E1      = ES_OAM_SHADOW + (ES_O_ENEMIES + 0) * 4
POBJ_E2      = ES_OAM_SHADOW + (ES_O_ENEMIES + 1) * 4
POBJ_PAD     = ES_OAM_SHADOW + ES_O_HI_PAD * 4
POBJ_HI      = POBJ_HI_BASE + (ES_O_PLAYER / 4)

; THE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED (hud_obj's
; discipline). A hi-table byte covers four sprites (2 bits each: bit 0 = X9,
; bit 1 = size), so rebuilding it as one byte is only correct while these four
; slots ARE that byte's four sprites.
.assert ES_O_PLAYER .MOD 4 = 0, error, "patrol_obj: player must start a hi-table byte"
.assert ES_O_ENEMIES = ES_O_PLAYER + 1, error, "patrol_obj: the enemies must follow the player"
.assert ES_O_HI_PAD = ES_O_PLAYER + 3, error, "patrol_obj: the four slots must be consecutive"

; The one tile in the pobj_chr claim's grid, and the two OAM attr bytes:
; attr = %0011_0000 | (palette << 1): priority 3, tile bit 8 clear.
; The player draws with palette 0 and both enemies with palette 1; the low
; operand bits ARE the palette-select bits.
POBJ_TILE       = 0
POBJ_ATTR_PLAYER = 48                ; priority 3, OBJ palette 0
POBJ_ATTR_ENEMY  = 48 | 2            ; priority 3, OBJ palette 1
POBJ_PARK_Y      = 240               ; Y = $F0 — off the bottom of the screen

; --- pat_obj_arm: CHR + palettes + OBSEL + resting entries (scene enter) ----
; CONTRACT pat_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palettes, OBSEL and the resting entries
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
pat_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pat_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_POBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(pat_obj_chr_bin)
    sta a:POBJ_REGS + 2             ; A1T
    lda #ES_R_PAT_OBJ_CHR_SIZE
    sta a:POBJ_REGS + 5             ; DAS (single-shot, armed per transfer)
    sep #$20
    .a8
    lda #^pat_obj_chr_bin
    sta a:POBJ_REGS + 4             ; A1B
    lda #ES_D_POBJ_UP_DMAP
    sta a:POBJ_REGS + 0             ; DMAP: A->B, 2 regs write-once
    lda #ES_D_POBJ_UP_BBAD
    sta a:POBJ_REGS + 1             ; BBAD: VMDATAL
    lda #(1 << ES_D_POBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palettes 0 + 1 (CGRAM 128..159), one 32-word loop ------------
    lda #ES_C_POBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:pat_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_PAT_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8), OBJ chr base from the claim ------
    ; All three actors are SMALL, so the hi table's size bits stay clear and
    ; pat_obj_place writes X9 bits only.
    sep #$20
    .a8
    lda #ES_V_POBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tiles + attrs (constant for the rail's life), pad parked ---------
    lda #POBJ_TILE
    sta a:POBJ_PLAYER + 2
    sta a:POBJ_E1 + 2
    sta a:POBJ_E2 + 2
    lda #POBJ_ATTR_PLAYER
    sta a:POBJ_PLAYER + 3
    lda #POBJ_ATTR_ENEMY
    sta a:POBJ_E1 + 3
    sta a:POBJ_E2 + 3
    lda #POBJ_PARK_Y
    sta a:POBJ_PAD + 1
    stz a:POBJ_HI                   ; all four small, X9 clear (pat_obj_place
                                    ; rebuilds this byte every frame)
    rep #$20
    .a16
    rts

; --- pat_obj_place: the three actors' positions -> the OAM shadow -----------
; CONTRACT pat_obj_place
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the three actors' positions written into the OAM shadow,
;             rebuilt whole rather than patched
;   clobbers: A, N, Z, C
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED (hud_obj's discipline): an
; OAM X coordinate is nine bits and the ninth lives here. Each actor's X9 is
; DERIVED from bit 8 of its own x every frame — the level's borders keep every
; x below 256 today, and a stale assumption would ship a sprite 256 px away the
; first time one grew. Slot layout in the byte: player bits 0..1, E1 bits 2..3,
; E2 bits 4..5, pad bits 6..7 (parked, contributes 0).
pat_obj_place:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pat_obj_place"
    ; ---- player: (px, pyi) ------------------------------------------------
    lda z:US_PX
    sep #$20
    .a8
    sta a:POBJ_PLAYER + 0
    rep #$20
    .a16
    lda z:US_PYI
    sep #$20
    .a8
    sta a:POBJ_PLAYER + 1
    rep #$20
    .a16
    ; ---- ground enemy: (e1x, the beat row) --------------------------------
    lda z:US_E1X
    sep #$20
    .a8
    sta a:POBJ_E1 + 0
    lda #PAT_E1_Y
    sta a:POBJ_E1 + 1
    rep #$20
    .a16
    ; ---- ledge enemy: (e2x, the platform row) -----------------------------
    lda z:US_E2X
    sep #$20
    .a8
    sta a:POBJ_E2 + 0
    lda #PAT_E2_Y
    sta a:POBJ_E2 + 1
    rep #$20
    .a16
    ; ---- the hi byte, rebuilt from the three X9 bits ----------------------
    lda z:US_PX
    xba
    and #1                          ; player X bit 8 -> bit 0
    sta z:US_NEWX                   ; borrow the move-check scratch a moment
    lda z:US_E1X
    xba
    and #1
    asl
    asl                             ; E1 X9 -> bit 2
    ora z:US_NEWX
    sta z:US_NEWX
    lda z:US_E2X
    xba
    and #1
    asl
    asl
    asl
    asl                             ; E2 X9 -> bit 4
    ora z:US_NEWX
    sep #$20
    .a8
    sta a:POBJ_HI
    rep #$20
    .a16
    rts

; --- pat_obj_park: hide all four (scene exit) -------------------------------
; CONTRACT pat_obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      all four slots hidden
;   clobbers: A, N, Z
;   assumes:  the scene that armed a slot re-parks it, so the next scene
;             inherits the boot contract rather than this scene's sprites.
;             Never called — this rail has one scene and no edges — and it
;             exists because the claim's contract is symmetric
;   tail:     rts
;
; In/out: A16/I16, DB=0. Never called — this game has one scene and no edges —
; but the claim's contract is symmetric and a second scene would need it.
pat_obj_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pat_obj_park"
    sep #$20
    .a8
    lda #POBJ_PARK_Y
    sta a:POBJ_PLAYER + 1
    sta a:POBJ_E1 + 1
    sta a:POBJ_E2 + 1
    sta a:POBJ_PAD + 1
    stz a:POBJ_HI                   ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts
