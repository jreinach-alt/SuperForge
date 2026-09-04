; aurora.inc — the rail's tuning, beside the geometry the generator emits.
;
; What is HERE is what a person chose; what is in the GENERATED aur_art.inc is
; what the art IS. A constant the tools compute and a constant somebody tuned
; go stale for different reasons and should not sit in one file.

; THE HOLD BETWEEN HUE PHASES, in ticks. A phase costs five VBlanks to upload
; and then the picture stands still for this long, so the cycle closes in
; AUR_HUE_PHASES * (AUR_HUE_SLICES + AUR_HUE_HOLD) ticks -- 12 * 45 = 540, or
; about nine seconds.
;
; It is counted down by TS_STEP's output rather than by frames, so a PAL
; console spends the same wall-clock time on the cycle with the fraction
; carried between frames.
AUR_HUE_HOLD = 39

; ...and the rate that counts it down: one tick an NTSC frame.
AUR_TICK_BASE = $0100

; The pad bits this rail reads. A BIT POSITION in the joypad word the input
; feature publishes, not an address — every rail in this tree spells its own,
; because which button a rail uses is the rail's choice.
JOY_B     = 1 << 15
JOY_START = 1 << 12

; HOW MUCH OF THE WORD A REPLAY ERASES PER FRAME, in tiles. All 77 at once is
; 2,464 B in a VBlank that already carries a hue slice, which the allocator
; refuses by name; and erasing over five frames reads better than a blink,
; because the word un-writes rather than vanishing.
AUR_INK_SLICE = 16
