; =============================================================================
; m7dg_obj.asm — the dungeon's cast on the rotating plane
; =============================================================================
; Seven sprites in eight OAM slots, written into the oam_sprites SHADOW;
; hardware OAM belongs to that feature's declared VBlank GP-DMA.
;
; ONE SPRITE IS PINNED AND THE REST ARE PROJECTED, and that split is the whole
; camera model. M7a_set_center holds the pivot — the hero's world position — at
; screen (128,112) for every heading, so the hero's OAM entry is a CONSTANT and
; deriving it would be deriving 128 the long way. Everything else lives at a
; world position and is mapped through m7_project each frame, which is what
; keeps an enemy standing on its own floor tile while the floor turns under it.
;
; THE HI TABLE IS REBUILT WHOLE, NEVER PATCHED. Two hi-table bytes cover our
; eight slots and this feature owns all eight, so mdo_draw zeroes both and
; mdo_put ORs each sprite's two bits in. A stale X9 renders a sprite 256 px
; away — and here that is not hypothetical: an enemy's screen x goes NEGATIVE
; the moment it straddles the left edge of the view, which is a set bit 8.

; --- the binding: WHERE the enemies are ------------------------------------
; The includer supplies ONE symbol — a table of (x, y) world-pixel word pairs,
; one pair per enemy slot, in DIRECT PAGE. A hard `.error` and no default, the
; col_map / rgb_gradient shape, and for the same reason: a default here would
; project SOMETHING at every heading, and "the sprites move plausibly but are
; not on their own tiles" is precisely the failure that survives a look.
;
; IT IS A BINDING RATHER THAN A FIXED LABEL because the enemies MOVE.
; Projecting the scene's `enemy_world` ROM table directly is honest only while
; the cast is static; the patrol paces them, so where an enemy IS is state,
; and a feature reading the ROM seed would draw every slime at its spawn while
; the collision test used its real position. One symbol, so the two cannot
; come apart.
.ifndef MDO_ENEMY_POS
    .error "m7dg_obj: the includer must define MDO_ENEMY_POS (the DP table of live enemy (x,y) world-pixel word pairs) before including this file"
.endif

; --- the projection's screen origin, borrowed rather than restated ----------
; These are m7_project's constants, and they are m7a_set_center's contract
; before that. Aliased here so this file reads in its own terms while there is
; still exactly one definition.
MDO_CX = M7P_SCREEN_CX                ; 128
MDO_CY = M7P_SCREEN_CY                ; 112

; --- the sprite geometry ---------------------------------------------------
MDO_SIZE = 16                           ; every actor is 16x16
MDO_HALF = MDO_SIZE / 2                 ; OAM (x,y) = centre - half
MDO_TILE_WORDS = 16                     ; an 8x8 4bpp tile is 32 B = 16 words
MDO_SHEET_TILES = 18                    ; the generator's grid: {0,1,16,17} + pad

; The three sheets, one row PAIR of the 16-wide OBJ name table each. A 16x16
; sprite reads {N, N+1, N+16, N+17} — the second row is +16 tiles away, which
; is hardware and is why the bases are 32 apart rather than 18.
MDO_HERO_TILE  = 0
MDO_ENEMY_TILE = 32
MDO_WIN_TILE   = 64
.assert (MDO_WIN_TILE + MDO_SHEET_TILES) * MDO_TILE_WORDS <= ES_V_OBJ_CHR_WORDS,  error, "m7dg_obj: the three sheets overflow the obj_chr claim"

; OAM attribute bits. Bit7 = V-flip, bit6 = H-flip, bits5:4 = priority, bits3:1
; = OBJ palette, bit0 = tile bit 8.
MDO_PRIO      = $30                     ; priority 3: in front of the plane
MDO_PAL_HERO  = $00                     ; OBJ palette 0, at CGRAM 128
MDO_PAL_ENEMY = $02                     ; OBJ palette 1, at 144
MDO_PAL_WIN   = $04                     ; OBJ palette 2, at 160

; The hi table's SIZE bit. Each hi-table byte covers four sprites, two bits
; each: bit 0 = X9, bit 1 = size. OBSEL's size pair 0 is small 8x8 / large
; 16x16, so "large" is what makes these 16x16 — and the bit is written per slot
; every frame, because the byte is rebuilt whole and a bit left clear would
; render a 16x16 actor as its top-left quarter.
MDO_LARGE = 2

MDO_PARK_Y = $F0                        ; below the screen — where an unused or
                                        ;  culled slot lives

; --- the cull window, and why it is not symmetric --------------------------
; The OBJ x is NINE BITS SIGNED: the hardware has a sign bit (X9) precisely so
; a sprite can hang off the LEFT edge, so the x window runs from "one column
; still on screen" up to the positive top of that space.
;
; The OBJ y is EIGHT BITS UNSIGNED. There is no sign bit, and a negative y
; written as a byte reappears at the BOTTOM of the screen — a sprite that
; should be half off the top instead draws whole, in the wrong place. So the y
; window starts at zero and a sprite is culled the moment its top row would go
; negative. That asymmetry is the hardware's, not a policy choice, and
; pretending otherwise is what puts a slime at the bottom of the screen when it
; walks off the top.
MDO_X_LO = -(MDO_SIZE - 1)              ; OAM x: at least one column on screen
MDO_X_HI = 2 * MDO_CX - 1               ; ...up to the 9-bit space's positive top
MDO_Y_HI = 2 * MDO_CY - 1               ; OAM y: the byte's own range

; The screen window above must be a SUBSET of what m7_project's pre-cull lets
; through, or a sprite could be rejected before the test that would have kept
; it. Both axes, asserted rather than reasoned about in a comment.
.assert MDO_CX - (MDO_X_LO + MDO_HALF) <= M7P_HX, error,  "m7dg_obj: the x cull window reaches left of m7_project's pre-cull"
.assert (MDO_X_HI + MDO_HALF) - MDO_CX <= M7P_HX, error,  "m7dg_obj: the x cull window reaches right of m7_project's pre-cull"
.assert MDO_CY - MDO_HALF <= M7P_HY, error,  "m7dg_obj: the y cull window reaches above m7_project's pre-cull"
.assert (MDO_Y_HI + MDO_HALF) - MDO_CY <= M7P_HY, error,  "m7dg_obj: the y cull window reaches below m7_project's pre-cull"

; --- this feature's DP scratch (the mdo claim) -----------------------------
MDO_X = 0                               ; 2 — the OAM x being placed (9-bit)
MDO_Y = 2                               ; 2 — the OAM y being placed
MDO_I = 4                               ; 2 — the enemy loop index

; The enter-time GP-DMA register file, addressed through the channel the mdo_up
; dma_init claim names.
MDO_REGS = $4300 + ES_D_MDO_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE, so a re-sized
; shadow moves it.
MDO_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; --- MDO_CHR_UP: one sprite sheet into OBJ VRAM ----------------------------
; Inline rather than a routine because the destination tile, the blob and the
; size are three different assemble-time constants per sheet; a shared routine
; would need them at runtime, which here would mean DP scratch for values the
; assembler already knows. Same call the split_v_obj palette upload makes.
;
; DAS is SINGLE-SHOT — consumed by each transfer — so it is armed inside, per
; sheet. Three sheets, three armings; arming once outside would move the first
; sheet and silently drop the other two.
;
; WIDTH-RISK: entered A16/I16, toggles A8 for the byte-wide channel registers
; and the MDMAEN write, and restores A16 before returning. I-width is never
; touched: `sep #$20` only, never `sep #$30`.
.macro MDO_CHR_UP mdo_tile, mdo_blob, mdo_size
    lda #(ES_V_OBJ_CHR + mdo_tile * MDO_TILE_WORDS)
    sta a:$2116                     ; VMADD = this sheet's base word
    ldx #.loword(mdo_blob)
    stx a:MDO_REGS + 2              ; A1T
    ldy #mdo_size
    sty a:MDO_REGS + 5              ; DAS, re-armed for THIS transfer
    sep #$20
    .a8
    lda #^mdo_blob
    sta a:MDO_REGS + 4              ; A1B = source bank
    lda #ES_D_MDO_UP_DMAP
    sta a:MDO_REGS + 0              ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_MDO_UP_BBAD
    sta a:MDO_REGS + 1              ; BBAD: VMDATAL, so B+1 = VMDATAH
    lda #(1 << ES_D_MDO_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16
.endmacro

; --- MDO_PAL_UP: one OBJ palette, CPU-side ---------------------------------
; Sixteen words is thirty-two stores; a DMA would cost more to set up than to
; run, and CGADD auto-increments so this build walks itself. Same shape and
; same reason as split_v_obj's SV_OBJ_PAL_UP.
;
; WIDTH-RISK: entered A16/I16, toggles A8 per byte store and restores A16
; before the loop test. `sep #$20` only — I-width tracking must not leak to the
; caller, whose X is the loop counter.
.macro MDO_PAL_UP mdo_at, mdo_blob, mdo_size
    .local mdo_loop
    sep #$20
    .a8
    lda #mdo_at
    sta a:$2121                     ; CGADD = the claim's base word
    rep #$20
    .a16
    ldx #0
mdo_loop:
    .a16
    .i16
    lda f:mdo_blob, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #mdo_size
    bcc mdo_loop
.endmacro

; --- obj_arm: the three sheets, the three palettes, OBSEL ------------------
; CONTRACT m7dg_obj::obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the three sheets, the three palettes and OBSEL
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
;
; contract — which is also why nothing here masks $4200 itself: the long
; CPU-side palette writes cannot be preempted by an NMI that is not armed yet).
; Clobbers A, X, Y.
;
; WITHOUT these uploads this feature renders COLOUR NOISE rather than nothing:
; OBJ VRAM and CGRAM 128.. Are random at power-on (rule 5), and an OAM entry
; pointing at them is a perfectly valid sprite made of garbage.
obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    rep #$20
    .a16
    MDO_CHR_UP MDO_HERO_TILE,  m7dg_hero_chr_bin,  ES_R_M7DG_HERO_CHR_SIZE
    MDO_CHR_UP MDO_ENEMY_TILE, m7dg_enemy_chr_bin, ES_R_M7DG_ENEMY_CHR_SIZE
    MDO_CHR_UP MDO_WIN_TILE,   m7dg_win_chr_bin,   ES_R_M7DG_WIN_CHR_SIZE
    MDO_PAL_UP ES_C_HERO_PAL,  m7dg_hero_pal_bin,  ES_R_M7DG_HERO_PAL_SIZE
    MDO_PAL_UP ES_C_ENEMY_PAL, m7dg_enemy_pal_bin, ES_R_M7DG_ENEMY_PAL_SIZE
    MDO_PAL_UP ES_C_WIN_PAL,   m7dg_win_pal_bin,   ES_R_M7DG_WIN_PAL_SIZE
    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + the OBJ name base -------------
    ; The base is the ALLOCATOR's encoding of the obj_chr claim. It is $02 here
    ; because the scene's mode7 claim owns words $0000-$3FFF and the packer
    ; therefore floors OBJ CHR at $4000 — but this file never derives that, and
    ; never spells that byte out as a literal $62. Size pair 0 puts 16x16 in
    ; the pair's LARGE half, which is the bit mdo_put sets per slot.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr obj_park
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen ---
; CONTRACT m7dg_obj::obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every slot this feature owns parked off the bottom of the
;             screen
;   clobbers: A, X, N, Z, C
;   assumes:  at enter, so the scene starts with nothing stale on screen;
;             the per-frame draw re-parks dead slots after that
;   tail:     rts
;
; with nothing stale on screen) and at exit (so a successor scene, which draws
; no sprites at all, cannot show this cast).
obj_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_park"
    ldx #(ES_O_HERO * 4)
@loop:
    .a16
    .i16
    lda #(MDO_PARK_Y << 8)
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
    stz a:MDO_HI_BASE + (ES_O_HERO / 4)
    stz a:MDO_HI_BASE + (ES_O_WIN / 4)  ; small + X9 clear, as oam_park_all left
    rep #$20                            ;   both bytes
    .a16
    rts

; =============================================================================
; DRAWING — every slot, every frame
; =============================================================================
; CONTRACT mdo_put
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one OAM entry plus its two hi-table bits. X is PRESERVED
;   clobbers: A, Y, N, Z, C
;   assumes:  the per-frame hi clear has already run
;   tail:     rts
;
; --- mdo_put: one OAM entry, plus its two hi-table bits --------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  ES_MDO+MDO_X = the OAM x (9 bits; bit 8 becomes X9), +MDO_Y = the OAM y
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED — see the file header.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one 2-byte phx/plx pair and
; one 2-byte pha/pla pair, and every arm of the routine passes through both. A
; push taken in A16 and pulled in A8 would drift the stack one byte per sprite
; per frame, which over a few seconds walks the return chain off its own stack.
mdo_put:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mdo_put"
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:ES_MDO + MDO_Y
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 cleared, next line)
    sep #$20
    .a8
    lda z:ES_MDO + MDO_X
    sta a:ES_OAM_SHADOW + 0, x      ; byte 0 = x's low eight bits
    rep #$20
    .a16
    ; ---- the hi-table field: 2 bits, at (slot & 3) * 2 --------------------
    phx
    txa
    .repeat 2
        lsr
    .endrepeat
    and #3
    tay                             ; Y = which field within the byte
    lda z:ES_MDO + MDO_X
    xba
    and #1                          ; x bit 8 -> X9
    ora #MDO_LARGE                  ; ...| the size bit: every actor is 16x16
@shift:
    .a16
    .i16
    cpy #0
    beq @placed
    asl
    asl
    dey
    bra @shift
@placed:
    .a16
    .i16
    pha                             ; the positioned bits, while X is rebuilt
    txa
    .repeat 4
        lsr                         ; slot byte offset >> 4 = hi byte index
    .endrepeat
    tax
    pla
    sep #$20
    .a8
    ora a:MDO_HI_BASE, x            ; OR, not store: the other slots share this
    sta a:MDO_HI_BASE, x            ;   byte and mdo_draw cleared it once
    rep #$20
    .a16
    plx
    rts

; --- mdo_park_slot: one slot, off-screen ------------------------------------
; CONTRACT mdo_park_slot
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the slot's entry moved off screen; a culled actor keeps its
;             slot, so slot identity and sprite priority stay stable
;   clobbers: A, N, Z
;   assumes:  X names a slot this feature owns
;   tail:     rts
;
; In: A16/I16, DB=0. X = the slot's byte offset. Out: clobbers A. A culled
; actor keeps its slot but leaves the screen, so slot identity — and therefore
; sprite priority — is stable frame to frame whatever is visible.
mdo_park_slot:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mdo_park_slot"
    lda #(MDO_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    rts

; --- obj_draw: the whole cast, every frame ---------------------------------
; CONTRACT m7dg_obj::obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole cast staged into the shadow
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; Called from the scene's tick AFTER m7a_set_heading, so the matrix the sprites
; are projected through is the same one the NMI hook is about to commit. Do it
; the other way round and every sprite is one frame stale against the floor it
; stands on — which at this rail's rotation speed is a visible skid.
;
; WIDTH-RISK: A16/I16 throughout; mdo_put and mdo_park_slot both restore A16
; before returning, and the pha/ply pair in the enemy loop is 2 bytes each way.
obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_draw"
    ; The two hi-table bytes our eight slots occupy, cleared once so mdo_put
    ; can OR into them without inheriting last frame's X9 bits.
    sep #$20
    .a8
    stz a:MDO_HI_BASE + (ES_O_HERO / 4)
    stz a:MDO_HI_BASE + (ES_O_WIN / 4)
    rep #$20
    .a16
    ; ---- the hero: pinned at screen centre, by the camera's construction --
    lda #(MDO_CX - MDO_HALF)
    sta z:ES_MDO + MDO_X
    lda #(MDO_CY - MDO_HALF)
    sta z:ES_MDO + MDO_Y
    ldx #(ES_O_HERO * 4)
    lda #(MDO_HERO_TILE | ((MDO_PRIO | MDO_PAL_HERO) << 8))
    jsr mdo_put
    ; ---- the enemies: world positions, through the transpose --------------
    stz z:ES_MDO + MDO_I
@ene_loop:
    .a16
    .i16
    lda z:ES_MDO + MDO_I
    asl
    asl                             ; 4 bytes per (x,y) word pair
    tax
    lda z:MDO_ENEMY_POS + 2, x
    pha                             ; the world y, while X takes the world x
    lda z:MDO_ENEMY_POS + 0, x
    tax
    ply                             ; X = world x, Y = world y
    jsr ::m7p_project
    bcs @ene_park                   ; off-screen at EVERY heading — no arithmetic
    ; ---- the screen-space cull, in OAM coordinates ------------------------
    ; y first: it is the axis with no sign bit, so it is the one that rejects.
    lda z:ES_M7P + M7P_SY
    sec
    sbc #MDO_HALF                   ; the OAM y this sprite would take
    bmi @ene_park                   ; negative: the byte cannot say "above zero"
    cmp #(MDO_Y_HI + 1)
    bcs @ene_park
    sta z:ES_MDO + MDO_Y
    lda z:ES_M7P + M7P_SX
    sec
    sbc #MDO_HALF                   ; the OAM x this sprite would take, signed
    clc
    adc #(0 - MDO_X_LO)             ; shift the low bound to zero...
    bmi @ene_park                   ; ...so one unsigned compare covers both ends
    cmp #(MDO_X_HI - MDO_X_LO + 1)
    bcs @ene_park
    sec
    sbc #(0 - MDO_X_LO)             ; back to the signed OAM x
    and #$01FF                      ; into the OBJ's 9-bit space, where bit 8 is
    sta z:ES_MDO + MDO_X            ;   X9 and means "off the left edge"
    lda z:ES_MDO + MDO_I
    clc
    adc #ES_O_ENEMIES
    asl
    asl
    tax                             ; X = this enemy's slot byte offset
    lda #(MDO_ENEMY_TILE | ((MDO_PRIO | MDO_PAL_ENEMY) << 8))
    jsr mdo_put
    bra @ene_next
@ene_park:
    .a16
    .i16
    lda z:ES_MDO + MDO_I
    clc
    adc #ES_O_ENEMIES
    asl
    asl
    tax
    jsr mdo_park_slot
@ene_next:
    .a16
    .i16
    lda z:ES_MDO + MDO_I
    inc
    sta z:ES_MDO + MDO_I
    cmp #ES_O_ENEMIES_SPRITES
    bcs @ene_done
    jmp @ene_loop                   ; long jump: the loop body outruns a branch
@ene_done:
    .a16
    .i16
    rts
