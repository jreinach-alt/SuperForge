; =============================================================================
; bg_stream2d_test — proof ROM for the Mode-1 normal-BG 2-AXIS (horizontal
;                    column + vertical row) streaming substrate (Sprint S2a).
; =============================================================================
; Scripts a SCRIPTED camera (no player physics) walking a WIDE AND TALL authored
; Four Seasons platformer level (128 tiles = 4 screens wide x 128 tiles tall) in
; BOTH axes past the 64-col x 64-row BG1 64x64 hardware tilemap, proving the
; 2-axis streaming substrate renders NEW authored content into the resident VRAM
; window with no stale/garbage strips and no black band — RIGHT, DOWN, LEFT
; (reverse-X), UP (reverse-Y), and IDLE.
;
; The level is loaded as TWO flat copies (tools/level_pipeline_bg.py --tall):
;   level_flat.bin      COLUMN-MAJOR (256 B/col) — horizontal producer source.
;   level_flat_row.bin  ROW-MAJOR    (256 B/row) — vertical producer source.
; bg_stream.asm keeps the 64-col ring fresh horizontally; bg_stream_row.asm
; keeps the 64-row ring fresh vertically; the kit NMI handler's STREAM_PENDING
; (columns, stride-32) and STREAM_ROW_PENDING (rows, stride-1) drains DMA the
; queued strips into BG1 VRAM during VBlank.
;
; UNITS: level authored as 8px tiles, so STREAM_CAM_COL = cam_x>>3 and
; STREAM_CAM_ROW = cam_y>>3 (set by sf_stream_set_cam2). BG1HOFS/BG1VOFS are set
; to cam_x/cam_y so the hardware scrolls within the 64x64 ring.
;
; Camera script (deterministic, frame-counter driven — NO input):
;   phase 0 (RIGHT): pan EAST +8px/f to cam_x = 768  (level right edge)
;   phase 1 (DOWN):  pan SOUTH +8px/f to cam_y = 800  (level bottom edge)
;   phase 2 (LEFT):  pan WEST -8px/f back to cam_x = 0 (reverse-X streaming)
;   phase 3 (UP):    pan NORTH -8px/f back to cam_y = 0 (reverse-Y streaming)
;   phase 4 (IDLE):  hold (no streaming)
; 8px/frame = 1 tile/frame. Level is 128 tiles (1024px) each axis; screen is
; 32x28 tiles. So each axis walks the FULL level past the 64-ring then reverses.
;
; Done-condition (asserts on the RENDERED DESTINATION — the python test reads
; BG1 VRAM tilemap words in the resident 64x64 window and confirms each streamed
; column AND row matches the authored level ground-truth at that world (col,row),
; at RIGHT/DOWN/LEFT/UP/IDLE camera positions).
;
; Build: 512KB (lorom_stream.cfg). BANK1 = column-major level (32KB), BANK2 =
; row-major level (32KB), BANK3 = Four Seasons CHR. -D BG_STREAM_2AXIS makes the
; column producer emit the rows-32..63 sub-slot for the 64x64 tilemap.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_frame.inc"
.include "sf_bg.inc"
.include "sf_stream.inc"
.include "engine_state.inc"
.include "bg_stream_world.inc"

; --- game DP state (kit contract: $32-$5F) ---
BGS_CAMX   = $32
BGS_CAMY   = $34
BGS_PHASE  = $36

; --- debug region offsets (relative to $7E:E000) ---
DBG_HEARTBEAT = $E010
DBG_CAMX      = $E012
DBG_CAMY      = $E014
DBG_PHASE     = $E016
DBG_CAM_COL   = $E018
DBG_CAM_ROW   = $E01A
DBG_FIRST_COL = $E01C
DBG_FIRST_ROW = $E01E
DBG_LAST_COL  = $E020
DBG_LAST_ROW  = $E022
DBG_ACTIVE    = $E024
DBG_ROW_ACT   = $E026

; PAN_DELTA = 4 px/frame (half a tile per frame, 1 tile every 2 frames). The
; vertical (row) producer stages 64 cols into a WRAM buffer per streamed row
; (a heavier per-row step than the horizontal producer's direct-from-ROM column
; DMA), so 4px/frame gives the leading edge margin to stay populated under
; continuous motion. (The substrate handles faster too, but the scripted-camera
; proof keeps the moving-edge lag within a 1-tile inset on both axes.)
PAN_DELTA   = 4                 ; px/frame
CAMX_MAX    = 768               ; world_w(1024) - screen_w(256)
CAMY_MAX    = 800               ; world_h(1024) - screen_h(224)
; phase boundaries (frame counter). Each axis needs ~CAMx_MAX/4 frames + margin.
P0_END      = 220               ; RIGHT done (768/4 = 192 frames + margin)
P1_END      = 450               ; DOWN done (800/4 = 200 + margin)
P2_END      = 670               ; LEFT done
P3_END      = 900               ; UP done
; >= P3_END: IDLE

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    gfxmode #1

    sep #$20
    .a8
    lda #$80
    sta $2100                   ; force blank for uploads + BG1SC
    rep #$30
    .a16
    .i16

    sf_load_bg_chr 0, level_chr, BGW_CHR_BYTES
    sf_load_bg_pals 0, bgw_palette, 1

    ; --- BG1 -> 64x64 hardware tilemap @ VRAM word $5800 (BG1SC=$5B) ---------
    sep #$20
    .a8
    lda #$5B
    sta $2107                   ; BG1SC: base word $5800, size 64x64
    lda #$01
    sta $212C                   ; TM = BG1
    sta SHADOW_TM
    stz $212D                   ; TS = 0
    rep #$30
    .a16
    .i16

    ; --- arm BOTH axes: column boot (cols 0..63) + row boot (rows 0..63) -----
    ; column producer first (allocates the DMA channel + sets STREAM_ACTIVE),
    ; then row producer (mirrors the channel, full 64x64 stage+DMA fill).
    sf_stream_init     level_flat,     #BGW_WORLD_W_TILES
    sf_stream_row_init level_flat_row, #BGW_WORLD_H_TILES

    ; --- camera starts at world (0,0) ---------------------------------------
    stz BGS_CAMX
    stz BGS_CAMY
    stz BGS_PHASE
    sep #$20
    .a8
    ldx #0
    lda #$00
    sta f:$7E0000 + STREAM_CAM_COL + 0, x
    sta f:$7E0000 + STREAM_CAM_COL + 1, x
    sta f:$7E0000 + STREAM_CAM_ROW + 0, x
    sta f:$7E0000 + STREAM_CAM_ROW + 1, x

    ; --- BG1 tilemap disown is now BAKED INTO sf_stream_init (S2b-M2 DX) ------
    ; (was an inline `stz BG_TILEMAP_DIRTY` here; the streaming front door owns
    ; it now so no streaming ROM can hit the black-screen trap.)
    rep #$30
    .a16
    .i16

    sf_debug_magic

    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; display on, bright 15
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- advance the camera per the deterministic 5-phase script ------------
    lda FRAME_COUNTER
    cmp #P0_END
    bcs @not_p0
    ; PHASE 0 — RIGHT (cam_x += , clamp CAMX_MAX)
    ldx #0
    stx BGS_PHASE
    lda BGS_CAMX
    cmp #CAMX_MAX
    bcs @moved
    clc
    adc #PAN_DELTA
    sta BGS_CAMX
    bra @moved
@not_p0:
    cmp #P1_END
    bcs @not_p1
    ; PHASE 1 — DOWN (cam_y += , clamp CAMY_MAX)
    ldx #1
    stx BGS_PHASE
    lda BGS_CAMY
    cmp #CAMY_MAX
    bcs @moved
    clc
    adc #PAN_DELTA
    sta BGS_CAMY
    bra @moved
@not_p1:
    cmp #P2_END
    bcs @not_p2
    ; PHASE 2 — LEFT (cam_x -= , clamp 0)
    ldx #2
    stx BGS_PHASE
    lda BGS_CAMX
    beq @moved
    sec
    sbc #PAN_DELTA
    sta BGS_CAMX
    bra @moved
@not_p2:
    cmp #P3_END
    bcs @phase4_idle
    ; PHASE 3 — UP (cam_y -= , clamp 0)
    ldx #3
    stx BGS_PHASE
    lda BGS_CAMY
    beq @moved
    sec
    sbc #PAN_DELTA
    sta BGS_CAMY
    bra @moved
@phase4_idle:
    ldx #4
    stx BGS_PHASE
@moved:

    ; --- 2-axis streaming service -------------------------------------------
    sf_stream_set_cam2 BGS_CAMX, BGS_CAMY
    sf_stream_tick2

    ; --- commit BG1 scroll = (cam_x, cam_y) ---------------------------------
    rep #$30
    .a16
    .i16
    lda BGS_CAMX
    sta SHADOW_BG1HOFS
    lda BGS_CAMY
    sta SHADOW_BG1VOFS
    sep #$20
    .a8
    lda #$01
    sta ES_BG_SHADOW_DIRTY
    rep #$30
    .a16
    .i16

    ; --- mirror state to the debug region -----------------------------------
    lda FRAME_COUNTER
    ldx #0
    sta f:$7E0000 + DBG_HEARTBEAT, x
    lda BGS_CAMX
    ldx #0
    sta f:$7E0000 + DBG_CAMX, x
    lda BGS_CAMY
    ldx #0
    sta f:$7E0000 + DBG_CAMY, x
    lda BGS_PHASE
    ldx #0
    sta f:$7E0000 + DBG_PHASE, x
    lda f:$7E0000 + STREAM_CAM_COL
    ldx #0
    sta f:$7E0000 + DBG_CAM_COL, x
    lda f:$7E0000 + STREAM_CAM_ROW
    ldx #0
    sta f:$7E0000 + DBG_CAM_ROW, x
    lda f:$7E0000 + STREAM_FIRST_COL
    ldx #0
    sta f:$7E0000 + DBG_FIRST_COL, x
    lda f:$7E0000 + STREAM_FIRST_ROW
    ldx #0
    sta f:$7E0000 + DBG_FIRST_ROW, x
    lda f:$7E0000 + STREAM_LAST_COL
    ldx #0
    sta f:$7E0000 + DBG_LAST_COL, x
    lda f:$7E0000 + STREAM_LAST_ROW
    ldx #0
    sta f:$7E0000 + DBG_LAST_ROW, x
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_ACTIVE
    rep #$20
    .a16
    and #$00FF
    ldx #0
    sta f:$7E0000 + DBG_ACTIVE, x
    sep #$20
    .a8
    lda f:$7E0000 + STREAM_ROW_ACTIVE
    rep #$20
    .a16
    and #$00FF
    ldx #0
    sta f:$7E0000 + DBG_ROW_ACT, x

    jmp game_loop

; =============================================================================
; Engine includes — both streaming producers + the rendering closure.
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "hdma_alloc.asm"
.include "bg_stream.asm"         ; horizontal column producer (BG_STREAM_2AXIS)
.include "bg_stream_row.asm"     ; vertical row producer (S2a)

; --- BANK1: COLUMN-MAJOR flat level (128 cols x 256 B = 32KB) ----------------
.segment "BANK1"
level_flat:
    .incbin "tests/fixtures/bg_stream2d/level_flat.bin"

; --- BANK2: ROW-MAJOR flat level (128 rows x 256 B = 32KB) -------------------
.segment "BANK2"
level_flat_row:
    .incbin "tests/fixtures/bg_stream2d/level_flat_row.bin"

; --- BANK3: Four Seasons CHR (4bpp BG tiles) --------------------------------
.segment "BANK3"
level_chr:
    .incbin "tests/fixtures/bg_stream2d/level_chr.bin"
