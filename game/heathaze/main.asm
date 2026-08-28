; =============================================================================
; heathaze — heat shimmer as a per-scanline displacement, not as artwork
; =============================================================================
; BG1 carries a desert road running to a mesa ridge; BG3 carries text. Below
; the horizon an HDMA channel writes a different BG1HOFS on every scanline, so
; the whole lower layer bends — the road's converging edges, its centre dashes
; and the saguaro trunks with it — while the sky and the ridge above the band
; stay perfectly still.
;
; THE WARP IS A TABLE, NOT A TILE. Drawing heat haze as artwork means authoring
; pre-warped copies of everything it touches: double the tile budget, only the
; art you drew in advance can distort, and the distortion cannot follow the art.
; The PPU bends a whole layer natively and for free during active display. So
; hz_rom holds 32 complete HDMA tables at a 256 B stride and the entire
; per-frame cost of the effect is ONE 8-bit store to the channel's A1T high
; byte.
;
; TWO SCENES, AND THE SECOND ONE IS THE HYGIENE LESSON — the same lesson
; lakeside taught on the blender, on a register nobody had noticed it applied
; to. `desert` drives BG1HOFS per scanline, so at the edge that port holds
; whatever the last scanline left in it. A successor composing no BG1HOFS
; claimant would write nothing and inherit a displaced world. `title` composes
; `hz_flat` — a claim whose whole content is that port's flat base — exactly as
; it composes `blend_off` for colour math. AN HDMA-DRIVEN REGISTER NEEDS THE
; SAME PER-SCENE DISARM DISCIPLINE THE BLENDER DOES.
;
; Every address, every register encoding and all four colour-math bytes come
; from the allocator's emitted symbols. Hardware I/O ports are the only
; literals in this file.

.p816
.smart

.define SF_HDR_TITLE "HEATHAZE"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "heathaze.inc"             ; the rail's geometry + tuning
.include "hz_art.inc"               ; GENERATED — the warp blob's layout
                                    ;   (stride, phase count, band), so the
                                    ;   table and its walker cannot disagree
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
.include "tick_scale.asm"           ; TS_STEP: the macro desert.asm's tick uses.
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
hz_hwarp_bin:
    .incbin "hz_hwarp.bin"
.assert ^hz_hwarp_bin = ES_R_HZ_HWARP_BANK, error, "hz_hwarp bank drifted from allocator claim"
.assert .loword(hz_hwarp_bin) = ES_R_HZ_HWARP_ADDR, error, "hz_hwarp addr drifted from allocator claim"
hz_map_bin:
    .incbin "hz_map.bin"
.assert ^hz_map_bin = ES_R_HZ_MAP_BANK, error, "hz_map bank drifted from allocator claim"
.assert .loword(hz_map_bin) = ES_R_HZ_MAP_ADDR, error, "hz_map addr drifted from allocator claim"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
hz_chr_bin:
    .incbin "hz_chr.bin"
.assert ^hz_chr_bin = ES_R_HZ_CHR_BANK, error, "hz_chr bank drifted from allocator claim"
.assert .loword(hz_chr_bin) = ES_R_HZ_CHR_ADDR, error, "hz_chr addr drifted from allocator claim"
hz_pal_bin:
    .incbin "hz_pal.bin"
.assert ^hz_pal_bin = ES_R_HZ_PAL_BANK, error, "hz_pal bank drifted from allocator claim"
.assert .loword(hz_pal_bin) = ES_R_HZ_PAL_ADDR, error, "hz_pal addr drifted from allocator claim"

; TWO WARP TABLES, TWO BANKS, AND THE ALLOCATOR CHOSE THE SPLIT. 16,640 B each
; is more than one 32 KB LoROM bank holds beside the world's art, so the
; packer put the horizontal table at the head of bank 1 and the vertical one
; alone in bank 2. This file follows that decision rather than making its own:
; the `.assert`s above and below are what turn a disagreement into a build
; failure instead of a table read from the wrong bank at run time.
;
; Each table is INTACT within its bank, which is the property that matters —
; HDMA increments A1T inside a bank and does not carry into A1B, so a blob set
; straddling a boundary would walk into whatever follows it. haze.asm asserts
; that separately, per table.
.segment "BANK2"
hz_warp_bin:
    .incbin "hz_warp.bin"
.assert ^hz_warp_bin = ES_R_HZ_WARP_BANK, error, "hz_warp bank drifted from allocator claim"
.assert .loword(hz_warp_bin) = ES_R_HZ_WARP_ADDR, error, "hz_warp addr drifted from allocator claim"
.segment "CODE"

; --- the global feature runtimes (after the blobs their uploads read) ------
; `haze.asm` is NOT here: its claims are scene-scoped, so it is included inside
; scenes/desert.asm's `.scope` where its symbols resolve (water's shape).
; `hz_bg` is global — both scenes draw the same world — so it sits at file
; scope and each scene calls it.
.include "hz_bg.asm"

; --- the rail's own shared enter helpers -----------------------------------
; These are RAIL routines, not feature routines: they establish the display
; shape and the text both scenes share, from symbols the allocator emitted.
; The registers they write are `scene_writes` permissions on `hz_bg` and
; `bg_text`, both of which this rail composes as GLOBALS — which is what puts
; the writes inside the globals' union no_literals checks main.asm against.

; --- hz_display: the scene's base display shape ----------------------------
; CONTRACT heathaze::hz_display
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BGMODE, BG1SC, BG3SC, BG34NBA and BG3HOFS/BG3VOFS established
;             for the scene now entering (NEITHER BG1 scroll port)
;   clobbers: A, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; TWO PORTS ARE DELIBERATELY ABSENT. BG12NBA's two nibbles name BG1's and
; BG2's CHR bases and stage 2 brings a BG2 layer, so each scene writes that
; byte itself. BG1HOFS is not this feature's port at all — see the body.
; Everything else here is identical in both scenes.
;
; BGMODE $09 is mode 1 plus the BG3-priority bit, which is what lets a BG3
; tile carrying the priority attribute sit above BG1 and BG2 — the text over
; the water. Both scroll pairs are write-twice latches set to HZ_VOFS = -1 on
; the vertical axis, so world row r lands on picture rows 8r..8r+7 (see
; heathaze.inc).
hz_display:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_display"
    sep #$20
    .a8
    lda #$09                        ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #ES_V_HZ_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                     ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 chr = the font base
    ; NEITHER BG1 SCROLL PORT IS HERE. It is not `hz_bg`'s port on this rail:
    ; `haze` seeds and drives BOTH per scanline in the desert scene — BG1VOFS
    ; for the mirage, BG1HOFS for the turbulence — and `hz_flat` establishes
    ; them on the title screen. A write here would be a declaration that lies,
    ; and `no_literals` refuses it.
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; BG3HOFS, high
    lda #<HZ_VOFS
    sta a:$2112                     ; BG3VOFS, low
    lda #>HZ_VOFS
    sta a:$2112                     ; BG3VOFS, high
    rep #$20
    .a16
    rts

; --- hz_text_arm: the font and a cleared BG3 tilemap -----------------------
; CONTRACT heathaze::hz_text_arm
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
hz_text_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_text_arm"
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
    lda #HZ_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    rts

; --- hz_puts: one string at one tilemap cell -------------------------------
; CONTRACT heathaze::hz_puts
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the string's address low 16 (it must live in the RODATA
;             block `hz_strings` marks, which is where the bank comes
;             from), X = the VRAM word address to write at
;   out:      the string written as tiles at this rail's text attribute
;   clobbers: A, Y, N, Z, C, V
;   assumes:  forced blank — text_puts writes the VRAM port
;   tail:     rts
;
; The bank byte comes from `^hz_strings` rather than from the caller: every
; string this rail prints lives in one RODATA block, so one label answers for
; all of them and a caller cannot pass a bank that disagrees with its pointer.
hz_puts:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_puts"
    sta z:ES_TXT_PTR
    lda #HZ_TXT_ATTR
    sta z:ES_TXT_TMP
    sep #$20
    .a8
    lda #^hz_strings
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    jsr text_puts
    rts

.segment "RODATA"
; The bank anchor hz_puts reads. Every string in this rail is emitted into
; this segment, so one label answers for all of them.
hz_strings:
.segment "CODE"

; --- the scenes ------------------------------------------------------------
.include "scenes/title.asm"
.include "scenes/desert.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE ENTRY, AND IT IS TWO STORES. The world does not scroll, the text is
; written once per scene under forced blank, and the warp tables are already in
; ROM — so the only thing that has to reach the hardware every frame is WHICH
; of the 64 resident phases each channel reads. `hz_nmi_commit` writes both
; channels' A1T high bytes into scene_mgr's HDMA shadow, and sm_nmi_core MVNs
; that block to $4300 after this hook returns (scene_mgr.asm:407 then :415),
; so the write lands on the same frame.
;
; IT IS GUARDED BY THE RUNNING SCENE, not called unconditionally. The phase it
; reads is `haze`'s SCENE-SCOPED dp claim, so in the title scene that
; direct-page word belongs to something else — reading it there would point an
; HDMA channel at an address derived from an unrelated value. The id comes
; from the edge symbol the allocator emitted rather than from a hand-written
; 1, which is the same reason SM_SWITCH takes its destination from the edge.
sm_nmi_hook:
    .a8
    .i16
    lda z:ES_SM_CTL                 ; the scene now running
    cmp #ES_E_TITLE_TO_DESERT_DST   ; ...the desert?
    bne @done
    jsr desert::hz_nmi_commit       ; the phase -> the channel's A1T high byte
@done:
    .a8
    .i16
    rts

; --- scene dispatch tables (manifest order: title=0, desert=1) -------------
sm_enter_tab:   .word title::enter, desert::enter
sm_tick_tab:    .word title::tick,  desert::tick
sm_exit_tab:    .word title::exit,  desert::exit

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
