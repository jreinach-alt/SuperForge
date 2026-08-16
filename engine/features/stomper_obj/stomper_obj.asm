; =============================================================================
; stomper_obj.asm — the three live actors, staged into the OAM shadow
; =============================================================================
; CHR + palettes from the stomper_rom blobs; four OAM slots from the `actors`
; claim (+0 player, +1 enemy 1, +2 enemy 2, +3 permanently parked pad). Entries
; are re-staged into the oam_sprites SHADOW every frame — never into hardware
; OAM, which the engine's declared VBlank GP-DMA owns.
;
; FIXED SLOTS, PARK-ON-DEATH: a dead enemy's entry is parked at Y = $F0
; (oam_park_all's own convention) instead of compacting its neighbour down. On
; screen the sprite simply disappears; in OAM every readback stays
; interpretable without knowing the death order.

ST_OBJ_REGS = $4300 + ES_D_ST_OBJ_UP_CH * 16

; The three entries, and the hi-table byte they share with the parked pad. The
; hi table is the last 32 B of the shadow claim (scroller_obj's shape).
ST_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
ST_OBJ_PLAYER  = ES_OAM_SHADOW + (ES_O_ACTORS + 0) * 4
ST_OBJ_E1      = ES_OAM_SHADOW + (ES_O_ACTORS + 1) * 4
ST_OBJ_E2      = ES_OAM_SHADOW + (ES_O_ACTORS + 2) * 4
ST_OBJ_HI      = ST_OBJ_HI_BASE + (ES_O_ACTORS / 4)

; THE HI-TABLE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED
; (scroller_obj's argument): the whole-byte rebuild is only correct while the
; four claimed sprites fill exactly one hi byte from its bottom bits.
.assert ES_O_ACTORS .MOD 4 = 0, error, "stomper_obj: actors must start a hi-table byte"

; The parked Y every culled entry carries — oam_park_all's own off-screen row.
ST_OBJ_PARK_Y = 240

; Tile + attr: all three actors draw the same solid 8x8 (OBJ tile 1); the
; palette bit is what tells them apart — attr $00 puts the player on palette 0,
; $02 puts the enemies on palette 1. Priority 3 (bits 4-5) is the tree's OBJ
; convention (scroller_obj attr 48); no actor ever overlaps a BG tile, so the
; priority is invisible either way.
ST_OBJ_TILE       = 1
ST_OBJ_ATTR_PLAYR = 48                  ; %00110000: priority 3, OBJ palette 0
ST_OBJ_ATTR_ENEMY = 50                  ; %00110010: priority 3, OBJ palette 1

; --- st_obj_arm: CHR + palettes + OBSEL + static tile/attr (scene enter) ----
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Clobbers A, X.
st_obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_ST_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(st_obj_chr_bin)
    sta a:ST_OBJ_REGS + 2           ; A1T
    lda #ES_R_ST_OBJ_CHR_SIZE
    sta a:ST_OBJ_REGS + 5           ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^st_obj_chr_bin
    sta a:ST_OBJ_REGS + 4           ; A1B
    lda #ES_D_ST_OBJ_UP_DMAP
    sta a:ST_OBJ_REGS + 0           ; DMAP: A->B, 2 regs write-once
    lda #ES_D_ST_OBJ_UP_BBAD
    sta a:ST_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_ST_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palettes 0 AND 1 (CGRAM 128..159, one claim, one pass) -------
    lda #ES_C_ST_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:st_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_ST_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0, OBJ chr base from the claim ------------------
    ; All actors are SMALL 8x8, so the hi table's size bits stay clear exactly
    ; as oam_park_all left them; the draw writes X9 bits only.
    sep #$20
    .a8
    lda #ES_V_ST_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- static tile + attr: written once; X/Y are per-frame --------------
    lda #ST_OBJ_TILE
    sta a:ST_OBJ_PLAYER + 2
    sta a:ST_OBJ_E1 + 2
    sta a:ST_OBJ_E2 + 2
    lda #ST_OBJ_ATTR_PLAYR
    sta a:ST_OBJ_PLAYER + 3
    lda #ST_OBJ_ATTR_ENEMY
    sta a:ST_OBJ_E1 + 3
    sta a:ST_OBJ_E2 + 3
    rep #$20
    .a16
    rts

; --- st_obj_draw: stage the three actors into the OAM shadow ----------------
; In/out: A16/I16, DB=0. Called from the scene's tick EVERY frame (and once
; from enter, so frame 0 commits real entries). Clobbers A, X.
;
; All three actors are re-staged EVERY frame rather than written once: a
; write-once sprite would pass "the sprite is where the state says" for the
; wrong reason and leave the staging path untested for the whole run
; (scroller_obj's argument). A dead enemy is PARKED here — the draw-side half
; of the alive gate.
;
; THE HI BYTE IS REBUILT FROM SCRATCH each frame: X9 for each live actor is
; DERIVED from bit 8 of its x (a parked entry's X9 is forced 0 — its X byte is
; stale by design and must not leak a ninth bit); the pad's bits stay 0.
; ES_ST_HI is the OR accumulator (write-before-read, this call).
st_obj_draw:
    .a16
    .i16
    ; ---- player (slot +0): always live -------------------------------------
    lda z:US_PX
    sep #$20
    .a8
    sta a:ST_OBJ_PLAYER + 0
    rep #$20
    .a16
    lda z:US_PYI
    sep #$20
    .a8
    sta a:ST_OBJ_PLAYER + 1
    rep #$20
    .a16
    lda z:US_PX
    xba                             ; bit 8 of X -> bit 0
    and #1                          ; player X9 -> hi-byte bit 0
    sta z:ES_ST_HI
    ; ---- enemy 1 (slot +1): live at (e1x, ST_E1_Y) or parked ---------------
    lda z:US_E1ALIVE
    beq @e1_dead
    lda z:US_E1X
    sep #$20
    .a8
    sta a:ST_OBJ_E1 + 0
    lda #ST_E1_Y
    sta a:ST_OBJ_E1 + 1
    rep #$20
    .a16
    lda z:US_E1X
    xba
    and #1
    asl
    asl                             ; enemy 1 X9 -> hi-byte bit 2
    ora z:ES_ST_HI
    sta z:ES_ST_HI
    bra @e1_done
@e1_dead:
    .a16
    .i16
    sep #$20
    .a8
    lda #ST_OBJ_PARK_Y
    sta a:ST_OBJ_E1 + 1             ; parked: off-screen row, X9 stays 0
    rep #$20
    .a16
@e1_done:
    .a16
    .i16
    ; ---- enemy 2 (slot +2): live at (e2x, ST_E2_Y) or parked ---------------
    lda z:US_E2ALIVE
    beq @e2_dead
    lda z:US_E2X
    sep #$20
    .a8
    sta a:ST_OBJ_E2 + 0
    lda #ST_E2_Y
    sta a:ST_OBJ_E2 + 1
    rep #$20
    .a16
    lda z:US_E2X
    xba
    and #1
    asl
    asl
    asl
    asl                             ; enemy 2 X9 -> hi-byte bit 4
    ora z:ES_ST_HI
    sta z:ES_ST_HI
    bra @e2_done
@e2_dead:
    .a16
    .i16
    sep #$20
    .a8
    lda #ST_OBJ_PARK_Y
    sta a:ST_OBJ_E2 + 1
    rep #$20
    .a16
@e2_done:
    .a16
    .i16
    ; ---- the whole hi byte: three derived X9 bits, sizes 0, pad 0 ----------
    lda z:ES_ST_HI
    sep #$20
    .a8
    sta a:ST_OBJ_HI
    rep #$20
    .a16
    rts
