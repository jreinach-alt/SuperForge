; =============================================================================
; aurora — an end-credits sky, drawn WITHOUT A PALETTE
; =============================================================================
; Three figures on a cliff edge, backs to us, under three curtains of aurora.
; Colour rolls up through the curtains; stars twinkle; and in the black band
; below, "The End" writes itself out in one monoline cursive hand and holds.
;
; BG1 IS DIRECT COLOUR AND CONSULTS NO CGRAM WORD AT ALL. Its 8-bit pixel IS
; the colour — r3 g3 b2 — and the tilemap entry's 3-bit palette field supplies
; the low bit of each channel (Mesen2 SnesPpu.cpp:1071-1076). So the sky and
; the aurora are drawn from 2048 reachable colours on a palette budget of
; zero, and all 256 CGRAM words are left to BG2 and the sprites.
;
; THE FIELD IS ALSO THE WHOLE ANIMATION. In an indexed 8bpp layer those three
; tilemap bits are ignored outright (:1077). Here they are a live per-tile
; colour control, and `aur_roll` plays a wave through them — thirteen map rows
; a frame, precomputed, no CHR traffic and no CGRAM.
;
; AND NOTHING SCROLLS. The gradient survives 8bpp only as an ordered dither,
; and sliding neighbouring scanlines by different amounts destroys that
; dither's vertical coherence — the gradient stops reading as texture and
; starts reading as static. The rail swayed once; standing still is what keeps
; it clean.
;
; THE FIRST MODE-3 RAIL IN THIS TREE, forced rather than chosen: direct colour
; acts on an 8bpp layer alone, mode 7 has no second layer, and mode 4's 2bpp
; bg2 cannot hold two ridges, a cliff, two star levels and a nine-step
; anti-aliased ink ramp. Mode 3 is bg1 8bpp + bg2 4bpp.
;
; B holds the roll still. Start writes the word again.
;
; Every address, the composed BGMODE and all of the screen bytes come from the
; allocator's emitted symbols. Hardware I/O ports are the only literals here.

.p816
.smart

.define SF_HDR_TITLE "AURORA"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "aurora.inc"               ; the rail's tuning
.include "aur_art.inc"              ; GENERATED — the picture's geometry (the
                                    ;   pen's tile run, the roll's row range,
                                    ;   where the figures stand), so the ASM
                                    ;   and the tests cannot disagree
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank
.include "sf_asm.inc"               ; shared macros: SF_ASSERT_WIDTH + the
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
.include "oam_sprites.asm"          ; the OAM shadow's VBlank DMA
.include "tick_scale.asm"           ; TS_STEP, which the scene expands. It must
                                    ;   be included BEFORE the scene — a ca65
                                    ;   macro has to be defined before the line
                                    ;   that expands it

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art — or, for `aur_roll`, as tilemap words.
; THE ORDER AND THE SEGMENTS ARE THE PACKER'S, not this file's. The allocator
; sorts rom claims by SIZE and fills windows in that order, so the roll and the
; stream land in bank 1, the art in bank 2, and the sprite page in bank 3. The
; `.assert`s are what turn a repack into a build failure instead of art read
; from the wrong bank — they have already caught one here.
;
; THE ROLL IS 26 KB AND IT IS A DMA SOURCE. A transfer cannot span a bank —
; A1B is constant — and the allocator refuses a DMA-source claim larger than
; the 32 KB LoROM window by name. That refusal is why the phase count is 32
; and not 64: 64 pages would be 53,248 B, and `bank_tiled` is not the way out,
; because it chunks at the WINDOW size and 32,768 is not a multiple of the
; 832-byte page — a transfer would straddle the split.
.segment "BANK1"
aur_roll_bin:
    .incbin "aur_roll.bin"
.assert ^aur_roll_bin = ES_R_AUR_ROLL_BANK, error, "aur_roll bank drifted from allocator claim"
.assert .loword(aur_roll_bin) = ES_R_AUR_ROLL_ADDR, error, "aur_roll addr drifted from allocator claim"
aur_write_bin:
    .incbin "aur_write.bin"
.assert ^aur_write_bin = ES_R_AUR_WRITE_BANK, error, "aur_write bank drifted from allocator claim"
.assert .loword(aur_write_bin) = ES_R_AUR_WRITE_ADDR, error, "aur_write addr drifted from allocator claim"

.segment "BANK2"
aur_chr1_bin:
    .incbin "aur_chr1.bin"
.assert ^aur_chr1_bin = ES_R_AUR_CHR1_BANK, error, "aur_chr1 bank drifted from allocator claim"
.assert .loword(aur_chr1_bin) = ES_R_AUR_CHR1_ADDR, error, "aur_chr1 addr drifted from allocator claim"
aur_chr2_bin:
    .incbin "aur_chr2.bin"
.assert ^aur_chr2_bin = ES_R_AUR_CHR2_BANK, error, "aur_chr2 bank drifted from allocator claim"
.assert .loword(aur_chr2_bin) = ES_R_AUR_CHR2_ADDR, error, "aur_chr2 addr drifted from allocator claim"
aur_map1_bin:
    .incbin "aur_map1.bin"
.assert ^aur_map1_bin = ES_R_AUR_MAP1_BANK, error, "aur_map1 bank drifted from allocator claim"
.assert .loword(aur_map1_bin) = ES_R_AUR_MAP1_ADDR, error, "aur_map1 addr drifted from allocator claim"
aur_map2_bin:
    .incbin "aur_map2.bin"
.assert ^aur_map2_bin = ES_R_AUR_MAP2_BANK, error, "aur_map2 bank drifted from allocator claim"
.assert .loword(aur_map2_bin) = ES_R_AUR_MAP2_ADDR, error, "aur_map2 addr drifted from allocator claim"
aur_pal_bin:
    .incbin "aur_pal.bin"
.assert ^aur_pal_bin = ES_R_AUR_PAL_BANK, error, "aur_pal bank drifted from allocator claim"
.assert .loword(aur_pal_bin) = ES_R_AUR_PAL_ADDR, error, "aur_pal addr drifted from allocator claim"

.segment "BANK3"
aur_obj_bin:
    .incbin "aur_obj.bin"
.assert ^aur_obj_bin = ES_R_AUR_OBJ_BANK, error, "aur_obj bank drifted from allocator claim"
.assert .loword(aur_obj_bin) = ES_R_AUR_OBJ_ADDR, error, "aur_obj addr drifted from allocator claim"
.segment "CODE"

; --- the scene -------------------------------------------------------------
; THE FOUR aur_* FEATURES ARE INCLUDED INSIDE IT, not here. Their claims are
; scene-scoped, so their ES_V_/ES_C_/ES_D_ symbols live in
; `engine_state_credits.inc` and only resolve within the scope that includes
; it (mil_opt's shape, and haze's before it).
.include "scenes/credits.asm"

; --- sm_nmi_hook: per-frame VBlank work ------------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; THREE TRANSFERS AND THAT IS THE WHOLE FRAME. The OAM shadow, the roll's
; thirteen map rows, and whichever tiles the pen dirtied — at most
; AUR_WRITE_PEAK of them, and none at all once the word stands.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma                 ; the OAM shadow, every armed VBlank
    jsr credits::aur_roll_nmi       ; the curtains' map rows: ONE page
    jsr credits::aur_write_nmi      ; ...and the pen's tiles, if it moved
    rts

; --- scene dispatch tables (manifest order: credits=0) ---------------------
sm_enter_tab:   .word credits::enter
sm_tick_tab:    .word credits::tick
sm_exit_tab:    .word credits::exit

; --- MAIN: boot ------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all                ; every sprite off-screen before anything
                                    ;   draws — power-on OAM is random (rule 5)
    jsr region_init                 ; the console's own region line, once
    ldx #0
    jsr (sm_enter_tab, x)
    sep #$20
    .a8
    lda #$81
    sta a:$4200                     ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write:
    ; scene_mgr commits INIDISP in its NMI, so a direct write here would be
    ; overwritten on the first VBlank.
    ;
    ; CALLED IN A8, DELIBERATELY — `fade_start_in` is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate.
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
