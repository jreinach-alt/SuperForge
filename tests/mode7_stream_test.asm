; =============================================================================
; mode7_stream_test — proof ROM for the Mode 7 2-axis tilemap-streaming rail.
; =============================================================================
; Streaming rail v2 / Sprint S1.  Scripts a camera WALKING a large authored
; Mode 7 overworld (256x256 tiles = 2048x2048 px, "several windows" wide AND
; tall vs the 128x128 Mode 7 VRAM window) — forward in X, forward in Y, BACK in
; both, and idle — and proves the streaming substrate renders NEW authored
; content past the 128x128 window with no stale/garbage strips and no black band.
;
; Static top-down Mode 7 (identity affine, M7SEL=$00 wrap) so the 128x128 VRAM
; tilemap is a 1:1 wrapped window onto the world centred on the camera tile.
; The Mode 7 CHR (8bpp flat tiles, colour == tile id) is uploaded ONCE via the
; interleaved seed; only the tilemap LOW bytes stream as the camera moves.
;
; Camera script (driven by a frame counter — NO input needed, deterministic):
;   phase 0 (frames   1..160):  walk EAST  (+X)  — streams columns
;   phase 1 (frames 161..320):  walk SOUTH (+Y)  — streams rows
;   phase 2 (frames 321..480):  walk WEST  (-X)  — streams columns (reverse)
;   phase 3 (frames 481..640):  walk NORTH (-Y)  — streams rows (reverse)
;   phase 4 (frames 641..):     IDLE             — no streaming
; 1 px/frame in 8.8 -> the camera advances 1 world px/frame = covers many tiles
; over each 160-frame phase (160 px = 20 tiles), walking PAST the 64-tile half
; window so genuinely new world content must stream in.
;
; Done-condition (emulator-verifiable, asserts on the RENDERED DESTINATION):
;   - boots ($7E:E000 == "SFDB"); heartbeat at $7E:E010 advances.
;   - the test drives the camera to a known world tile, then reads the Mode 7
;     VRAM tilemap LOW bytes and confirms the streamed window matches the
;     authored world ground-truth at that world position (incl. the hidden
;     32-tile TOWN-tile landmark lattice) — no stale strips, no garbage.
;   - the camera tile pos + window origin are mirrored to the debug region so
;     the python test knows where the window maps without re-deriving timing.
;
; Build: 512KB (lorom_stream.cfg). -D MODE7_STREAM_NMI pulls the streaming
;        VBlank DMA dispatch into nmi_handler.asm. (Explicit Makefile rule.)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_mode7.inc"         ; (for the M7 register equates + load_map)
.include "sf_mode7_stream.inc"  ; the streaming front door
.include "engine_state.inc"
.include "world_stream.inc"     ; world dims, spawn, TILE_*/TERR_*, palette

; --- game DP state (kit contract: $32-$5F) ---
M7S_CAMX   = $32                ; camera X pixel (world space, 16-bit int)
M7S_CAMY   = $34                ; camera Y pixel (world space, 16-bit int)
M7S_PHASE  = $36                ; current walk phase 0..4 (debug mirror)

; --- debug region offsets (relative to $7E:E000) ---
DBG_HEARTBEAT = $E010           ; 2B: frame counter
DBG_CAM_TX    = $E012           ; 2B: camera tile X (mirrored from streaming)
DBG_CAM_TY    = $E014           ; 2B: camera tile Y
DBG_PHASE     = $E016           ; 2B: walk phase
DBG_LAST_TX   = $E018           ; 2B: last-streamed tile X
DBG_LAST_TY   = $E01A           ; 2B: last-streamed tile Y

; Mode 7 register equates (also in mode7_engine.asm; redeclare locally for the
; direct static setup so this ROM doesn't depend on engine internals).
REG_BGMODE = $2105
REG_M7SEL  = $211A
REG_M7A    = $211B
REG_M7B    = $211C
REG_M7C    = $211D
REG_M7D    = $211E
REG_M7X    = $211F
REG_M7Y    = $2120

WALK_PHASE_LEN = 160            ; frames per walk phase

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc + (under -D) mode7_stream_nmi.inc

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init

    ; --- upload the interleaved seed (initial 128x128 window) under blank ----
    sf_mode7_load_map world_seed, #$8000

    ; --- upload the world palette to CGRAM (index i = tile id i colour) ------
    sep #$20
    .a8
    stz $2121                   ; CGADD = 0
    ldx #0
@pal_loop:
    lda f:world_palette, x
    sta $2122
    inx
    cpx #(WORLD_PAL_COUNT * 2)
    bne @pal_loop
    rep #$30
    .a16
    .i16

    ; --- static top-down Mode 7: BGMODE 7, identity matrix, wrap ------------
    sep #$20
    .a8
    lda #$07
    sta REG_BGMODE              ; BGMODE = 7
    sta SHADOW_BGMODE
    stz REG_M7SEL              ; M7SEL = $00 (wrap, no flip)
    ; identity affine: A=$0100, B=0, C=0, D=$0100 (write-twice low then high)
    lda #$00
    sta REG_M7A                 ; A lo
    lda #$01
    sta REG_M7A                 ; A hi  -> $0100 = 1.0
    lda #$00
    sta REG_M7B
    sta REG_M7B                 ; B = 0
    sta REG_M7C
    sta REG_M7C                 ; C = 0
    sta REG_M7D                 ; D lo
    lda #$01
    sta REG_M7D                 ; D hi  -> $0100 = 1.0
    ; rotation centre = 0 (write-twice 13-bit; we pan via M7HOFS/VOFS shadow)
    stz REG_M7X
    stz REG_M7X
    stz REG_M7Y
    stz REG_M7Y
    ; main screen: BG1 only (Mode 7 layer). The stock NMI commits TM from
    ; SHADOW_TM every frame, so set the SHADOW (not just the live reg) or BG1
    ; gets turned off next VBlank. (SHADOW_TS is committed too; leave it 0.)
    lda #$01
    sta $212C                   ; TM = BG1 (live, for the first frame)
    sta SHADOW_TM               ; TM shadow (the NMI re-commits this each frame)
    stz $212D                   ; TS = 0
    rep #$30
    .a16
    .i16

    ; --- camera starts at spawn (world tile centre) -------------------------
    lda #(WORLD_SPAWN_TX * 8)
    sta M7S_CAMX
    lda #(WORLD_SPAWN_TY * 8)
    sta M7S_CAMY
    stz M7S_PHASE

    ; --- arm streaming for the spawn tile -----------------------------------
    sf_mode7_stream_init #WORLD_SPAWN_TX, #WORLD_SPAWN_TY

    sf_debug_magic

    ; --- screen on + NMI on -------------------------------------------------
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

    ; --- advance the camera per the deterministic walk script ---------------
    ; phase = (FRAME_COUNTER / WALK_PHASE_LEN), clamped to 4
    lda FRAME_COUNTER
    ; compute phase via repeated subtract (no DIV); cheap, 5 phases max
    ldx #0
@phase_calc:
    cmp #WALK_PHASE_LEN
    bcc @phase_done
    sec
    sbc #WALK_PHASE_LEN
    inx
    cpx #4
    bcc @phase_calc
@phase_done:
    stx M7S_PHASE
    ; dispatch on phase
    cpx #0
    bne @not_east
    ; EAST: +X
    lda M7S_CAMX
    inc
    sta M7S_CAMX
    bra @moved
@not_east:
    cpx #1
    bne @not_south
    ; SOUTH: +Y
    lda M7S_CAMY
    inc
    sta M7S_CAMY
    bra @moved
@not_south:
    cpx #2
    bne @not_west
    ; WEST: -X
    lda M7S_CAMX
    dec
    sta M7S_CAMX
    bra @moved
@not_west:
    cpx #3
    bne @moved              ; phase 4 = idle (no move)
    ; NORTH: -Y
    lda M7S_CAMY
    dec
    sta M7S_CAMY
@moved:

    ; --- streaming: update cam tile pos, stage leading edges ----------------
    sf_mode7_stream_set_cam M7S_CAMX, M7S_CAMY
    sf_mode7_stream_tick

    ; --- pan the Mode 7 view so the camera tile stays centred. The window
    ;     origin (in tiles) = cam_tile - 64; scroll px = origin*8. With the
    ;     wrapped VRAM window, scroll = (cam_px - 512) & $1FFF keeps the camera
    ;     centred on the 256px-wide wrapped Mode 7 plane. We feed it through the
    ;     BG1 scroll shadow (= M7HOFS/M7VOFS under Mode 7; stock NMI commits). --
    lda M7S_CAMX
    sec
    sbc #128                    ; centre: shift left by half a 256px window
    and #$1FFF
    sta SHADOW_BG1HOFS
    lda M7S_CAMY
    sec
    sbc #128
    and #$1FFF
    sta SHADOW_BG1VOFS
    sep #$20
    .a8
    lda #$01
    sta ES_BG_SHADOW_DIRTY      ; ask the NMI to commit the scroll shadow
    rep #$30
    .a16
    .i16

    ; --- mirror state to the debug region for the python test ---------------
    lda FRAME_COUNTER
    ldx #0
    sta f:$7E0000 + DBG_HEARTBEAT, x
    lda f:$7E0000 + M7S_CAM_TX
    ldx #0
    sta f:$7E0000 + DBG_CAM_TX, x
    lda f:$7E0000 + M7S_CAM_TY
    ldx #0
    sta f:$7E0000 + DBG_CAM_TY, x
    lda M7S_PHASE
    ldx #0
    sta f:$7E0000 + DBG_PHASE, x
    lda f:$7E0000 + M7S_LAST_TX
    ldx #0
    sta f:$7E0000 + DBG_LAST_TX, x
    lda f:$7E0000 + M7S_LAST_TY
    ldx #0
    sta f:$7E0000 + DBG_LAST_TY, x

    jmp game_loop

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order, plus the
; streaming routine. (mode7 perspective machinery is linked but unused; we drive
; a static affine directly above.)
; =============================================================================
mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"
.include "mode7_stream.asm"      ; the reusable streaming tick/init routines

; --- BANK1: the 32KB interleaved Mode 7 seed (initial 128x128 window) --------
.segment "BANK1"
world_seed:
    .incbin "tests/fixtures/mode7_stream/world_seed.bin"

; --- BANK2/BANK3: the FLAT tilemap (256 cols x 1 byte, 128 rows/bank). The
;     streaming tick computes bank = (row>>7) + WORLD_FLAT_BANK_BASE (=2), so
;     bank0 must link at $02:8000 and bank1 at $03:8000. ---------------------
.segment "BANK2"
world_flat_b2:
    .incbin "tests/fixtures/mode7_stream/world_flat_bank0.bin"   ; rows 0..127
.segment "BANK3"
world_flat_b3:
    .incbin "tests/fixtures/mode7_stream/world_flat_bank1.bin"   ; rows 128..255

; --- BANK4/BANK5: world-space collision (256x256 = 64KB), 16-bit indexed.
;     Split into two 32KB bank files (one bank per 128 world rows). World-space
;     collision[ty*256+tx]: bank = (ty>>7), offset = (ty&127)*256 + tx. -------
.segment "BANK4"
world_collision_b4:
    .incbin "tests/fixtures/mode7_stream/world_collision_bank0.bin"   ; rows 0..127
.segment "BANK5"
world_collision_b5:
    .incbin "tests/fixtures/mode7_stream/world_collision_bank1.bin"   ; rows 128..255
