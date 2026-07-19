; =============================================================================
; split_h_2p_demo — 2-PLAYER SPLIT SCREEN: two independently-positioned Mode-7
;                   cameras over ONE world, ~zero per-frame CPU
; =============================================================================
; WHAT IT IS: a horizontal split screen. The top half is player 1's Mode-7
; floor camera, the bottom half is player 2's — both looking at the SAME
; wrapping checker world, each from its own position (and, in the rotate and
; sprite builds, its own heading). The point of the rail: neither camera runs
; a live perspective solve. Each band streams a ROM-resident, per-scanline
; pose table straight through the HDMA engine, so the entire per-frame CPU is
; ~40 register stores — which is what leaves budget for TWO cameras at 60 fps.
;
; CONTROLS: the DEFAULT build (make split_h_2p_demo) is a ZERO-INPUT autonomous
; demo — the two cameras pan on their own, it reads no buttons, and it plays a
; kit music track over the TAD driver (the other builds are silent). The PLAYABLE
; build is `_sprites` (build_split_h_2p_variants.sh): pad 1 drives camera 1 and
; pad 2 drives camera 2 — D-pad LEFT/RIGHT rotates that camera one step per
; frame held, B drives it forward. (Full -D variant map: this rail's README.md.)
;
; FILE LAYOUT (top to bottom):
;   INTERRUPTS   — NMI: re-arm HDMA + tick the display heartbeat (per VBlank).
;   INIT (RESET) — upload the world/palettes/Mode-7 regs, allocate + bind the
;                  matrix and origin HDMA channel pairs, screen on.
;   MAIN LOOP    — game_loop: the once-per-frame heartbeat. START READING HERE.
;   SUBROUTINES  — stamp_origins, bind_matrix_pair, stamp_pose_banks, and the
;                  small mask/channel helpers the binds share.
;   sprites_2p.inc — the optional sprite-stress rail (the SPRITES=N builds).
;   DATA         — pose tables, the checker map, the rotate pose-bank slices.
;
; Build: make split_h_2p_demo   ·   variants: build_split_h_2p_variants.sh
; LDCFG: lorom_tad_m7.cfg  (bank 0 = code + pose tables; BANK1 = 32 KB map;
;        bank 2 = TAD audio — the autonomous showcase plays a kit track. The
;        -D variants link lorom_64k.cfg / lorom_stream.cfg and are silent.)
;
; HOW IT WORKS: both bands are per-scanline perspective floors of the SAME
; world, each with a fully LIVE, INDEPENDENT world position — and NO live
; matrix solve at all:
;
;   MATRIX  — both bands stream ROM-resident pose tables via INDIRECT-mode HDMA
;             (DMAP $43: indirect + write-2-registers-twice). A template-owned
;             7-byte WRAM index table per channel ([$80|112, ptr][$80|112, ptr]
;             [0]) gives each band its own per-line camera; retargeting a band
;             to another pose (heading) is ONE 2-byte pointer rewrite in VBlank.
;             Pose tables come from tools/gen_pose_tables.py (--angles 1/32/64/
;             128/256/512; 256 is the rotate default — one pose step PER FRAME
;             at the demo turn rate. The default (non-rotating) build streams
;             the single fixed-angle pose: both cameras share one heading, and
;             position alone distinguishes the two bands.
;   ORIGIN  — per-band world position via the proven origin-splice channel pair
;             (NON-REPEAT DMAP $03): one channel streams M7X/M7Y ($211F), one
;             M7HOFS/M7VOFS ($210D). At fixed heading the per-band origin is
;             PURE SUBTRACTION (M7X/Y = pos; HOFS = posx-128; VOFS = posy -
;             band_bottom_line) — no engine solve. Both positions update EVERY
;             frame in the VBlank window.
;
; WHY THIS SHAPE (the measured history): one live per-scanline solve costs
; 86-138% of a 60fps frame (tests/persp_cycles_test.asm), and the live-A rail's
; integrated loop measurably closes in 2 frames (30 Hz motion). This rail's
; whole per-frame CPU is ~40 VBlank stores — the loop closes EVERY frame, and
; test_cadence gates that IN SITU (the E010-heartbeat-is-not-a-budget-gate
; lesson: G_FRAMES and E010 must BOTH advance +1 per stepped frame).
;
; ValueLatch guard BY CONSTRUCTION: all shared-latch registers are written by
; code only under forced blank (boot); during display only HDMA drives them;
; every runtime table write happens in VBlank right after wai (the HDMA init
; fetch for the next frame cannot observe a half-written entry).
;
; COMPILE-TIME SWITCHES (variant script passes them):
;   -DFREEZE=1          both cameras hold position (stills for comparisons).
;   -DSAME_ORIGIN=1     camera 2's position := camera 1's -> band 2 leaves the
;                       warm stripe -> the red position signal MUST die (the
;                       independent-position non-vacuity control).
;   -DRETARGET=1        at frame 90 band 2's pose pointers flip to the 45-degree
;                       pose sliced from the 64-angle shipping set -> the
;                       non-trivial-heading streaming + retarget smoke.
;   -DROTATE=1          BOTH cameras rotate AND move: a full pose set streams
;                       from dedicated banks (per-channel indirect data banks),
;                       both cameras drive FORWARD along their heading
;                       (move_lut) -> two opposite-sense circles. Pose pointers
;                       are recomputed EVERY frame (worst case, deliberately) —
;                       the cadence gate measures this build too. Rotation
;                       pivots at each band's bottom-centre BY CONSTRUCTION:
;                       the subtraction origin zeroes the matrix term there,
;                       so heading needs NO new origin math. Links
;                       lorom_stream.cfg (the 64KB default image has no room
;                       for the pose banks). Do not combine with RETARGET
;                       (both own band 2's pointers). FREEZE composes:
;                       ROTATE+FREEZE = rotate in place.
;   -DPOSES=256         (with ROTATE) the ROTATION-SMOOTHNESS DEFAULT: 256
;                       poses (1.40625 deg each), one pose step PER FRAME on
;                       both cameras (+1/-1, equal-and-opposite senses) =
;                       a pose step EVERY frame at the sustained turn rate (the
;                       rotation-smoothness target: no visible pose stepping in
;                       the floor). Implies PERBAND (below). Blob
;                       = 4 bank slices (BANK2..5 AB, BANK6..9 CD); per-frame
;                       ptr = $8000 + (h & 63)*448, bank = base + (h >> 6),
;                       DASB stamped per band per frame in VBlank
;                       (stamp_pose_banks; mirrors at $7E:E040+). POSES=64
;                       (default) keeps the classic single-bank shape:
;                       cam 1 steps every 4 frames, cam 2 every 6, move64.
;   -DPERBAND=1         per-band matrix channel PAIRS (implied by POSES=256;
;                       standalone for the cheap 64-pose structural builds):
;                       each band gets its OWN AB+CD pair -> its own $43x7 ->
;                       any pose bank per band. 6 allocator channels total.
;                       Band-2's tables open with a NON-REPEAT count-112 skip
;                       prefix whose single stray line-0 unit is masked by
;                       CHANNEL PRIORITY (band-2's pair allocated FIRST =
;                       lower channels; band-1's SECOND = higher channels
;                       write M7A-D LAST in the HBlank and win).
;   -DPERBAND_BADORDER=1 NON-VACUITY CONTROL: inverts the allocation order so
;                       the stray line-0 unit WINS -> exactly PPU line 0
;                       renders band-2's skip pose (the test's row-7 gate).
;   -DLATCH_VIOLATION=1 a code-side write-twice to M7HOFS ($210D) spun across
;                       active display, with BAND-1's channel value (in band 1
;                       the register value is unchanged -> pure latch-interleave
;                       corruption there, and band 1 is the band the test
;                       measures; during band-2 display the same spin is
;                       additionally a value stomp — out of the metric window).
;                       Pair it with FREEZE: the test compares frozen-vs-frozen
;                       (the rotating-baseline confound lesson).
;
; Cost: classic = 4 allocator channels (2 matrix + 2 origin, mask $3C on a
; fresh allocator); PERBAND/POSES=256 = ALL 6 (4 matrix + 2 origin, mask $FC
; — a later OBJ-window clip or sky band needs channel multiplexing). ~40 CPU
; stores/frame (+ ~30 for the 256 build's four DASB stamps), 448 B ROM per
; pose per channel. VRAM: one shared low-32KB map+CHR — no extra per camera.
;
; (Build + LDCFG are in the file-top map above; the -D switch effects on the
; link shape are noted per-switch here.)
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

.ifdef ROTATE
.ifdef RETARGET
    .error "ROTATE and RETARGET both own band 2's pose pointers — do not combine"
.endif
.endif

; --- pose-set knob (first-class): POSES=64 (default — classic shared-table
;     4-channel shape, single-bank blobs, byte-compatible with the prior ROMs)
;     or POSES=256 (the rotate-smoothness default: implies PERBAND — per-band
;     matrix channel pairs, 6 allocator channels, 4 bank slices per blob,
;     per-frame DASB stamping). -DPERBAND alone keeps the 64-pose per-band
;     structural/control builds cheap (the mask/line-0 tests). ---------------
.ifndef POSES
POSES = 64
.endif
.if (POSES <> 64) && (POSES <> 256)
    .error "POSES must be 64 (classic single-bank) or 256 (per-band pairs)"
.endif
.if POSES = 256
.ifndef ROTATE
    .error "POSES=256 is the rotation-smoothness set — requires ROTATE"
.endif
.ifndef PERBAND
PERBAND = 1                     ; 256 poses IMPLIES per-band matrix pairs
.endif
.endif
.ifdef PERBAND_BADORDER
.ifndef PERBAND
    .error "PERBAND_BADORDER is a PERBAND control — define PERBAND too"
.endif
.endif

; --- audio: the autonomous showcase build plays music ------------------------
; The DEFAULT build (make split_h_2p_demo — neither FREEZE nor ROTATE defined)
; is the zero-input showcase: it links a TAD-audio config and plays a kit
; track. EVERY -D variant opts out — the stills/controls to keep their link
; shape, and all the ROTATE/sprite instruments because their per-frame CADENCE
; is MEASURED (an audio tick every frame would perturb the +1/+1 gate). This is
; why the interactive `_sprites` build is silent by design. (The 256-pose
; stream link has no spare bank for the TAD data either — a separate concern.)
.ifndef FREEZE
.ifndef ROTATE
SF_AUDIO = 1                    ; showcase-only; gates the includes + calls below
.endif
.endif

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SPLIT H 2P"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0
.include "engine_state.inc"
.ifdef SF_AUDIO
.include "tad-audio.inc"        ; TAD ca65 API imports (-I .../ca65-api)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids (-I assets/audio)
.include "sf_audio.inc"         ; kit audio macros (sf_audio_init/tick/sf_music)
.endif

; --- band geometry ------------------------------------------------------------
SEAM       = 112                ; band 1 = lines 0..111, band 2 = 112..223
B_LINES    = 112                ; scanlines per band (each floor is 112 tall);
                                ; also the HDMA repeat/skip line count per entry

; --- camera start positions (world px; the map wraps at 1024) ------------------
; Camera 1 starts centred on the COOL stripe (world X 512), camera 2 on the WARM
; stripe (world X 768 = +256): band 2's RED channel is the independent-position
; framebuffer signal. Default motion: cam 1 pans +1 px/frame in Y, cam 2 +2 —
; both stay inside their stripes forever (X never changes), so the red signal is
; frame-index-robust while the checker PHASE shows independent motion.
P1_X0      = 512
P1_Y0      = 512
P2_X0      = 768
P2_Y0      = 512

; --- CGRAM (15-bit BGR): "Four Seasons" terrain dressing. The two floors read
;     as SUMMER (cool = greens, R=0) and AUTUMN (warm = oranges, R=31). The
;     warm/cool split is the RED channel and is the per-band position oracle,
;     so it is held at MAXIMUM separation on purpose: cool R=0, warm R=31
;     (rendered red 0 vs 255) — the dressing recolours GREEN/BLUE freely but
;     never touches that invariant, and the C1/seam red thresholds are
;     re-derived from the render and confirmed unchanged (see test).
COLOR_BACKDROP    = $5400       ; distant dusk backdrop (behind the floor)
COLOR_COOL_DARK   = $0DA0       ; summer forest green  (R=0,  G=13, B=3)
COLOR_COOL_LIGHT  = $1340       ; summer meadow green  (R=0,  G=26, B=4)
COLOR_WARM_DARK   = $00DF       ; autumn burnt orange  (R=31, G=6,  B=0)
COLOR_WARM_LIGHT  = $023F       ; autumn amber/pumpkin (R=31, G=17, B=0)

FX_M7_MATRIX = $2B              ; allocator effect tags
FX_M7_ORIGIN = $2C
FX_M7_MATRIX2 = $2D             ; PERBAND: band-2's own matrix pair

; --- WRAM layout (engine-free $7E:C000 gap; no new DP state -> zp-check clean) -
IDX_AB     = $C000              ; 7 B  AB index table: [$80|112,ptr][$80|112,ptr][0]
                                ;      (PERBAND: band-1 only, [$80|112,ptr][0])
IDX_CD     = $C010              ; 7 B  CD index table
IDX_AB2    = $C080              ; 7 B  PERBAND band-2 AB: [112,skip][$80|112,ptr][0]
IDX_CD2    = $C090              ; 7 B  PERBAND band-2 CD (same shape)
MP_IDXAB   = $C0A0              ; word: bind_matrix_pair arg — AB table loword
MP_IDXCD   = $C0A2              ; word: CD table loword
MP_BANKAB  = $C0A4              ; byte: AB channel DASB (indirect data bank)
MP_BANKCD  = $C0A5              ; byte: CD channel DASB
MP_FX      = $C0A6              ; word: allocator effect tag
MP_MSK     = $C0A8              ; word: out — the pair's channel mask
MP_CHXAB   = $C0AA              ; word: out — AB channel reg offset (ch * $10)
MP_CHXCD   = $C0AC              ; word: out — CD channel reg offset (ch * $10)
CHX_AB1    = $C0B0              ; word: band-1 AB channel reg offset [PERBAND]
CHX_CD1    = $C0B2              ; word: band-1 CD channel reg offset [PERBAND]
CHX_AB2    = $C0B4              ; word: band-2 AB channel reg offset [PERBAND]
CHX_CD2    = $C0B6              ; word: band-2 CD channel reg offset [PERBAND]

; band-2's pose-pointer slots: shared-table entry 2 (classic) or its own
; table's entry 2 (PERBAND — entry 1 is the 112-line skip prefix).
.ifdef PERBAND
B2_AB_PTR  = IDX_AB2 + 4
B2_CD_PTR  = IDX_CD2 + 4
.else
B2_AB_PTR  = IDX_AB + 4
B2_CD_PTR  = IDX_CD + 4
.endif

.ifdef ROTATE
; pose blob slice-base aliases (the loop's pointer math is POSES-agnostic:
; ptr = slice_base + (h & 63)*448; POSES=256 adds bank = base + (h >> 6)):
.if POSES = 64
pose_ab_base = poses64_ab
pose_cd_base = poses64_cd
.else
pose_ab_base = poses256_ab_s0
pose_cd_base = poses256_cd_s0
.endif
.endif
OTBL_XY    = $C020              ; 11 B origin table (M7X/M7Y):  [112,X1,Y1][1,X2,Y2][0]
OTBL_HV    = $C040              ; 11 B origin table (HOFS/VOFS): same shape
POS1X      = $C060              ; 4 words: the two camera positions
POS1Y      = $C062
POS2X      = $C064
POS2Y      = $C066
HOFS1_MIR  = $C068              ; word: band-1 HOFS mirror (the latch model's value)
H1         = $C06A              ; word: camera 1 heading index (0..63) [ROTATE]
H2         = $C06C              ; word: camera 2 heading index (0..63) [ROTATE]
CNT6       = $C06E              ; word: camera 2's every-6-frames divider [ROTATE]
PTRTMP     = $C070              ; word: h*448 pose-offset scratch [ROTATE]
F1X        = $C072              ; 4 words: per-axis 8.8 FRACTION accumulators
F1Y        = $C074              ;   (low byte = sub-pixel fraction; the high
F2X        = $C076              ;   byte carries the frame's signed integer
F2Y        = $C078              ;   delta after the velocity add) [ROTATE]
G_MSK      = $7EE020            ; word: matrix channel mask (debug read)
                                ;      (PERBAND: band-2's pair — allocated FIRST)
G_MSK2     = $7EE022            ; word: origin channel mask (debug read)
G_MSK3     = $7EE024            ; word: PERBAND band-1 matrix pair mask
G_BANKS    = $7EE040            ; 4 B: POSES=256 stamped-DASB debug mirrors —
                                ;      +0 AB1, +1 CD1, +2 AB2, +3 CD2 (the test
                                ;      reads the banks the VBlank stamper wrote)
G_FRAMES   = $7EE030            ; word: MAIN-LOOP iteration counter — the in-situ
                                ;       cadence signal (vs the NMI's E010)

.segment "CODE"

; -----------------------------------------------------------------------------
; NMI — minimal (persp3 pattern): re-arm HDMA, heartbeat, ack. The heartbeat is
; a DISPLAY/NMI liveness counter ONLY — the loop-rate gate is G_FRAMES.
; WIDTH-RISK: an interrupt can fire while the CPU is in EITHER register width,
; so the handler must not assume 8- or 16-bit mode on entry. (The 65816 runs
; its accumulator and index registers in 8- or 16-bit mode, chosen by two CPU
; flags; the assembler needs the .a8/.a16 hints to size each instruction, and
; if the two disagree the instruction stream desyncs.) So this handler saves
; the caller's flags (php), forces a known 16-bit width for its own work
; (rep #$30), then restores the exact entry width on the way out (plp) — the
; interrupted code resumes in the width it expected.
; -----------------------------------------------------------------------------
NMI:
    php
    rep #$30
    .a16
    .i16
    pha
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    sta $420C                   ; re-arm all bound channels every VBlank
    rep #$20
    .a16
    lda f:$7E0000 + $E010
    inc a
    sta f:$7E0000 + $E010
.ifdef SP_CYCLES
    ; sprite-rail instrument: u32 frame counter (persp_cycles pattern, $E034)
    lda f:$7E0000 + $E034
    inc a
    sta f:$7E0000 + $E034
    bne :+
    lda f:$7E0000 + $E036
    inc a
    sta f:$7E0000 + $E036
:
.endif
    sep #$20
    .a8
    lda $4210                   ; RDNMI ack
    rep #$20
    .a16
    pla
    plp
    rti

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    jsr hdma_alloc_init         ; reserves CH0/CH1

    ; --- upload the warm/cool checker world (GP-DMA ch0, forced blank) --------
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after $2119
    rep #$20
    .a16
    stz $2116                   ; VMADD = $0000
    sep #$20
    .a8
    lda #$01
    sta $4300                   ; DMAP0: mode 1 (2 regs $2118/$2119)
    lda #$18
    sta $4301                   ; BBAD0 = VMDATA
    rep #$20
    .a16
    lda #.loword(checker_map)
    sta $4302                   ; A1T0L/H (ch0 source address): map loword
    sep #$20
    .a8
    lda #^checker_map
    sta $4304                   ; A1B0 (ch0 source bank): map bank
    rep #$20
    .a16
    lda #$8000
    sta $4305                   ; DAS0L/H (ch0 byte count): the 32 KB map
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; MDMAEN (GP-DMA trigger): fire channel 0

    ; --- Load the floor palette into CGRAM, the PPU's colour memory: set the
    ;     start index once, then stream 2 bytes (low, high) per 15-bit BGR
    ;     colour. Safe now — the screen is force-blanked, so the PPU is not
    ;     reading colours mid-frame. The checker map indexes these five entries;
    ;     the warm/cool split (only the warm pair carries red) is the per-band
    ;     world-position signal the tests read off the framebuffer. ---
    stz $2121                   ; CGADD (CGRAM address): start at colour 0
    lda #<COLOR_BACKDROP
    sta $2122                   ; CGDATA (CGRAM data): write byte; index auto-advances
    lda #>COLOR_BACKDROP
    sta $2122                   ; colour 0: backdrop
    lda #<COLOR_COOL_DARK
    sta $2122
    lda #>COLOR_COOL_DARK
    sta $2122                   ; colour 1: cool dark  (summer forest, R=0)
    lda #<COLOR_COOL_LIGHT
    sta $2122
    lda #>COLOR_COOL_LIGHT
    sta $2122                   ; colour 2: cool light (summer meadow, R=0)
    lda #<COLOR_WARM_DARK
    sta $2122
    lda #>COLOR_WARM_DARK
    sta $2122                   ; colour 3: warm dark  (autumn burnt orange, R=31)
    lda #<COLOR_WARM_LIGHT
    sta $2122
    lda #>COLOR_WARM_LIGHT
    sta $2122                   ; colour 4: warm light (autumn amber, R=31)

    ; --- Mode-7 registers ONCE under forced blank (ValueLatch guard-safe).
    ;     M7X/Y + HOFS/VOFS get boot defaults here; per frame the ORIGIN HDMA
    ;     channels own them (band values from the tables below). ---------------
    lda #$07
    sta $2105                   ; BGMODE = 7
    lda #$01
    sta $212C                   ; TM = BG1 only
    lda #$00
    sta $211A                   ; M7SEL = wrap
    lda #$00
    sta $210D
    sta $210D                   ; M7HOFS = 0
    sta $210E
    sta $210E                   ; M7VOFS = 0
    lda #<P1_X0
    sta $211F
    lda #>P1_X0
    sta $211F                   ; M7X = camera 1 X
    lda #<P1_Y0
    sta $2120
    lda #>P1_Y0
    sta $2120                   ; M7Y = camera 1 Y
    rep #$30
    .a16
    .i16

    ; --- camera positions ------------------------------------------------------
    lda #P1_X0
    sta f:$7E0000 + POS1X
    lda #P1_Y0
    sta f:$7E0000 + POS1Y
.ifndef SAME_ORIGIN
    lda #P2_X0
    sta f:$7E0000 + POS2X
    lda #P2_Y0
    sta f:$7E0000 + POS2Y
.else
    ; NON-VACUITY control: camera 2 folded onto camera 1 -> band 2 goes cool.
    lda #P1_X0
    sta f:$7E0000 + POS2X
    lda #P1_Y0
    sta f:$7E0000 + POS2Y
.endif

    ; --- MATRIX index tables (INDIRECT-mode 3-byte entries, pv_rebuild's form).
    ;     Both bands start on the fixed-angle pose (band-local: index 0 == the
    ;     band's first scanline; each band's ptr aims at its pose's byte 0). ----
    sep #$20
    .a8
    lda #($80 | B_LINES)        ; repeat mode: a NEW 4-byte unit per scanline
    sta f:$7E0000 + IDX_AB + 0
    sta f:$7E0000 + IDX_CD + 0
.ifndef PERBAND
    sta f:$7E0000 + IDX_AB + 3
    sta f:$7E0000 + IDX_CD + 3
    lda #$00
    sta f:$7E0000 + IDX_AB + 6  ; terminator
    sta f:$7E0000 + IDX_CD + 6
.else
    ; PERBAND table shapes: band-1's tables carry ONLY its entry + terminator
    ; (count 0 at line 112 ends the channel for the frame — silent during band
    ; 2's lines). Band-2's tables open with a NON-REPEAT count-112 SKIP entry:
    ; it transfers its 4-byte unit ONCE at line 0 (stray write — masked by
    ; band-1's HIGHER channels landing later in the same HBlank), then holds
    ; silently for 111 lines; the repeat entry streams band 2 from line 112.
    sta f:$7E0000 + IDX_AB2 + 3 ; band-2 pose entry (repeat 112) after the skip
    sta f:$7E0000 + IDX_CD2 + 3
    lda #B_LINES                ; $70 = non-repeat, 112 lines
    sta f:$7E0000 + IDX_AB2 + 0
    sta f:$7E0000 + IDX_CD2 + 0
    lda #$00
    sta f:$7E0000 + IDX_AB + 3  ; band-1 terminator (after its 112 lines)
    sta f:$7E0000 + IDX_CD + 3
    sta f:$7E0000 + IDX_AB2 + 6 ; band-2 terminator
    sta f:$7E0000 + IDX_CD2 + 6
.endif
    rep #$20
    .a16
.ifndef ROTATE
    lda #.loword(poses1_ab)
    sta f:$7E0000 + IDX_AB + 1  ; band 1 AB -> fixed-angle pose
    sta f:$7E0000 + B2_AB_PTR   ; band 2 AB -> same pose (position distinguishes)
    lda #.loword(poses1_cd)
    sta f:$7E0000 + IDX_CD + 1
    sta f:$7E0000 + B2_CD_PTR
.elseif POSES = 64
    ; ROTATE: band 1 starts at heading 0, band 2 at heading 32 (opposite);
    ; pointers into the 64-pose bank blobs (pose h at blob + h*448).
    lda #.loword(poses64_ab)
    sta f:$7E0000 + IDX_AB + 1
    lda #.loword(poses64_ab) + 32 * 448
    sta f:$7E0000 + B2_AB_PTR
    lda #.loword(poses64_cd)
    sta f:$7E0000 + IDX_CD + 1
    lda #.loword(poses64_cd) + 32 * 448
    sta f:$7E0000 + B2_CD_PTR
    lda #32
    sta f:$7E0000 + H2          ; H1/CNT6 stay 0 (coldstart-cleared WRAM)
.else
    ; POSES=256 ROTATE: band 1 starts at heading 0 (slice 0, offset 0), band 2
    ; at heading 128 (opposite = slice 2, offset 0). Pose h lives at
    ; loword $8000 + (h & 63)*448 in bank slice (h >> 6); the initial DASB
    ; banks are staged inside bind_band1_pair/bind_band2_pair.
    lda #.loword(poses256_ab_s0)
    sta f:$7E0000 + IDX_AB + 1
    sta f:$7E0000 + B2_AB_PTR   ; (128 & 63)*448 = 0 -> slice base
    lda #.loword(poses256_cd_s0)
    sta f:$7E0000 + IDX_CD + 1
    sta f:$7E0000 + B2_CD_PTR
    lda #128
    sta f:$7E0000 + H2          ; H1 stays 0 (coldstart-cleared WRAM)
.endif
.ifdef PERBAND
    ; skip-prefix indirect pointers: any valid address in the band-2 channel's
    ; data bank (the transferred unit is masked at line 0 by band-1's pair).
    ; Static — never rewritten at runtime. Deliberately aimed at a pose that
    ; DIFFERS from band-1's (rot45 / blob base): if the priority mask ever
    ; broke, PPU line 0 would visibly render the wrong matrix (and the
    ; -DPERBAND_BADORDER control proves that failure is detectable).
.ifndef ROTATE
    lda #.loword(pose_rot45_ab)
    sta f:$7E0000 + IDX_AB2 + 1
    lda #.loword(pose_rot45_cd)
    sta f:$7E0000 + IDX_CD2 + 1
.elseif POSES = 64
    lda #.loword(poses64_ab)
    sta f:$7E0000 + IDX_AB2 + 1
    lda #.loword(poses64_cd)
    sta f:$7E0000 + IDX_CD2 + 1
.else
    lda #.loword(poses256_ab_s0)
    sta f:$7E0000 + IDX_AB2 + 1
    lda #.loword(poses256_cd_s0)
    sta f:$7E0000 + IDX_CD2 + 1
.endif
.endif

    ; --- ORIGIN tables (NON-REPEAT DMAP $03): counts + terminators here; the
    ;     4-byte value slots are re-stamped every frame by stamp_origins. -------
    sep #$20
    .a8
    lda #SEAM                   ; band 1 entry: transfer once, HOLD 112 lines
    sta f:$7E0000 + OTBL_XY + 0
    sta f:$7E0000 + OTBL_HV + 0
    lda #$01                    ; band 2 entry: fires at line 112, HOLDs (term next)
    sta f:$7E0000 + OTBL_XY + 5
    sta f:$7E0000 + OTBL_HV + 5
    lda #$00
    sta f:$7E0000 + OTBL_XY + 10
    sta f:$7E0000 + OTBL_HV + 10
    rep #$20
    .a16
    jsr stamp_origins           ; initial values (forced blank; no race)

    ; --- allocate + bind the MATRIX pair(s) (INDIRECT, DMAP $43) ---------------
.ifndef PERBAND
    ; classic: ONE pair — both bands' entries share each channel's table.
    ; Stage the pose data banks + table lowords, then bind_matrix_pair.
    sep #$20
    .a8
.ifndef ROTATE
    lda #^poses1_ab
    sta f:$7E0000 + MP_BANKAB
    lda #^poses1_cd
    sta f:$7E0000 + MP_BANKCD
.else
    lda #^poses64_ab            ; BANK2
    sta f:$7E0000 + MP_BANKAB
    lda #^poses64_cd            ; BANK3
    sta f:$7E0000 + MP_BANKCD
.endif
    rep #$20
    .a16
    lda #IDX_AB
    sta f:$7E0000 + MP_IDXAB
    lda #IDX_CD
    sta f:$7E0000 + MP_IDXCD
    lda #FX_M7_MATRIX
    sta f:$7E0000 + MP_FX
    jsr bind_matrix_pair
    lda f:$7E0000 + MP_MSK
    sta f:G_MSK
.else
    ; PERBAND: TWO pairs — ALLOCATION ORDER IS LOAD-BEARING. HDMA processes
    ; CH0->CH7 within each HBlank and every DMAP-$43 unit delivers complete
    ; low+high pairs to both registers, so the LAST channel to write M7A-D in
    ; an HBlank wins coherently. Band-2's skip-prefix entry fires ONE stray
    ; unit at line 0 -> allocate band-2's pair FIRST (lower channels) and
    ; band-1's SECOND (higher channels): band-1's proper line-0 values land
    ; last and mask the stray write. (-DPERBAND_BADORDER inverts the order so
    ; the stray unit WINS at line 0 — the non-vacuity control.)
.ifndef PERBAND_BADORDER
    jsr bind_band2_pair
    jsr bind_band1_pair
.else
    jsr bind_band1_pair
    jsr bind_band2_pair
.endif
.if POSES = 256
    jsr stamp_pose_banks        ; initial slice banks from H1/H2 (h2 boots in
                                ; slice 2; forced blank — no race)
.endif
.endif

    ; --- allocate + bind the ORIGIN pair (DIRECT, DMAP $03) --------------------
    lda #$0002
    ldx #FX_M7_ORIGIN
    jsr hdma_request
    sta f:G_MSK2
    bcs @bind_done
    jsr split_mask
    sep #$20
    .a8
    lda #<OTBL_XY
    sta API_BLOCK_BASE + 0
    lda #>OTBL_XY
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3      ; DMAP: direct, write-2-registers-twice
    rep #$20
    .a16
    lda API_BLOCK_BASE + 10
    ldx #$001F                  ; BBAD = M7X/M7Y
    jsr hdma_bind_direct
    sep #$20
    .a8
    lda #<OTBL_HV
    sta API_BLOCK_BASE + 0
    lda #>OTBL_HV
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3
    rep #$20
    .a16
    lda API_BLOCK_BASE + 12
    ldx #$000D                  ; BBAD = M7HOFS/M7VOFS
    jsr hdma_bind_direct
@bind_done:

    sf_debug_magic              ; "SFDB" at $7E:E000

.ifdef SF_AUDIO
    ; --- showcase audio: upload the SPC700 loader + driver under the coldstart
    ;     forced blank (before NMI is enabled — the S-SMP is still in IPL), then
    ;     start the track. It streams over the sf_audio_tick calls in game_loop.
    sf_audio_init
    sf_music #Song::ode_to_joy
.endif

.ifdef SPRITES
    rep #$30
    .a16
    .i16
.ifdef SP_PIN
    ; pin both headings BEFORE the boot projection so frame 1's floor and
    ; sprites already share the pinned pose (with FREEZE: a true still; the
    ; loop restamps pointers/banks from these values every frame)
    lda #SP_H1
    sta f:$7E0000 + H1
    lda #SP_H2
    sta f:$7E0000 + H2
.endif
    jsr sp_init                 ; sprite rail: CHR/OBSEL/palettes/OAM/entities
                                ; (forced blank)
.endif

.ifdef SP_CYCLES
    ; sprite-rail instrument: HDMA stays dark (no per-line steal), screen
    ; stays force-blanked; NMI counts frames while the free-running loop
    ; counts projection+OAM ticks (persp_cycles methodology).
    sep #$20
    .a8
    lda #$00
    sta f:$7E0000 + NMI_HDMA_ENABLE
    lda #$80
    sta $4200                   ; NMI on (frame counter only)
    rep #$30
    .a16
    .i16
    jmp sp_cycles_loop
.endif

    ; --- screen on + NMI on ----------------------------------------------------
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP (screen/brightness): full brightness,
                                ; forced blank OFF — the display is now live
.ifdef SP_INPUT
    ; COMPOSED $4200 value: NMI enable ($80) | auto-joypad read ($01). This
    ; store is a composition point — later features (e.g. the IRQ gradient
    ; line) OR more bits in here; keep it a single explicit value per build.
    lda #$81
.else
    lda #$80
.endif
    sta $4200
    rep #$30
    .a16
    .i16

; =============================================================================
; game_loop — wai, then ALL table writes inside the VBlank window (the NMI just
; returned; the next frame's HDMA init fetch cannot see a half-written entry).
; G_FRAMES counts CLOSED LOOP ITERATIONS: the cadence test asserts it advances
; +1 per stepped frame alongside E010 (the loop fits one frame — measured, not
; assumed; the live-solve rail's 30 Hz lesson).
; =============================================================================
.ifdef SPRITES
    jmp sp_game_loop            ; sprite rail: same-VBlank snapshot-commit loop
.endif
game_loop:
    .a16
    .i16
    wai
    lda f:G_FRAMES
    inc a
    sta f:G_FRAMES
.ifdef SF_AUDIO
    sf_audio_tick               ; drive the song transfer + command queue (this
                                ; build has ample per-frame headroom for it)
.endif

.ifndef ROTATE
.ifndef FREEZE
    ; --- independent motion: cam 1 pans +1 px/frame in Y, cam 2 +2 (different
    ;     speeds = the independent-driver signal; X fixed -> stripes hold). -----
    lda f:$7E0000 + POS1Y
    inc a
    and #$03FF                  ; world wraps at 1024
    sta f:$7E0000 + POS1Y
    lda f:$7E0000 + POS2Y
    inc a
    inc a
    and #$03FF
    sta f:$7E0000 + POS2Y
.endif
.else
.if POSES = 64
    ; --- ROTATE: advance headings (cam 1 every 4 frames, cam 2 every 6 the
    ;     other way), drive both cameras FORWARD along their heading, and
    ;     recompute all four pose pointers — EVERY frame, deliberately the
    ;     worst case; the cadence gate measures this. All in VBlank. ----------
    lda f:G_FRAMES
    and #$0003
    bne @no_h1
    lda f:$7E0000 + H1
    inc a
    and #$003F                  ; 64 headings
    sta f:$7E0000 + H1
@no_h1:
    lda f:$7E0000 + CNT6
    inc a
    sta f:$7E0000 + CNT6
    cmp #6
    bcc @no_h2
    lda #0
    sta f:$7E0000 + CNT6
    lda f:$7E0000 + H2
    dec a                       ; opposite rotation sense
    and #$003F
    sta f:$7E0000 + H2
@no_h2:
.else
    ; --- POSES=256 ROTATE: ONE pose step EVERY frame on both cameras
    ;     (1.40625°/frame each = the same angular rate as the 64-pose demo's
    ;     cam 1; equal-and-opposite senses — cam 2's old 0.94°/frame does not
    ;     divide into integer steps/frame). Pose-step interval = 1 frame at
    ;     sustained turn: the rotation stays smooth (no visible pose stepping),
    ;     so there is no frame divider here. -----------------------------------
    lda f:$7E0000 + H1
    inc a
    and #$00FF                  ; 256 headings
    sta f:$7E0000 + H1
    lda f:$7E0000 + H2
    dec a                       ; opposite rotation sense
    and #$00FF
    sta f:$7E0000 + H2
.endif
.ifndef FREEZE
    ; forward = move_lut[h] = round(2*256*(-sin,-cos)) in 8.8: x = h*4 offset.
    ; Each axis runs an 8.8 FRACTIONAL ACCUMULATOR: frac += vel; the high
    ; byte after the add is the frame's SIGNED integer delta (two's
    ; complement decomposition: value = high + frac/256), which moves the
    ; integer position; the fraction is kept. Constant 2.0 px/frame speed at
    ; EVERY heading — no speed pulse, no direction staircase (keeping the
    ; per-axis fraction is what removes the integer-velocity translation jerk).
    ; The FOUR blocks below are this same accumulator step repeated once per
    ; axis, in order: camera 1 X, camera 1 Y, camera 2 X, camera 2 Y.
    lda f:$7E0000 + H1
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F1X
    sta f:$7E0000 + F1X
    xba                         ; A low byte = signed integer delta
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00                  ; sign-extend
:
    clc
    adc f:$7E0000 + POS1X
    and #$03FF                  ; world wraps at 1024 (s16 delta wraps exactly)
    sta f:$7E0000 + POS1X
    lda f:$7E0000 + F1X
    and #$00FF                  ; keep only the sub-pixel fraction
    sta f:$7E0000 + F1X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F1Y
    sta f:$7E0000 + F1Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS1Y
    and #$03FF
    sta f:$7E0000 + POS1Y
    lda f:$7E0000 + F1Y
    and #$00FF
    sta f:$7E0000 + F1Y
    lda f:$7E0000 + H2
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F2X
    sta f:$7E0000 + F2X
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2X
    and #$03FF
    sta f:$7E0000 + POS2X
    lda f:$7E0000 + F2X
    and #$00FF
    sta f:$7E0000 + F2X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F2Y
    sta f:$7E0000 + F2Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2Y
    and #$03FF
    sta f:$7E0000 + POS2Y
    lda f:$7E0000 + F2Y
    and #$00FF
    sta f:$7E0000 + F2Y
.endif
    ; pose pointers: ptr(h) = slice_base + (h & 63)*448; (h&63)*448 =
    ; (m<<9) - (m<<6). At POSES=64 the mask is a no-op by construction (h is
    ; already 0..63); at POSES=256 the slice index (h >> 6) selects the BANK
    ; (stamped by stamp_pose_banks below, same VBlank window).
    lda f:$7E0000 + H1
    and #$003F                  ; band-local pose within the 64-pose bank slice
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; m<<6
    sta f:$7E0000 + PTRTMP
    asl a
    asl a
    asl a                       ; m<<9
    sec
    sbc f:$7E0000 + PTRTMP      ; m*448
    sta f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_ab_base)
    sta f:$7E0000 + IDX_AB + 1  ; band 1 AB
    lda f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_cd_base)
    sta f:$7E0000 + IDX_CD + 1  ; band 1 CD
    lda f:$7E0000 + H2
    and #$003F
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta f:$7E0000 + PTRTMP
    asl a
    asl a
    asl a
    sec
    sbc f:$7E0000 + PTRTMP
    sta f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_ab_base)
    sta f:$7E0000 + B2_AB_PTR   ; band 2 AB
    lda f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_cd_base)
    sta f:$7E0000 + B2_CD_PTR   ; band 2 CD
.if POSES = 256
    jsr stamp_pose_banks        ; the four $43x7 DASB bytes, same VBlank window
.endif
.endif
    jsr stamp_origins

.ifdef RETARGET
    ; --- heading retarget smoke: at frame 90, band 2 -> the 45-degree pose from
    ;     the 64-angle shipping set. ONE pointer per channel, in VBlank. --------
    lda f:G_FRAMES
    cmp #90
    bne @no_flip
    lda #.loword(pose_rot45_ab)
    sta f:$7E0000 + B2_AB_PTR
    lda #.loword(pose_rot45_cd)
    sta f:$7E0000 + B2_CD_PTR
@no_flip:
.endif

.ifdef LATCH_VIOLATION
    ; --- NEGATIVE CONTROL: write-twice M7HOFS mid-display with BAND-1's channel
    ;     value (pure latch-interleave in band 1 — the band the test measures;
    ;     in band 2 the same spin is additionally a value stomp, outside the
    ;     metric window). Spans well past VBlank into active display -> tears. --
    ldx #2000
    sep #$20
    .a8
@latch_spin:
    lda f:$7E0000 + HOFS1_MIR + 0
    sta $210D
    lda f:$7E0000 + HOFS1_MIR + 1
    sta $210D
    dex
    bne @latch_spin
    rep #$20
    .a16
.endif
    jmp game_loop

; =============================================================================
; stamp_origins — write both bands' origin values into the HDMA tables.
; Fixed-heading origin math is pure subtraction (no engine solve):
;   band N: M7X = posNx, M7Y = posNy, HOFS = posNx - 128,
;           VOFS = posNy - band_bottom  (band 1 bottom = line 112, band 2 = 224)
; Caller guarantees the VBlank window (or forced blank at boot).
; WIDTH-RISK: runs entirely in 16-bit accumulator/index mode and leaves it that
; way, so a 16-bit caller needs no width change around the call. Long
; addressing throughout (no data-bank dependency). Clobbers A.
; =============================================================================
stamp_origins:
    .a16
    .i16
    ; --- band 1: XY slot (OTBL_XY+1..4), HV slot (OTBL_HV+1..4) ---
    lda f:$7E0000 + POS1X
    sta f:$7E0000 + OTBL_XY + 1     ; M7X (band 1)
    sec
    sbc #128
    sta f:$7E0000 + OTBL_HV + 1     ; HOFS = posx - 128
    sta f:$7E0000 + HOFS1_MIR       ; latch-model mirror (same value HDMA sends)
    lda f:$7E0000 + POS1Y
    sta f:$7E0000 + OTBL_XY + 3     ; M7Y (band 1)
    sec
    sbc #SEAM
    sta f:$7E0000 + OTBL_HV + 3     ; VOFS = posy - 112 (band-1 bottom line)
    ; --- band 2: XY slot (OTBL_XY+6..9), HV slot (OTBL_HV+6..9) ---
    lda f:$7E0000 + POS2X
    sta f:$7E0000 + OTBL_XY + 6
    sec
    sbc #128
    sta f:$7E0000 + OTBL_HV + 6
    lda f:$7E0000 + POS2Y
    sta f:$7E0000 + OTBL_XY + 8
    sec
    sbc #224
    sta f:$7E0000 + OTBL_HV + 8     ; VOFS = posy - 224 (band-2 bottom line)
    rts

; =============================================================================
; split_mask — split a 2-channel allocator mask into its two single-bit masks.
; In:  A16 = mask (two bits set among bits 2..7)
; Out: API_BLOCK_BASE+8 = full mask, +10 = lowest bit, +12 = the other bit.
; WIDTH-RISK: 16-bit accumulator/index the whole way in and out — no width
; change for a 16-bit caller. Clobbers A.
; =============================================================================
split_mask:
    .a16
    .i16
    and #$00FF
    sta API_BLOCK_BASE + 8
    eor #$FFFF
    inc a
    and API_BLOCK_BASE + 8          ; A = lowest set bit
    sta API_BLOCK_BASE + 10
    eor API_BLOCK_BASE + 8          ; the remaining bit
    sta API_BLOCK_BASE + 12
    rts

; =============================================================================
; set_indirect_banks — write $43x7 (indirect DATA bank) for both MATRIX channels.
; hdma_bind_direct programs DMAP/BBAD/A1T only; indirect mode ALSO needs DASB =
; the bank the per-line pose bytes are fetched from. Forced blank at call time.
; In: API_BLOCK_BASE+10/+12 = the two single-bit channel masks (from split_mask);
;     API_BLOCK_BASE+14/+15 = the AB / CD channels' data banks (caller-set:
;     the default build's poses sit in the code bank; -DROTATE's 64-pose blobs
;     sit in BANK2 / BANK3 — one bank per channel, $43x7 is per-channel).
; WIDTH-RISK: enters and exits in 16-bit mode; the only 8-bit windows are the
; single-byte DASB stores, each wrapped in a balanced sep/rep. Clobbers A, X.
; =============================================================================
set_indirect_banks:
    .a16
    .i16
    ldx #$0000                      ; X = channel reg base ($00,$10,..,$70)
    lda #$0001                      ; A = walking channel bit
@walk:
    bit API_BLOCK_BASE + 10
    bne @set_ab
    bit API_BLOCK_BASE + 12
    bne @set_cd
    bra @next
@set_ab:
    pha
    sep #$20
    .a8
    lda API_BLOCK_BASE + 14         ; AB-channel data bank
    sta a:$4307, x                  ; DASBx
    rep #$20
    .a16
    pla
    bra @next
@set_cd:
    pha
    sep #$20
    .a8
    lda API_BLOCK_BASE + 15         ; CD-channel data bank
    sta a:$4307, x
    rep #$20
    .a16
    pla
@next:
    asl a
    pha
    txa
    clc
    adc #$0010
    tax
    pla
    cmp #$0100                      ; walked CH0..CH7
    bcc @walk
    rts

; =============================================================================
; bind_matrix_pair — allocate + bind ONE indirect-mode matrix channel pair.
; In (WRAM args): MP_IDXAB/MP_IDXCD = the pair's index-table lowords (bank $7E);
;                 MP_BANKAB/MP_BANKCD = the channels' indirect data banks (DASB);
;                 MP_FX = allocator effect tag.
; Out: MP_MSK = the pair's channel mask (0 if the request failed — fail-soft);
;      MP_CHXAB/MP_CHXCD = the channels' register offsets (ch * $10) for later
;      per-frame DASB stamping ($4307 + chx).
; AB lands on the pair's LOWER channel (split_mask low bit), CD on the higher.
; WIDTH-RISK: 16-bit in and out; it drops to 8-bit only to stage single bytes
; (bank/DMAP fields) and every such window has a matched sep/rep. Clobbers A, X.
; =============================================================================
bind_matrix_pair:
    .a16
    .i16
    lda f:$7E0000 + MP_FX
    tax                         ; A16/I16: full 16-bit transfer
    lda #$0002
    jsr hdma_request
    sta f:$7E0000 + MP_MSK
    bcc :+
    rts                         ; fail-soft: boot without the effect
:
    jsr split_mask              ; -> API+10 = low bit (AB), API+12 = high (CD)
    sep #$20
    .a8
    lda f:$7E0000 + MP_IDXAB + 0
    sta API_BLOCK_BASE + 0
    lda f:$7E0000 + MP_IDXAB + 1
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2      ; index tables live in WRAM
    lda #$43
    sta API_BLOCK_BASE + 3      ; DMAP: INDIRECT + write-2-registers-twice
    rep #$20
    .a16
    lda API_BLOCK_BASE + 10
    ldx #$001B                  ; BBAD = M7A/M7B
    jsr hdma_bind_direct
    sep #$20
    .a8
    lda f:$7E0000 + MP_IDXCD + 0
    sta API_BLOCK_BASE + 0
    lda f:$7E0000 + MP_IDXCD + 1
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$43
    sta API_BLOCK_BASE + 3
    rep #$20
    .a16
    lda API_BLOCK_BASE + 12
    ldx #$001D                  ; BBAD = M7C/M7D
    jsr hdma_bind_direct
    ; $43x7 (DASB) per channel — the ONE register hdma_bind_direct does not
    ; cover. API+14 = AB-channel bank, +15 = CD's.
    sep #$20
    .a8
    lda f:$7E0000 + MP_BANKAB
    sta API_BLOCK_BASE + 14
    lda f:$7E0000 + MP_BANKCD
    sta API_BLOCK_BASE + 15
    rep #$20
    .a16
    jsr set_indirect_banks
    ; channel register offsets (ch * $10) — the per-frame DASB stamper's homes
    ; (split_mask's outputs survive the binds: +10/+12 are not scratched).
    lda API_BLOCK_BASE + 10
    jsr mask_to_chx
    sta f:$7E0000 + MP_CHXAB
    lda API_BLOCK_BASE + 12
    jsr mask_to_chx
    sta f:$7E0000 + MP_CHXCD
    rts

; =============================================================================
; mask_to_chx — derive a channel's register offset from its single-bit mask.
; In:  A16 = single-bit channel mask (exactly one of bits 0..7 set)
; Out: A16 = channel index * $10 (the $43x0 register block offset)
; WIDTH-RISK: 16-bit accumulator/index the whole way — no width change for a
; 16-bit caller. Clobbers A, X.
; =============================================================================
mask_to_chx:
    .a16
    .i16
    ldx #$0000
@shift:
    lsr a
    bcs @done
    pha
    txa
    clc
    adc #$0010
    tax
    pla
    bra @shift
@done:
    .a16
    txa
    rts

.ifdef PERBAND
; =============================================================================
; bind_band1_pair / bind_band2_pair — the two per-band matrix pair binds.
; Allocation ORDER is the caller's contract (band 2 FIRST = lower channels;
; see the channel-priority comment at the call site). Each stages its own
; index tables, data banks + effect tag, then delegates to bind_matrix_pair
; and records its mask (G_MSK3 = band 1, G_MSK = band 2) and channel offsets.
; WIDTH-RISK: 16-bit in and out; the only 8-bit windows stage single bank
; bytes and each has a matched sep/rep. Clobbers A, X.
; =============================================================================
bind_band1_pair:
    .a16
    .i16
    sep #$20
    .a8
.ifndef ROTATE
    lda #^poses1_ab
    sta f:$7E0000 + MP_BANKAB
    lda #^poses1_cd
    sta f:$7E0000 + MP_BANKCD
.else
    lda #^pose_ab_base          ; slice-0 bank (h1 boots 0; POSES=256 re-stamps
    sta f:$7E0000 + MP_BANKAB   ; all four banks per frame via stamp_pose_banks)
    lda #^pose_cd_base
    sta f:$7E0000 + MP_BANKCD
.endif
    rep #$20
    .a16
    lda #IDX_AB
    sta f:$7E0000 + MP_IDXAB
    lda #IDX_CD
    sta f:$7E0000 + MP_IDXCD
    lda #FX_M7_MATRIX
    sta f:$7E0000 + MP_FX
    jsr bind_matrix_pair
    lda f:$7E0000 + MP_MSK
    sta f:G_MSK3
    lda f:$7E0000 + MP_CHXAB
    sta f:$7E0000 + CHX_AB1
    lda f:$7E0000 + MP_CHXCD
    sta f:$7E0000 + CHX_CD1
    rts

; WIDTH-RISK: 16-bit in and out; single-byte bank stages each carry a matched
; sep/rep. Clobbers A, X.
bind_band2_pair:
    .a16
    .i16
    sep #$20
    .a8
.ifndef ROTATE
    lda #^poses1_ab
    sta f:$7E0000 + MP_BANKAB
    lda #^poses1_cd
    sta f:$7E0000 + MP_BANKCD
.else
    lda #^pose_ab_base          ; slice-0 placeholder; the boot-time
    sta f:$7E0000 + MP_BANKAB   ; stamp_pose_banks call fixes band 2's slice
    lda #^pose_cd_base          ; (h2 boots 128 = slice 2 at POSES=256)
    sta f:$7E0000 + MP_BANKCD
.endif
    rep #$20
    .a16
    lda #IDX_AB2
    sta f:$7E0000 + MP_IDXAB
    lda #IDX_CD2
    sta f:$7E0000 + MP_IDXCD
    lda #FX_M7_MATRIX2
    sta f:$7E0000 + MP_FX
    jsr bind_matrix_pair
    lda f:$7E0000 + MP_MSK
    sta f:G_MSK
    lda f:$7E0000 + MP_CHXAB
    sta f:$7E0000 + CHX_AB2
    lda f:$7E0000 + MP_CHXCD
    sta f:$7E0000 + CHX_CD2
    rts
.endif

.if POSES = 256
; =============================================================================
; stamp_pose_banks — write both bands' FOUR indirect data banks ($43x7) from
; the current headings: bank = blob_base_bank + (h >> 6) (slice of 64 poses;
; both bands' AB channels share the same blob banks — independent DASB values
; into shared ROM data). Caller guarantees the VBlank window (or forced blank
; at boot). Mirrors the four stamped banks to G_BANKS+0..3 (AB1, CD1, AB2,
; CD2) so the test suite can read what the hardware was given.
; WIDTH-RISK: 16-bit in and out; 8-bit only for the single-byte DASB stores,
; each in a balanced sep/rep. The 16-bit `tax` sites carry channel offsets
; (ch*$10 <= $70), so the accumulator high byte is always clean — no stale
; high byte can leak into the index register. Clobbers A, X.
; =============================================================================
stamp_pose_banks:
    .a16
    .i16
    lda f:$7E0000 + H1
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                       ; slice index = h1 >> 6 (0..3)
    sta f:$7E0000 + PTRTMP
    lda f:$7E0000 + CHX_AB1
    tax                         ; X = band-1 AB channel offset (ch * $10)
    lda f:$7E0000 + PTRTMP
    clc
    adc #^poses256_ab_s0        ; AB blob base bank
    sep #$20
    .a8
    sta a:$4307, x              ; DASB (band-1 AB)
    sta f:G_BANKS + 0
    rep #$20
    .a16
    lda f:$7E0000 + CHX_CD1
    tax
    lda f:$7E0000 + PTRTMP
    clc
    adc #^poses256_cd_s0        ; CD blob base bank
    sep #$20
    .a8
    sta a:$4307, x              ; DASB (band-1 CD)
    sta f:G_BANKS + 1
    rep #$20
    .a16
    lda f:$7E0000 + H2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                       ; slice index = h2 >> 6 (0..3)
    sta f:$7E0000 + PTRTMP
    lda f:$7E0000 + CHX_AB2
    tax
    lda f:$7E0000 + PTRTMP
    clc
    adc #^poses256_ab_s0
    sep #$20
    .a8
    sta a:$4307, x              ; DASB (band-2 AB)
    sta f:G_BANKS + 2
    rep #$20
    .a16
    lda f:$7E0000 + CHX_CD2
    tax
    lda f:$7E0000 + PTRTMP
    clc
    adc #^poses256_cd_s0
    sep #$20
    .a8
    sta a:$4307, x              ; DASB (band-2 CD)
    sta f:G_BANKS + 3
    rep #$20
    .a16
    rts
.endif

; =============================================================================
.ifdef SPRITES
.include "sprites_2p.inc"       ; sprite stress rail (players + AI + tiers)
.endif
.ifdef SF_AUDIO
.include "tad_bridge.asm"       ; TAD bridge implementation (showcase build)
.endif
.include "hdma_alloc.asm"

; --- ROM-resident pose tables (the indirect DATA the matrix channels fetch) ---
.segment "RODATA"
poses1_ab:    .incbin "assets/poses1_ab.bin"      ; fixed-angle pose (--angles 1)
poses1_cd:    .incbin "assets/poses1_cd.bin"
pose_rot45_ab: .incbin "assets/pose_rot45_ab.bin" ; 64-set index 8 (45 degrees)
pose_rot45_cd: .incbin "assets/pose_rot45_cd.bin"
.ifdef ROTATE
.if POSES = 64
move_lut:     .incbin "assets/move64.bin"         ; 64 x (dx,dy) forward vectors
.else
move_lut:     .incbin "assets/move256.bin"        ; 256 x (dx,dy) forward vectors
.endif
.endif

.segment "BANK1"
checker_map:
    .incbin "assets/checker_map.bin"

.ifdef ROTATE
.if POSES = 64
; --- the 64-pose single-bank set: one exact 32KB LoROM bank per blob,
;     one bank per channel ($43x7 is per-channel). lorom_stream.cfg link. ----
.segment "BANK2"
poses64_ab:   .incbin "assets/poses64_ab.bin"
.segment "BANK3"
poses64_cd:   .incbin "assets/poses64_cd.bin"
.else
; --- the 256-pose rotate-default set: 4 bank slices per blob (64 poses x
;     448 B = 28,672 B per slice); pose (64k + j) lives in slice k at loword
;     $8000 + j*448. Both bands' AB channels fetch from these shared banks —
;     per-band $43x7 DASB values select each band's slice independently. ----
.segment "BANK2"
poses256_ab_s0: .incbin "assets/poses256_ab.bin", 0 * 28672, 28672
.segment "BANK3"
poses256_ab_s1: .incbin "assets/poses256_ab.bin", 1 * 28672, 28672
.segment "BANK4"
poses256_ab_s2: .incbin "assets/poses256_ab.bin", 2 * 28672, 28672
.segment "BANK5"
poses256_ab_s3: .incbin "assets/poses256_ab.bin", 3 * 28672, 28672
.segment "BANK6"
poses256_cd_s0: .incbin "assets/poses256_cd.bin", 0 * 28672, 28672
.segment "BANK7"
poses256_cd_s1: .incbin "assets/poses256_cd.bin", 1 * 28672, 28672
.segment "BANK8"
poses256_cd_s2: .incbin "assets/poses256_cd.bin", 2 * 28672, 28672
.segment "BANK9"
poses256_cd_s3: .incbin "assets/poses256_cd.bin", 3 * 28672, 28672
.endif
.endif
