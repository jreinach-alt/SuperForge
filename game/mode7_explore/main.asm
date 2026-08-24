; =============================================================================
; mode7_explore — the streaming Mode 7 overworld
; =============================================================================
; An avatar walks a 512x512-tile world — 4096x4096 px, sixteen times the area
; the Mode 7 VRAM window can hold — and the world streams in around her as she
; goes. The picture dawns in from black over the first frames; the D-pad steps
; on the tile grid, one 8 px slide at a time; water and mountains refuse.
;
; TWO SCENES. Step onto the one enterable house and a MOSAIC WIPE carries her
; into a Mode 1 town interior; step onto its door and the same wipe carries her
; back out, at the spot she left. game.toml's header carries the composition
; reasoning, including the features deliberately NOT composed and which
; allocator check would have refused each.
;
; THE TRANSITION IS THIS FILE'S, NOT scene_mgr's. `sm_request` is never called:
; the wipe is a mosaic dissolve rather than a fade, and `overworld::enter` would
; re-upload the 32 KB seed centred on SPAWN — throwing away the very position
; the return exists to preserve. What drives it instead is three small things
; below: `mxx_blank_now` (mosaic's swap callback), `mxx_swap_service` (the
; blank-phase rebuild it defers to the next frame) and the scene id this file
; writes into ES_SM_CTL so `sm_tick` dispatches the right tick. The phase byte
; stays 0 for the ROM's life.
;
; NO AUDIO. `tad_rom` is not in this game's globals, so there is no Tad_Init, no
; Tad_Process pump and no TAD object in the link — the rail's subject is the
; streamed picture. Adding audio is a claim in game.toml plus the two calls.

.p816
.smart

.define SF_HDR_TITLE "MODE7 EXPLORE"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.assert SF_INC_FORMAT = 1, error, "this rail was written against allocator include format 1 — allocate.py now emits a different symbol shape; re-read the emitted engine_state_globals.inc before bumping this"
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"              ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the GLOBAL half of the composition game.toml declares) -
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "oam_sprites.asm"
.include "mosaic.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro mxl_tick's loop counts
                                    ;   with. INCLUDED BEFORE THE SCENES, and
                                    ;   it must be — a ca65 macro has to be
                                    ;   defined before the line that expands
                                    ;   it, and m7x_logic.asm is inside
                                    ;   scenes/overworld.asm's scope.

; =============================================================================
; THE ROM CLAIM SITES
; =============================================================================
; Each site .asserts its blob's linker placement against the allocator's emitted
; claim, so a drift between the map and the tree stops the build. The PRESENCE
; side is `make rom-unbacked` (docs/37): a claim with no .incbin here would
; reserve the window and let whatever the linker left there be read as art —
; which for `m7x_map` would be a plausible-looking world streamed out of the
; neighbouring blob.

; --- the streamed world: eight 32 KB chunks, one per LoROM window ------------
; A `bank_tiled` claim's chunk symbols exist only as `.ident(.sprintf(...))`
; expansions, which is the one templated form the backing gate expands. The
; chunk COUNT comes from ES_R_M7X_MAP_CHUNKS — a narrated `.repeat 8` is its own
; refusal (docs/37 §5 limit 1), and the derivation is not ceremony: grow the
; world and the count follows without anyone editing a number here.
;
; The `+ 1` is the allocator's first ROM window (window 0 is CODE+RODATA), read
; off build/m7x/allocation_report.txt rather than chosen — and the two .asserts
; below are what make that agreement checkable instead of assumed.
.repeat ES_R_M7X_MAP_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 1)
.ident(.sprintf("m7x_map_t%d", WI)):
    .incbin "m7x_map.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("m7x_map_t%d", WI)) = .ident(.sprintf("ES_R_M7X_MAP_T%d_BANK", WI)), error, "m7x_map chunk bank drifted from allocator claim"
.assert .loword(.ident(.sprintf("m7x_map_t%d", WI))) = .ident(.sprintf("ES_R_M7X_MAP_T%d_ADDR", WI)), error, "m7x_map chunk addr drifted from allocator claim"
; CONSECUTIVE BANKS ARE AN OUTCOME, NOT A GUARANTEE — so state it here, where
; it can be checked. `place_rom` first-fits each chunk INDEPENDENTLY, rescanning
; the window free lists from index 0, and `RomClaim.bank_tiled` promises only
; "pre-chunked so every chunk fits one window" — never adjacent. Driving the
; real packer over synthetic claim sets returns orders like [1,2,4], [2,3,1] and
; [4,3]: a `window=` pin, a ragged blob behind a small pin, and two ragged tiled
; blobs with no pin at all.
;
; THREE consumers on this rail spell the bank as `T0_BANK + index` and would
; silently read the wrong one: mode7_stream's MVN stub table (M7S_BLOB_BANK +
; CI), its stream_stage_col span bank, and col_map's chunk term
; (`ty >> CM_CHUNK_SHIFT` + CM_WORLD_BLOB_BANK). The result would be plausible
; terrain streamed out of the wrong rows with every gate green, which is the
; silent-corruption class this repo names.
;
; Stated HERE and not in a feature, because this is the only file that can name
; all eight chunk symbols: a `%s` template is refused outright by no_literals'
; blanket-rom-template pass, so a feature file cannot reach them. Same site and
; all eight chunk symbols: a `%s` template is refused outright by no_literals'
; blanket-rom-template pass, so a feature file cannot reach them. Same site and
; same reasoning as game/microzero/main.asm.
.assert .ident(.sprintf("ES_R_M7X_MAP_T%d_BANK", WI)) = ES_R_M7X_MAP_T0_BANK + WI, error, "m7x_map chunks are not bank-consecutive — the T0_BANK + index addressing in mode7_stream and col_map would read the wrong bank"
.endrepeat

; --- the initial VRAM image: 32,768 B = one WHOLE window --------------------
; So it gets a window to itself and the single DMA that uploads it cannot cross
; a bank boundary (a DMA's A-bus address wraps within its bank rather than
; carrying).
.segment "BANK9"
m7x_seed_bin:
    .incbin "m7x_seed.bin"
.assert ^m7x_seed_bin = ES_R_M7X_SEED_BANK, error, "m7x_seed bank drifted from allocator claim"
.assert .loword(m7x_seed_bin) = ES_R_M7X_SEED_ADDR, error, "m7x_seed addr drifted from allocator claim"

; --- everything small, in the window the packer put it in -------------------
; The ORDER here is the allocator's, not a preference: place_rom packs by
; (-bytes, name), so the 2 KB affine LUT leads, then the 1,216 B avatar sheet,
; then the 256 B terrain LUT, then the two 128/32 B town blobs and the three
; palettes alphabetically. A re-sort moves an address and the build stops with
; the claim named.
.segment "BANK10"
m7_lut_bin:
    .incbin "m7_affine_lut.bin"
.assert ^m7_lut_bin = ES_R_M7_LUT_BANK, error, "m7_lut bank drifted from allocator claim"
.assert .loword(m7_lut_bin) = ES_R_M7_LUT_ADDR, error, "m7_lut addr drifted from allocator claim"
m7x_obj_chr_bin:
    .incbin "m7x_obj_chr.bin"
.assert ^m7x_obj_chr_bin = ES_R_M7X_OBJ_CHR_BANK, error, "m7x_obj_chr bank drifted from allocator claim"
.assert .loword(m7x_obj_chr_bin) = ES_R_M7X_OBJ_CHR_ADDR, error, "m7x_obj_chr addr drifted from allocator claim"
m7x_terr_bin:
    .incbin "m7x_terr.bin"
.assert ^m7x_terr_bin = ES_R_M7X_TERR_BANK, error, "m7x_terr bank drifted from allocator claim"
.assert .loword(m7x_terr_bin) = ES_R_M7X_TERR_ADDR, error, "m7x_terr addr drifted from allocator claim"
; The Mode 1 interior's tiles and palette. Backed NOW even though this slice
; never reads them: `make rom-unbacked` is a per-COMPOSITION check, and the
; claims are in the composition the moment m7x_rom is in `globals`. Backing them
; here is also what lets the town slice be additive — it inherits a placed,
; asserted blob instead of renegotiating the packer's answer for every other
; claim in the window.
m7x_town_chr_bin:
    .incbin "m7x_town_chr.bin"
.assert ^m7x_town_chr_bin = ES_R_M7X_TOWN_CHR_BANK, error, "m7x_town_chr bank drifted from allocator claim"
.assert .loword(m7x_town_chr_bin) = ES_R_M7X_TOWN_CHR_ADDR, error, "m7x_town_chr addr drifted from allocator claim"
m7x_obj_pal_bin:
    .incbin "m7x_obj_pal.bin"
.assert ^m7x_obj_pal_bin = ES_R_M7X_OBJ_PAL_BANK, error, "m7x_obj_pal bank drifted from allocator claim"
.assert .loword(m7x_obj_pal_bin) = ES_R_M7X_OBJ_PAL_ADDR, error, "m7x_obj_pal addr drifted from allocator claim"
m7x_town_pal_bin:
    .incbin "m7x_town_pal.bin"
.assert ^m7x_town_pal_bin = ES_R_M7X_TOWN_PAL_BANK, error, "m7x_town_pal bank drifted from allocator claim"
.assert .loword(m7x_town_pal_bin) = ES_R_M7X_TOWN_PAL_ADDR, error, "m7x_town_pal addr drifted from allocator claim"
m7x_pal_bin:
    .incbin "m7x_pal.bin"
.assert ^m7x_pal_bin = ES_R_M7X_PAL_BANK, error, "m7x_pal bank drifted from allocator claim"
.assert .loword(m7x_pal_bin) = ES_R_M7X_PAL_ADDR, error, "m7x_pal addr drifted from allocator claim"

.segment "CODE"

; --- m7_affine (after the LUT blob its lookup reads) -----------------------
.include "m7_affine.asm"

; =============================================================================
; THE TRANSITION — a mosaic wipe in two halves, and why it is two
; =============================================================================
; `mosaic` JSRs its swap routine at PEAK BLACK, in the middle of `mosaic_tick`,
; in the middle of a frame. What the swap has to do on this rail is a long
; CPU-side VRAM rebuild — 2 KB of computed tilemap, 128 B of CHR, 32 B of
; palette — and that needs FORCED BLANK, not brightness 0. Brightness 0 is a
; black picture the PPU is still fetching every scanline; VRAM writes into it
; are not reliable, on hardware or in a cycle-accurate emulator.
;
; AND FORCED BLANK IS NOT OURS TO ASSERT DIRECTLY. INIDISP bit 7 lives in $2100,
; which scene_mgr claims and commits from the ES_SM_NMI+1 shadow in the NMI
; handler, and whose `scene_writes` deliberately withholds INIDISP from enter
; and boot code — its feature.toml names the hazard ("an enter-time INIDISP
; write would be reverted by the very next NMI"). `no_literals`' reg-ownership
; pass enforces that: a `sta a:$2100` here is refused by name.
;
; So the swap is split at exactly that seam. The callback below sets the
; shadow's blank bit and returns; the NEXT NMI commits it; and the rebuild runs
; at the top of the FOLLOWING main-loop iteration, by which time forced blank is
; genuinely on screen — the same two guarantees (blank on screen, NMI masked)
; that scene_mgr's own phase-2 switch makes, arrived at without a second writer
; of $2100. It costs one frame of the dissolve's fifteen-frame IN ramp, and both
; frames are black, so the split is invisible.
;
; The alternative considered and rejected: opening INIDISP through
; `scene_writes` on scene_mgr's claim. That is an engine change to a GLOBAL
; feature, it weakens a guard every rail in the tree inherits, and it buys one
; frame of ramp. Not worth it for a rail-local need.

; The swap request, held in a game-lifetime word because it is written by the
; scene that is LEAVING and read after the one that is arriving has begun.
SWAP_NONE          = 0
SWAP_TO_TOWN       = 1
SWAP_TO_OVERWORLD  = 2

; Scene ids, in the manifest order game.toml declares. These index all three
; dispatch tables AND are what `sm_tick` reads out of ES_SM_CTL.
SCENE_OVERWORLD = 0
SCENE_TOWN      = 1

; --- the two mosaic swap callbacks -----------------------------------------
; In/out: A8/I16, DB=0 — mosaic's `_mos_call_swap` contract, which is a TAIL
; CALL through `jmp (abs)` and so cannot be checked by ca65 or by width-check in
; either direction. Clobbers A.
;
; WIDTH-RISK: entered A8/I16 and MUST return A8/I16 with DB unchanged. Reached
; only through mosaic's function pointer, so no same-file arrival exists for the
; annotations below to be checked against — these markers are the contract.
;
; THE REQUEST IS RAISED HERE AND NOWHERE ELSE, and that is the fix for a real
; bug this rail shipped for one build: the arm site used to set the request word
; and `mxx_swap_service` fired on the very next frame — 20 frames early, with a
; fully-lit picture on screen, so the rebuild ran without forced blank and the
; whole dissolve played over an already-swapped scene. Setting the word only
; from the callback makes the word MEAN "peak black has happened", which is
; exactly the condition the service needs, rather than "a wipe was requested",
; which is a different fact 20 frames earlier.
;
; The other half is the forced-blank bit. `_mos_apply` preserves the shadow's
; HIGH nibble on every subsequent frame (`and #240` / `ora bright`), so the
; blank raised here survives every brightness write of the IN ramp until
; mxx_swap_service clears it — precisely the property mosaic's header promises
; the swap routine.
mxx_blank_to_town:
    .a8
    .i16
    lda #SWAP_TO_TOWN
    bra _mxx_blank_now
mxx_blank_to_overworld:
    .a8
    .i16
    lda #SWAP_TO_OVERWORLD
_mxx_blank_now:
    .a8
    .i16
    sta z:US_SWAP_REQ               ; the service's WHICH...
    stz z:US_SWAP_REQ + 1           ; ...and the high half of the u16 it reads
    lda z:ES_SM_NMI + 1
    ora #128                        ; INIDISP bit 7 — committed by the next NMI
    sta z:ES_SM_NMI + 1
    rts

; --- the scenes (each carries its own map + its scene-scoped features) -----
.include "scenes/overworld.asm"
.include "scenes/town.asm"

; --- mxx_swap_service: the blank-phase half of a swap ----------------------
; In/out: A16/I16, DB=0. Called FIRST in the main loop, before anything else
; touches the frame. Clobbers A, X, Y.
;
; Runs at most once per wipe, on the frame after `mxx_blank_now` fired. Forced
; blank is on screen (the NMI that ended the previous frame committed it) and
; NMI is masked here for the duration, because the rebuild is far longer than a
; frame and an NMI landing inside it would set VMADD for the OAM and affine
; commits and drop the rest of the upload at whatever addresses followed. That
; is the hazard CLAUDE.md's forced-blank note names: forced blank does NOT mask
; NMI — $4200 bit 7 does.
;
; The scene id flips HERE rather than inside either scene, because this file is
; what owns the dispatch tables and the manifest order they encode.
mxx_swap_service:
    .a16
    .i16
    lda z:US_SWAP_REQ
    beq @none
    sep #$20
    .a8
    stz a:$4200                     ; NMITIMEN: NMI + auto-joypad off
    lda a:$4210                     ; RDNMI: ack any pending edge
    rep #$20
    .a16
    lda z:US_SWAP_REQ
    cmp #SWAP_TO_TOWN
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
    rep #$20
    .a16
    stz z:US_SWAP_REQ
    sep #$20
    .a8
    lda z:ES_SM_NMI + 1
    and #127                        ; drop forced blank — the IN ramp takes the
    sta z:ES_SM_NMI + 1             ;   low nibble from here on
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad back on
    rep #$20
    .a16
@none:
    .a16
    .i16
    rts

; --- mxx_fade_tick: the boot dawn-in, gated ---------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; `fade` and `mosaic` are TWO WRITERS OF ONE SHADOW and the allocator cannot see
; it: neither claims INIDISP, because scene_mgr does. mosaic's feature.toml
; states the contract in the API instead — "the consumer gates its fade tick on
; `mosaic_active`" — and this is that gate. It is not a nicety: `fade_tick`
; writes the shadow byte WHOLE (`sta z:ES_SM_NMI+1`), so a fade running through
; a wipe would drop the forced-blank bit the swap is holding, un-blanking the
; screen in the middle of a 2 KB VRAM rebuild.
;
; The ramp this protects is the boot dawn-in, and nothing else on this rail
; arms `fade` — so after the first half-second the gate costs one query and one
; branch per frame, forever.
mxx_fade_tick:
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

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Three commits, no ordering constraint between them. `stream_nmi_dispatch`
; programs its own VMAIN and VMADD per slot, which is what makes hook order free
; here (AGENTS.md's "VBlank VRAM writers program their own VMAIN + VMADD"), and
; oam_nmi_dma and m7a_nmi_commit touch neither.
;
; DELIBERATELY SHORT. A long hook corrupts HDMA mid-frame: sm_nmi_core MVNs its
; 128-byte channel shadow to $4300 AFTER the hook returns, and a hook that
; overruns VBlank lands that block during active display. Everything per-frame
; on this rail is in the tick; what is here is three transfers of already-built
; state.
; THE STREAM DRAIN IS GATED ON THE SCENE, and it has to be. `stream_nmi_dispatch`
; reads its pending row/column counts out of SCENE DP — and scene DP is REUSED
; across scenes, so in the town those same bytes are the interior's own state.
; Ungated, an armed count would be whatever `town_tx` happens to hold, and the
; NMI would DMA staging WRAM into the Mode 7 tilemap the whole visit exists to
; preserve. Testing the scene id is one load and one branch, and it is the only
; test that is true by construction rather than by the previous scene having
; tidied up after itself.
; CONTRACT mode7_explore::sm_nmi_hook
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       the scene's committed shadows and staged buffers
;   out:      the OAM shadow committed and, on the overworld scene only, the staged
;             row/col slots drained
;   clobbers: A, X, Y and the flags — sm_nmi_core saves and restores around
;             the call, so the hook owns all three for its duration
;   assumes:  VBlank, from sm_nmi_core. The A8/I16 pair is sm_nmi_core's
;             contract, and it is what every routine this hook calls declares
;             on its own entry
;   tail:     rts, back into sm_nmi_core — which then MVNs the 128-byte
;             channel shadow to $4300 and applies HDMAEN
;
; THE NAME IS QUALIFIED because every rail has an `sm_nmi_hook` and they are
; 37 different routines. The qualifier keys this declaration uniquely; a bare
; `jsr sm_nmi_hook` from scene_mgr.asm links against a different one in every
; rail's build, so the cross-file pass deliberately does not resolve it.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    lda z:ES_SM_CTL             ; cur scene id
    bne @no_stream              ; the town streams nothing
    jsr overworld::stream_nmi_dispatch  ; drain the staged row/col slots
@no_stream:
    .a8
    .i16
    jsr m7a_nmi_commit          ; the eight Mode 7 ports, from the DP shadow
    jsr mosaic_nmi_commit       ; $2106 from the wipe's shadow — UNCONDITIONAL,
                                ;   so an idle mosaic establishes $00 rather
                                ;   than leaving power-on garbage there
    rts

; --- scene dispatch tables (manifest order: overworld=0, town=1) -----------
; AFTER the scene includes: ca65 resolves a scope's members only once the scope
; has been seen, so these tables must follow them.
;
; `sm_enter_tab` and `sm_exit_tab` are NEVER INDEXED on this rail past boot —
; the transition is mxx_swap_service, not `sm_request`, so the phase machine
; never runs. They are complete anyway because the tables are indexed by scene
; id and a hole is what the day someone adds a title screen would fall into.
; The town's entry is its `resume`, which is the routine that would be its enter
; if the phase machine were driving.
sm_enter_tab:   .word overworld::enter,  town::resume
sm_tick_tab:    .word overworld::tick,   town::tick
sm_exit_tab:    .word overworld::exit,   town::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
;
; THE DAWN-IN IS SET UP BY OMISSION, and that is worth stating because it looks
; like nothing. sm_init zeroes ES_SM_NMI, whose +1 byte is the INIDISP shadow —
; so the first armed VBlank commits $00: display ON, brightness 0. The scene's
; enter arms `fade`, whose tick then walks the shadow 0 -> 15. Nothing here
; writes $2100 directly and nothing may: scene_mgr commits INIDISP from that
; shadow on every armed frame, so a bare write would be reverted by the next
; VBlank (scene_mgr's feature.toml calls it the enter-time-INIDISP hazard).
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr mosaic_init             ; the wipe is idle and its $2106 shadow is $00 —
                                ;   both are READ BEFORE ANY WRITE (mosaic_tick
                                ;   from frame one, the NMI commit from the
                                ;   first armed VBlank), so this is a real
                                ;   establishment and not a to-be-safe fill.
                                ;   Mesen's uninit detector named the three
                                ;   bytes before this call existed.
    jsr oam_park_all            ; whole shadow written before its first DMA
    stz z:US_SWAP_REQ           ; no wipe pending — the write-before-read
                                ;   contract for the one global mxx_swap_service
                                ;   reads on the very first loop iteration
    ; ---- enter the boot scene (id 0 = overworld) under forced blank -------
    ldx #(SCENE_OVERWORLD * 2)
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    rep #$20
    .a16
; THE ORDER IS LOAD-BEARING, three times over:
;
;   * mxx_swap_service FIRST. It runs under the forced blank the previous
;     frame's NMI committed, and it must finish before anything reads the scene
;     id — it is what changes it.
;   * mosaic_tick BEFORE sm_tick. The frame the dissolve goes idle is then a
;     frame sm_tick already sees as live, so the avatar is drawn on the first
;     fully-bright frame rather than one frame after it. On the swap frame the
;     reverse case is equally deliberate: mosaic fires the callback, and sm_tick
;     then dispatches into a scene whose tick is still frozen by the query.
;   * mxx_fade_tick AFTER both. It is the gated boot ramp (see its header); the
;     gate is what stops it writing the shadow byte whole and dropping the
;     forced blank a swap is holding.
@loop:
    .a16
    .i16
    jsr input_read
    jsr mxx_swap_service        ; the blank-phase half of a wipe, if one is due
    jsr mosaic_tick             ; advance any wipe (fires the swap at peak black)
    jsr sm_tick                 ; the current scene's frame
    jsr mxx_fade_tick           ; the boot dawn-in, gated on mosaic_active
    jsr sm_frame_sync
    bra @loop
