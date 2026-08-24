; =============================================================================
; platformer_obj.asm — the hero and the two patrol ghosts
; =============================================================================
; Three actors in four OAM slots. Everything is written into the oam_sprites
; SHADOW; hardware OAM belongs to that feature's declared VBlank GP-DMA.
;
; THE HI TABLE IS REBUILT WHOLE, NEVER PATCHED. A hi-table byte covers four
; sprites (2 bits each: bit 0 = X9, bit 1 = size) and this feature owns all
; four of the first byte's, so obj_draw zeroes it once a frame and obj_put ORs
; each actor's two bits in. A stale X9 renders a sprite 256 px away, which is
; the failure this project has a lessons-learned entry about — and here it is
; not hypothetical: a ghost's SCREEN x is its world x minus the camera, which
; goes negative the moment the patrol walks off the left of the view, and a
; negative screen x IS a set bit 8.

; The enter-time GP-DMA register file, addressed through the channel the obj_up
; dma_init claim names.
OBJ_REGS = $4300 + ES_D_OBJ_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE, so a re-sized
; shadow moves it.
OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
OBJ_HI_OURS = OBJ_HI_BASE + (ES_O_HERO / 4)

; Sprite attribute bits, and the OAM entry's high byte.
OBJ_PRIO   = $30                ; OBJ priority 3: in front of every BG layer
OBJ_HFLIP  = $40
OBJ_PAL0   = $00                ; the hero's palette, at CGRAM 128
OBJ_PAL1   = $02                ; the ghosts', at 144
OBJ_LARGE  = 2                  ; the hi-table SIZE bit (every actor is 16x16)
OBJ_PARK_Y = $F0                ; below the screen — where a dead or unused
                                ;  slot lives, and what oam_park_all wrote

; --- obj_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — re-armed HERE, per call, at the one arming site.
obj_up:
    .a16
    .i16
    stx a:OBJ_REGS + 2              ; A1T
    sty a:OBJ_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:OBJ_REGS + 4              ; A1B
    lda #ES_D_OBJ_UP_DMAP
    sta a:OBJ_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_OBJ_UP_BBAD
    sta a:OBJ_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_OBJ_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; --- obj_pal_up: 16 words from a ROM palette blob into CGRAM ----------------
; In: A16/I16, DB=0. A = CGRAM word index, ES_ESCR+2/+4 = the blob's 24-bit
;  address (low word / bank). Clobbers A, X.
obj_pal_up:
    .a16
    .i16
    sep #$20
    .a8
    sta a:$2121                     ; CGADD = the claim's base word
    rep #$20
    .a16
    ldy #0
:   .a16
    .i16
    lda [ES_ESCR + 2], y
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    iny
    iny
    cpy #(16 * 2)
    bcc :-
    rts

; --- obj_arm: the OBJ page, both palettes, OBSEL (scene enter) --------------
; CONTRACT platformer_obj::obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the OBJ page, both palettes and OBSEL
;   clobbers: A, X, Y, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    lda #^plf_obj_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116
    ldx #.loword(plf_obj_chr_bin)
    ldy #ES_R_PLF_OBJ_CHR_ROM_SIZE
    jsr obj_up
    ; ---- the two OBJ palettes ---------------------------------------------
    lda #.loword(plf_hero_pal_bin)
    sta z:ES_ESCR + 2
    sep #$20
    .a8
    lda #^plf_hero_pal_bin
    sta z:ES_ESCR + 4
    rep #$20
    .a16
    lda #ES_C_HERO_PAL
    jsr obj_pal_up
    lda #.loword(plf_ghost_pal_bin)
    sta z:ES_ESCR + 2
    sep #$20
    .a8
    lda #^plf_ghost_pal_bin
    sta z:ES_ESCR + 4
    rep #$20
    .a16
    lda #ES_C_GHOST_PAL
    jsr obj_pal_up
    ; ---- OBSEL: size mode 0 (8x8 / 16x16), OBJ chr base from the claim ----
    ; Every actor here is 16x16, so only the pair's large half is in use — but
    ; obj_put still writes the size bit per slot, because the byte is rebuilt
    ; whole and a bit left clear is a 16x16 sprite rendered as its top-left
    ; quarter.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr obj_park
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen ---
; CONTRACT platformer_obj::obj_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every slot this feature owns parked off the bottom of the
;             screen
;   clobbers: A, X, N, Z, C
;   assumes:  at enter, so a round starts with nothing stale on screen
;   tail:     rts
;
; nothing stale on screen) and at exit (so a menu, which draws no sprites at
; all, cannot show the last round's cast).
obj_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_park"
    ldx #(ES_O_HERO * 4)
:   .a16
    .i16
    lda #(OBJ_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) * 4)
    bcc :-
    stz a:OBJ_HI_OURS               ; small + X9 clear, as oam_park_all left it
    rts

; =============================================================================
; DRAWING — every slot, every frame
; =============================================================================
; --- obj_put: one OAM entry, plus its two hi-table bits ---------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  US_AX = x (bit 8 becomes X9), US_AY = y
; Out: X preserved. Clobbers A, Y.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED — see the file header for
; why that is load-bearing here rather than defensive.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one 2-byte pha/pla pair and
; one phx/plx pair, and every arm of the routine passes through both. A push
; taken in A16 and pulled in A8 would drift the stack by one byte per sprite.
obj_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:US_AY
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 cleared, next line)
    sep #$20
    .a8
    lda z:US_AX
    sta a:ES_OAM_SHADOW + 0, x      ; byte 0 = x's low eight bits
    rep #$20
    .a16
    ; ---- the hi-table field: 2 bits, at (slot & 3) * 2 ---------------------
    phx
    txa
    .repeat 2
        lsr
    .endrepeat
    and #3
    tay                             ; Y = which field within the byte
    lda z:US_AX
    xba
    and #1                          ; x bit 8 -> X9
    ora #OBJ_LARGE                  ; ...| the size bit: every actor is 16x16
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
    ora a:OBJ_HI_BASE, x            ; OR, not store: the other slots share this
    sta a:OBJ_HI_BASE, x            ;   byte and obj_draw cleared it once
    rep #$20
    .a16
    plx
    rts

; --- the per-frame feet lifts ----------------------------------------------
; Indexed by US_AFRAME * 2. WORDS rather than bytes because every read here is
; in A16 and a `.byte` table would hand back the next entry in the high half.
;
; ONE ENTRY PER ANIMATION FRAME, because an actor's frames do not share a sole
; and a single anchor is therefore wrong for at least one of them (see
; platformer.inc's "the feet anchor, PER FRAME"). This is the whole fix for
; both halves of the defect: the constant overlap (a uniform anchor at or below
; every frame's bottom) and the intermittent one (a uniform anchor that only
; the tallest frame sinks through).
plf_hero_feet:
    .word PLF_HERO_LIFT_F0, PLF_HERO_LIFT_F1
    .word PLF_HERO_LIFT_F2, PLF_HERO_LIFT_F3
plf_ghost_feet:
    .word PLF_GHOST_LIFT_F0, PLF_GHOST_LIFT_F1
    .word PLF_GHOST_LIFT_F2, PLF_GHOST_LIFT_F3

; --- obj_hero: the hero's entry, from the round's state ---------------------
; CONTRACT obj_hero
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the hero's entry staged from the round's state
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one
;   tail:     rts
;
; The 16x16 sprite is drawn over the 8x8 physics box: centred on it in x (box.x
; - 4) and FEET-ALIGNED in y from the frame's own lift, so the picture's soles
; sit on the last scanline above the surface the box rests on. Both offsets are
; in world space and the camera is subtracted after, which is what keeps the
; sprite and the level in step.
;
; THE BLINK IS A SKIPPED DRAW, not a moved sprite: obj_park has already put the
; slot off-screen this frame, so leaving it alone IS the invisible phase.
obj_hero:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_hero"
    lda z:US_HURT
    beq @draw
    and #PLF_BLINK
    bne @hidden                     ; the blink's off phase — leave it parked
@draw:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc z:ES_PLF_CAM
    sec
    sbc #(PLF_BOX / 2)              ; the 16-wide picture over the 8-wide box
    sta z:US_AX
    lda z:US_AFRAME
    asl                             ; -> the lift table's word offset
    tax
    lda z:US_PIXY
    sec
    sbc f:plf_hero_feet, x          ; ...feet-aligned on THIS FRAME's lift:
    sta z:US_AY                     ;   the box's bottom (US_PIXY + PLF_BOX)
                                    ;  is the surface, and the art's last
                                    ;  drawn row must land one scanline ABOVE
                                    ;  it -- an OBJ renders at OAM y + 1
    lda z:US_AFRAME
    asl                             ; frame f occupies tiles {2f, 2f+1, ...}
    clc
    adc #PLF_HERO_TILE
    ora #((OBJ_PRIO | OBJ_PAL0) << 8)
    ldx z:US_FACING
    beq @put
    ora #(OBJ_HFLIP << 8)           ; walking left -> mirror the picture
@put:
    .a16
    .i16
    ldx #(ES_O_HERO * 4)
    jsr obj_put
@hidden:
    .a16
    .i16
    rts

; --- obj_ghost: one ghost's entry ------------------------------------------
; CONTRACT obj_ghost
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one ghost's entry staged
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  US_AX = the ghost's world x, US_AY its world y and US_TMP2
;             the slot number are all set by the caller
;   tail:     rts
;
; In: A16/I16, DB=0. US_AX = the ghost's WORLD x, US_AY = its world y,
;  US_TMP2 = the slot number. Clobbers A, X, Y.
; The caller has already decided the ghost is alive; a dead one keeps the
; parked entry obj_park wrote.
obj_ghost:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "obj_ghost"
    lda z:US_AX
    sec
    sbc z:ES_PLF_CAM
    sec
    sbc #(PLF_BOX / 2)
    sta z:US_AX                     ; ...now SCREEN x, and it may be negative
    lda z:US_AFRAME
    asl                             ; -> the lift table's word offset
    tax
    lda z:US_AY
    sec
    sbc f:plf_ghost_feet, x         ; feet-aligned on THIS FRAME's lift, same
    sta z:US_AY                     ;   rule as the hero. The ghost's four
                                    ;  agree at 15, which is why anchoring it
                                    ;  on that alone put its hem ON the
                                    ;  surface line on EVERY frame: the
                                    ;  missing term is the OBJ's +1 scanline,
                                    ;  not the actor's content_bottom
    lda z:US_TMP2
    .repeat 2
        asl                         ; slot -> the shadow's byte offset
    .endrepeat
    tax
    lda z:US_AFRAME
    asl                             ; frame f occupies tiles {2f, 2f+1, ...}
    clc
    adc #PLF_GHOST_TILE
    ora #((OBJ_PRIO | OBJ_PAL1) << 8)
    jsr obj_put
    rts
