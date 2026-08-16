; =============================================================================
; shmup.inc — the rail's geometry, tuning and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because shmup_bg.asm,
; shmup_obj.asm and the play scene all read from it and ca65 resolves scopes
; backward. Pure equates: no code, no claims, nothing the allocator owns.
;
; Screen space is 256x224. The playfield does not scroll horizontally and the
; BG1 field scrolls vertically ONLY through BG1VOFS, so actor coordinates are
; plain screen pixels throughout — there is no world space to convert from.

; --- $4218 bit POSITIONS. Written as shifts because a bare 4096 is also a
;     plausible VRAM word address and no_literals cannot know which you meant.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11
JOY_START = 1 << 12
JOY_A     = 1 << 7

; --- tuning: the numbers that decide what this rail plays like --------------
SHIP_SPEED   = 2                 ; px/frame, d-pad
BULLET_SPEED = 4                 ; px/frame, up
FOE_SPEED    = 1                 ; px/frame, down
SPAWN_PERIOD = 48                ; frames between fighters
START_LIVES  = 3
IFRAMES      = 90                ; invulnerable frames after a hit
BLINK_PHASE  = 4                 ; hidden while (hurt & 4): ~4 on / 4 off
ANIM_RATE    = 6                 ; game frames per animation step
ANIM_STEPS   = 2                 ; the plume's two frames
BURST_LIFE   = 16                ; frames a kill-burst plays (4 frames x 4)

; --- the ship ----------------------------------------------------------------
SHIP_W       = 16
SHIP_H       = 16
SHIP_SPAWN_X = 120               ; spawn + respawn column (playfield centre-ish)
SHIP_SPAWN_Y = 176               ; ...low, clear of the fighters' spawn line
SHIP_MIN_X   = 8
SHIP_MAX_X   = 224               ; 256 - 16 ship - 16 inset
SHIP_MIN_Y   = 32                ; clear of the HUD band
SHIP_MAX_Y   = 200               ; 224 - 16 ship - 8 inset

; A bullet must not step over a 16 px fighter between frames, and the left/top
; clamps subtract SHIP_SPEED from an UNSIGNED coordinate before comparing —
; both are structural, so both are asserted rather than commented.
.assert BULLET_SPEED <= 8, error, "BULLET_SPEED > 8 tunnels past a 16px fighter"
.assert SHIP_SPEED <= SHIP_MIN_X, error, "SHIP_SPEED > SHIP_MIN_X wraps the left clamp below 0"
.assert SHIP_SPEED <= SHIP_MIN_Y, error, "SHIP_SPEED > SHIP_MIN_Y wraps the top clamp below 0"

; --- bullets, fighters, bursts ----------------------------------------------
BULLET_W    = 8
BULLET_H    = 8
BULLET_DX   = 4                  ; muzzle offset: centre the 8px bullet on 16px
BULLET_DY   = 8                  ; ...just above the nose
BULLET_TOP  = 16                 ; above this it has gone behind the HUD: expire
FOE_W       = 16
FOE_H       = 16
FOE_SPAWN_Y = 24                 ; just under the HUD band: a pop-in, not a slide
FOE_GONE_Y  = 208                ; below this the 16px fighter has fully left
PARK_Y      = 240                ; Y = $F0 — a dead slot's parking row

; --- the pools (inside shmup_obj's shm_pools claim) --------------------------
; One region, three pools, a fixed 16-byte stride per field so a pool is
; (base, count) and a field is base + field + slot*2. The offsets below are
; RELATIVE to an allocator-emitted claim, never absolute addresses — which is
; what lets three pools share one region without anyone hand-checking that
; they do not overlap.
SHM_STRIDE = 16                  ; 8 u16 slots per array
SHM_ALIVE  = 0                   ; field offsets within a pool
SHM_PX     = 16
SHM_PY     = 32
SHM_PT     = 48
SHM_BUL    = 0                   ; pool bases within the claim
SHM_BUL_N  = 7
SHM_FOE    = 48
SHM_FOE_N  = 4
SHM_BUR    = 96
SHM_BUR_N  = 4
SHM_POOL_BYTES = SHM_BUR + 4 * SHM_STRIDE
; shm_pool_spawn's "every slot is live" answer. Negative so a caller branches
; with `bmi` — a real slot offset is always positive and always small.
SHM_POOL_FULL = $FFFF
.assert SHM_BUL_N * 2 <= SHM_STRIDE, error, "bullet pool overruns its stride"
.assert SHM_FOE_N * 2 <= SHM_STRIDE, error, "fighter pool overruns its stride"
.assert SHM_BUR_N * 2 <= SHM_STRIDE, error, "burst pool overruns its stride"

; --- the BG1 planet field ----------------------------------------------------
; Ten 4x4-tile stamps of four planet blocks over a 32x32 map. 32 rows x 8 px =
; 256 px, exactly what BG1VOFS wraps at, so the field loops with no seam.
SHM_MAP_W       = 32
SHM_MAP_H       = 32
SHM_TILE_BLANK  = 0
SHM_PLANET_BASE = 1              ; planet p cell (r,c) = 1 + p*16 + r*4 + c
SHM_PLANET_SIDE = 4
SHM_PLANET_TILES = SHM_PLANET_SIDE * SHM_PLANET_SIDE
SHM_STAMPS      = 10
SHM_BAR_TILE    = 65             ; the solid HUD-bar tile, last in the page
SHM_BAR_ROWS    = 3              ; BG2 rows 0..2 carry the band

; CGRAM word 0 — the night sky. Written as a 5-bit BGR triple rather than a
; packed word so it reads as a colour and not as an address (and so
; no_literals never has to guess which it is): R=1 G=3 B=7, a deep midnight
; blue that sprites still read against.
SHM_SKY = (7 << 10) | (3 << 5) | 1

; --- OBJ tiles, on the 16-wide VRAM grid tools/gen_shmup_assets.py emits -----
; A 16x16 sprite names its TOP-LEFT tile; the PPU reads {N, N+1, N+16, N+17}.
OBJ_SHIP   = 0                   ; + frame*2
OBJ_FOE    = 4                   ; + frame*2
OBJ_BURST  = 8                   ; + frame*2, four frames
OBJ_BULLET = 32                  ; the small 8x8, on grid row 2

; --- OAM attr bytes: %vhoopppN (bit 0 = tile bit 8, 1-3 palette, 4-5 priority)
OBJ_PRIO      = 3 << 4
OBJ_ATTR_SHIP = OBJ_PRIO                 ; OBJ palette 0
OBJ_ATTR_FOE  = OBJ_PRIO | (1 << 1)      ; OBJ palette 1 — fighters AND bullets
OBJ_ATTR_BUR  = OBJ_PRIO | (2 << 1)      ; OBJ palette 2

; --- BG3 text geometry -------------------------------------------------------
SHM_HUD_ROW      = 1
SHM_HUD_SCORE_C  = 2             ; "SCORE" label
SHM_HUD_SCORED_C = 8             ; ...its 4 digits
SHM_HUD_LIVES_C  = 18            ; "LIVES" label
SHM_HUD_LIVESD_C = 24            ; ...its 1 digit

; The verdict block is TWO fixed 11-cell rows written ONE CELL PER FRAME
; through bg_text's VBlank queue, because a running scene cannot write VRAM any
; other way. Fixed width and position means a new block totally overwrites the
; last — no residue, no length bookkeeping, no clear pass.
SHM_MSG_W    = 11
SHM_MSG_COL  = 10
SHM_MSG_ROW0 = 12
SHM_MSG_ROW1 = 14
SHM_MSG_LEN  = SHM_MSG_W * 2

; --- HUD reprint requests (US_DIRTY bits) -----------------------------------
SHM_DIRTY_SCORE = 1
SHM_DIRTY_LIVES = 2

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_TITLE = 0
SCENE_PLAY  = 1
