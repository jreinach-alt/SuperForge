; =============================================================================
; lakeside.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout is B=bit 15 ...
; R=bit 4; `no_literals` refuses the hex forms and the gate is right — $1000
; lands inside a claim and nothing in the token distinguishes a hardware bit
; from an address. The shift also says what these are: "bit 12 of a hardware
; word".
JOY_B     = 1 << 15
JOY_START = 1 << 12

; The drift, in pixels per frame. The one number to reach for when tuning how
; fast the surface slides.
;
; ITS DIMENSION IS A VELOCITY, which is why one TS_STEP is the whole of the
; region arm: px/frame carries exactly one factor of the frame ratio r, and
; TS_STEP applies exactly one. A rail whose surface ACCELERATED would need a
; second constant scaled by r^2, with the extra r folded into the base on the
; PAL arm (game/jumper/scenes/sky.asm is where that arithmetic is spelled).
; There is no such number here.
LK_WATER_SPEED = 1

; The map is 32x32 8 px cells, so the surface is 256 px wide and the scroll
; wraps every 256. Derived once here so a test and the ASM cannot disagree
; about it.
LK_WORLD_PX = 32 * 8

; BG3 2bpp tile attr: palette 7 (bg_text's claim pins CGRAM words 28..31),
; priority set. The priority bit is load-bearing rather than decorative: with
; BGMODE's BG3-priority bit also set, a BG3 tile carrying it sits ABOVE BG1
; and BG2, which is what puts a line of text over the water. That text is NOT
; in the blend's `math` list, so those pixels render at full intensity while
; the water blends around them — the per-layer colour-math enable doing
; exactly the job it exists for.
LK_TXT_ATTR = (7 << 10) | (1 << 13)

; The scroll latches are 10-bit and read "scanline N shows tilemap line
; VOFS + N", and the first ACTIVE scanline is 1 — so a VOFS of 0 puts world
; line 1 at the top of the picture. Minus one is the correction; $FFFF reads
; as 1023 and scanline 1 renders line (1023 + 1) mod 256 = 0. Every layer in
; this rail uses it, which is what makes world row r occupy picture rows
; 8r..8r+7 on BG1, BG2 and BG3 at once.
LK_VOFS = $FFFF
