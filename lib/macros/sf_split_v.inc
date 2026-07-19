; =============================================================================
; sf_split_v.inc — vertical left/right window dual-view (macro library)
; =============================================================================
; Front door over the PPU window system for a VERTICAL (left/right) split: two
; BG layers, each scrolled to its own camera of the SAME 2D stage, clipped to
; opposite halves of the screen by window 1. No mid-scanline register writes and
; no HDMA — the split is set once and is effectively free; a straight MOVING
; seam is one window-edge write per frame.
;
; MECHANISM (Mode 1, BG1 + BG2 on the main screen):
;   - BG1 holds the stage scrolled to camera A -> shown on the LEFT half.
;   - BG2 holds the stage scrolled to camera B -> shown on the RIGHT half.
;   - Window 1 band = the RIGHT half [seam, 255]. W12SEL low nibble = BG1
;     win1-INSIDE (BG1 hidden inside the band -> left only); high nibble = BG2
;     win1-OUTSIDE (BG2 hidden outside the band -> right only) => W12SEL = $32.
;     TMW enables window masking for BG1 + BG2 on the main screen.
;   - Optional per-half OBJ clipping: window 1 also masks OBJ inside the band,
;     so a sprite crossing the seam has its across-seam portion clipped to the
;     left half (WOBJSEL = win1-INSIDE, TMW OBJ bit set).
;
; The CALLER owns the two cameras: scroll BG1 to camera A and BG2 to camera B of
; the same stage (the stage's CHR + tilemap duplicated into BG1's and BG2's
; VRAM regions). This macro only programs the window-clip recipe.
;
; Like the rest of the kit these macros write ENGINE SHADOW state; the NMI
; handler commits the shadows to the PPU window registers every VBlank. Requires
; (linked into the ROM): engine/engine_state.inc + the engine NMI handler.
;
; Operand convention (matches sf_window / sf_bg): a literal seam takes `#`
; (e.g. `sf_split_v #128, 0`); a bare symbol is a memory load (`sf_split_v
; my_seam, 1`). The obj_clip selector is a literal 0/1 (or omitted = 0).
; =============================================================================

.ifndef SF_SPLIT_V_INC
SF_SPLIT_V_INC = 1

.include "sf_window.inc"            ; the window-shadow front door this builds on

; -----------------------------------------------------------------------------
; sf_split_v seam, obj_clip — establish the vertical dual-view in ONE call.
; -----------------------------------------------------------------------------
;   seam      window-1 left edge X (0..255); the seam column. BG1 shows left of
;             it, BG2 shows right of it. `#N` literal or a memory symbol.
;   obj_clip  literal 0/1 (or omitted = 0). 1 also confines OBJ to the LEFT half
;             (a marker crossing the seam is clipped to its side).
; Static recipe — call once in setup. For a straight MOVING seam, call
; sf_split_v_seam once per frame (one window-edge write, no HDMA). Clobbers A.
; WIDTH-RISK: enters A16 (the sub-macros toggle A8 for their byte stores and
; restore A16); exits A16. No width state leaks past the call.
.macro sf_split_v sf_seam, sf_obj_clip
    sf_window1_edges sf_seam, #255
    sf_window_bg12 #(SF_WIN1_INSIDE | (SF_WIN1_OUTSIDE << 4))   ; $32
    .ifblank sf_obj_clip
        sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2)          ; $03
    .else
        .if sf_obj_clip
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_OBJ)  ; $13
            sf_window_obj #SF_WIN1_INSIDE      ; OBJ hidden inside [seam,255] -> left half
        .else
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2)      ; $03
        .endif
    .endif
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_seam seam — move the seam (window-1 left edge).
; -----------------------------------------------------------------------------
; One window-edge write; call per frame in the game loop for a straight moving
; seam (no HDMA). `#N` literal or a memory symbol. Clobbers A.
; WIDTH-RISK: enters A16, toggles A8 internally, exits A16.
.macro sf_split_v_seam sf_seam
    sf_window1_edges sf_seam, #255
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_off — collapse the split back to a single full-screen view.
; -----------------------------------------------------------------------------
; Clears every window shadow; the NMI then unmasks both BG layers, so the layer
; with priority (BG1 = camera A) fills the whole screen. Clobbers A.
; WIDTH-RISK: enters A16, toggles A8 internally, exits A16.
.macro sf_split_v_off
    sf_window_off
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_colorseam seam, half_width, obj_clip — split with a COLOURED SEAM.
; -----------------------------------------------------------------------------
; Like sf_split_v, but also draws a visible seam bar with ZERO sprites: window 2
; is a thin band [seam-half_width, seam+half_width] that masks BG1+BG2+BG3, so
; the BACKDROP (CGRAM 0) shows through as the seam colour. Window 1 still does
; the left/right split (BG1 left, BG2 right), combined with window 2 per layer
; via OR logic. The caller sets the seam colour with `sf_bg_color 0, 0, <bgr15>`
; and scrolls BG1/BG2 to the two cameras.
;   seam, half_width : BARE literals (setup-time constants; the band edges are
;                      computed at assemble time). obj_clip : literal 0/1 (or
;                      omitted) — 1 also confines OBJ to the left half.
; Static recipe — call once in setup. Move it per frame with sf_split_v_move.
; Clobbers A. WIDTH-RISK: enters A16; the sub-macros toggle A8 and restore A16.
.macro sf_split_v_colorseam sf_seam, sf_hw, sf_obj_clip
    sf_window1_edges #sf_seam, #255
    sf_window2_edges #(sf_seam - sf_hw), #(sf_seam + sf_hw)
    ; BG1 = win1-inside|win2-inside ($A); BG2 = win1-outside|win2-inside ($B).
    sf_window_bg12 #(SF_WIN1_INSIDE | SF_WIN2_INSIDE | ((SF_WIN1_OUTSIDE | SF_WIN2_INSIDE) << 4))
    sf_window_bg34 #SF_WIN2_INSIDE              ; BG3 masked inside the band too
    sf_window_logic #$00                        ; all-OR (combine win1 + win2)
    .ifblank sf_obj_clip
        sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3)          ; $07
    .else
        .if sf_obj_clip
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3 | SF_WIN_OBJ)  ; $17
            sf_window_obj #SF_WIN1_INSIDE       ; OBJ confined to the left half
        .else
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3)      ; $07
        .endif
    .endif
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_move seam, half_width — move the coloured seam (split + band).
; -----------------------------------------------------------------------------
; Recompute window-1 edge (WH0) and the window-2 band (WH2/WH3) from the current
; seam. `seam` is a MEMORY symbol (the live seam X, 0..255); half_width a bare
; literal. Call per frame in the game loop for a moving coloured seam (no HDMA).
; Clobbers A.
; WIDTH-RISK: enters A16, toggles A8 for the byte edge writes, exits A16.
.macro sf_split_v_move sf_seam, sf_hw
    sep #$20
    .a8
    lda sf_seam
    sta SHADOW_WH0                  ; window-1 left = seam
    lda #255
    sta SHADOW_WH1
    lda sf_seam
    sec
    sbc #sf_hw
    sta SHADOW_WH2                  ; band left  = seam - half_width
    lda sf_seam
    clc
    adc #sf_hw
    sta SHADOW_WH3                  ; band right = seam + half_width
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_diagonal base, slope, half_width, obj_clip — DIAGONAL coloured seam.
; -----------------------------------------------------------------------------
; Like sf_split_v_colorseam, but the split edge AND the backdrop band SLANT: the
; window edges (WH0/WH2/WH3) are driven per scanline by HDMA (3 channels). The
; seam X at scanline s is `base + (s * slope>>8)`.
;   base       seam X at the TOP scanline (bare literal 0..255).
;   slope      8.8 seam increment per scanline (bare literal; 0 = vertical,
;              $0080 = 0.5 px/line, $0100 = 1 px/line).
;   half_width band half-width in px (bare literal).
;   obj_clip   literal 0/1 (or omitted) — 1 confines OBJ to the left half.
; The caller sets the seam colour (`sf_bg_color 0, 0, <bgr15>`), scrolls BG1/BG2,
; AND must: `.include "hdma_alloc.asm"` + `.include "hdma_engine.asm"` and call
; `jsr hdma_alloc_init` once in setup (this needs the HDMA allocator). Static
; slant — the tables are built once. Clobbers A, X, Y.
; WIDTH-RISK: enters A16; the sub-macros toggle A8 and restore A16; the builder
; (hdma_build_split_diag) is A16/I16 entry+exit.
.macro sf_split_v_diagonal sf_base, sf_slope, sf_hw, sf_obj_clip
    sf_window1_edges #sf_base, #255
    sf_window2_edges #(sf_base - sf_hw), #(sf_base + sf_hw)
    sf_window_bg12 #(SF_WIN1_INSIDE | SF_WIN2_INSIDE | ((SF_WIN1_OUTSIDE | SF_WIN2_INSIDE) << 4))
    sf_window_bg34 #SF_WIN2_INSIDE
    sf_window_logic #$00
    .ifblank sf_obj_clip
        sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3)
    .else
        .if sf_obj_clip
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3 | SF_WIN_OBJ)
            sf_window_obj #SF_WIN1_INSIDE
        .else
            sf_window_mask_main #(SF_WIN_BG1 | SF_WIN_BG2 | SF_WIN_BG3)
        .endif
    .endif
    rep #$30
    .a16
    .i16
    lda #sf_base
    sta HDMA_SPLITD_BASE
    lda #sf_slope
    sta HDMA_SPLITD_SLOPE
    lda #sf_hw
    sta HDMA_SPLITD_HW
    jsr hdma_build_split_diag
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_cameras cam_a, cam_b — scroll BG1/BG2 to the two cameras.
; -----------------------------------------------------------------------------
; Convenience over `scroll #1, cam_a, #0` + `scroll #2, cam_b, #0` (the two
; cameras of the split). Operands follow the scroll convention (`#N` literal or
; a memory symbol). Requires sf_bg.inc (the `scroll` macro). Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 via `scroll`; returns A16.
.macro sf_split_v_cameras sf_cam_a, sf_cam_b
    scroll #1, sf_cam_a, #0
    scroll #2, sf_cam_b, #0
.endmacro

; =============================================================================
; SEAMLESS split (the divider is NEVER toggled) — sf_split_v_bevel + _spread
; =============================================================================
; The pair below is the SEAMLESS separation proven by templates/split_v_seamtrial
; and the composition core of templates/split_v_fight. Unlike the toggled
; colour-seam recipe above (window off <-> re-armed, a discrete pop, plus a
; masked band that steals 2*hw px of content the instant it turns on), this split
; is ALWAYS on at screen centre and separates by a CONTINUOUS camera divergence:
;
;   sf_split_v_bevel   : ONE-TIME setup. Always-on centre window + a VERTICAL
;                        BEVELED BG3 divider bar (highlight/mid/shadow) revealed
;                        only inside window 2's band.
;   sf_split_v_spread  : PER-FRAME. cam_a = mid - spread, cam_b = mid + spread,
;                        so at spread=0 the two halves are pixel-identical and the
;                        ever-present seam is INVISIBLE (no pop, no shift); the
;                        band half-width hw = spread>>4 is ZERO at merge (no stolen
;                        width) and grows only after the halves part.
;
; The caller eases `spread` from whatever drives the separation (fighter distance,
; a scripted sweep, ...). The divider is VERTICAL, not diagonal: an angled divider
; encodes verticality (airborne vs grounded) a ground-only game lacks — use
; sf_split_v_diagonal (above) for a game with flight.

; The seamless split centres the window at screen centre. The whole design hinges
; on this: at spread=0 both cameras coincide and the ever-present centre window is
; invisible, so the split is a CONTINUOUS divergence, never a toggle.
SF_SPLIT_V_CENTRE = 128            ; the split column (screen centre)

; -----------------------------------------------------------------------------
; sf_split_v_bevel — install the SEAMLESS beveled-bar divider (setup, once).
; -----------------------------------------------------------------------------
; Sets up EVERYTHING the always-on centre split needs so the caller only drives
; the per-frame spread (sf_split_v_spread):
;   (1) raises FORCED BLANK, THEN uploads the canonical 3-tile beveled bar to BG3
;       CHR word $7000 and points BG34NBA there (=$07). Forced blank must come
;       first: with the display on, the PPU owns the VRAM+CGRAM buses and silently
;       DROPS every write, so the CHR upload here and the palette in step (2) would
;       leave a blank bar over a black palette (the visible "divider" then being
;       only the backdrop through the masked band). One forced-blank window wraps
;       steps (1)-(3). LANDMINE: gfxmode leaves BG3 CHR at $A000, but VRAM word
;       addresses are 15-bit so $A000 WRAPS to $2000 (onto BG1 CHR) — keep BG3 CHR
;       in $0000..$7FFF.
;   (2) sets the bevel palette (CGRAM 9/10/11 = shadow / mid / highlight).
;   (3) writes the bar into the BG3 tilemap (word $6000) under that same forced
;       blank, then
;       clears BG3's dirty bit so the NMI never re-DMAs it — this sidesteps the
;       VBlank multi-tilemap DMA truncation (gfxmode marks all three maps dirty;
;       three 2 KB DMAs overrun VBlank and the last, BG3, is cut off mid-transfer
;       at a NON-deterministic row). The BG3 shadow is populated too (belt: if
;       anything re-marks BG3 dirty, the DMA writes the bar, not garbage). Uses
;       the ABSOLUTE BG_TILEMAP_DIRTY, not the ES_ OFFSET.
;   (4) pins BG3 scroll to 0 (a static layer still needs its scroll set — an
;       uninitialised scroll shadow slides the bar off its column).
;   (5) installs the ALWAYS-ON window recipe: window 1 splits at centre; window 2
;       reveals the BG3 bar only inside its band (BG3 win2-OUTSIDE) and masks
;       BG1/BG2 inside it. OBJ is NOT masked, so actors render across both halves
;       (essential — at merge an actor on either side must stay visible).
; Requires gfxmode #1 ALREADY called (this repoints BG34NBA after it) and the
; engine NMI handler linked. Emits the bar tile data into RODATA once (guarded),
; so it is drop-in — the caller authors no divider art. Clobbers A, X, Y.
; WIDTH-RISK: enters A16/I16; toggles A8 for VMAIN / palette / forced-blank /
; dirty-clear byte writes; exits A16/I16. Contains sep/rep (documented here).
.macro sf_split_v_bevel
    .local chr, b3fill, b3barL, b3barR, b3store
    ; --- (1) forced blank FIRST, then BG3 CHR: beveled bar -> word $7000. The
    ;     display is on when this macro runs (after gfxmode), so without the blank
    ;     the PPU drops the CHR + palette writes below (bug: blank bar, $0000 palette). ---
    sep #$20
    .a8
    lda #$8F
    sta $2100                       ; INIDISP: forced blank ON (brightness 15) — held
                                    ; across steps (1)-(3) so every VRAM/CGRAM write lands
    lda #$80
    sta $2115                       ; VMAIN: +1 word after high byte
    rep #$30
    .a16
    .i16
    lda #$7000
    sta $2116                       ; VMADD = BG3 CHR base word $7000
    ldx #$0000
chr:
    .a16
    .i16
    lda f:sf_split_v_bevel_tiles, x
    sta $2118
    inx
    inx
    cpx #(3*8*2)                     ; 3 tiles x 8 words
    bne chr
    sep #$20
    .a8
    lda #$07
    sta $210C                       ; BG34NBA: BG3 CHR word $7000 (held; NMI won't touch it)
    rep #$30
    .a16
    .i16
    ; --- (2) bevel palette (CGRAM 9/10/11) ---
    sf_bg_color 0, 9,  $18C6        ; shadow edge (dark)
    sf_bg_color 0, 10, $4E73        ; mid
    sf_bg_color 0, 11, $7FFF        ; highlight core (bright)
    ; --- (3) BG3 tilemap bar (still under the forced blank from step 1) +
    ;     shadow (belt) + dirty-clear ---
    sep #$20
    .a8
    lda #$80
    sta $2115                       ; VMAIN +1 word
    rep #$30
    .a16
    .i16
    lda #$6000
    sta $2116                       ; VMADD = BG3 tilemap word $6000
    ldx #$0000                      ; X = shadow BYTE offset = cell*2 (long,X only — no long,Y)
b3fill:
    .a16
    .i16
    txa
    lsr a                           ; cell = byte offset >> 1
    and #$001F                      ; col = cell & 31
    cmp #(SF_SPLIT_V_CENTRE/8 - 1)  ; bar LEFT half column (px 120..127)
    beq b3barL
    cmp #(SF_SPLIT_V_CENTRE/8)      ; bar RIGHT half column (px 128..135)
    beq b3barR
    lda #$0000                      ; blank (transparent) tile 0
    bra b3store
b3barL:
    .a16
    .i16
    lda #$0801                      ; barL: CHR tile 1 | palette 2<<10
    bra b3store
b3barR:
    .a16
    .i16
    lda #$0802                      ; barR: CHR tile 2 | palette 2<<10
b3store:
    .a16
    .i16
    sta $2118                       ; VRAM (auto-inc from $6000)
    sta f:$7E0000 + SHADOW_BG3_TILEMAP, x   ; BG3 shadow (belt-and-suspenders; long,X)
    inx
    inx
    cpx #2048                       ; 1024 cells x 2 bytes
    bne b3fill
    sep #$20
    .a8
    lda #$0F
    sta $2100                       ; forced blank OFF (brightness 15)
    lda BG_TILEMAP_DIRTY            ; keep ONLY BG1 dirty: drop BG2 (shared map) +
    and #$01                        ; BG3 (static) so the NMI never runs the 3-DMA
    sta BG_TILEMAP_DIRTY            ; truncation (uses the absolute addr, not ES_ offset)
    rep #$30
    .a16
    .i16
    ; --- (4) pin BG3 scroll (uninitialised scroll shadow mis-aligns the bar) ---
    scroll #3, #0, #0
    ; --- (5) always-on window recipe (centre split + in-band BG3 bar reveal) ---
    sf_window1_edges #SF_SPLIT_V_CENTRE, #255
    sf_window2_edges #(SF_SPLIT_V_CENTRE-1), #SF_SPLIT_V_CENTRE  ; setup band (rewritten per frame)
    sf_window_bg12 #$BA             ; BG1 win1-in|win2-in ; BG2 win1-out|win2-in
    sf_window_bg34 #$0C             ; BG3 win2-OUTSIDE (bar shown only inside the band)
    sf_window_logic #$00            ; all-OR
    sf_window_mask_main #$07        ; mask BG1+BG2+BG3 (NOT OBJ — actors render freely)
    ; --- canonical beveled-bar tile data (emit ONCE into RODATA, out of exec path) ---
    .ifndef SF_SPLIT_V_BEVEL_DATA
    SF_SPLIT_V_BEVEL_DATA = 1
    .pushseg
    .segment "RODATA"
sf_split_v_bevel_tiles:
    ; tile0 blank; tile1 = bar LEFT half (screen 120..127); tile2 = bar RIGHT half
    ; (screen 128..135). 2bpp, 8 words each (hi=plane1, lo=plane0). Bright core at
    ; x~128 fading to dark edges (an energy-beam bevel); all 8 rows identical.
    .repeat 8
        .word $0000
    .endrepeat
    .repeat 8
        .word $FFFE                 ; barL cols [3,3,3,3,3,3,3,2]
    .endrepeat
    .repeat 8
        .word $C03F                 ; barR cols [2,2,1,1,1,1,1,1]
    .endrepeat
    .popseg
    .endif
.endmacro

; -----------------------------------------------------------------------------
; sf_split_v_spread mid, spread, cam_a, cam_b — per-frame seamless divergence.
; -----------------------------------------------------------------------------
; The per-frame half of the seamless split. Given the shared viewpoint `mid` and
; the (already eased) integer `spread`, it:
;   - diverges the cameras: cam_a = mid - spread, cam_b = mid + spread (so at
;     spread=0 the two halves are pixel-identical -> the seam is invisible),
;   - ramps the divider band: hw = spread>>4, ZERO at merge (no width stolen),
;     growing as the halves part; writes WH2/WH3 = 128-+hw (at merge it writes an
;     EMPTY band, left>right, which disables window 2 so NO divider pixel shows),
;   - scrolls BG1 to cam_a and BG2 to cam_b.
; `mid`/`spread` are memory symbols; `cam_a`/`cam_b` are memory symbols that
; RECEIVE the two camera scrolls — read them to place per-half actors (an actor
; at world X shows at (X - cam_a)&$FF in the left half, (X - cam_b)&$FF in the
; right). Clobbers A, X, Y.
;
; INVARIANT — cam_a frames the LEFT half, cam_b the RIGHT. The actor placed
; against cam_a MUST be the one currently to the LEFT (smaller world X); place the
; rightmost against cam_b. This macro is symmetric in `mid`/`spread`, so it does
; the right thing through a SIDE-SWAP as long as the CALLER re-picks which actor
; goes with which camera BY POSITION each frame. If instead you bind an actor to a
; fixed camera and the two cross, the split does not break (still seamless,
; uncorrupted) but the framing INVERTS — each half frames the opposite side and
; the actors slide to the outer screen edges. split_v_fight does the position
; assignment every frame, so its fighters can cross and SWAP sides seamlessly.
; WIDTH-RISK: enters A16/I16; toggles A8 for the WH2/WH3 byte writes; exits A16.
.macro sf_split_v_spread sf_mid, sf_spread, sf_cam_a, sf_cam_b
    .local empty, done
    ; cam_a = mid - spread ; cam_b = mid + spread (mask to a byte scroll; the map
    ; is 256 px periodic, so mod-256 arithmetic is the correct screen mapping)
    lda sf_mid
    sec
    sbc sf_spread
    and #$00FF
    sta sf_cam_a
    lda sf_mid
    clc
    adc sf_spread
    and #$00FF
    sta sf_cam_b
    ; hw = spread >> 4
    lda sf_spread
    lsr a
    lsr a
    lsr a
    lsr a
    beq empty                       ; hw == 0 -> empty band (invisible at merge)
    ; band = [128-hw, 128+hw]; write WH3 then WH2, preserving hw across the A8 stores
    pha                             ; save hw
    clc
    adc #SF_SPLIT_V_CENTRE          ; A = 128 + hw = WH3 (right edge)
    sep #$20
    .a8
    sta SHADOW_WH3
    rep #$20
    .a16
    pla                             ; A = hw
    eor #$FFFF
    inc a                           ; A = -hw
    clc
    adc #SF_SPLIT_V_CENTRE          ; A = 128 - hw = WH2 (left edge)
    sep #$20
    .a8
    sta SHADOW_WH2
    rep #$20
    .a16
    bra done
empty:
    .a16
    .i16
    sep #$20
    .a8
    lda #1
    sta SHADOW_WH2                  ; empty band: left(1) > right(0) -> window 2 inactive
    lda #0
    sta SHADOW_WH3
    rep #$20
    .a16
done:
    .a16
    .i16
    scroll #1, sf_cam_a, #0
    scroll #2, sf_cam_b, #0
.endmacro

.endif ; SF_SPLIT_V_INC
