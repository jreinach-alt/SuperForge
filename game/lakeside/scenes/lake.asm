; =============================================================================
; lake scene — the surface on the sub screen, half-added over the world
; =============================================================================
; The whole of the gameplay is one rate and one button: the surface drifts
; every frame, and B stills it. What the scene is FOR is the four bytes it
; writes at the bottom of `enter` — TM, TS, CGWSEL and CGADSUB, every one of
; them an allocator-composed value this scene owns because `water` and
; `lake_bg` declared their intent rather than claiming the ports.
;
; `water.asm` is included INSIDE this scope: its VRAM, palette and scroll
; claims are scene-scoped, so its symbols live in engine_state_lake.inc and
; only resolve here. sm_nmi_hook reaches its VBlank commit as
; `lake::wat_nmi_commit`, which is `breaker`'s shape for the same reason.
.scope lake
.include "engine_state_lake.inc"    ; GENERATED — this scene's map
.include "water.asm"                ; the surface (scene-scoped claims)

; =============================================================================
; THE TIMEBASE
; =============================================================================
; The drift's base rate, in the 8.8 unit TS_STEP takes. LK_WATER_SPEED is the
; one number to reach for when tuning how fast the surface slides; what this
; line adds is that it is a rate against the declared tick rather than a
; per-frame immediate. On NTSC the published step is LK_WATER_SPEED to the
; pixel (the scale is 1 and the carried fraction stays 0 forever, so the NTSC
; picture cannot move); on PAL it alternates in the pattern that averages
; LK_WATER_SPEED * 1.2018, so the surface slides the same distance per REAL
; second on both machines.
TS_DRIFT_BASE = LK_WATER_SPEED * TS_ONE

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    stz z:US_TSW_ACC                ; the timebase's carried fraction and this
    stz z:US_TSW                    ;   frame's step: written before read
    stz z:US_STILLED                ; the surface drifts on entry
    jsr lk_arm                      ; the world: CHR, map, palette group 0
    jsr wat_arm                     ; the surface: CHR, map, palette group 2
    jsr lk_text_arm                 ; BG3: the font and a cleared tilemap
    jsr lk_display                  ; BGMODE, the layer bases, the offsets
    ; ---- BG12NBA: the two CHR base nibbles, one write-only byte ------------
    ; The one register in this rail that carries two features' layout at once.
    ; BG1's nibble is `lake_bg`'s emitted base, BG2's is `water`'s, shifted
    ; into the high half — neither narrated, and the port has exactly one
    ; owner because it is write-only. This is the residue the screen/blend
    ; vocabulary deliberately does not reach: it composes the four blend
    ; ports and nothing else, and the composition names the split as a
    ; warning rather than pretending it away.
    sep #$20
    .a8
    lda #(ES_V_LK_CHR_NBA | (ES_V_WAT_CHR_NBA << 4))
    sta a:$210B
    rep #$20
    .a16
    ; ---- BG2SC: the surface's tilemap base --------------------------------
    ; `water`'s own claim under `scene_writes`, so it is written here and not
    ; in water.asm — the declaration-that-lies check refuses it in the file
    ; that granted the permission.
    sep #$20
    .a8
    lda #ES_V_WAT_MAP_SC_BASE
    sta a:$2108
    rep #$20
    .a16
    ; ---- the strings this scene shows -------------------------------------
    ; The second line sits on tilemap row 21, which is inside the surface's
    ; uniform band — so it is text drawn OVER water. BG3 is not in the
    ; blend's `math` list, so those pixels render at full intensity while the
    ; water blends around them.
    ldx #(ES_V_TEXT_MAP + 2*32 + 12)
    lda #.loword(s_name)
    jsr lk_puts
    ldx #(ES_V_TEXT_MAP + 21*32 + 7)
    lda #.loword(s_hint)
    jsr lk_puts
    ; ---- the composed screen/blend state ----------------------------------
    ; THE FOUR BYTES THIS RAIL EXISTS TO WRITE.
    ;   TM      bg1 + bg3 on the main screen  (`lake_bg`'s designations)
    ;   TS      bg2 on the sub screen         (`water`'s designation)
    ;   CGWSEL  addend source = the sub screen
    ;   CGADSUB add, halve, gating bg1 and the backdrop into the math
    ; Every one is an ES_SCR_LAKE_* symbol the allocator composed from the
    ; two features' claims and proved against the one-blender hardware. A
    ; narrated encoding here would be a second, uncheckable copy of the
    ; declaration — which is the same reason _SC_BASE and _NBA exist.
    sep #$20
    .a8
    lda #ES_SCR_LAKE_TM
    sta a:$212C
    lda #ES_SCR_LAKE_TS
    sta a:$212D
    lda #ES_SCR_LAKE_CGWSEL
    sta a:$2130
    lda #ES_SCR_LAKE_CGADSUB
    sta a:$2131
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) -----------------
; In/out: A16/I16, DB=0.
;
; B TOGGLES the drift rather than gating it while held, so stillness is a
; LATCHED state and not a per-frame condition. That is a real property of the
; rail and it is also what makes the still state measurable: a picture pair
; taken N frames apart while stilled must be pixel-identical, which a
; hold-to-still control could not promise, because whether the button is down
; at the instant of a capture is not the same question as whether the surface
; is still.
tick:
    .a16
    .i16
    ; This frame's drift, once. Computed even while the surface is stilled, so
    ; the carried fraction does not depend on the toggle: what the toggle
    ; gates is the APPLICATION of the step, not the timebase behind it.
    TS_STEP z:US_TSW_ACC, TS_DRIFT_BASE
    sta z:US_TSW
    lda z:ES_INP_PRESS
    and #JOY_B
    beq @no_toggle
    lda z:US_STILLED
    eor #1
    sta z:US_STILLED
@no_toggle:
    .a16
    .i16
    lda z:US_STILLED
    bne @still                      ; latched still: the surface holds
    lda z:US_TSW
    jsr wat_advance
@still:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    sep #$20
    .a8
    SM_SWITCH "LAKE", "TITLE"       ; the declared edge picks the id AND the
    rep #$20                        ;   entry point
    .a16
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked.
;
; The blender is NOT disarmed here, and that is the design rather than an
; omission: the composed state is per scene, and the successor establishes
; all four bytes from its OWN composed symbols on enter. `title` composes
; `blend_off` precisely so it can, which is why the allocator's per-edge
; hygiene check reports zero warnings for this rail.
exit:
    .a16
    .i16
    rts

.segment "RODATA"
s_name: .byte "LAKESIDE", 0
s_hint: .byte "B STILLS THE DRIFT", 0
.segment "CODE"
.endscope
