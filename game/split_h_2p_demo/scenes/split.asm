; =============================================================================
; scenes/split.asm — the two cameras, seeded and set running
; =============================================================================
; Enter uploads the plane, seeds two world positions, builds SIX HDMA tables and
; arms six channels (a per-band indirect matrix pair plus a per-band direct
; origin pair), seeds the swarm and the OAM shadow. After that the FLOOR drives
; itself off the PPU — the VBlank hook is two cheap calls, `oam_nmi_dma` and
; `cam_tick`, and nothing else, because a long hook pushes sm_nmi_core's
; post-hook channel-shadow MVN into active display.
;
; The per-frame TICK is where the cast lives: `cam_advance`, `swm_ai`,
; `swm_players`, `obj_project`, `swm_beat`, all during active display. That
; work is MEASURED, not counted — `make sh2-measure` runs the entity-count
; sweep and the loop-period sweep that say where the cadence cliff is.
;
; WHERE THE TWO BANDS COME FROM. Both are Mode 7, both stream the same 112-line
; perspective pose, both look at the same 128x128 plane. The ONLY thing that
; differs is the four bytes of origin the HDMA lands at line 112, and the fact
; that camera 2 sits 256 world pixels east of camera 1 — one full stripe of the
; checker's warm/cool period, so band 2 renders the WARM (red) stripe and band 1
; the COOL (no red) one. That colour separation is the rail's own position
; oracle and every framebuffer assertion in tests/test_split_h_2p_demo.py reads
; it.

.scope split

; --- the camera starts ------------------------------------------------------
; DERIVED, not narrated. The world is SH2_WORLD_PX across (sh2_cam asserts that
; against the map blob's own size), and the checker's warm/cool stripe period is
; SH2_STRIPE_T tiles — the generator's own STRIPE constant. Camera 1 sits at the
; world's middle, which the generator's PHASE term puts at the centre of a COOL
; stripe; camera 2 sits exactly one stripe east, which is the centre of a WARM
; one. Writing the algebra rather than 512 and 768 is what makes the two follow
; the map if it is ever re-themed — and `no_literals` refuses those numbers
; anyway, because both land inside emitted WRAM claims.
SH2_STRIPE_T  = 32                                  ; the generator's STRIPE
SH2_STRIPE_PX = SH2_STRIPE_T * SH2_TILE_PX          ; 256 px per colour stripe
SH2_P1_X0     = SH2_WORLD_PX / 2                    ; 512: on the cool stripe
SH2_P1_Y0     = SH2_WORLD_PX / 2
SH2_P2_X0     = SH2_P1_X0 + SH2_STRIPE_PX           ; 768: on the warm stripe
SH2_P2_Y0     = SH2_P1_Y0

; The scene's TM: the Mode 7 plane and the OBJ layer the cast draws on. Each bit
; is named by the feature that composites its layer — sh2_floor owns the plane,
; sh2_obj owns the sprites — so this line is the composition and nothing else.
SH2_TM = SH2_TM_BG1 | SHO_TM_OBJ

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 5 colours + M7SEL

    ; ---- the two cameras, seeded before anything reads them ---------------
    ; Power-on WRAM is random and sh2_cam declares no `[init] zero` for its dp
    ; claim: these four stores ARE the write-before-read contract for all eight
    ; bytes (rule 5), not defensive initialisation. cam_arm stamps the origin
    ; tables straight out of them on the next line, so a missing one would show
    ; as a band looking at garbage rather than as a subtle drift.
    lda #SH2_P1_X0
    sta z:SH2_POS1X
    lda #SH2_P1_Y0
    sta z:SH2_POS1Y
.ifndef SH2_SAME_ORIGIN
    lda #SH2_P2_X0
    sta z:SH2_POS2X
    lda #SH2_P2_Y0
    sta z:SH2_POS2Y
.else
    ; THE NON-VACUITY CONTROL. Camera 2 is
    ; folded onto camera 1, so band 2 leaves the WARM stripe and the red
    ; position signal must DIE. Without this, "band 2 carries red" is a claim
    ; about a checker pattern rather than about two cameras: a rail with ONE
    ; camera and a hardcoded warm floor would pass it just as well.
    ;
    ; Note the cameras still pan at DIFFERENT rates here — only the START
    ; positions are folded — so band 2 slides down the cool stripe rather than
    ; tracking band 1. That is deliberate: it kills the red without also
    ; killing the independent-motion signal, so the two tests fail
    ; independently rather than as a pair.
    lda #SH2_P1_X0
    sta z:SH2_POS2X
    lda #SH2_P1_Y0
    sta z:SH2_POS2Y
.endif

    ; ---- the two headings and the four fraction accumulators --------------
    ; Same write-before-read contract as the positions, over sh2_cam's second
    ; DP claim: cam_arm derives four pose pointers and four DASB banks straight
    ; out of H1/H2 on the next line, and cam_drive adds into the fractions from
    ; the first frame. Power-on DP is random, so a missing store here is a
    ; camera streaming a heading nobody chose, or a first-frame position jump
    ; of up to 255/256 of a pixel.
    ;
    ; Camera 2 boots HALF A TURN away (SH2_H2_0), so the two floors face
    ; opposite ways from frame 1 and the equal-and-opposite rotation reads as
    ; two cameras immediately rather than after the headings have drifted.
    lda #SH2_H1_0
    sta z:SH2_H1
.ifndef SH2_SAME_HEADING
    lda #SH2_H2_0
.else
    lda #SH2_H1_0                   ; the control: one heading, both bands
.endif
    sta z:SH2_H2
    stz z:SH2_F1X
    stz z:SH2_F1Y
    stz z:SH2_F2X
    stz z:SH2_F2Y

    ; ---- the origin SEED, under forced blank ------------------------------
    ; These four registers are sh2_cam's `seed = true` reg claim: the value
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
    lda #<SH2_P1_X0
    sta a:$211F
    lda #>SH2_P1_X0
    sta a:$211F                     ; M7X
    lda #<SH2_P1_Y0
    sta a:$2120
    lda #>SH2_P1_Y0
    sta a:$2120                     ; M7Y
    lda #<(SH2_P1_X0 - SH2_HALF_W)
    sta a:$210D
    lda #>(SH2_P1_X0 - SH2_HALF_W)
    sta a:$210D                     ; M7HOFS
    lda #<(SH2_P1_Y0 - SH2_SEAM)
    sta a:$210E
    lda #>(SH2_P1_Y0 - SH2_SEAM)
    sta a:$210E                     ; M7VOFS
    rep #$20
    .a16

    jsr cam_arm                     ; six tables + six channel shadows

    ; ---- the cast, AFTER the cameras are seeded ---------------------------
    ; obj_arm uploads the character block, OBSEL and both OBJ palettes, then
    ; takes the FIRST projection — which reads the positions and headings seeded
    ; above, so the ordering is a data dependency and not a style. Frame 1 then
    ; shows a consistent snapshot rather than a parked shadow.
    ; ---- the swarm, BEFORE the cast that draws it -------------------------
    ; swm_arm copies all 64 entity seed records from ROM over the whole WRAM
    ; claim and sets the live count to 24. It runs before obj_arm because
    ; obj_arm closes with the first projection, and that projection reads this
    ; table — an ordering that is a data dependency, not a style.
    jsr swm_arm
    jsr swm_players                 ; entities 0/1 take the seeded cameras
    jsr obj_arm

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on sh2_floor's behalf
    ; (see that feature.toml's attribution note). M7SEL is the feature's own and
    ; floor_arm has already written it.
    ;
    ; WRITTEN ONCE, FOR ALL 224 LINES. This rail does not split the video mode:
    ; both bands are Mode 7 the whole frame and the split is entirely in the
    ; camera origin. That is why `split_band` is neither composed nor
    ; generalised here — there is no second splitter.
    sep #$20
    .a8
    lda #$07                        ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #SH2_TM
    sta a:$212C                     ; TM: the plane and the cast

    ; ---- arm the four channels -------------------------------------------
    ; The scene_mgr NMI applies this shadow to HDMAEN on every armed frame; the
    ; channel REGISTERS were staged by cam_arm into the 128-byte shadow the same
    ; NMI MVNs to $4300. Enabling a channel whose shadow was never staged is
    ; the shape that reads as "the picture is garbage" — hence both halves in
    ; one enter, in this order.
    lda #((1 << ES_H_SH2AB1_CH) | (1 << ES_H_SH2CD1_CH))
    ora #((1 << ES_H_SH2AB2_CH) | (1 << ES_H_SH2CD2_CH))
    ora #((1 << ES_H_SH2XY_CH) | (1 << ES_H_SH2HV_CH))
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate; call it from A16 and
    ; the CPU eats the following opcode byte as that immediate's high half, the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders black
    ; with perfectly correct VRAM and CGRAM — a failure the build never
    ; mentions. It is rule 6's silent-corruption class arriving through a
    ; CROSS-FILE contract width-lint cannot see in either direction.
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
; THE WHOLE OF THE RAIL'S MAIN-THREAD COST, in four calls and in this order:
;
;   cam_advance   the two pads (or, under -D SH2_AUTOCAM, the autonomous step)
;                 move the two cameras. FIRST, because everything below is
;                 about the state it produces.
;   swm_ai        22 waypoint followers steer and step, in world space only.
;   swm_players   entities 0 and 1 take the two cameras' new positions, so a
;                 player's marker is drawn in the OTHER band this frame.
;   obj_project   both bands' casts into the OAM shadow.
;
; ADVANCE THEN PROJECT: the next VBlank stamps the pose pointers, the DASB
; banks and the origin tables out of the state cam_advance just wrote, and
; commits the OAM shadow obj_project just built from that same state — so the
; sprites and the floor are always the same frame's. The advance sits here
; rather than inside `cam_tick`: the phase is identical either way, and this
; keeps the work out of the VBlank window.
;
; IN THE TICK RATHER THAN THE NMI HOOK, and the reason is measured: 24 entities
; projected from VBlank push sm_nmi_core's post-hook channel-shadow MVN into
; active display, which rewrites the running HDMA state mid-frame and speckles
; the floor from that row down. Active display is where a WRAM-only job of this
; size belongs — and the AI runs there too, which is more work again in the
; same place.
tick:
    .a16
    .i16
    jsr cam_advance
    jsr swm_ai
    jsr swm_players
    jsr obj_project
    jsr swm_beat                    ; LAST: the cadence gate's loop counter
    rts

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's contract), and re-uploading 32 KB to prove a
; point costs a frame. What IS undone is the display state this scene turned on,
; so a successor inherits a blank main screen rather than a Mode 7 plane it
; never asked for. HDMAEN is scene_mgr's own to clear at the transition. This
; rail has no edges, so nothing reaches here yet — it is the contract, kept
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
