; =============================================================================
; title scene — the same foundry, flat, in MODE 1, with BG3 as a text layer
; =============================================================================
; The picture here is exactly the `works` scene's flat control: the same CHR,
; the same two tilemaps, the same palettes, with BG1VOFS and BG2VOFS set to
; the same two values the flat row carries. Nothing about the art knows which
; mode it is being drawn in.
;
; WHAT IS DIFFERENT IS BG3. Here it is a 2bpp text layer, above BG1 and BG2
; wherever a tile carries the priority attribute; in `works` it is not a layer
; at all and its map holds scroll offsets. This scene is therefore where the
; rail's hygiene obligation is discharged, and it is one step past `hz_flat`'s:
;
;   `blend_off`  — the composed blend state is per scene and nothing carries
;                  it across an edge, so a scene that blends nothing composes
;                  the OFF state rather than inheriting a tint.
;   `hz_flat`    — an HDMA-driven scroll port is in the same position: it
;                  holds whatever the last scanline left in it.
;   HERE         — a whole LAYER'S IDENTITY is in the same position. `works`
;                  leaves BG3SC pointing at a table of scroll words. A scene
;                  that drew text without re-pointing it would render those
;                  words AS GLYPHS: 64 bytes of vertical scroll positions,
;                  displayed as tile ids, in the font. The re-point below is
;                  the discharge, and it is `bg_text`'s port to write —
;                  BG3SC/BG34NBA/BG3HOFS/BG3VOFS are all in that feature's
;                  `scene_writes`.
;
; `bg_text` IS SCENE-SCOPED HERE, NOT GLOBAL. Its BG3 register claim meets the
; offset composition's synthesized ownership of the BG3 fetch path, so a
; global `bg_text` would put both in `works`'s union and stop the build by
; name (docs/100 O5). tests/test_smelter.py quotes that refusal verbatim.
.scope title
.include "engine_state_title.inc"   ; GENERATED — this scene's map
.include "bg_text.asm"              ; scene-scoped: BG3 is a layer HERE and
                                    ;   nowhere else in this rail

; --- smt_text_arm: the font, a cleared BG3 tilemap, the text palette -------
; CONTRACT title::smt_text_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the 96-glyph font in the text CHR page, the text tilemap filled
;             with spaces at this rail's attribute, and the four BG3 palette
;             words written
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; Every palette word is written explicitly — power-on CGRAM is random (rule 5)
; and this claim's four words are not covered by either art blob.
smt_text_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_text_arm"
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                     ; CGADD = 28 (BG3 palette 7)
    stz a:$2122                     ; 0: transparent slot, black
    stz a:$2122
    stz a:$2122                     ; 1: unused by this face, black
    stz a:$2122
    stz a:$2122                     ; 2: unused by this face, black
    stz a:$2122
    lda #$FF                        ; 3: white $7FFF — the glyph ink
    sta a:$2122
    lda #$7F
    sta a:$2122
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #SMT_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    rts

; --- smt_puts: one string at one tilemap cell ------------------------------
; CONTRACT title::smt_puts
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the string's address low 16 (it must live in the RODATA
;             block below, which is where the bank comes from), X = the VRAM
;             word address to write at
;   out:      the string written as tiles at this rail's text attribute
;   clobbers: A, Y, N, Z, C, V
;   assumes:  forced blank AND the NMI masked
;   tail:     rts
smt_puts:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_puts"
    sta z:ES_TXT_PTR
    lda #SMT_TXT_ATTR
    sta z:ES_TXT_TMP
    sep #$20
    .a8
    lda #^smt_strings
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    jsr text_puts
    rts

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    jsr smt_arm_bg                  ; the world: CHR, both maps, both palettes
    jsr smt_text_arm                ; BG3: the font and a cleared tilemap
    jsr smt_layer_bases             ; BG1SC, BG2SC, BG12NBA
    sep #$20
    .a8
    ; ---- the composed video mode ------------------------------------------
    ; $09: mode 1, plus the BG3-priority bit. NOT narrated — the byte is the
    ; allocator's, composed from `smt_flat`'s [[claims.video]] claim, so the
    ; declaration and the write cannot disagree about which mode this scene is.
    lda #ES_VID_TITLE_BGMODE
    sta a:$2105
    ; ---- BG3 BECOMES A LAYER AGAIN — the disarm ---------------------------
    ; Coming from `works`, BG3SC points at the offset table and BG3HOFS/VOFS
    ; index it. Without these four writes the text tilemap would never be
    ; looked at and 64 bytes of scroll words would render as glyphs.
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                     ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 chr = the font base
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; BG3HOFS, high
    stz a:$2112                     ; BG3VOFS, low
    stz a:$2112                     ; BG3VOFS, high
    ; ---- the flat picture, from `smt_flat`'s claim ------------------------
    ; The same two values the works scene's flat control row carries, so the
    ; title and the flattened works are the same picture — which is what makes
    ; "the plates are level" a statement about the table rather than about two
    ; unrelated scenes. Write-twice latches: low byte then high.
    lda #<SMT_PLAT_BASE
    sta a:$210E                     ; BG1VOFS, low
    lda #>SMT_PLAT_BASE
    sta a:$210E                     ; BG1VOFS, high
    lda #<SMT_MELT_BASE
    sta a:$2110                     ; BG2VOFS, low
    lda #>SMT_MELT_BASE
    sta a:$2110                     ; BG2VOFS, high
    stz a:$210D                     ; BG1HOFS, low
    stz a:$210D                     ; BG1HOFS, high
    stz a:$210F                     ; BG2HOFS, low
    stz a:$210F                     ; BG2HOFS, high
    rep #$20
    .a16
    ; ---- the strings this scene shows -------------------------------------
    ldx #(ES_V_TEXT_MAP + 2*32 + 12)
    lda #.loword(s_name)
    jsr smt_puts
    ldx #(ES_V_TEXT_MAP + 12*32 + 7)
    lda #.loword(s_what)
    jsr smt_puts
    ldx #(ES_V_TEXT_MAP + 14*32 + 9)
    lda #.loword(s_how)
    jsr smt_puts
    ldx #(ES_V_TEXT_MAP + 21*32 + 10)
    lda #.loword(s_press)
    jsr smt_puts
    ; ---- the composed screen/blend state ----------------------------------
    ; Four bytes, all four from the allocator. TM turns on the three layers
    ; this scene designates; TS is $00 because nothing here is sub-designated;
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
    SM_SWITCH "TITLE", "WORKS"      ; the declared edge picks the id AND the
    rep #$20                        ;   entry point; an undeclared one would
    .a16                            ;   stop the build naming the edge
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. The successor re-declares
; its whole look — its mode, its layer bases, BG3's meaning and both scroll
; ports.
exit:
    .a16
    .i16
    rts

.segment "RODATA"
smt_strings:
s_name:  .byte "SMELTER", 0
s_what:  .byte "PER COLUMN SCROLL", 0
s_how:   .byte "FROM A TILEMAP", 0
s_press: .byte "PRESS START", 0
.segment "CODE"
.endscope
