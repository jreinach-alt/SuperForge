; =============================================================================
; shmup_obj.asm — the ship, the bullets, the fighters, the bursts, and POOL
; =============================================================================
; CHR + palettes from the shmup_rom blobs; sixteen OAM slots from the four
; pinned oam claims. Positions are written every frame into the oam_sprites
; SHADOW — never into hardware OAM, which the engine's declared VBlank GP-DMA
; owns.
;
; POOL is the bottom half of this file: three fixed- slot pools over one WRAM
; claim, and a spawn/kill/init trio that is the whole of it. It needed no new
; claim class (`docs/09` §1.1 predicted exactly that) — a pool is an alive[]
; array plus parallel arrays and a scan, with no channel, no register and no
; VBlank cost for a class to describe.
;
; STABLE OAM SLOTS. Every pool slot is drawn EVERY frame — live actors at their
; position, dead slots parked at y=$F0 — so pool slot k is always OAM slot k
; and a test can name an actor by its OAM index. That is why obj_draw walks
; whole pools instead of compacting live ones to the front, and it is the
; property the whole test file is built on.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (shmup_obj/feature.toml's
; obj_obsel claim). Its VALUE comes from ES_V_OBJ_CHR_OBSEL_BASE.

OBJ_REGS = $4300 + ES_D_OBJ_UP_CH * 16

; The hi table is the last 32 B of the shadow claim, so its base is derived
; from the emitted size — the same expression oam_sprites uses.
OBJ_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
OBJ_HI_OURS = OBJ_HI_BASE + ES_O_SHIP / 4

; enter_scr's 8 B of enter-time scratch. +0..2 carries a blob's 24-bit address
; for the palette copy; the CHR upload uses +0 for its bank byte, and the two
; never overlap in time (obj_arm runs them in sequence).
OBJ_PAL_PTR = ES_ESCR + 4

; Hi-table 2-bit fields: bit 0 = X9, bit 1 = size (0 = small = OBSEL's 8x8, 1 =
; large = its 16x16). Named because "2" as a size is unreadable.
OBJ_SMALL = 0
OBJ_LARGE = 2

; THE PACKING THIS FILE DEPENDS ON, ASSERTED RATHER THAN ASSUMED. A hi-table
; byte covers four sprites, so writing our share as four WHOLE bytes is only
; correct while our sixteen slots ARE those four bytes. The allocator pins them
; that way (the `at` fields in feature.toml); if a future edit moves one, this
; stops the build instead of silently clearing another feature's sprite flags.
.assert ES_O_SHIP .MOD 4 = 0, error, "shmup_obj: the slot run must start a hi-table byte"
.assert ES_O_BULLETS = ES_O_SHIP + 1, error, "shmup_obj: bullets must follow the ship"
.assert ES_O_FOES = ES_O_BULLETS + ES_O_BULLETS_SPRITES, error, "shmup_obj: fighters must follow the bullets"
.assert ES_O_BURSTS = ES_O_FOES + ES_O_FOES_SPRITES, error, "shmup_obj: bursts must follow the fighters"
.assert (ES_O_BURSTS + ES_O_BURSTS_SPRITES - ES_O_SHIP) = 16, error, "shmup_obj: the slot run must be exactly four hi-table bytes"
.assert ES_SHM_POOLS_SIZE = SHM_POOL_BYTES, error, "shmup_obj: the pool region and shmup.inc's layout disagree"
.assert ES_R_SHM_FOE_PAL_ROM_SIZE = ES_R_SHM_SHIP_PAL_ROM_SIZE, error, "OBJ palettes must be the same size"
.assert ES_R_SHM_BURST_PAL_ROM_SIZE = ES_R_SHM_SHIP_PAL_ROM_SIZE, error, "OBJ palettes must be the same size"

; =============================================================================
; SCENE LIFECYCLE
; =============================================================================

; --- obj_pal_up: one 16-word OBJ palette, blob -> CGRAM ---------------------
; In: A16/I16, DB=0, forced blank. A = CGRAM word base,
;  OBJ_PAL_PTR = the blob's 24-bit address. Clobbers A, Y.
; Indirect because there are three blobs and the packer chooses their order — a
; routine per blob would be three copies of this loop to keep in step.
obj_pal_up:
    .a16
    .i16
    sep #$20
    .a8
    sta a:$2121                     ; CGADD = claim base
    ldy #0
:   .a8
    .i16
    lda [<OBJ_PAL_PTR], y
    sta a:$2122                     ; low byte
    iny
    lda [<OBJ_PAL_PTR], y
    sta a:$2122                     ; high byte
    iny
    cpy #ES_R_SHM_SHIP_PAL_ROM_SIZE
    bcc :-
    rep #$20
    .a16
    rts

; --- obj_pal_point: aim OBJ_PAL_PTR at a blob -------------------------------
; In: A16/I16. A = the blob's low 16 bits, X = its bank byte. Clobbers A.
obj_pal_point:
    .a16
    .i16
    sta z:OBJ_PAL_PTR
    txa
    sep #$20
    .a8
    sta z:OBJ_PAL_PTR + 2           ; the bank byte ALONE — a 16-bit store here
                                    ; would reach past enter_scr's 8 bytes
    rep #$20
    .a16
    rts

; --- obj_arm: CHR + the three palettes + OBSEL + parked entries -------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
obj_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_OBJ_CHR
    sta a:$2116                     ; VMADD = the obj chr claim's base
    lda #.loword(shm_obj_chr_bin)
    sta a:OBJ_REGS + 2              ; A1T
    lda #ES_R_SHM_OBJ_CHR_ROM_SIZE
    sta a:OBJ_REGS + 5              ; DAS (single transfer, armed here)
    sep #$20
    .a8
    lda #^shm_obj_chr_bin
    sta a:OBJ_REGS + 4              ; A1B
    lda #ES_D_OBJ_UP_DMAP
    sta a:OBJ_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_OBJ_UP_BBAD
    sta a:OBJ_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_OBJ_UP_CH)
    sta a:$420B                     ; fire
    rep #$20
    .a16
    ; ---- the three OBJ palettes -------------------------------------------
    lda #.loword(shm_ship_pal_bin)
    ldx #^shm_ship_pal_bin
    jsr obj_pal_point
    lda #ES_C_SHIP_PAL
    jsr obj_pal_up
    lda #.loword(shm_foe_pal_bin)
    ldx #^shm_foe_pal_bin
    jsr obj_pal_point
    lda #ES_C_FOE_PAL
    jsr obj_pal_up
    lda #.loword(shm_burst_pal_bin)
    ldx #^shm_burst_pal_bin
    jsr obj_pal_point
    lda #ES_C_BURST_PAL
    jsr obj_pal_up
    ; ---- OBSEL: size mode 0 (small 8x8 / large 16x16), OBJ chr base from the
    ; claim. BOTH halves are in use here — the bullet is small, everything else
    ; is large — so obj_put writes the hi table's size bits as well as its X9
    ; bits, and derives both rather than assuming either.
    sep #$20
    .a8
    lda #ES_V_OBJ_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    jsr obj_park                    ; every slot defined before the first DMA
    rts

; --- obj_park: hide all sixteen (scene exit, and enter's opening state) -----
; In/out: A16/I16, DB=0. Clobbers A, X. The scene that armed a slot re-parks
; it, so the next scene inherits the boot contract rather than this scene's
; sprites.
obj_park:
    .a16
    .i16
    ldx #(ES_O_SHIP * 4)
    lda #(PARK_Y << 8)              ; x = 0, y = $F0 (off the bottom)
:   .a16
    .i16
    sta a:ES_OAM_SHADOW + 0, x
    inx
    inx
    inx
    inx
    cpx #((ES_O_BURSTS + ES_O_BURSTS_SPRITES) * 4)
    bcc :-
    stz a:OBJ_HI_OURS + 0           ; small + X9 clear, as oam_park_all left it
    stz a:OBJ_HI_OURS + 2
    rts

; =============================================================================
; DRAWING — every slot, every frame
; =============================================================================

; --- obj_put: one OAM entry, plus its two hi-table bits ---------------------
; In: A16/I16, DB=0.
;  X = the slot's BYTE offset in the shadow (slot * 4)
;  A = tile | (attr << 8) — the entry's bytes 2 and 3
;  US_AX = x (bit 8 becomes X9), US_AY = y, US_TMP = OBJ_SMALL / OBJ_LARGE
; Out: X preserved. Clobbers A, Y.
;
; THE X9 BIT IS DERIVED EVERY FRAME, NEVER ASSUMED. An OAM X coordinate is nine
; bits and the ninth lives in the hi table; a stale one renders a sprite 256 px
; away, which is the failure this project has a lessons-learned entry about.
;
; NOTHING IN THIS RAIL ACTUALLY EXCEEDS x = 255 TODAY — the ship clamps at 224,
; the spawn table tops out at 216, and a bullet is the ship + 4. That is the
; reason to derive the bit rather than the reason not to: a shortcut that
; assumed bit 8 clear would pass every test in the file and ship a sprite 256
; px away the first time a coordinate grew. Deriving all sixteen X9 bits from
; the sixteen X values costs a shift and an OR each, and removes the assumption
; instead of documenting it (breaker_obj made the same call for four sprites).
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
    ora z:US_TMP                    ; ...| this actor class's size bit
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
    ora a:OBJ_HI_BASE, x            ; OR, not store: three other sprites share
    sta a:OBJ_HI_BASE, x            ;   this byte and obj_draw cleared it once
    rep #$20
    .a16
    plx
    rts

; --- obj_draw: the whole cast, into the shadow ------------------------------
; In/out: A16/I16, DB=0. Called from the scene's tick, every frame.
obj_draw:
    .a16
    .i16
    stz a:OBJ_HI_OURS + 0           ; obj_put ORs into these, so they start at
    stz a:OBJ_HI_OURS + 2           ;   zero exactly once per frame
    jsr obj_draw_ship
    jsr obj_draw_bullets
    jsr obj_draw_foes
    jmp obj_draw_bursts

; --- obj_draw_ship ----------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. The ship blinks through its
; i-frames: hidden while (hurt & BLINK_PHASE), so ~4 frames on, 4 off. Hidden
; means PARKED, not "skipped" — a skipped slot would keep last frame's position
; and freeze the ship mid-screen.
obj_draw_ship:
    .a16
    .i16
    lda z:US_HURT
    beq @show
    and #BLINK_PHASE
    beq @show
    stz z:US_AX
    lda #PARK_Y
    sta z:US_AY
    bra @put
@show:
    .a16
    .i16
    lda z:US_PX
    sta z:US_AX
    lda z:US_PY
    sta z:US_AY
@put:
    .a16
    .i16
    lda #OBJ_LARGE
    sta z:US_TMP
    lda z:US_AFRAME
    asl                             ; a 16x16 frame is two grid tiles wide
    clc
    adc #OBJ_SHIP
    ora #(OBJ_ATTR_SHIP << 8)
    ldx #(ES_O_SHIP * 4)
    jmp obj_put

; --- obj_draw_bullets -------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
obj_draw_bullets:
    .a16
    .i16
    ldx #0                          ; X = the slot's byte offset in the pool
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_BUL + SHM_ALIVE, x
    bne @live
    stz z:US_AX
    lda #PARK_Y
    sta z:US_AY
    bra @put
@live:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_BUL + SHM_PX, x
    sta z:US_AX
    lda f:ES_SHM_POOLS_LONG + SHM_BUL + SHM_PY, x
    sta z:US_AY
@put:
    .a16
    .i16
    phx
    lda #OBJ_SMALL                  ; the bullet is the one 8x8 actor
    sta z:US_TMP
    txa
    asl                             ; pool slot k*2 -> OAM slot k*4
    clc
    adc #(ES_O_BULLETS * 4)
    tax
    lda #(OBJ_BULLET | (OBJ_ATTR_FOE << 8))
    jsr obj_put
    plx
    inx
    inx
    cpx #(2 * SHM_BUL_N)
    bcc @one
    rts

; --- obj_draw_foes ----------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. All live fighters share this frame's
; animation step — one lookup, not four.
obj_draw_foes:
    .a16
    .i16
    ldx #0
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_FOE + SHM_ALIVE, x
    bne @live
    stz z:US_AX
    lda #PARK_Y
    sta z:US_AY
    bra @put
@live:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_FOE + SHM_PX, x
    sta z:US_AX
    lda f:ES_SHM_POOLS_LONG + SHM_FOE + SHM_PY, x
    sta z:US_AY
@put:
    .a16
    .i16
    phx
    lda #OBJ_LARGE
    sta z:US_TMP
    txa
    asl
    clc
    adc #(ES_O_FOES * 4)
    tax
    lda z:US_AFRAME
    asl
    clc
    adc #OBJ_FOE
    ora #(OBJ_ATTR_FOE << 8)
    jsr obj_put
    plx
    inx
    inx
    cpx #(2 * SHM_FOE_N)
    bcc @one
    rts

; --- obj_draw_bursts --------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. The burst frame steps from the
; slot's OWN timer — (BURST_LIFE - t) >> 2 walks the four explosion frames once
; — so two bursts started a frame apart are a frame apart, which one shared
; animation clock could not express.
obj_draw_bursts:
    .a16
    .i16
    ldx #0
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_BUR + SHM_ALIVE, x
    bne @live
    stz z:US_AX
    lda #PARK_Y
    sta z:US_AY
    stz z:US_TMP2                   ; frame 0: a dead slot's tile is never seen
    bra @put
@live:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_BUR + SHM_PX, x
    sta z:US_AX
    lda f:ES_SHM_POOLS_LONG + SHM_BUR + SHM_PY, x
    sta z:US_AY
    lda #BURST_LIFE
    sec
    sbc f:ES_SHM_POOLS_LONG + SHM_BUR + SHM_PT, x
    .repeat 2
        lsr                         ; frames elapsed / 4 -> frame index 0..3
    .endrepeat
    asl                             ; ...and a frame is two grid tiles wide
    sta z:US_TMP2
@put:
    .a16
    .i16
    phx
    lda #OBJ_LARGE
    sta z:US_TMP
    txa
    asl
    clc
    adc #(ES_O_BURSTS * 4)
    tax
    lda z:US_TMP2
    clc
    adc #OBJ_BURST
    ora #(OBJ_ATTR_BUR << 8)
    jsr obj_put
    plx
    inx
    inx
    cpx #(2 * SHM_BUR_N)
    bcc @one
    rts

; =============================================================================
; POOL — three fixed-slot pools over one WRAM claim
; =============================================================================
; A pool is (base, count): `alive[]` at base + SHM_ALIVE, and parallel arrays
; at base + SHM_PX / SHM_PY / SHM_PT, all indexed by the SAME byte offset. The
; caller holds that offset in X and indexes directly, so there is no per-field
; index arithmetic anywhere and every address is an offset into an
; allocator-emitted claim.
;
; WHY LONG ADDRESSING (`lda f:ES_SHM_POOLS_LONG, x`) rather than plain
; absolute: pinning the pools into a low game-array region would let bank-0
; absolute indexing reach them, but the claim's address is the allocator's to
; choose, so the code must not care which bank it lands in. One extra cycle
; per access, and the pools stop being a hidden constraint on the WRAM packer.

; --- shm_pool_init: every slot of every pool is free ------------------------
; In/out: A16/I16, DB=0. Clobbers A, X. Called from the scene's enter, before
; any tick runs. Writes the WHOLE stride of each alive array, not just the
; slots in use, so the arrays are defined end to end. The parallel arrays are
; deliberately NOT touched: a slot's position is written by spawn-then-use, and
; pre-filling it would hide a "spawn forgot to set y" defect behind a plausible
; zero.
shm_pool_init:
    .a16
    .i16
    ldx #0
:   .a16
    .i16
    lda #0                          ; (stz has no long addressing mode)
    sta f:ES_SHM_POOLS_LONG + SHM_BUL + SHM_ALIVE, x
    sta f:ES_SHM_POOLS_LONG + SHM_FOE + SHM_ALIVE, x
    sta f:ES_SHM_POOLS_LONG + SHM_BUR + SHM_ALIVE, x
    inx
    inx
    cpx #SHM_STRIDE
    bcc :-
    rts

; --- shm_pool_spawn: claim the first free slot ------------------------------
; In: A16/I16, DB=0. X = the pool's base offset, Y = its slot COUNT. Out: A = X
; = the claimed slot's offset INTO THE CLAIM (base + slot*2), so
;  `sta f:ES_SHM_POOLS_LONG + SHM_PX, x` writes that slot's x directly.
;  A = SHM_POOL_FULL when every slot is live — branch with `bmi`, since a
;  real offset is always positive. Clobbers A, X, Y.
; The slot is marked live before returning, so a caller that spawns and then
; forgets to fill the parallel arrays leaks a slot rather than double-claiming.
shm_pool_spawn:
    .a16
    .i16
@scan:
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @found
    inx
    inx
    dey
    bne @scan
    lda #SHM_POOL_FULL
    rts
@found:
    .a16
    .i16
    lda #1
    sta f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    txa
    rts

; --- shm_pool_kill: free the slot at the offset in X ------------------------
; In/out: A16/I16, DB=0. X preserved, A clobbered (`stz` has no long form, so
; freeing a slot costs the accumulator — the iteration idiom keeps its cursor
; in X for exactly this reason).
shm_pool_kill:
    .a16
    .i16
    lda #0
    sta f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    rts
