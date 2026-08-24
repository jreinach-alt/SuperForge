; =============================================================================
; sr_obj.asm — the runner sprite: the player's whole visible output
; =============================================================================
; CHR + palette from the sr_rom blobs; one OAM slot from the `runner` claim.
; The entry is re-staged into the oam_sprites SHADOW every frame from the scene
; tick — never into hardware OAM, which the engine's declared VBlank GP-DMA
; owns. It is re-staged every frame rather than written once at enter, so the
; staging path is exercised on every frame rather than only on frame 0.
;
; THE X THIS FEATURE CONSUMES IS A SCREEN COORDINATE: US_SCRX = px - cam_x,
; derived by the scene every tick. The world/screen subtraction is half the
; rail's lesson and it happens in the game (scenes/run.asm); this file only
; renders its result. Y is US_PYI (the physics' pixel mirror) directly — cam_y
; is pinned 0, so world row = screen row = OAM row, and the box the physics
; collides is the box the screen shows (jumper_obj's derivation).
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (sr_obsel). Value from
; ES_V_SR_OBJ_CHR_OBSEL_BASE.

SR_OBJ_REGS = $4300 + ES_D_SR_OBJ_UP_CH * 16

; The one entry, and the hi-table byte it shares with three parked neighbours.
SR_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
SR_OBJ_RUNNER  = ES_OAM_SHADOW + ES_O_RUNNER * 4
SR_OBJ_HI      = SR_OBJ_HI_BASE + (ES_O_RUNNER / 4)

; A hi byte covers four sprites (2 bits each: X9 + size); this rail claims ONE,
; so writing the whole byte is only correct while the runner starts the byte
; and the other three stay the parked ones oam_park_all left. Asserted, so a
; future claim reordering stops the build (jumper_obj's discipline).
.assert ES_O_RUNNER .MOD 4 = 0, error, "sr_obj: runner must start a hi-table byte"

; Tile inside the sr_obj_chr claim's grid: tile 0 is empty so a zeroed OAM
; entry draws nothing, tile 1 is the solid red player. Attr = %0011_0000:
; priority 3, OBJ palette 0.
SR_OBJ_TILE = 1
SR_OBJ_ATTR = 48

; --- sr_obj_arm: CHR + palette + OBSEL + tile/attr (scene enter) ------------
; CONTRACT sr_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palette, OBSEL and the static tile/attr bytes
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
sr_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sr_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_SR_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(sr_obj_chr_bin)
    sta a:SR_OBJ_REGS + 2           ; A1T
    lda #ES_R_SR_OBJ_CHR_SIZE
    sta a:SR_OBJ_REGS + 5           ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^sr_obj_chr_bin
    sta a:SR_OBJ_REGS + 4           ; A1B
    lda #ES_D_SR_OBJ_UP_DMAP
    sta a:SR_OBJ_REGS + 0           ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SR_OBJ_UP_BBAD
    sta a:SR_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_SR_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_SR_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:sr_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SR_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8), OBJ chr base from the claim ------
    sep #$20
    .a8
    lda #ES_V_SR_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr: written once; only X/Y are per-frame ----------------
    lda #SR_OBJ_TILE
    sta a:SR_OBJ_RUNNER + 2
    lda #SR_OBJ_ATTR
    sta a:SR_OBJ_RUNNER + 3
    rep #$20
    .a16
    rts

; --- sr_obj_draw: stage the runner into the OAM shadow ----------------------
; CONTRACT sr_obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the runner staged into the OAM shadow
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one — playing AND won, because the runner stays on
;             screen after the goal
;   tail:     rts
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED: X9 derived from bit 8 of
; the SCREEN X every frame. The follow clamp keeps scrx in 8..240 on this rail,
; so the bit is always 0 — deriving it anyway is what keeps that assumption out
; of the code (the stale-X9 lesson, jumper_obj's note).
sr_obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sr_obj_draw"
    lda z:US_SCRX
    sep #$20
    .a8
    sta a:SR_OBJ_RUNNER + 0
    rep #$20
    .a16
    lda z:US_PYI
    sep #$20
    .a8
    sta a:SR_OBJ_RUNNER + 1
    rep #$20
    .a16
    lda z:US_SCRX
    xba                             ; bit 8 of X -> bit 0 of the low byte
    and #1                          ; ...which is this sprite's X9 bit
    sep #$20
    .a8
    sta a:SR_OBJ_HI                 ; whole byte: X9 as derived, size 0, and
                                    ; the three parked neighbours' bits clear
    rep #$20
    .a16
    rts
