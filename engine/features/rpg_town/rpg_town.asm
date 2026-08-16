; =============================================================================
; rpg_town.asm — the rpg rail's Mode 1 town interior (scene-scoped BG feature)
; =============================================================================
; ONE BG feature owns all of a scene's co-resident BG layers. This one
; owns BG1 and, through BG12NBA, BG2's base nibble too — this build is written
; once and has one owner. BG3 is bg_text's, which is the split `dialog` is
; designed around.
;
; The room is a DESIGNED 32x32 tilemap generated alongside the tileset
; (tools/gen_rpg_assets.py), uploaded whole rather than computed at enter: the
; map is 2 KB of ROM either way, and a generated map is a map the collision
; probe below can read from the SAME bytes the PPU draws — what is drawn IS
; what blocks, with no shadow to keep synchronised.
RPGT_REGS = $4300 + ES_D_RPGT_UP_CH * 16
RPGT_PAL_LONG = (ES_R_TOWN_PAL_BANK << 16) | ES_R_TOWN_PAL_ADDR
RPGT_MAP_LONG = (ES_R_TOWN_MAP_BANK << 16) | ES_R_TOWN_MAP_ADDR

; The room's tile ids, as gen_rpg_assets.py numbers them.
TT_VOID = 0
TT_COBBLE = 1
TT_COBBLE2 = 2
TT_BRICK = 3
TT_ROOF = 4
TT_TORCH = 5
TT_DOOR = 6
TT_GRASS = 7
TT_WATER = 8
TT_BARREL = 9                       ; a blocking plaza prop (not in the walkable
                                    ;  whitelist below, so it blocks by
                                    ;  default)
TT_TORCH_LIT = 10                   ; the save-torch flare tile; swapped
                                    ;  in by town_flare_commit, never in the
                                    ;  map

; --- rpgt_upload_one: one blob -> one VRAM word base ------------------------
; In: A16 = source bank (low byte), X = source addr, Y = VRAM word base,
;  ES_RPG_HOT+14 = byte count. DAS is armed HERE, per transfer, because this
;  routine fires three of them and DAS is single-shot.
; In/out: A16/I16, DB=0. Clobbers A.
.a16
.i16
rpgt_upload_one:
    sep #$20
    .a8
    sta a:RPGT_REGS + 4             ; A1B
    lda #$80
    sta a:$2115                     ; VMAIN: word step after $2119
    rep #$20
    .a16
    sty a:$2116                     ; VMADD
    stx a:RPGT_REGS + 2             ; A1T
    lda z:ES_RPG_HOT + 14
    sta a:RPGT_REGS + 5             ; DAS — re-armed for every transfer
    sep #$20
    .a8
    lda #ES_D_RPGT_UP_DMAP
    sta a:RPGT_REGS + 0
    lda #ES_D_RPGT_UP_BBAD
    sta a:RPGT_REGS + 1
    lda #(1 << ES_D_RPGT_UP_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    rts

; --- rpgt_arm: CHR + tilemap + palette + the BG1 register bases -------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16.
.a16
.i16
rpgt_arm:
    lda #ES_R_TOWN_CHR_SIZE
    sta z:ES_RPG_HOT + 14
    ldx #ES_R_TOWN_CHR_ADDR
    ldy #ES_V_TOWN_CHR
    lda #ES_R_TOWN_CHR_BANK
    jsr rpgt_upload_one
    lda #ES_R_TOWN_MAP_SIZE
    sta z:ES_RPG_HOT + 14
    ldx #ES_R_TOWN_MAP_ADDR
    ldy #ES_V_TOWN_MAP
    lda #ES_R_TOWN_MAP_BANK
    jsr rpgt_upload_one
    ; ---- the 16 room colours, CPU-side -----------------------------------
    sep #$20
    .a8
    lda #ES_C_TOWN_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    ldx #0
@pal:
    lda f:RPGT_PAL_LONG, x
    sta a:$2122
    inx
    cpx #ES_R_TOWN_PAL_SIZE
    bcc @pal
    ; ---- the layer bases: both encodings are the ALLOCATOR's --------------
    lda #ES_V_TOWN_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32, this claim's tilemap
    lda #ES_V_TOWN_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr = this claim's page
    ; ---- the camera is FIXED: the sprite moves, the room does not ---------
    stz a:$210D
    stz a:$210D                     ; BG1HOFS (write-twice)
    stz a:$210E
    stz a:$210E                     ; BG1VOFS
    rep #$20
    .a16
    rts

; --- rpgt_blocks: does town tile (X=tx, Y=ty) block the player? -------------
; Out: A16 = 1 blocked, 0 walkable. Reads the tilemap blob in ROM — the SAME
; bytes the PPU draws, so what is drawn IS what blocks. Tiles outside the 32x32
; grid block (the brick border already does; this is the guard for a caller
; that computed a bad tile). In/out: A16/I16, DB=0. Clobbers A, X. WIDTH-RISK:
; exported. Entry A16/I16, exit A16/I16; the A8 window around the one-byte tile
; read is balanced on BOTH arms.
.a16
.i16
rpgt_blocks:
    cpx #32
    bcs @block
    cpy #32
    bcs @block
    tya
    asl
    asl
    asl
    asl
    asl                             ; ty * 32 cells
    sta z:ES_RPG_HOT + 14
    txa
    clc
    adc z:ES_RPG_HOT + 14
    asl                             ; * 2 B per tilemap word
    tax
    sep #$20
    .a8
    lda f:RPGT_MAP_LONG, x          ; the tile id (the word's low byte)
    rep #$20
    .a16
    and #255
    cmp #TT_COBBLE
    beq @walk
    cmp #TT_COBBLE2
    beq @walk
    cmp #TT_GRASS
    beq @walk
    cmp #TT_DOOR
    beq @walk
@block:
    .a16
    .i16
    lda #1
    rts
@walk:
    .a16
    .i16
    lda #0
    rts

; --- rpgt_tile_at: the raw tile id of town tile (X=tx, Y=ty) ----------------
; Out: A16 = tile id (0..255). Out-of-grid returns TT_VOID. In/out: A16/I16,
; DB=0. Clobbers A, X. WIDTH-RISK: exported. Entry A16/I16, exit A16/I16.
.a16
.i16
rpgt_tile_at:
    cpx #32
    bcs @void
    cpy #32
    bcs @void
    tya
    asl
    asl
    asl
    asl
    asl
    sta z:ES_RPG_HOT + 14
    txa
    clc
    adc z:ES_RPG_HOT + 14
    asl
    tax
    sep #$20
    .a8
    lda f:RPGT_MAP_LONG, x
    rep #$20
    .a16
    and #255
    rts
@void:
    .a16
    .i16
    lda #TT_VOID
    rts
