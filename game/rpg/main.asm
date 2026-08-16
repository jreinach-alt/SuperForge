; =============================================================================
; rpg — a top-down RPG: a Mode 7 overworld you walk, and a Mode 1 town
; =============================================================================
; You steer an avatar across a designed
; 128x128-tile Mode 7 world on the tile grid — grass and path walk, water,
; mountain and wood block — reach the town gate, and a MOSAIC WIPE carries you
; into a Mode 1 town. There a villager gives you a PAGED DIALOG BOX, a save
; point writes battery SRAM, and the south gate wipes you back out to the spot
; you left. Music plays across every swap.
;
; It debuts ONE engine feature: `dialog` — the opaque BG3 message window. Its
; argument, its claims and its binding contract are in
; engine/features/dialog/feature.toml.
;
; Everything else is composed: mode7_persp + split_band + col_map + oam_sprites
; + bg_text + mosaic + save + audio + scene_mgr + fade + input.
;
; THE TRANSITION IS NOT scene_mgr's PHASE MACHINE, for mode7_explore's reasons:
; the wipe is a mosaic dissolve rather than a fade, and phase 3's
; fade would fight mosaic for the one INIDISP shadow. main.asm drives ES_SM_CTL's
; scene id itself; the phase byte stays 0 for the ROM's life.

.define SF_HDR_TITLE "SUPERFORGE RPG"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB. header.inc's default is $05 (32 KB,
                                    ;   the toy/probe size) and this cart links
                                    ;   at 524,288 B — an undeclared size is the
                                    ;   shape of a cart whose header lies about
                                    ;   its own size, on the one field the
                                    ;   allocator does NOT derive (it derives
                                    ;   $FFD6/$FFD8 from claims; $FFD7 is the
                                    ;   game's).
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids for this
                                    ;   game's export (assets/audio/export)
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- world constants --------------------------------------------------------
; SB_LINES is 44 and that is NOT a taste: mode7_persp's pose tables are
; generated with `--lines 180` (Makefile), i.e. 224 - 44, so the seam the
; perspective was solved for is line 44. Moving it would shift every scanline's
; matrix off its row. At ~20% sky it is the picture this rail wants anyway, so
; there is nothing to trade.
SB_LINES = 44
HUD_LINES = SB_LINES            ; mode7_persp names this: it is the first Mode 7
                                ;   scanline, and its pose tables are 224 - it
                                ;   lines long. One constant, two readers.
SB_MODE_TOP = 1                 ; BGMODE 1 above the horizon — nothing enabled
SB_MODE_BOT = 7                 ; BGMODE 7 below it: the ground plane
TM_BG1 = 1 << 0
TM_BG3 = 1 << 2
TM_OBJ = 1 << 4
SB_TM_TOP = TM_OBJ              ; the SKY: no BG at all, so the BACKDROP shows —
                                ;   and the backdrop is CGRAM word 0, which
                                ;   rpg_floor's palette claim owns and paints
                                ;   sky blue — one claim paints both the sky
                                ;   and the plane's index 0.
SB_TM_BOT = TM_BG1 | TM_OBJ     ; the floor, and the avatar standing on it

PIVOT_LINE = 168                ; the scanline the camera maps to — the world
                                ;   row the avatar stands on
SCREEN_MID_X = 128
WORLD_TILES_LOG2 = 7            ; 128 x 128 tiles = a 1024-px torus
TILE_PX = 8
STEP_FRAMES = 8                 ; one tile, animated at 1 px/frame

SPAWN_TX = 64                   ; must match tools/gen_rpg_assets.py's SPAWN_*
SPAWN_TY = 78

; --- joypad masks, as SHIFTS ------------------------------------------------
; `no_literals` refuses the hex forms and the gate is right: $0200 lands inside
; a WRAM claim and nothing in the token distinguishes a hardware bit from an
; address. The shift also reads better — it says "bit 9 of a hardware word".
JOY_RIGHT = 1 << 8
JOY_LEFT = 1 << 9
JOY_DOWN = 1 << 10
JOY_UP = 1 << 11
JOY_A = 1 << 7

; --- col_map flag bits (tools/gen_rpg_assets.py emits the table) ------------
F_BLOCK = 1 << 0
F_TOWN = 1 << 1

; --- the town's fixed cells (must match tools/gen_rpg_assets.py) ------------
TOWN_SPAWN_TX = 16
TOWN_SPAWN_TY = 20
TOWN_NPC_TX = 12
TOWN_NPC_TY = 10
TOWN_SAVE_TX = 20
TOWN_SAVE_TY = 16
TOWN_EXIT_TX = 16
TOWN_EXIT_TY = 24

; --- engine features (the GLOBAL half of the composition) -------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "mosaic.asm"
.include "save.asm"
.include "bg_text.asm"
.include "split_band.asm"
.include "rpg_logic.asm"

; =============================================================================
; THE ROM CLAIM SITES
; =============================================================================
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37): a claim with no .incbin would reserve
; the window and let whatever the linker left there be read as art — which for
; `m7_world` is a 32 KB image DMA'd straight into the Mode 7 region.
;
; The ORDER is the allocator's, not a preference: place_rom packs by
; (-bytes, name), and build/rpg/allocation_report.txt is what these follow.

.segment "BANK1"
rpg_tad_placeholder = 0         ; window 1 is tad_rom's pinned AUDIO_DATA0

.segment "BANK6"
rpg_m7_bin:
    .incbin "rpg_m7.bin"
.assert ^rpg_m7_bin = ES_R_M7_WORLD_BANK, error, "m7_world bank drifted from allocator claim"
.assert .loword(rpg_m7_bin) = ES_R_M7_WORLD_ADDR, error, "m7_world addr drifted from allocator claim"

.segment "BANK7"
rpg_col_bin:
    .incbin "rpg_col.bin"
.assert ^rpg_col_bin = ES_R_COL_WORLD_BANK, error, "col_world bank drifted from allocator claim"
.assert .loword(rpg_col_bin) = ES_R_COL_WORLD_ADDR, error, "col_world addr drifted from allocator claim"
rpg_obj_chr_bin:
    .incbin "rpg_obj_chr.bin"
.assert ^rpg_obj_chr_bin = ES_R_OBJ_CHR_BANK, error, "obj_chr bank drifted from allocator claim"
.assert .loword(rpg_obj_chr_bin) = ES_R_OBJ_CHR_ADDR, error, "obj_chr addr drifted from allocator claim"
rpg_town_chr_bin:
    .incbin "rpg_town_chr.bin"
.assert ^rpg_town_chr_bin = ES_R_TOWN_CHR_BANK, error, "town_chr bank drifted from allocator claim"
.assert .loword(rpg_town_chr_bin) = ES_R_TOWN_CHR_ADDR, error, "town_chr addr drifted from allocator claim"
rpg_town_map_bin:
    .incbin "rpg_town_map.bin"
.assert ^rpg_town_map_bin = ES_R_TOWN_MAP_BANK, error, "town_map bank drifted from allocator claim"
.assert .loword(rpg_town_map_bin) = ES_R_TOWN_MAP_ADDR, error, "town_map addr drifted from allocator claim"
rpg_font_bin:
    .incbin "font_2bpp.bin"
.assert ^rpg_font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(rpg_font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
crc16_lut_bin:
    .incbin "crc16_lut.bin"
.assert ^crc16_lut_bin = ES_R_CRC16_LUT_ROM_BANK, error, "crc16_lut_rom bank drifted from allocator claim"
.assert .loword(crc16_lut_bin) = ES_R_CRC16_LUT_ROM_ADDR, error, "crc16_lut_rom addr drifted from allocator claim"
rpg_flags_bin:
    .incbin "rpg_flags.bin"
.assert ^rpg_flags_bin = ES_R_COL_FLAGS_BANK, error, "col_flags bank drifted from allocator claim"
.assert .loword(rpg_flags_bin) = ES_R_COL_FLAGS_ADDR, error, "col_flags addr drifted from allocator claim"
rpg_dlg_chr_bin:
    .incbin "dlg_chr.bin"
.assert ^rpg_dlg_chr_bin = ES_R_DLG_CHR_BANK, error, "dlg_chr bank drifted from allocator claim"
.assert .loword(rpg_dlg_chr_bin) = ES_R_DLG_CHR_ADDR, error, "dlg_chr addr drifted from allocator claim"
rpg_m7_pal_bin:
    .incbin "rpg_m7_pal.bin"
.assert ^rpg_m7_pal_bin = ES_R_M7_PAL_BANK, error, "m7_pal bank drifted from allocator claim"
.assert .loword(rpg_m7_pal_bin) = ES_R_M7_PAL_ADDR, error, "m7_pal addr drifted from allocator claim"
rpg_obj_pal_bin:
    .incbin "rpg_obj_pal.bin"
.assert ^rpg_obj_pal_bin = ES_R_OBJ_PAL_BANK, error, "obj_pal bank drifted from allocator claim"
.assert .loword(rpg_obj_pal_bin) = ES_R_OBJ_PAL_ADDR, error, "obj_pal addr drifted from allocator claim"
rpg_town_pal_bin:
    .incbin "rpg_town_pal.bin"
.assert ^rpg_town_pal_bin = ES_R_TOWN_PAL_BANK, error, "town_pal bank drifted from allocator claim"
.assert .loword(rpg_town_pal_bin) = ES_R_TOWN_PAL_ADDR, error, "town_pal addr drifted from allocator claim"
rpg_dlg_pal_bin:
    .incbin "dlg_pal.bin"
.assert ^rpg_dlg_pal_bin = ES_R_DLG_PAL_BANK, error, "dlg_pal bank drifted from allocator claim"
.assert .loword(rpg_dlg_pal_bin) = ES_R_DLG_PAL_ADDR, error, "dlg_pal addr drifted from allocator claim"

; --- the perspective pose tables: two bank_tiled blobs, 64 KB each ----------
; The chunk COUNT comes from the emitted symbol, not from a narrated `.repeat 2`
; (a narrated count is its own refusal — see docs/37 §5).
.repeat ES_R_POSES_AB_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 2)
.ident(.sprintf("rpg_poses_ab_t%d", WI)):
    .incbin "poses_ab.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("rpg_poses_ab_t%d", WI)) = .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", WI)), error, "poses_ab chunk bank drifted from allocator claim"
.assert .loword(.ident(.sprintf("rpg_poses_ab_t%d", WI))) = .ident(.sprintf("ES_R_POSES_AB_T%d_ADDR", WI)), error, "poses_ab chunk addr drifted from allocator claim"
.endrepeat
.repeat ES_R_POSES_CD_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 4)
.ident(.sprintf("rpg_poses_cd_t%d", WI)):
    .incbin "poses_cd.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("rpg_poses_cd_t%d", WI)) = .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", WI)), error, "poses_cd chunk bank drifted from allocator claim"
.assert .loword(.ident(.sprintf("rpg_poses_cd_t%d", WI))) = .ident(.sprintf("ES_R_POSES_CD_T%d_ADDR", WI)), error, "poses_cd chunk addr drifted from allocator claim"
.endrepeat

.segment "CODE"

; The SCENE-SCOPED features are included inside their scenes, not here: each
; names symbols that belong to one scene (ES_D_RPGF_UP_CH, ES_V_TOWN_CHR,
; ES_V_OBJ_CHR, ES_DLG_CTL), and rpg_obj is in BOTH scenes with a DIFFERENT
; OBJ page in each — the Mode 7 region floors OBJ CHR at word $4000 in the
; overworld and nothing floors it in the town. race.asm is the precedent.

; =============================================================================
; THE TRANSITION — a mosaic wipe in two halves
; =============================================================================
; mode7_explore's shape, for its reasons. `mosaic` JSRs its swap
; routine at PEAK BLACK, mid-frame; what the swap has to do here is a 32 KB
; Mode 7 re-upload or a 4 KB Mode 1 rebuild, and that needs FORCED BLANK, not
; brightness 0. INIDISP bit 7 is scene_mgr's — its `scene_writes` withholds it
; from enter and boot code and `no_literals`' reg-ownership pass refuses a bare
; `sta a:$2100` here by name. So the callback raises the shadow's blank bit at
; peak black, the next NMI commits it, and the rebuild runs at the top of the
; following main-loop iteration with blank genuinely on screen.
SWAP_NONE = 0
SWAP_TO_TOWN = 1
SWAP_TO_OVERWORLD = 2

SCENE_OVERWORLD = 0
SCENE_TOWN = 1

; --- the two mosaic swap callbacks ------------------------------------------
; In/out: A8/I16, DB=0 — mosaic's `_mos_call_swap` contract, a TAIL CALL through
; `jmp (abs)` that neither ca65 nor width_lint can check in either direction.
; WIDTH-RISK: entered A8/I16 and MUST return A8/I16 with DB unchanged. Reached
; only through mosaic's function pointer, so no same-file arrival exists — these
; markers ARE the contract.
rpg_blank_to_town:
    .a8
    .i16
    lda #SWAP_TO_TOWN
    bra _rpg_blank_now
rpg_blank_to_overworld:
    .a8
    .i16
    lda #SWAP_TO_OVERWORLD
_rpg_blank_now:
    .a8
    .i16
    sta z:RPG_PEND                  ; the service's WHICH. Raised HERE and
                                    ;   nowhere else, so the byte MEANS "peak
                                    ;   black has happened" rather than "a wipe
                                    ;   was requested" 20 frames earlier. The
                                    ;   second reading rebuilds the world while
                                    ;   the player can still see it.
    lda z:ES_SM_NMI + 1
    ora #128                        ; INIDISP bit 7 — committed by the next NMI
    sta z:ES_SM_NMI + 1
    rts

; --- the scenes -------------------------------------------------------------
.include "scenes/overworld.asm"
.include "scenes/town.asm"

; --- rpg_swap_service: the blank-phase half of a swap -----------------------
; In/out: A16/I16, DB=0. Called FIRST in the main loop, before anything reads
; the scene id — it is what changes it. Clobbers A, X, Y.
;
; NMI is masked for the duration: the rebuild is far longer than a frame and an
; NMI landing inside it would set VMADD for the OAM and dialog commits and drop
; the rest of the upload at whatever addresses followed. Forced blank does NOT
; mask NMI — $4200 bit 7 does.
rpg_swap_service:
    .a16
    .i16
    sep #$20
    .a8
    lda z:RPG_PEND
    beq @none
    stz a:$4200                     ; NMITIMEN: NMI + auto-joypad off
    lda a:$4210                     ; RDNMI: ack any pending edge
    stz a:$420C                     ; HDMAEN OFF, and this line is load-bearing.
                                    ;   HDMA RUNS IN FORCED BLANK
                                    ;   (substrate.toml `hdma_runs_in_forced_blank
                                    ;   = true`), and every forced-blank upload
                                    ;   in this rail is a GP-DMA on channel 0 —
                                    ;   which is also the channel the OVERWORLD's
                                    ;   `bgm` BGMODE HDMA claim holds. Leaving
                                    ;   $420C armed across the swap let that HDMA
                                    ;   eat the rebuild's transfers: measured on
                                    ;   the emulator, the 1,536-B font upload
                                    ;   landed 116 correct bytes and then
                                    ;   diverged, and the panel rendered the
                                    ;   right tilemap over the wrong CHR.
                                    ;   scene_mgr's own phase-2 switch does
                                    ;   exactly this at `@switch`'s HDMAEN clear with
                                    ;   exactly this comment; this rail drives
                                    ;   its own transition, so it owes the same
                                    ;   line. The NMI re-applies ES_SM_NMI+2
                                    ;   after the scene has set it.
    lda z:RPG_PEND
    cmp #SWAP_TO_TOWN
    rep #$20
    .a16
    bne @to_overworld
    jsr town::resume
    lda #SCENE_TOWN
    bra @entered
@to_overworld:
    .a16
    .i16
    jsr overworld::resume
    lda #SCENE_OVERWORLD
@entered:
    .a16
    .i16
    sep #$20
    .a8
    sta z:ES_SM_CTL                 ; cur: sm_tick dispatches the new scene
    stz z:RPG_PEND
    lda z:ES_SM_NMI + 1
    and #127                        ; drop forced blank — the IN ramp takes the
    sta z:ES_SM_NMI + 1             ;   low nibble from here on
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad back on
@none:
    .a8
    .i16
    rep #$20
    .a16
    rts

; --- rpg_fade_tick: the boot dawn-in, gated on mosaic_active ----------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; `fade` and `mosaic` are two writers of ONE shadow and the allocator cannot see
; it (neither claims INIDISP; scene_mgr does). mosaic's feature.toml states the
; contract in the API instead — "the consumer gates its fade tick on
; mosaic_active" — and this is that gate. `fade_tick` writes the shadow byte
; WHOLE, so a fade running through a wipe would drop the forced-blank bit the
; swap is holding, un-blanking the screen mid-rebuild.
rpg_fade_tick:
    .a16
    .i16
    sep #$20
    .a8
    jsr mosaic_active               ; Z set when idle
    rep #$20
    .a16
    beq @run
    rts
@run:
    .a16
    .i16
    jsr fade_tick
    rts

; --- sm_nmi_hook: per-frame VBlank work -------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Four commits, no ordering constraint between them: dialog_nmi_commit programs
; its own VMAIN and VMADD, which is what makes hook order free (AGENTS.md's
; "VBlank VRAM writers program their own VMAIN + VMADD"), and the other three
; touch neither.
;
; BOTH COMMITS ARE GATED ON THE SCENE, and the gate is not tidiness — it is the
; only thing standing between two features that share DP BYTES. Scene DP is
; REUSED across scenes: ES_M7ORG and ES_DLG_CTL both live at $50-plus in their
; own scene's map. Ungated, the town's BG1 scroll would be whatever the
; overworld's camera bytes happen to hold, and — far worse — dialog's `dirty`
; byte read in the OVERWORLD is col_map's scratch, so an idle panel would fire a
; 576-B DMA into the Mode 7 tilemap whenever a probe left a non-zero there.
; One load and one branch, and it is true by construction rather than by the
; previous scene having tidied up after itself.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; commit the OAM shadow
    lda z:ES_SM_CTL                 ; cur scene id
    bne @town
    jsr overworld::commit_origin
    bra @after
@town:
    .a8
    .i16
    jsr town::dialog_nmi_commit     ; the panel's row span, when one is staged
    jsr town::town_flare_commit     ; the save-torch flare tile swap, when
                                    ;   armed. Programs its own VMADD, so order
                                    ;   with dialog_nmi_commit is free.
@after:
    .a8
    .i16
    jsr mosaic_nmi_commit           ; $2106 from the wipe's shadow — UNCONDITIONAL,
                                    ;   so an idle mosaic establishes $00 rather
                                    ;   than leaving power-on garbage there
    rts

; --- scene dispatch tables (manifest order: overworld=0, town=1) ------------
; AFTER the scene includes: ca65 resolves a scope's members only once the scope
; has been seen. `sm_enter_tab`/`sm_exit_tab` are never indexed past boot — the
; transition is rpg_swap_service, not `sm_request` — but they are complete
; because the tables are indexed by scene id and a hole is what the day someone
; adds a title screen would fall into.
sm_enter_tab:   .word overworld::enter, town::resume
sm_tick_tab:    .word overworld::tick,  town::tick
sm_exit_tab:    .word overworld::exit,  town::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr mosaic_init                 ; the wipe is idle and its $2106 shadow is
                                    ;   $00 — both READ BEFORE ANY WRITE
    jsr text_dp_init
    jsr oam_park_all                ; whole shadow written before its first DMA
    ; ---- audio boot (TAD contract, tad-audio.inc + AGENTS.md) --------------
    ; Interrupts are DISABLED here BY CONSTRUCTION: init.inc leaves NMI off and
    ; the only $4200 write is below, after scene enter. The S-SMP is still in
    ; the IPL and the init chain above puts us well past the 40-scanline
    ; post-reset minimum. Tad_Init runs ONCE per power-on (re-calling
    ; hardlocks). The song load is ASYNC — Tad_Process streams it from the main
    ; loop and PLAY_SONG_IMMEDIATELY (the TAD default) starts it as soon as it
    ; lands.
    ;
    ; THIS IS THE ONLY Tad_LoadSong IN THE RAIL, and that is the mechanism, not
    ; an omission: music surviving the mosaic wipe both ways is the ABSENCE of
    ; any further load — neither scene's enter/resume touches the song, so the
    ; SPC never restarts and the ARAM upload persists across every swap —
    ; the same mechanism the room game relies on.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- the game's own globals, before anything reads them ---------------
    lda #SPAWN_TX
    sta z:RPG_CAM_TX
    lda #SPAWN_TY
    sta z:RPG_CAM_TY
    lda #TOWN_SPAWN_TX
    sta z:RPG_TOWN_TX
    lda #TOWN_SPAWN_TY
    sta z:RPG_TOWN_TY
    stz z:RPG_STEP_DX
    stz z:RPG_STEP_DY
    stz z:RPG_STEP_N                ; step_n + pend, both bytes, in one store
    stz z:RPG_T0
    stz a:US_VISITS
    ; ---- the battery: restore the town position + visit count if a slot
    ;      verifies. Branches on sv_load's RETURN CODE, never on an SRAM byte —
    ;      virgin SRAM is power-on garbage under the random regime.
    jsr rpg_try_load
    ; ---- enter the boot scene (id 0 = overworld) under forced blank -------
    ldx #(SCENE_OVERWORLD * 2)
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad -------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN
    rep #$20
    .a16
; THE ORDER IS LOAD-BEARING, three times over — mode7_explore's reasons:
;   * rpg_swap_service FIRST: it runs under the forced blank the previous
;     frame's NMI committed, and it must finish before anything reads the
;     scene id.
;   * mosaic_tick BEFORE sm_tick, so the frame the dissolve goes idle is a
;     frame sm_tick already sees as live.
;   * rpg_fade_tick AFTER both: the gate is what stops it writing the shadow
;     byte whole and dropping the forced blank a swap is holding.
@loop:
    .a16
    .i16
    jsr input_read
    jsr rpg_swap_service
    jsr mosaic_tick
    jsr sm_tick
    jsr rpg_fade_tick
    ; ---- audio pump: once per frame, MAIN THREAD ONLY. The TAD ABI forbids
    ; ISR calls, so this must never move into sm_nmi_hook. It is ordered here
    ; — after the tick chain, before the frame sync — for room's reason and no
    ; other: it touches APUIO and its own claimed DP/lowram, no PPU state, so
    ; it is independent of the three load-bearing orderings above. During a
    ; wipe's forced-blank stretch some frames are skipped; fine by design —
    ; the SPC runs autonomously and the queues are just processed late.
    ; ~55 CPU cycles steady state (audio/feature.toml, measured).
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop

; --- text_dp_init: the text engine's global DP block ------------------------
; microzero's routine, verbatim in shape: the 3-byte pointer's bank byte needs
; an 8-bit store of its own, because a 16-bit one stomps the neighbouring claim.
text_dp_init:
    .a16
    .i16
    stz z:ES_TXT_PTR
    stz z:ES_TXT_TMP
    sep #$20
    .a8
    stz z:ES_TXT_PTR + 2
    rep #$20
    .a16
    stz z:ES_TXT_Q + 0
    stz z:ES_TXT_Q + 2
    stz z:ES_TXT_Q + 4
    rts
