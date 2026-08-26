; =============================================================================
; title scene — the shore with no water, and the blender carrying its off state
; =============================================================================
; The same world the lake scene shows, with BG2 designated to neither screen
; and the colour-math unit composed OFF. It is not decoration: it is the scene
; the blend is NOT running in, so returning here is what proves the lake's
; teardown. A blend left armed by `lake` would tint this screen through
; registers it never wrote — which is exactly the edge the allocator warns
; about, and exactly what `blend_off` removes.
;
; ITS OFF STATE IS COMPOSED, NOT NARRATED. ES_SCR_TITLE_CGWSEL / _CGADSUB are
; emitted only because this scene carries a blend claim, and the write below
; is the only reason those symbols exist.
.scope title
.include "engine_state_title.inc"   ; GENERATED — this scene's map

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    stz z:US_FRAMES
    jsr lk_arm                      ; the world: CHR, map, palette group 0
    jsr lk_text_arm                 ; BG3: the font and a cleared tilemap
    jsr lk_display                  ; BGMODE, the layer bases, the offsets
    ; ---- BG12NBA: the two CHR base nibbles, one write-only byte ------------
    ; BG2's nibble is 0 here — this scene has no water layer, so no BG2 CHR
    ; base exists to name and none is needed: TS composes $00 and TM's bg2 bit
    ; is clear, so the PPU never reads it. The `lake` scene writes the same
    ; port with its own surface's emitted nibble folded in, which is the one
    ; part of the display shape that genuinely differs between the two.
    sep #$20
    .a8
    lda #ES_V_LK_CHR_NBA
    sta a:$210B
    rep #$20
    .a16
    ; ---- the strings this scene shows -------------------------------------
    ldx #(ES_V_TEXT_MAP + 2*32 + 12)
    lda #.loword(s_name)
    jsr lk_puts
    ldx #(ES_V_TEXT_MAP + 12*32 + 6)
    lda #.loword(s_what)
    jsr lk_puts
    ldx #(ES_V_TEXT_MAP + 21*32 + 10)
    lda #.loword(s_press)
    jsr lk_puts
    ; ---- the composed screen/blend state ----------------------------------
    ; Four bytes, all four from the allocator. TM turns on the two layers
    ; `lake_bg` designates; TS is $00 because nothing in this scene is
    ; sub-designated; CGWSEL/CGADSUB are `blend_off`'s composed off state,
    ; which is what stops the lake's half-add persisting into this screen.
    sep #$20
    .a8
    lda #ES_SCR_TITLE_TM
    sta a:$212C
    lda #ES_SCR_TITLE_TS
    sta a:$212D
    lda #ES_SCR_TITLE_CGWSEL
    sta a:$2130
    lda #ES_SCR_TITLE_CGADSUB
    sta a:$2131
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) -----------------
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    inc z:US_FRAMES
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    sep #$20
    .a8
    SM_SWITCH "TITLE", "LAKE"       ; the declared edge picks the id AND the
    rep #$20                        ;   entry point; an undeclared one would
    .a16                            ;   stop the build naming the edge
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. The successor re-declares
; its whole look, including all four colour-math bytes, so there is nothing
; here to un-arm.
exit:
    .a16
    .i16
    rts

.segment "RODATA"
s_name:  .byte "LAKESIDE", 0
s_what:  .byte "SUB SCREEN HALF ADD", 0
s_press: .byte "PRESS START", 0
.segment "CODE"
.endscope
