; =============================================================================
; showcase_scene1.inc — Mode-1 BG content + procedural sprite field.
; =============================================================================
; The visible substrate the knobs act on: a BG1 colour field (so brightness /
; color-math / scroll are visible), a BG3 layer (so the BG3-priority split is
; visible), and a procedural OBJ swarm (the FIELD slot). Authored into the engine
; SHADOW tilemaps ($7E:A200 BG1, $7E:B200 BG3) which the NMI DMAs to VRAM.
;
; CHR layout (Mode-1 bases per @mode1_init): BG1 chr word $2000, BG3 chr word
; $A000, OBJ chr word $4000 (the HUD glyph upload; the field reuses the glyph
; tiles as little blocks for S1 — a real page swaps in dedicated field CHR).
; =============================================================================

; --- BG1 4bpp tiles: 0 transparent, 1 solid idx1, 2 solid idx2 ---------------
sc1_bg1_chr:
    .res 32, $00                      ; tile 0 transparent
    .byte $FF,$00,$FF,$00,$FF,$00,$FF,$00    ; tile 1 plane0 = all set (idx 1)
    .byte $FF,$00,$FF,$00,$FF,$00,$FF,$00
    .res 16, $00
    .byte $00,$FF,$00,$FF,$00,$FF,$00,$FF    ; tile 2 plane1 = all set (idx 2)
    .byte $00,$FF,$00,$FF,$00,$FF,$00,$FF
    .res 16, $00
sc1_bg1_chr_end:

; --- BG3 2bpp-style tile reused as 4bpp: a hatch in idx 1 ---------------------
sc1_bg3_chr:
    .res 32, $00                      ; tile 0 transparent
    .byte $AA,$00,$55,$00,$AA,$00,$55,$00    ; tile 1 hatch (idx 1)
    .byte $AA,$00,$55,$00,$AA,$00,$55,$00
    .res 16, $00
sc1_bg3_chr_end:

; -----------------------------------------------------------------------------
; show_build_bg — upload BG1/BG3 chr + palettes (forced blank). Tilemaps are
; authored AFTER gfxmode (which clears the shadow tilemaps), in show_demo_init's
; post-gfxmode step via show_paint_tilemaps.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 around the PPU byte writes; exits A16/I16.
.proc show_build_bg
    rep #$30
    .a16
    .i16
    ; --- BG palettes: BG pal 0 colours 1=green,2=red; BG3 pal (sub-pal) too ---
    sep #$20
    .a8
    stz $2121                         ; CGADD 0
    stz $2122
    stz $2122                         ; colour 0 = black
    lda #$E0
    sta $2122
    lda #$03
    sta $2122                         ; colour 1 = $03E0 green
    lda #$1F
    sta $2122
    lda #$00
    sta $2122                         ; colour 2 = $001F red
    rep #$20
    .a16

    ; --- BG1 chr -> VRAM word $2000 ---
    sep #$20
    .a8
    lda #$80
    sta $2115                         ; VMAIN: inc after high
    rep #$20
    .a16
    lda #$2000
    sta $2116
    ldx #$0000
@b1:
    sep #$20
    .a8
    lda f:sc1_bg1_chr, x
    sta $2118
    inx
    lda f:sc1_bg1_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(sc1_bg1_chr_end - sc1_bg1_chr)
    bcc @b1

    ; --- BG3 chr -> VRAM word $A000 ---
    lda #$A000
    sta $2116
    ldx #$0000
@b3:
    sep #$20
    .a8
    lda f:sc1_bg3_chr, x
    sta $2118
    inx
    lda f:sc1_bg3_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(sc1_bg3_chr_end - sc1_bg3_chr)
    bcc @b3
    rts
.endproc

; -----------------------------------------------------------------------------
; show_paint_tilemaps — fill the BG1 + BG3 SHADOW tilemaps, mark dirty. Called
; AFTER engine_gfxmode (which clears them). BG1 = a checker of tiles 1/2 (so
; mosaic/colour-math/scroll have texture); BG3 = a hatch band on the lower half
; so the BG3-priority split is legible. Flat word loop: X = 0..1023, row = X>>5,
; col = X & 31, byte offset = X*2.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; DB=$7E bracket for the shadow writes; exits A16/I16.
.proc show_paint_tilemaps
    rep #$30
    .a16
    .i16
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                               ; DB = $7E (shadow tilemaps live here)
    rep #$20
    .a16

    ; --- BG1: checker over rows 4..24, cols 2..29. X = flat tile index 0..1023;
    ;     byte offset into the tilemap = X*2 (computed in the store). ---
    ldx #0                            ; flat tile index 0..1023
@b1:
    jsr _sc1_tile_for_bg1             ; X = index -> A16 = tile word (X preserved)
    pha                               ; save tile word
    txa
    asl                               ; X*2 = byte offset
    tay                               ; Y = byte offset
    pla                               ; A = tile word
    sta SHADOW_BG1_TILEMAP, y         ; word store (tile low, attr high = 0)
    inx
    cpx #1024
    bcc @b1

    ; --- BG3: hatch (tile 1) on rows 16..27, all cols; else blank ---
    ldx #0
@b3:
    jsr _sc1_tile_for_bg3             ; X preserved -> A16 = tile word
    pha
    txa
    asl
    tay
    pla
    sta SHADOW_BG3_TILEMAP, y
    inx
    cpx #1024
    bcc @b3

    plb                               ; restore DB = $00

    ; Mark BG1 + BG3 dirty so the NMI DMAs them to VRAM.
    sep #$20
    .a8
    lda f:BG_TILEMAP_DIRTY            ; (DB now $00; use abs — but be explicit)
    ora #$05                          ; bit0 BG1 | bit2 BG3
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts
.endproc

; _sc1_tile_for_bg1 — X = flat tile index -> A16 = tile word for BG1. X preserved.
; row = X>>5, col = X&31, parity = (row^col)&1. Stack-only (no memory scratch).
; WIDTH-RISK: A16/I16 entry/exit.
.proc _sc1_tile_for_bg1
    rep #$30
    .a16
    .i16
    ; row check
    txa
    lsr
    lsr
    lsr
    lsr
    lsr                               ; A = row
    cmp #4
    bcc @off
    cmp #25
    bcs @off
    ; col check
    txa
    and #$1F                          ; A = col
    cmp #2
    bcc @off
    cmp #30
    bcs @off
    ; parity = (row ^ col) & 1
    txa
    and #$1F                          ; col
    pha                               ; [1,s] = col
    txa
    lsr
    lsr
    lsr
    lsr
    lsr                               ; row
    eor 1, s                          ; row ^ col
    ply                               ; balance the pha (Y clobbered, restored by loop)
    and #$01
    bne @two
    lda #$0001                        ; tile 1 (green)
    rts
@two:
    lda #$0002                        ; tile 2 (red)
    rts
@off:
    lda #$0000
    rts
.endproc

; _sc1_tile_for_bg3 — X = flat tile index -> A16 = tile word for BG3. X preserved.
; WIDTH-RISK: A16/I16 entry/exit.
.proc _sc1_tile_for_bg3
    rep #$30
    .a16
    .i16
    txa
    lsr
    lsr
    lsr
    lsr
    lsr                               ; row
    cmp #16
    bcc @off
    cmp #28
    bcs @off
    lda #$0001                        ; hatch tile 1
    rts
@off:
    lda #$0000
    rts
.endproc

; =============================================================================
; Sprite field — a procedural OBJ swarm (the FIELD slot). For S1 the positions
; are generated from the index + frame counter (no per-record physics), so the
; 192-byte SHOW_SPR_FIELD model stays reserved for a future page that needs
; per-sprite state. The field lands in OAM slots 48.. (allocations §2), within
; Y in [32,191] so it never shares a scanline with the HUD bands.
; =============================================================================

SC1_FIELD_OAM_BASE = SHOW_OAM_FIELD_BASE  ; first OAM slot for the field (§2, shared)
SC1_FIELD_TILE     = SF_OBJG_BAR      ; solid bar glyph reused as a field dot
SC1_FIELD_YMIN     = 40
SC1_FIELD_YSPAN    = 120              ; y in [40,160] — inside [32,191]

; -----------------------------------------------------------------------------
; show_field_init — clear the field model region (defensive; RAM was seeded 0).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte clear; exits A16/I16.
.proc show_field_init
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
; m1_field_tick — draw `count` field sprites at OAM 48.., procedural motion.
; Knobs: KN_FLD_CNT count, KN_FLD_SPD speed, KN_FLD_SPR spread, KN_FLD_PAL pal.
; Builds each OAM entry via SF_SPR_* (DP) + engine_spr directly (no spr macro,
; so x/y/flags need no addressable operands). Multiply-free running accumulators:
;   x-acc starts at frame_phase, += (spread+5) each sprite -> x = 16 + (acc mod 216)
;   y-acc starts at 0,           += 13          each sprite -> y = YMIN+(acc mod YSPAN)
;   frame_phase = FRAME_COUNTER >> (4 - min(speed,4)>>2)... kept simple: phase =
;   FRAME_COUNTER (drifts 1px/frame); speed widens the per-sprite stride so a
;   higher speed visibly spreads the swarm. All 8-bit, wrap-safe.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr runs A16/I16; X is the
; loop index across engine_spr (phx/plx); exits A16/I16.
.proc m1_field_tick
    rep #$30
    .a16
    .i16
    ; Field starts at OAM slot 48 (allocations §2) — set SPRITE_COUNT so the
    ; field does not overwrite the HUD slots 0-47 placed earlier this frame.
    lda #SC1_FIELD_OAM_BASE
    sta SPRITE_COUNT

    sep #$20
    .a8
    ; OBJ attr flags = palette<<1 (PPPn).
    lda f:SHOW_KNOB_VAL + KN_FLD_PAL
    and #$07
    asl
    sta f:SHOW_FLD_FLAGS
    ; x stride = (spread + 5); y stride is the constant 13.
    lda f:SHOW_KNOB_VAL + KN_FLD_SPR
    clc
    adc #5
    sta f:SHOW_FLD_TMP2              ; x stride
    ; x-acc seeded with the frame phase (drift); y-acc = 0.
    lda FRAME_COUNTER               ; frame low byte
    sta f:SHOW_FLD_TMP              ; x-acc
    lda #0
    sta f:SHOW_FLD_TMP3            ; y-acc
    rep #$20
    .a16

    ldx #0                            ; field sprite index
@loop:
    .a16
    .i16
    ; stop at min(count, 80)
    sep #$20
    .a8
    cpx #80
    bcs @doneb
    txa
    cmp f:SHOW_KNOB_VAL + KN_FLD_CNT
    bcs @doneb

    ; x = 16 + (x-acc mod 216)
    lda f:SHOW_FLD_TMP              ; x-acc (A8)
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
    lda f:SHOW_FLD_TMP3            ; y-acc
@mody:
    cmp #SC1_FIELD_YSPAN
    bcc @yok
    sec
    sbc #SC1_FIELD_YSPAN
    bra @mody
@yok:
    clc
    adc #SC1_FIELD_YMIN
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_Y

    ; place sprite
    lda #SC1_FIELD_TILE
    sta SF_SPR_TILE
    sep #$20
    .a8
    lda f:SHOW_FLD_FLAGS
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_FLAGS
    lda #2                          ; BG priority 2 (over the BG)
    sta SF_SPR_PRI
    phx
    jsr engine_spr
    plx

    ; advance the accumulators (A8): x-acc += stride ; y-acc += 13
    sep #$20
    .a8
    lda f:SHOW_FLD_TMP
    clc
    adc f:SHOW_FLD_TMP2            ; + x stride
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
    ; Record the realized OAM high-water mark (= total sprites this frame) so the
    ; limit meter's O signal reads ACTUAL OAM usage (not a knob proxy). The field
    ; runs LAST in the demo tick, so SPRITE_COUNT here is the frame total.
    sep #$20
    .a8
    lda SPRITE_COUNT
    sta f:SHOW_OAM_USED
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; Register Mode 1 with the dispatch layer (deliverable 6). ALL Mode-1 contract
; symbols are unique (m1_*); this is the page's ONLY edit to wire itself in. The
; fan-out replaces a stub's registration row in place with the real page's row.
; =============================================================================
show_register_mode 1, m1_demo_init, m1_apply, m1_field_tick, m1_arena_ind, m1_param_tbl, m1_slot_name, m1_parm_name, m1_cost_knob
