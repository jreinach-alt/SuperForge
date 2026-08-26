; =============================================================================
; lakeside — a sub-screen water layer, half-added over a lakeshore world
; =============================================================================
; BG1 carries the world, BG2 carries the water surface designated to the SUB
; screen, BG3 carries text. The blender adds the surface to the main screen at
; half intensity, so the lake bed shows THROUGH the water where the two
; overlap and at full intensity where the surface has no pixel.
;
; TWO SCENES, AND THE SECOND ONE IS THE HYGIENE LESSON. `lake` arms a blend;
; the composed state is per scene and nothing carries it across an edge, so a
; successor that composed no blend half would inherit the water's colour math
; and tint a title screen through registers it never wrote. `title` composes
; `blend_off` instead — a blend claim whose whole content is the off state —
; so the return edge disarms the blender through the same vocabulary that
; armed it, and the allocator's per-edge warning never arises.
;
; Every address, every register encoding and all four colour-math bytes come
; from the allocator's emitted symbols. Hardware I/O ports are the only
; literals in this file.

.p816
.smart

.define SF_HDR_TITLE "LAKESIDE"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "lakeside.inc"             ; the rail's geometry + tuning
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
.include "bg_text.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro lake.asm's tick uses.
                                    ;   INCLUDED BEFORE THE SCENES, and it must
                                    ;   be — a ca65 macro has to be defined
                                    ;   before the line that expands it.

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art.
.segment "BANK1"
lk_map_bin:
    .incbin "lk_map.bin"
.assert ^lk_map_bin = ES_R_LK_MAP_BANK, error, "lk_map bank drifted from allocator claim"
.assert .loword(lk_map_bin) = ES_R_LK_MAP_ADDR, error, "lk_map addr drifted from allocator claim"
wat_map_bin:
    .incbin "wat_map.bin"
.assert ^wat_map_bin = ES_R_WAT_MAP_BANK, error, "wat_map bank drifted from allocator claim"
.assert .loword(wat_map_bin) = ES_R_WAT_MAP_ADDR, error, "wat_map addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
lk_chr_bin:
    .incbin "lk_chr.bin"
.assert ^lk_chr_bin = ES_R_LK_CHR_BANK, error, "lk_chr bank drifted from allocator claim"
.assert .loword(lk_chr_bin) = ES_R_LK_CHR_ADDR, error, "lk_chr addr drifted from allocator claim"
wat_chr_bin:
    .incbin "wat_chr.bin"
.assert ^wat_chr_bin = ES_R_WAT_CHR_BANK, error, "wat_chr bank drifted from allocator claim"
.assert .loword(wat_chr_bin) = ES_R_WAT_CHR_ADDR, error, "wat_chr addr drifted from allocator claim"
lk_pal_bin:
    .incbin "lk_pal.bin"
.assert ^lk_pal_bin = ES_R_LK_PAL_BANK, error, "lk_pal bank drifted from allocator claim"
.assert .loword(lk_pal_bin) = ES_R_LK_PAL_ADDR, error, "lk_pal addr drifted from allocator claim"
wat_pal_bin:
    .incbin "wat_pal.bin"
.assert ^wat_pal_bin = ES_R_WAT_PAL_BANK, error, "wat_pal bank drifted from allocator claim"
.assert .loword(wat_pal_bin) = ES_R_WAT_PAL_ADDR, error, "wat_pal addr drifted from allocator claim"
.segment "CODE"

; --- the global feature runtimes (after the blobs their uploads read) ------
; `water.asm` is NOT here: its claims are scene-scoped, so it is included
; inside scenes/lake.asm's `.scope` where its symbols resolve (breaker's
; shape). `lake_bg` and `bg_text` are global — both scenes draw the same world
; and the same text layer — so they sit at file scope and each scene calls
; them.
.include "lake_bg.asm"

; --- the rail's own shared enter helpers -----------------------------------
; These are RAIL routines, not feature routines: they establish the display
; shape and the text both scenes share, from symbols the allocator emitted.
; The registers they write are `scene_writes` permissions on `lake_bg` and
; `bg_text`, both of which this rail composes as GLOBALS — which is what puts
; the writes inside the globals' union no_literals checks main.asm against.

; --- lk_display: the scene's base display shape ----------------------------
; CONTRACT lakeside::lk_display
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BGMODE, BG1SC, BG1HOFS/BG1VOFS, BG3SC, BG34NBA and
;             BG3HOFS/BG3VOFS established for the scene now entering
;   clobbers: A, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; BG12NBA is DELIBERATELY ABSENT: its two nibbles name BG1's and BG2's CHR
; bases, and only the lake scene has a BG2 base to name, so each scene writes
; that one byte itself. Everything here is identical in both scenes.
;
; BGMODE $09 is mode 1 plus the BG3-priority bit, which is what lets a BG3
; tile carrying the priority attribute sit above BG1 and BG2 — the text over
; the water. Both scroll pairs are write-twice latches set to LK_VOFS = -1 on
; the vertical axis, so world row r lands on picture rows 8r..8r+7 (see
; lakeside.inc).
lk_display:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lk_display"
    sep #$20
    .a8
    lda #$09                        ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #ES_V_LK_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                     ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 chr = the font base
    stz a:$210D                     ; BG1HOFS, low  (the world does not scroll)
    stz a:$210D                     ; BG1HOFS, high
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; BG3HOFS, high
    lda #<LK_VOFS
    sta a:$210E                     ; BG1VOFS, low
    sta a:$2112                     ; BG3VOFS, low
    lda #>LK_VOFS
    sta a:$210E                     ; BG1VOFS, high
    sta a:$2112                     ; BG3VOFS, high
    rep #$20
    .a16
    rts

; --- lk_text_arm: the font and a cleared BG3 tilemap -----------------------
; CONTRACT lakeside::lk_text_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the 96-glyph font in the text CHR page, the text tilemap
;             filled with spaces at this rail's attribute, and the BG3
;             sub-palette written
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; The four BG3 2bpp palette words are written here rather than in the asset
; blobs because bg_text's `text_pal` claim is four words at CGRAM 28 and this
; rail wants a plain two-tone face: index 0 is the transparent slot, 3 is the
; white the glyphs are drawn in. Every word is written explicitly — power-on
; CGRAM is random (rule 5).
lk_text_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lk_text_arm"
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                     ; CGADD = 28 (BG3 palette 7)
    stz a:$2122                     ; 0: transparent slot, black
    stz a:$2122
    stz a:$2122                     ; 1: unused by this face, black
    stz a:$2122
    stz a:$2122                     ; 2: unused by this face, black
    stz a:$2122
    lda #$FF                        ; 3: white $7FFF — the glyph ink
    sta a:$2122
    lda #$7F
    sta a:$2122
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #LK_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    rts

; --- lk_puts: one string at one tilemap cell -------------------------------
; CONTRACT lakeside::lk_puts
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the string's address low 16 (it must live in the RODATA
;             block `lk_strings` marks, which is where the bank comes
;             from), X = the VRAM word address to write at
;   out:      the string written as tiles at this rail's text attribute
;   clobbers: A, Y, N, Z, C, V
;   assumes:  forced blank — text_puts writes the VRAM port
;   tail:     rts
;
; The bank byte comes from `^lk_strings` rather than from the caller: every
; string this rail prints lives in one RODATA block, so one label answers for
; all of them and a caller cannot pass a bank that disagrees with its pointer.
lk_puts:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lk_puts"
    sta z:ES_TXT_PTR
    lda #LK_TXT_ATTR
    sta z:ES_TXT_TMP
    sep #$20
    .a8
    lda #^lk_strings
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    jsr text_puts
    rts

.segment "RODATA"
; The bank anchor lk_puts reads. Every string in this rail is emitted into
; this segment, so one label answers for all of them.
lk_strings:
.segment "CODE"

; --- the scenes ------------------------------------------------------------
.include "scenes/title.asm"
.include "scenes/lake.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE ENTRY, and it is the water's. The world does not scroll and the text is
; written once per scene under forced blank, so the only thing that has to
; reach the PPU every frame is the surface's horizontal offset.
;
; IT IS GUARDED BY THE RUNNING SCENE, not called unconditionally. The
; accumulator it reads is `water`'s SCENE-SCOPED dp claim, so in the title
; scene that direct-page word belongs to something else — reading it there
; would publish an unrelated value to a latch. The id comes from the edge
; symbol the allocator emitted rather than from a hand-written 1, which is
; the same reason SM_SWITCH takes its destination from the edge.
sm_nmi_hook:
    .a8
    .i16
    lda z:ES_SM_CTL                 ; the scene now running
    cmp #ES_E_TITLE_TO_LAKE_DST     ; ...the lake?
    bne @done
    jsr lake::wat_nmi_commit        ; the drift -> BG2HOFS
@done:
    .a8
    .i16
    rts

; --- scene dispatch tables (manifest order: title=0, lake=1) ---------------
sm_enter_tab:   .word title::enter, lake::enter
sm_tick_tab:    .word title::tick,  lake::tick
sm_exit_tab:    .word title::exit,  lake::exit

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
