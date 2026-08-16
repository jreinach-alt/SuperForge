; =============================================================================
; brawler_obj.asm — the two knights, staged into the OAM shadow
; =============================================================================
; Arthur out of OBJ name table 0, Mordred out of name table 1. CHR + palettes
; from the brawler_rom blobs; four OAM slots from the `knights` claim (+0
; Arthur, +1 Mordred, +2/+3 permanently parked pads). Entries are re-staged
; into the oam_sprites SHADOW every frame — never into hardware OAM, which the
; engine's declared VBlank GP-DMA owns.
;
; The claim-side argument for all of that is in feature.toml. This file is
; where the second name table becomes an address.

; The enter-time GP-DMA register file, addressed through the channel the
; `br_obj_up` dma_init claim names — a declared resource, not a hard-coded 0.
BR_OBJ_REGS = $4300 + ES_D_BR_OBJ_UP_CH * 16

; =============================================================================
; THE SECOND OBJ NAME TABLE, DERIVED FROM THE TWO EMITTED BASES
; =============================================================================
; OBSEL ($2101) is three fields:
;  bits 0-2 OBJ name base, in 8 K-word steps -> tiles 0..255
;  bits 3-4 the "name select" GAP, in 4 K-word steps -> tiles 256..511 sit
;  at base + (gap + 1) * 0x1000 words
;  bits 5-7 the size PAIR every sprite chooses between
; Verified against the hardware model rather than restated from a doc: Mesen2
; `SnesPpu.cpp:1899-1902` decodes the register exactly that way
; (`OamBaseAddress = (value & 0x07) << 13`,
;  `OamAddressOffset = (((value & 0x18) >> 3) + 1) << 12`) and `:740` adds the
; offset only when the OAM attribute's bit 0 is set (`useSecondTable`, `:701`).
;
; The allocator gives both halves a base and cannot say more: `VramClaim.obj`
; is a bare bool, so nothing in the claim vocabulary says which claim is name
; table 0, and nothing checks that the pair lands a LEGAL distance apart. So
; the relationship is re-derived here from the two emitted symbols and
; ASSERTED. Nothing below narrates an address: the span is a subtraction of two
; allocator outputs, and if a future packing ever separates the halves by an
; illegal distance the build STOPS instead of drawing garbage.
BR_OBJ_SPAN = ES_V_BR_MOR_CHR - ES_V_BR_ART_CHR
BR_OBJ_GAP  = (BR_OBJ_SPAN >> 12) - 1
.assert BR_OBJ_SPAN >= (1 << 12), error, "brawler_obj: Mordred's CHR is not ABOVE Arthur's by at least one name-select step — the allocator packed the two OBJ halves in an order OBSEL cannot express"
.assert BR_OBJ_SPAN = ((BR_OBJ_GAP + 1) << 12), error, "brawler_obj: the two OBJ CHR bases are not a whole number of 4 K-word name-select steps apart"
.assert BR_OBJ_GAP <= 3, error, "brawler_obj: the OBJ name-select gap needs more than the 2 bits OBSEL has (the halves are packed too far apart)"
.assert ES_V_BR_ART_CHR = (ES_V_BR_ART_CHR_OBSEL_BASE << 13), error, "brawler_obj: Arthur's CHR base is not expressible in OBSEL's 8 K-word base field"

; Size pair 3 = small 16x16 / large 32x32. A game choice (the knights are
; 32x32), not layout — so it is stated here beside the emitted base exactly as
; BGMODE's 1 and TM's $15 are stated at their write sites.
BR_OBJ_SIZE_PAIR = 3
BR_OBSEL = (BR_OBJ_SIZE_PAIR << 5) | (BR_OBJ_GAP << 3) | ES_V_BR_ART_CHR_OBSEL_BASE

; =============================================================================

; The two entries, and the hi-table byte they share with the two parked pads.
; The hi table is the last 32 B of the shadow claim (scroller_obj's shape).
BR_OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
BR_OBJ_ARTHUR  = ES_OAM_SHADOW + (ES_O_KNIGHTS + BR_OAM_ARTHUR) * 4
BR_OBJ_MORDRED = ES_OAM_SHADOW + (ES_O_KNIGHTS + BR_OAM_MORDRED) * 4
BR_OBJ_HI      = BR_OBJ_HI_BASE + (ES_O_KNIGHTS / 4)

; THE HI-TABLE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED
; (scroller_obj's argument): the whole-byte rebuild is only correct while the
; four claimed sprites fill exactly one hi byte from its bottom bits.
.assert ES_O_KNIGHTS .MOD 4 = 0, error, "brawler_obj: knights must start a hi-table byte"

; Hi-table bit positions. Each sprite owns two bits: X9 then SIZE.
BR_HI_ART_X9  = 1 << (BR_OAM_ARTHUR * 2)
BR_HI_ART_SZ  = 1 << (BR_OAM_ARTHUR * 2 + 1)
BR_HI_MOR_X9  = 1 << (BR_OAM_MORDRED * 2)
BR_HI_MOR_SZ  = 1 << (BR_OAM_MORDRED * 2 + 1)

; THE PARKED Y IS 224, NOT oam_park_all's 240. OAM Y wraps mod 256, so a
; 32-tall sprite parked at 240 pokes rows 16..31 back onto screen lines 0..15,
; which reads as a band of debris along the top of the picture. 224 is the
; first row at which a 32-tall sprite is entirely below the 224-line display.
; The two PADS keep their size bit clear (16x16) and stay wherever
; oam_park_all left them, which is safe at that size.
BR_PARK_Y = 224
; The condition is that the parked sprite ENDS at or before the wrap, not that
; it reaches it: 224 + 32 = 256 exactly, and 240 + 32 = 272 wraps 16 rows back
; onto scanlines 0..15. (Written the other way round first, where it was true
; of both values and would never have fired.)
.assert BR_PARK_Y + 32 <= 256, error, "a 32-tall sprite parked here wraps onto the visible lines"
.assert BR_PARK_Y >= 224, error, "the parked sprite is inside the 224-line display"

; --- br_obj_up_dma: one VRAM upload. VMADD must already be set by the caller
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, once per
; call. Two knights means two calls, which is exactly the multi-transfer shape
; a once-outside-the-loop DAS write silently breaks.
br_obj_up_dma:
    .a16
    .i16
    stx a:BR_OBJ_REGS + 2           ; A1T
    sty a:BR_OBJ_REGS + 5           ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:BR_OBJ_REGS + 4           ; A1B — the bank byte the caller passed
    lda #ES_D_BR_OBJ_UP_DMAP
    sta a:BR_OBJ_REGS + 0           ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_BR_OBJ_UP_BBAD
    sta a:BR_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_BR_OBJ_UP_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    rts

; --- br_obj_arm: CHR + palettes + OBSEL (scene enter) ----------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
; Clobbers A, X, Y.
;
; No static tile/attr writes here, unlike every prior rail's obj arm: BOTH of
; this rail's OAM bytes 2 and 3 change every frame (the tile is an animation
; step, the attribute carries the facing flip), so there is nothing to hoist.
br_obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- OBJ name table 0: Arthur, tiles 0..255 --------------------------
    lda #ES_V_BR_ART_CHR
    sta a:$2116                     ; VMADD = the first half's claimed base
    ldx #.loword(br_art_chr_bin)
    ldy #ES_R_BR_ART_CHR_SIZE
    lda #^br_art_chr_bin
    jsr br_obj_up_dma
    ; ---- OBJ name table 1: Mordred, tiles 256..447 -----------------------
    ; The SECOND base, from its own claim. This is the whole §4.5b lesson in
    ; one store: two OBJ CHR regions in one scene are fine, and neither one is
    ; expressed as an offset from the other.
    lda #ES_V_BR_MOR_CHR
    sta a:$2116
    ldx #.loword(br_mor_chr_bin)
    ldy #ES_R_BR_MOR_CHR_SIZE
    lda #^br_mor_chr_bin
    jsr br_obj_up_dma
    ; ---- OBJ palette 0 (Arthur) ------------------------------------------
    sep #$20
    .a8
    lda #ES_C_BR_ART_PAL
    sta a:$2121                     ; CGADD = the claim base (CGRAM 128)
    rep #$20
    .a16
    ldx #0
:   lda f:br_art_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BR_ART_PAL_SIZE
    bcc :-
    ; ---- OBJ palette 1 (Mordred) -----------------------------------------
    ; A separate CGADD, from a separate claim, out of a separate blob: the two
    ; knights come from two source PNGs and neither half is written by the
    ; other's upload.
    sep #$20
    .a8
    lda #ES_C_BR_MOR_PAL
    sta a:$2121                     ; CGADD = the claim base (CGRAM 144)
    rep #$20
    .a16
    ldx #0
:   lda f:br_mor_pal_bin, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BR_MOR_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size pair, name-select gap, name base --------------------
    sep #$20
    .a8
    lda #BR_OBSEL
    sta a:$2101
    rep #$20
    .a16
    rts

; --- br_anim_tile: the current step's base-relative tile offset -------------
; In: A16/I16, DB=0. A = anim-table stride index (an anim state), X = step
;  index within that table. Out: A = the tile offset, high byte cleared.
; Clobbers A, X, and US_TILE — which is the caller's own destination for the
; result, so the scratch costs nothing. It deliberately does NOT borrow
; ES_BR_HI: that word is the draw's OR accumulator and is live ACROSS the
; second call.
;
; Naming each animation table at ASSEMBLE time is the obvious shape and it
; forces a branch chain per call site. Here the five tables are one blob on a
; fixed stride and the state word indexes it.
br_anim_tile:
    .a16
    .i16
    .assert BR_ANIM_STRIDE = 8, error, "br_anim_tile's shift chain assumes an 8-byte stride"
    asl a
    asl a
    asl a                           ; state * BR_ANIM_STRIDE
    sta z:US_TILE                   ; the table's byte offset into the blob
    txa
    clc
    adc z:US_TILE                   ; + the step index
    tax
    lda f:br_anim_bin, x            ; byte entry (+1 stray high byte)
    and #$00FF
    rts

; --- br_obj_draw: stage both knights into the OAM shadow --------------------
; In/out: A16/I16, DB=0. Called from the scene's tick EVERY frame (and once
; from enter, so frame 0 commits real entries). Clobbers A, X, Y.
;
; Both knights are re-staged EVERY frame rather than written once at enter: a
; write-once sprite would pass "the sprite is where the state says" for the
; wrong reason and leave the staging path untested for the whole
; run (scroller_obj's argument).
;
; THE HI BYTE IS REBUILT FROM SCRATCH each frame: X9 for each knight is DERIVED
; from bit 8 of its x, and the SIZE bits are set because both actors are the
; large half of the OBSEL pair — this is the first rail in the tree whose hi
; table carries a non-zero size bit, so it is written rather than left over
; from oam_park_all's clear. The pads' four bits stay 0. ES_BR_HI is the OR
; accumulator (write-before-read, this call).
br_obj_draw:
    .a16
    .i16
    ; ---- Arthur (slot +0): always live -----------------------------------
    lda z:US_ASTATE
    ldx z:US_AFRAME
    jsr br_anim_tile
    sta z:US_TILE
    lda #BR_ATTR_ARTHUR
    ldx z:US_FACING
    beq :+
    ora #BR_ATTR_HFLIP              ; facing left: flip the right-facing art
:   .a16
    .i16
    sta z:US_ATTR
    lda z:US_PX
    sep #$20
    .a8
    sta a:BR_OBJ_ARTHUR + 0         ; X low 8
    rep #$20
    .a16
    lda z:US_PY
    sep #$20
    .a8
    sta a:BR_OBJ_ARTHUR + 1         ; Y
    lda z:US_TILE
    sta a:BR_OBJ_ARTHUR + 2         ; tile low 8 (name table 0: the offset IS
                                    ;  the tile number)
    lda z:US_ATTR
    sta a:BR_OBJ_ARTHUR + 3         ; attr: priority, palette 0, name bit 0
    rep #$20
    .a16
    lda z:US_PX
    xba                             ; bit 8 of X -> bit 0
    and #1
    .assert BR_HI_ART_X9 = 1, error, "Arthur's X9 is no longer hi-byte bit 0 — the mask below has to shift"
    ora #BR_HI_ART_SZ               ; ...plus his LARGE size bit
    sta z:ES_BR_HI
    ; ---- Mordred (slot +1): live at (ex, ey) or parked while respawning ---
    lda z:US_ERESP
    beq @mor_live
    ; Respawning. The entry stays a 32x32 knight, parked below the display —
    ; its X byte is stale by design, so its X9 must NOT leak a ninth bit.
    sep #$20
    .a8
    lda #BR_PARK_Y
    sta a:BR_OBJ_MORDRED + 1
    rep #$20
    .a16
    lda #BR_HI_MOR_SZ
    ora z:ES_BR_HI
    sta z:ES_BR_HI
    bra @mor_done
@mor_live:
    .a16
    .i16
    ; Mordred has no attack table: he runs while he is closing and idles when
    ; he is stunned or already on top of the player. The choice is made ONCE
    ; per frame, in enemy_step, and stored — so the table his clock advanced
    ; and the table this draw reads cannot be different tables.
    lda z:US_ESTATE
    ldx z:US_EFRAME
    jsr br_anim_tile
    sta z:US_TILE
    lda #BR_ATTR_MORDRED
    ldx z:US_EFACE
    beq :+
    ora #BR_ATTR_HFLIP
:   .a16
    .i16
    sta z:US_ATTR
    lda z:US_EX
    sep #$20
    .a8
    sta a:BR_OBJ_MORDRED + 0
    rep #$20
    .a16
    lda z:US_EY
    sep #$20
    .a8
    sta a:BR_OBJ_MORDRED + 1
    lda z:US_TILE
    sta a:BR_OBJ_MORDRED + 2        ; tile LOW 8 BITS. Every Mordred tile is
                                    ;  >= 256; the 9th bit rides in the attr
    lda z:US_ATTR
    sta a:BR_OBJ_MORDRED + 3        ; attr: priority, palette 1, NAME BIT SET
    rep #$20
    .a16
    lda z:US_EX
    xba
    and #1
    .assert BR_HI_MOR_X9 = (1 << 2), error, "Mordred's X9 is no longer hi-byte bit 2 — the shift below has to change"
    asl a
    asl a                           ; -> hi-byte bit 2
    ora #BR_HI_MOR_SZ
    ora z:ES_BR_HI
    sta z:ES_BR_HI
@mor_done:
    .a16
    .i16
    ; ---- the whole hi byte: two derived X9 bits, two size bits, pads 0 ----
    lda z:ES_BR_HI
    sep #$20
    .a8
    sta a:BR_OBJ_HI
    rep #$20
    .a16
    rts
