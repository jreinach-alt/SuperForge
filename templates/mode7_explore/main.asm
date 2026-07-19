; =============================================================================
; mode7_explore — Mode 7 overhead EXPLORATION on a STREAMING large world
; =============================================================================
; A top-down Mode 7 EXPLORATION game: an avatar walks a LARGE authored overworld
; (512x512 tiles = 4096x4096 px — SEVERAL screens wide AND tall vs the 128x128
; Mode 7 VRAM window; the camera-clamp box gives ~3 windows of camera travel /
; ~4 windows of distinct streamed content each axis).  Regions stream into the
; VRAM window seamlessly as the avatar walks — no pop-in, tearing, or black bands
; — forward, back, and idle; water + mountains BLOCK movement, and an ocean coast
; frames the explorable region.
;
; Controls: the D-pad walks the avatar one tile (up/down/left/right); the camera
;   scrolls the world under the screen-centred avatar.  No other buttons are read.
;
; File layout (top to bottom): INIT (RESET — one-time boot: audio, seed upload,
;   palette, avatar, Mode 7, streaming arm, screen-on-dark, music); MAIN LOOP
;   (game_loop — the once-per-frame heartbeat, START READING THERE); the per-frame
;   body (explore_tick -> apply_camera / draw_avatar / try_start_step +
;   terr_at_world world-space LUT collision / mirror_debug / boot_fade); the
;   engine includes (input, sprite, DMA, BG, Mode 7 stream, TAD audio bridge); and
;   DATA (the seed window + the 8-bank flat streaming tilemap).
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
;      in.  Built with MODE7_STREAM_NMI (the VBlank DMA dispatch) + lorom_tad_stream.cfg.
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
; position.  This is a plain static affine (no perspective), driven directly below.
;
; Build: make mode7_explore   (generic templates rule reads the LDCFG sentinel)
; LDCFG: lorom_tad_stream.cfg
;   ^ 512KB LoROM: bank 0 = code, bank 1 = the 32KB interleaved seed, banks 2-9 =
;     the FLAT streaming tilemap (8 banks x 32KB = 256KB, 512x512), bank $0A = the
;     TAD audio data (overworld music).  A *_tad*.cfg name links the TAD audio
;     objects + audio include path in the generic build rule (no Makefile edit).
;     Collision is LUT-derived from those same flat banks — NO dedicated collision banks.
;     The MODE7_STREAM_NMI .define below pulls the streaming VBlank DMA dispatch
;     into nmi_handler.asm (the generic template rule can't pass -D, so the ROM
;     defines it in source before the include — see CLAUDE.md ".ifdef" gate).
; =============================================================================

.p816
.smart

; --- pull the Mode 7 streaming VBlank DMA dispatch into nmi_handler.asm.
;     Streaming rewrites VRAM, and the PPU only accepts VRAM writes during VBlank
;     (forced blank) — so the leading-edge row/column DMA MUST run in the NMI. The
;     stock NMI does that dispatch, but only when engine/mode7_stream_nmi.inc is
;     pulled in, which it gates behind `.ifdef MODE7_STREAM_NMI`. Defining the
;     symbol here (BEFORE the nmi_handler include below) is equivalent to
;     `-D MODE7_STREAM_NMI` on the ca65 command line, so the generic sentinel-
;     driven template build needs no Makefile edit. --------------------------------
MODE7_STREAM_NMI = 1

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "OVERLAND TREK"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_state_mirror
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_bg.inc"            ; (mode7 register helpers pull bg engine partners)
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; sf_mode7_load_map (the seed upload) + M7 equates
.include "sf_mode7_stream.inc"  ; sf_mode7_stream_init / _set_cam / _tick (2-axis streamer)
.include "sf_input.inc"         ; btn / btnp (+ buttons.inc)
.include "sf_scene_mode.inc"    ; sf_blank_enter / sf_blank_exit (forced-blank bracket)
.include "sf_mosaic_transition.inc" ; sf_mosaic_transition_arm/tick/active (the scene wipe)
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD driver ca65 API (the vendored audio driver)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids for the shipped song set
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music
.include "explore_world.inc"    ; world dims, spawn, TILE_*/TERR_*, palette
.include "explore_obj.inc"      ; avatar OBJ CHR + palette + AVATAR_TILE
.include "explore_town.inc"     ; Mode 1 town-interior CHR + palette + TOWN_TILE_*

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
av_y         = $48             ; avatar screen Y for this frame (walk-bob target)
facing       = $4A             ; latched facing (FACE_*): last d-pad direction Elnora turned to
av_tile      = $4C             ; draw scratch: OAM base tile resolved from `facing`
av_attr      = $4E             ; draw scratch: OAM attribute flags resolved from `facing`

; --- town-visit arc DP state ($50-$5F; still the template game-DP window, clear
;     of the engine ES_* block at $0100+ and the streamer's $9A scratch). The
;     mosaic town-visit: step onto the demo house -> Mode 1 interior -> step onto
;     the door -> back to the streamed Mode 7 overworld at the SAVED camera. ------
scene_id     = $50             ; 0 = overworld (Mode 7 stream), 1 = town (Mode 1)
ovw_camx     = $52             ; saved overworld camera X px (restored on town exit)
ovw_camy     = $54             ; saved overworld camera Y px
town_px      = $56             ; town player tile X (0..31)
town_py      = $58             ; town player tile Y (0..31)
town_facing  = $5A             ; town avatar facing (FACE_*)
town_ctx     = $5C             ; town_classify query scratch: tile X
town_cty     = $5E             ; town_classify query scratch: tile Y

; --- facing codes: Elnora turns to face the last direction the d-pad pushed.
;     draw_avatar maps these to (OAM base tile, attribute flags) via face_*_lut.
;     LEFT reuses the RIGHT profile CHR, H-flipped by the OAM attribute bit. ------
FACE_DOWN    = 0
FACE_UP      = 1
FACE_LEFT    = 2
FACE_RIGHT   = 3

; --- grid + world constants ---
TILE_PX      = 8               ; one tile = 8 world px (the grid step)
STEP_FRAMES  = 8               ; animate the 8px slide over 8 frames (1px/frame)
WORLD_HALF   = 64              ; half the 128-tile VRAM window (camera-clamp margin)
; camera clamp (TILE units): keep the 128 window inside the authored world so it
; never crosses the world's toroidal seam (no wrap-repeat of the same 128 tiles).
CLAMP_TX_MIN = WORLD_HALF
CLAMP_TX_MAX = (WORLD_T_TILES - 1 - WORLD_HALF)   ; 512-1-64 = 447
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
REG_BG1SC   = $2107            ; BG1 tilemap base + size (Mode 1 town)
REG_BG12NBA = $210B            ; BG1/BG2 CHR base (Mode 1 town)
REG_TM      = $212C            ; main-screen layer designation

; --- joypad masks (JOY1_CURRENT bit layout, matches the kit templates) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_UP    = $0800
JOY_DOWN  = $0400

; --- TOWN scene (Mode 1 single-screen interior). A designed room: a plank floor
;     framed by stone walls, a table, and an EXIT DOOR in the bottom wall. The
;     avatar SPRITE walks the room (camera fixed at scroll 0). Collision + the
;     rendered tilemap both derive from town_classify (the room geometry is the
;     single source of truth). BG1 CHR/tilemap live in UPPER VRAM so the Mode 7
;     image ($0000-$3FFF) survives the visit (return needs no re-stream). --------
TOWN_ROOM_X0 = 2               ; room wall rectangle (tile coords)
TOWN_ROOM_X1 = 29
TOWN_ROOM_Y0 = 1
TOWN_ROOM_Y1 = 26
TOWN_DOOR_TX = 15              ; exit door: a gap in the bottom wall — step on it to
TOWN_DOOR_TY = 26             ;   mosaic back out to the overworld
TOWN_TABLE_X0 = 13            ; a 2x2 table (blocked) in the upper room
TOWN_TABLE_X1 = 14
TOWN_TABLE_Y0 = 10
TOWN_TABLE_Y1 = 11
TOWN_SPAWN_TX = 15            ; avatar spawn (a few tiles above the door)
TOWN_SPAWN_TY = 22
; town cell CLASS == the BG1 tile id used to render it (TOWN_TILE_* from
; explore_town.inc): FLOOR/DOOR walk, WALL/TABLE block, DOOR also EXITS.
TOWN_CLS_FLOOR = 0
TOWN_CLS_WALL  = 1
TOWN_CLS_DOOR  = 2
TOWN_CLS_TABLE = 3
; town BG1 VRAM (UPPER VRAM: clear of the Mode 7 image $0000-$3FFF AND the avatar
;   OBJ CHR at word $4000). CHR base word $5000 (BG12NBA nibble 5); tilemap base
;   word $5800 (BG1SC $58 = $5800>>10<<2, 32x32). The stock NMI's BG1 tilemap DMA
;   also targets word $5800 — but this rail never sets BG_TILEMAP_DIRTY, so the
;   town map is written DIRECTLY to VRAM under blank and never DMA-clobbered.
TOWN_CHR_VWORD = $5000
TOWN_MAP_VWORD = $5800
TOWN_BG1SC_VAL   = $58         ; BG1SC: tilemap base word $5800, 32x32
TOWN_BG12NBA_VAL = $05         ; BG12NBA: BG1 CHR base word $5000

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; stock engine NMI; pulls mode7_stream_nmi.inc (MODE7_STREAM_NMI)

NMI_STUB:
    rti

; =============================================================================
; INIT — one-time boot: audio, seed, palette, avatar, Mode 7, streaming, screen.
; =============================================================================
RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    sf_audio_init               ; boot the S-SMP + TAD driver ONCE, at power-on
                                ;   (the S-SMP must still be in its IPL state; this
                                ;   rail never soft-restarts, so never call it twice)

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
    stz $2121                   ; CGADD (CGRAM address): start at color 0
    ldx #0
@pal_loop:
    lda f:world_palette, x
    sta $2122                   ; CGDATA (CGRAM data): write a byte; index auto-advances
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
    lda #$11                    ; TM (main screen layers): BG1 (Mode 7) + OBJ
    sta $212C
    sta SHADOW_TM
    stz $212D                   ; TS (subscreen layers): none — this rail uses no subscreen
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
    stz facing                  ; boot idle -> DOWN (FACE_DOWN=0); mx002/oracle read tile 16

    ; --- arm streaming for the spawn tile -----------------------------------
    sf_mode7_stream_init #WORLD_SPAWN_TX, #WORLD_SPAWN_TY

    sf_debug_magic

    ; --- screen on + NMI on. Start at brightness 0 (display ON, not blank) so the
    ;     overworld DAWNS IN from black over the first ~30 frames (boot_fade, in
    ;     the loop) instead of snapping straight into gameplay — the attract/title
    ;     moment. The music (started below) rises with it. --------------------------
    sep #$20
    .a8
    stz $2100                   ; INIDISP: display on, brightness 0 (dawn-in from black)
    stz SHADOW_INIDISP          ; boot_fade ramps this shadow 0->15; the NMI commits it
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

    ; --- apply the spawn camera + draw the avatar so frame 0 is centred ------
    jsr apply_camera
    jsr draw_avatar

    ; --- start the overworld music (asynchronous: the song streams in over the
    ;     sf_audio_ticks pumped by the frame loop below) ------------------------
    sf_music #Song::ode_to_joy

; =============================================================================
; MAIN LOOP — the once-per-frame heartbeat.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin              ; wait for NMI; latch input
    sf_audio_tick               ; pump TAD every frame (streams the song load + SFX queue)
    ; boot dawn-in ramp — but NOT while a mosaic wipe owns the brightness (else the
    ; fade snaps the screen back to full-bright every frame and defeats the dissolve).
    sf_mosaic_transition_active ; A = nonzero while a scene wipe is in flight
    bne @skip_fade
    jsr boot_fade               ; boot dawn-in brightness ramp (no-op once full)
@skip_fade:
    .a16
    .i16
    sf_mosaic_transition_tick   ; advance any wipe (JSRs the swap at peak black; idle = no-op)
    ; dispatch the active scene's per-frame tick
    lda scene_id
    bne @town_frame
    jsr explore_tick            ; SC 0: streamed Mode 7 overworld
    bra @loop_end
@town_frame:
    .a16
    .i16
    jsr town_tick               ; SC 1: Mode 1 town interior
@loop_end:
    .a16
    .i16
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
    ; while a scene wipe runs the overworld is FROZEN — no input, no streaming, no
    ; state change; the Mode 7 floor keeps rendering (and mosaic-dissolving) from
    ; static VRAM. Resume when the wipe goes idle. (Also: a step onto the demo
    ; house arms the wipe, so this same guard suppresses further input that frame.)
    sf_mosaic_transition_active
    beq @run
    rts
@run:
    .a16
    .i16
    ; --- (1) a slide is in progress: advance it, ignore new input ---
    lda step_active
    beq @idle
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
    bne @apply
    stz step_active             ; slide complete — camera grid-aligned again
    jsr check_town_entry        ; landed on the demo house? -> arm the town wipe
    bra @apply
@idle:
    .a16
    ; --- (2) held D-pad -> try ONE grid step, in priority order (L, R, U, D).
    ;     After each try, if a slide STARTED (step_active set) we're done; if the
    ;     chosen direction was BLOCKED, FALL THROUGH to the next held axis. This
    ;     lets a held DIAGONAL keep moving along an open axis when its higher-
    ;     priority axis is against a wall — without the fall-through, a blocked
    ;     priority axis would eat the whole diagonal and freeze the avatar. ---
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq @chk_right
    lda #FACE_LEFT              ; latch facing to the held direction (turn even vs a wall)
    sta facing
    ldx #$FFFF                  ; dx = -1 tile
    ldy #$0000
    jsr try_start_step
    lda step_active
    bne @apply                ; LEFT started a slide -> done (else try next axis)
@chk_right:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq @chk_up
    lda #FACE_RIGHT            ; latch facing RIGHT
    sta facing
    ldx #$0001
    ldy #$0000
    jsr try_start_step
    lda step_active
    bne @apply                ; RIGHT started -> done
@chk_up:
    .a16
    lda JOY1_CURRENT
    bit #JOY_UP
    beq @chk_down
    lda #FACE_UP               ; latch facing UP
    sta facing
    ldx #$0000
    ldy #$FFFF
    jsr try_start_step
    lda step_active
    bne @apply                ; UP started -> done
@chk_down:
    .a16
    lda JOY1_CURRENT
    bit #JOY_DOWN
    beq @apply
    lda #FACE_DOWN             ; latch facing DOWN
    sta facing
    ldx #$0000
    ldy #$0001
    jsr try_start_step
@apply:
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
; draw_avatar — draw Elnora (OAM slot 0, 16x16, OBJ palette 0) at screen centre;
; the world scrolls under her (camera-follows-player). Her FACING (latched from
; the last d-pad direction) selects one of the authored sprites: DOWN (tile 16),
; UP (18), or the RIGHT profile (20); LEFT reuses tile 20 H-FLIPPED via the OAM
; attribute bit (av_attr bit 6). A subtle WALK BOB hops the sprite 1px on a
; 2-frame cadence WHILE a slide is in progress (per facing — the Y hop is
; facing-independent), so she looks like she's stepping; she rests flat at AV_Y0
; when idle (the tests read OAM slot 0 at rest, so the idle Y stays exactly AV_Y0).
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; the bob branch + facing LUT lookup stay A16/I16;
; spr/spr_clear run their own widths and return A16/I16.
; =============================================================================
draw_avatar:
    .a16
    .i16
    spr_clear
    ldx #AV_Y0                  ; default screen Y (flat — idle stands still)
    lda step_active
    beq @have_y                 ; not sliding -> no bob
    lda FRAME_COUNTER
    and #$0002                  ; bit 1 toggles every 2 frames (the bob cadence)
    beq @have_y                 ; down-phase -> flat
    ldx #(AV_Y0 - 1)            ; up-phase -> hop the avatar 1px while it walks
@have_y:
    .a16                        ; branch target: A16/I16, X holds the screen Y
    stx av_y                    ; Y committed; X is now free for the facing index
    ; --- resolve facing -> (tile, attr) via word LUTs (X = facing*2 word index) ---
    ; WIDTH-RISK: A16/I16 throughout; `tax` transfers the full 16-bit index (A is
    ; A16 here, high byte cleared by the and #$00FF), so no stale-high-byte hazard.
    lda facing
    and #$00FF                  ; defensively keep the facing code in 0..3
    asl a                       ; *2 -> word index into the LUTs
    tax
    lda f:face_tile_lut, x      ; OAM base tile for this facing
    sta av_tile
    lda f:face_attr_lut, x      ; OAM attribute flags (bit6 H-flip for LEFT, else 0)
    sta av_attr
    spr av_tile, #AV_X0, av_y, av_attr, #2   ; OBJ palette 0, priority 2, 16x16
    rts

; --- facing (FACE_*) -> OAM base tile + attribute flags. 16x16 sprite (size bit
;     CLEAR): DOWN/UP/RIGHT draw unflipped ($0000); LEFT reuses the RIGHT profile
;     CHR H-FLIPPED ($0040 = attr bit 6) so Elnora's staff leads on the left. -----
face_tile_lut:
    .word AVATAR_TILE_DOWN      ; FACE_DOWN  -> 16 {16,17,32,33}
    .word AVATAR_TILE_UP        ; FACE_UP    -> 18 {18,19,34,35}
    .word AVATAR_TILE_SIDE      ; FACE_LEFT  -> 20 (H-flipped)
    .word AVATAR_TILE_SIDE      ; FACE_RIGHT -> 20 {20,21,36,37}
face_attr_lut:
    .word $0000                 ; FACE_DOWN  — 16x16, no flip, palette 0
    .word $0000                 ; FACE_UP
    .word $0040                 ; FACE_LEFT  — H-flip (OAM attr bit 6)
    .word $0000                 ; FACE_RIGHT

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
    bcc @blocked             ; tx < MIN -> reject
    cmp #(CLAMP_TX_MAX + 1)
    bcs @blocked             ; tx > MAX -> reject
    lda tgt_ty
    cmp #CLAMP_TY_MIN
    bcc @blocked
    cmp #(CLAMP_TY_MAX + 1)
    bcs @blocked
    ; --- world-space collision lookup: terrain = collision[ty*256 + tx] -------
    jsr terr_at_world           ; A8 terrain id on return? -> A16 zero-extended
    cmp #TERR_BLOCKED_MIN
    bcc @walkable            ; id < MIN -> walkable
    cmp #(TERR_BLOCKED_MAX + 1)
    bcs @walkable            ; id > MAX -> walkable
@blocked:
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
@walkable:
    .a16
    ; arm the slide: step_dx/step_dy already hold the per-frame px deltas
    lda #STEP_FRAMES
    sta step_remain
    lda #1
    sta step_active
    rts

; =============================================================================
; terr_at_world — return the WORLD-SPACE terrain CLASS of tile (tgt_tx, tgt_ty)
; in A (zero-extended to A16).  Collision reads the SAME FLAT ROM tilemap byte the
; streaming engine reads (a tile id), then LUTs it through the 256-entry
; tile_terrain_lut to a terrain class.  NO separate collision table (a 512x512
; byte collision table would push the ROM past 512 KB).
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
; boot_fade — dawn the overworld in from black at power-on: ramp INIDISP
; brightness 0 -> 15 over the first ~30 frames (FRAME_COUNTER / 2, clamped), so
; the boot is a gentle attract fade rather than a hard snap into gameplay. The
; NMI commits SHADOW_INIDISP to $2100 each frame, so writing the shadow is all
; this needs. A no-op once full brightness is reached (the common case).
; Entry/Exit: A16/I16. Clobbers A.
; WIDTH-RISK: A16/I16 entry; toggles A8 for the 1-byte INIDISP shadow (an 8-bit
; PPU-shadow field), restores A16 before rts.
; =============================================================================
boot_fade:
    .a16
    .i16
    sep #$20
    .a8
    lda SHADOW_INIDISP
    cmp #$0F
    beq @done                   ; already full brightness -> nothing to do
    lda FRAME_COUNTER           ; low byte (the fade finishes long before it wraps)
    lsr a                       ; brightness = frame / 2 (full at ~frame 30)
    cmp #$0F
    bcc @store
    lda #$0F                    ; clamp to full brightness
@store:
    .a8                         ; branch target: still 8-bit for the shadow store
    sta SHADOW_INIDISP          ; NMI commits this to INIDISP ($2100) in VBlank
@done:
    .a8                         ; branch target: 8-bit; restore A16 for the caller
    rep #$30
    .a16
    .i16
    rts

; =============================================================================
; check_town_entry — after a grid slide lands, if the camera tile is the authored
; demo house (terrain class TERR_TOWN_ENTER) arm the mosaic wipe into the Mode 1
; town interior. ONLY the demo house carries TERR_TOWN_ENTER — the decorative
; 32-tile lattice houses are TERR_TOWN — so a streaming sweep crossing a lattice
; house never warps. Entry/Exit: A16/I16. Clobbers A, X, Y, tgt_tx/ty, col_*.
; WIDTH-RISK: A16/I16 entry; terr_at_world toggles A8 internally and restores A16.
; =============================================================================
check_town_entry:
    .a16
    .i16
    lda cam_px
    lsr a
    lsr a
    lsr a                       ; camera tile X = cam_px / 8
    sta tgt_tx
    lda cam_py
    lsr a
    lsr a
    lsr a
    sta tgt_ty
    jsr terr_at_world           ; A = terrain class (A16, high byte 0)
    cmp #TERR_TOWN_ENTER
    bne @no
    sf_mosaic_transition_arm #$01, swap_to_town  ; BG1-only mosaic; swap at peak black
@no:
    .a16
    .i16
    rts

; =============================================================================
; swap_to_town — mosaic-wipe swap callback: Mode 7 overworld -> Mode 1 town.
; JSR'd by the stepper at PEAK BLACK (A8/I16 entry). Under one forced-blank
; bracket: save the live camera, halt streaming (so the NMI can't touch the
; PRESERVED Mode 7 image at $0000-$3FFF), switch to Mode 1 with BG1 in UPPER VRAM,
; upload the town CHR/palette, draw the room, seed the player. Ends A8/I16
; re-darkened so the IN ramp brightens from black.
; WIDTH-RISK: A8/I16 entry; rep to A16 for the work; sf_blank_enter/exit + the
; upload helpers manage their own widths and exit A16; ends A8 (re-darken + rts).
; =============================================================================
swap_to_town:
    .a8
    .i16
    rep #$30
    .a16
    .i16
    lda cam_px                  ; save the overworld camera for restore-on-exit
    sta ovw_camx
    lda cam_py
    sta ovw_camy
    stz step_active             ; drop any grid-slide state (overworld resumes at rest)
    stz step_remain
    ; zero the streaming leading-edge counts so the NMI's Mode 7 tilemap DMA
    ; can't fire while we are in Mode 1 (long-indexed store: DB=$00 needs a 24-bit addr)
    ldx #0
    lda #0
    sta f:$7E0000 + M7S_ROW_COUNT, x
    sta f:$7E0000 + M7S_COL_COUNT, x
    sf_blank_enter              ; forced blank + NMI mask for the discontinuous rebuild
    sep #$20
    .a8
    lda #$01
    sta REG_BGMODE              ; BGMODE = 1 (immediate, under blank)
    sta SHADOW_BGMODE           ; ...and the shadow the NMI re-commits each frame
    lda #TOWN_BG1SC_VAL
    sta REG_BG1SC               ; BG1 tilemap base word $5800, 32x32
    lda #TOWN_BG12NBA_VAL
    sta REG_BG12NBA             ; BG1 CHR base word $5000
    rep #$30
    .a16
    .i16
    jsr upload_town_chr         ; town BG1 CHR -> VRAM word $5000 (under blank)
    jsr upload_town_pal         ; town interior palette -> CGRAM 0..15
    jsr build_town_vram         ; draw the room tilemap directly -> VRAM word $5800
    sep #$20
    .a8
    lda #$11
    sta REG_TM                  ; main screen: BG1 (Mode 1) + OBJ
    sta SHADOW_TM
    rep #$30
    .a16
    .i16
    stz SHADOW_BG1HOFS          ; town camera fixed at scroll 0 (NMI commits it)
    stz SHADOW_BG1VOFS
    lda #TOWN_SPAWN_TX          ; seed the town player + facing
    sta town_px
    lda #TOWN_SPAWN_TY
    sta town_py
    lda #FACE_UP
    sta town_facing
    lda #1
    sta scene_id                ; dispatch town_tick from next frame
    jsr draw_town_avatar        ; place OAM 0 so the first (dark) IN frame is correct
    sf_blank_exit               ; drop forced blank + re-enable NMI
    sep #$20                    ; re-darken: IN ramp starts from black (matches rpg swap)
    .a8
    lda SHADOW_INIDISP
    and #$F0                    ; keep blank/high bits, brightness nibble -> 0
    sta SHADOW_INIDISP
    sta $2100                   ; commit now so this frame is black (no bright flash)
    rts                         ; A8/I16 -> stepper resumes

; =============================================================================
; swap_to_overworld — mosaic-wipe swap callback: Mode 1 town -> Mode 7 overworld.
; JSR'd at PEAK BLACK (A8/I16). Under one forced-blank bracket: restore the Mode 7
; PPU registers (BGMODE 7, identity affine, WRAP), re-stage the world palette (the
; town clobbered CGRAM 0..11), restore the SAVED camera + scroll. The Mode 7
; tilemap image ($0000-$3FFF) was PRESERVED across the visit, so NO re-stream is
; needed — the window is byte-identical to how it was left (the mosaic-out masks
; even the palette re-stage). Ends A8/I16 re-darkened.
; WIDTH-RISK: A8/I16 entry; rep to A16 for the work; ends A8 (re-darken + rts).
; =============================================================================
swap_to_overworld:
    .a8
    .i16
    rep #$30
    .a16
    .i16
    sf_blank_enter
    sep #$20
    .a8
    lda #$07
    sta REG_BGMODE              ; BGMODE = 7
    sta SHADOW_BGMODE
    stz REG_M7SEL               ; M7SEL = $00 (WRAP)
    lda #$00                    ; identity affine A=$0100 B=0 C=0 D=$0100
    sta REG_M7A
    lda #$01
    sta REG_M7A
    lda #$00
    sta REG_M7B
    sta REG_M7B
    sta REG_M7C
    sta REG_M7C
    sta REG_M7D
    lda #$01
    sta REG_M7D
    stz REG_M7X                 ; centre = 0
    stz REG_M7X
    stz REG_M7Y
    stz REG_M7Y
    lda #$11
    sta REG_TM                  ; BG1 (Mode 7) + OBJ
    sta SHADOW_TM
    rep #$30
    .a16
    .i16
    jsr restage_world_pal       ; Mode 7 world palette -> CGRAM 0.. (town overwrote 0..15)
    lda ovw_camx               ; restore the saved overworld camera
    sta cam_px
    lda ovw_camy
    sta cam_py
    lda #0
    sta scene_id                ; back to the overworld dispatch
    jsr apply_camera            ; pan the Mode 7 view to the saved camera
    sf_mode7_stream_set_cam cam_px, cam_py  ; sync the streamer's camera tile
    jsr draw_avatar             ; screen-centred overworld avatar
    sf_blank_exit
    sep #$20                    ; re-darken so the IN ramp brightens from black
    .a8
    lda SHADOW_INIDISP
    and #$F0
    sta SHADOW_INIDISP
    sta $2100
    rts

; =============================================================================
; upload_town_chr — copy the town BG1 CHR blob (TOWN_CHR_BYTES) to VRAM word
; $5000 (above the preserved Mode 7 image + the avatar OBJ CHR at $4000). CPU word
; writes; call under forced blank. Entry/Exit A16/I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 entry; A8 only for the VMAIN byte; restored A16.
; =============================================================================
upload_town_chr:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after high byte
    rep #$30
    .a16
    .i16
    lda #TOWN_CHR_VWORD
    sta $2116                   ; VMADD = $5000
    ldx #0
@lp:
    .a16                        ; loop body: A16/I16
    lda f:town_chr, x
    sta $2118                   ; VMDATA word; VMADD++
    inx
    inx
    cpx #TOWN_CHR_BYTES
    bne @lp
    rts

; =============================================================================
; upload_town_pal — town interior palette (TOWN_PAL_COUNT colours) -> CGRAM 0..15
; (BG palette 0; overwrites the Mode 7 world colours, re-staged on return). Colour
; 0 = the floor base, also the backdrop, so tile gaps read as floor. Under blank.
; Entry/Exit A16/I16. Clobbers A, X. WIDTH-RISK: A16/I16 entry; A8 for the CGDATA
; byte writes with I16 index; A16 exit.
; =============================================================================
upload_town_pal:
    .a16
    .i16
    sep #$20
    .a8
    stz $2121                   ; CGADD = 0
    ldx #0
@lp:
    .a8                         ; loop body: A8/I16
    lda f:town_pal, x
    sta $2122                   ; CGDATA byte (low then high auto-pair)
    inx
    cpx #(TOWN_PAL_COUNT * 2)
    bne @lp
    rep #$20
    .a16
    rts

; =============================================================================
; restage_world_pal — re-upload the Mode 7 world palette to CGRAM 0.. (the town
; interior palette overwrote CGRAM 0..15). Mirrors the boot palette upload. Under
; blank. Entry/Exit A16/I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 entry; A8 for the CGDATA byte writes; A16 exit.
; =============================================================================
restage_world_pal:
    .a16
    .i16
    sep #$20
    .a8
    stz $2121                   ; CGADD = 0
    ldx #0
@lp:
    .a8                         ; loop body: A8/I16
    lda f:world_palette, x
    sta $2122
    inx
    cpx #(WORLD_PAL_COUNT * 2)
    bne @lp
    rep #$20
    .a16
    rts

; =============================================================================
; build_town_vram — draw the town room tilemap DIRECTLY into VRAM word $5800 (BG1
; tilemap). 32x32 cells; each cell's CLASS (town_classify) IS its BG1 tile id
; (palette 0). Written directly (not via the BG shadow/mset), so it needs no
; BG_TILEMAP_DIRTY — the rail never arms the NMI tilemap DMA, so this map is never
; clobbered. Call under forced blank. Entry/Exit A16/I16. Clobbers A, X, Y,
; town_ctx, town_cty.
; WIDTH-RISK: A16/I16 entry; A8 only for the VMAIN byte; the loop stays A16/I16.
; =============================================================================
build_town_vram:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after high byte
    rep #$30
    .a16
    .i16
    lda #TOWN_MAP_VWORD
    sta $2116                   ; VMADD = $5800
    stz town_cty                ; row ty = 0
@rows:
    .a16
    stz town_ctx                ; col tx = 0
@cols:
    .a16
    jsr town_classify           ; A = class (== BG1 tile id) for (town_ctx, town_cty)
    sta $2118                   ; write tilemap word (palette 0, no flip); VMADD++
    lda town_ctx
    inc a
    sta town_ctx
    cmp #32
    bne @cols
    lda town_cty
    inc a
    sta town_cty
    cmp #32
    bne @rows
    rts

; =============================================================================
; town_classify — classify town cell (town_ctx, town_cty) -> class in A (A16,
; high byte 0). The room geometry (walls / door / table) is the SINGLE SOURCE OF
; TRUTH for BOTH the rendered tilemap AND collision. FLOOR=0 WALL=1 DOOR=2 TABLE=3.
; Reads town_ctx/town_cty (unchanged). Entry/Exit A16/I16. Clobbers A.
; WIDTH-RISK: A16/I16 throughout — pure 16-bit compares + immediate loads.
; =============================================================================
town_classify:
    .a16
    .i16
    lda town_ctx                ; the door sits IN the bottom wall — test it first
    cmp #TOWN_DOOR_TX
    bne @not_door
    lda town_cty
    cmp #TOWN_DOOR_TY
    bne @not_door
    lda #TOWN_CLS_DOOR
    rts
@not_door:
    .a16
    lda town_ctx                ; outside the room rectangle -> wall
    cmp #TOWN_ROOM_X0
    bcc @wall
    cmp #(TOWN_ROOM_X1 + 1)
    bcs @wall
    lda town_cty
    cmp #TOWN_ROOM_Y0
    bcc @wall
    cmp #(TOWN_ROOM_Y1 + 1)
    bcs @wall
    lda town_ctx                ; on the room border -> wall
    cmp #TOWN_ROOM_X0
    beq @wall
    cmp #TOWN_ROOM_X1
    beq @wall
    lda town_cty
    cmp #TOWN_ROOM_Y0
    beq @wall
    cmp #TOWN_ROOM_Y1
    beq @wall
    lda town_ctx                ; the 2x2 table -> table (blocked)
    cmp #TOWN_TABLE_X0
    bcc @floor
    cmp #(TOWN_TABLE_X1 + 1)
    bcs @floor
    lda town_cty
    cmp #TOWN_TABLE_Y0
    bcc @floor
    cmp #(TOWN_TABLE_Y1 + 1)
    bcs @floor
    lda #TOWN_CLS_TABLE
    rts
@floor:
    .a16
    lda #TOWN_CLS_FLOOR
    rts
@wall:
    .a16
    lda #TOWN_CLS_WALL
    rts

; =============================================================================
; town_tick — Mode 1 town per-frame: gate ALL input while a wipe runs (draw only),
; else one grid step per D-pad PRESS (edge latch, first match L,R,U,D). Stepping
; onto the DOOR arms the mosaic wipe back to the overworld. Then draw the avatar.
; Entry/Exit A16/I16. WIDTH-RISK: A16/I16 entry; town_try_step stays A16.
; =============================================================================
town_tick:
    .a16
    .i16
    sf_mosaic_transition_active ; gate input during the wipe (entering OR leaving)
    bne @draw
    lda JOY1_PRESSED_LATCH
    bit #JOY_LEFT
    beq @chk_r
    lda #FACE_LEFT
    sta town_facing
    ldx #$FFFF
    ldy #$0000
    jsr town_try_step
    bra @draw
@chk_r:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_RIGHT
    beq @chk_u
    lda #FACE_RIGHT
    sta town_facing
    ldx #$0001
    ldy #$0000
    jsr town_try_step
    bra @draw
@chk_u:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_UP
    beq @chk_d
    lda #FACE_UP
    sta town_facing
    ldx #$0000
    ldy #$FFFF
    jsr town_try_step
    bra @draw
@chk_d:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_DOWN
    beq @draw
    lda #FACE_DOWN
    sta town_facing
    ldx #$0000
    ldy #$0001
    jsr town_try_step
@draw:
    .a16
    .i16
    jsr draw_town_avatar
    rts

; =============================================================================
; town_try_step — attempt a one-tile town move by (X=dx, Y=dy signed). Walkable
; (FLOOR/DOOR) commits the move; the DOOR also arms the mosaic wipe back to the
; overworld. WALL/TABLE reject. Entry: A16/I16, X=dx, Y=dy. Exit A16/I16.
; Clobbers A, X, Y, town_ctx/cty. WIDTH-RISK: A16/I16 throughout.
; =============================================================================
town_try_step:
    .a16
    .i16
    txa
    clc
    adc town_px
    sta town_ctx                ; destination tile X
    tya
    clc
    adc town_py
    sta town_cty                ; destination tile Y
    jsr town_classify           ; A = class of the destination cell
    cmp #TOWN_CLS_WALL
    beq @blocked
    cmp #TOWN_CLS_TABLE
    beq @blocked
    lda town_ctx                ; walkable -> commit the move
    sta town_px
    lda town_cty
    sta town_py
    jsr town_classify           ; re-read (town_ctx/cty unchanged): is it the DOOR?
    cmp #TOWN_CLS_DOOR
    bne @done
    sf_mosaic_transition_arm #$01, swap_to_overworld
@done:
    .a16
    rts
@blocked:
    .a16
    rts

; =============================================================================
; draw_town_avatar — draw Elnora (OAM 0, 16x16) at her TOWN tile (town_px*8,
; town_py*8); the town camera is fixed so the SPRITE moves. Facing selects the
; same authored sprites via the shared face_*_lut. Entry/Exit A16/I16.
; Clobbers A, X, Y, town_ctx, town_cty, av_tile, av_attr.
; WIDTH-RISK: A16/I16 entry; the facing tax runs A16 (and #$00FF clears the high
; byte first); spr/spr_clear run their own widths and return A16.
; =============================================================================
draw_town_avatar:
    .a16
    .i16
    spr_clear
    lda town_px
    asl a
    asl a
    asl a                       ; screen X = town_px * 8
    sta town_ctx
    lda town_py
    asl a
    asl a
    asl a                       ; screen Y = town_py * 8
    sta town_cty
    lda town_facing
    and #$00FF                  ; keep facing 0..3 (clears high byte for tax)
    asl a                       ; *2 -> word LUT index
    tax
    lda f:face_tile_lut, x      ; OAM base tile for this facing
    sta av_tile
    lda f:face_attr_lut, x      ; OAM attribute flags (bit6 H-flip for LEFT)
    sta av_attr
    spr av_tile, town_ctx, town_cty, av_attr, #2   ; OBJ palette 0, priority 2, 16x16
    rts

; =============================================================================
; Engine includes — the subroutine bodies the boot + loop above call into. The
; Mode 7 streamer needs its partners present: input (reads the pad), sprite (the
; avatar OAM), the DMA scheduler + BG engine (the streamer queues its VRAM writes
; and scroll commits through them), then the Mode 7 math/HDMA/engine whose sine +
; Z-reciprocal LUTs the linker resolves. We drive a plain static affine above, so
; the Mode 7 PERSPECTIVE machinery is linked but never called.
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
.include "tad_bridge.asm"        ; tad_* entry points the sf_audio macros call
                                 ;   (the TAD driver + song blob link as separate
                                 ;   objects, pulled in by the *_tad*.cfg build rule)
; the mosaic scene-wipe curves + stepper (the emitted half of sf_mosaic_transition
; .inc): the town-visit dissolve. Included ONCE, in CODE, next to the engine .asm.
.include "sf_mosaic_transition_data.inc"

; --- BANK1: the 32KB interleaved Mode 7 seed (initial 128x128 window) --------
; .incbin resolves relative to THIS file's dir, so "assets/<basename>" is
; copy-safe (copying templates/mode7_explore/ -> templates/<theme>/ only needs
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
