; =============================================================================
; cf_obj.asm — the camera_follow player: one 8x8 OBJ, drawn at world - camera
; =============================================================================
; CHR + palette from the cf_rom blobs; four OAM slots (one player, three pad)
; from this feature's claims. The position is written every frame from the
; world scene's US_SCRX / US_SCRY into the oam_sprites SHADOW — never into
; hardware OAM, which the engine's declared VBlank GP-DMA owns.
;
; US_SCRX/US_SCRY are SCREEN coordinates — the scene's tick derives them as
; player world position minus camera (the rail's whole trick), and this file
; never sees a world coordinate. Mid-world the camera tracks, so these words
; are constant while the BG slides; at a world edge the camera clamps, so these
; words walk while the BG holds. Which regime is on screen is decided entirely
; upstream of this file.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (cf_obj/feature.toml's
; cf_obj_obsel claim). Its VALUE comes from ES_V_CF_OBJ_CHR_OBSEL_BASE.

CF_OBJ_REGS = $4300 + ES_D_CF_OBJ_UP_CH * 16

; The four entries, and the ONE hi-table byte they share. The hi table is the
; last 32 B of the shadow claim, so its base is derived from the emitted size —
; the same expression oam_sprites uses.
CF_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
CF_OBJ_PLAYER  = ES_OAM_SHADOW + ES_O_CF_PLAYER * 4
CF_OBJ_PAD0    = ES_OAM_SHADOW + (ES_O_CF_PAD + 0) * 4
CF_OBJ_PAD1    = ES_OAM_SHADOW + (ES_O_CF_PAD + 1) * 4
CF_OBJ_PAD2    = ES_OAM_SHADOW + (ES_O_CF_PAD + 2) * 4
CF_OBJ_HI      = CF_OBJ_HI_BASE + (ES_O_CF_PLAYER / 4)

; THE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED. A hi-table
; byte covers four sprites (2 bits each: bit 0 = X9, bit 1 = size), so writing
; it as one byte is only correct while these four slots ARE that byte's four
; sprites. Both claims are pinned (`at = 0` / `at = 1`), so this holds today; a
; future claim that reordered them would stop the build rather than silently
; write another feature's sprite flags (hud_obj's assertion, unchanged).
.assert ES_O_CF_PLAYER .MOD 4 = 0, error, "cf_obj: player must start a hi-table byte"
.assert ES_O_CF_PAD = ES_O_CF_PLAYER + 1, error, "cf_obj: the four slots must be consecutive"

; The one tile in the cf_obj_chr claim's grid, and the OAM attr byte.
; attr = %0011_0000: priority 3, OBJ palette 0, tile bit 8 clear.
CF_OBJ_TILE   = 0
CF_OBJ_ATTR   = 48
CF_OBJ_PARK_Y = 240              ; Y = 240 — off the bottom of the screen

; --- cf_obj_arm: CHR + palette + OBSEL + the resting entries (scene enter) --
; CONTRACT cf_obj_arm
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
cf_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cf_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_CF_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(cf_obj_chr_bin)
    sta a:CF_OBJ_REGS + 2           ; A1T
    lda #ES_R_CF_OBJ_CHR_SIZE
    sta a:CF_OBJ_REGS + 5           ; DAS (single transfer, armed here — DAS
                                    ; is single-shot; this routine fires once)
    sep #$20
    .a8
    lda #^cf_obj_chr_bin
    sta a:CF_OBJ_REGS + 4           ; A1B
    lda #ES_D_CF_OBJ_UP_DMAP
    sta a:CF_OBJ_REGS + 0           ; DMAP: A->B, 2 regs write-once
    lda #ES_D_CF_OBJ_UP_BBAD
    sta a:CF_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_CF_OBJ_UP_CH)
    sta a:$420B                     ; fire
    ; ---- OBJ palette 0 (CGRAM 128..143) -----------------------------------
    lda #ES_C_CF_OBJ_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:cf_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_CF_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from
    ; the claim. The player is SMALL, so the hi table's size bits stay clear
    ; exactly as oam_park_all left them and cf_obj_place writes X9 only.
    sep #$20
    .a8
    lda #ES_V_CF_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- tile + attr, and the three pad slots parked -----------------------
    lda #CF_OBJ_TILE
    sta a:CF_OBJ_PLAYER + 2
    lda #CF_OBJ_ATTR
    sta a:CF_OBJ_PLAYER + 3
    lda #CF_OBJ_PARK_Y
    sta a:CF_OBJ_PAD0 + 1
    sta a:CF_OBJ_PAD1 + 1
    sta a:CF_OBJ_PAD2 + 1
    stz a:CF_OBJ_HI                 ; all four small, X9 clear (cf_obj_place
                                    ; rewrites this byte every frame)
    rep #$20
    .a16
    rts

; --- cf_obj_place: US_SCRX / US_SCRY -> the OAM shadow ----------------------
; CONTRACT cf_obj_place
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the rider's entry re-staged. Unlike scroller's pinned rider
;             this position genuinely changes, because the clamp regimes
;             move it
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; RE-STAGED EVERY FRAME rather than written once — and unlike scroller's
; pinned rider, this position genuinely changes (the clamp regimes move it),
; so the staging path is load-bearing rather than ceremonial.
;
; THE HI BYTE IS REBUILT FROM SCRATCH, NOT PATCHED. An OAM X coordinate is nine
; bits; the ninth lives in the hi table. The screen derivation keeps scrx in
; [0, 248] once both clamps hold, so bit 8 is clear today — and a shortcut that
; assumed it would pass every test here and ship a sprite 256 px away the first
; time a coordinate grew. Deriving X9 from the X value every frame costs two
; instructions and removes the assumption. The three pad slots contribute 0
; (parked, never move); the size bits stay 0: 8x8.
cf_obj_place:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cf_obj_place"
    lda z:US_SCRX
    sep #$20
    .a8
    sta a:CF_OBJ_PLAYER + 0
    rep #$20
    .a16
    lda z:US_SCRY
    sep #$20
    .a8
    sta a:CF_OBJ_PLAYER + 1
    rep #$20
    .a16
    lda z:US_SCRX
    xba
    and #1                          ; bit 8 of X -> slot 0's X9 (bit 0)
    sep #$20
    .a8
    sta a:CF_OBJ_HI
    rep #$20
    .a16
    rts

; --- cf_obj_park: hide all four (scene exit) --------------------------------
; In/out: A16/I16, DB=0. The scene that armed a slot re-parks it, so the next
; scene inherits the boot contract rather than this scene's sprites. This rail
; has one scene and never transitions, so nothing calls it today — it exists
; because the claim's contract is symmetric and a second scene would need it.
cf_obj_park:
    .a16
    .i16
    sep #$20
    .a8
    lda #CF_OBJ_PARK_Y
    sta a:CF_OBJ_PLAYER + 1
    sta a:CF_OBJ_PAD0 + 1
    sta a:CF_OBJ_PAD1 + 1
    sta a:CF_OBJ_PAD2 + 1
    stz a:CF_OBJ_HI                 ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts
