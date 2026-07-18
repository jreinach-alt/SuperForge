; =============================================================================
; rail_draw.asm — depth-sorted OAM emit for pseudo-3D depth actors (reusable)
; =============================================================================
; Emit a pool of fake-3D depth actors (obstacles, pickups, mobs riding the
; pinhole 1/z projection of engine/mode7_project.asm) into a contiguous OAM
; slot range ORDERED BY SIZE TIER — tier 0 (nearest/largest) takes the LOWEST
; OAM slots, tier 3 (farthest/smallest) the highest; dead/culled actors park
; off-screen at y=$F0. Lower OAM index draws in FRONT on the SNES, so emitting
; nearer actors first makes nearer actors occlude farther ones — correct
; back-to-front depth layering with NO sort and NO comparisons (the era trick:
; bucket by the size tier you already compute).
;
; Why this exists (the OAM-pop fix): a naive rail draws each pool slot into a
; FIXED OAM slot (pool slot k -> OAM slot base+k). That is stable but it layers
; by pool-slot identity, not by depth — when a near actor recycles and a far
; actor keeps its low slot, the far actor draws IN FRONT of a nearer one, and a
; recycled actor "pops" its old slot's depth order. Re-deriving the OAM order
; from the per-frame tier EVERY frame removes both: order tracks depth, and the
; pool slot an actor lives in is irrelevant to where it draws.
;
; The order is re-derived every frame from each actor's CURRENT tier, so
; death/respawn order never matters. The emit is exactly `count` sprites into
; OAM slots [base, base+count) — slots are deterministic (a test can scan that
; window), but WHICH pool actor lands in WHICH slot changes with depth (track an
; actor by its lane_x/depth_z identity, not by a fixed slot).
;
; PARAMETER BLOCK (the caller stamps it in low WRAM, $1800-$1DFF region so
; (dp),y indirect with DB=$00 reaches it; X = its 16-bit address on entry).
; All multi-byte fields are little-endian words:
;
;   +$00  rd_alive   word   pool ALIVE[] base (abs WRAM; 1 = live, 0 = free)
;   +$02  rd_lanex   word   pool LANE_X[] base (s16 lateral world-px offset)
;   +$04  rd_depth   word   pool DEPTH_Z[] base (u16 forward depth z, world px)
;   +$06  rd_camx    word   camera world X (s16) — passed to the projection
;   +$08  rd_count   word   actor count N (1..32; = OAM slots consumed)
;   +$0A  rd_tiertbl word   ROM addr of the per-tier descriptor table (below)
;   +$0C  rd_cache   word   WRAM scratch base, N x 4 words (8 bytes/actor):
;                             [sx, sy, tier, vis] per pool slot (vis: 1 = draw).
;   +$0E  rd_tier    word   pool TIER[] base (u8 EFFECTIVE size tier 0..3 per
;                             actor; the routine orders + selects the descriptor
;                             by THIS stored tier, not the raw projected tier, so
;                             the game's GROW/SHRINK hysteresis is honored. Fill
;                             it before the call. The projection still supplies
;                             sx/sy/culled.)
;
; PER-TIER DESCRIPTOR TABLE (rd_tiertbl points here; 4 entries, tier 0..3,
; 3 words each = 24 bytes, in ROM/RODATA):
;   tier k: .word draw_tile      ; OAM tile number (OBJ-name-base relative)
;           .word draw_flags     ; OAM attr: bit7 size, bit6 Hflip, bits3:0 pal
;           .word center_off     ; px to subtract from PROJ_SX (half sprite w)
;
; The routine projects each live actor once (mode7_project), caches the result,
; then walks tier 0..3 emitting matching live+visible actors in order, finally
; parking the unused slots. Net: exactly `count` engine_spr calls, into OAM
; slots base..base+N-1.
;
; CONTRACT
;   IN   X = parameter-block WRAM address. Entry .a16 .i16, DB=$00 (game-loop
;        default). The caller MUST have done spr_clear (or equivalent) and drawn
;        any FIXED-slot sprites (e.g. the player at slot 0) so SPRITE_COUNT
;        already equals the intended OAM base — the routine appends `count`
;        sprites via engine_spr in call order, exactly like the spr macro.
;   OUT  `count` sprites emitted into the next `count` OAM slots, tier-ordered.
;        A, X, Y clobbered; the projection block ($48-$57) and math scratch
;        ($B0-$BF) clobbered (mode7_project's contract); RD_* DP scratch
;        ($58-$5F) clobbered. Exits .a16 .i16.
;
; Requires (linked, sf_mode7 order): mode7_project.asm + the generated
; mode7_project.inc (PROJ_* + the LUT) + mode7_math.asm (smul16) +
; sprite_engine.asm (engine_spr / SPR_API_*). The kit front door is the
; sf_rail.inc macro group (sf_rail_draw_sorted) — see lib/macros/sf_rail.inc.
;
; Must NOT set .p816/.smart — included into a parent that already does.
; =============================================================================

; --- private DP scratch. Game DP $58-$5F window: survives both the
; mode7_project call ($48-$57) and the engine_spr calls ($60+), neither of
; which touches $58-$5F. The routine OWNS these for its duration. ---
RD_PARAM    = $58           ; word: parameter-block pointer (DP indirect base)
RD_IDX      = $5A           ; word: pool byte offset cursor (0,2,4,...)
RD_TIER     = $5C           ; word: current emit-pass tier (0..3)
RD_TMP      = $5E           ; word: per-iteration scratch (cache ptr / field)

; cache stride per actor (4 words = 8 bytes): [sx, sy, tier, vis]
RD_CACHE_STRIDE = 8

; =============================================================================
; rail_draw_sorted — see header. X = param-block address.
; =============================================================================
; WIDTH-RISK: entry .a16 .i16. Calls mode7_project (toggles I8 internally,
; restores I16) and engine_spr (wants rep #$30, returns A16/I16). This routine
; stays .a16 .i16 throughout; every multi-path label carries an explicit width
; annotation. It does no sep/rep of its own.
rail_draw_sorted:
    .a16
    .i16
    stx z:RD_PARAM                  ; stash the param-block pointer (DP base)

    ; =====================================================================
    ; PASS 1 — project every actor once; cache (sx, sy, tier, vis) per slot.
    ; =====================================================================
    stz z:RD_IDX
@proj_loop:
    .a16
    .i16
    ldy #$08                        ; rd_count
    lda (RD_PARAM), y
    asl a                           ; 2*count (byte length of the pool arrays)
    cmp z:RD_IDX
    bne @proj_one
    jmp @emit_setup                 ; projected all -> start the ordered emit
@proj_one:
    .a16
    .i16
    ; --- marshal the actor at byte offset RD_IDX into the projection block ---
    ; obj_x = LANE_X[idx]
    ldy #$02                        ; rd_lanex base
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    sta z:RD_TMP                    ; RD_TMP -> &LANE_X[idx]
    lda (RD_TMP)
    sta z:PROJ_OBJ_X
    ; depth z = DEPTH_Z[idx]
    ldy #$04                        ; rd_depth base
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    sta z:RD_TMP
    lda (RD_TMP)
    sta z:PROJ_DEPTH
    ; cam_x = rd_camx
    ldy #$06
    lda (RD_PARAM), y
    sta z:PROJ_CAM_X
    ; alive[idx] -> remember for vis (an actor is visible only if alive AND
    ; not culled by the projection).
    ldy #$00                        ; rd_alive base
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    sta z:RD_TMP
    lda (RD_TMP)                    ; A = alive flag (0/1)
    pha                             ; save alive across the JSR

    jsr mode7_project               ; -> PROJ_SX/SY/TIER/CULLED (.a16 .i16 out)

    ; --- read the EFFECTIVE (stored, hysteresis-applied) tier: TIER[idx] ---
    ; The routine orders + selects the descriptor by this stored tier, not the
    ; raw PROJ_TIER, so the caller's grow/shrink hysteresis is honored. (PROJ_SX/
    ; SY/CULLED still come from the projection.)
    ldy #$0E                        ; rd_tier base
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    sta z:RD_TMP
    lda (RD_TMP)                    ; A = stored tier 0..3
    pha                             ; save the stored tier across the ptr calc

    ; --- write the cache entry for this slot: cache base + idx*4 (idx is a
    ; word index = RD_IDX/2; *4 words = RD_IDX*4 bytes) ---
    ldy #$0C                        ; rd_cache base
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX                    ; A = cache_base + 4*RD_IDX (= idx*8 bytes)
    sta z:RD_TMP                    ; RD_TMP -> cache[idx]
    ; cache[+0] = sx
    lda z:PROJ_SX
    sta (RD_TMP)
    ; cache[+2] = sy
    ldy #$02
    lda z:PROJ_SY
    sta (RD_TMP), y
    ; cache[+4] = tier (the stored/effective tier, popped from the stack)
    pla                             ; A = stored tier
    ldy #$04
    sta (RD_TMP), y
    ; cache[+6] = vis  (alive AND not culled)
    pla                             ; A = alive (0/1)  (pushed before the JSR)
    ldy z:PROJ_CULLED
    beq @vis_keep                   ; culled == 0 -> keep alive flag as vis
    lda #$0000                      ; culled -> not visible
@vis_keep:
    .a16
    .i16
    ldy #$06
    sta (RD_TMP), y

    ; advance to the next actor
    lda z:RD_IDX
    clc
    adc #2
    sta z:RD_IDX
    jmp @proj_loop

    ; =====================================================================
    ; PASS 2 — emit tier 0..3, each pass scanning the cache for live+visible
    ; actors of that tier. Nearer tier -> lower OAM slot -> drawn in front.
    ; =====================================================================
@emit_setup:
    .a16
    .i16
    stz z:RD_TIER
@tier_loop:
    .a16
    .i16
    lda z:RD_TIER
    cmp #4
    bne @tier_scan
    jmp @park_rest                  ; all 4 tiers emitted -> park unused slots
@tier_scan:
    .a16
    .i16
    stz z:RD_IDX
@scan_loop:
    .a16
    .i16
    ldy #$08                        ; rd_count
    lda (RD_PARAM), y
    asl a                           ; 2*count
    cmp z:RD_IDX
    bne @scan_one
    jmp @tier_next
@scan_one:
    .a16
    .i16
    ; cache[idx] ptr = rd_cache + 4*RD_IDX
    ldy #$0C
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    sta z:RD_TMP                    ; RD_TMP -> cache[idx]
    ; vis?
    ldy #$06
    lda (RD_TMP), y
    beq @scan_skip                  ; not visible -> skip
    ; tier == current pass tier?
    ldy #$04
    lda (RD_TMP), y
    cmp z:RD_TIER
    bne @scan_skip
    ; --- emit this actor: look up the tier descriptor, place at PROJ-cached x/y
    jsr @emit_actor
@scan_skip:
    .a16
    .i16
    lda z:RD_IDX
    clc
    adc #2
    sta z:RD_IDX
    jmp @scan_loop
@tier_next:
    .a16
    .i16
    lda z:RD_TIER                   ; RD_TIER holds the tier NUMBER (0..3)
    inc a                           ; advance to the next tier
    sta z:RD_TIER
    jmp @tier_loop

    ; =====================================================================
    ; PARK — fill the remaining OAM slots (count - emitted) off-screen so the
    ; OAM window stays exactly `count` deterministic slots.
    ; =====================================================================
@park_rest:
    .a16
    .i16
    ; remaining = count - (SPRITE_COUNT - oam_base). We don't track oam_base
    ; directly; instead the routine knows it emitted some number of visible
    ; actors. Simpler+robust: re-walk and count visible, park (count - visible).
    ; Count visible:
    stz z:RD_TMP                    ; reuse RD_TMP as visible-count accumulator
    stz z:RD_IDX
@count_loop:
    .a16
    .i16
    ldy #$08
    lda (RD_PARAM), y
    asl a
    cmp z:RD_IDX
    beq @count_done
    ; cache[idx].vis
    ldy #$0C
    lda (RD_PARAM), y
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    clc
    adc z:RD_IDX
    sta z:RD_TIER                   ; reuse RD_TIER as a temp cache ptr here
    ldy #$06
    lda (RD_TIER), y
    beq @count_skip
    inc z:RD_TMP                    ; one more visible
@count_skip:
    .a16
    .i16
    lda z:RD_IDX
    clc
    adc #2
    sta z:RD_IDX
    jmp @count_loop
@count_done:
    .a16
    .i16
    ; park (count - visible) sprites at y=$F0
    ldy #$08
    lda (RD_PARAM), y               ; A = count
    sec
    sbc z:RD_TMP                    ; A = count - visible = #slots to park
    sta z:RD_IDX                    ; reuse RD_IDX as the park counter
@park_loop:
    .a16
    .i16
    lda z:RD_IDX
    beq @done
    ; park one sprite off-screen
    stz SPR_API_TILE
    stz SPR_API_X
    lda #$00F0
    sta SPR_API_Y
    stz SPR_API_FLAGS
    lda #$0002
    sta SPR_API_PRI
    jsr engine_spr
    lda z:RD_IDX
    dec a
    sta z:RD_IDX
    jmp @park_loop
@done:
    .a16
    .i16
    rts

; -----------------------------------------------------------------------------
; @emit_actor — emit ONE cached actor (RD_TMP -> cache[idx], RD_TIER = its tier)
; -----------------------------------------------------------------------------
; Reads the per-tier descriptor (tile, flags, center_off) from rd_tiertbl and
; the cached sx/sy, computes screen-left X = sx - center_off, and calls
; engine_spr (next OAM slot). Preserves RD_PARAM/RD_TIER/RD_IDX; clobbers A, X,
; Y, SPR_API_*. WIDTH-RISK: .a16 .i16 throughout (engine_spr's contract).
@emit_actor:
    .a16
    .i16
    ; descriptor address = rd_tiertbl + RD_TIER*6 (3 words/entry) -> X
    ldy #$0A                        ; rd_tiertbl
    lda (RD_PARAM), y
    clc
    adc z:RD_TIER
    clc
    adc z:RD_TIER
    clc
    adc z:RD_TIER
    clc
    adc z:RD_TIER
    clc
    adc z:RD_TIER
    clc
    adc z:RD_TIER                   ; A = tiertbl + 6*tier
    tax                             ; X = descriptor address
    ; tile = desc[+0]
    lda a:0, x
    sta SPR_API_TILE
    ; flags = desc[+2]
    lda a:2, x
    sta SPR_API_FLAGS
    lda #$0002
    sta SPR_API_PRI
    ; screen X = cache sx - desc center_off  (X still = descriptor address)
    lda (RD_TMP)                    ; cache[+0] = sx
    sec
    sbc a:4, x                      ; sx - center_off
    sta SPR_API_X
    ; Y = cache sy
    ldy #$02
    lda (RD_TMP), y
    sta SPR_API_Y
    jsr engine_spr                  ; -> next OAM slot, in tier order
    rts
