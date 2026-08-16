; =============================================================================
; scenes/bands.asm — THREE cameras, compiled into the SAME two HDMA tables
; =============================================================================
; This file is `game/split_h_matrix_demo/scenes/bands.asm` with one more
; SHM_BAND line, one more scale constant and a different band geometry. The
; band count being a table property and not a declared one is thereby
; checkable: nothing else about the two rails differs — not the features, not
; the claims, not the channels, not the art, not the origin, not the arming,
; not the tick.

.scope bands

; --- the band geometry ------------------------------------------------------
; Two seams at 75 and 150 cut the 224-line picture into 75 / 75 / 74.
SHM_SEAM1    = 75
SHM_SEAM2    = 150
SHM_B1_LINES = SHM_SEAM1                    ; 0..74
SHM_B2_LINES = SHM_SEAM2 - SHM_SEAM1        ; 75..149
SHM_B3_LINES = SHM_LINES - SHM_SEAM2        ; 150..223
SHM_BANDS_N  = 3

.assert SHM_B1_LINES + SHM_B2_LINES + SHM_B3_LINES = SHM_LINES, error, "bands: the band heights do not cover the picture"

; --- the camera scales, 8.8 fixed point -------------------------------------
; THREE distinct on-screen checker periods — 8, 32 and 16 px — and the middle
; band is the SMALLEST scale rather than the ordering being monotonic. That is
; deliberate: a monotonic ramp could be mistaken for one perspective camera,
; and this cannot.
SHM_SCALE_A = $0100                         ; 1.0  -> an 8-px checker period
SHM_SCALE_B = $0040                         ; 0.25 -> a 32-px period
SHM_SCALE_C = $0080                         ; 0.5  -> a 16-px period

; --- the LIVE band -----------------------------------------------------------
; The BOTTOM one (slot 2), matching the sibling's choice of "the last band".
; Its clamp ceiling is camera A's scale, so driving Right to the top collapses
; band 3 onto band 1's period — a one-camera control picture reached by input
; rather than by a second ROM, and it leaves the MIDDLE band at 0.25 so "three
; distinct cameras" fails while "two do" survives.
SHM_LIVE_SLOT = 2
SHM_ZOOM_LO   = $0020                       ; 0.125 -> a 64-px period
SHM_ZOOM_HI   = SHM_SCALE_A                 ; collapse: band 3 onto band 1

; The scene's TM: the Mode 7 plane and nothing else. No OBJ bit: nothing draws.
SHM_TM = SHM_TM_BG1

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 3 colours + M7SEL

    ; ---- the ORIGIN, written ONCE under forced blank -----------------------
    ; `shm_cam`'s plain `reg` claim. Every band shares ONE origin — the split is
    ; entirely in the MATRIX — so these four values stand for the whole frame,
    ; and the ValueLatch guard is satisfied by construction (write-twice ports,
    ; written under forced blank, never touched during active display; the only
    ; writer then is the matrix HDMA, which touches M7A-M7D and not these).
    sep #$20
    .a8
    lda #<SHM_CENTRE
    sta a:$211F
    lda #>SHM_CENTRE
    sta a:$211F                     ; M7X = the world centre
    lda #<SHM_CENTRE
    sta a:$2120
    lda #>SHM_CENTRE
    sta a:$2120                     ; M7Y
    lda #0
    sta a:$210D
    sta a:$210D                     ; M7HOFS = 0 (low, high)
    sta a:$210E
    sta a:$210E                     ; M7VOFS = 0
    rep #$20
    .a16

    ; ---- the zoom state, seeded before anything reads it -------------------
    ; The write-before-read contract for all eight bytes of shm_cam's dp claim
    ; (rule 5) — power-on DP is random and the feature declares no
    ; `[init] zero`. SHM_OFF is the only line that differs from the sibling's:
    ; slot 2 rather than slot 1, which is the ENTIRE mechanism by which one
    ; feature serves both band counts.
    lda #SHM_SCALE_C
    sta z:SHM_SCALE
    lda #(SHM_LIVE_SLOT * SHM_ENTRY)
    sta z:SHM_OFF
    lda #SHM_ZOOM_LO
    sta z:SHM_LO
    lda #SHM_ZOOM_HI
    sta z:SHM_HI

    ; ---- compile the bands into the two HDMA tables ------------------------
    ; THREE lines where the sibling has two. Same tables, same channels, same
    ; terminator, one more HBlank write per channel per frame.
    jsr shm_zero
    SHM_BAND 0, SHM_B1_LINES, SHM_SCALE_A
    SHM_BAND 1, SHM_B2_LINES, SHM_SCALE_B
    SHM_BAND 2, SHM_B3_LINES, SHM_SCALE_C
    SHM_END  SHM_BANDS_N
    jsr shm_arm

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on shm_floor's behalf.
    ; Written ONCE for all 224 lines: every band is Mode 7 the whole frame.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #SHM_TM
    sta a:$212C                     ; TM: the plane

    ; ---- arm the two channels --------------------------------------------
    lda #((1 << ES_H_SHMAB_CH) | (1 << ES_H_SHMCD_CH))
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY — fade_start_in is `.a8` and calling it from
    ; A16 eats the following opcode byte as an immediate's high half, leaving
    ; INIDISP at brightness 0 with perfectly correct VRAM. It has cost a real
    ; debugging round before.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0. One pad read and a clamped add, during active display.
tick:
    .a16
    .i16
    jsr shm_zoom_step
    rts

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
; No edges on this rail, so nothing reaches here — it is the contract, kept
; honest.
exit:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
