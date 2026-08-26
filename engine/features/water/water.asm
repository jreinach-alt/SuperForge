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
