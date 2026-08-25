; =============================================================================
; sh2_obj.asm — the cast: world-fixed markers on two rotating floors
; =============================================================================
; Everything the PPU sees. `m7_persp_project` answers "where on screen, at what
; size, or culled" for one marker against one band; this file owns the OBJ
; character block, OBSEL, the two palettes, the OAM slot range, and the
; per-band loop that turns those answers into shadow entries. That split is the
; tree's established one — `m7_project` and `m7dg_obj` divide the same job the
; same way.
;
; EVERY MARKER IS PROJECTED TWICE, ONCE PER BAND. The bands are two independent
; cameras over ONE world, so a marker inside both views is drawn twice: at
; different rows, at different sizes, at different screen x. Nothing is shared
; between the two passes but the LUTs — the coefficients, the camera position,
; the band top and the OAM attribute are all re-staged.
;
; THE PALETTE IS THE BAND'S SIGNATURE. Band 1's markers are WHITE and band 2's
; are MAGENTA, so which camera produced a sprite is legible in the PICTURE
; rather than only in the projector's bookkeeping. That is what lets the seam
; claim be tested as pixels — no white below the seam, no magenta above it —
; and `-D SH2_SP_CULLOFF` makes exactly that false.
;
; SLOT COMPACTION, AND ITS SHRINK PATH. Visible markers take CONSECUTIVE slots
; from the claim's base; a culled marker costs no store at all (mpp_project
; returns carry clear and this file writes nothing). The tail is then parked
; only as far as the PREVIOUS frame's watermark, so a frame showing fewer
; markers leaves no ghosts and a frame showing the same number pays nothing.
; The shrink path is the half an only-ever-growing cast ships broken, which is
; why the marker world is gated on the visible count RISING AND FALLING
; (tools/gen_split_h_2p_assets.py, swarm_world).
;
; WHERE THE WORK RUNS: the scene TICK, during active display, LAST — after
; sh2_advance has stepped the cameras and after sh2_swarm has moved the
; entities, so the projection reads the state the NEXT VBlank will stamp into
; the pose pointers and the origin tables. One consistent snapshot per frame,
; with the sprites and the floor always the same frame's.
;
; NOT THE VBLANK HOOK, and that is measured rather than preferred: with the
; cast projected from the hook, sm_nmi_core's post-hook MVN of the 128-byte
; channel shadow lands during ACTIVE DISPLAY and rewrites every channel's
; running HDMA state mid-frame — the floor speckles from that row down while
; VRAM, the index tables and the shadow all read back correct. Only four
; markers fitted.

; The enter-time GP-DMA register file, addressed through the channel the sho_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SHO_REGS = $4300 + ES_D_SHO_UP_CH * 16

; --- the OBJ configuration ---------------------------------------------------
; OBSEL's size pair 3 is 16x16 / 32x32, which is the ladder the tier table
; picks between: tiers 0..2 are the small box, tiers 3..4 the large one. The
; name base is the allocator's — sh2_floor pins the Mode 7 region at words
; $0000-$3FFF and every OBJ CHR claim is floored above it, so the base is a
; fact of the allocation and ES_V_OBJ_CHR_OBSEL_BASE is the only place it is
; written.
SHO_SIZE_PAIR = 3 << 5

; The scene's TM gains OBJ. Sh2_floor names the BG1 bit and says there is no
; OBJ bit "on purpose: nothing draws"; that is true until something draws, and
; it does here, so the bit is named HERE — by the feature that composites
; the layer — and the scene ORs the two together.
SHO_TM_OBJ = 1 << 4

; The two marker colours, BGR555. White and magenta are both outside the
; floor's colour space (its cool pair carries red 0, its warm pair red 31 and
; green at most 17), so a marker pixel is never confusable with a floor pixel —
; which is what the framebuffer assertions stand on.
SHO_COL_B1 = $7FFF                      ; white  — band 1
SHO_COL_B2 = $7C1F                      ; magenta — band 2

; OAM word 1 = attribute << 8 | tile. Bits 5:4 of the attribute are priority (3
; = in front of the plane) and bits 3:1 are the OBJ palette.
SHO_PRIO3   = 3 << 12
SHO_ATTR_B1 = SHO_PRIO3                 ; OBJ palette 0, at CGRAM 128
SHO_ATTR_B2 = SHO_PRIO3 | (1 << 9)      ; OBJ palette 1, at CGRAM 144

SHO_PARK_Y = $F000                      ; y = $F0, x = 0 — the park slot

; --- the slot range, from the claim -----------------------------------------
; Byte offsets into the shadow's low table, because the stores are indexed and
; `ldx` has no long mode: the cursor is the useful form, not a slot index.
SHO_SLOT0 = ES_O_SHO_CAST * 4
SHO_SLOTN = (ES_O_SHO_CAST + ES_O_SHO_CAST_SPRITES) * 4

; The hi table sits after the 128 four-byte entries; each of its bytes covers
; FOUR sprites (bit 0 = X9, bit 1 = size). Our range is a whole number of those
; bytes by declaration, which is what lets obj_project REBUILD them rather than
; read-modify-write against bits somebody else owns.
SHO_HI_OFF = ES_OAM_SHADOW_SIZE - (1 << 5)
SHO_HI_LO  = ES_O_SHO_CAST / 4
SHO_HI_HI  = (ES_O_SHO_CAST + ES_O_SHO_CAST_SPRITES) / 4
.assert ES_O_SHO_CAST_SPRITES = SHO_HI_HI * 4 - SHO_HI_LO * 4, error, "sh2_obj: the OAM claim is not a whole number of hi-table bytes — the X9/size pairs could only be patched, not rebuilt"
.assert ES_C_BAND2_PAL = ES_C_BAND1_PAL + ES_C_BAND1_PAL_WORDS, error, "sh2_obj: the two OBJ palettes are not adjacent — obj_arm clears them in one CGADD walk"
.assert ES_V_OBJ_CHR_WORDS * 2 = ES_R_SH2_SP_CHR_SIZE, error, "sh2_obj: the obj_chr VRAM claim does not hold the whole character blob"

; --- the cast: sh2_swarm's table, and its LIVE count -------------------------
; The cast is not a world-FIXED marker blob in ROM: this draws whatever
; `sh2_swarm` currently holds — two player markers that track the two cameras
; and twenty-two AI followers — so the table is WRAM and its length is a WRAM
; word, not a constant. That is also what lets the cadence sweep poke the
; count between frames: this loop asks every frame.
;
; NOTHING ELSE ABOUT THE DRAW CHANGED. A record's first two words are (x, y) in
; exactly the layout the marker blob had, which is why the entity stride is the
; only edit inside obj_band.
.assert SWM_E::wx = 0 && SWM_E::wy = 2, error, "sh2_obj: an entity record no longer opens with (x, y) — obj_band reads them positionally"

; --- the bookkeeping, inside the 18-byte dp claim ---------------------------
SHO_SLOT  = ES_SHO + 0                  ; the compaction cursor (byte offset)
SHO_WATER = ES_SHO + 2                  ; the PREVIOUS frame's final cursor
SHO_MENT  = ES_SHO + 4                  ; this marker's byte offset in the blob
SHO_MCNT  = ES_SHO + 6                  ; markers left in this band's pass
SHO_HALF  = ES_SHO + 8                  ; the tier's half box size (8 / 16)
SHO_TILE  = ES_SHO + 10                 ; the tier's CHR name
SHO_ATTR  = ES_SHO + 12                 ; the band's OAM attribute word
SHO_BITS  = ES_SHO + 14                 ; the 9-bit OAM x, then the hi-table pair
SHO_W0    = ES_SHO + 16                 ; OAM word 0 under construction

; =============================================================================
; obj_arm — the character block, OBSEL, the palettes, the first snapshot
; =============================================================================
; CONTRACT sh2_obj::obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the sheets, the palettes, OBSEL and the parked cast
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage. The caller seeds
;             sh2_cam's positions and headings FIRST — this routine's
;             closing projection reads them
;   tail:     rts
;
; WIDTH-RISK: A16/I16 in and out; every 8-bit window is a byte-wide PPU or DMA
; register store inside a balanced sep/rep, and the index registers stay 16-bit
; throughout (the CGRAM clear loop counts in X).
obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_arm"
    ; ---- the character block: one DMA, 2,048 B ----------------------------
    ; VMAIN $80 advances one word after the HIGH byte, which is what makes the
    ; mode-1 pair land as a word and step. DAS is single-shot — consumed by the
    ; transfer — so it is armed HERE, for THIS transfer; there is one, so there
    ; is one arming site.
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN
    lda #^sh2_sp_chr_bin
    sta a:SHO_REGS + 4              ; A1B
    lda #ES_D_SHO_UP_DMAP
    sta a:SHO_REGS + 0              ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_SHO_UP_BBAD
    sta a:SHO_REGS + 1              ; BBAD: VMDATAL, so B+1 = VMDATAH
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the claim's base word
    ldx #.loword(sh2_sp_chr_bin)
    stx a:SHO_REGS + 2              ; A1T
    ldy #ES_R_SH2_SP_CHR_SIZE
    sty a:SHO_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SHO_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)

    ; ---- OBSEL: the size pair the ladder steps between, and the name base --
    lda #(SHO_SIZE_PAIR | ES_V_OBJ_CHR_OBSEL_BASE)
    sta a:$2101

    ; ---- both OBJ palettes, WHOLE ------------------------------------------
    ; Sixteen words each, and every one is written even though the tokens draw
    ; colour index 1 only. That is rule 5, not tidiness: CGRAM powers on random
    ; and a claim this feature owns but never writes is a region whose contents
    ; nobody chose. CGADD auto-increments through both palettes in one walk
    ; (they are adjacent by the .assert above), so the clear is one loop.
    lda #ES_C_BAND1_PAL
    sta a:$2121                     ; CGADD
    ldx #0
:   stz a:$2122                     ; low byte
    stz a:$2122                     ; high byte
    inx
    cpx #(ES_C_BAND1_PAL_WORDS + ES_C_BAND2_PAL_WORDS)
    bcc :-
    ; ...then the one drawn entry of each.
    lda #(ES_C_BAND1_PAL + 1)
    sta a:$2121
    lda #<SHO_COL_B1
    sta a:$2122
    lda #>SHO_COL_B1
    sta a:$2122
    lda #(ES_C_BAND2_PAL + 1)
    sta a:$2121
    lda #<SHO_COL_B2
    sta a:$2122
    lda #>SHO_COL_B2
    sta a:$2122
    rep #$20
    .a16

    ; ---- the watermark, written before it is read -------------------------
    ; The one byte of this feature's state that must survive between frames.
    ; Power-on DP is random and the dp claim declares no zero-fill, so this
    ; store IS the write-before-read contract: a garbage watermark would park a
    ; run of slots the cast never owned on the very first frame.
    stz z:SHO_WATER
    jsr obj_project                 ; frame 1 shows a consistent snapshot
    rts

; =============================================================================
; obj_project — both bands into the OAM shadow, with slot compaction
; =============================================================================
; CONTRACT obj_project
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both bands' casts projected into the OAM shadow
;   clobbers: A, X, Y, N, Z, C, and both scratch blocks
;   assumes:  it runs LAST in the scene tick, after sh2_advance has
;             stepped the cameras and after the swarm has moved the
;             followers, so what it projects is this frame's state
;   tail:     rts
;
; Called LAST in the scene tick, after sh2_advance and the swarm, so the cast
; is projected from exactly the state the next VBlank will stamp into the HDMA
; tables. Any other order shows one frame's cast against another frame's floor.
obj_project:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_project"
    ; ---- the hi table for OUR slots, rebuilt from zero ---------------------
    ; X9 = 0, size = small. The store path ORs each visible marker's two bits
    ; back in. NEVER carried across frames: a stale X9 is a sprite 256 px from
    ; where it belongs, and on this rail that is not hypothetical — a marker
    ; straddling the left edge of a view has a negative screen x every time.
    ldx #SHO_HI_LO
    lda #0
:   sta f:ES_OAM_SHADOW_LONG + SHO_HI_OFF, x
    inx
    inx
    cpx #SHO_HI_HI
    bcc :-
    lda #SHO_SLOT0
    sta z:SHO_SLOT                  ; the compaction cursor restarts

    ; ---- band 1: camera 1, screen rows 0..111, white ----------------------
    lda z:SH2_POS1X
    sta z:MPP_PX
    lda z:SH2_POS1Y
    sta z:MPP_PY
    lda #0
    sta z:MPP_TOP
    lda #SHO_ATTR_B1
    sta z:SHO_ATTR
    lda z:SH2_H1
    jsr mpp_band_coeffs
    jsr obj_band

    ; ---- band 2: camera 2, screen rows 112..223, magenta ------------------
    lda z:SH2_POS2X
    sta z:MPP_PX
    lda z:SH2_POS2Y
    sta z:MPP_PY
    lda #SH2_SEAM
    sta z:MPP_TOP
    lda #SHO_ATTR_B2
    sta z:SHO_ATTR
    lda z:SH2_H2
    jsr mpp_band_coeffs
    jsr obj_band

    ; ---- the tail park: [slot, water) was visible LAST frame ---------------
    ; Exactly the slots that have gone away, and nothing beyond them. A full
    ; park of the claim every frame would work and would cost the same whether
    ; anything vanished or not; this costs one store per vanished sprite, which
    ; on a rail whose visible count breathes is most frames' whole cost.
    ldx z:SHO_SLOT
@park:
    .a16
    .i16
    cpx z:SHO_WATER
    bcs @parked
    lda #SHO_PARK_Y
    sta f:ES_OAM_SHADOW_LONG, x
    inx
    inx
    inx
    inx
    bra @park
@parked:
    .a16
    .i16
    lda z:SHO_SLOT
    sta z:SHO_WATER
    rts

; =============================================================================
; obj_band — every marker against the staged band
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y and both scratch blocks.
;
; The whole cast, every frame, for each band — deliberately the worst case. A
; visibility cache would make the cost depend on what the camera happened to be
; looking at last frame, and the rail should be judged on the work it actually
; does.
obj_band:
    .a16
    .i16
    lda f:SWM_N                     ; the LIVE count, asked every frame
    beq @none
    sta z:SHO_MCNT
    lda #0
    sta z:SHO_MENT
@loop:
    .a16
    .i16
    ldx z:SHO_MENT
    lda f:ES_SWM_ENTS_LONG + SWM_E::wx, x
    sta z:MPP_WX
    lda f:ES_SWM_ENTS_LONG + SWM_E::wy, x
    sta z:MPP_WY
    jsr mpp_project
    bcc @next                       ; culled: NOT ONE STORE — the compaction
    jsr obj_put                     ;   cursor does not move either
@next:
    .a16
    .i16
    lda z:SHO_MENT
    clc
    adc #.sizeof(SWM_E)
    sta z:SHO_MENT
    dec z:SHO_MCNT
    bne @loop
@none:
    .a16
    .i16
    rts

; =============================================================================
; obj_put — one visible marker into the next free shadow slot
; =============================================================================
; In/out: A16/I16, DB=0. Mpp_project has just returned carry set, so
; MPP_SX/MPP_SY/MPP_TIER are this marker's answer. Clobbers A, X, Y.
;
; WIDTH-RISK: A16/I16 in and out. The ONE 8-bit window is the hi-table
; read-modify-write at the end, inside a balanced sep/rep; X is 16-bit across
; it because it carries the hi-table byte index.
obj_put:
    .a16
    .i16
    lda z:SHO_SLOT
    cmp #SHO_SLOTN
    bcc @room
    rts                             ; the claim is full: drop, never overrun it
@room:
    .a16
    .i16
    ; ---- the tier's geometry ----------------------------------------------
    ldx z:MPP_TIER
    lda a:SHO_HALF_TAB, x
    and #$00FF
    sta z:SHO_HALF                  ; 8 for a 16x16 token, 16 for a 32x32
    lda a:SHO_TILE_TAB, x
    and #$00FF
    sta z:SHO_TILE

    ; ---- OAM word 0 = (y byte << 8) | x low byte --------------------------
    ; The projection answers where the token's CENTRE goes; OAM takes its
    ; top-left, so both axes lose the half box. The x is NINE bits (the ninth
    ; goes to the hi table below) because the hardware has a sign bit precisely
    ; so a sprite can hang off the LEFT edge.
    lda z:MPP_SX
    sec
    sbc z:SHO_HALF
    and #((1 << 9) - 1)
    sta z:SHO_BITS                  ; the 9-bit OAM x, kept for the hi table
    and #$00FF
    sta z:SHO_W0                    ; ...its low byte, which is word 0's
    lda z:MPP_SY
    sec
    sbc z:SHO_HALF
    and #$00FF                      ; OAM y is EIGHT bits, unsigned
    xba                             ; y << 8 (the low half was masked to zero)
    ora z:SHO_W0
    ldx z:SHO_SLOT
    sta f:ES_OAM_SHADOW_LONG, x
    lda z:SHO_TILE
    ora z:SHO_ATTR
    sta f:ES_OAM_SHADOW_LONG + 2, x ; word 1 = attribute << 8 | tile
    txa
    clc
    adc #4
    sta z:SHO_SLOT                  ; the cursor advances only for a VISIBLE one

    ; ---- the hi table: X9 and the size bit --------------------------------
    lda z:SHO_BITS
    xba
    and #(1 << 0)                   ; x's ninth bit -> the pair's bit 0
    sta z:SHO_W0
    lda z:SHO_HALF                  ; 16 -> bit 1 after >>3; 8 -> nothing
    lsr a
    lsr a
    lsr a
    and #(1 << 1)
    ora z:SHO_W0
    beq @done                       ; both clear: the rebuilt zero already says so
    sta z:SHO_W0                    ; the pair's two bits, unpositioned
    txa                             ; X still holds this marker's byte offset
    lsr a
    lsr a                           ; -> the OAM entry index
    sta z:SHO_BITS
    and #((1 << 2) - 1)             ; which of the byte's four sprites
    asl a
    asl a
    ora z:SHO_W0
    tax
    lda a:SHO_HI_POS, x             ; the pair, shifted into its position
    and #$00FF
    sta z:SHO_W0
    lda z:SHO_BITS
    lsr a
    lsr a                           ; -> the hi-table byte index
    tax
    sep #$20
    .a8
    lda z:SHO_W0
    ora f:ES_OAM_SHADOW_LONG + SHO_HI_OFF, x
    sta f:ES_OAM_SHADOW_LONG + SHO_HI_OFF, x
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

; =============================================================================
; the ladder's two small tables, and the hi-table position table
; =============================================================================
; Data, after the last rts so nothing falls into it. Read with `a:` addressing
; because they are in the CODE bank and the callers run with DB = 0.
;
; The CHR names are 0/2/4 for the three 16x16 tokens and 8/12 for the two 32x32
; ones: a 16x16 OBJ reads {N, N+1, N+16, N+17} and a 32x32 reads the whole 4x4
; block from N, so the spacing is the hardware's name grid, not a choice.
SHO_TILE_TAB: .byte 0, 2, 4, 8, 12
SHO_HALF_TAB: .byte 8, 8, 8, 16, 16

; entry (pair * 4 + bits) = bits << (pair * 2). A table rather than a shift
; loop because the shift count is data, and four positions is sixteen bytes.
SHO_HI_POS:   .byte $00, $01, $02, $03
              .byte $00, $04, $08, $0C
              .byte $00, $10, $20, $30
              .byte $00, $40, $80, $C0
