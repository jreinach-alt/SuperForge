; =============================================================================
; engine_state.inc — Engine WRAM Layout for NMI, DMA, Input, Sprites
; =============================================================================
; Include guard: this .inc is `.include`-d both by a parent ROM's
; generated template AND by standalone-compiled engine units (e.g.
; engine/streaming_engine.asm, when assembled separately for the Sprint A/B
; test ROMs). When both are linked together, ca65 sees duplicate equates
; without this guard. Added Sprint B2 to enable .include of the streaming
; engine into the native template.
.ifndef _ENGINE_STATE_INC_INCLUDED
_ENGINE_STATE_INC_INCLUDED = 1
; Defines all fixed WRAM addresses used by the engine runtime.
;
; The NMI handler sets DP=$0100 at entry, so engine state variables at
; $0100-$01BF are accessible via fast DP-relative addressing during NMI.
; The main thread (DP=$0000) accesses engine state via absolute addressing.
;
; This avoids all conflicts with the game register file (DP $00-$3F)
; and engine-call scratch (DP $A0-$B7).
;
; Memory map:
;   $0000-$00FF  Direct Page (game registers R0-R127, API block $40-$9F)
;   $0100-$013F  Engine state (NMI DP-relative: DMA, joy, frame, sprites)
;   $0200-$02FF  DMA queue (32 entries x 8 bytes)
;   $0300-$04FF  Shadow OAM low table (128 sprites x 4 bytes = 512 bytes)
;   $0500-$051F  Shadow OAM high table (128 sprites x 2 bits = 32 bytes)
;   $0540-$055F  DMA staging area + scratch ($0548-$054E stage, $0550-$0555 scratch)
;   $0560-$056F  Sprite engine scratch
;   $0570-$1FFF  CPU stack (~6.75 KB, grows down from $1FFF)
;   $2000-$9FFF  Reserved program area (parent engine contract)
;   $A000-$BFFF  Engine heap / tables
;   $E000-$EFFF  Debug region (4 KB, accessed via long addressing f:$7EE000+)
;
; Key constants:
;   ENGINE_STATE_BASE = $0100    DMA_QUEUE_BASE     = $0200
;   SHADOW_OAM_BASE   = $0300   SHADOW_OAM_HI      = $0500
;   SHADOW_OAM_TOTAL  = 544     VBLANK_DMA_BUDGET   = 5500
;   SPRITE_COUNT (abs) = $0130  OAM_DIRTY (abs)     = $0132
;   STACK_TOP          = $1FFF
;
; Free DP bytes available for live-engine allocation:
;   $0E-$13 (6 bytes)  — former STAT5_DMA_REM/STAT7_DROPS/STAT0_CPU_PCT
;                        (PR #59 relocated to $7E:E100..E105).
;                        NOTE: $10-$15 is used as transient main-thread VWF
;                        scratch by engine/text_engine.asm — NOT free for
;                        persistent state. $0E-$0F alone is unclaimed but
;                        adjacent to text_engine scratch; verify before use.
;   $36-$39 (4 bytes)  — CLAIMED by Phase 16-6-0 remediation for bright_fade
;                        (ES_BRIGHT_FADE_TARGET/STEP_FRAC/FRAMES/DIRECTION).
;                        Was former SPR_SCANLINE_PK/EN + part of ES_RESERVED_39
;                        (PR #59 relocated to $7E:E106..E108).
;   $3A-$3B (2 bytes)  — remaining free from former sprite scanline state
;                        (PR #59 relocated to $7E:E108).
;   $3D     (1 byte)   — former ES_GFXMODE (PR #59 relocated to $7E:E109)
;   $3F     (1 byte)   — former ES_RESERVED_3F2 (commit 03948a6)
;   $77     (1 byte)   — former ES_FADE_RESERVED; used as transient scratch
;                        by engine/mode_split_hdma.asm — NOT free for
;                        persistent state. Documented as scratch-claim.
;   $89-$9E (14 bytes) — former pre-Phase-16 Mode 7 state block
;   $A3-$A6 (4 bytes)  — FREE (previously claimed by Phase 16-6-0 for
;                        bright_fade; remediated 2026-05-13 to $36-$39
;                        because $A0-$A6 is the "engine scratch" zone
;                        per CLAUDE.md and conflicted with mode5_text,
;                        streaming_engine, and text_engine transient
;                        scratch).
;   $AF-$B0 (2 bytes)  — former ES_SCENE_RESERVED; $B0 used as transient
;                        scratch by handlers_engine.asm atan2 path —
;                        NOT free for persistent state.
;   $B6     (1 byte)   — former ES_OFFSET_RESERVED; used as transient
;                        scratch by handlers_engine.asm atan2 path —
;                        NOT free for persistent state.
;   Total: 36 bytes across three audits (03948a6 + 088396e + Phase-16 M7 fork).
;   See detailed allocation notes at each "; free" block.
;   Legacy symbols for the $89-$A6 addresses live in engine_state_m7_legacy.inc
;   (pulled only by the frozen pre-Phase-16 Mode 7 engine and 3 Phase 16
;   DT-001 live-path test ROMs that embed their own legacy NMI handlers).
;
; Cross-ref: dispatch.asm (DP=$0000 layout), superforge_nmi_handler_v0.1.md
; =============================================================================

.p816
.smart

; === Engine State DP Base ===
; NMI handler sets DP to this value for fast access to engine variables.
ENGINE_STATE_BASE = $0100

; === Engine State Variables (DP-relative offsets from $0100) ===
; When NMI handler has DP=$0100, these are DP offsets.
; When main thread has DP=$0000, use absolute address ENGINE_STATE_BASE + offset.

; --- DMA Scheduler State ($00-$09) ---
ES_DMA_QUEUE_PTR    = $00   ; 2 bytes: pointer to DMA queue base in WRAM
ES_DMA_QUEUE_COUNT  = $02   ; 2 bytes: number of entries currently in queue
ES_DMA_BUDGET       = $04   ; 2 bytes: configured VBlank byte budget (default 5500)
ES_BYTES_REMAINING  = $06   ; 2 bytes: remaining budget during NMI execution
ES_HDMA_ENABLE_MASK = $08   ; 1 byte:  bitmask of active HDMA channels (bits 0-3)
ES_DMA_QUEUE_READY  = $09   ; 1 byte:  main thread sets 1 when DMA queue is built

; --- Frame Synchronization ($0A-$0F) ---
ES_NMI_DONE_FLAG    = $0A   ; 1 byte:  NMI handler sets 1 at exit; main thread clears
ES_FRAME_PHASE      = $0B   ; 1 byte:  current frame phase (0=WAIT..4=RESOLVE)
ES_FRAME_COUNTER    = $0C   ; 2 bytes: global frame counter (incremented by NMI)
; $0E-$13: 6 bytes free (was ES_STAT5_DMA_REM + ES_STAT7_DROPS + ES_STAT0_CPU_PCT;
; relocated to WRAM extended at $7E:E100, $7E:E102, $7E:E104 per the "only
; spend engine DP when strictly required" discipline — diagnostic-only,
; written by NMI/frame_lifecycle but only read by debug_overlay and tests).

; --- Controller State ($14-$1F) ---
ES_JOY1_CURRENT     = $14   ; 2 bytes: P1 current frame button state
ES_JOY1_PREVIOUS    = $16   ; 2 bytes: P1 previous frame button state
ES_JOY1_PRESSED     = $18   ; 2 bytes: P1 rising edge accumulator (NMI writes via ORA)
ES_JOY2_CURRENT     = $1A   ; 2 bytes: P2 current frame button state
ES_JOY2_PREVIOUS    = $1C   ; 2 bytes: P2 previous frame button state
ES_JOY2_PRESSED     = $1E   ; 2 bytes: P2 rising edge accumulator (NMI writes via ORA)

; --- Shadow PPU Registers ($20-$2F) ---
ES_SHADOW_BG1HOFS   = $20   ; 2 bytes: BG1 horizontal scroll
ES_SHADOW_BG1VOFS   = $22   ; 2 bytes: BG1 vertical scroll
ES_SHADOW_BG2HOFS   = $24   ; 2 bytes: BG2 horizontal scroll
ES_SHADOW_BG2VOFS   = $26   ; 2 bytes: BG2 vertical scroll
ES_SHADOW_BG3HOFS   = $28   ; 2 bytes: BG3 horizontal scroll
ES_SHADOW_BG3VOFS   = $2A   ; 2 bytes: BG3 vertical scroll
ES_SHADOW_BGMODE    = $2C   ; 1 byte:  BGMODE register shadow
ES_SHADOW_MOSAIC    = $2D   ; 1 byte:  MOSAIC register shadow
ES_SHADOW_INIDISP   = $2E   ; 1 byte:  INIDISP register shadow (brightness + blank)
ES_SHADOW_TM        = $2F   ; 1 byte:  TM (main screen designation) shadow

; --- Sprite Engine State ($30-$3B) ---
ES_SPRITE_COUNT     = $30   ; 2 bytes: current active sprite count
ES_OAM_DIRTY        = $32   ; 1 byte:  1 = shadow OAM needs DMA transfer
ES_SPR_ORDER_MODE   = $33   ; 1 byte:  0=priority, 1=y_sort, 2=stable
ES_SPR_FLICKER_EN   = $34   ; 1 byte:  0=off, 1=on (OAM rotation flicker)
ES_SPR_FLICKER_OFF  = $35   ; 1 byte:  rotation counter 0-127

; --- Brightness Fade State ($36-$39) — Phase 16-6-0 (remediation 2026-05-13) ---
; Per-frame INIDISP brightness stepper, symmetric with the volume fade
; pair at $74-$77. The engine function `bright_fade(target, frames)` (engine
; ID 100) stages a target brightness (0..15) and a frame count, and the
; stepper at SIGNAL phase advances SHADOW_INIDISP one step toward the
; target each frame. The forced-blank bit ($80) is preserved.
;
; Layout:
;   $36  ES_BRIGHT_FADE_TARGET    1 B  target brightness (0..15)
;   $37  ES_BRIGHT_FADE_STEP_FRAC 1 B  countdown of "frames to wait between
;                                       brightness ticks". Reloaded after
;                                       each brightness step from
;                                       max(remaining_frames /
;                                           remaining_distance, 1).
;   $38  ES_BRIGHT_FADE_FRAMES    1 B  frames remaining (0 = inactive).
;                                       Decremented every frame the fade
;                                       is active; when 0 the stepper
;                                       clamps SHADOW_INIDISP to target.
;   $39  ES_BRIGHT_FADE_DIRECTION 1 B  0 = fading down, 1 = fading up
;
; Allocation history: originally claimed $A3-$A6 in the M1/M2 implementation
; (sprint phase_16_6_0_bright_fade). Audit-1 of PR #165 flagged a collision
; with mode5_text_engine's scratch at $A0-$A3; further investigation showed
; that $A0-$AF is the "engine scratch" zone per CLAUDE.md, shared by
; text_engine ($A0-$A2 TEXT_SCRATCH_LONGPTR), mode5_text_engine
; ($A0-$A3), streaming_engine ($A0-$AC), and the Mode 7 HDMA legacy
; ($A1-$AD). Bright-fade state is persistent across frames and must NOT
; live in the transient scratch zone. Remediation 2026-05-13 moved it to
; $36-$39, a verified-free 4-byte block (former ES_SPR_SCANLINE_PK/EN +
; first byte of ES_RESERVED_39; relocated to WRAM extended in PR #59).
; $36-$39 is grep-clean across the engine sources; not shadowed
; by engine_state_m7_legacy.inc.
ES_BRIGHT_FADE_TARGET    = $36
ES_BRIGHT_FADE_STEP_FRAC = $37
ES_BRIGHT_FADE_FRAMES    = $38
ES_BRIGHT_FADE_DIRECTION = $39

; $3A-$3B: 2 bytes free (remaining from former ES_RESERVED_39 at $39-$3B,
; commit 03948a6). SPR_SCANLINE_PEAK relocated to WRAM extended $7E:E106
; and SPR_SCANLINE_DETECT_EN relocated to $7E:E108 per the "only spend
; engine DP when strictly required" discipline.

; --- BG Engine State ($3C-$3F) ---
ES_BG_TILEMAP_DIRTY = $3C   ; 1 byte: bitmask of dirty layers (bit0=BG1, bit1=BG2, bit2=BG3)
; $3D: NMITIMEN ($4200) compose shadow (seam-IRQ opt-in, 2026-07-03; the
; byte was free — former ES_GFXMODE, relocated to WRAM extended $7E:E109).
; $4200 is WRITE-ONLY and SHARED (bit 7 NMI, bits 5/4 V-/H-count IRQ,
; bit 0 auto-joypad): every writer must OR/AND its bits into this shadow
; and store the shadow — never blind-store $4200 (the auto-joypad and
; seam-IRQ owners would stomp each other). Coldstart WRAM clear zeroes it;
; consumers: lib/macros (kit) sf_irq.inc sf_nmitimen_or/sf_nmitimen_and,
; header.inc "OPT-IN IRQ VECTOR" note.
ES_SHADOW_NMITIMEN  = $3D   ; 1 byte:  NMITIMEN register shadow (compose, then store)
ES_BG_SHADOW_DIRTY  = $3E   ; 1 byte: 1=shadow PPU regs need commit during VBlank
; Phase 17 Sprint D-5 (Bug A fix): BG2 tilemap VRAM destination high byte.
; The NMI BG2-tilemap DMA used to hardcode VRAM word $5C00 (= "$5C" as the
; high byte). When BG1 is in 64×32 streaming mode (BG1SC=$59), BG1 page 1
; occupies VRAM word $5C00-$5FFF and the static-mode BG2 DMA destination
; aliases BG1's streamed columns 32..63 — producing ghost platforms in the
; sky. The streaming-mode boot now overrides this byte to $48 so BG2's
; tilemap lands at VRAM word $4800-$4BFF (1KB, 32×32, no overlap with
; either BG1 streaming page or BG2 chr at $4000-$47FF).
; Defaults to $5C at engine init for static-mode ROMs.
ES_BG2_TILEMAP_VRAM_HI = $3F   ; 1 byte: high byte of BG2 tilemap VRAM word addr

; --- Palette Engine State ($40-$43) ---
ES_CGRAM_DIRTY_LO    = $40   ; 1 byte: lowest dirty CGRAM entry index (0-255)
ES_CGRAM_DIRTY_HI    = $41   ; 1 byte: highest dirty CGRAM entry index (0-255)
ES_CGRAM_DIRTY_FLAG  = $42   ; 1 byte: 1 = CGRAM needs DMA transfer
ES_PAL_CYCLE_COUNT   = $43   ; 1 byte: number of active palette cycles (0-4)

; --- Color Math Engine State ($44-$4B) ---
ES_SHADOW_TS         = $44   ; 1 byte: sub screen designation ($212D)
ES_SHADOW_CGWSEL     = $45   ; 1 byte: color math control ($2130)
ES_SHADOW_CGADSUB    = $46   ; 1 byte: color addition/subtraction ($2131)
ES_SHADOW_COLDATA_R  = $47   ; 1 byte: fixed color red (0-31)
ES_SHADOW_COLDATA_G  = $48   ; 1 byte: fixed color green (0-31)
ES_SHADOW_COLDATA_B  = $49   ; 1 byte: fixed color blue (0-31)
ES_BLEND_DIRTY       = $4A   ; 1 byte: 1 = color math registers need commit
ES_TINT_ACTIVE       = $4B   ; 1 byte: 1 = tint is active

; --- Text Engine State ($4C-$4F) ---
ES_FONT_BASE_TILE    = $4C   ; 2 bytes: tile index where font starts in tileset
ES_FONT_LOADED       = $4E   ; 1 byte: 1 = font tiles loaded to VRAM
ES_VWF_ACTIVE        = $4F   ; 1 byte: 0=monospace, 1=VWF mode (repurposed TEXT_DIRTY)
                             ; Set by engine_font_select based on font manifest flags

; --- HDMA Effects Engine State ($50-$69) ---
; Phase 17-0b1: $50-$51 were the Phase 4 allocator's tracking bytes
; (HDMA_ALLOC + HDMA_EFFECT_CNT). The Phase 17-0a allocator at
; `engine/hdma_alloc.asm` is now the single source of truth — its state
; lives at $7E:C800+ in high WRAM. Slot $50 was reclaimed in Phase
; 17-13 for M7_OWNED_MASK (the ownership-aware NMI commit gate). Slot
; $51 stays reserved.
ES_M7_OWNED_MASK    = $50   ; 1 byte: HDMA channels owned by Mode 7
                            ; (read by NMI Phase 5 to gate per-channel
                            ; shadow→hardware commit). Public symbol:
                            ; M7_OWNED_MASK at the wrapper section below.
ES_HDMA_RESERVED_51 = $51   ; 1 byte: reclaimable (was HDMA_EFFECT_CNT)

; Per-channel HDMA configuration (read by NMI Phase 5)
; Each channel: [DMAP, BBAD, table_lo, table_hi] = 4 bytes
ES_HDMA_CH3_DMAP    = $52   ; 1 byte
ES_HDMA_CH3_BBAD    = $53   ; 1 byte
ES_HDMA_CH3_TBL_LO  = $54   ; 1 byte
ES_HDMA_CH3_TBL_HI  = $55   ; 1 byte

ES_HDMA_CH4_DMAP    = $56
ES_HDMA_CH4_BBAD    = $57
ES_HDMA_CH4_TBL_LO  = $58
ES_HDMA_CH4_TBL_HI  = $59

ES_HDMA_CH5_DMAP    = $5A
ES_HDMA_CH5_BBAD    = $5B
ES_HDMA_CH5_TBL_LO  = $5C
ES_HDMA_CH5_TBL_HI  = $5D

ES_HDMA_CH6_DMAP    = $5E
ES_HDMA_CH6_BBAD    = $5F
ES_HDMA_CH6_TBL_LO  = $60
ES_HDMA_CH6_TBL_HI  = $61

ES_HDMA_CH7_DMAP    = $62
ES_HDMA_CH7_BBAD    = $63
ES_HDMA_CH7_TBL_LO  = $64
ES_HDMA_CH7_TBL_HI  = $65

; Wave effect animation state
ES_HDMA_WAVE_PHASE  = $66   ; 2 bytes: current wave phase (16-bit, auto-incremented)
ES_HDMA_WAVE_SPEED  = $68   ; 2 bytes: phase increment per frame

; --- TAD Audio Bridge State ($6A-$77) ---
ES_TAD_STATUS       = $6A   ; 1 byte:  last TAD status ($00=ready, $01=playing, $02=loading, $FF=error)
ES_TAD_SEQ_CTR      = $6B   ; 1 byte:  sequence counter for handshake
ES_TAD_SONG_ID      = $6C   ; 1 byte:  current song ID ($FF = none)
ES_TAD_VOLUME       = $6D   ; 1 byte:  music volume (0-127)
ES_TAD_SFX_MASK     = $6E   ; 1 byte:  active SFX bitmask (bit0=ch0, bit1=ch1)
ES_TAD_PAUSED       = $6F   ; 1 byte:  1 = music paused
ES_TAD_QUEUE_CMD    = $70   ; 1 byte:  queued command ($00 = none)
ES_TAD_QUEUE_P1     = $71   ; 1 byte:  queued param 1
ES_TAD_QUEUE_P2     = $72   ; 1 byte:  queued param 2
ES_TAD_READY        = $73   ; 1 byte:  1 = TAD driver loaded and ready

; --- Volume Fade State ($74-$77) ---
ES_FADE_TARGET      = $74   ; 1 byte:  target volume (0-127)
ES_FADE_SPEED       = $75   ; 1 byte:  volume change per frame (1-127, 0=inactive)
ES_FADE_DIRECTION   = $76   ; 1 byte:  0=fading down, 1=fading up
; $77: 1 byte free (was ES_FADE_RESERVED; reclaimed after audit — no callers).

; --- Coroutine Engine State ($78-$81) ---
ES_CO_POOL_BASE     = $78   ; 2 bytes: pointer to coroutine pool base ($D400)
ES_CO_ACTIVE_COUNT  = $7A   ; 1 byte: number of non-FREE slots (stat(13))
ES_CO_AUTO_RESUME_N = $7B   ; 1 byte: number of auto-resume slots
ES_CO_CURRENT_SLOT  = $7C   ; 1 byte: currently running slot index ($FF=none)
ES_CO_CALLER_PC     = $7D   ; 2 bytes: saved caller PC for resume return
ES_CO_CALLER_SP     = $7F   ; 2 bytes: saved caller SP_BC for resume return
ES_CO_CALLER_REGS   = $81   ; 1 byte: marker — actual caller register storage at CO_CALLER_SAVE_AREA

; --- Window Masking State ($82-$89) ---
; Used by iris() HDMA effect and clip() to control SNES hardware windowing.
; Default: all zeros (windows disabled). iris() sets these; hdma_off() clears.
ES_SHADOW_W12SEL    = $82   ; 1 byte: W12SEL ($2123) — Window 1/2 enable for BG1/BG2
ES_SHADOW_W34SEL    = $83   ; 1 byte: W34SEL ($2124) — Window 1/2 enable for BG3/BG4
ES_SHADOW_WOBJSEL   = $84   ; 1 byte: WOBJSEL ($2125) — Window 1/2 enable for OBJ/Color
ES_SHADOW_WBGLOG    = $85   ; 1 byte: WBGLOG ($212A) — BG window mask logic
ES_SHADOW_WOBJLOG   = $86   ; 1 byte: WOBJLOG ($212B) — OBJ/Color window mask logic
ES_SHADOW_TMW       = $87   ; 1 byte: TMW ($212E) — Main screen window mask designation
ES_SHADOW_TSW       = $88   ; 1 byte: TSW ($212F) — Sub screen window mask designation

; =============================================================================
; FREE DP BYTES (live-engine-allocatable): $9A-$9E (5 bytes) — 5 bytes total
; (was 15 bytes; CP3 of sprint engine-hygiene-1 claimed $89-$98 for
; HDMA_IRIS_*; CP3 of sprint phase 17 sprint B final claimed $99 for
; ES_STREAM_DMA_CHAN — see below)
;
; Note: $A3-$A6 is also nominally "free" (post-Phase-16-6-0 remediation)
; but lives inside the $A0-$AF "engine scratch" zone per CLAUDE.md.
; Allocating persistent state there conflicts with text_engine,
; mode5_text_engine, streaming_engine, and other transient scratch
; users — do NOT allocate persistent state into $A0-$AF.
; =============================================================================
; Available for live-engine allocation. These bytes formerly held the
; pre-Phase-16 Mode 7 state block (M7_ACTIVE, M7_HORIZON, M7_HEIGHT,
; M7_ANGLE, M7_CAM_X/Y, M7_CENTER_X/Y, M7_LUT_*, M7_FLAGS, M7_SPLIT_LINE,
; M7_DIRTY, M7_M7SEL, M7_PREV_GFXMODE, M7_BUF_SELECT). Live Mode 7 =
; Brad's M7_PV_* block at $C3-$F5 (see below).
;
; **Sub-block CLAIMED $89-$98 (16 bytes) — HDMA_IRIS_* (CP3 hygiene-1)**
; engine/hdma_engine.asm defines these absolute-WRAM symbols at $0189-$0198
; (= ENGINE_STATE_BASE + DP $89-$98). They were relocated from the
; collision-zone $0588-$0597 in sprint engine-hygiene-1 (2026-05-03).
; Iris and legacy Mode 7 share the byte address space here; no current
; ROM combines both. See docs/audit/engine_wram_allocation_audit.md.
;
; When allocating here ($9A-$9E):
;   1. Just define a new ES_* symbol at the desired offset in this file.
;   2. Live ROMs (parent-built scenes, current Phase 17 dispatch tests,
;      Brad flight/racing ASM ROMs) will see the new symbol immediately.
;      Those ROMs do NOT include engine_state_m7_legacy.inc, so there is
;      no collision with the dead M7_* symbols.
;   3. Legacy standalone ROMs (Phase 8 / 8T / 14 / 15 baselines, plus
;      tests/phase16/test_mode7_{live,static_visual,visual}_16_0.asm) DO
;      include engine_state_m7_legacy.inc for their frozen Mode 7 engine.
;      In those ROMs, the legacy M7_* symbols and your new ES_* symbol
;      both resolve to the same DP byte — that's fine because legacy ROMs
;      are standalone binaries that don't run live-engine code, so both
;      interpretations of the byte never coexist at runtime.
;
; Do NOT allocate $9F-$A2 (ES_HDMA_CH2_* — live; NMI phase 5 reads these
; unconditionally). Do NOT allocate $A3-$A6 — see warning above.
; =============================================================================

; --- Phase 17 Sprint B (final): BG1 streaming DMA channel ---
; Channel allocated by hdma_request at streaming_init time. Used by both
; the boot bulk DMA (64 column transfers) and per-frame streaming
; (one column per frame in streaming_update_bg1). Replaces Sprint A's
; hardcoded CH7 so streaming coexists with Mode 7 HDMA (which can claim
; CH5/CH6/CH7 depending on scene config). Range: 2..7. If hdma_request
; fails, streaming_init sets STREAM_ACTIVE=0 (graceful degrade).
ES_STREAM_DMA_CHAN  = $99   ; 1 byte: 2..7 (allocated channel number)

; Mode 7 HDMA CH2 configuration (CH2 not used by standard HDMA effects).
; Retained in engine_state.inc because NMI phase 5 reads ES_HDMA_CH2_*
; unconditionally as part of the generic HDMA channel setup loop.
ES_HDMA_CH2_DMAP    = $9F   ; 1 byte: CH2 DMAP (HDMA mode $02)
ES_HDMA_CH2_BBAD    = $A0   ; 1 byte: CH2 BBAD (target register)
ES_HDMA_CH2_TBL_LO  = $A1   ; 1 byte: CH2 table address low
ES_HDMA_CH2_TBL_HI  = $A2   ; 1 byte: CH2 table address high

; --- $A3-$A6: 4 bytes free ---
; Audit-1 remediation 2026-05-13: bright_fade state previously claimed
; this range but has been relocated to $36-$39. $A0-$A6 is the "engine
; scratch" zone per CLAUDE.md; multiple subsystems (text_engine,
; mode5_text_engine, streaming_engine, mode7_hdma_legacy) use it as
; transient main-thread scratch. Persistent engine state must NOT live
; here — use $36-$39 (now claimed by bright_fade), $9A-$9E, or another
; verified-free non-scratch slot for future allocation.
;
; Legacy ROMs still alias these bytes to ES_M7_BUF_SELECT + Mode 7
; reserve through engine_state_m7_legacy.inc (those baselines don't link
; the live engine, so the aliases never coexist with live state).

; =============================================================================
; --- Main-thread transient scratch zone ($00:00A0..$00:00BF) ---
; =============================================================================
; The ES_* symbols above are NMI-DP-relative (DP=$0100), so ES_HDMA_CH2_BBAD=$A0
; resolves to absolute $01A0 — that is, $00:01A0 — physically different from
; $00:00A0 (the main-thread DP=$0000 byte). The subsystem scratch zone
; documented below uses **main-thread DP=$0000**, so these are distinct
; physical bytes from the ES_HDMA_CH2_* / ES_SPLIT_BAND_COUNT / etc state
; above; the symbol name overlap is purely textual and never produces a
; runtime collision.
;
; This block formalizes every transient-scratch claim made by an engine
; subsystem outside engine_state.inc. The bytes are STILL declared in the
; subsystem's own .asm file (kept stable to avoid touching link order); the
; symbols below are an SSoT cross-reference for the zp_lint linter
; (tools/zp_lint.py) and human auditors. Layout matches `docs/audit/
; zp_allocation_landscape.md` Section 1 (audit 2026-05-13, on branch
; claude/zp-allocation-audit).
;
; Lifecycle: every byte in this block is TRANSIENT — valid only during a
; single subsystem call (print(), mode5_text_puts(), atan2(), sqrt()
; interpolation, coroutine resume/yield, etc). The transient users never
; nest, so cross-subsystem aliasing is safe-by-construction; the
; overlapping symbol names (E_S_MODE5_TEXT_SCRATCH_ROW_OFF aliases
; ES_TEXT_SCRATCH_LONGPTR_LO at $A0, for instance) are intentional and
; documented per byte below.
;
; Allocation rule: persistent engine state MUST NOT live here. This zone is
; reserved for transient call-scoped scratch. See CLAUDE.md "ZP Allocation
; Discipline" for the discipline + linter override convention.

; $A0-$A2 (3 B) — text_engine TEXT_SCRATCH_LONGPTR
; engine/text_engine.asm line 58. Used by engine_print and engine_print_vwf
; as a 24-bit indirect pointer to the string pool. The text engine reads
; the next character via `lda [<TEXT_SCRATCH_LONGPTR]` — the bank byte
; stored at $A0+2 is what makes this work under the 128 KB linker config
; (see CLAUDE.md "WRAM Long-Addressing Requires the Bank Byte").
; Owners: text_engine (print path). Mutually-exclusive with mode5_text_engine
; (different engine functions; never called concurrently within a frame).
ES_TEXT_SCRATCH_LONGPTR    = $A0   ; 3 bytes: 24-bit indirect ptr for engine_print

; $A0-$A1 (2 B) — mode5_text_engine M5T_ROW_OFF
; engine/mode5_text_engine.asm line 441. Row byte offset within SHADOW for
; the current Mode 5 text write. Aliases ES_TEXT_SCRATCH_LONGPTR low+mid
; bytes (the text engine and mode5_text engine never run inside the same
; subroutine call, so the scratch is reused safely).
; Owners: mode5_text_engine (engine_mode5_text path). Mutually-exclusive
; with text_engine print path.
ES_MODE5_TEXT_ROW_OFF      = $A0   ; 2 bytes: SHADOW row byte offset

; $A2 (1 B) — mode5_text_engine M5T_COL
; engine/mode5_text_engine.asm line 442. Current column counter (0..31).
ES_MODE5_TEXT_COL          = $A2   ; 1 byte: current text column

; $A3 (1 B) — mode5_text_engine M5T_TERMINATED
; engine/mode5_text_engine.asm line 443. String-termination flag.
; This is the byte that the original Phase 16-6-0 bright_fade allocation
; collided with — audit-1 of PR #165 caught it; bright_fade moved to
; $36-$39 in remediation (see ES_BRIGHT_FADE_* above). The remediation
; preserved this transient scratch claim — DO NOT relocate it without
; updating mode5_text_engine.asm.
ES_MODE5_TEXT_TERMINATED   = $A3   ; 1 byte: 0=reading, 1=padding

; $A5 (1 B) — SP_BC (engine call stack pointer)
; engine/coroutine_engine.asm line 37, also referenced by handlers_func.asm.
; Managed by the engine runtime; coroutine resume/yield saves/restores
; this in the coroutine slot. TRANSIENT in the sense that it changes during
; coroutine call boundaries but is otherwise engine-managed state.
; Defined behind `.ifndef _SP_BC_DEFINED` in coroutine_engine.asm so the
; assembly continues to compile after this declaration; the symbol here is
; informational and does NOT shadow the runtime definition.
ES_SP_BC                   = $A5   ; 1 byte: engine call stack pointer

; $A5-$AE — bg_stream.asm (Mode-1 horizontal column-streaming producer) scratch
; engine/bg_stream.asm. The streaming compute/queue/shadow-mirror routines use
; the engine-scratch zone $A5-$AE for the new-column index ($A6), forward
; target ($A5), slot/bank scratch ($A7-$A9), the 24-bit ROM source pointer
; ($AA-$AC), and a count-1 tmp ($AE). All TRANSIENT — valid only within a
; single bg_stream_tick / bg_stream_init call (main thread, never nested with
; the text/mode5/coroutine transient users above, which run from different
; engine functions). $A6 had no covering symbol before this declaration; the
; sibling bytes alias the scratch claims above (safe-by-construction — the
; streaming producer and those engine functions are never on the same call
; stack). See engine/bg_stream.asm "DP scratch convention" headers.
ES_BG_STREAM_COL           = $A6   ; 2 bytes: just-streamed world column index

; $A4 — bg_stream_row.asm (Mode-1 VERTICAL row-streaming producer, Sprint S2a)
; scratch: the world ROW being staged/queued (mirror of the column producer's
; $A6 col index, one byte lower so the two producers' transient scratch don't
; collide within a single sf_stream_tick2 — column tick runs to completion
; before the row tick begins, so even the overlapping $A5-$AE/$B0-$B5 spans are
; mutually-exclusive by-construction, never nested). TRANSIENT.
ES_BG_STREAM_ROW           = $A4   ; 2 bytes: just-streamed world row index

; $A8-$AA (3 B) — mode5_text_engine M5T_INDIRECT_PTR
; engine/mode5_text_engine.asm line 444. 24-bit indirect pointer to the
; string data; the bank byte at $AA carries the 128 KB linker config bank.
; Aliases no other subsystem (text_engine uses $A0-$A2, not $A8-$AA).
ES_MODE5_TEXT_INDIRECT_PTR = $A8   ; 3 bytes: 24-bit ptr to string pool

; $B0-$BD (14 B) — math wrapper scratch (atan2, sqrt interpolation)
; the parent engine-call wrappers: atan2 and sqrt
; interpolation (lines 1371-1395) use this block.
; Layout (named after atan2's variables; sqrt reuses $B0 alone as `delta`):
;   $B0  ES_ATAN2_DX        2 B  signed dx (8.8)
;   $B2  ES_ATAN2_DY        2 B  signed dy (8.8)
;   $B4  ES_ATAN2_ABS_DX    2 B  |dx|
;   $B6  ES_ATAN2_ABS_DY    2 B  |dy|
;   $B8  ES_ATAN2_OCTANT    2 B  octant flag bits {steep|dx_neg|dy_neg}
;   $BA  ES_ATAN2_BASE      2 B  ratio*64 numerator, then base angle
;   $BC  ES_ATAN2_DIVISOR   2 B  divisor for hardware divide
; TRANSIENT: valid only during one atan2() or sqrt() call.
;
; NOTE: SPLIT_BAND_COUNT lives at absolute $01B8 (= ENGINE_STATE_BASE +
; ES_SPLIT_BAND_COUNT, NMI-DP-relative); atan2 touches main-thread DP
; $00:00B8 — different physical addresses, no runtime collision. The
; textual symbol-name overlap is purely a documentation hazard.
ES_ATAN2_DX                = $B0   ; 2 bytes
ES_ATAN2_DY                = $B2   ; 2 bytes
ES_ATAN2_ABS_DX            = $B4   ; 2 bytes
ES_ATAN2_ABS_DY            = $B6   ; 2 bytes
ES_ATAN2_OCTANT            = $B8   ; 2 bytes
ES_ATAN2_BASE              = $BA   ; 2 bytes
ES_ATAN2_DIVISOR           = $BC   ; 2 bytes

; $B4 (1 B) — coroutine_engine MEM_TMP
; engine/coroutine_engine.asm line 38. Cold-path scratch for the coroutine
; engine's memory operations. Aliases ES_ATAN2_ABS_DX's low byte; safe
; because atan2 and coroutine_resume never nest inside the same call frame.
ES_CO_MEM_TMP              = $B4   ; 1 byte: coroutine engine scratch

; --- Scene Manager State ($A7-$B0) ---
ES_SCENE_FLAGS      = $A7   ; 1 byte:  bit 0 = halt requested (stops frame dispatch)
                            ;          bit 1 = scene transition in progress
                            ;          bit 2 = scene transition reentrant guard
ES_SCENE_CURRENT_ID = $A8   ; 1 byte:  current scene ID (0-254, $FF = none/boot)
ES_SCENE_TARGET_ID  = $A9   ; 1 byte:  target scene ID for pending transition
ES_SCENE_KEEP_MUSIC = $AA   ; 1 byte:  1 = keep music across next transition
ES_SCENE_COUNT      = $AB   ; 1 byte:  total number of scenes in ROM
ES_SCENE_INDEX_LO   = $AC   ; 2 bytes: ROM address of scene index table (low 16)
ES_SCENE_INDEX_BK   = $AE   ; 1 byte:  ROM bank of scene index table
; $AF-$B0: 2 bytes free (was ES_SCENE_RESERVED; reclaimed after audit).

; --- Phase 17-1: BG4 Shadow Scroll ($B1-$B4) ---
; BG4 is Mode-0-exclusive; the original Mode 1 / Mode 7 shadow set covered
; only BG1-BG3. Adding the 4 bytes here keeps Mode 0 scroll on the same
; NMI-commit path the other layers use.
ES_SHADOW_BG4HOFS   = $B1   ; 2 bytes: BG4 horizontal scroll
ES_SHADOW_BG4VOFS   = $B3   ; 2 bytes: BG4 vertical scroll

; --- Phase 17-3: Offset-Per-Tile Engine ($B5-$B6) ---
; Used by Modes 2/4/6 — BG3 is repurposed as the per-column offset source.
; scroll_column() writes the shadow buffer at $7E:C000 and sets the dirty
; flag; NMI handler (or explicit engine_offset_flush call) DMAs shadow to
; the BG3 tilemap in VRAM.
ES_OFFSET_DIRTY     = $B5   ; 1 byte: non-zero = shadow needs NMI flush to VRAM
; $B6: 1 byte free (was ES_OFFSET_RESERVED; 17-5 landed without needing a
; V-offset mask byte — the H/V halves use the BG1/BG2-enable bits in the
; offset word itself).

; --- Phase 17-7: $2133 SETINI shadow ($B7) ---
; Mirror of $2133 for readback by tests + engine logic. Bits:
;   bit 0 = screen interlace (0 = 224 line-doubled, 1 = 448 interlaced)
;   bit 1 = obj interlace (double-height sprites)
;   bit 2 = overscan (224 → 239 scanlines)
;   bit 3 = pseudo-hires (Modes 1-4); unused in Mode 5/6 which are hi-res
;           unconditionally
;   bit 7 = external BG
; Initialized to $00 (line-doubled default per decision 8). `hires_interlace`
; writes bit 0 and syncs $2133.
ES_SHADOW_SETINI    = $B7   ; 1 byte: shadow of PPU $2133 SETINI

; --- Phase 17-9: Split-mode HDMA state ($B8-$BA) ---
; Minimal engine-state footprint for the mode_band() / mode_bands_commit()
; API. The band table itself lives at $7E:C820 (32 × 4 B); the per-commit
; channel-mask bookkeeping and current band count live here.
;
; Trimmed from an 8-byte sketch:
;   - DIRTY / ACTIVE were optimizations — commit runs unconditionally on
;     every `mode_bands_commit()` call; active status derives from
;     `SPLIT_CH_MASK != 0`.
;   - REJECT_FLAGS was diagnostic; moved to the test ROM's debug region.
;   - 17-9b TM override state: ES_SPLIT_TM_CH_MASK added below.
ES_SPLIT_BAND_COUNT = $B8   ; 1 byte: number of bands currently staged (0..32)
ES_SPLIT_CH_MASK    = $B9   ; 1 byte: HDMA channel bitmask from hdma_request
                            ; (0 if no channel owned; doubles as "active" flag)
ES_SPLIT_TM_CH_MASK = $BA   ; 1 byte: Phase 17-9b — HDMA channel bitmask for
                            ; the tm_override channel (0 if not owned).
                            ; Used by engine_mode_bands_clear to release.

; Phase 17-10 hires_box() geometry — x/y/w/h in physical pixel coords (16-bit).
; Populated by engine_hires_box; read by text-layout code that wants to know
; where the Mode 5 dialog rect lives without recomputing it.
ES_HIRES_BOX_X      = $BB   ; 2 bytes: left edge (px)
ES_HIRES_BOX_Y      = $BD   ; 2 bytes: top scanline (= Mode 5 band y0)
ES_HIRES_BOX_W      = $BF   ; 2 bytes: width (px)
ES_HIRES_BOX_H      = $C1   ; 2 bytes: height (px, = band scanline count)

; --- Phase 16-0a Mode 7 Brad-port state (split $C3-$CF + $DD-$F5) ---
; 38 bytes total, split around Phase 17-0b1 HDMA allocator at $01D0-$01DC.
; Brad's pv_rebuild + pv_set_origin reference each byte through the M7_PV_*
; symbols (ENGINE_STATE_BASE + ES_M7_PV_*), so the internal split is
; transparent to the ported code. Mode 7 Brad-port and Phase 17 BG modes
; are mutually exclusive per scene; symbols just need unique addresses.
ES_M7_PV_ACTIVE       = $C3   ; 1 byte:  1 = Brad-port renderer active
ES_M7_DIRTY_REBUILD   = $C4   ; 1 byte:  1 = pv_rebuild needed
ES_M7_DIRTY_ORIGIN    = $C5   ; 1 byte:  1 = pv_set_origin needed
ES_M7_PV_BUFFER       = $C6   ; 1 byte:  double-buffer index (0 or 1)
ES_M7_PV_L0           = $C7   ; 1 byte:  horizon scanline
ES_M7_PV_L1           = $C8   ; 1 byte:  bottom scanline (usually 224)
ES_M7_PV_S0           = $C9   ; 2 bytes: far-scale u16
ES_M7_PV_S1           = $CB   ; 2 bytes: near-scale u16
ES_M7_PV_SH           = $CD   ; 2 bytes: vertical texel height
ES_M7_PV_INTERP       = $CF   ; 1 byte:  interpolation factor (1/2/4)
; --- $D0-$DC claimed by Phase 17-0b1 HDMA allocator (see ~line 695) ---
ES_M7_PV_WRAP         = $DD   ; 1 byte:  0 = no wrap, 1 = wrap
ES_M7_PV_ANGLE        = $DE   ; 1 byte:  camera rotation 0-255
ES_M7_PV_POSX         = $DF   ; 4 bytes: camera X, signed 16.16
ES_M7_PV_POSY         = $E3   ; 4 bytes: camera Y, signed 16.16
ES_M7_PV_M7T          = $E7   ; 8 bytes: cached matrix A/B/C/D (8.8)
ES_M7_PV_FOCUS_Y      = $EF   ; 1 byte:  pv_set_origin target scanline
ES_M7_PV_NMI_M7X      = $F0   ; 2 bytes: computed M7X
ES_M7_PV_NMI_M7Y      = $F2   ; 2 bytes: computed M7Y
ES_M7_PV_M7SEL        = $F4   ; 1 byte:  shadow M7SEL
ES_M7_PV_PREV_GFXMODE = $F5   ; 1 byte:  saved gfxmode before Mode 7 switch

; Phase 17-11 Mode 7 + Mode 1 HUD overlay state (revised post-merge)
ES_M7_HUD_ACTIVE      = $F6   ; 1 byte:  1 = HUD overlay active
ES_M7_HUD_HEIGHT      = $F7   ; 1 byte:  HUD band height in scanlines

; Phase 17 Mode 5 text-rendering completion (2026-05-10)
; ES_MODE5_TEXT_INIT: 1 = Mode 5 font has been uploaded to VRAM word $2200
;   (set by engine_mode5_text_init on first call). Used to gate the one-time
;   forced-blank font-upload path in engine_mode5_text_init. Never written
;   by engine_mode5_text — text writes are SHADOW-only and don't disturb
;   display. See engine/mode5_text_engine.asm.
ES_MODE5_TEXT_INIT    = $F8   ; 1 byte:  1 = Mode 5 font uploaded

; Mode 7 "barrel chamber" per-scanline M7A override (G1; sf_mode7_barrel).
; When ES_M7_BARREL_ACTIVE != 0, mode7_barrel_apply (the post-pv_rebuild hook)
; overwrites the per-scanline M7A word of each FLOOR-band scanline in the active
; AB double-buffer with the caller's barrel table (a u16-per-scanline curve at
; the far pointer below), leaving M7B/M7C/M7D = the engine's per-frame rotation.
; The table holds one 8.8 M7A word per FLOOR scanline (index 0 = scanline L0).
ES_M7_BARREL_ACTIVE   = $F9   ; 1 byte:  1 = M7A barrel override active
ES_M7_BARREL_PTR      = $FA   ; 3 bytes: far pointer to the barrel u16 table

; Engine state ends at $FD — 253 bytes of DP claimed.
; Free DP (per "; free" blocks above): 28 bytes reclaimed across two audits —
;   commit 03948a6 (Phase 17-9 Stage 1a): 12 bytes of dead fields
;   commit 088396e (PR #59): 10 diagnostic-only bytes relocated to WRAM
;     extended ($7E:E100..E109 — STAT5_DMA_REM, STAT7_DROPS, STAT0_CPU_PCT,
;     SPR_SCANLINE_PEAK, SPR_SCANLINE_DETECT_EN, GFXMODE_STATE)
;   plus the $89-$9E + $A3 block documented at the top of this file.
; Hot frame-path state should be the only thing that lives in $0100..$01FF;
; diagnostic / cold state belongs in WRAM extended.
; Hard DP ceiling is 256 bytes ($0100..$01FF); 70 bytes of DP-fast
; headroom remain for future engine subsystems. Past $01FF, state costs
; +1 cycle per access (absolute addressing) or requires mid-function DP
; swap — unsuitable for hot frame-path state, fine for cold state.

; === Absolute WRAM Addresses (for main thread absolute addressing) ===
NMI_DMA_QUEUE_PTR   = ENGINE_STATE_BASE + ES_DMA_QUEUE_PTR
NMI_DMA_QUEUE_COUNT = ENGINE_STATE_BASE + ES_DMA_QUEUE_COUNT
NMI_DMA_BUDGET      = ENGINE_STATE_BASE + ES_DMA_BUDGET
NMI_BYTES_REMAINING = ENGINE_STATE_BASE + ES_BYTES_REMAINING
NMI_HDMA_ENABLE     = ENGINE_STATE_BASE + ES_HDMA_ENABLE_MASK
NMI_DMA_READY       = ENGINE_STATE_BASE + ES_DMA_QUEUE_READY
NMI_DONE_FLAG       = ENGINE_STATE_BASE + ES_NMI_DONE_FLAG
FRAME_PHASE         = ENGINE_STATE_BASE + ES_FRAME_PHASE
FRAME_COUNTER       = ENGINE_STATE_BASE + ES_FRAME_COUNTER
JOY1_CURRENT        = ENGINE_STATE_BASE + ES_JOY1_CURRENT
JOY1_PREVIOUS       = ENGINE_STATE_BASE + ES_JOY1_PREVIOUS
JOY1_PRESSED        = ENGINE_STATE_BASE + ES_JOY1_PRESSED
JOY2_CURRENT        = ENGINE_STATE_BASE + ES_JOY2_CURRENT
JOY2_PREVIOUS       = ENGINE_STATE_BASE + ES_JOY2_PREVIOUS
JOY2_PRESSED        = ENGINE_STATE_BASE + ES_JOY2_PRESSED

; --- Joypad Press Latches (WRAM scratch, read by main thread) ---
; NMI accumulates rising edges into JOYn_PRESSED via ORA.
; Frame lifecycle latches and clears at INPUT phase so game code reads
; a stable snapshot. ~4-cycle race window vs ~30,000-cycle old window.
JOY1_PRESSED_LATCH  = $0556     ; 2 bytes: P1 pressed latch for game code
JOY2_PRESSED_LATCH  = $0558     ; 2 bytes: P2 pressed latch for game code
; Phase 17 Sprint D-5 (Bug A): runtime BG2 tilemap VRAM high byte. Set by
; bg_engine init to PPU_BG2SC_VALUE; overridden by streaming-mode boot to
; PPU_BG2SC_STREAMING_VALUE. Read by NMI handler when DMAing SHADOW_BG2_TILEMAP.
BG2_TILEMAP_VRAM_HI = ENGINE_STATE_BASE + ES_BG2_TILEMAP_VRAM_HI

SHADOW_BG1HOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG1HOFS
SHADOW_BG1VOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG1VOFS
SHADOW_BG2HOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG2HOFS
SHADOW_BG2VOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG2VOFS
SHADOW_BG3HOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG3HOFS
SHADOW_BG3VOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG3VOFS
SHADOW_BG4HOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG4HOFS
SHADOW_BG4VOFS      = ENGINE_STATE_BASE + ES_SHADOW_BG4VOFS
OFFSET_DIRTY        = ENGINE_STATE_BASE + ES_OFFSET_DIRTY
SHADOW_SETINI       = ENGINE_STATE_BASE + ES_SHADOW_SETINI
SPLIT_BAND_COUNT    = ENGINE_STATE_BASE + ES_SPLIT_BAND_COUNT
SPLIT_CH_MASK       = ENGINE_STATE_BASE + ES_SPLIT_CH_MASK
SPLIT_TM_CH_MASK    = ENGINE_STATE_BASE + ES_SPLIT_TM_CH_MASK
HIRES_BOX_X         = ENGINE_STATE_BASE + ES_HIRES_BOX_X
HIRES_BOX_Y         = ENGINE_STATE_BASE + ES_HIRES_BOX_Y
HIRES_BOX_W         = ENGINE_STATE_BASE + ES_HIRES_BOX_W
HIRES_BOX_H         = ENGINE_STATE_BASE + ES_HIRES_BOX_H
MODE5_TEXT_INIT     = ENGINE_STATE_BASE + ES_MODE5_TEXT_INIT

; Phase 17-9: Mode-band table + HDMA indirect table in WRAM.
; Placed past the Phase 17-0a allocator's state ($C800..$C807) AND its
; per-request scratch ($C810..$C814). The HDMA table uses the per-
; scanline (repeat-bit SET) encoding — see engine/mode_split_hdma.asm
; @sort_done — which requires up to 228 bytes for a full-screen
; 3-band split. Allocated 256 bytes here for headroom.
;   $7E:C820..$C89F  — 32 band records × 4 B (y0, y1, mode, tm)
;   $7E:C8A0..$C99F  — BGMODE HDMA continuous1 table (256 B, ≤228 used)
;   $7E:C9A0..$CB9F  — Phase 17-9b TM/TS HDMA continuous2 table (512 B, ≤451
;                      used). Transfer mode 1 writes 2 bytes per scanline to
;                      $212C/$212D adjacent registers, so worst-case encoding
;                      is 1 header + 127×2 data + 1 header + 97×2 data + 1
;                      terminator = 451 bytes.
; Mutually exclusive with Mode 7 HDMA tables per phase_17_allocations.md §2.
SPLIT_BAND_TABLE    = $C820
SPLIT_BAND_ENTRY_SIZE = 4               ; y0, y1, mode, tm per entry
SPLIT_BAND_MAX      = 32
SPLIT_HDMA_TABLE    = $C8A0             ; BGMODE HDMA continuous1 table base
SPLIT_TM_HDMA_TABLE = $C9A0             ; Phase 17-9b TM/TS continuous2 table

; Phase 17-3/17-5: Offset-tilemap shadow buffer (2 KB at $7E:C000-$C7FF).
; Mutually exclusive with Mode 7 HDMA tables (same $C000 region).
;
; Layout (after 17-5 widened the flush to cover both OPT rows):
;   $C000..$C03F  H half — 32 cols × 2 B (row 0 of BG3 tilemap in VRAM)
;   $C040..$C07F  V half — 32 cols × 2 B (row 1 of BG3 tilemap in VRAM)
;
; A single 128-byte DMA from $7E:C000 to VRAM word $0800 writes BG3 tilemap
; rows 0 and 1 back-to-back in one transfer. Pre-17-5 ROMs that only used
; H OPT now also flush a zero-filled V half, which is a no-op — the PPU
; ignores V fetches whose enable bits (13 for BG1, 14 for BG2) are clear.
OFFSET_SHADOW       = $C000
OFFSET_SHADOW_H     = $C000             ; 17-3/17-4 alias (row 0 fetch)
OFFSET_SHADOW_V     = $C040             ; 17-5 addition (row 1 fetch)
OFFSET_SHADOW_SIZE  = 128               ; 32 cols × 2 B × 2 rows (H + V)

; Per-column offset entry bits (spec: Mode 2 BG3 tilemap offset format):
;   bits 0-9    : scroll offset value (0-1023)
;   bit  13     : apply to BG1 (1 = yes)
;   bit  14     : apply to BG2 (1 = yes)
;   bit  15     : reserved (0)
OFFSET_BG1_ENABLE   = $2000             ; bit 13
OFFSET_BG2_ENABLE   = $4000             ; bit 14
SHADOW_BGMODE       = ENGINE_STATE_BASE + ES_SHADOW_BGMODE
SHADOW_MOSAIC       = ENGINE_STATE_BASE + ES_SHADOW_MOSAIC
SHADOW_INIDISP      = ENGINE_STATE_BASE + ES_SHADOW_INIDISP
SHADOW_NMITIMEN     = ENGINE_STATE_BASE + ES_SHADOW_NMITIMEN
SHADOW_TM           = ENGINE_STATE_BASE + ES_SHADOW_TM
SPRITE_COUNT        = ENGINE_STATE_BASE + ES_SPRITE_COUNT
OAM_DIRTY           = ENGINE_STATE_BASE + ES_OAM_DIRTY
SPR_ORDER_MODE      = ENGINE_STATE_BASE + ES_SPR_ORDER_MODE
SPR_FLICKER_ENABLE  = ENGINE_STATE_BASE + ES_SPR_FLICKER_EN
SPR_FLICKER_OFFSET  = ENGINE_STATE_BASE + ES_SPR_FLICKER_OFF
SPR_SCANLINE_PEAK   = $7EE106       ; 2 bytes, relocated from ES_SPR_SCANLINE_PK
SPR_SCANLINE_DETECT_EN = $7EE108    ; 1 byte,  relocated from ES_SPR_SCANLINE_EN

; --- Relocated telemetry (WRAM extended, $7E:E100..) ---
; Diagnostic-only values, read by debug_overlay and test ROMs. Defined as
; full 24-bit symbols so `sta SYM` / `lda SYM` emit STA long / LDA long
; with the correct bank byte ($7E). For STZ/INC (which have no long form),
; the caller must use `lda #0` + `sta SYM` or a long RMW sequence — see
; engine/nmi_handler.asm for the drop-counter RMW. Note: from .a16 mode
; ca65 needs `sta f:SYM` to force long-form addressing of a 24-bit
; symbol — see CP4 of sprint engine-hygiene-1 in hdma_engine.asm for
; the canonical pattern.
;
; Relocated cold-state owners in the $7EE0A0..$7EE0FF region:
;   $7EE0A0..$7EE0A3  OVERLAY_*       (debug_overlay; CP2 hygiene-1)
;   $7EE0C0..$7EE0C5  HDMA_SCROLL_*   (hdma_engine;   CP4 hygiene-1)
;   $7EE0D0..$7EE0D9  PARALLAX_BANDS_* (hdma_engine; Phase 16-8 step 5)
;                       — LAYER, YSPLIT, RATIO_TOP, RATIO_BOT, CHAN
;                       — published state read by tests + engine wrapper.
;   $7EE0DA..$7EE0DF  PARALLAX_BANDS transient (hdma_engine; step 5)
;                       — HOFS_TOP, HOFS_BOT, WORLDX scratch recomputed
;                       — each table build; not read outside hdma_engine.
;   $7EE0B0..$7EE0B9  HDMA_BEND_*     (hdma_engine; kit brick #1 sf_bend/tunnel)
;                       — CURVE, AMP, LAYER, CHAN, AXIS. The curve-LUT-driven
;                       per-scanline BGnHOFS/BGnVOFS builder behind sf_bend(_v)/
;                       sf_tunnel(_v); animation phase/speed reuse the wave DP
;                       slots ($66/$68). AXIS ($7EE0B8, v1.2): 0=H (BGnHOFS),
;                       1=V (BGnVOFS) — the only per-axis difference is the
;                       BBAD target register (V = H+1), set once at arm.
;   ($7EE0BA..$7EE0BF still reserved for future cold state — not yet claimed;
;    iris went to DP $89-$98 because of LDX/CPX addressing)
;   $7EE200..$7EE3FF  HDMA_BEND_SCALED_W (hdma_engine; bend/tunnel v1.1 E-PERF)
;                       — 256 signed 16-bit scaled-curve words (512 B). The
;                       per-frame refill's source LUT; too big for the 1 KB
;                       channel slot, so its own region in the debug block.
;   $7EE400..$7EE9FF  HDMA_BEND_BAKED  (hdma_engine; bend/tunnel v1.1 E-SLIDE)
;                       — 481-entry oversized roll table (1536 B). The pure-roll
;                       pointer-slide fast-path's baked table; the per-frame
;                       tick advances A1Tn into it, no table writes.
;
; Relocated hot-path diagnostic state in $7EE100+:
STAT5_DMA_REM       = $7EE100       ; 2 bytes
STAT7_DROPS         = $7EE102       ; 2 bytes
STAT0_CPU_PCT       = $7EE104       ; 2 bytes
BG_TILEMAP_DIRTY    = ENGINE_STATE_BASE + ES_BG_TILEMAP_DIRTY
GFXMODE_STATE       = $7EE109       ; 1 byte, relocated from ES_GFXMODE
; $7EE10A..$7EE10D claimed by SHADOW_WH0..WH3 (sf_window window-edge shadows —
; defined with the other window shadows above; next free is $7EE10E).
BG_SHADOW_REGS_DIRTY = ENGINE_STATE_BASE + ES_BG_SHADOW_DIRTY
CGRAM_DIRTY_LO      = ENGINE_STATE_BASE + ES_CGRAM_DIRTY_LO
CGRAM_DIRTY_HI      = ENGINE_STATE_BASE + ES_CGRAM_DIRTY_HI
CGRAM_DIRTY_FLAG    = ENGINE_STATE_BASE + ES_CGRAM_DIRTY_FLAG
PAL_CYCLE_COUNT     = ENGINE_STATE_BASE + ES_PAL_CYCLE_COUNT
SHADOW_TS           = ENGINE_STATE_BASE + ES_SHADOW_TS
SHADOW_CGWSEL       = ENGINE_STATE_BASE + ES_SHADOW_CGWSEL
SHADOW_CGADSUB      = ENGINE_STATE_BASE + ES_SHADOW_CGADSUB
SHADOW_COLDATA_R    = ENGINE_STATE_BASE + ES_SHADOW_COLDATA_R
SHADOW_COLDATA_G    = ENGINE_STATE_BASE + ES_SHADOW_COLDATA_G
SHADOW_COLDATA_B    = ENGINE_STATE_BASE + ES_SHADOW_COLDATA_B
BLEND_DIRTY         = ENGINE_STATE_BASE + ES_BLEND_DIRTY
TINT_ACTIVE         = ENGINE_STATE_BASE + ES_TINT_ACTIVE
FONT_BASE_TILE      = ENGINE_STATE_BASE + ES_FONT_BASE_TILE
FONT_LOADED         = ENGINE_STATE_BASE + ES_FONT_LOADED
VWF_ACTIVE           = ENGINE_STATE_BASE + ES_VWF_ACTIVE

; HDMA state (absolute addresses)
; Phase 17-0b1: HDMA_ALLOC + HDMA_EFFECT_CNT symbol aliases removed. Any
; remaining references will fail to assemble — that's the intended signal.
; Use `hdma_request` / `hdma_release` / `hdma_channels` instead.
HDMA_CH3_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH3_DMAP
HDMA_CH3_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH3_BBAD
HDMA_CH3_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH3_TBL_LO
HDMA_CH3_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH3_TBL_HI
HDMA_CH4_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH4_DMAP
HDMA_CH4_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH4_BBAD
HDMA_CH4_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH4_TBL_LO
HDMA_CH4_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH4_TBL_HI
HDMA_CH5_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH5_DMAP
HDMA_CH5_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH5_BBAD
HDMA_CH5_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH5_TBL_LO
HDMA_CH5_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH5_TBL_HI
HDMA_CH6_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH6_DMAP
HDMA_CH6_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH6_BBAD
HDMA_CH6_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH6_TBL_LO
HDMA_CH6_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH6_TBL_HI
HDMA_CH7_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH7_DMAP
HDMA_CH7_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH7_BBAD
HDMA_CH7_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH7_TBL_LO
HDMA_CH7_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH7_TBL_HI
HDMA_WAVE_PHASE     = ENGINE_STATE_BASE + ES_HDMA_WAVE_PHASE
HDMA_WAVE_SPEED     = ENGINE_STATE_BASE + ES_HDMA_WAVE_SPEED

; TAD Audio Bridge (absolute addresses)
TAD_STATUS          = ENGINE_STATE_BASE + ES_TAD_STATUS
TAD_SEQ_CTR         = ENGINE_STATE_BASE + ES_TAD_SEQ_CTR
TAD_SONG_ID         = ENGINE_STATE_BASE + ES_TAD_SONG_ID
TAD_VOLUME          = ENGINE_STATE_BASE + ES_TAD_VOLUME
TAD_SFX_MASK        = ENGINE_STATE_BASE + ES_TAD_SFX_MASK
TAD_PAUSED          = ENGINE_STATE_BASE + ES_TAD_PAUSED
TAD_QUEUE_CMD       = ENGINE_STATE_BASE + ES_TAD_QUEUE_CMD
TAD_QUEUE_P1        = ENGINE_STATE_BASE + ES_TAD_QUEUE_P1
TAD_QUEUE_P2        = ENGINE_STATE_BASE + ES_TAD_QUEUE_P2
TAD_READY           = ENGINE_STATE_BASE + ES_TAD_READY

; Volume fade state (absolute addresses)
FADE_TARGET         = ENGINE_STATE_BASE + ES_FADE_TARGET
FADE_SPEED          = ENGINE_STATE_BASE + ES_FADE_SPEED
FADE_DIRECTION      = ENGINE_STATE_BASE + ES_FADE_DIRECTION

; Brightness fade state (absolute addresses) — Phase 16-6-0
BRIGHT_FADE_TARGET    = ENGINE_STATE_BASE + ES_BRIGHT_FADE_TARGET
BRIGHT_FADE_STEP_FRAC = ENGINE_STATE_BASE + ES_BRIGHT_FADE_STEP_FRAC
BRIGHT_FADE_FRAMES    = ENGINE_STATE_BASE + ES_BRIGHT_FADE_FRAMES
BRIGHT_FADE_DIRECTION = ENGINE_STATE_BASE + ES_BRIGHT_FADE_DIRECTION

; Window masking state (absolute addresses)
SHADOW_W12SEL       = ENGINE_STATE_BASE + ES_SHADOW_W12SEL
SHADOW_W34SEL       = ENGINE_STATE_BASE + ES_SHADOW_W34SEL
SHADOW_WOBJSEL      = ENGINE_STATE_BASE + ES_SHADOW_WOBJSEL
SHADOW_WBGLOG       = ENGINE_STATE_BASE + ES_SHADOW_WBGLOG
SHADOW_WOBJLOG      = ENGINE_STATE_BASE + ES_SHADOW_WOBJLOG
SHADOW_TMW          = ENGINE_STATE_BASE + ES_SHADOW_TMW
SHADOW_TSW          = ENGINE_STATE_BASE + ES_SHADOW_TSW

; Window-POSITION shadows WH0-WH3 ($2126-$2129) — the sf_window brick.
; DP ($82-$88) holds the window ENABLE/LOGIC/MASK shadows; DP is full, so the
; four window-EDGE bytes live in the WRAM-extended block ($7E:E10A..E10D, next
; free after GFXMODE_STATE @ $7E:E109 — see the "$7EE100+" map above). Full
; 24-bit symbols so `lda`/`sta` emit long-form with the $7E bank byte (the
; NMI flush is in A8/DB=$00; a bare `lda SHADOW_WH0` resolves long because the
; symbol value exceeds $FFFF). The PPU has no read-back path for WH0-3, so
; the shadow is the SSoT the NMI commits each frame; coldstart zeros WRAM, so
; the default ($00 edges, window 1 covering the whole line) is well-defined.
SHADOW_WH0          = $7EE10A       ; 1 byte: WH0 ($2126) — window 1 LEFT edge
SHADOW_WH1          = $7EE10B       ; 1 byte: WH1 ($2127) — window 1 RIGHT edge
SHADOW_WH2          = $7EE10C       ; 1 byte: WH2 ($2128) — window 2 LEFT edge
SHADOW_WH3          = $7EE10D       ; 1 byte: WH3 ($2129) — window 2 RIGHT edge

; Coroutine state (absolute addresses)
CO_POOL_BASE_PTR    = ENGINE_STATE_BASE + ES_CO_POOL_BASE
CO_ACTIVE_COUNT     = ENGINE_STATE_BASE + ES_CO_ACTIVE_COUNT
CO_AUTO_RESUME_N    = ENGINE_STATE_BASE + ES_CO_AUTO_RESUME_N
CO_CURRENT_SLOT     = ENGINE_STATE_BASE + ES_CO_CURRENT_SLOT
CO_CALLER_PC        = ENGINE_STATE_BASE + ES_CO_CALLER_PC
CO_CALLER_SP        = ENGINE_STATE_BASE + ES_CO_CALLER_SP

; Legacy Mode 7 state (M7_ACTIVE/HORIZON/HEIGHT/ANGLE/CAM/CENTER/LUT/
; FLAGS/SPLIT_LINE/DIRTY/M7SEL/PREV_GFXMODE/BUF_SELECT) lives in
; engine_state_m7_legacy.inc. Live Mode 7 = Brad M7_PV_* block below.

; Mode 7 HDMA CH2 config (absolute addresses)
HDMA_CH2_DMAP       = ENGINE_STATE_BASE + ES_HDMA_CH2_DMAP
HDMA_CH2_BBAD       = ENGINE_STATE_BASE + ES_HDMA_CH2_BBAD
HDMA_CH2_TBL_LO     = ENGINE_STATE_BASE + ES_HDMA_CH2_TBL_LO
HDMA_CH2_TBL_HI     = ENGINE_STATE_BASE + ES_HDMA_CH2_TBL_HI

; Phase 16-0a Mode 7 Brad-port state (absolute addresses)
M7_PV_ACTIVE        = ENGINE_STATE_BASE + ES_M7_PV_ACTIVE
M7_DIRTY_REBUILD    = ENGINE_STATE_BASE + ES_M7_DIRTY_REBUILD
M7_DIRTY_ORIGIN     = ENGINE_STATE_BASE + ES_M7_DIRTY_ORIGIN
M7_PV_BUFFER        = ENGINE_STATE_BASE + ES_M7_PV_BUFFER
M7_PV_L0            = ENGINE_STATE_BASE + ES_M7_PV_L0
M7_PV_L1            = ENGINE_STATE_BASE + ES_M7_PV_L1
M7_PV_S0            = ENGINE_STATE_BASE + ES_M7_PV_S0
M7_PV_S1            = ENGINE_STATE_BASE + ES_M7_PV_S1
M7_PV_SH            = ENGINE_STATE_BASE + ES_M7_PV_SH
M7_PV_INTERP        = ENGINE_STATE_BASE + ES_M7_PV_INTERP
M7_PV_WRAP          = ENGINE_STATE_BASE + ES_M7_PV_WRAP
M7_PV_ANGLE         = ENGINE_STATE_BASE + ES_M7_PV_ANGLE
M7_PV_POSX          = ENGINE_STATE_BASE + ES_M7_PV_POSX
M7_PV_POSY          = ENGINE_STATE_BASE + ES_M7_PV_POSY
M7_PV_M7T           = ENGINE_STATE_BASE + ES_M7_PV_M7T
M7_PV_FOCUS_Y       = ENGINE_STATE_BASE + ES_M7_PV_FOCUS_Y
M7_PV_NMI_M7X       = ENGINE_STATE_BASE + ES_M7_PV_NMI_M7X
M7_PV_NMI_M7Y       = ENGINE_STATE_BASE + ES_M7_PV_NMI_M7Y
M7_PV_M7SEL         = ENGINE_STATE_BASE + ES_M7_PV_M7SEL
M7_PV_PREV_GFXMODE  = ENGINE_STATE_BASE + ES_M7_PV_PREV_GFXMODE
M7_HUD_ACTIVE       = ENGINE_STATE_BASE + ES_M7_HUD_ACTIVE
M7_HUD_HEIGHT       = ENGINE_STATE_BASE + ES_M7_HUD_HEIGHT
M7_BARREL_ACTIVE    = ENGINE_STATE_BASE + ES_M7_BARREL_ACTIVE
M7_BARREL_PTR       = ENGINE_STATE_BASE + ES_M7_BARREL_PTR

; Scene manager state (absolute addresses)
SCENE_FLAGS         = ENGINE_STATE_BASE + ES_SCENE_FLAGS
SCENE_CURRENT_ID    = ENGINE_STATE_BASE + ES_SCENE_CURRENT_ID
SCENE_TARGET_ID     = ENGINE_STATE_BASE + ES_SCENE_TARGET_ID
SCENE_KEEP_MUSIC    = ENGINE_STATE_BASE + ES_SCENE_KEEP_MUSIC
SCENE_COUNT         = ENGINE_STATE_BASE + ES_SCENE_COUNT
SCENE_INDEX_LO      = ENGINE_STATE_BASE + ES_SCENE_INDEX_LO
SCENE_INDEX_BK      = ENGINE_STATE_BASE + ES_SCENE_INDEX_BK

; Scene flag bit definitions
SCENE_FLAG_HALT     = $01       ; bit 0: halt native code execution
SCENE_FLAG_TRANS    = $02       ; bit 1: scene transition in progress
SCENE_FLAG_REENTER  = $04       ; bit 2: reentrant guard (scene() inside _init())

; === Coroutine Pool (WRAM bank $7E, $D400+) ===
; 16 slots x 256 bytes = 4096 bytes ($D400-$E3FF, but we only use $D400-$DFFF).
; Must use long addressing (f:$7ED400+) or set DB=$7E.
CO_POOL_BASE        = $D400         ; pool start address in WRAM
CO_SLOT_SIZE        = 256           ; bytes per slot ($100)
CO_MAX_SLOTS        = 16
CO_STATUS_FREE      = 0
CO_STATUS_SUSPENDED = 1
CO_STATUS_RUNNING   = 2
CO_STATUS_DEAD      = 3

; Per-slot field offsets (within each 256-byte slot)
CO_SLOT_STATUS      = $00           ; 1 byte: status (FREE/SUSPENDED/RUNNING/DEAD)
CO_SLOT_FLAGS       = $01           ; 1 byte: flags (bit0=auto_resume, bit1=fire_and_forget)
CO_SLOT_SAVED_PC    = $02           ; 2 bytes: saved program PC
CO_SLOT_SAVED_SP    = $04           ; 2 bytes: saved call stack pointer
CO_SLOT_SAVED_REGS  = $06           ; 64 bytes: saved registers R0-R15 (4 bytes each)
                                    ; $46-$FF: reserved

; Coroutine flags
CO_FLAG_AUTO_RESUME = $01           ; bit 0: auto-resume each frame
CO_FLAG_FIRE_FORGET = $02           ; bit 1: fire-and-forget (auto-clean on DEAD)

; Caller register save area (WRAM bank $7E, $BF00+)
; When a coroutine is resumed, the caller's R0-R15 are saved here temporarily.
; Only one coroutine can be RUNNING at a time, so a single save area suffices.
CO_CALLER_SAVE_AREA = $BF00         ; 64 bytes ($BF00-$BF3F) — after PAL_ROM_DEFAULTS ($BD00-$BEFF)

; === HDMA Wave Effect Scratch (WRAM $0580+) ===
; Used by hdma_build_wave during table construction.
HDMA_WAVE_AMP       = $0580     ; 2 bytes: wave amplitude (0-15 pixels)
HDMA_WAVE_LAYER     = $0582     ; 2 bytes: target BG layer (1-3)
HDMA_WAVE_CHAN      = $0584     ; 2 bytes: allocated channel number

; === HDMA Bend / Tunnel Effect cold state (WRAM-extended $7EE0B0+) ===
; Used by hdma_build_hofs_curve (the curve-LUT-driven per-scanline BGnHOFS
; builder behind sf_bend / sf_tunnel). Lives in the reserved cold-state block
; at $7EE0B0..$7EE0BF (engine_state.inc allocations note, ~line 747) so it sits
; beside HDMA_SCROLL_* ($7EE0C0) without DP pressure. These are 24-bit symbols:
; from .a16 mode ca65 needs `f:` to force long-form addressing (see the CP4
; pattern at hdma_engine.asm). STZ has no long form — clear with `lda #0` +
; `sta f:SYM`. The animation phase/speed REUSE the wave-effect DP slots
; ES_HDMA_WAVE_PHASE ($66) / ES_HDMA_WAVE_SPEED ($68) — same one-channel,
; one-animated-effect contract as scanline_scroll, so no new DP byte is spent.
HDMA_BEND_CURVE     = $7EE0B0   ; 2 bytes: active curve id (0 = SINE, 1 = PARABOLA)
HDMA_BEND_AMP       = $7EE0B2   ; 2 bytes: amplitude scale (0-15 pixels of peak displacement)
HDMA_BEND_LAYER     = $7EE0B4   ; 2 bytes: target BG layer (1, 2, or 3)
HDMA_BEND_CHAN      = $7EE0B6   ; 2 bytes: allocated channel number (3-7) or 0 = inactive
; v1.2 vertical-axis extension: 0 = H (BGnHOFS, the classic line-scroll bend),
; 1 = V (BGnVOFS, the barrel/horizon row-squash). The ONLY mechanical difference
; between axes is the BBAD target register (V register = H register + 1:
; BG1VOFS=$0E, BG2VOFS=$10, BG3VOFS=$12), computed once at arm in
; hdma_build_hofs_curve. The precompute, optimized refill, and pointer-slide
; fast-path are all axis-agnostic (they touch the table data + A1Tn, never BBAD)
; and reused UNCHANGED for both axes.
HDMA_BEND_AXIS      = $7EE0B8   ; 2 bytes: target axis (0 = H/BGnHOFS, 1 = V/BGnVOFS)

; === HDMA Bend scaled-curve word LUT (WRAM-extended, $7E:E200..$7E:E3FF) ===
; Enhancement v1.1 (E-PERF): the amplitude-scaled curve, precomputed ONCE per
; arm as 256 SIGNED 16-bit WORDS (already sign-extended), so the per-frame
; refill writes each scanline's offset as ONE 16-bit store — no sep/rep toggle
; and no per-line sign-extension branch in the hot loop. 256 * 2 = 512 bytes.
; This will NOT fit in the channel's 1 KB HDMA-table slot after the live table
; (225*3+1 = 676 B) + BEND_SCALED_OFF=768, so it lives in its own dedicated
; WRAM scratch region in the $7E:E000 debug/cold-state block (E200..E3FF is
; otherwise unclaimed — see the $7EE0A0..$7EE1FF allocation note above). Bank
; $7E; use long addressing (f:) or DB=$7E. Rebuilt only when amp/curve change
; (precompute), never per frame.
HDMA_BEND_SCALED_W  = $7EE200   ; 512 bytes: 256 signed 16-bit scaled-curve words

; === HDMA Bend pointer-slide baked table (WRAM-extended, $7E:E400..$7E:E9FF) ===
; Enhancement v1.1 (E-SLIDE): the pure-roll (animated, NO horizontal scroll)
; fast-path bakes an OVERSIZED mode-$02 table ONCE at arm — screen height (225)
; + one full curve period (256) = 481 entries of [1, off_lo, off_hi] — so the
; per-frame tick can phase the roll by ONLY advancing the channel's HDMA source
; pointer (A1Tn, $43n2/3) by 3*k bytes (k scanlines), with NO table writes.
; baked[j] = scaled_curve[j & $FF] for j=0..480, so sliding the window start to
; `phase` makes scanline s read baked[phase+s] = curve[(phase+s)&$FF] — exactly
; the curve formula. Count bytes are all $01 (never $00), so there is no early
; HDMA terminator inside the slideable window; HDMA stops naturally at VBlank
; after 224 active lines. 481*3 + 1 = 1444 bytes; the region is padded to 1536.
; Bank $7E; use long addressing (f:). Built once per pure-roll arm.
HDMA_BEND_BAKED     = $7EE400   ; 1536 bytes: 481-entry oversized roll table
                                ; NOTE: tests/phase4/test_coroutine.asm reuses $7EE400 as its
                                ; own DEBUG_BASE — disjoint ROM, never links hdma_engine, so no
                                ; real collision (audit-1 D2, docs/audit/hdma_bend_enhance-audit-1.md).

; === HDMA Table Memory (WRAM bank $7E, $C000+) ===
; Each channel gets 1024 bytes for its HDMA table.
; Wave mode uses 3 bytes/scanline (mode $02): 225*3+1 = 676 bytes per table.
; Must use long addressing (f:$7EC000+) or set DB=$7E.
HDMA_TABLE_CH3      = $C000     ; 1024 bytes ($C000-$C3FF)
HDMA_TABLE_CH4      = $C400     ; 1024 bytes ($C400-$C7FF)
HDMA_TABLE_CH5      = $C800     ; 1024 bytes ($C800-$CBFF)
HDMA_TABLE_CH6      = $CC00     ; 1024 bytes ($CC00-$CFFF)
HDMA_TABLE_CH7      = $D000     ; 1024 bytes ($D000-$D3FF)

; === Mode 7 HDMA Tables (WRAM bank $7E, $BE00+) ===
; Phase 16-0: packed-matrix Mode 3 continuous HDMA layout.
;
; Mode 7 and standard HDMA effects share the same WRAM region (mutually
; exclusive). When Mode 7 is active, standard HDMA tables ($C000-$D3FF) are
; repurposed for these two packed tables.
;
; Table format: HDMA Mode 3 (4 bytes per transfer to 2 consecutive PPU
; registers, continuous). Each scanline below the horizon gets a 5-byte entry:
;   [count=1, M7A_lo, M7A_hi, M7B_lo, M7B_hi]  (on CH_AB → $211B = M7A/M7B)
;   [count=1, M7C_lo, M7C_hi, M7D_lo, M7D_hi]  (on CH_CD → $211D = M7C/M7D)
; Terminator: a single $00 byte.
;
; Max size per table: 1 + 5 × 224 + 1 = 1122 bytes. Padded to 1280 bytes
; ($500) for alignment and margin.
;
; No horizon block. For scanlines above the horizon, HDMA simply terminates
; early and the PPU retains the M7A-D values last written — init writes
; identity ($0100/$0000/$0000/$0100) during `mode7_on`, so horizon scanlines
; render flat.
;
; No per-scanline H/V scroll tables. Mode 7 scroll is propagated through
; the existing ES_SHADOW_BG1HOFS / ES_SHADOW_BG1VOFS path (NMI phase 4
; writes $210D / $210E each frame). The M7HOFS/M7VOFS PPU registers are
; aliases of BG1 scroll; no dedicated Mode 7 scroll HDMA is needed.
;
; Single-buffered. The old 10-buffer double-buffered layout (5 tables × 2
; buffers) is dropped: build happens during the main thread's BUILD phase
; which completes before VBlank; HDMA reads during active display. No race.
; Empirically validated via racing_12_0.asm and stress_15_3.asm (both
; single-buffered, both render cleanly).
M7_HDMA_TBL_AB      = $BE00   ; 1280 bytes: M7A+M7B packed table ($BE00-$C2FF)
M7_HDMA_TBL_CD      = $C300   ; 1280 bytes: M7C+M7D packed table ($C300-$C7FF)

; === Phase 17-0a: HDMA Channel Allocator State ===
; Tracks which of the 8 HDMA channels (CH0-CH7) are currently allocated and
; which effect owns each. Lives in the Phase-16-reserved $C800-$CCFF block
; so it does not collide with the HDMA wave state ($0168-$0169) or TAD audio
; ($016A-$0173) that the 17-0A spec originally flagged as risks.
;
; Layout at $7E:C800-$C807 (8 bytes):
;   $C800  1 B  HDMA_ALLOC_MASK       — bitmask of allocated channels
;                                        (bit N = 1 iff CHn is in use)
;   $C801  1 B  HDMA_ALLOC_HIGH_WATER — max bit-count seen since init
;                                        (debug/budget aid; not functional)
;   $C802  6 B  HDMA_ALLOC_EFFECT_TBL — effect ID per channel (CH2..CH7;
;                                        CH0/CH1 are reserved for VBlank DMA
;                                        and are never allocated by this
;                                        module). Index: (channel - 2).
;                                        Effect IDs: $00 = free, $01..$FE
;                                        = owner, $FF = reserved-by-system.
; Phase 17-0b1 FIX: original 17-0a placement at $7E:C800 directly conflicts
; with HDMA_TABLE_CH5 = $C800 (Phase 4 HDMA table region). When an engine
; like `hdma_build_gradient` allocated CH5 and built its table there, the
; table writes silently clobbered the allocator's own state — invisible
; during 17-9/9b/10 testing because no composition exercised both systems.
; The migration moves the allocator state to the engine-state area (which
; has room past $01C3); the REQ scratch goes immediately after.
HDMA_ALLOC_MASK         = $01D0
HDMA_ALLOC_HIGH_WATER   = $01D1
HDMA_ALLOC_EFFECT_TBL   = $01D2    ; 6 bytes, indexed (ch - 2)
; $01D8-$01DC: REQ scratch (see engine/hdma_alloc.asm)
; $C810-$C814: HDMA_ALLOC_REQ_* scratch (NEEDED, EFFECT, CAND, PRIO, MODE) —
;              defined in engine/hdma_alloc.asm. Not exported here; listed
;              so future additions in this block don't collide.
; $C815-$CCFF: free for future allocator extensions / 17-9 split-mode tables.

; Allocator effect IDs (opaque — passed to hdma_request, stored in the
; per-channel effect table so hdma_release can verify ownership).
HDMA_EFFECT_FREE        = $00
HDMA_EFFECT_MODE7_AB    = $01      ; Mode 7 matrix A+B (continuous4)
HDMA_EFFECT_MODE7_CD    = $02      ; Mode 7 matrix C+D (continuous4)
HDMA_EFFECT_COLDATA_R   = $03
HDMA_EFFECT_COLDATA_G   = $04
HDMA_EFFECT_COLDATA_B   = $05
HDMA_EFFECT_BGMODE      = $06      ; Phase 17-9 split-mode BGMODE
HDMA_EFFECT_TM_OVERRIDE = $07      ; Phase 17-9 per-band TM/TS
HDMA_EFFECT_MODE7_HUD_BGMODE = $08 ; Phase 17-11 Mode 7 + Mode 1 HUD CH3 BGMODE
HDMA_EFFECT_STREAMING   = $09      ; Phase 17 Sprint B (final) BG1 tilemap streaming
HDMA_EFFECT_USER        = $80      ; user-space effects (gradient/wave/iris)
HDMA_EFFECT_RESERVED    = $FF      ; system-reserved (e.g., CH0/CH1)

; Allocator priority levels (higher priority wins when channel pressure
; exists — 17-0A implements greedy "first fit" and does not preempt; the
; priority field is retained for future preemption support).
HDMA_PRIO_LOW           = 0
HDMA_PRIO_MED           = 1
HDMA_PRIO_HIGH          = 2

; HDMA transfer-mode preferences — describe the shape of the transfer so
; the allocator can reject unsatisfiable requests in BM-009. Values match
; the $43n0 DMAP mode bits (low 3 bits).
HDMA_MODE_CONT1         = 0        ; 1 byte / 1 register
HDMA_MODE_CONT2         = 1        ; 2 bytes / 1 register (write-twice)
HDMA_MODE_CONT4         = 3        ; 4 bytes / 2 regs (Mode 7 matrix packed)
HDMA_MODE_INDIRECT1     = 4        ; 1 byte / 1 reg indirect
; The low 3 bits of these values can be written directly to a channel's
; DMAP register once the channel is assigned. Higher bits are reserved
; for direction/address-mode flags that effect code sets.


; === Mode 7 HDMA Channel Assignment (Phase 16 parameterization) ===
; Phase 16 parameterizes which HDMA channels Mode 7 claims, so the concrete
; channel numbers can be relocated without editing mode7_hdma.asm. Phase 17-0a
; (HDMA channel allocator) replaces these literal defaults with per-scene
; allocator output. Until then, defaults match the racing_12_0 / stress_15_3
; layout (CH5 + CH6, which leaves CH0-CH4 + CH7 free for COLDATA gradient,
; user HDMA, and OAM DMA).
;
; 17-0A NOTE: These equates are GRANDFATHERED for Phase 16. Scenes that do
; not declare `[scene.effects]` in superforge.toml continue to use them as
; compile-time literals. Scenes that DO declare `[scene.effects]` get an
; auto-generated `<scene>_hdma_alloc.inc` with `.define` overrides from
; `toolchain/hdma_alloc.py`. No existing ROM regresses.
;
; Effect declarations consuming this in Phase 17-0a:
;   [scene.effects]
;   mode7 = { channels = 2, mode = "continuous4" }   # → (CH_AB, CH_CD)
; Phase 17-13: M7_OWNED_MASK is the single source of truth for which HDMA
; channels Mode 7 currently owns. The engine NMI handler commits each
; channel's shadow registers (HDMA_CHn_DMAP/BBAD/TBL_LO/HI) to hardware
; iff the channel's bit is set in BOTH `NMI_HDMA_ENABLE` AND
; `M7_OWNED_MASK`. Channels enabled in NMI_HDMA_ENABLE but not owned by
; Mode 7 were programmed directly to hardware by their effect at
; activation; the NMI leaves their hardware regs alone and only re-arms
; $420C from NMI_HDMA_ENABLE.
;
; Bits: $04=CH2 .. $80=CH7. Default 0 (no Mode 7 active). Wrapper at
; engine/mode7_hdma_allocator.asm sets the mask on mode7_init/hud
; activation and clears bits on disable/hud_off.
;
; Slot at $50 was Phase 17-0b2's M7_CH_AB_NUM (runtime channel
; selection scaffolding the recovery merge made obsolete; Brad's port
; pins literals via M7_PV_HDMA_BITMASK = $60). Repurposed here. Slot at
; $51 (was M7_CH_CD_NUM) stays free.
M7_OWNED_MASK       = ENGINE_STATE_BASE + ES_M7_OWNED_MASK  ; 1 B: HDMA channels owned by Mode 7
M7_TMP_MASK         = $0583   ; 1 B: WRAM scratch for channel-mask assembly
                              ; (past HDMA_PHASE4_CH2_PIN at $0582; zero-init OK)
; Legacy HDMA channel constants (M7_HDMA_CH_AB/CD/*_BIT/CHANNELS_BITMASK)
; live in engine_state_m7_legacy.inc — only the frozen pre-Phase-16 engine
; and a handful of Phase 9 RGB gradient demos reference them. Brad's live
; port uses the Phase 17-0a allocator's pin via hdma_alloc_bootstrap(#$60).
M7_HDMA_MODE        = $03     ; Mode 3: 4 bytes per transfer, 2 regs, continuous.
                              ; Mode 2 + repeat and Mode 3 + repeat both corrupt
                              ; the M7A-D write-twice latch; see Phase 15 HANDOFF
                              ; §"HDMA mode" and Phase 16-0 DT-001.

; === Font System WRAM Regions (bank $7E) ===
; Font control block and manifest table. In the gap between warm globals ($0EFF)
; and the reserved program area ($2000). Must use long addressing (f:$7E0F00+) or DB=$7E.
WRAM_FONT_TABLE     = $0F00     ; 16 bytes: font control block ($0F00-$0F0F)
WFT_ACTIVE_FONT_ID  = $0F00    ; 2 bytes: currently selected font ID
WFT_ACTIVE_BASE_TILE = $0F02   ; 2 bytes: active font base tile index
WFT_WIDTH_TABLE_LO   = $0F04   ; 2 bytes: ROM address low of width table
WFT_WIDTH_TABLE_BK   = $0F06   ; 1 byte: ROM bank of width table
WFT_FONT_COUNT       = $0F07   ; 1 byte: number of fonts loaded (0-4)
; Phase 16-8 step 3 VWF infrastructure (2026-05-09): WFT_VWF_CURSOR_X,
; WFT_VWF_VRAM_BASE, WFT_VWF_WRAM_BUF were declared by the original Phase
; 3 font sprint but never read or written by the engine (engine_print_vwf
; uses local scratch VWF_SCRATCH_PIXEL_X — was $0588, see Phase 16-8
; step 3 dismiss-teleport bug fix: relocated to $0520 to clear the
; TILEMAP_WIDTH/HEIGHT alias). Reclaiming these 6 bytes for use as
; reserved-zero pad keeps the WFT layout stable for the issue #136
; user-font work without forcing a manifest reshuffle. See audit
; BUG-7 in docs/sprints/phase_16_8_step3_font_system_audit.md.
WFT_VWF_TILE_COUNT   = $0F0A   ; 2 bytes: tiles generated in current VWF render
WFT_RESERVED_0F08    = $0F08   ; 2 bytes: RESERVED (was WFT_VWF_CURSOR_X — dead)
WFT_RESERVED_0F0C    = $0F0C   ; 2 bytes: RESERVED (was WFT_VWF_VRAM_BASE — dead)
WFT_RESERVED_0F0E    = $0F0E   ; 2 bytes: RESERVED (was WFT_VWF_WRAM_BUF — dead)

; Font manifest table: 4 fonts x 12 bytes = 48 bytes ($0F10-$0F3F)
; Per entry: [id(1), flags(1), base_tile(2), tile_count(2),
;            width_tbl_lo(2), width_tbl_hi(1), width_tbl_bank(0+padding),
;            tile_data_lo(2), tile_data_bank(1)]
FONT_MANIFEST_BASE   = $0F10   ; 48 bytes ($0F10-$0F3F)
FONT_MANIFEST_ENTRY_SIZE = 12
FONT_MANIFEST_MAX    = 4

; Font manifest entry field offsets
FM_ID               = 0         ; 1 byte: font ID (0-3)
FM_FLAGS            = 1         ; 1 byte: bit 0=has_width_table, bit 1=loaded
FM_BASE_TILE        = 2         ; 2 bytes: VRAM tile index base
FM_TILE_COUNT       = 4         ; 2 bytes: number of tiles (typically 96)
FM_WIDTH_TBL_ADDR   = 6         ; 2 bytes: ROM address of width table (low 16)
FM_WIDTH_TBL_BANK   = 8         ; 1 byte: ROM bank of width table
FM_TILE_DATA_ADDR   = 9         ; 2 bytes: ROM address of tile data (low 16)
FM_TILE_DATA_BANK   = 11        ; 1 byte: ROM bank of tile data

; VWF tile render buffer: 24 tiles x 16 bytes = 384 bytes
; In the gap between HDMA/Mode 7 tables ($CCFF) and coroutine pool ($D400).
VWF_TILE_BUFFER     = $CD00     ; 384 bytes ($CD00-$CE7F)
VWF_TILE_BUFFER_SIZE = 384
VWF_MAX_TILES       = 24

; VWF VRAM region: rendered tiles DMA'd here during NMI.
;
; Phase 16-8 step 3 VWF infrastructure (2026-05-09): the legacy values
; (`VWF_VRAM_BASE = $E600`, `VWF_VRAM_BASE_TILE = 288`) were both broken
; and arithmetically inconsistent. Tile 288 aliased onto font 1's CHR
; range (256..351); tile 288 word-resolves to BG3 chr base + 288*8 = $A900,
; not $E600. See `docs/sprints/phase_16_8_step3_font_system_audit.md` BUG-2
; and BUG-3.
;
; The fix relocates VWF tiles to a slot beyond all 4 built-in fonts:
;   font 0 owns tiles 160..255 (clean,    monospace)
;   font 1 owns tiles 256..351 (dialog,   VWF)
;   font 2 owns tiles 352..447 (frame,    monospace)
;   font 3 owns tiles 448..543 (reserved built-in slot)
;   VWF buffer owns tiles 544..567 (24 tiles, 384 bytes)
;   tiles 568..767 RESERVED for user-supplied fonts (issue #136)
;
; Math (BG3 chr base = word $A000, each tile = 8 words = 16 bytes):
;   VWF_VRAM_BASE_TILE = 544
;   word offset from chr base = 544 * 8 = 4352 = $1100
;   VWF_VRAM_BASE (word) = $A000 + $1100 = $B100
;   buffer covers VRAM word $B100..$B1BF (384 bytes = $180 bytes)
;
; ISSUE #136 NOTE — user-supplied fonts must allocate base_tile values
; in the range 568..767 (or 544..767 if VWF is not in use). The build-time
; allocator in toolchain/build.py BASE_TILES table has hardcoded slots
; for ids 0..3; the issue #136 agent must extend that table with a
; collision-checked allocator that respects this VWF reservation.
VWF_VRAM_BASE       = $B100    ; 384 bytes in VRAM ($B100-$B27F byte)
VWF_VRAM_BASE_TILE  = 544      ; tile index relative to BG3 chr base $A000

; VWF dirty flag (WRAM scratch, checked by NMI).
;
; Phase 16-8 step 3 VWF infrastructure (2026-05-09): relocated from $0586
; (which aliased TEXT_SCRATCH_NLEFT and HDMA_WAVE_SIGN — see audit BUG-5)
; to $0587. The new slot is reserved for VWF only and is not aliased.
; The NMI handler (engine/nmi_handler.asm Phase 3D) drains VWF_DIRTY by
; DMAing $7E:CD00..$CE7F to VRAM word $B100 every frame the flag is set.
VWF_DIRTY           = $0587    ; 1 byte: 1 = VWF buffer needs DMA to VRAM

; === RGB Gradient HDMA Scratch (WRAM $0630-$0656) ===
; Used by hdma_build_gradient_rgb and hdma_build_gradient_stops.
; Placed after iris Bresenham table ($05A0-$0625) with 10-byte gap.
HDMA_GRAD_RGB_TOP_R   = $0630   ; 2 bytes: top red intensity (0-31)
HDMA_GRAD_RGB_TOP_G   = $0632   ; 2 bytes: top green intensity (0-31)
HDMA_GRAD_RGB_TOP_B   = $0634   ; 2 bytes: top blue intensity (0-31)
HDMA_GRAD_RGB_BOT_R   = $0636   ; 2 bytes: bottom red intensity (0-31)
HDMA_GRAD_RGB_BOT_G   = $0638   ; 2 bytes: bottom green intensity (0-31)
HDMA_GRAD_RGB_BOT_B   = $063A   ; 2 bytes: bottom blue intensity (0-31)
HDMA_GRAD_RGB_ACCUM_R = $063C   ; 2 bytes: red accumulator (8.8 fixed-point)
HDMA_GRAD_RGB_ACCUM_G = $063E   ; 2 bytes: green accumulator (8.8 fixed-point)
HDMA_GRAD_RGB_ACCUM_B = $0640   ; 2 bytes: blue accumulator (8.8 fixed-point)
HDMA_GRAD_RGB_STEP_R  = $0642   ; 2 bytes: red step per scanline (8.8, signed)
HDMA_GRAD_RGB_STEP_G  = $0644   ; 2 bytes: green step per scanline (8.8, signed)
HDMA_GRAD_RGB_STEP_B  = $0646   ; 2 bytes: blue step per scanline (8.8, signed)
HDMA_GRAD_RGB_CH_R    = $0648   ; 2 bytes: allocated HDMA channel for red
HDMA_GRAD_RGB_CH_G    = $064A   ; 2 bytes: allocated HDMA channel for green
HDMA_GRAD_RGB_CH_B    = $064C   ; 2 bytes: allocated HDMA channel for blue
HDMA_GRAD_RGB_EASING  = $064E   ; 1 byte:  easing type (0=linear, 1=ease-in, 2=ease-out, 3=smoothstep)
HDMA_GRAD_RGB_FLAGS   = $064F   ; 1 byte:  bit0=animated, bit1=stops dirty
HDMA_GRAD_PHASE       = $0650   ; 2 bytes: animation phase (8.8, auto-incremented by NMI)
HDMA_GRAD_SPEED       = $0652   ; 2 bytes: phase increment per frame (8.8)
HDMA_GRAD_STOP_ADDR   = $0654   ; 2 bytes: pointer to stop array in WRAM
HDMA_GRAD_STOP_COUNT  = $0656   ; 1 byte:  number of stops (2-16)

; RGB gradient table layout within HDMA table memory ($7E:C000+)
; Each channel gets 452 bytes (225 entries × 2 bytes + 2 terminator)
; HDMA format: [count_byte=1, data_byte] per scanline
HDMA_RGB_TBL_R        = $C000   ; 452 bytes: CH3 red table ($C000-$C1C3)
HDMA_RGB_TBL_G        = $C1C4   ; 452 bytes: CH4 green table ($C1C4-$C387)
HDMA_RGB_TBL_B        = $C388   ; 452 bytes: CH5 blue table ($C388-$C54B)

; === Tile Flag Tables for col_map (WRAM bank $7E, $CE80+) ===
; Per-layer flag tables for terrain collision detection.
; Each layer: 256 tiles × 1 byte = 256 bytes (tiles 0-255).
; Kit-scale tilemaps use at most 256 distinct tiles per layer.
; Must use long addressing (f:$7ECE80+) or set DB=$7E.
FLAG_TABLE_BG1      = $CE80    ; 256 bytes: BG1 tile flags ($CE80-$CF7F)
FLAG_TABLE_BG2      = $CF80    ; 256 bytes: BG2 tile flags ($CF80-$D07F)
FLAG_TABLE_BG3      = $D080    ; 256 bytes: BG3 tile flags ($D080-$D17F)
FLAG_TABLE_ENTRY_SIZE = 256    ; bytes per layer flag table

; Per-layer tilemap dimensions (engine state low WRAM, scratch area)
TILEMAP_WIDTH_BG1   = $0588    ; 1 byte: BG1 tilemap width in tiles (default 32)
TILEMAP_WIDTH_BG2   = $0589    ; 1 byte: BG2 tilemap width in tiles (default 32)
TILEMAP_WIDTH_BG3   = $058A    ; 1 byte: BG3 tilemap width in tiles (default 32)
TILEMAP_HEIGHT_BG1  = $058B    ; 1 byte: BG1 tilemap height in tiles (default 32)
TILEMAP_HEIGHT_BG2  = $058C    ; 1 byte: BG2 tilemap height in tiles (default 32)
TILEMAP_HEIGHT_BG3  = $058D    ; 1 byte: BG3 tilemap height in tiles (default 32)

; === BG1 Tilemap Streaming (Phase 17 Sprint A) ===
; -----------------------------------------------------------------------------
; *** VESTIGIAL — Mode 1 BG1 HORIZONTAL-ONLY; NOT A SHIPPED KIT RAIL. ***
; *** Do NOT build a Mode 7 streaming world on this block. ***
; This STREAM_* metadata is the Phase-17 normal-BG (Mode 1) horizontal column-
; streaming residue. Its PRODUCER routines (engine/streaming_engine.asm) are NOT
; materialized into the kit (not in dryrun_split.sh ENGINE_FILES), so this is a
; FALSE FOOTHOLD — the names exist but nothing drives them in the kit. It is
; single-axis (columns only), tied to the 64-column Mode 1 hardware tilemap, and
; has no Mode 7 path. It is kept (not deleted) only because a future Mode-1
; normal-BG large-world rail may revive it.
;
; For a 2-AXIS Mode 7 STREAMING world (the SHIPPED `mode7_explore` rail), use the
; proven substrate instead: engine/mode7_stream.asm + engine/mode7_stream_nmi.inc
; (the M7S_* state below this file's Mode 7 streaming block) via the kit macro
; lib/macros/sf_mode7_stream.inc. See docs/guides/mode7_overworld_streaming.md.
; -----------------------------------------------------------------------------
; Streaming metadata for BG1-tilemap "sliding window" — when a level is wider
; than the 64-column hardware tilemap, columns 8 ahead of the camera's
; leading edge are kept fresh by per-frame VBlank DMA into the wrap zone.
; SHADOW_BG1_TILEMAP at $7E:A200 is NOT touched (Sprint A skips it; Sprint B
; handles col_map rework for streamed templates).
;
; Allocation: $0590-$05A0 (17 bytes, low-WRAM scratch). Range $0590-$05FF
; was unused before Phase 17.
;
; Cooperative NMI protocol: the streaming routine sets STREAM_PENDING=1 with
; the column's VRAM address + 24-bit ROM source. The test ROM's NMI handler
; (or a future engine-NMI extension) executes the column DMA inline and
; clears STREAM_PENDING. The 12-8c streaming pipeline established this
; pattern; Sprint A reuses it to avoid extending the GP-DMA queue with
; per-entry VMADD writes.
STREAM_LEVEL_DATA_PTR = $0620  ; 3 bytes: 24-bit ROM pointer to level data
                                ; (RELOCATED from $0590 — collided with save_load_engine
                                ;  scratch + something else that triggers freeze on writes
                                ;  to $059D-$059F. $0620-$062F is the 16-byte gap between
                                ;  iris Bresenham table ($05A0-$061F) and HDMA gradient
                                ;  scratch ($0630-$0656). Verified open via grep.)
STREAM_LEVEL_DATA_PTR_OLD = $0590  ; old location (unused)
                                 ; (column-major: 32 tiles × 2 bytes per column)
STREAM_LEVEL_WIDTH_T  = $0623  ; 2 bytes: level width in tiles (e.g., 256)
STREAM_CAM_COL        = $0625  ; 2 bytes: current camera column index (cam_x / 16)
STREAM_LAST_COL       = $0627  ; 2 bytes: last column written to wrap zone
                                 ; (advances by 1 each time a column is queued)
STREAM_ACTIVE         = $0629  ; 1 byte: 0 = streaming disabled, nonzero = active

; STREAM_PENDING — semantics changed by streaming-speed-cap experiment:
; previously a 0/1 flag; now a queue COUNT (0..STREAM_PENDING_MAX_SLOTS).
; NMI handler drains all queued slots in sequence, decrementing the count
; to zero. Main thread's streaming_update_bg1 may queue up to MAX slots
; per frame (currently 4), enabling speeds well above the 1-slot ceiling
; of ~8 px/frame. Each additional slot supports an extra 8 px/frame of
; sustained scroll speed.
STREAM_PENDING        = $062A  ; 1 byte: queue count (0..STREAM_PENDING_MAX_SLOTS)

; Phase 17 Sprint D-9: bidirectional streaming.
; STREAM_FIRST_COL is the lowest world column currently held in the 64-col
; ring window. Invariant maintained by streaming_init / compute_next_col:
;   STREAM_LAST_COL - STREAM_FIRST_COL == 63 (after boot completes).
; Forward streaming advances both by 1 per queued column; reverse streaming
; retreats both by 1 per queued column. This lets the engine repopulate
; ring slots when the camera scrolls left after previously scrolling right
; (without it, slots hold stale data from the right-edge sweep — visible
; as ghost tiles AND reproduced into SHADOW_BG1_TILEMAP, so col_map also
; sees fake walls). See docs/dx_paper_cuts.md "Phase 17 Sprint D-9".
STREAM_FIRST_COL      = $062C  ; 2 bytes: lowest world col in ring window

; Legacy aliases for slot 0. The pre-experiment design exposed exactly
; these two addresses; tests/phase_streaming/test_streaming_4096.asm
; reads them after a single streaming_compute_next_col call. We keep
; the names pointing at slot 0 of the new contiguous queue table so the
; legacy test keeps passing without edits.
STREAM_PENDING_VADDR  = $0660  ; 2 bytes: VRAM word addr (slot 0)
STREAM_PENDING_SRC    = $0662  ; 3 bytes: 24-bit ROM src ptr (slot 0)

; Pending-slot queue. 4 slots × 5 bytes = 20 bytes ($0660..$0673).
; Layout per slot: VADDR(2) | SRC(3). Indexed access: slot N starts at
; STREAM_PENDING_TBL + N*5. NMI dispatch + main-thread queue both rely
; on this contiguous layout for indexed addressing. Range $0657-$07FF
; was unused before the speed-cap experiment (verified by grep on
; engine_state.inc).
STREAM_PENDING_TBL    = $0660  ; base of the slot queue
STREAM_PENDING_SLOT_SZ = 5     ; bytes per slot
; S2a: bumped 4 -> 8. With a 64x64 tilemap a streamed COLUMN spans 64 rows,
; crossing the row-32 page seam, so each queued column now emits TWO sub-slots
; (A: rows 0..31, B: rows 32..63). 8 slots = up to 4 columns/frame of forward
; streaming headroom. Table = $0660..$0687 (8*5=40B); the row queue starts at
; $0720, clear of this range.
STREAM_PENDING_MAX_SLOTS = 8   ; col sub-slot capacity (= 4 cols x 2 halves)

; Phase 17 Sprint B (final): allocated DMA channel number (2..7).
; Replaces the Sprint A hardcoded CH7 so streaming coexists with Mode 7
; HDMA. Set by streaming_init via hdma_request; consumed by both boot
; bulk DMA and per-frame streaming. The absolute address aliases
; ES_STREAM_DMA_CHAN at DP $99 (= ENGINE_STATE_BASE + $99 = $0199).
STREAM_DMA_CHAN       = $0199  ; 1 byte: allocated DMA channel (2..7)

; =============================================================================
; Mode-1 BG1 VERTICAL (row) streaming — Streaming rail Mode 1 / Sprint S2a.
; =============================================================================
; The NET-NEW vertical axis that completes the 2-axis (horizontal + vertical)
; normal-BG streaming substrate. Mirrors the horizontal STREAM_* block above
; ($0620 metadata + $0660 slot queue) but for ROWS. The tilemap is widened to
; 64x64 (BG1SC=$5B) so there is ring room on BOTH axes: 64 cols x 64 rows of
; resident VRAM tilemap, with a 32x28-tile visible window. The producer
; (engine/bg_stream_row.asm) stages a leading-edge ROW as cam_y crosses 8px
; tile boundaries, position-wraps it into the ring (world_row & $3F), and
; queues a VBlank row DMA (stride-1) into the NMI consumer's ROW drain.
;
; A row spans the full 64-col ring width, which crosses the 64x64 page seam at
; col 32 (SC0/SC2 on the left, SC1/SC3 on the right). So each queued ROW emits
; TWO sub-slots (A: cols 0..31, B: cols 32..63), each a 32-word stride-1 DMA.
; (The horizontal column path is symmetric: a column spans 64 rows, crossing
; the row-32 page seam, so it also emits TWO sub-slots — A: rows 0..31, B:
; rows 32..63. See STREAM_PENDING_MAX_SLOTS bump below.)
;
; This block lives at $0680-$06B7 (verified free: the horizontal queue ends at
; STREAM_PENDING_TBL+8*5-1 = $0687 after the MAX_SLOTS bump; the row block
; starts safely above at $0690... wait — recompute: bumped col table is
; $0660..$0687 (8*5=40B). Row metadata $0680-$068F overlaps! RELOCATED row
; metadata to $0700 and row queue to $0720 to clear the bumped col table.)
STREAM_ROW_LEVEL_PTR  = $0700  ; 3 bytes: 24-bit ROM ptr to ROW-MAJOR level data
STREAM_LEVEL_HEIGHT_T = $0703  ; 2 bytes: level height in tiles (e.g. 128)
STREAM_CAM_ROW        = $0705  ; 2 bytes: current camera row index (cam_y >> 3)
STREAM_LAST_ROW       = $0707  ; 2 bytes: highest world row held in ring window
STREAM_ROW_ACTIVE     = $0709  ; 1 byte: 0 = row streaming off, 1 = on
STREAM_ROW_PENDING    = $070A  ; 1 byte: row sub-slot queue count (0..MAX)
STREAM_FIRST_ROW      = $070C  ; 2 bytes: lowest world row held in ring window
; Row pending-slot queue. Same 5-byte layout as the column queue: VADDR(2) |
; SRC(3). 8 slots x 5 bytes = 40 bytes ($0720-$0747). 8 slots because one
; queued ROW = 2 sub-slots and the per-frame clamp allows up to 4 rows/frame
; (vertical max speed headroom) — but 8 sub-slots = 4 rows; sized to match.
STREAM_ROW_PENDING_TBL = $0720 ; base of the row slot queue
STREAM_ROW_PENDING_MAX_SLOTS = 8   ; row sub-slot capacity (= 4 rows x 2 halves)
; Row staging buffers. A streamed ROW covers the 64 world columns currently in
; the horizontal ring window [FIRST_COL, FIRST_COL+63]; those columns map to
; col slots (world_col & $3F) which ROTATE as the camera pans horizontally. So
; the producer STAGES the row's 64 tile words into a WRAM buffer indexed by col
; SLOT (buf[col & $3F] = tile word) — wrap handled in the staging loop — then
; queues TWO DMA sub-slots that copy the buffer's slot-0..31 half to the SC0/SC2
; VRAM page and the slot-32..63 half to the SC1/SC3 page (page-aligned, no
; slot-wrap inside a DMA). Two buffers (double-buffer: up to 2 rows can be in
; flight between main-thread queue and the next VBlank drain without the second
; row's staging clobbering the first's not-yet-DMA'd data).
;   $0760-$07DF  STREAM_ROW_STAGE0  64 words = 128 bytes (slots 0..63)
;   $07E0-$085F  STREAM_ROW_STAGE1  64 words = 128 bytes (slots 0..63)
; (Each buffer is 64 col-slots x 2 bytes = 128 bytes; with COUNT=2 the double-
; buffer spans $0760-$085F = 256 bytes contiguous. STAGE_IDX MUST live OUTSIDE
; this span — it previously sat at $0840, INSIDE STAGE1 ($07E0-$085F), so
; staging an idx=1 (odd) row's col-slot 48 word landed on $0840 and corrupted
; STAGE_IDX mid-stage; the next _bsr_stage_base then computed a garbage buffer
; base and the row DMA read engine state instead of the staged row. This was
; the primary S2a vertical-streaming corruption — relocated to $0860, the first
; byte past the buffers.)
STREAM_ROW_STAGE_BUFS  = $0760 ; base of the row staging double-buffer
STREAM_ROW_STAGE_SZ    = $0080 ; 128 bytes per staging buffer (64 words)
STREAM_ROW_STAGE_COUNT = 2     ; number of staging buffers (double-buffer)
STREAM_ROW_STAGE_IDX   = $0860 ; 1 byte: next staging buffer index (0/1), rolls
                               ; — OUTSIDE the $0760-$085F buffer span (was $0840)

; =============================================================================
; Mode 7 2-axis tilemap streaming (engine/mode7_stream.asm) — Streaming rail v2.
; =============================================================================
; A SEPARATE substrate from the dormant Phase-17 Mode-1 BG1 STREAM_* block
; above (that one is single-axis, BG1, $0660-tbl based — NOT reused here). This
; block is the proven overhead-racing 2-axis (row + column) Mode 7 streaming:
; staging buffers in low WRAM, a per-frame main-thread tick that diffs the
; camera tile position and fills the buffers at the VRAM-WRAPPED position
; (coord & $7F), and an NMI VBlank dispatcher that DMAs the staged rows/cols
; into the Mode 7 VRAM tilemap (low bytes only — leaves the CHR high bytes).
;
; WRAM layout ($7E:3A00-$4229, free in the kit — verified grep-clean):
;   $3A00-$3DFF  M7S_ROW_BUF   8 slots x 128B = 1024B  (staged row tile-ids)
;   $3E00-$41FF  M7S_COL_BUF   8 slots x 128B = 1024B  (staged col tile-ids)
;   $4200-$4201  M7S_ROW_COUNT 2B   pending row count (0..8)
;   $4202-$4203  M7S_COL_COUNT 2B   pending col count (0..8)
;   $4204-$4213  M7S_ROW_VADDR 8x2B VRAM word addr per staged row
;   $4214-$4223  M7S_COL_VADDR 8x2B VRAM word addr per staged col
;   $4224-$4225  M7S_NMI_COUNT 2B   NMI dispatch loop remaining
;   $4226-$4227  M7S_NMI_IDX   2B   NMI dispatch VADDR table index
;   $4228-$4229  M7S_CAM_TX    2B   camera tile X in world space (0..WORLD-1)
;   $422A-$422B  M7S_CAM_TY    2B   camera tile Y in world space
;   $422C-$422D  M7S_LAST_TX   2B   last-streamed tile X
;   $422E-$422F  M7S_LAST_TY   2B   last-streamed tile Y
;   $4230        M7S_ACTIVE    1B   0 = streaming off, 1 = on
M7S_ROW_BUF     = $3A00
M7S_COL_BUF     = $3E00
M7S_ROW_COUNT   = $4200
M7S_COL_COUNT   = $4202
M7S_ROW_VADDR   = $4204
M7S_COL_VADDR   = $4214
M7S_NMI_COUNT   = $4224
M7S_NMI_IDX     = $4226
M7S_CAM_TX      = $4228
M7S_CAM_TY      = $422A
M7S_LAST_TX     = $422C
M7S_LAST_TY     = $422E
M7S_ACTIVE      = $4230
; --- streaming tick WRAM scratch ($4232-$423F, call-scoped) ---
;   $4232  M7S_SCR_DSTBASE  2B  dest buffer base (M7S_ROW_BUF/COL_BUF + slot*64)
;   $4234  M7S_SCR_SRC      2B  current source coord (column or row), wraps
;   $4236  M7S_SCR_TILE     2B  tile-id just read from flat ROM
;   $4238  M7S_SCR_FIXCOL   2B  fixed source column (column-stage path)
;   $423A  M7S_SCR_SLOT     2B  slot byte index (saved across the longptr build)
M7S_SCR_DSTBASE = $4232
M7S_SCR_SRC     = $4234
M7S_SCR_TILE    = $4236
M7S_SCR_FIXCOL  = $4238
M7S_SCR_SLOT    = $423A
M7S_SCR_LOOP    = $423C        ; 2B: tick OUTER loop counter (helpers don't touch)
M7S_MAX         = 8            ; max rows/cols streamed per frame (>= max tiles/frame)
M7S_HALF        = 64           ; half the 128-tile VRAM window (leading-edge offset)

; --- Mode 7 streaming DP scratch (transient, tick-call-scoped: $9A-$9E free) ---
; Only the 24-bit flat-ROM POINTER lives in DP (an indirect-long `[<dp],y` read
; requires a DP operand). All other tick scratch lives in the WRAM block above.
; TRANSIENT — valid only during one mode7_stream_tick call; never nested.
; $9A-$9C is within the verified-free $9A-$9E DP block.
ES_M7S_PTR      = $9A          ; 3 bytes: 24-bit flat-ROM tilemap pointer

; Col_map flag bit definitions (standard 8-flag convention)
TILE_FLAG_SOLID     = 0        ; bit 0: solid / wall
TILE_FLAG_PLATFORM  = 1        ; bit 1: one-way platform
TILE_FLAG_HAZARD    = 2        ; bit 2: damage / hazard
TILE_FLAG_WATER     = 3        ; bit 3: water / liquid
TILE_FLAG_LADDER    = 4        ; bit 4: ladder / climbable
TILE_FLAG_TRIGGER   = 5        ; bit 5: trigger zone
TILE_FLAG_USER0     = 6        ; bit 6: user-defined
TILE_FLAG_USER1     = 7        ; bit 7: user-defined

; === Scene Index Table (ROM) ===
; Each entry: 16 bytes per scene
; [bc_addr_lo(2), bc_addr_hi(1), bc_size(2),
;  asset_addr_lo(2), asset_addr_hi(1), asset_size(2),
;  init_pc(2), flags(1), audio_bank(1), reserved(2)]
SCENE_INDEX_ENTRY_SIZE = 16

; Scene index entry field offsets
SI_BC_ADDR_LO      = 0        ; 2 bytes: program ROM address (low 16)
SI_BC_ADDR_BK      = 2        ; 1 byte:  program ROM bank
SI_BC_SIZE          = 3        ; 2 bytes: program size in bytes
SI_ASSET_ADDR_LO   = 5        ; 2 bytes: asset list ROM address (low 16)
SI_ASSET_ADDR_BK   = 7        ; 1 byte:  asset list ROM bank
SI_ASSET_SIZE       = 8        ; 2 bytes: total asset size
SI_INIT_PC          = 10       ; 2 bytes: _init() entry point PC (offset within scene program)
SI_FLAGS            = 12       ; 1 byte:  scene flags (bit 0 = has_flag_table)
SI_AUDIO_BANK       = 13       ; 1 byte:  audio bank ID ($FF = no audio)
SI_RESERVED         = 14       ; 2 bytes: reserved

; Scene program WRAM layout
SHARED_BC_BASE      = $2000    ; 4 KB shared segment ($2000-$2FFF)
SCENE_BC_BASE       = $3000    ; 28 KB scene segment ($3000-$9FFF)
SCENE_BC_MAX_SIZE   = $7000    ; 28672 bytes max per scene

; === DMA Queue (absolute WRAM) ===
DMA_QUEUE_BASE      = $0200     ; 32 entries x 8 bytes = 256 bytes ($0200-$02FF)
DMA_QUEUE_MAX       = 32
DMA_QUEUE_ENTRY_SZ  = 8
VBLANK_DMA_BUDGET   = 5500      ; Conservative default (bytes)

; DMA queue entry field offsets
DMA_ENT_PRIORITY    = 0         ; 1 byte
DMA_ENT_DMAP        = 1         ; 1 byte: DMA channel config
DMA_ENT_BBAD        = 2         ; 1 byte: PPU destination register
DMA_ENT_SRC_LO      = 3         ; 2 bytes: source address low
DMA_ENT_SRC_BANK    = 5         ; 1 byte: source bank
DMA_ENT_SIZE         = 6         ; 2 bytes: transfer size

; === Shadow OAM (absolute WRAM) ===
SHADOW_OAM_BASE     = $0300     ; 512 bytes low table ($0300-$04FF)
SHADOW_OAM_HI       = $0500     ; 32 bytes high table ($0500-$051F)
SHADOW_OAM_TOTAL    = 544       ; 512 + 32 bytes (full OAM)

; === VWF Render Scratch (WRAM $0520-$0527) ===
; 8 bytes used by engine_print_vwf / engine_print_chars_vwf during a single
; render call (PIXEL_X, BUF_START, TILE_START, TILES_USED — symbols defined
; in engine/text_engine.asm). Range $0520-$053F was free before this claim;
; this block reserves the first 8 bytes and leaves $0528-$053F open.
;
; Phase 16-8 step 3 dismiss-teleport bug (2026-05-09): the previous VWF
; scratch lived at $0588-$058F and aliased TILEMAP_WIDTH_BG{1,2,3} +
; TILEMAP_HEIGHT_BG{1,2,3}. Each VWF render trashed the live tilemap
; dimension globals; col_map then computed wrong byte offsets and the
; platformer dialog dismiss left the player teleporting into the sky.
; See dx_paper_cuts.md for the full mechanism.
VWF_SCRATCH_RESERVED_LO = $0520 ; 8 bytes reserved (see text_engine.asm)
VWF_SCRATCH_RESERVED_HI = $0527

; === Sprite Sort Buffers (WRAM bank $7E, engine heap region $A000+) ===
; These addresses are in WRAM above $2000. In LoROM, bank $00 maps $A000+ to ROM,
; so code accessing these MUST set DB=$7E first (or use long addressing with f:).
; The sort/scanline routines set DB=$7E on entry and restore DB=$00 on exit.
SPR_SORT_INDEX      = $A000     ; 128 bytes: maps logical -> OAM slot for sorting
SPR_SORT_KEYS       = $A080     ; 128 bytes: Y position or priority for sort keys
SPR_SCANLINE_COUNTS = $A100     ; 224 bytes: per-scanline sprite count (scanlines 0-223)

; === BG Shadow Tilemaps (WRAM bank $7E, engine heap $A200+) ===
; Each 32x32 tilemap = 2048 bytes. Must set DB=$7E to access.
SHADOW_BG1_TILEMAP  = $A200     ; 2048 bytes: BG1 shadow tilemap ($A200-$A9FF)
                                ; NOTE: $F000-$F2FF is claimed by
                                ; sprite_engine.asm's SPR_REMAP_TEMP(+_HI)
                                ; (relocated 2026-06-11 from $A200, which
                                ; sat INSIDE this shadow map — see the BUG
                                ; FIX comment in sprite_engine.asm)
SHADOW_BG2_TILEMAP  = $AA00     ; 2048 bytes: BG2 shadow tilemap ($AA00-$B1FF)
SHADOW_BG3_TILEMAP  = $B200     ; 2048 bytes: BG3 shadow tilemap ($B200-$B9FF)

; === Shadow CGRAM and Palette Engine (WRAM bank $7E, $BA00+) ===
; Must set DB=$7E to access.
SHADOW_CGRAM        = $BA00     ; 512 bytes: shadow CGRAM ($BA00-$BBFF)
PAL_CYCLE_DESCS     = $BC00     ; 256 bytes: 4 descriptors x 64 bytes ($BC00-$BCFF)
PAL_ROM_DEFAULTS    = $BD00     ; 512 bytes: ROM default palette backup ($BD00-$BEFF)

; === Stack ===
STACK_TOP           = $1FFF     ; Stack grows down from here

; === PPU Register Init Values (Decision D9, locked) ===
; These are the register values written during bg_init. They encode VRAM word
; addresses, not byte addresses. See CLAUDE.md "PPU Register Encoding" for
; the bit-field details and Mesen2 verification source.
;
; BGnSC: tilemap base = (value & $7C) << 8  (word address)
; BG12NBA: BG1 chr = (value & $07) << 12, BG2 chr = (value & $70) << 8
PPU_BG1SC_VALUE     = $58       ; Tilemap at word $5800 (byte $B000), 32x32
PPU_BG2SC_VALUE     = $5C       ; Tilemap at word $5C00 (byte $B800), 32x32
PPU_BG3SC_VALUE     = $60       ; Tilemap at word $6000 (byte $C000), 32x32
PPU_BG12NBA_VALUE   = $42       ; BG1 chr word $2000, BG2 chr word $4000

; Phase 17 Sprint D-5 (Bug A): streaming-mode BG2 tilemap location. When
; BG1 is in 64×32 streaming layout (BG1SC=$59), VRAM word $5800-$5FFF is
; OWNED by BG1's two pages; the static BG2SC=$5C value would alias BG1
; page 1 ($5C00-$5FFF). Streaming-mode boot relocates BG2 tilemap to VRAM
; word $4800-$4BFF (just above BG2 chr at $4000-$47FF, no overlap).
;
;   BGnSC encoding: tilemap_word_addr = (value & $7C) << 8
;   $48 & $7C = $48 → tilemap at word $4800. Size bits $00 = 32×32.
;
; BG2 chr remains at word $4000 (BG12NBA=$42 unchanged); the new layout
; assumes BG2 chr fits in the 2KB span $4000-$47FF, which is enough for
; 64 4bpp tiles or 128 2bpp tiles. The platformer-template sky uses ~14
; tiles; airship/RPG/etc. are static-mode and unaffected.
PPU_BG2SC_STREAMING_VALUE = $48 ; Tilemap at word $4800 (byte $9000), 32x32
PPU_BG2_VRAM_HI_STREAMING = $48 ; high byte of VRAM word $4800
PPU_BG2_VRAM_HI_STATIC    = $5C ; high byte of VRAM word $5C00
PPU_BG34NBA_VALUE   = $0A       ; BG3 chr at word $A000
PPU_BGMODE_MODE1    = $09       ; Mode 1, BG3 priority=1, 8x8 tiles

; =============================================================================
; Phase 17-0: BG Mode Dispatch State (Direct Page, main-thread DP=$0000)
; =============================================================================
; Claimed in docs/sprints/phase_17_allocations.md §1 ($38-$3F). Holds the
; cross-call state the generalized engine_gfxmode dispatcher needs so callers
; and tests can observe the last requested mode and whether a call was
; rejected. Free per docs/sprints/phase_15_allocations.md §2.1.
;
; Accessed via DP addressing when DP=$0000 (main thread / test ROMs). These
; are distinct from the engine-state WRAM variables at $0100+ (SHADOW_BGMODE,
; GFXMODE_STATE); the new ZP bytes are not shadowed there.
BG_MODE_CURRENT         = $38   ; 1 byte: current mode (0, 1, 2, 3, 4, or 7)
BG_MODE_PREVIOUS        = $39   ; 1 byte: mode before the most recent gfxmode()
BG_MODE_PENDING         = $3A   ; 1 byte: reserved for 17-9 split-mode pending
BG_MODE_DISPATCH_FLAGS  = $3B   ; 1 byte: bit 0 = last call rejected (out of range)
; $3C-$3F (ZP page 0): 4 bytes free (was BG_MODE_RESERVED_3C; reserved for
; 17-3/17-9 dispatcher state, but neither sub-phase needed DP-fast cursor
; state in ZP page 0 — 17-3 uses existing SHADOW_BGMODE at $0100+ and
; 17-9's cursor is in engine state at $B8/$B9). Audit 2026-04-22 confirmed
; no references across engine/*.asm.

.endif  ; _ENGINE_STATE_INC_INCLUDED
