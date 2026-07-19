; =============================================================================
; platformer — the flagship rail: a complete little platformer, start to restart
; =============================================================================
; A side-scrolling platform game in one playable loop: walk and jump a hero
; across a 512x224 level, collect all the coins to WIN, stomp or dodge two
; patrol ghosts, and don't fall in a pit. It composes the whole kit:
;   SCENES   title -> game -> game-over / win -> SOFT RESTART back to title
;            (no power cycle: each scene init re-builds exactly what it owns)
;            via sf_scene: a declared id->init/tick table, sf_scene_goto
;            transitions, sf_scene_dispatch at the loop top.
;   WORLD    512x224 scrolling level (sf_level) with camera follow; solid
;            terrain, ONE-WAY platforms, two PITS; coins as flagged tiles.
;   ACTORS   animated hero (16x16, H-flip facing, 8x8 physics box) + two
;            patrol ghosts — one on a ledge crossing the world's page seam
;            (sf_level_patrol_step); stomp to defeat.
;   PHYSICS  variable-height jump (sf_jump_cut), landing snap, head bump,
;            one-way platforms, pit death plane (sf_pit).
;   AUDIO    music per scene + SFX (jump / coin / hurt / stomp) over the TAD
;            bridge — this ROM uses the audio build shape (sf_audio.inc):
;            lorom_tad_sram.cfg + the two TAD objects (see the Makefile rule).
;   HUD      LIVES + COINS counters, reprint-on-change.
;   LOOK     BG2 parallax skyline (2 bands: far clouds 0.125, near hills 0.375
;            of camera X via sf_parallax_bands), a dusk-sky RGB gradient on the
;            backdrop (sf_gradient_rgb + sf_colormath_on), and a fade-in on
;            every scene transition (sf_bright_fade) — see the LOOK & FEEL map
;            below for the VRAM/CGRAM/channel layout.
;   SAVE     battery-SRAM "continue" (sf_save, slot 0) — see the SAVE / CONTINUE
;            design block below.
;
; Rules: collect ALL the coins to WIN. Touching a ghost from the side or
; falling into a pit costs a life (3); at zero, GAME OVER. Stomping a ghost
; (land on its head) defeats it. START on the title begins; START in a game
; PAUSES it; START on game-over/win returns to the title; every new game fully
; resets (level reloaded — coins return; ghosts revive). GAME OVER with coins
; collected BANKS them to battery SRAM; the title then offers SELECT = CONTINUE,
; which starts a fresh level (3 lives, coins respawned) with the banked coin
; count restored — you only need the remaining coins to win.
;
; =============================================================================
; SAVE / CONTINUE — design (deliberately minimal; the demand is "continue")
; =============================================================================
; SAVE POINT — game over, and only with a non-empty coin bank. Rationale:
;   a WIN completes the loop (nothing left to resume) and a zero-coin death
;   continues identically to a new game, so neither writes a save. The one
;   moment a player loses progress worth keeping is dying with coins banked
;   — that is the save: slot 0, version 1, payload = the 16-bit COINS word
;   (2 bytes). LIVES are NOT saved: a continue always grants the fresh 3
;   (continuing with 0 lives would be unplayable).
; CONTROLS — on the title, START = new game (always, save or no save);
;   SELECT = continue, offered on-screen ("SELECT: CONTINUE") only when
;   slot 0 holds a valid save in THIS format. The line is the only UI.
; VALIDITY GATE (cont_gate below) — sf_save_exists (magic + CRC) first;
;   then version and payload-length from the slot header, which is
;   CRC-proven once exists answers 1. Corrupt, cleared, virgin, wrong-
;   version, or wrong-length slots all fall back to plain new-game
;   semantics: no CONTINUE line, SELECT inert. The continue path itself
;   re-checks the sf_load return code and restores ONLY on a full match —
;   a rejected load changes nothing (the fresh-run defaults already stand),
;   so a half-restored state is impossible by construction.
; BUILD SHAPE — audio + battery saves: lorom_tad_sram.cfg (the TAD banks
;   plus the SRAM window; see that cfg's header for the story) + the
;   save/load engine include at the bottom of this file.
;
; SOFT-RESTART CONTRACT (the scene-flow pattern): NEVER re-run sf_coldstart
; or sf_audio_init mid-game (the S-SMP is no longer in IPL state; the PPU is
; live). A scene init re-builds only what it owns: text rows (sf_text_clear),
; sprites (spr_clear), its game state, the level (sf_level_load re-msets
; both pages — coins respawn), and the music (sf_music switches songs).
;
; Controls:
;   D-pad left/right   walk                 A or B          jump (hold = higher)
;   START (in game)    pause / unpause      START (menus)   begin / back to title
;   SELECT (title)     continue from the banked save (only when it is offered)
;
; File layout (top to bottom; the major === section banners):
;   INIT             — RESET: one-time uploads, PPU + look-&-feel, boot to title
;   MAIN LOOP        — game_loop, the once-per-frame heartbeat (read this first)
;   PER-FRAME UPDATE — menu_tick / game_tick (one frame of the current scene)
;   SUBROUTINES      — scene inits, life/respawn, the menu BG reset, cont_gate
;   DATA             — strings, the level map, tile + sky art, engine includes
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Tile IDs: 1 ground (SOLID), 2 ledge (SOLID), 3 one-way platform
; (PLATFORM), 4 coin (flag $04 = bit 2 — walk-through, picked up on touch).
;
; Build:  make platformer      (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad_sram.cfg
;   ^ Linker-config sentinel: the audio + battery-save link shape — TAD audio
;     banks + the SRAM window for save/continue. The generic build/%.sfc rule
;     reads this and links lorom_tad_sram.cfg (a *_tad*.cfg name also pulls in
;     the TAD audio objects + the audio include path) instead of the default
;     lorom.cfg; copy-to-adapt keeps the line, no Makefile edit needed.
;     (See docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SUPER KIT QUEST"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"
.include "sf_text.inc"
.include "sf_anim.inc"
.include "sf_enemy.inc"         ; sf_stomp_check (actor-vs-actor: world-agnostic)
.include "sf_level.inc"         ; level world + integrator + seam patrol
.include "sf_frame.inc"
.include "sf_scene.inc"         ; scene state machine + dispatch (this game's
                                ;   scene flow is the pattern it formalizes)
.include "sf_save.inc"          ; battery-SRAM coin bank (save / continue)
.include "sf_fx.inc"            ; parallax bands, RGB gradient, color math,
                                ;     brightness fades (the look-&-feel group)
.include "engine_state.inc"
.include "tad-audio.inc"
.include "tad_audio_enums.inc"
.include "sf_audio.inc"

; --- palette colors (BG palette 0; BGR15) ---
BG_BROWN = $11B7                ; dirt body (index 1)
BG_GREEN = $03E0                ; platform body (index 2)
BG_GOLD  = $03FF                ; coin body (index 3)
GRASS_GREEN = $1726             ; grass top + platform edge (index 4)
DIRT_DARK   = $090F             ; dirt speckle / shading (index 5)
COIN_HI     = $4BFF             ; coin highlight (index 6)

; =============================================================================
; LOOK & FEEL — VRAM / CGRAM / HDMA-channel map (re-check before reusing a channel!)
; =============================================================================
; VRAM (words):
;   $0000-$0FFF  OBJ CHR (hero + ghost, OBSEL name base 0)
;   $2000-$27FF  BG1 CHR (game tiles 0-79; font tiles 80-127, sf_text)
;   $4000-$403F  BG2 CHR (sky tiles 1-3, BG12NBA=$42 engine default)
;   $4400-$47FF  BG2 SKY TILEMAP (32x32, STATIC — uploaded once at init;
;                BG2SC repointed to $44 below)
;   $5800-$5FFF  BG1 64x32 level tilemap (page 0 $5800 / page 1 $5C00).
;                CRITICAL: the engine's BG2 *shadow/DMA machinery* transports
;                BG1's page 1 to $5C00 (sf_level.inc) — it is OFF-LIMITS for
;                the sky. The sky tilemap bypasses it entirely: one CPU upload
;                under forced blank, never touched again (parallax moves the
;                layer with HOFS only, no tilemap rewrites).
;   $6000-$63FF  BG3 text tilemap;  $A000+ BG3 font CHR
; CGRAM:
;   0-15    BG palette 0 — BG1 level tiles (slots 1-6 below: dirt, platform,
;           coin, grass, dirt-speck, coin-highlight)
;   32-47   BG palette 2 — BG2 sky (slot 1 cloud, slot 2 silhouette).
;           Palette 1 is intentionally SKIPPED: its entries 28-31 alias BG3
;           palette 7 — entry 31 is the text colour (sf_text.inc).
;   128+    OBJ palettes 0 (hero) and 1 (ghost)
; HDMA channels (allocator pool 3..7; CH0/CH1 reserved by hdma_alloc_init):
;   1 channel  — sf_parallax_bands on BG2 ($43n0 -> BG2HOFS, write-twice)
;   3 channels — sf_gradient_rgb (COLDATA r/g/b dusk ramp)
;   = 4 of 5 pool channels; no Mode 7 in this template (gradient would refuse
;   to arm if there were — shared table region).
; COMPOSITION (the dusk look): sf_colormath_on #1, #$20 = ADD the fixed
; colour on the BACKDROP ONLY. The gradient drives COLDATA per scanline, so
; every backdrop pixel (open sky, the valley gaps between hills) renders the
; warm-top -> dark-bottom ramp; BG2 cloud/silhouette pixels sit in front
; un-mathed; BG1/BG3/OBJ are untouched (HUD text stays full white). The
; gradient is STATIC (no sf_gradient_phase) — the parallax freeze invariant
; ("standing still => sky pixels byte-identical") includes the backdrop.
; =============================================================================
SKY_CLOUD = $525C               ; dusk-lit cloud (warm cream/pink)
SKY_SILH  = $2846               ; skyline silhouette (dark purple)

PLX_YSPLIT = 96                 ; band split: clouds above, hills below
PLX_RTOP   = $0020              ; far clouds: 32/256 = 0.125 of camera X
PLX_RBOT   = $0060              ; near hills: 96/256 = 0.375 of camera X

DUSK_TOP_R = 24                 ; warm orange top of the ramp
DUSK_TOP_G = 8
DUSK_TOP_B = 2
DUSK_BOT_R = 2                  ; deep blue-purple bottom
DUSK_BOT_G = 0
DUSK_BOT_B = 12

FADE_FRAMES = 36                ; scene fade-in length

; --- world geometry ---
SPAWN_X   = 24                  ; player spawn column (px), left end of the ground
SPAWN_Y   = 184                 ; ground row 24: top 192, box rest 184
COIN_FLAG = $04                 ; tile flag bit 2 (walk-through pickup)
TOTAL_COINS = 6
G1_Y      = 184                 ; ghost 1: ground beat (box rest)
G2_Y      = 120                 ; ghost 2: seam ledge row 16 (box rest)
G1_START_X = 112                ; ghost 1 initial column (on the ground)
G2_START_X = 240                ; ghost 2 initial column (on the seam ledge)
GHOST1_MIN_X = 64               ; ghost 1 turns here going west, so its ground
                                ;   beat never reaches the spawn (a fair start)
BLINK_PHASE  = $04              ; i-frame blink mask on the counting-down timer:
                                ;   hidden while (HURTLOCK & $04) -> ~4 on / 4 off
PIT_DEATH_Y  = 216              ; box y past this = fallen below the ground plane
DEATHBEAT_FRAMES = 24           ; pit-death pause (frames the fall holds on screen
                                ;   before the respawn — a beat, not a teleport)
SPAWN_GRACE    = 60             ; i-frames granted at the start of a fresh level
RESPAWN_IFRAMES = 90            ; i-frames granted on a mid-level respawn
HERO_TITLE_X = 120              ; title-card hero pose: screen x (centered-ish)
HERO_TITLE_Y = 168              ; ...and screen y, below the menu text lines

; --- scenes ---
SC_TITLE = 0
SC_GAME  = 1
SC_OVER  = 2
SC_WIN   = 3

; --- sf_stomp_check result codes (returned in A) ---
STOMP_RESULT = 1                ; landed on the enemy's head — it dies, we bounce
HURT_RESULT  = 2                ; side or from-below contact — the player is hit

; --- save format (slot 0; see the SAVE / CONTINUE design block above) ---
SAVE_VER = 1                    ; bump when the payload layout changes
SAVE_LEN = 2                    ; payload = the 16-bit COINS word

; --- OBJ VRAM + sprite attributes (the spr macro's flags word) ---
HERO_BASE  = 0                  ; 4 frames @ 16x16 -> tiles 0-15
GHOST_BASE = 16                 ; 4 frames @ 16x16 -> tiles 16-31
SPR_LARGE  = $0080              ; spr flags: 16x16 sprite (bit 7)
SPR_HFLIP  = $0040              ; spr flags: horizontal flip (face left)
GHOST_ATTR = $0082              ; ghost spr flags: large + OBJ palette 1 ($02)
OFFSCREEN_Y = $00E0             ; y to park a dead/unused sprite below the screen

; --- DP state ($32-$5F) ---
PX       = $32                  ; player world x (8x8 physics box)
PYF      = $34                  ; player y 8.8
VY       = $36
NEWY     = $38
GROUNDED = $3A
CORNX    = $3C                  ; level prober scratch (also draw scratch)
CORNY    = $3E
LVAR     = $40
E1X      = $42                  ; ghost 1 (ground beat)
E1D      = $44
E2X      = $46                  ; ghost 2 (seam ledge)
E2D      = $48
ENEWX    = $4A                  ; patrol scratch (shared)
ELEADX   = $4C
EFOOTY   = $4E
ELVAR    = $50
CAMX     = $52
CAMY     = $54
FACING   = $56                  ; 0 right / 1 left
ATICK    = $58                  ; shared anim clock (player + ghosts)
AFRAME   = $5A
PIXY     = $5C                  ; player pixel y (post-physics, drawn)
SCRATCH  = $5E                  ; transient (coin tile math)

; --- game state (the $1800-$1DFF region; TAD owns $1DE0+) ---
LIVES    = $1800
COINS    = $1802
SCENE    = $1804                ; scene-state word — bound to sf_scene below;
                                ;   written ONLY via sf_scene_goto
SDIRTY   = $1806                ; HUD reprint flag
E1ALIVE  = $1808
E2ALIVE  = $180A
HURTLOCK = $180C                ; i-frames after a hit/respawn
CONTOK   = $180E                ; title: 1 = slot 0 is continuable (set by
                                ;   cont_gate on every title entry)
CONTPEND = $1810                ; menu -> scene_game: 1 = SELECT continue
                                ;   chosen (consumed by the game init)
PAUSED   = $1812                ; 1 = gameplay frozen (START toggles it)
LIVES_STR = $1814               ; 2-byte HUD buffer: LIVES as 1 ASCII digit + NUL
DEATHBEAT = $1816               ; >0 = pit-fall death pause counting down to respawn
SAVEBUF  = $1900                ; sf_load staging (SAVE_LEN bytes used).
                                ;   Deliberately NOT COINS itself, and placed
                                ;   with headroom: cont_gate proves the length
                                ;   is SAVE_LEN before any load, but staging
                                ;   keeps even a never-expected oversize
                                ;   payload off the live game state

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, look-&-feel)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    jsr hdma_alloc_init         ; HDMA allocator baseline (reserves CH0/CH1)
    sf_audio_init               ; ONCE, at boot (never on soft restart)

    ; --- one-time uploads under the coldstart forced blank ---
    sf_load_bg_tile 1, ground_tile  ; grass-topped surface (also the ledges)
    sf_load_bg_tile 2, ground_tile  ; ledge = same grass surface as the ground
    sf_load_bg_tile 3, plat_tile    ; mossy one-way platform
    sf_load_bg_tile 4, coin_tile    ; coin roundel
    sf_load_bg_tile 5, dirt_tile    ; ground interior (below the grass surface)
    ; one BG palette, distinct CHR color indices per tile kind (raw tile
    ; IDs from sf_level_load always select palette 0 — see sf_bg.inc)
    sf_bg_color 0, 1, BG_BROWN  ; dirt body (index 1)
    sf_bg_color 0, 2, BG_GREEN  ; platform body (index 2)
    sf_bg_color 0, 3, BG_GOLD   ; coin body (index 3)
    sf_bg_color 0, 4, GRASS_GREEN ; grass + platform edge (index 4)
    sf_bg_color 0, 5, DIRT_DARK   ; dirt speckle (index 5)
    sf_bg_color 0, 6, COIN_HI     ; coin highlight (index 6)
    sf_text_init
    sf_load_obj_chr HERO_BASE,  hero_chr,  hero_chr_bytes
    sf_load_obj_chr GHOST_BASE, ghost_chr, ghost_chr_bytes
    sf_load_obj_pal 0, hero_pal
    sf_load_obj_pal 1, ghost_pal

    ; --- BG2 sky uploads (still under the coldstart forced blank) ---
    sf_bg_color 2, 1, SKY_CLOUD ; BG palette 2 (see the CGRAM map above)
    sf_bg_color 2, 2, SKY_SILH

    ; sky CHR: tiles 1-3 (3 x 32 bytes, contiguous) -> BG2 CHR base + tile 1
    sep #$20
    .a8                         ; the 65816's accumulator is 8- or 16-bit, chosen
                                ;   by sep/rep at runtime. .a8/.a16 tell the
                                ;   assembler which width the CPU is in here so it
                                ;   encodes each op right; the linter checks these
                                ;   match (.claude/rules/width-tracking.md).
    lda #$80
    sta $2115                   ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #($4000 + 1 * 16)
    sta $2116                   ; VMADD = BG2 CHR word base + tile 1
    ldx #$0000
@sky_chr_up:
    lda f:sky_tiles, x
    sta $2118                   ; VMDATA (VRAM data port): write a word, VMADD++
    inx
    inx
    cpx #(3 * 32)
    bne @sky_chr_up

    ; sky tilemap: 32x32 words to $4400, generated from the 8-column-periodic
    ; per-row pattern table (sky_pattern: 32 rows x 8 bytes, tile id per
    ; col&7). Non-zero tiles get palette 2 ($0800 in the map word).
    lda #$4400
    sta $2116                   ; VMADD = BG2 sky tilemap base
    stz CORNX                   ; linear cell index 0..1023 (DP scratch,
                                ;   free before the game starts)
@sky_map_up:
    lda CORNX
    lsr
    lsr
    and #$00F8                  ; (idx>>5)*8 = row*8  (col>>2 bits masked off)
    sta SCRATCH
    lda CORNX
    and #$0007                  ; col & 7
    ora SCRATCH
    tax
    lda f:sky_pattern, x
    and #$00FF
    beq @sky_map_w              ; tile 0 -> transparent, no palette bits
    ora #$0800                  ; palette 2
@sky_map_w:
    .a16
    sta $2118                   ; VMDATA: word write, VMADD++
    lda CORNX
    inc a
    sta CORNX
    cmp #1024
    bne @sky_map_up

    jsr init_ppu
    gfxmode #1
    sf_level_init

    ; --- give BG2 its own display surface + put it on the main screen.
    ; sf_level_init left TM=$15 (BG2 layer off — its SHADOW machinery is the
    ; level's page-1 transport into $5C00). The sky lives at $4400, so
    ; repointing BG2SC and enabling the layer is safe: the engine's BG2
    ; shadow DMA keeps writing $5C00 (BG2_TILEMAP_VRAM_HI), never $4400. ---
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; INIDISP (display control): forced blank on, so
                                ;   the BG2SC write below lands outside active display
    lda #$44
    sta $2108                   ; BG2SC: sky tilemap word $4400, 32x32
    lda #$17
    sta SHADOW_TM               ; OBJ + BG3 + BG2 + BG1 (NMI sustains it)
    sta $212C                   ; TM (main-screen layer enable): show those layers
    lda SHADOW_INIDISP
    sta $2100                   ; INIDISP: restore display (forced blank off)
    rep #$20
    .a16
    sf_tile_flags 1, SF_FLAG_SOLID
    sf_tile_flags 2, SF_FLAG_SOLID
    sf_tile_flags 3, SF_FLAG_PLATFORM
    sf_tile_flags 4, COIN_FLAG
    sf_tile_flags 5, SF_FLAG_SOLID  ; dirt interior collides exactly like ground

    rep #$30
    .a16
    .i16
    stz CAMX
    stz CAMY
    stz ATICK
    stz AFRAME
    spr_clear

    ; --- arm the look-&-feel HDMA effects (once, at boot — there is no
    ; per-effect parallax teardown; see sf_fx.inc TEARDOWN note). The NMI
    ; re-arms $420C from NMI_HDMA_ENABLE every VBlank from here on.
    ; ORDER MATTERS: the GRADIENT must arm FIRST. Its engine builder writes
    ; the three COLDATA tables at FIXED WRAM addresses $C000/$C1C4/$C388
    ; (it assumes it owns CH3-CH5), while parallax places its table by
    ; CHANNEL SLOT (_hdma_table_addrs). Gradient-first → it gets CH3-CH5
    ; (registers match its fixed tables); parallax then gets CH6 (slot
    ; $CC00, clear of the gradient's $C000-$C54B). Parallax-first would put
    ; the parallax table in CH3's slot $C000 — the first sf_parallax_tick
    ; rebuild stomps the red gradient table (observed: dusk loses its warm
    ; channel the moment gameplay starts). ---
    sf_colormath_on #1, #$20    ; ADD fixed colour on the BACKDROP only
    sf_gradient_rgb #DUSK_TOP_R, #DUSK_TOP_G, #DUSK_TOP_B, #DUSK_BOT_R, #DUSK_BOT_G, #DUSK_BOT_B
    scroll #2, CAMX, #0         ; world-X feed: SHADOW_BG2HOFS = camera X (0)
    sf_parallax_bands #2, #PLX_YSPLIT, #PLX_RTOP, #PLX_RBOT

    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMITIMEN: enable VBlank NMI ($80) + auto-joypad
                                ;   read ($01) — the frame heartbeat starts here
    rep #$30
    .a16
    .i16

    sf_scene_goto SC_TITLE      ; boot lands on the title

; =============================================================================
; MAIN LOOP — the once-per-frame heartbeat; dispatches to the current scene
; =============================================================================
game_loop:
    sf_frame_begin
    sf_audio_tick               ; every frame, every scene
    sf_bright_fade_tick         ; scene fade-in stepper; ~35 cyc when idle,
                                ;   measured (tests/test_platformer_cycles.py)

    ; shared anim clock (player idle + ghosts share the 4-step rate)
    sf_anim_step ATICK, AFRAME, #8, #4

    sf_scene_dispatch           ; jsr the current scene's tick (table below)
    jmp game_loop

; =============================================================================
; PER-FRAME UPDATE — the two scene ticks (menu_tick handles INPUT for the
; menus; game_tick runs one frame of INPUT -> physics -> combat -> DRAW)
; =============================================================================
; -----------------------------------------------------------------------------
; menu tick (title + over + win): text-only (sprites cleared); START routes
; by scene; SELECT on the title continues from the banked save (gated
; on CONTOK — cont_gate validated the slot at title entry). A goto runs the
; new init in place — rts right after (never fall through into stale-scene
; code; see sf_scene.inc TRANSITION SEMANTICS).
; -----------------------------------------------------------------------------
menu_tick:
    .a16
    lda SCENE                   ; CONTINUE: title only, valid save only
    cmp #SC_TITLE
    bne menu_start_chk
    lda CONTOK
    beq menu_start_chk
    btnp #BTN_SELECT
    beq menu_start_chk
    lda #$0001
    sta CONTPEND                ; scene_game's init consumes this
    sf_scene_goto SC_GAME
    rts
menu_start_chk:
    .a16
    btnp #BTN_START
    beq menu_done
    lda SCENE
    cmp #SC_TITLE
    beq menu_to_game
    sf_scene_goto SC_TITLE      ; over/win -> back to the title
    rts
menu_to_game:
    .a16
    stz CONTPEND                ; START is always a fresh run, save or no save
    sf_scene_goto SC_GAME
    rts
menu_done:
    .a16
    spr_clear
    ; title card: stand the hero on the title so it reads as a game, not a bare
    ; menu (title only — over/win stay text-only). Drawn after spr_clear and
    ; below every menu text line, so it never overlaps one.
    lda SCENE
    cmp #SC_TITLE
    bne md_no_hero
    sf_anim_tile hero_anim_idle, AFRAME
    clc
    adc #HERO_BASE
    sta SCRATCH
    lda #HERO_TITLE_X
    sta CORNX
    lda #HERO_TITLE_Y
    sta CORNY
    lda #SPR_LARGE              ; 16x16, OBJ palette 0, facing right
    sta LVAR
    spr SCRATCH, CORNX, CORNY, LVAR, #2
md_no_hero:
    .a16
    sf_frame_end
    sf_debug_complete
    rts

; -----------------------------------------------------------------------------
; the game tick (one frame of gameplay)
; -----------------------------------------------------------------------------
game_tick:
    .a16

    ; ---- pause (START toggles a full freeze) ----
    ; While paused, skip EVERY game update below (walk, jump, physics, pits,
    ; coins, patrols, combat) — nothing moves and nothing can hurt the player;
    ; the last frame holds on screen. Audio + the frame sync keep running (they
    ; live in game_loop, above the dispatch). A PAUSED banner shows the state.
    btnp #BTN_START
    beq gf_pause_state
    lda PAUSED
    eor #$0001
    sta PAUSED
    beq gf_unpaused             ; toggled to running -> clear the banner
    print pause_str, #104, #112 ; toggled to paused -> show it (row 14, centered)
    bra gf_pause_state
gf_unpaused:
    .a16
    sf_text_clear #14, #15      ; wipe the PAUSED banner row
gf_pause_state:
    .a16
    lda PAUSED
    beq gf_running
    sf_frame_end                ; paused: hold the frame, sync VBlank, return
    sf_debug_complete
    rts
gf_running:
    .a16

    ; ---- death beat: hold the fallen frame after a pit fall (a beat, not an
    ; instant teleport) then respawn when it expires ----
    lda DEATHBEAT
    beq gf_no_deathbeat
    dec a
    sta DEATHBEAT
    bne gf_deathbeat_hold       ; still counting -> keep holding the fall
    jsr respawn_player          ; beat over -> back to spawn (with i-frames)
    bra gf_no_deathbeat
gf_deathbeat_hold:
    .a16
    sf_frame_end                ; hold the fall on screen, sync VBlank, return
    sf_debug_complete
    rts
gf_no_deathbeat:
    .a16

    ; ---- walk (level-checked per axis: tentative x, box probe) ----
    btn #BTN_RIGHT
    bne :+
    jmp gf_no_right
:   rep #$20
    .a16
    lda PX
    inc a
    inc a
    cmp #(512 - 8)
    bcc :+
    jmp gf_no_right
:   sta ENEWX                   ; tentative (patrol scratch is free here)
    lda PYF
    xba
    and #$00FF
    sta PIXY
    sf_level_solid_box ENEWX, PIXY, CORNX, CORNY, LVAR
    bne gf_no_right             ; wall -> blocked
    lda ENEWX
    sta PX
    stz FACING
gf_no_right:
    .a16
    btn #BTN_LEFT
    bne :+
    jmp gf_no_left
:   rep #$20
    .a16
    lda PX
    dec a
    dec a
    cmp #8
    bcs :+
    jmp gf_no_left
:   sta ENEWX
    lda PYF
    xba
    and #$00FF
    sta PIXY
    sf_level_solid_box ENEWX, PIXY, CORNX, CORNY, LVAR
    bne gf_no_left
    lda ENEWX
    sta PX
    lda #$0001
    sta FACING
gf_no_left:
    .a16

    ; ---- jump (A, or B as an alias) + SFX and the variable-height cut ----
    btnp #BTN_A
    bne gf_do_jump
    btnp #BTN_B                 ; B jumps too (either face button, player's pick)
    beq gf_no_jump
gf_do_jump:
    .a16
    lda GROUNDED
    beq gf_no_jump
    sf_jump VY, GROUNDED
    sf_sfx #SFX::jump
gf_no_jump:
    .a16
    ; hold either jump button to keep rising; releasing BOTH cuts it short
    btn #BTN_A
    bne gf_jump_held
    btn #BTN_B
    bne gf_jump_held
    sf_jump_cut VY
gf_jump_held:
    .a16

    sf_level_physics_step PYF, VY, PX, NEWY, GROUNDED, CORNX, CORNY, LVAR
    lda PYF
    xba
    and #$00FF
    sta PIXY

    ; ---- pit: lose a life (with a death beat before respawn) ----
    sf_pit PYF, #PIT_DEATH_Y
    beq gf_no_pit
    jsr life_lost               ; life-- + game-over check; does NOT reposition
    lda SCENE
    cmp #SC_GAME
    bne gf_pit_over
    lda #DEATHBEAT_FRAMES
    sta DEATHBEAT               ; start the beat; the fallen player draws this
    bra gf_no_pit               ;   frame, holds, then respawn_player fires
gf_pit_over:
    .a16
    rts                         ; scene changed (game over) — back to loop top
gf_no_pit:
    .a16

    ; ---- coin pickup: probe the box center for flag bit 2 ----
    lda PX
    clc
    adc #4
    sta CORNX
    lda PIXY
    clc
    adc #4
    sta CORNY
    sf_level_point CORNX, CORNY, LVAR, #2
    bne :+
    jmp gf_no_coin
:   ; clear the tile (page-aware mset) + count + SFX
    lda PX
    clc
    adc #4
    lsr a
    lsr a
    lsr a                       ; tile x 0..63
    sta CORNX
    lda CORNY
    lsr a
    lsr a
    lsr a                       ; tile y
    sta SCRATCH
    lda CORNX
    cmp #32
    bcc gf_coin_l1
    sec
    sbc #32
    sta CORNX
    mset #2, CORNX, SCRATCH, #0
    jmp gf_coin_count
gf_coin_l1:
    .a16
    mset #1, CORNX, SCRATCH, #0
gf_coin_count:
    .a16
    lda COINS
    inc a
    sta COINS
    lda #$0001
    sta SDIRTY
    sf_sfx #SFX::collect_coin
    lda COINS
    cmp #TOTAL_COINS
    bcc gf_no_coin
    sf_scene_goto SC_WIN
    rts
gf_no_coin:
    .a16

    ; ---- patrols: ghost 1 (ground), ghost 2 (across the seam) ----
    lda E1ALIVE
    bne :+
    jmp gf_e1_done
:   sf_level_patrol_step E1X, E1Y_const, E1D, ENEWX, ELEADX, EFOOTY, ELVAR
    ; fair-start clamp: the ground beat would otherwise walk to x=0 and grind a
    ; player who never leaves spawn. Turn it back east at GHOST1_MIN_X.
    lda E1X
    cmp #GHOST1_MIN_X
    bcs gf_e1_done              ; already east of the clamp — no turn needed
    lda #GHOST1_MIN_X
    sta E1X
    lda #$0001
    sta E1D                     ; face/walk east, back into the lane
gf_e1_done:
    .a16
    lda E2ALIVE
    bne :+
    jmp gf_e2_done
:   sf_level_patrol_step E2X, E2Y_const, E2D, ENEWX, ELEADX, EFOOTY, ELVAR
gf_e2_done:
    .a16

    ; ---- stomp / contact (one resolution per frame; i-frames gate hurt) ----
    lda HURTLOCK
    beq gf_check_e1
    dec a
    sta HURTLOCK
    jmp gf_combat_done
gf_check_e1:
    .a16
    sf_stomp_check PX, PIXY, VY, E1X, #G1_Y, E1ALIVE
    cmp #STOMP_RESULT
    bne :+
    sf_sfx #SFX::menu_select    ; stomp!
    jmp gf_combat_done
:   cmp #HURT_RESULT
    bne gf_check_e2
    jmp gf_hurt
gf_check_e2:
    .a16
    sf_stomp_check PX, PIXY, VY, E2X, #G2_Y, E2ALIVE
    cmp #STOMP_RESULT
    bne :+
    sf_sfx #SFX::menu_select
    jmp gf_combat_done
:   cmp #HURT_RESULT
    bne gf_combat_done
gf_hurt:
    .a16
    jsr life_lost               ; life-- + game-over check; does NOT reposition
    lda SCENE
    cmp #SC_GAME
    bne gf_hurt_over
    jsr respawn_player          ; a ghost hit respawns at once — the i-frame
    jmp gf_combat_done          ;   blink is the feedback (no death beat)
gf_hurt_over:
    .a16
    rts                         ; game over took the scene — back to loop top
gf_combat_done:
    .a16

    ; ---- HUD ----
    lda SDIRTY
    beq gf_hud_done
    stz SDIRTY
    ; LIVES is 0-3: print ONE ASCII digit (a 5-digit "00003" reads as a score).
    ; '0'+LIVES in the low byte, 0 (NUL) in the high byte -> a 1-char string in
    ; a single 16-bit store; walk-through cols stay blank so LIVES never trails
    ; stale digits as it shrinks.
    lda LIVES
    clc
    adc #'0'
    and #$00FF
    sta LIVES_STR
    print LIVES_STR, #56, #8
    sf_print_u16 COINS, #168, #8   ; COINS can pass 9 — keep the fixed-width form
gf_hud_done:
    .a16

    ; ---- camera + draw ----
    sf_camera_follow PX, PIXY, 512, 224, CAMX, CAMY
    scroll #1, CAMX, CAMY
    scroll #2, CAMX, #0         ; parallax world-X feed (camera X)
    sf_parallax_tick            ; rebuild the 2-band BG2 HOFS table (world-X read
                                ;   + 2 ratio multiplies + 3 band entries: ~690
                                ;   cyc, measured — tests/test_platformer_cycles.py)

    spr_clear
    ; player: 16x16 sprite over the 8x8 box (centered x-4, feet-aligned y-8)
    sf_anim_tile hero_anim_idle, AFRAME
    clc
    adc #HERO_BASE
    sta SCRATCH
    lda PX
    sec
    sbc CAMX
    sec
    sbc #4
    sta CORNX
    lda PIXY
    sec
    sbc #8
    sta CORNY
    lda #SPR_LARGE              ; 16x16, OBJ palette 0 (hero)
    ldx FACING
    beq :+
    ora #SPR_HFLIP             ; facing left -> mirror the sprite
:   sta LVAR                    ; flags scratch
    ; i-frame blink: while HURTLOCK>0 the player is invulnerable (post-hit or
    ; spawn grace) — flash the hero so that reads on screen. Physics and control
    ; keep running; only the sprite is skipped, and spr_clear already parked it,
    ; so a skipped draw simply leaves the hero invisible this frame.
    lda HURTLOCK
    beq gf_draw_hero            ; vulnerable -> always draw
    and #BLINK_PHASE
    bne gf_hero_hidden          ; blink-off phase -> leave the hero parked
gf_draw_hero:
    .a16
    spr SCRATCH, CORNX, CORNY, LVAR, #2
gf_hero_hidden:
    .a16

    ; ghosts (slot 1+2; dead ones park at $E0)
    sf_anim_tile ghost_anim_idleWalkRun, AFRAME
    clc
    adc #GHOST_BASE
    sta SCRATCH
    lda E1ALIVE
    beq gf_d1_dead
    lda E1X
    sec
    sbc CAMX
    sec
    sbc #4
    sta CORNX
    lda #(G1_Y - 8)
    sta CORNY
    bra gf_d1_put
gf_d1_dead:
    .a16
    stz CORNX
    lda #OFFSCREEN_Y
    sta CORNY
gf_d1_put:
    .a16
    spr SCRATCH, CORNX, CORNY, #GHOST_ATTR, #2
    lda E2ALIVE
    beq gf_d2_dead
    lda E2X
    sec
    sbc CAMX
    sec
    sbc #4
    sta CORNX
    lda #(G2_Y - 8)
    sta CORNY
    bra gf_d2_put
gf_d2_dead:
    .a16
    stz CORNX
    lda #OFFSCREEN_Y
    sta CORNY
gf_d2_put:
    .a16
    spr SCRATCH, CORNX, CORNY, #GHOST_ATTR, #2

    sf_frame_end
    sf_debug_complete
    rts

; =============================================================================
; SUBROUTINES — the scene table, the scene inits, and the gameplay helpers
; =============================================================================
; the scene table: id -> init/tick (sf_scene_end emits the tick jump table)
sf_scene_begin SCENE
sf_scene SC_TITLE, scene_title, menu_tick
sf_scene SC_GAME,  scene_game,  game_tick
sf_scene SC_OVER,  scene_over,  menu_tick
sf_scene SC_WIN,   scene_win,   menu_tick
sf_scene_end

; -----------------------------------------------------------------------------
; scene inits (the soft-restart pattern: re-build ONLY what each owns —
; sf_scene_goto owns the SCENE write; see sf_scene.inc SOFT-RESTART CONTRACT)
; -----------------------------------------------------------------------------
; patrol's ey operand is READ-ONLY (it computes footy from it), so a ROM
; word is a valid memory operand for a fixed-height beat:
E1Y_const: .word G1_Y
E2Y_const: .word G2_Y

scene_title:
    rep #$30
    .a16
    .i16
    sf_bright_fade #0, #0       ; cut to black, rebuild dark, fade in
    jsr menu_bg_reset           ; wipe the previous run's level + un-freeze cam
    sf_text_clear #0, #28
    print title_str, #72, #88
    print start_str, #80, #120
    jsr cont_gate               ; CONTOK + the CONTINUE line, if earned
    sf_music #Song::chords
    sf_bright_fade #15, #FADE_FRAMES
    rts

; cont_gate — evaluate the slot-0 coin bank for the title menu.
; CONTOK := 1 and the CONTINUE line prints iff the slot holds a VALID save
; (sf_save_exists: magic + CRC — the only legitimate "is there a save?"
; test, see sf_save.inc) in THIS game's format. The version + length reads
; below are raw SRAM header bytes, which is safe HERE ONLY because exists
; already answered 1: the whole header is covered by the CRC it verified.
; Any miss (virgin, corrupt, cleared, foreign version, foreign length)
; leaves CONTOK = 0 -> no line, SELECT inert, new-game semantics intact.
cont_gate:
    rep #$30
    .a16
    .i16
    stz CONTOK
    sf_save_exists 0
    bne cg_validate
    rts
cg_validate:
    .a16
    lda f:$700002               ; slot 0 header: version (lo) + reserved (hi,
    cmp #SAVE_VER               ;   the engine writes 0) — CRC-proven above
    bne cg_done
    lda f:$700004               ; slot 0 header: payload length
    cmp #SAVE_LEN
    bne cg_done
    lda #$0001
    sta CONTOK
    print cont_str, #64, #136
cg_done:
    .a16
    rts

scene_game:
    rep #$30
    .a16
    .i16
    sf_bright_fade #0, #0       ; dark while the level rebuilds (hides
                                ;     the load-in), then fade in below
    sf_text_clear #0, #28
    sf_level_load level_map, CORNX, CORNY, LVAR   ; coins respawn
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
    stz FACING
    stz PAUSED                  ; start un-paused (WRAM is random at power-on)
    stz DEATHBEAT               ; and with no death beat pending
    lda #3
    sta LIVES
    stz COINS
    lda #$0001
    sta E1ALIVE
    sta E2ALIVE
    lda #G1_START_X
    sta E1X
    stz E1D
    lda #G2_START_X
    sta E2X
    lda #$0001
    sta E2D
    lda #SPAWN_GRACE
    sta HURTLOCK                ; spawn grace i-frames
    lda #$0001
    sta SDIRTY

    ; CONTINUE: consume the menu's pending flag and restore ONLY the
    ; coin bank. Everything above is the fresh-run baseline, so a rejected
    ; load (or no pending continue) needs no fallback work — new-game
    ; semantics simply stand. The cmp on the return code is the final gate:
    ; only a full-length successful load touches COINS (sf_load leaves the
    ; staging buffer untouched on $FFFF/$FFFE by contract).
    lda CONTPEND
    beq sg_fresh
    stz CONTPEND
    sf_load 0, #SAVEBUF
    cmp #SAVE_LEN
    bne sg_fresh
    lda SAVEBUF
    sta COINS
sg_fresh:
    .a16
    print lives_str, #8, #8
    print coins_str, #120, #8
    sf_music #Song::ode_to_joy
    sf_bright_fade #15, #FADE_FRAMES
    rts

scene_over:
    rep #$30
    .a16
    .i16
    sf_bright_fade #0, #0
    jsr menu_bg_reset           ; the game-over screen is text over dusk sky,
                                ;   not over the level the player just died in
    sf_text_clear #0, #28
    print over_str, #92, #104
    print start_str, #80, #136
    sf_music_stop
    sf_bright_fade #15, #FADE_FRAMES
    rts

scene_win:
    rep #$30
    .a16
    .i16
    sf_bright_fade #0, #0
    jsr menu_bg_reset           ; likewise the win card: clear the finished level
    sf_text_clear #0, #28
    print win_str, #96, #104
    print start_str, #80, #136
    sf_music #Song::chords
    sf_bright_fade #15, #FADE_FRAMES
    rts

; life_lost — hurt SFX, LIVES--, and on the last life bank + go to GAME OVER.
; Does NOT reposition: the caller respawns (a ghost hit instantly, a pit fall
; after its death beat), so the two death flavors can pace the respawn.
life_lost:
    rep #$30
    .a16
    .i16
    sf_sfx #SFX::player_hurt
    lda LIVES
    dec a
    sta LIVES
    lda #$0001
    sta SDIRTY
    lda LIVES
    beq ll_over
    rts                         ; survived — caller repositions
ll_over:
    .a16
    ; SAVE POINT: bank the run's coins for CONTINUE — only a non-empty
    ; bank is worth a battery write (a zero-coin continue IS a new game).
    ; COINS still holds the run's count here; scene_over doesn't touch it.
    lda COINS
    beq ll_no_bank
    sf_save 0, #COINS, SAVE_LEN, SAVE_VER
ll_no_bank:
    .a16
    sf_scene_goto SC_OVER
    rts

; respawn_player — put a surviving player back at spawn with i-frames. Called
; by the two death paths after life_lost keeps the game going.
respawn_player:
    rep #$30
    .a16
    .i16
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
    lda #RESPAWN_IFRAMES
    sta HURTLOCK
    rts

; -----------------------------------------------------------------------------
; menu_bg_reset — return BG1 and the parallax sky to their clean-boot state so
; a menu (title / game-over / win) never shows the previous run's world.
; -----------------------------------------------------------------------------
; A menu is text (BG3) over the dusk sky (BG2 + the backdrop gradient); the
; level lives on BG1 and must be gone. Two things carry over from gameplay:
;   1. the camera — sf_camera_follow left CAMX/CAMY wherever the player was,
;      which drags both BG1 and the parallax sky off their title positions; and
;   2. BG1's tilemap — still the level the player was just in.
; Every menu init calls this UNDER its cut-to-black fade, so the cleared
; tilemap reaches VRAM (next NMI) before the fade-in reveals it — no flash of
; the old level. mset writes the WRAM shadow map the NMI DMAs each frame, so
; no forced blank is needed.
menu_bg_reset:
    rep #$30
    .a16
    .i16
    stz CAMX
    stz CAMY
    scroll #1, CAMX, CAMY        ; BG1 (level) scroll shadow -> world origin
    scroll #2, CAMX, #0          ; BG2 parallax world-X feed -> world origin
    sf_parallax_tick             ; rebuild the sky bands at world-X 0 (clean pos)
    ; Clear BG1's 64x32 map, tile 0 (empty sky) in every cell. It is two 32x32
    ; hardware pages: engine layer 1 = page 0 (world cols 0-31), engine layer 2
    ; = page 1 (cols 32-63) — the split sf_level_load fills the level into.
    stz SCRATCH                  ; tile 0 = empty sky (the fill value)
    lda #$0001
    sta LVAR                     ; LVAR = the page's engine layer (1 then 2)
@page_loop:
    .a16
    stz CORNY                    ; map row 0..31
@row_loop:
    .a16
    stz CORNX                    ; map col 0..31
@col_loop:
    .a16
    mset LVAR, CORNX, CORNY, SCRATCH
    lda CORNX
    inc a
    sta CORNX
    cmp #32
    bcs @row_next                ; row done (short forward branch, in range)
    jmp @col_loop                ; else next col — long jump past mset's expansion
@row_next:
    .a16
    lda CORNY
    inc a
    sta CORNY
    cmp #32
    bcs @page_next
    jmp @row_loop
@page_next:
    .a16
    lda LVAR
    inc a
    sta LVAR
    cmp #3                       ; pages 1 and 2 (BG1's two 32x32 halves)
    bcs @clear_done
    jmp @page_loop
@clear_done:
    .a16
    rts

; =============================================================================
; DATA — strings, the level map, tile + sky art, and the engine includes
; =============================================================================
title_str:
    .byte "SUPER KIT QUEST", 0
start_str:
    .byte "PRESS START", 0
lives_str:
    .byte "LIVES", 0
coins_str:
    .byte "COINS", 0
over_str:
    .byte "GAME OVER", 0
win_str:
    .byte "YOU WIN!", 0
cont_str:                       ; the title's continue offer (row 17;
    .byte "SELECT: CONTINUE", 0 ;   printed by cont_gate only when CONTOK)
pause_str:
    .byte "PAUSED", 0

; --- the level: 28 rows x 64 tile IDs ---
; ground rows 24-27 with pits at cols 22-25 (x 176-207) and 46-49 (x 368-399);
; ledges + one-way platforms; 6 coins (tile 4); ghost2's ledge crosses the seam
level_map:
    ; rows 0-14: sky
    .repeat 15 * 64
    .byte 0
    .endrepeat
    ; row 15: the seam coin (col 31) — at ledge standing height so walking
    ; the ledge collects it (box center y = rest+4 = row 15)
    .repeat 31
    .byte 0
    .endrepeat
    .byte 4
    .repeat 32
    .byte 0
    .endrepeat
    ; row 16: ghost2's ledge, cols 26-38 (x 208-311: crosses the seam)
    .repeat 26
    .byte 0
    .endrepeat
    .repeat 13
    .byte 2
    .endrepeat
    .repeat 25
    .byte 0
    .endrepeat
    ; row 17: sky
    .repeat 64
    .byte 0
    .endrepeat
    ; row 18: stepping platform cols 19-21 (x 152-175) — the route UP to the
    ; ledge: ground -> platform 1 (row 20) -> here -> ledge (row 16). Without
    ; it the ledge is out of jump range (found in playtest: WIN impossible)
    .repeat 19
    .byte 0
    .endrepeat
    .repeat 3
    .byte 3
    .endrepeat
    .repeat 42
    .byte 0
    .endrepeat
    ; row 19: coins on the one-way platforms (cols 12, 43)
    .repeat 12
    .byte 0
    .endrepeat
    .byte 4
    .repeat 30
    .byte 0
    .endrepeat
    .byte 4
    .repeat 20
    .byte 0
    .endrepeat
    ; row 20: one-way platforms: cols 10-15 (x 80-127) and cols 41-46 (x 328-375)
    .repeat 10
    .byte 0
    .endrepeat
    .repeat 6
    .byte 3
    .endrepeat
    .repeat 25
    .byte 0
    .endrepeat
    .repeat 6
    .byte 3
    .endrepeat
    .repeat 17
    .byte 0
    .endrepeat
    ; rows 21-22: sky
    .repeat 2 * 64
    .byte 0
    .endrepeat
    ; row 23: ground-level coins (cols 7, 34, 60)
    .repeat 7
    .byte 0
    .endrepeat
    .byte 4
    .repeat 26
    .byte 0
    .endrepeat
    .byte 4
    .repeat 25
    .byte 0
    .endrepeat
    .byte 4
    .repeat 3
    .byte 0
    .endrepeat
    ; rows 24-27: ground with two pits (cols 22-25 and 46-49). Row 24 is the
    ; grass surface (tile 1); rows 25-27 are plain dirt (tile 5) — identical
    ; SOLID collision and the same pit gaps, just grass on top, dirt beneath.
    ; row 24: grass surface
    .repeat 22
    .byte 1
    .endrepeat
    .repeat 4
    .byte 0
    .endrepeat
    .repeat 20
    .byte 1
    .endrepeat
    .repeat 4
    .byte 0
    .endrepeat
    .repeat 14
    .byte 1
    .endrepeat
    ; rows 25-27: dirt interior
    .repeat 3
    .repeat 22
    .byte 5
    .endrepeat
    .repeat 4
    .byte 0
    .endrepeat
    .repeat 20
    .byte 5
    .endrepeat
    .repeat 4
    .byte 0
    .endrepeat
    .repeat 14
    .byte 5
    .endrepeat
    .endrepeat
.assert * - level_map = 28 * 64, error, "level must be 28x64"

; --- tiles ---
; --- level tile art (BG1, 4bpp, original 8x8 pixel art in the dusk palette;
; hand-authored here like the sky above — not from an external pack). Grids and
; the grid->bitplane generator that produced these bytes live in the review's
; notes; each row below is one tile's 8 rows of (plane0,plane1)+(plane2,plane3). ---
ground_tile:                    ; tile 1/2: grass top (idx 4) over dirt (1) + specks (5)
    .byte $00,$00, $00,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $04,$00, $20,$00
    .byte $02,$00, $80,$00, $10,$00, $00,$00
dirt_tile:                      ; tile 5: solid dirt (idx 1) + dark specks (5), no grass
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $10,$00, $40,$00, $04,$00, $00,$00
    .byte $82,$00, $00,$00, $20,$00, $08,$00
plat_tile:                      ; tile 3: mossy platform — grass edge (4) + green (2)
    .byte $00,$00, $00,$FF, $00,$FF, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $FF,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
coin_tile:                      ; tile 4: coin roundel — gold (3) with a highlight (6)
    .byte $3C,$3C, $4E,$7E, $9F,$FF, $BF,$FF
    .byte $FF,$FF, $FF,$FF, $7E,$7E, $3C,$3C
    .byte $00,$00, $30,$00, $60,$00, $40,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; --- sky art (BG2, 4bpp, original): tiles 1-3, contiguous for one upload ---
sky_tiles:
    ; tile 1: cloud puff (color index 1 — SKY_CLOUD)
    .byte $00,$00, $3C,$00, $7E,$00, $FF,$00
    .byte $FF,$00, $7E,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    ; tile 2: silhouette solid block (color index 2 — SKY_SILH)
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    ; tile 3: silhouette jagged top (color index 2)
    .byte $00,$18, $00,$3C, $00,$3C, $00,$7E
    .byte $00,$7E, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; --- sky tilemap pattern: 32 rows x 8 bytes (tile id per col & 7).
; The 8-column period = 64 px, so parallax shifts are unambiguous in the
; screenshot gates up to 63 px (camera max 256: clouds shift <= 32, hills
; <= 96 but tested at small deltas). Residues 0-1 are ALWAYS empty — a
; 16 px backdrop "valley" every 64 px where the dusk gradient reads pure
; (the gradient gate samples column x=8). Clouds rows 3-7 sit fully in the
; top band (scanlines 0-95); hills rows 12-16 fully in the bottom band. ---
sky_pattern:
    .repeat 3 * 8               ; rows 0-2: open sky
    .byte 0
    .endrepeat
    .byte 0,0,0,1,1,0,0,0       ; row 3: small cloud top
    .byte 0,0,1,1,1,1,0,0       ; row 4: fat cloud body
    .repeat 2 * 8               ; rows 5-6: open sky
    .byte 0
    .endrepeat
    .byte 0,0,0,0,0,0,1,1       ; row 7: second cloud, offset
    .repeat 4 * 8               ; rows 8-11: open sky
    .byte 0
    .endrepeat
    .byte 0,0,0,0,3,3,0,0       ; row 12: hill peak (jagged)
    .byte 0,0,0,3,2,2,3,0       ; row 13: hill shoulders
    .byte 0,0,3,2,2,2,2,3       ; row 14: hill base edges
    .byte 0,0,2,2,2,2,2,2       ; rows 15-16: solid silhouette (valley at 0-1)
    .byte 0,0,2,2,2,2,2,2
    .repeat 15 * 8              ; rows 17-31: below the skyline (backdrop)
    .byte 0
    .endrepeat
.assert * - sky_pattern = 32 * 8, error, "sky pattern must be 32 rows x 8"

; --- converted art (committed png2snes output; regen-guarded) ---
.include "assets/hero.inc"
.include "assets/ghost.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
.include "tad_bridge.asm"
; look-&-feel engine partners (order per sf_fx.inc: hdma_alloc ->
; hdma_engine -> hdma_color_engine; the rest are order-independent)
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
.include "bright_fade_engine.asm"
.include "save_load_engine.asm"  ; battery-SRAM coin bank (sf_save.inc)
