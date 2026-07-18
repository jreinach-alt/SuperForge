; =============================================================================
; rpg — Mode 7 overworld <-> Mode 1 town/battle (grid movement + collision)
; =============================================================================
; Sprint 1 of the RPG arc: a proper Mode 7 overhead OVERWORLD with grid movement
; and tile collision, built on Sprint 0's scene-transition primitive (which it
; preserves). The overworld is a DESIGNED world (grass/path walkable, water +
; mountain BLOCKED, a town-entrance landmark). The avatar stays at screen center
; (OAM 0); the D-pad scrolls the Mode 7 camera under it ONE tile (8 px) per
; press, animated over 8 frames. A press into a BLOCKED tile is rejected via a
; PARALLEL collision table (assets/ovw_collision.inc) — no per-frame VRAM reads.
; NPCs, dialog, encounters, menus, and saves are LATER sprints.
;
; The Mode 7<->Mode 1 swap (Sprint 0's net-new brick) is UNCHANGED and still
; round-trips: A -> TOWN, START -> BATTLE, A returns; the saved camera now
; reflects the player's WALKED grid position (correct/desirable).
;
; THREE SCENES (sf_scene, dense ids from 0):
;   SC_OVERWORLD = 0   Mode 7 flat-overhead world; D-pad grid-walks the camera
;   SC_TOWN      = 1   Mode 1 flat tilemap (cobble/brick/water/torch)
;   SC_BATTLE    = 2   Mode 1, a near-clone of TOWN with a distinct backdrop
;
; THE SWAP (the net-new brick): sf_scene is a SOFT restart — CHR/palettes/BGMODE
; persist across a goto, so a Mode 7<->Mode 1 switch is net-new glue inside the
; destination scene's init, bracketed by a forced blank (sf_scene_mode.inc):
;   Mode 7 -> Mode 1 (town/battle): SAVE the overworld camera first, then
;     blank_enter -> mode7_off -> gfxmode #1 -> RE-RAISE blank (gfxmode turns
;     the screen back on) -> upload Mode 1 CHR/pals -> mset the tilemap ->
;     blank_exit.
;   Mode 1 -> Mode 7 (overworld return): blank_enter -> load_map under blank ->
;     re-upload Mode 7 CGRAM -> mode7_on -> perspective/focus/cam with the SAVED
;     camera -> mode7_tick once -> blank_exit.
;
; keep_music: TAD survives a soft swap; persist = call nothing in a scene init,
; keep sf_audio_tick in the spine. NEVER sf_audio_init / sf_coldstart in a scene
; init (soft-restart contract).
;
; Build: make rpg   (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad_m7_sram.cfg
;   ^ Linker-config sentinel (GAP-2): the generic build/%.sfc rule reads this
;     line and links this template with lorom_tad_m7_sram.cfg — TAD audio banks
;     (keep_music) + a dedicated BANK1 for the 32KB interleaved Mode 7 map + the
;     battery-SRAM window for the save point. A *_tad*.cfg name also pulls in
;     the TAD audio objects + the audio include path. Copy-to-adapt keeps this
;     line; no Makefile edit needed. (See docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_state_mirror
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_chr, sf_load_bg_pals
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; sf_mode7_on/off/load_map/cam/perspective/focus/tick
.include "sf_fx.inc"            ; gradient + color math (the horizon-haze layer)
.include "sf_scene.inc"         ; scene state machine + dispatch
.include "sf_scene_mode.inc"    ; sf_blank_enter / sf_blank_exit (the new brick)
.include "sf_text.inc"          ; sf_text_init / print / sf_text_clear (BG3 dialog)
.include "sf_dialog.inc"        ; sf_dialog_init/open_text/close (turnkey OPAQUE BG3 panel)
.include "sf_mosaic_transition.inc" ; sf_mosaic_transition_arm/tick/active (scene wipe)
.include "sf_save.inc"          ; sf_save / sf_load / sf_save_exists (battery SRAM, slot 0)
.include "sf_input.inc"         ; btn / btnp (+ buttons.inc)
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD ca65 API imports
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music

; --- scene ids (dense from 0; sf_scene enforces order) ---
SC_OVERWORLD = 0
SC_TOWN      = 1
SC_BATTLE    = 2

; --- WRAM game-array region ($1800-$1DFF; DB=$00 reaches it) ---
SCENE        = $1804            ; scene-state word (sf_scene_begin)

; --- game DP state ($32-$5F per kit convention) ---
; persistent cross-scene — $32-$3F. The saved overworld camera (map px,
; integer) IS the ground truth for the player's position; it is always on an
; 8px grid boundary when at rest. Saved across the town/battle swap and
; restored on return (mode7_init resets the camera, so the template owns it).
ovw_camx     = $32             ; saved overworld camera X (map px, integer)
ovw_camy     = $34             ; saved overworld camera Y
ovw_angle    = $36             ; saved overworld facing (low byte = 0..255)
boot_done    = $38             ; 0 until first overworld init has seeded a camera
boot_load_done = $3A           ; 0 until the boot-load hook has run once (latch)
town_save_near = $3C           ; 1 = town player is adjacent to the SAVE POINT tile
; per-scene scratch (overworld grid-step machine) — $40-$5F. Per the kit's
; per-scene overlay convention; town/battle reuse these slots.
step_active  = $40             ; 1 = a grid slide is in progress
step_remain  = $42             ; frames left in the current slide (px @ 1/frame)
step_dx      = $44             ; per-frame camera dx (-1 / 0 / +1)
step_dy      = $46             ; per-frame camera dy (-1 / 0 / +1)
tgt_tx       = $48             ; candidate destination tile X (collision lookup)
tgt_ty       = $4A             ; candidate destination tile Y
; --- Sprint 2 overworld NPC interaction state (per-scene scratch) ---
near_npc     = $4C             ; 1 = a cardinal neighbour tile is an NPC (adjacent)
talking      = $4E             ; 1 = the sprite-text strip is showing (A toggled it)
neigh_tile   = $50             ; collision-lookup scratch for the neighbour scan
; --- Sprint 3 TOWN scene state (Mode 1 grid movement). Per-scene overlay:
;     scenes are time-exclusive, so these reuse the upper scratch slots. The
;     town avatar (OAM 0) MOVES across the screen (unlike the overworld, where
;     the camera moves and the avatar is centred), so its tile x/y are the
;     persistent town-player position; the rest is per-frame scratch. ---
town_px      = $52             ; town player tile X (0..31) — persistent in-scene
town_py      = $54             ; town player tile Y (0..31)
town_near    = $56             ; 1 = adjacent (4-neighbour) to the town NPC tile
town_dialog  = $58             ; 1 = the BG3 dialog box is open
town_a_prev  = $5A             ; previous-frame A state (edge-detect for open/close)
town_dtx     = $5C             ; collision destination tile X scratch
town_dty     = $5E             ; collision destination tile Y scratch

; --- overworld camera defaults (spawn tile center) + grid constants ---
; OVW_SPAWN_TX/TY come from ovw_collision.inc; camera px = tile*8 (1:1 scale).
TILE_PX      = 8               ; one tile = 8 map px (the grid step)
STEP_FRAMES  = 8               ; animate the 8px slide over 8 frames (1px/frame)
OVW_CAMX0    = OVW_SPAWN_TX * 8
OVW_CAMY0    = OVW_SPAWN_TY * 8
OVW_ANGLE0   = 0
AV_X0        = 120             ; avatar screen X (kept centered; camera follows)
AV_Y0        = 104             ; avatar screen Y (near FOCUS_Y, where cam maps)

; --- Sprint 2 overworld NPC prompt sprites (OBJ; Mode 7 has no BG3). The avatar
;     owns OAM slot 0 (drawn first after spr_clear). There is NO floating "!"
;     indicator: SNES-era RPGs used walk-up + adjacency + A, never a "!"
;     hovering over an NPC (period-accuracy fix). The "HELLO" sprite-text strip
;     (the on-A acknowledgement) is kept; with the indicator removed it takes the
;     next call-order slots after the avatar:
;       slots 1-5 = the 5-glyph "HELLO" sprite-text strip (drawn when talking)
;     When NOT talking the strip is simply not drawn — spr_clear already parked
;     all 128 slots at Y=$F0, so the unused prompt slots stay culled (slot 1 is
;     therefore CULLED even when the player is adjacent but has not pressed A).
;     This range (1-5) is disjoint from the avatar (0) and from anything Sprint
;     0/1 draws (the overworld draws only the avatar). ---
TEXT_X0      = 96              ; sprite-text strip left edge (5 glyphs * 8 = 40 px)
TEXT_Y0      = 72              ; sprite-text strip Y (above the avatar head)
TEXT_GLYPH_W = 8               ; one glyph = 8 px wide (8x8 OBJ tiles)

; --- Sprint 3 TOWN design (Mode 1, 32x32 flat tilemap; the avatar walks the
;     grid and the camera is fixed). The town is a DESIGNED, DENSE room: a
;     cobbled plaza framed by brick walls, two buildings, a fountain (water),
;     decorative torches, a villager NPC, and a gated EXIT back to the world.
;     Collision reads the SHADOW BG1 tilemap (the SSoT — what's drawn is what
;     blocks): BRICK + WATER block; cobble/torch/empty walk. The NPC cell is
;     ALSO blocked (separate equality check, like the overworld's TERR_NPC) so
;     the player stops adjacent and the dialog fires.
TOWN_SPAWN_TX = 16             ; town player spawn tile (centre of the plaza)
TOWN_SPAWN_TY = 16
TOWN_NPC_TX   = 16             ; the villager NPC tile (player stands adjacent + A)
TOWN_NPC_TY   = 8
TOWN_EXIT_TX  = 16             ; the gated EXIT tile (gap in the bottom wall); the
TOWN_EXIT_TY  = 21             ;   player walks onto it to return to the overworld
TOWN_AV_PAL   = $0080          ; avatar OAM attr: OBJ palette 0, priority 2 (bits 9-10? no)
; --- SAVE POINT: a visible landmark in the lower plaza (a torch tile, like the
;     NPC) the player stands adjacent to and presses A to SAVE. The cell is
;     collision-BLOCKED (the player stops next to it). A villager-style save sprite
;     (OAM slot 2) marks it. Placed in the lower courtyard, clear of the NPC (16,8)
;     and the EXIT (16,21). ---
TOWN_SAVE_TX  = 10             ; save-point tile X (lower-left courtyard)
TOWN_SAVE_TY  = 18             ; save-point tile Y
SAVE_SPRITE_TILE = AVATAR_TILE ; reuse the 16x16 character tile for the save NPC
; --- SRAM save: slot 0, payload {scene_id(1), tile_x(2), tile_y(2), version(1)}
;     staged in low WRAM before sf_save (engine reads from this WRAM block). ---
SAVE_SLOT     = 0
SAVE_VERSION  = 1
SAVE_PAYLOAD_LEN = 6           ; scene(1) + tx(2) + ty(2) + ver(1)
SAVE_STAGE    = $1820          ; low-WRAM staging buffer (game-array region, clear
                               ;   of SCENE $1804, dialog $1DC0, mosaic $1DD4)
SAVE_SCENE_OFF = 0             ; payload +0: scene id (0=overworld, 1=town)
SAVE_TX_OFF    = 1             ; payload +1: player tile X (16-bit)
SAVE_TY_OFF    = 3             ; payload +3: player tile Y (16-bit)
SAVE_VER_OFF   = 5             ; payload +5: version byte
; avatar screen pos = tile*8 (1:1; the town fills the screen, camera fixed at 0)
; --- DIALOG PANEL via sf_dialog (kit macro): a turnkey OPAQUE bordered nine-patch
;     window drawn into the BG3 SHADOW tilemap with the per-tile PRIORITY bit, so
;     under BGMODE $09 it composites ABOVE BG1/BG2/OBJ and the print text composites
;     above it — all on BG3, committed by the stock NMI (no custom VBlank, no BG2
;     box, no direct VRAM writes). Replaces the template's earlier hand-rolled BG2
;     panel (deleted: the box was on BG2 / palette 2 / CGRAM 33-34, NOT — as a stale
;     comment once claimed — BG3 palette 7).
;
;     VRAM/CGRAM map (verified vs the rpg town layout; r2-kit-macros audit F1):
;       - Box CHR  = BG3 tiles SF_DLG_TILE_BASE..+8 (default 144-152 = words
;         $2480-$24C8), in the FREE 80-159 BG1/BG3 tile gap. Town BG1 tileset is
;         tiles 0..12 ($2000-$20D0); the kit font is tile 160 ($2500). No overlap.
;         RESERVATION: the rpg keeps BG1 town tiles in 0..79 — do NOT grow the town
;         tileset past tile 143 or it will alias the dialog box CHR (relocate via
;         SF_DLG_TILE_BASE if you must).
;       - Box palette = BG3 sub-palette SF_DLG_PALETTE (default 6 = CGRAM 24-27).
;         The town BG1 uses palette 0 (CGRAM 0-15) only; the font uses CGRAM 31
;         (BG3 palette 7). CGRAM 24-27 is free. (sf_dialog_init uploads its own
;         4-colour panel palette there.)
;     Panel geometry (32x28 BG3 cell grid; print x/y are PIXELS = cell*8): a
;     wide bottom window framing 3 text lines. col/row/w/h are CELLS. ---
DLG_PANEL_COL = 2              ; panel top-left tile col
DLG_PANEL_ROW = 18             ; panel top tile row (a low bottom-of-screen window)
DLG_PANEL_W   = 28             ; panel width in cells (cols 2..29)
DLG_PANEL_H   = 9              ; panel height in cells (rows 18..26)
; dialog text print position (PIXELS): inset 1 cell from the frame top-left.
DLG_TEXT_X    = (DLG_PANEL_COL + 1) * 8   ; col 3 -> pixel-X 24
DLG_TEXT_Y0   = (DLG_PANEL_ROW + 1) * 8   ; row 19 -> pixel-Y 152
DLG_TEXT_DY   = 16             ; rows are 2 tiles apart (16 px) for readability

; --- OWNER-CHOSEN "option D / max-map" Mode 7 perspective (LOCKED, 2026-06-18).
;     These PV_* values are the project owner's selection from a set of RENDERED
;     perspective options — option D: a THIN sky (~18% of the screen, horizon at
;     scanline 40) maximising on-screen map area, with a GENTLE near/far scale
;     (~6:1) so the near ground is walkable, NOT the racer's steep smear. They
;     are carried from the Phase 13 RPG-overworld reference + the owner's
;     max-map preference. DO NOT re-derive, "improve", or second-guess these
;     numbers — a prior agent invented its own perspective and that was the
;     rejected failure. Any change here requires explicit OWNER sign-off.
;
;     The horizon at PV_L0=40 puts the sky in the top ~18%; the floor recedes
;     from there to the bottom (PV_L1=224). The scale ratio S0:S1 = 640:96
;     (~6.7:1) is a long forward view with a gentle, walkable near plane.
;     THE SKY: a horizon floor REQUIRES the sky-split (sf_mode7_sky_split) + an
;     M7SEL FILL (not WRAP), or the ground smears upward past the horizon (the
;     rejected "floor-in-sky" defect). Both are armed in scene_overworld_init;
;     SKY_HORIZON tracks PV_L0, so the sky-split band auto-moves to scanline 40.
;
;     Grid movement is UNAFFECTED: the camera (M7_PV_POSX/Y) still moves in
;     WORLD px per tile (8 px/tile); only the on-screen framing tilts. The
;     Sprint 1 world-camera-delta tests read M7_PV_POSX/Y, not screen pixels. ---
PV_L0   = 40                   ; horizon scanline (~18% sky; OWNER option D / max-map)
PV_L1   = 224                  ; bottom scanline (floor reaches the screen bottom)
PV_S0   = 640                  ; far-scale  (long forward view; see far)
PV_S1   = 96                   ; near-scale (gentle ~6:1 — walkable, not a racer's smear)
PV_SH   = 0                    ; 0 = square aspect (no extra vertical squash)
PV_INTERP = 2
PV_WRAP = 1
FOCUS_Y = 135                  ; rotation origin (camera maps to this scanline; option D)
M7SEL_FILL = $C0               ; M7SEL bit7-6 = 11 -> out-of-map = fill tile 0

; --- sky TM-split scratch table (5 bytes in game WRAM bank $7E; persists so the
;     NMI can re-arm the channel each VBlank). $7E0000+$2010 mirrors the racer;
;     it is clear of the engine state ($0100-$01A2) and the game DP block. ---
SKY_SPLIT_TABLE = $7E0000 + $2010
SKY_HORIZON     = PV_L0         ; the floor begins at PV_L0 -> sky is lines 0..39

; --- HORIZON FOG GRADIENT (static daytime haze) — carried verbatim from the
;     racer's "GRADIENT HORIZON TINT" daytime keyframes (templates/racer/main.asm
;     DAY_T*/DAY_B*). A 3-channel COLDATA gradient drives the PPU fixed colour per
;     scanline; color math SUBTRACTS it on BG1(floor) + backdrop. The ramp is
;     strongest at the TOP of the frame (the horizon, scanline 0) and ~zero at the
;     bottom (the near field): a depth-graded haze toward the horizon. The avatar
;     (OBJ) is OUTSIDE the color-math mask and stays un-hazed.
;
;     CHANNEL COEXISTENCE (the #1 risk; the racer solved it): the overworld already
;     uses sky-split = CH2 and the Mode 7 matrix = CH5/CH6. The gradient needs
;     CH3/CH4/CH7. The gradient builders REFUSE to arm while M7_PV_ACTIVE=1, so the
;     arm MUST happen BEFORE sf_mode7_on. AND the allocator's Mode-7 bootstrap pin
;     does NOT conflict-check CH5/CH6, so we PRE-PIN them (mode7_hdma_alloc_request)
;     before first-fit hands the gradient a channel — otherwise an unpinned first-fit
;     gives the gradient CH5 and the NMI's Mode 7 commit overwrites it every VBlank
;     (silent: the blue ramp dies). Result: sky-split CH2, gradient CH3/CH4/CH7,
;     matrix CH5/CH6 — disjoint. $7E:E012 mirrors the first gradient channel (==3).
;     These keyframes are the racer's proven DAYTIME values — DO NOT invent new ones.
;     The top (horizon) keyframes are .ifndef-overridable purely so a preview build
;     can render alternate fog INTENSITIES for the owner to choose (ca65 -D); the
;     COMMITTED default is the racer daytime set below.
.ifndef FOG_TR
FOG_TR = 0                      ; horizon (top) tint, 0-31 per COLDATA channel
.endif
.ifndef FOG_TG
FOG_TG = 6                      ;   warm haze: pull green + blue at the horizon
.endif
.ifndef FOG_TB
FOG_TB = 14
.endif
FOG_BR = 0                      ; near field (bottom): untinted
FOG_BG = 0
FOG_BB = 0
FOG_DBG_CHAN = $7E0000 + $E012  ; debug mirror: first gradient channel (expect 3)

; --- joypad masks (JOY1_CURRENT bit layout, matches the racer/boss templates) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_UP    = $0800
JOY_DOWN  = $0400
JOY_A     = $0080
JOY_START = $1000

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; stock engine NMI (pulls mode7_nmi.inc)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; HDMA channel allocator baseline (reserves CH0/CH1)
                                ;   — the horizon-fog gradient first-fits CH3/CH4/CH7
    sf_audio_init               ; ONCE at boot (never on a soft swap)

    ; --- STABLE OAM ordering: the avatar lives at slot 0 and tests read it by
    ;     identity, so disable Y-sort (mode 2 = stable, call order). ---
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- start the music (keep_music persists it across every swap) ---
    sf_music #Song::ode_to_joy

    sf_debug_magic

    ; --- enable NMI + auto-joypad, then enter the overworld. The overworld
    ;     init does its own blank bracket, so NMI being on here is fine. ---
    sep #$20
    .a8
    lda #$0F
    sta SHADOW_INIDISP          ; full brightness target for blank_exit
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

    sf_scene_goto SC_OVERWORLD  ; first scene (Mode 1->Mode 7 path = boot path)

    ; --- BOOT-LOAD: if SRAM slot 0 holds a valid TOWN save, switch into the town
    ;     at the saved tile right now (before the first frame renders). Else stay
    ;     on the freshly-booted overworld. Runs ONCE at boot only. ---
    jsr boot_apply

; =============================================================================
; The frame spine — runs every frame regardless of scene.
;   sf_audio_tick   drive the TAD queue + async song load (keep_music)
;   sf_mode7_tick   service Mode 7 (no-op when M7_PV_ACTIVE=0, i.e. in town)
;   sf_mosaic_transition_tick  advance the scene-wipe dissolve (no-op when idle;
;       at peak darkness it JSRs the armed swap routine, which does the actual
;       sf_scene_goto under its own forced blank)
;   sf_scene_dispatch  run the current scene's tick. Each tick gates its INPUT on
;       sf_mosaic_transition_active so the player can't act during the wipe.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin
    sf_audio_tick
    sf_mode7_tick
    sf_mosaic_transition_tick
    sf_scene_dispatch
    sf_frame_end
    jmp game_loop

; =============================================================================
; SC_OVERWORLD — Mode 7 perspective overworld.
; init: (re)build Mode 7 from the saved camera; tick: pan camera on D-pad + draw
; the avatar sprite. This is BOTH the boot path and the Mode1->Mode7 return.
; =============================================================================
; WIDTH-RISK: A16/I16 entry/exit (sf_scene init contract). All the sf_* macros
; toggle their own widths and restore A16/I16; sf_blank_enter/exit bracket the
; discontinuous rebuild. No raw width toggles in this body.
scene_overworld_init:
    .a16
    .i16
    ; on the FIRST overworld entry (boot) there is no saved camera yet — seed
    ; the saved-camera block with the map-center defaults. On later returns the
    ; saved values from the town transition are used as-is.
    lda boot_done
    bne sov_have_cam
    lda #OVW_CAMX0
    sta ovw_camx
    lda #OVW_CAMY0
    sta ovw_camy
    lda #OVW_ANGLE0
    sta ovw_angle
    lda #1
    sta boot_done
sov_have_cam:
    .a16
    .i16
    ; clear the grid-step machine on every (re)entry — a return from the town
    ; must not resume a half-finished slide that started before the swap.
    stz step_active
    stz step_remain
    stz step_dx
    stz step_dy
    ; clear the NPC interaction state too (a return from town must not resume a
    ; stale "talking" strip or a stale adjacency flag — recomputed next tick).
    stz near_npc
    stz talking
    ; --- the masked Mode1->Mode7 rebuild (also the boot rebuild) ---
    sf_blank_enter
    sf_mode7_load_map ovw_map, #$8000   ; re-upload interleaved map (under blank)

    ; re-upload the Mode 7 CGRAM (palette persists in CGRAM across a soft swap,
    ; but the town overwrote BG palette 0 — restore the overworld palette).
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    ldx #$0000
sov_pal:
    .a8
    lda f:ovw_pal, x
    sta $2122                   ; CGDATA (low/high auto-pair)
    inx
    cpx #(OVW_PAL_COUNT * 2)
    bne sov_pal
    rep #$30
    .a16
    .i16

    ; OBJ CHR + palette out of the Mode 7 map's VRAM. The map owns VRAM words
    ; $0000-$3FFF, so the OBJ name base moves to word $4000 (OBSEL=$62); tile
    ; 1024 IS word $4000, so OAM tile numbers stay 0.. relative to that base.
    sf_load_obj_pal 0, obj_pal
    sf_load_obj_chr 1024, town_chr, TOWN_CHR_BYTES
    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: name base word $4000, 16x16/32x32
    rep #$30
    .a16
    .i16

    ; --- HORIZON FOG GRADIENT: arm BEFORE sf_mode7_on (see the FOG_* block above).
    ;     The gradient builders refuse under M7_PV_ACTIVE=1, so this is the only
    ;     window; runtime is static (no retune).
    ;
    ;     RE-ENTRANT (Mode1->Mode7 return path): rebuild the SAME fresh-arm state RESET
    ;     established at boot, so the re-arm is byte-identical to the first arm:
    ;       (a) clear HDMA_GRAD_RGB_CH_R/G/B so the gradient builder's own
    ;           _hdma_rgb_release early-exits instead of de-allocating channels
    ;           against the about-to-be-reset allocator mask;
    ;       (b) hdma_alloc_init — reset the allocator to baseline (reserve CH0/CH1);
    ;       (c) clear HDMA_PHASE4_CH2_PIN — the first arm pins CH2 (the sky-split's
    ;           channel, which the allocator doesn't know is taken) so hdma_alloc
    ;           skips to CH3; that pin is only cleared by hdma_off, so a stale pin
    ;           would desync the second arm's CH2 dance.
    ;     Without this the second arm's hdma_alloc walks a corrupt mask and its
    ;     mask->channel decode loops forever (the return hangs before sf_mode7_on).
    ;     These are low-WRAM bytes ($0582 / $0648-$064D); DB=$00 direct stores reach
    ;     them. On the FIRST boot they are already zero (coldstart WRAM clear), so this
    ;     block is a no-op there.
    stz HDMA_GRAD_RGB_CH_R      ; (a) clear gradient channel tracking -> release no-ops
    stz HDMA_GRAD_RGB_CH_G
    stz HDMA_GRAD_RGB_CH_B
    jsr hdma_alloc_init         ; (b) allocator baseline (reserve CH0/CH1)
    sep #$20                    ; (c) clear the stale CH2 pin (a 1-byte flag — A8 so
    .a8                         ;     the 16-bit stz does not also zero M7_TMP_MASK
    stz HDMA_PHASE4_CH2_PIN     ;     at $0583); restore A16 for the macros below.
    rep #$20
    .a16
    ;
    ;     CHANNEL ORDER: pre-pin Mode 7's CH5+CH6 FIRST (mode7_hdma_alloc_request,
    ;     idempotent — mode7_init repeats it inside sf_mode7_on), THEN arm the
    ;     gradient so first-fit lands it on CH3/CH4/CH7 (NOT CH5, which the NMI's
    ;     Mode 7 matrix commit would overwrite every VBlank). $7E:E012 verifies the
    ;     first gradient channel (expect 3).
    jsr mode7_hdma_alloc_request ; pre-pin Mode 7's CH5+CH6 so the gradient skips them
    sf_gradient_ease #0         ; linear ramp, horizon(top) -> near(bottom)
    sf_gradient_rgb #FOG_TR, #FOG_TG, #FOG_TB, #FOG_BR, #FOG_BG, #FOG_BB
    ldx #$0000
    sta f:FOG_DBG_CHAN, x       ; debug: A = first gradient channel (expect 3)
    sf_gradient_phase #0        ; static haze — no phase animation
    ; color math: SUBTRACT the per-scanline fixed colour on BG1(floor) + backdrop
    ; ($21). The COLDATA ramp becomes the depth-graded horizon haze; OBJ (the
    ; avatar + NPC prompts) is outside the mask and stays un-hazed.
    sf_colormath_on #2, #$21
    sf_colormath_tint #0, #0, #0

    sf_mode7_on                 ; M7_PV_ACTIVE=1, pin CH5+CH6 (resets cam!)
    sf_mode7_perspective #PV_L0, #PV_L1, #PV_S0, #PV_S1, #PV_SH, #PV_INTERP, #PV_WRAP
    sf_mode7_focus #FOCUS_Y
    ; M7SEL = FILL (not WRAP): out-of-map samples render tile 0, so map edges do
    ; not tile the floor across the off-map area. HALF of the floor-in-sky fix.
    sf_mode7_flags #M7SEL_FILL
    sf_mode7_cam ovw_camx, ovw_camy, ovw_angle   ; apply the SAVED camera
    ; arm the per-scanline sky-split: BG1 OFF above PV_L0 so the CGRAM[0] sky
    ; backdrop shows there (the OTHER half of the fix). Re-armed on every return
    ; from town/battle (sf_mode7_off zeroed NMI_HDMA_ENABLE, so we re-OR CH2).
    sf_mode7_sky_split #SKY_HORIZON, SKY_SPLIT_TABLE
    sf_mode7_tick               ; build the first table BEFORE screen-on


    sf_blank_exit               ; drop blank at full brightness, re-enable NMI

    lda #SC_OVERWORLD
    sf_state_mirror             ; mirror scene id to $7E:E016 (A holds it)
    rts

; -----------------------------------------------------------------------------
; scene_overworld_tick — RPG grid movement + tile collision.
;
; The avatar stays at screen center (OAM 0); the D-pad scrolls the Mode 7
; CAMERA under it, one tile (8 px) per press, animated over STEP_FRAMES frames
; at 1 px/frame. A press into a BLOCKED tile (water/mountain) is rejected via
; the parallel ovw_collision table — the camera does not move. Cardinal only;
; fixed orientation (no rotation). A -> TOWN, START -> BATTLE.
;
; Flow each frame:
;   1. If a slide is in progress, advance it (ignore new input until it lands).
;   2. Else read scene-transition buttons, then a held D-pad direction; if the
;      destination tile is walkable, START a slide.
;   3. Apply the camera + draw the centered avatar.
;
; WIDTH-RISK: A16/I16 entry/exit. After a goto we RETURN immediately (the
; soft-restart contract) — never fall through into stale-scene draw code. All
; arithmetic is A16; the collision helper toggles A8 internally and restores.
; -----------------------------------------------------------------------------
scene_overworld_tick:
    .a16
    .i16
    ; --- (0) GATE INPUT during a scene wipe: while sf_mosaic_transition is in
    ;     flight, skip ALL input (movement + the A/START scene triggers) but still
    ;     apply the camera + draw the avatar, so the outgoing scene keeps rendering
    ;     under the mosaic until the swap fires at peak darkness. ---
    sf_mosaic_transition_active
    beq sovt_input_ok           ; A==0 -> idle, take input normally
    jmp sovt_apply              ; wipe in flight -> camera+draw only, no input
sovt_input_ok:
    .a16
    .i16
    ; --- (1) a slide is in progress: advance it, ignore new input ---
    lda step_active
    beq sovt_idle
    ; apply this frame's 1px camera delta
    lda ovw_camx
    clc
    adc step_dx
    sta ovw_camx
    lda ovw_camy
    clc
    adc step_dy
    sta ovw_camy
    ; one fewer frame left; when it hits 0 the slide has landed on the new tile
    lda step_remain
    dec a
    sta step_remain
    ; (the idle/interaction block below pushed sovt_apply out of bra range, so
    ;  these are long jmps — A16 unaffected.)
    beq sovt_slide_done
    jmp sovt_apply
sovt_slide_done:
    .a16
    stz step_active             ; slide complete — camera is grid-aligned again
    jmp sovt_apply

sovt_idle:
    .a16
    ; --- (2a-NPC) proximity: standing still, so recompute NPC adjacency. This
    ;     sets near_npc (gates the prompt indicator + the A-interaction). If the
    ;     player is NO LONGER next to an NPC, the talking strip is dismissed
    ;     (walking away closes the dialog — the user-visible cycle). ---
    jsr check_npc_adjacency
    lda near_npc
    bne sovt_have_npc
    stz talking                 ; not adjacent -> dialog closed
sovt_have_npc:
    .a16
    ; --- (2a) A button. While ADJACENT to an NPC, A is the INTERACT button: it
    ;     toggles the sprite-text strip and does NOT change scene. Only when the
    ;     player is NOT next to an NPC does A trigger the town transition (so the
    ;     Sprint 0/1 A->town round-trip from the spawn is unchanged). ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq sovt_no_a
    lda near_npc
    beq sovt_a_to_town          ; not near an NPC -> A goes to the town
    ; near an NPC: toggle the dialog (show on first press, dismiss on next)
    lda talking
    eor #$0001
    sta talking
    jmp sovt_apply              ; long jmp (out of bra range past the D-pad block)
sovt_a_to_town:
    .a16
    ; arm the mosaic scene wipe instead of an instant swap: the dissolve drops
    ; OBJ now, pixelates the Mode 7 floor to black, runs swap_to_town at peak
    ; darkness (the real sf_scene_goto under a forced blank), then de-pixelates
    ; the town. Mask $07 = BG1+BG2+BG3 (covers both the Mode 7 floor + sky and the
    ; Mode 1 town/dialog). The tick returns; the wipe runs from the game loop.
    sf_mosaic_transition_arm #$07, swap_to_town
    rts
sovt_no_a:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_START
    beq sovt_no_start
    sf_mosaic_transition_arm #$07, swap_to_battle
    rts
sovt_no_start:
    .a16
    ; --- (2b) held D-pad -> try to start ONE grid step (first matching dir).
    ;     A held direction starts a single step; the step machine then locks out
    ;     new input until the slide lands, so holding walks tile-by-tile and a
    ;     single tap moves exactly one tile. ---
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq sovt_chk_right
    ldx #$FFFF                  ; dx = -1 tile
    ldy #$0000                  ; dy =  0
    jsr try_start_step
    bra sovt_apply
sovt_chk_right:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq sovt_chk_up
    ldx #$0001                  ; dx = +1
    ldy #$0000
    jsr try_start_step
    bra sovt_apply
sovt_chk_up:
    .a16
    lda JOY1_CURRENT
    bit #JOY_UP
    beq sovt_chk_down
    ldx #$0000
    ldy #$FFFF                  ; dy = -1
    jsr try_start_step
    bra sovt_apply
sovt_chk_down:
    .a16
    lda JOY1_CURRENT
    bit #JOY_DOWN
    beq sovt_apply
    ldx #$0000
    ldy #$0001                  ; dy = +1
    jsr try_start_step

sovt_apply:
    .a16
    .i16
    ; --- (3) apply the camera + service Mode 7 this frame ---
    sf_mode7_cam ovw_camx, ovw_camy, ovw_angle

    ; --- sprites. During a scene WIPE the avatar must NOT show: OBJ has no HW
    ;     mosaic, and the Mode 7 engine keeps OBJ enabled via its per-scanline HDMA
    ;     TM source ($3600), so the mosaic's SHADOW_TM OBJ-drop can't hide it here.
    ;     Instead, spr_clear alone (no avatar/prompt draw) leaves every OAM slot
    ;     parked at Y=$F0 — the avatar is culled for the whole dissolve. ---
    spr_clear
    sf_mosaic_transition_active
    bne sovt_apply_done         ; wipe in flight -> no sprites (avatar culled)
    ; --- draw the avatar (OAM slot 0, 16x16 large, OBJ palette 0), fixed at
    ;     screen center — the world scrolls under it (camera-follows-player). ---
    spr #AVATAR_TILE, #AV_X0, #AV_Y0, #$0080, #2
    ; --- the NPC prompt sprites: indicator when adjacent, text strip when
    ;     talking. Drawn AFTER the avatar so they take call-order slots 1..6;
    ;     when not shown they are simply not drawn (spr_clear parked them). ---
    jsr draw_npc_prompt
sovt_apply_done:
    .a16
    .i16
    rts

; =============================================================================
; draw_npc_prompt — render the overworld NPC acknowledgement with OBJ sprites
; (Mode 7 has no BG3). MUST be called right after the avatar's spr so the
; call-order slots line up: slots 1-5 = the "HELLO" text strip.
;   talking -> draw the 5-glyph text strip (slots 1-5) above the avatar head.
; There is NO floating "!" indicator (period-accuracy fix): adjacency alone draws
; nothing; only the on-A "HELLO" acknowledgement renders. When NOT talking the
; strip is not drawn; spr_clear (called before the avatar each frame) already
; parked all 128 OAM slots at Y=$F0, so slot 1 renders CULLED whenever the player
; is merely adjacent (and not yet talking). All glyphs are 8x8 small OBJ, palette 0.
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; spr asserts/returns A16/I16. No raw width toggles.
; =============================================================================
draw_npc_prompt:
    .a16
    .i16
    lda talking
    bne dnp_text                ; talking -> draw the "HELLO" strip (slots 1-5)
    rts                         ; not talking -> nothing to draw (slots culled)
dnp_text:
    .a16
    ; --- slots 1-5: the "HELLO" sprite-text strip (5 glyphs, 8 px apart) ---
    spr #GLYPH_TILE_H, #(TEXT_X0 + 0 * TEXT_GLYPH_W), #TEXT_Y0, #$0000, #2
    spr #GLYPH_TILE_E, #(TEXT_X0 + 1 * TEXT_GLYPH_W), #TEXT_Y0, #$0000, #2
    spr #GLYPH_TILE_L, #(TEXT_X0 + 2 * TEXT_GLYPH_W), #TEXT_Y0, #$0000, #2
    spr #GLYPH_TILE_L, #(TEXT_X0 + 3 * TEXT_GLYPH_W), #TEXT_Y0, #$0000, #2
    spr #GLYPH_TILE_O, #(TEXT_X0 + 4 * TEXT_GLYPH_W), #TEXT_Y0, #$0000, #2
    rts

; =============================================================================
; try_start_step — start a grid slide in tile-direction (X=dx, Y=dy) IF the
; destination tile is walkable. X/Y are signed 16-bit tile deltas (-1/0/+1).
;
; Computes the destination tile from the CURRENT camera (cam/8 + delta), looks
; up ovw_collision[ty*128 + tx], and rejects when the terrain id is in the
; blocked range [TERR_BLOCKED_MIN, TERR_BLOCKED_MAX]. Walkable -> arm the slide
; (step_dx/dy = delta px, step_remain = STEP_FRAMES, step_active = 1). Blocked
; -> leave step_active = 0 so the camera does not move (a press into a wall is
; a no-op). Map is 128x128 tiles; coords are clamped to 0..127 so an edge step
; just looks up the edge tile (the map wraps in Mode 7 hardware anyway).
;
; Entry: A16/I16. X = dx, Y = dy. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry. Toggles A8 for the 1-byte terrain read, restores
; A16 before returning. The blocked/walkable branch targets carry explicit
; width annotations.
; =============================================================================
try_start_step:
    .a16
    .i16
    ; stash the signed tile deltas (also the per-frame px deltas: 1 px/frame
    ; for STEP_FRAMES frames = 8 px = one tile, since the step direction is
    ; exactly -1/0/+1 px each frame).
    stx step_dx                 ; dx (-1/0/+1)
    sty step_dy                 ; dy
    ; tgt_tx = ((camx / 8) + dx) & 127
    lda ovw_camx
    lsr a
    lsr a
    lsr a                       ; current tile X = camx / 8
    clc
    adc step_dx
    and #$007F                  ; wrap/clamp to the 128-tile grid
    sta tgt_tx
    ; tgt_ty = ((camy / 8) + dy) & 127
    lda ovw_camy
    lsr a
    lsr a
    lsr a
    clc
    adc step_dy
    and #$007F
    sta tgt_ty
    ; col_idx = ty*128 + tx  (ty<<7 | tx; both < 128 so no bit overlap)
    lda tgt_ty
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; ty * 128
    ora tgt_tx                  ; + tx
    tax                         ; X = byte index into ovw_collision (I16)
    ; read terrain id = ovw_collision[idx] (RODATA; ^label gives the bank)
    sep #$20
    .a8
    lda f:ovw_collision, x      ; A8 terrain id (the table is bytes)
    cmp #TERR_NPC               ; an NPC tile is BLOCKED (separate equality check
    beq tss_blocked            ;   so the contiguous water/mountain range never
    ;                            swallows TERR_TOWN, which must stay walkable)
    cmp #TERR_BLOCKED_MIN
    bcc tss_walkable            ; id < MIN          -> walkable
    cmp #(TERR_BLOCKED_MAX + 1)
    bcs tss_walkable            ; id > MAX          -> walkable
tss_blocked:
    .a8
    ; blocked terrain (water / mountain / NPC): clear staged deltas, do not move
    rep #$20
    .a16
    stz step_dx
    stz step_dy
    rts
tss_walkable:
    .a8
    rep #$20
    .a16
    ; arm the slide: step_dx/step_dy already hold the per-frame px deltas
    lda #STEP_FRAMES
    sta step_remain
    lda #1
    sta step_active
    rts

; =============================================================================
; terr_at — return the terrain id of tile (X=tx, Y=ty) in A (zero-extended to
; A16 on exit). Coords are wrapped to the 128 grid; index = (ty&127)*128 + (tx&127).
; Entry: A16/I16, X=tx, Y=ty. Exit: A16 with the terrain byte in the low 8 bits
; (high byte 0), I16 preserved. Clobbers A, X. (Caller's Y survives.)
; WIDTH-RISK: A16/I16 entry; computes the 16-bit index in A then toggles A8 for
; the 1-byte table read and RESTORES A16 before rts so the caller's tracking
; stays A16 across the jsr. (If terr_at exited A8, ca65 would still assemble the
; caller's post-jsr `cmp #imm` as 16-bit while the CPU ran A8 — the stray-third-
; byte = BRK silent-corruption class.) No multi-path label.
; =============================================================================
terr_at:
    .a16
    .i16
    tya                         ; A = ty
    and #$007F
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; (ty&127) * 128
    sta neigh_tile              ; stash the row base
    txa                         ; A = tx
    and #$007F
    ora neigh_tile             ; + (tx&127)
    tax                         ; X = byte index into ovw_collision
    sep #$20
    .a8
    lda f:ovw_collision, x      ; A8 terrain byte
    rep #$20                    ; restore A16 so the caller stays A16 across the jsr
    .a16
    and #$00FF                  ; zero-extend: A = terrain id (high byte cleared)
    rts

; =============================================================================
; check_npc_adjacency — set near_npc = 1 if any of the player's 4 cardinal
; neighbour tiles is an NPC (TERR_NPC), else 0. The player tile = camera/8.
; Used to gate the prompt indicator + the A-press interaction. Pure read of the
; parallel collision table — no per-frame VRAM reads.
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 throughout — terr_at returns A16 (zero-extended), so every
; compare is a 16-bit `cmp #imm` matching the runtime; no per-call width toggle.
; cna_found is reached via beq from A16 and stays A16.
; =============================================================================
check_npc_adjacency:
    .a16
    .i16
    stz near_npc                ; default: not adjacent
    ; player tile (tx,ty) = (camx/8, camy/8)
    lda ovw_camx
    lsr a
    lsr a
    lsr a
    sta tgt_tx                  ; reuse tgt_tx/ty as the player-tile scratch
    lda ovw_camy
    lsr a
    lsr a
    lsr a
    sta tgt_ty
    ; --- neighbour EAST (tx+1, ty) ---
    lda tgt_tx
    inc a
    tax
    ldy tgt_ty
    jsr terr_at                 ; A16 = terrain id (zero-extended)
    cmp #TERR_NPC
    beq cna_found
    ; --- neighbour WEST (tx-1, ty) ---
    lda tgt_tx
    dec a
    tax
    ldy tgt_ty
    jsr terr_at
    cmp #TERR_NPC
    beq cna_found
    ; --- neighbour SOUTH (tx, ty+1) ---
    ldx tgt_tx
    lda tgt_ty
    inc a
    tay
    jsr terr_at
    cmp #TERR_NPC
    beq cna_found
    ; --- neighbour NORTH (tx, ty-1) ---
    ldx tgt_tx
    lda tgt_ty
    dec a
    tay
    jsr terr_at
    cmp #TERR_NPC
    beq cna_found
    rts                         ; none of the 4 neighbours is an NPC
cna_found:
    .a16
    lda #1
    sta near_npc
    rts

; =============================================================================
; SC_TOWN — Mode 1 flat tilemap: a DESIGNED, DENSE cobbled plaza (brick walls,
; two buildings, a fountain, torches), a villager NPC, a BG3 dialog box, and a
; gated EXIT back to the overworld. The avatar grid-walks the room (camera fixed;
; the SPRITE moves, unlike the overworld). Collision reads the shadow BG1 tilemap.
; init: SAVE the overworld camera, then the masked Mode7->Mode1 swap, then set up
; BG3 text (font) for the dialog box. keep_music: NO sf_audio_init here.
; =============================================================================
; WIDTH-RISK: A16/I16 entry/exit. The save reads M7_PV_POSX+2/POSY+2/ANGLE
; (engine state) into the game's saved-camera block BEFORE mode7_off tears it
; down. sf_blank_enter/exit bracket the rebuild; gfxmode turns the screen back
; on mid-rebuild so blank is RE-RAISED after it. sf_text_init (a ~1.5KB CPU font
; upload) runs UNDER the re-raised blank and BEFORE gfxmode zeros the BG3 shadow.
scene_town_init:
    .a16
    .i16
    jsr save_overworld_camera   ; M7_PV_* -> ovw_camx/camy/angle (before teardown)

    sf_blank_enter
    sf_mode7_off                ; release CH5/6, zero NMI_HDMA_ENABLE, M7 off
    gfxmode #1                  ; Mode 1 BGs + writes $2100=$0F (screen ON!) ...
    sf_blank_enter              ; ... so RE-RAISE blank before the uploads

    ; --- BG3 text font upload: MUST be under the (re-raised) forced blank and
    ;     BEFORE the BG3 shadow is first written. gfxmode already zeroed the BG3
    ;     shadow tilemap above, so the dialog `print`s (in show_town_dialog) run
    ;     AFTER this. The font CHR lands at VRAM word $2500 (BG3 chr base $2000 +
    ;     tile 160); the town BG1 tileset (tiles 0..12, well below index 80) does
    ;     not collide with it. ---
    sf_text_init                ; upload 8x8 font + engine text state + white colour

    ; --- DIALOG PANEL CHR + palette (sf_dialog): upload the 9 opaque nine-patch
    ;     tiles (2bpp) to BG3 CHR word $2480 (tiles 144-152) and the 4-colour panel
    ;     palette to CGRAM 24-27 (BG3 sub-palette 6). MUST be under the (re-raised)
    ;     forced blank, like the font (CPU-side VRAM/CGRAM port writes). The town
    ;     BG1 tileset (tiles 0..12) + the kit font (tile 160) do NOT collide with
    ;     the 144-152 box gap. The panel is laid into the BG3 shadow tilemap by
    ;     sf_dialog_open_text (on A in show_town_dialog), not here. ---
    sf_dialog_init

    ; Mode 1 CHR + palettes (the map owned VRAM under Mode 7; gfxmode points
    ; BG1 CHR at word $2000 — upload there). OBJ CHR/pal for the avatar + NPC.
    ; OBJ name base = word $4000 (tile 1024), the SAME known-good slot the
    ; overworld uses; OBSEL=$62. (Word $0000 holds stale Mode 7 map remnants the
    ; swap does not clear, and an OBJ upload there did not render — $4000 is the
    ; clean slot above the BG1 CHR ($2000) + font ($2500).)
    sf_load_bg_chr 0, town_chr, TOWN_CHR_BYTES
    sf_load_bg_pals 0, town_bg_pal, TOWN_BG_PAL_COUNT
    sf_load_obj_pal 0, obj_pal
    sf_load_obj_chr 1024, town_chr, TOWN_CHR_BYTES   ; OBJ name base word $4000
    sep #$20
    .a8
    lda #$02
    sta $2101                   ; OBSEL: OBJ name base word $4000, size pair 8x8/16x16.
                                ; The avatar+NPC use the LARGE size bit, so LARGE must
                                ; be 16x16 (size field 0) — NOT 32x32 (field 3 = $62).
                                ; At 32x32 a 16x16-intended sprite read tile 8 (the IND
                                ; "!" glyph) into its top-right quadrant: the phantom
                                ; exclamation mark beside every character. 8/16 = 16x16.
    ; NOTE: the dialog panel now lives on BG3 (sf_dialog), so the town no longer
    ; uses BG2 — the old BG2_TILEMAP_VRAM_HI publish (for the deleted BG2 box) is
    ; gone. The BG3 text/dialog tilemap DMA is configured by gfxmode #1.
    rep #$30
    .a16
    .i16
    ; backdrop (CGRAM index 0) = cobble-gray so empty tiles read as floor.
    ; $318C = BGR15(96,96,104).
    sf_bg_color 0, 0, $318C

    jsr build_town_map          ; mset the dense town AFTER gfxmode (it zeroed it)

    ; --- seed the town player at the plaza spawn + clear per-scene town state.
    ;     Each (re)entry resets the player to the spawn and closes any dialog so a
    ;     return never resumes stale state. ---
    lda #TOWN_SPAWN_TX
    sta town_px
    lda #TOWN_SPAWN_TY
    sta town_py
    stz town_near
    stz town_dialog
    stz town_a_prev

    sf_blank_exit

    lda #SC_TOWN
    sf_state_mirror
    rts

; -----------------------------------------------------------------------------
; scene_town_tick — Mode 1 town: grid-walk the avatar, NPC proximity + dialog.
;
; Flow each frame:
;   1. recompute NPC adjacency (town_near) from the player tile.
;   2. A button (edge-detected): near the NPC -> toggle the BG3 dialog box;
;      else, if standing on the EXIT tile -> return to the overworld.
;   3. while the dialog is OPEN, movement is frozen (a real dialog blocks walk).
;   4. else, a held D-pad direction tries one grid step (tile collision).
;   5. draw the avatar (OAM 0) + the NPC sprite (OAM 1); if dialog open, the box
;      is already on BG3 (drawn once on open; cleared on close).
;
; WIDTH-RISK: A16/I16 entry/exit. After a goto we RETURN immediately. The town
; helpers (town_collide / town_npc_adjacent) toggle A8 for the 1-byte tilemap
; read and restore A16 before returning.
; -----------------------------------------------------------------------------
scene_town_tick:
    .a16
    .i16
    ; --- (0) GATE INPUT during a scene wipe: while leaving the town the mosaic
    ;     wipe runs; skip all town input (movement, A, save point) but keep drawing
    ;     so the town renders under the dissolve until the swap fires. ---
    sf_mosaic_transition_active
    beq stt_input_ok
    jmp stt_draw                ; wipe in flight -> draw only, no input
stt_input_ok:
    .a16
    .i16
    ; --- (1) NPC + SAVE-POINT adjacency (gate the A interactions) ---
    jsr town_npc_adjacent       ; sets town_near = 0/1
    jsr town_save_adjacent      ; sets town_save_near = 0/1

    ; --- (2) A button (rising edge via the PRESSED latch). Priority:
    ;     dialog open -> CLOSE it; else near NPC -> open NPC dialog; else near the
    ;     SAVE POINT -> save the game (+ SAVED panel); else on the EXIT -> leave. ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq stt_no_a_edge
    ; (2a) any panel open (NPC dialog OR the SAVED confirm) -> A closes it
    lda town_dialog
    bne stt_close_dialog
    ; (2b) near the NPC -> open the NPC dialog
    lda town_near
    beq stt_chk_save
    jsr show_town_dialog        ; open: the BG3 panel + NPC text
    lda #1
    sta town_dialog
    bra stt_no_a_edge
stt_chk_save:
    .a16
    ; (2c) near the SAVE POINT -> write SRAM slot 0 + show the SAVED panel
    lda town_save_near
    beq stt_try_exit
    jsr do_save_town            ; sf_save slot 0 + SAVED panel (opens the dialog)
    lda #1
    sta town_dialog             ; the SAVED panel is now open; A closes it
    bra stt_no_a_edge
stt_close_dialog:
    .a16
    jsr hide_town_dialog        ; close: clear the BG3 panel (NPC text or SAVED)
    stz town_dialog
    bra stt_no_a_edge
stt_try_exit:
    .a16
    ; not near the NPC or save point: if standing on the EXIT tile, leave town
    lda town_px
    cmp #TOWN_EXIT_TX
    bne stt_no_a_edge
    lda town_py
    cmp #TOWN_EXIT_TY
    bne stt_no_a_edge
    ; leave the town via the mosaic wipe back to the overworld (swap_to_overworld
    ; runs the real sf_scene_goto SC_OVERWORLD at peak darkness).
    sf_mosaic_transition_arm #$07, swap_to_overworld
    rts
stt_no_a_edge:
    .a16
    ; --- (3) dialog open -> freeze movement (a dialog blocks walking) ---
    lda town_dialog
    bne stt_draw
    ; --- (4) D-pad (edge-latched) -> one grid step per press (first matching
    ;     dir), collision-checked. The PRESSED latch gives one tile per tap, so
    ;     the town walks tile-by-tile (no per-frame slide machine needed). ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_LEFT
    beq stt_chk_right
    ldx #$FFFF
    ldy #$0000
    jsr town_try_step
    bra stt_draw
stt_chk_right:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_RIGHT
    beq stt_chk_up
    ldx #$0001
    ldy #$0000
    jsr town_try_step
    bra stt_draw
stt_chk_up:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_UP
    beq stt_chk_down
    ldx #$0000
    ldy #$FFFF
    jsr town_try_step
    bra stt_draw
stt_chk_down:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_DOWN
    beq stt_draw
    ldx #$0000
    ldy #$0001
    jsr town_try_step
stt_draw:
    .a16
    .i16
    jsr draw_town_sprites
    rts

; =============================================================================
; SC_BATTLE — Mode 1, a near-clone of TOWN with a distinct backdrop color so
; the scene table + dispatch are proven for all three (fleshed out later).
; =============================================================================
; WIDTH-RISK: A16/I16 entry/exit. Same swap shape as town; the only difference
; is build_battle_map fills a different backdrop tile so a screenshot reads it
; apart from the town.
scene_battle_init:
    .a16
    .i16
    jsr save_overworld_camera

    sf_blank_enter
    sf_mode7_off
    gfxmode #1
    sf_blank_enter

    sf_load_bg_chr 0, town_chr, TOWN_CHR_BYTES
    sf_load_bg_pals 0, town_bg_pal, TOWN_BG_PAL_COUNT
    sf_load_obj_pal 0, obj_pal
    sf_load_obj_chr 0, town_chr, TOWN_CHR_BYTES
    sep #$20
    .a8
    lda #$00
    sta $2101
    rep #$30
    .a16
    .i16
    ; backdrop (CGRAM index 0) = water-blue so the battle field reads as a blue
    ; arena (vs the town's gray cobble). $5565 = BGR15(40,90,170).
    sf_bg_color 0, 0, $5565

    jsr build_battle_map

    sf_blank_exit

    lda #SC_BATTLE
    sf_state_mirror
    rts

; -----------------------------------------------------------------------------
; scene_battle_tick — A returns to the overworld.
; WIDTH-RISK: A16/I16 entry/exit; return immediately after a goto.
; -----------------------------------------------------------------------------
scene_battle_tick:
    .a16
    .i16
    ; gate input during a wipe (leaving the battle), else A returns to overworld.
    sf_mosaic_transition_active
    bne sbt_idle                ; wipe in flight -> no input
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq sbt_idle
    sf_mosaic_transition_arm #$07, swap_to_overworld
    rts
sbt_idle:
    .a16
    rts

; =============================================================================
; Mosaic-wipe SWAP routines — the caller-supplied swap_label for
; sf_mosaic_transition_arm. The stepper JSRs ONE of these at PEAK DARKNESS
; (brightness ~0). Each runs the real sf_scene_goto (which runs the destination
; scene init under ITS OWN forced blank), then RE-DARKENS the screen to black so
; the IN-ramp brightens from 0 — the destination init's gfxmode/sf_blank_exit
; leaves SHADOW_INIDISP at FULL brightness ($0F), which would otherwise flash the
; new scene fully-bright-but-pixelated for one frame before the de-pixelate ramp.
;
; Entry: A8/I16 (the stepper's _sf_mosaic_call_swap convention). sf_scene_goto
; forces A16/I16 and the scene init returns A16/I16; we drop back to A8 for the
; INIDISP re-darken and RTS in A8/I16 (the swap contract).
; WIDTH-RISK: A8/I16 entry. sf_scene_goto + the scene init run A16/I16; we sep
; #$20 for the 1-byte INIDISP writes and EXIT A8/I16 (the stepper resumes A8).
; =============================================================================
swap_to_town:
    .a8
    .i16
    sf_scene_goto SC_TOWN
    bra _swap_redarken
swap_to_battle:
    .a8
    .i16
    sf_scene_goto SC_BATTLE
    bra _swap_redarken
swap_to_overworld:
    .a8
    .i16
    sf_scene_goto SC_OVERWORLD
    ; fall through to _swap_redarken
_swap_redarken:
    ; here A16/I16 (sf_scene_goto's exit). Drop the brightness nibble to 0 so the
    ; IN ramp starts from black; write $2100 directly so the very next committed
    ; frame is black (no full-bright flash). Preserve the blank bit (should be
    ; clear after the init's sf_blank_exit, but AND keeps it safe either way).
    sep #$20
    .a8
    lda SHADOW_INIDISP
    and #$F0                     ; keep blank bit + high nibble, clear brightness
    sta SHADOW_INIDISP           ; brightness 0 (NMI re-commits; IN ramp takes over)
    sta $2100                    ; immediate: black this frame, no flash
    rts                          ; A8/I16 -> stepper resumes

; =============================================================================
; do_save_town — stage {scene=TOWN, town_px, town_py, version} and write it to
; SRAM slot 0 via sf_save (the kit save engine: header + payload + CRC-16). Then
; show a "SAVED" confirmation via sf_dialog. Called from the town tick when the
; player is adjacent to the save point and presses A.
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; A8 for the 1-byte scene/version stage writes; the
; 16-bit tx/ty stages run A16; sf_save forces A16/I16; restores A16/I16 before rts.
; =============================================================================
do_save_town:
    .a16
    .i16
    ; --- stage scene id at +0 (1 byte = SC_TOWN) ---
    sep #$20
    .a8
    lda #SC_TOWN
    sta f:$7E0000 + SAVE_STAGE + SAVE_SCENE_OFF
    rep #$20
    .a16
    ; --- stage player tile x/y (16-bit each) ---
    lda town_px
    sta f:$7E0000 + SAVE_STAGE + SAVE_TX_OFF
    lda town_py
    sta f:$7E0000 + SAVE_STAGE + SAVE_TY_OFF
    ; --- stage version at +5 ---
    sep #$20
    .a8
    lda #SAVE_VERSION
    sta f:$7E0000 + SAVE_STAGE + SAVE_VER_OFF
    rep #$20
    .a16
    ; --- write to SRAM slot 0 (sf_save: slot, src, len, ver) ---
    sf_save SAVE_SLOT, #SAVE_STAGE, SAVE_PAYLOAD_LEN, SAVE_VERSION
    ; --- "SAVED" confirmation panel (sf_dialog, same BG3 panel as the NPC dialog) ---
    sf_dialog_open #DLG_PANEL_COL, #DLG_PANEL_ROW, #DLG_PANEL_W, #DLG_PANEL_H
    print str_saved, #DLG_TEXT_X, #DLG_TEXT_Y0
    rts

; =============================================================================
; try_boot_load — boot-load hook, run once from the FIRST overworld init. If SRAM
; slot 0 holds a VALID save (sf_save_exists: magic + CRC-16), load the payload
; into the stage buffer and, when the saved scene is TOWN, arm the entry: write
; the restored town tile and request a switch into the town. Else (no/corrupt
; save, or saved scene = overworld) start fresh on the overworld.
; Returns A = 1 if a valid TOWN save was applied (caller should switch into the
; town), 0 otherwise (stay on the overworld).
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; sf_save_exists / sf_load force A16/I16; the 16-bit
; tile reloads run A16; exits A16/I16.
; =============================================================================
try_boot_load:
    .a16
    .i16
    sf_save_exists SAVE_SLOT     ; A = 1 valid, 0 none/corrupt
    cmp #$0001
    beq @load_it
    lda #$0000                   ; no valid save -> fresh start
    rts
@load_it:
    .a16
    sf_load SAVE_SLOT, #SAVE_STAGE   ; A = length / $FFFF none / $FFFE corrupt
    cmp #SAVE_PAYLOAD_LEN
    beq @apply
    lda #$0000                   ; unexpected length -> treat as invalid (fresh)
    rts
@apply:
    .a16
    ; restored scene id -> if TOWN, apply the tile + request the switch
    sep #$20
    .a8
    lda f:$7E0000 + SAVE_STAGE + SAVE_SCENE_OFF
    rep #$20
    .a16
    and #$00FF
    cmp #SC_TOWN
    beq @restore_town
    lda #$0000                   ; saved scene = overworld -> stay here (fresh OW)
    rts
@restore_town:
    .a16
    ; apply the restored town tile so scene_town_init's spawn-seed can read it
    ; (the caller re-applies after enter so init's spawn default does not win).
    lda f:$7E0000 + SAVE_STAGE + SAVE_TX_OFF
    sta town_px
    lda f:$7E0000 + SAVE_STAGE + SAVE_TY_OFF
    sta town_py
    lda #$0001                   ; signal: switch into the town at the restored tile
    rts

; =============================================================================
; boot_apply — the boot-load HOOK, run ONCE from RESET right after the first
; overworld goto. If SRAM slot 0 holds a valid TOWN save, switch into the town
; AT the restored tile: sf_scene_goto SC_TOWN runs the town init (which re-seeds
; the spawn tile), then we RE-apply the restored tile from the stage buffer and
; rebuild the town sprites so the very first town frame is centred on the saved
; position. No valid/town save -> stay on the overworld (fresh start).
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; sf_scene_goto + the inits run A16/I16; exits A16/I16.
; =============================================================================
boot_apply:
    .a16
    .i16
    jsr try_boot_load           ; A = 1 if a valid TOWN save was found (tile applied)
    cmp #$0001
    bne @no_load                ; no/corrupt save, or saved scene = overworld
    sf_scene_goto SC_TOWN       ; enter the town (init re-seeds the spawn tile)
    ; re-apply the restored tile (the town init wrote TOWN_SPAWN over it)
    lda f:$7E0000 + SAVE_STAGE + SAVE_TX_OFF
    sta town_px
    lda f:$7E0000 + SAVE_STAGE + SAVE_TY_OFF
    sta town_py
    jsr draw_town_sprites       ; rebuild OAM so frame 0 shows the restored position
@no_load:
    .a16
    rts

; =============================================================================
; save_overworld_camera — snapshot the live Mode 7 camera into the game's
; persistent saved-camera block BEFORE mode7_disable tears it down. mode7_init
; resets the camera to map-center, so without this the return would teleport.
; M7_PV_POSX/POSY are 4-byte 16.16 (integer part at +2); M7_PV_ANGLE is 1 byte.
; WIDTH-RISK: A16/I16 entry/exit; A8 only for the 1-byte angle read.
; =============================================================================
save_overworld_camera:
    .a16
    .i16
    lda M7_PV_POSX + 2          ; integer camera X
    sta ovw_camx
    lda M7_PV_POSY + 2          ; integer camera Y
    sta ovw_camy
    sep #$20
    .a8
    lda M7_PV_ANGLE             ; facing (low byte)
    rep #$20
    .a16
    and #$00FF
    sta ovw_angle
    rts

; =============================================================================
; build_town_map — a DESIGNED, DENSE Mode 1 town: a fully COBBLED plaza (every
; floor cell explicitly set, not backdrop-fill) framed by brick walls, two brick
; buildings in the upper plaza + two in the lower courtyard, decorative torches,
; an inner GATE wall, and a gated EXIT gap. DRY plaza — NO water (the prior moat
; + fountain were never design intent and are removed). Carried finding F1
; (Sprint 0 audit): a dense 896-cell town does NOT tear under the forced-blank
; bracket — so this fills every cell. Re-expresses Phase 13's town SHAPE (a
; walled plaza with buildings + a southern gate); clean-room layout, no byte-copy.
;
; Tile legend (town_assets.inc): 1=cobble 2=brick 4=torch. NO WATER — this is a
; a dry walled plaza; the prior moat + fountain were never in the design
; intent and have been removed (the bottom quarter is now reclaimed as TOWN:
; brick walls + a lower courtyard + buildings, not empty space).
; Collision (town_collide / town_npc_adjacent) reads the shadow BG1 tilemap:
; BRICK blocks; cobble/torch walk. The NPC sprite sits on a torch cell at
; (TOWN_NPC_TX,TOWN_NPC_TY); that exact cell is also collision-blocked so the
; player stops adjacent.
; WIDTH-RISK: A16/I16 entry/exit. mset preserves A16/I16; the loop counters live
; in DP scratch (mset clobbers X/Y), no raw width toggles.
; =============================================================================
btm_i = $44                    ; map-build loop counter (per-scene scratch)
btm_j = $46

build_town_map:
    .a16
    .i16
    ; --- (1) DENSE cobble floor: fill the whole 32x28 visible grid with cobble.
    ;     This is the designed-dense base (F1 says it does not tear). Walls /
    ;     buildings then OVERWRITE specific cells below. ---
    stz btm_j                   ; row 0..27
btm_floor_rows:
    .a16
    stz btm_i                   ; col 0..31
btm_floor_cols:
    .a16
    mset #1, btm_i, btm_j, #TOWN_TILE_COBBLE
    lda btm_i
    inc a
    sta btm_i
    cmp #32
    bne btm_floor_cols
    lda btm_j
    inc a
    sta btm_j
    cmp #28
    bne btm_floor_rows

    ; --- (2) brick wall border (the room frame). The plaza now fills the FULL
    ;     32x28 grid (no water below): top row 0 + BOTTOM row 27 (full width),
    ;     then left col 0 + right col 31 down ALL 28 rows. The inner GATE wall
    ;     (row 21) + the gate gap are step (4)/(5). ---
    stz btm_i
btm_wall_h:
    .a16
    mset #1, btm_i, #0,  #TOWN_TILE_BRICK
    mset #1, btm_i, #27, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #32
    bne btm_wall_h
    lda #1
    sta btm_j
btm_wall_v:
    .a16
    mset #1, #0,  btm_j, #TOWN_TILE_BRICK
    mset #1, #31, btm_j, #TOWN_TILE_BRICK
    lda btm_j
    inc a
    sta btm_j
    cmp #27
    bne btm_wall_v

    ; --- (3) buildings (collidable BRICK blocks). The upper plaza keeps two
    ;     buildings (left 5x3 at (3..7,3..5); right 5x3 at (24..28,3..5)); the
    ;     LOWER courtyard (reclaimed from the old water band) gets two more
    ;     (left 5x2 at (3..7,23..24); right 5x2 at (24..28,23..24)) so the bottom
    ;     quarter reads as town buildings, not empty space. ---
    lda #3
    sta btm_j                   ; UPPER building rows 3..5
btm_bldg_rows:
    .a16
    lda #3
    sta btm_i                   ; left building cols 3..7
btm_bldg_left:
    .a16
    mset #1, btm_i, btm_j, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #8
    bne btm_bldg_left
    lda #24
    sta btm_i                   ; right building cols 24..28
btm_bldg_right:
    .a16
    mset #1, btm_i, btm_j, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #29
    bne btm_bldg_right
    lda btm_j
    inc a
    sta btm_j
    cmp #6
    bne btm_bldg_rows

    lda #23
    sta btm_j                   ; LOWER courtyard building rows 23..24
btm_bldg2_rows:
    .a16
    lda #3
    sta btm_i                   ; left lower building cols 3..7
btm_bldg2_left:
    .a16
    mset #1, btm_i, btm_j, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #8
    bne btm_bldg2_left
    lda #24
    sta btm_i                   ; right lower building cols 24..28
btm_bldg2_right:
    .a16
    mset #1, btm_i, btm_j, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #29
    bne btm_bldg2_right
    lda btm_j
    inc a
    sta btm_j
    cmp #25
    bne btm_bldg2_rows

    ; --- (4) inner GATE wall (row 21, full width) separating the upper plaza
    ;     (rows 1..20) from the lower courtyard (rows 22..26). The gate gap is
    ;     punched back to cobble in step (5). ---
    stz btm_i
btm_gate_wall:
    .a16
    mset #1, btm_i, #21, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #32
    bne btm_gate_wall

    ; --- (5) EXIT gate: punch a 1-tile cobble gap in the inner gate wall at
    ;     (TOWN_EXIT_TX, TOWN_EXIT_TY) so the player can step onto it to leave
    ;     (a wall gate, not a bridge over water). ---
    mset #1, #TOWN_EXIT_TX, #TOWN_EXIT_TY, #TOWN_TILE_COBBLE

    ; --- (6) decorative torches (lamps): one at each building edge, the NPC's
    ;     cell, and the known test cell (4,4), so the plaza reads as inhabited.
    ;     (These are real lamps — distinct from the phantom "!" that was the
    ;     avatar sprite drawn 32x32; that is fixed by the OBSEL 8/16 size above.) ---
    mset #1, #TOWN_NPC_TX, #TOWN_NPC_TY, #TOWN_TILE_TORCH
    mset #1, #4,  #4,  #TOWN_TILE_TORCH   ; (kept: an existing VRAM test reads this)
    mset #1, #8,  #5,  #TOWN_TILE_TORCH
    mset #1, #23, #5,  #TOWN_TILE_TORCH
    mset #1, #4,  #18, #TOWN_TILE_TORCH
    mset #1, #27, #18, #TOWN_TILE_TORCH
    ; --- (7) SAVE POINT landmark: a torch tile under the save sprite so the cell
    ;     reads as a real interactable (the cell is collision-blocked in
    ;     town_collide; the save NPC sprite is drawn on it by draw_town_sprites). ---
    mset #1, #TOWN_SAVE_TX, #TOWN_SAVE_TY, #TOWN_TILE_TORCH
    rts

; =============================================================================
; town_collide — return A=1 if town tile (X=tx, Y=ty) BLOCKS the player, else 0.
; Collision SSoT = the shadow BG1 tilemap (what is DRAWN is what blocks): BRICK
; (2) blocks; cobble/torch/empty walk. (No water in the dry plaza any more.) The
; NPC cell (TOWN_NPC_TX, TOWN_NPC_TY) is ALSO blocked so the player stops
; adjacent to the villager.
; Tiles out of the 0..31 grid block (the brick border already does, but guard).
; Entry: A16/I16, X=tx, Y=ty. Exit: A16 (0/1), I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 entry; computes the 16-bit byte index in A, toggles A8 for
; the 1-byte tilemap read, RESTORES A16 before every rts so the caller stays A16
; across the jsr (an A8 exit would assemble the caller's post-jsr 16-bit ops in
; the wrong width — the stray-third-byte=BRK silent-corruption class). The
; blocked/walkable branch targets carry explicit width annotations.
; =============================================================================
town_collide:
    .a16
    .i16
    ; off-grid -> blocked (guard; X/Y are 0..31 from town_try_step's clamps)
    cpx #32
    bcs tc_blocked_pre
    cpy #32
    bcs tc_blocked_pre
    ; NPC cell is blocked (separate equality check, like the overworld TERR_NPC)
    cpx #TOWN_NPC_TX
    bne tc_chk_save
    cpy #TOWN_NPC_TY
    bne tc_chk_save
    lda #1                      ; (tx,ty) == NPC cell -> blocked
    rts
tc_chk_save:
    .a16
    ; SAVE POINT cell is blocked too -> the player stops adjacent and presses A
    cpx #TOWN_SAVE_TX
    bne tc_not_npc
    cpy #TOWN_SAVE_TY
    bne tc_not_npc
    lda #1                      ; (tx,ty) == save-point cell -> blocked
    rts
tc_not_npc:
    .a16
    ; byte index = (ty*32 + tx) * 2  (ty<<5 | tx, then <<1 for 16-bit cells)
    tya
    asl a
    asl a
    asl a
    asl a
    asl a                       ; ty * 32
    sta neigh_tile              ; stash the row base
    txa
    ora neigh_tile             ; + tx -> cell index
    asl a                       ; * 2 (each tilemap cell is a 16-bit word)
    tax                         ; X = byte offset into the shadow BG1 tilemap
    sep #$20
    .a8
    lda f:$7E0000 + SHADOW_BG1_TILEMAP, x   ; low byte = tile id (long w/ bank)
    rep #$20
    .a16
    and #$00FF                  ; A = tile id (zero-extended)
    cmp #TOWN_TILE_BRICK         ; brick walls/buildings block; cobble/torch walk
    beq tc_blocked
    lda #0                      ; walkable
    rts
tc_blocked:
    .a16
    lda #1
    rts
tc_blocked_pre:
    .a16
    lda #1
    rts

; =============================================================================
; town_try_step — move the town player ONE tile in (X=dx, Y=dy) IF the
; destination is walkable (town_collide). X/Y are signed 16-bit tile deltas
; (-1/0/+1). Walkable -> commit town_px/town_py. Blocked -> no-op (a press into
; a wall does nothing). Destination is clamped to the 0..31 grid.
; Entry: A16/I16, X=dx, Y=dy. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry/exit. town_collide returns A16; the dest scratch is
; computed in A16 throughout.
; =============================================================================
town_try_step:
    .a16
    .i16
    ; dest tile = (town_px + dx, town_py + dy), clamped to 0..31
    txa                         ; A = dx (signed)
    clc
    adc town_px
    and #$001F                  ; wrap/clamp to 0..31 (the room is 32 wide)
    sta town_dtx
    tya                         ; A = dy
    clc
    adc town_py
    and #$001F
    sta town_dty
    ; collision query (X=dtx, Y=dty)
    ldx town_dtx
    ldy town_dty
    jsr town_collide            ; A = 1 blocked / 0 walkable
    cmp #1
    beq tts_blocked
    ; walkable -> commit
    lda town_dtx
    sta town_px
    lda town_dty
    sta town_py
    rts
tts_blocked:
    .a16
    rts                         ; blocked -> player does not move

; =============================================================================
; town_npc_adjacent — set town_near=1 if the player tile is a 4-neighbour of the
; NPC tile (TOWN_NPC_TX, TOWN_NPC_TY), else 0. Manhattan distance == 1 on the
; grid. Used to gate the prompt indicator + the A dialog interaction.
; Entry/Exit: A16/I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 throughout — pure 16-bit compares, no width toggle.
; =============================================================================
town_npc_adjacent:
    .a16
    .i16
    stz town_near
    ; dx = |town_px - NPC_TX| ; dy = |town_py - NPC_TY| ; adjacent iff dx+dy==1
    ; East/West neighbour: same row, |dx|==1
    lda town_py
    cmp #TOWN_NPC_TY
    bne tna_chk_vert
    ; same row -> check |town_px - NPC_TX| == 1
    lda town_px
    sec
    sbc #TOWN_NPC_TX            ; px - NPC_TX
    cmp #1
    beq tna_found
    cmp #$FFFF                  ; -1 (px = NPC_TX - 1)
    beq tna_found
    rts
tna_chk_vert:
    .a16
    ; North/South neighbour: same column, |dy|==1
    lda town_px
    cmp #TOWN_NPC_TX
    bne tna_done
    lda town_py
    sec
    sbc #TOWN_NPC_TY
    cmp #1
    beq tna_found
    cmp #$FFFF
    beq tna_found
tna_done:
    .a16
    rts
tna_found:
    .a16
    lda #1
    sta town_near
    rts

; =============================================================================
; town_save_adjacent — set town_save_near=1 if the player tile is a 4-neighbour
; of the SAVE POINT tile (TOWN_SAVE_TX, TOWN_SAVE_TY), else 0. Same Manhattan-1
; test as town_npc_adjacent, for the save-point interaction.
; Entry/Exit: A16/I16. Clobbers A, X.
; WIDTH-RISK: A16/I16 throughout — pure 16-bit compares, no width toggle.
; =============================================================================
town_save_adjacent:
    .a16
    .i16
    stz town_save_near
    lda town_py
    cmp #TOWN_SAVE_TY
    bne tsa_chk_vert
    lda town_px
    sec
    sbc #TOWN_SAVE_TX
    cmp #1
    beq tsa_found
    cmp #$FFFF
    beq tsa_found
    rts
tsa_chk_vert:
    .a16
    lda town_px
    cmp #TOWN_SAVE_TX
    bne tsa_done
    lda town_py
    sec
    sbc #TOWN_SAVE_TY
    cmp #1
    beq tsa_found
    cmp #$FFFF
    beq tsa_found
tsa_done:
    .a16
    rts
tsa_found:
    .a16
    lda #1
    sta town_save_near
    rts

; =============================================================================
; show_town_dialog — open the dialog box via sf_dialog: draw the OPAQUE windowed
; nine-patch panel into the BG3 SHADOW (sf_dialog_open), then print the authored
; dialog text on BG3 ON TOP. The panel HIDES the town behind the box (a real
; SNES-RPG window, not the old ASCII-art frame the scene showed through): every
; panel cell is an opaque BG3 tile carrying the per-tile PRIORITY bit, so under
; BGMODE $09 the box composites above BG1/BG2/OBJ and the print text composites
; above the box. Called once on OPEN.
; Entry/Exit: A16/I16. Clobbers A, X, Y + the engine text + dialog scratch.
; WIDTH-RISK: A16/I16 entry; sf_dialog_open + the print macros run their own
; widths and return A16/I16. No raw width toggles here.
; =============================================================================
show_town_dialog:
    .a16
    .i16
    ; sf_dialog_open draws the OPAQUE nine-patch panel into the BG3 shadow (above
    ; BG1/BG2/OBJ via the per-tile priority bit). The 3 authored dialog lines then
    ; print on BG3 ON TOP (the kit print composites above the box). Text is inset
    ; 2 leading spaces so the first glyph 'W' lands a couple cells in from the
    ; frame; the opaque box provides the real window frame (no ASCII rails).
    sf_dialog_open #DLG_PANEL_COL, #DLG_PANEL_ROW, #DLG_PANEL_W, #DLG_PANEL_H
    print str_dlg_l0, #DLG_TEXT_X, #DLG_TEXT_Y0
    print str_dlg_l1, #DLG_TEXT_X, #(DLG_TEXT_Y0 + DLG_TEXT_DY)
    print str_dlg_l2, #DLG_TEXT_X, #(DLG_TEXT_Y0 + 2 * DLG_TEXT_DY)
    rts

; =============================================================================
; hide_town_dialog — close the box: sf_dialog_close clears the BG3 panel rect
; (fill + border AND the dialog text printed inside it) back to the transparent
; blank, using the last-opened geometry. The NMI commits the cleared BG3 shadow
; next frame -> box + text disappear, town restored.
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; sf_dialog_close runs its own widths, returns A16/I16.
; =============================================================================
hide_town_dialog:
    .a16
    .i16
    ; sf_dialog_close clears the panel region of the BG3 shadow back to the kit
    ; transparent blank (using the last-opened geometry). Because the dialog TEXT
    ; was printed inside that same panel rect on BG3, clearing the panel cells also
    ; removes the text — one call restores the scene. The NMI commits next VBlank.
    sf_dialog_close
    rts

; =============================================================================
; draw_town_sprites — draw the town avatar (OAM 0) at its tile position and the
; villager NPC (OAM 1) at its fixed tile. The avatar MOVES (sprite position =
; tile*8); the NPC is fixed. NO floating prompt: SNES-era RPGs used walk-up +
; adjacency + A, never a "!" hovering over an NPC. The interaction logic is
; UNCHANGED (town_npc_adjacent sets town_near; A while adjacent opens the dialog
; in scene_town_tick) — only the anachronistic indicator GLYPH is removed. So
; only slots 0 (avatar) + 1 (NPC) are drawn; spr_clear parks the rest at Y=$F0,
; so OAM slot 2 stays CULLED even when the player is adjacent to the villager.
; Entry/Exit: A16/I16. Clobbers A, X, Y.
; WIDTH-RISK: A16/I16 entry; spr/spr_clear run their own widths and return A16.
; =============================================================================
draw_town_sprites:
    .a16
    .i16
    spr_clear
    ; --- OAM 0: the avatar (16x16, OBJ palette 0) at (town_px*8, town_py*8) ---
    lda town_px
    asl a
    asl a
    asl a                       ; town_px * 8 -> screen X
    sta tgt_tx                  ; reuse scratch for the spr operand
    lda town_py
    asl a
    asl a
    asl a                       ; town_py * 8 -> screen Y
    sta tgt_ty
    spr #AVATAR_TILE, tgt_tx, tgt_ty, #TOWN_AV_PAL, #2
    ; --- OAM 1: the villager NPC (16x16) at its fixed tile, drawn one tile UP so
    ;     the 16x16 sprite body sits over the torch cell + the cell above it. ---
    spr #AVATAR_TILE, #(TOWN_NPC_TX * 8), #(TOWN_NPC_TY * 8), #TOWN_AV_PAL, #2
    ; --- OAM 2: the SAVE POINT attendant (16x16) at the save tile — a visible
    ;     landmark the player walks up to and presses A on to save the game. ---
    spr #SAVE_SPRITE_TILE, #(TOWN_SAVE_TX * 8), #(TOWN_SAVE_TY * 8), #TOWN_AV_PAL, #2
    rts

; =============================================================================
; Town dialog strings (clean-room ORIGINAL text — NUL-terminated ASCII the BG3
; font renders, chars $20-$7F). NO ASCII rails/border: the OPAQUE sf_dialog
; nine-patch panel provides the real windowed frame, and these lines print ON
; TOP. Each line is inset 2 leading spaces so the first glyph 'W' lands at tile
; col 5 (DLG_TEXT_X=24 -> col 3, + 2 spaces) inside the panel border.
; =============================================================================
str_dlg_l0:   .byte "  WELCOME, TRAVELLER!", 0
str_dlg_l1:   .byte "  REST HERE A WHILE, THE", 0
str_dlg_l2:   .byte "  ROAD AHEAD IS LONG.", 0
; save-point confirmation (shown by do_save_town after sf_save writes slot 0)
str_saved:    .byte "  GAME SAVED.", 0

; =============================================================================
; build_battle_map — like the town but the floor backdrop is WATER-blue (set in
; the init), so a screenshot reads instantly different (a blue battle field vs
; the gray cobble town). A torch at (4,4) too (the test reads the same cell).
; WIDTH-RISK: A16/I16 entry/exit (same sparse contract as build_town_map).
; =============================================================================
build_battle_map:
    .a16
    .i16
    ; brick frame: top + bottom row (full width)
    stz btm_i
bbm_wall_h:
    .a16
    mset #1, btm_i, #0,  #TOWN_TILE_BRICK
    mset #1, btm_i, #21, #TOWN_TILE_BRICK
    lda btm_i
    inc a
    sta btm_i
    cmp #32
    bne bbm_wall_h
    ; left + right columns (rows 1..20)
    lda #1
    sta btm_j
bbm_wall_v:
    .a16
    mset #1, #0,  btm_j, #TOWN_TILE_BRICK
    mset #1, #31, btm_j, #TOWN_TILE_BRICK
    lda btm_j
    inc a
    sta btm_j
    cmp #21
    bne bbm_wall_v

    ; a cobble platform band across the middle (a battle "arena floor" line)
    stz btm_i
bbm_floor:
    .a16
    mset #1, btm_i, #14, #TOWN_TILE_COBBLE
    lda btm_i
    inc a
    sta btm_i
    cmp #32
    bne bbm_floor

    mset #1, #4, #4, #TOWN_TILE_TORCH
    mset #1, #27, #4, #TOWN_TILE_TORCH
    rts

; =============================================================================
; Scene table (sf_scene) — declares id -> (init, tick) and emits the tick jump
; table. Must be in CODE/RODATA; placed next to the scene bodies.
; =============================================================================
    sf_scene_begin SCENE
    sf_scene SC_OVERWORLD, scene_overworld_init, scene_overworld_tick
    sf_scene SC_TOWN,      scene_town_init,      scene_town_tick
    sf_scene SC_BATTLE,    scene_battle_init,    scene_battle_tick
    sf_scene_end

; =============================================================================
; Engine includes — the sf_mode7 link-partner order + the sprite/BG/DMA engines
; the macros JSR into, plus the TAD bridge for audio.
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
.include "text_engine.asm"      ; engine_print / engine_bg3_clear_rows (BG3 dialog)
.include "sf_text_data.inc"     ; built-in 8x8 font + decimal routine (sf_text.inc)
.include "sf_dialog_data.inc"   ; sf_dialog EMITTED half: box CHR + draw/clear procs
.include "sf_mosaic_transition_data.inc" ; sf_mosaic_transition EMITTED half: curves + stepper
.include "save_load_engine.asm" ; sf_save EMITTED half: engine_save/load + CRC table
.include "tad_bridge.asm"

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
; --- horizon-fog link partners (sf_fx.inc order: alloc -> hdma -> color; the
;     color engine pulls gradient_ease_lut.inc itself). colormath is order-free. ---
.include "hdma_engine.asm"      ; channel wrapper + _hdma_enable_channel
.include "hdma_color_engine.asm"; RGB gradient builders (gradient_rgb)
.include "colormath_engine.asm" ; engine_color_math_on/tint (shadow-only; NMI commits)
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- first-party assets (committed generator output; see assets/*.py) ---
.include "assets/ovw_palette.inc"
.include "assets/town_assets.inc"

; --- the parallel overworld collision/terrain table (16KB) + TERR_*/spawn/town
;     equates. Parked in its OWN bank (ROM3, COLLISION segment) so bank 0's
;     CODE+RODATA has room for the horizon-fog gradient + color-math engines
;     (RODATA would otherwise overflow ROM0 by ~3.3KB). The movement code reads
;     it with long addressing by (ty*128 + tx) — `lda f:ovw_collision,x` — so the
;     bank is immaterial; the 16KB max index ($3FFF) stays inside the one bank.
;     The TERR_*/spawn/NPC equates are assemble-time, segment-independent. ---
.segment "COLLISION"
.include "assets/ovw_collision.inc"
.segment "CODE"

; --- the 32KB interleaved overworld-map blob (bank 1 of the 64KB image) ---
; .incbin path (GAP-3): ca65 resolves .incbin relative to the INCLUDING FILE's
; directory (NOT via -I, which covers .include only), so "assets/<basename>" is
; copy-safe — copying templates/rpg/ -> templates/<theme>/ only needs the
; basename changed (ovw_map.bin -> <theme>_map.bin), never the directory.
.segment "BANK1"
ovw_map:
    .incbin "assets/ovw_map.bin"
