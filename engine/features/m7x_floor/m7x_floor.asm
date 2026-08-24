; =============================================================================
; m7x_floor.asm — the overworld's Mode 7 plane: one DMA, twelve colours, one
; reg
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM — what
; changes the plane after this is mode7_stream, and that feature holds its own
; claims.
;
; The blob labels (`m7x_seed_bin`, `m7x_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the m7x_up
; dma_init claim names — a declared resource, not a hard-coded 0.
M7X_REGS = $4300 + ES_D_M7X_UP_CH * 16

; --- floor_arm: the whole plane (scene enter) ------------------------------
; CONTRACT m7x_floor::floor_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the 32 KB WRAPPED seed uploaded by ONE DMA — built with
;             mode7_stream's own torus placement, so a re-written row
;             cannot tear — plus the Mode-7 registers and the palette
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. The upload is ONE 32,768-byte DMA: mode 1 writes
;             $2118/$2119 alternately, which is exactly the blob's
;             tilemap/CHR interleave, and VMAIN $80 steps the word address
;             after the HIGH byte. DAS is single-shot and is armed here
;             for THIS transfer; 32,768 B is one whole LoROM window, so it
;             cannot cross a bank
;   tail:     rts
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_mode7_explore_assets.py emits the seed already in that layout. DMA
; mode 1 writes B, B+1, B, B+1 ... — with BBAD = VMDATAL that is $2118, $2119,
; $2118, $2119, which is exactly the interleave. So the whole window is one
; transfer of 32,768 bytes with no unpacking pass.
;
; WHAT THE SEED IS, and why it is not a sequential picture. The Mode 7 tilemap
; is a 128x128 TORUS, and mode7_stream writes each leading-edge row and column
; into the slot its WORLD coordinate wraps to: world tile (wx,wy) lives at word
; (wy & 127)*128 + (wx & 127). The generator builds the seed with that same
; wrapped placement. A sequentially-built seed would look right on frame 0 and
; tear the first time a row was re-written — which is one step.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is written,
; by one word. That is what makes the alternating byte pair land as one word
; and step to the next — with the default $00 it would advance after the LOW
; byte and every high byte would overwrite the wrong word.
;
; DAS is single-shot (consumed by the transfer), so it is armed HERE, for THIS
; transfer. There is one transfer and therefore one arming site; the rule bites
; when a loop fires several and only the first moves bytes.
;
; The seed is 32,768 B = one whole LoROM window, so this cannot cross a bank
; boundary — a DMA's A-bus address wraps within its bank rather than carrying.
floor_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "floor_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^m7x_seed_bin
    sta a:M7X_REGS + 4              ; A1B = source bank
    lda #ES_D_M7X_UP_DMAP
    sta a:M7X_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_M7X_UP_BBAD
    sta a:M7X_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(m7x_seed_bin)
    stx a:M7X_REGS + 2              ; A1T
    ldy #ES_R_M7X_SEED_SIZE
    sty a:M7X_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_M7X_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: twelve absolute CGRAM indices, CPU-written ----------
    ; Twelve words is twenty-four stores; a DMA would cost more to set up than
    ; to run. CGADD auto-increments, so this build takes low byte then high
    ; byte per word and walks itself.
    ;
    ; INDEX 0 IS REAL GROUND, not a spare. A Mode 7 8bpp pixel value is an
    ; ABSOLUTE CGRAM index, so word 0 is both palette entry 0 and the backdrop
    ; slot. This is a flat top-down view with no horizon, so nothing ever shows
    ; through the backdrop and putting opaque grass there is the right answer
    ; rather than a compromise — which is also why no scene of this rail may
    ; compose `backdrop`.
    sep #$20
    .a8
    lda #ES_C_M7X_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:m7x_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7X_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: WRAP (the 128x128 map repeats past its edge), no flip, and NOT
    ; the "screen over" fill mode. Wrap is what the streamer's whole design
    ; assumes — every dest write is `& 127` on both axes — so the register and
    ; the kernel agree by construction. The game keeps the CAMERA clamped to
    ; [64, 447] so the visible window is always authored world rather than a
    ; repeat of the same 128 tiles; that clamp is the game's, this bit is the
    ; hardware's. (BGMODE and TM are the scene's `scene_writes`; see this
    ; feature's feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts

; --- floor_restage: everything floor_arm did EXCEPT the 32 KB upload --------
; CONTRACT floor_restage
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      everything floor_arm establishes EXCEPT the 32 KB upload:
;             CGRAM 0..11 and M7SEL, which are the only two things the
;             town visit destroys
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked, on the return from the
;             interior. Re-uploading the seed here would UNDO the feature
;             this exists for — the seed is centred on spawn, so it would
;             put the plane back at the start of the world; the prose
;             above works through what survives and why
;   tail:     rts
;
; WHAT THE TOWN VISIT ACTUALLY DESTROYS, and it is exactly two things.
;
; The Mode 7 IMAGE survives: the interior's CHR and tilemap are pinned into
; UPPER VRAM (words $5000 / $5800), clear of this region at $0000-$3FFF, so the
; window comes back byte-identical to how it was left and there is nothing to
; re-stream. That is the whole reason the town is a mosaic swap rather than a
; scene reload, and re-uploading the seed here would undo it — the seed is
; centred on SPAWN, so it would put the plane back at the start of the world.
;
; What does NOT survive is CGRAM 0..11, which the interior's sixteen-word
; palette lands on top of, and M7SEL, which is written by nothing else in the
; ROM but is a register the return must not assume. Both are re-established
; here, in the same order and by the same code paths floor_arm uses.
;
; So this is not "floor_arm minus a step" as an optimisation; the omitted step
; is the one that would break the feature the return exists to deliver.
floor_restage:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "floor_restage"
    sep #$20
    .a8
    lda #ES_C_M7X_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:m7x_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7X_PAL_SIZE
    bcc :-
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL = 0: WRAP, which the streamer assumes
    rep #$20
    .a16
    rts
