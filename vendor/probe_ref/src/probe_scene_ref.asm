; =============================================================================
; probe_scene_ref.asm — the streaming workd: Position Space Expansion
; =============================================================================
; CONTAINS THIRD-PARTY CONTENT — CC BY 4.0. ATTRIBUTION REQUIRED.
;   The per-scanline perspective routines in this file — `pv_rebuild`,
;   `pv_set_origin`, `pv_abcd_lines_{full,sa1,angle0}`,
;   `pv_interpolate_{2x,4x}`, `pv_buffer_x` — are MODIFIED TRANSLITERATIONS
;   of `dizworld.s`, and it `.include`s two further third-party files
;   (`mode7_diz_math.asm`, `mode7_diz_ztable.inc`), each with its own notice.
;   Source:  https://github.com/bbbradsmith/SNES_stuff/tree/main/dizworld
;   Author:  (c) Brad Smith (rainwarrior) — https://rainwarrior.ca
;   Licence: Creative Commons Attribution 4.0 International (CC BY 4.0)
;            https://creativecommons.org/licenses/by/4.0/
;   Everything else in this file is first-party. A ROM that links it must
;   credit Brad Smith. See NOTICE and docs/92_provenance_audit.md §4.
; =============================================================================
; Based on: mode7_racing_12_8c.asm (the streaming workc VBlank DMA Pipeline)
;
; the streaming workd: Expand position space from 1024×1024 to 4096×4096 pixels.
;   - Position wrap mask: AND #$03FF → AND #$0FFF (player + AI)
;   - Sector boundaries scaled ×4 for lap detection
;   - Waypoint coordinates scaled ×4 in track_meta.inc
;   - Streaming tile space (512×512) unchanged
;
; Asset files:
;   assets/racing/track_tiles_v2.bin     -- 768 bytes (12 tiles, 8bpp)
;   assets/racing/track_tilemap_v2.bin   -- 16384 bytes (128x128 tile indices)
;   assets/racing/track_palette_v2.inc   -- 34 bytes (17 BGR555 colors)
;   assets/racing/track_meta.inc         -- start pos (pixel coords), waypoints
;   assets/racing/sky_tiles_v2.inc       -- 192 bytes (6 tiles)
;   assets/racing/sky_tilemap_v2.inc     -- 2048 bytes (32x32 tilemap)
;   assets/racing/sky_palette_v2.inc     -- 8 bytes (4 BGR555 colors)
;   assets/racing/accel_lut.inc          -- 256 bytes (accel LUT)
;   assets/racing/player_car.inc         -- 1024 bytes (32 tiles, 4bpp)
;   assets/racing/player_car_palette.inc -- 32 bytes (16 BGR555 colors)
;
; Debug region ($7E:E000+):
;   $E000-$E003: "SFDB" magic
;   $E004:       current angle (byte)
;   $E006-$E007: posx integer (pixels, 0-1023)
;   $E008-$E009: posy integer (pixels, 0-1023)
;   $E00A-$E00B: joy1_current (16-bit joypad state)
;   $E00C-$E00D: frame counter (16-bit)
;   $E00E:       pv_tm1 value (terrain TM)
;   $E00F:       pv_tm2 value (sky TM)
;   $E010:       tile count (byte)
;   $E011:       palette color count (byte)
;   $E034-$E035: velocity (16-bit, 8.8 forward speed)
;   $E036-$E037: turn_rate (signed angle delta this frame)
;   $E038:       drift_state (0=straight, 1=lean left, 2=lean right)
;   $E039:       current_lap (1-3, sector-based detection)
;   $E03A:       race_position (stub = 1)
; =============================================================================

.p816
.smart

.include "header.inc"

.segment "CODE"

; =====================================================================
; Airfield map constants (from mode7_map_converter.py output)
; =====================================================================
AIRSHIP_TILES_COUNT    = 12     ; 12 track tile types (updated from 41 airfield tiles)
AIRSHIP_TILE_SIZE      = 64
AIRSHIP_TILES_SIZE     = 768    ; 12 tiles × 64 bytes (updated from 2624)
AIRSHIP_PALETTE_COLORS = 17
AIRSHIP_PALETTE_SIZE   = 34

; =====================================================================
; Streaming engine — WRAM staging buffers (the streaming work)
; Multi-column/row support: up to 8 columns + 8 rows per frame
; Max speed (48.0 in 8.8) = 6 tiles/frame; clamp at 8 for margin.
; =====================================================================
STREAM_ROW_BUF      = $3A00   ; 8×128B = 1024B: row staging buffers ($3A00-$3DFF)
STREAM_COL_BUF      = $3E00   ; 8×128B = 1024B: column staging buffers ($3E00-$41FF)
STREAM_ROW_COUNT    = $4200   ; 2B: number of pending rows (0-8)
STREAM_COL_COUNT    = $4202   ; 2B: number of pending columns (0-8)
STREAM_ROW_VADDR    = $4204   ; 8×2B = 16B: VRAM word addresses for row DMAs
STREAM_COL_VADDR    = $4214   ; 8×2B = 16B: VRAM word addresses for column DMAs
STREAM_MAX          = 8       ; max columns/rows per frame
; Legacy aliases (unused but kept for reference)
STREAM_ROW_PENDING  = $4200   ; same as STREAM_ROW_COUNT
STREAM_COL_PENDING  = $4202   ; same as STREAM_COL_COUNT
STREAM_COL_IDX      = $4224   ; 1B: (unused)
STREAM_LOOP_COUNT   = $4226   ; 2B: streaming loop iteration count (NMI uses WRAM)
STREAM_LOOP_IDX     = $4228   ; 2B: streaming loop index (NMI uses WRAM)

; Streaming engine — Zero Page state ($60-$6B)
stream_cam_tx       = $60     ; 2B: camera tile X in logical space (0-511)
stream_cam_ty       = $62     ; 2B: camera tile Y in logical space (0-511)
stream_last_tx      = $64     ; 2B: last streamed tile X
stream_last_ty      = $66     ; 2B: last streamed tile Y
stream_loop_count   = $68     ; 2B: loop iteration count (survives decompressor)
stream_loop_idx     = $6A     ; 2B: loop word index (0,2,4,6)

; =====================================================================
; Debug region addresses
; =====================================================================
DEBUG_BASE      = $E000
DEBUG_MAGIC     = DEBUG_BASE + $00
DEBUG_ANGLE     = DEBUG_BASE + $04
DEBUG_POSX      = DEBUG_BASE + $06
DEBUG_POSY      = DEBUG_BASE + $08
DEBUG_JOY       = DEBUG_BASE + $0A
DEBUG_FRAMES    = DEBUG_BASE + $0C
DEBUG_TM1       = DEBUG_BASE + $0E
DEBUG_TM2       = DEBUG_BASE + $0F
DEBUG_TILECNT   = DEBUG_BASE + $10
DEBUG_PALCNT    = DEBUG_BASE + $11
DEBUG_VSTART    = DEBUG_BASE + $12   ; V-counter at start of game loop work
DEBUG_VEND      = DEBUG_BASE + $14   ; V-counter at end of game loop work
DEBUG_VDELTA    = DEBUG_BASE + $16   ; scanlines consumed (end - start)
DEBUG_REBUILD   = DEBUG_BASE + $18   ; 1 if pv_rebuild ran this frame
DEBUG_FOG_L0    = DEBUG_BASE + $2C   ; fog_l0 (pv_l0 fog was applied at)
DEBUG_HEIGHT    = DEBUG_BASE + $3B   ; camera height (byte)
DEBUG_VELOCITY  = DEBUG_BASE + $34   ; velocity (16-bit, 8.8)
DEBUG_STEER     = DEBUG_BASE + $36   ; turn_rate this frame (signed)
DEBUG_DRIFT     = DEBUG_BASE + $38   ; drift_state (byte)
DEBUG_LAP       = DEBUG_BASE + $39   ; current_lap (byte)
DEBUG_POSITION  = DEBUG_BASE + $3A   ; race_position (byte)
DEBUG_AI0       = DEBUG_BASE + $50   ; AI car 0 state dump (16 bytes)
DEBUG_STREAM_TX = DEBUG_BASE + $3C   ; stream_cam_tx (2B)
DEBUG_STREAM_TY = DEBUG_BASE + $3E   ; stream_cam_ty (2B)
; 12-8b test: decompressed row at $E090 (128 bytes), column at $E110 (128 bytes)
; Note: $E050-$E08F used by AI car state dumps (4 cars × 16 bytes)
DEBUG_DECOMP_ROW = DEBUG_BASE + $90  ; 128B: decompressed test row
DEBUG_DECOMP_COL = DEBUG_BASE + $110 ; 128B: decompressed test column

; =====================================================================
; AI Car Pool — 4 cars × 16 bytes at $7E:3600-$363F
; All AI routines use X = ai_car_off (0, 16, 32, 48) for car indexing
; =====================================================================
AI_BASE       = $3600
AI_X          = AI_BASE + 0     ; 2B: map X (8.8)
AI_Y          = AI_BASE + 2     ; 2B: map Y (8.8)
AI_VEL        = AI_BASE + 4     ; 2B: forward velocity (8.8)
AI_ANGLE      = AI_BASE + 6     ; 1B: heading (0-255)
AI_WP_IDX     = AI_BASE + 7     ; 1B: current waypoint index
AI_SIZE_GRADE = AI_BASE + 8     ; 1B: sprite grade (0=XL, 1=Large, 2=Medium, 3=Small)
AI_SCREEN_X   = AI_BASE + 9     ; 2B: projected screen X (16-bit signed, for 9-bit OAM)
AI_SCREEN_Y   = AI_BASE + 11    ; 1B: projected screen Y
AI_VISIBLE    = AI_BASE + 12    ; 1B: 1 = on screen
AI_CAM_Z      = AI_BASE + 13    ; 2B: camera-space depth
AI_LAP        = AI_BASE + 15    ; 1B: completed lap count
AI_CAR_COUNT  = 4
AI_CAR_STRIDE = 16

; Per-car loop scratch (freed ZP: $34-$35, $3A-$42)
; NOTE: variables read via LDX in I16 mode MUST be 2-byte aligned with high byte = 0.
; We use 16-bit STA or STZ to ensure this.
ai_car_off    = $34             ; 2B: WRAM offset for current car (0,16,32,48) — I16 reads
ai_car_idx    = $40             ; 1B: current car index (0-3) — A8 only, never loaded into X/Y
ai_oam_off    = $3A             ; 2B: OAM byte offset for current car's first entry — I16 reads
ai_oam_hi0    = $3C             ; 2B: hi-table byte offset (from oam+512) — I16 reads
ai_oam_attr   = $3E             ; 1B: OAM attr byte for current car (palette + priority) — A8 only

; Mode 7 perspective constants (derived from height=26)
; ZR0 = (1<<21) / pv_s0 = 2097152 / 436
AI_ZR0        = 4809
; ZR_INC per scanline = (ZR1 - ZR0) / (L1 - L0) = 22426 / 179
AI_ZR_INC     = 125

; =====================================================================
; Zero Page Layout ($00-$FF)
; =====================================================================
; $00-$15:   NMI shadow + control
nmi_ready   = $00
nmi_count   = $01
nmi_bgmode  = $02
nmi_hofs    = $03   ; 2 bytes
nmi_vofs    = $05   ; 2 bytes
nmi_m7t     = $07   ; 8 bytes (A,B,C,D x 2 bytes each)
nmi_m7x     = $0F   ; 2 bytes
nmi_m7y     = $11   ; 2 bytes
nmi_tm      = $13   ; 1 byte
nmi_hdma_en = $14   ; 1 byte
new_hdma_en = $15   ; 1 byte

; $16-$21:   Camera position
posx        = $16   ; 6 bytes ($16-$1B)
posy        = $1C   ; 6 bytes ($1C-$21)

; $22-$2F:   Game state
angle       = $22   ; 1 byte
prev_angle  = $23   ; 1 byte (for detecting angle changes)
joy1_current = $24  ; 2 bytes (current joypad state)
frame_count = $26   ; 2 bytes
move_vel_x  = $28   ; 2 bytes (signed 8.8 velocity scratch)
move_vel_y  = $2A   ; 2 bytes
sign_ext    = $2C   ; 2 bytes (sign extension scratch)
height      = $2E   ; 1 byte (camera elevation, 8-120)
prev_height = $2F   ; 1 byte (for detecting height changes)

; $30-$39:   Sky palette shadow + racing scratch
nmi_bg2hofs    = $30   ; 2 bytes (BG2 horizontal scroll shadow for NMI)
effective_vel  = $32   ; 2 bytes (per-frame velocity after grip penalty — 12-2)
                       ; ($34-$35 freed: rot_scroll_acc removed in 12-2)
nmi_sky_pal    = $36   ; 4 bytes: sky_lo, sky_hi, cloud_lo, cloud_hi (BGR555)

; $57-$5F:   Racing physics + HUD state
velocity       = $57   ; 2 bytes (forward speed, 8.8 unsigned, 0-$3000 = 0-48.0)
turn_rate      = $59   ; 2 bytes (angle delta this frame, signed 8-bit zero-extended)
drift_state    = $5B   ; 1 byte  (0=straight, 1=lean left, 2=lean right)
grip           = $5C   ; 1 byte  (255=full grip, 192=leaning)
current_lap    = $5D   ; 1 byte  (1-3, sector-based lap detection)
race_position  = $5E   ; 1 byte  (1-5, stub = always 1)
lap_checkpoint = $5F   ; 1 byte  (start/finish crossing flag)

; $B0-$CD:   Math routines (defined in mode7_diz_math.asm)
;            math_a=$B0, math_b=$B4, math_p=$B8, math_r=$C0
;            cosa=$C8, sina=$CA, diz_temp=$CC

; $D0-$DF:   General temp (used by pv_rebuild)
temp        = $D0   ; 16 bytes

; $E0-$F7:   Perspective state
pv_buffer   = $E0   ; 1 byte
pv_l0       = $E1   ; 1 byte
pv_l1       = $E2   ; 1 byte
pv_s0       = $E3   ; 2 bytes
pv_s1       = $E5   ; 2 bytes
pv_sh       = $E7   ; 2 bytes
pv_interp   = $E9   ; 1 byte
pv_wrap     = $EA   ; 1 byte
pv_zr       = $EB   ; 2 bytes
pv_zr_inc   = $ED   ; 2 bytes
pv_sh_      = $EF   ; 2 bytes
pv_scale    = $F1   ; 4 bytes
pv_negate   = $F5   ; 1 byte
pv_interps  = $F6   ; 2 bytes

; $F9-$FA:   Edge detection
joy1_prev    = $F9  ; 2 bytes (previous frame joypad state for btnp)

; $46-$56: the base scene horizon fog band (expanded from 3 to 5 scanlines)
fog_cache       = $46  ; 15 bytes: saved pre-attenuation COLDATA bytes (5 scanlines × 3 channels)
fog_l0          = $55  ; 1 byte: pv_l0 value fog was applied at (0 = no fog applied)
fog_active      = $56  ; 1 byte: 1 = fog band is currently applied to WRAM




; =====================================================================
; WRAM Buffer Layout (bank $7E)
; =====================================================================
; HDMA double-buffers for perspective coefficient tables
; Each AB/CD buffer: 224 scanlines x 4 bytes = 896 bytes, round to 1024
pv_hdma_ab0  = $2000   ; 1024 bytes
pv_hdma_cd0  = $2400   ; 1024 bytes
pv_hdma_bgm0 = $2800   ; 16 bytes
pv_hdma_tm0  = $2810   ; 16 bytes
pv_hdma_abi0 = $2820   ; 16 bytes
pv_hdma_cdi0 = $2830   ; 16 bytes
pv_hdma_col_r0 = $2840 ; 16 bytes — CH0 COLDATA-R indirect table
pv_hdma_col_g0 = $2850 ; 16 bytes — CH1 COLDATA-G indirect table
pv_hdma_col_b0 = $2860 ; 16 bytes — CH2 COLDATA-B indirect table

pv_hdma_ab1  = $2900   ; 1024 bytes (buffer 1 = buffer 0 + stride)
pv_hdma_cd1  = $2D00   ; 1024 bytes
pv_hdma_bgm1 = $3100   ; 16 bytes
pv_hdma_tm1  = $3110   ; 16 bytes
pv_hdma_abi1 = $3120   ; 16 bytes
pv_hdma_cdi1 = $3130   ; 16 bytes
pv_hdma_col_r1 = $3140 ; 16 bytes — buffer 1 CH0 COLDATA-R indirect table
pv_hdma_col_g1 = $3150 ; 16 bytes — buffer 1 CH1 COLDATA-G indirect table
pv_hdma_col_b1 = $3160 ; 16 bytes — buffer 1 CH2 COLDATA-B indirect table

PV_HDMA_STRIDE = pv_hdma_ab1 - pv_hdma_ab0

; HDMA channel register block shadows (8 channels x 16 bytes = 128 bytes)
new_hdma     = $3200   ; 128 bytes - settings to apply at next NMI
nmi_hdma     = $3280   ; 128 bytes - current HDMA settings

; OAM shadow
oam          = $3300   ; 544 bytes (ends at $3522)


; Indirect TM tables (1-byte values for HDMA indirect)
; Relocated from $3600/$3601 in 12-0 per allocations doc (freed terrain shadow area)
pv_tm1       = $3580   ; 1 byte: TM value for Mode 7 terrain ($11 = BG1+OBJ)
pv_tm2       = $3581   ; 1 byte: TM value for sky ($12 = BG2+OBJ)

; Active gradient WRAM (static — populated once at init, used by fog band)
active_grad_r = $3700  ; 224 bytes — R channel COLDATA
active_grad_g = $37E0  ; 224 bytes — G channel COLDATA
active_grad_b = $38C0  ; 224 bytes — B channel COLDATA
; Total: $3700-$399F = 672 bytes

; Terrain palette WRAM shadow (written to CGRAM at boot, no NMI updates)
terrain_pal_shadow = $3560  ; 34 bytes ($3560-$3581)

; =====================================================================
; Constants
; =====================================================================
STACK_INIT   = $1FFF

; mode_y parameters
MODE_Y_SY    = 168     ; scanline to place camera focus (fixed, independent of height)
PV_L1_VAL    = 224     ; bottom of screen (constant)

; Height bounds and default
HEIGHT_DEFAULT = 26    ; default camera elevation (horizon at ~20% = scanline 45)
HEIGHT_MIN     = 8     ; minimum (horizon at scanline 36)
HEIGHT_MAX     = 120   ; maximum (horizon at scanline 92)

; Joypad button masks ($4218 layout)
JOY_B        = $8000
JOY_Y        = $4000   ; unused — reserved
JOY_UP       = $0800
JOY_DOWN     = $0400
JOY_LEFT     = $0200
JOY_RIGHT    = $0100
JOY_A        = $0080   ; unused — reserved
JOY_X        = $0040   ; unused — reserved
JOY_L        = $0020
JOY_R        = $0010
JOY_SELECT   = $2000

; Fog band: 5-scanline linear fade at horizon boundary (expanded in 12-0)
FOG_BAND_SIZE    = 5

; Racing physics constants (12-2)
STEER_NORMAL  = 2      ; angle units/frame for D-pad steering
STEER_LEAN    = 1      ; additional angle units/frame from L/R shoulder lean
FRICTION      = $0020  ; velocity decay per frame when B not held (0.125 px/frame)
VELOCITY_MAX  = $3000  ; top speed (48.0 in 8.8)

; OBJ tile VRAM base (word address, after Mode 7 data)
OBJ_VRAM_BASE = $4000

; BG2 sky layer VRAM layout
BG2_CHR_BASE  = $5000   ; word address for BG2 chr data (BG12NBA high nibble = $5)
BG2_MAP_BASE  = $6000   ; word address for BG2 tilemap (BG2SC = $60)
SKY_COLOR     = $7E08   ; sky blue in 15-bit BGR: B=31, G=16, R=8

; =====================================================================
; CODE segment
; =====================================================================
.segment "CODE"

; =============================================================================
; NMI Handler - commits shadow registers, enables HDMA
; =============================================================================
NMI:
NMI_STUB:
    rep #$30
    .a16
    .i16
    pha
    phx
    phy
    phb
    phd
    sep #$30
    .a8
    .i8
    lda #$00
    pha
    plb                     ; DB = 0 for HW register access
    lda z:nmi_ready
    bne @nmi_do_update
    jmp @nmi_exit
@nmi_do_update:
    ; OAM DMA (channel 0) — upload shadow OAM to PPU
    stz a:$2102             ; OAMADDL = 0
    stz a:$2103             ; OAMADDH = 0
    lda #$02                ; DMAP: A→B, increment, 1-byte
    sta a:$4300
    lda #$04                ; BBAD: $2104 (OAMDATA)
    sta a:$4301
    rep #$20
    .a16
    lda #.loword(oam)
    sta a:$4302             ; A1T address
    sep #$20
    .a8
    lda #$7E
    sta a:$4304             ; A1B bank
    rep #$20
    .a16
    lda #544                ; 512 + 32 bytes
    sta a:$4305             ; DAS size
    sep #$20
    .a8
    lda #$01
    sta a:$420B             ; trigger DMA CH0

    ; --- Streaming DMA (the streaming workc) ---
    ; Check if a row is pending
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_ROW_PENDING
    beq @no_row_dma
    ; DMA up to 4 pending rows. Use WRAM for loop state (NMI must not touch ZP temp)
    sta f:$7E0000 + STREAM_LOOP_COUNT    ; remaining count (1-4)
    lda #0
    sta f:$7E0000 + STREAM_LOOP_IDX      ; VADDR table index
    tay                                   ; Y = 0 = buffer offset
@row_dma_loop:
    sep #$20
    .a8
    lda #$00                    ; VMAIN: increment by 1 word (row = contiguous)
    sta a:$2115
    rep #$20
    .a16
    ; Get VRAM address for this row from table
    lda f:$7E0000 + STREAM_LOOP_IDX
    tax
    lda f:$7E0000 + STREAM_ROW_VADDR, x
    sta a:$2116
    sep #$20
    .a8
    lda #$00                    ; DMA mode 0: A→B single register
    sta a:$4370
    lda #$18                    ; B-bus = VMDATAL
    sta a:$4371
    rep #$20
    .a16
    ; A-bus = STREAM_ROW_BUF + buffer_offset
    tya
    clc
    adc #STREAM_ROW_BUF
    sta a:$4372
    sep #$20
    .a8
    lda #$7E
    sta a:$4374
    rep #$20
    .a16
    lda #128
    sta a:$4375
    sep #$20
    .a8
    lda #$80
    sta a:$420B                 ; trigger DMA
    rep #$20
    .a16
    ; Advance to next row
    tya
    clc
    adc #128
    tay                         ; Y += 128
    lda f:$7E0000 + STREAM_LOOP_IDX
    clc
    adc #2
    sta f:$7E0000 + STREAM_LOOP_IDX
    lda f:$7E0000 + STREAM_LOOP_COUNT
    dec
    sta f:$7E0000 + STREAM_LOOP_COUNT
    bne @row_dma_loop
    ; Clear row count
    lda #0
    sta f:$7E0000 + STREAM_ROW_COUNT
@no_row_dma:
    ; --- Column DMAs ---
    .a16
    lda f:$7E0000 + STREAM_COL_COUNT
    beq @no_col_dma
    sta f:$7E0000 + STREAM_LOOP_COUNT
    lda #0
    sta f:$7E0000 + STREAM_LOOP_IDX
    tay
@col_dma_loop:
    sep #$20
    .a8
    lda #$02                    ; VMAIN: increment by 128 words (column stride)
    sta a:$2115
    rep #$20
    .a16
    lda f:$7E0000 + STREAM_LOOP_IDX
    tax
    lda f:$7E0000 + STREAM_COL_VADDR, x
    sta a:$2116
    sep #$20
    .a8
    lda #$00
    sta a:$4370
    lda #$18
    sta a:$4371
    rep #$20
    .a16
    tya
    clc
    adc #STREAM_COL_BUF
    sta a:$4372
    sep #$20
    .a8
    lda #$7E
    sta a:$4374
    rep #$20
    .a16
    lda #128
    sta a:$4375
    sep #$20
    .a8
    lda #$80
    sta a:$420B
    rep #$20
    .a16
    ; Advance to next column
    tya
    clc
    adc #128
    tay
    lda f:$7E0000 + STREAM_LOOP_IDX
    clc
    adc #2
    sta f:$7E0000 + STREAM_LOOP_IDX
    lda f:$7E0000 + STREAM_LOOP_COUNT
    dec
    sta f:$7E0000 + STREAM_LOOP_COUNT
    bne @col_dma_loop
    ; Clear column count
    lda #0
    sta f:$7E0000 + STREAM_COL_COUNT
@no_col_dma:
    sep #$20
    .a8

    ; Commit Mode 7 registers
    lda z:nmi_m7t+0
    sta a:$211B             ; M7A low
    lda z:nmi_m7t+1
    sta a:$211B             ; M7A high
    lda z:nmi_m7t+2
    sta a:$211C             ; M7B low
    lda z:nmi_m7t+3
    sta a:$211C             ; M7B high
    lda z:nmi_m7t+4
    sta a:$211D             ; M7C low
    lda z:nmi_m7t+5
    sta a:$211D             ; M7C high
    lda z:nmi_m7t+6
    sta a:$211E             ; M7D low
    lda z:nmi_m7t+7
    sta a:$211E             ; M7D high
    lda z:nmi_m7x+0
    sta a:$211F             ; M7X low
    lda z:nmi_m7x+1
    sta a:$211F             ; M7X high
    lda z:nmi_m7y+0
    sta a:$2120             ; M7Y low
    lda z:nmi_m7y+1
    sta a:$2120             ; M7Y high
    lda z:nmi_hofs+0
    sta a:$210D             ; BG1HOFS/M7HOFS low
    lda z:nmi_hofs+1
    sta a:$210D             ; high
    lda z:nmi_vofs+0
    sta a:$210E             ; BG1VOFS/M7VOFS low
    lda z:nmi_vofs+1
    sta a:$210E             ; high
    ; BG2 horizontal scroll (cloud drift)
    lda z:nmi_bg2hofs+0
    sta a:$210F             ; BG2HOFS low
    lda z:nmi_bg2hofs+1
    sta a:$210F             ; BG2HOFS high
    lda z:nmi_tm
    sta a:$212C             ; TM

    ; Color math setup: fixed color addition on BG2 (sky gradient via COLDATA)
    lda #$02                ; CGWSEL: fixed color as subscreen source
    sta a:$2130
    lda #$02                ; CGADSUB: add to BG2 only (not BG1/backdrop)
    sta a:$2131

    ; Write CGRAM 17-18 from nmi_sky_pal shadow (dark navy + medium blue)
    ; Colors 19-20 (sky blue + pale horizon) are static, set once at init.
    lda #17
    sta a:$2121             ; CGADD = color 17
    lda z:nmi_sky_pal+0     ; color 17 low byte
    sta a:$2122
    lda z:nmi_sky_pal+1     ; color 17 high byte
    sta a:$2122
    lda z:nmi_sky_pal+2     ; color 18 low byte
    sta a:$2122
    lda z:nmi_sky_pal+3     ; color 18 high byte
    sta a:$2122

    ; BG2SC hardcoded to $60 (tilemap at VRAM word $6000, 32×32)
    lda #$60
    sta a:$2108

    ; Copy HDMA channel settings from nmi_hdma to $4300-$437F
    rep #$30
    .a16
    .i16
    phb
    ldx #nmi_hdma
    ldy #$4300
    lda #(16*8)-1
    .byte $54, $00, $7E     ; MVN dst=$00, src=$7E (ca65 mvn syntax breaks bank bytes)
    plb
    sep #$20
    .a8
    ; Enable HDMA channels
    lda z:nmi_hdma_en
    sta a:$420C
    ; Force blank off, full brightness
    lda #$0F
    sta a:$2100
    ; Clear nmi_ready
    stz z:nmi_ready
@nmi_exit:
    .a8
    .i8
    ; Count frames
    inc z:nmi_count
    ; Acknowledge NMI
    lda a:$4210
    ; Restore registers
    rep #$30
    .a16
    .i16
    pld
    plb
    ply
    plx
    pla
    rti
    .a8
    .i8

; =============================================================================
; RESET - Main entry point
; =============================================================================
RESET:
    sei
    clc
    xce                     ; Native mode
    rep #$30
    .a16
    .i16
    lda #$0000
    tcd                     ; DP = $0000
    ldx #STACK_INIT
    txs

    ; Force blank
    sep #$20
    .a8
    lda #$80
    sta $2100

    ; --- Clear WRAM (banks $7E) ---
    ; Zero the first byte, then MVN fill
    lda #0
    sta f:$7E0000
    rep #$30
    .a16
    .i16
    phb
    ldx #0
    ldy #1
    lda #$FFFE              ; $10000-2 bytes
    .byte $54, $7E, $7E     ; MVN dst=$7E, src=$7E (raw bytes — ca65 breaks bank refs)
    plb
    sep #$30
    .a8
    .i8

    ; --- Initialize indirect HDMA data tables in WRAM ---
    ; pv_tm1 = $11 (BG1 + OBJ on main screen for terrain)
    lda #$11
    sta f:$7E0000 + pv_tm1
    ; pv_tm2 = $12 (BG2 + OBJ for sky region above horizon)
    lda #$12
    sta f:$7E0000 + pv_tm2
    ; (a later stage-2: fade tables removed — sky gradient lives in ROM BANK1)

    ; --- Clear PPU state ---
    stz $2105
    lda #$80
    sta $2115               ; VMAIN: increment after high byte write
    stz $212C               ; TM = 0
    stz $212D               ; TS = 0
    stz $211A               ; M7SEL = 0 (wrapping)

    ; =====================================================================
    ; Upload Mode 7 VRAM — interleaved tilemap + chardata from ROM bank 1
    ; =====================================================================
    ; Mode 7 VRAM: each word address W has low byte = tilemap[W],
    ; high byte = tile_char_data[W]. We iterate W=0..16383, reading
    ; tilemap and tile data from ROM bank 1 labels.
    rep #$20
    .a16
    stz $2116               ; VMADDL/H = $0000
    rep #$10
    .i16
    ldx #$0000
@vram_loop:
    sep #$20
    .a8
    lda f:airship_tilemap_full, x   ; tilemap byte from bank 1
    sta $2118                       ; VMDATAL
    rep #$20
    .a16
    cpx #AIRSHIP_TILES_SIZE
    bcs @char_zero
    sep #$20
    .a8
    lda f:airship_tiles, x          ; tile char data byte from bank 1
    bra @write_char
@char_zero:
    sep #$20
    .a8
    lda #$00                        ; zero-fill beyond tile data
@write_char:
    sta $2119                       ; VMDATAH
    rep #$20
    .a16
    inx
    cpx #$4000                      ; 16384 words
    bne @vram_loop

    ; =====================================================================
    ; Upload CGRAM palette from ROM bank 1
    ; =====================================================================
    sep #$20
    .a8
    stz $2121               ; CGADD = 0
    rep #$10
    .i16
    ldx #$0000
@pal_loop:
    lda f:airship_palette, x
    sta $2122
    inx
    cpx #AIRSHIP_PALETTE_SIZE
    bne @pal_loop

    ; Copy day palette to terrain shadow WRAM (DB must be $7E for abs writes)
    phb
    lda #$7E
    pha
    plb                     ; DB = $7E
    ldx #$0000
@pal_shadow_init:
    lda f:airship_palette, x
    sta a:terrain_pal_shadow, x
    inx
    cpx #AIRSHIP_PALETTE_SIZE
    bne @pal_shadow_init
    plb                     ; restore DB

    ; Re-initialize pv_tm1/pv_tm2: terrain_pal_shadow ($3560, 34 bytes) overlaps
    ; pv_tm1 ($3580) and pv_tm2 ($3581) — palette color 16 (both $0000 in track
    ; palette) would have zeroed them out. Use ldx pattern to force long addressing.
    rep #$10
    .i16
    ldx #0
    lda #$11
    sta f:$7E0000 + pv_tm1, x
    lda #$12
    sta f:$7E0000 + pv_tm2, x
    sep #$10
    .i8

    ; =====================================================================
    ; Write OBJ palette 0 (CGRAM 128-143): player car — 16 colors, 32 bytes
    ; =====================================================================
    lda #128
    sta $2121               ; CGADD = color 128
    rep #$10
    .i16
    ldx #0
@car_pal_loop:
    lda f:player_car_palette, x
    sta $2122               ; CGDATA low
    inx
    lda f:player_car_palette, x
    sta $2122               ; CGDATA high
    inx
    cpx #32                 ; 16 colors × 2 bytes
    bne @car_pal_loop
    sep #$10
    .i8

    ; =====================================================================
    ; Write OBJ palette 1 (CGRAM 144-159): AI car 0 (red) + HUD-compatible
    ; Index 0=$0000 (transparent), 1=$7FFF (white — HUD font), 2=$001F (red),
    ; 3=$04BF (highlight), 4-15=$0000
    ; =====================================================================
    lda #144
    sta $2121               ; CGADD = color 144
    rep #$10
    .i16
    ldx #0
@ai_pal_loop:
    lda f:ai_palette_data, x
    sta $2122               ; CGDATA low
    inx
    lda f:ai_palette_data, x
    sta $2122               ; CGDATA high
    inx
    cpx #32                 ; 16 colors × 2 bytes
    bne @ai_pal_loop
    ; Write OBJ palette 2 (CGRAM 160-175): AI car 1 (green)
    lda #160
    sta $2121
    ldx #0
@ai_pal_green_loop:
    lda f:ai_palette_green_data, x
    sta $2122
    inx
    lda f:ai_palette_green_data, x
    sta $2122
    inx
    cpx #32
    bne @ai_pal_green_loop

    ; Write OBJ palette 3 (CGRAM 176-191): AI car 2 (yellow)
    lda #176
    sta $2121
    ldx #0
@ai_pal_yellow_loop:
    lda f:ai_palette_yellow_data, x
    sta $2122
    inx
    lda f:ai_palette_yellow_data, x
    sta $2122
    inx
    cpx #32
    bne @ai_pal_yellow_loop

    ; Write OBJ palette 4 (CGRAM 192-207): AI car 3 (purple)
    lda #192
    sta $2121
    ldx #0
@ai_pal_purple_loop:
    lda f:ai_palette_purple_data, x
    sta $2122
    inx
    lda f:ai_palette_purple_data, x
    sta $2122
    inx
    cpx #32
    bne @ai_pal_purple_loop

    sep #$10
    .i8

    ; =====================================================================
    ; Upload HUD font tiles (28 tiles) to OBJ VRAM $4000-$41BF
    ; =====================================================================
    ; Tiles 0-15: hex digits 0-9, A-F (restored from an earlier stage)
    ; Tiles 16-27: HUD letters L,A,P,S,T,N,D,R,H,/,.,space
    ; 1bpp→4bpp expansion: bp0=pattern, bp1/bp2/bp3=0
    ; Each tile = 8 rows × 4 bytes (bp0+bp1 pair, then bp2+bp3 pair) = 32B
    ; 32 tiles × 8 bytes of 1bpp data = 256 bytes in hud_font_1bpp table
    ; Set OBSEL: base address = $4000 words (bits 2-0 = %010), 8×8/16×16
    lda #$02
    sta $2101               ; OBSEL
    rep #$20
    .a16
    lda #$4000
    sta $2116               ; VMADD = $4000 (OBJ base)
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #$0000
@hud_font_loop:
    ; Low bitplane pair (bp0 = glyph row, bp1 = 0): 8 rows
    ldy #8
@hud_bp01:
    lda f:hud_font_1bpp, x
    sta $2118               ; VMDATAL = bp0
    stz $2119               ; VMDATAH = bp1 = 0
    inx
    dey
    bne @hud_bp01
    ; High bitplane pair (bp2 = 0, bp3 = 0): 8 rows
    ldy #8
@hud_bp23:
    stz $2118               ; bp2 = 0
    stz $2119               ; bp3 = 0
    dey
    bne @hud_bp23
    ; 32 tiles × 8 bytes = 256
    cpx #256
    bne @hud_font_loop

    ; =====================================================================
    ; Upload AI Large grade top row (4 tiles) to VRAM $4400 (tiles 64-67)
    ; =====================================================================
    rep #$20
    .a16
    lda #$4400
    sta $2116               ; VMADD = $4400
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #0
@ai_lg_top_loop:
    lda f:ai_car_large_top, x
    sta $2118
    inx
    lda f:ai_car_large_top, x
    sta $2119
    inx
    cpx #128                ; 4 tiles × 32 bytes
    bne @ai_lg_top_loop

    ; Upload AI Large grade bottom row (4 tiles) to VRAM $4A00 (tiles 80-83)
    ; These are the +16 tiles for the 16×16 PPU layout
    rep #$20
    .a16
    lda #$4A00
    sta $2116               ; VMADD = $4A00 (tile 80)
    sep #$20
    .a8
    ldx #0
@ai_lg_bot_loop:
    lda f:ai_car_large_bot, x
    sta $2118
    inx
    lda f:ai_car_large_bot, x
    sta $2119
    inx
    cpx #128
    bne @ai_lg_bot_loop

    ; Upload AI Medium grade top row (2 tiles) to VRAM $4440 (tiles 68-69)
    rep #$20
    .a16
    lda #$4440
    sta $2116               ; VMADD = $4440 (tile 68)
    sep #$20
    .a8
    ldx #0
@ai_md_top_loop:
    lda f:ai_car_medium_top, x
    sta $2118
    inx
    lda f:ai_car_medium_top, x
    sta $2119
    inx
    cpx #64                 ; 2 tiles × 32 bytes
    bne @ai_md_top_loop

    ; Upload AI Medium grade bottom row (2 tiles) to VRAM $4A40 (tiles 84-85)
    rep #$20
    .a16
    lda #$4A40
    sta $2116               ; VMADD = $4A40 (tile 84)
    sep #$20
    .a8
    ldx #0
@ai_md_bot_loop:
    lda f:ai_car_medium_bot, x
    sta $2118
    inx
    lda f:ai_car_medium_bot, x
    sta $2119
    inx
    cpx #64
    bne @ai_md_bot_loop

    ; Upload AI Small grade (1 tile) to VRAM $4460 (tile 70)
    rep #$20
    .a16
    lda #$4460
    sta $2116               ; VMADD = $4460 (tile 70)
    sep #$20
    .a8
    ldx #0
@ai_sm_loop:
    lda f:ai_car_small, x
    sta $2118
    inx
    lda f:ai_car_small, x
    sta $2119
    inx
    cpx #32                 ; 1 tile × 32 bytes
    bne @ai_sm_loop
    ; Stay in .i16 — player car upload below uses 16-bit X

    ; =====================================================================
    ; Upload player car tiles (32 tiles, 4bpp) to OBJ VRAM $4200-$43FF
    ; =====================================================================
    ; 32-tile block layout (see allocations doc Section 3):
    ;   Row 0 (tiles 32-47): top strips + bottom 8x8 rows for both frames
    ;   Row 1 (tiles 48-63): 16x16 bottom strips (PPU +16 auto-read)
    ; Simple byte-pair upload: VMDATAL then VMDATAH per word (same as sky tiles)
    rep #$20
    .a16
    lda #$4200
    sta $2116               ; VMADD = $4200 (tile 32)
    sep #$20
    .a8
    ldx #$0000
@car_tile_loop:
    lda f:player_car_tiles, x
    sta $2118               ; VMDATAL
    inx
    lda f:player_car_tiles, x
    sta $2119               ; VMDATAH
    inx
    cpx #1024               ; 32 tiles × 32 bytes
    bne @car_tile_loop

    ; =====================================================================
    ; BG2 Sky Layer — upload sky gradient tiles + tilemap + palette
    ; =====================================================================
    ; 6 dithered 4bpp tiles at VRAM $5000 (192 bytes total).
    ; Palette indices: 1=dark navy, 2=medium blue, 3=sky blue, 4=pale horizon.
    ; Tiles generated by toolchain/sky_tiles_v2.py.

    rep #$20
    .a16
    lda #BG2_CHR_BASE
    sta $2116               ; VMADDL/H = $5000
    sep #$20
    .a8

    ; Upload all 6 sky tiles (192 bytes) byte-by-byte via VMDATA
    ldx #$0000
@sky_tile_loop:
    lda f:sky_tiles_v2, x
    sta $2118               ; VMDATAL
    inx
    lda f:sky_tiles_v2, x
    sta $2119               ; VMDATAH
    inx
    cpx #192
    bne @sky_tile_loop

    ; Upload BG2 sky tilemap at VRAM $6000 (32x32 = 1024 entries, 2 bytes each)
    ; Entry format: tile | $0400 (palette 1, no flip, priority 0)
    rep #$20
    .a16
    lda #BG2_MAP_BASE
    sta $2116               ; VMADDL/H = $6000
    ldx #$0000
@sky_map_loop:
    lda f:sky_tilemap_v2, x
    sta $2118               ; write tilemap entry word
    inx
    inx
    cpx #2048               ; 1024 entries x 2 bytes
    bne @sky_map_loop

    ; Write sky palette CGRAM 17-20 (4 colors, 8 bytes)
    sep #$20
    .a8
    lda #17
    sta $2121               ; CGADD = color 17
    ldx #$0000
@sky_pal_loop:
    lda f:sky_palette_v2, x
    sta $2122               ; CGDATA (auto-increments after 2 writes)
    inx
    cpx #8
    bne @sky_pal_loop

    ; Configure BG2 registers
    lda #$60                ; BG2SC: tilemap at word $6000, 32x32
    sta $2108               ; BG2SC
    lda #$50                ; BG12NBA: BG1 chr=$0000, BG2 chr=$5000
    sta $210B               ; BG12NBA

    ; Init nmi_sky_pal shadow for NMI (colors 17-18: dark navy + medium blue)
    lda #<$4008             ; dark navy low byte
    sta z:nmi_sky_pal+0
    lda #>$4008             ; dark navy high byte
    sta z:nmi_sky_pal+1
    lda #<$5810             ; medium blue low byte
    sta z:nmi_sky_pal+2
    lda #>$5810             ; medium blue high byte
    sta z:nmi_sky_pal+3

    ; =====================================================================
    ; Copy static midday gradient from ROM to WRAM active_grad_r/g/b
    ; =====================================================================
    phb
    lda #$7E
    pha
    plb                     ; DB = $7E for WRAM access
    rep #$10
    .i16
    ldx #0
@grad_r_copy:
    lda f:sky_coldata_r, x
    sta a:active_grad_r, x
    inx
    cpx #224
    bne @grad_r_copy
    ldx #0
@grad_g_copy:
    lda f:sky_coldata_g, x
    sta a:active_grad_g, x
    inx
    cpx #224
    bne @grad_g_copy
    ldx #0
@grad_b_copy:
    lda f:sky_coldata_b, x
    sta a:active_grad_b, x
    inx
    cpx #224
    bne @grad_b_copy
    plb                     ; restore DB
    sep #$10
    .i8

    ; =====================================================================
    ; Initialize OAM shadow buffer
    ; =====================================================================
    ; All sprites: Y=$F0 (off-screen). No heading/height digits in racing base.
    ; First, clear all 128 sprites to off-screen
    rep #$30
    .a16
    .i16
    ldx #0
    lda #$F000              ; Y=$F0, X=$00
@oam_clear:
    sta f:$7E0000 + oam, x
    inx
    inx
    lda #$0000              ; tile=0, attr=0
    sta f:$7E0000 + oam, x
    inx
    inx
    lda #$F000
    cpx #512                ; 128 sprites × 4 bytes
    bne @oam_clear
    ; Clear high table (32 bytes)
    lda #$0000
    ldx #512
@oam_hi_clear:
    sta f:$7E0000 + oam, x
    inx
    inx
    cpx #544
    bne @oam_hi_clear

    sep #$20
    .a8

    ; =====================================================================
    ; Initialize static HUD OAM entries (positions, fixed tiles, attributes)
    ; =====================================================================
    jsr init_hud_static
    jsr init_player_car

    ; =====================================================================
    ; Write "SFDB" magic
    ; =====================================================================
    rep #$20
    .a16
    lda #$4653              ; "SF" little-endian
    sta f:$7E0000 + DEBUG_MAGIC
    lda #$4244              ; "DB" little-endian
    sta f:$7E0000 + DEBUG_MAGIC + 2
    ; (No completion flag — a later stage loops forever)

    ; =====================================================================
    ; Initialize perspective parameters
    ; =====================================================================
    sep #$20
    .a8
    stz z:pv_buffer
    lda #PV_L1_VAL
    sta z:pv_l1
    lda #0
    sta z:pv_sh             ; SH=0 -> SA=1, uniform scale (8-bit store OK)
    stz z:pv_sh+1
    lda #2
    sta z:pv_interp         ; 2x interpolation
    lda #1
    sta z:pv_wrap
    stz z:angle             ; angle = 0
    stz z:prev_angle        ; prev_angle = 0
    lda #HEIGHT_DEFAULT
    sta z:height
    sta z:prev_height
    rep #$20
    .a16
    stz z:joy1_prev         ; clear previous joypad state (16-bit)
    stz z:frame_count
    stz z:joy1_current
    stz z:velocity          ; start at rest
    stz z:turn_rate
    sep #$20
    .a8
    stz z:drift_state       ; 0 = straight
    lda #$FF
    sta z:grip              ; full grip
    lda #1
    sta z:current_lap       ; start on lap 1
    sta z:race_position     ; stub: position 1
    stz z:lap_checkpoint

    ; Compute pv_l0, pv_s0, pv_s1 from initial height
    jsr compute_perspective_from_height

    ; Skip initial fog band — will be applied in game loop instead
    ; (Apply during init was crashing; fog works fine from the game loop)

    ; Set bgmode for NMI shadow (Mode 1 for sky portion, switched to 7 by HDMA)
    lda #$01
    sta z:nmi_bgmode
    ; TM for NMI
    lda #$11                ; BG1 + OBJ main screen
    sta z:nmi_tm

    ; Camera at track start/finish line (from track_meta.inc, pixel coordinates)
    ; track_start_x = $01F0 (pixel 496 = tile 62), track_start_y = $0308 (pixel 776 = tile 97)
    rep #$20
    .a16
    stz z:posx+0
    lda f:track_start_x
    sta z:posx+2
    stz z:posx+4
    stz z:posy+0
    lda f:track_start_y
    sta z:posy+2
    stz z:posy+4
    sep #$20
    .a8
    lda f:track_start_angle
    sta z:angle

    ; --- Streaming engine state init (the streaming work) ---
    ; Compute initial camera tile position from start pixel coordinates
    rep #$20
    .a16
    lda z:posx+2                ; pixel X (0-4095)
    lsr
    lsr
    lsr                         ; /8 = tile X
    and #$01FF                  ; clamp to 0-511
    sta z:stream_cam_tx
    sta z:stream_last_tx
    lda z:posy+2                ; pixel Y
    lsr
    lsr
    lsr
    and #$01FF
    sta z:stream_cam_ty
    sta z:stream_last_ty
    ; Clear WRAM pending flags
    ldx #0
    lda #0
    sta f:$7E0000 + STREAM_ROW_PENDING, x
    sta f:$7E0000 + STREAM_COL_PENDING, x
    sep #$20
    .a8

    ; --- 12-8b TEST: decompress row and column, write to debug region ---
    rep #$20
    .a16
    lda z:stream_cam_ty         ; logical row = start tile Y
    sta z:temp+0
    ldy #DEBUG_DECOMP_ROW       ; dest = $E080
    sep #$20
    .a8
    jsr stream_decompress_row

    rep #$20
    .a16
    lda z:stream_cam_tx         ; logical col = start tile X
    sta z:temp+0
    ldy #DEBUG_DECOMP_COL       ; dest = $E100
    sep #$20
    .a8
    jsr stream_decompress_column

    ; Write stream_cam_tx/ty to debug region
    rep #$20
    .a16
    lda z:stream_cam_tx
    ldx #0
    sta f:$7E0000 + DEBUG_STREAM_TX, x
    lda z:stream_cam_ty
    sta f:$7E0000 + DEBUG_STREAM_TY, x
    sep #$20
    .a8

    ; --- Initialize all 4 AI car structs ---
    jsr ai_init_all

    rep #$20
    .a16

    ; Set initial M7 matrix to identity
    lda #$0100
    sta z:nmi_m7t+0         ; A = 1.0
    stz z:nmi_m7t+2         ; B = 0
    stz z:nmi_m7t+4         ; C = 0
    lda #$0100
    sta z:nmi_m7t+6         ; D = 1.0

    ; =====================================================================
    ; Call pv_rebuild to generate HDMA tables
    ; =====================================================================
    jsr pv_rebuild

    ; =====================================================================
    ; Call pv_set_origin to compute M7X/M7Y
    ; =====================================================================
    ; Switch to .a16 .i8 for pv_set_origin (it expects this)
    rep #$20
    sep #$10
    .a16
    .i8
    ldy #MODE_Y_SY          ; place camera focus at scanline 168
    jsr pv_set_origin

    ; =====================================================================
    ; Set M7SEL for wrapping
    ; =====================================================================
    sep #$20
    .a8
    stz $211A               ; M7SEL = 0 (wrapping enabled)

    ; =====================================================================
    ; Copy HDMA settings to nmi_hdma for first frame
    ; =====================================================================
    rep #$30
    .a16
    .i16
    phb
    ldx #new_hdma
    ldy #nmi_hdma
    lda #(16*8)-1
    .byte $54, $7E, $7E     ; MVN dst=$7E, src=$7E (raw bytes — ca65 breaks bank refs)
    plb
    sep #$20
    .a8
    lda z:new_hdma_en
    sta z:nmi_hdma_en

    ; =====================================================================
    ; Configure Mode 7 PPU initial state
    ; =====================================================================
    ; Set Mode 7 for initial display
    lda #$07
    sta $2105               ; BGMODE = 7

    ; Identity matrix (will be overridden by HDMA per-scanline)
    stz $211B
    lda #$01
    sta $211B               ; M7A = $0100
    stz $211C
    stz $211C               ; M7B = $0000
    stz $211D
    stz $211D               ; M7C = $0000
    stz $211E
    lda #$01
    sta $211E               ; M7D = $0100

    ; M7X/M7Y from pv_set_origin
    lda z:nmi_m7x+0
    sta $211F
    lda z:nmi_m7x+1
    sta $211F
    lda z:nmi_m7y+0
    sta $2120
    lda z:nmi_m7y+1
    sta $2120

    ; HOFS/VOFS
    lda z:nmi_hofs+0
    sta $210D
    lda z:nmi_hofs+1
    sta $210D
    lda z:nmi_vofs+0
    sta $210E
    lda z:nmi_vofs+1
    sta $210E

    ; TM = BG1 + OBJ on
    lda #$11
    sta $212C


    ; Screen on, full brightness
    lda #$0F
    sta $2100

    ; Enable NMI + auto-joypad
    lda #$81
    sta $4200               ; NMITIMEN: NMI on VBlank + auto-joypad

    ; =====================================================================
    ; Persistent Game Loop
    ; =====================================================================
@game_loop:
    sep #$20
    .a8
    lda #1
    sta z:nmi_ready
    wai                     ; Wait for NMI
@wait_nmi:
    lda z:nmi_ready
    bne @wait_nmi

    ; --- Undo fog band (restore pre-attenuation bytes) ---
    sep #$20
    rep #$10
    .a8
    .i16
    jsr undo_fog_band

    ; --- Latch V-counter at start of game loop work ---
    lda a:$2137             ; SLHV: latch H/V counters
    lda a:$213D             ; OPVCT: read V-counter (low byte, 0-261)
    sta f:$7E0000 + DEBUG_VSTART
    lda a:$213D             ; OPVCT: read high bit (bit 0 only)
    and #$01
    sta f:$7E0000 + DEBUG_VSTART + 1
    lda #0
    sta f:$7E0000 + DEBUG_REBUILD  ; clear rebuild flag

    ; --- Read joypad (auto-read completed during NMI) ---
    rep #$20
    .a16
    lda a:$4218             ; JOY1 (16-bit)
    sta z:joy1_current

    ; --- Edge detection (joy1_edge not used — Select handler stripped) ---
    lda z:joy1_current
    sta z:joy1_prev         ; update prev for next frame

    ; --- Increment frame counter ---
    inc z:frame_count

    ; --- Save previous angle ---
    sep #$20
    .a8
    lda z:angle
    sta z:prev_angle

    ; --- Per-frame defaults: full grip, straight ---
    lda #$FF
    sta z:grip
    stz z:drift_state

    ; --- Acceleration / Friction (B button) ---
    rep #$20
    .a16
    lda z:joy1_current
    bit #JOY_B
    beq @do_friction

    ; B held: look up acceleration, add to velocity
    ; sep #$30: A8 + I8 — prevents dirty C.high (from prior joy read) corrupting X
    sep #$30
    .a8
    lda z:velocity+1        ; velocity high byte = speed integer (LUT index)
    tax                     ; X is 8-bit here, so only 8-bit value transferred
    lda f:accel_lut, x      ; acceleration value (0.8 fractional units)
    clc
    adc z:velocity          ; add to velocity fractional byte
    sta z:velocity
    bcc @accel_no_carry
    inc z:velocity+1        ; carry into integer byte
@accel_no_carry:
    rep #$30
    .a16
    lda z:velocity
    cmp #VELOCITY_MAX
    bcc @accel_done
    lda #VELOCITY_MAX
    sta z:velocity
@accel_done:
    bra @steer

@do_friction:
    rep #$20
    .a16
    lda z:velocity
    beq @steer              ; already stopped
    sec
    sbc #FRICTION
    bcc @vel_floor
    sta z:velocity
    bra @steer
@vel_floor:
    stz z:velocity

@steer:
    ; --- D-pad steering: LEFT/RIGHT ---
    rep #$20
    .a16
    lda z:joy1_current
    bit #JOY_LEFT
    beq @no_left
    sep #$20
    .a8
    lda z:angle
    clc
    adc #STEER_NORMAL       ; turn left (CCW)
    sta z:angle
    rep #$20
    .a16
@no_left:
    lda z:joy1_current
    bit #JOY_RIGHT
    beq @no_right
    sep #$20
    .a8
    lda z:angle
    sec
    sbc #STEER_NORMAL       ; turn right (CW)
    sta z:angle
    rep #$20
    .a16
@no_right:

    ; --- L/R shoulders: hard lean ---
    lda z:joy1_current
    bit #JOY_L
    beq @no_l_lean
    sep #$20
    .a8
    lda z:angle
    clc
    adc #STEER_LEAN         ; extra left turn
    sta z:angle
    lda #1
    sta z:drift_state
    lda #192
    sta z:grip
    rep #$20
    .a16
@no_l_lean:
    lda z:joy1_current
    bit #JOY_R
    beq @no_r_lean
    sep #$20
    .a8
    lda z:angle
    sec
    sbc #STEER_LEAN         ; extra right turn
    sta z:angle
    lda #2
    sta z:drift_state
    lda #192
    sta z:grip
    rep #$20
    .a16
@no_r_lean:

    ; --- Compute turn_rate = angle - prev_angle (signed delta) ---
    sep #$20
    .a8
    lda z:angle
    sec
    sbc z:prev_angle
    sta z:turn_rate
    stz z:turn_rate+1       ; zero-extend to 16 bits

    ; --- If angle changed, rebuild HDMA tables ---
    lda z:angle
    cmp z:prev_angle
    beq @no_rebuild
    jsr pv_rebuild          ; rebuilds HDMA tables + copies new_hdma→nmi_hdma internally
    sep #$20
    .a8
    lda #1
    sta f:$7E0000 + DEBUG_REBUILD   ; flag: pv_rebuild ran this frame
@no_rebuild:
    .a8                     ; both paths arrive in A8

    ; --- Recompute signed cos/sin for movement direction ---
    ; pv_rebuild strips signs from cosa/sina. Movement needs signed values.
    rep #$30
    .a16
    .i16
    lda z:angle
    and #$00FF
    jsr sincos              ; cosa/sina now have correct signs for movement

    ; --- Compute effective_vel (apply lean speed penalty if drifting) ---
    sep #$20
    .a8
    lda z:drift_state
    beq @full_grip
    ; Lean: effective_vel = velocity - (velocity >> 2)  [= 75% of velocity]
    rep #$20
    .a16
    lda z:velocity
    lsr a                   ; velocity / 2
    lsr a                   ; velocity / 4
    sta z:effective_vel
    lda z:velocity
    sec
    sbc z:effective_vel
    sta z:effective_vel
    bra @do_move
@full_grip:
    rep #$20
    .a16
    lda z:velocity
    sta z:effective_vel
@do_move:
    ; --- Move forward unconditionally (velocity drives movement every frame) ---
    jsr move_forward

    ; --- Streaming engine: check for tile boundary crossing ---
    jsr stream_check_update

    ; --- Player lap detection (sector-based) ---
    rep #$30
    .a16
    .i16
    jsr player_lap_check

    ; --- Recompute M7X/M7Y from current position (once, before AI projection) ---
    rep #$20
    sep #$10
    .a16
    .i8
    ldy #MODE_Y_SY
    jsr pv_set_origin

    ; --- AI car loop: steer, move, project, OAM write for all 4 cars ---
    rep #$20
    .a16
    stz z:ai_car_off            ; 16-bit zero (clears high byte for I16 reads)
    stz z:ai_oam_off            ; pre-clear high bytes
    stz z:ai_oam_hi0
    sep #$20
    .a8
    stz z:ai_car_idx
@ai_car_loop:
    ; Compute per-car OAM parameters
    ; 12 entries per car (6 used, 6 culled): entry base = 24 + car_idx * 12
    ; ai_oam_off = (24 + car_idx * 12) * 4 = 96 + car_idx * 48
    lda z:ai_car_idx
    ; Multiply by 48: x48 = x32 + x16
    asl a               ; x2
    asl a               ; x4
    asl a               ; x8
    asl a               ; x16
    sta z:ai_oam_off    ; temp = x16 (high byte already 0 from init)
    asl a               ; x32
    clc
    adc z:ai_oam_off    ; x48
    adc #96             ; + base offset (entry 24 * 4 bytes)
    sta z:ai_oam_off

    ; ai_oam_attr = (palette << 1) | priority
    ; OAM attr: bits 1-3 = palette, bits 4-5 = priority (2 = $20)
    ; palette 1=$02, palette 2=$04, palette 3=$06, palette 4=$08
    lda z:ai_car_idx
    inc a               ; palette = car_idx + 1
    asl a               ; shift to bits 1-2
    ora #$20            ; priority 2
    sta z:ai_oam_attr

    ; ai_oam_hi0: hi-table byte for first 4 entries = (24 + car_idx*12) / 4
    ; Car 0: entry 24 → byte 6.  Car 1: entry 36 → byte 9
    ; Car 2: entry 48 → byte 12. Car 3: entry 60 → byte 15
    ; = 6 + car_idx * 3
    lda z:ai_car_idx
    sta z:ai_oam_hi0    ; high byte already 0 from init
    asl a               ; x2
    clc
    adc z:ai_oam_hi0    ; x3
    adc #6              ; + 6
    sta z:ai_oam_hi0

    rep #$30
    .a16
    .i16
    jsr ai_steer
    jsr ai_move

    rep #$30
    .a16
    .i16
    jsr ai_project

    sep #$20
    .a8
    jsr ai_oam_write

    ; Advance to next car
    sep #$20
    .a8
    lda z:ai_car_off
    clc
    adc #AI_CAR_STRIDE
    sta z:ai_car_off
    inc z:ai_car_idx
    lda z:ai_car_idx
    cmp #AI_CAR_COUNT
    bcc @ai_car_loop

    ; --- Write debug region ---
    rep #$20
    .a16
    lda z:angle
    and #$00FF
    sta f:$7E0000 + DEBUG_ANGLE
    lda z:posx+2
    sta f:$7E0000 + DEBUG_POSX
    lda z:posy+2
    sta f:$7E0000 + DEBUG_POSY
    lda z:joy1_current
    sta f:$7E0000 + DEBUG_JOY
    lda z:frame_count
    sta f:$7E0000 + DEBUG_FRAMES
    sep #$20
    .a8
    lda f:$7E0000 + pv_tm1
    sta f:$7E0000 + DEBUG_TM1
    lda f:$7E0000 + pv_tm2
    sta f:$7E0000 + DEBUG_TM2
    lda #AIRSHIP_TILES_COUNT
    sta f:$7E0000 + DEBUG_TILECNT
    lda #AIRSHIP_PALETTE_COLORS
    sta f:$7E0000 + DEBUG_PALCNT
    lda z:pv_l0
    sta f:$7E0000 + DEBUG_FOG_L0
    lda z:height
    sta f:$7E0000 + DEBUG_HEIGHT
    lda z:drift_state
    sta f:$7E0000 + DEBUG_DRIFT
    lda z:current_lap
    sta f:$7E0000 + DEBUG_LAP
    lda z:race_position
    sta f:$7E0000 + DEBUG_POSITION

    ; --- Update HUD OAM entries ---
    jsr update_speed_display
    jsr update_lap_display
    jsr update_position_display
    jsr update_debug_display

    ; --- Update player car sprite ---
    jsr update_player_car

    ; --- Write velocity and turn_rate (16-bit) ---
    rep #$20
    .a16
    lda z:velocity
    sta f:$7E0000 + DEBUG_VELOCITY
    lda z:turn_rate
    sta f:$7E0000 + DEBUG_STEER
    ; Stream tile position debug
    lda z:stream_cam_tx
    sta f:$7E0000 + DEBUG_STREAM_TX
    lda z:stream_cam_ty
    sta f:$7E0000 + DEBUG_STREAM_TY
    sep #$20
    .a8

    ; --- Latch V-counter at end of game loop work ---
    lda a:$2137             ; SLHV: latch H/V counters
    lda a:$213D             ; OPVCT low byte
    sta f:$7E0000 + DEBUG_VEND
    lda a:$213D             ; OPVCT high bit
    and #$01
    sta f:$7E0000 + DEBUG_VEND + 1
    ; Compute delta = end - start (scanlines consumed)
    rep #$20
    .a16
    lda f:$7E0000 + DEBUG_VEND
    sec
    sbc f:$7E0000 + DEBUG_VSTART
    bpl :+
        clc
        adc #262            ; wrap around frame boundary
    :
    sta f:$7E0000 + DEBUG_VDELTA
    sep #$20
    .a8

    ; --- Apply fog band (5-scanline horizon attenuation) ---
    sep #$20
    rep #$10
    .a8
    .i16
    jsr apply_fog_band

    jmp @game_loop

; =============================================================================
; ai_init_all — Initialize all 4 AI car structs (called once at RESET)
; =============================================================================
; Mode: .a8 on entry
; Each car starts at a different waypoint, staggered around the circuit
; =============================================================================
ai_init_all:
    .a8
    ; Car 0: waypoint 0, Red (palette 1) — near player start
    ldx #0
    ldy #0
    jsr @init_one_car
    ; Car 1: waypoint 1, Green (palette 2) — adjacent to car 0 for dual visibility
    ldx #16
    ldy #1
    jsr @init_one_car
    ; Car 2: waypoint 6, Yellow (palette 3)
    ldx #32
    ldy #6
    jsr @init_one_car
    ; Car 3: waypoint 10, Purple (palette 4)
    ldx #48
    ldy #10
    jsr @init_one_car
    rts

; X = car WRAM offset (0,16,32,48), Y = starting waypoint index
@init_one_car:
    .a8
    ; Save car WRAM offset (X) and waypoint index (Y) to temps
    stx z:temp+0              ; save car WRAM offset
    sty z:temp+6              ; save waypoint index
    rep #$30
    .a16
    .i16
    ; Look up waypoint position using X-indexing
    tya
    and #$00FF
    asl a
    asl a                   ; wp_idx * 4 (each waypoint = 2 words = 4 bytes)
    tax
    lda f:track_waypoints+0, x  ; waypoint X
    sta z:temp+2
    lda f:track_waypoints+2, x  ; waypoint Y
    sta z:temp+4
    ; Store to car struct
    ldx z:temp+0              ; restore car WRAM offset
    lda z:temp+2
    sta f:$7E0000 + AI_X, x
    lda z:temp+4
    sta f:$7E0000 + AI_Y, x
    lda #$0600              ; velocity — 6.0 px/frame
    sta f:$7E0000 + AI_VEL, x
    lda #0
    sta f:$7E0000 + AI_CAM_Z, x
    sta f:$7E0000 + AI_SCREEN_X, x
    sep #$20
    .a8
    lda #192                ; heading east
    sta f:$7E0000 + AI_ANGLE, x
    lda z:temp+6            ; restore wp_idx from temp
    sta f:$7E0000 + AI_WP_IDX, x
    lda #3                  ; start at grade 3 (small)
    sta f:$7E0000 + AI_SIZE_GRADE, x
    lda #0
    sta f:$7E0000 + AI_SCREEN_Y, x
    sta f:$7E0000 + AI_VISIBLE, x
    sta f:$7E0000 + AI_LAP, x
    rts

; =============================================================================
; AI steering constants
; =============================================================================
AI_TURN_RATE    = 3             ; ~4.2°/frame
AI_WP_PROXIMITY = $0060         ; 96px Manhattan distance for waypoint arrival
WAYPOINT_COUNT  = 13

; 8-direction octant angle lookup table
; Index = (dy<0?4:0) | (dx<0?2:0) | (|dy|>|dx|?1:0)
; Angle mapping (SBC model): 0=N, 32=NW, 64=W, 96=SW, 128=S, 160=SE, 192=E, 224=NE
angle_lut:
    .byte 192, 160, 64, 96, 224, 0, 32, 0

; =============================================================================
; ai_steer — Turn AI heading toward current target waypoint
; =============================================================================
; Mode: .a16 .i16 on entry and exit
; Reads AI_WP_IDX, AI_X, AI_Y, AI_ANGLE from WRAM
; Writes AI_ANGLE to WRAM
; Clobbers: A, X, Y, temp+0..temp+5
; =============================================================================
ai_steer:
    .a16
    .i16
    ; --- Load target waypoint ---
    ldx z:ai_car_off
    lda f:$7E0000 + AI_WP_IDX, x
    and #$00FF              ; zero-extend byte
    asl                     ; *2
    asl                     ; *4 (each WP = 4 bytes)
    tax
    lda f:track_waypoints+0, x
    sta z:temp+0            ; target_x
    lda f:track_waypoints+2, x
    sta z:temp+2            ; target_y

    ; --- Compute dx = target_x - ai_x ---
    ldx z:ai_car_off
    lda z:temp+0
    sec
    sbc f:$7E0000 + AI_X, x
    sta z:temp+0            ; dx (signed)

    ; --- Compute dy = target_y - ai_y ---
    lda z:temp+2
    sec
    sbc f:$7E0000 + AI_Y, x
    sta z:temp+2            ; dy (signed)

    ; --- Build octant index ---
    ; Start with index = 0
    ldy #0                  ; octant accumulator

    ; Check dy sign (bit 2)
    lda z:temp+2
    bpl @dy_pos
        eor #$FFFF          ; negate: |dy|
        inc
        sta z:temp+4        ; |dy|
        iny                  ; bit 2 = 4 (will shift later)
        iny
        iny
        iny
        bra @check_dx
@dy_pos:
    .a16
    sta z:temp+4            ; |dy|
@check_dx:
    ; Check dx sign (bit 1)
    lda z:temp+0
    bpl @dx_pos
        eor #$FFFF
        inc
        sta z:temp+0        ; |dx| (reuse temp+0)
        iny                  ; bit 1 = 2
        iny
        bra @check_dom
@dx_pos:
    .a16
    ; temp+0 is already |dx| (was positive)
@check_dom:
    ; Check |dy| > |dx| (bit 0)
    lda z:temp+4            ; |dy|
    cmp z:temp+0            ; compare |dy| vs |dx|
    bcc @dx_dominant
    beq @dx_dominant
        iny                  ; bit 0 = 1
@dx_dominant:

    ; --- Look up desired angle from octant table ---
    sep #$20
    .a8
    tyx                      ; octant index Y → X
    lda f:angle_lut, x      ; desired angle (8-bit)
    sta z:temp+5            ; save desired

    ; --- Gradual turn toward desired angle ---
    ; delta = desired - current (wrapping 8-bit)
    ldx z:ai_car_off
    sec
    sbc f:$7E0000 + AI_ANGLE, x   ; A = desired - current (8-bit wrapped)
    beq @steer_done         ; already aligned

    ; Check if delta is small enough to snap
    cmp #AI_TURN_RATE+1
    bcc @snap               ; delta in [1, AI_TURN_RATE] → snap
    cmp #256-AI_TURN_RATE
    bcs @snap               ; delta in [256-RATE, 255] → snap

    ; Check turn direction: delta in [1,127] = turn right (+), [128,255] = turn left (-)
    cmp #128
    bcs @turn_left
        ; Turn right: ai_angle += AI_TURN_RATE
        lda f:$7E0000 + AI_ANGLE, x
        clc
        adc #AI_TURN_RATE
        sta f:$7E0000 + AI_ANGLE, x
        bra @steer_done
@turn_left:
    .a8
        lda f:$7E0000 + AI_ANGLE, x
        sec
        sbc #AI_TURN_RATE
        sta f:$7E0000 + AI_ANGLE, x
        bra @steer_done
@snap:
    .a8
    lda z:temp+5            ; desired angle
    sta f:$7E0000 + AI_ANGLE, x
@steer_done:
    .a8
    rep #$20
    .a16
    rts

; =============================================================================
; ai_move — Move AI car 0 forward along its heading
; =============================================================================
; Mode: .a16 .i16 on entry and exit
; Clobbers: cosa, sina, math_a, math_b, math_p, A, X, Y
; Note: Does NOT save/restore player cosa/sina — ai_project handles that.
; =============================================================================
ai_move:
    .a16
    .i16
    ; --- Compute sincos for AI heading ---
    ldx z:ai_car_off
    lda f:$7E0000 + AI_ANGLE, x
    and #$00FF              ; zero-extend byte to 16-bit
    jsr sincos              ; cosa/sina now set for AI heading

    ; --- X displacement: ai_x -= (sina * ai_vel) >> 16 ---
    lda z:sina
    sta z:math_a
    ldx z:ai_car_off
    lda f:$7E0000 + AI_VEL, x
    sta z:math_b
    sep #$10
    .i8
    jsr smul16              ; math_p = sina × ai_vel (32-bit signed)
    rep #$10
    .i16
    ldx z:ai_car_off
    lda f:$7E0000 + AI_X, x
    sec
    sbc z:math_p+2          ; subtract integer displacement
    and #$0FFF              ; wrap to 4096-pixel map
    sta f:$7E0000 + AI_X, x

    ; --- Y displacement: ai_y -= (cosa * ai_vel) >> 16 ---
    lda z:cosa
    sta z:math_a
    lda f:$7E0000 + AI_VEL, x
    sta z:math_b
    sep #$10
    .i8
    jsr smul16
    rep #$10
    .i16
    ldx z:ai_car_off
    lda f:$7E0000 + AI_Y, x
    sec
    sbc z:math_p+2
    and #$0FFF
    sta f:$7E0000 + AI_Y, x

    ; --- Waypoint proximity check ---
    ; Read target waypoint (same lookup as ai_steer)
    ldx z:ai_car_off
    lda f:$7E0000 + AI_WP_IDX, x
    and #$00FF
    asl
    asl
    tax
    ; |target_x - ai_x|
    lda f:track_waypoints+0, x
    sec
    ldx z:ai_car_off
    sbc f:$7E0000 + AI_X, x
    bpl @wp_dx_pos
        eor #$FFFF
        inc
@wp_dx_pos:
    .a16
    sta z:temp+0            ; |dx|
    ; |target_y - ai_y|
    lda f:$7E0000 + AI_WP_IDX, x
    and #$00FF
    asl
    asl
    tax
    lda f:track_waypoints+2, x
    sec
    ldx z:ai_car_off
    sbc f:$7E0000 + AI_Y, x
    bpl @wp_dy_pos
        eor #$FFFF
        inc
@wp_dy_pos:
    .a16
    ; A = |dy|, temp+0 = |dx|
    clc
    adc z:temp+0            ; Manhattan distance = |dx| + |dy|
    cmp #AI_WP_PROXIMITY
    bcs @wp_not_reached
        ; Advance to next waypoint
        sep #$20
        .a8
        ldx z:ai_car_off
        lda f:$7E0000 + AI_WP_IDX, x
        inc
        cmp #WAYPOINT_COUNT
        bcc @wp_no_wrap
            lda #0
            ; --- Lap complete: increment lap counter ---
            pha                     ; save A (0)
            lda f:$7E0000 + AI_LAP, x  ; X is still 0
            inc
            sta f:$7E0000 + AI_LAP, x
            pla                     ; restore A (0) for wp_idx store
@wp_no_wrap:
        .a8
        sta f:$7E0000 + AI_WP_IDX, x
        rep #$20
        .a16
@wp_not_reached:
    .a16
    rts

; =============================================================================
; ai_project — Camera-space transform + screen projection for AI car 0
; =============================================================================
; Mode: .a16 .i16 on entry
; Uses (nmi_m7x, nmi_m7y) as Mode 7 origin reference (NOT player position).
; Reads HDMA A coefficient at the computed scanline for correct screen_x.
; Writes ai_screen_x, ai_screen_y, ai_visible, ai_cam_z
; Copies full AI struct to debug region $E050-$E05F
; =============================================================================
ai_project:
    .a16
    .i16
    ; --- Save player cosa/sina ---
    lda z:cosa
    pha
    lda z:sina
    pha

    ; --- Recompute sincos for player angle ---
    lda z:angle
    and #$00FF
    jsr sincos

    ; --- dx = AI_X - M7X, dy = AI_Y - M7Y (world space) ---
    ldx z:ai_car_off
    lda f:$7E0000 + AI_X, x
    sec
    sbc z:nmi_m7x
    sta z:temp+0            ; dx (world-space, signed)

    lda f:$7E0000 + AI_Y, x
    sec
    sbc z:nmi_m7y
    sta z:temp+2            ; dy (world-space, signed)

    ; --- cam_z = -(dx*sina + dy*cosa) >> 8 ---
    ; Camera forward = (-sina, -cosa); cam_z = forward distance from M7 origin
    lda z:temp+0            ; dx
    sta z:math_a
    lda z:sina
    sta z:math_b
    sep #$10
    .i8
    jsr smul16              ; math_p = dx * sina
    rep #$10
    .i16
    rep #$20
    .a16
    lda z:math_p+1          ; >> 8 (bytes 1-2 of 32-bit)
    sta z:temp+6            ; partial cam_z

    lda z:temp+2            ; dy
    sta z:math_a
    lda z:cosa
    sta z:math_b
    sep #$10
    .i8
    jsr smul16
    rep #$10
    .i16
    rep #$20
    .a16
    lda z:temp+6
    clc
    adc z:math_p+1          ; (dx*sina + dy*cosa) >> 8
    ; Negate: camera forward = (-sina, -cosa)
    eor #$FFFF
    inc a
    sta z:temp+6            ; cam_z (positive = in front)

    ; --- Visibility: cam_z > 0 ---
    lda z:temp+6            ; cam_z
    bmi @ai_nv_jmp
    beq @ai_nv_jmp
    ldx z:ai_car_off
    sta f:$7E0000 + AI_CAM_Z, x
    bra @ai_do_project
@ai_nv_jmp:
    ldx z:ai_car_off
    sta f:$7E0000 + AI_CAM_Z, x
    jmp @ai_not_visible
@ai_do_project:

    ; ===== SCREEN_Y =====
    ; V = (1835008 + 816*cam_z) / (125*cam_z + 8192)
    ; Derived by solving depth = 8192*(224-V) / (ZR0 + (V-L0)*ZR_INC) for V.

    ; Denominator = 125 * cam_z + 8192 (16-bit)
    lda #125
    sta z:math_a
    lda z:temp+6            ; cam_z (positive)
    sta z:math_b
    sep #$10
    .i8
    jsr smul16
    rep #$10
    .i16
    rep #$20
    .a16
    lda z:math_p+2
    beq :+
    jmp @ai_not_visible     ; cam_z too large
:   lda z:math_p+0
    clc
    adc #8192
    bcc :+
    jmp @ai_not_visible
:   sta z:temp+14           ; denominator

    ; Numerator = 816 * cam_z + 1835008 (32-bit)
    ; 1835008 = $001C0000 = 8192 * 224
    ; 816 = ZR_INC * pv_l0 - ZR0 = 125*45 - 4809
    lda #816
    sta z:math_a
    lda z:temp+6
    sta z:math_b
    sep #$10
    .i8
    jsr smul16
    rep #$10
    .i16
    rep #$20
    .a16
    lda z:math_p+0
    sta z:math_a+0          ; low word
    lda z:math_p+2
    clc
    adc #$001C              ; + $001C0000
    sta z:math_a+2          ; math_a = 32-bit numerator

    ; udiv32: quotient = numerator / denominator
    lda z:temp+14
    sta z:math_b+0
    stz z:math_b+2
    sep #$10
    .i8
    jsr udiv32
    rep #$10
    .i16
    rep #$20
    .a16

    ; V = quotient
    lda z:math_p+2
    beq :+
    jmp @ai_not_visible
:   lda z:math_p+0
    sta z:temp+8            ; screen_y = V

    ; Bounds: pv_l0 < V < 224
    lda z:pv_l0
    and #$00FF
    cmp z:temp+8
    bcc :+
    jmp @ai_not_visible     ; V <= pv_l0
:   lda z:temp+8
    cmp #224
    bcc :+
    jmp @ai_not_visible
:

    ; Store screen_y
    sep #$20
    .a8
    ldx z:ai_car_off
    sta f:$7E0000 + AI_SCREEN_Y, x
    rep #$20
    .a16

    ; ===== SCREEN_X from HDMA coefficient table =====
    ; Read A_V, B_V at scanline V from active HDMA buffer, then:
    ;   H = 128 + (dx*256 - B_V*(V-224)) / A_V
    ; This is the exact Mode 7 inverse — guaranteed to match the hardware.

    ; Byte offset = (V - pv_l0) * 4
    sep #$20
    .a8
    lda z:temp+8            ; V (8-bit)
    sec
    sbc z:pv_l0
    rep #$20
    .a16
    and #$00FF
    asl
    asl                     ; * 4
    sta z:temp+4            ; byte offset

    ; Add active buffer offset
    sep #$20
    .a8
    jsr pv_buffer_x         ; X = 0 or PV_HDMA_STRIDE
    rep #$20
    .a16
    txa
    clc
    adc z:temp+4
    tax                     ; X = full HDMA table index

    ; Read A_V, B_V, C_V, D_V from WRAM (DB=$7E for addresses $2000+)
    phb
    pea $7E7E
    plb
    plb                     ; DB = $7E
    lda a:pv_hdma_ab0+0, x  ; A_V (signed 16-bit)
    sta z:temp+10
    lda a:pv_hdma_ab0+2, x  ; B_V (signed 16-bit)
    sta z:temp+12
    lda a:pv_hdma_cd0+0, x  ; C_V (signed 16-bit)
    sta z:math_r+4
    lda a:pv_hdma_cd0+2, x  ; D_V (signed 16-bit)
    sta z:math_r+6
    plb                     ; restore DB

    ; Path selection: use A/B equation if |A_V| >= |C_V|, else C/D equation.
    ; X equation: H = 128 + (dx*256 - B*(V-224)) / A   (uses dx, B, A)
    ; Y equation: H = 128 + (dy*256 - D*(V-224)) / C   (uses dy, D, C)
    lda z:temp+10           ; A_V
    bpl :+
    eor #$FFFF
    inc a
:   sta z:temp+4            ; |A_V| (reusing temp+4)
    lda z:math_r+4          ; C_V
    bpl :+
    eor #$FFFF
    inc a
:   ; A = |C_V|; compare with |A_V|
    cmp z:temp+4
    bcc @sx_use_ab          ; |C_V| < |A_V| → use A/B path
    ; |C_V| >= |A_V| → use C/D path
    ; divisor = C_V, multiplier = D_V, delta = dy (temp+2)
    cmp #4
    bcs :+
    jmp @ai_not_visible     ; both |A| and |C| too small
:   lda z:math_r+4          ; C_V
    sta z:temp+10           ; divisor (overwrite A_V with C_V)
    lda z:math_r+6          ; D_V
    sta z:temp+12           ; multiplier (overwrite B_V with D_V)
    ; Use dy instead of dx: copy temp+2 → temp+0 temporarily
    ; (We won't need dx again after this point)
    lda z:temp+2            ; dy
    sta z:temp+0            ; overwrite dx with dy for shared code below
    bra @sx_compute
@sx_use_ab:
    ; divisor = A_V (already in temp+10), multiplier = B_V (temp+12), delta = dx (temp+0)
    lda z:temp+4            ; |A_V|
    cmp #4
    bcs @sx_compute
    jmp @ai_not_visible
@sx_compute:

    ; Shared computation: H = 128 + (delta*256 - mult*(V-224)) / divisor
    ; delta in temp+0, mult in temp+12, divisor in temp+10

    ; mult * (V - 224) via smul16
    lda z:temp+12           ; multiplier (B_V or D_V, signed)
    sta z:math_a
    lda z:temp+8            ; V
    sec
    sbc #224                ; V - 224 (negative, signed)
    sta z:math_b
    sep #$10
    .i8
    jsr smul16              ; math_p = mult * (V-224)
    rep #$10
    .i16
    rep #$20
    .a16
    ; Save mult*(V-224) to math_r
    lda z:math_p+0
    sta z:math_r+0
    lda z:math_p+2
    sta z:math_r+2

    ; Build delta*256 as 32-bit signed in math_a
    ; delta is in temp+0 (signed 16-bit)
    ; delta*256 byte layout: [0, delta_lo, delta_hi, sign_ext]
    sep #$20
    .a8
    stz z:math_a+0          ; byte 0 = 0
    lda z:temp+0            ; delta low byte
    sta z:math_a+1          ; byte 1
    lda z:temp+1            ; delta high byte
    sta z:math_a+2          ; byte 2
    bpl @sx_dx_pos
    lda #$FF
    bra @sx_dx_ext
@sx_dx_pos:
    lda #$00
@sx_dx_ext:
    sta z:math_a+3          ; byte 3 = sign extension
    rep #$20
    .a16

    ; numerator = delta*256 - mult*(V-224) (32-bit signed)
    lda z:math_a+0
    sec
    sbc z:math_r+0
    sta z:math_a+0
    lda z:math_a+2
    sbc z:math_r+2
    sta z:math_a+2

    ; Signed division: numerator / divisor
    ; Result sign = XOR of numerator and divisor sign bits
    lda z:math_a+2
    eor z:temp+10
    sta z:temp+14           ; bit 15 = result sign

    ; Make numerator positive
    lda z:math_a+2
    bpl @sx_num_pos
    lda z:math_a+0
    eor #$FFFF
    clc
    adc #1
    sta z:math_a+0
    lda z:math_a+2
    eor #$FFFF
    adc #0
    sta z:math_a+2
@sx_num_pos:
    ; Make divisor positive
    lda z:temp+10           ; divisor (A_V or C_V)
    bpl @sx_div_pos
    eor #$FFFF
    inc a
@sx_div_pos:
    sta z:math_b+0
    stz z:math_b+2

    ; udiv32: |numerator| / |A_V|
    sep #$10
    .i8
    jsr udiv32
    rep #$10
    .i16
    rep #$20
    .a16

    ; Quotient overflow check
    lda z:math_p+2
    bne @ai_not_visible
    lda z:math_p+0
    cmp #256
    bcs @ai_not_visible

    ; Apply result sign
    lda z:temp+14
    bpl @sx_result_pos
    lda z:math_p+0
    eor #$FFFF
    inc a
    bra @sx_add_128
@sx_result_pos:
    lda z:math_p+0
@sx_add_128:
    ; screen_x = 128 + signed_offset (16-bit signed result)
    clc
    adc #128
    ; Bounds check: allow [-32, 288] for composite sprite partial visibility
    ; A is 16-bit signed: check A >= -32 (i.e., A+32 >= 0) and A < 288
    sta z:temp+12           ; save screen_x
    clc
    adc #32                 ; shift range: [0, 320) means visible
    cmp #320
    bcs @ai_not_visible     ; unsigned compare: outside [0,320) → off screen

    ; Store 16-bit screen_x and mark visible
    ldx z:ai_car_off
    lda z:temp+12
    sta f:$7E0000 + AI_SCREEN_X, x  ; 16-bit store (AI_SCREEN_X is now 2B)
    sep #$20
    .a8
    lda #1
    sta f:$7E0000 + AI_VISIBLE, x
    bra @ai_debug_dump

@ai_not_visible:
    sep #$20
    .a8
    ldx z:ai_car_off
    lda #0
    sta f:$7E0000 + AI_VISIBLE, x

@ai_debug_dump:
    .a8
    rep #$30
    .a16
    .i16
    ; Copy 16 bytes from AI_BASE+car_off to DEBUG_AI0+car_off
    lda z:ai_car_off
    and #$00FF
    clc
    adc #16
    sta z:temp+14           ; end offset
    ldx z:ai_car_off
@ai_dump_loop:
    lda f:$7E0000 + AI_BASE, x
    sta f:$7E0000 + DEBUG_AI0, x
    inx
    inx
    cpx z:temp+14
    bcc @ai_dump_loop

    ; Restore player cosa/sina
    pla
    sta z:sina
    pla
    sta z:cosa
    rts

; =============================================================================
; ai_oam_write — Write OAM entries for AI car 0 with 4 size grades
; =============================================================================
; Mode: .a8 on entry
; Reads AI_VISIBLE, AI_SCREEN_X (16-bit), AI_SCREEN_Y, AI_CAM_Z, AI_SIZE_GRADE
; Grade 0 (XL):    entries 24-29 (2×16×16 + 4×8×8), reuse player tiles, pal 1
; Grade 1 (Large): entries 24-25 (2×16×16), tiles 64-67, pal 1
; Grade 2 (Medium): entry 24 (1×16×16), tiles 68-69, pal 1
; Grade 3 (Small): entry 24 (1×8×8), tile 70, pal 1
; Hysteresis: separate grow/shrink thresholds prevent grade flickering.
; OAM hi-table bytes 6-7 updated each frame for size + X9 bits.
; =============================================================================
AI_OAM_ENTRY = 24
AI_OAM_ADDR  = oam + AI_OAM_ENTRY * 4   ; $3300 + 96 = $3360
AI_OAM_ATTR  = $22                        ; pri=2, pal=1
AI_OAM_HI6   = oam + 512 + 6             ; hi-table byte 6 (entries 24-27)
AI_OAM_HI7   = oam + 512 + 7             ; hi-table byte 7 (entries 28-31)

; Hysteresis thresholds
AI_GRADE_XL_GROW   = 44
AI_GRADE_XL_SHRINK = 48
AI_GRADE_LG_GROW   = 104
AI_GRADE_LG_SHRINK = 112
AI_GRADE_MD_GROW   = 200
AI_GRADE_MD_SHRINK = 208

; Tile numbers per grade
AI_TILE_LARGE  = 64
AI_TILE_MEDIUM = 68
AI_TILE_SMALL  = 70

ai_oam_write:
    .a8
    ldx z:ai_car_off
    lda f:$7E0000 + AI_VISIBLE, x
    bne @ai_oam_visible
    jmp @ai_oam_cull_all

@ai_oam_visible:
    ; Pre-load AI struct fields into temp vars for grade writers
    ; (grade writers use X for OAM offset, can't also use it for AI struct)
    rep #$20
    .a16
    lda f:$7E0000 + AI_SCREEN_X, x     ; 16-bit signed
    sta z:temp+10
    sep #$20
    .a8
    lda f:$7E0000 + AI_SCREEN_Y, x
    sta z:temp+12

@ai_grade_select:
    ; Read cam_z (16-bit, positive — confirmed by ai_project)
    rep #$20
    .a16
    ldx z:ai_car_off
    lda f:$7E0000 + AI_CAM_Z, x
    sta z:temp+0              ; temp+0 = cam_z

    ; Read current grade and apply hysteresis
    sep #$20
    .a8
    lda f:$7E0000 + AI_SIZE_GRADE, x
    cmp #0
    beq @check_from_xl
    cmp #1
    beq @check_from_lg
    cmp #2
    beq @check_from_md
    bra @check_from_sm

@check_from_xl:
    rep #$20
    .a16
    lda z:temp+0
    cmp #AI_GRADE_XL_SHRINK
    bcc @set_grade_xl
    cmp #AI_GRADE_LG_SHRINK
    bcc @set_grade_lg
    cmp #AI_GRADE_MD_SHRINK
    bcc @set_grade_md
    bra @set_grade_sm

@check_from_lg:
    rep #$20
    .a16
    lda z:temp+0
    cmp #AI_GRADE_XL_GROW
    bcc @set_grade_xl
    cmp #AI_GRADE_LG_SHRINK
    bcc @set_grade_lg
    cmp #AI_GRADE_MD_SHRINK
    bcc @set_grade_md
    bra @set_grade_sm

@check_from_md:
    rep #$20
    .a16
    lda z:temp+0
    cmp #AI_GRADE_XL_GROW
    bcc @set_grade_xl
    cmp #AI_GRADE_LG_GROW
    bcc @set_grade_lg
    cmp #AI_GRADE_MD_SHRINK
    bcc @set_grade_md
    bra @set_grade_sm

@check_from_sm:
    rep #$20
    .a16
    lda z:temp+0
    cmp #AI_GRADE_XL_GROW
    bcc @set_grade_xl
    cmp #AI_GRADE_LG_GROW
    bcc @set_grade_lg
    cmp #AI_GRADE_MD_GROW
    bcc @set_grade_md
    bra @set_grade_sm

@set_grade_xl:
    sep #$20
    .a8
    ldx z:ai_car_off
    lda #0
    sta f:$7E0000 + AI_SIZE_GRADE, x
    jmp @write_grade_xl
@set_grade_lg:
    sep #$20
    .a8
    ldx z:ai_car_off
    lda #1
    sta f:$7E0000 + AI_SIZE_GRADE, x
    jmp @write_grade_lg
@set_grade_md:
    sep #$20
    .a8
    ldx z:ai_car_off
    lda #2
    sta f:$7E0000 + AI_SIZE_GRADE, x
    jmp @write_grade_md
@set_grade_sm:
    sep #$20
    .a8
    ldx z:ai_car_off
    lda #3
    sta f:$7E0000 + AI_SIZE_GRADE, x
    jmp @write_grade_sm

; =============================================================================
; Grade 0 (XL): entries 24-29, reuse player tiles 32-39, pal 1
; Anchor: (screen_x - 16, screen_y - 12)
; Hi-table: byte6 = size bits $0A | X9 bits, byte7 = $00
; =============================================================================
@write_grade_xl:
    .a8
    ldx z:ai_oam_off
    ; Build hi-table byte 6 base: entries 24,25 = large → bits 1,3 set = $0A
    lda #$0A
    sta z:temp+6              ; will OR in X9 bits for entries 24-27
    stz z:temp+7              ; hi-table byte 7 (entries 28-29 X9 bits)

    ; Compute anchor
    rep #$20
    .a16
    lda z:temp+10
    sec
    sbc #16
    sta z:temp+2              ; anchor_x (signed 16-bit)
    sep #$20
    .a8
    lda z:temp+12
    sec
    sbc #12
    sta z:temp+4              ; anchor_y

    ; --- Entry 24: (anchor_x, anchor_y), tile 32, 16×16 ---
    lda z:temp+4
    sta f:$7E0000 + oam + OAM_Y, x
    lda #32
    sta f:$7E0000 + oam + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + OAM_ATTR, x
    ; Write X low byte, accumulate X9 bit 0
    rep #$20
    .a16
    lda z:temp+2              ; anchor_x
    sep #$20
    .a8
    sta f:$7E0000 + oam + OAM_X, x
    ; X9 for entry 24 → bit 0 of hi-table byte 6
    rep #$20
    .a16
    lda z:temp+2
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$01
    sta z:temp+6
    rep #$20
    .a16
:
    ; --- Entry 25: (anchor_x+16, anchor_y), tile 34, 16×16 ---
    lda z:temp+2
    clc
    adc #16
    sta z:temp+8              ; sub_x for entry 25
    sep #$20
    .a8
    lda z:temp+4
    sta f:$7E0000 + oam + 4 + OAM_Y, x
    lda #34
    sta f:$7E0000 + oam + 4 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 4 + OAM_ATTR, x
    lda z:temp+8              ; low byte of sub_x
    sta f:$7E0000 + oam + 4 + OAM_X, x
    ; X9 for entry 25 → bit 2 of hi-table byte 6
    rep #$20
    .a16
    lda z:temp+8
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$04
    sta z:temp+6
    rep #$20
    .a16
:
    ; --- Entries 26-29: 8×8 bottom row, Y = anchor_y+16 ---
    sep #$20
    .a8
    lda z:temp+4
    clc
    adc #16
    sta z:temp+5              ; bot_y

    ; Entry 26: (anchor_x, bot_y), tile 36
    lda z:temp+5
    sta f:$7E0000 + oam + 8 + OAM_Y, x
    lda #36
    sta f:$7E0000 + oam + 8 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 8 + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    sep #$20
    .a8
    sta f:$7E0000 + oam + 8 + OAM_X, x
    ; X9 for entry 26 → byte 6 bit 4
    rep #$20
    .a16
    lda z:temp+2
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$10
    sta z:temp+6
    rep #$20
    .a16
:
    ; Entry 27: (anchor_x+8, bot_y), tile 37
    sep #$20
    .a8
    lda z:temp+5
    sta f:$7E0000 + oam + 12 + OAM_Y, x
    lda #37
    sta f:$7E0000 + oam + 12 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 12 + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    clc
    adc #8
    sta z:temp+8              ; save for X9 check
    sep #$20
    .a8
    sta f:$7E0000 + oam + 12 + OAM_X, x
    ; X9 for entry 27 → byte 6 bit 6
    rep #$20
    .a16
    lda z:temp+8
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$40
    sta z:temp+6
    rep #$20
    .a16
:
    ; Entry 28: (anchor_x+16, bot_y), tile 38
    sep #$20
    .a8
    lda z:temp+5
    sta f:$7E0000 + oam + 16 + OAM_Y, x
    lda #38
    sta f:$7E0000 + oam + 16 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 16 + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    clc
    adc #16
    sta z:temp+8              ; save for X9 check
    sep #$20
    .a8
    sta f:$7E0000 + oam + 16 + OAM_X, x
    ; X9 for entry 28 → byte 7 bit 0
    rep #$20
    .a16
    lda z:temp+8
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+7
    ora #$01
    sta z:temp+7
    rep #$20
    .a16
:
    ; Entry 29: (anchor_x+24, bot_y), tile 39
    sep #$20
    .a8
    lda z:temp+5
    sta f:$7E0000 + oam + 20 + OAM_Y, x
    lda #39
    sta f:$7E0000 + oam + 20 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 20 + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    clc
    adc #24
    sta z:temp+8              ; save for X9 check
    sep #$20
    .a8
    sta f:$7E0000 + oam + 20 + OAM_X, x
    ; X9 for entry 29 → byte 7 bit 2
    rep #$20
    .a16
    lda z:temp+8
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+7
    ora #$04
    sta z:temp+7
    rep #$20
    .a16
:
    ; Write hi-table bytes
    sep #$20
    .a8
    lda z:temp+6
    phx
    ldx z:ai_oam_hi0
    sta f:$7E0000 + oam + 512, x
    lda z:temp+7
    inx
    sta f:$7E0000 + oam + 512, x
    plx
    ; Cull entries 6-11 (unused tail of 12-entry allocation)
    lda #OAM_OFFSCREEN
    sta f:$7E0000 + oam + 24 + OAM_Y, x
    sta f:$7E0000 + oam + 28 + OAM_Y, x
    sta f:$7E0000 + oam + 32 + OAM_Y, x
    sta f:$7E0000 + oam + 36 + OAM_Y, x
    sta f:$7E0000 + oam + 40 + OAM_Y, x
    sta f:$7E0000 + oam + 44 + OAM_Y, x
    rts

; =============================================================================
; Grade 1 (Large): entries 24-25 (2×16×16), tiles 64/66, pal 1
; Anchor: (screen_x - 16, screen_y - 8)
; =============================================================================
@write_grade_lg:
    .a8
    ldx z:ai_oam_off
    lda #$0A                  ; entries 24,25 = large size
    sta z:temp+6

    rep #$20
    .a16
    lda z:temp+10
    sec
    sbc #16
    sta z:temp+2
    sep #$20
    .a8
    lda z:temp+12
    sec
    sbc #8
    sta z:temp+4

    ; Entry 24: tile 64
    sta f:$7E0000 + oam + OAM_Y, x
    lda #AI_TILE_LARGE
    sta f:$7E0000 + oam + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    sep #$20
    .a8
    sta f:$7E0000 + oam + OAM_X, x
    rep #$20
    .a16
    lda z:temp+2
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$01
    sta z:temp+6
    rep #$20
    .a16
:
    ; Entry 25: tile 66
    lda z:temp+2
    clc
    adc #16
    sta z:temp+8
    sep #$20
    .a8
    lda z:temp+4
    sta f:$7E0000 + oam + 4 + OAM_Y, x
    lda #AI_TILE_LARGE + 2
    sta f:$7E0000 + oam + 4 + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + 4 + OAM_ATTR, x
    lda z:temp+8
    sta f:$7E0000 + oam + 4 + OAM_X, x
    rep #$20
    .a16
    lda z:temp+8
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$04
    sta z:temp+6
    rep #$20
    .a16
:
    ; Write hi-table + cull entries 26-29
    sep #$20
    .a8
    lda z:temp+6
    phx
    ldx z:ai_oam_hi0
    sta f:$7E0000 + oam + 512, x
    lda #$00
    inx
    sta f:$7E0000 + oam + 512, x
    plx
    lda #OAM_OFFSCREEN
    sta f:$7E0000 + oam + 8 + OAM_Y, x
    sta f:$7E0000 + oam + 12 + OAM_Y, x
    sta f:$7E0000 + oam + 16 + OAM_Y, x
    sta f:$7E0000 + oam + 20 + OAM_Y, x
    ; Cull entries 6-11
    sta f:$7E0000 + oam + 24 + OAM_Y, x
    sta f:$7E0000 + oam + 28 + OAM_Y, x
    sta f:$7E0000 + oam + 32 + OAM_Y, x
    sta f:$7E0000 + oam + 36 + OAM_Y, x
    sta f:$7E0000 + oam + 40 + OAM_Y, x
    sta f:$7E0000 + oam + 44 + OAM_Y, x
    rts

; =============================================================================
; Grade 2 (Medium): entry 24 (1×16×16), tile 68, pal 1
; Center: (screen_x - 8, screen_y - 8)
; =============================================================================
@write_grade_md:
    .a8
    ldx z:ai_oam_off
    lda #$02                  ; entry 24 = large size
    sta z:temp+6

    rep #$20
    .a16
    lda z:temp+10
    sec
    sbc #8
    sta z:temp+2
    sep #$20
    .a8
    lda z:temp+12
    sec
    sbc #8
    sta f:$7E0000 + oam + OAM_Y, x
    lda #AI_TILE_MEDIUM
    sta f:$7E0000 + oam + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+2
    sep #$20
    .a8
    sta f:$7E0000 + oam + OAM_X, x
    rep #$20
    .a16
    lda z:temp+2
    and #$0100
    beq :+
    sep #$20
    .a8
    lda z:temp+6
    ora #$01
    sta z:temp+6
    rep #$20
    .a16
:
    sep #$20
    .a8
    lda z:temp+6
    phx
    ldx z:ai_oam_hi0
    sta f:$7E0000 + oam + 512, x
    lda #$00
    inx
    sta f:$7E0000 + oam + 512, x
    plx
    lda #OAM_OFFSCREEN
    sta f:$7E0000 + oam + 4 + OAM_Y, x
    sta f:$7E0000 + oam + 8 + OAM_Y, x
    sta f:$7E0000 + oam + 12 + OAM_Y, x
    sta f:$7E0000 + oam + 16 + OAM_Y, x
    sta f:$7E0000 + oam + 20 + OAM_Y, x
    ; Cull entries 6-11
    sta f:$7E0000 + oam + 24 + OAM_Y, x
    sta f:$7E0000 + oam + 28 + OAM_Y, x
    sta f:$7E0000 + oam + 32 + OAM_Y, x
    sta f:$7E0000 + oam + 36 + OAM_Y, x
    sta f:$7E0000 + oam + 40 + OAM_Y, x
    sta f:$7E0000 + oam + 44 + OAM_Y, x
    rts

; =============================================================================
; Grade 3 (Small): entry 24 (1×8×8), tile 70, pal 1
; Center: (screen_x - 4, screen_y - 4)
; =============================================================================
@write_grade_sm:
    .a8
    ; Hi-table: all small, clear X9 bits
    lda #$00
    ldx z:ai_oam_hi0
    sta f:$7E0000 + oam + 512, x
    inx
    sta f:$7E0000 + oam + 512, x
    ldx z:ai_oam_off

    lda z:temp+12
    sec
    sbc #4
    sta f:$7E0000 + oam + OAM_Y, x
    lda #AI_TILE_SMALL
    sta f:$7E0000 + oam + OAM_TILE, x
    lda z:ai_oam_attr
    sta f:$7E0000 + oam + OAM_ATTR, x
    rep #$20
    .a16
    lda z:temp+10
    sec
    sbc #4
    sep #$20
    .a8
    sta f:$7E0000 + oam + OAM_X, x

    ; Cull entries 1-11
    lda #OAM_OFFSCREEN
    sta f:$7E0000 + oam + 4 + OAM_Y, x
    sta f:$7E0000 + oam + 8 + OAM_Y, x
    sta f:$7E0000 + oam + 12 + OAM_Y, x
    sta f:$7E0000 + oam + 16 + OAM_Y, x
    sta f:$7E0000 + oam + 20 + OAM_Y, x
    sta f:$7E0000 + oam + 24 + OAM_Y, x
    sta f:$7E0000 + oam + 28 + OAM_Y, x
    sta f:$7E0000 + oam + 32 + OAM_Y, x
    sta f:$7E0000 + oam + 36 + OAM_Y, x
    sta f:$7E0000 + oam + 40 + OAM_Y, x
    sta f:$7E0000 + oam + 44 + OAM_Y, x
    rts

; =============================================================================
; Cull all 12 AI OAM entries (not visible)
; =============================================================================
@ai_oam_cull_all:
    .a8
    ldx z:ai_oam_off
    lda #OAM_OFFSCREEN
    sta f:$7E0000 + oam + OAM_Y, x
    sta f:$7E0000 + oam + 4 + OAM_Y, x
    sta f:$7E0000 + oam + 8 + OAM_Y, x
    sta f:$7E0000 + oam + 12 + OAM_Y, x
    sta f:$7E0000 + oam + 16 + OAM_Y, x
    sta f:$7E0000 + oam + 20 + OAM_Y, x
    sta f:$7E0000 + oam + 24 + OAM_Y, x
    sta f:$7E0000 + oam + 28 + OAM_Y, x
    sta f:$7E0000 + oam + 32 + OAM_Y, x
    sta f:$7E0000 + oam + 36 + OAM_Y, x
    sta f:$7E0000 + oam + 40 + OAM_Y, x
    sta f:$7E0000 + oam + 44 + OAM_Y, x
    rts

; =============================================================================
; player_lap_check — Sector-based lap detection
; =============================================================================
; Divides the 4096×4096 track into 4 sectors based on player position.
; Player must visit sectors 0→1→2→3→0 in order for a lap to count.
; lap_checkpoint ($5F) tracks highest sector reached this lap.
; current_lap ($5D) increments on sector 3→0 transition.
; Mode: .a16/.i16 on entry, preserved on exit
; =============================================================================
SECTOR_Y_SOUTH  = 2400
SECTOR_Y_NORTH  = 1200
SECTOR_X_MID    = 2048

player_lap_check:
    .a16
    ; Determine current sector from posy_int, posx_int
    lda z:posy+2
    cmp #SECTOR_Y_SOUTH
    bcs @sector_0               ; Y >= 600 → sector 0 (south / start-finish)
    cmp #SECTOR_Y_NORTH
    bcc @sector_2               ; Y < 300 → sector 2 (north)
    lda z:posx+2
    cmp #SECTOR_X_MID
    bcs @sector_1               ; X >= 512 → sector 1 (east)
    bra @sector_3               ; X < 512 → sector 3 (west)

@sector_0:
    sep #$20
    .a8
    lda z:lap_checkpoint
    cmp #3
    bne @set_s0                 ; only complete lap if coming from sector 3
    ; LAP COMPLETE
    lda z:current_lap
    inc
    cmp #4
    bcs @set_s0                 ; cap at 3
    sta z:current_lap
@set_s0:
    stz z:lap_checkpoint        ; reset to sector 0
    rep #$20
    .a16
    rts

@sector_1:
    sep #$20
    .a8
    lda z:lap_checkpoint
    bne @done_a8                ; only advance from sector 0
    lda #1
    sta z:lap_checkpoint
    bra @done_a8

@sector_2:
    sep #$20
    .a8
    lda z:lap_checkpoint
    cmp #1
    bne @done_a8                ; only advance from sector 1
    lda #2
    sta z:lap_checkpoint
    bra @done_a8

@sector_3:
    sep #$20
    .a8
    lda z:lap_checkpoint
    cmp #2
    bne @done_a8                ; only advance from sector 2
    lda #3
    sta z:lap_checkpoint
    ; fall through

@done_a8:
    rep #$20
    .a16
    rts


; =============================================================================
; move_forward - Add velocity based on current angle to position
; =============================================================================
; Uses cosa/sina (set by sincos) as direction vector.
; Reads effective_vel ($32-$33, 8.8) as speed — set by caller before JSR.
; Multiplies effective_vel × sina/cosa (8.8 × 8.8 → 16.16), adds to position.
; Mode: .a16/.i16 on entry
; =============================================================================
move_forward:
    .a16
    ; X velocity = sina × effective_vel (8.8 × 8.8 → 16.16)
    lda z:sina
    sta z:math_a
    lda z:effective_vel
    sta z:math_b
    sep #$10
    .i8
    jsr smul16              ; math_p = sina × effective_vel (32-bit signed)
    rep #$10
    .i16
    rep #$20
    .a16
    ; Subtract result from posx (forward = decreasing x in Mode 7 coords)
    lda z:posx+0
    sec
    sbc z:math_p+0
    sta z:posx+0
    lda z:posx+2
    sbc z:math_p+2
    and #$0FFF              ; wrap to 0-4095
    sta z:posx+2

    ; Y velocity = cosa × effective_vel
    lda z:cosa
    sta z:math_a
    lda z:effective_vel
    sta z:math_b
    sep #$10
    .i8
    jsr smul16
    rep #$10
    .i16
    rep #$20
    .a16
    lda z:posy+0
    sec
    sbc z:math_p+0
    sta z:posy+0
    lda z:posy+2
    sbc z:math_p+2
    and #$0FFF
    sta z:posy+2
    rts


; =============================================================================
; HUD OAM base address (WRAM $3300, entry N = $3300 + N*4)
; =============================================================================
HUD_OAM        = oam            ; = $3300
; OAM entry field offsets
OAM_X          = 0
OAM_Y          = 1
OAM_TILE       = 2
OAM_ATTR       = 3
; OAM attr byte: [flipY|flipX|pri1|pri0|pal2|pal1|pal0|nameTable]
; $32 = %0011_0010 → priority=11=3, palette=001=OBJ_pal1, nameTable=0
HUD_ATTR       = $32
; HUD tile indices for static characters
TILE_L         = 16
TILE_A         = 17
TILE_P         = 18
TILE_S         = 19
TILE_T         = 20
TILE_N         = 21
TILE_D         = 22
TILE_R         = 23
TILE_H         = 24
TILE_SLASH     = 25
TILE_DOT       = 26
TILE_SPACE     = 27
TILE_3         = 3              ; digit "3" for total-laps display
; Debug HUD tiles (added for AI projection debugging)
TILE_Z         = 28
TILE_Y         = 29
TILE_V         = 30
TILE_DASH      = 31
; Off-screen Y value (hides a sprite)
OAM_OFFSCREEN  = $F0

; =============================================================================
; init_hud_static — Write fixed X/Y/tile/attr for all 13 HUD OAM entries
; =============================================================================
; Called once during RESET (forced-blank, A8/I16).
; Sets up entries 0-12. Dynamic tile indices are overwritten each frame by
; update_speed_display / update_lap_display / update_position_display.
; =============================================================================
init_hud_static:
    sep #$20
    .a8
    rep #$10
    .i16

    ; --- Speed display: entries 0-3 (upper-left, Y=8) ---
    ; Entry 0: tens digit (X=8)
    lda #8
    sta f:$7E0000 + HUD_OAM + 0*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 0*4 + OAM_Y
    lda #0                      ; tile = "0" placeholder (updated per frame)
    sta f:$7E0000 + HUD_OAM + 0*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 0*4 + OAM_ATTR

    ; Entry 1: ones digit (X=16)
    lda #16
    sta f:$7E0000 + HUD_OAM + 1*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 1*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 1*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 1*4 + OAM_ATTR

    ; Entry 2: decimal point (X=24, static tile)
    lda #24
    sta f:$7E0000 + HUD_OAM + 2*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 2*4 + OAM_Y
    lda #TILE_DOT
    sta f:$7E0000 + HUD_OAM + 2*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 2*4 + OAM_ATTR

    ; Entry 3: fraction digit (X=32)
    lda #32
    sta f:$7E0000 + HUD_OAM + 3*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 3*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 3*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 3*4 + OAM_ATTR

    ; --- Lap display: entries 4-9 (upper-right, Y=8) ---
    ; Entry 4: "L" (X=192)
    lda #192
    sta f:$7E0000 + HUD_OAM + 4*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 4*4 + OAM_Y
    lda #TILE_L
    sta f:$7E0000 + HUD_OAM + 4*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 4*4 + OAM_ATTR

    ; Entry 5: "A" (X=200)
    lda #200
    sta f:$7E0000 + HUD_OAM + 5*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 5*4 + OAM_Y
    lda #TILE_A
    sta f:$7E0000 + HUD_OAM + 5*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 5*4 + OAM_ATTR

    ; Entry 6: "P" (X=208)
    lda #208
    sta f:$7E0000 + HUD_OAM + 6*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 6*4 + OAM_Y
    lda #TILE_P
    sta f:$7E0000 + HUD_OAM + 6*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 6*4 + OAM_ATTR

    ; Entry 7: current lap digit (X=216, updated per frame)
    lda #216
    sta f:$7E0000 + HUD_OAM + 7*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 7*4 + OAM_Y
    lda #1                      ; tile "1" placeholder
    sta f:$7E0000 + HUD_OAM + 7*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 7*4 + OAM_ATTR

    ; Entry 8: "/" separator (X=224)
    lda #224
    sta f:$7E0000 + HUD_OAM + 8*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 8*4 + OAM_Y
    lda #TILE_SLASH
    sta f:$7E0000 + HUD_OAM + 8*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 8*4 + OAM_ATTR

    ; Entry 9: "3" total laps (X=232)
    lda #232
    sta f:$7E0000 + HUD_OAM + 9*4 + OAM_X
    lda #8
    sta f:$7E0000 + HUD_OAM + 9*4 + OAM_Y
    lda #TILE_3
    sta f:$7E0000 + HUD_OAM + 9*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 9*4 + OAM_ATTR

    ; --- Position display: entries 10-12 (lower-left, Y=200) ---
    ; Entry 10: position digit (X=8)
    lda #8
    sta f:$7E0000 + HUD_OAM + 10*4 + OAM_X
    lda #200
    sta f:$7E0000 + HUD_OAM + 10*4 + OAM_Y
    lda #1
    sta f:$7E0000 + HUD_OAM + 10*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 10*4 + OAM_ATTR

    ; Entry 11: suffix char 1 (X=16)
    lda #16
    sta f:$7E0000 + HUD_OAM + 11*4 + OAM_X
    lda #200
    sta f:$7E0000 + HUD_OAM + 11*4 + OAM_Y
    lda #TILE_S
    sta f:$7E0000 + HUD_OAM + 11*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 11*4 + OAM_ATTR

    ; Entry 12: suffix char 2 (X=24)
    lda #24
    sta f:$7E0000 + HUD_OAM + 12*4 + OAM_X
    lda #200
    sta f:$7E0000 + HUD_OAM + 12*4 + OAM_Y
    lda #TILE_T
    sta f:$7E0000 + HUD_OAM + 12*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 12*4 + OAM_ATTR

    ; --- AI debug display: entries 25-35 (second row, Y=18) ---
    ; Debug row (Y=18): nearest visible car info
    ; Layout: [car#][grade] [sx_h][sx_t][sx_o] [sy_h][sy_t][sy_o] [cz_h][cz_t]
    ; 10 entries (72-82) — outside AI car OAM range (24-71)

    ; Entry 72: car index
    lda #8
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_Y
    lda #TILE_DASH
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_ATTR

    ; Entry 73: size grade
    lda #16
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_Y
    lda #TILE_DASH
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_ATTR

    ; Entry 74: screen_x hundreds
    lda #28
    sta f:$7E0000 + HUD_OAM + 74*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 74*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 74*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 74*4 + OAM_ATTR

    ; Entry 75: screen_x tens
    lda #36
    sta f:$7E0000 + HUD_OAM + 75*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 75*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 75*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 75*4 + OAM_ATTR

    ; Entry 76: screen_x ones
    lda #44
    sta f:$7E0000 + HUD_OAM + 76*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 76*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 76*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 76*4 + OAM_ATTR

    ; Entry 77: screen_y hundreds
    lda #56
    sta f:$7E0000 + HUD_OAM + 77*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 77*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 77*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 77*4 + OAM_ATTR

    ; Entry 78: screen_y tens
    lda #64
    sta f:$7E0000 + HUD_OAM + 78*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 78*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 78*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 78*4 + OAM_ATTR

    ; Entry 79: screen_y ones
    lda #72
    sta f:$7E0000 + HUD_OAM + 79*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 79*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 79*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 79*4 + OAM_ATTR

    ; Entry 80: cam_z tens
    lda #84
    sta f:$7E0000 + HUD_OAM + 80*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 80*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 80*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 80*4 + OAM_ATTR

    ; Entry 81: cam_z ones
    lda #92
    sta f:$7E0000 + HUD_OAM + 81*4 + OAM_X
    lda #18
    sta f:$7E0000 + HUD_OAM + 81*4 + OAM_Y
    lda #0
    sta f:$7E0000 + HUD_OAM + 81*4 + OAM_TILE
    lda #HUD_ATTR
    sta f:$7E0000 + HUD_OAM + 81*4 + OAM_ATTR

    rts

; =============================================================================
; update_speed_display — Write tens/ones/fraction tile indices for speed
; =============================================================================
; Reads velocity ($57-$58, 8.8).  speed_integer = velocity >> 8 (0-48).
; Tens = speed_integer / 10  (RDDIVL)
; Ones = speed_integer mod 10 (RDMPYL)
; Frac = (velocity_lo * 10) >> 8  (RDMPYH)
; Uses HW divider (16-cycle wait via 8 NOPs) + HW multiplier (8-cycle wait).
; Mode: A8/I16 on entry and exit
; =============================================================================
update_speed_display:
    sep #$20
    .a8

    ; Fraction digit — start multiply first (8-cycle wait is shorter)
    lda z:velocity          ; velocity low byte (fractional)
    sta $4202               ; WRMPYA = fraction
    lda #10
    sta $4203               ; WRMPYB = 10 (triggers multiply)

    ; Integer divide — start immediately after (16-cycle wait)
    stz $4205               ; WRDIVH = 0
    lda z:velocity+1        ; speed integer (0-48)
    sta $4204               ; WRDIVL = integer
    lda #10
    sta $4206               ; WRDIVB = 10 (triggers divide; 16-cycle wait)
    ; 8 NOPs × 2 cycles each = 16 cycles
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    ; Multiply result is also ready (8 cycles elapsed after WRMPYB write)
    lda $4217               ; RDMPYH = tenths digit (0-9)
    sta f:$7E0000 + HUD_OAM + 3*4 + OAM_TILE  ; entry 3 = fraction

    lda $4214               ; RDDIVL = tens digit (0-4)
    sta f:$7E0000 + HUD_OAM + 0*4 + OAM_TILE  ; entry 0 = tens

    lda $4216               ; RDMPYL = ones digit (0-9)
    sta f:$7E0000 + HUD_OAM + 1*4 + OAM_TILE  ; entry 1 = ones

    rts

; =============================================================================
; update_lap_display — Write current lap digit to OAM entry 7
; =============================================================================
; Mode: A8/I16 on entry and exit
; =============================================================================
update_lap_display:
    sep #$20
    .a8
    lda z:current_lap       ; 1-3
    sta f:$7E0000 + HUD_OAM + 7*4 + OAM_TILE
    rts

; =============================================================================
; update_position_display — Write position digit + ordinal suffix to entries 10-12
; =============================================================================
; Mode: A8/I16 on entry and exit
; position_suffix_table: 5 entries × 2 bytes = { suffix_char1, suffix_char2 }
;   1 → S, T  (1ST)
;   2 → N, D  (2ND)
;   3 → R, D  (3RD)
;   4 → T, H  (4TH)
;   5 → T, H  (5TH)
; =============================================================================
update_position_display:
    sep #$20
    .a8
    rep #$10
    .i16
    lda z:race_position     ; 1-5
    sta f:$7E0000 + HUD_OAM + 10*4 + OAM_TILE  ; entry 10 = digit

    ; Index into suffix table: (position - 1) * 2
    dec a                   ; 0-4
    asl a                   ; × 2
    ; Zero-extend A_lo to full 16-bit X: A_hi may contain garbage from
    ; previous A16 operations (e.g. frame_count high byte after sep #$20).
    ; Without this, tax in A8/I16 mode produces X = (A_hi<<8)|A_lo, wrong
    ; when A_hi != 0 (frame_count >= 256).
    xba                     ; A_lo ← old A_hi, A_hi ← computed index
    lda #0                  ; A_lo = 0 (clears the hidden high byte)
    xba                     ; A_lo ← computed index, A_hi ← 0
    tax                     ; X = computed index (clean 16-bit)
    lda f:position_suffix_table, x
    sta f:$7E0000 + HUD_OAM + 11*4 + OAM_TILE  ; entry 11 = suffix char 1
    inx
    lda f:position_suffix_table, x
    sta f:$7E0000 + HUD_OAM + 12*4 + OAM_TILE  ; entry 12 = suffix char 2
    rts

; =============================================================================
; update_debug_display — Show nearest visible car's info on HUD line 2
; =============================================================================
; Layout: [car#][grade] [sx_h][sx_t][sx_o] [sy_h][sy_t][sy_o] [cz_h][cz_t]
; Scans cars 0-3 for first visible, shows that car's values
; Mode: A8/I16 on entry and exit
; =============================================================================
update_debug_display:
    sep #$20
    .a8
    rep #$10
    .i16

    ; --- Find nearest visible car (first with vis=1) ---
    ldx #0                      ; car 0 offset
    lda f:$7E0000 + AI_VISIBLE, x
    bne @dbg_found
    ldx #16                     ; car 1 offset
    lda f:$7E0000 + AI_VISIBLE, x
    bne @dbg_found
    ldx #32                     ; car 2 offset
    lda f:$7E0000 + AI_VISIBLE, x
    bne @dbg_found
    ldx #48                     ; car 3 offset
    lda f:$7E0000 + AI_VISIBLE, x
    bne @dbg_found
    ; No visible car — show dashes and return
    lda #TILE_DASH
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_TILE
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_TILE
    rts

@dbg_found:
    .a8
    ; X = WRAM offset of visible car (0/16/32/48)
    ; Save X in temp for later reads
    stx z:temp+0

    ; --- Entry 72: car index (X/16) ---
    txa
    lsr a
    lsr a
    lsr a
    lsr a                       ; A = car index 0-3
    sta f:$7E0000 + HUD_OAM + 72*4 + OAM_TILE

    ; --- Entry 73: size grade ---
    ldx z:temp+0
    lda f:$7E0000 + AI_SIZE_GRADE, x
    sta f:$7E0000 + HUD_OAM + 73*4 + OAM_TILE

    ; --- screen_x: 3-digit decimal (entries 74-76) ---
    ldx z:temp+0
    lda f:$7E0000 + AI_SCREEN_X, x
    sta f:$004204
    lda #0
    sta f:$004205
    lda #100
    sta f:$004206
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda f:$004214             ; hundreds
    sta f:$7E0000 + HUD_OAM + 74*4 + OAM_TILE
    lda f:$004216             ; remainder
    sta f:$004204
    lda #0
    sta f:$004205
    lda #10
    sta f:$004206
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda f:$004214             ; tens
    sta f:$7E0000 + HUD_OAM + 75*4 + OAM_TILE
    lda f:$004216             ; ones
    sta f:$7E0000 + HUD_OAM + 76*4 + OAM_TILE

    ; --- screen_y: 3-digit decimal (entries 77-79) ---
    ldx z:temp+0
    lda f:$7E0000 + AI_SCREEN_Y, x
    sta f:$004204
    lda #0
    sta f:$004205
    lda #100
    sta f:$004206
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda f:$004214             ; hundreds
    sta f:$7E0000 + HUD_OAM + 77*4 + OAM_TILE
    lda f:$004216             ; remainder
    sta f:$004204
    lda #0
    sta f:$004205
    lda #10
    sta f:$004206
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda f:$004214             ; tens
    sta f:$7E0000 + HUD_OAM + 78*4 + OAM_TILE
    lda f:$004216             ; ones
    sta f:$7E0000 + HUD_OAM + 79*4 + OAM_TILE

    ; --- cam_z: 2-digit decimal (entries 80-81) ---
    ldx z:temp+0
    lda f:$7E0000 + AI_CAM_Z, x
    sta f:$004204
    lda #0
    sta f:$004205
    lda #10
    sta f:$004206
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    lda f:$004214             ; tens
    sta f:$7E0000 + HUD_OAM + 80*4 + OAM_TILE
    lda f:$004216             ; ones
    sta f:$7E0000 + HUD_OAM + 81*4 + OAM_TILE

    rts

; =============================================================================
; compute_perspective_from_height — Derive pv_l0, pv_s0, pv_s1 from height
; =============================================================================
; Formulas (matching Dizworld mode_y):
;   pv_l0 = 32 + (height / 2)    — horizon scanline
;   pv_s0 = 384 + (height * 2)   — far scale
;   pv_s1 = 64 + (height / 2)    — near scale
; Mode: .a8 on entry and exit
; =============================================================================
compute_perspective_from_height:
    .a8
    lda z:height
    lsr                     ; height / 2
    clc
    adc #32
    sta z:pv_l0             ; pv_l0 = 32 + (height / 2)
    lda z:height
    lsr
    clc
    adc #64
    sta z:pv_s1             ; pv_s1 low byte = 64 + (height / 2)
    stz z:pv_s1+1           ; pv_s1 < 256 always (max = 64 + 60 = 124)
    ; pv_s0 = 384 + (height * 2): result can be > 255
    rep #$20
    .a16
    lda z:height
    and #$00FF
    asl                     ; height * 2
    clc
    adc #384
    sta z:pv_s0             ; pv_s0 = 384 + (height * 2)
    sep #$20
    .a8
    rts


; =============================================================================
; Include math routines (umul16, smul16, smul16_u8, udiv32, sincos)
; =============================================================================
.include "mode7_diz_math.asm"

; =============================================================================
; Include sine LUT
; =============================================================================
mode7_sin_lut:
.include "mode7_sin_lut.inc"

; =============================================================================
; pv_buffer_x - returns buffer offset in X
; =============================================================================
; Input: pv_buffer (ZP)
; Output: X = 0 or PV_HDMA_STRIDE
; Mode: .a8 .i16
; =============================================================================
pv_buffer_x:
    .a8
    .i16
    lda z:pv_buffer
    beq @buf0
        ldx #PV_HDMA_STRIDE
        rts
@buf0:
        ldx #0
        rts

; =============================================================================
; pv_rebuild - Build perspective HDMA tables
; =============================================================================
; Ported from dizworld.s pv_rebuild
; Inputs: pv_l0, pv_l1, pv_s0, pv_s1, pv_sh, pv_interp, pv_wrap, angle
; Outputs: HDMA tables in WRAM, new_hdma settings
; =============================================================================
pv_rebuild:
    php
    phb
    sep #$20
    rep #$10
    .a8
    .i16
    lda #$7E
    pha
    plb                     ; DB = $7E for WRAM buffer access
    ; 1. Flip double buffer
    lda z:pv_buffer
    eor #1
    sta z:pv_buffer
    ; 2. Build BGMODE + TM HDMA tables
    jsr pv_buffer_x
    stx z:temp
    ldy z:temp              ; X = Y = pv_buffer_x
    lda z:pv_l0
    beq @bgm_end
    dec                     ; set on scanline before L0
    beq @bgm_end
    sta z:temp
@bgm_mode:
    cmp #128
    bcc :+
        lda #128
    :
    sta a:pv_hdma_bgm0+0, x
    sta a:pv_hdma_tm0+0, y
    eor #$FF
    sec
    adc z:temp
    sta z:temp
    lda z:nmi_bgmode
    sta a:pv_hdma_bgm0+1, x
    lda #<pv_tm2
    sta a:pv_hdma_tm0+1, y
    lda #>pv_tm2
    sta a:pv_hdma_tm0+2, y
    inx
    inx
    iny
    iny
    iny
    lda z:temp
    bne @bgm_mode
@bgm_end:
    ; Set mode 7 at L0
    lda #1
    sta a:pv_hdma_bgm0+0, x
    lda #7
    sta a:pv_hdma_bgm0+1, x
    stz a:pv_hdma_bgm0+2, x ; end of table
    ; Set TM at L0
    lda #1
    sta a:pv_hdma_tm0+0, y
    lda #<pv_tm1
    sta a:pv_hdma_tm0+1, y
    lda #>pv_tm1
    sta a:pv_hdma_tm0+2, y
    lda #0
    sta a:pv_hdma_tm0+3, y  ; end of table
    ; 3. Build RGB COLDATA indirect tables (CH0=R, CH1=G, CH2=B)
    ; a later stage-5: HDMA always points to fixed WRAM active gradient ($3700+).
    ; No per-snapshot ROM lookup needed — lerp updates WRAM in place.
    ; HDMA indirect format: [count | $80, addr_lo, addr_hi] then $00 terminator.
    jsr pv_buffer_x
    ; --- CH0: Red → active_grad_r ($3700) ---
    lda #($80 | 224)
    sta a:pv_hdma_col_r0+0, x
    lda #<active_grad_r
    sta a:pv_hdma_col_r0+1, x
    lda #>active_grad_r
    sta a:pv_hdma_col_r0+2, x
    stz a:pv_hdma_col_r0+3, x  ; end of table
    ; --- CH1: Green → active_grad_g ($37E0) ---
    lda #($80 | 224)
    sta a:pv_hdma_col_g0+0, x
    lda #<active_grad_g
    sta a:pv_hdma_col_g0+1, x
    lda #>active_grad_g
    sta a:pv_hdma_col_g0+2, x
    stz a:pv_hdma_col_g0+3, x  ; end of table
    ; --- CH2: Blue → active_grad_b ($38C0) ---
    lda #($80 | 224)
    sta a:pv_hdma_col_b0+0, x
    lda #<active_grad_b
    sta a:pv_hdma_col_b0+1, x
    lda #>active_grad_b
    sta a:pv_hdma_col_b0+2, x
    stz a:pv_hdma_col_b0+3, x  ; end of table

    ; 4. Calculate ABCD coefficients
    ; ==============================
    ; Setup: compute ZR0, ZR1, interpolation increment, SA, rotation scale
    rep #$20
    sep #$10
    .a16
    .i8
    phb
    ldy #0
    phy
    plb                     ; DB = 0 for hardware multiply/divide

    ; ZR0 = (1<<21) / S0
    lda #(1 << 5)           ; (1<<21) >> 16 = 32
    stz z:math_a+0
    sta a:math_a+2
    lda z:pv_s0
    sta a:math_b+0
    stz a:math_b+2
    jsr udiv32
    lda a:math_p+2
    beq :+
        lda #$FFFF
        sta a:math_p+0
    :
    lda a:math_p+0
    bne :+
        inc
    :
    sta z:pv_zr

    ; ZR1 = (1<<21) / S1
    lda z:pv_s1
    sta a:math_b+0
    jsr udiv32
    lda a:math_p+2
    beq :+
        lda #$FFFF
        sta a:math_p+0
    :
    lda a:math_p+0
    bne :+
        inc
    :
    ; ZR_INC = (ZR1 - ZR0) / (L1 - L0) * interp
    ldy #0
    sec
    sbc z:pv_zr
    bcs :+
        eor #$FFFF
        inc
        iny
    :                       ; Y = negate flag
    sta f:$004204           ; WRDIVL/H = abs(ZR1 - ZR0)
    sep #$20
    .a8
    ; Set up interpolation stride
    lda z:pv_interp
    cmp #2
    beq :+
    cmp #4
    beq :+
        lda #1
    :
    asl
    asl
    sta z:pv_interps+0
    stz z:pv_interps+1
    ; Divide
    lda z:pv_l1
    sec
    sbc z:pv_l0
    sta f:$004206           ; WRDIVB = (L1-L0)
    sta z:temp+0            ; temp+0 = L1-L0 = scanline count
    ldx z:pv_interp
    cpx #4
    bne :+
        lsr
        lsr
        bra :++
    :
    cpx #2
    bne :+
        lsr
    :
    inc
    sta z:temp+1            ; temp+1 = (L1-L0)/interp + 1 = un-interpolated count
    rep #$20
    .a16
    ; Read division result
    lda f:$004214           ; RDDIVL/H
    ldx z:pv_interp
    cpx #4
    bne :+
        asl
        asl
        bra :++
    :
    cpx #2
    bne :+
        asl
    :
    cpy #0
    beq :+
        eor #$FFFF
        inc
    :
    sta z:pv_zr_inc

    ; Calculate SA = (SH * 256) / (S0 * (L1-L0))
    lda z:pv_s0
    sta z:math_a
    lda #0
    ldx z:temp+0            ; L1-L0
    txa
    sta z:math_b
    jsr umul16
    lda z:math_p+0
    sta z:math_b+0
    lda z:math_p+2
    sta z:math_b+2          ; b = S0 * (L1-L0)
    stz z:math_a+0
    lda z:pv_sh
    beq @sh_zero
        sta z:pv_sh_
        sta z:math_a+2
        jsr udiv32
        lda z:math_p+0
        bra @sa_done
@sh_zero:
        lda #(1 << 8)       ; SA = 1.0 when SH=0
        lda z:math_b+1
        sta z:pv_sh_        ; computed SH
@sa_done:
    sta z:math_a            ; SA for later use

    ; Fetch sincos
    lda #0
    ldx z:angle
    txa
    ; sincos expects .a16 .i16
    rep #$10
    .i16
    jsr sincos
    sep #$10
    .i8

    ; Store rotation matrix in nmi_m7t
    lda z:cosa
    sta z:nmi_m7t+0         ; A = cos
    sta z:nmi_m7t+6         ; D = cos
    lda z:sina
    sta z:nmi_m7t+2         ; B = sin
    eor #$FFFF
    inc
    sta z:nmi_m7t+4         ; C = -sin

    ; Determine negation flags from cosa/sina signs
    ldx #0
    lda z:cosa
    bpl :+
        eor #$FFFF
        inc
        sta z:cosa
        ldx #%1001
    :
    stx z:pv_negate
    lda z:sina
    bmi :+
        lda #%0100
        bra :++
    :
        eor #$FFFF
        inc
        sta z:sina
        lda #%0010
    :
    eor z:pv_negate
    tax
    stx z:pv_negate

    ; Generate scale values (convert 8.8 cos/sin to 1.7, prescale vertical by SA)
    lda z:cosa
    sta z:math_b
    lsr
    tax
    stx z:pv_scale+0        ; scale A = cos / 2
    lda z:pv_sh
    beq :++
        jsr umul16
        lda z:math_p+1
        lsr
        cmp #$0100
        bcc :+
            lda #$00FF
        :
        tax
    :
    stx z:pv_scale+3        ; scale D = SA * cos / 2

    lda z:sina
    sta z:math_b
    lsr
    tax
    stx z:pv_scale+2        ; scale C = sin / 2
    lda z:pv_sh
    beq :++
        jsr umul16
        lda z:math_p+1
        lsr
        cmp #$0100
        bcc :+
            lda #$00FF
        :
        tax
    :
    stx z:pv_scale+1        ; scale B = SA * sin / 2

    plb                     ; restore DB to $7E

    ; Generate HDMA indirection buffers
    sep #$20
    rep #$10
    .a8
    .i16
    jsr pv_buffer_x
    stx z:temp+4
    stx z:temp+6
    rep #$20
    .a16

    ; Head: before horizon (scanlines 0 to L0-2)
    lda z:pv_l0
    and #$00FF
    beq @abcdi_head_end
    dec
    beq @abcdi_head_end
    sta z:temp+2
@abcdi_head:
    cmp #128
    bcc :+
        lda #128
    :
    sta a:pv_hdma_abi0+0, x
    sta a:pv_hdma_cdi0+0, x
    eor #$FF
    sec
    adc z:temp+2
    and #$00FF
    sta z:temp+2
    lda #.loword(pv_hdma_ab0)
    clc
    adc z:temp+4
    sta a:pv_hdma_abi0+1, x
    lda #.loword(pv_hdma_cd0)
    clc
    adc z:temp+4
    sta a:pv_hdma_cdi0+1, x
    inx
    inx
    inx
    lda z:temp+2
    bne @abcdi_head
@abcdi_head_end:
    ; Body: terrain scanlines (L0 to L1-1)
    lda z:temp+0
    and #$00FF
    sta z:temp+2
@abcdi_body:
    cmp #127
    bcc :+
        lda #127
    :
    eor #$80                ; repeat mode
    sta a:pv_hdma_abi0+0, x
    sta a:pv_hdma_cdi0+0, x
    eor #$7F
    sec
    adc z:temp+2
    and #$00FF
    sta z:temp+2
    lda #.loword(pv_hdma_ab0)
    clc
    adc z:temp+4
    sta a:pv_hdma_abi0+1, x
    lda #.loword(pv_hdma_cd0)
    clc
    adc z:temp+4
    sta a:pv_hdma_cdi0+1, x
    inx
    inx
    inx
    lda z:temp+2
    beq @abcdi_body_end
    lda z:temp+4
    clc
    adc #(127*4)
    sta z:temp+4
    lda z:temp+2
    bra @abcdi_body
@abcdi_body_end:
    stz a:pv_hdma_abi0+0, x ; end of table
    stz a:pv_hdma_cdi0+0, x

    ; Generate scanlines with perspective correction
    .a16
    .i16
    phb
    sep #$10
    .i8
    ldx #0
    phx
    plb                     ; DB = 0 for hardware multiply access

    ; Set up long pointers for indirect writes
    ldx #$7E
    stx z:math_a+2
    stx z:math_b+2
    stx z:math_p+2
    stx z:math_r+2
    lda #.loword(pv_hdma_ab0+0)
    sta z:math_a+0
    lda #.loword(pv_hdma_ab0+2)
    sta z:math_b+0
    lda #.loword(pv_hdma_cd0+0)
    sta z:math_p+0
    lda #.loword(pv_hdma_cd0+2)
    sta z:math_r+0
    rep #$10
    .i16

    ldy z:temp+6            ; Y = pv_buffer_x
    lda z:temp+1
    and #$00FF
    sta z:temp+2            ; countdown
    lda z:pv_negate
    and #$000F
    sta z:temp+4            ; negate bits

    ; Choose angle=0 fast path (since angle=0 and no negation)
    ldx z:pv_scale+1
    bne @use_sa1_or_full
    lda z:pv_negate
    and #%1001
    bne @use_sa1_or_full
    ; angle=0 path
    jsr pv_abcd_lines_angle0_
    bra @abcd_done
@use_sa1_or_full:
    sep #$20
    .a8
    txa
    cmp z:pv_scale+2
    bne @use_full
    lda z:pv_scale+0
    cmp z:pv_scale+3
    bne @use_full
    ; SA=1 path
    rep #$20
    .a16
    jsr pv_abcd_lines_sa1_
    bra @abcd_done
@use_full:
    rep #$20
    .a16
    jsr pv_abcd_lines_full_
@abcd_done:
    plb                     ; DB = $7E

    ; Interpolation pass
    .a16
    .i16
    lda z:pv_interps
    cmp #(2*4)
    bcc @interpolate_end
    ldx z:temp+6            ; pv_buffer_x
    lda z:temp+1
    and #$0FF
    beq @interpolate_end
    dec
    beq @interpolate_end
    sta z:temp+2
    lda z:pv_interps
    cmp #(4*4)
    beq :+
        jsr pv_interpolate_2x_
        bra :++
    :
        jsr pv_interpolate_4x_
    :
@interpolate_end:

    ; 5. Set up HDMA channel registers for next frame
    sep #$20
    rep #$10
    .a8
    .i16
    ; CH0: COLDATA-R ($2132) - indirect, 1 byte, data in WRAM bank $7E
    lda #$40
    sta a:new_hdma+(0*16)+0  ; DMAP: indirect
    lda #$32
    sta a:new_hdma+(0*16)+1  ; BBAD: $2132 (COLDATA)
    lda #$7E
    sta a:new_hdma+(0*16)+4  ; A1B: indirect table in WRAM
    sta a:new_hdma+(0*16)+7  ; DASB: data in WRAM bank $7E

    ; CH1: COLDATA-G ($2132) - indirect, 1 byte, data in WRAM bank $7E
    lda #$40
    sta a:new_hdma+(1*16)+0  ; DMAP: indirect
    lda #$32
    sta a:new_hdma+(1*16)+1  ; BBAD: $2132 (COLDATA)
    lda #$7E
    sta a:new_hdma+(1*16)+4  ; A1B: indirect table in WRAM
    sta a:new_hdma+(1*16)+7  ; DASB: data in WRAM bank $7E

    ; CH2: COLDATA-B ($2132) - indirect, 1 byte, data in WRAM bank $7E
    lda #$40
    sta a:new_hdma+(2*16)+0  ; DMAP: indirect
    lda #$32
    sta a:new_hdma+(2*16)+1  ; BBAD: $2132 (COLDATA)
    lda #$7E
    sta a:new_hdma+(2*16)+4  ; A1B: indirect table in WRAM
    sta a:new_hdma+(2*16)+7  ; DASB: data in WRAM bank $7E

    ; CH3: BGMODE ($2105) - direct, 1 byte
    stz a:new_hdma+(3*16)+0  ; DMAP: 1-byte direct
    lda #$05
    sta a:new_hdma+(3*16)+1  ; BBAD: $2105
    lda #$7E
    sta a:new_hdma+(3*16)+4  ; A1B bank

    ; CH4: TM ($212C) - indirect, 1 byte
    lda #$40
    sta a:new_hdma+(4*16)+0  ; DMAP: indirect
    lda #$2C
    sta a:new_hdma+(4*16)+1  ; BBAD: $212C
    lda #$7E
    sta a:new_hdma+(4*16)+4  ; A1B bank
    sta a:new_hdma+(4*16)+7  ; DASB indirect bank

    ; CH5: M7A+M7B ($211B) - indirect, 4-byte transfer
    lda #$43
    sta a:new_hdma+(5*16)+0  ; DMAP: indirect, 4-byte
    lda #$1B
    sta a:new_hdma+(5*16)+1  ; BBAD: $211B
    lda #$7E
    sta a:new_hdma+(5*16)+4
    sta a:new_hdma+(5*16)+7

    ; CH6: M7C+M7D ($211D) - indirect, 4-byte transfer
    lda #$43
    sta a:new_hdma+(6*16)+0
    lda #$1D
    sta a:new_hdma+(6*16)+1
    lda #$7E
    sta a:new_hdma+(6*16)+4
    sta a:new_hdma+(6*16)+7

    ; Set table addresses based on active buffer
    lda #%01111001          ; enable CH0+CH3-CH6 (CH1/CH2 dropped — no RGB gradient)
    sta z:new_hdma_en

    jsr pv_buffer_x
    stx z:temp
    rep #$20
    .a16
    ; CH0-CH2: RGB COLDATA indirect tables
    lda #.loword(pv_hdma_col_r0)
    clc
    adc z:temp
    sta a:new_hdma+(0*16)+2  ; CH0 table addr (R)
    lda #.loword(pv_hdma_col_g0)
    clc
    adc z:temp
    sta a:new_hdma+(1*16)+2  ; CH1 table addr (G)
    lda #.loword(pv_hdma_col_b0)
    clc
    adc z:temp
    sta a:new_hdma+(2*16)+2  ; CH2 table addr (B)
    ; CH3-CH6: same as before
    lda #.loword(pv_hdma_bgm0)
    clc
    adc z:temp
    sta a:new_hdma+(3*16)+2  ; CH3 table addr
    lda #.loword(pv_hdma_tm0)
    clc
    adc z:temp
    sta a:new_hdma+(4*16)+2  ; CH4 table addr
    lda #.loword(pv_hdma_abi0)
    clc
    adc z:temp
    sta a:new_hdma+(5*16)+2  ; CH5 table addr
    lda #.loword(pv_hdma_cdi0)
    clc
    adc z:temp
    sta a:new_hdma+(6*16)+2  ; CH6 table addr

    ; Copy new_hdma -> nmi_hdma
    phb
    ldx #new_hdma
    ldy #nmi_hdma
    lda #(16*8)-1
    .byte $54, $7E, $7E     ; MVN dst=$7E, src=$7E (raw bytes — ca65 breaks bank refs)
    plb
    sep #$20
    .a8
    lda z:new_hdma_en
    sta z:nmi_hdma_en

    plb
    plp
    rts

; =============================================================================
; pv_abcd_lines_angle0_ - Angle=0 optimized line generator
; =============================================================================
; At angle=0: A=D=scale, B=C=0
; temp+2/3 = un-interpolated scanline count
; Y = pv_buffer_x
; Mode: .a16 .i16
; =============================================================================
pv_abcd_lines_angle0_:
    .a16
    .i16
    lda z:pv_zr
    lsr
    lsr
    lsr
    lsr
    tax
    lda f:pv_ztable, x
    sta a:$4202             ; WRMPYA = z
    nop                     ; delay
    ; scale a
    ldx z:pv_scale+0
    stx a:$4203
        lda z:pv_zr
        clc
        adc z:pv_zr_inc
        sta z:pv_zr
    lda a:$4216
    ; scale d
    ldx z:pv_scale+3
    stx a:$4203
        ; scale and store a while waiting
        lsr
        lsr
        lsr
        lsr
        lsr
        sta [math_a], y     ; pv_hdma_ab0+0 (A coefficient)
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    sta [math_r], y         ; pv_hdma_cd0+2 (D coefficient)
    ; b/c = 0
    lda #0
    sta [math_b], y         ; pv_hdma_ab0+2 (B = 0)
    sta [math_p], y         ; pv_hdma_cd0+0 (C = 0)
    ; next line
    tya
    clc
    adc z:pv_interps
    tay
    dec z:temp+2
    bne pv_abcd_lines_angle0_
    rts

; =============================================================================
; pv_abcd_lines_sa1_ - SA=1 path (d=a, c=-b)
; =============================================================================
pv_abcd_lines_sa1_:
    .a16
    .i16
    lda z:pv_zr
    lsr
    lsr
    lsr
    lsr
    tax
    lda f:pv_ztable, x
    sta a:$4202
    nop
    ; scale a/d
    ldx z:pv_scale+0
    stx a:$4203
        lda z:pv_zr
        clc
        adc z:pv_zr_inc
        sta z:pv_zr
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    ; scale b/c
    ldx z:pv_scale+1
    stx a:$4203
        ; negate and store a
        lsr z:temp+4
        bcc :+
            eor #$FFFF
            inc
        :
        sta [math_a], y     ; a
        sta [math_r], y     ; d = a
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr z:temp+4
    bcc :+
        sta [math_p], y     ; c
        eor #$FFFF
        inc
        sta [math_b], y     ; b = -c
        bra :++
    :
        sta [math_b], y     ; b
        eor #$FFFF
        inc
        sta [math_p], y     ; c = -b
    :
    ; next
    lda z:pv_negate
    and #$000F
    sta z:temp+4
    tya
    clc
    adc z:pv_interps
    tay
    dec z:temp+2
    bne pv_abcd_lines_sa1_
    rts

; =============================================================================
; pv_abcd_lines_full_ - Full perspective with independent scale
; =============================================================================
pv_abcd_lines_full_:
    .a16
    .i16
    lda z:pv_zr
    lsr
    lsr
    lsr
    lsr
    tax
    lda f:pv_ztable, x
    sta a:$4202
    nop
    ; scale a
    ldx z:pv_scale+0
    stx a:$4203
        lda z:pv_zr
        clc
        adc z:pv_zr_inc
        sta z:pv_zr
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    ; scale b
    ldx z:pv_scale+1
    stx a:$4203
        lsr z:temp+4
        bcc :+
            eor #$FFFF
            inc
        :
        sta [math_a], y     ; a
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    ; scale c
    ldx z:pv_scale+2
    stx a:$4203
        lsr z:temp+4
        bcc :+
            eor #$FFFF
            inc
        :
        sta [math_b], y     ; b
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    ; scale d
    ldx z:pv_scale+3
    stx a:$4203
        lsr z:temp+4
        bcc :+
            eor #$FFFF
            inc
        :
        sta [math_p], y     ; c
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr z:temp+4
    bcc :+
        eor #$FFFF
        inc
    :
    sta [math_r], y         ; d
    ; reload negate
    lda z:pv_negate
    and #$000F
    sta z:temp+4
    tya
    clc
    adc z:pv_interps
    tay
    dec z:temp+2
    beq :+
    jmp pv_abcd_lines_full_
:
    rts

; =============================================================================
; pv_interpolate_4x_ - Interpolate from every 4th line to every 2nd
; =============================================================================
pv_interpolate_4x_:
    .a16
    .i16
    lda z:temp+2
    pha
    phx
:
    lda a:pv_hdma_ab0+0,    x
    clc
    adc a:pv_hdma_ab0+0+16, x
    ror
    sta a:pv_hdma_ab0+0+ 8, x
    lda a:pv_hdma_ab0+2,    x
    clc
    adc a:pv_hdma_ab0+2+16, x
    ror
    sta a:pv_hdma_ab0+2+ 8, x
    lda a:pv_hdma_cd0+0,    x
    clc
    adc a:pv_hdma_cd0+0+16, x
    ror
    sta a:pv_hdma_cd0+0+ 8, x
    lda a:pv_hdma_cd0+2,    x
    clc
    adc a:pv_hdma_cd0+2+16, x
    ror
    sta a:pv_hdma_cd0+2+ 8, x
    txa
    clc
    adc #16
    tax
    dec z:temp+2
    bne :-
    plx
    pla
    asl
    sta z:temp+2
    ; fall through to 2x

; =============================================================================
; pv_interpolate_2x_ - Interpolate from every 2nd line to every line
; =============================================================================
pv_interpolate_2x_:
    .a16
    .i16
:
    lda a:pv_hdma_ab0+0,   x
    clc
    adc a:pv_hdma_ab0+0+8, x
    ror
    sta a:pv_hdma_ab0+0+4, x
    lda a:pv_hdma_ab0+2,   x
    clc
    adc a:pv_hdma_ab0+2+8, x
    ror
    sta a:pv_hdma_ab0+2+4, x
    lda a:pv_hdma_cd0+0,   x
    clc
    adc a:pv_hdma_cd0+0+8, x
    ror
    sta a:pv_hdma_cd0+0+4, x
    lda a:pv_hdma_cd0+2,   x
    clc
    adc a:pv_hdma_cd0+2+8, x
    ror
    sta a:pv_hdma_cd0+2+4, x
    txa
    clc
    adc #8
    tax
    dec z:temp+2
    bne :-
    rts

; =============================================================================
; pv_set_origin - Compute M7X/M7Y from camera position
; =============================================================================
; Input: Y = scanline to place posx/posy at center of
; Mode: .a16 .i8 on entry
; =============================================================================
pv_set_origin:
    .a16
    .i8
    sty z:temp+0            ; target scanline
    tya
    sec
    sbc z:pv_l0
    and #$00FF
    asl
    asl
    sta z:temp+2            ; index to line (scanline * 4)
    sep #$20
    rep #$10
    .a8
    .i16
    lda z:pv_l1
    sec
    sbc z:temp+0
    sta z:math_b            ; scanlines above bottom
    jsr pv_buffer_x         ; X = buffer index
    rep #$20
    .a16
    txa
    clc
    adc z:temp+2
    tax                     ; X = index of target scanline in buffers
    ; Read coefficient data from WRAM bank $7E (buffers at $2000+ are outside
    ; the $0000-$1FFF WRAM mirror — must set DB=$7E for absolute addressing).
    ; Original Dizworld had buffers at $0300 (within mirror), but SuperForge
    ; relocated them to $2000+ to avoid engine state conflicts.
    phb
    pea $7E7E               ; push two copies of $7E
    plb                     ; DB = $7E
    plb                     ; (discard second copy, leave stack clean)
    lda a:pv_hdma_ab0+2, x
    sta z:math_a            ; b coefficient
    lda a:pv_hdma_cd0+2, x
    plb                     ; restore original DB
    pha                     ; save d coefficient
    sep #$10
    .i8
    jsr smul16_u8
    clc
    adc z:posx+2
    sta z:nmi_m7x           ; ox = posx + (scanlines * b)
    sec
    sbc #128
    sta z:nmi_hofs          ; hofs = ox - 128
    pla
    sta z:math_a            ; d coefficient
    jsr smul16_u8
    clc
    adc z:posy+2
    sta z:nmi_m7y           ; oy = posy + (scanlines * d)
    lda z:pv_l1
    and #$00FF
    eor #$FFFF
    sec
    adc z:nmi_m7y
    sta z:nmi_vofs          ; vofs = oy - L1
    rts

; =============================================================================
; init_player_car — One-time setup: OAM positions, Y values, hi-table size bits
; =============================================================================
; Entries 16-21: 2 large (16×16) + 4 small (8×8) = 32×24 pixels at X=112, Y=176
; Hi-table byte $3504 = $0A: entries 16,17 = large (16×16), 18,19 = small (8×8)
; Must be in forced-blank (called from RESET init before display enable).
; Clobbers: A, X (A8, I8 on entry/exit)
; =============================================================================
CAR_X_LEFT  = 112       ; left  16×16 block X
CAR_X_RIGHT = 128       ; right 16×16 block X
CAR_Y_TOP   = 176       ; 16×16 rows Y
CAR_Y_BOT   = 192       ; 8×8 bottom row Y
CAR_ATTR    = $30       ; priority 3, palette 0, no flip
CAR_ATTR_H  = $70       ; priority 3, palette 0, H-flip
CAR_OAM     = oam + 64  ; = $3340 (entry 16 base)

init_player_car:
    rep #$10
    .i16
    sep #$20
    .a8
    ; --- Set hi-table byte to mark entries 16,17 as large (16×16) ---
    ; Byte index = 16/4 = 4, offset from oam = 512+4 = 516 → WRAM $3504
    ; Bits: entry16=bit1, entry17=bit3 → $0A (entries 18,19 at bits 5,7 = 0 = small)
    ; Use ldx#0 + long,X form — plain 'sta f:addr' emits STA abs (DB-relative) on ca65
    ldx #0
    lda #$0A
    sta f:$7E0000 + oam + 512 + 4, x  ; hi-table byte 4 ($3504)

    ; --- Set Y positions (never change) ---
    lda #CAR_Y_TOP
    sta f:$7E0000 + CAR_OAM + 1, x  ; entry 16 Y
    sta f:$7E0000 + CAR_OAM + 5, x  ; entry 17 Y
    lda #CAR_Y_BOT
    sta f:$7E0000 + CAR_OAM + 9, x  ; entry 18 Y
    sta f:$7E0000 + CAR_OAM + 13, x ; entry 19 Y
    sta f:$7E0000 + CAR_OAM + 17, x ; entry 20 Y
    sta f:$7E0000 + CAR_OAM + 21, x ; entry 21 Y

    ; --- Set initial state: straight (frame 0) ---
    jsr update_player_car
    rts

; =============================================================================
; update_player_car — Per-frame: set X, tile, attr for OAM entries 16-21
; =============================================================================
; Dispatches to car_set_straight / car_set_lean_left / car_set_lean_right.
; Clobbers: A (A8 assumed)
; =============================================================================
update_player_car:
    sep #$20
    .a8
    lda z:drift_state
    bne @not_straight
    jsr car_set_straight
    rts
@not_straight:
    cmp #2
    beq @lean_right
    jsr car_set_lean_left
    rts
@lean_right:
    jsr car_set_lean_right
    rts

; =============================================================================
; car_set_straight — Frame 0 tiles, no flip, standard X positions
; =============================================================================
; OAM entry layout: [X, Y, tile, attr] per 4-byte slot. STA long,X (absolute long
; indexed) is used with X=0 to avoid illegal addressing modes.
; Clobbers: A, X
; =============================================================================
car_set_straight:
    rep #$10
    .i16
    sep #$20
    .a8
    ldx #0
    lda #112
    sta f:$7E0000 + CAR_OAM +  0, x  ; entry 16 X
    lda #32
    sta f:$7E0000 + CAR_OAM +  2, x  ; entry 16 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM +  3, x  ; entry 16 attr
    lda #128
    sta f:$7E0000 + CAR_OAM +  4, x  ; entry 17 X
    lda #34
    sta f:$7E0000 + CAR_OAM +  6, x  ; entry 17 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM +  7, x  ; entry 17 attr
    lda #112
    sta f:$7E0000 + CAR_OAM +  8, x  ; entry 18 X
    lda #36
    sta f:$7E0000 + CAR_OAM + 10, x  ; entry 18 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 11, x  ; entry 18 attr
    lda #120
    sta f:$7E0000 + CAR_OAM + 12, x  ; entry 19 X
    lda #37
    sta f:$7E0000 + CAR_OAM + 14, x  ; entry 19 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 15, x  ; entry 19 attr
    lda #128
    sta f:$7E0000 + CAR_OAM + 16, x  ; entry 20 X
    lda #38
    sta f:$7E0000 + CAR_OAM + 18, x  ; entry 20 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 19, x  ; entry 20 attr
    lda #136
    sta f:$7E0000 + CAR_OAM + 20, x  ; entry 21 X
    lda #39
    sta f:$7E0000 + CAR_OAM + 22, x  ; entry 21 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 23, x  ; entry 21 attr
    rts

; =============================================================================
; car_set_lean_left — Frame 1 tiles, no flip, standard X positions
; =============================================================================
car_set_lean_left:
    rep #$10
    .i16
    sep #$20
    .a8
    ldx #0
    lda #112
    sta f:$7E0000 + CAR_OAM +  0, x  ; entry 16 X
    lda #40
    sta f:$7E0000 + CAR_OAM +  2, x  ; entry 16 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM +  3, x  ; entry 16 attr
    lda #128
    sta f:$7E0000 + CAR_OAM +  4, x  ; entry 17 X
    lda #42
    sta f:$7E0000 + CAR_OAM +  6, x  ; entry 17 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM +  7, x  ; entry 17 attr
    lda #112
    sta f:$7E0000 + CAR_OAM +  8, x  ; entry 18 X
    lda #44
    sta f:$7E0000 + CAR_OAM + 10, x  ; entry 18 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 11, x  ; entry 18 attr
    lda #120
    sta f:$7E0000 + CAR_OAM + 12, x  ; entry 19 X
    lda #45
    sta f:$7E0000 + CAR_OAM + 14, x  ; entry 19 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 15, x  ; entry 19 attr
    lda #128
    sta f:$7E0000 + CAR_OAM + 16, x  ; entry 20 X
    lda #46
    sta f:$7E0000 + CAR_OAM + 18, x  ; entry 20 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 19, x  ; entry 20 attr
    lda #136
    sta f:$7E0000 + CAR_OAM + 20, x  ; entry 21 X
    lda #47
    sta f:$7E0000 + CAR_OAM + 22, x  ; entry 21 tile
    lda #CAR_ATTR
    sta f:$7E0000 + CAR_OAM + 23, x  ; entry 21 attr
    rts

; =============================================================================
; car_set_lean_right — Frame 1 tiles, H-flip, mirrored X (256-X-W)
; =============================================================================
car_set_lean_right:
    rep #$10
    .i16
    sep #$20
    .a8
    ldx #0
    lda #128
    sta f:$7E0000 + CAR_OAM +  0, x  ; entry 16 X (256-112-16)
    lda #40
    sta f:$7E0000 + CAR_OAM +  2, x  ; entry 16 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM +  3, x  ; entry 16 attr
    lda #112
    sta f:$7E0000 + CAR_OAM +  4, x  ; entry 17 X (256-128-16)
    lda #42
    sta f:$7E0000 + CAR_OAM +  6, x  ; entry 17 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM +  7, x  ; entry 17 attr
    lda #136
    sta f:$7E0000 + CAR_OAM +  8, x  ; entry 18 X (256-112-8)
    lda #44
    sta f:$7E0000 + CAR_OAM + 10, x  ; entry 18 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM + 11, x  ; entry 18 attr
    lda #128
    sta f:$7E0000 + CAR_OAM + 12, x  ; entry 19 X (256-120-8)
    lda #45
    sta f:$7E0000 + CAR_OAM + 14, x  ; entry 19 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM + 15, x  ; entry 19 attr
    lda #120
    sta f:$7E0000 + CAR_OAM + 16, x  ; entry 20 X (256-128-8)
    lda #46
    sta f:$7E0000 + CAR_OAM + 18, x  ; entry 20 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM + 19, x  ; entry 20 attr
    lda #112
    sta f:$7E0000 + CAR_OAM + 20, x  ; entry 21 X (256-136-8)
    lda #47
    sta f:$7E0000 + CAR_OAM + 22, x  ; entry 21 tile
    lda #CAR_ATTR_H
    sta f:$7E0000 + CAR_OAM + 23, x  ; entry 21 attr
    rts

; =============================================================================
; Sky gradient tile + tilemap + palette data (the reference scene-1)
; =============================================================================
; Generated by: PYTHONPATH=. python toolchain/sky_tiles_v2.py
; 6 dithered 4bpp tiles (192 bytes), 32x32 tilemap (2048 bytes), 4-color palette (8 bytes)

.include "sky_tiles_v2.inc"
.include "sky_tilemap_v2.inc"
.include "sky_palette_v2.inc"

; Acceleration LUT (the reference scene-2): 256 entries, index=velocity_hi, value=accel (0.8)
; Generated by: python toolchain/accel_lut.py
.include "accel_lut.inc"

; Player car tiles + palette (the reference scene-4)
; Generated by: PYTHONPATH=. python toolchain/player_car.py
.include "player_car.inc"
.include "player_car_palette.inc"

; =============================================================================
; HUD font 1bpp bitmaps — 28 glyphs × 8 bytes = 224 bytes
; 4-wide × 6-tall patterns centered in 8×8 tile, MSB = left
; Tiles 0-15: hex digits 0-9, A-F (restored from an earlier stage)
; Tiles 16-27: L, A, P, S, T, N, D, R, H, /, ., space
; =============================================================================
hud_font_1bpp:
    ; Tile 0 — digit "0": .##. / #..# / #..# / #..# / #..# / .##.
    .byte $00,$60,$90,$90,$90,$90,$60,$00
    ; Tile 1 — digit "1": ..#. / .##. / ..#. / ..#. / ..#. / .###
    .byte $00,$20,$60,$20,$20,$20,$70,$00
    ; Tile 2 — digit "2": .##. / #..# / ...# / ..#. / .#.. / ####
    .byte $00,$60,$90,$10,$20,$40,$F0,$00
    ; Tile 3 — digit "3": .##. / #..# / ..#. / ...# / #..# / .##.  (wait: ..## more accurate)
    .byte $00,$60,$90,$20,$10,$90,$60,$00
    ; Tile 4 — digit "4": #..# / #..# / #### / ...# / ...# / ...#
    .byte $00,$90,$90,$F0,$10,$10,$10,$00
    ; Tile 5 — digit "5": #### / #... / ###. / ...# / #..# / .##.
    .byte $00,$F0,$80,$E0,$10,$90,$60,$00
    ; Tile 6 — digit "6": .##. / #... / ###. / #..# / #..# / .##.
    .byte $00,$60,$80,$E0,$90,$90,$60,$00
    ; Tile 7 — digit "7": #### / ...# / ..#. / ..#. / ..#. / ..#.
    .byte $00,$F0,$10,$20,$20,$20,$20,$00
    ; Tile 8 — digit "8": .##. / #..# / .##. / #..# / #..# / .##.
    .byte $00,$60,$90,$60,$90,$90,$60,$00
    ; Tile 9 — digit "9": .##. / #..# / #..# / .### / ...# / .##.
    .byte $00,$60,$90,$90,$70,$10,$60,$00
    ; Tile 10 — hex A: .##. / #..# / #### / #..# / #..# / #..#
    .byte $00,$60,$90,$F0,$90,$90,$90,$00
    ; Tile 11 — hex B: ###. / #..# / ###. / #..# / #..# / ###.
    .byte $00,$E0,$90,$E0,$90,$90,$E0,$00
    ; Tile 12 — hex C: .##. / #..# / #... / #... / #..# / .##.
    .byte $00,$60,$90,$80,$80,$90,$60,$00
    ; Tile 13 — hex D: ###. / #..# / #..# / #..# / #..# / ###.
    .byte $00,$E0,$90,$90,$90,$90,$E0,$00
    ; Tile 14 — hex E: #### / #... / ###. / #... / #... / ####
    .byte $00,$F0,$80,$E0,$80,$80,$F0,$00
    ; Tile 15 — hex F: #### / #... / ###. / #... / #... / #...
    .byte $00,$F0,$80,$E0,$80,$80,$80,$00
    ; Tile 16 — letter L: #... / #... / #... / #... / #... / ####
    .byte $00,$80,$80,$80,$80,$80,$F0,$00
    ; Tile 17 — letter A: .##. / #..# / #### / #..# / #..# / #..#
    .byte $00,$60,$90,$F0,$90,$90,$90,$00
    ; Tile 18 — letter P: ###. / #..# / ###. / #... / #... / #...
    .byte $00,$E0,$90,$E0,$80,$80,$80,$00
    ; Tile 19 — letter S: .##. / #... / .##. / ...# / ...# / .##.  (actually: #..# bottom)
    .byte $00,$60,$80,$60,$10,$90,$60,$00
    ; Tile 20 — letter T: #### / ..#. / ..#. / ..#. / ..#. / ..#.
    .byte $00,$F0,$20,$20,$20,$20,$20,$00
    ; Tile 21 — letter N: #..# / ##.# / #.## / #..# / #..# / #..#
    .byte $00,$90,$D0,$B0,$90,$90,$90,$00
    ; Tile 22 — letter D: ###. / #..# / #..# / #..# / #..# / ###.
    .byte $00,$E0,$90,$90,$90,$90,$E0,$00
    ; Tile 23 — letter R: ###. / #..# / #..# / ###. / #.#. / #..#
    .byte $00,$E0,$90,$90,$E0,$A0,$90,$00
    ; Tile 24 — letter H: #..# / #..# / #### / #..# / #..# / #..#
    .byte $00,$90,$90,$F0,$90,$90,$90,$00
    ; Tile 25 — slash /: ...# / ..#. / ..#. / .#.. / .#.. / #...
    .byte $00,$10,$20,$20,$40,$40,$80,$00
    ; Tile 26 — period .: .... / .... / .... / .... / .##. / ....
    .byte $00,$00,$00,$00,$00,$60,$00,$00
    ; Tile 27 — space: (all blank)
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    ; Tile 28 — letter Z: #### / ...# / ..#. / .#.. / #... / ####
    .byte $00,$F0,$10,$20,$40,$80,$F0,$00
    ; Tile 29 — letter Y: #..# / #..# / .##. / ..#. / ..#. / ..#.
    .byte $00,$90,$90,$60,$20,$20,$20,$00
    ; Tile 30 — letter V: #..# / #..# / #..# / #..# / .##. / ..#.
    .byte $00,$90,$90,$90,$90,$60,$20,$00
    ; Tile 31 — dash/minus: .... / .... / .... / #### / .... / ....
    .byte $00,$00,$00,$00,$F0,$00,$00,$00

; =============================================================================
; Position ordinal suffix table — 5 entries × 2 bytes (suffix_char1, suffix_char2)
; =============================================================================
position_suffix_table:
    .byte TILE_S, TILE_T    ; position 1 → "ST"
    .byte TILE_N, TILE_D    ; position 2 → "ND"
    .byte TILE_R, TILE_D    ; position 3 → "RD"
    .byte TILE_T, TILE_H    ; position 4 → "TH"
    .byte TILE_T, TILE_H    ; position 5 → "TH"

; (Cloud tile bitplane data removed in the reference scene-1 — replaced by sky gradient tiles)

; (Cloud tilemap removed in the reference scene-1 — replaced by sky_tilemap_v2.inc)

; (Star tiles and star tilemap removed in the base scene — dissolve system stripped)

; =============================================================================
; AI car palette + tile data — generated by toolchain/player_car.py
; =============================================================================
.segment "RODATA"
.include "ai_palette.inc"
.include "ai_palette_green.inc"
.include "ai_palette_yellow.inc"
.include "ai_palette_purple.inc"
.include "ai_car_large.inc"
.include "ai_car_medium.inc"
.include "ai_car_small.inc"

; =============================================================================
; RODATA: pv_ztable (4096-byte reciprocal lookup)
; =============================================================================
; (segment already set to RODATA above)
.include "mode7_diz_ztable.inc"

; =============================================================================
; Streaming Engine — Camera Tile Tracking (the streaming workc)
; =============================================================================
; Called each frame after move_forward. Computes the camera's tile position
; and triggers decompression into staging buffers when a tile boundary is crossed.
; The NMI handler then DMA's the staging buffers to VRAM.
;
; Entry: A8/I16 (from game loop)
; Clobbers: A, X, Y, temp ($D0-$DF)
; =============================================================================
.segment "CODE"

stream_check_update:
    rep #$20
    .a16
    ; Compute camera tile X from pixel position
    lda z:posx+2                ; pixel X (16-bit)
    lsr
    lsr
    lsr                         ; /8 = tile X
    and #$01FF                  ; wrap to 0-511
    sta z:stream_cam_tx

    ; Compute camera tile Y
    lda z:posy+2
    lsr
    lsr
    lsr
    and #$01FF
    sta z:stream_cam_ty

    ; --- Column streaming (X axis) ---
    ; Stream up to 4 new view-edge columns per frame.
    ; Only stream columns that actually enter the current view — no
    ; intermediate positions that would alias VRAM slots.
    lda z:stream_cam_tx
    cmp z:stream_last_tx
    bne :+
    jmp @no_col_update
:

    ; Compute wrapped delta: (cam_tx - last_tx) & $01FF
    lda z:stream_cam_tx
    sec
    sbc z:stream_last_tx
    and #$01FF
    cmp #256
    bcs @col_west_setup

    ; --- Moving east ---
    ; Delta = (cam_tx - last_tx) & $01FF, already in A, < 256
    ; Clamp to 4
    cmp #(STREAM_MAX + 1)
    bcc :+
    lda #STREAM_MAX
:   ldx #0
    sta f:$7E0000 + STREAM_COL_COUNT, x
    sta z:stream_loop_count    ; loop count (survives decompress)
    lda #0
    sta z:stream_loop_idx      ; loop index (word offset: 0,2,4,6)
@col_east_loop:
    rep #$20
    .a16
    ; Step last_tx forward by 1
    lda z:stream_last_tx
    inc
    and #$01FF
    sta z:stream_last_tx
    ; Leading edge = new last_tx + 64 (east edge of view)
    clc
    adc #64
    and #$01FF
    sta z:temp+0                ; logical column X

    ; VRAM column = leading_edge % 128
    and #$007F
    ldx z:stream_loop_idx
    sta f:$7E0000 + STREAM_COL_VADDR, x

    ; Decompress into STREAM_COL_BUF + (index/2 * 128)
    ; STREAM_LOOP_IDX is index*2, so buffer offset = IDX * 64
    txa                         ; A = IDX (0, 2, 4, 6)
    .repeat 6
        asl
    .endrepeat                  ; A = IDX * 64 = index * 128
    clc
    adc #STREAM_COL_BUF
    tay                         ; Y = dest buffer address

    sep #$20
    .a8
    jsr stream_decompress_column

    rep #$20
    .a16
    lda z:stream_loop_idx
    clc
    adc #2
    sta z:stream_loop_idx
    lsr                         ; A = loop iteration (1-based)
    cmp z:stream_loop_count
    bcc @col_east_loop
    bra @no_col_update

@col_west_setup:
    ; --- Moving west ---
    ; west delta = (last_tx - cam_tx) & $01FF
    lda z:stream_last_tx
    sec
    sbc z:stream_cam_tx
    and #$01FF                  ; west delta (positive)
    ; Clamp to 4
    cmp #(STREAM_MAX + 1)
    bcc :+
    lda #STREAM_MAX
:   ldx #0
    sta f:$7E0000 + STREAM_COL_COUNT, x
    sta z:stream_loop_count
    lda #0
    sta z:stream_loop_idx
@col_west_loop:
    rep #$20
    .a16
    ; Step last_tx backward by 1
    lda z:stream_last_tx
    dec
    and #$01FF
    sta z:stream_last_tx
    ; Leading edge = new last_tx - 63 (west edge of view)
    sec
    sbc #63
    and #$01FF
    sta z:temp+0

    and #$007F
    ldx z:stream_loop_idx
    sta f:$7E0000 + STREAM_COL_VADDR, x

    txa
    .repeat 6
        asl
    .endrepeat
    clc
    adc #STREAM_COL_BUF
    tay

    sep #$20
    .a8
    jsr stream_decompress_column

    rep #$20
    .a16
    lda z:stream_loop_idx
    clc
    adc #2
    sta z:stream_loop_idx
    lsr
    cmp z:stream_loop_count
    bcc @col_west_loop

@no_col_update:
    rep #$20
    .a16
    ; --- Row streaming (Y axis) ---
    ; Same multi-row approach: up to 4 rows per frame
    lda z:stream_cam_ty
    cmp z:stream_last_ty
    bne :+
    jmp @no_row_update
:

    lda z:stream_cam_ty
    sec
    sbc z:stream_last_ty
    and #$01FF
    cmp #256
    bcs @row_north_setup

    ; --- Moving south ---
    cmp #(STREAM_MAX + 1)
    bcc :+
    lda #STREAM_MAX
:   ldx #0
    sta f:$7E0000 + STREAM_ROW_COUNT, x
    sta z:stream_loop_count
    lda #0
    sta z:stream_loop_idx
@row_south_loop:
    rep #$20
    .a16
    lda z:stream_last_ty
    inc
    and #$01FF
    sta z:stream_last_ty
    clc
    adc #64
    and #$01FF
    sta z:temp+0                ; logical row Y

    ; VRAM row address = (row % 128) * 128
    and #$007F
    .repeat 7
        asl
    .endrepeat
    ldx z:stream_loop_idx
    sta f:$7E0000 + STREAM_ROW_VADDR, x

    txa
    .repeat 6
        asl
    .endrepeat
    clc
    adc #STREAM_ROW_BUF
    tay

    sep #$20
    .a8
    jsr stream_decompress_row

    rep #$20
    .a16
    lda z:stream_loop_idx
    clc
    adc #2
    sta z:stream_loop_idx
    lsr
    cmp z:stream_loop_count
    bcc @row_south_loop
    bra @no_row_update

@row_north_setup:
    ; --- Moving north ---
    lda z:stream_last_ty
    sec
    sbc z:stream_cam_ty
    and #$01FF
    cmp #(STREAM_MAX + 1)
    bcc :+
    lda #STREAM_MAX
:   ldx #0
    sta f:$7E0000 + STREAM_ROW_COUNT, x
    sta z:stream_loop_count
    lda #0
    sta z:stream_loop_idx
@row_north_loop:
    rep #$20
    .a16
    lda z:stream_last_ty
    dec
    and #$01FF
    sta z:stream_last_ty
    sec
    sbc #63
    and #$01FF
    sta z:temp+0

    and #$007F
    .repeat 7
        asl
    .endrepeat
    ldx z:stream_loop_idx
    sta f:$7E0000 + STREAM_ROW_VADDR, x

    txa
    .repeat 6
        asl
    .endrepeat
    clc
    adc #STREAM_ROW_BUF
    tay

    sep #$20
    .a8
    jsr stream_decompress_row

    rep #$20
    .a16
    lda z:stream_loop_idx
    clc
    adc #2
    sta z:stream_loop_idx
    lsr
    cmp z:stream_loop_count
    bcc @row_north_loop

@no_row_update:
    sep #$20
    .a8
    rts


; =============================================================================
; Streaming Engine — Flat ROM Copy (the streaming workd)
; =============================================================================
; Reads tiles directly from the flat 512×512 tilemap stored across ROM banks 2-9.
; Each bank holds 64 rows × 512 cols = 32KB. ~5 cycles/tile instead of ~50.
;
; Flat tilemap layout:
;   Bank = (row >> 6) + 2         (banks $02-$09)
;   Offset = $8000 + (row & 63) * 512 + col
;
; temp+0: input parameter (row Y or col X)
; temp+2: output buffer base (WRAM address)
; temp+4: 24-bit ROM pointer (3 bytes: lo, hi, bank)
; =============================================================================
.segment "CODE"

; flat_row_addr: Compute 24-bit ROM address for row Y, column 0.
; Input:  A (16-bit) = logical row Y (0-511)
; Output: temp+4/+5/+6 = 24-bit pointer (lo16, bank)
; Clobbers: A
.macro FLAT_ROW_ADDR
    ; bank = (Y >> 6) + 2
    pha
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr                         ; A = Y >> 6 (0-7)
    clc
    adc #$02                    ; + 2 = bank number
    sep #$20
    .a8
    sta z:temp+6                ; bank byte
    rep #$20
    .a16
    pla
    ; offset = $8000 + (Y & 63) * 512
    and #$003F                  ; Y & 63
    xba                         ; * 256
    asl                         ; * 512
    clc
    adc #$8000                  ; + bank base
    sta z:temp+4                ; lo16
.endmacro

; Input:  temp+0 = logical row Y (16-bit, 0-511)
;         Y register (I16) = destination WRAM address
; Output: 128 bytes written to destination
; Clobbers: A, X, Y, temp+0..temp+6
; =============================================================================
; stream_decompress_row — copy 128 tiles from flat ROM for one row
;
; Input:  temp+0 = logical row Y (0-511)
;         Y (I16) = destination WRAM buffer address (e.g. $3A00)
; Entry:  A8/I16
; Output: 128 bytes written to dest buffer in VRAM-wrapped order
; Clobbers: A, X, Y, temp+0..temp+8
;
; CRITICAL: tiles must be placed at buffer[(world_col % 128)] so that
; the NMI DMA (which writes buffer[0]→VRAM col 0, buffer[1]→VRAM col 1)
; matches Mode 7's VRAM[(row%128)][(col%128)] tile lookup.
; =============================================================================
stream_decompress_row:
    sty z:temp+2                ; save output buffer base

    ; Compute 24-bit ROM pointer for this row
    rep #$20
    .a16
    lda z:temp+0                ; row Y
    FLAT_ROW_ADDR               ; -> temp+4/+5 = lo16, temp+6 = bank

    ; Starting source column = (stream_cam_tx - 63) & $01FF
    lda z:stream_cam_tx
    sec
    sbc #63
    and #$01FF
    sta z:temp+0                ; source_col (advances each iteration)

    ; temp+8 = iteration counter (counts down from 128)
    lda #128
    sta z:temp+8

    sep #$20
    .a8
@row_loop:
    ; Y = source column for ROM read
    rep #$20
    .a16
    lda z:temp+0
    tay                         ; Y = source column
    ; X = buffer_base + (source_col & $7F) = VRAM-wrapped dest
    and #$007F
    clc
    adc z:temp+2
    tax                         ; X = dest WRAM address
    sep #$20
    .a8
    lda [temp+4], y             ; read tile from flat ROM
    sta f:$7E0000, x            ; store to VRAM-wrapped buffer position

    ; Advance source column (wrap at 512)
    rep #$20
    .a16
    lda z:temp+0
    inc
    and #$01FF
    sta z:temp+0

    ; Decrement counter
    lda z:temp+8
    dec
    sta z:temp+8
    sep #$20
    .a8
    bne @row_loop
    rts

; =============================================================================
; stream_decompress_column — copy 128 tiles from flat ROM for one column
;
; Input:  temp+0 = logical column X (0-511)
;         Y (I16) = destination WRAM buffer address (e.g. $3C00)
; Entry:  A8/I16
; Output: 128 bytes written to dest buffer in VRAM-wrapped order
; Clobbers: A, X, Y, temp+0..temp+8
;
; CRITICAL: tiles must be placed at buffer[(world_row % 128)] so that
; the NMI DMA (VMAIN=$02: buffer[0]→VRAM row 0, buffer[1]→VRAM row 1)
; matches Mode 7's VRAM[(row%128)][(col%128)] tile lookup.
; =============================================================================
stream_decompress_column:
    sty z:temp+2                ; save output buffer base

    ; Starting source row = (stream_cam_ty - 63) & $01FF
    rep #$20
    .a16
    lda z:stream_cam_ty
    sec
    sbc #63
    and #$01FF
    sta z:temp+8                ; current row (advances each iteration)

    ; Iteration counter in temp+10
    lda #128
    sta z:temp+10

    sep #$20
    .a8
@col_loop:
    ; Compute 24-bit ROM pointer for current row
    rep #$20
    .a16
    lda z:temp+8                ; current row
    FLAT_ROW_ADDR               ; -> temp+4/+5/+6 = 24-bit pointer

    ; X = buffer_base + (current_row & $7F) = VRAM-wrapped dest
    lda z:temp+8
    and #$007F
    clc
    adc z:temp+2
    tax                         ; X = dest WRAM address

    ; Y = column offset (fixed for this entire call)
    lda z:temp+0
    tay
    sep #$20
    .a8
    lda [temp+4], y             ; read tile from flat ROM
    sta f:$7E0000, x            ; store to VRAM-wrapped buffer position

    ; Advance row (wrap at 512)
    rep #$20
    .a16
    lda z:temp+8
    inc
    and #$01FF
    sta z:temp+8

    ; Decrement counter
    lda z:temp+10
    dec
    sta z:temp+10
    sep #$20
    .a8
    bne @col_loop
    rts


; =============================================================================
; BANK1: Track map data (tileset + tilemap + palette + metadata)
; =============================================================================
; Generated by: PYTHONPATH=. python toolchain/track_generator_v2.py
; Outputs: track_tiles_v2.bin (768B), track_tilemap_v2.bin (16384B),
;          track_palette_v2.inc (34B), track_meta.inc (~128B)
; =============================================================================
.segment "BANK1"
; Keep airship_* label names to avoid changing VRAM upload loop
airship_tiles:
    .incbin "assets/racing/track_tiles_v2.bin"     ; 768 bytes: 12 tiles × 64B, 8bpp
airship_tilemap_full:
    .incbin "assets/racing/track_tilemap_boot.bin"  ; 16384 bytes: 128×128 boot region (centered on start)
airship_palette:
    .include "track_palette_v2.inc"         ; 34 bytes: 17 BGR555 colors

; Track metadata: start position (pixel coords) and waypoints
.include "track_meta.inc"

; Metatile data (kept for boot tilemap validation, not used at runtime)
stream_super_meta_map:
    .incbin "assets/racing/super_meta_map.bin"      ; 4096 bytes
stream_super_meta_defs:
    .incbin "assets/racing/super_meta_defs.bin"     ; 4096 bytes
stream_metatile_defs:
    .incbin "assets/racing/metatile_defs.bin"       ; 1024 bytes

; =============================================================================
; Flat tilemap — 512×512 tiles across 8 ROM banks (256KB total)
; Each bank holds 64 rows × 512 bytes = 32KB.
; Row Y maps to bank (Y >> 6) + 2, offset $8000 + (Y & 63) * 512.
; =============================================================================
.segment "BANK2"
flat_tilemap_b2:
    .incbin "assets/racing/track_flat_bank0.bin"    ; rows 0-63
.segment "BANK3"
flat_tilemap_b3:
    .incbin "assets/racing/track_flat_bank1.bin"    ; rows 64-127
.segment "BANK4"
flat_tilemap_b4:
    .incbin "assets/racing/track_flat_bank2.bin"    ; rows 128-191
.segment "BANK5"
flat_tilemap_b5:
    .incbin "assets/racing/track_flat_bank3.bin"    ; rows 192-255
.segment "BANK6"
flat_tilemap_b6:
    .incbin "assets/racing/track_flat_bank4.bin"    ; rows 256-319
.segment "BANK7"
flat_tilemap_b7:
    .incbin "assets/racing/track_flat_bank5.bin"    ; rows 320-383
.segment "BANK8"
flat_tilemap_b8:
    .incbin "assets/racing/track_flat_bank6.bin"    ; rows 384-447
.segment "BANK9"
flat_tilemap_b9:
    .incbin "assets/racing/track_flat_bank7.bin"    ; rows 448-511

; Static midday sky gradient (672 bytes = 3 channels × 224 scanlines)
; Generated by: python sky_gradient_gen.py --sky-r 2 --sky-g 8 --sky-b 28 --hor-r 31 --hor-g 16 --hor-b 4
.segment "BANKA"
.include "sky_midday_gradient.inc"

; Return to CODE segment for fog band routines
.segment "CODE"





; =============================================================================
; apply_fog_band — Attenuate 5 scanlines at horizon for smooth sky-to-ground fade
; Saves original bytes to fog_cache, then writes attenuated values.
; Attenuation (pv_l0-5 to pv_l0-1): 87.5%, 75%, 50%, 25%, 12.5%
; fog_cache layout: [R0..R4, G0..G4, B0..B4] = 15 bytes
; Expects: A8/I16. Clobbers: A, X, Y.
; =============================================================================
apply_fog_band:
    .a8
    .i16
    lda z:pv_l0
    cmp #FOG_BAND_SIZE + 1  ; need at least 6 sky scanlines
    bcs :+
    jmp @fog_skip            ; horizon too low, skip
:   sta z:fog_l0             ; remember where fog was applied
    ; Compute X = pv_l0 - FOG_BAND_SIZE = index of first fog scanline
    lda #0
    xba
    lda z:fog_l0
    sec
    sbc #FOG_BAND_SIZE
    tax                      ; X = fog start index

    phb
    lda #$7E
    pha
    plb                      ; DB = $7E for WRAM access

    ; --- R channel (prefix $20, fog_cache+0..+4) ---
    ; Scanline 0: 87.5% = val - (val>>3)
    lda a:active_grad_r, x
    sta z:fog_cache+0
    and #$1F
    sta z:temp+8
    lsr a
    lsr a
    lsr a                    ; val/8
    sta z:temp+9
    lda z:temp+8
    sec
    sbc z:temp+9             ; val - val/8 = 7*val/8
    ora #$20
    sta a:active_grad_r, x
    inx
    ; Scanline 1: 75% = (val*3)>>2
    lda a:active_grad_r, x
    sta z:fog_cache+1
    and #$1F
    sta z:temp+8
    asl a
    clc
    adc z:temp+8
    lsr a
    lsr a
    ora #$20
    sta a:active_grad_r, x
    inx
    ; Scanline 2: 50% = val>>1
    lda a:active_grad_r, x
    sta z:fog_cache+2
    and #$1F
    lsr a
    ora #$20
    sta a:active_grad_r, x
    inx
    ; Scanline 3: 25% = val>>2
    lda a:active_grad_r, x
    sta z:fog_cache+3
    and #$1F
    lsr a
    lsr a
    ora #$20
    sta a:active_grad_r, x
    inx
    ; Scanline 4: 12.5% = val>>3
    lda a:active_grad_r, x
    sta z:fog_cache+4
    and #$1F
    lsr a
    lsr a
    lsr a
    ora #$20
    sta a:active_grad_r, x

    ; --- G channel (prefix $40, fog_cache+5..+9) ---
    lda #0
    xba
    lda z:fog_l0
    sec
    sbc #FOG_BAND_SIZE
    tax
    ; Scanline 0: 87.5%
    lda a:active_grad_g, x
    sta z:fog_cache+5
    and #$1F
    sta z:temp+8
    lsr a
    lsr a
    lsr a
    sta z:temp+9
    lda z:temp+8
    sec
    sbc z:temp+9
    ora #$40
    sta a:active_grad_g, x
    inx
    ; Scanline 1: 75%
    lda a:active_grad_g, x
    sta z:fog_cache+6
    and #$1F
    sta z:temp+8
    asl a
    clc
    adc z:temp+8
    lsr a
    lsr a
    ora #$40
    sta a:active_grad_g, x
    inx
    ; Scanline 2: 50%
    lda a:active_grad_g, x
    sta z:fog_cache+7
    and #$1F
    lsr a
    ora #$40
    sta a:active_grad_g, x
    inx
    ; Scanline 3: 25%
    lda a:active_grad_g, x
    sta z:fog_cache+8
    and #$1F
    lsr a
    lsr a
    ora #$40
    sta a:active_grad_g, x
    inx
    ; Scanline 4: 12.5%
    lda a:active_grad_g, x
    sta z:fog_cache+9
    and #$1F
    lsr a
    lsr a
    lsr a
    ora #$40
    sta a:active_grad_g, x

    ; --- B channel (prefix $80, fog_cache+10..+14) ---
    lda #0
    xba
    lda z:fog_l0
    sec
    sbc #FOG_BAND_SIZE
    tax
    ; Scanline 0: 87.5%
    lda a:active_grad_b, x
    sta z:fog_cache+10
    and #$1F
    sta z:temp+8
    lsr a
    lsr a
    lsr a
    sta z:temp+9
    lda z:temp+8
    sec
    sbc z:temp+9
    ora #$80
    sta a:active_grad_b, x
    inx
    ; Scanline 1: 75%
    lda a:active_grad_b, x
    sta z:fog_cache+11
    and #$1F
    sta z:temp+8
    asl a
    clc
    adc z:temp+8
    lsr a
    lsr a
    ora #$80
    sta a:active_grad_b, x
    inx
    ; Scanline 2: 50%
    lda a:active_grad_b, x
    sta z:fog_cache+12
    and #$1F
    lsr a
    ora #$80
    sta a:active_grad_b, x
    inx
    ; Scanline 3: 25%
    lda a:active_grad_b, x
    sta z:fog_cache+13
    and #$1F
    lsr a
    lsr a
    ora #$80
    sta a:active_grad_b, x
    inx
    ; Scanline 4: 12.5%
    lda a:active_grad_b, x
    sta z:fog_cache+14
    and #$1F
    lsr a
    lsr a
    lsr a
    ora #$80
    sta a:active_grad_b, x

    plb                      ; restore DB
    lda #1
    sta z:fog_active
    rts

@fog_skip:
    .a8
    stz z:fog_active
    stz z:fog_l0
    rts

; =============================================================================
; undo_fog_band — Restore pre-attenuation bytes from fog_cache (5 scanlines)
; fog_cache layout: [R0..R4, G0..G4, B0..B4] = 15 bytes
; Expects: A8/I16. Clobbers: A, X.
; =============================================================================
undo_fog_band:
    .a8
    .i16
    lda z:fog_active
    beq @undo_done           ; no fog applied, nothing to undo
    ; Compute X = fog_l0 - FOG_BAND_SIZE
    lda #0
    xba
    lda z:fog_l0
    sec
    sbc #FOG_BAND_SIZE
    tax

    phb
    lda #$7E
    pha
    plb

    ; Restore R channel (5 bytes)
    lda z:fog_cache+0
    sta a:active_grad_r+0, x
    lda z:fog_cache+1
    sta a:active_grad_r+1, x
    lda z:fog_cache+2
    sta a:active_grad_r+2, x
    lda z:fog_cache+3
    sta a:active_grad_r+3, x
    lda z:fog_cache+4
    sta a:active_grad_r+4, x

    ; Restore G channel (5 bytes)
    lda z:fog_cache+5
    sta a:active_grad_g+0, x
    lda z:fog_cache+6
    sta a:active_grad_g+1, x
    lda z:fog_cache+7
    sta a:active_grad_g+2, x
    lda z:fog_cache+8
    sta a:active_grad_g+3, x
    lda z:fog_cache+9
    sta a:active_grad_g+4, x

    ; Restore B channel (5 bytes)
    lda z:fog_cache+10
    sta a:active_grad_b+0, x
    lda z:fog_cache+11
    sta a:active_grad_b+1, x
    lda z:fog_cache+12
    sta a:active_grad_b+2, x
    lda z:fog_cache+13
    sta a:active_grad_b+3, x
    lda z:fog_cache+14
    sta a:active_grad_b+4, x

    plb
    stz z:fog_active
    stz z:fog_l0
@undo_done:
    rts




