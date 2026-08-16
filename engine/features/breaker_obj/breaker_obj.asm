; =============================================================================
; breaker_obj.asm — the paddle (3 OBJs) and the ball (1)
; =============================================================================
; CHR + palette from the breaker_rom blobs; four OAM slots from the paddle and
; ball claims. Positions are written every frame from the play scene's px / bx
; / by into the oam_sprites SHADOW — never into hardware OAM, which the
; engine's declared VBlank GP-DMA owns.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (breaker_obj/feature.toml's
; obj_obsel claim). Its VALUE comes from ES_V_OBJ_CHR_OBSEL_BASE.

OBJ_REGS = $4300 + ES_D_OBJ_UP_CH * 16

; The four entries, and the ONE hi-table byte they share. The hi table is the
; last 32 B of the shadow claim, so its base is derived from the emitted size —
; the same expression oam_sprites uses.
OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
OBJ_P0   = ES_OAM_SHADOW + (ES_O_PADDLE + 0) * 4
OBJ_P1   = ES_OAM_SHADOW + (ES_O_PADDLE + 1) * 4
OBJ_P2   = ES_OAM_SHADOW + (ES_O_PADDLE + 2) * 4
OBJ_BALL = ES_OAM_SHADOW + ES_O_BALL * 4
OBJ_HI   = OBJ_HI_BASE + (ES_O_PADDLE / 4)

; THE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED. A hi-table
; byte covers four sprites (2 bits each: bit 0 = X9, bit 1 = size), so writing
; it as one byte is only correct while these four slots ARE that byte's four
; sprites. The allocator packs them that way today; if a future claim reorders
; them, this stops the build instead of silently writing another feature's
; sprite flags.
.assert ES_O_PADDLE .MOD 4 = 0, error, "breaker_obj: paddle must start a hi-table byte"
.assert ES_O_BALL = ES_O_PADDLE + 3, error, "breaker_obj: the four slots must be consecutive"

; Tiles inside the obj_chr claim's grid, and the OAM attr byte.
; attr = %0011_0000: priority 3, OBJ palette 0, tile bit 8 clear.
OBJ_TILE_PADDLE = 0
OBJ_TILE_BALL   = 1
OBJ_ATTR        = 48
OBJ_PARK_Y      = 240            ; Y = $F0 — off the bottom of the screen

; --- obj_arm: CHR + palette + OBSEL + the resting entries (scene enter) -----
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(brk_obj_chr_bin)
    sta a:OBJ_REGS + 2              ; A1T
    lda #ES_R_BRK_OBJ_CHR_ROM_SIZE
    sta a:OBJ_REGS + 5              ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^brk_obj_chr_bin
    sta a:OBJ_REGS + 4              ; A1B
    lda #ES_D_OBJ_UP_DMAP
    sta a:OBJ_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_OBJ_UP_BBAD
    sta a:OBJ_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:brk_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BRK_OBJ_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from the
    ; claim. Every sprite here is SMALL, so the hi table's size bits stay clear
    ; exactly as oam_park_all left them and obj_place writes X9 bits only.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tiles + attrs: the paddle's three segments are one tile drawn three
    ; times; the ball is the next tile in the grid ---------------------------
    lda #OBJ_TILE_PADDLE
    sta a:OBJ_P0 + 2
    sta a:OBJ_P1 + 2
    sta a:OBJ_P2 + 2
    lda #OBJ_TILE_BALL
    sta a:OBJ_BALL + 2
    lda #OBJ_ATTR
    sta a:OBJ_P0 + 3
    sta a:OBJ_P1 + 3
    sta a:OBJ_P2 + 3
    sta a:OBJ_BALL + 3
    stz a:OBJ_HI                    ; all four small, X9 clear (obj_place
                                    ; rewrites this byte every frame)
    rep #$20
    .a16
    rts

; --- obj_place: px / bx / by -> the OAM shadow ------------------------------
; In/out: A16/I16, DB=0. Called from the scene's refresh, every frame.
; Clobbers A.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED. An OAM X coordinate is nine
; bits; the ninth lives in the hi table. The paddle clamp and the arena walls
; keep bit 8 clear today, so a shortcut that assumed it would pass every test
; and ship a sprite 256 px away the first time a coordinate grew. Deriving all
; four X9 bits from the four X values every frame costs a handful of shifts and
; removes the assumption. Size bits stay 0: everything here is 8x8.
obj_place:
    .a16
    .i16
    ; ---- paddle: three segments, 8 px apart -------------------------------
    lda z:US_PX
    sep #$20
    .a8
    sta a:OBJ_P0 + 0
    lda #BRK_PADDLE_Y
    sta a:OBJ_P0 + 1
    rep #$20
    .a16
    lda z:US_PX
    clc
    adc #8
    sep #$20
    .a8
    sta a:OBJ_P1 + 0
    lda #BRK_PADDLE_Y
    sta a:OBJ_P1 + 1
    rep #$20
    .a16
    lda z:US_PX
    clc
    adc #16
    sep #$20
    .a8
    sta a:OBJ_P2 + 0
    lda #BRK_PADDLE_Y
    sta a:OBJ_P2 + 1
    rep #$20
    .a16
    ; ---- the ball: on screen only while the game is live (state 0 or 1).
    ; After GAME OVER or a WIN it is parked, so no ball freezes mid-flight
    ; over the end screen. ---------------------------------------------------
    lda z:US_GSTATE
    cmp #BRK_STATE_OVER
    bcs @ball_parked
    lda z:US_BX
    sep #$20
    .a8
    sta a:OBJ_BALL + 0
    rep #$20
    .a16
    lda z:US_BY
    sep #$20
    .a8
    sta a:OBJ_BALL + 1
    rep #$20
    .a16
    bra @hi
@ball_parked:
    .a16
    .i16
    sep #$20
    .a8
    lda #OBJ_PARK_Y
    sta a:OBJ_BALL + 1
    rep #$20
    .a16
@hi:
    .a16
    .i16
    ; ---- the shared hi byte: four X9 bits, at 2 bits per sprite ------------
    lda z:US_PX
    clc
    adc #16                         ; the rightmost paddle segment
    xba
    and #1                          ; ...its bit 8
    .repeat 4
        asl
    .endrepeat                      ; slot +2 -> bits 4-5
    sta z:US_TMP
    lda z:US_PX
    clc
    adc #8
    xba
    and #1
    asl
    asl                             ; slot +1 -> bits 2-3
    ora z:US_TMP
    sta z:US_TMP
    lda z:US_PX
    xba
    and #1                          ; slot +0 -> bits 0-1
    ora z:US_TMP
    sta z:US_TMP
    lda z:US_BX
    xba
    and #1
    .repeat 6
        asl
    .endrepeat                      ; slot +3 (the ball) -> bits 6-7
    ora z:US_TMP
    sep #$20
    .a8
    sta a:OBJ_HI
    rep #$20
    .a16
    rts

; --- obj_park: hide all four (scene exit) ----------------------------------
; In/out: A16/I16, DB=0. The scene that armed a slot re-parks it, so the next
; scene inherits the boot contract rather than this scene's sprites.
obj_park:
    .a16
    .i16
    sep #$20
    .a8
    lda #OBJ_PARK_Y
    sta a:OBJ_P0 + 1
    sta a:OBJ_P1 + 1
    sta a:OBJ_P2 + 1
    sta a:OBJ_BALL + 1
    stz a:OBJ_HI                    ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts
