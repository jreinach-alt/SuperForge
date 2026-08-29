; =============================================================================
; mill — mode 4's ONE offset word a column, and bit 15 picks its axis
; =============================================================================
; A machine hall. A buttress at the left wall, then four bays; in each, a bank
; of pistons pumping vertically and a pair of tread belts running sideways.
; Every one of them is driven by the SAME 32-word row, uploaded once a frame,
; because in mode 4 the PPU fetches one offset word per column and BIT 15 OF
; THAT WORD SELECTS ITS AXIS.
;
; THE OFFSET WORDS ARE FETCHED AFTER A COLUMN'S TILEMAP DATA, so the word at
; index j displaces SCREEN column j+1 and screen column 0 takes no word at all.
; Both halves of that are paid in the blob: the table stores every word a
; column early, and column 0 is drawn as WALL rather than as a machine that
; never moves. The rail shipped without either and it looked exactly like what
; it was — the leftmost column of every bay standing still beside three that
; ran. tools/gen_mill_assets.py's LEAD block is where it is paid.
;
; THAT IS THE HALF SMELTER CANNOT REACH. Modes 2 and 6 fetch a word for EACH
; axis inside a column's group, so a column is displaced on both and the axis
; is not a choice; mode 4 fetches only the first and reads bit 15 (Mesen2
; Core/SNES/SnesPpu.cpp FetchTileData case 2 under BgMode 4, and the bit-15
; test at :156-161). So one row here pumps a bay and runs the next one
; sideways, for the same zero HDMA channels and the same 64 B a frame.
;
; TWO AXES, TWO LAYERS, AND THAT IS FORCED. A displaced column moves WHOLE, so
; each axis imposes an invariance on the art it moves: a vertically displaced
; column must be identical row to row, and a horizontally displaced one shows
; the NEIGHBOURING TILE (the layer keeps its own fine three bits —
; hScroll = (BGnHOFS & 7) | (word & $3F8), SnesPpu.cpp:157) so its map row must
; hold one repeating texture. Both in one layer and a shifted belt column
; samples a piston's cap. BG1 takes the pistons, BG2 the belts, and the row
; then exercises the enable bits AND the axis bit in the same 32 words.
;
; AND THE TWO LAYERS ARE AT DIFFERENT DEPTHS, which is new in this tree. Mode 4
; renders bg1 8bpp and bg2 2bpp, so the CHR is two claims at 64 and 16 bytes a
; tile and each names its layer — the allocator's O9 joins each depth to the
; mode rather than leaving it to the art.
;
; B holds the flat control row: every column at rest, every enable bit and
; every axis bit still set, the same channel moving the same 64 B.
;
; Every address, every register encoding, the composed BGMODE and all four
; colour-math bytes come from the allocator's emitted symbols. Hardware I/O
; ports are the only literals in this file.

.p816
.smart

.define SF_HDR_TITLE "MILL"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "mill.inc"                 ; the rail's tuning
.include "mil_art.inc"              ; GENERATED — the hall's geometry (the row
                                    ;   stride, the phase count, the bay
                                    ;   layout, the map rows the art was drawn
                                    ;   at), so the table, its walker and the
                                    ;   tests cannot disagree
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro hall.asm's tick uses.
                                    ;   INCLUDED BEFORE THE SCENE, and it must
                                    ;   be — a ca65 macro has to be defined
                                    ;   before the line that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — or, for `mil_row`, as scroll offsets.
;
; THE ORDER IS THE PACKER'S, not this file's: the allocator sorts rom claims by
; size and these `.assert`s are what turn a disagreement into a build failure
; instead of art read from the wrong address.
.segment "BANK1"
mil_chr1_bin:
    .incbin "mil_chr1.bin"
.assert ^mil_chr1_bin = ES_R_MIL_CHR1_BANK, error, "mil_chr1 bank drifted from allocator claim"
.assert .loword(mil_chr1_bin) = ES_R_MIL_CHR1_ADDR, error, "mil_chr1 addr drifted from allocator claim"
mil_row_bin:
    .incbin "mil_row.bin"
.assert ^mil_row_bin = ES_R_MIL_ROW_BANK, error, "mil_row bank drifted from allocator claim"
.assert .loword(mil_row_bin) = ES_R_MIL_ROW_ADDR, error, "mil_row addr drifted from allocator claim"
mil_map1_bin:
    .incbin "mil_map1.bin"
.assert ^mil_map1_bin = ES_R_MIL_MAP1_BANK, error, "mil_map1 bank drifted from allocator claim"
.assert .loword(mil_map1_bin) = ES_R_MIL_MAP1_ADDR, error, "mil_map1 addr drifted from allocator claim"
mil_map2_bin:
    .incbin "mil_map2.bin"
.assert ^mil_map2_bin = ES_R_MIL_MAP2_BANK, error, "mil_map2 bank drifted from allocator claim"
.assert .loword(mil_map2_bin) = ES_R_MIL_MAP2_ADDR, error, "mil_map2 addr drifted from allocator claim"
mil_chr2_bin:
    .incbin "mil_chr2.bin"
.assert ^mil_chr2_bin = ES_R_MIL_CHR2_BANK, error, "mil_chr2 bank drifted from allocator claim"
.assert .loword(mil_chr2_bin) = ES_R_MIL_CHR2_ADDR, error, "mil_chr2 addr drifted from allocator claim"
mil_pal_bin:
    .incbin "mil_pal.bin"
.assert ^mil_pal_bin = ES_R_MIL_PAL_BANK, error, "mil_pal bank drifted from allocator claim"
.assert .loword(mil_pal_bin) = ES_R_MIL_PAL_ADDR, error, "mil_pal addr drifted from allocator claim"
.segment "CODE"

; --- the global feature runtime (after the blobs its uploads read) ---------
; `mil_opt.asm` is NOT here: its claims are scene-scoped, so it is included
; inside scenes/hall.asm's `.scope` where its symbols resolve (haze's shape,
; and smelter's).
.include "mil_bg.asm"

; --- the scene -------------------------------------------------------------
.include "scenes/hall.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE ENTRY, ONE TRANSFER, AND ONE SCENE. Every offset row this rail will ever
; show is already in ROM, so the only thing that has to reach the hardware each
; frame is WHICH row BG3's map is holding: 64 B, and it is the entire per-frame
; cost of thirty-two columns moving on the axes their own words name.
;
; UNGUARDED, because this rail has exactly one scene. Smelter guards its
; equivalent on the running scene id because the phase it reads is a
; scene-scoped dp claim that means something else in the title; here there is
; no other scene for it to mean something else in.
sm_nmi_hook:
    .a8
    .i16
    jsr hall::mil_nmi_row
    rts

; --- scene dispatch tables (manifest order: hall=0) ------------------------
sm_enter_tab:   .word hall::enter
sm_tick_tab:    .word hall::tick
sm_exit_tab:    .word hall::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr region_init                 ; the console's own region line, once. It
                                    ;   is game-lifetime state: a console does
                                    ;   not change region between scenes.
    ; ---- enter the boot scene (id 0 = hall) under forced blank -----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write:
    ; scene_mgr commits INIDISP in its NMI, so a direct write here would be
    ; overwritten on the first VBlank.
    ;
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate. Call it from A16 and the CPU
    ; reads the following opcode byte as the immediate's high half — the ramp
    ; never arms, INIDISP stays at brightness 0, and the ROM renders black with
    ; correct VRAM and CGRAM. Rule 6's silent-corruption class arriving through
    ; a CROSS-FILE caller/callee contract.
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    .i16
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
