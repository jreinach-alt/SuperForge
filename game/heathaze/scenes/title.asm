; =============================================================================
; title scene — the desert, undistorted, with both off states composed
; =============================================================================
; The same world the desert scene shows, with the colour-math unit composed
; OFF and BG1HOFS composed FLAT. Neither is decoration.
;
; The blender's off state is `blend_off`, for the reason lakeside's title
; gives: a blend left armed by a predecessor tints a screen through registers
; it never wrote.
;
; THE SCROLL'S FLAT STATE IS THE ONE THIS RAIL ADDS, and it is the same
; problem on a different port. `haze` drives BG1HOFS per scanline, so when the
; desert scene ends the port holds whatever the LAST scanline of the last
; armed frame left in it — up to six pixels of arbitrary displacement. A
; successor that composed no BG1VOFS claimant would write nothing and inherit
; it, and the whole world would sit visibly off-centre. `hz_flat` is that
; port's `blend_off`: a claim whose entire content is the flat base, so
; entering here writes the register from a composed symbol rather than
; inheriting a warp.
.scope title
.include "engine_state_title.inc"   ; GENERATED — this scene's map

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    jsr hz_arm_bg                   ; the world: CHR, map, palette group 0
    jsr hz_text_arm                 ; BG3: the font and a cleared tilemap
    jsr hz_display                  ; BGMODE, the layer bases, the offsets
    ; ---- BG12NBA: the two CHR base nibbles, one write-only byte ------------
    ; BG2's nibble is 0: this rail's stage 1 has no BG2 layer, so no BG2 CHR
    ; base exists to name and none is read — TS composes $00 and TM's bg2 bit
    ; is clear. Stage 2's shimmer layer is the nibble that arrives here.
    sep #$20
    .a8
    lda #ES_V_HZ_CHR_NBA
    sta a:$210B
    ; ---- BG1VOFS: the flat base, from `hz_flat`'s claim --------------------
    ; Write-twice: low byte then high. THIS IS THE DISARM. Without it the
    ; picture arrives displaced by whatever the desert's last scanline held —
    ; and a VERTICAL displacement left behind is worse than a horizontal one,
    ; because it also leaves the world's rows off their tile boundaries.
    lda #<HZ_VOFS
    sta a:$210E                     ; BG1VOFS, low
    lda #>HZ_VOFS
    sta a:$210E                     ; BG1VOFS, high
    lda #0
    sta a:$210D                     ; BG1HOFS, low
    sta a:$210D                     ; BG1HOFS, high
    rep #$20
    .a16
    ; ---- the strings this scene shows -------------------------------------
    ldx #(ES_V_TEXT_MAP + 2*32 + 11)
    lda #.loword(s_name)
    jsr hz_puts
    ldx #(ES_V_TEXT_MAP + 12*32 + 4)
    lda #.loword(s_what)
    jsr hz_puts
    ldx #(ES_V_TEXT_MAP + 21*32 + 10)
    lda #.loword(s_press)
    jsr hz_puts
    ; ---- the composed screen/blend state ----------------------------------
    ; Four bytes, all four from the allocator. TM turns on the two layers
    ; `hz_bg` designates; TS is $00 because nothing here is sub-designated;
    ; CGWSEL/CGADSUB are `blend_off`'s composed off state.
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
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    sep #$20
    .a8
    SM_SWITCH "TITLE", "DESERT"     ; the declared edge picks the id AND the
    rep #$20                        ;   entry point; an undeclared one would
    .a16                            ;   stop the build naming the edge
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. The successor re-declares
; its whole look, including BG1HOFS and all four colour-math bytes.
exit:
    .a16
    .i16
    rts

.segment "RODATA"
s_name:  .byte "HEAT HAZE", 0
s_what:  .byte "PER SCANLINE DISPLACEMENT", 0
s_press: .byte "PRESS START", 0
.segment "CODE"
.endscope
