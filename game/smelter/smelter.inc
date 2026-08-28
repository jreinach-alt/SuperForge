; =============================================================================
; smelter.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout is B=bit 15 ...
; R=bit 4; `no_literals` refuses the hex forms and the gate is right — $1000
; lands inside a claim and nothing in the token distinguishes a hardware bit
; from an address.
JOY_B     = 1 << 15
JOY_START = 1 << 12

; The animation's rate, in PHASES per frame, in the 8.8 unit TS_STEP takes.
; $0060 is 0.375 phases/frame, so the 64-phase loop closes in ~171 NTSC frames
; — about 2.8 s. A plate on the slowest harmonic therefore takes 2.8 s to rise
; and fall once and the fastest takes ~0.95 s, which is the range a foundry
; hoist actually moves in. Faster reads as vibration; slower stops reading as
; motion at all.
;
; ITS DIMENSION IS A VELOCITY, which is why one TS_STEP is the whole of the
; region arm: phases/frame carries exactly one factor of the frame ratio r and
; TS_STEP applies exactly one. A rail whose motion ACCELERATED would need a
; second constant scaled by r^2 (game/jumper/state.toml spells that case).
; There is no such number here.
SMT_PHASE_BASE = $0060

; BG3 2bpp tile attr, TITLE SCENE ONLY: palette 7 (bg_text's claim pins CGRAM
; words 28..31), priority set. With BGMODE's BG3-priority bit also set, a BG3
; tile carrying it sits ABOVE BG1 and BG2 — a legible line of text over the
; plates.
;
; THERE IS NO SUCH CONSTANT FOR `works`, and its absence is the rail: in mode 2
; BG3 is not a layer, so it has no tiles, no palette and no priority. The words
; the PPU reads out of its map are scroll offsets.
SMT_TXT_ATTR = (7 << 10) | (1 << 13)

; THE SCROLL LATCH'S OFF-BY-ONE, which every screen-position number in this
; rail and in tests/test_smelter.py is expressed through.
;
; The vertical scroll latch reads "scanline N shows tilemap line VOFS + N",
; and the first ACTIVE scanline is 1 — so map pixel row P lands on picture row
; P - VOFS - 1. An offset-per-tile word REPLACES a column's VOFS (it does not
; add to it), so for a gated column the same relation holds with the word's
; value in place of the register: picture row = P - word - 1.
;
; That is where the picture's numbers come from. With the plate band's top at
; map pixel row SMT_PLAT_TOP_PX = 320 and the flat control's value 240, a
; plate's top edge sits at picture row 79; the crust at map row 256 with the
; melt's base 126 sits at 129.
SMT_ROW_BIAS = 1
