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

; THE BEATS. Their ORDER is the jump table's order in aur_pres.asm, so these
; are indices and not flags. What each one waits on is in that file's header;
; only one of them is a matter of taste, and it is the one below.
AUR_P_UP    = 0        ; fading up on a bare sky, everything held
AUR_P_PLAY  = 1        ; the pen writes and the aurora rises
AUR_P_HOLD  = 2        ; the finished card stands, still cycling
AUR_P_DOWN  = 3        ; fading to black, still cycling
AUR_P_RESET = 4        ; at black: the ink and the aurora draining back out

; HOW LONG THE FINISHED CARD STANDS, in ticks (one an NTSC frame). The rest of
; the loop is not tuned at all — a ramp, the pen, a ramp and a drain, each of
; which ends when the thing it is waiting on has finished. This is the one
; number somebody chose, and it is the beat where the COLOUR is the only thing
; happening: the word is written, nothing moves, and the curtains drift. It is
; long because that drift is the rail.
;
; It is also what puts the loop's period on the recorder's capture grid. The
; other four beats cost 106 frames between them, so 284 makes the period 390
; = 130 captures exactly at EVERY=3 — which is a convenience, not a
; requirement: the loop closes at black and one black frame is the same as
; another, so a period off the grid would still cut cleanly.
AUR_PRES_HOLD = 284

; The pad bits this rail reads. A BIT POSITION in the joypad word the input
; feature publishes, not an address — every rail in this tree spells its own,
; because which button a rail uses is the rail's choice.
JOY_B     = 1 << 15
JOY_START = 1 << 12
