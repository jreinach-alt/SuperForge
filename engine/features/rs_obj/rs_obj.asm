; =============================================================================
; rs_obj.asm — the railshooter's OBJ surface: the pinhole projection, the
;  depth-sorted emit, and the twelve slots they fill
; =============================================================================
; Three things live here, and they are one thing: the rail's whole visible
; foreground.
;
;  1. rs_project a pinhole (1/z) world->screen map through a baked LUT,
;  FULLY DECOUPLED from the Mode 7 affine matrix
;  2. rs_draw a two-pass depth-sorted emit: project every hazard once
;  into a cache, then walk size tier 0..3 filling OAM slots
;  1..6 so nearer hazards take LOWER slots and draw in FRONT
;  3. rs_obj_arm the enter-time CHR/palette/OBSEL/park
;
; All entry layout math is assemble-time expressions over emitted symbols; the
; OBSEL name base is the allocator's ES_V_RS_CHR_OBSEL_BASE, so the "OBJ over
; Mode 7" gotcha — the map owns VRAM words $0000-$3FFF, so the OBJ base must be
; floored past it — is discharged by the claim rather than by a hand-narrated
; mask.

RS_OBJ_REGS = $4300 + ES_D_RS_OBJ_UP_CH * 16

; --- the projection LUT's shape, DERIVED from the claims --------------------
; The generator bakes 81 buckets of 8 world px each. Deriving the count from
; the claim's size rather than repeating it is what keeps a regenerated LUT and
; this code from disagreeing silently.
RS_PROJ_Q_LOG2 = 3                              ; bucket = z >> this
RS_PROJ_N      = ES_R_RS_PROJ_SCAN_SIZE
.assert 2 * RS_PROJ_N = ES_R_RS_PROJ_SCALE_SIZE, error, "the two projection LUT halves disagree on bucket count"
.assert ((RS_Z_FAR >> RS_PROJ_Q_LOG2) + 1) = RS_PROJ_N, error, "RS_Z_FAR disagrees with the projection LUT's bucket count"

; --- the DP call frame (the rs_draw claim), named -------------------------
; +14..+23 are the multiply's, and they are DEAD once rs_project returns — so
; rs_put reuses two of them for its own parameters rather than claiming more.
RSD_OBJX  = ES_RS_DRAW + 0          ; in:  s16 world x
RSD_Z     = ES_RS_DRAW + 2          ; in:  u16 forward depth, world px
RSD_CAMX  = ES_RS_DRAW + 4          ; in:  s16 camera world x
RSD_SX    = ES_RS_DRAW + 6          ; out: s16 screen x (the CENTRE)
RSD_SY    = ES_RS_DRAW + 8          ; out: screen scanline, in the low byte
RSD_TIER  = ES_RS_DRAW + 10         ; out: raw size tier 0..3 from z
RSD_CULL  = ES_RS_DRAW + 12         ; out: 0 visible, non-zero culled
RSD_MA    = ES_RS_DRAW + 14         ; 4 B: multiplicand, shifted LEFT
RSD_MB    = ES_RS_DRAW + 18         ; 2 B: multiplier, shifted RIGHT to zero
RSD_ACC   = ES_RS_DRAW + 20         ; 4 B: the product
RSD_IDX   = ES_RS_DRAW + 24         ; the pool/cache cursor, a byte offset
RSD_PASS  = ES_RS_DRAW + 26         ; pass 2's current tier 0..3
RSD_TMP   = ES_RS_DRAW + 28         ; a cache pointer / scratch
RSD_EMIT  = ES_RS_DRAW + 30         ; pass 2's OAM cursor within the window
; --- the redesign's additions --------------------------------------
RSD_RSX   = ES_RS_DRAW + 32         ; the AIM POINT's projected screen centre,
RSD_RSY   = ES_RS_DRAW + 34         ;   held from the projection pass to the
RSD_RVIS  = ES_RS_DRAW + 36         ;   screen-space hitscan and then the draw
RSD_KIND  = ES_RS_DRAW + 38         ; pass 1: which pool is being cached
RSD_STK   = ES_RS_DRAW + 40         ; pass 2: the pylon window's OAM cursor
RSD_CUR   = ES_RS_DRAW + 42         ; pass 1: the cache byte offset being written
RSD_HIDX  = ES_RS_DRAW + 44         ; the HUD's digit cursor...
RSD_HREM  = ES_RS_DRAW + 46         ;   ...the score's running remainder,
RSD_HDIV  = ES_RS_DRAW + 48         ;   ...the power of ten being extracted,
RSD_HVAL  = ES_RS_DRAW + 50         ;   ...and the digit it produced
RSD_PSEG  = ES_RS_DRAW + 52         ; the pylon stack's segments-left counter,
RSD_PSTEP = ES_RS_DRAW + 54         ;   and its per-segment height. BOTH LIVE
                                    ;  ACROSS AN rs_put CALL, which is why
                                    ;  they are here and not in RSD_TMP/ACC --
                                    ;  see rs_put's clobber list
RSD_PTILE = RSD_MA + 0              ; rs_put's tile   (aliases the dead MA)
RSD_PATTR = RSD_MA + 2              ; rs_put's attr|size

; --- the cache: 4 words per PROJECTED ACTOR ---------------------------------
; Hazards occupy entries 0..RS_OBS_N-1 and pylons the RS_PYL_N after them, so a
; cache entry's index maps back to a pool slot by subtraction — which is what
; lets the hitscan go from "the aim point is inside THIS box" to "free THAT
; pool slot" without a second search.
;
; RSC_VIS IS A KIND, NOT A BOOLEAN: 0 = nothing to draw, 1 = hazard, 2 = pylon.
; One word carries both facts because the emit needs both and the cache stride
; is what the (cheap) index arithmetic is built on.
RSC_SX     = 0                      ; the already-centre-adjusted LEFT x
RSC_SY     = 2                      ; the ground point, and the sprite's top
RSC_TIER   = 4                      ; the STORED (hysteresis-applied) tier
RSC_VIS    = 6                      ; 0 dead/culled, 1 hazard, 2 pylon
RSC_STRIDE = 8
RSC_KIND_HAZ = 1
RSC_KIND_PYL = 2
RSC_PYL0   = RSC_STRIDE * RS_OBS_N  ; where the pylon entries start
.assert RSC_STRIDE * (RS_OBS_N + RS_PYL_N) = ES_RS_CACHE_SIZE, error, "rs_cache is not (hazards + pylons) x 4 words"

; --- OAM addressing ----------------------------------------------------------
; The window starts at the RETICLE now: OAM index order is priority and the
; crosshair has to be in front of the things it is aiming at.
RS_OAM_ENTRY = ES_OAM_SHADOW + ES_O_RS_RETICLE * 4
RS_OAM_HI    = ES_OAM_SHADOW + OAM_LOW_BYTES + (ES_O_RS_RETICLE >> 2)
RS_HI_BYTES  = RS_OAM_N / 4
.assert ES_O_RS_RETICLE = 0, error, "rs_obj assumes its OAM window starts at slot 0"
.assert ES_O_RS_PYLONS + ES_O_RS_PYLONS_SPRITES = RS_OAM_N, error, "the OAM window's end disagrees with the last claim"
; EVERY sub-window is tied to its allocator claim, not just the ends. The slot
; numbers in railshooter.inc are DERIVED (base + count arithmetic) while the
; claims are DECLARED with `at =`, so the two can silently disagree -- and OAM
; index order IS draw priority here, so a disagreement is a wrong-priority bug
; that renders, rather than a build error. Reordering the window (
; moved the HUD in front of the pylons) is exactly when that happens.
.assert RS_OAM_BURST   = ES_O_RS_BURST,   error, "RS_OAM_BURST drifted from the rs_burst claim"
.assert RS_OAM_SHIP    = ES_O_RS_SHIP,    error, "RS_OAM_SHIP drifted from the rs_ship claim"
.assert RS_OAM_HAZARDS = ES_O_RS_HAZARDS, error, "RS_OAM_HAZARDS drifted from the rs_hazards claim"
.assert RS_OAM_SHOTS   = ES_O_RS_SHOTS,   error, "RS_OAM_SHOTS drifted from the rs_shots claim"
.assert RS_OAM_SCORE   = ES_O_RS_HUD,     error, "RS_OAM_SCORE drifted from the rs_hud claim"
.assert RS_OAM_PYLONS  = ES_O_RS_PYLONS,  error, "RS_OAM_PYLONS drifted from the rs_pylons claim"
.assert (RS_OAM_N & 3) = 0, error, "the rs_obj OAM window is not a whole number of hi-table bytes"

; =============================================================================
; rs_obj_arm — CHR + both OBJ palettes + OBSEL + a parked window (scene enter)
; =============================================================================
; CONTRACT rs_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the sheets, the palettes and OBSEL
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract, which is also what keeps a CPU-side palette loop
;             from being preempted by an NMI that is not armed yet.
;             Without these uploads the feature renders COLOUR NOISE
;             rather than nothing: OBJ VRAM and CGRAM 128.. are random at
;             power-on (rule 5), and an entry pointing at them is a
;             perfectly valid sprite made of garbage
;   tail:     rts
;
; WIDTH-RISK: A16/I16 entry AND exit; toggles A8 for the byte ports and
; restores A16 before rts. I is never touched. The cross-file caller (the
; scene's enter) is checked against the CONTRACT block above.
rs_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rs_obj_arm"
    ; ---- CHR -> the obj chr claim (word port, DMA mode 1) -----------------
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_RS_CHR
    sta a:$2116                     ; VMADD = the claim base (past the M7 map)
    lda #.loword(rs_obj_chr_bin)
    sta a:RS_OBJ_REGS + 2           ; A1T
    lda #ES_R_RS_OBJ_CHR_SIZE
    sta a:RS_OBJ_REGS + 5           ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #^rs_obj_chr_bin
    sta a:RS_OBJ_REGS + 4           ; A1B
    lda #ES_D_RS_OBJ_UP_DMAP
    sta a:RS_OBJ_REGS + 0           ; DMAP: A->B, 2 regs (word port)
    lda #ES_D_RS_OBJ_UP_BBAD
    sta a:RS_OBJ_REGS + 1           ; BBAD: VMDATAL
    lda #(1 << ES_D_RS_OBJ_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs free)
    ; ---- palettes: OBJ 0 then OBJ 1, one contiguous CGRAM walk -------------
    ; The blob is the two palettes back to back and the claims are adjacent by
    ; hardware contract (128 and 144), so CGADD's auto-increment carries the
    ; walk straight from one into the other.
    lda #ES_C_RS_SHIP_PAL
    sta a:$2121                     ; CGADD = 128
    rep #$20
    .a16
    ldx #0
:   .a16
    .i16
    lda f:rs_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_RS_OBJ_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 3 (16x16 small / 32x32 large) | the emitted base -
    ; Mode 3 is what this rail's art needs: the two near hazard tiers and the
    ; ship are 32x32, the two far tiers, the bullet and the reticle are 16x16.
    sep #$20
    .a8
    lda #(3 << 5) | ES_V_RS_CHR_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    ; ---- park the whole window before the first VBlank DMA ----------------
    jsr rs_obj_disarm
    rts

; =============================================================================
; rs_obj_disarm — park every claimed slot off-screen and clear the hi table.
; =============================================================================
; CONTRACT rs_obj_disarm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every slot this feature owns parked
;   clobbers: A, X, N, Z, C
;   assumes:  it is also the first act of every rs_draw, which is what
;             keeps a slot that stopped being drawn from lingering
;   tail:     rts
;
; makes the hi table REBUILT rather than patched: a stale X9 renders a sprite
; 256 px away, and that is a failure this project has a lessons-learned entry
; about.
;
; WIDTH-RISK: A16/I16 entry AND exit; A8 for the byte stores, I16 throughout.
rs_obj_disarm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rs_obj_disarm"
    sep #$20
    .a8
    ldx #0
@park:
    .a8
    .i16
    stz a:RS_OAM_ENTRY + 0, x       ; x
    lda #RS_PARK_Y
    sta a:RS_OAM_ENTRY + 1, x       ; y — fully off a 224-line frame
    stz a:RS_OAM_ENTRY + 2, x       ; tile
    stz a:RS_OAM_ENTRY + 3, x       ; attr
    inx
    inx
    inx
    inx
    cpx #(RS_OAM_N * 4)
    bcc @park
    ldx #0
@hi:
    .a8
    .i16
    stz a:RS_OAM_HI, x              ; X9 = 0, size = small, whole-byte rebuild
    inx
    cpx #RS_HI_BYTES
    bcc @hi
    rep #$20
    .a16
    rts

; =============================================================================
; rs_mul — unsigned 16x16 -> 32, shift-add, sized to the operands
; =============================================================================
; In: A16/I16. RSD_MA = the multiplicand (low word set, high word zeroed),
;  RSD_MB = the multiplier. Out: RSD_ACC = the 32-bit product.
;
; NO HARDWARE MULTIPLIER, and the reason is m7_project's, taken again at the
; same size: `$4202/$4203` is an 8x8 unsigned multiply whose two entry points
; destroy each other's state, so a signed 16x16 on it costs four products plus
; sign plumbing AND a whole-scene `ALU` claim. This rail runs ELEVEN products a
; frame (six hazards + four shots + the reticle) — "neither unavoidable nor
; rare" fails on both counts.
;
; The loop runs once per SET bit of the multiplier and stops as soon as the
; remaining bits are zero, so the caller puts the SMALLER operand in MB. Here
; that is |dx| — a lane offset, typically under 64 — against a scale that can
; reach twelve bits.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label carries the
; annotation and every arrival is A16/I16.
rs_mul:
    .a16
    .i16
    stz RSD_ACC + 0
    stz RSD_ACC + 2
@step:
    .a16
    .i16
    lda RSD_MB
    beq @done
    lsr a
    sta RSD_MB
    bcc @shift                      ; the bit that fell out of MB
    clc
    lda RSD_ACC + 0
    adc RSD_MA + 0
    sta RSD_ACC + 0
    lda RSD_ACC + 2
    adc RSD_MA + 2
    sta RSD_ACC + 2
@shift:
    .a16
    .i16
    asl RSD_MA + 0
    rol RSD_MA + 2
    bra @step
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_project — the pinhole (1/z) map: world -> screen, through the baked LUT
; =============================================================================
; In: A16/I16, DB=0. RSD_OBJX = the object's lateral world x, RSD_Z = its
;  forward depth in WORLD PIXELS ahead of the camera, RSD_CAMX = the
;  camera's world x.
; Out: RSD_SX = the object's screen CENTRE x (signed), RSD_SY = its scanline,
;  RSD_TIER = its raw size tier from z, RSD_CULL = 0 when visible.
;  A, X, Y clobbered.
;
;  bucket = z >> RS_PROJ_Q_LOG2
;  screen_y = rs_proj_scan[bucket] (= HORIZON + CAM_H*256/z)
;  scale = rs_proj_scale[bucket] (= FOCAL*256/z, a .8)
;  screen_x = 128 + ((obj_x - cam_x) * scale) >> 8
;
; THE DELTA IS WRAP-AWARE, and the obvious form is not. Subtract two raw world
; x values and, with a camera that strafes freely around a 1024-px wrapping
; world, an obstacle 20 px to the left across the seam reads as 1004 px to the
; right and flies off screen. Folding the difference into [-512, 512) costs
; one `and` and one compare and makes the strafe safe anywhere on the rail.
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 ONLY around the byte-wide
; scanline table read (`sep #$20` alone, never `sep #$30`, because X is live
; across it). Every multi-path label is annotated.
rs_project:
    .a16
    .i16
    ; ---- the z culls: at the camera, or past the far edge ------------------
    ; They hop through `@cull_far` rather than branching straight to `@cull`:
    ; the routine's tail is over 127 bytes away from here, so a direct relative
    ; branch is a RANGE ERROR — a build refusal, not a silent one, and the
    ; three-byte trampoline is the whole cost of keeping it that way.
    lda RSD_Z
    beq @cull_far
    cmp #(RS_Z_FAR + 1)
    bcc @z_ok                       ; else past the far edge, or a wrapped-
                                    ;   negative z, and neither can be drawn
@cull_far:
    .a16
    .i16
    jmp @cull
@z_ok:
    .a16
    .i16
    ; ---- the raw size tier from z (nearer = bigger) ------------------------
    ldx #0                          ; tier 0 default: nearest / largest
    cmp #RS_TIER_T0
    bcc @have_tier
    inx
    cmp #RS_TIER_T1
    bcc @have_tier
    inx
    cmp #RS_TIER_T2
    bcc @have_tier
    inx                             ; tier 3: farthest / smallest
@have_tier:
    .a16
    .i16
    stx RSD_TIER
    ; ---- bucket = z / Q (a power of two, so shifts) ------------------------
    lda RSD_Z
    .repeat RS_PROJ_Q_LOG2
    lsr a
    .endrepeat
    cmp #RS_PROJ_N
    bcc @bucket_ok
    lda #(RS_PROJ_N - 1)            ; z == Z_FAR lands one past the last bucket
@bucket_ok:
    .a16
    .i16
    tax
    ; ---- screen_y = rs_proj_scan[bucket] (a byte table) --------------------
    sep #$20
    .a8
    lda f:rs_proj_scan_bin, x
    rep #$20
    .a16
    and #$00FF
    sta RSD_SY
    ; ---- scale = rs_proj_scale[bucket] (a word table) -> the multiplicand --
    txa
    asl a
    tax
    lda f:rs_proj_scale_bin, x
    sta RSD_MA + 0
    stz RSD_MA + 2
    ; ---- dx = obj_x - cam_x, folded into [-512, 512) ----------------------
    lda RSD_OBJX
    sec
    sbc RSD_CAMX
    and #RS_WORLD_MASK              ; the wrap: 0..1023
    cmp #(RS_WORLD_PX / 2)
    bcc @dx_signed
    sec
    sbc #RS_WORLD_PX                ; the short way round is to the left
@dx_signed:
    .a16
    .i16
    ; ---- |dx| into the multiplier; remember the sign in X -----------------
    ; THE SIGN TEST IS A `cmp`, NOT A `bpl`, AND THAT IS LOAD-BEARING: `ldx #0`
    ; sets N and Z from the value LOADED, so a `bpl` after it always branches
    ; and every leftward dx would take the positive path. Measured: hazards in
    ; the left lanes cached sx = 24,925 instead of 96 (emulator dump,
    ; 2026-08-08 — the arithmetic was right and the flag was somebody else's).
    ldx #0                          ; assume positive
    cmp #(1 << 15)                  ; carry set = the sign bit is set
    bcc @dx_abs
    eor #$FFFF
    inc a
    ldx #1                          ; X = "negate the product"
@dx_abs:
    .a16
    .i16
    sta RSD_MB
    phx                             ; the sign, across the multiply
    jsr rs_mul
    plx
    ; ---- screen_x = 128 +/- (product >> 8) --------------------------------
    ; (product >> 8) is the 16-bit word at ACC+1: low = bits 15:8, high =
    ; 23:16.
    lda RSD_ACC + 1
    cpx #0
    beq @sx_pos
    eor #$FFFF
    inc a
@sx_pos:
    .a16
    .i16
    clc
    adc #RS_SCREEN_HALF                  ; the screen's centre column
    sta RSD_SX
    ; ---- the LATERAL cull, and it is not defensive padding ----------------
    ; OAM x is NINE BITS: a left edge outside [-256, 255] is stored modulo 512
    ; and the PPU draws the sprite on the OTHER SIDE of the screen. Under the
    ; shipped projection the lateral gain was low enough that the fold was
    ; rarely reached; under the GROUND LOCK the gain is the plane's own
    ; (FOCAL/z = 3.3 screen px per world px at the bottom row, up from 1.8),
    ; and it IS reached. MEASURED on the first locked build: a pylon projected
    ; to sx = -350, was stored as +162, and swept back across the frame a
    ; second time — zero jumps in the same trace after this cull, against four.
    ; So an actor whose CENTRE is far enough outside the frame that no pixel of
    ; it could show is culled instead of folded.
    ;
    ; ONE unsigned compare does both edges: bias by the widest centre offset,
    ; and anything below that wraps to a large unsigned word, so it fails the
    ; same `cmp` the right edge does. The span is the screen plus BOTH centre
    ; offsets, which is the tightest bound one compare can carry over two
    ; sprite widths: a 16-px frame keeps its whole legal left range, and the
    ; only thing given up is a 32-px frame with 8 px or less still showing at
    ; the extreme right edge — 8 px of one sprite against a sprite drawn on the
    ; wrong side of the screen.
    clc
    adc #RS_CENTRE_32
    cmp #(RS_SCREEN_W + RS_CENTRE_32 + RS_CENTRE_16)
    bcs @cull
    stz RSD_CULL                    ; visible
    rts
@cull:
    .a16
    .i16
    lda #1
    sta RSD_CULL
    stz RSD_SX
    lda #RS_PARK_Y
    sta RSD_SY
    lda #RS_TIER_FAR
    sta RSD_TIER
    rts

; =============================================================================
; rs_put — write ONE sprite into the OAM shadow, with its hi-table bits
; =============================================================================
; In: A16/I16, DB=0. X = the OAM slot index. RSD_PTILE = the tile number,
;  RSD_PATTR = the attribute byte OR RS_SIZE_LARGE, RSD_SX = the sprite's
;  signed screen LEFT x, RSD_SY = its screen y.
; Out: A16/I16. A, X, Y clobbered.
;
; IT ALSO CLOBBERS RSD_ACC AND RSD_TMP, and that is not a footnote: a caller
; that emits SEVERAL sprites in a loop and parks its counter in either of them
; gets a counter of scrap, runs the loop an arbitrary number of times, and
; walks `rs_put` straight off the end of the OAM shadow into whatever WRAM the
; allocator put next. Measured, because it happened: the pylon stack's segment
; counter lived in RSD_TMP, the first pylon spawn at frame 128 flattened the
; rail's whole declared-state block, and the symptom looked like "the long
; stores never landed" three regions away from the cause. A multi-sprite caller
; keeps its cursors in DP the emit owns (RSD_PSEG / RSD_PSTEP / RSD_STK).
;
; THE HI TABLE IS ORed, NOT ASSIGNED, and the whole table was zeroed at the top
; of rs_draw — so the two bits per sprite are REBUILT every frame rather than
; read-modify-written around bits belonging to a neighbour.
;
; X9 IS SET FOR EVERY SPRITE, NOT JUST THE ONES THAT LOOK OFF-SCREEN. OAM x is
; nine bits; a hazard fanning out past the left edge has a negative left x, and
; without X9 its low byte wraps to a small positive number and the sprite
; renders on the RIGHT of the screen instead of being clipped off the left.
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 for the byte stores with `sep
; #$20` alone (X is live across the whole section) and restores A16 before
; rts. Every label is annotated.
rs_put:
    .a16
    .i16
    stx RSD_ACC                     ; the slot index — wanted twice, and both
                                    ;  uses must happen while A is 16 bits
    txa
    asl a
    asl a
    tay                             ; Y = the entry's byte offset (slot * 4)
    ; ---- the hi-table bits: bit (2k) = X9, bit (2k+1) = size --------------
    lda RSD_SX
    and #(1 << 8)                   ; bit 8 of the 9-bit x
    beq :+
    lda #1                          ; X9
:   .a16
    .i16
    sta RSD_TMP
    lda RSD_PATTR
    and #RS_SIZE_LARGE
    beq :+
    lda RSD_TMP
    ora #2                          ; the size select rides the same pair
    sta RSD_TMP
:   .a16
    .i16
    ; shift the pair into this slot's position: (slot & 3) * 2
    lda RSD_ACC
    and #3
    beq @hi_placed
    tax
@hi_shift:
    .a16
    .i16
    asl RSD_TMP
    asl RSD_TMP
    dex
    bne @hi_shift
@hi_placed:
    .a16
    .i16
    ; ---- the hi-table BYTE index, computed here and not in the A8 section --
    ; `tya`/`tax` in A8/I16 move the FULL 16-bit C, so a stale high byte would
    ; index the shadow 256 bytes away. Both index computations therefore finish
    ; while A is still 16 bits — the same rule rc_kart's speed-bar loop
    ; carries.
    lda RSD_ACC
    lsr a
    lsr a
    tax                             ; X = slot >> 2
    sep #$20
    .a8
    ; ---- the four entry bytes ---------------------------------------------
    lda RSD_SX                      ; low byte of the 9-bit x
    sta a:RS_OAM_ENTRY + 0, y
    lda RSD_SY
    sta a:RS_OAM_ENTRY + 1, y
    lda RSD_PTILE
    sta a:RS_OAM_ENTRY + 2, y
    lda RSD_PATTR
    sta a:RS_OAM_ENTRY + 3, y
    ; ---- OR the hi pair into this slot's byte -----------------------------
    lda RSD_TMP
    ora a:RS_OAM_HI, x
    sta a:RS_OAM_HI, x
    rep #$20
    .a16
    rts

; =============================================================================
; the per-tier OAM descriptors: {tile, attr|size, centre_off}
; =============================================================================
; Four rows each, tier 0 (nearest / largest) to tier 3 (farthest / smallest).
; The SNES cannot scale a sprite, so an object "grows" by swapping between
; these PRE-DRAWN frames as its z falls — the rail's second lesson, and the
; reason the tier hysteresis in rs_logic exists at all.
;
; The two tables share a SHAPE so one row-offset computation (tier * 6) serves
; both, and they share their centre offsets so the projection's centre->left
; adjustment does not have to know which pool it is caching.
rs_tier_tab:
    .word RS_T_HAZ_T0, (RS_ATTR_PRI | RS_ATTR_PAL1 | RS_SIZE_LARGE), RS_CENTRE_32
    .word RS_T_HAZ_T1, (RS_ATTR_PRI | RS_ATTR_PAL1 | RS_SIZE_LARGE), RS_CENTRE_32
    .word RS_T_HAZ_T2, (RS_ATTR_PRI | RS_ATTR_PAL1), RS_CENTRE_16
    .word RS_T_HAZ_T3, (RS_ATTR_PRI | RS_ATTR_PAL1), RS_CENTRE_16

rs_pyl_tab:
    .word RS_T_PYL_T0, (RS_ATTR_PRI | RS_ATTR_PAL1 | RS_SIZE_LARGE), RS_CENTRE_32
    .word RS_T_PYL_T1, (RS_ATTR_PRI | RS_ATTR_PAL1 | RS_SIZE_LARGE), RS_CENTRE_32
    .word RS_T_PYL_T2, (RS_ATTR_PRI | RS_ATTR_PAL1), RS_CENTRE_16
    .word RS_T_PYL_T3, (RS_ATTR_PRI | RS_ATTR_PAL1), RS_CENTRE_16

; How TALL the column is, per tier, and how tall one segment of it is. The
; count falls with distance for the same reason the frame shrinks: a three-high
; stack of 16x16 at the horizon would be a 48-px tower on a structure that
; should be a speck. At the near tiers the column is 32x96; at the far one it
; is a single 16x16 block.
rs_pyl_stack_tab:
    .word RS_PYL_STACK, RS_PYL_STACK, 2, 1
rs_pyl_step_tab:
    .word RS_PYL_H32, RS_PYL_H32, RS_PYL_H16, RS_PYL_H16
.assert RS_PYL_N * RS_PYL_STACK = 6, error, "the pylon OAM claim no longer fits its tallest case"

; The ten digit frames. NOT base + 2*v: a 16x16 frame reads {N, N+1, N+16,
; N+17}, so a row-pair holds eight and the ninth has to start the next pair.
RS_T_DIGIT_R0 = 128
RS_T_DIGIT_R1 = 160
rs_digit_tab:
    .word RS_T_DIGIT_R0 + 0, RS_T_DIGIT_R0 + 2, RS_T_DIGIT_R0 + 4
    .word RS_T_DIGIT_R0 + 6, RS_T_DIGIT_R0 + 8, RS_T_DIGIT_R0 + 10
    .word RS_T_DIGIT_R0 + 12, RS_T_DIGIT_R0 + 14
    .word RS_T_DIGIT_R1 + 0, RS_T_DIGIT_R1 + 2

; The ship's poses in BANK ORDER — index 0 is wings level and index
; RS_BANK_STEPS is hard over. A table and not base + 4*step because the sheet
; could not hold five 32x32 lanes contiguously: the first four fill grid rows
; 0..3 and the fifth lives in the block rows 12..15
; (gen_railshooter_assets.py's layout note, and rs_obj/feature.toml's).
rs_ship_frame_tab:
    .word RS_T_SHIP_F0, RS_T_SHIP_F1, RS_T_SHIP_F2
    .word RS_T_SHIP_F3, RS_T_SHIP_F4
.assert RS_BANK_STEPS = 4, error, "rs_ship_frame_tab has one entry per bank step plus level"
.assert RS_LEAN_HARD_R - RS_LEAN_HARD_L = 2 * RS_BANK_STEPS, error, "the lean range and the bank-step count disagree"
.assert RS_LEAN_LEVEL - RS_LEAN_HARD_L = RS_BANK_STEPS, error, "RS_LEAN_LEVEL is not the middle of the lean range"

; The powers of ten the score is decomposed by, most significant first.
rs_pow10_tab:
    .word 1000, 100, 10, 1

; =============================================================================
; rs_cache_build — PASS 1: project every actor once, and the aim point
; =============================================================================
; CONTRACT rs_cache_build
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the per-frame projection cache built
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one — BEFORE the hitscan and the draw, which both
;             read it
;   tail:     rts
;
; before the draw, which is the whole reason it is a routine of its own now:
; the hit test compares the aim point against the SAME projected boxes the OAM
; emit is about to write, so "the crosshair was on it" and "it died" cannot
; disagree.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep; every callee restores both.
rs_cache_build:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rs_cache_build"
    lda #RS_OBS_BASE
    sta RSD_IDX
    lda #0
    sta RSD_CUR
    lda #RSC_KIND_HAZ
    sta RSD_KIND
    lda #(RS_OBS_BASE + 2 * RS_OBS_N)
    sta RSD_TMP
    jsr rs_cache_pool
    lda #RS_PYL_BASE
    sta RSD_IDX
    lda #RSC_PYL0
    sta RSD_CUR
    lda #RSC_KIND_PYL
    sta RSD_KIND
    lda #(RS_PYL_BASE + 2 * RS_PYL_N)
    sta RSD_TMP
    jsr rs_cache_pool
    jsr rs_cache_reticle
    rts

; --- rs_cache_pool: cache the pool spanning RSD_IDX..RSD_TMP into RSD_CUR ---
; WIDTH-RISK: A16/I16 entry AND exit; every label annotated.
rs_cache_pool:
    .a16
    .i16
@lp:
    .a16
    .i16
    ldx RSD_IDX
    jsr rs_cache_one
    lda RSD_CUR
    clc
    adc #RSC_STRIDE
    sta RSD_CUR
    lda RSD_IDX
    clc
    adc #2
    sta RSD_IDX
    cmp RSD_TMP
    bcc @lp
    rts

; --- rs_cache_one: project the actor at absolute byte offset X -------------
; In: X = the actor's byte offset inside rs_actors. RSD_CUR = the cache byte
; offset to write, RSD_KIND = what to stamp in RSC_VIS when it is visible. The
; STORED tier (hysteresis-applied) decides the frame and the centre offset; the
; projection supplies sx/sy/culled. Which FRAME is drawn is the game's
; grow-only decision, not the projection's raw answer.
;
; THE ALIVE TEST COMES FIRST, AND THAT ORDER IS THE POINT. It used to come LAST
; — after WX, Z and TIER had already been loaded and the projection already run
; — so every dead slot read three parallel-array words that spawn had never
; written. The rail was the only ROM in the tree the emulator's
; read-before-write detector flagged (38 reads in 400 frames, against 0 for
; both `m7_oshoot` and `racer`, which build on the same pool). Nothing reached
; the picture — `RSC_VIS` is stamped 0 and both consumers gate on it — but the
; garbage TIER was used unmasked as the index into a 24-byte descriptor table,
; which is an out-of-bounds read one refactor away from mattering, and
; CLAUDE.md rule 5 asks for that to be treated as a ROM bug rather than harness
; noise. `rs_obj/feature.toml`'s [init] argument is now true of the reads as
; well as the writes: the arrays are never read before they are written.
;
; A dead slot stamps its OWN zero descriptor rather than falling into the
; shared tail: the tail reads RSD_SX/RSD_SY, which only `rs_project` writes, so
; routing a never-projected slot through it would trade three uninitialised
; WRAM reads for two uninitialised DP ones. It also skips the projection
; outright, which is a shift-add saved per dead slot per frame. WIDTH-RISK:
; A16/I16 entry AND exit; every label annotated; rs_project holds the same
; contract and clobbers X, hence the phx/plx.
rs_cache_one:
    .a16
    .i16
    lda f:ES_RS_ACTORS_LONG + RS_F_ALIVE, x
    beq @dead
    lda f:ES_RS_ACTORS_LONG + RS_F_WX, x
    sta RSD_OBJX
    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x
    sta RSD_Z
    lda z:US_CAM_X
    sta RSD_CAMX
    phx
    jsr rs_project
    plx
    lda f:ES_RS_ACTORS_LONG + RS_F_TIER, x
    sta RSD_PASS                    ; the stored tier, across the arithmetic
    lda RSD_CULL
    bne @culled
    lda RSD_KIND
    bra @have_vis
@dead:
    ; A slot spawn has never touched: nothing is read from it, and the whole
    ; descriptor is written explicitly so the cache is never part-defined.
    .a16
    .i16
    ldx RSD_CUR
    lda #0
    sta f:ES_RS_CACHE_LONG + RSC_SX, x
    sta f:ES_RS_CACHE_LONG + RSC_SY, x
    sta f:ES_RS_CACHE_LONG + RSC_TIER, x
    sta f:ES_RS_CACHE_LONG + RSC_VIS, x
    rts
@culled:
    .a16
    .i16
    lda #0
@have_vis:
    .a16
    .i16
    pha                             ; vis/kind, across the descriptor arithmetic
    ; ---- centre-adjust: the projection answers a CENTRE, OAM wants a LEFT --
    lda RSD_PASS
    asl a
    sta RSD_ACC
    asl a
    clc
    adc RSD_ACC                     ; tier * 6 = the descriptor row offset
    tax
    lda RSD_SX
    sec
    sbc f:rs_tier_tab + 4, x        ; centre_off (both tables agree on it)
    sta RSD_SX
    ; ---- write the entry ---------------------------------------------------
    ldx RSD_CUR
    lda RSD_SX
    sta f:ES_RS_CACHE_LONG + RSC_SX, x
    lda RSD_SY
    sta f:ES_RS_CACHE_LONG + RSC_SY, x
    lda RSD_PASS
    sta f:ES_RS_CACHE_LONG + RSC_TIER, x
    pla
    sta f:ES_RS_CACHE_LONG + RSC_VIS, x
    rts

; --- rs_cache_reticle: the aim point, projected like everything else -------
; THE DRAG IS EMERGENT AND THIS IS WHERE IT HAPPENS. The reticle's world x is
; standing still; the camera's is swinging along the S-curve; the projection
; subtracts one from the other. Nothing nudges the sprite in screen space.
; WIDTH-RISK: A16/I16 entry AND exit; every label annotated.
rs_cache_reticle:
    .a16
    .i16
    lda f:US_RET_X_LONG
    sta RSD_OBJX
    lda f:US_RET_Z_LONG
    sta RSD_Z
    lda z:US_CAM_X
    sta RSD_CAMX
    jsr rs_project
    lda RSD_CULL
    bne @culled
    lda RSD_SX
    sta RSD_RSX                     ; the CENTRE — the aim point itself
    lda RSD_SY
    sta RSD_RSY
    lda #1
    sta RSD_RVIS
    rts
@culled:
    .a16
    .i16
    lda #0
    sta RSD_RVIS
    rts

; =============================================================================
; rs_draw — the whole foreground, in the order the OAM window is laid out
; =============================================================================
; CONTRACT rs_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole cast staged from the cache
;   clobbers: A, X, Y, N, Z, C, V, and whatever the routines it dispatches
;             to clobber
;   assumes:  once per frame from the scene's tick, after the state it
;             reads has been committed. The shadow is rebuilt whole rather
;             than patched, so a stale byte from last frame cannot survive
;             into this one — AFTER rs_cache_build
;   tail:     rts
;
; every projection it needs is already in the cache.
;
; The first act is a full park + hi-table clear, which is what makes "a slot
; nothing wrote is parked" true by construction and the hi table REBUILT rather
; than patched.
;
; WIDTH-RISK: A16/I16 entry AND exit; every callee restores both.
rs_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rs_draw"
    jsr rs_obj_disarm
    jsr rs_draw_reticle
    jsr rs_draw_burst
    jsr rs_draw_ship
    jsr rs_draw_actors
    jsr rs_draw_shots
    jsr rs_draw_hud
    rts

; --- rs_draw_ship: the ship, FIXED on screen, banking with the curve --------
; It does not respond to the pad at all and its screen x never changes — only
; the CHR frame does, so the bank reads as a lean rather than a slide.
;
; THE LEAN IS A POSE NUMBER, NOT A DIRECTION. `US_LEAN` is RS_LEAN_LEVEL plus a
; signed bank step, stored BIASED so this unsigned `cmp` orders the nine states
; — below the level is a left bank, above it a right one. The magnitude indexes
; `rs_ship_frame_tab`; the sign chooses whether the frame is H-flipped. That is
; the whole of the H-flip economy: FOUR bank steps cost four CHR lanes rather
; than eight, because the art is authored rolling LEFT and the light that
; shades it has no sideways component (gen_railshooter_assets.py, LIGHT_DIR),
; so the mirror is exact.
;
; The RAMP is not here. `rs_path_step` grades the path's slope and walks the
; stored pose one step per frame; this routine only ever renders the pose it
; is handed, which is why a test can read the tile index per frame and see the
; intermediate poses.
;
; During the fail state it BLINKS, which is what tells a pilot the run ended
; rather than the emulator stalling. WIDTH-RISK: A16/I16 entry and exit; no
; sep/rep here (rs_put restores).
rs_draw_ship:
    .a16
    .i16
    lda f:US_FAIL_T_LONG
    beq @alive
    and #8                          ; ~7 frames on, ~7 off
    bne @gone
@alive:
    .a16
    .i16
    lda #(RS_ATTR_PRI | RS_ATTR_PAL0 | RS_SIZE_LARGE)
    sta RSD_PATTR
    lda f:US_LEAN_LONG
    cmp #RS_LEAN_LEVEL
    bcc @left
    beq @level
    lda #(RS_ATTR_PRI | RS_ATTR_PAL0 | RS_ATTR_HFLIP | RS_SIZE_LARGE)
    sta RSD_PATTR                   ; a right bank is the left frame, mirrored
    lda f:US_LEAN_LONG
    sec
    sbc #RS_LEAN_LEVEL
    bra @frame
@level:
    .a16
    .i16
    lda #0
    bra @frame
@left:
    .a16
    .i16
    lda #RS_LEAN_LEVEL
    sec
    sbc f:US_LEAN_LONG
@frame:
    .a16
    .i16
    asl a                           ; a word table
    tax
    lda f:rs_ship_frame_tab, x
    sta RSD_PTILE
    lda #RS_SHIP_X
    sta RSD_SX
    lda #RS_SHIP_Y
    sta RSD_SY
    ldx #RS_OAM_SHIP
    jsr rs_put
@gone:
    .a16
    .i16
    rts

; --- rs_draw_actors: the depth-sorted emit, over hazards AND pylons --------
; PASS 2. Walks tier 0 -> 3 over the whole cache and fills each kind's OAM
; sub-window in that order, so a nearer actor always takes a LOWER slot within
; its window and therefore draws IN FRONT.
;
; No sort and no comparisons between actors: bucketing by the size tier the
; game already stores IS the sort. The order is re-derived every frame, so an
; actor's pool slot is irrelevant to where it draws — which is the fix for the
; "pop" a fixed pool-slot -> OAM-slot map suffers.
;
; THE TWO WINDOWS DO NOT INTERLEAVE, and that is deliberate. Hazards occupy
; slots 3..6 and pylons 22..27, so a pylon can never draw in front of a hazard
; whatever their depths: the things a pilot must shoot are never occluded by
; the scenery the rail is flying around. The HUD sits between them (10..21) and
; is in front of the scenery for the same reason.
;
; WIDTH-RISK: A16/I16 entry AND exit; every label annotated; every callee
; restores both.
rs_draw_actors:
    .a16
    .i16
    lda #0
    sta RSD_PASS
    sta RSD_EMIT
    sta RSD_STK
@tier:
    .a16
    .i16
    lda #0
    sta RSD_IDX
@scan:
    .a16
    .i16
    ldx RSD_IDX
    lda f:ES_RS_CACHE_LONG + RSC_VIS, x
    beq @next
    sta RSD_TMP                     ; the kind, wanted after the tier test
    lda f:ES_RS_CACHE_LONG + RSC_TIER, x
    cmp RSD_PASS
    bne @next
    lda f:ES_RS_CACHE_LONG + RSC_SX, x
    sta RSD_SX
    lda f:ES_RS_CACHE_LONG + RSC_SY, x
    sta RSD_SY
    lda RSD_TMP
    cmp #RSC_KIND_PYL
    beq @pylon
    jsr rs_emit_hazard
    bra @next
@pylon:
    .a16
    .i16
    jsr rs_emit_pylon
@next:
    .a16
    .i16
    lda RSD_IDX
    clc
    adc #RSC_STRIDE
    sta RSD_IDX
    cmp #(RSC_STRIDE * (RS_OBS_N + RS_PYL_N))
    bcc @scan
    lda RSD_PASS
    inc a
    sta RSD_PASS
    cmp #RS_TIER_ROWS
    bcc @tier
    rts

; --- rs_emit_hazard: one sprite into the hazard sub-window -----------------
; In: RSD_SX/RSD_SY placed, RSD_PASS = the tier. WIDTH-RISK: A16/I16 both ways.
rs_emit_hazard:
    .a16
    .i16
    lda RSD_PASS
    asl a
    sta RSD_ACC
    asl a
    clc
    adc RSD_ACC                     ; tier * 6
    tax
    lda f:rs_tier_tab + 0, x
    sta RSD_PTILE
    lda f:rs_tier_tab + 2, x
    sta RSD_PATTR
    lda RSD_EMIT
    clc
    adc #RS_OAM_HAZARDS
    tax
    jsr rs_put
    lda RSD_EMIT
    inc a
    sta RSD_EMIT
    rts

; --- rs_emit_pylon: a VERTICAL STACK into the pylon sub-window -------------
; The column stands ON its ground point: segment k's top is sy - (k+1)*step, so
; the lowest segment's bottom lands exactly on the projected ground contact.
; Height falls with the tier (rs_pyl_stack_tab), because a three-high stack of
; the far frame would be a 48-px tower on something that should be a speck.
; WIDTH-RISK: A16/I16 entry AND exit; every label annotated.
rs_emit_pylon:
    .a16
    .i16
    lda RSD_PASS
    asl a
    sta RSD_ACC
    asl a
    clc
    adc RSD_ACC                     ; tier * 6
    tax
    lda f:rs_pyl_tab + 0, x
    sta RSD_PTILE
    lda f:rs_pyl_tab + 2, x
    sta RSD_PATTR
    lda RSD_PASS
    asl a
    tax                             ; tier * 2, for the two word tables
    lda f:rs_pyl_stack_tab, x
    sta RSD_PSEG                    ; segments left to emit
    lda f:rs_pyl_step_tab, x
    sta RSD_PSTEP                   ; ...and how tall each one is
@seg:
    .a16
    .i16
    lda RSD_SY
    sec
    sbc RSD_PSTEP
    sta RSD_SY                      ; climb one segment toward the horizon
    lda RSD_STK
    clc
    adc #RS_OAM_PYLONS
    tax
    jsr rs_put
    lda RSD_STK
    inc a
    sta RSD_STK
    lda RSD_PSEG
    dec a
    sta RSD_PSEG
    bne @seg
    rts

; --- rs_draw_shots: the tracers, pool slot k IS OAM slot RS_OAM_SHOTS+k -----
; The tracers keep the stable-slot contract the hazards deliberately break:
; they are all one size and never occlude each other, so there is nothing for a
; depth order to fix and a test can read shot k at a known slot. WIDTH-RISK:
; A16/I16 entry AND exit; every label annotated.
rs_draw_shots:
    .a16
    .i16
    lda #0
    sta RSD_IDX
@lp:
    .a16
    .i16
    ldx RSD_IDX
    lda f:ES_RS_ACTORS_LONG + RS_BUL_ALIVE, x
    beq @next
    lda f:ES_RS_ACTORS_LONG + RS_BUL_WX, x
    sta RSD_OBJX
    lda f:ES_RS_ACTORS_LONG + RS_BUL_Z, x
    sta RSD_Z
    lda z:US_CAM_X
    sta RSD_CAMX
    jsr rs_project
    lda RSD_CULL
    bne @next
    lda RSD_SX
    sec
    sbc #RS_CENTRE_16
    sta RSD_SX
    lda #RS_T_BULLET
    sta RSD_PTILE
    lda #(RS_ATTR_PRI | RS_ATTR_PAL1)
    sta RSD_PATTR
    lda RSD_IDX
    lsr a                           ; the byte offset back to a slot index
    clc
    adc #RS_OAM_SHOTS
    tax
    jsr rs_put
@next:
    .a16
    .i16
    lda RSD_IDX
    clc
    adc #2
    sta RSD_IDX
    cmp #(2 * RS_BUL_N)
    bcc @lp
    rts

; --- rs_draw_reticle: the aim point, from the cache -------------------------
; Centred ON its ground point (both axes pulled back half a frame), because it
; is a crosshair the pilot lines up with a target and not a marker that sits
; under one. WIDTH-RISK: A16/I16 entry AND exit; every label annotated.
rs_draw_reticle:
    .a16
    .i16
    lda RSD_RVIS
    beq @done
    lda RSD_RSX
    sec
    sbc #RS_CENTRE_16
    sta RSD_SX
    lda RSD_RSY
    sec
    sbc #RS_CENTRE_16
    sta RSD_SY
    lda #RS_T_RETICLE
    sta RSD_PTILE
    lda #(RS_ATTR_PRI | RS_ATTR_PAL1)
    sta RSD_PATTR
    ldx #RS_OAM_RETICLE
    jsr rs_put
@done:
    .a16
    .i16
    rts

; --- rs_draw_burst: the kill flash ------------------------------------------
; The rendered event that makes a kill not resemble a miss. It is pinned in
; SCREEN space at the position the hazard was projected to when it died, so it
; stays over the wreck rather than tracking a world point that no longer has an
; actor on it. WIDTH-RISK: A16/I16 entry AND exit; every label annotated.
rs_draw_burst:
    .a16
    .i16
    lda f:US_BURST_T_LONG
    beq @done
    lda #RS_T_BURST_A
    sta RSD_PTILE
    lda f:US_BURST_F_LONG
    beq @have_frame
    lda #RS_T_BURST_B
    sta RSD_PTILE
@have_frame:
    .a16
    .i16
    lda #(RS_ATTR_PRI | RS_ATTR_PAL1 | RS_SIZE_LARGE)
    sta RSD_PATTR
    lda f:US_BURST_SX_LONG
    sta RSD_SX
    lda f:US_BURST_SY_LONG
    sta RSD_SY
    ldx #RS_OAM_BURST
    jsr rs_put
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_draw_hud — the score and the life bar, in OBJ because Mode 7 has no BG3
; =============================================================================
; In/out: A16/I16, DB=0.
;
; The HUD in pixels: five discrete life segments that a pilot watches go, and a
; score that moves on a kill. Both live in the sky band (y 8..23).
;
; THAT BAND IS NOT PRIVATE, AND THIS COMMENT USED TO CLAIM IT WAS. It said
; "which no projected actor can reach", and the reasoning error is precise: no
; projected GROUND POINT can reach the sky band, but a pylon's SPRITE stands 96
; px above its ground point and that is not a projected point. Measured, a
; play-window sprite crosses these scanlines on about a tenth of all frames and
; box-overlaps a life segment on about one in fifty. So the HUD's per-scanline
; sprite cost DOES sometimes add to the play band's -- 22 slivers of the
; hardware's 34 at the worst frame the audit could construct, which is why it
; fits, rather than because the bands are disjoint. The HUD now takes LOWER OAM
; slots than the pylons so it draws in front of them.
;
; THE SCORE IS DECOMPOSED BY REPEATED SUBTRACTION, four powers of ten, at most
; nine iterations each: ~250 cycles a frame against a ~28,000-cycle budget. A
; hardware divide would need the ALU claim this rail deliberately does not
; take -- for a HUD.
;
; WIDTH-RISK: A16/I16 entry AND exit; every label annotated; rs_put restores
; both and clobbers A/X/Y, which is why every cursor lives in the DP frame
; rather than in a register.
rs_draw_hud:
    .a16
    .i16
    lda f:US_SCORE_LONG
    sta RSD_HREM
    lda #0
    sta RSD_HIDX
@digit:
    .a16
    .i16
    lda RSD_HIDX
    asl a
    tax
    lda f:rs_pow10_tab, x
    sta RSD_HDIV
    lda #0
    sta RSD_HVAL
@sub:
    .a16
    .i16
    lda RSD_HREM
    cmp RSD_HDIV
    bcc @have_digit
    sec
    sbc RSD_HDIV
    sta RSD_HREM
    lda RSD_HVAL
    inc a
    sta RSD_HVAL
    bra @sub
@have_digit:
    .a16
    .i16
    lda RSD_HVAL
    asl a
    tax
    lda f:rs_digit_tab, x
    sta RSD_PTILE
    lda #(RS_ATTR_PRI | RS_ATTR_PAL1)
    sta RSD_PATTR
    lda RSD_HIDX
    asl a
    asl a
    asl a
    asl a                           ; * RS_SCORE_DX
    clc
    adc #RS_SCORE_X0
    sta RSD_SX
    lda #RS_HUD_Y
    sta RSD_SY
    lda RSD_HIDX
    clc
    adc #RS_OAM_SCORE
    tax
    jsr rs_put
    lda RSD_HIDX
    inc a
    sta RSD_HIDX
    cmp #RS_SCORE_DIGITS
    bcc @digit
    ; ---- the life bar: five segments, full or empty, always all five ------
    ; Both frames are the same shape at the same place, so a lost segment reads
    ; as a state change rather than as something vanishing.
    lda #0
    sta RSD_HIDX
@life:
    .a16
    .i16
    lda #RS_T_LIFE_EMPTY
    sta RSD_PTILE
    lda RSD_HIDX
    cmp f:US_LIVES_LONG
    bcs @life_place
    lda #RS_T_LIFE_FULL
    sta RSD_PTILE
@life_place:
    .a16
    .i16
    lda #(RS_ATTR_PRI | RS_ATTR_PAL1)
    sta RSD_PATTR
    lda RSD_HIDX
    asl a
    asl a
    asl a
    asl a                           ; * RS_LIFE_DX
    clc
    adc #RS_LIFE_X0
    sta RSD_SX
    lda #RS_HUD_Y
    sta RSD_SY
    lda RSD_HIDX
    clc
    adc #RS_OAM_LIFE
    tax
    jsr rs_put
    lda RSD_HIDX
    inc a
    sta RSD_HIDX
    cmp #RS_LIVES_N
    bcc @life
    rts
.assert RS_SCORE_DX = 16 && RS_LIFE_DX = 16, error, "the HUD's x step is spelled as four asl -- change both or neither"
