; =============================================================================
; smelter — per-column vertical scroll out of BG3's tilemap, for no channel
; =============================================================================
; A foundry floor. Four steel plates hang over a cavern of molten metal and
; each rises and falls on its own; between them the melt erupts in arches,
; column by 8-pixel column. Nothing here is HDMA. In modes 2, 4 and 6 the PPU
; reads BG3's map entries as per-column scroll offsets instead of as tiles, so
; the displacement rides the tilemap fetch a layer already pays for: ZERO HDMA
; channels, zero cycles during active display, and one 64 B VBlank transfer a
; frame whatever the columns are doing.
;
; TWO SCENES, TWO DECLARED MODES, ONE SET OF ART. `title` is mode 1 with a
; text layer on BG3; `works` is mode 2 with the offset table on BG3. BG1 and
; BG2 are 4bpp in both, so `smt_bg` is global and does not change a byte
; across the edge. What changes is what BG3 MEANS — and that is the rail's
; hygiene lesson, one step past `hz_flat`'s: a scene can hand its successor a
; whole layer pointed at data.
;
; B flattens every column; Start returns to the title.
;
; Every address, every register encoding, the composed BGMODE and all four
; colour-math bytes come from the allocator's emitted symbols. Hardware I/O
; ports are the only literals in this file.

.p816
.smart

.define SF_HDR_TITLE "SMELTER"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "smelter.inc"              ; the rail's geometry + tuning
.include "smt_art.inc"              ; GENERATED — the offset table's layout
                                    ;   (stride, phase count, plate columns,
                                    ;   the map rows the art was drawn at), so
                                    ;   the table, its walker, the collision
                                    ;   and the tests cannot disagree
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "oam_sprites.asm"          ; the OAM shadow's VBlank DMA — global, so
                                    ;   the title parks its sprites rather than
                                    ;   not having any
.include "tick_scale.asm"           ; TS_STEP: the macro works.asm's tick uses.
                                    ;   INCLUDED BEFORE THE SCENES, and it must
                                    ;   be — a ca65 macro has to be defined
                                    ;   before the line that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — or, for `smt_col`, as scroll offsets.
.segment "BANK1"
; THE ORDER HERE IS THE PACKER'S, not this file's. The allocator sorts rom
; claims by size and the `.assert`s below are what turn a disagreement into a
; build failure instead of art read from the wrong address — which is exactly
; what happened when the knight's three blobs were appended in a reading order
; rather than in the packed one.
smt_obj_bin:
    .incbin "smt_obj.bin"
.assert ^smt_obj_bin = ES_R_SMT_OBJ_BANK, error, "smt_obj bank drifted from allocator claim"
.assert .loword(smt_obj_bin) = ES_R_SMT_OBJ_ADDR, error, "smt_obj addr drifted from allocator claim"
smt_col_bin:
    .incbin "smt_col.bin"
.assert ^smt_col_bin = ES_R_SMT_COL_BANK, error, "smt_col bank drifted from allocator claim"
.assert .loword(smt_col_bin) = ES_R_SMT_COL_ADDR, error, "smt_col addr drifted from allocator claim"
; THE WHOLE BLOB MUST LIE IN ONE BANK. smt_nmi_row builds a source address
; with a 16-bit add to the blob's low word and takes the bank from `^` — the
; same shape water's surf walker uses — so a blob straddling a boundary would
; have its later rows read out of the bank below.
SF_ASSERT_NO_BANK_CROSS smt_col_bin, ES_R_SMT_COL_SIZE, "smt_col crosses a bank"
smt_mmap_bin:
    .incbin "smt_mmap.bin"
.assert ^smt_mmap_bin = ES_R_SMT_MMAP_BANK, error, "smt_mmap bank drifted from allocator claim"
.assert .loword(smt_mmap_bin) = ES_R_SMT_MMAP_ADDR, error, "smt_mmap addr drifted from allocator claim"
smt_pmap_bin:
    .incbin "smt_pmap.bin"
.assert ^smt_pmap_bin = ES_R_SMT_PMAP_BANK, error, "smt_pmap bank drifted from allocator claim"
.assert .loword(smt_pmap_bin) = ES_R_SMT_PMAP_ADDR, error, "smt_pmap addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
smt_melt_anim_bin:
    .incbin "smt_melt_anim.bin"
.assert ^smt_melt_anim_bin = ES_R_SMT_MELT_ANIM_BANK, error, "smt_melt_anim bank drifted from allocator claim"
.assert .loword(smt_melt_anim_bin) = ES_R_SMT_MELT_ANIM_ADDR, error, "smt_melt_anim addr drifted from allocator claim"
; ONE BANK, same reason as smt_col: smt_nmi_melt adds the frame's offset to the
; blob's low word with a 16-bit add and takes the bank from `^`.
SF_ASSERT_NO_BANK_CROSS smt_melt_anim_bin, ES_R_SMT_MELT_ANIM_SIZE, "smt_melt_anim crosses a bank"
smt_chr_bin:
    .incbin "smt_chr.bin"
.assert ^smt_chr_bin = ES_R_SMT_CHR_BANK, error, "smt_chr bank drifted from allocator claim"
.assert .loword(smt_chr_bin) = ES_R_SMT_CHR_ADDR, error, "smt_chr addr drifted from allocator claim"
smt_hrow_bin:
    .incbin "smt_hrow.bin"
.assert ^smt_hrow_bin = ES_R_SMT_HROW_BANK, error, "smt_hrow bank drifted from allocator claim"
.assert .loword(smt_hrow_bin) = ES_R_SMT_HROW_ADDR, error, "smt_hrow addr drifted from allocator claim"
smt_pal_bin:
    .incbin "smt_pal.bin"
.assert ^smt_pal_bin = ES_R_SMT_PAL_BANK, error, "smt_pal bank drifted from allocator claim"
.assert .loword(smt_pal_bin) = ES_R_SMT_PAL_ADDR, error, "smt_pal addr drifted from allocator claim"
smt_obj_pal_bin:
    .incbin "smt_obj_pal.bin"
.assert ^smt_obj_pal_bin = ES_R_SMT_OBJ_PAL_BANK, error, "smt_obj_pal bank drifted from allocator claim"
.assert .loword(smt_obj_pal_bin) = ES_R_SMT_OBJ_PAL_ADDR, error, "smt_obj_pal addr drifted from allocator claim"
smt_anim_bin:
    .incbin "smt_anim.bin"
.assert ^smt_anim_bin = ES_R_SMT_ANIM_BANK, error, "smt_anim bank drifted from allocator claim"
.assert .loword(smt_anim_bin) = ES_R_SMT_ANIM_ADDR, error, "smt_anim addr drifted from allocator claim"
.segment "CODE"

; --- the global feature runtimes (after the blobs their uploads read) ------
; `smt_opt.asm` is NOT here: its claims are scene-scoped, so it is included
; inside scenes/works.asm's `.scope` where its symbols resolve (haze's shape).
; `smt_bg` is global — both scenes draw the same world — so it sits at file
; scope and each scene calls it.
.include "smt_bg.asm"

; --- the rail's own shared enter helpers -----------------------------------
; These are RAIL routines, not feature routines: they establish the layer
; bases both scenes share, from symbols the allocator emitted. The registers
; they write are `scene_writes` permissions on `smt_bg`, which this rail
; composes as a GLOBAL — which is what puts the writes inside the globals'
; union no_literals checks main.asm against.

; --- smt_layer_bases: BG1's and BG2's configuration ------------------------
; CONTRACT smelter::smt_layer_bases
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1SC, BG2SC and BG12NBA established for the scene now entering
;   clobbers: A, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; IDENTICAL IN BOTH SCENES, and that is the demonstration: BG1 and BG2 are
; 4bpp under mode 1 and under mode 2 alike, so the same maps at the same bases
; with the same CHR carry the same picture. Neither BGMODE nor either scroll
; port is here — the mode is a [[claims.video]] claim per scene, and the two
; VOFS ports answer to `smt_flat` on the title and `smt_opt` in the works.
;
; BG12NBA carries BOTH layers' CHR base nibbles in one write-only byte, so it
; has exactly one owner however the layers are declared. Both nibbles name the
; same shared CHR page, and the two emitted symbols are OR'd rather than
; narrated (breaker_bg.asm:209 is the precedent).
smt_layer_bases:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_layer_bases"
    sep #$20
    .a8
    lda #ES_V_SMT_PMAP_SC_BASE
    sta a:$2107                     ; BG1SC: the plate map at its claimed base
    lda #ES_V_SMT_MMAP_SC_BASE
    sta a:$2108                     ; BG2SC: the melt map at its claimed base
    lda #(ES_V_SMT_CHR_NBA | (ES_V_SMT_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: both layers read one CHR page
    rep #$20
    .a16
    rts

; --- the scenes ------------------------------------------------------------
.include "scenes/title.asm"
.include "scenes/works.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE ENTRY, AND IT IS ONE TRANSFER. The world does not scroll, the text is
; written once per scene under forced blank, and every offset row this rail
; will ever show is already in ROM — so the only thing that has to reach the
; hardware every frame is WHICH row BG3's map is holding. That is 64 B, and it
; is the entire per-frame cost of thirty-two independently moving columns.
;
; IT IS GUARDED BY THE RUNNING SCENE, not called unconditionally. The phase it
; reads is `smt_opt`'s SCENE-SCOPED dp claim, so in the title scene that
; direct-page word belongs to something else — reading it there would fire a
; transfer from an address derived from an unrelated value, into a BG3 page
; that is the text tilemap. The id comes from the edge symbol the allocator
; emitted rather than from a hand-written 1, which is the same reason
; SM_SWITCH takes its destination from the edge.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; the OAM shadow, every armed VBlank, in
                                    ;   both scenes: the title's entries are
                                    ;   the parked ones and they still have to
                                    ;   reach the hardware
    lda z:ES_SM_CTL                 ; the scene now running
    cmp #ES_E_TITLE_TO_WORKS_DST    ; ...the works?
    bne @done
    jsr works::smt_nmi_row          ; the phase -> BG3's V row, 64 B
@done:
    .a8
    .i16
    rts

; --- scene dispatch tables (manifest order: title=0, works=1) --------------
sm_enter_tab:   .word title::enter, works::enter
sm_tick_tab:    .word title::tick,  works::tick
sm_exit_tab:    .word title::exit,  works::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all                ; every sprite off-screen before anything
                                    ;   draws — power-on OAM is random (rule 5)
    jsr region_init                 ; the console's own region line, once. It
                                    ;   is game-lifetime state: a console does
                                    ;   not change region between scenes.
    ; ---- enter the boot scene (id 0 = title) under forced blank ----------
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
    ; therefore assembles as a ONE-byte immediate. Call it from A16 and the
    ; CPU reads the following opcode byte as the immediate's high half — the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders
    ; black with correct VRAM, CGRAM and OAM. That is rule 6's
    ; silent-corruption class arriving through a CROSS-FILE caller/callee
    ; contract.
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
