; =============================================================================
; sf_obj_text.inc — OBJ sprite-font HUD renderer (front-door macros)
; =============================================================================
; The HUD readout primitive: draw a run of glyphs as OBJ sprites at an arbitrary
; screen X,Y, in OBJ palette 7, in EVERY BG mode (modes 0-7). The HUD is OBJ —
; not a BG layer — precisely so it survives the 256-colour modes (3/4) where the
; BG owns CGRAM 0-239; OBJ palette 7 = CGRAM 240-255 is the HUD's own reserved
; slice (showcase allocations contract §3). One palette, no per-mode branching.
;
; Glyph CHR + the SF_OBJG_* tile equates come from sf_obj_text_data.inc (the
; kit's built-in font re-encoded 4bpp, glyph pixels = colour index 1). The
; HUD's 16 OBJ-pal-7 colours go to CGRAM 240-255; sf_obj_text_init does this.
;
; --- USAGE (call all three in setup, under forced blank, BEFORE the screen on) ---
;   1. sf_obj_text_init [base_tile]     ; upload glyph CHR + OBJ pal 7. base_tile
;                                       ; default 1024 (VRAM word $4000); set
;                                       ; OBSEL=$02 yourself (8x8 small + name
;                                       ; base $4000 — per-page VRAM rule).
;   2. per frame (or once): spr_clear   ; then place the HUD runs in call order —
;   3.   sf_obj_print str, x, y         ; the first run takes OBJ slots 0.., etc.
;        sf_obj_num   value, x, y
;
; SLOT BAND (allocations §2): sprites land in shadow-OAM slots in CALL ORDER from
; SPRITE_COUNT (after spr_clear, the first glyph = slot 0). The top readout band
; (OBJ 0-31, Y<=24) is therefore "spr_clear, then HUD-print first". A bottom bar
; (OBJ 32-47, Y>=208) is whatever the caller places after. This renderer places a
; glyph run at any X,Y — the band is the caller's call-ordering decision.
;
; Requires (linked into the ROM): engine/engine_state.inc, engine/sprite_engine.asm
; (engine_spr), and sf_obj_text_data.inc (the glyph data — include ONCE per ROM,
; like sf_text_data.inc). Each ROM that uses these macros must `.include
; "sf_obj_text_data.inc"` and `.include "sf_obj_text.inc"` once.
;
; WIDTH-RISK: every macro asserts A16/I16 entry (rep #$30, safe-by-default) and
; the helper subroutines return A16/I16. The helpers toggle A8 internally for the
; byte-wide OBJ writes and restore A16 before rts.
; =============================================================================

.ifndef SF_OBJ_TEXT_INC
SF_OBJ_TEXT_INC = 1

.include "sf_video.inc"            ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"           ; spr / spr_clear / SF_SPR_* (engine_spr call)

; DP scratch for the OBJ-text helpers — the engine's MAIN-THREAD transient scratch
; zone ($00:00A0-$00:00BF, DP=$0000), the documented home for call-scoped scratch
; (engine_state.inc "Main-thread transient scratch zone"). SF_OBJT_STRPTR mirrors
; the text engine's own 24-bit string pointer (ES_TEXT_SCRATCH_LONGPTR=$A0): the 3
; contiguous bytes $A0/$A1/$A2 form the far pointer that `lda [SF_OBJT_STRPTR],y`
; dereferences (low/mid/bank). All TRANSIENT — valid only within a single
; sf_obj_print/sf_obj_num call; the HUD renderer never nests with text_engine /
; mode5_text / bg_stream (distinct main-thread calls), so the zone aliasing is
; safe-by-construction per the engine's documented scratch discipline. These are
; NAMED equates (not raw hex), so the zp-check linter reads them via the symbol,
; not as an unbacked raw-hex DP touch. Disjoint from SF_SPR_* ($60-$70).
;
; NOTE the ES_* symbols at $A0-$BF are NMI-DP-relative (resolve to $01A0+); these
; main-thread DP=$0000 bytes are physically distinct ($00A0+) — no runtime
; collision, exactly as engine_print uses the same window.
SF_OBJT_STRPTR  = $A0              ; 3 B: 24-bit source string pointer (low/mid/bank)
SF_OBJT_X       = $A3              ; 2 B: running pen X (9-bit)
SF_OBJT_Y       = $A5              ; 2 B: pen Y (low byte)
SF_OBJT_FLAGS   = $A7              ; 2 B: OBJ attribute flags (palette<<1 | hflip)
SF_OBJT_BASE    = $A9              ; 2 B: glyph base tile (added to SF_OBJG_*)
SF_OBJT_TMP     = $AB              ; 2 B: scratch (decimal value for sf_obj_num)

; Default OBJ glyph base tile: 1024 = VRAM word $4000 (the OBSEL name base). The
; per-page VRAM rule (allocations §3): OBJ name base word $4000, like racer /
; mode7_flight, clear of every mode's BG tiles/tilemap. The glyphs are 8x8, so the
; page sets OBSEL=$02 (size %000 = 8x8 small + base %010 = word $4000) — racer /
; mode7_flight use $62 (same base, 16x16/32x32) for their larger sprites.
.ifndef SF_OBJ_TEXT_BASE_TILE
SF_OBJ_TEXT_BASE_TILE = 1024
.endif

; OBSEL OBJ name base, expressed as a tile number: word $4000 / 16 = 1024. An OAM
; tile field T addresses VRAM word (name_base + T*16); since the glyph CHR is
; UPLOADED at absolute tile SF_OBJ_TEXT_BASE_TILE, glyph index N renders at OAM
; tile (SF_OBJ_TEXT_BASE_TILE - name_base_tile + N). With the default upload base
; == name base, that is simply N. This constant lets sf_obj_text_init compute the
; correct OAM-tile offset for a non-default base. (Page must keep OBSEL's name
; base matching this, i.e. word $4000 → OBSEL=$02.)
.ifndef SF_OBJ_TEXT_NAME_BASE_TILE
SF_OBJ_TEXT_NAME_BASE_TILE = 1024
.endif

; HUD OBJ palette: 7 (CGRAM 240-255). `spr` flags = palette<<1 (PPPn), so pal 7
; -> $0E. The single mode-agnostic palette (allocations §3).
SF_OBJ_HUD_PAL    = 7
SF_OBJ_HUD_FLAGS  = (SF_OBJ_HUD_PAL << 1)      ; = $0E

; -----------------------------------------------------------------------------
; sf_obj_text_init [base_tile] — upload glyph CHR + the HUD's OBJ pal 7.
; -----------------------------------------------------------------------------
;   base_tile  OBJ tile index the glyph blob starts at (multiple of 16; default
;              SF_OBJ_TEXT_BASE_TILE = 1024 = VRAM word $4000). The macro stores
;              this base in SF_OBJT_BASE so sf_obj_print/num add SF_OBJG_* to it.
; Uploads sf_obj_font_chr (1408 B, 44 glyphs) to OBJ VRAM and writes the 16 HUD
; colours to OBJ palette 7 (CGRAM 240-255). VRAM + CGRAM are forced-blank/VBlank
; only — call in setup, BEFORE the screen turns on. Does NOT touch OBSEL — set
; OBSEL=$02 yourself (8x8 small + name base word $4000; per-page VRAM rule).
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry (rep #$30); the sf_load_obj_* macros toggle
; A8 internally for the PPU byte writes and restore A16. Exits A16/I16.
.macro sf_obj_text_init sf_base
    .local sf_b
    rep #$30
    .a16
    .i16
.ifblank sf_base
    sf_b = SF_OBJ_TEXT_BASE_TILE
.else
    sf_b = sf_base
.endif
    ; Glyph CHR -> OBJ VRAM at base_tile (sf_load_obj_chr asserts 16-alignment).
    sf_load_obj_chr sf_b, sf_obj_font_chr, SF_OBJ_FONT_BYTES
    ; OBJ palette 7 = CGRAM 240-255: slot 0 transparent, slot 1 = the glyph
    ; colour (white), the rest filled so a value-bar/marker can pick a tint.
    sf_load_obj_pal SF_OBJ_HUD_PAL, _sf_obj_hud_pal
    ; Store the OAM-TILE base for sf_obj_print/num: glyph N -> OAM tile
    ; (upload_base - name_base + N). Default (upload==name base) = 0, so glyph N
    ; is OAM tile N. (Not the raw upload tile — that only happened to work when
    ; the upload base was a multiple of 256; this is the correct OBSEL-relative
    ; offset for any base.)
    lda #(sf_b - SF_OBJ_TEXT_NAME_BASE_TILE)
    sta SF_OBJT_BASE
.endmacro

; -----------------------------------------------------------------------------
; sf_obj_print str, x, y [, flags] — draw a NUL-terminated string as OBJ glyphs.
; -----------------------------------------------------------------------------
;   str    a BARE ROM label of NUL-terminated ASCII. Renderable chars: 0-9, A-Z,
;          space, : . - + (and the markers via the SF_OBJG_* tiles a caller can
;          place directly with `spr`). Lowercase a-z map to upper-case glyphs.
;          Unknown chars render as a blank (space). NOT verbatim — the macro
;          takes the label's address + bank itself.
;   x, y   screen pixel coordinates (verbatim operands — write `#16, #8`). x is
;          9-bit (0-511, off-screen wrap handled by engine_spr). Each glyph is
;          8 px wide; the pen advances +8 per character. y <= ~24 for the top
;          HUD band (allocations §2). On-screen: x 0-247, y 0-215.
;   flags  OBJ attribute flags (verbatim, optional — default SF_OBJ_HUD_FLAGS =
;          pal 7). Pass e.g. `#($0E | $40)` for H-flip; bit7 (large size) is NOT
;          honoured here (the glyph is an 8x8 small sprite).
; Each character becomes one 8x8 OBJ sprite in the next shadow-OAM slot (call
; order from SPRITE_COUNT). Call spr_clear first so the run starts at slot 0.
; Clobbers A, X, Y + DP $A0-$AC (the main-thread transient scratch zone).
; WIDTH-RISK: asserts A16/I16 entry (rep #$30); toggles A8 for the bank-byte
; store, restores A16; _sf_obj_print_run runs its own widths and returns A16/I16.
.macro sf_obj_print sf_str, sf_x, sf_y, sf_flags
    rep #$30
    .a16
    .i16
    lda #.loword(sf_str)
    sta SF_OBJT_STRPTR         ; low 16 of the far pointer ($A0/$A1)
    sep #$20
    .a8
    lda #.bankbyte(sf_str)
    sta SF_OBJT_STRPTR+2       ; bank byte ($A2) — completes the 24-bit pointer
    rep #$20
    .a16
    lda sf_x
    sta SF_OBJT_X
    lda sf_y
    sta SF_OBJT_Y
.ifblank sf_flags
    lda #SF_OBJ_HUD_FLAGS
.else
    lda sf_flags
.endif
    sta SF_OBJT_FLAGS
    jsr _sf_obj_print_run
.endmacro

; -----------------------------------------------------------------------------
; sf_obj_num value, x, y [, flags] — draw a 16-bit value as 5 decimal glyphs.
; -----------------------------------------------------------------------------
;   value  16-bit unsigned 0-65535 (verbatim — a memory operand like `MOSAIC`
;          reads that address; `#7` draws a literal). Zero-padded 5 digits
;          ("00007") — a fixed-width readout that never leaves stale digits.
;   x,y,flags  as sf_obj_print.
; Five 8x8 OBJ digit sprites in call order. Clobbers A, X, Y + DP $A0-$AC.
; WIDTH-RISK: asserts A16/I16 entry (rep #$30); _sf_obj_num_run runs its own
; widths and returns A16/I16.
.macro sf_obj_num sf_val, sf_x, sf_y, sf_flags
    rep #$30
    .a16
    .i16
    lda sf_val
    sta SF_OBJT_TMP            ; the value to convert
    lda sf_x
    sta SF_OBJT_X
    lda sf_y
    sta SF_OBJT_Y
.ifblank sf_flags
    lda #SF_OBJ_HUD_FLAGS
.else
    lda sf_flags
.endif
    sta SF_OBJT_FLAGS
    jsr _sf_obj_num_run
.endmacro

; =============================================================================
; Helper subroutines + data. Assembled into each ROM that includes this file
; (guarded by SF_OBJ_TEXT_INC, so a single include defines them once).
; =============================================================================

; --- _sf_obj_print_run --------------------------------------------------------
; Loop the NUL-terminated string at SF_OBJT_STRPTR/BNK: map each ASCII char to a
; glyph tile (base + SF_OBJG_*) and place an 8x8 OBJ at (SF_OBJT_X, SF_OBJT_Y),
; advancing X by 8 per glyph. NUL ends the run. Enters/returns A16/I16.
; WIDTH-RISK: A8 for byte reads/marshalling, A16 around engine_spr (its contract).
.proc _sf_obj_print_run
    rep #$30
    .a16
    .i16
@loop:
    ; Fetch next char via a 24-bit DP-indirect read. SF_OBJT_STRPTR is a 3-byte
    ; far pointer in contiguous DP ($A0/$A1 low+mid, $A2 bank), so
    ; [SF_OBJT_STRPTR],y dereferences addr:bank — the pointer lives in DP (no ROM
    ; self-modify; ROM is not writable).
    sep #$20
    .a8
    ldy #0
    lda [SF_OBJT_STRPTR], y    ; A = next char (24-bit ptr from $A0/$A1/$A2)
    rep #$20
    .a16
    and #$00FF
    beq @done                 ; NUL terminates
    jsr _sf_obj_glyph_tile    ; A(char) -> A = absolute glyph tile (base+index)
    ; place the glyph sprite
    sta SF_SPR_TILE
    lda SF_OBJT_X
    sta SF_SPR_X
    lda SF_OBJT_Y
    sta SF_SPR_Y
    lda SF_OBJT_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI            ; HUD priority 0 (top band, no BG contention)
    jsr engine_spr           ; -> shadow OAM, slot in call order
    ; advance pen X by 8, source pointer by 1
    rep #$20
    .a16
    lda SF_OBJT_X
    clc
    adc #8
    sta SF_OBJT_X
    inc SF_OBJT_STRPTR
    bra @loop
@done:
    rep #$30
    .a16
    .i16
    rts
.endproc

; --- _sf_obj_num_run ----------------------------------------------------------
; Convert SF_OBJT_TMP (16-bit) to 5 zero-padded decimal digits and place each as
; an OBJ glyph at (SF_OBJT_X, SF_OBJT_Y), advancing X by 8. Enters/returns A16.
; Division by repeated subtraction against the power-of-ten table (no MUL/DIV).
.proc _sf_obj_num_run
    rep #$30
    .a16
    .i16
    ldx #0                    ; index into _sf_pow10 (5 entries: 10000..1)
@digit:
    lda SF_OBJT_TMP
    ldy #0                    ; digit accumulator
@sub:
    cmp f:_sf_pow10, x        ; while value >= 10^k
    bcc @emit
    sec
    sbc f:_sf_pow10, x
    sta SF_OBJT_TMP
    iny
    bra @sub
@emit:
    ; Y = this decimal digit (0-9). Glyph tile = base + SF_OBJG_0 + digit.
    tya
    clc
    adc #SF_OBJG_0
    clc
    adc SF_OBJT_BASE
    sta SF_SPR_TILE
    lda SF_OBJT_X
    sta SF_SPR_X
    lda SF_OBJT_Y
    sta SF_SPR_Y
    lda SF_OBJT_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    phx                       ; engine_spr clobbers X
    jsr engine_spr
    plx
    rep #$20
    .a16
    lda SF_OBJT_X
    clc
    adc #8
    sta SF_OBJT_X
    inx
    inx                       ; next power of ten (2 bytes/entry)
    cpx #10                   ; 5 entries × 2 bytes
    bcc @digit
    rts
.endproc

; --- _sf_obj_glyph_tile -------------------------------------------------------
; In: A = ASCII char ($00..$FF, only low byte meaningful). Out: A = absolute OBJ
; glyph tile (SF_OBJT_BASE + glyph index). Maps via _sf_ascii2glyph (128-entry
; ROM table, index = char & $7F). Unknown chars -> SPACE (0). Enters/returns A16.
.proc _sf_obj_glyph_tile
    rep #$20
    .a16
    and #$007F
    tax
    sep #$20
    .a8
    lda f:_sf_ascii2glyph, x   ; glyph index (0-43)
    rep #$20
    .a16
    and #$00FF
    clc
    adc SF_OBJT_BASE
    rts
.endproc

; --- power-of-ten table for the decimal split (16-bit, low..high digit) -------
_sf_pow10:
    .word 10000, 1000, 100, 10, 1

; --- the HUD's 16-colour OBJ palette (BGR555). Slot 0 transparent; slot 1 the
; glyph/bar colour (white). Slots 2-15 give value bars/markers a tint palette.
_sf_obj_hud_pal:
    .word $0000      ; 0 transparent
    .word $7FFF      ; 1 white  (glyph colour / SF_OBJG_BAR full)
    .word $7C00      ; 2 blue
    .word $03E0      ; 3 green
    .word $001F      ; 4 red
    .word $7FE0      ; 5 cyan
    .word $7C1F      ; 6 magenta
    .word $03FF      ; 7 yellow
    .word $4210      ; 8 grey
    .word $5294      ; 9 lt grey
    .word $0210      ; 10 dk green
    .word $0010      ; 11 dk red
    .word $4010      ; 12 dk blue
    .word $7FFF      ; 13 white
    .word $6318      ; 14 silver
    .word $7FFF      ; 15 white

; --- _sf_ascii2glyph: ASCII ($00-$7F) -> glyph tile INDEX (relative to base).
;     Index meanings: 0=space/blank, 1-10 = '0'-'9', 11-36 = 'A'-'Z',
;     37=':' 38='.' 39='-' 40='+'. Everything else -> 0 (blank). Lowercase
;     a-z fold to the upper-case glyph. ---
_sf_ascii2glyph:
    ; $00-$0F  (control) -> blank
    .byte 0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0
    ; $10-$1F  -> blank
    .byte 0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0
    ; $20 space=0  $21!=0 .. $2A*=0  $2B+=40  $2C,=0  $2D-=39  $2E.=38  $2F/=0
    .byte 0,0,0,0,0,0,0,0, 0,0,0,40,0,39,38,0
    ; $30-$39  '0'-'9' = 1..10   $3A:=37  $3B-$3F -> 0
    .byte 1,2,3,4,5,6,7,8, 9,10,37,0,0,0,0,0
    ; $40 @=0   $41-$4F 'A'-'O' = 11..25
    .byte 0,11,12,13,14,15,16,17, 18,19,20,21,22,23,24,25
    ; $50-$5A 'P'-'Z' = 26..36   $5B-$5F -> 0
    .byte 26,27,28,29,30,31,32,33, 34,35,36,0,0,0,0,0
    ; $60 `=0   $61-$6F 'a'-'o' = 11..25 (fold to upper)
    .byte 0,11,12,13,14,15,16,17, 18,19,20,21,22,23,24,25
    ; $70-$7A 'p'-'z' = 26..36   $7B-$7F -> 0
    .byte 26,27,28,29,30,31,32,33, 34,35,36,0,0,0,0,0

.endif ; SF_OBJ_TEXT_INC
