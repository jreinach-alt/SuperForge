; =============================================================================
; heathaze.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout is B=bit 15 ...
; R=bit 4; `no_literals` refuses the hex forms and the gate is right — $1000
; lands inside a claim and nothing in the token distinguishes a hardware bit
; from an address.
JOY_B     = 1 << 15
JOY_START = 1 << 12

; The shimmer's rate, in PHASES per frame, in the 8.8 unit TS_STEP takes.
; $0060 is 0.375 phases/frame — the 64-phase loop closes in ~171 NTSC frames,
; about 2.8 s, which is the cadence a heat shimmer actually has. Faster reads
; as vibration; slower stops reading as motion at all.
;
; ITS DIMENSION IS A VELOCITY, which is why one TS_STEP is the whole of the
; region arm: phases/frame carries exactly one factor of the frame ratio r and
; TS_STEP applies exactly one. A rail whose shimmer ACCELERATED would need a
; second constant scaled by r^2 (game/jumper/scenes/sky.asm spells that case).
; There is no such number here.
HZ_PHASE_BASE = $0060

; HOW FAR AHEAD THE TURBULENT TERM RUNS, in phases of the 64-phase loop.
;
; THIS NUMBER IS THE EFFECT. The two HDMA channels step the same phase counter;
; give them the same phase and the horizontal term rides the vertical one like
; a decal stuck to it, which reads as one flat layer wobbling. Give them
; different phases and the sideways wobble slides ACROSS a surface that is
; itself moving — refraction, where the thing doing the bending and the thing
; being bent do not travel together, which is what the eye actually reads as
; hot air.
;
; 29 rather than 32: half a loop would put the two exactly out of phase and
; the pair would beat symmetrically, which is its own kind of pattern. 29 is
; also coprime with 64, so the relative phase walks the WHOLE loop before
; repeating — an even lead would share a factor of two with 64 and close after
; half of it.
HZ_HORIZ_LEAD = 29

; BG3 2bpp tile attr: palette 7 (bg_text's claim pins CGRAM words 28..31),
; priority set. With BGMODE's BG3-priority bit also set, a BG3 tile carrying
; it sits ABOVE BG1, which is what keeps a line of text legible over a layer
; that is being displaced under it — the text does not shimmer, because BG3
; is not the layer the warp channel drives.
HZ_TXT_ATTR = (7 << 10) | (1 << 13)

; The scroll latches are 10-bit and read "scanline N shows tilemap line
; VOFS + N", and the first ACTIVE scanline is 1 — so a VOFS of 0 puts world
; line 1 at the top of the picture. Minus one is the correction; $FFFF reads
; as 1023 and scanline 1 renders line (1023 + 1) mod 256 = 0. Both layers in
; this rail use it, which is what makes world row r occupy picture rows
; 8r..8r+7 on BG1 and BG3 at once — and it is why HZ_BAND_TOP = 120 in
; hz_art.inc is the first scanline of map row 15 exactly.
HZ_VOFS = $FFFF
