; =============================================================================
; maze_obj.asm — the red player, drawn where the collision put it
; =============================================================================
; CHR + palette from the maze_rom blobs; one OAM slot from the `player` claim.
; The entry is re-staged into the oam_sprites SHADOW every frame — never into
; hardware OAM, which the engine's declared VBlank GP-DMA owns.
;
; THE POSITION IS THE GAME'S, NOT THIS FEATURE'S. The includer binds
; MZO_PX/MZO_PY to the scene's own state words (game/maze/scenes/room.asm
; binds them to US_PX/US_PY — the m7dg_obj MDO_ENEMY_POS pattern) so the
; sprite draws exactly the coordinate the per-axis move-check committed, and
; the two surfaces cannot drift. Each missing binding is a hard .error naming
; it, and there is no default (rgb_gradient's refusal, col_map's binding).

.ifndef MZO_PX
    .error "maze_obj: the includer must bind MZO_PX (the player x state word) before including this file"
.endif
.ifndef MZO_PY
    .error "maze_obj: the includer must bind MZO_PY (the player y state word) before including this file"
.endif

MZO_REGS = $4300 + ES_D_MZ_OBJ_UP_CH * 16

; The one entry, and the hi-table byte it shares with three parked neighbours.
; The hi table is the last 32 B of the shadow claim, so its base is derived
; from the emitted size — the same expression oam_sprites uses.
MZO_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
MZO_ENTRY   = ES_OAM_SHADOW + ES_O_PLAYER * 4
MZO_HI      = MZO_HI_BASE + (ES_O_PLAYER / 4)

; A hi byte covers four sprites (2 bits each: X9 + size); writing it whole is
; only correct while this sprite starts the byte and the other three are the
; parked ones oam_park_all left. Asserted, not assumed (scroller_obj's guard).
.assert ES_O_PLAYER .MOD 4 = 0, error, "maze_obj: player must start a hi-table byte"

; Tile inside the mz_obj_chr claim's grid, and the OAM attr byte.
; attr = %0011_0000: priority 3, OBJ palette 0, tile bit 8 clear.
MZO_TILE = 0
MZO_ATTR = 48

; --- mzo_arm: CHR + palette + OBSEL + tile/attr (scene enter) ---------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Clobbers A, X.
mzo_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MZ_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(mz_obj_chr_bin)
    sta a:MZO_REGS + 2              ; A1T
    lda #ES_R_MZ_OBJ_CHR_SIZE
    sta a:MZO_REGS + 5              ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^mz_obj_chr_bin
    sta a:MZO_REGS + 4              ; A1B
    lda #ES_D_MZ_OBJ_UP_DMAP
    sta a:MZO_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_MZ_OBJ_UP_BBAD
    sta a:MZO_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_MZ_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_MZ_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:mz_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MZ_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8), OBJ chr base from the claim ------
    sep #$20
    .a8
    lda #ES_V_MZ_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr: written once; only X/Y are per-frame ----------------
    lda #MZO_TILE
    sta a:MZO_ENTRY + 2
    lda #MZO_ATTR
    sta a:MZO_ENTRY + 3
    rep #$20
    .a16
    rts

; --- mzo_draw: stage the player into the OAM shadow -------------------------
; In/out: A16/I16, DB=0. Called from the scene's tick, EVERY frame — after the
; move-check has committed this frame's position, so the entry staged is the
; coordinate collision decided. Clobbers A.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED. An OAM X coordinate is
; nine bits and the ninth lives in the hi table. The room's border keeps
; MZO_PX under 256 today, so a shortcut that assumed X9 clear would pass every
; test here and ship a sprite 256 px away the first time a coordinate grew.
; Deriving it costs one mask (scroller_obj's reasoning). The size bit stays 0.
mzo_draw:
    .a16
    .i16
    lda z:MZO_PX
    sep #$20
    .a8
    sta a:MZO_ENTRY + 0
    rep #$20
    .a16
    lda z:MZO_PY
    sep #$20
    .a8
    sta a:MZO_ENTRY + 1
    rep #$20
    .a16
    lda z:MZO_PX
    xba                             ; bit 8 of X -> bit 0 of the low byte
    and #1                          ; ...which is this sprite's X9 bit
    sep #$20
    .a8
    sta a:MZO_HI                    ; whole byte: X9 as derived, size 0, and
                                    ; the three parked neighbours' bits clear
                                    ; exactly as oam_park_all left them
    rep #$20
    .a16
    rts
