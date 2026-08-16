; =============================================================================
; scenes/bands.asm — TWO cameras, compiled into one HDMA table pair
; =============================================================================
; Enter uploads the plane, writes the shared Mode 7 origin once under forced
; blank, compiles TWO bands into the two WRAM tables and arms two channels.
; After that the picture drives itself off the PPU: the VBlank hook is one call
; and two stores, and the tick is one pad read.

.scope bands

; --- the band geometry ------------------------------------------------------
; SEAM 112 splits the 224-line picture in half; SCALE_A 1.0 renders the world's
; 8-px checker at an 8-px on-screen period and SCALE_B 0.25 renders the SAME
; world at 32.
;
; BOTH ENTRIES CARRY THEIR BAND'S FULL HEIGHT (112 + 112 = 224), which is
; `sh2_cam`'s own origin-table shape and puts band 2's transfer on scanline 112
; exactly. The tempting alternative — a top band of SEAM - 1 lines — leaves 223
; lines of table for a 224-line picture and moves the seam by one scanline. The
; difference is asserted, not assumed:
; test_the_seam_is_exactly_where_the_declaration_puts_it reads the row.
SHM_SEAM     = 112
SHM_B1_LINES = SHM_SEAM                     ; 0..111
SHM_B2_LINES = SHM_LINES - SHM_SEAM         ; 112..223
SHM_BANDS_N  = 2

.assert SHM_B1_LINES + SHM_B2_LINES = SHM_LINES, error, "bands: the band heights do not cover the picture"

; --- the camera scales, 8.8 fixed point -------------------------------------
SHM_SCALE_A = $0100                         ; 1.0  -> an 8-px checker period
SHM_SCALE_B = $0040                         ; 0.25 -> a 32-px period

; --- the LIVE band -----------------------------------------------------------
; The BOTTOM one. Its clamp range spans from twice this rail's magnification
; (0.125, a 64-px period) up to camera A's own scale — so driving Right to the
; ceiling COLLAPSES the two cameras onto one, which is the rail's own control
; picture reached by input instead of by a second ROM.
SHM_LIVE_SLOT = 1
SHM_ZOOM_LO   = $0020                       ; 0.125 -> a 64-px period
SHM_ZOOM_HI   = SHM_SCALE_A                 ; collapse: both bands at 1.0

; The scene's TM: the Mode 7 plane and nothing else. Each bit is named by the
; feature that composites its layer — shm_floor owns the plane — so this line is
; the composition and nothing else. No OBJ bit: nothing draws.
SHM_TM = SHM_TM_BG1

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 3 colours + M7SEL

    ; ---- the ORIGIN, written ONCE under forced blank -----------------------
    ; `shm_cam`'s plain `reg` claim, and the mirror image of `sh2_cam`'s `seed`:
    ; there, per-band origin HDMA overwrites these four every line 0, so the
    ; enter write is a base. Here the split is entirely in the MATRIX, so every
    ; band shares ONE origin and these values stand for the whole frame.
    ;
    ; The ValueLatch guard is satisfied BY CONSTRUCTION: all four are
    ; write-twice 13-bit ports, they are written under forced blank, and they
    ; are never touched during active display — the only writer then is the
    ; matrix HDMA, which touches M7A-M7D and not these.
    ;
    ; M7X/M7Y = the world centre. With M7HOFS/M7VOFS at 0 the transform reduces
    ; to `world = scale * (screen - centre) + centre` per axis, so band 1 at
    ; scale 1.0 shows world pixel `screen` exactly — the identity that makes the
    ; on-screen checker period 8 px and therefore READABLE as the band's scale.
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
    ; Power-on DP is random and shm_cam declares no `[init] zero`: these four
    ; stores ARE the write-before-read contract for all eight bytes (rule 5).
    ; shm_zoom_stamp reads SHM_SCALE and SHM_OFF in the FIRST VBlank after the
    ; screen comes on, so a missing store would show as the bottom band at a
    ; garbage zoom rather than as a subtle drift.
    lda #SHM_SCALE_B
    sta z:SHM_SCALE
    lda #(SHM_LIVE_SLOT * SHM_ENTRY)
    sta z:SHM_OFF
    lda #SHM_ZOOM_LO
    sta z:SHM_LO
    lda #SHM_ZOOM_HI
    sta z:SHM_HI

    ; ---- compile the bands into the two HDMA tables ------------------------
    ; THE WHOLE OF THE SPLIT, and it is a list. shm_zero first (the terminator
    ; slack must not be power-on garbage — the DMA controller fetches past the
    ; $00 on real hardware), then one SHM_BAND per camera in scanline order,
    ; then the terminator, then the channel staging.
    ;
    ; Adding a third camera here is ONE more line. That is the sibling rail.
    jsr shm_zero
    SHM_BAND 0, SHM_B1_LINES, SHM_SCALE_A
    SHM_BAND 1, SHM_B2_LINES, SHM_SCALE_B
    SHM_END  SHM_BANDS_N
    jsr shm_arm

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on shm_floor's behalf
    ; (see that feature.toml's attribution note). M7SEL is the feature's own and
    ; floor_arm has already written it.
    ;
    ; WRITTEN ONCE, FOR ALL 224 LINES. This rail does not split the video mode:
    ; every band is Mode 7 the whole frame and the split is entirely in the
    ; camera matrix. That is why `split_band` is neither composed nor
    ; generalised here — there is no second splitter.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #SHM_TM
    sta a:$212C                     ; TM: the plane

    ; ---- arm the two channels --------------------------------------------
    ; The scene_mgr NMI applies this shadow to HDMAEN on every armed frame; the
    ; channel REGISTERS were staged by shm_arm into the 128-byte shadow the same
    ; NMI MVNs to $4300. Enabling a channel whose shadow was never staged is the
    ; shape that reads as "the picture is garbage" — hence both halves in one
    ; enter, in this order.
    lda #((1 << ES_H_SHMAB_CH) | (1 << ES_H_SHMCD_CH))
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate; call it from A16 and the CPU
    ; eats the following opcode byte as that immediate's high half, the ramp
    ; never arms, INIDISP stays at brightness 0, and the ROM renders black with
    ; perfectly correct VRAM and CGRAM. It has cost a real debugging round
    ; before: the silent-corruption class arriving through a CROSS-FILE width
    ; contract the lint cannot see in either direction.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0.
;
; THE WHOLE OF THE RAIL'S MAIN-THREAD COST: one pad read and a clamped add.
; It runs during active display and touches DP only; the two bytes that reach
; the HDMA table are the VBlank hook's.
tick:
    .a16
    .i16
    jsr shm_zoom_step
    rts

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's contract), and re-uploading 32 KB to prove a
; point costs a frame. What IS undone is the display state this scene turned
; on. HDMAEN is scene_mgr's own to clear at the transition. This rail has no
; edges, so nothing reaches here — it is the contract, kept honest.
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
