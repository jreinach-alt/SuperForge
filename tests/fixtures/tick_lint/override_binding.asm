; The assembly shape: a derivation block at column 0 HEADS the equate it
; derives, and heads exactly one of them.
; TICK: ok — a TS_STEP base, not a count of frames.
TURN_BASE      = TURN_STEP * TS_ONE     ; the TS_STEP base: 1 unit/frame
PATROL_BASE    = PATROL_SPEED * TS_ONE  ; ...and one world px/frame

MO_LIFE_FRAMES = 90                     ; the bolt's life, authored
;   a column-0 comment run heads the declaration BELOW it — it does not reach
; TICK: ok — a build-time conversion, not a clock.
MO_LIFE_PAL    = 75                     ; frames, after the conversion
