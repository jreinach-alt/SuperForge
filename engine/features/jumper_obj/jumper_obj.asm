; =============================================================================
; jumper_obj.asm — the player sprite: the physics' whole visible output
; =============================================================================
; CHR + palette from the jumper_rom blobs; one OAM slot from the `hopper`
; claim. The entry is re-staged into the oam_sprites SHADOW every frame from
; the scene tick — never into hardware OAM, which the engine's declared VBlank
; GP-DMA owns. It is re-staged every frame rather than written once at enter,
; so the staging path is exercised on every frame rather than only on frame 0.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (jr_obsel). Value from
; ES_V_JR_OBJ_CHR_OBSEL_BASE.

JR_OBJ_REGS = $4300 + ES_D_JR_OBJ_UP_CH * 16

; The one entry, and the hi-table byte it shares with three parked neighbours.
JR_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
JR_OBJ_HOPPER  = ES_OAM_SHADOW + ES_O_HOPPER * 4
JR_OBJ_HI      = JR_OBJ_HI_BASE + (ES_O_HOPPER / 4)

; A hi byte covers four sprites (2 bits each: X9 + size); this rail claims ONE,
; so writing the whole byte is only correct while the hopper starts the byte
; and the other three stay the parked ones oam_park_all left. Asserted, so a
; future claim reordering stops the build (scroller_obj's discipline).
.assert ES_O_HOPPER .MOD 4 = 0, error, "jumper_obj: hopper must start a hi-table byte"

; Tile inside the jr_obj_chr claim's grid: tile 0 is empty so a zeroed OAM
; entry draws nothing, tile 1 is the solid red player. Attr = %0011_0000:
; priority 3, OBJ palette 0.
JR_OBJ_TILE = 1
JR_OBJ_ATTR = 48

; --- jr_obj_arm: CHR + palette + OBSEL + tile/attr (scene enter) ------------
; CONTRACT jr_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the OBJ page, the palette and OBSEL
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
jr_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "jr_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_JR_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(jr_obj_chr_bin)
    sta a:JR_OBJ_REGS + 2           ; A1T
    lda #ES_R_JR_OBJ_CHR_SIZE
    sta a:JR_OBJ_REGS + 5           ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^jr_obj_chr_bin
    sta a:JR_OBJ_REGS + 4           ; A1B
    lda #ES_D_JR_OBJ_UP_DMAP
    sta a:JR_OBJ_REGS + 0           ; DMAP: A->B, 2 regs write-once
    lda #ES_D_JR_OBJ_UP_BBAD
    sta a:JR_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_JR_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_JR_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:jr_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_JR_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8), OBJ chr base from the claim ------
    sep #$20
    .a8
    lda #ES_V_JR_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr: written once; only X/Y are per-frame ----------------
    lda #JR_OBJ_TILE
    sta a:JR_OBJ_HOPPER + 2
    lda #JR_OBJ_ATTR
    sta a:JR_OBJ_HOPPER + 3
    rep #$20
    .a16
    rts

; --- jr_obj_draw: stage the player into the OAM shadow ----------------------
; CONTRACT jr_obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the hero's entry from US_PX and US_PYI. OAM Y is the world Y
;             directly: the OBJ +1 display rule and the BG's VOFS -1 land
;             both surfaces on the same world row, so the box the physics
;             collides is the box the screen shows. The hi byte is rebuilt
;             from scratch, never patched: an OAM x is nine bits and the
;             ninth lives in the hi table, so X9 is DERIVED from bit 8 of
;             the x every frame. A shortcut that assumed it clear passes
;             every test until a coordinate grows, and then ships a sprite
;             256 px away
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; Position from the scene's own state: US_PX (pixels) and US_PYI (the physics'
; pixel mirror). OAM Y = world Y directly — the OBJ +1 display rule and the
; BG's VOFS -1 land both surfaces on the same world row, so the box the physics
; collides is the box the screen shows.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED: X9 derived from bit 8 of
; the X value every frame (px never exceeds 240 in this world; deriving it
; anyway is what keeps the assumption out of the code — the stale-X9 lesson).
jr_obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "jr_obj_draw"
    lda z:US_PX
    sep #$20
    .a8
    sta a:JR_OBJ_HOPPER + 0
    rep #$20
    .a16
    lda z:US_PYI
    sep #$20
    .a8
    sta a:JR_OBJ_HOPPER + 1
    rep #$20
    .a16
    lda z:US_PX
    xba                             ; bit 8 of X -> bit 0 of the low byte
    and #1                          ; ...which is this sprite's X9 bit
    sep #$20
    .a8
    sta a:JR_OBJ_HI                 ; whole byte: X9 as derived, size 0, and
                                    ; the three parked neighbours' bits clear
    rep #$20
    .a16
    rts
