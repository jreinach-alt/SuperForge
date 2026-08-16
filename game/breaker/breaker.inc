; =============================================================================
; breaker.inc — the rail's geometry and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because breaker_obj.asm,
; breaker_bg.asm and the play scene all read from it and ca65 resolves scopes
; backward. Pure equates: no code, no claims, nothing the allocator owns.
;
; Screen space is 256x224 and the arena does not scroll, so screen pixels and
; BG1 cell coordinates differ by exactly a >> 3 — which is what makes the
; ball's leading-edge probe a shift and a mask (breaker_bg.asm's brk_probe).

; --- $4218 bit POSITIONS. Written as shifts because a bare 4096 is also a
;     plausible VRAM word address and no_literals cannot know which you meant.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_START = 1 << 12
JOY_A     = 1 << 7

; --- the paddle --------------------------------------------------------------
BRK_PADDLE_Y     = 200           ; screen y of its top edge (cell row 25)
BRK_PADDLE_W     = 24            ; three 8 px segments
BRK_PADDLE_H     = 8
BRK_PADDLE_SPEED = 3             ; px per frame
BRK_PADDLE_MIN_X = 8             ; hard against the left wall (cell col 1)
BRK_PADDLE_MAX_X = 224           ; 248 - BRK_PADDLE_W: hard against the right
BRK_PADDLE_HOME  = 116           ; centred, where every round starts

; --- the ball ----------------------------------------------------------------
BRK_BALL_SIZE   = 8
BRK_BALL_WAIT_Y = 192            ; riding on the paddle's top edge
BRK_BALL_LOST_Y = 216            ; below this it is gone: the pit
; The two probe points sit at +1 and +6 of the 8 px ball, not on the 0/7
; corners, so a lone corner pixel can slide past a live cell without breaking
; it. That is a bounded 1 px clip, and it is invisible because the ball tile's
; corner pixels are transparent (tools/gen_breaker_assets.py's disc mask).
BRK_PROBE_NEAR  = 1
BRK_PROBE_FAR   = 6
; Max speed is 2 px/frame against 8 px cells, so the leading edge can never
; step over a whole cell — no tunnelling, which is what lets a per-axis
; move-then-probe be the whole collision model.
BRK_SPEED_1  = 1
BRK_SPEED_2  = 2
BRK_SPEED_N1 = $FFFF             ; -1, two's complement
BRK_SPEED_N2 = $FFFE             ; -2

BRK_START_BALLS = 3

; --- the state machine -------------------------------------------------------
BRK_STATE_WAIT = 0               ; ball rides the paddle, A launches
BRK_STATE_PLAY = 1
BRK_STATE_OVER = 2               ; >= OVER means "the round is finished", which
BRK_STATE_WIN  = 3               ; is why the two ends sort above the live ones

; --- HUD reprint requests (US_DIRTY bits) -----------------------------------
BRK_DIRTY_SCORE = 1
BRK_DIRTY_BALLS = 2

; --- BG3 text geometry -------------------------------------------------------
; The message block is TWO fixed 11-cell rows (a verdict line and a prompt
; line) written one cell per frame through bg_text's VBlank queue. Fixed width
; and fixed position means a new block totally overwrites the last one — there
; is no residue to clear and no length bookkeeping.
BRK_MSG_W    = 11
BRK_MSG_COL  = 10
BRK_MSG_ROW0 = 14
BRK_MSG_ROW1 = 16
BRK_MSG_LEN  = BRK_MSG_W * 2

BRK_HUD_ROW      = 1
BRK_HUD_SCORE_C  = 2             ; "SCORE" label
BRK_HUD_SCORED_C = 8             ; ...its 4 digits
BRK_HUD_BALLS_C  = 20            ; "BALLS" label
BRK_HUD_BALLSD_C = 26            ; ...its 1 digit
