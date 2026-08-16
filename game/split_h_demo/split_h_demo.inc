; =============================================================================
; split_h_demo.inc — the cockpit rail's geometry and band bindings
; =============================================================================
; Sizes, coordinates and hardware-shape bytes. Never an address: every address
; on this rail comes from the allocator's emitted map (allocator/no_literals.py
; refuses anything else).

; --- the seam ---------------------------------------------------------------
; Line 40 is BOTH the band boundary AND the perspective horizon: split_band's
; table splits at SB_LINES and mode7_persp derives PERSP_LINES = 224 -
; HUD_LINES, so the pose blobs this rail links carry exactly 184 rows. One
; number, both roles — the first thing to tweak when reshaping the rail.
;
; 40 rather than microzero's 44 DELIBERATELY. The two rails are the two
; bindings of one generalised splitter, and a second binding that reused the
; first one's seam would prove only half of the generalisation.
HUD_LINES = 40

; --- split_band's binding contract (five symbols, no defaults) --------------
; The rail's whole subject. docs/09's SPLIT row: `split_band` is the sole
; ACTIVE-PHASE owner of BGMODE, frame-wide (`band = "scene"`), and a second
; split shape is the same claim with different table values. These are those
; values.
;
; TM $04/$01 is where this binding parts company with microzero's $16/$11: this
; rail composes no `sky_band` (no BG2) and no `oam_sprites` (no OBJ), so the top
; band is BG3 ALONE and the floor band is BG1 ALONE. Enabling layers with no
; content in them would put the test's picture claims on the wrong composition.
SB_LINES    = HUD_LINES         ; lines 0..39 = the instrument band
SB_MODE_TOP = $09               ; BGMODE above the seam: Mode 1, BG3 priority
SB_MODE_BOT = $07               ; BGMODE below the seam: Mode 7 floor
SB_TM_TOP   = $04               ; TM above the seam: BG3 only
SB_TM_BOT   = $01               ; TM below the seam: BG1 only

; --- the cockpit camera -----------------------------------------------------
; The camera spins IN PLACE around the pivot line and never travels: the origin
; is written once at enter and only the HEADING moves, which is exactly the axis
; pose_rom is indexed by.
;
; The world is microzero's — `mode7_floor` + `world_rom`, reused rather than
; re-authored, because the plane is not this rail's subject (the SPLIT is) and a
; second 256 KB map would be ROM spent on nothing the tests read. The start tile
; is that map's start/finish spoke, so the floor band shows road under the
; instrument panel.
; mode7_floor's world binding (the includer's, like col_map's and
; mode7_stream's): WHICH world the seed upload walks is the game's business.
; These are microzero's blob's geometry, asserted against the claim the
; allocator emitted rather than restated on trust.
WORLD_T_TILES       = 512       ; 512x512 tiles = 4096x4096 px
WORLD_ROWS_PER_BANK = 64        ; 64 rows x 512 B = one 32 KB ROM window
.assert WORLD_ROWS_PER_BANK * WORLD_T_TILES = ES_R_WORLD_MAP_T0_SIZE, error, "rows-per-bank disagrees with the world_map chunk size"
.assert WORLD_ROWS_PER_BANK * ES_R_WORLD_MAP_CHUNKS = WORLD_T_TILES, error, "the world_map claim's chunk count does not cover WORLD_T_TILES rows"

CAM0_TX  = 456                  ; tile coords (tools/gen_m7_assets.start_tile)
CAM0_TY  = 256
CAM0_PX  = 3652                 ; pixel coords (tile*8 + 4)
CAM0_PY  = 2052
PIVOT_LINE = 168                ; the scanline the camera origin projects to;
                                ;   VOFS derives from it

; --- the pose ramp ----------------------------------------------------------
; tools/gen_pose_tables.py --lines 184 --scale-far 436 --scale-near 77. The row
; count is 224 - HUD_LINES and the .assert below is what keeps the blob and the
; seam from drifting apart (a short blob would stream a neighbour's bytes
; through M7A-M7D for the tail rows and the floor would tear at a line no test
; names).
SHD_POSE_LINES = 184
.assert SHD_POSE_LINES = 224 - HUD_LINES, error, "pose blob row count disagrees with the seam — regenerate with --lines (224 - HUD_LINES)"

; --- rotation: the stress axis ----------------------------------------------
; pose_rom is indexed by 64 headings, so one step per held frame is 360/64 =
; 5.6 deg — a full revolution in 64 held frames. Fast enough that a seam that
; drifts by one scanline while the matrix churns shows up in a capture.
ROT_SPD  = 1
HEAD_MASK = 63                  ; 64 headings, wrapping

; --- the instrument panel ---------------------------------------------------
; BG3 2bpp tile attr: palette 7 (bg_text's claimed CGRAM words 28..31), priority
; bit set so the panel sits above BG1 in the Mode-1 band.
SHD_TXT_ATTR = (7 << 10) | (1 << 13)
; The live readout: 4 consecutive cells on row 2, col 21 — TXT_Q_MAX exactly,
; so one text_queue_hex4 staging fills the queue and the NMI commits it whole.
; A wider dynamic instrument (a multi-cell fill bar, say) would need a staged
; WRAM buffer pushed by its own VBlank DMA; bg_text's one-run cell queue is the
; shipped idiom here and 4 cells is its capacity, so the instrument is a 4-digit
; readout by design rather than by trim.
SHD_HUD_CELL = ES_V_TEXT_MAP + 2 * 32 + 21
.assert SHD_HUD_CELL >= ES_V_TEXT_MAP, error, "HUD readout starts before bg_text's text_map claim"
.assert SHD_HUD_CELL + 4 <= ES_V_TEXT_MAP + ES_V_TEXT_MAP_WORDS, error, "HUD readout overruns bg_text's text_map claim"

; --- joypad bit masks ($4218 auto-read layout; shifts, not addresses) -------
JOY_A     = 1 << 7
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8
