; Deliberately violating: a per-frame routine and two frame-unit equates.
MXL_STEP_FRAMES = MXL_TILE_PX           ; one grid slide, at 1 px/frame
ROLL_PEAK_CAP   = 4 << ROLL_FIX         ; 4.0 px/frame — the hard cap
EDGE            = 2                     ; frame line, a border and not a clock
ROLL_FIX        = 8                     ; the 8.8 fraction width

rs_burst_step:
    rts

obj_place:                              ; called once per frame by the tick
    rts

ok_step:
    ; TICK: ok — advanced by a declared tick, not by the NMI
    rts
