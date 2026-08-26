; =============================================================================
; water.asm — BG2: the surface, and the drift that slides it
; =============================================================================
; The keystone BG pattern with one difference: this layer is designated to the
; SUB screen, so what it draws is not a picture but the blender's second
; operand. Everything below is ordinary VRAM/CGRAM work — the translucency is
; the composed CGWSEL/CGADSUB the SCENE writes, from symbols the allocator
; emitted, and there is deliberately nothing about it in this file.
;
; WHAT IS *NOT* HERE, and it is not an omission: TM, TS, CGWSEL, CGADSUB and
; BG2SC. The first four are the screen/blend vocabulary's — composed from this
; feature's [[claims.screen]] and [[claims.blend]] and written by the scene
; from ES_SCR_<SCENE>_*; a raw claim on any of them beside a screen claim is
; refused (docs/99 R6). BG2SC is this feature's own claim under `scene_writes`,
; which is a PERMISSION granted to scene-enter code — and no_literals'
; declaration-that-lies check refuses the permission if this file writes it
; too. So the layer's map base is established in game/lakeside/scenes/*.asm
; beside the rest of the scene's display shape, and that placement is enforced
; rather than conventional.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The surface's LAYOUT, as the asset generator emitted it: which tile the map's
; twinkle cells point at, where the highlight's phases live behind it, how many
; there are, and how far the surface drifts between two of them. Pinned by
; format version rather than copied, because a re-authored tile order moves
; every one of these numbers and a narrated copy would index the wrong bytes
; with every gate still green (AGENTS.md, "A generated include carries a FORMAT
; VERSION and its consumer pins it"). The two shift/size pairs are asserted
; against each other so neither half can be edited alone.
.include "lk_art.inc"
.assert LK_ART_FORMAT = 1, error, "lk_art.inc format moved under water.asm"
.assert (1 << LK_GLINT_STEP_SHIFT) = LK_GLINT_STEP_PX, error, "glint step shift/px disagree"
.assert (1 << LK_GLINT_TILE_SHIFT) = LK_GLINT_TILE_BYTES, error, "glint tile shift/bytes disagree"
.assert (LK_GLINT_PHASES & (LK_GLINT_PHASES - 1)) = 0, error, "glint phase count is not a power of two"

; The enter-time GP-DMA register file, addressed through the channel the
; `wat_up` dma_init claim names — a declared resource, not a hard-coded 1.
WAT_REGS = $4300 + ES_D_WAT_UP_CH * 16

; The vertical offset, written once and never again. BG2VOFS is a scroll
; latch, not a base: scanline N shows tilemap line VOFS + N, and the first
; ACTIVE scanline is 1, so a VOFS of zero would put world line 1 at the top of
; the picture and shift the whole surface up by one line against BG1. Minus
; one is the correction; the PPU keeps 10 bits, so $FFFF reads as 1023 and
; scanline 1 renders line (1023 + 1) mod 256 = 0. It is modular and needs no
; clamp. `lake_bg` applies the identical correction to BG1 and the scene to
; BG3, which is what makes world row r occupy picture rows 8r..8r+7 on all
; three layers at once — the property every band assertion in
; tests/test_lakeside.py rests on.
WAT_VOFS = $FFFF

; --- wat_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; CONTRACT wat_up_dma
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the source address low 16, Y = the byte count, A = the
;             source bank in the low byte
;   out:      the block transferred to VRAM from the caller's VMADD
;   clobbers: A, N, Z
;   assumes:  forced blank, and the enter-time window in which the channel
;             registers are free — this is a dma_init claim, phase
;             forced_blank by class
;   tail:     rts
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call. One arming site is the only shape a caller cannot
; forget (scroller_bg.asm and room_bg.asm record the same reasoning). Arm it
; once outside a multi-slot loop and only the first transfer moves bytes.
wat_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "wat_up_dma"
    stx a:WAT_REGS + 2              ; A1T
    sty a:WAT_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:WAT_REGS + 4              ; A1B — the bank byte the caller passed
    lda #ES_D_WAT_UP_DMAP
    sta a:WAT_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_WAT_UP_BBAD
    sta a:WAT_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_WAT_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- wat_arm: CHR, the map, the palette, the scroll (scene enter) -----------
; CONTRACT wat_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the surface's CHR and tilemap in VRAM, its palette in CGRAM
;             group 2, the scroll accumulator zeroed and BG2's two offset
;             latches established
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
;
; The scroll write is the `wat_scroll` claim's write-before-read contract — the
; reason that claim carries no `[init] zero`. Scene_mgr holds NMI masked across
; the whole switch, so the first VBlank that can commit this word is the first
; one AFTER this routine ran; there is no frame in which the NMI hook could
; publish power-on garbage to BG2HOFS.
wat_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "wat_arm"
    stz z:ES_WAT_SCROLL             ; world px, wrapping
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- the surface CHR: empty, crest, trough ----------------------------
    lda #ES_V_WAT_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(wat_chr_bin)
    ldy #ES_R_WAT_CHR_SIZE
    lda #^wat_chr_bin
    jsr wat_up_dma
    ; ---- the tilemap ------------------------------------------------------
    lda #ES_V_WAT_MAP
    sta a:$2116
    ldx #.loword(wat_map_bin)
    ldy #ES_R_WAT_MAP_SIZE
    lda #^wat_map_bin
    jsr wat_up_dma
    ; ---- palette group 2, CGRAM words 32..47 ------------------------------
    ; CGDATA is a byte port written low-then-high, so the loop is CPU-side:
    ; 16 words is a few dozen cycles of forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_WAT_PAL
    sta a:$2121                     ; CGADD = the claim base (word 32)
    rep #$20
    .a16
    ldx #0
:   lda f:wat_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_WAT_PAL_SIZE
    bcc :-
    ; ---- the two scroll latches -------------------------------------------
    ; Both are write-twice 8-bit latches. VOFS is written here and never
    ; again; HOFS is written here so the layer is aligned before the first
    ; frame the fade makes visible, and re-written by wat_nmi_commit from the
    ; accumulator every armed VBlank after that.
    sep #$20
    .a8
    stz a:$210F                     ; BG2HOFS, low
    stz a:$210F                     ; BG2HOFS, high
    lda #<WAT_VOFS
    sta a:$2110                     ; BG2VOFS, low
    lda #>WAT_VOFS
    sta a:$2110                     ; BG2VOFS, high
    rep #$20
    .a16
    rts

; --- wat_advance: slide the surface by this frame's whole-pixel step --------
; CONTRACT wat_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the whole pixels to advance this frame, as published by
;             the caller's TS_STEP — a region-correct velocity, not a raw
;             per-frame constant
;   out:      ES_WAT_SCROLL advanced by A
;   clobbers: A, N, Z, C
;   assumes:  nothing about the caller's data bank: the accumulator is a dp
;             claim reached with z:
;   tail:     rts
;
; UNBOUNDED, deliberately. The map is 32 cells = 256 px wide and the PPU keeps
; 10 bits of BG2HOFS, so the surface wraps every 256 px whatever this word
; holds; u16 wraparound at 65536 is a multiple of 256, so the picture stays
; continuous across that too. A clamp would introduce an end stop the water
; does not have.
;
; TICK: ok — this routine's unit of time is the DECLARED TICK, not the frame.
;   It adds nothing of its own: `A` arrives as TS_STEP's published whole-unit
;   step, which is the scaler's output and is already expressed against the
;   tick, so the name-matched `_advance` here is a site that CONSUMES a
;   removed frame coupling rather than one that states a new one. Nothing in
;   the body reads a frame counter, and the caller's rate is a base in 8.8,
;   not a per-frame immediate.
wat_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "wat_advance"
    clc
    adc z:ES_WAT_SCROLL
    sta z:ES_WAT_SCROLL
    rts

; --- wat_nmi_commit: BG2HOFS, every armed VBlank ---------------------------
; CONTRACT wat_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      BG2HOFS committed from the scroll accumulator
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. BG2HOFS is a write-twice latch, so the pair must
;             land inside one VBlank and not straddle two
;   tail:     rts
;
; No width toggle at all: the accumulator's two bytes are read as bytes and
; pushed through the latch low-then-high, so this routine cannot leak a width
; back to the NMI hook.
wat_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "wat_nmi_commit"
    lda z:ES_WAT_SCROLL + 0
    sta a:$210F                     ; BG2HOFS, low
    lda z:ES_WAT_SCROLL + 1
    sta a:$210F                     ; BG2HOFS, high
    rts

; --- wat_nmi_glint: the highlight's phase, every armed VBlank --------------
; CONTRACT wat_nmi_glint
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_WAT_SCROLL — where the surface has drifted to, in world px
;   out:      the highlight's display slot rewritten with the phase that
;             position selects, read straight out of the surface's own CHR
;             blob in ROM
;   clobbers: A, X, Y, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. It programs its own VMAIN and VMADD, so where it
;             sits in the hook is free — the rule a new VBlank VRAM writer
;             answers is "program your own, or be ordered last"
;   tail:     rts
;
; THE LOOP IS INDEXED BY POSITION, NOT BY A COUNT OF FRAMES, and that is the
; whole design. The surface's accumulated scroll is already a region-correct
; quantity — the rail advances it through TS_STEP, so it measures distance
; travelled rather than frames elapsed — and selecting a phase from it means
; the twinkle inherits that correctness with no clock of its own, holds still
; exactly when the drift is stilled, and returns to phase 0 in step with the
; 32 px pattern period the picture is asked to repeat across.
;
; TICK: ok -- the phase is a function of a DISTANCE, not of a frame count.
;   ES_WAT_SCROLL is the accumulated output of the caller's TS_STEP, so this
;   routine reads a quantity the scaler already expressed against the declared
;   tick; nothing here counts frames and there is no per-frame immediate.
;
; 32 B through a 16-bit store to VMDATAL, which the PPU splits across
; VMDATAL/VMDATAH: 16 iterations, ~330 cycles of a VBlank that has nothing
; else to do in this rail. No channel, no byte budget, no claim — the bytes
; come from the blob the `wat_chr` rom claim already backs.
wat_nmi_glint:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "wat_nmi_glint"
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_WAT_CHR + LK_GLINT_SLOT * LK_GLINT_TILE_WORDS
    sta a:$2116                     ; VMADD = the display slot's word base
    lda z:ES_WAT_SCROLL
    .repeat LK_GLINT_STEP_SHIFT
    lsr a                           ; ...one phase per LK_GLINT_STEP_PX of drift
    .endrepeat
    and #(LK_GLINT_PHASES - 1)
    .repeat LK_GLINT_TILE_SHIFT
    asl a                           ; ...the phase's offset, in blob bytes
    .endrepeat
    clc
    adc #(LK_GLINT_SRC * LK_GLINT_TILE_BYTES)
    tax
    ldy #(LK_GLINT_TILE_BYTES / 2)
@word:
    .a16
    .i16
    lda f:wat_chr_bin, x            ; absolute long indexed — carries across a
    sta a:$2118                     ;   bank, so the blob's placement is free
    inx
    inx
    dey
    bne @word
    sep #$20
    .a8
    rts
