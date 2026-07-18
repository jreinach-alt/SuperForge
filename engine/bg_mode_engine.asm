; =============================================================================
; bg_mode_engine.asm — Phase 17-0 Generalized gfxmode Dispatcher
; =============================================================================
; Extends the Phase 3 Mode-1-only engine_gfxmode stub into a dispatcher that
; accepts Modes 0, 1, 2, 3, 4, and 7. Modes 5 and 6 are reserved for 17-7 and
; 17-8 (treated as no-op in 17-0 with the dispatch-rejection flag set). Modes
; 8-255 are out of range and rejected without touching PPU state (BM-004).
;
; This file defines an alternate engine_gfxmode symbol; bg_engine.asm's
; definition is guarded by .ifndef BG_MODE_ENGINE_PROVIDES_GFXMODE so a ROM
; that includes both files gets the Phase 17 dispatcher. ROMs that include
; only bg_engine.asm (Phase 3/12/13/font) keep the original Mode-1 body.
;
; Per-mode behavior (17-0 minimum):
;   Modes 0, 1, 2, 3, 4 : write BGMODE byte to $2105 + SHADOW_BGMODE, flag
;                          BG_SHADOW_REGS_DIRTY. Full per-mode setup (chr base,
;                          tilemap clears, TM) arrives in 17-1/17-2/17-3/etc.
;   Mode 7              : jsr mode7_init — sets SHADOW_BGMODE=$07, M7_ACTIVE=1,
;                          default horizon (57), identity matrix.
;   Modes 5, 6          : no-op + rejection flag (lifted in 17-7/17-8).
;   Modes 8-255         : no-op + rejection flag (permanent).
;
; Bounds-check and rejection flag live in BG_MODE_DISPATCH_FLAGS bit 0
; (engine_state.inc ZP $3B). After a rejected call, SHADOW_BGMODE and
; BG_MODE_CURRENT are unchanged.
;
; Caller contract:
;   DP=$0000, DB=$00, A16/I16 on entry, A16/I16 on exit.
;   Must be in forced blank ($2100 bit 7 set) — same as Phase 3 stub.
;
; Clobbers: A, X.
; Return:   ENGINE_A0 = $00000000.
;
; Cross-ref: docs/sprints/phase_17_bg_modes.md §17-0, phase_17_allocations.md §1.
; =============================================================================

; Prerequisites: engine_state.inc included, .p816/.smart set in parent.
; Signal to bg_engine.asm to skip its Mode-1-only engine_gfxmode definition.
BG_MODE_ENGINE_PROVIDES_GFXMODE = 1

; API block + return register equates (match handlers_engine.asm). Guarded so
; a parent that already defines these (e.g., via handlers_engine.asm) wins.
.ifndef API_BLOCK_BASE
API_BLOCK_BASE = $60
.endif
.ifndef ENGINE_A0
ENGINE_A0 = $40
.endif


.segment "CODE"

; -----------------------------------------------------------------------------
; engine_gfxmode — Phase 17-0 dispatcher
; -----------------------------------------------------------------------------
; WIDTH-RISK: entry = A16/I16. Internally toggles A to .a8 for the mode
; compare chain and the BGMODE write, restores A16 before rts. Every branch
; target that is reached from a different width path carries an explicit
; .a8 or .a16 annotation so ca65's sequential tracker stays aligned with the
; runtime width.
; -----------------------------------------------------------------------------
engine_gfxmode:
    rep #$30
    .a16
    .i16

    lda API_BLOCK_BASE + 0          ; param 0 = mode (low word)
    and #$00FF
    sep #$20
    .a8

    ; --- Bounds check: accept only modes 0, 1, 2, 3, 4, 7 ---
    ; Note: @reject is too far for short branches once per-mode init bodies
    ; are added. Use inverted-branch + jmp to span the gap (jmp = absolute,
    ; 16-bit, no range limit within the bank).
    cmp #$08
    bcc @range_ok_8                 ; mode >= 8 → fall through to jmp @reject
    jmp @reject
@range_ok_8:
    cmp #$07
    beq @valid                      ; mode == 7 → Mode 7 path below
    cmp #$06
    beq @valid                      ; mode == 6 → Mode 6 path (17-8)
    cmp #$05
    beq @valid                      ; mode == 5 → Mode 5 path (17-7)
    bcc @range_ok_5                 ; modes 0-4 pass through (A<5 here is the
                                    ; only remaining case; 5/6/7 caught above,
                                    ; >=8 rejected at the top — so this branch
                                    ; is always taken and falls straight through)
@range_ok_5:

    ; --- Valid mode 0, 1, 2, 3, 4, or 7 ---
@valid:
    .a8
    pha                             ; save new mode on stack
    lda BG_MODE_CURRENT
    sta BG_MODE_PREVIOUS
    pla
    sta BG_MODE_CURRENT

    ; Clear rejection flag (bit 0)
    lda BG_MODE_DISPATCH_FLAGS
    and #$FE
    sta BG_MODE_DISPATCH_FLAGS

    ; Dispatch: Mode 7 has its own full init; Modes 0-4 share a minimal path.
    lda BG_MODE_CURRENT
    cmp #$07
    bne @mode0_4

    ; --- Mode 7: delegate to mode7_init (full init with default horizon 57) ---
    ; mode7_init expects A16/I16 on entry and exits A16.
    ;
    ; Conditional include: only ROMs that .include mode7_engine.asm before
    ; bg_mode_engine.asm get the full Mode 7 init. Phase 17-1+ demos that
    ; never use Mode 7 skip the include and get a minimal BGMODE-only stub
    ; so they don't drag in the Mode 7 LUTs / state.
.ifdef MODE7_ENGINE_PROVIDES_INIT
    rep #$30
    .a16
    .i16
    jsr mode7_init
.else
    ; Stub: write BGMODE=$07 + shadow only. Caller must use the dedicated
    ; mode7_on() API for full Mode 7 setup (matrix, horizon, HDMA tables).
    .a8
    lda #$07
    sta SHADOW_BGMODE
    sta $2105
    lda #$01
    sta BG_SHADOW_REGS_DIRTY
    rep #$20
    .a16
.endif
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@mode0_4:
    ; --- Modes 0-4: write raw BGMODE byte + shadow ---
    ; A8, A = mode number (0, 1, 2, 3, or 4). Low 3 bits become the BGMODE
    ; field of $2105.
    .a8
    sta SHADOW_BGMODE
    sta $2105                       ; caller contract: forced blank active

    ; Per-mode extension dispatch. A still holds the mode number.
    ; Phase 17-1 lands the Mode 0 body. Phase 17-2 lands the Mode 3 body.
    ; Phase 17-3 lands the Mode 2 body (offset-per-tile via BG3 tilemap).
    ; Modes 1 and 4 stay on the minimal stub (BGMODE + shadow only); later
    ; sub-phases extend each.
    ; Dispatch table — invert branches + jmp because per-mode init bodies
    ; exceed BRA's ±128-byte range once all land.
    cmp #$00
    bne :+
    jmp @mode0_init
:   cmp #$01
    bne :+
    jmp @mode1_init
:   cmp #$02
    bne :+
    jmp @mode2_init
:   cmp #$03
    bne :+
    jmp @mode3_init
:   cmp #$04
    bne :+
    jmp @mode4_init
:   cmp #$05
    bne :+
    jmp @mode5_init
:   cmp #$06
    bne :+
    jmp @mode6_init
:   jmp @mode_done

@mode0_init:
    ; --- Mode 0 full PPU setup (Phase 17-1) ---
    ; VRAM layout (consumed by tests/phase17/test_mode0_4bg.asm + future
    ; Mode 0 demos):
    ;   word $0000  BG1 tilemap (2 KB, 32x32)
    ;   word $0400  BG2 tilemap (2 KB, 32x32)
    ;   word $0800  BG3 tilemap (2 KB, 32x32)
    ;   word $0C00  BG4 tilemap (2 KB, 32x32)
    ;   word $1000  Shared BG chardata (BG1=BG2=BG3=BG4 chr base)
    ;
    ; The shared-chr layout uses BG12NBA = BG34NBA = $11. Each BG palettizes
    ; the same VRAM tile data through its own dedicated palette range
    ; (BG1: pal 0-7, BG2: pal 8-15, BG3: pal 16-23, BG4: pal 24-31), so a
    ; single tile at word $1000 renders four distinct colors when referenced
    ; from each BG's tilemap.
    lda #$00                        ; BG1SC: tilemap word $0000, 32x32
    sta $2107
    lda #$04                        ; BG2SC: tilemap word $0400
    sta $2108
    lda #$08                        ; BG3SC: tilemap word $0800
    sta $2109
    lda #$0C                        ; BG4SC: tilemap word $0C00
    sta $210A
    lda #$11                        ; BG12NBA: BG1+BG2 chr at word $1000
    sta $210B
    lda #$11                        ; BG34NBA: BG3+BG4 chr at word $1000
    sta $210C
    lda #$1F                        ; TM: BG1+BG2+BG3+BG4+OBJ
    sta $212C
    sta SHADOW_TM
    jmp @mode_done

@mode1_init:
    ; --- Mode 1 full PPU setup (S0 superset port) ---
    ; Ports the kit Mode-1 stub (bg_engine.asm engine_gfxmode) so the
    ; dispatcher is a true superset of all 8 modes. Replicates the stub's
    ; SC/NBA/TM register writes, the three shadow-tilemap clears, the dirty
    ; flags, and GFXMODE_STATE — but DELIBERATELY does NOT turn the screen
    ; on (no INIDISP write). The dispatcher's caller contract (file header)
    ; is "must be in forced blank on entry; caller manages display"; modes
    ; 0/2/3/4 stay in forced blank and leave display to the caller, so Mode 1
    ; does too. (The stub wrote INIDISP=$0F because it was the only mode and
    ; owned display; the dispatcher splits that responsibility out.)
    ;
    ; VRAM layout (matches the kit's Mode-1 convention + the NMI handler's
    ; hardcoded BG tilemap DMA destinations):
    ;   word $5800  BG1 tilemap (shadow $7E:A200, DMA'd by NMI)
    ;   word $5C00  BG2 tilemap (shadow $7E:AA00)
    ;   word $6000  BG3 tilemap (shadow $7E:B200)
    ;   word $2000  BG1 chr, word $4000 BG2 chr, word $A000 BG3 chr
    ;
    ; A8 on entry (the @mode0_4 dispatch ladder runs A8). @mode0_4 already
    ; wrote the raw mode byte ($01) to $2105 + SHADOW_BGMODE before
    ; dispatching; re-write BGMODE here as $09 (mode 1 + BG3 priority bit 3)
    ; so BG3 priority matches the kit stub.
    ; WIDTH-RISK: entry = A8/I16 (from @mode0_4). Internally toggles A16 for
    ; the three DB=$7E shadow-tilemap clears (phb/plb bracket), restores A8
    ; before the final `jmp @mode_done`. Each branch target inside carries an
    ; explicit width annotation matching the runtime CPU width.
    .a8
    .i16
    lda #PPU_BGMODE_MODE1            ; $09 = Mode 1 + BG3 priority
    sta $2105
    sta SHADOW_BGMODE

    lda #PPU_BG1SC_VALUE             ; BG1SC: tilemap word $5800, 32x32
    sta $2107
    lda #PPU_BG2SC_VALUE             ; BG2SC: tilemap word $5C00
    sta $2108
    lda #PPU_BG3SC_VALUE             ; BG3SC: tilemap word $6000
    sta $2109
    lda #PPU_BG12NBA_VALUE           ; BG12NBA: BG1 chr $2000, BG2 chr $4000
    sta $210B
    lda #PPU_BG34NBA_VALUE           ; BG34NBA: BG3 chr $A000
    sta $210C
    lda #$17                         ; TM: OBJ + BG1 + BG2 + BG3
    sta $212C
    sta SHADOW_TM

    ; GFXMODE_STATE = 1 (Mode 1 active) — matches the stub's contract.
    lda #$01
    sta f:GFXMODE_STATE             ; GFXMODE_STATE is a $7E:xxxx abs address

    ; --- Clear the three shadow tilemaps (3 × 2048 B). DB=$7E for $A200+. ---
    phb
    rep #$20
    .a16
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

    ; BG1 shadow tilemap ($A200, 2048 bytes)
    ldx #$0000
@m1_clear_bg1:
    .a16
    .i16
    stz $A200, x
    inx
    inx
    cpx #$0800
    bne @m1_clear_bg1

    ; BG2 shadow tilemap ($AA00, 2048 bytes)
    ldx #$0000
@m1_clear_bg2:
    .a16
    .i16
    stz $AA00, x
    inx
    inx
    cpx #$0800
    bne @m1_clear_bg2

    ; BG3 shadow tilemap ($B200, 2048 bytes)
    ldx #$0000
@m1_clear_bg3:
    .a16
    .i16
    stz $B200, x
    inx
    inx
    cpx #$0800
    bne @m1_clear_bg3

    plb                             ; restore DB = $00

    ; Mark all 3 BG layers dirty so the NMI DMAs the cleared tilemaps.
    sep #$20
    .a8
    lda #$07
    sta BG_TILEMAP_DIRTY

    ; Clear the BG scroll shadows (NMI commits these to $210D.. each frame).
    rep #$20
    .a16
    stz SHADOW_BG1HOFS
    stz SHADOW_BG1VOFS
    stz SHADOW_BG2HOFS
    stz SHADOW_BG2VOFS
    stz SHADOW_BG3HOFS
    stz SHADOW_BG3VOFS

    ; Re-enter A8 to match @mode0_init's jmp-into-@mode_done width contract.
    sep #$20
    .a8
    jmp @mode_done

@mode2_init:
    ; --- Mode 2 full PPU setup (Phase 17-3) ---
    ; Mode 2: BG1 & BG2 are both 4bpp. BG3 is NOT rendered — its tilemap
    ; is repurposed as the per-column offset source (one 16-bit word per
    ; column applied to BG1/BG2 H-scroll). See engine/offset_engine.asm
    ; for the shadow-buffer + NMI-flush pipeline.
    ;
    ; VRAM layout (consumed by tests/phase17/test_mode2_static.asm):
    ;   word $0000  BG1 tilemap
    ;   word $0400  BG2 tilemap
    ;   word $0800  BG3 tilemap = OFFSET SOURCE (DMA target of
    ;                             engine_offset_flush)
    ;   word $1000  BG1+BG2 shared chr (BG12NBA = $11)
    ;
    ; BG34NBA = $00 (BG3 chr unused in Mode 2 but register still written
    ; for safety). TM enables BG1 + BG2 + OBJ; BG3 is intentionally OFF
    ; because its "tiles" are offset values, not pixels.
    lda #$00                        ; BG1SC: tilemap word $0000
    sta $2107
    lda #$04                        ; BG2SC: tilemap word $0400
    sta $2108
    lda #$08                        ; BG3SC: tilemap word $0800 (offset src)
    sta $2109
    lda #$11                        ; BG12NBA: BG1+BG2 chr at word $1000
    sta $210B
    lda #$00                        ; BG34NBA: BG3 chr word $0000 (unused)
    sta $210C
    lda #$13                        ; TM: BG1 + BG2 + OBJ (BG3 disabled)
    sta $212C
    sta SHADOW_TM
    jmp @mode_done

@mode5_init:
    ; --- Mode 5 full PPU setup (Phase 17-7) ---
    ; Mode 5: hi-res 512×224 (line-doubled default per decision 8). BG1 =
    ; 4bpp, BG2 = 2bpp. Setting BGMODE=$05 alone auto-activates horizontal
    ; doubling per Mesen2 SnesPpu.cpp:1279 (hiResMode = BgMode==5).
    ;
    ; Both BGs use DoubleWidth tilemaps (BGnSC bit 0 = 1) so a single
    ; 64×32 tilemap (4 KB) covers all 64 tile columns needed for 512 px.
    ;
    ; VRAM layout (consumed by tests/phase17/test_mode5_hires.asm):
    ;   word $0000  BG1 tilemap (4 KB, 64×32, DoubleWidth)
    ;   word $0800  BG2 tilemap (4 KB, 64×32, DoubleWidth)
    ;   word $1000  BG1 chardata (4bpp; 32 B/tile)
    ;   word $3000  BG2 chardata (2bpp; 16 B/tile)
    ;
    ; Hi-res tile-pair encoding: each 16-px wide glyph is two 8×8 tiles in
    ; VRAM; main-screen tilemap entry points to the "main tile" (odd output
    ; columns), sub-screen tilemap entry points to the "sub tile" (even
    ; output columns). See toolchain/hires_tile.py for the PNG encoder.
    ;
    ; $2133 SETINI initialized to $00 (interlace OFF, line-doubled 512×224
    ; — matches the way most shipping Mode 5 titles ship, per decision
    ; 8; one outlier title runs 448i in gameplay). `hires_interlace(1)`
    ; opts into 512×448 when a scene needs it.
    lda #$03                        ; BG1SC: tilemap word $0000, DoubleWidth + DoubleHeight
    sta $2107                       ;   DoubleHeight (bit 1) is REQUIRED for interlace
                                    ;   coherent rendering per Mesen2 SnesPpu.cpp:1614-1616
                                    ;   (IsDoubleHeight returns true in Mode 5+interlace,
                                    ;   expanding realY to 0..447; without DoubleHeight bit
                                    ;   in BG1SC, tilemap rows 32..63 wrap to 0..31 and the
                                    ;   content renders duplicated top/bottom — the exact
                                    ;   "split" symptom observed in 17-7a bsnes testing).
                                    ;   Scenes that only populate rows 0..31 (HUD strips +
                                    ;   centered content) get blank bottom half in 448i,
                                    ;   which is correct for a 512×224 authored layout.
                                    ;   BG1 DoubleHeight expands its tilemap from 4 KB to
                                    ;   8 KB (SC2+SC3 land at word $0800..$0FFF, which
                                    ;   overlaps BG2's tilemap at $0800 — mutually OK as
                                    ;   long as both contents are zero in the overlap).
    lda #$09                        ; BG2SC: tilemap word $0800, DoubleWidth only
    sta $2108                       ;   Intentionally NOT DoubleHeight: BG2's extended
                                    ;   tilemap would overlap BG1 chr at $1000 and render
                                    ;   font bytes as garbage tile indices. BG2 is expected
                                    ;   to carry no content in interlace demos; if a scene
                                    ;   does put content on BG2 in 448i, it must relocate
                                    ;   BG1 chr and enable DoubleHeight on BG2 separately.
    lda #$31                        ; BG12NBA: BG1 chr $1000, BG2 chr $3000
    sta $210B
    lda #$13                        ; TM: BG1 + BG2 + OBJ (no BG3/BG4)
    sta $212C
    sta SHADOW_TM
    ; TS: BG1 + BG2 must be enabled on the sub-screen too, otherwise Mode 5's
    ; main/sub split renders half the glyph (only odd output cols from main)
    ; and even cols show as backdrop. See Mesen2 ApplyHiResMode lines 1441-
    ; 1446 — output col 2x reads from subScreenBuffer[x], which is only
    ; populated when the layer is designated on TS.
    lda #$13
    sta $212D
    stz $2133                       ; SETINI: interlace OFF
    stz SHADOW_SETINI
    jmp @mode_done

@mode6_init:
    ; --- Mode 6 full PPU setup (Phase 17-8) ---
    ; Mode 6: BG1 = 4bpp hi-res (same pair-tile encoding as Mode 5); no BG2
    ; layer. BG3 is the OPT source (same convention as Mode 2). Setting
    ; BGMODE=$06 auto-activates horizontal doubling (Mesen2 SnesPpu.cpp:1279
    ; — hiResMode = BgMode==6). DoubleWidth + DoubleHeight tilemap used to
    ; cover the full 64×28 tile region for 448-line interlace (same gotcha
    ; as Mode 5; see 17-7a commit fa15c01).
    ;
    ; VRAM layout (consumed by tests/phase17/test_mode6_hires_opt.asm):
    ;   word $0000  BG1 tilemap (4 KB, 64×32 with DoubleWidth; +4 KB via
    ;               DoubleHeight extends into word $0800..$0FFF which
    ;               overlaps BG3's OPT region — see note below)
    ;   word $0800  BG3 tilemap = OPT SOURCE (engine_offset_flush target)
    ;   word $1000  BG1 chardata (4bpp; 32 B/tile, hi-res pair convention)
    ;
    ; VRAM overlap note: BG1's DoubleHeight extension (SC2/SC3 at word
    ; $0800..$0FFF) overlaps BG3's OPT tilemap at word $0800. For
    ; line-doubled 512×224 (the default per decision 8), BG1 only fetches
    ; rows 0..27 → stays in SC0/SC1 at word $0000..$07FF. The overlap
    ; only matters if a Mode 6 scene enables interlace AND authors content
    ; across the full 448-line range — a niche combo. 17-8's demo runs
    ; line-doubled, which fits cleanly.
    ;
    ; BG12NBA = $01: BG1 chr at (1)*$1000 = $1000. BG2 bits ignored
    ; (no BG2 in Mode 6).
    ; TM = $11: BG1 + OBJ (no BG2, no BG3 — BG3 is OPT source).
    ; TS = $11: BG1 on sub-screen too (hi-res left/right pair requirement).
    lda #$03                        ; BG1SC: tilemap word $0000, DoubleWidth+DoubleHeight
    sta $2107
    lda #$08                        ; BG3SC: tilemap word $0800 (offset src)
    sta $2109
    lda #$01                        ; BG12NBA: BG1 chr $1000 (BG2 unused)
    sta $210B
    lda #$11                        ; TM: BG1 + OBJ
    sta $212C
    sta SHADOW_TM
    lda #$11
    sta $212D                       ; TS: BG1 on sub-screen (hi-res pair)
    stz $2133                       ; SETINI: interlace OFF
    stz SHADOW_SETINI
    jmp @mode_done

@mode4_init:
    ; --- Mode 4 full PPU setup (Phase 17-6) ---
    ; Mode 4: BG1 = 8bpp (256-color direct CGRAM index), BG2 = 2bpp
    ; (4-color sub-palettes). BG3 is NOT rendered — its tilemap is the
    ; per-column OPT source (row 0 only; Mode 4 reuses Mode 2's H fetch
    ; but omits the V fetch — see Mesen2 SnesPpu.cpp:346-361).
    ;
    ; OPT word format in Mode 4 uses bit 15 as a per-column H/V axis
    ; select (clear = H tile-granular; set = V pixel-granular). 17-6
    ; exercises only the H (bit 15 = 0) path per minimal-coverage scope
    ; (decision 9). A future sub-phase may add explicit V-select writes.
    ;
    ; VRAM layout (consumed by tests/phase17/test_mode4_opt.asm):
    ;   word $0000  BG1 tilemap (2 KB)
    ;   word $0400  BG2 tilemap (2 KB)
    ;   word $0800  BG3 tilemap = OPT SOURCE
    ;   word $1000  BG1 chardata (8bpp; 64 B/tile)
    ;   word $3000  BG2 chardata (2bpp; 16 B/tile)
    ;
    ; BG12NBA = $31: BG1 chr at (1)*$1000 = $1000, BG2 chr at (3)*$1000
    ; = $3000. BG2 2bpp tiles are small, so placement is flexible.
    ; TM = $13: BG1 + BG2 + OBJ (BG3 OFF — it's the OPT source).
    lda #$00                        ; BG1SC: tilemap word $0000
    sta $2107
    lda #$04                        ; BG2SC: tilemap word $0400
    sta $2108
    lda #$08                        ; BG3SC: tilemap word $0800 (offset src)
    sta $2109
    lda #$31                        ; BG12NBA: BG1 chr $1000, BG2 chr $3000
    sta $210B
    lda #$00                        ; BG34NBA: BG3 chr $0000 (unused)
    sta $210C
    lda #$13                        ; TM: BG1 + BG2 + OBJ (BG3 disabled)
    sta $212C
    sta SHADOW_TM
    jmp @mode_done

@mode3_init:
    ; --- Mode 3 full PPU setup (Phase 17-2) ---
    ; Mode 3: BG1 = 8bpp (256-color direct CGRAM index), BG2 = 4bpp
    ; (16 colors via sub-palette). BG3/BG4 not present in this mode.
    ;
    ; VRAM layout (consumed by tests/phase17/test_mode3_256color.asm):
    ;   word $0000  BG1 tilemap (2 KB, 32x32)
    ;   word $0400  BG2 tilemap (2 KB, 32x32)
    ;   word $1000  BG1 chardata (8bpp; 64 B/tile)
    ;   word $2000  BG2 chardata (4bpp; 32 B/tile)
    ;
    ; BG12NBA = $21: BG1 chr at (1)*$1000 = $1000, BG2 chr at (2)*$1000
    ; = $2000.
    lda #$00                        ; BG1SC: tilemap word $0000
    sta $2107
    lda #$04                        ; BG2SC: tilemap word $0400
    sta $2108
    lda #$21                        ; BG12NBA: BG1 chr $1000, BG2 chr $2000
    sta $210B
    lda #$13                        ; TM: BG1 + BG2 + OBJ (no BG3/BG4 in Mode 3)
    sta $212C
    sta SHADOW_TM
    jmp @mode_done

@mode_done:
    lda #$01
    sta BG_SHADOW_REGS_DIRTY

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@reject:
    .a8
    ; Out of range (>= 8) or reserved (5/6). Set rejection flag, leave
    ; SHADOW_BGMODE/BG_MODE_CURRENT unchanged — the last-good mode remains.
    lda BG_MODE_DISPATCH_FLAGS
    ora #$01
    sta BG_MODE_DISPATCH_FLAGS

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; -----------------------------------------------------------------------------
; engine_hires_interlace — toggle Mode 5/6 screen interlace ($2133 bit 0).
;
; API block:
;   API_BLOCK_BASE + 0   enable (0 = line-doubled 512×224, 1 = 512×448
;                                interlaced)
;
; Writes bit 0 of both the live PPU $2133 and the SHADOW_SETINI mirror.
; Other SETINI bits are preserved. Decision 8 default is enable=0; most
; shipping titles (action-RPGs, hi-res logo intros, etc.) ship with interlace
; OFF. One outlier title is the only known commercial 448i-in-gameplay
; reference.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Internal A8 toggles bracketed.
;
; Clobbers: A.
; -----------------------------------------------------------------------------
engine_hires_interlace:
    rep #$30
    .a16
    .i16

    sep #$20
    .a8

    ; Load enable (low byte of param 0), mask to bit 0.
    lda API_BLOCK_BASE + 0
    and #$01

    ; Update shadow: clear bit 0 of SHADOW_SETINI, then OR in the new bit.
    ; Preserves bits 1-7 (obj interlace, overscan, pseudo-hires, etc.).
    pha
    lda SHADOW_SETINI
    and #$FE
    sta SHADOW_SETINI
    pla
    ora SHADOW_SETINI
    sta SHADOW_SETINI
    sta $2133                       ; commit to PPU

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts
