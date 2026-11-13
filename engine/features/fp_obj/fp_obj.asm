; =============================================================================
; fp_obj.asm — the four_pads actors: four tokens and four pad lamps
; =============================================================================
; CHR + palettes from the fp_rom blobs; eight OAM slots (tokens 0-3, lamps
; 4-7) from this feature's claims, written into the oam_sprites SHADOW. See
; fp_obj/feature.toml for what each sprite says about its pad.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (the obj_obsel claim). Its VALUE
; comes from ES_V_OBJ_CHR_OBSEL_BASE.

FP_OBJ_REGS = $4300 + ES_D_OBJ_UP_CH * 16

; The two runs of four entries and the two hi-table bytes they fill. The hi
; table is the last 32 B of the shadow claim (oam_sprites' own expression).
FP_HI_BASE  = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
FP_TOKEN0   = ES_OAM_SHADOW + ES_O_TOKENS * 4
FP_LAMP0    = ES_OAM_SHADOW + ES_O_LAMPS * 4
FP_HI_TOKEN = FP_HI_BASE + (ES_O_TOKENS / 4)
FP_HI_LAMP  = FP_HI_BASE + (ES_O_LAMPS / 4)

; THE PACKING THIS FILE DEPENDS ON, asserted: each run of four must BE one
; hi-table byte, or writing that byte whole would stamp another feature's
; sprite flags.
.assert ES_O_TOKENS .MOD 4 = 0, error, "fp_obj: tokens must start a hi-table byte"
.assert ES_O_LAMPS .MOD 4 = 0, error, "fp_obj: lamps must start a hi-table byte"
.assert ES_O_TOKENS_SPRITES = FP_PLAYERS, error, "fp_obj: one token per player"
.assert ES_O_LAMPS_SPRITES = FP_PLAYERS, error, "fp_obj: one lamp per player"

; OAM attr: priority 3 (bits 5-4), palette n (bits 3-1) = player n+1, tile
; bit 8 clear. Player p's attr is FP_ATTR_BASE | (p << 1).
FP_ATTR_BASE = %00110000
FP_PARK_Y    = 240               ; Y = $F0 — below the visible screen

; --- fp_obj_arm: CHR + palettes + OBSEL + every slot parked (scene enter) -----
; CONTRACT fp_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the three tiles in OBJ VRAM, the four palettes in CGRAM 128..191,
;             OBSEL, all eight entries parked with their tile + palette set,
;             both hi-table bytes zero (small, X9 clear)
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;             (OBJ VRAM and CGRAM 128.. are random at power-on, rule 5, and an
;             entry pointing at them would be a valid sprite made of garbage)
;   tail:     rts
fp_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "fp_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(fp_obj_chr_bin)
    sta a:FP_OBJ_REGS + 2           ; A1T
    lda #ES_R_FP_OBJ_CHR_ROM_SIZE
    sta a:FP_OBJ_REGS + 5           ; DAS — one transfer, armed for it
    sep #$20
    .a8
    lda #^fp_obj_chr_bin
    sta a:FP_OBJ_REGS + 4           ; A1B
    lda #ES_D_OBJ_UP_DMAP
    sta a:FP_OBJ_REGS + 0           ; DMAP
    lda #ES_D_OBJ_UP_BBAD
    sta a:FP_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palettes 0-3 (CGRAM 128..191), one 128 B walk ----------------
    lda #ES_C_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:fp_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_FP_OBJ_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (8x8 small), OBJ chr base from the claim --------
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- every slot: its palette, its resting tile, parked -----------------
    ldx #0
@slot:
    .a8
    lda f:fp_attr_tab, x            ; player x's palette (both runs)
    sta a:FP_TOKEN0 + 3, x
    sta a:FP_LAMP0 + 3, x
    lda #FP_TILE_TOKEN
    sta a:FP_TOKEN0 + 2, x
    lda #FP_TILE_RING
    sta a:FP_LAMP0 + 2, x
    lda #FP_PARK_Y
    sta a:FP_TOKEN0 + 1, x
    sta a:FP_LAMP0 + 1, x
    inx
    inx
    inx
    inx
    cpx #(FP_PLAYERS * 4)
    bcc @slot
    stz a:FP_HI_TOKEN               ; all small, X9 clear — and they stay so:
    stz a:FP_HI_LAMP                ;   the scene clamps every X below 256
    rep #$20
    .a16
    rts

; --- fp_obj_park: hide all eight (scene exit) -------------------------------
; CONTRACT fp_obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      all eight slots at Y = $F0
;   clobbers: A, X, N, Z, C
;   assumes:  the scene that armed the slots re-parks them. One scene and no
;             edges, so nothing calls it today; the claim's contract is
;             symmetric and a second scene would need it
;   tail:     rts
fp_obj_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "fp_obj_park"
    sep #$20
    .a8
    ldx #0
@park:
    .a8
    lda #FP_PARK_Y
    sta a:FP_TOKEN0 + 1, x
    sta a:FP_LAMP0 + 1, x
    inx
    inx
    inx
    inx
    cpx #(FP_PLAYERS * 4)
    bcc @park
    rep #$20
    .a16
    rts

; Per-player OAM attr byte, indexed by slot*4 (the walk above steps X by 4):
; palette n for player n+1, priority 3.
.segment "RODATA"
fp_attr_tab:
    .byte FP_ATTR_BASE | (0 << 1), 0, 0, 0
    .byte FP_ATTR_BASE | (1 << 1), 0, 0, 0
    .byte FP_ATTR_BASE | (2 << 1), 0, 0, 0
    .byte FP_ATTR_BASE | (3 << 1), 0, 0, 0
.segment "CODE"
