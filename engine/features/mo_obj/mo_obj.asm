; =============================================================================
; mo_obj.asm — the cast: the pinned hero, six chasers, eight bolts
; =============================================================================
; Arming (once, at scene enter): two sprite sheets into OBJ VRAM, three OBJ
; palettes into CGRAM, OBSEL, both pools cleared through `pool_init`. Drawing
; (every frame): the hero at the pin, then every slot of both pools through
; m7_project's transpose — live at its projection, free or off-screen parked at
; y = MO_PARK_Y.
;
; THE HERO IS NOT PROJECTED. M7a_set_center pins the pivot — the hero's world
; position — at screen centre for every heading, so his screen position is a
; constant by construction and projecting it would be computing 128 the long
; way. This rail re-pins that pivot EVERY FRAME to a hero who is walking, which
; is the only difference from m7_dungeon's camera and costs nothing here.
;
; EVERY POOL SLOT IS EMITTED EVERY FRAME, live or parked, so slot identity is
; stable: OAM slot 7 is bolt 0 whether or not bolt 0 exists. That is what makes
; an OAM-byte assertion mean something — a test reads an actor by slot instead
; of hunting OAM for something plausible.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED. The OBJ x is nine bits: the
; low eight in the entry, bit 8 in the hi table. A projected actor sliding off
; the left edge has bit 8 set, and a STALE X9 renders it 256 px away on the
; right — the failure mode this project has a lessons-learned entry about. All
; four hi-table bytes are cleared at the top of the draw and rebuilt whole,
; which is why this feature owns the sixteenth slot it never draws.

; The enter-time GP-DMA register file, addressed through the channel the
; mo_obj_up dma_init claim names — a declared resource, not a hard-coded 0.
MO_OBJ_REGS = $4300 + ES_D_MO_OBJ_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE, so a re-sized
; shadow moves it.
MO_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; --- this feature's DP scratch (the mo_draw claim), named ------------------
MO_D_X    = 0                   ; 2 — the OAM x being placed (9-bit)
MO_D_Y    = 2                   ; 2 — the OAM y being placed
MO_D_CUR  = 4                   ; 2 — the pool cursor, a BYTE offset (0,2,4...)
MO_D_SIZE = 6                   ; 2 — the hi-table SIZE bit mo_put ORs in:
                                ;  MO_LARGE for a 16x16 actor, 0 for an 8x8
                                ;  HUD digit. OBSEL size pair 0 is
                                ;  (8x8 / 16x16), so this ONE bit is the whole
                                ;  difference between the two and the sheet,
                                ;  the palette and the entry format are shared.
                                ;
                                ;  This offset was `MO_D_SLOT`, documented as
                                ;  "the OAM slot byte offset that cursor
                                ;  emits" and referenced by NOTHING — the draw
                                ;  computes that value into X inline. A dead
                                ;  field in a claimed 8-byte block, so the
                                ;  score readout spends it rather than growing
                                ;  the claim.

; --- the projection's screen origin, borrowed rather than restated ---------
; m7_project centres the pivot on (128,112) and this feature places sprites
; around that same point. Aliasing the constants means the two cannot disagree.
MO_CX = M7P_SCREEN_CX
MO_CY = M7P_SCREEN_CY

; --- the cull window, and why it is not symmetric --------------------------
; A sprite is worth emitting if ANY of it is on screen. Horizontally the OBJ x
; is a 9-bit signed space, so a sprite may start up to (MO_SIZE - 1) px left of
; zero and still show a column; vertically the OAM y is a plain byte with no
; negative half, so the low bound is 0 and a sprite straddling the top edge is
; parked rather than wrapped. That asymmetry is the hardware's.
MO_X_LO = -(MO_SIZE - 1)
MO_X_HI = 2 * MO_CX - 1
MO_Y_HI = 2 * MO_CY - 1

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; --- MO_CHR_UP: one sprite sheet into OBJ VRAM -----------------------------
; Inline rather than a routine because the destination tile, the blob and the
; size are three different assemble-time constants per sheet; a shared routine
; would need them at runtime, which here would mean DP scratch for values the
; assembler already knows.
;
; DAS is SINGLE-SHOT — consumed by each transfer — so it is armed inside, per
; sheet. Two sheets, two armings; arming once outside would move the first
; sheet and silently drop the second.
;
; WIDTH-RISK: entered A16/I16, toggles A8 for the byte-wide channel registers
; and the MDMAEN write, and restores A16 before returning. I-width is never
; touched: `sep #$20` only, never `sep #$30`.
.macro MO_CHR_UP mo_tile, mo_blob, mo_size
    lda #(ES_V_OBJ_CHR + mo_tile * MO_TILE_WORDS)
    sta a:$2116                     ; VMADD = this sheet's base word
    ldx #.loword(mo_blob)
    stx a:MO_OBJ_REGS + 2           ; A1T
    ldy #mo_size
    sty a:MO_OBJ_REGS + 5           ; DAS, re-armed for THIS transfer
    sep #$20
    .a8
    lda #^mo_blob
    sta a:MO_OBJ_REGS + 4           ; A1B = source bank
    lda #ES_D_MO_OBJ_UP_DMAP
    sta a:MO_OBJ_REGS + 0           ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_MO_OBJ_UP_BBAD
    sta a:MO_OBJ_REGS + 1           ; BBAD: VMDATAL, so B+1 = VMDATAH
    lda #(1 << ES_D_MO_OBJ_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16
.endmacro

; --- MO_PAL_UP: one OBJ palette, CPU-side ----------------------------------
; Sixteen words is thirty-two stores; a DMA would cost more to set up than to
; run, and CGADD auto-increments so this build walks itself.
;
; WIDTH-RISK: entered A16/I16, toggles A8 per byte store and restores A16
; before the loop test. `sep #$20` only — I-width tracking must not leak to the
; caller, whose X is the loop counter.
.macro MO_PAL_UP mo_at, mo_blob, mo_size
    .local mo_pal_loop
    sep #$20
    .a8
    lda #mo_at
    sta a:$2121                     ; CGADD = the claim's base word
    rep #$20
    .a16
    ldx #0
mo_pal_loop:
    .a16
    .i16
    lda f:mo_blob, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #mo_size
    bcc mo_pal_loop
.endmacro

; --- obj_arm: the two sheets, the three palettes, OBSEL, both pools ---------
; CONTRACT mo_obj::obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the two sheets, the three palettes, OBSEL and both pools
;             initialised
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
;
; WIDTH-RISK: A16/I16 entry AND exit. The macros toggle A8 internally and
; restore A16; `pool_init` requires A16/I16 on both sides and contains no
; sep/rep at all (pool.asm's contract delta (a)) — a cross-file contract
; width_lint cannot see, so this marker is what carries it.
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
    MO_CHR_UP MO_HERO_TILE,  mo_hero_chr_bin,  ES_R_MO_HERO_CHR_SIZE
    MO_CHR_UP MO_ENEMY_TILE, mo_enemy_chr_bin, ES_R_MO_ENEMY_CHR_SIZE
    MO_PAL_UP ES_C_HERO_PAL,   mo_hero_pal_bin,   ES_R_MO_HERO_PAL_SIZE
    MO_PAL_UP ES_C_ENEMY_PAL,  mo_enemy_pal_bin,  ES_R_MO_ENEMY_PAL_SIZE
    MO_PAL_UP ES_C_BULLET_PAL, mo_bullet_pal_bin, ES_R_MO_BULLET_PAL_SIZE
    MO_PAL_UP ES_C_SCORE_PAL,  mo_score_pal_bin,  ES_R_MO_SCORE_PAL_SIZE
    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + the OBJ name base -------------
    ; The base is the ALLOCATOR's encoding of the obj_chr claim. It is $02 here
    ; because the scene's mode7 claim owns words $0000-$3FFF and the packer
    ; therefore floors OBJ CHR at $4000 — but this file never derives that, and
    ; never spells that byte out as a literal $62. Size pair 0 puts 16x16 in
    ; the pair's LARGE half, which is the bit mo_put sets per slot.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr mo_actors_arm
    jsr obj_park
    rts

; --- mo_actors_arm: both pools, through the mechanism ----------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; THE CLEAR GOES THROUGH `pool_init`, not through a local loop, and that is the
; point of composing the feature at all: the array this rail's spawn scans is
; the array the mechanism cleared. The parallel fields (wx, wy, vx, vy, ttl)
; are deliberately NOT pre-filled — pool.asm's own header states why: a slot's
; position is written by spawn-then-use, and pre-filling would hide a "spawn
; forgot to set y" defect behind a plausible zero.
;
; The counts are the .inc's single constants, which is what discharges pool's
; unenforced upper bound (contract delta (c)): the same symbol reaches init,
; spawn and count for each pool.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep anywhere. POOL_BIND requires
; A16 and leaves it; `pool_init` requires A16/I16 and contains no sep/rep.
mo_actors_arm:
    .a16
    .i16
    POOL_BIND ES_MO_ACTORS_LONG + MO_ENE_ALIVE
    ldx #MO_ENE_N
    jsr pool_init
    POOL_BIND ES_MO_ACTORS_LONG + MO_BUL_ALIVE
    ldx #MO_BUL_N
    jsr pool_init
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen ---
; CONTRACT mo_obj::obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every slot this feature owns parked off the bottom of the
;             screen
;   clobbers: A, X, N, Z, C
;   assumes:  at enter, so the scene starts with nothing stale on screen
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
    lda #(MO_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD2 + ES_O_HI_PAD2_SPRITES) * 4)
    bcc @loop                       ; ...through the score's four slots too: the
                                    ;  range this feature owns now ends at
                                    ;  hi_pad2, and a slot left unparked at
                                    ;  enter shows power-on garbage as a sprite
    jsr mo_hi_clear
    rts

; --- mo_hi_clear: the four hi-table bytes this feature owns ----------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; TWENTY slots is exactly five bytes, and this feature owns every one of them
; whole — which is the reason the sixteenth AND twentieth slots are claimed at
; all. Clearing before the draw is what lets mo_put OR its two bits in without
; inheriting last frame's X9.
;
; The fifth byte arrived with the score readout (slots 16..19). Missing it
; would have been invisible on the X9 bit — the digits sit at x = 16..32, so
; bit 8 is never set — and visible on the SIZE bit, which is exactly the
; direction that hurts: last frame's stale MO_LARGE would render each 8x8 digit
; as a 16x16 sprite sampling the three tiles after it.
;
; WIDTH-RISK: toggles A8 for the five byte stores and restores A16.
mo_hi_clear:
    .a16
    .i16
    sep #$20
    .a8
    stz a:MO_HI_BASE + 0
    stz a:MO_HI_BASE + 1
    stz a:MO_HI_BASE + 2
    stz a:MO_HI_BASE + 3
    stz a:MO_HI_BASE + 4
    rep #$20
    .a16
    rts

; =============================================================================
; DRAWING — every slot, every frame
; =============================================================================
; --- mo_put: one OAM entry, plus its two hi-table bits ---------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  ES_MO_DRAW+MO_D_X = the OAM x (9 bits; bit 8 becomes X9), +MO_D_Y = y
; Out: X preserved. Clobbers A, Y.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one 2-byte phx/plx pair and
; one 2-byte pha/pla pair, and every arm of the routine passes through both. A
; push taken in A16 and pulled in A8 would drift the stack one byte per sprite
; per frame, which over a few seconds walks the return chain off its own stack.
mo_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:ES_MO_DRAW + MO_D_Y
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 cleared, next line)
    sep #$20
    .a8
    lda z:ES_MO_DRAW + MO_D_X
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
    lda z:ES_MO_DRAW + MO_D_X
    xba
    and #1                          ; x bit 8 -> X9
    ora z:ES_MO_DRAW + MO_D_SIZE    ; ...| the size bit the CALLER selected:
                                    ;  MO_LARGE for a 16x16 actor, 0 for an 8x8
                                    ;  HUD digit. It used to be a hard
                                    ;  `ora #MO_LARGE`, which was right while
                                    ;  every sprite this feature drew was an
                                    ;  actor; the score readout is the first
                                    ;  that is not.
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
    ora a:MO_HI_BASE, x             ; OR, not store: the other slots share this
    sta a:MO_HI_BASE, x             ;   byte and mo_hi_clear zeroed it once
    rep #$20
    .a16
    plx
    rts

; --- mo_park_slot: one slot, off-screen ------------------------------------
; CONTRACT mo_park_slot
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the slot's entry moved off screen; a free or culled actor
;             keeps its slot, so slot identity and sprite priority stay
;             stable
;   clobbers: A, N, Z
;   assumes:  X names a slot this feature owns
;   tail:     rts
;
; In: A16/I16, DB=0. X = the slot's byte offset. Out: clobbers A. A free or
; culled actor keeps its slot but leaves the screen, so slot identity — and
; therefore sprite priority — is stable frame to frame whatever is visible.
mo_park_slot:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mo_park_slot"
    lda #(MO_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    rts

; --- MO_DRAW_POOL: one pool's whole slot range, projected or parked --------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and this feature's scratch.
;
; ONE body, expanded for both pools, and that is deliberate rather than
; thrifty: the chasers and the bolts must go onto the floor through the SAME
; projection, or a bolt and the chaser it is about to hit would disagree about
; where the world is. Written out twice, the two draws are 95% the same code
; and the 5% is exactly where they drift; here there is one copy.
;
; The cursor is a BYTE offset (0, 2, 4 ...) because that is the idiom
; pool_spawn and pool_kill take and return, so the same number indexes the
; alive array, the parallel fields, and — doubled — the OAM slot.
;
; WIDTH-RISK: A16/I16 throughout. M7p_project, mo_put and mo_park_slot all
; require and restore A16/I16, and m7p_project returns its answer in the CARRY,
; so nothing between its `jsr` and the `bcs` may touch flags.
.macro MO_DRAW_POOL mo_alive, mo_wx, mo_wy, mo_count, mo_slot0, mo_tileattr
    .local mo_loop, mo_park, mo_next, mo_done
    stz z:ES_MO_DRAW + MO_D_CUR
mo_loop:
    .a16
    .i16
    ldx z:ES_MO_DRAW + MO_D_CUR
    lda f:ES_MO_ACTORS_LONG + mo_alive, x
    beq mo_park                     ; a free slot still gets its OAM entry
    lda f:ES_MO_ACTORS_LONG + mo_wy, x
    pha                             ; the world y, while X takes the world x
    lda f:ES_MO_ACTORS_LONG + mo_wx, x
    tax
    ply                             ; X = world x, Y = world y
    jsr ::m7p_project
    bcs mo_park                     ; outside the circumradius at EVERY heading
    ; ---- the screen-space cull, in OAM coordinates -----------------------
    ; y first: it is the axis with no sign bit, so it is the one that rejects.
    lda z:ES_M7P + M7P_SY
    sec
    sbc #MO_HALF                    ; the OAM y this sprite would take
    bmi mo_park                     ; negative: the byte cannot say "above zero"
    cmp #(MO_Y_HI + 1)
    bcs mo_park
    sta z:ES_MO_DRAW + MO_D_Y
    lda z:ES_M7P + M7P_SX
    sec
    sbc #MO_HALF                    ; the OAM x this sprite would take, signed
    clc
    adc #(0 - MO_X_LO)              ; shift the low bound to zero...
    bmi mo_park                     ; ...so one unsigned compare covers both ends
    cmp #(MO_X_HI - MO_X_LO + 1)
    bcs mo_park
    sec
    sbc #(0 - MO_X_LO)              ; back to the signed OAM x
    and #$01FF                      ; into the OBJ's 9-bit space, where bit 8 is
    sta z:ES_MO_DRAW + MO_D_X       ;   X9 and means "off the left edge"
    lda z:ES_MO_DRAW + MO_D_CUR
    asl                             ; cursor * 2 = slot offset within the range
    clc
    adc #(mo_slot0 * 4)
    tax
    lda #mo_tileattr
    jsr mo_put
    bra mo_next
mo_park:
    .a16
    .i16
    lda z:ES_MO_DRAW + MO_D_CUR
    asl
    clc
    adc #(mo_slot0 * 4)
    tax
    jsr mo_park_slot
mo_next:
    .a16
    .i16
    lda z:ES_MO_DRAW + MO_D_CUR
    inc
    inc                             ; +2: the pool's byte stride
    sta z:ES_MO_DRAW + MO_D_CUR
    cmp #(2 * mo_count)
    bcs mo_done
    jmp mo_loop                     ; long jump: the body outruns a branch
mo_done:
    .a16
    .i16
.endmacro

; --- the three tile|attr words the draw emits ------------------------------
; Byte 2 is the tile, byte 3 the attribute (priority | OBJ palette), so one
; 16-bit store writes both. The bolt takes the CHASER's tile under its own
; palette, which makes a bolt identifiable by COLOUR in the rendered frame
; rather than by shape — and saves a third CHR sheet.
MO_TA_HERO   = MO_HERO_TILE   | ((MO_PRIO | MO_PAL_HERO) << 8)
MO_TA_ENEMY  = MO_ENEMY_TILE  | ((MO_PRIO | MO_PAL_ENEMY) << 8)
MO_TA_BULLET = MO_BULLET_TILE | ((MO_PRIO | MO_PAL_BULLET) << 8)

; --- obj_draw: the whole cast, every frame ---------------------------------
; CONTRACT mo_obj::obj_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole cast staged into the shadow
;   clobbers: A, X, Y, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; Called from the scene's tick AFTER m7a_set_heading AND AFTER m7a_set_center,
; so the matrix and the pivot the actors are projected through are the same
; pair the NMI hook is about to commit. Draw before the pivot moves and every
; actor is placed with LAST frame's camera while the floor renders with this
; one's — a one-frame skid that reads as the cast sliding across the floor
; rather than standing on it. On m7_dungeon that mattered only when the hero
; was knocked back; here the pivot moves every frame the player walks, so it is
; the normal case rather than the exception.
;
; THE BOLTS DRAW AFTER THE CHASERS, at higher OAM indices, so a bolt crossing a
; chaser reads as passing under it. OAM index order IS sprite-vs-sprite
; priority, and the slot map is pinned in feature.toml precisely so this is a
; decision rather than an accident of claim names.
;
; WIDTH-RISK: A16/I16 throughout; mo_put, mo_park_slot and m7p_project all
; restore A16/I16 before returning, and the pha/ply pair inside MO_DRAW_POOL is
; 2 bytes each way.
obj_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_draw"
    jsr mo_hi_clear
    lda #MO_LARGE
    sta z:ES_MO_DRAW + MO_D_SIZE    ; everything below is a 16x16 actor. The HUD
                                    ;  clears this for itself (mo_score_digit),
                                    ;  and re-arms nothing: obj_draw sets it
                                    ;  every frame before the first mo_put, so
                                    ;  the two callers cannot leave it wrong
                                    ;  for
                                    ;  each other whatever order they run in.
    ; ---- the hero: pinned at screen centre, by the camera's construction --
    lda #(MO_CX - MO_HALF)
    sta z:ES_MO_DRAW + MO_D_X
    lda #(MO_CY - MO_HALF)
    sta z:ES_MO_DRAW + MO_D_Y
    ldx #(ES_O_HERO * 4)
    lda #MO_TA_HERO
    jsr mo_put
    ; ---- the chasers, then the bolts, both through the transpose ----------
    ; ca65 has NO line-continuation character, so a macro call is one line and
    ; the tile|attr words are named above rather than spelled inline.
    MO_DRAW_POOL MO_ENE_ALIVE, MO_ENE_WX, MO_ENE_WY, MO_ENE_N, ES_O_ENEMIES, MO_TA_ENEMY
    MO_DRAW_POOL MO_BUL_ALIVE, MO_BUL_WX, MO_BUL_WY, MO_BUL_N, ES_O_BULLETS, MO_TA_BULLET
    rts

; --- mo_score_digit: one 8x8 HUD digit into its pinned slot ----------------
; In: A16/I16, DB=0.
;  A = the digit value 0..9
;  X = the digit's INDEX in the readout (0 = leftmost)
; Out: clobbers A, X, Y.
;
; THE MECHANISM IS HERE, THE POLICY IS THE SCENE'S — the same split
; do_hit_blink is written against. This feature knows how to put an 8x8 glyph
; on screen; it does not know what a score is, how wide it is, or when it
; changes, and asking it would mean a feature reading the game's `[scene.*]`
; block, which is the inversion state.toml's header argues against.
;
; The size bit is cleared per digit rather than once around the loop, so a
; caller that interleaves digits with anything else cannot be caught out by it.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep here. Mo_put toggles A8
; internally for its two byte stores and restores A16, and PRESERVES X — which
; is what lets the digit index survive the call and become the x offset.
.assert MO_DIGIT_PITCH = 8, error, "the digit pitch is shifted, not multiplied — a non-8 pitch needs a different sequence here"
; CONTRACT mo_score_digit
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one score digit staged into its slot
;   clobbers: A, X, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
mo_score_digit:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mo_score_digit"
    pha                             ; the digit value, while X becomes the x
    txa
    .repeat 3
        asl                         ; index * 8 = MO_DIGIT_PITCH, by the assert
    .endrepeat
    clc
    adc #MO_SCORE_X
    sta z:ES_MO_DRAW + MO_D_X
    lda #MO_SCORE_Y
    sta z:ES_MO_DRAW + MO_D_Y
    stz z:ES_MO_DRAW + MO_D_SIZE    ; 8x8: the SMALL half of OBSEL size pair 0
    txa
    asl
    asl                             ; index * 4 = the slot's byte offset...
    clc
    adc #(ES_O_SCORE * 4)           ; ...within the score's pinned OAM window
    tax
    pla
    clc
    adc #MO_DIGIT_TILE              ; digit d draws with tile MO_DIGIT_TILE + d
    ora #((MO_PRIO | MO_PAL_SCORE) << 8)   ; ...at priority 3 under the score's
                                    ;  own palette band. The priority matters:
                                    ;  without it the HUD would sit behind the
                                    ;  affine plane, which covers the screen.
    jsr mo_put
    rts
