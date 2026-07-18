; =============================================================================
; showcase_scene0.inc — Mode-0 PLANES BG content (4 layers) + sprite field.
; =============================================================================
; The visible substrate the Mode-0 knobs act on: FOUR 2bpp (4-color) BG layers,
; each with its OWN tile shape AND its OWN palette bank, so all four planes are
; legible and individually identifiable. Mode 0's engine_gfxmode wires:
;   BG1 tilemap word $0000, BG2 $0400, BG3 $0800, BG4 $0C00, shared chr $1000,
;   BG12NBA=BG34NBA=$11, TM=$1F (4 BG + OBJ). The NMI tilemap-DMA pipeline only
;   serves the Mode-1 VRAM layout ($5800/$5C00/$6000), so Mode 0 authors ALL FOUR
;   tilemaps + the shared CHR DIRECTLY to VRAM under forced blank in m0_demo_init
;   (the dirty/shadow path is NOT used for the BG content here).
;
; PLANE -> BG mapping is INDIRECT via BGxSC (the priority-shuffle ORD knob
; permutes which tilemap each BG reads — see m0_apply / m0_priority_apply). At
; rest (ORD=0) BG1 reads tilemap word $0000 (plane A), BG2 $0400 (B), BG3 $0800
; (C), BG4 $0C00 (D); BG1 is front-most by Mode-0 hardware priority.
;
; CHR layout: four 2bpp tiles at word $1000, each plane its own glyph:
;   tile 0 transparent, tile 1 plane A (solid), tile 2 plane B (vbars),
;   tile 3 plane C (hbars), tile 4 plane D (diamonds). Each BG's tilemap fills
;   its quadrant/field with its plane tile, palettized through its own bank.
; =============================================================================

; --- 2bpp shared CHR (word $1000): 5 tiles x 16 bytes (8x8, 2 planes). Each
;     plane's signature shape in colour index 1 (and 3 for plane D accents). ---
sc0_chr:
    ; tile 0 — transparent (index 0 everywhere)
    .res 16, $00
    ; tile 1 — plane A: SPARSE checker (idx 1 on a coarse checker) so the planes
    ;   BEHIND it show through in the stacked-parallax preset (a SOLID front plane
    ;   would hide all the others). ~25% coverage.
    .byte $88,$00,$22,$00,$88,$00,$22,$00   ; plane0 = sparse dots
    .byte $00,$00,$00,$00,$00,$00,$00,$00   ; plane1 = clear -> idx 1
    ; tile 2 — plane B: VERTICAL bars (idx 1 on alt columns)
    .byte $CC,$CC,$CC,$CC,$CC,$CC,$CC,$CC   ; plane0 = %11001100
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    ; tile 3 — plane C: HORIZONTAL bars (idx 1 on alt rows)
    .byte $FF,$00,$FF,$00,$FF,$00,$FF,$00   ; plane0 = alt rows set
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    ; tile 4 — plane D: DIAMOND / cross weave (idx 1 outline + idx 3 centre)
    .byte $18,$3C,$7E,$FF,$FF,$7E,$3C,$18   ; plane0 = diamond
    .byte $00,$18,$3C,$7E,$7E,$3C,$18,$00   ; plane1 = inner -> idx 3 core
sc0_chr_end:

; -----------------------------------------------------------------------------
; m0_build_bg — upload the shared CHR (word $1000) + four BG palette banks, all
; under forced blank. Palette banks: BG1 uses CGRAM pal 0, BG2 pal 8, BG3 pal 16,
; BG4 pal 24 (Mode-0 per-BG palette ranges). Each bank's colour 1 (and 3 for the
; diamond core) is a distinct hue so the planes read apart. The PAL knob later
; repaints colour 1 of each bank live.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 around the PPU byte writes; exits A16/I16.
.proc m0_build_bg
    rep #$30
    .a16
    .i16
    ; --- four palette banks, each 4 colours at CGRAM (pal*16) ---
    jsr m0_paint_palettes

    ; --- shared CHR -> VRAM word $1000 ---
    sep #$20
    .a8
    lda #$80
    sta $2115                         ; VMAIN: inc after high byte
    rep #$20
    .a16
    lda #$1000
    sta $2116
    ldx #$0000
@chr:
    sep #$20
    .a8
    lda f:sc0_chr, x
    sta $2118
    inx
    lda f:sc0_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(sc0_chr_end - sc0_chr)
    bcc @chr
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_paint_palettes — write the four BG palette banks' colour-1 (+ diamond core)
; from the live PAL knobs (so a PAL change repaints without a CHR re-upload). Bank
; b lives at CGRAM (b*64) -> pal index 0,8,16,24 = CGRAM 0,128,256,384 ... but
; CGRAM is 256 entries; BG pal P = CGRAM P*16. BG1 pal0=CGRAM0, BG2 pal8=CGRAM128,
; BG3 pal16=CGRAM256? — CGRAM is 256 entries (0..255). Mode-0 maps BG1 pal0-7,
; BG2 pal8-15, BG3 pal16-23, BG4 pal24-31; pal P base = P*16 capped at the 256
; CGRAM entries (pal 0,8 in range; pal 16=CGRAM256 wraps — so BG3/BG4 use the
; first colour of their range that is in-range). We keep ALL four banks inside
; CGRAM 0..255 by using pal 0 / 1 / 2 / 3 (CGRAM 0/16/32/48) for the four BGs'
; colour-1 source AND remap each BG to its low pal bank: the tilemap attr bytes
; carry the palette bank (see m0_paint_tilemaps). This keeps every colour write
; in-range and every plane a distinct hue.
; PAL knob values (4..7-ish hue selectors) pick from a small hue LUT.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for CGADD/CGDATA byte writes; exits A16/I16.
.proc m0_paint_palettes
    rep #$30
    .a16
    .i16
    ; Bank 0 (BG1 sub-palette 0): colour 0 black, colour 1 = hue[P1]
    ldx #0                            ; X = layer 0..3
@bank:
    ; Mode-0 per-BG palette regions: BG1 @ CGRAM 0, BG2 @ 32, BG3 @ 64, BG4 @ 96
    ; (each BG has its OWN 32-entry region; sub-palette 0 = the region base). So
    ; CGADD = layer*32. (Mode 0's 4-BG-each-own-palette quirk; see mode0_test.asm.)
    sep #$20
    .a8
    txa
    asl
    asl
    asl
    asl
    asl                               ; layer*32
    sta $2121                         ; CGADD
    ; colour 0 = black (both bytes 0)
    stz $2122
    stz $2122
    rep #$20
    .a16
    ; colour 1 = hue LUT[ PAL_knob[layer] ]  (15-bit BGR). m0_layer_hue PRESERVES
    ; X (= layer) across the call, so X stays the layer for the colour-2 derive
    ; below — no caller-side phx/plx juggling (that was the stale-X bug: the 2nd
    ; phx used to push the LUT offset the callee left in X, so colour 2 read the
    ; wrong layer's hue).
    jsr m0_layer_hue                  ; X=layer in/out -> A16 = BGR15 colour
    sep #$20
    .a8
    sta $2122                         ; colour-1 low byte
    xba
    sta $2122                         ; colour-1 high byte
    rep #$20
    .a16
    ; colour 2 = a dim variant (half-bright) of the SAME layer's hue so vbar/hbar
    ; shapes are legible (X is still this layer).
    jsr m0_layer_hue
    lsr
    and #$3DEF                         ; >>1 per 5-bit channel (rough dim)
    sep #$20
    .a8
    sta $2122
    xba
    sta $2122
    rep #$20
    .a16
    ; colour 3 = white-ish accent (diamond core for plane D, harmless for others)
    sep #$20
    .a8
    lda #$FF
    sta $2122
    lda #$7F
    sta $2122
    rep #$20
    .a16
    inx
    cpx #4
    bcc @bank
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_layer_hue — X = layer 0..3 -> A16 = a 15-bit BGR colour from a hue LUT
; selected by that layer's PAL knob. The LUT gives 8 distinct, legible hues; the
; PAL knob (0..7) indexes it. X is PRESERVED across the call (input layer is
; restored before rts) — internally X is reused as a knob/LUT index, so it is
; saved on entry and restored on exit. Used by m0_paint_palettes.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte reads; exits A16 (value in A), X
; restored to the input layer (phx/plx balanced, both I16).
.proc m0_layer_hue
    rep #$30
    .a16
    .i16
    phx                               ; save input layer (X is reused below)
    ; knob index for this layer's PAL = M0K_PAL_L1 + layer
    sep #$20
    .a8
    txa
    clc
    adc #M0K_PAL_L1                     ; M0K_PAL_L1 + layer
    rep #$20
    .a16
    and #$00FF
    tax                               ; X = knob index
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL, x             ; hue selector 0..7
    and #$07
    asl                               ; *2 (.word LUT)
    rep #$20
    .a16
    and #$00FF
    tax                               ; X = LUT byte offset
    lda f:m0_hue_lut, x               ; A16 = BGR15 colour (A preserved past plx)
    plx                               ; restore input layer (X = layer on exit)
    rts
.endproc

; --- hue LUT: 8 distinct 15-bit BGR colours (vivid, well-separated). ----------
m0_hue_lut:
    .word $001F     ; 0 red
    .word $03E0     ; 1 green
    .word $7C00     ; 2 blue
    .word $03FF     ; 3 yellow
    .word $7FE0     ; 4 cyan
    .word $7C1F     ; 5 magenta
    .word $029F     ; 6 orange
    .word $7FFF     ; 7 white

; -----------------------------------------------------------------------------
; m0_paint_tilemaps — fill all FOUR BG tilemaps (VRAM word $0000/$0400/$0800/
; $0C00) directly under forced blank. Each tilemap is filled with ITS plane tile
; (BG1->tile1 A, BG2->tile2 B, BG3->tile3 C, BG4->tile4 D), attr byte = the
; layer's palette bank (pal 0/1/2/3 in attr bits 2-4) so each plane reads in its
; own hue. A 32x32 (1024 entry) fill per layer = 1024 words each.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for VMAIN; exits A16/I16.
.proc m0_paint_tilemaps
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                         ; VMAIN inc after high
    rep #$20
    .a16

    ; Each BG uses sub-palette 0 of ITS OWN Mode-0 palette region (BG1 CGRAM 0,
    ; BG2 32, BG3 64, BG4 96). So the tilemap attr palette bits are 0 for every
    ; BG — the per-BG hue comes from the region, not the attr. (Mode-0 quirk.)
    ; BG1 (tm $0000) plane A tile 1
    lda #$0000
    sta $2116
    lda #$0001                        ; tile 1, sub-palette 0
    jsr m0_fill_tilemap

    ; BG2 (tm $0400) plane B tile 2
    lda #$0400
    sta $2116
    lda #$0002
    jsr m0_fill_tilemap

    ; BG3 (tm $0800) plane C tile 3
    lda #$0800
    sta $2116
    lda #$0003
    jsr m0_fill_tilemap

    ; BG4 (tm $0C00) plane D tile 4
    lda #$0C00
    sta $2116
    lda #$0004
    jsr m0_fill_tilemap
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_fill_tilemap — A16 = the tilemap word (tile + attr); write it 1024 times to
; the current VMADD (caller set $2116). VMAIN is inc-after-high so each pair of
; $2118/$2119 advances one word. X clobbered.
; LEGIBILITY (F-6): the top M0_HUD_DARK_ROWS tile rows of EVERY BG are written as
; transparent tile 0 instead of the plane tile, so the (dark) backdrop shows
; behind the white OBJ-pal-7 HUD readout (slot label y=6, tags y=18, values
; y=28). With all 4 planes blank up there the strip reads dark regardless of the
; priority shuffle. 32 tiles/row * M0_HUD_DARK_ROWS = the blanked prefix
; (M0_HUD_DARK_TILES, defined in showcase_mode0.inc which is .included first).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the VRAM byte pair; exits A16/I16.
.proc m0_fill_tilemap
    rep #$30
    .a16
    .i16
    sta f:SHOW_FLD_TMP                ; stash the word (long scratch)
    ldx #0
@w:
    ; top M0_HUD_DARK_TILES tiles -> transparent tile 0 (dark HUD backing strip)
    cpx #M0_HUD_DARK_TILES
    bcs @plane                        ; past the dark strip -> the plane tile
    sep #$20
    .a8
    stz $2118                         ; tile 0 low byte
    stz $2119                         ; attr 0 (sub-palette 0, no flip)
    rep #$20
    .a16
    bra @next
@plane:
    sep #$20
    .a8
    lda f:SHOW_FLD_TMP               ; tile low byte
    sta $2118
    lda f:SHOW_FLD_TMP+1            ; attr high byte
    sta $2119
    rep #$20
    .a16
@next:
    inx
    cpx #1024
    bcc @w
    rts
.endproc

; =============================================================================
; Sprite field — a procedural OBJ swarm (the FIELD slot), reused from the harness
; field pattern (OAM base 48+, records SHOW_OAM_USED). Mode-0 reuses the same
; multiply-free running-accumulator motion as the Mode-1 reference.
; =============================================================================
SC0_FIELD_OAM_BASE = SHOW_OAM_FIELD_BASE
SC0_FIELD_TILE     = SF_OBJG_BAR      ; solid bar glyph reused as a field dot
SC0_FIELD_YMIN     = 40
SC0_FIELD_YSPAN    = 120              ; y in [40,160] — inside the field band

; -----------------------------------------------------------------------------
; m0_field_init — clear the field model region (defensive; RAM was seeded 0).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte clear; exits A16/I16.
.proc m0_field_init
    rep #$30
    .a16
    .i16
    ldx #0
@z:
    sep #$20
    .a8
    lda #0
    sta f:SHOW_SPR_FIELD, x
    rep #$20
    .a16
    inx
    cpx #192
    bcc @z
    rts
.endproc

; -----------------------------------------------------------------------------
; m0_field_tick — draw `count` field sprites at OAM 48.., procedural motion.
; Knobs: M0K_FLD_CNT count, M0K_FLD_SPD speed, M0K_FLD_SPR spread, M0K_FLD_PAL pal.
; Same accumulator scheme as the Mode-1 reference (wrap-safe 8-bit math); records
; SHOW_OAM_USED (the meter O signal). The field runs LAST in the demo tick.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr runs A16/I16; X is the
; loop index across engine_spr (phx/plx); exits A16/I16.
.proc m0_field_tick
    rep #$30
    .a16
    .i16
    lda #SC0_FIELD_OAM_BASE
    sta SPRITE_COUNT

    sep #$20
    .a8
    ; OBJ attr flags = palette<<1 (PPPn)
    lda f:SHOW_KNOB_VAL + M0K_FLD_PAL
    and #$07
    asl
    sta f:SHOW_FLD_FLAGS
    ; x stride = (spread + 5); y stride = 13 const + speed contribution
    lda f:SHOW_KNOB_VAL + M0K_FLD_SPR
    clc
    adc #5
    sta f:SHOW_FLD_TMP2              ; x stride
    ; x-acc seeded with frame phase scaled by speed (drift)
    lda FRAME_COUNTER
    sta f:SHOW_FLD_TMP              ; x-acc
    lda #0
    sta f:SHOW_FLD_TMP3            ; y-acc
    rep #$20
    .a16

    ldx #0
@loop:
    .a16
    .i16
    sep #$20
    .a8
    cpx #80
    bcs @doneb
    txa
    cmp f:SHOW_KNOB_VAL + M0K_FLD_CNT
    bcs @doneb

    ; x = 16 + (x-acc mod 216)
    lda f:SHOW_FLD_TMP
@modx:
    cmp #216
    bcc @xok
    sec
    sbc #216
    bra @modx
@xok:
    clc
    adc #16
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_X

    ; y = YMIN + (y-acc mod YSPAN)
    sep #$20
    .a8
    lda f:SHOW_FLD_TMP3
@mody:
    cmp #SC0_FIELD_YSPAN
    bcc @yok
    sec
    sbc #SC0_FIELD_YSPAN
    bra @mody
@yok:
    clc
    adc #SC0_FIELD_YMIN
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_Y

    lda #SC0_FIELD_TILE
    sta SF_SPR_TILE
    sep #$20
    .a8
    lda f:SHOW_FLD_FLAGS
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_FLAGS
    lda #2
    sta SF_SPR_PRI
    phx
    jsr engine_spr
    plx

    ; advance accumulators (A8): x-acc += stride ; y-acc += 13
    sep #$20
    .a8
    lda f:SHOW_FLD_TMP
    clc
    adc f:SHOW_FLD_TMP2
    sta f:SHOW_FLD_TMP
    lda f:SHOW_FLD_TMP3
    clc
    adc #13
    sta f:SHOW_FLD_TMP3
    rep #$20
    .a16

    inx
    jmp @loop
@doneb:
    .a8
    .i16
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda SPRITE_COUNT
    sta f:SHOW_OAM_USED
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; Register Mode 0 (PLANES) with the dispatch layer. ALL Mode-0 contract symbols
; are unique (m0_*); this is the page's ONLY wiring of itself in (alongside the
; one .include in main.asm + the one stub-row removal). The stub's
; `show_register_stub 0` row is removed in showcase_stub.inc for the same slot.
; =============================================================================
show_register_mode 0, m0_demo_init, m0_apply, m0_field_tick, m0_arena_ind, m0_param_tbl, m0_slot_name, m0_parm_name, m0_cost_knob
