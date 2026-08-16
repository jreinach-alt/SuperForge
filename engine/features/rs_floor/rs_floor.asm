; =============================================================================
; rs_floor.asm — the railshooter's Mode 7 grid plane: one DMA, four colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; plane never streams: the camera advances forever and the PPU samples the map
; modulo 128 tiles, so a 1024-px world wraps seamlessly under an endless rail.
; That is the whole reason this rail composes no `mode7_stream`.
;
; The blob labels (`rs_map_bin`, `rs_floor_pal_bin`) are the game's `.incbin`
; claim sites in main.asm — the feature names them, the game backs them, and
; `make rom-unbacked` proves the bytes exist per COMPOSITION.

; The enter-time GP-DMA register file, addressed through the channel the rs_up
; dma_init claim names — a declared resource, not a hard-coded 0.
RS_FLOOR_REGS = $4300 + ES_D_RS_UP_CH * 16

; --- the world --------------------------------------------------------------
; DERIVED from the map claim's own size rather than narrated: the Mode 7 blob
; is 2 bytes per tile (tilemap even, CHR odd) over a square plane, so its size
; fixes the side. Writing the derivation is what makes the wrap mask follow the
; map instead of agreeing with it by coincidence — and `no_literals` refuses a
; bare 1023 anyway.
RS_MAP_T    = 128                           ; world side, in tiles
RS_TILE_PX  = 8
.assert 2 * RS_MAP_T * RS_MAP_T = ES_R_RS_MAP_SIZE, error, "rs_floor world size disagrees with the rs_map claim"
RS_WORLD_PX = RS_MAP_T * RS_TILE_PX         ; 1024 — the plane's period
RS_WORLD_MASK = RS_WORLD_PX - 1             ; the camera's wrap (`and #MASK`)
RS_CENTRE   = RS_WORLD_PX / 2               ; 512 — the rail's spawn column

; --- rs_floor_arm: the whole plane (scene enter) ---------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_railshooter_assets.py emits the blob already in that layout. DMA
; mode 1 writes B, B+1, B, B+1 … — with BBAD = VMDATAL that is $2118, $2119,
; $2118, $2119, which is exactly the interleave. So the whole plane is one
; transfer of 32,768 bytes with no unpacking pass.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is
; written, by one word. With the default $00 it would advance after the LOW
; byte and every high byte would overwrite the wrong word.
;
; DAS is single-shot (consumed by the transfer), so it is armed HERE, for THIS
; transfer. One transfer, one arming site; the rule bites when a loop fires
; several and only the first moves bytes.
;
; The blob is 32,768 B = one whole LoROM window, so this cannot cross a bank
; boundary — a DMA's A-bus address wraps within its bank rather than carrying.
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 internally for the $43xx and
; PPU byte ports and restores A16 before every fall-through; I16 is never
; touched. Cross-file callers (the scene's enter) are invisible to width_lint.
rs_floor_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^rs_map_bin
    sta a:RS_FLOOR_REGS + 4         ; A1B = source bank
    lda #ES_D_RS_UP_DMAP
    sta a:RS_FLOOR_REGS + 0         ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_RS_UP_BBAD
    sta a:RS_FLOOR_REGS + 1         ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(rs_map_bin)
    stx a:RS_FLOOR_REGS + 2         ; A1T
    ldy #ES_R_RS_MAP_SIZE
    sty a:RS_FLOOR_REGS + 5         ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_RS_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: four absolute CGRAM indices, CPU-written -------------
    ; Four words is eight stores; a DMA would cost more to set up than to run.
    ; CGADD auto-increments, so this build takes low byte then high byte per
    ; word and walks itself.
    ;
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (which is why `backdrop` cannot compose here). This
    ; rail SEES it: split_band turns BG1 off above the seam, so every sky
    ; scanline sky_band's ramp does not cover is this colour. Deep space,
    ; therefore, and not a floor tint.
    sep #$20
    .a8
    lda #ES_C_RS_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   .a16
    .i16
    lda f:rs_floor_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_RS_FLOOR_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns ------------------------------
    ; M7SEL = 0: no screen-over repeat, no flip. The map is 128x128 tiles and
    ; the PPU samples it modulo 128, so the world WRAPS infinitely in both axes
    ; — which is exactly what an endless forward rail needs, and why the camera
    ; can `and #RS_WORLD_MASK` its two axes and never see an edge. (BGMODE and
    ; TM are the scene's `scene_writes`, seeded for split_band; see this
    ; feature's feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
