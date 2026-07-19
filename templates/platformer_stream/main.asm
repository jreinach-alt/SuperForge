; =============================================================================
; platformer_stream — a PLAYABLE Mode 1 platformer on the 2-axis BG1 streaming
;                      substrate (a large-world streaming rail).
; =============================================================================
; A side-view platformer where the player runs / jumps / climbs / falls through
; a believable Four Seasons level several screens WIDE AND TALL (128x128 tiles =
; 1024x1024 px = 4 screens/axis). The level STREAMS seamlessly on BOTH axes as
; the CAMERA (which follows the player) pans — forward, back, up, down, idle —
; with no pop-in / tearing / black bands. World-space collision blocks walls and
; platforms; jump physics (gravity, variable-height jump, landing snap, head
; bump) uses the 16-bit world-Y integrator so the player can span the full
; 1024px-tall level (NOT capped at one 256px screen).
;
; It composes:
;   STREAMING  the 2-axis BG1 substrate (lib/macros/sf_stream.inc over
;              engine/bg_stream.asm + engine/bg_stream_row.asm + the kit NMI
;              STREAM_PENDING / STREAM_ROW_PENDING drains). 64x64 BG1 ring
;              (BG1SC=$5B); cam keyed to the player-follow camera world pos.
;   PHYSICS    sf_physics_step_world (16-bit world-Y) with CALLER-SUPPLIED
;              world-space collision probes (ps_solidprobe / ps_owprobe) reading
;              the ROM-resident row-major collision table by WORLD coordinate —
;              independent of the streamed ring window. Walk is level-checked
;              per axis (tentative X box probe blocks walls).
;   CAMERA     sf_camera_follow (clamps BOTH axes to the 1024x1024 world); the
;              player renders SCREEN-relative (world - camera).
;   ART        Four Seasons CC0 tileset (level_chr.bin) + a 16x16 hero sprite.
;   BACKDROP   a dusk sky colour on the backdrop so open sky never reads as an
;              unfinished black screen.
;
; The BG_TILEMAP_DIRTY disown is BAKED INTO sf_stream_init — this ROM does NOT
; carry the manual disown step.
;
; Controls:
;   D-pad left/right   walk          A   jump (hold for a higher jump)
;   Forward is NOT automatic (this is a normal platformer); at boot you spawn in
;   an air shaft and gravity alone carries you ~5 screens down to the floor.
;
; File layout (top to bottom; the major === section banners):
;   INIT             — RESET: uploads, arm both stream axes, dusk gradient, spawn
;   MAIN LOOP        — game_loop, the once-per-frame heartbeat (read this first)
;   PER-FRAME UPDATE — game_tick: walk, jump, physics, camera, stream, draw
;   SUBROUTINES      — world-space collision probes + the debug mirror
;   DATA             — engine includes, hero art, and the level / collision blobs
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; This rail boots straight into gameplay — streaming rails have no title screen
; by design, and the default `make platformer_stream` build is fully playable.
; The level is authored by tools/level_pipeline_bg.py (--seasons --tall); the
; 2-axis streaming design is documented in docs/guides/normal_bg_streaming.md.
;
; Build:  make platformer_stream
; LDCFG: lorom_stream.cfg
;   ^ 512KB LoROM: BANK1 column-major level, BANK2 row-major level, BANK3 CHR,
;     BANK4 world-space collision table. The generic build/%.sfc rule reads
;     this sentinel. Assembled with -D BG_STREAM_2AXIS (see the Makefile rule).
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SEASON RUNNER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"
.include "sf_frame.inc"
.include "sf_bg.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"
.include "sf_anim.inc"
.include "sf_camera.inc"        ; sf_camera_follow (clamps BOTH axes)
.include "sf_physics.inc"       ; sf_physics_step_world (16-bit world-Y)
.include "sf_stream.inc"        ; 2-axis streaming front door
.include "sf_fx.inc"            ; dusk-sky RGB gradient + color math (backdrop)
.include "engine_state.inc"
.include "bg_stream_world.inc"  ; BGW_* world geometry + bgw_palette

; --- world geometry (matches the 128x128 --tall level) -----------------------
WORLD_W_PX = BGW_WORLD_W_TILES * 8      ; 1024
WORLD_H_PX = BGW_WORLD_H_TILES * 8      ; 1024
CAMX_MAX   = WORLD_W_PX - 256           ; 768
CAMY_MAX   = WORLD_H_PX - 224           ; 800

; --- spawn: HIGH, over the open fall-shaft (cols 15..19 metatile = world px
;     240..319). The believable Four Seasons level (level_pipeline_bg.py
;     --seasons) opens a deep air column from the left plateau (top row 8 =
;     world y 128) straight down to the bedrock floor (top row 120 = world
;     y 960). The player spawns in the shaft MOUTH and GRAVITY alone carries
;     it down ~5 screens to the floor — the deterministic down-axis streaming
;     test needs no scripted input. PYF is the box-BOTTOM (feet) world px.
SPAWN_X = 272                           ; world px box-left (metatile col 17, in shaft)
SPAWN_Y = 136                           ; world px feet Y (airborne in the shaft mouth;
                                        ;   falls to the floor at feet=959)
; sky colour (dusk) on the backdrop so open sky isn't black. The dusk RGB
; HDMA gradient (see RESET) paints the believable sky; this is the floor of
; the ramp so even an un-gradiented frame is a warm dusk, never bare black.
SKY_DUSK = $2C68                        ; warm dusk blue/purple

; --- dusk-sky RGB gradient (mirrors the kit platformer's dusk-sky LOOK) ------
; The gradient drives the PPU FIXED COLOR ($2132) per scanline on 3 HDMA
; channels (CH3=R, CH4=G, CH5=B); color math ADDs it on the BACKDROP ONLY, so
; every open-sky pixel ramps from a warm orange dusk at the top to a deep
; blue-purple at the bottom — a believable sunset behind the level, not bare
; purple. 5-bit intensities (0-31). Static (no phase) so a standing-still
; frame is byte-identical (the streaming/fall freeze invariant includes sky).
DUSK_TOP_R = 24                         ; warm orange top of the ramp
DUSK_TOP_G = 8
DUSK_TOP_B = 2
DUSK_BOT_R = 2                          ; deep blue-purple bottom
DUSK_BOT_G = 0
DUSK_BOT_B = 12

; --- OBJ VRAM ---
HERO_BASE = 0                           ; 4 frames @ 16x16 -> tiles 0-15

; --- DP game state ($32-$5F; kit contract) -----------------------------------
PX       = $32                  ; player world X (px, 16-bit) — left of 8x8 box
PYF      = $34                  ; player world Y (px, 16-bit integer) — box top
PYSUB    = $36                  ; player Y subpixel (8.8 fraction, low byte used)
VY       = $38                  ; signed velocity (8.8 px/frame; negative = up)
NEWY     = $3A                  ; physics scratch: probe row handed to the probes
GROUNDED = $3C                  ; out: 1 standing / 0 airborne
CAMX     = $3E                  ; follow-camera world X (px)
CAMY     = $40                  ; follow-camera world Y (px)
FACING   = $42                  ; 0 right / 1 left
ATICK    = $44                  ; anim clock
AFRAME   = $46                  ; anim frame
PIXX     = $48                  ; player SCREEN X (px)  — draw scratch
PIXY     = $4A                  ; player SCREEN Y (px)  — draw scratch
TENTX    = $4C                  ; tentative world X for the walk box probe
PROBECOL = $4E                  ; collision probe: tile column scratch
PROBEROW = $50                  ; collision probe: tile row scratch
SCRATCH  = $52                  ; transient
LONGPTR  = $54                  ; 24-bit collision-table pointer (3 bytes: $54-$56)

; --- debug region offsets (relative to $7E:E000) -----------------------------
DBG_HEARTBEAT = $E010
DBG_PX        = $E012
DBG_PYF       = $E014
DBG_VY        = $E016
DBG_GROUNDED  = $E018
DBG_CAMX      = $E01A
DBG_CAMY      = $E01C
DBG_FACING    = $E01E
DBG_PYSUB     = $E020

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, streaming, spawn)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

; =============================================================================
RESET:
    sf_coldstart
    sf_engine_init

    ; --- HDMA channel allocator: reserve CH0/CH1 (bulk-DMA), free CH2..CH7 ---
    ; MUST run before sf_stream_init so the streaming column producer requests
    ; its channel (CH2) through the initialized allocator, leaving CH3..CH5 for
    ; the dusk-sky RGB gradient below. Without this, hdma_request runs against
    ; an un-bootstrapped allocator and the gradient's 3-channel grab could
    ; collide with streaming's channel.
    jsr hdma_alloc_init

    gfxmode #1

    ; --- forced blank for the boot uploads + register writes -----------------
    ; (.a8/.a16 + .i8/.i16 track the CPU's register width for ca65: the 65816
    ;  switches between 8- and 16-bit registers, and the assembler must match the
    ;  CPU so it sizes immediates right — the first of many width blocks here.)
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; INIDISP (display control): force blank (bit 7)
                                ;   so the VRAM/CGRAM uploads below are PPU-safe
    rep #$30
    .a16
    .i16

    ; --- BG1 level art: Four Seasons CHR + palette ---------------------------
    sf_load_bg_chr 0, level_chr, BGW_CHR_BYTES
    sf_load_bg_pals 0, bgw_palette, 1

    ; --- dusk backdrop colour (CGRAM entry 0) so open sky isn't black --------
    sf_bg_color 0, 0, SKY_DUSK

    ; --- hero OBJ sprite -----------------------------------------------------
    sf_load_obj_chr HERO_BASE, hero_chr, hero_chr_bytes
    sf_load_obj_pal 0, hero_pal

    ; --- BG1 -> 64x64 hardware tilemap @ VRAM word $5800 (BG1SC=$5B) ----------
    sep #$20
    .a8
    lda #$5B
    sta $2107                   ; BG1SC: base word $5800, size 64x64
    lda #$11
    sta $212C                   ; TM = OBJ + BG1
    sta SHADOW_TM
    stz $212D                   ; TS = 0
    rep #$30
    .a16
    .i16

    ; --- arm BOTH streaming axes (column producer first, then row) -----------
    ; sf_stream_init now BAKES IN the BG_TILEMAP_DIRTY disown, so this ROM does
    ; NOT need the manual `stz BG_TILEMAP_DIRTY` step.
    sf_stream_init     level_flat,     #BGW_WORLD_W_TILES
    sf_stream_row_init level_flat_row, #BGW_WORLD_H_TILES

    ; --- dusk-sky RGB gradient on the backdrop (CH3..CH5 via the allocator) ---
    ; Streaming has claimed CH2 above; the gradient grabs the next 3 free
    ; channels. Color math ADDs the per-scanline fixed colour on the backdrop
    ; only (CGWSEL=$00 addend, CGADSUB=$20 add-on-backdrop), so open sky shows
    ; the warm-orange -> blue-purple dusk ramp. The stock NMI commits the
    ; CGWSEL/CGADSUB shadows and re-arms HDMAEN every VBlank — no custom VBlank.
    sep #$20
    .a8
    stz SHADOW_CGWSEL               ; fixed colour is the addend
    lda #$20
    sta SHADOW_CGADSUB              ; add on the backdrop
    rep #$30
    .a16
    .i16
    sf_gradient_rgb #DUSK_TOP_R, #DUSK_TOP_G, #DUSK_TOP_B, #DUSK_BOT_R, #DUSK_BOT_G, #DUSK_BOT_B

    ; --- player spawn (16-bit world coords) ----------------------------------
    rep #$30
    .a16
    .i16
    lda #SPAWN_X
    sta PX
    lda #SPAWN_Y
    sta PYF
    stz PYSUB
    stz VY
    stz GROUNDED
    stz FACING
    stz ATICK
    stz AFRAME

    ; --- camera starts following the spawn; seed the streaming cam -----------
    sf_camera_follow PX, PYF, WORLD_W_PX, WORLD_H_PX, CAMX, CAMY
    sf_stream_set_cam2 CAMX, CAMY
    ; commit the initial scroll so the resident ring shows the spawn region
    rep #$30
    .a16
    .i16
    lda CAMX
    sta SHADOW_BG1HOFS
    lda CAMY
    sta SHADOW_BG1VOFS
    sep #$20
    .a8
    lda #$01
    sta BG_SHADOW_REGS_DIRTY
    rep #$30
    .a16
    .i16

    spr_clear

    sf_debug_magic

    ; --- display on + NMI on -------------------------------------------------
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; display on, bright 15
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt + joypad enable): VBlank NMI
                                ;   (bit 7) + auto joypad read (bit 0)
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: the once-per-frame heartbeat (advances the anim clock,
;             runs one game_tick, repeats)
; =============================================================================
game_loop:
    sf_frame_begin

    ; shared anim clock (idle / walk cycle)
    sf_anim_step ATICK, AFRAME, #8, #4

    jsr game_tick

    jmp game_loop

; =============================================================================
; PER-FRAME UPDATE — game_tick: one frame of walk, jump, physics, camera,
;                    stream, draw
; =============================================================================
game_tick:
    .a16
    .i16

    ; ---- walk RIGHT (tentative X, box probe vs solid) -----------------------
    btn #BTN_RIGHT, #0
    bne :+
    jmp gt_no_right
:   rep #$30
    .a16
    .i16
    lda PX
    inc a
    inc a                       ; +2 px/frame
    cmp #(WORLD_W_PX - 8)
    bcc :+
    jmp gt_no_right             ; world right edge -> blocked
:   sta TENTX
    jsr walk_blocked            ; A=1 if the tentative box hits a solid wall
    cmp #$0001
    beq gt_no_right
    lda TENTX
    sta PX
    stz FACING
gt_no_right:
    .a16
    .i16

    ; ---- walk LEFT ----------------------------------------------------------
    btn #BTN_LEFT, #0
    bne :+
    jmp gt_no_left
:   rep #$30
    .a16
    .i16
    lda PX
    cmp #2
    bcs :+
    jmp gt_no_left              ; world left edge
:   dec a
    dec a                       ; -2 px/frame
    sta TENTX
    jsr walk_blocked
    cmp #$0001
    beq gt_no_left
    lda TENTX
    sta PX
    lda #$0001
    sta FACING
gt_no_left:
    .a16
    .i16

    ; ---- jump (grounded-gated) + variable-height cut ------------------------
    btnp #BTN_A, #0
    beq gt_no_jump
    lda GROUNDED
    beq gt_no_jump
    sf_jump VY, GROUNDED
gt_no_jump:
    .a16
    btn #BTN_A, #0
    bne gt_a_held
    sf_jump_cut VY
gt_a_held:
    .a16
    .i16

    ; ---- vertical physics (16-bit world-Y) with world-space collision -------
    sf_physics_step_world PYF, PYSUB, VY, PX, NEWY, GROUNDED, ps_solidprobe, ps_owprobe

    ; ---- camera follow (clamps both axes) + commit BG1 scroll ---------------
    sf_camera_follow PX, PYF, WORLD_W_PX, WORLD_H_PX, CAMX, CAMY
    rep #$30
    .a16
    .i16
    lda CAMX
    sta SHADOW_BG1HOFS
    lda CAMY
    sta SHADOW_BG1VOFS
    sep #$20
    .a8
    lda #$01
    sta BG_SHADOW_REGS_DIRTY
    rep #$30
    .a16
    .i16

    ; ---- 2-axis streaming service (cam keyed to the follow camera) ----------
    sf_stream_set_cam2 CAMX, CAMY
    sf_stream_tick2

    ; ---- draw the player at SCREEN pos (world - camera) ----------------------
    ; PYF is the box BOTTOM (feet) pixel. The 8x8 physics box occupies world
    ; rows [PYF-7..PYF], world cols [PX..PX+7]. The 16x16 hero is centred over
    ; that box: sprite X = (PX - cam_x) - 4 (centre the 16px sprite over the 8px
    ; box), sprite Y (top-left) = (PYF - cam_y) - 15 (feet-align: bottom of the
    ; 16px sprite at the feet pixel).
    rep #$30
    .a16
    .i16
    lda PX
    sec
    sbc CAMX
    sec
    sbc #4
    sta PIXX                    ; sprite X = screen box-left - 4
    lda PYF
    sec
    sbc CAMY
    sec
    sbc #15                     ; sprite top = feet screen Y - 15 (16px tall)
    and #$00FF                  ; sprite Y is 8-bit (screen stays on-screen)
    sta PIXY

    spr_clear
    sf_anim_tile hero_anim_idle, AFRAME
    clc
    adc #HERO_BASE
    sta SCRATCH                 ; tile id (separate slot from the flags below)
    lda #$0080                  ; large (16x16), palette 0
    ldx FACING
    beq :+
    ora #$0040                  ; H-flip when facing left
:   sta PROBECOL                ; flags scratch (free here after physics)
    spr SCRATCH, PIXX, PIXY, PROBECOL, #2

    ; ---- debug mirror -------------------------------------------------------
    jsr debug_mirror

    sf_frame_end
    sf_debug_complete
    rts

; =============================================================================
; SUBROUTINES — the world-space collision probes + the debug mirror
; =============================================================================

; =============================================================================
; world-space collision probes
; =============================================================================
; The collision table (level_collision, BANK4) is 128x128 row-major, 1 byte
; per tile: $01 = solid, $00 = air. Indexed by WORLD tile coordinate, so these
; probes are INDEPENDENT of the streamed 64x64 ring window — true world-space
; collision over the full 1024x1024 level.
;
; col_solid: A16/I16 in; tile_col in PROBECOL, tile_row in PROBEROW; returns
;   A16 = $0001 if that world tile is solid, else $0000. Clobbers A, X, Y.
;   addr = level_collision + tile_row*128 + tile_col.
; RETURNS A16 (not A8) BY DESIGN: callers compare with `cmp #$01` in A16, so the
; assembler's running width matches the CPU's at the compare — no silent-BRK
; from a 3-byte A16 immediate being executed as A8. (A col_solid that exited A8
; while callers stayed A16 was exactly that BRK-class bug during bring-up.)
; WIDTH-RISK: builds a 24-bit pointer in A16, reads the table byte in A8, then
; re-enters A16 and masks to $0000/$0001 (the `and #$00FF` clears the B byte).
col_solid:
    .i16
    rep #$30
    .a16
    .i16
    ; offset = tile_row * 128 + tile_col  (16-bit; max 127*128+127 = 16383)
    lda PROBEROW
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; row << 7 = row * 128
    clc
    adc PROBECOL
    ; 24-bit ptr = level_collision + offset
    clc
    adc #.loword(level_collision)
    sta LONGPTR
    lda #0
    adc #^level_collision       ; bank + any carry out of the low add
    sta LONGPTR+2               ; LONGPTR+2 = bank (high byte of this word ignored)
    ; (offset < 16384 and level_collision is bank-aligned at $xx8000, so the
    ;  low-16 add cannot carry past the bank — but adc folds a carry in anyway.)
    sep #$20
    .a8
    ldy #0
    lda [LONGPTR], y            ; collision byte: $01 solid / $00 air (A8 read)
    and #$01
    rep #$20
    .a16
    and #$00FF                  ; -> $0000 / $0001 in A16 (clears the B byte)
    rts

; ps_solidprobe — sf_physics_step_world's SOLID probe. Entry: NEWY = world
; pixel Y of the probe row (A16/I16, set by the integrator). Tests the player's
; 8px-wide box (world X = PX..PX+7) at that row; returns A=$0001 if EITHER the
; left or right column is solid, else $0000 (the integrator compares cmp #$0001).
; Clobbers A, X, Y. Exits A16 (the integrator reloads its state after the JSR).
; WIDTH-RISK: probes are A8 internally (col_solid), result returned in A16.
ps_solidprobe:
    .a16
    .i16
    ; tile_row = NEWY >> 3
    lda NEWY
    lsr
    lsr
    lsr
    sta PROBEROW
    ; left column = PX >> 3
    lda PX
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid
    cmp #$01
    bne :+
    rep #$20
    .a16
    lda #$0001
    rts
:   rep #$20
    .a16
    ; right column = (PX + 7) >> 3
    lda PX
    clc
    adc #7
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid
    cmp #$01
    bne :+
    rep #$20
    .a16
    lda #$0001
    rts
:   rep #$20
    .a16
    lda #$0000
    rts

; ps_owprobe — one-way (jump-through) platform probe. The authored level marks
; no PLATFORM-only tiles in the collision table (everything solid is fully
; solid), so there are no one-way platforms to land on: this probe always
; returns $0000 (NOT a one-way top). Kept as a real entry point so the world-Y
; integrator's one-way arm is wired and a future level that adds one-way tops
; (a second collision value) extends only this routine. Exits A16.
; WIDTH-RISK: pure A16; no width toggle.
ps_owprobe:
    .a16
    .i16
    rep #$20
    .a16
    lda #$0000
    rts

; walk_blocked — horizontal-walk box probe. Entry: TENTX = tentative world X of
; the box left (A16/I16). PYF is the feet CONTACT line (the integrator rests it
; ON the floor's top pixel, so PYF itself is the standing surface, NOT body).
; The colliding BODY is the 8 px strictly ABOVE the contact line — world rows
; [PYF-8 .. PYF-1]. Tests the box [TENTX..TENTX+7] x [PYF-8..PYF-1] (top + bottom
; body rows, left + right cols) against solid; returns A16 = $0001 if ANY corner
; is solid (a wall), else $0000. Counting the contact line (PYF>>3) as body is a
; subtle trap: the player rests with feet ON the floor row, so PYF>>3 is the
; SOLID floor itself — walking along any floor would read as "blocked into a wall".
; Does NOT touch PX/NEWY. Clobbers A, X, Y. Exits A16.
; WIDTH-RISK: A16 wrapper around the A8 col_solid reads (col_solid returns A16).
walk_blocked:
    .a16
    .i16
    ; rows: top = (PYF-8)>>3, bottom = (PYF-1)>>3  (body is the 8px above feet)
    ; cols: left = TENTX>>3, right = (TENTX+7)>>3
    ; --- top-left ---
    lda PYF
    sec
    sbc #8
    lsr
    lsr
    lsr
    sta PROBEROW
    lda TENTX
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid
    cmp #$01
    bne :+
    rep #$20
    .a16
    lda #$0001
    rts
:   ; --- top-right ---
    rep #$20
    .a16
    lda TENTX
    clc
    adc #7
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid               ; PROBEROW still = top row
    cmp #$01
    bne :+
    rep #$20
    .a16
    lda #$0001
    rts
:   ; --- bottom body row (PYF-1)>>3 (just above the feet contact line) ---
    rep #$20
    .a16
    lda PYF
    dec a
    lsr
    lsr
    lsr
    sta PROBEROW
    ; bottom-left
    lda TENTX
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid
    cmp #$01
    bne :+
    rep #$20
    .a16
    lda #$0001
    rts
:   ; bottom-right (the last corner; air here = the whole box is clear)
    rep #$20
    .a16
    lda TENTX
    clc
    adc #7
    lsr
    lsr
    lsr
    sta PROBECOL
    jsr col_solid
    cmp #$01
    bne :+                      ; BR air -> all four corners clear -> not blocked
    rep #$20
    .a16
    lda #$0001                  ; BR solid -> blocked
    rts
:   rep #$20
    .a16
    lda #$0000                  ; all clear -> walk allowed
    rts

; =============================================================================
; debug_mirror — publish player/camera state to the debug region for the test.
; =============================================================================
debug_mirror:
    rep #$30
    .a16
    .i16
    lda FRAME_COUNTER
    ldx #0
    sta f:$7E0000 + DBG_HEARTBEAT, x
    lda PX
    ldx #0
    sta f:$7E0000 + DBG_PX, x
    lda PYF
    ldx #0
    sta f:$7E0000 + DBG_PYF, x
    lda VY
    ldx #0
    sta f:$7E0000 + DBG_VY, x
    lda GROUNDED
    ldx #0
    sta f:$7E0000 + DBG_GROUNDED, x
    lda CAMX
    ldx #0
    sta f:$7E0000 + DBG_CAMX, x
    lda CAMY
    ldx #0
    sta f:$7E0000 + DBG_CAMY, x
    lda FACING
    ldx #0
    sta f:$7E0000 + DBG_FACING, x
    lda PYSUB
    ldx #0
    sta f:$7E0000 + DBG_PYSUB, x
    rts

; =============================================================================
; DATA — engine includes (streaming producers + rendering closure), the hero
;        art, and the level / CHR / collision blobs (BANK1-4)
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"       ; hdma_request + _hdma_enable_channel (gradient dep)
.include "hdma_color_engine.asm" ; dusk-sky RGB gradient builder (MUST follow hdma_engine)
.include "colormath_engine.asm"  ; CGWSEL/CGADSUB/COLDATA shadows (backdrop add)
.include "bg_stream.asm"         ; horizontal column producer (BG_STREAM_2AXIS)
.include "bg_stream_row.asm"     ; vertical row producer

; --- converted art (committed png2snes output) ------------------------------
.include "assets/hero.inc"

; --- BANK1: COLUMN-MAJOR flat level (128 cols x 256 B = 32KB) ----------------
.segment "BANK1"
level_flat:
    .incbin "tests/fixtures/platformer_stream/level_flat.bin"

; --- BANK2: ROW-MAJOR flat level (128 rows x 256 B = 32KB) -------------------
.segment "BANK2"
level_flat_row:
    .incbin "tests/fixtures/platformer_stream/level_flat_row.bin"

; --- BANK3: Four Seasons CHR (4bpp BG tiles) --------------------------------
.segment "BANK3"
level_chr:
    .incbin "tests/fixtures/platformer_stream/level_chr.bin"

; --- BANK4: world-space collision table (128x128 row-major, 1 B/tile) -------
.segment "BANK4"
level_collision:
    .incbin "tests/fixtures/platformer_stream/level_collision.bin"
