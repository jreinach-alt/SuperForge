; racer world geometry — assemble-time constants matching the generated assets
; (tools/gen_racer_assets.py paints this rail's world; gen_m7_assets.py owns
; the tile vocabulary and the floor art). Values are sizes/coordinates, not
; addresses; addresses come from the allocator map.
;
; THE WORLD IS THIS RAIL'S OWN CIRCUIT: a closed 16-corner octilinear loop on
; a 4096 px torus — twelve lefts, four rights, kerbs, a start/finish chequer
; — painted in gen_m7_assets' tile vocabulary. Sharing the vocabulary is what
; keeps the composition cheap: the floor CHR/palette blobs and the DERIVED
; col_flags table (the map is this rail's collision ground truth) serve the
; circuit unchanged, so the rail's own bytes are one 256 KB map behind
; world_rom's claim and nothing else. Geometry, corner list and the torus
; wrap limit live in the generator's COURSE block — one source of truth.
WORLD_T_TILES       = 512   ; world is 512x512 tiles = 4096x4096 px
WORLD_PX_MASK       = 4095  ; the torus wrap (rc_logic's RCL_WORLD_MASK)
WORLD_ROWS_PER_BANK = 64    ; 64 rows x 512 B = one 32 KB ROM window
WORLD_COLS_BYTES    = 512

; Start: mid-road on the start/finish chequer, on the circuit's east straight,
; heading north — tools/gen_racer_assets START_TX/START_TY (the generator
; asserts the tile under this camera is the chequer).
CAM0_TX = 456               ; tile coords (gen_racer_assets.START_TX)
CAM0_TY = 256
CAM0_PX = 3652              ; pixel coords (tile*8 + 4)
CAM0_PY = 2052

HUD_LINES = 44              ; the seam: sky band lines 0..43, Mode 7 from 44.
                            ; NOT a free parameter — mode7_persp's index
                            ; tables skip exactly this many lines and the
                            ; pose blobs carry 224-HUD_LINES rows, so the
                            ; horizon is pinned by pose_rom's geometry.
PIVOT_LINE = 168            ; camera focus scanline — the world row the origin
                            ; projects to. VOFS derives from it.
KART_LINE  = 176            ; the kart's top scanline: low in the frame while
                            ; the camera looks further ahead (player_car's
                            ; CAR_LINE argument, same numbers)
BAR_LINE   = 16             ; the speed bar, ABOVE the horizon in the sky band

; joypad bit masks ($4218 auto-read layout; shifts, not addresses)
JOY_B     = 1 << 15
JOY_START = 1 << 12
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8
