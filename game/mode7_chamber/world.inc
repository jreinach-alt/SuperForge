; =============================================================================
; world.inc — the chamber's geometry and feel constants (NOT addresses)
; =============================================================================
; Every address, channel and register encoding on this rail is allocator-emitted
; and `no_literals` refuses a raw one. What lives here is the other kind of
; constant: world geometry, the seam, and the roll's feel numbers.
;
; Values are DECIMAL or SHIFTS, never hex, for the reason AGENTS.md gives: a
; bare $0400 lands inside a real WRAM claim and nothing in the token
; distinguishes a hardware constant from a hand-narrated address. The shift
; form also says what is meant — "bit 10 of a 1024-px period" reads; `$03FF`
; does not.

; --- the plane --------------------------------------------------------------
; DERIVED from the map claim's own size rather than narrated: the Mode 7 blob
; is 2 bytes per tile (tilemap even, CHR odd) over a square plane, so its size
; fixes the side. Writing the derivation is what makes the camera constants
; below FOLLOW the map instead of agreeing with it by coincidence.
CH_MAP_T    = 128                       ; world side, in tiles
CH_TILE_PX  = 8
CH_WORLD_PX = CH_MAP_T * CH_TILE_PX     ; 1024 — the plane's period (M7SEL wrap)
CH_MAP_MASK = CH_WORLD_PX - 1           ; the roll wraps to this, both directions

; --- the frame --------------------------------------------------------------
; The seam: lines 0..MB_SEAM-1 are the Mode 1 band, MB_SEAM..223 the Mode 7
; floor. The horizon IS the mode split, so one number serves both.
MB_SEAM     = 32
CH_LINES    = 224                       ; the active picture
CH_HALF_W   = 128                       ; half the 256-px screen: the pivot's x

; --- the camera -------------------------------------------------------------
; Horizontal position is FIXED (written once and never again); the vertical
; position is the roll.
CH_CAM_X    = CH_WORLD_PX / 2           ; chamber centre
CH_START_Y  = CH_WORLD_PX / 2

; --- split_band's binding contract ------------------------------------------
; The five symbols that feature carries no default for. FOURTH live binding of
; one splitter, after microzero's $16/$11, split_h_demo's $04/$01 and racer's
; $12/$11.
SB_LINES    = MB_SEAM                   ; the seam: Mode 1 rows 0..31
SB_MODE_TOP = $09                       ; Mode 1, BG3 priority high
SB_MODE_BOT = $07                       ; Mode 7 (the floor)
; TM_TOP IS $00 HERE. A band that enabled OBJ would reach the same stated
; intent — a clean strip showing the backdrop, with no BG3 tilemap to author —
; only while nothing draws sprites. This rail composes no OBJ feature at all,
; so nothing owns the OAM table and power-on OAM is RANDOM (CLAUDE.md rule 5;
; vendor/rom's ppu_reset.inc initialises OAMADD, not OAM's contents). Enabling
; the layer would render power-on garbage over the band. $00 reaches the intent
; without claiming a resource this rail has no owner for.
SB_TM_TOP   = $00                       ; nothing on the main screen: the
                                        ;   backdrop (CGRAM word 0, dark stone)
SB_TM_BOT   = $01                       ; BG1: the Mode 7 floor

; --- rgb_gradient's binding contract ----------------------------------------
; WHICH LAYERS the vignette lands on: bit 0 BG1 + bit 5 BACKDROP, and it
; matters in both bands — BG1 is the floor below the seam, and the backdrop is
; the whole picture above it. Without the backdrop bit the Mode 1 band would be
; flat black instead of vignetted stone.
RG_MATH_LAYERS = (1 | 32)
