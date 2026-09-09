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

; =============================================================================
; THE WIND BED'S CADENCE, in SHIMMER PHASES (see scenes/desert.asm)
; =============================================================================
; A sound effect is a ONE-SHOT and the SFX ring hands the driver at most one
; request a frame, so an ambience is something the RAIL has to keep alive. The
; `wind` effect runs 212 SFX ticks — the driver's sound-effect clock is a fixed
; 125 Hz (vendor docs/sound-effects.md), so that is 1.696 s — and this is how
; often the scene asks for it again.
;
; 32 PHASES, WHICH IS EXACTLY HALF THE SHIMMER LOOP. The shimmer advances
; HZ_PHASE_BASE = 0.375 phases a frame through 64 phases, so 32 phases is
; 85.33 NTSC frames = 1.420 s: the bed is re-queued while the previous one is
; still sounding, and its restart lands twice per turn of the picture rather
; than drifting against it. THE OVERLAP IS THE POINT — a period LONGER than the
; effect leaves a hole every cycle and the ambience reads as a gust, which is
; the thing the owner asked for it not to be.
;
; NOT SHORTER, EITHER, and the reason is the ring rather than the ear. The
; queue holds four requests and retires ONE a frame; a cadence fast enough to
; keep it non-empty would push this rail's other cue — the B toggle — behind a
; gust that is inaudible anyway because the driver restarts the bed onto the
; channel already playing it. At 32 phases the ring is empty on 84 of every 85
; frames and a press is delivered on the frame it happens.
;
; COUNTED IN PHASES, NOT FRAMES, so the region arm is already paid: US_TSH is
; the region-corrected advance and accumulating it needs no second TS_STEP.
; The consequence is stated rather than hidden — on PAL the gust cadence is
; the same 1.42 SECONDS, not the same 85 frames.
HZ_WIND_PHASES = 32
