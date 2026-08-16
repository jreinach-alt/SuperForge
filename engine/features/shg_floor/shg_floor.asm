; =============================================================================
; shg_floor.asm — the rail's Mode 7 plane: one DMA, five BLUE-ZERO colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; difference between the two bands is the CAMERA's (shg_cam); the wash over
; them is shg_grad's; the world underneath never changes.
;
; A sibling of sit_floor over shg_rom's blobs — the mechanism comments live in
; the tomls; what is repeated here is only what a reader of THIS file needs at
; the write sites. The one real divergence is the palette, and it is the
; rail's test metric rather than a preference: see below.
;
; The blob label `shg_map_bin` is the game's .incbin claim site in main.asm —
; the feature names it, the game backs it, and `make rom-unbacked` proves the
; bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the shg_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SHG_REGS = $4300 + ES_D_SHG_UP_CH * 16

; TM's layer bits ($212C). Named so the single layer this scene composites is
; legible at the write site. No OBJ bit: nothing draws but the plane.
SHG_TM_BG1 = 1

; --- the palette, and why it is CPU-written rather than a blob ---------------
; BGR555 is (B << 10) | (G << 5) | R, five bits per channel — written as the
; shifts it is, not as the hex it becomes (the room_logic convention; hex is
; for I/O ports here).
;
; EVERY COLOUR KEEPS BLUE = 0. That is the whole reason these five words are
; not shg_rom bytes: shg_grad ADDs a per-line fixed colour to BG1 with
; CGADSUB's halve bit clear, and Mesen2's own blend is
; `b = min((pixelA_b + fixed_b) >> halfShift, 31)` (SnesPpu.cpp:1376) — so
; with the world's blue identically zero and no halving, the RENDERED blue
; channel is EXACTLY the gradient term, whatever the checker is doing in red
; and green. sit_rom's otherwise-identical art ships a palette with blue in
; three of its five words, which would make the same measurement a
; stripe-geometry question.
SHG_G_SHIFT = 5
SHG_B_SHIFT = 10
SHG_COL_BACKDROP   = 0                                  ; black; B=G=R=0
SHG_COL_COOL_DARK  = (15 << SHG_G_SHIFT)                ; G=15
SHG_COL_COOL_LIGHT = (31 << SHG_G_SHIFT)                ; G=31
SHG_COL_WARM_DARK  = (15 << SHG_G_SHIFT) | 31           ; G=15 + R=31
SHG_COL_WARM_LIGHT = (31 << SHG_G_SHIFT) | 31           ; G=31 + R=31

; The map's four solid tiles carry 8bpp pixel values 1..4 (the generator's own
; "tile k is 64 bytes of palette index k+1"), and a Mode 7 pixel value IS an
; absolute CGRAM index — so these four words must sit at 1..4 in this order.
shg_pal_words:
    .word SHG_COL_BACKDROP
    .word SHG_COL_COOL_DARK
    .word SHG_COL_COOL_LIGHT
    .word SHG_COL_WARM_DARK
    .word SHG_COL_WARM_LIGHT
.assert (* - shg_pal_words) = ES_C_SHG_CG_WORDS * 2, error, "shg_floor: the palette table is not the width of its cgram claim"

; =============================================================================
; floor_arm — the whole plane (scene enter).
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; ONE mode-1 DMA: the 32,768 B blob is the interleaved Mode 7 image (tilemap in
; even bytes, 8bpp CHR in odd), and BBAD = VMDATAL under VMAIN = $80 makes the
; alternating $2118/$2119 writes land it word by word. DAS is single-shot and
; armed HERE, for THIS transfer. One whole LoROM window, so the A-bus address
; cannot cross a bank boundary.
; =============================================================================
floor_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^shg_map_bin
    sta a:SHG_REGS + 4              ; A1B = source bank
    lda #ES_D_SHG_UP_DMAP
    sta a:SHG_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_SHG_UP_BBAD
    sta a:SHG_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(shg_map_bin)
    stx a:SHG_REGS + 2              ; A1T
    ldy #ES_R_SHG_MAP_SIZE
    sty a:SHG_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SHG_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: five absolute CGRAM indices, CPU-written -------------
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (why `backdrop` cannot compose here). Black, so the
    ; blue-zero contract holds there too: CGADSUB $01 leaves the backdrop out
    ; of colour math entirely (bit 5 clear — SnesPpu.cpp:924), so anywhere the
    ; plane did not reach would read blue 0 rather than the gradient. With
    ; M7SEL = 0 the map wraps and the plane reaches every pixel, so that case
    ; does not arise here; it is stated because the metric depends on it.
    sep #$20
    .a8
    lda #ES_C_SHG_CG
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda a:shg_pal_words, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #(ES_C_SHG_CG_WORDS * 2)
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns ------------------------------
    ; M7SEL = 0: no screen-over repeat, no flip — the 128x128 map wraps
    ; infinitely, which is what puts camera 2's warm stripe one 256-px period
    ; east of camera 1's cool one, and what keeps the plane under every pixel
    ; as both cameras pan. (BGMODE and TM are the scene's `scene_writes`; see
    ; this feature's toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
