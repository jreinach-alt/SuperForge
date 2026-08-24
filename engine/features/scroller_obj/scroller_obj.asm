; =============================================================================
; scroller_obj.asm — the one sprite, and it does not move
; =============================================================================
; CHR + palette from the scroller_rom blobs; one OAM slot from the `rider`
; claim. The entry is re-staged into the oam_sprites SHADOW every frame — never
; into hardware OAM, which the engine's declared VBlank GP-DMA owns.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (scroller_obj/feature.toml's
; scr_obj_obsel claim). Its VALUE comes from ES_V_SCR_OBJ_CHR_OBSEL_BASE.

SCR_OBJ_REGS = $4300 + ES_D_SCR_OBJ_UP_CH * 16

; The one entry, and the hi-table byte it shares with three parked neighbours.
; The hi table is the last 32 B of the shadow claim, so its base is derived
; from the emitted size — the same expression oam_sprites uses.
SCR_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
SCR_OBJ_RIDER   = ES_OAM_SHADOW + ES_O_RIDER * 4
SCR_OBJ_HI      = SCR_OBJ_HI_BASE + (ES_O_RIDER / 4)

; THE HI-TABLE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED. A hi
; byte covers four sprites (2 bits each: bit 0 = X9, bit 1 = size), so a
; read-modify-write of it would touch three neighbours. This rail claims ONE
; sprite, so the shortcut of writing the whole byte is only correct while that
; sprite starts the byte and the other three are the parked ones oam_park_all
; left. Asserting it stops the build if a future claim reorders the packing,
; instead of silently clearing another feature's sprite flags.
.assert ES_O_RIDER .MOD 4 = 0, error, "scroller_obj: rider must start a hi-table byte"

; The rider's screen position. It is a SCREEN position and it never changes —
; that is the whole point of the rail, and the reason it is a constant here
; rather than a state word.
SCR_RIDER_X = 120
SCR_RIDER_Y = 100

; Tile inside the scr_obj_chr claim's grid, and the OAM attr byte.
; attr = %0011_0000: priority 3, OBJ palette 0, tile bit 8 clear.
SCR_OBJ_TILE = 0
SCR_OBJ_ATTR = 48

; --- scr_obj_arm: CHR + palette + OBSEL + the resting entry (scene enter) ----
; CONTRACT scr_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palette, OBSEL and the resting entry
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
scr_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "scr_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_SCR_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(scr_obj_chr_bin)
    sta a:SCR_OBJ_REGS + 2          ; A1T
    lda #ES_R_SCR_OBJ_CHR_SIZE
    sta a:SCR_OBJ_REGS + 5          ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^scr_obj_chr_bin
    sta a:SCR_OBJ_REGS + 4          ; A1B
    lda #ES_D_SCR_OBJ_UP_DMAP
    sta a:SCR_OBJ_REGS + 0          ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SCR_OBJ_UP_BBAD
    sta a:SCR_OBJ_REGS + 1          ; BBAD: VMDATAL
    lda #(1 << ES_D_SCR_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_SCR_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:scr_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SCR_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from the
    ; claim. The one sprite is SMALL, so the hi table's size bit stays clear
    ; exactly as oam_park_all left it and scr_obj_draw writes the X9 bit only.
    sep #$20
    .a8
    lda #ES_V_SCR_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr: written once; only X/Y are per-frame ----------------
    lda #SCR_OBJ_TILE
    sta a:SCR_OBJ_RIDER + 2
    lda #SCR_OBJ_ATTR
    sta a:SCR_OBJ_RIDER + 3
    rep #$20
    .a16
    rts

; --- scr_obj_draw: stage the rider into the OAM shadow ----------------------
; CONTRACT scr_obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the rider staged into the OAM shadow
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; RE-STAGED RATHER THAN WRITTEN ONCE, deliberately. The position is constant,
; so an enter-time write would render the same picture — and would make "the
; sprite holds its screen position while the world scrolls" pass for the wrong
; reason, with the staging path never executed after frame 0. Writing it every
; frame keeps the staging path live for the whole run.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED. An OAM X coordinate is nine
; bits and the ninth lives in the hi table. SCR_RIDER_X keeps bit 8 clear
; today, so a shortcut that assumed it would pass every test here and ship a
; sprite 256 px away the first time the coordinate grew. Deriving X9 from the X
; value costs one mask and removes the assumption. The size bit stays 0: 8x8.
scr_obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "scr_obj_draw"
    lda #SCR_RIDER_X
    sep #$20
    .a8
    sta a:SCR_OBJ_RIDER + 0
    lda #SCR_RIDER_Y
    sta a:SCR_OBJ_RIDER + 1
    rep #$20
    .a16
    lda #SCR_RIDER_X
    xba                             ; bit 8 of X -> bit 0 of the low byte
    and #1                          ; ...which is this sprite's X9 bit
    sep #$20
    .a8
    sta a:SCR_OBJ_HI                ; whole byte: X9 as derived, size 0, and
                                    ; the three parked neighbours' bits clear
                                    ; exactly as oam_park_all left them
    rep #$20
    .a16
    rts
