; =============================================================================
; m7_affine.asm — the static Mode 7 affine matrix: LUT lookup, shadow, commit
; =============================================================================
; Three routines and one sixteen-byte DP shadow (ES_M7AFF):
;
;  m7a_set_heading main thread heading byte -> the four matrix words
;  m7a_set_center main thread world pivot -> M7X/M7Y + the screen origin
;  m7a_nmi_commit NMI hook the shadow -> the eight hardware ports
;
; The split is the point. Nothing here touches a PPU port outside the NMI hook,
; so the matrix cannot tear: all eight registers are latched together during
; VBlank, before scanline 0 of the frame they describe. Writing M7A-M7D
; straight from the main loop is the tempting shortcut; feature.toml records
; why it is a latent tearing bug rather than a saving.
;
; The LUT blob `m7_lut_bin` is the game's .incbin claim site (main.asm), the
; same shape every other rom-claim consumer uses: the feature names the label,
; the game backs it, and `make rom-unbacked` proves the bytes are really there.

; --- m7a_set_heading: heading byte -> the four matrix words -----------------
; In: A16/I16, DB=0. A = heading, 0..255 (the high byte is ignored, so a
;  caller may pass an unmasked 16-bit angle accumulator straight in).
; Out: A16/I16. ES_M7AFF+0..+7 = M7A, M7B, M7C, M7D for that heading. Clobbers:
; A, X.
;
; Entry stride is 8 bytes (four signed 1.7.8 words, order A,B,C,D — see
; tools/gen_m7_affine_lut.py). `f:` long-indexed reads, so the table is
; reachable from whichever bank the allocator packed it into without the caller
; setting DB.
m7a_set_heading:
    .a16
    .i16
    and #255                        ; one full turn per 256 headings
    asl
    asl
    asl                             ; * 8 bytes per entry
    tax
    lda f:m7_lut_bin + 0, x
    sta z:ES_M7AFF + 0              ; M7A =  cos(t)
    lda f:m7_lut_bin + 2, x
    sta z:ES_M7AFF + 2              ; M7B =  sin(t)
    lda f:m7_lut_bin + 4, x
    sta z:ES_M7AFF + 4              ; M7C = -sin(t)
    lda f:m7_lut_bin + 6, x
    sta z:ES_M7AFF + 6              ; M7D =  cos(t)
    rts

; --- m7a_set_center: world pivot -> M7X/M7Y + BG1HOFS/BG1VOFS --------------
; In: A16/I16, DB=0. X = world x, Y = world y (pixels). Out: A16/I16.
; ES_M7AFF+8..+15 set. Clobbers: A.
;
; THE TWO HALVES OF "PUT THE PIVOT AT SCREEN CENTRE". The PPU computes, per
; screen pixel (sx,sy):
;
;  vram_x = A*(sx + HOFS - M7X) + B*(sy + VOFS - M7Y) + M7X
;  vram_y = C*(sx + HOFS - M7X) + D*(sy + VOFS - M7Y) + M7Y
;
; so (M7X,M7Y) is the point the rotation turns ABOUT, and (HOFS,VOFS) is what
; slides the world under the screen. Setting the pivot to the world position
; and the origin to that position minus half a screen makes the bracket vanish
; at screen centre — the pivot lands on (128,112) and stays there whatever the
; heading. That is the whole "the camera is centred on you, the floor spins
; around you" effect, and it is two subtractions.
;
; 256x224 is the NTSC active area, so half is (128,112).
m7a_set_center:
    .a16
    .i16
    stx z:ES_M7AFF + 8              ; M7X = pivot x (world)
    sty z:ES_M7AFF + 10             ; M7Y = pivot y (world)
    txa
    sec
    sbc #128                        ; half of 256 active pixels
    sta z:ES_M7AFF + 12             ; BG1HOFS (= M7HOFS)
    tya
    sec
    sbc #112                        ; half of 224 active scanlines
    sta z:ES_M7AFF + 14             ; BG1VOFS (= M7VOFS)
    rts

; --- m7a_nmi_commit: the shadow -> the eight ports -------------------------
; WIDTH-RISK: entry = A8/I16, DB=0 — the sm_nmi_hook contract. The caller is in
; ANOTHER FILE (the game's main.asm), which make width-check cannot see in
; either direction (CLAUDE.md rule 6, "the single-file limit remains"), so this
; contract is proven only on the emulator and this marker is what carries it.
; Exits A8/I16, DB unchanged. Clobbers A only.
;
; ALL EIGHT PORTS ARE WRITE-TWICE, LOW BYTE FIRST. $211B-$211E (M7A-M7D) latch
; a signed 1.7.8 word; $211F/$2120 (M7X/M7Y) latch a 13-bit signed world
; coordinate; $210D/$210E (M7HOFS/M7VOFS) latch a 13-bit signed offset. Each is
; a single 8-bit port with a one-byte-deep shift latch: the FIRST write
; supplies the low half and the SECOND the high half. Get the order backwards
; and the matrix is transposed garbage that still looks like "a rotating floor"
; at some headings, which is exactly the kind of bug that ships.
;
; The shadow is laid out little-endian in that same order, so each register is
; two consecutive loads from consecutive DP bytes — +N is the low half, +N+1
; the high half.
m7a_nmi_commit:
    .a8
    .i16
    lda z:ES_M7AFF + 0
    sta a:$211B
    lda z:ES_M7AFF + 1
    sta a:$211B                     ; M7A, low then high
    lda z:ES_M7AFF + 2
    sta a:$211C
    lda z:ES_M7AFF + 3
    sta a:$211C                     ; M7B
    lda z:ES_M7AFF + 4
    sta a:$211D
    lda z:ES_M7AFF + 5
    sta a:$211D                     ; M7C
    lda z:ES_M7AFF + 6
    sta a:$211E
    lda z:ES_M7AFF + 7
    sta a:$211E                     ; M7D
    lda z:ES_M7AFF + 8
    sta a:$211F
    lda z:ES_M7AFF + 9
    sta a:$211F                     ; M7X, the affine pivot
    lda z:ES_M7AFF + 10
    sta a:$2120
    lda z:ES_M7AFF + 11
    sta a:$2120                     ; M7Y
    lda z:ES_M7AFF + 12
    sta a:$210D
    lda z:ES_M7AFF + 13
    sta a:$210D                     ; M7HOFS (the BG1HOFS port)
    lda z:ES_M7AFF + 14
    sta a:$210E
    lda z:ES_M7AFF + 15
    sta a:$210E                     ; M7VOFS (the BG1VOFS port)
    rts
