; =============================================================================
; mode7_explore — Mode 7 overhead EXPLORATION on a STREAMING large world
; =============================================================================
; Streaming rail v2 / Sprint S2 (+ F1 remediation: world grown to 512x512 so
; "several windows" is LITERAL).  A top-down Mode 7 overworld EXPLORATION game:
; an avatar walks a LARGE authored world (512x512 tiles = 4096x4096 px — SEVERAL
; windows wide AND tall vs the 128x128 Mode 7 VRAM window; the camera-clamp box
; gives ~3 windows of camera travel / ~4 windows of distinct streamed content
; each axis).  Regions stream into the VRAM window seamlessly as the avatar
; walks — no pop-in, tearing, or black bands — forward, back, and idle; water +
; mountains BLOCK movement.
;
; FORKED from templates/rpg/ (the proven Mode 7 overhead overworld + grid
; movement + tile collision).  REUSED unchanged: the screen-centred avatar (OAM
; 0), the grid-step slide machine (1 tile / 8 px per press, animated over 8
; frames), and the collision-rejects-a-wall pattern.  CHANGED vs rpg:
;
;   1. STREAMING (not a static whole-map load).  rpg loads a 128x128 Mode 7 map
;      once (`sf_mode7_load_map ovw_map`).  Here the world is 512x512; we seed
;      the initial 128x128 window once, then `sf_mode7_stream_tick` each frame
;      keyed to the camera's WORLD tile position streams the leading row/column
;      in.  Built with MODE7_STREAM_NMI (the VBlank DMA dispatch) + lorom_stream.cfg.
;
;   2. WORLD-SPACE coords + LUT collision (not the 128-pinned `& $7F`, and NOT a
;      separate collision table).  The camera walks 0..511 tiles; collision reads
;      the SAME FLAT ROM tilemap byte the streaming engine reads (a ROM read, not
;      a VRAM read — safe) at the world tile, then LUTs it through a 256-entry
;      tile-id -> terrain-class table (tile_terrain_lut) to walkable/blocked.  The
;      tilemap is the SINGLE SOURCE OF TRUTH — what you SEE is what blocks you —
;      and a 512x512 byte tilemap (256 KB) + a byte collision table (256 KB) would
;      exceed the 512 KB ROM, so the LUT-derive approach is what keeps the rail at
;      512 KB.  The avatar walks genuinely NEW terrain, never wrap-repeating the
;      same 128 tiles.  The camera is CLAMPED to [HALF .. WORLD-1-HALF] = [64..447]
;      so the 128 window always holds real authored data (never crosses the
;      world's toroidal seam) and the avatar traverses ~3 windows of travel.
;
; STATIC top-down Mode 7 (identity affine, M7SEL=$00 WRAP — NOT fill): the
; 128x128 VRAM tilemap is a 1:1 wrapped window onto the world centred on the
; camera tile.  The avatar stays screen-centred; the CAMERA carries world
; position.  This is the SAME static-Mode-7 setup the S1 proof ROM uses.
;
; Build: make mode7_explore   (generic templates rule reads the LDCFG sentinel)
; LDCFG: lorom_stream.cfg
;   ^ 512KB LoROM: bank 0 = code, bank 1 = the 32KB interleaved seed, banks 2-9 =
;     the FLAT streaming tilemap (8 banks x 32KB = 256KB, 512x512).  Collision is
;     LUT-derived from those same flat banks — NO dedicated collision banks.
;     The MODE7_STREAM_NMI .define below pulls the streaming VBlank DMA dispatch
;     into nmi_handler.asm (the generic template rule can't pass -D, so the ROM
;     defines it in source before the include — see CLAUDE.md ".ifdef" gate).
; =============================================================================

.p816
.smart

; --- pull the Mode 7 streaming VBlank DMA dispatch into nmi_handler.asm. The
;     stock NMI gates engine/mode7_stream_nmi.inc behind `.ifdef MODE7_STREAM_NMI`;
;     defining it here (BEFORE the nmi_handler include below) is equivalent to the
;     `-D MODE7_STREAM_NMI` the S1 test ROM passes on the ca65 command line, so the
;     generic sentinel-driven template build needs no Makefile edit. ------------
MODE7_STREAM_NMI = 1

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_state_mirror
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_bg.inc"            ; (mode7 register helpers pull bg engine partners)
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; sf_mode7_load_map (the seed upload) + M7 equates
.include "sf_mode7_stream.inc"  ; sf_mode7_stream_init / _set_cam / _tick (S1 substrate)
.include "sf_input.inc"         ; btn / btnp (+ buttons.inc)
.include "engine_state.inc"
.include "explore_world.inc"    ; world dims, spawn, TILE_*/TERR_*, palette
.include "explore_obj.inc"      ; avatar OBJ CHR + palette + AVATAR_TILE

; --- game DP state ($32-$5F per kit convention; clear of the kit API block
;     $60-$9F and the streaming engine's ES_M7S_PTR scratch at $9A). ----------
cam_px       = $32             ; camera X pixel (world space, 16-bit integer)
cam_py       = $34             ; camera Y pixel (world space, 16-bit integer)
step_active  = $36             ; 1 = a grid slide is in progress
step_remain  = $38             ; frames left in the current slide (1 px/frame)
step_dx      = $3A             ; per-frame camera dx (-1 / 0 / +1)
step_dy      = $3C             ; per-frame camera dy (-1 / 0 / +1)
tgt_tx       = $3E             ; candidate destination tile X (collision lookup)
tgt_ty       = $40             ; candidate destination tile Y
col_ptr      = $42             ; 3 bytes: 24-bit pointer into the FLAT tilemap (collision read)
col_scratch  = $46             ; collision row-base scratch

; --- grid + world constants ---
TILE_PX      = 8               ; one tile = 8 world px (the grid step)
STEP_FRAMES  = 8               ; animate the 8px slide over 8 frames (1px/frame)
WORLD_HALF   = 64              ; half the 128-tile VRAM window (camera-clamp margin)
; camera clamp (TILE units): keep the 128 window inside the authored world so it
; never crosses the world's toroidal seam (no wrap-repeat of the same 128 tiles).
CLAMP_TX_MIN = WORLD_HALF
CLAMP_TX_MAX = (WORLD_T_TILES - 1 - WORLD_HALF)   ; 256-1-64 = 191
CLAMP_TY_MIN = WORLD_HALF
CLAMP_TY_MAX = (WORLD_T_TILES - 1 - WORLD_HALF)
CAM_PX0      = WORLD_SPAWN_TX * 8
CAM_PY0      = WORLD_SPAWN_TY * 8
AV_X0        = 120             ; avatar screen X (kept centred; world scrolls under it)
AV_Y0       = 104             ; avatar screen Y

; --- collision reads the FLAT tilemap (the SAME banks the streaming engine
;     reads) and LUTs the tile id -> terrain class.  The flat tilemap is 8 banks
;     (BANK2..BANK9 = $02:8000..$09:8000), 64 rows/bank, 512 bytes/row:
;       bank   = WORLD_FLAT_BANK_BASE + (ty >> 6)        (= $02 + (ty>>6))
;       offset = $8000 + (ty & 63) * 512 + tx
;     The byte read there is a TILE ID; tile_terrain_lut[tile] is its terrain
;     class.  NO separate collision table (would push the ROM past 512 KB). ------
; WORLD_FLAT_BANK_BASE comes from explore_world.inc (= 2).

; --- debug region offsets (relative to $7E:E000) ---
DBG_HEARTBEAT = $E010           ; 2B: frame counter
DBG_CAM_TX    = $E012           ; 2B: camera tile X (from streaming state)
DBG_CAM_TY    = $E014           ; 2B: camera tile Y
DBG_LAST_TX   = $E018           ; 2B: last-streamed tile X
DBG_LAST_TY   = $E01A           ; 2B: last-streamed tile Y
DBG_BLOCK_CT  = $E01C           ; 2B: count of blocked steps (collision proof)

; --- Mode 7 register equates (local, for the direct static setup) ---
REG_BGMODE = $2105
REG_M7SEL  = $211A
REG_M7A    = $211B
REG_M7B    = $211C
REG_M7C    = $211D
REG_M7D    = $211E
REG_M7X    = $211F
REG_M7Y    = $2120

; --- joypad masks (JOY1_CURRENT bit layout, matches the kit templates) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_UP    = $0800
JOY_DOWN  = $0400

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; stock engine NMI; pulls mode7_stream_nmi.inc (MODE7_STREAM_NMI)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init

    ; --- STABLE OAM ordering: the avatar lives at slot 0 (tests read it by
    ;     identity), so disable Y-sort (mode 2 = stable, call order). ---
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- upload the interleaved seed (the initial 128x128 window) under blank ---
    sf_mode7_load_map explore_seed, #$8000

    ; --- upload the world palette to CGRAM (index i = PAL_RGB[i]) ------------
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

    ; --- avatar OBJ CHR + palette.  The Mode 7 map owns VRAM words $0000-$3FFF,
    ;     so the OBJ name base moves to word $4000 (OBSEL=$62); tile 1024 = word
    ;     $4000, so OAM tile numbers stay 0.. relative to that base.  The avatar
    ;     CHR is uploaded at OBJ tile (1024 + AVATAR_TILE) so AVATAR_TILE indexes
    ;     it directly. ---------------------------------------------------------
    sf_load_obj_pal 0, obj_pal
    sf_load_obj_chr 1024, avatar_chr, EXPLORE_OBJ_BYTES
    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: OBJ name base word $4000, 16x16/32x32
    rep #$30
    .a16
    .i16

    ; --- static top-down Mode 7: BGMODE 7, identity matrix, WRAP --------------
    sep #$20
    .a8
    lda #$07
    sta REG_BGMODE              ; BGMODE = 7
    sta SHADOW_BGMODE
    stz REG_M7SEL              ; M7SEL = $00 (WRAP, no flip) — NOT fill
    ; identity affine: A=$0100, B=0, C=0, D=$0100 (write-twice low then high)
    lda #$00
    sta REG_M7A
    lda #$01
    sta REG_M7A                 ; A = $0100 = 1.0
    lda #$00
    sta REG_M7B
    sta REG_M7B                 ; B = 0
    sta REG_M7C
    sta REG_M7C                 ; C = 0
    sta REG_M7D                 ; D lo
    lda #$01
    sta REG_M7D                 ; D = $0100 = 1.0
    stz REG_M7X
    stz REG_M7X
    stz REG_M7Y
    stz REG_M7Y
    ; main screen: BG1 (Mode 7 layer) + OBJ.  The stock NMI commits TM from
    ; SHADOW_TM each frame, so set the SHADOW (not just the live reg).
    lda #$11                    ; TM = BG1 + OBJ
    sta $212C
    sta SHADOW_TM
    stz $212D                   ; TS = 0
    rep #$30
    .a16
    .i16

    ; --- camera starts at spawn (world tile centre) -------------------------
    lda #CAM_PX0
    sta cam_px
    lda #CAM_PY0
    sta cam_py
    stz step_active
    stz step_remain
    stz step_dx
    stz step_dy

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

    ; --- apply the spawn camera + draw the avatar so frame 0 is centred ------
    jsr apply_camera
    jsr draw_avatar

; =============================================================================
; The frame spine.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin              ; wait for NMI; latch input
    jsr explore_tick
    sf_frame_end
    jmp game_loop

; =============================================================================
; explore_tick — RPG grid movement + WORLD-SPACE tile collision + streaming.
;
; The avatar stays screen-centred (OAM 0); the D-pad scrolls the Mode 7 CAMERA
; under it, one tile (8 px) per press, animated over STEP_FRAMES frames at 1
; px/frame.  A press into a BLOCKED tile (water/mountain) is rejected via the
; WORLD-SPACE collision table — the camera does not move.  The camera is clamped
; to the authored world so the 128 window always holds real data.
;
; Each frame:
;   1. If a slide is in progress, advance it (ignore new input until it lands).
;   2. Else read a held D-pad direction; if the destination tile is walkable,
;      START a slide.
;   3. Apply the camera, stream the leading edge, draw the centred avatar.
;
; WIDTH-RISK: A16/I16 entry/exit. try_start_step toggles A8 internally for the
; 1-byte terrain read and restores A16. No raw width toggles in this body.
; =============================================================================
explore_tick:
    .a16
    .i16
    ; --- (1) a slide is in progress: advance it, ignore new input ---
    lda step_active
    beq et_idle
    lda cam_px
    clc
    adc step_dx
    sta cam_px
    lda cam_py
    clc
    adc step_dy
    sta cam_py
    lda step_remain
    dec a
    sta step_remain
    bne et_apply
    stz step_active             ; slide complete — camera grid-aligned again
    bra et_apply
et_idle:
    .a16
    ; --- (2) held D-pad -> try ONE grid step (first matching dir) ---
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq et_chk_right
    ldx #$FFFF                  ; dx = -1 tile
    ldy #$0000
    jsr try_start_step
    bra et_apply
et_chk_right:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq et_chk_up
    ldx #$0001
    ldy #$0000
    jsr try_start_step
    bra et_apply
et_chk_up:
    .a16
    lda JOY1_CURRENT
    bit #JOY_UP
    beq et_chk_down
    ldx #$0000
    ldy #$FFFF
    jsr try_start_step
    bra et_apply
et_chk_down:
    .a16
    lda JOY1_CURRENT
    bit #JOY_DOWN
    beq et_apply
    ldx #$0000
    ldy #$0001
    jsr try_start_step
et_apply:
    .a16
    .i16
    ; --- (3) apply camera, stream the leading edge, draw the avatar ---
    jsr apply_camera
    sf_mode7_stream_set_cam cam_px, cam_py
    sf_mode7_stream_tick
    jsr draw_avatar
    jsr mirror_debug
    rts

; =============================================================================
; apply_camera — pan the Mode 7 view so the camera tile stays screen-centred.
; The window origin (tiles) = cam_tile - 64; with the wrapped 128x128 VRAM
; window the BG1 scroll (= M7HOFS/M7VOFS under Mode 7) = (cam_px - 128) & $1FFF
; keeps the camera centred on the 256px-wide wrapped Mode 7 plane (the stock NMI
; commits the scroll shadow).
; Entry/Exit: A16/I16. Clobbers A.
; WIDTH-RISK: A16/I16 entry; A8 only for the 1-byte dirty-flag store, restored.
; =============================================================================
apply_camera:
    .a16
    .i16
    lda cam_px
    sec
    sbc #128
    and #$1FFF
    sta SHADOW_BG1HOFS
    lda cam_py
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
    rts

; =============================================================================
; draw_avatar — draw the explorer avatar (OAM slot 0, 16x16, OBJ palette 0)
; fixed at screen centre; the world scrolls under it (camera-follows-player).
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; spr/spr_clear run their own widths, return A16/I16.
; =============================================================================
draw_avatar:
    .a16
    .i16
    spr_clear
    spr #AVATAR_TILE, #AV_X0, #AV_Y0, #$0080, #2   ; OBJ palette 0, priority 2, 16x16
    rts

; =============================================================================
; try_start_step — start a grid slide in tile-direction (X=dx, Y=dy) IF the
; destination tile is walkable. X/Y are signed 16-bit tile deltas (-1/0/+1).
;
; Computes the destination tile from the CURRENT camera (cam/8 + delta), CLAMPS
; it to the authored-world camera-clamp box, looks up the WORLD-SPACE collision
; table (16-bit indexed collision[ty*256+tx], two ROM banks), and rejects when
; the terrain id is in [TERR_BLOCKED_MIN, TERR_BLOCKED_MAX] (water/mountain).
; Walkable -> arm the slide. Blocked or clamped -> no move (a press into a wall
; or the world edge is a no-op; the blocked counter is bumped for the test).
;
; Entry: A16/I16. X = dx, Y = dy. Clobbers A, X, Y, col_ptr, col_scratch.
; WIDTH-RISK: A16/I16 entry. Toggles A8 for the 1-byte terrain read, restores
; A16 before returning. The blocked/walkable branch targets carry explicit
; width annotations.
; =============================================================================
try_start_step:
    .a16
    .i16
    stx step_dx                 ; dx (-1/0/+1)
    sty step_dy                 ; dy
    ; tgt_tx = (cam_px / 8) + dx
    lda cam_px
    lsr a
    lsr a
    lsr a                       ; current tile X = cam_px / 8
    clc
    adc step_dx
    sta tgt_tx
    ; tgt_ty = (cam_py / 8) + dy
    lda cam_py
    lsr a
    lsr a
    lsr a
    clc
    adc step_dy
    sta tgt_ty
    ; --- CLAMP the destination tile to the authored-world camera box. A step
    ;     that would push the window past the world edge is rejected (no move),
    ;     so the 128 window never crosses the toroidal seam. -------------------
    lda tgt_tx
    cmp #CLAMP_TX_MIN
    bcc tss_blocked             ; tx < MIN -> reject
    cmp #(CLAMP_TX_MAX + 1)
    bcs tss_blocked             ; tx > MAX -> reject
    lda tgt_ty
    cmp #CLAMP_TY_MIN
    bcc tss_blocked
    cmp #(CLAMP_TY_MAX + 1)
    bcs tss_blocked
    ; --- world-space collision lookup: terrain = collision[ty*256 + tx] -------
    jsr terr_at_world           ; A8 terrain id on return? -> A16 zero-extended
    cmp #TERR_BLOCKED_MIN
    bcc tss_walkable            ; id < MIN -> walkable
    cmp #(TERR_BLOCKED_MAX + 1)
    bcs tss_walkable            ; id > MAX -> walkable
tss_blocked:
    .a16
    ; blocked terrain or world edge: clear staged deltas, bump the blocked count
    stz step_dx
    stz step_dy
    ; long-indexed RMW so the WRAM store always encodes a 24-bit address (DB=$00)
    ldx #0
    lda f:$7E0000 + DBG_BLOCK_CT
    inc a
    sta f:$7E0000 + DBG_BLOCK_CT, x
    rts
tss_walkable:
    .a16
    ; arm the slide: step_dx/step_dy already hold the per-frame px deltas
    lda #STEP_FRAMES
    sta step_remain
    lda #1
    sta step_active
    rts

; =============================================================================
; terr_at_world — return the WORLD-SPACE terrain CLASS of tile (tgt_tx, tgt_ty)
; in A (zero-extended to A16).  F1 remediation: collision now reads the SAME FLAT
; ROM tilemap byte the streaming engine reads (a tile id), then LUTs it through
; the 256-entry tile_terrain_lut to a terrain class.  NO separate collision table
; (a 512x512 byte collision table would push the ROM past 512 KB).
;
; The flat tilemap is 8 banks (BANK2..BANK9), 64 rows/bank, 512 bytes/row:
;   bank   = WORLD_FLAT_BANK_BASE + (ty >> 6)
;   offset = $8000 + (ty & 63) * 512 + tx
; tile id  = [24-bit ptr]  (the LOW-byte tilemap entry == CHR/tile index)
; terrain  = tile_terrain_lut[tile id]   (a RODATA byte LUT, bank-resolved via ^)
;
; Entry: A16/I16, tgt_tx/tgt_ty hold the tile. Exit: A16 with the terrain class
; in the low 8 bits (high byte 0), I16 preserved. Clobbers A, X, Y, col_ptr,
; col_scratch.
; WIDTH-RISK: A16/I16 entry; builds the 24-bit pointer in A16, toggles A8 for the
; two 1-byte reads (tile id, then the LUT entry), RESTORES A16 before rts (an A8
; exit would assemble the caller's post-jsr `cmp #imm` as 16-bit while the CPU
; ran A8 — the stray-third-byte = BRK silent-corruption class). No multi-path
; label after the toggle.
; =============================================================================
terr_at_world:
    .a16
    .i16
    ; --- bank byte = WORLD_FLAT_BANK_BASE + (ty >> 6) ---
    lda tgt_ty
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                       ; ty >> 6 (0..7 for a 512-row world)
    clc
    adc #WORLD_FLAT_BANK_BASE
    sep #$20
    .a8
    sta col_ptr+2               ; 24-bit pointer bank byte
    rep #$20
    .a16
    ; --- offset = $8000 + (ty & 63) * 512 + tx ---
    lda tgt_ty
    and #$003F                  ; ty & 63
    xba                         ; * 256 (low byte -> high byte)
    asl a                       ; * 512
    clc
    adc #$8000                  ; + LoROM bank base
    sta col_scratch             ; row base offset
    lda tgt_tx
    and #$01FF                  ; tx (0..511)
    clc
    adc col_scratch
    sta col_ptr                 ; lo16 of the 24-bit pointer
    ; --- read tile id from the flat tilemap via indirect long ---
    ldy #0
    sep #$20
    .a8
    lda [col_ptr], y            ; A8 tile id (the rendered tile)
    ; --- LUT the tile id -> terrain class. tile_terrain_lut lives in RODATA;
    ;     index by the tile id (0..255) via absolute-long X so the bank is the
    ;     LUT's actual bank (^tile_terrain_lut), not a hardcoded one (CLAUDE.md
    ;     "WRAM Long-Addressing Requires the Bank Byte" ROM-side sibling). ------
    rep #$20
    .a16
    and #$00FF                  ; A = tile id (high byte cleared) -> X index
    tax
    sep #$20
    .a8
    lda f:tile_terrain_lut, x   ; A8 terrain class (ld65 resolves the LUT bank)
    rep #$20                    ; restore A16 so the caller stays A16 across the jsr
    .a16
    and #$00FF                  ; zero-extend: A = terrain class (high byte cleared)
    rts

; =============================================================================
; mirror_debug — mirror the streaming + game state to the debug region so the
; python proof test knows the camera/window position without re-deriving timing.
; Entry/Exit: A16/I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 throughout — pure 16-bit stores.
; =============================================================================
mirror_debug:
    .a16
    .i16
    ; Long-indexed stores (ldx #0 + sta f:$7E0000+addr,x) so ca65 always encodes
    ; a full 24-bit address — a bare `sta f:$E0xx` with DB=$00 emits STA abs and
    ; the write hits the I/O/ROM region, not WRAM (CLAUDE.md "Never use bare
    ; sta f:$7Eaddr for WRAM writes when DB=$00").
    ldx #0
    lda FRAME_COUNTER
    sta f:$7E0000 + DBG_HEARTBEAT, x
    lda f:$7E0000 + M7S_CAM_TX
    sta f:$7E0000 + DBG_CAM_TX, x
    lda f:$7E0000 + M7S_CAM_TY
    sta f:$7E0000 + DBG_CAM_TY, x
    lda f:$7E0000 + M7S_LAST_TX
    sta f:$7E0000 + DBG_LAST_TX, x
    lda f:$7E0000 + M7S_LAST_TY
    sta f:$7E0000 + DBG_LAST_TY, x
    rts

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order, plus the
; streaming routine. (mode7 perspective machinery is linked but unused; we drive
; a static affine directly above.)
; =============================================================================
.include "input_handler.asm"
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "bg_engine.asm"

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
; .incbin resolves relative to THIS file's dir (GAP-3), so "assets/<basename>"
; is copy-safe (copying templates/mode7_explore/ -> templates/<theme>/ only needs
; the basename changed, never the directory).
.segment "BANK1"
explore_seed:
    .incbin "assets/explore_seed.bin"

; --- BANK2..BANK9: the FLAT streaming tilemap (512 cols x 1 byte, 64 rows/bank).
;     The streaming tick (and terr_at_world collision) compute
;     bank = (row>>6) + WORLD_FLAT_BANK_BASE (=2), so bank0 must link at $02:8000,
;     bank1 at $03:8000, ... bank7 at $09:8000.  8 banks x 32KB = 256KB = 512x512.
;     Collision LUTs these SAME banks — no dedicated collision banks. -----------
.segment "BANK2"
explore_flat_b2:
    .incbin "assets/explore_flat_bank0.bin"   ; rows 0..63
.segment "BANK3"
explore_flat_b3:
    .incbin "assets/explore_flat_bank1.bin"   ; rows 64..127
.segment "BANK4"
explore_flat_b4:
    .incbin "assets/explore_flat_bank2.bin"   ; rows 128..191
.segment "BANK5"
explore_flat_b5:
    .incbin "assets/explore_flat_bank3.bin"   ; rows 192..255
.segment "BANK6"
explore_flat_b6:
    .incbin "assets/explore_flat_bank4.bin"   ; rows 256..319
.segment "BANK7"
explore_flat_b7:
    .incbin "assets/explore_flat_bank5.bin"   ; rows 320..383
.segment "BANK8"
explore_flat_b8:
    .incbin "assets/explore_flat_bank6.bin"   ; rows 384..447
.segment "BANK9"
explore_flat_b9:
    .incbin "assets/explore_flat_bank7.bin"   ; rows 448..511
