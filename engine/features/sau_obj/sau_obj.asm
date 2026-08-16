; =============================================================================
; sau_obj.asm — the saucer fight's cast: gunship, beam, HP HUD, shots, cards
; =============================================================================
; Arming (once, at scene enter): one sprite sheet into OBJ VRAM, one OBJ
; palette into CGRAM, OBSEL, the shot pool cleared through `pool_init`.
; Emitting (every frame, from the scene's draw): the stable slot map — 0
; gunship, 1-16 beam, 17-24 HP HUD, 25-28 shots, 29 thruster, 30-53 card cells,
; 54-55 pad — every slot emitted every frame, live at its position or parked at
; SAU_PARK_Y, so slot identity is stable and a test reads an actor by slot
; rather than by searching OAM for a plausible sprite.
;
; NOTHING HERE PROJECTS. Every actor is SCREEN-space — the gunship strafes in
; screen pixels, the beam segments stack at screen pixels and the beam column
; is locked to a screen x — so the emit is a store, not a transform — the one
; Mode 7 consumer on this rail is the floor, through m7_track/m7_affine.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED (mo_obj's discipline). On
; this rail no actor's x can exceed 236, so the bit is always 0 — but derived-
; not-assumed costs one AND and survives the day a card gets wider. All
; fourteen hi-table bytes are cleared at the top of the draw and rebuilt whole,
; which is why the two pad slots are claimed at all.

; The enter-time GP-DMA register file, addressed through the channel the
; sau_obj_up dma_init claim names — a declared resource, not a hard-coded 0.
SAU_OBJ_REGS = $4300 + ES_D_SAU_OBJ_UP_CH * 16

; The hi table is the last 32 bytes of the shadow claim, after the 128
; four-byte low entries. Derived from the claim's own SIZE.
SAU_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32

; The hi-table bytes this feature owns: slots 0..55 is exactly 14 bytes, with
; nothing left mid-byte. Derived from the claim set, so growing the card band
; without growing the pad is a build-time contradiction rather than a stale X9
; bit at runtime.
SAU_HI_BYTES = (ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) / 4
.assert (ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) .mod 4 = 0, error, "the sau_obj slot bands do not tile whole hi-table bytes"

; --- this feature's DP scratch (the sau_draw claim), named -----------------
SAU_D_X    = 0                  ; 2 — the OAM x being placed (9-bit space)
SAU_D_Y    = 2                  ; 2 — the OAM y being placed
SAU_D_SIZE = 4                  ; 2 — the hi-table SIZE bit sau_put ORs in:
                                ;  SAU_LARGE for the 16x16 gunship, 0 for
                                ;  the 8x8 cast (OBSEL size pair 0)
SAU_D_TILE = 6                  ; 2 — tile|attr scratch for a computed tile
                                ;  (the gunship's iframe flash pick, the
                                ;  thruster's phase pick, a glyph)

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; --- obj_arm: the sheet, the palette, OBSEL, the pool ----------------------
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
; `pool_init` call requires A16/I16 on both sides and contains no sep/rep
; (pool.asm's contract delta (a)) — a cross-file contract width_lint cannot
; see, so this marker carries it.
obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    lda #^sau_sprite_chr_bin
    sta a:SAU_OBJ_REGS + 4          ; A1B = source bank
    lda #ES_D_SAU_OBJ_UP_DMAP
    sta a:SAU_OBJ_REGS + 0          ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_SAU_OBJ_UP_BBAD
    sta a:SAU_OBJ_REGS + 1          ; BBAD: VMDATAL, so B+1 = VMDATAH
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the sheet's base word
    ldx #.loword(sau_sprite_chr_bin)
    stx a:SAU_OBJ_REGS + 2          ; A1T
    ldy #ES_R_SAU_SPRITE_CHR_SIZE
    sty a:SAU_OBJ_REGS + 5          ; DAS, armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_SAU_OBJ_UP_CH)
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
    lda f:sau_sprite_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SAU_SPRITE_PAL_SIZE
    bcc @pal

    ; ---- OBSEL: size pair 0 (8x8 / 16x16) + the OBJ name base -------------
    ; The base byte is the ALLOCATOR's encoding of the obj_chr claim (floored
    ; past the pinned Mode 7 region). Size pair 0 puts the 16x16 gunship in
    ; the pair's LARGE half, which is the bit sau_put sets per slot; every
    ; other actor is small.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr sau_pool_arm
    jsr obj_park
    rts

; --- sau_pool_arm: the shot pool, through the mechanism --------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; The clear goes THROUGH `pool_init` (the array the spawn scans is the array
; the mechanism cleared); the parallel fields are NOT pre-filled — spawn-
; then-use, pool.asm's own header. The count is saucer.inc's single constant,
; which discharges pool's unenforced upper bound (delta (c)).
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep anywhere.
sau_pool_arm:
    .a16
    .i16
    POOL_BIND ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE
    ldx #SAU_SHOT_N
    jsr pool_init
    rts

; --- obj_park: every slot this feature owns, off the bottom of the screen --
; In/out: A16/I16, DB=0. Clobbers A, X. Called at enter so the scene starts
; with nothing stale on screen; the masked re-init (the RESULT->RESET loop)
; re-enters through battle_init, and the per-frame draw re-parks every unused
; slot, so enter-once suffices.
obj_park:
    .a16
    .i16
    ldx #(ES_O_PLAYER * 4)
@slot:
    .a16
    .i16
    lda #(SAU_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_HI_PAD + ES_O_HI_PAD_SPRITES) * 4)
    bcc @slot
    jsr sau_hi_clear
    rts

; --- sau_hi_clear: the fourteen hi-table bytes this feature owns -----------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Fifty-six slots is exactly fourteen bytes, every one owned whole — the reason
; the pad slots exist. Clearing before the draw is what lets sau_put OR its two
; bits in without inheriting last frame's X9 or SIZE (mo_hi_clear's
; stale-MO_LARGE lesson: the direction that hurts is an 8x8 rendered 16x16,
; sampling the three tiles after it).
;
; WIDTH-RISK: toggles A8 for the byte stores and restores A16. X is used as the
; byte cursor and is CLOBBERED — every caller reloads it (the draw's callers
; all re-derive X from a slot index).
sau_hi_clear:
    .a16
    .i16
    sep #$20
    .a8
    ldx #0
@byte:
    .a8
    .i16
    stz a:SAU_HI_BASE, x
    inx
    cpx #SAU_HI_BYTES
    bcc @byte
    rep #$20
    .a16
    rts

; =============================================================================
; EMITTING — every slot, every frame
; =============================================================================
; --- sau_put: one OAM entry, plus its two hi-table bits --------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  ES_SAU_DRAW+SAU_D_X = the OAM x (9 bits; bit 8 becomes X9),
;  +SAU_D_Y = y, +SAU_D_SIZE = SAU_LARGE or 0
; Out: X preserved. Clobbers A, Y.
;
; bs_put's body, byte for byte in mechanism: entry bytes 2-3 in one store, y
; into byte 1, x low eight into byte 0, then the two hi-table bits shifted to
; (slot & 3) * 2 and OR'd into a byte the per-frame clear zeroed.
;
; WIDTH-RISK: pushes and pulls in A16/I16 only — one phx/plx pair and one
; pha/pla pair, every arm passes through both. A push taken in A16 and pulled
; in A8 drifts the stack one byte per sprite per frame.
sau_put:
    .a16
    .i16
    sta a:ES_OAM_SHADOW + 2, x      ; bytes 2,3: tile and attr, in one store
    lda z:ES_SAU_DRAW + SAU_D_Y
    xba
    and #$FF00
    sta a:ES_OAM_SHADOW + 0, x      ; byte 1 = y (byte 0 written next)
    sep #$20
    .a8
    lda z:ES_SAU_DRAW + SAU_D_X
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
    lda z:ES_SAU_DRAW + SAU_D_X
    xba
    and #1                          ; x bit 8 -> X9 (derived, never assumed)
    ora z:ES_SAU_DRAW + SAU_D_SIZE  ; | the size bit the caller selected
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
    ora a:SAU_HI_BASE, y            ; OR, not store: the other slots share this
    sta a:SAU_HI_BASE, y            ;   byte and sau_hi_clear zeroed it once
    rep #$20
    .a16
    plx
    rts

; --- sau_park_slot: one slot, off-screen -----------------------------------
; In: A16/I16, DB=0. X = the slot's byte offset. Out: X preserved; clobbers A.
; A free actor keeps its slot but leaves the screen, so slot identity — and
; therefore sprite priority — is stable frame to frame whatever is visible.
sau_park_slot:
    .a16
    .i16
    lda #(SAU_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x
    stz a:ES_OAM_SHADOW + 2, x
    rts

; --- sau_park_range: park Y consecutive slots from X ----------------------
; In: A16/I16, DB=0. X = the first slot's BYTE offset, Y = how many slots. Out:
; X advanced past the last one parked, Y = 0. Clobbers A.
;
; The card band's tail parks through this: whatever the current card did not
; use goes off-screen, so a six-glyph DEFEAT cannot leave the seventh glyph of
; a previous VICTORY on the display. `sau_park_slot` preserves both index
; registers, so the loop's cursor and counter both survive the call — which is
; why this reuses it instead of restating what "parked" means.
sau_park_range:
    .a16
    .i16
@park:
    .a16
    .i16
    cpy #0
    beq @done
    jsr sau_park_slot               ; X and Y preserved
    inx
    inx
    inx
    inx
    dey
    bra @park
@done:
    .a16
    .i16
    rts
