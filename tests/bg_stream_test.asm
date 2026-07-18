; =============================================================================
; bg_stream_test — proof ROM for the Mode-1 normal-BG horizontal column-
;                  streaming rail (Streaming rail Mode 1 / Sprint S1).
; =============================================================================
; Scripts a SCRIPTED camera (no player physics yet) panning a WIDE authored
; Four Seasons platformer level (256 tiles = 8 screens wide x 32 tall) PAST the
; 64-column BG1 hardware tilemap, and proves the horizontal streaming substrate
; renders NEW authored content into the resident VRAM window with no stale/
; garbage strips and no black band — forward (right), reverse (left), and idle.
;
; The level is loaded as a flat COLUMN-MAJOR ROM tilemap (tools/level_pipeline_bg.py
; -> level_flat.bin, 64 bytes/column). bg_stream.asm (the producer) keeps the
; 64-col ring fresh as STREAM_CAM_COL advances; the kit NMI handler's
; STREAM_PENDING drain DMAs queued columns into BG1 VRAM during VBlank.
;
; UNITS: the level is authored as 8px tile columns, so STREAM_CAM_COL is set in
; TILE-column units (cam_x >> 3) by sf_stream_set_cam, matching the producer's
; look-ahead. BG1HOFS is set to cam_x so the hardware scrolls within the ring.
;
; Camera script (deterministic, frame-counter driven — NO input):
;   phase 0 (frames    1..224):  pan EAST (+8 px/frame)  — streams cols forward
;   phase 1 (frames  225..448):  pan WEST (-8 px/frame)  — streams cols reverse
;   phase 2 (frames  449..):     IDLE                    — no streaming
; 8 px/frame = 1 tile column/frame. The level is 256 tiles (2048 px) wide;
; the screen is 32 tiles (256 px). 224 frames east = 1792 px = the level's
; right edge (cam_x = world_w - screen_w), so the camera walks the FULL wide
; level past the 64-col resident VRAM window (cols 0..223 stream in), then
; reverses back to col 0 (reverse streaming), then idles.
;
; Done-condition (emulator-verifiable, asserts on the RENDERED DESTINATION):
;   - boots ($7E:E000 == "SFDB"); heartbeat at $7E:E010 advances.
;   - the python test reads the BG1 VRAM tilemap LOW bytes in the resident
;     64x32 window and confirms each streamed column matches the authored
;     level ground-truth at that world column (no stale strips, no garbage),
;     at forward, reverse, and idle camera positions.
;   - cam_x, STREAM_CAM_COL, STREAM_LAST_COL, STREAM_FIRST_COL are mirrored to
;     the debug region so the python test knows the window mapping.
;
; Build: 512KB (lorom_stream.cfg) — the wide flat level lives in BANK1.
;        NO -D needed: the kit nmi_handler.asm already carries the
;        STREAM_PENDING drain (Mode-1 BG1 horizontal).
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_bg.inc"            ; gfxmode, sf_load_bg_chr, sf_load_bg_pals
.include "sf_stream.inc"        ; the Mode-1 streaming front door (this sprint)
.include "engine_state.inc"
.include "bg_stream_world.inc"  ; BGW_* world dims + palette (generated)

; --- game DP state (kit contract: $32-$5F) ---
BGS_CAMX   = $32                ; camera X pixel (world space, 16-bit int)
BGS_PHASE  = $34                ; current pan phase 0..2 (debug mirror)

; --- debug region offsets (relative to $7E:E000) ---
DBG_HEARTBEAT = $E010           ; 2B: frame counter
DBG_CAMX      = $E012           ; 2B: camera X pixel
DBG_PHASE     = $E014           ; 2B: pan phase
DBG_CAM_COL   = $E016           ; 2B: STREAM_CAM_COL mirror
DBG_LAST_COL  = $E018           ; 2B: STREAM_LAST_COL mirror
DBG_FIRST_COL = $E01A           ; 2B: STREAM_FIRST_COL mirror
DBG_ACTIVE    = $E01C           ; 2B: STREAM_ACTIVE (1 = channel allocated)

PHASE0_END = 224                ; frames panning east (reaches level right edge)
PHASE1_END = 448                ; frames panning west (back to col 0, then idle)
PAN_DELTA  = 8                  ; px/frame = 1 tile column/frame
CAMX_MAX   = 1792               ; world_w(2048) - screen_w(256) = right-edge clamp

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; kit NMI: scroll commit + STREAM_PENDING drain

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init

    ; --- Mode 1, BG1 32x32 regs + dims (we override BG1SC to 64x32 below) ---
    gfxmode #1

    ; --- under forced blank: upload Four Seasons CHR + palette ---------------
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; force blank for the uploads + BG1SC write
    rep #$30
    .a16
    .i16

    sf_load_bg_chr 0, level_chr, BGW_CHR_BYTES
    sf_load_bg_pals 0, bgw_palette, 1

    ; --- BG1 -> 64x32 hardware tilemap @ VRAM word $5800 (BG1SC=$59) ---------
    ; This is what the streaming ring + the kit NMI consumer target.
    sep #$20
    .a8
    lda #$59
    sta $2107                   ; BG1SC: base word $5800, size 64x32 (one-time;
                                ;   the NMI does NOT re-commit BG1SC — proven by
                                ;   sf_level_init writing it once)
    ; main screen: BG1 only (TM=$01). Stock NMI commits TM from SHADOW_TM.
    lda #$01
    sta $212C                   ; TM = BG1 (live, first frame)
    sta SHADOW_TM
    stz $212D                   ; TS = 0
    rep #$30
    .a16
    .i16

    ; --- arm streaming: boot bulk-DMA cols 0..63 of the wide level ----------
    ; (runs under forced blank — the boot DMA halts the CPU)
    sf_stream_init level_flat, #BGW_WORLD_W_TILES

    ; --- camera starts at world X 0 -----------------------------------------
    stz BGS_CAMX
    stz BGS_PHASE
    ; STREAM_CAM_COL = 0 (matches boot). STZ has no abs-long form; use
    ; lda #0 + sta f:...,x (the CLAUDE.md WRAM-write pattern).
    sep #$20
    .a8
    ldx #0
    lda #$00
    sta f:$7E0000 + STREAM_CAM_COL + 0, x
    sta f:$7E0000 + STREAM_CAM_COL + 1, x

    ; --- BG1 tilemap disown is now BAKED INTO sf_stream_init (S2b-M2 DX) ------
    ; (was an inline `stz BG_TILEMAP_DIRTY` here; the streaming front door owns
    ; it now so no streaming ROM can hit the black-screen trap that the engine's
    ; full-tilemap DMA over the streamed ring would otherwise cause.)
    rep #$30
    .a16
    .i16

    sf_debug_magic

    ; --- screen on + NMI on --------------------------------------------------
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for NMI; latch input

    ; --- advance the camera per the deterministic pan script -----------------
    ; phase 0: east; phase 1: west; phase 2: idle. FRAME_COUNTER from sf_frame.
    lda FRAME_COUNTER
    cmp #PHASE0_END
    bcs @not_phase0
    ; PHASE 0 — EAST (+PAN_DELTA), clamp at CAMX_MAX (level right edge)
    ldx #0
    stx BGS_PHASE
    lda BGS_CAMX
    cmp #CAMX_MAX
    bcs @moved                  ; already at right edge — hold
    clc
    adc #PAN_DELTA
    sta BGS_CAMX
    bra @moved
@not_phase0:
    cmp #PHASE1_END
    bcs @phase2_idle
    ; PHASE 1 — WEST (-PAN_DELTA), clamp at 0
    ldx #1
    stx BGS_PHASE
    lda BGS_CAMX
    beq @moved                  ; already at 0
    sec
    sbc #PAN_DELTA
    sta BGS_CAMX
    bra @moved
@phase2_idle:
    ; PHASE 2 — IDLE (no move)
    ldx #2
    stx BGS_PHASE
@moved:

    ; --- streaming: update cam column, queue leading/trailing columns --------
    sf_stream_set_cam BGS_CAMX
    sf_stream_tick

    ; --- commit BG1 horizontal scroll = cam_x (hardware scroll in the ring) --
    ; The kit NMI commits the scroll shadow when ES_BG_SHADOW_DIRTY is set.
    rep #$30
    .a16
    .i16
    lda BGS_CAMX
    sta SHADOW_BG1HOFS
    sep #$20
    .a8
    lda #$01
    sta ES_BG_SHADOW_DIRTY
    rep #$30
    .a16
    .i16

    ; --- mirror state to the debug region for the python test ----------------
    lda FRAME_COUNTER
    ldx #0
    sta f:$7E0000 + DBG_HEARTBEAT, x
    lda BGS_CAMX
    ldx #0
    sta f:$7E0000 + DBG_CAMX, x
    lda BGS_PHASE
    ldx #0
    sta f:$7E0000 + DBG_PHASE, x
    lda f:$7E0000 + STREAM_CAM_COL
    ldx #0
    sta f:$7E0000 + DBG_CAM_COL, x
    lda f:$7E0000 + STREAM_LAST_COL
    ldx #0
    sta f:$7E0000 + DBG_LAST_COL, x
    lda f:$7E0000 + STREAM_FIRST_COL
    ldx #0
    sta f:$7E0000 + DBG_FIRST_COL, x
    ; STREAM_ACTIVE is 1 byte — read as byte, mirror as word
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_ACTIVE
    rep #$20
    .a16
    and #$00FF
    ldx #0
    sta f:$7E0000 + DBG_ACTIVE, x

    jmp game_loop

; =============================================================================
; Engine includes — the streaming producer + its HDMA-channel allocator, plus
; the standard rendering closure the kit NMI + gfxmode path depend on.
; hdma_alloc.asm MUST precede bg_stream.asm (provides hdma_request).
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "hdma_alloc.asm"
.include "bg_stream.asm"         ; the Mode-1 horizontal streaming producer

; --- BANK1: the WIDE flat level (256 cols x 64 bytes = 16KB, column-major) ---
; The producer reads column N's 64 bytes at offset (N * 64). bg_stream_init
; bulk-DMAs cols 0..63; the per-frame tick streams the leading/trailing edge.
.segment "BANK1"
level_flat:
    .incbin "tests/fixtures/bg_stream/level_flat.bin"

; --- BANK2: the Four Seasons CHR (4bpp BG tiles, ~800 bytes) ------------------
; Lives in its own bank so the long-addressed sf_load_bg_chr read is bank-clean.
.segment "BANK2"
level_chr:
    .incbin "tests/fixtures/bg_stream/level_chr.bin"
