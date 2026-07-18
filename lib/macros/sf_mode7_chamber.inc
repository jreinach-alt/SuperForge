; =============================================================================
; sf_mode7_chamber.inc — Mode 7 "barrel chamber" front door (macro library)
; =============================================================================
; The reusable capability behind a rotating, barrel-curved Mode 7 chamber under
; a Mode 1 HUD band with a brightness vignette — the effect a debugger teardown
; + save-state extraction resolved to four cooperating per-scanline HDMA writes
; over the engine's Mode 7 perspective floor:
;
;   1. DUAL-REGISTER MODE-SPLIT (sf_mode7_modesplit) — two direct HDMA channels
;      that switch BGMODE ($2105) AND TM ($212C) at a configurable scanline, so
;      a Mode 1 HUD band renders cleanly above the Mode 7 floor. Both band bytes
;      are configurable (the captured chamber uses $2105 $09->$07 and $212C
;      $14->$17 at line 32). This is the dual-register generalisation of the
;      racer rail's single-register arm_sky_split.
;
;   2. PER-SCANLINE M7A BARREL (sf_mode7_barrel) — arms the engine's G1 hook
;      (engine_mode7_barrel + mode7_barrel_apply, wired into sf_mode7_tick): a
;      caller M7A curve table bows the floor into a barrel. M7B/C/D keep the
;      engine's per-frame rotation, so the floor still spins.
;
;   3. COLDATA VIGNETTE (sf_mode7_vignette) — one direct HDMA channel ramps the
;      $2132 fixed colour 0->8->0 down the frame for a depth vignette (brightest
;      mid, dark top/bottom). Visible only with additive colour math enabled
;      (sf_colormath_on #1) — the captured effect's documented dependency.
;
; WHY DIRECT-CONFIGURED, NON-MODE-7-OWNED CHANNELS (the G4 channel-coordination
; story): the mode-split + vignette channels are programmed DIRECTLY ($43xx +
; an OR into NMI_HDMA_ENABLE), exactly like the racer's arm_sky_split. They are
; NOT added to M7_OWNED_MASK, so the engine NMI's Mode-7 ownership gate passes
; them through untouched — there is NO contention with the CH5/CH6 matrix HDMA
; the way the old engine_mode7_hud CH3 raw-override collided with the gradient.
; The caller assigns each effect an explicit, distinct channel (see the demo's
; allocation table), so all four coexist inside 8 channels with no double-claim.
;
; CANONICAL CHAMBER ALLOCATION (the demo's, matching the capture's ROLES):
;   CH0,CH1  reserved (VBlank bulk DMA, hdma_alloc_init)
;   CH2      BGMODE $2105 split   (sf_mode7_modesplit bgm_ch)
;   CH3      TM     $212C split   (sf_mode7_modesplit tm_ch)
;   CH4      COLDATA $2132 vignette (sf_mode7_vignette col_ch)
;   CH5,CH6  Mode 7 matrix AB/CD  (M7A barrel override lives in the A column)
;   CH7      free
;
; ENGINE LINK PARTNERS: the same set sf_mode7.inc documents (this file adds no
; new engine includes — the barrel hook lives in mode7_hdma.asm, already pulled
; by the sf_mode7.inc link-partner block).
; =============================================================================

.ifndef SF_MODE7_CHAMBER_INC
SF_MODE7_CHAMBER_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_mode7_modesplit bgm_top, bgm_bot, tm_top, tm_bot, split, bgm_ch, tm_ch,
;                    bgm_table, tm_table — the dual-register HUD-band split.
; -----------------------------------------------------------------------------
; Call ONCE during setup (after sf_mode7_on, A16/I16 entry). Builds two 3-entry
; direct HDMA tables in caller WRAM and arms two channels that, at scanline
; `split`, switch BOTH:
;   $2105 (BGMODE)  bgm_top -> bgm_bot   (e.g. $09 Mode1+BG3pri -> $07 Mode7)
;   $212C (TM)      tm_top  -> tm_bot    (e.g. $14 OBJ+BG3 -> $17 BG1+BG2+BG3+OBJ)
;
;   bgm_top/bgm_bot  8-bit BGMODE band bytes (verbatim 16-bit operands, low byte)
;   tm_top/tm_bot    8-bit TM band bytes (verbatim)
;   split            8-bit scanline the HUD band ends / the floor begins
;                    (1..127 — a 7-bit HDMA repeat count). At the captured
;                    chamber this is 32.
;   bgm_ch, tm_ch    channel numbers (2..7) for the BGMODE / TM tables — pick
;                    distinct free channels (the demo uses CH2 / CH3).
;   bgm_table, tm_table  5-byte WRAM bank-$7E scratch addresses (persistent —
;                    the NMI re-arms from them every VBlank; use fixed game-WRAM
;                    slots, not transient DP).
;
; HDMA table shape (per register): [split, top_byte, 1, bot_byte, 0]
;   [split, top]  lines 0..split-1 -> register = top_byte (the HUD band)
;   [ 1,   bot ]  line split        -> register = bot_byte (the floor begins)
;   [ 0        ]  terminator        -> register holds bot_byte for the rest
;
; Clobbers A, X. Requires NMI_HDMA_ENABLE in scope (engine_state.inc).
; WIDTH-RISK: entry A16/I16. Sets A8 (sep #$20) for the byte writes to the
; tables + $43xx + the NMI_HDMA_ENABLE RMW; keeps I16; restores caller width
; via PLP.
.macro sf_mode7_modesplit sf_bgm_top, sf_bgm_bot, sf_tm_top, sf_tm_bot, sf_split, sf_bgm_ch, sf_tm_ch, sf_bgm_table, sf_tm_table
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ; --- BGMODE ($2105) split table ---
    ldx #$0000
    lda sf_split
    sta f:sf_bgm_table + 0, x
    lda sf_bgm_top
    sta f:sf_bgm_table + 1, x
    lda #$01
    sta f:sf_bgm_table + 2, x
    lda sf_bgm_bot
    sta f:sf_bgm_table + 3, x
    lda #$00
    sta f:sf_bgm_table + 4, x
    ; --- TM ($212C) split table ---
    lda sf_split
    sta f:sf_tm_table + 0, x
    lda sf_tm_top
    sta f:sf_tm_table + 1, x
    lda #$01
    sta f:sf_tm_table + 2, x
    lda sf_tm_bot
    sta f:sf_tm_table + 3, x
    lda #$00
    sta f:sf_tm_table + 4, x
    ; --- configure the BGMODE channel ($2105, direct 1-byte) ---
    lda #$00
    sta $4300 + (sf_bgm_ch * $10)       ; DMAPn: A->B, absolute, 1 byte -> 1 reg
    lda #$05
    sta $4301 + (sf_bgm_ch * $10)       ; BBADn: $2105 (BGMODE)
    lda #<sf_bgm_table
    sta $4302 + (sf_bgm_ch * $10)       ; A1Tn L
    lda #>sf_bgm_table
    sta $4303 + (sf_bgm_ch * $10)       ; A1Tn H
    lda #^sf_bgm_table
    sta $4304 + (sf_bgm_ch * $10)       ; A1Bn (table bank)
    ; --- configure the TM channel ($212C, direct 1-byte) ---
    lda #$00
    sta $4300 + (sf_tm_ch * $10)        ; DMAPn
    lda #$2C
    sta $4301 + (sf_tm_ch * $10)        ; BBADn: $212C (TM)
    lda #<sf_tm_table
    sta $4302 + (sf_tm_ch * $10)
    lda #>sf_tm_table
    sta $4303 + (sf_tm_ch * $10)
    lda #^sf_tm_table
    sta $4304 + (sf_tm_ch * $10)
    ; --- arm both channels in NMI_HDMA_ENABLE (additive) ---
    lda NMI_HDMA_ENABLE
    ora #(1 << sf_bgm_ch)
    ora #(1 << sf_tm_ch)
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_vignette table_label, col_ch, table_wram, count — the depth vignette.
; -----------------------------------------------------------------------------
; Call ONCE during setup (after sf_mode7_on, A16/I16 entry). Copies a ROM
; COLDATA HDMA table (already in raw $43xx direct-mode encoding: [count,value]
; pairs, $00 terminator) into caller WRAM and arms a direct HDMA channel on
; $2132. The captured chamber ramps $E0..$E8..$E0 (0->8->0 gray) for a vignette
; brightest through the middle. Pair with additive colour math
; (sf_colormath_on #1, #$21 + sf_colormath_tint #0,#0,#0) so the per-scanline
; fixed colour ADDS onto the floor — without it the COLDATA is invisible.
;
;   table_label  LABEL of the ROM COLDATA table ([count,value]... $00). Address
;                + bank taken via .loword/^.
;   col_ch       channel number (2..7) for the COLDATA HDMA (demo: CH4).
;   table_wram   bank-$7E WRAM scratch base; the table is copied here (must hold
;                `count` bytes + persist — the NMI re-arms from it every VBlank).
;   count        table length in BYTES including the terminator (verbatim 16-bit
;                operand, low byte) — at most 127 so the copy loop stays I8-free.
;
; Clobbers A, X, Y. Requires NMI_HDMA_ENABLE in scope.
; WIDTH-RISK: entry A16/I16. A8/I16 for the copy + $43xx + NMI_HDMA_ENABLE RMW;
; restores caller width via PLP.
.macro sf_mode7_vignette sf_tbl, sf_col_ch, sf_table_wram, sf_count
    .local mv_copy
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ; --- copy the ROM table into WRAM (sf_count bytes) ---
    ldx #$0000
mv_copy:
    .a8
    .i16
    lda f:sf_tbl, x
    sta f:sf_table_wram, x
    inx
    cpx sf_count
    bcc mv_copy
    ; --- configure the COLDATA channel ($2132, direct 1-byte) ---
    lda #$00
    sta $4300 + (sf_col_ch * $10)       ; DMAPn: A->B, absolute, 1 byte -> 1 reg
    lda #$32
    sta $4301 + (sf_col_ch * $10)       ; BBADn: $2132 (COLDATA)
    lda #<sf_table_wram
    sta $4302 + (sf_col_ch * $10)
    lda #>sf_table_wram
    sta $4303 + (sf_col_ch * $10)
    lda #^sf_table_wram
    sta $4304 + (sf_col_ch * $10)
    ; --- arm the channel in NMI_HDMA_ENABLE (additive) ---
    lda NMI_HDMA_ENABLE
    ora #(1 << sf_col_ch)
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_barrel table_label — arm the per-scanline M7A barrel curve (G1).
; -----------------------------------------------------------------------------
; Call ONCE during setup (after sf_mode7_on, A16/I16 entry). Points the engine
; barrel hook (engine_mode7_barrel) at a ROM table of u16 M7A words, one per
; FLOOR scanline (index 0 = perspective horizon scanline l0). sf_mode7_tick's
; mode7_barrel_apply then overwrites M7A per floor-scanline every rebuild. The
; captured chamber uses a symmetric $0100->$0180->$0100 ramp (1.0 flat at the
; edges, 1.5 bulge mid) — the barrel bow.
;
;   table_label  LABEL of the u16 M7A table (address + bank via .loword/^).
;
; Clobbers A, X.
; WIDTH-RISK: entry A16/I16; A8 for the bank byte; exits A16/I16.
.macro sf_mode7_barrel sf_tbl
    rep #$30
    .a16
    .i16
    lda #.loword(sf_tbl)
    sta API_BLOCK_BASE + $00            ; barrel table low word
    sep #$20
    .a8
    lda #^sf_tbl
    sta API_BLOCK_BASE + $02            ; barrel table bank
    rep #$20
    .a16
    jsr engine_mode7_barrel
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_barrel_off — disarm the M7A barrel override.
; -----------------------------------------------------------------------------
; Clobbers A.
; WIDTH-RISK: entry A16/I16; exits A16/I16.
.macro sf_mode7_barrel_off
    rep #$30
    .a16
    .i16
    jsr engine_mode7_barrel_off
.endmacro

.endif ; SF_MODE7_CHAMBER_INC
