; =============================================================================
; bs_obj.asm — the boss fight's cast: ship, rain, HP HUD, shots
; =============================================================================
; Arming (once, at scene enter): one sprite sheet into OBJ VRAM, one OBJ
; palette into CGRAM, OBSEL, both pools cleared through `pool_init`. Drawing
; (every frame, from the scene's tick): the stable slot map — 0 player, 1-8
; attacks, 9-16 HP HUD, 17-20 shots — every slot emitted every frame, live at
; its position or parked at BS_PARK_Y, so slot identity is stable and a test
; reads an actor by slot rather than by searching OAM for a plausible sprite.
;
; NOTHING HERE PROJECTS. Every actor is SCREEN-space — the ship strafes in
; screen pixels and the attacks rain in screen pixels — so the draw is a
; store, not a transform — the one Mode 7 consumer on
; this rail is the floor, through m7_track/m7_affine.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED (mo_obj's discipline). On
; this rail no actor's x can exceed 236, so the bit is always 0 — but derived-
; not-assumed costs one AND and survives the day a spawn table changes. All six
; hi-table bytes are cleared at the top of the draw and rebuilt whole, which is
; why the three pad slots are claimed at all.

; The enter-time GP-DMA register file, addressed through the channel the
; bs_obj_up dma_init claim names — a declared resource, not a hard-coded 0.
BS_OBJ_REGS = $4300 + ES_D_BS_OBJ_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE.
BS_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; --- this feature's DP scratch (the bs_draw claim), named ------------------
BS_D_X    = 0                   ; 2 — the OAM x being placed (9-bit space)
BS_D_Y    = 2                   ; 2 — the OAM y being placed
BS_D_SIZE = 4                   ; 2 — the hi-table SIZE bit bs_put ORs in:
                                ;  BS_LARGE for the 16x16 player, 0 for
                                ;  the 8x8 cast (OBSEL size pair 0)
BS_D_TILE = 6                   ; 2 — tile|attr scratch for a computed tile
                                ;  (the player's iframe flash pick)

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; --- obj_arm: the sheet, the palette, OBSEL, both pools ---------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (the scene_mgr enter
; contract — which is why the CPU-side palette loop cannot be preempted by an
; NMI that is not armed yet). Clobbers A, X, Y.
;
; WITHOUT these uploads this feature renders COLOUR NOISE rather than nothing:
; OBJ VRAM and CGRAM 128.. Are random at power-on (rule 5), and an OAM entry
; pointing at them is a perfectly valid sprite made of garbage.
;
; DAS is SINGLE-SHOT — consumed by the transfer — so it is armed here, for this
; transfer. One sheet, one arming site.
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 for byte-wide channel
; registers and PPU ports, `sep #$20` only — I-width never moves. The
; `pool_init` calls require A16/I16 on both sides and contain no sep/rep
; (pool.asm's contract delta (a)) — a cross-file contract width_lint cannot
; see, so this marker carries it.
obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    lda #^bs_sprite_chr_bin
    sta a:BS_OBJ_REGS + 4           ; A1B = source bank
    lda #ES_D_BS_OBJ_UP_DMAP
    sta a:BS_OBJ_REGS + 0           ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_BS_OBJ_UP_BBAD
    sta a:BS_OBJ_REGS + 1           ; BBAD: VMDATAL, so B+1 = VMDATAH
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the sheet's base word
    ldx #.loword(bs_sprite_chr_bin)
    stx a:BS_OBJ_REGS + 2           ; A1T
    ldy #ES_R_BS_SPRITE_CHR_SIZE
    sty a:BS_OBJ_REGS + 5           ; DAS, armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_BS_OBJ_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)

    ; ---- the palette: sixteen words at OBJ palette 0 ----------------------
    lda #ES_C_SPRITE_PAL
    sta a:$2121                     ; CGADD = 128, the claim's contract
    rep #$20
    .a16
    ldx #0
@pal:
    .a16
    .i16
    lda f:bs_sprite_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BS_SPRITE_PAL_SIZE
    bcc @pal

    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + the OBJ name base -------------
    ; The base byte is the ALLOCATOR's encoding of the obj_chr claim (floored
    ; past the pinned Mode 7 region). Size pair 0 puts the 16x16 player in the
    ; pair's LARGE half, which is the bit bs_put sets per slot; every other
    ; actor is 8x8 in the small half.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr bs_actors_arm
    jsr obj_park
    rts

; --- bs_actors_arm: both pools, through the mechanism ----------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; The clear goes THROUGH `pool_init` (the array the spawn scans is the array
; the mechanism cleared); the parallel fields are NOT pre-filled — spawn-
; then-use, pool.asm's own header. The counts are boss.inc's single constants,
; which discharges pool's unenforced upper bound (delta (c)).
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep anywhere.
bs_actors_arm:
    .a16
    .i16
    POOL_BIND ES_BS_ACTORS_LONG + BS_ATK_ALIVE
    ldx #BS_ATK_N
    jsr pool_init
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx #BS_SHOT_N
    jsr pool_init
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen --
; In/out: A16/I16, DB=0. Clobbers A, X. Called at enter so the scene starts
; with nothing stale on screen; the masked re-init (the RESULT->RESET loop)
; re-enters through battle_init, and the per-frame draw re-parks dead slots, so
; enter-once suffices.
obj_park:
    .a16
    .i16
    ldx #(ES_O_PLAYER * 4)
@loop:
    .a16
    .i16
    lda #(BS_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) * 4)
    bcc @loop
    jsr bs_hi_clear
    rts

; --- bs_hi_clear: the six hi-table bytes this feature owns -----------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Twenty-four slots is exactly six bytes, every one owned whole — the reason
; the pad slots exist. Clearing before the draw is what lets bs_put OR its two
; bits in without inheriting last frame's X9 or SIZE (mo_hi_clear's
; stale-MO_LARGE lesson: the direction that hurts is an 8x8 rendered 16x16,
; sampling the three tiles after it).
;
; WIDTH-RISK: toggles A8 for the six byte stores and restores A16.
bs_hi_clear:
    .a16
    .i16
    sep #$20
    .a8
    stz a:BS_HI_BASE + 0
    stz a:BS_HI_BASE + 1
    stz a:BS_HI_BASE + 2
    stz a:BS_HI_BASE + 3
    stz a:BS_HI_BASE + 4
    stz a:BS_HI_BASE + 5
    rep #$20
    .a16
    rts

; =============================================================================
; DRAWING — every slot, every frame
; =============================================================================
; --- bs_put: one OAM entry, plus its two hi-table bits ---------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  ES_BS_DRAW+BS_D_X = the OAM x (9 bits; bit 8 becomes X9), +BS_D_Y = y,
;  +BS_D_SIZE = BS_LARGE or 0
; Out: X preserved. Clobbers A, Y.
;
; mo_put's body, byte for byte in mechanism: entry bytes 2-3 in one store, y
; into byte 1, x low eight into byte 0, then the two hi-table bits shifted to
; (slot & 3) * 2 and OR'd into a byte the per-frame clear zeroed.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one phx/plx pair and one
; pha/pla pair, every arm passes through both. A push taken in A16 and pulled
; in A8 drifts the stack one byte per sprite per frame.
bs_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:ES_BS_DRAW + BS_D_Y
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 written next)
    sep #$20
    .a8
    lda z:ES_BS_DRAW + BS_D_X
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
    lda z:ES_BS_DRAW + BS_D_X
    xba
    and #1                          ; x bit 8 -> X9 (derived, never assumed)
    ora z:ES_BS_DRAW + BS_D_SIZE    ; | the size bit the caller selected
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
    tay
    pla
    sep #$20
    .a8
    ora a:BS_HI_BASE, y             ; OR, not store: the other slots share this
    sta a:BS_HI_BASE, y             ;   byte and bs_hi_clear zeroed it once
    rep #$20
    .a16
    plx
    rts

; --- bs_park_slot: one slot, off-screen ------------------------------------
; In: A16/I16, DB=0. X = the slot's byte offset. Out: X preserved; clobbers A.
; A free actor keeps its slot but leaves the screen, so slot identity — and
; therefore sprite priority — is stable frame to frame whatever is visible.
bs_park_slot:
    .a16
    .i16
    lda #(BS_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    rts
