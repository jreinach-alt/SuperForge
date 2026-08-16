; =============================================================================
; m7x_obj.asm — the avatar: one sprite, pinned, three authored facings
; =============================================================================
; One OAM entry written into the oam_sprites SHADOW; hardware OAM belongs to
; that feature's declared VBlank GP-DMA.
;
; SHE NEVER PROJECTS, AND THAT IS THE CAMERA MODEL, not a shortcut.
; M7a_set_center pins the affine pivot — the camera's world position — at
; screen centre, and on this rail the avatar IS the camera. Her screen position
; is therefore a CONSTANT by construction, and deriving it would be deriving
; 120 the long way. What moves is the floor. That is also why `m7_project` is
; not in this feature's `depends` even though m7dg_obj needs it: there is no
; second actor standing on the plane.
;
; THE HI TABLE IS REBUILT WHOLE, NEVER PATCHED. One hi-table byte covers four
; slots and this feature owns all four, so mxo_draw rewrites the byte outright
; instead of read-modify-writing it. A stale X9 renders a sprite 256 px away —
; here the avatar's x never goes negative, but the invariant is the byte's
; ownership, not today's arithmetic.

; --- the binding: WHICH WAY SHE FACES, and WHETHER SHE IS MID-STEP ----------
; Two symbols the includer supplies, hard `.error` and NO DEFAULT — col_map's /
; rgb_gradient's shape, for the reason rgb_gradient records ("a silent default
; is exactly how the platformer inherited a wash on its terrain"). Both are the
; GAME's state, declared in state.toml, so binding them is what keeps the
; sprite and the walk machine reading one variable rather than two that agree
; by habit.
;
;  MXO_FACING u16 DP: FACE_DOWN 0 / FACE_UP 1 / FACE_LEFT 2 / FACE_RIGHT 3
;  MXO_WALK u16 DP: frames left in the current slide, 0 when at rest. It
;  serves BOTH questions the draw asks — "is she walking" is
;  `!= 0`, and the bob's 2-frame cadence is bit 1 of the same
;  countdown, so the hop is phase-locked to the step rather than
;  to a free-running frame counter that would drift against it.
.ifndef MXO_FACING
    .error "m7x_obj: the includer must define MXO_FACING (the DP word holding the latched facing code) before including this file"
.endif
.ifndef MXO_WALK
    .error "m7x_obj: the includer must define MXO_WALK (the DP word holding frames-left in the current slide, 0 at rest) before including this file"
.endif

; --- the screen pin --------------------------------------------------------
; 256x224 is the NTSC active area, so its centre is (128,112) — the same two
; numbers m7a_set_center subtracts to put the pivot there. An OAM entry names
; the sprite's TOP-LEFT, so the 16x16 body's centre lands on the pivot when the
; entry is centre - half.
MXO_CX   = 128
MXO_CY   = 112
MXO_SIZE = 16
MXO_HALF = MXO_SIZE / 2
MXO_X    = MXO_CX - MXO_HALF        ; 120
MXO_Y    = MXO_CY - MXO_HALF        ; 104

MXO_TILE_WORDS = 16                 ; an 8x8 4bpp tile is 32 B = 16 words
MXO_PARK_Y = $F0                    ; below the screen — where the pad slots live

; OAM attribute bits. Bit7 = V-flip, bit6 = H-flip, bits5:4 = priority,
; bits3:1 = OBJ palette, bit0 = tile bit 8. PRIORITY 2, NOT 3, and it is
; PINNED rather than preferred. In Mode 7 BG1 is the only layer, so 2 and 3
; composite identically here and the choice is invisible in the picture —
; which is exactly why it is worth pinning: the OAM ATTRIBUTE BYTE is a test
; surface, and an observable byte that drifts "harmlessly" is an oracle that
; has quietly stopped meaning anything. Measured: the settled frame is
; pixel-identical either way, which is exactly why the byte needs pinning
; rather than arguing about.
MXO_PRIO  = $20                     ; priority 2: in front of the plane
MXO_PAL   = $00                     ; OBJ palette 0, at CGRAM 128
MXO_HFLIP = $40                     ; the bit that makes LEFT out of SIDE

; The hi table's SIZE bit. Each hi-table byte covers four sprites, two bits
; each: bit 0 = X9, bit 1 = size. OBSEL's size pair 0 is small 8x8 / large
; 16x16, so "large" is what makes this a 16x16 sprite — leave it clear and the
; avatar renders as her own top-left quarter.
MXO_LARGE = 2

; The facing codes. Named here because this feature is what turns one into a
; tile and an attribute; the game latches them.
FACE_DOWN  = 0
FACE_UP    = 1
FACE_LEFT  = 2
FACE_RIGHT = 3

; The sheet's three authored facings, from the generator's own emitted
; constants (m7x_world.inc) rather than transcribed: DOWN at tile 16, UP at 18,
; SIDE at 20, each a 16x16 quad {N, N+1, N+16, N+17}. LEFT is SIDE H-FLIPPED
; through the attribute bit, so no fourth sprite is authored or shipped — and
; that only works because this is a TRUE 16x16 OBJ: a 32x32 size box holding
; 16x16 art would slide the art +16 px when flipped instead of mirroring it in
; place.
.assert M7X_AVATAR_TILES * MXO_TILE_WORDS <= ES_V_OBJ_CHR_WORDS, error, "m7x_obj: the avatar sheet overflows the obj_chr claim"

; The enter-time GP-DMA register file, addressed through the channel the mxo_up
; dma_init claim names.
MXO_REGS = $4300 + ES_D_MXO_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE, so a re-sized
; shadow moves it.
MXO_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
MXO_HI_BYTE = MXO_HI_BASE + (ES_O_AVATAR / 4)

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; --- obj_arm: the sheet, the palette, OBSEL --------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (the scene_mgr enter
; contract — which is also why nothing here masks $4200 itself: the long
; CPU-side palette writes cannot be preempted by an NMI that is not armed yet).
; Clobbers A, X, Y.
;
; WITHOUT these uploads this feature renders COLOUR NOISE rather than nothing:
; OBJ VRAM and CGRAM 128.. Are random at power-on (rule 5), and an OAM entry
; pointing at them is a perfectly valid sprite made of garbage.
;
; WIDTH-RISK: entered A16/I16, toggles A8 for the byte-wide channel registers,
; the MDMAEN write and each palette byte, and restores A16 before returning.
; I-width is never touched: `sep #$20` only, never `sep #$30` — X is a live
; index across the palette loop.
obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    lda #^m7x_obj_chr_bin
    sta a:MXO_REGS + 4              ; A1B = source bank
    lda #ES_D_MXO_UP_DMAP
    sta a:MXO_REGS + 0              ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_MXO_UP_BBAD
    sta a:MXO_REGS + 1              ; BBAD: VMDATAL, so B+1 = VMDATAH
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the claim's base word
    ldx #.loword(m7x_obj_chr_bin)
    stx a:MXO_REGS + 2              ; A1T
    ldy #ES_R_M7X_OBJ_CHR_SIZE
    sty a:MXO_REGS + 5              ; DAS, armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_MXO_UP_CH)
    sta a:$420B                     ; fire
    ; ---- the OBJ palette: sixteen words, CPU-side ------------------------
    ; Thirty-two stores; a DMA would cost more to set up than to run, and CGADD
    ; auto-increments so this build walks itself. Same shape and same reason as
    ; m7dg_obj's MDO_PAL_UP and split_v_obj's SV_OBJ_PAL_UP.
    lda #ES_C_MXO_PAL
    sta a:$2121                     ; CGADD = the claim's base word (128)
    rep #$20
    .a16
    ldx #0
:   lda f:m7x_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7X_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + the OBJ name base -------------
    ; The base is the ALLOCATOR's encoding of the obj_chr claim. It is above
    ; the Mode 7 region because the scene's `mode7` claim owns words
    ; $0000-$3FFF and the packer therefore floors OBJ CHR at $4000 — but this
    ; file never derives that, and never spells the byte out as a literal $62.
    ; Size pair 0 puts 16x16 in the pair's LARGE half, which is the bit
    ; mxo_draw sets.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr obj_park
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen ---
; In/out: A16/I16, DB=0. Clobbers A, X. Called at enter (so the scene starts
; with nothing stale on screen) and at exit (so a successor scene, which may
; draw no sprites at all, cannot show this one's avatar). The three pad slots
; are parked here and never touched again — they exist so the hi-table byte has
; one owner (see the header).
obj_park:
    .a16
    .i16
    ldx #(ES_O_AVATAR * 4)
@loop:
    .a16
    .i16
    lda #(MXO_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) * 4)
    bcc @loop
    sep #$20
    .a8
    stz a:MXO_HI_BYTE               ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts

; =============================================================================
; DRAWING — one entry, every frame
; =============================================================================
; --- mxo_draw: the avatar at the pin, facing where she was last pushed ------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE WALK BOB. While a slide is in flight she hops one pixel on a two-frame
; cadence, so she reads as stepping rather than gliding; at rest she sits flat
; at MXO_Y exactly. The cadence is bit 1 of the slide's own countdown, which is
; what phase-locks the hop to the step — a free-running frame counter would
; drift against a step that starts on an arbitrary frame, and the hop would
; land mid-slide sometimes and at the boundary others.
;
; WIDTH-RISK: A16/I16 throughout except the two byte-wide OAM stores and the
; hi-table byte, each bracketed by `sep #$20` / `rep #$20`. I-width is never
; touched.
mxo_draw:
    .a16
    .i16
    ; ---- the screen y: flat, or hopped one pixel -------------------------
    ldy #MXO_Y
    lda z:MXO_WALK
    beq @have_y                     ; at rest — no bob
    and #2                          ; bit 1 of the countdown: 2 frames up,
    beq @have_y                     ;   2 frames down
    ldy #(MXO_Y - 1)
@have_y:
    .a16
    .i16
    sty z:ES_MXO + 0
    ; ---- facing -> (tile, attr), through the two word LUTs ---------------
    ; A16 throughout, and the index is masked to 0..3 before `tax`, so I16's
    ; transfer of the full 16-bit C register cannot carry a stray high byte
    ; into X (the documented tax-across-width class).
    lda z:MXO_FACING
    and #3
    asl                             ; *2 — word index
    tax
    lda f:mxo_tile_lut, x
    sta a:ES_OAM_SHADOW + (ES_O_AVATAR * 4) + 2   ; bytes 2,3: tile and attr
    ; ---- the entry's x and y --------------------------------------------
    lda z:ES_MXO + 0
    xba
    and #$FF00
    ora #MXO_X                      ; byte 0 = x, byte 1 = y, in one store
    sta a:ES_OAM_SHADOW + (ES_O_AVATAR * 4) + 0
    ; ---- the hi-table byte, written WHOLE --------------------------------
    ; X9 is clear: MXO_X is 120 and never moves, so bit 8 of the OAM x is 0 by
    ; construction. The SIZE bit is what makes her 16x16. The other three
    ; fields belong to this feature's parked pad slots and are zero — small, X9
    ; clear, parked below the screen — which is why this is a store and not an
    ; OR.
    sep #$20
    .a8
    lda #MXO_LARGE
    sta a:MXO_HI_BYTE
    rep #$20
    .a16
    rts

; --- facing -> tile | (attr << 8) ------------------------------------------
; One word per facing, in the exact shape the OAM entry's bytes 2 and 3 want,
; so the draw is one indexed load and one store. DOWN/UP/RIGHT draw unflipped;
; LEFT reuses the RIGHT profile's CHR with the H-flip bit set, which is the
; whole reason the sheet ships three facings and not four.
mxo_tile_lut:
    .word M7X_AVATAR_TILE_DOWN | ((MXO_PRIO | MXO_PAL) << 8)
    .word M7X_AVATAR_TILE_UP   | ((MXO_PRIO | MXO_PAL) << 8)
    .word M7X_AVATAR_TILE_SIDE | ((MXO_PRIO | MXO_PAL | MXO_HFLIP) << 8)
    .word M7X_AVATAR_TILE_SIDE | ((MXO_PRIO | MXO_PAL) << 8)
