; microzero world geometry — assemble-time constants matching the generated
; assets (tools/gen_m7_assets.py) and the world_rom bank tiling. Values are
; sizes/coordinates, not addresses — addresses come from the allocator map.
WORLD_T_TILES       = 512   ; world is 512x512 tiles = 4096x4096 px
WORLD_ROWS_PER_BANK = 64    ; 64 rows x 512 B = one 32 KB ROM window
WORLD_COLS_BYTES    = 512

; race camera start: mid-road on the start/finish spoke (due east), i.e. on
; the octagon's east straight at the centre-line apothem. Derived from
; tools/gen_m7_assets.start_tile() — test_microzero_track.py asserts these
; agree with the generator, so the map and the spawn cannot drift apart.
CAM0_TX = 456               ; tile coords (256 + OCT_MID 200)
CAM0_TY = 256
CAM0_PX = 3652              ; pixel coords (tile*8 + 4)
CAM0_PY = 2052

HUD_LINES = 44              ; Mode-1 HUD band: lines 0..43; Mode 7 from 44
PIVOT_LINE = 168            ; camera focus scanline — the world row the
                            ; camera origin projects to. VOFS derives from this.
CAR_LINE   = 176            ; the car sprite's top scanline. INDEPENDENT of
                            ; PIVOT_LINE: the camera focuses at 168 while the
                            ; car draws at 176/192, so the car sits low in the
                            ; frame and the camera looks further ahead.
                            ; Deriving it from PIVOT_LINE instead floats the
                            ; car mid-screen over 70 scanlines of empty road.

; game rules: entering a race costs a life, finishing its laps scores
; laps x RACE_LAP_SCORE, and running out resets the run on title entry
LIVES_START    = 3
RACE_LAPS      = 3
RACE_LAP_SCORE = 100

; joypad bit masks ($4218 auto-read layout; shifts, not addresses)
JOY_B     = 1 << 15
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8
