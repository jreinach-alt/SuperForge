; =============================================================================
; sf_split_h.inc — horizontal raster-band split via HDMA (macro library)
; =============================================================================
; Front door for a HORIZONTAL (top/bottom) split: HDMA rewrites a PPU register
; at HBlank between scanlines, so different scanline BANDS render differently.
; This is the clean, well-proven axis for per-region rendering on stock SNES —
; the register latch takes effect per-scanline at HBlank, so an HDMA-driven band
; boundary is a single clean scanline seam (a mid-active-display register write,
; by contrast, smears). The split is armed once; the engine NMI re-arms $420C
; from NMI_HDMA_ENABLE every VBlank, so a static band costs nothing per frame.
;
; MECHANISM (one register, two bands): an HDMA table of the shape
;   [split, top_byte, $01, bot_byte, $00]
;   [split, top ]  lines 0..split-1  -> register = top_byte  (the top band)
;   [ 1,    bot ]  line split          -> register = bot_byte  (the bottom band)
;   [ 0        ]   terminator          -> register holds bot_byte for the rest
; drives ONE PPU register (BGMODE / TM / TS / COLDATA / brightness / a window
; edge / a Mode-7 matrix column). Arm several channels — one per register — to
; compose a multi-register band (e.g. BGMODE + TM together = a genuine mode
; split: a Mode-1 tile layer above a Mode-7 floor).
;
; CHANNEL ROUTING (the registry — why this is not hand-hardcoded $43xx): each
; band routes through the engine HDMA allocator. sf_split_h_arm calls
; hdma_request for ONE free channel, then hdma_bind_direct (engine/hdma_alloc.asm)
; binds that channel to the register's BBAD and arms it. The allocator owns the
; channel<->register map, so two independent splits can never collide on a
; channel the way hand-rolled CH2/CH3 programming did. hdma_request/bind require
; A16/I16 and DB=$00 (the $43xx are bank-$00 I/O; NMI_HDMA_ENABLE is mirrored low
; WRAM). Reserve CH0/CH1 first with hdma_alloc_init at boot.
;
; ARCHETYPE COVERAGE (v1):
;   A  Mode-7 floor + genuine tile HUD band  — BGMODE + TM bands (2 channels)
;   B  Mode-7 scenic backdrop behind a tile playfield — BGMODE + TM/TS bands
;   D  window / colour-math / brightness band (no mode change) — COLDATA /
;      brightness / window-edge band (1 channel, the cheap companion)
;   C-horiz  stacked per-band Mode-7 CAMERA (matrix M7A-D / M7X/Y bands) — a
;      BACKLOG stretch: it needs the ValueLatch guard (see below), so v1 ships
;      NO matrix-band demo. The registry equates for the matrix registers are
;      provided so a caller CAN arm one, but only under the guard's contract.
;
; THE ValueLatch GUARD (for MATRIX bands only — SF_SPLIT_M7A..M7Y):
;   The Mode-7 write-twice latch byte is SHARED across M7A-D ($211B-$211E), M7X
;   ($211F), M7Y ($2120), M7HOFS ($210D) and M7VOFS ($210E). Note $210D/$210E are
;   the SAME PPU addresses as BG1HOFS/BG1VOFS — a code-side BG1 scroll write
;   shares this same latch. If an HDMA channel writes a matrix register BETWEEN
;   the two bytes of a code-side write-twice to any shared-latch register, BOTH
;   corrupt. v1 payloads (BGMODE / TM / TS /
;   COLDATA / window / brightness) DO NOT touch that latch, so they need NO
;   guard — proven safe. A matrix band DOES, so its contract is: every code-side
;   write-twice pair to a shared-latch register happens ONLY in VBlank / forced
;   blank (shadow -> NMI-commit; never in the main loop during active display),
;   while the matrix-band HDMA fires only during active display — the two are
;   then structurally non-interleaving. Ship a matrix band ONLY under that rule.
;
; CLEAN-ROOM: mechanism only — no game references. The register values are
; factual hardware configuration.
;
; ENGINE LINK PARTNERS (link into the ROM's CODE segment):
;   engine_state.inc (equates), the engine NMI handler (re-arms $420C from
;   NMI_HDMA_ENABLE), and hdma_alloc.asm (hdma_alloc_init / hdma_request /
;   hdma_release / hdma_bind_direct).
; =============================================================================

.ifndef SF_SPLIT_H_INC
SF_SPLIT_H_INC = 1

.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0 (the marshal slots)

; -----------------------------------------------------------------------------
; HDMA-target registry — BBAD (register low byte) for the split-eligible PPU
; registers. Pass one of these as `reg_sel` to sf_split_h_arm / _2band.
; -----------------------------------------------------------------------------
SF_SPLIT_BGMODE   = $05         ; $2105 BGMODE  — the video-mode band (A/B)
SF_SPLIT_TM       = $2C         ; $212C TM      — main-screen layer enable (A/B)
SF_SPLIT_TS       = $2D         ; $212D TS      — sub-screen layer enable (B)
SF_SPLIT_COLDATA  = $32         ; $2132 COLDATA — fixed-colour band (D)
SF_SPLIT_BRIGHT   = $00         ; $2100 INIDISP — brightness/force-blank band (D)
SF_SPLIT_W12SEL   = $23         ; $2123 W12SEL  — window-1/2 BG select band (D)
SF_SPLIT_WH0      = $26         ; $2126 WH0     — window-1 left edge band (D)
SF_SPLIT_WH1      = $27         ; $2127 WH1     — window-1 right edge band (D)
; --- MATRIX — ValueLatch guard required (see header) --------------------------
SF_SPLIT_M7A      = $1B         ; $211B M7A  — MATRIX — ValueLatch guard required
SF_SPLIT_M7B      = $1C         ; $211C M7B  — MATRIX — ValueLatch guard required
SF_SPLIT_M7C      = $1D         ; $211D M7C  — MATRIX — ValueLatch guard required
SF_SPLIT_M7D      = $1E         ; $211E M7D  — MATRIX — ValueLatch guard required
SF_SPLIT_M7X      = $1F         ; $211F M7X  — MATRIX — ValueLatch guard required
SF_SPLIT_M7Y      = $20         ; $2120 M7Y  — MATRIX — ValueLatch guard required

; -----------------------------------------------------------------------------
; sf_split_h_arm reg_sel, table_label, effect_id — arm ONE register's band.
; -----------------------------------------------------------------------------
; Request one free HDMA channel from the allocator and bind it to `reg_sel`
; (a BBAD registry equate) driving the HDMA table at `table_label`. On success
; the channel is armed (its bit ORed into NMI_HDMA_ENABLE) and the channel mask
; is left in ENGINE_A0 (read it back for a later sf_split_h_off). On allocator
; failure (no free channel) it is a no-op (ENGINE_A0 = 0, carry set by
; hdma_request).
;   reg_sel      a BBAD registry equate (SF_SPLIT_*), or a raw register low byte.
;   table_label  LABEL of the HDMA table (RODATA/WRAM). Address + bank taken via
;                .loword / ^.
;   effect_id    allocator tag ($01..$FE) — distinct per split so _off releases
;                the right channel.
; Call ONCE in setup (A16/I16 entry, DB=$00). Clobbers A, X, Y.
; WIDTH-RISK: entry A16/I16, DB=$00. Toggles A8 for the API-block bank byte, then
; A16 for the hdma_request marshal + jsr; exits A16/I16. hdma_request/bind keep
; DB=$00; no DB switch here.
.macro sf_split_h_arm sf_reg_sel, sf_table, sf_effect_id
    rep #$30
    .a16
    .i16
    ; --- request ONE channel: A16 = n_channels(=1) in bits 0..3; X = effect_id.
    lda #$0001                  ; 1 channel, priority 0, mode_pref 0
    ldx #sf_effect_id
    jsr hdma_request            ; -> ENGINE_A0 = channel mask, C=1 on failure
    bcs :+                      ; allocator empty -> no-op (mask 0 already stored)
    ; --- bind the allocated channel to reg_sel + the HDMA table, then arm ---
    lda #.loword(sf_table)
    sta API_BLOCK_BASE + 0      ; table address low word (lo at +0, hi at +1)
    sep #$20
    .a8
    lda #^sf_table
    sta API_BLOCK_BASE + 2      ; table bank
    lda #$00
    sta API_BLOCK_BASE + 3      ; DMAP = $00 (direct 1-byte -> 1-register): every
                                ;   1-byte split (BGMODE/TM/TS/COLDATA/bright/
                                ;   window) is direct mode. Written explicitly so
                                ;   hdma_bind_direct never sees a stale slot — the
                                ;   matrix band (sf_split_h_matrix_band) is the
                                ;   only caller that sets $03 here instead.
    rep #$20
    .a16
    ; hdma_bind_direct needs DB=$00 (its $43xx + NMI_HDMA_ENABLE writes are
    ; DB-relative absolute). Force it here so the caller's DB (whatever the Mode-7
    ; setup left) cannot misdirect the writes; restore it after.
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = $00
    rep #$20
    .a16
    lda ENGINE_A0               ; A16 = channel mask (single bit)
    ldx #sf_reg_sel             ; X16 = BBAD
    jsr hdma_bind_direct        ; programs $43xx + ORs mask into NMI_HDMA_ENABLE
    plb                         ; restore caller DB
:
.endmacro

; -----------------------------------------------------------------------------
; sf_split_h_2band reg_sel, top, bot, split, table_label, effect_id — the
; 2-band convenience: emit the [split,top,1,bot,0] HDMA table in RODATA, then arm
; the register's band on an allocator-assigned channel.
; -----------------------------------------------------------------------------
;   reg_sel      BBAD registry equate (SF_SPLIT_*).
;   top, bot     the register byte for the TOP band (lines 0..split-1) and the
;                BOTTOM band (line split onward). Bare literals.
;   split        the scanline the top band ends / the bottom band begins
;                (1..127 — a 7-bit HDMA repeat count). Bare literal.
;   table_label  a UNIQUE identifier for the emitted table (one per call — ca65
;                textual substitution defines the label here). Bare identifier.
;   effect_id    allocator tag ($01..$FE), distinct per split.
; Call ONCE in setup (A16/I16 entry, DB=$00). Clobbers A, X, Y.
; WIDTH-RISK: inherits sf_split_h_arm's contract (A16/I16 in/out, DB=$00). The
; table bytes are assembled in RODATA (a .pushseg block), no runtime width cost.
.macro sf_split_h_2band sf_reg_sel, sf_top, sf_bot, sf_split, sf_table, sf_effect_id
    ; Thin wrapper over sf_split_h_bands: the 2-band step is exactly the pair
    ; list {split,top, 1,bot} (the trailing $00 terminator is emitted by
    ; sf_split_h_bands). Signature/behaviour unchanged — the demo + tests use it.
    sf_split_h_bands sf_reg_sel, sf_table, sf_effect_id, {sf_split, sf_top, $01, sf_bot}
.endmacro

; -----------------------------------------------------------------------------
; sf_split_h_bands reg_sel, table_label, effect_id, {c0,v0, c1,v1, ...} — the
; N-BAND compiler: emit an N-entry HDMA table from a caller-provided list of
; (count, value) band pairs and arm it on an allocator channel.
; -----------------------------------------------------------------------------
; HDMA TABLE SEMANTICS (direct 1-register, non-repeat format — the same shape
; the 2-band step uses, generalised to N entries):
;   .byte c0,v0, c1,v1, ..., $00
;   each `count` (c_i) is a 7-bit LINE COUNT (1..127, bit7=0 -> non-repeat: one
;     value byte v_i is written to the register, then held for c_i scanlines);
;   `value` (v_i) is the register byte for that band;
;   the final `$00` TERMINATES the table — after the last band the register
;     HOLDS the last value (v_last) for the remainder of the frame.
;   So the bands tile the screen top-to-bottom: band0 = lines 0..c0-1 = v0,
;   band1 = lines c0..c0+c1-1 = v1, ... and v_last holds to line 224.
;   The counts should sum to <= 224 (the visible height); an over-long final
;   band is simply clamped by the frame ending. A 3-band split is {c0,v0,
;   c1,v1, c2,v2} (the terminator is appended here — do NOT include it).
;
;   reg_sel      BBAD registry equate (SF_SPLIT_*), or a raw register low byte.
;   table_label  UNIQUE identifier for the emitted RODATA table (one per call).
;   effect_id    allocator tag ($01..$FE), distinct per split.
;   pairs        a BRACE-GROUPED {c0,v0, c1,v1, ...} list — ONE macro arg (the
;                braces keep the comma-separated pairs together). Emitted
;                verbatim as `.byte <pairs>, $00`.
; Call ONCE in setup (A16/I16 entry, DB=$00). Clobbers A, X, Y.
; WIDTH-RISK: inherits sf_split_h_arm's contract (A16/I16 in/out, DB=$00). The
; table bytes are assembled in RODATA (a .pushseg block), no runtime width cost.
.macro sf_split_h_bands sf_reg_sel, sf_table, sf_effect_id, sf_pairs
    .pushseg
    .segment "RODATA"
sf_table:
    .byte sf_pairs, $00
    .popseg
    sf_split_h_arm sf_reg_sel, sf_table, sf_effect_id
.endmacro

; -----------------------------------------------------------------------------
; sf_split_h_off mask — release a split's channel and disarm its HDMA.
; -----------------------------------------------------------------------------
; Return the channel to the allocator (hdma_release) and clear its bit from
; NMI_HDMA_ENABLE so the NMI stops re-arming it. `mask` is the channel mask the
; arm left in ENGINE_A0 (a memory symbol or `#literal`).
; Call from the main loop or a scene teardown (A16 entry, DB=$00). Clobbers
; A, X, Y.
; WIDTH-RISK: entry A16/I16, DB=$00. hdma_release toggles A8 internally + sets
; DB=$7E and restores it; the NMI_HDMA_ENABLE clear here is done A8 then A16.
.macro sf_split_h_off sf_mask
    rep #$30
    .a16
    .i16
    lda sf_mask
    pha                         ; keep the mask (16-bit push) for the clear below
    jsr hdma_release            ; A16 = mask -> returned to the allocator
    pla                         ; A16 pop (balances the push) — mask in A16
    eor #$FFFF
    sep #$20
    .a8
    and NMI_HDMA_ENABLE         ; A8: clear the channel's bit(s)
    sta NMI_HDMA_ENABLE         ; stop the NMI re-arming it
    rep #$30
    .a16
    .i16
.endmacro

; =============================================================================
; ARCHETYPE C-horiz — stacked per-band Mode-7 CAMERA bands (the MATRIX band)
; =============================================================================
; Render TWO (or more) vertically-stacked views of ONE Mode-7 world, each band a
; DIFFERENT camera set by the Mode-7 matrix (M7A-D) changing at the band seam via
; HDMA. Trial-proven (framebuffer-verified): top band scale $0100 (1.0) renders
; the world at an 8-px on-screen checker period; bottom band scale $0040 (0.25)
; renders it 4x larger (32-px period) — the SAME map+CHR+CGRAM, only the matrix
; differs. Both cameras share the low-32KB Mode-7 VRAM: no extra VRAM cost.
;
; -----------------------------------------------------------------------------
; BYPASS, NOT COEXIST (the exclusivity rule — READ THIS):
;   The engine's sf_mode7_perspective / pv_rebuild owns the per-scanline M7A-D
;   HDMA stream on CH5/CH6 (a SINGLE-camera trapezoid rebuilt every frame). A
;   per-band matrix CANNOT layer on top of that — it must OWN the M7A-D HDMA. So
;   a matrix band is MUTUALLY EXCLUSIVE with the perspective renderer: do the
;   MINIMAL Mode-7 init (BGMODE=7, M7SEL, load map, CGRAM, M7X/Y once under
;   forced blank) but do NOT call sf_mode7_perspective / sf_mode7_tick. The
;   matrix band drives M7A-D itself. (Mixing the two double-arms M7A-D and
;   collapses the plane.)
;
; THE NON-REPEAT TRAP (the #1 gotcha — front and centre):
;   Each band's HDMA entry uses a count byte with bit7 = 0 (NON-REPEAT): the
;   4-byte matrix unit is transferred ONCE and HELD for `count` scanlines. That
;   is exactly a flat per-band camera (a constant matrix per band) and it is
;   CHEAP — 2 HBlank writes/frame per channel. Do NOT set bit7 (REPEAT): repeat
;   mode re-reads a NEW 4-byte unit EVERY scanline and walks off the short
;   per-band table, collapsing the whole plane to tile 0. REPEAT mode is only for
;   a per-scanline ramp (the perspective variant — a documented BACKLOG stretch,
;   NOT this macro).
;
; REGISTERS + CHANNELS (cost = 2 channels):
;   AB channel: DMAP $03 (write-2-registers-twice), BBAD $1B ($211B) — the entry
;               [count, A_lo, A_hi, B_lo, B_hi] streams into M7A ($211B) + M7B
;               ($211C).
;   CD channel: DMAP $03, BBAD $1D ($211D) — [count, C_lo, C_hi, D_lo, D_hi]
;               streams into M7C ($211D) + M7D ($211E).
;   M7X / M7Y ($211F/$2120): FOLDABLE — set ONCE under forced blank for a
;               constant-centre stack (scale/rotation-per-band alone reprojects
;               the shared centre). A per-band CENTRE would need a 3rd channel —
;               NOT in this variant. Per-band PERSPECTIVE (per-scanline matrix) is
;               NOT in this variant either (see BACKLOG in docs/guides/split_h.md).
;
; ValueLatch GUARD — satisfied BY CONSTRUCTION for flat bands:
;   The Mode-7 write-twice latch is shared across M7A-D / M7X/Y / M7HOFS/VOFS
;   (== BG1HOFS/VOFS). A flat matrix band writes those regs ONLY under forced
;   blank / VBlank (M7X/Y/M7SEL/offsets set once at boot; the matrix is entirely
;   HDMA-driven during active display), so no code-side write-twice can interleave
;   with the matrix HDMA — structurally non-interleaving. (The prior sf_split_h
;   trial's per-scanline REPEAT-mode negative control is the proven collision
;   case; a flat band does not manufacture that risk.)
;
; -----------------------------------------------------------------------------
; sf_split_h_matrix_band table_ab, table_cd, effect_id — arm a flat matrix band.
; -----------------------------------------------------------------------------
;   table_ab  LABEL of the M7A/M7B HDMA table in RODATA/WRAM. Shape (NON-REPEAT):
;               .byte count0        ; band-0 line count (1..127, bit7 = 0)
;               .word A0, B0         ; band-0 M7A, M7B (8.8 fixed)
;               .byte count1
;               .word A1, B1         ; band-1 …
;               .byte $00            ; terminator (last matrix HELD to frame end)
;   table_cd  LABEL of the matching M7C/M7D table (same band structure):
;               .byte count0
;               .word C0, D0
;               … .byte $00
;   effect_id allocator tag ($01..$FE). This macro requests 2 channels TOGETHER
;             under one tag; sf_split_h_matrix_off releases both.
;
; Requests 2 channels via hdma_request (one call), then binds them:
;   channel bit LOW  -> AB table, BBAD $1B, DMAP $03
;   channel bit HIGH -> CD table, BBAD $1D, DMAP $03
; and OR-arms both. FAIL-SOFT: if <2 channels free, hdma_request returns C=1 and
; this is a no-op (ENGINE_A0 = 0). The 2-channel mask is left in ENGINE_A0 (read
; it back for a later sf_split_h_matrix_off / sf_split_h_off — the SAME mask
; disarms both channels at once). Call ONCE in setup (A16/I16 entry, DB=$00,
; AFTER hdma_alloc_init). Clobbers A, X, Y.
;
; WIDTH-RISK: entry A16/I16, DB=$00. Toggles A8 for the API-block bank/DMAP
; bytes, A16 for the marshal + jsr. Sets DB=$00 for both binds (like
; sf_split_h_arm), restores caller DB. Exits A16/I16. hdma_request/bind keep
; DB=$00 internally per their contracts.
.macro sf_split_h_matrix_band sf_tab_ab, sf_tab_cd, sf_effect_id
    rep #$30
    .a16
    .i16
    ; --- request TWO channels under one effect tag (fail-soft if <2 free) ---
    lda #$0002                  ; 2 channels, priority 0, mode_pref 0
    ldx #sf_effect_id
    jsr hdma_request            ; -> ENGINE_A0 = 2-bit channel mask, C=1 on fail
    bcs :+                      ; allocator could not give 2 -> no-op
    ; --- isolate the LOW channel bit (-> AB) and the HIGH bit (-> CD) from the
    ;     2-bit mask. LOW bit = mask & -mask; HIGH bit = mask ^ LOW. Stash both
    ;     in the free API slots 4/5 (+16/+20) so the binds can restore each. ---
    lda ENGINE_A0
    sta API_BLOCK_BASE + 16     ; slot4: full 2-bit mask (survives for _off)
    ; low bit = mask AND (0 - mask)  (two's-complement isolate-lowest-set-bit)
    eor #$FFFF
    inc a                       ; A = -mask
    and ENGINE_A0               ; A = lowest set bit (the AB channel)
    sta API_BLOCK_BASE + 20     ; slot5: AB channel bit
    ; --- bind the AB channel: BBAD $1B, DMAP $03, table_ab ---
    lda #.loword(sf_tab_ab)
    sta API_BLOCK_BASE + 0
    sep #$20
    .a8
    lda #^sf_tab_ab
    sta API_BLOCK_BASE + 2      ; AB table bank
    lda #$03
    sta API_BLOCK_BASE + 3      ; DMAP $03 = matrix write-2-regs (M7A + M7B)
    rep #$20
    .a16
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = $00 (hdma_bind_direct contract)
    rep #$20
    .a16
    lda API_BLOCK_BASE + 20     ; A16 = AB channel bit
    ldx #SF_SPLIT_M7A           ; BBAD $1B ($211B -> M7A, continues into M7B)
    jsr hdma_bind_direct
    ; --- bind the CD channel: BBAD $1D, DMAP $03, table_cd ---
    lda #.loword(sf_tab_cd)
    sta API_BLOCK_BASE + 0
    sep #$20
    .a8
    lda #^sf_tab_cd
    sta API_BLOCK_BASE + 2      ; CD table bank
    lda #$03
    sta API_BLOCK_BASE + 3      ; DMAP $03 = matrix write-2-regs (M7C + M7D)
    rep #$20
    .a16
    ; CD channel bit = full mask XOR AB bit.
    lda API_BLOCK_BASE + 16
    eor API_BLOCK_BASE + 20     ; A16 = CD channel bit
    ldx #SF_SPLIT_M7C           ; BBAD $1D ($211D -> M7C, continues into M7D)
    jsr hdma_bind_direct
    plb                         ; restore caller DB
    ; leave the full 2-bit mask in ENGINE_A0 for a later _off.
    lda API_BLOCK_BASE + 16
    sta ENGINE_A0
:
    ; (the fail-soft no-op path lands here: ENGINE_A0 = 0 from hdma_request)
.endmacro

; -----------------------------------------------------------------------------
; sf_split_h_matrix_bands table_ab, table_cd, effect_id, {c0,A0,B0,C0,D0, c1,…}
;   — the BANDLIST COMPILER: emit the two NON-REPEAT HDMA tables from ONE list of
;   (count, M7A, M7B, M7C, M7D) 5-tuples, then arm the flat matrix band.
; -----------------------------------------------------------------------------
;   table_ab / table_cd  UNIQUE identifiers for the two emitted RODATA tables
;                        (one pair per call — ca65 textual substitution defines
;                        the labels here).
;   effect_id            allocator tag ($01..$FE).
;   bands                a BRACE-GROUPED {c0,A0,B0,C0,D0, c1,A1,B1,C1,D1, …} list
;                        — ONE macro arg. Each 5-tuple is a band: `count` (7-bit
;                        line count, bit7 = 0 -> NON-REPEAT), then the four 8.8
;                        matrix words M7A,M7B,M7C,M7D. The tuples are split into
;                        the AB table ([count,A,B]) and CD table ([count,C,D])
;                        with matching counts + $00 terminators.
; Bands tile the screen top-to-bottom; counts should sum to <= 224. Emits the
; tables in RODATA (a .pushseg block) then calls sf_split_h_matrix_band — same
; arm/fail-soft/mask contract. Call ONCE in setup (A16/I16, DB=$00). Clobbers
; A, X, Y.
;
; WIDTH-RISK: inherits sf_split_h_matrix_band's contract (A16/I16 in/out,
; DB=$00). The table bytes assemble in RODATA — no runtime width cost.
.macro sf_split_h_matrix_bands sf_tab_ab, sf_tab_cd, sf_effect_id, sf_bands
    .pushseg
    .segment "RODATA"
    ; Two recursive walks over the SAME 5-tuple list: the AB walk keeps
    ; [count,A,B] per band, the CD walk keeps [count,C,D]. Each recursion consumes
    ; ONE 5-tuple (count,A,B,C,D) and re-invokes itself with the remaining tokens
    ; via .left / .mid, terminating when the list is empty (.tcount = 0). Both
    ; tables get a $00 terminator.
sf_tab_ab:
    sf_m7band_ab {sf_bands}
    .byte $00
sf_tab_cd:
    sf_m7band_cd {sf_bands}
    .byte $00
    .popseg
    sf_split_h_matrix_band sf_tab_ab, sf_tab_cd, sf_effect_id
.endmacro

; --- private recursive emitters for sf_split_h_matrix_bands (guarded so a second
;     .include of this file does not redefine them). Each consumes ONE 5-tuple
;     (count, M7A, M7B, M7C, M7D) from the head of the list and recurses on the
;     tail. NOTE ca65 counts COMMAS as tokens: a 5-tuple is 5 values + 4
;     separating commas = 9 tokens; the comma BETWEEN tuples is the 10th, so the
;     next tuple's `count` is at token index 10. Value tokens sit at even indices
;     0,2,4,6,8 within a tuple; the recursion advances by 10 tokens per band and
;     terminates once fewer than 9 tokens remain (no complete tuple). ---
.macro sf_m7band_ab sf_list
    .if .tcount({sf_list}) >= 9
        .byte  (.mid(0, 1, {sf_list}))          ; count (NON-REPEAT: bit7 must be 0)
        .word  (.mid(2, 1, {sf_list}))          ; M7A
        .word  (.mid(4, 1, {sf_list}))          ; M7B
        .if .tcount({sf_list}) > 10             ; another tuple follows the comma?
            sf_m7band_ab {.mid(10, .tcount({sf_list}) - 10, {sf_list})}
        .endif
    .endif
.endmacro

.macro sf_m7band_cd sf_list
    .if .tcount({sf_list}) >= 9
        .byte  (.mid(0, 1, {sf_list}))          ; count (matches the AB band)
        .word  (.mid(6, 1, {sf_list}))          ; M7C
        .word  (.mid(8, 1, {sf_list}))          ; M7D
        .if .tcount({sf_list}) > 10             ; another tuple follows the comma?
            sf_m7band_cd {.mid(10, .tcount({sf_list}) - 10, {sf_list})}
        .endif
    .endif
.endmacro

; =============================================================================
; ARCHETYPE C-horiz PERSPECTIVE — per-band PER-SCANLINE Mode-7 camera (SHIPPED)
; =============================================================================
; The perspective sibling of the FLAT matrix band above. Where the flat band
; holds a CONSTANT matrix per band (NON-REPEAT, 2 HBlank writes/frame/channel),
; the PERSPECTIVE variant renders TWO full per-scanline trapezoids — two genuinely
; different perspective floors, one per band, at a clean single-scanline seam.
;
; MECHANISM (USE the engine renderer, then SPLICE — do NOT hand-roll a REPEAT
; ramp): the engine's sf_mode7_perspective / sf_mode7_tick already owns CH5/CH6
; and streams a full per-scanline REPEAT-mode AB/CD trapezoid for the LIVE camera
; across the whole floor band [M7_PV_L0 .. M7_PV_L1) — its HBlank cost is the
; SAME as the shipping flight/racer rails (proven at 60fps). This macro pair
; POST-PATCHES the active AB/CD buffer's band-2 scanlines [seam .. L1) with a
; SECOND, captured-once camera's per-scanline matrix -> two distinct perspective
; floors. The splice is CPU writes into WRAM: it adds NO HDMA channel (still just
; CH5|CH6, mask $60). Cost per frame: 1 pv_rebuild (~10k) + the band-2 splice
; copy (~5k). Framebuffer-proven (the split_h_persp_demo rail + its P1-P5 tests).
;
; TWO-CALL API:
;   sf_split_h_persp_capture — call ONCE at boot, after you have built camera B
;     via the engine macros + ONE sf_mode7_tick (so pv_rebuild has filled the
;     active buffer with camera B). Captures the active buffer's band-2 [seam..L1)
;     AB (A,B) + CD (C,D) into the caller's static WRAM save tables.
;   sf_split_h_persp_splice — call EVERY frame, AFTER sf_mode7_tick (which rebuilt
;     the WHOLE floor with the LIVE camera A into the freshly-flipped buffer).
;     Re-applies the saved camera-B band over band-2.
;
; THE ValueLatch GUARD — PROVEN LOAD-BEARING (not just theoretical):
;   The Mode-7 write-twice latch byte is SHARED across M7A-D / M7X/Y / M7HOFS
;   ($210D) / M7VOFS ($210E) — and $210D/$210E ARE BG1HOFS/VOFS. The matrix HDMA
;   fires ONLY during active display; therefore every code-side write-twice pair
;   to ANY shared-latch register MUST happen ONLY in VBlank / forced blank
;   (M7X/Y/M7SEL/offsets once at boot; the engine NMI commits M7X/Y). A code-side
;   write-twice to a shared-latch reg DURING active display, while the per-scanline
;   REPEAT-mode matrix HDMA streams, TEARS the floor — this is the split_h_persp_demo
;   -DLATCH_VIOLATION negative control, which is the PROOF the guard is load-bearing
;   (the flat NON-REPEAT band could not manufacture this collision; the per-scanline
;   density does). Ship the perspective variant ONLY under this rule.
;
; EXCLUSIVITY: like the flat band, this OWNS the Mode-7 renderer — it drives
; sf_mode7_perspective / sf_mode7_tick directly (NOT via a separate matrix band).
; Do NOT combine with sf_split_h_matrix_band on the same scene (both own M7A-D).
;
; SAVE-TABLE SIZING: each save table is (M7_PV_L1 - seam) * 4 bytes (4 bytes per
; band-2 scanline: [A_lo,A_hi,B_lo,B_hi] for AB; [C_lo,C_hi,D_lo,D_hi] for CD).
; Park them in the kit debug region ($7E:Exxx), like the flat rail's G_MSK, to
; avoid DP pressure (the engine routines take the addresses via the API block —
; no new persistent DP state, so `make zp-check` stays clean).
;
; ENGINE LINK PARTNERS (in addition to the flat band's): mode7_hdma.asm provides
; mode7_band_capture (capture) and mode7_band_splice (per-frame apply); the
; Mode-7 perspective renderer (mode7_engine.asm / pv_rebuild) must be linked.
; -----------------------------------------------------------------------------

; -----------------------------------------------------------------------------
; sf_split_h_persp_capture seam, save_ab, save_cd — capture camera B (ONCE).
; -----------------------------------------------------------------------------
;   seam     the seam scanline (first line of the bottom band). A bare literal
;            in [M7_PV_L0+1 .. M7_PV_L1-1].
;   save_ab  address of the static WRAM AB save table ((L1-seam)*4 bytes).
;   save_cd  address of the static WRAM CD save table ((L1-seam)*4 bytes).
; Call ONCE at boot, immediately after a camera-B sf_mode7_tick. Marshals the two
; far save-table pointers + seam into the API block and calls mode7_band_capture,
; which reads the active AB/CD buffers' band-2 span into save_ab / save_cd.
; WIDTH-RISK: entry A16/I16. Toggles A8 for the API-block bank + seam bytes; the
; engine routine runs its own width contract. Exits A16/I16. Clobbers A, X, Y.
.macro sf_split_h_persp_capture sf_seam, sf_save_ab, sf_save_cd
    rep #$30
    .a16
    .i16
    lda #.loword(sf_save_ab)
    sta API_BLOCK_BASE + 0          ; dest AB save-table low word
    lda #.loword(sf_save_cd)
    sta API_BLOCK_BASE + 4          ; dest CD save-table low word
    sep #$20
    .a8
    lda #^sf_save_ab
    sta API_BLOCK_BASE + 2          ; dest AB save-table bank
    lda #^sf_save_cd
    sta API_BLOCK_BASE + 6          ; dest CD save-table bank
    lda #sf_seam
    sta API_BLOCK_BASE + 8          ; seam scanline (u8)
    rep #$20
    .a16
    jsr mode7_band_capture
.endmacro

; -----------------------------------------------------------------------------
; sf_split_h_persp_splice seam, save_ab, save_cd — re-apply camera B (per frame).
; -----------------------------------------------------------------------------
;   seam / save_ab / save_cd  MUST match the sf_split_h_persp_capture call.
; Call EVERY frame AFTER sf_mode7_tick. Marshals the two far save-table pointers +
; seam into the API block and calls mode7_band_splice, which overwrites the active
; AB/CD buffers' band-2 span [seam..L1) (all four coefficients) with the saved
; camera B — over the live camera-A floor pv_rebuild just wrote.
; WIDTH-RISK: same contract as sf_split_h_persp_capture (A16/I16 in/out, A8 for
; the API bank + seam bytes). Clobbers A, X, Y.
.macro sf_split_h_persp_splice sf_seam, sf_save_ab, sf_save_cd
    rep #$30
    .a16
    .i16
    lda #.loword(sf_save_ab)
    sta API_BLOCK_BASE + 0          ; source AB save-table low word
    lda #.loword(sf_save_cd)
    sta API_BLOCK_BASE + 4          ; source CD save-table low word
    sep #$20
    .a8
    lda #^sf_save_ab
    sta API_BLOCK_BASE + 2          ; source AB save-table bank
    lda #^sf_save_cd
    sta API_BLOCK_BASE + 6          ; source CD save-table bank
    lda #sf_seam
    sta API_BLOCK_BASE + 8          ; seam scanline (u8)
    rep #$20
    .a16
    jsr mode7_band_splice
.endmacro

.endif ; SF_SPLIT_H_INC
