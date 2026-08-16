; =============================================================================
; scenes/persp.asm — the two perspective cameras, seeded and set running
; =============================================================================
; Enter uploads the plane, seeds the two animation indices, builds SIX HDMA
; tables and arms six channels (a per-band INDIRECT matrix pair plus a per-band
; DIRECT origin pair). After that the FLOOR drives itself off the PPU: the
; VBlank hook is ONE call, `cam_tick`, which re-points the two bands at the
; poses their indices name.
;
; WHERE THE TWO BANDS COME FROM. Both are Mode 7, both look at the same 128x128
; plane, both stream a 112-line per-scanline pose in REPEAT mode. TWO things
; differ, on purpose, and they are the rail's two independent claims:
;
;   the MATRIX   band 1 streams camera A's HEADING set, band 2 camera B's ZOOM
;                set — different perspective parameters, so the two trapezoids
;                have measurably different on-screen checker periods at the
;                same screen row.
;   the ORIGIN   camera B sits one full checker stripe east of camera A (256
;                world px), so band 2 renders the WARM (red) stripe and band 1
;                the COOL (no red) one. That colour separation is the rail's
;                own per-band POSITION oracle, orthogonal to the period.
;
; The two fail INDEPENDENTLY, which is what makes them two claims rather than
; one: holding Down collapses the matrix claim (zoom 0 is camera A's own pose)
; and leaves the position claim standing.

.scope persp

; The scene's TM: the Mode 7 plane, and nothing else. Named by the feature that
; composites the layer — shp_floor owns the plane — so this line is the whole
; composition. There is no OBJ bit: nothing draws.
SHP_TM = SHP_TM_BG1

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 5 colours + M7SEL

    ; ---- the two animation indices, seeded before anything reads them -----
    ; Power-on DP is random and shp_cam declares no `[init] zero` for its dp
    ; claim: these two stores ARE the write-before-read contract for the four
    ; bytes cam_ptrs reads (rule 5), not defensive initialisation. cam_arm
    ; derives both bands' pose pointers straight out of them on the next line,
    ; so a missing one shows as a band streaming a pose nobody chose — or, if
    ; the garbage index is large enough, as a pointer past the end of its set.
    ;
    ; Camera B boots MID-SWEEP (SHP_ZOOM_0), not at 0, and that is deliberate:
    ; zoom 0 IS camera A's heading-0 pose, so booting there would render two
    ; identical trapezoids and hide the split behind its own control.
    lda #SHP_HEAD_0
    sta z:SHP_HEAD
    lda #SHP_ZOOM_0
    sta z:SHP_ZOOM

    ; ---- the origin SEED, under forced blank ------------------------------
    ; These four registers are shp_cam's `seed = true` reg claim: the value
    ; established here is a base that the feature's own origin HDMA pair
    ; overwrites from line 0 of every frame. The seed is band 1's, so even a
    ; frame in which HDMA never armed would render a coherent picture rather
    ; than whatever the PPU powered on holding.
    ;
    ; All four are write-twice 13-bit ports: low byte then high byte, and the
    ; hardware latch is what pairs them. Written under forced blank on purpose
    ; — a write-twice spun across active display is the ValueLatch hazard, and
    ; the only writer during display is HDMA, which delivers complete pairs.
    sep #$20
    .a8
    lda #<SHP_POS_AX
    sta a:$211F
    lda #>SHP_POS_AX
    sta a:$211F                     ; M7X
    lda #<SHP_POS_AY
    sta a:$2120
    lda #>SHP_POS_AY
    sta a:$2120                     ; M7Y
    lda #<(SHP_POS_AX - SHP_HALF_W)
    sta a:$210D
    lda #>(SHP_POS_AX - SHP_HALF_W)
    sta a:$210D                     ; M7HOFS
    lda #<(SHP_POS_AY - SHP_SEAM)
    sta a:$210E
    lda #>(SHP_POS_AY - SHP_SEAM)
    sta a:$210E                     ; M7VOFS
    rep #$20
    .a16

    jsr cam_arm                     ; six tables + six channel shadows

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on shp_floor's behalf
    ; (see that feature.toml's attribution note). M7SEL is the feature's own and
    ; floor_arm has already written it.
    ;
    ; WRITTEN ONCE, FOR ALL 224 LINES. This rail does not split the video mode:
    ; both bands are Mode 7 the whole frame and the split is entirely in the
    ; camera matrix and origin. That is why `split_band` is neither composed
    ; nor generalised here — there is no second splitter.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #SHP_TM
    sta a:$212C                     ; TM: the plane

    ; ---- arm the six channels --------------------------------------------
    ; The scene_mgr NMI applies this shadow to HDMAEN on every armed frame; the
    ; channel REGISTERS were staged by cam_arm into the 128-byte shadow the same
    ; NMI MVNs to $4300. Enabling a channel whose shadow was never staged is
    ; the shape that reads as "the picture is garbage" — hence both halves in
    ; one enter, in this order.
    lda #((1 << ES_H_SHPAB1_CH) | (1 << ES_H_SHPCD1_CH))
    ora #((1 << ES_H_SHPAB2_CH) | (1 << ES_H_SHPCD2_CH))
    ora #((1 << ES_H_SHPXY_CH) | (1 << ES_H_SHPHV_CH))
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate; call it from A16 and
    ; the CPU eats the following opcode byte as that immediate's high half, the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders black
    ; with perfectly correct VRAM and CGRAM. It has cost a real debugging round
    ; before: the silent-corruption class arriving through a CROSS-FILE width
    ; contract the lint cannot see in either direction.
    ;
    ; A bare INIDISP write here would not do: scene_mgr commits INIDISP from its
    ; own NMI shadow, so it would be overwritten on the first VBlank.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0.
;
; ONE CALL. `cam_input` reads the latched pad and steps whichever of the two
; animation axes the player is holding: Left/Right camera A's heading (wrapping
; — a heading is cyclic), Up/Down camera B's zoom (clamping — a zoom is a
; segment, and its two ends are this rail's runtime controls).
;
; IN THE TICK RATHER THAN THE NMI HOOK, and for the same reason `sh2_cam`'s
; advance moved there: the VBlank window's job is to COMMIT the state, and the
; state advance belongs in active display where there is room. The phase is
; ADVANCE-THEN-STAMP — this frame's tick moves the indices, the next VBlank's
; cam_tick points the bands at them — so the picture a frame renders is always
; the state its own tick produced.
tick:
    .a16
    .i16
.ifdef SHP_AUTODEMO
    jsr cam_auto
.else
    jsr cam_input
.endif
    rts

.ifdef SHP_AUTODEMO
; --- cam_auto (-DSHP_AUTODEMO): both cameras, driving themselves -------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE AUTONOMOUS BUILD: no pad, both axes off the frame counter, so the rail
; plays its whole cycle with no controller attached. The SHIPPING ROM is the
; pad-driven one — `sh2_autocam` splits the same way — because an axis that can
; be stopped, held and walked back is assertable and a free-running one can only
; be sampled. This variant is the sampled version, kept for a cold demo.
;
; THE TWO RATES COINCIDE, which is why this needs no counter of its own. A full
; turn is 64 frames; `pose_rom` is indexed by 64 headings, so a full turn is +1
; heading per frame and SHP_HEAD IS the frame counter mod 64. The 8 zooms cycle
; in those same 64 frames, and `(frame & 63) >> 3` is `(frame >> 3) & 7` — the
; identical sawtooth. So the zoom is a pure function of the heading and NO new
; dp claim is needed; one that existed only in the -D build would shift the
; allocator's map and move the SHIPPING ROM's md5 for a variant it does not
; contain (split_v_fight's demo_walk pays the same toll, fight.asm:326-330).
;
; The boot seed stands (enter's SHP_ZOOM_0 mid-sweep); the first tick moves the
; zoom onto the sawtooth's phase, so frames 1..7 render zoom 0 — camera A's own
; pose, i.e. the matrix collapse. That is the sweep's endpoint, not a defect,
; and one boot plays the whole cycle.
;
; WIDTH-RISK: A16/I16 on entry AND exit; the body contains NO sep/rep, so it
; cannot leak a width into the caller on either axis.
cam_auto:
    .a16
    .i16
    lda z:SHP_HEAD
    inc a
    and #SHP_HEAD_MASK              ; +1 heading/frame, wrapping: frame mod 64
    sta z:SHP_HEAD
    lsr a
    lsr a
    lsr a                           ; head >> 3 == (frame >> 3) & 7
    sta z:SHP_ZOOM
    rts
.endif

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's contract), and re-uploading 32 KB to prove a
; point costs a frame. What IS undone is the display state this scene turned on,
; so a successor inherits a blank main screen rather than a Mode 7 plane it
; never asked for. HDMAEN is scene_mgr's own to clear at the transition. This
; rail has no edges, so nothing reaches here — it is the contract, kept honest.
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
