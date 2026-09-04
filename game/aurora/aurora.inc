; aurora.inc — the rail's tuning, beside the geometry the generator emits.
;
; What is HERE is what a person chose; what is in the GENERATED aur_art.inc is
; what the art IS. A constant the tools compute and a constant somebody tuned
; go stale for different reasons and should not sit in one file.

; THE CYCLE'S PACE is not here any more — it is the generated rate curve
; (AUR_RATE_LEN frames a phase, summing to exactly one phase's worth of
; tiles), because the pace and the shape are the same decision and splitting
; them across two files would let them disagree. AUR_HUE_PHASES * AUR_RATE_LEN
; = 3,072 frames, about fifty-one seconds.

; The rate the curve is read at: one entry an NTSC frame. Fed to TS_STEP, so a
; PAL console reads it faster and covers the same cycle in the same wall-clock
; time, with the fraction carried between frames.
AUR_TICK_BASE = $0100

; HOW MUCH OF THE WORD A REPLAY ERASES PER FRAME, in tiles. All 77 at once is
; 2,464 B in a VBlank that already carries the hue cycle's transfer, which the
; allocator refuses by name; and erasing over five frames reads better than a
; blink, because the word un-writes rather than vanishing.
AUR_INK_SLICE = 16

; The pad bits this rail reads. A BIT POSITION in the joypad word the input
; feature publishes, not an address — every rail in this tree spells its own,
; because which button a rail uses is the rail's choice.
JOY_B     = 1 << 15
JOY_START = 1 << 12
