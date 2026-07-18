; =============================================================================
; sf_window.inc — PPU window-masking macros (macro library)
; =============================================================================
; Thin front-door over the SNES hardware windows. The two windows are vertical
; bands defined by left/right X coordinates (WH0-WH3); each layer (BG1-4, OBJ)
; can be masked inside or outside the "final" window area, on the main and/or
; sub screen. Used for spotlights, iris wipes, status-bar splits, and the
; Phase-18 windowing/spotlight effects.
;
; Like the rest of the kit, these macros write ENGINE SHADOW state; the NMI
; handler commits the shadows to the PPU window registers every VBlank:
;   - enable / logic / mask shadows are DP  (ES_SHADOW_W12SEL..TSW, $82-$88)
;   - window-EDGE shadows are WRAM-extended  (SHADOW_WH0..WH3, $7E:E10A..E10D)
; So set the window once in your setup (or move the edges per-frame in the game
; loop) and the NMI keeps the PPU in sync. The window registers are write-only
; on real hardware, which is exactly why the shadow is the source of truth.
;
; Requires (linked into the ROM): engine/engine_state.inc (the shadows) + the
; engine NMI handler (engine/nmi_handler.asm — it owns the VBlank flush). No
; engine function is called; every macro is pure shadow stores.
;
; HARDWARE BIT LAYOUTS (docs/reference/fullsnes.txt §window registers,
; cross-checked against the rendered output — see sf_window paper-cut) ---------
;   W12SEL ($2123) BG1+BG2   W34SEL ($2124) BG3+BG4   WOBJSEL ($2125) OBJ+MATH
;     per layer, a 4-bit field: low nibble = the low layer (BG1/BG3/OBJ),
;     high nibble = the high layer (BG2/BG4/MATH). Each nibble holds TWO 2-bit
;     window-area fields (NOT independent enable/invert bits):
;       bits 1-0 = window-1 area, bits 3-2 = window-2 area; per 2-bit field:
;         %00 / %01 = DISABLED, %10 (2) = enable + mask INSIDE the [L,R] band,
;         %11 (3) = enable + mask OUTSIDE the band.
;     So $02 = BG1 win1 inside; $03 = BG1 win1 outside; $33 = BG1+BG2 both
;     win1-outside (the engine's iris value — masks outside the circle).
;   WBGLOG ($212A): 2-bit logic per BG (0=OR 1=AND 2=XOR 3=XNOR), combining
;     window 1 and 2 into one "final" area. Only matters when BOTH windows are
;     enabled for that layer; with a single window, OR ($00) is the safe value.
;   TMW ($212E) / TSW ($212F): bit0=BG1 .. bit3=BG4, bit4=OBJ. A SET bit
;     DISABLES that layer inside the final window area (main / sub screen).
;     The backdrop is always shown, so masking a layer reveals the backdrop.
;   WH0/WH1 ($2126/$2127): window 1 left / right X (inclusive band [L,R]).
;   WH2/WH3 ($2128/$2129): window 2 left / right X.
;
; Operand convention (matches sf_bg / sf_sprite): literal values take `#`
; (e.g. `sf_window_mask_main #SF_WIN_BG1`); a bare symbol is a memory load.
; =============================================================================

.ifndef SF_WINDOW_INC
SF_WINDOW_INC = 1

.include "engine_api.inc"           ; pulls engine_state.inc (the shadow SSoT)

; --- Layer-mask bits for TMW / TSW (sf_window_mask_main / _sub) --------------
SF_WIN_BG1  = $01
SF_WIN_BG2  = $02
SF_WIN_BG3  = $04
SF_WIN_BG4  = $08
SF_WIN_OBJ  = $10

; --- Window-area selectors for the enable macros (per low-layer 2-bit field) -
; INSIDE  = mask applies inside  [left,right]; OUTSIDE = mask applies outside.
; These are the LOW-layer (BG1/BG3/OBJ) values; shift left by 4 for the high
; layer (BG2/BG4/MATH), e.g. (SF_WIN1_OUTSIDE | (SF_WIN1_OUTSIDE << 4)) = $33.
SF_WIN1_INSIDE   = $02     ; window-1 field = %10: enable, mask inside band
SF_WIN1_OUTSIDE  = $03     ; window-1 field = %11: enable, mask outside band
SF_WIN2_INSIDE   = $08     ; window-2 field = %10 << 2: enable, mask inside band
SF_WIN2_OUTSIDE  = $0C     ; window-2 field = %11 << 2: enable, mask outside

; --- Mask logic values for sf_window_logic (per-BG 2-bit field) --------------
SF_WINLOG_OR   = $00
SF_WINLOG_AND  = $01
SF_WINLOG_XOR  = $02
SF_WINLOG_XNOR = $03

; -----------------------------------------------------------------------------
; sf_window1_edges left, right — set window 1's left/right X (WH0/WH1).
; -----------------------------------------------------------------------------
; left/right are pixel X coordinates 0..255 (the band is inclusive [left,right]).
; Writes the WRAM-extended edge shadows; the NMI commits them to $2126/$2127.
; Call in setup, or every frame in the game loop to animate the clip edge.
; Clobbers A.
; WIDTH-RISK: toggles A8 for the byte stores; exits A16.
.macro sf_window1_edges sf_left, sf_right
    sep #$20
    .a8
    lda sf_left
    sta SHADOW_WH0                  ; WH0: window 1 left edge ($2126)
    lda sf_right
    sta SHADOW_WH1                  ; WH1: window 1 right edge ($2127)
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window2_edges left, right — set window 2's left/right X (WH2/WH3).
; -----------------------------------------------------------------------------
; As sf_window1_edges, for the second window (combined with window 1 via the
; per-layer logic in WBGLOG when both are enabled). Clobbers A.
; WIDTH-RISK: toggles A8 for the byte stores; exits A16.
.macro sf_window2_edges sf_left, sf_right
    sep #$20
    .a8
    lda sf_left
    sta SHADOW_WH2                  ; WH2: window 2 left edge ($2128)
    lda sf_right
    sta SHADOW_WH3                  ; WH3: window 2 right edge ($2129)
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_bg12 sel — set the BG1/BG2 window-enable byte (W12SEL, $2123).
; -----------------------------------------------------------------------------
; sel is the full byte: low nibble = BG1, high nibble = BG2; within each nibble
; OR the SF_WIN1_*/SF_WIN2_* selectors. e.g. `#SF_WIN1_INSIDE` enables window 1
; (mask inside the band) on BG1 only; `#(SF_WIN1_OUTSIDE | (SF_WIN1_OUTSIDE << 4))`
; ($33) does both BG1 and BG2, outside. Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_bg12 sf_sel
    sep #$20
    .a8
    lda sf_sel
    sta SHADOW_W12SEL              ; NMI commits to $2123
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_bg34 sel — set the BG3/BG4 window-enable byte (W34SEL, $2124).
; -----------------------------------------------------------------------------
; low nibble = BG3, high nibble = BG4 (see sf_window_bg12). Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_bg34 sf_sel
    sep #$20
    .a8
    lda sf_sel
    sta SHADOW_W34SEL             ; NMI commits to $2124
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_obj sel — set the OBJ/MATH window-enable byte (WOBJSEL, $2125).
; -----------------------------------------------------------------------------
; low nibble = OBJ, high nibble = the color-math window (see sf_window_bg12).
; Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_obj sf_sel
    sep #$20
    .a8
    lda sf_sel
    sta SHADOW_WOBJSEL           ; NMI commits to $2125
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_logic log — set the BG window-1/2 combine logic (WBGLOG, $212A).
; -----------------------------------------------------------------------------
; 2 bits per BG: bits1-0=BG1, 3-2=BG2, 5-4=BG3, 7-6=BG4; each is one of
; SF_WINLOG_OR/AND/XOR/XNOR. Only matters when BOTH windows are enabled for that
; BG; OR ($00) is the safe single-window value. Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_logic sf_log
    sep #$20
    .a8
    lda sf_log
    sta SHADOW_WBGLOG            ; NMI commits to $212A
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_mask_main mask — main-screen layer masking (TMW, $212E).
; -----------------------------------------------------------------------------
; OR the SF_WIN_* layer bits; a SET bit DISABLES that layer inside the final
; window area on the MAIN screen (revealing the backdrop). Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_mask_main sf_mask
    sep #$20
    .a8
    lda sf_mask
    sta SHADOW_TMW              ; NMI commits to $212E
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_mask_sub mask — sub-screen layer masking (TSW, $212F).
; -----------------------------------------------------------------------------
; As sf_window_mask_main, for the SUB screen (color-math source). Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_mask_sub sf_mask
    sep #$20
    .a8
    lda sf_mask
    sta SHADOW_TSW             ; NMI commits to $212F
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_window_off — disable all windowing (clears every window shadow).
; -----------------------------------------------------------------------------
; Zeros the enable/logic/mask shadows; the NMI then writes zeros to the PPU
; window regs, so no layer is masked. Edge shadows (WH0-3) are left as-is —
; they are harmless with the enables cleared. Clobbers A.
; WIDTH-RISK: toggles A8; exits A16.
.macro sf_window_off
    sep #$20
    .a8
    stz SHADOW_W12SEL
    stz SHADOW_W34SEL
    stz SHADOW_WOBJSEL
    stz SHADOW_WBGLOG
    stz SHADOW_TMW
    stz SHADOW_TSW
    rep #$20
    .a16
.endmacro

.endif ; SF_WINDOW_INC
