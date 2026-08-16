; =============================================================================
; scenes/sky.asm — the whole rail: enter, tick, and the order the tick runs in
; =============================================================================
; ONE scope holding this scene's map, its four scene-scoped features, and the
; tick. There is only one scene, so there is no second consumer for any of it.
;
; THE ORDER IN `tick` IS LOAD-BEARING, and it is one sentence: advance the
; state, THEN compose from it, THEN draw from it. The join reads the heading and
; the altitude index the state step just settled, and the sprites read the same
; altitude, so the floor's perspective and the shadow that reports it are one
; frame's answer rather than a mixture of two.

.scope sky

.include "engine_state_sky.inc"      ; GENERATED — this scene's map
.include "m7f_cam.asm"               ; the join: the altitude axis itself

; WHERE THE COLDATA RAMP LANDS, declared at the composition site because it is
; this scene's look and not the feature's (rgb_gradient.asm has no
; default, and says why).
;
;   BG1      the Mode 7 floor, so the fog fade lands on the terrain;
;   BACKDROP CGRAM word 0, which is what the TM split reveals above the
;            horizon — so the SAME ramp is the sky. Mode 7 has one background;
;            without the backdrop bit there is no layer up there to tint.
;
; OBJ IS DELIBERATELY ABSENT: the airship and its shadow draw over both bands
; and must keep their own colours, or the ship whitens into the haze at the
; exact moment the picture is meant to read as distance.
RG_MATH_LAYERS = (1 << 0) | (1 << 5)

.include "rgb_gradient.asm"          ; the sky ramp + fog: COMPOSED, not forked
.include "m7f_floor.asm"             ; the plane, the palette, the sky split
.include "m7f_obj.asm"               ; the airship and its altimeter shadow
.include "m7f_logic.asm"             ; turn, throttle, altitude, integrate

; --- the ROM claim sites the SCENE owns -------------------------------------
; Three blobs, and BOTH the bank and the order within it are the ALLOCATOR's
; answer rather than a layout choice: `place_rom` packs by (-bytes, name), so
; adding the day/night palette table re-sorted the whole set and moved two of
; these across a bank boundary. That is what the `.assert`s are for — a re-sort
; stops the build with the claim named instead of letting a blob be read as its
; neighbour's bytes, which on this rail would be a plausible-looking sunset
; belonging to no snapshot.
;
; They live in the scene rather than beside main.asm's global blobs because
; both owners — `rgb_gradient` and `m7f_floor` — are composed at SCENE scope,
; so their ADDR/BANK symbols are emitted into engine_state_sky.inc.
; race.asm is the same shape.
.segment "BANK2"
; The COLDATA sky ramp + horizon fog: THIS RAIL'S blob behind rgb_gradient's
; `grad_tabs` claim, indexed by distance from the horizon rather than by
; scanline, because this rail's horizon moves.
grad_tabs_bin:
    .incbin "m7f_grad.bin"
.assert ^grad_tabs_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(grad_tabs_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"
m7f_tod_bin:
    .incbin "m7f_tod.bin"
.assert ^m7f_tod_bin = ES_R_M7F_TOD_BANK, error, "m7f_tod bank drifted from allocator claim"
.assert .loword(m7f_tod_bin) = ES_R_M7F_TOD_ADDR, error, "m7f_tod addr drifted from allocator claim"

.segment "BANK3"
m7f_todpal_bin:
    .incbin "m7f_todpal.bin"
.assert ^m7f_todpal_bin = ES_R_M7F_TODPAL_BANK, error, "m7f_todpal bank drifted from allocator claim"
.assert .loword(m7f_todpal_bin) = ES_R_M7F_TODPAL_ADDR, error, "m7f_todpal addr drifted from allocator claim"
.segment "CODE"

; --- the scene's base display ----------------------------------------------
; BGMODE 7 is the affine plane and BG1 is the only layer it has. TM is a SEED
; here (m7f_floor's `m7f_tm_seed` claim): the value written under forced blank
; is the base the sky split's HDMA then drives per band from line 0 onward.
; Seeding it with BG1+OBJ rather than with the sky value means a frame in which
; the split somehow failed to arm would show the floor rather than a blank
; screen — a louder failure, which is the one to prefer.
TM_BG1 = 1 << 0
TM_OBJ = 1 << 4

; --- enter: the whole scene, under forced blank -----------------------------
; In/out: A16/I16, DB=0. scene_mgr's enter contract: forced blank on, NMITIMEN
; zeroed, HDMAEN cleared. Every claim this scene owns is written here before
; anything reads it (rule 5) — power-on WRAM is random and a zero fill "to be
; safe" would hide the day that stops being true.
enter:
    .a16
    .i16
    ; ---- the camera's own state, seeded BEFORE m7f_arm composes from it ----
    lda #.loword(M7F_SPAWN_X)
    sta z:M7F_POSX + 2
    stz z:M7F_POSX + 0                  ; the 16.16 fraction starts at zero
    lda #.loword(M7F_SPAWN_Y)
    sta z:M7F_POSY + 2
    stz z:M7F_POSY + 0
    lda #M7F_SPAWN_HEAD
    sta z:M7F_HEAD
    lda #M7F_ALT_SPAWN                  ; index 40 — the mid-altitude spawn
    sta z:M7F_ALTIDX
    stz z:M7F_SPEED                     ; hovering: the flight starts still

    ; ---- the propeller clock ----------------------------------------------
    lda #M7F_PROP_RATE
    sta z:US_PROP_T
    stz z:US_PROP_F

    ; ---- the pose tables FIRST, then the plane, the sky split and the cast -
    ; THE ORDER IS A CONTRACT, not a preference, and the uninit-read detector
    ; is what named it: under the moving horizon the sky split's first count
    ; byte IS the band's first scanline, so `sky_arm` reads M7F_HORIZON — which
    ; only `m7f_arm` derives. Armed the other way round the split is built from
    ; power-on garbage for one frame, which is a rule-5 read of a byte nothing
    ; has written and was flagged as exactly that.
    jsr m7f_arm                         ; composes BOTH buffers; derives the band
    ; rgb_gradient FIRST, then floor_arm — and the order is a CONTRACT, not a
    ; preference. `rg_arm` writes A1T/A1B for the three COLDATA channels with
    ; its own fixed-seam header tables; `floor_arm`'s `fog_arm` then re-points
    ; them at this rail's horizon-anchored cursor. Reversed, rg_arm wins, the
    ; sky still gradients, and the fog silently stops following the horizon.
    jsr rg_arm                          ; the COLDATA planes + the colour math
    jsr floor_arm                       ; ...whose horizon the sky split uses
    jsr obj_arm
    jsr cloud_arm

    ; ---- the display registers the SCENE owns -----------------------------
    sep #$20
    .a8
    lda #7
    sta a:$2105                         ; BGMODE 7
    lda #(TM_BG1 | TM_OBJ)
    sta a:$212C                         ; TM: the seed the sky split overrides
    rep #$20
    .a16

    ; ---- arm the three channels this scene drives -------------------------
    ; Two matrix channels plus the sky split. The bits are OR-ed into the
    ; scene_mgr HDMAEN shadow, which the NMI applies every armed frame — the
    ; features stage their own channel registers, the scene turns them on.
    sep #$20
    .a8
    ; SIX of eight now: the two matrix channels, the sky split, and
    ; rgb_gradient's three COLDATA planes. Two spare.
    lda z:ES_SM_NMI + 2
    ora #((1 << ES_H_M7FAB_CH) | (1 << ES_H_M7FCD_CH) | (1 << ES_H_M7F_SKY_CH))
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH))
    sta z:ES_SM_NMI + 2

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. `fade_start_in` is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate; call it from A16 and the CPU
    ; eats the following opcode byte as that immediate's high half, the ramp
    ; never arms, INIDISP stays at brightness 0, and the ROM renders BLACK with
    ; perfectly correct VRAM, CGRAM and band tables. It is rule 6's
    ; silent-corruption class arriving through a cross-file contract width-lint
    ; cannot see, and this rail met it too — the first build of this scene
    ; composed a byte-exact band table behind a black screen.
    ;
    ; A bare INIDISP write here would not do: scene_mgr commits INIDISP from its
    ; own NMI shadow, so it would be overwritten on the first VBlank.
    jsr ::fade_start_in
    rep #$20
    .a16

    jsr obj_draw                        ; frame 1 shows the ship, not a park
    jsr cloud_draw                      ; ...and the sky, not four parked slots
    rts

; --- tick: one frame ---------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE COMPOSE RUNS HERE, IN ACTIVE DISPLAY, and that is the design rather than
; an accident of where it fits: it is far larger than a VBlank window, it writes
; the BACK buffer only, and `m7f_nmi_commit` swaps it in atomically at the next
; VBlank. Nothing the player can do makes the two overlap.
tick:
    .a16
    .i16
    jsr m7f_tick_state          ; turn, throttle, altitude, integrate
    jsr m7f_compose_timed       ; the join: this frame's 160-line band table,
                                ;   bracketed by its own SLHV cost latch
    jsr obj_prop_tick
    jsr cloud_tick              ; wind + rotation parallax, from THIS frame's
    jsr obj_draw                ;   heading — and the cull from its horizon
    jsr cloud_draw
    rts

; --- exit: nothing to tear down ---------------------------------------------
; In/out: A16/I16, DB=0. There is no second scene to hand anything to, and
; scene_mgr's own exit path clears HDMAEN and masks NMI. The routine exists
; because the dispatch table needs three entries, and saying so here is
; cheaper than a reader wondering what was forgotten.
exit:
    .a16
    .i16
    rts

.endscope
