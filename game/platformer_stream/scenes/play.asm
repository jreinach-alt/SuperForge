; =============================================================================
; play scene — the level, on a 64x64 BG1 ring
; =============================================================================
; The rail's only scene: it is entered once, at boot, for the ROM's life
; (game.toml's header carries the one-scene reasoning).
;
; WHAT THIS FILE OWNS: the LAYER and the COMPOSITION. The CHR, the palette and
; the backdrop word, the five BG1 registers this scene owns by permission, the
; bindings each scene-scoped feature demands, and the ORDER its enter and tick
; call them in. The ring's CONTENTS are `pfs_stream`'s on both axes; the
; player, the physics and the follow camera are `pfs_logic`'s.
;
; THE SCENE HAS NO RING FILL OF ITS OWN, and its absence is deliberate. The
; enter arms the streamer (`pfs_stream_arm`), which fills all 64x64 slots by
; running its own per-frame staging kernel 64 times under the forced blank —
; the true page geometry, the true staging shape, one code path. A second
; bulk-upload path here would be a second chance to be wrong, and a wrong ring
; addressing could hide behind a correct boot frame.
;
; LAYER OWNERSHIP: this enter is the only writer of BGMODE, TM, TS, BG1SC and
; BG12NBA in this ROM. That is not a convention here — pfs_bg's
; `[[claims.reg]]` opens exactly those five to scene code via `scene_writes`,
; and no_literals' declaration-that-lies check refuses the permission if
; pfs_bg.asm writes them too.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; =============================================================================
; THE SPAWN WINDOW
; =============================================================================
; The follow camera's answer at spawn, computed at assembly time because
; nothing moves yet: the player centred in a 256x224 screen. Both coordinates
; land well inside the world with the clamp inactive, and the .asserts below
; are what keep that true if the level's spawn ever moves — a negative or
; past-the-edge camera would wrap the ring silently rather than fail.
;
; PFS_SPAWN_X / PFS_SPAWN_Y and every PFS_WORLD_* constant come from
; pfs_world.inc, which the level generator EMITS beside the blobs. The ASM
; cannot disagree with the bytes about where the world's edges are.
PFS_SCREEN_W   = 256
PFS_SCREEN_H   = 224
PFS_CAM_X0     = PFS_SPAWN_X - PFS_SCREEN_W / 2
PFS_CAM_Y0     = PFS_SPAWN_Y - PFS_SCREEN_H / 2
.assert PFS_CAM_X0 >= 0, error, "spawn camera X is left of the world"
.assert PFS_CAM_Y0 >= 0, error, "spawn camera Y is above the world"
.assert PFS_CAM_X0 <= PFS_WORLD_W_PX - PFS_SCREEN_W, error, "spawn camera X is past the world's right edge"
.assert PFS_CAM_Y0 <= PFS_WORLD_H_PX - PFS_SCREEN_H, error, "spawn camera Y is past the world's bottom edge"

; =============================================================================
; THE RING, AND THE ONE FACT EVERYTHING TURNS ON
; =============================================================================
; A 64x64 BG tilemap is FOUR 32x32 hardware pages, not one rectangle:
;
;   VRAM(col,row) = base + (col >= 32 ? $400 : 0)     <- the horizontal page
;                        + (row >= 32 ? $800 : 0)     <- the vertical page
;                        + (row & 31) * 32 + (col & 31)
;
; The page arithmetic that follows from it is `pfs_stream`'s, not this scene's
; — the streamer owns the ring's CONTENTS on both axes and this file owns the
; LAYER. What is left here is the one size bit the enter writes into BG1SC.
;
; World tile (col, row) lives at ring slot (col & 63, row & 63) — POSITION-
; WRAPPED, never at a sequential buffer index. That distinction is the standing
; ring-addressing trap for Mode 7 planes and applies to normal-BG rings
; identically,
; and it is what makes the scroll registers below able to name a WORLD pixel:
; the hardware's own 512-px tilemap wrap lands the visible window on the right
; slots for as long as those slots hold the resident window, which is exactly
; what the streamer maintains.
PFS_SC_64X64   = 3                                   ; BGnSC size bits 1-0

; --- scene-scoped engine feature code — INSIDE the scope: its claims are
; scene-scoped, so its symbols must be too --------------------------------
.include "pfs_bg.asm"

; =============================================================================
; pfs_stream's WORLD BINDING — five symbols, declared here, with NO DEFAULT
; =============================================================================
; The streamer carries no default for any of them (pfs_stream.asm `.error`s per
; missing symbol, naming it): a defaulted blob streams the wrong ROM bytes into
; a plausible-looking level, which is rgb_gradient's recorded reasoning and it
; holds identically here.
;
; THE TWO BLOB SYMBOLS ARE `::`-QUALIFIED and the ring base is NOT, and the
; asymmetry is not a style choice: `pfs_flat` / `pfs_flat_row` are the GAME's
; rom claims (main.asm's globals map), while `pfs_map` is this SCENE's vram
; claim (engine_state_play.inc, included inside this scope). An unqualified
; parent-scope lookup is DEFERRED by ca65, and a deferred symbol is not a
; constant expression — which `_pfs_mvn_col`'s `.byte $54, dst, src` needs its
; bank operands to be.
;
; EACH BLOB IS EXACTLY ONE 32 KB LoROM WINDOW, which is what lets the streamer
; read a whole column (or row) without its source pointer crossing a bank seam
; — the property pfs_stream's header says the INCLUDER owes an assert for
; (m7_dungeon's shape). 32768 here is the window SIZE in bytes, which is
; silicon, and the same value col_map's own `rpc = 32768 / W` names below.
PFS_COL_WIN  = ::ES_R_PFS_FLAT_ADDR         ; column-major: col N's 128 words
PFS_COL_BANK = ::ES_R_PFS_FLAT_BANK         ;   at N*256
PFS_ROW_WIN  = ::ES_R_PFS_FLAT_ROW_ADDR     ; row-major: row M's at M*256
PFS_ROW_BANK = ::ES_R_PFS_FLAT_ROW_BANK
PFS_MAP_BASE = ES_V_PFS_MAP                 ; the ring's VRAM word base
.assert ::ES_R_PFS_FLAT_SIZE = 32768, error, "the column-major blob is not exactly one LoROM window — pfs_stream's source pointer would walk off the end of its bank"
.assert ::ES_R_PFS_FLAT_ROW_SIZE = 32768, error, "the row-major blob is not exactly one LoROM window — pfs_stream's source pointer would walk off the end of its bank"
.include "pfs_stream.asm"

; =============================================================================
; col_map's WORLD BINDING — six symbols, declared here, with NO DEFAULT
; =============================================================================
; col_map carries no default for any of these, because a defaulted
; world size reads real ROM bytes at the wrong stride and hands back a
; PLAUSIBLE flag. Each name is `::`-qualified: ca65 defers an unqualified
; parent-scope lookup, and a deferred symbol is not a constant expression,
; which col_map's assembly-time `.if CM_WORLD_BLOB_CHUNKS` needs it to be.
;
; W_LOG2 = H_LOG2 = 7 folds col_map's general form
;     rpc = 32768/W · bank = T0_BANK + (ty >> log2 rpc) · offset = (ty & (rpc-1))*W + tx
; to `pfs_col + ty*128 + tx` — a flat `base + tile_row*128 + tile_col`,
; instruction for instruction after the constants fold. The world
; sizes come from the generator's emitted .inc rather than being written
; twice, and the assert ties both to the blob's own claimed size.
CM_WORLD_W_LOG2      = ::PFS_WORLD_W_LOG2
CM_WORLD_H_LOG2      = ::PFS_WORLD_H_LOG2
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_PFS_COL_SIZE, error, "col_map's world size disagrees with the pfs_col claim"

CM_WORLD_BLOB        = ::ES_R_PFS_COL_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_PFS_COL_BANK
; DERIVED from the claim's own size, never narrated: 16 KB against a 32 KB
; LoROM window is 1, and the day the world outgrows a window it becomes 2
; without anyone editing a number. 32768 here is the window SIZE in bytes,
; which is silicon — the same value col_map's own `rpc = 32768 / W` names.
CM_WORLD_BLOB_CHUNKS = (::ES_R_PFS_COL_SIZE + 32767) / 32768
;
; HOW THIS RAIL DISCHARGES col_map's BANK-ADJACENCY OBLIGATION: it has none.
; That obligation is on a MULTI-chunk includer (microzero and the cost probe
; paste the two `.repeat` asserts); at CHUNKS = 1 col_map takes its
; constant-bank branch and never adds a chunk index, so there is nothing to be
; consecutive. The obvious companion guard — `.assert CM_WORLD_BLOB_CHUNKS = 1`
; — is deliberately NOT written, and `game/m7_dungeon/scenes/dungeon.asm`
; carries the measured reasoning at length: it cannot fire in any build that
; assembles, because every route to CHUNKS >= 2 is refused one layer up (a
; `bank_tiled` claim stops emitting the plain `_SIZE`/`_ADDR`/`_BANK` symbols
; these three lines name; a DMA-source claim past a window is refused by the
; allocator outright; a non-DMA one emits `_SIZE` twice and ca65 refuses the
; redefinition). An assert that cannot fire reads as coverage without being
; any. The size assert above CAN fire, and does the real work.
CM_FLAGS             = ::pfs_flags_bin
.include "col_map.asm"

; --- the player, over that world ------------------------------------------
; AFTER col_map: pfs_logic's probe kernel names CM_PX / CM_PY / CM_FLAG and
; calls col_map_at, so the binding above has to have been resolved first.
.include "pfs_logic.asm"

; --- the dusk sky ----------------------------------------------------------
; WHERE rgb_gradient's ramp LANDS is the SCENE's call, not the feature's, and
; there is no default (rgb_gradient.asm `.error`s without this). THE BACKDROP,
; which is a colour-math target of BG1 + backdrop: the ramp IS the sky. It
; shows through every transparent level cell — and this rail's sky is entirely
; transparent cells, since there is no BG2 skyline — while BG1's terrain and
; the hero keep their authored colours.
;
; `pfs_bg`'s CGRAM word 0 is the FLOOR of that ramp, so a
; frame with colour math off is still a warm dusk rather than bare black. The
; ramp adds the per-scanline sunset on top of it.
PFS_MATH_BACKDROP = 1 << 5
RG_MATH_LAYERS = PFS_MATH_BACKDROP
.include "rgb_gradient.asm"

; The FLOOR of that ramp, and the one colour in this scene that is not in a
; blob. Written as the 5-bit RGB it is rather than as the word $2C68 — so it
; reads as a colour and `no_literals` has nothing to weigh.
;
; WHY IT IS WRITTEN HERE AND NOT SHIPPED IN THE PALETTE. `pfs_bg`'s
; feature.toml has said since the foundation milestone that CGRAM word 0 —
; the BG's colour 0 and the hardware BACKDROP at once — carries this value.
; The vendored `pfs_pal.bin`'s word 0 is $0000, because for a BG tile colour 0
; is TRANSPARENT and the byte was never the sky. So the declaration had no code
; behind it and the sky rendered as the ramp alone over black: MEASURED, our
; scanline 2 read 5-bit (24, 8, 2) against a reference (31, 10, 13) — exactly
; this backdrop short by (8, 3, 11). One word, and it is the largest region of
; the picture.
PFS_SKY_DUSK = (11 << 10) | (3 << 5) | 8

; --- enter: the layer, then the ring ---------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's contract).
;
; THE SPAWN CAMERA IS WRITTEN TWICE, TO TWO OWNERS, FROM ONE PAIR OF CONSTANTS,
; and that is the ordering hazard mode7_explore's enter comments at length: the
; streamer's tile tracking has to start in sync with the window it just filled,
; or the first tick differences against a baseline the ring does not hold and
; the leading edge lands one tile out. Here both `pfs_arm` (which seeds
; `pfs_cam`, the pair the NMI hook scrolls with) and `pfs_stream_set_cam` take
; PFS_CAM_X0/PFS_CAM_Y0, which are the follow camera's own answer at the spawn
; — `pl_camera` computes clamp(spawn - half a screen) and the asserts at the
; top of this file are what keep the clamp inactive there — so the scroll, the
; ring and the first tick's camera agree BY CONSTRUCTION rather than by three
; transcriptions of the same number.
;
; A reload sits between the two calls because `pfs_arm` documents "Clobbers
; A, X, Y" and means it.
;
; FORCED BLANK AND A MASKED NMI ARE BOTH REQUIRED by `pfs_stream_arm` (its
; header states the precondition): the fill is 64 columns x 2 transfers, far
; longer than a frame, and forced blank alone does NOT mask NMI — $4200 bit 7
; does. scene_mgr zeroes NMITIMEN across the whole switch and MAIN only turns
; it on after this returns, which is the guarantee this call is written
; against.
enter:
    .a16
    .i16
    lda #PFS_CAM_X0
    ldx #PFS_CAM_Y0
    jsr pfs_arm                     ; CHR, palette + backdrop, the camera words
    lda #PFS_CAM_X0
    ldx #PFS_CAM_Y0
    jsr pfs_stream_set_cam          ; the streamer's tile tracking, same window
    jsr pfs_stream_arm              ; all 64x64 slots, through the per-frame
                                    ;   staging kernel — one code path, so a
                                    ;   bug in the addressing cannot hide
                                    ;   behind a correct boot frame
    ; ---- the backdrop word, over the palette blob's transparent colour 0 --
    ; AFTER pfs_arm, which uploaded all 16 words: this overwrites word 0 only.
    ; CGDATA is a word port written low byte then high byte.
    sep #$20
    .a8
    lda #ES_C_PFS_PAL_C
    sta a:$2121                     ; CGADD = the claim's base word (0)
    lda #<PFS_SKY_DUSK
    sta a:$2122
    lda #>PFS_SKY_DUSK
    sta a:$2122
    rep #$20
    .a16
    jsr pl_arm                      ; the OBJ half: hero CHR, OBJ palette, OBSEL
    jsr ts_arm                      ; the timebase's accumulators, and the
                                    ;   region's three velocity constants
    jsr pfs_spawn                   ; every byte of both player DP claims
    jsr rg_arm                      ; the dusk ramp's three COLDATA channels
    ; ---- mode + layers: the five registers pfs_bg opens to scene code -----
    sep #$20
    .a8
    lda #$01
    sta a:$2105                     ; BGMODE 1 (BG1 4bpp; no BG2/BG3 on screen)
    lda #(ES_V_PFS_MAP_SC_BASE | PFS_SC_64X64)
    sta a:$2107                     ; BG1SC: the claim's base + 64x64 size bits
    lda #ES_V_PFS_CHR_V_NBA
    sta a:$210B                     ; BG12NBA: BG1 in the low nibble
    lda #$11
    sta a:$212C                     ; TM: BG1 + OBJ
    stz a:$212D                     ; TS: nothing on the sub screen — an
                                    ;   established value, not power-on residue
    ; ---- the three gradient channels into the HDMAEN shadow ---------------
    ; scene_mgr's NMI applies this mask every armed frame, after MVNing the
    ; 128-byte channel shadow rg_arm just filled. ORed rather than stored: the
    ; mask is scene_mgr's, and a bare store would drop anything else armed.
    ; A8 here on purpose — ES_SM_NMI+2 is the LAST byte of a 3-byte claim, and
    ; a 16-bit store would run one byte into `fade`'s.
    lda z:ES_SM_NMI+2
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0. Display is active, so no VRAM writes may happen here.
;
; The player: walk, jump, the 16.8 vertical arc, the follow camera, the draw.
; Everything it produces reaches hardware through the NMI hook — the OAM
; shadow's DMA and the camera commit — because nothing here may touch VRAM,
; CGRAM or a PPU port while the beam is on.
;
; THE ORDER IS LOAD-BEARING, and it is mode7_explore's: the streamer runs
; AFTER the follow camera has settled. `pfs_logic_tick` ends with `pl_camera`
; (then the draw, which only reads it), so `pfs_cam` holds THIS frame's window
; by the time `pfs_stream_set_cam` reads it. Stream first and the ring is
; always one frame behind the picture — invisible at 2 px/frame of walk until
; a tile boundary is crossed, and then it is a torn column.
;
; NOTHING HERE TOUCHES VRAM. `pfs_stream_tick` stages into its WRAM slot
; buffers and publishes counts; the bytes reach the tilemap from
; `pfs_stream_nmi_dispatch` in the VBlank hook, which is the only place they
; may.
;
; THE CAMERA IS PASSED, not reached for — pfs_stream_set_cam takes world pixels
; in A and X (col_map's precedent: deciding WHICH window to show is the game's
; business, and a feature that read `pfs_bg`'s claim directly could no longer
; be built, or measured by its probe, without it).
tick:
    .a16
    .i16
    jsr pfs_logic_tick
    lda z:ES_PFS_CAM + 0            ; the window pl_camera just settled on...
    ldx z:ES_PFS_CAM + 2
    jsr pfs_stream_set_cam
    jsr pfs_stream_tick             ; ...and the leading edge it implies
    rts

; --- exit: nothing to put back ----------------------------------------------
; In/out: A16/I16, DB=0, forced blank. The rail never leaves this scene, and an
; exit that quietly did nothing to a register it had not armed would be worse
; than one that is honestly empty.
exit:
    .a16
    .i16
    rts

; --- the backdrop wash's data, a SCENE-scoped claim ------------------------
; `rgb_gradient` claims grad_tabs itself, so the blob lives here rather than in
; pfs_rom: ca65 resolves scopes backward and ES_R_GRAD_TABS_* is a symbol of
; THIS scope. It packs immediately after main.asm's global blobs in BANK3,
; which is the order the packer produced (build/pfs/allocation_report.txt).
;
; These are the bytes `rg_arm` DMAs into the three COLDATA channels, and the
; dusk ramp they draw is the largest region of the picture. They were placed
; and asserted a milestone before rgb_gradient was bound, because
; `make rom-unbacked` is a per-COMPOSITION check — the claim is in the
; composition the moment rgb_gradient is in the scene's features — which is
; also why nothing had to renegotiate the packer's answer when the binding
; landed.
.segment "BANK3"
grad_tabs_bin:
    .incbin "pfs_grad.bin"
.assert ^grad_tabs_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(grad_tabs_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"

.segment "CODE"
.endscope
