; aurora.inc — the rail's tuning, beside the geometry the generator emits.
;
; What is HERE is what a person chose; what is in the GENERATED aur_art.inc is
; what the art IS. A constant the tools compute and a constant somebody tuned
; go stale for different reasons and should not sit in one file.

; THE ROLL'S RATE, in 8.8 phases per NTSC frame. The wave closes on
; AUR_ROLL_PHASES, so this decides how long a fold takes to travel a curtain.
; $0044 = 0.266 phases a frame -> 32 phases in about two seconds.
;
; It is fed to TS_STEP, so a PAL console covers the same wave in the same
; wall-clock time with the fraction carried between frames.
AUR_PHASE_BASE = $0044

; The pad bits this rail reads. A BIT POSITION in the joypad word the input
; feature publishes, not an address — every rail in this tree spells its own,
; because which button a rail uses is the rail's choice.
JOY_B     = 1 << 15
JOY_START = 1 << 12
