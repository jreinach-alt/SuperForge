; aurora.inc — the rail's tuning, beside the geometry the generator emits.
;
; What is HERE is what a person chose; what is in the GENERATED aur_art.inc is
; what the art IS. A constant the tools compute and a constant somebody tuned
; go stale for different reasons and should not sit in one file.

;; THE CYCLE'S PACE. A TIME LAPSE, not an animation.
;
; A phase is AUR_HUE_SLICES transfers with AUR_HUE_STEP ticks BETWEEN them,
; then AUR_HUE_HOLD ticks of stillness. So a phase costs
; SLICES*STEP + HOLD = 6*10 + 150 = 210 ticks, and the cycle closes in
; PHASES * that = 16 * 210 = 3,360 -- about fifty-six seconds.
;
; THE GAP BETWEEN SLICES IS THE POINT, not an economy. Uploaded back to back
; the six slices land in six frames and the picture STEPS from one colour to
; the next; spread over a second they land as a dapple, because the slices are
; spatially scattered, and the curtain shifts the way a real one does rather
; than being repainted. It is the same six transfers either way.
;
; Both are counted down by TS_STEP's output rather than by frames, so a PAL
; console spends the same wall-clock time on the cycle with the fraction
; carried between frames.
AUR_HUE_HOLD = 150
AUR_HUE_STEP = 10

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
