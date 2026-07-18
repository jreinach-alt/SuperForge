; =============================================================================
; sf_pool.inc — fixed-slot actor/projectile pools (macro library)
; =============================================================================
; The multi-actor brick for shmups, run-n-guns, brawler mobs: N interchangeable
; short-lived actors (bullets, enemies, particles) managed by slot.
;
; A pool is an ALIVE array: N words (0 = free, 1 = live) at a base address the
; game owns. The game pairs it with parallel arrays for whatever per-slot state
; it needs (x, y, vy, type, ...), indexed by the SAME byte offset:
;
;   BULLETS    = $1800              ; alive[8]
;   BULLET_X   = $1810              ; x[8]
;   BULLET_Y   = $1820              ; y[8]
;
; WHERE TO PUT POOLS — $1800-$1DFF (the game-array region). The pool and its
; parallel arrays need plain absolute addressing (`lda BULLETS, x`), which
; with DB=$00 only reaches the low-WRAM mirror $0000-$1FFF. Do NOT place them
; at $2000+: bank $00's $2000-$5FFF is hardware registers / open bus, NOT
; WRAM — reads return garbage silently. (WRAM $2000+ exists only via bank $7E
; long addressing — fine for one-off debug writes, wrong for indexed arrays.)
; $1800-$1DFF is free by construction: engine state ends at $056F, and the
; CPU stack grows DOWN from $1FFF — $1E00-$1FFF leaves 512 bytes of stack,
; ~10x the kit's deepest measured call chain. sf_coldstart zeroes WRAM, so
; pools start all-free even without sf_pool_init (call it anyway on game
; reset/restart).
;
; THE ITERATION IDIOM (keep the offset in X; your loop counter survives
; because these are plain indexed reads, no engine calls):
;
;       ldx #0
;   bullet_loop:
;       lda BULLETS, x
;       beq bullet_next             ; free slot -> skip
;       lda BULLET_Y, x             ; ... update the live actor ...
;       sec
;       sbc #4
;       sta BULLET_Y, x
;       cmp #8
;       bcs bullet_next
;       sf_pool_kill_x BULLETS      ; off the top -> free the slot
;   bullet_next:
;       inx
;       inx
;       cpx #(2 * BULLET_N)
;       bne bullet_loop
;
; STABLE OAM SLOTS: the engine's spr assigns OAM slots in call order after
; spr_clear, so actors COMPACT when you skip dead ones (sf_sprite.inc). For
; stable slots, draw EVERY pool slot each frame — live actors at their
; position, dead slots off-screen (y = $F0). Then pool slot k always renders
; in the same OAM slot and a test can identify actors by slot. The shmup
; template demonstrates this.
;
; Requires: nothing (pure data macros — no engine link partners).
; =============================================================================

.ifndef SF_POOL_INC
SF_POOL_INC = 1

; -----------------------------------------------------------------------------
; sf_pool_init base, n — mark all n slots free.
; -----------------------------------------------------------------------------
;   base  the alive array's address (symbol or literal)
;   n     slot count (compile-time constant, 1..128)
; Call at game (re)start. Does NOT clear your parallel arrays — a slot's state
; is defined by sf_pool_spawn-then-write, never read before written.
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16/I16.
.macro sf_pool_init sf_base, sf_n
    .local pl_clr
    .assert (sf_n) >= 1 .and (sf_n) <= 128, error, "sf_pool_init: n must be 1..128"
    rep #$30
    .a16
    .i16
    ldx #$0000
pl_clr:
    stz sf_base, x
    inx
    inx
    cpx #(2 * (sf_n))
    bne pl_clr
.endmacro

; -----------------------------------------------------------------------------
; sf_pool_spawn base, n — claim the first free slot.
; -----------------------------------------------------------------------------
; Returns in A AND X: the claimed slot's BYTE OFFSET (0, 2, 4, ...) — index
; your parallel arrays with it directly (`sta BULLET_X, x`). When the pool is
; full, A = $FFFF (and X = 2*n): branch with `bmi` (offsets are always
; positive) or `cmp #$FFFF`. The slot is marked live before returning.
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16/I16 with the
; result in A. Internal control flow uses .local labels.
.macro sf_pool_spawn sf_base, sf_n
    .local pl_scan, pl_found, pl_done
    rep #$30
    .a16
    .i16
    ldx #$0000
pl_scan:
    lda sf_base, x
    beq pl_found
    inx
    inx
    cpx #(2 * (sf_n))
    bne pl_scan
    lda #$FFFF                  ; pool full
    bra pl_done
pl_found:
    .a16
    lda #$0001
    sta sf_base, x              ; claim it
    txa                         ; result = byte offset
pl_done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_pool_kill_x base — free the slot at the byte offset in X.
; -----------------------------------------------------------------------------
; The iteration-idiom kill: X already holds the slot offset (from the loop or
; from sf_pool_spawn). Preserves A, X.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16/I16.
.macro sf_pool_kill_x sf_base
    rep #$30
    .a16
    .i16
    stz sf_base, x
.endmacro

; -----------------------------------------------------------------------------
; sf_pool_count base, n — count live slots.
; -----------------------------------------------------------------------------
; Returns the live count in A (for HUDs, wave-cleared checks, spawn gating).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16/I16 with the
; count in A.
.macro sf_pool_count sf_base, sf_n
    .local pl_next, pl_skip
    rep #$30
    .a16
    .i16
    ldx #$0000
    ldy #$0000
pl_next:
    lda sf_base, x
    beq pl_skip
    iny
pl_skip:
    .a16
    inx
    inx
    cpx #(2 * (sf_n))
    bne pl_next
    tya
.endmacro

.endif ; SF_POOL_INC
