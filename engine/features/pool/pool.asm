; =============================================================================
; pool.asm — fixed-slot actor pools, as a REUSABLE mechanism
; =============================================================================
; FOUR rails share this mechanism -- `railshooter`, `m7_oshoot` and `boss`
; with TWO pools each, and `boss_saucer` with ONE (its only alive array is the
; shot pool) -- so this file is written for all four, not just for the first.
; Multiplicity costs nothing either way: N pools are N `POOL_BIND` stamps.
;
; A pool is an `alive[]` array of N WORDS (0 = free, non-zero = live) plus
; parallel arrays the game indexes with the SAME byte offset. These four
; routines are the whole mechanism: clear it, claim the first free slot, free a
; slot, count the live ones. Everything else -- how many slots, which fields,
; how many pools -- is the consumer's, and lives in the consumer's own `wram`
; claim.
;
; =============================================================================
; THE BINDING CONTRACT — what a consumer must do, and what this file promises
; =============================================================================
; This feature owns ONE resource: `ES_POOL_PTR`, a 4-byte DP claim holding the
; 24-bit base of the alive[] array the next call operates on (3 bytes of
; pointer + 1 byte of pad, so the stamp is two 16-bit stores rather than a
; store plus a width toggle).
;
;  THE CONSUMER MUST, before every call:
;  POOL_BIND <expr> where <expr> is a 24-bit constant address -- the
;  allocator-emitted `ES_<CLAIM>_LONG` plus the
;  pool's byte offset inside that claim.
;
;  THIS FILE PROMISES:
;  * it dereferences ONLY through ES_POOL_PTR, so a consumer's arrays may
;  live anywhere the allocator puts them, in any bank;
;  * it touches no other DP, no register, no channel and no VBlank byte;
;  * it never calls out, so the pointer cannot be stomped mid-call and two
;  consumers in one scene cannot interleave.
;
; WHY THE POINTER IS A CALL FRAME AND NOT PER-POOL STATE: it is written
; immediately before each call and dead immediately after. N pools therefore
; cost N stamps and no extra claim, which is exactly how one scene holds TWO
; pool instances. See feature.toml for why this beats a `pool`/`pool2` sibling
; pair and why it beats `shmup_obj`'s fold-into-the-sprite-feature shape.
;
; =============================================================================
; THE CURSOR IS X FOR THE CALLER AND Y INSIDE — and that is forced, not chosen
; =============================================================================
; `[dp],y` is the ONLY indirect-long indexed addressing mode the 65816 has --
; there is no `[dp],x`. But `lda long,x` exists and `lda long,y` does not, so a
; consumer's PARALLEL arrays (which are read with the claim's emitted long
; address, not through this pointer) must be indexed with X. The routines
; therefore take and return the byte offset in X and move it to Y internally.
; That keeps the caller's idiom identical to `shmup_obj`'s:
;
;  ldx #0
;  @loop:
;  lda f:ES_MY_ACTORS_LONG + MY_ALIVE, x
;  beq @next
;  lda f:ES_MY_ACTORS_LONG + MY_Y, x; ... update the live actor ...
;
;  POOL_BIND ES_MY_ACTORS_LONG + MY_ALIVE
;  jsr pool_kill; X preserved
;  @next:
;  inx
;  inx
;  cpx #(2 * MY_N)
;  bcc @loop
;
; =============================================================================
; BEHAVIOURAL CONTRACT
; =============================================================================
; The four routines here are a translation of a MACRO library, and a macro that
; expands inline can do things a `jsr`'d routine cannot. Each difference below
; is a place where a call site written against the inline form compiles, links
; and is WRONG. The table lives here because this is the file anyone opens
; when they want the contract.
;
;  (a) WIDTH — the silent-corruption one, and the only one the linter cannot
;  help with. A macro that OPENS with `rep #$30` is safe from any arrival
;  width, so its call sites never have to think about it. These
;  routines contain NO `sep`/`rep` at all and REQUIRE A16/I16 on entry --
;  deliberately, so a call can sit inside an A16/I16 kernel without
;  disturbing either axis, but it moves the obligation to the caller. A
;  call site that arrives in A8 assembles operands the CPU then reads at
;  the wrong width: the stray byte executes as `BRK` and the failure is
;  silent. `width_lint` is SINGLE-FILE (CLAUDE.md rule 6), so a caller in
;  another file is invisible to it in both directions -- these WIDTH-RISK
;  markers and the emulator are the whole check. If a caller cannot
;  guarantee A16/I16 at a site, it must `rep #$30` before the `jsr`
;  itself; that is one instruction and it buys back the inline form's
;  arrive-in-any-width property.
;
;  (b) A IS NOT PRESERVED BY `pool_kill`. An inline kill preserves A,
;  because a `stz base,x` is the whole macro. Here the kill is
;  `lda #0` + a store, so A comes back 0 -- and
;  `POOL_BIND`, which a caller must run FIRST, has already clobbered A
;  before that. X is still preserved, which is what the iteration idiom
;  actually needs. No call site in this tree depends on A surviving, so this
;  is a trap laid rather than sprung -- but a NEW site must not assume the
;  inline form's guarantee.
;
;  (c) THE SLOT COUNT IS A RUNTIME ARGUMENT, NOT A COMPILE-TIME ONE. Taking
;  `n` as a macro parameter lets it be asserted at ASSEMBLY time
;  (`.assert >= 1 .and <= 128`), so a bad count is a build error. Here it
;  arrives in X and the only runtime guard is
;  `cpx #0`, which turns a count of 0 into a no-op instead of a
;  65,536-iteration hang. THE UPPER BOUND IS UNENFORCED. What the caller
;  must guarantee, and what nothing will check for it:
;  * 1 <= count <= 128, so `2*count` cannot overflow the index;
;  * the SAME count at `pool_init`, `pool_spawn` and `pool_count` for a
;  given pool -- a spawn told about more slots than init cleared scans
;  uninitialised words and can claim a slot outside the array;
;  * `count * 2` bytes actually allocated at the bound base.
;  A rail whose counts come from one `.inc` constant each (as
;  `railshooter`'s RS_OBS_N / RS_BUL_N do) satisfies all three by
;  construction; one that computes a count at runtime does not.
;
;  (d) `pool_spawn`'s X ON THE FULL PATH IS NOT THE POOL SIZE. The inline form
;  naturally leaves X = 2*n when the pool is full; here it is 0. A caller
;  that branches on A (`bmi`, the documented idiom) never sees the
;  difference; one that read X to learn the pool size would.
;
; Must NOT set .p816/.smart -- included into a parent that already does.
; =============================================================================

;
; POOL_BIND <addr24> — stamp the base of the alive[] array for the next call.
;
; `addr24` is a 24-bit CONSTANT expression (an emitted `ES_*_LONG` plus a byte
; offset). Two 16-bit stores; A is clobbered, X and Y are not.
;
; WIDTH-RISK: requires A16 on entry and leaves A16. It contains no `sep`/`rep`
; and toggles nothing -- that is deliberate, so the macro can be dropped into
; the middle of an A16/I16 kernel without disturbing either axis.
;
; WHICH BREACH IS THE DANGEROUS ONE, stated precisely, because the two are not
; symmetric. If the ASSEMBLER is tracking A8, `lda #.loword(...)` assembles a
; ONE-byte immediate and any base above $00FF is a build-time range error --
; loud, and caught before the ROM exists. The silent breach is the MIRROR
; image: the assembler tracking A16 while the CPU is actually in A8. Then both
; stores assemble at full width, the CPU reads the second operand byte as an
; opcode, and a stray `$00` executes as `BRK`. That is the class CLAUDE.md rule
; 6 exists for, it leaves no assembler diagnostic, and `width_lint` cannot see
; it across a file boundary -- which is why this contract is stated on the
; macro rather than assumed from the call sites.
.macro POOL_BIND addr24
    lda #.loword(addr24)
    sta z:ES_POOL_PTR
    lda #.hiword(addr24)                ; bank byte in the low half; the high
    sta z:ES_POOL_PTR + 2               ;   half lands on the claim's pad byte
.endmacro

; =============================================================================
; pool_init — mark every slot of the bound pool free.
; =============================================================================
; CONTRACT pool_init
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = slot count (1..128); ES_POOL_PTR bound to the pool
;   out:      the WHOLE alive array marked free, end to end. The parallel
;             arrays are deliberately untouched — pre-filling a position
;             would hide a spawn that forgot to set it. The two paths
;             differ and the prose above states each; a count of 0 is a
;             no-op rather than a 65,536-iteration wrap
;   clobbers: A, X, Y, N, Z, C on the clear path. On the count-0 guard
;             path A and Y are UNCHANGED and X is 0 by definition of the
;             path — see the prose above, which states both
;   assumes:  DB is irrelevant: every access here is long
;   tail:     rts
;
; In: A16/I16. X = slot count (1..128). ES_POOL_PTR bound. Out: A16/I16. DB
; irrelevant (all access is long). The two paths differ and
;  are stated separately, because one line covering both would be false on
;  one of them:
;  CLEAR path (count >= 1): A = 0, X = 0, Y = 2*count.
;  GUARD path (count == 0): A and Y UNCHANGED, X = 0 by definition of
;  the path. Nothing was written.
;
; Writes the WHOLE alive array, not just the slots a caller intends to use, so
; the array is defined end to end. It deliberately does NOT touch the parallel
; arrays: a slot's position is written by spawn-then-use, and pre-filling it
; would hide a "spawn forgot to set y" defect behind a plausible zero.
;
; A count of 0 is a no-op rather than a 65,536-iteration wrap -- the guard is
; three cycles and the alternative is a hang that looks like a hardware fault.
;
; WIDTH-RISK: A16/I16 entry AND exit, no sep/rep anywhere in the routine.
; Cross-file callers used to be invisible to width_lint; the CONTRACT block
; below is what the gate now reads them against.
pool_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pool_init"
    cpx #0
    beq @done
    ldy #0
    lda #0                              ; (stz has no [dp],y form)
@clear:
    .a16
    .i16
    sta [ES_POOL_PTR], y
    iny
    iny
    dex
    bne @clear
@done:
    .a16
    .i16
    rts

; =============================================================================
; pool_spawn — claim the first free slot of the bound pool.
; =============================================================================
; In: A16/I16. X = slot count (1..128). ES_POOL_PTR bound. Out: A16/I16. On
; success A = X = the claimed slot's BYTE OFFSET (0, 2, 4...)
;  -- index the parallel arrays with it directly. On a full pool
;  A = POOL_FULL ($FFFF): branch with `bmi`, since a real offset is always
;  positive. Y clobbered.
;  X ON THE FULL PATH IS 0, not the pool size -- do not read X to learn how
;  big the pool is. See the header's delta (d). The
;  documented idiom (`bmi` on A) is unaffected.
;
; The slot is marked live BEFORE returning, so a caller that spawns and then
; forgets to fill the parallel arrays leaks a slot rather than double-claiming
; it -- a leak is visible (the pool stops accepting), a double-claim is two
; actors sharing one position and is not.
;
; WIDTH-RISK: A16/I16 entry AND exit, no sep/rep. Both `rts` paths and the
; `@found` label carry explicit annotations; `@found` is reached only by `beq`
; from the scan, which is A16/I16 throughout.
POOL_FULL = $FFFF

; CONTRACT pool_spawn
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = slot count (1..128); ES_POOL_PTR bound to the pool
;   out:      on success A = X = the claimed slot's BYTE offset, and the
;             slot is marked live BEFORE returning. On a full pool A =
;             POOL_FULL ($FFFF) — branch with `bmi`, since a real offset
;             is always positive — and X is 0, not the pool size
;   clobbers: A, X, Y, N, Z, C
;   assumes:  DB is irrelevant: every access here is long
;   tail:     rts
pool_spawn:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pool_spawn"
    ldy #0
    cpx #0
    beq @full
@scan:
    .a16
    .i16
    lda [ES_POOL_PTR], y
    beq @found
    iny
    iny
    dex
    bne @scan
@full:
    .a16
    .i16
    lda #POOL_FULL
    rts
@found:
    .a16
    .i16
    lda #1
    sta [ES_POOL_PTR], y                ; claim it before anyone can rescan
    tya
    tax                                 ; the offset in BOTH A and X
    rts

; =============================================================================
; pool_kill — free the slot at the byte offset in X.
; =============================================================================
; CONTRACT pool_kill
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = the slot's byte offset; ES_POOL_PTR bound to the pool
;   out:      the slot marked free. X is PRESERVED, which is what lets the
;             iteration idiom keep its cursor there; A = 0 and Y = X
;   clobbers: A, Y, N, Z. NOT A-preserving — the file header's delta table
;             item (b) says why
;   assumes:  DB is irrelevant: every access here is long
;   tail:     rts
;
; In: A16/I16. X = the slot's byte offset. ES_POOL_PTR bound. Out: A16/I16. X
; PRESERVED (the iteration idiom keeps its cursor there);
;  A = 0, Y = X.
;
; NOT A-PRESERVING — see the contract delta table in this file's header,
; item (b).
;
; WIDTH-RISK: A16/I16 entry AND exit, no sep/rep. Single path.
pool_kill:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pool_kill"
    txy                                 ; the cursor moves to the only index
    lda #0                              ;   register [dp],y can use
    sta [ES_POOL_PTR], y
    rts

; =============================================================================
; pool_count — how many slots of the bound pool are live.
; =============================================================================
; CONTRACT pool_count
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = slot count (1..128); ES_POOL_PTR bound to the pool
;   out:      A = the live count, 0..slot count — in A rather than X
;             because every caller feeds it straight to a store. X carries
;             the same value for a caller that would rather index with it.
;             The scan path leaves X = the count and Y = 0; the count-0
;             guard path leaves both UNCHANGED
;   clobbers: A, X, Y, N, Z, C
;   assumes:  DB is irrelevant: every access here is long. The scan runs
;             DOWNWARD by necessity, not style — the prose above works
;             through why
;   tail:     rts
;
; In: A16/I16. X = slot count (1..128). ES_POOL_PTR bound. Out: A16/I16. A =
; the live count, 0..slot count.
;  On the SCAN path X = that same count and Y = 0.
;  On the count-of-0 GUARD path A = 0 and X and Y are UNCHANGED (X is 0 by
;  definition of the path, and Y is whatever the caller left).
;
; The two paths are stated separately on purpose. A single summary line would
; be false on one of them — the same defect `pool_init`'s header carried —
; and it is not worth repeating one routine later.
;
; THE SCAN RUNS DOWNWARD, and that is forced rather than stylistic. Three roles
; want a register — the array cursor, the loop bound and the accumulator — and
; only two index registers exist beside A, which has to hold each loaded word
; to test it. `[dp],y` is the only indirect-long indexed mode the 65816 has, so
; Y must be the cursor; walking DOWN to zero makes the bound implicit and frees
; X to accumulate. An upward scan would need `2*count` parked somewhere to
; `cpy` against, and this feature claims no scratch to park it in. An inline
; form with a COMPILE-TIME base can afford the upward scan, because its cursor
; is X and Y is free to count; a runtime base cannot.
;
; It answers in A rather than X because every caller feeds the result straight
; to a STORE — none of them compares it — and A is where a store wants it. X
; carries the same value for a caller that would rather index with it.
;
; WIDTH-RISK: A16/I16 entry AND exit, no sep/rep anywhere in the routine.
; Cross-file callers used to be invisible to width_lint; the CONTRACT block
; below is what the gate now reads them against — see the header's delta
; table item (a) for why that
; matters more for a `jsr`'d routine than for an inlined macro.
pool_count:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pool_count"
    lda #0                              ; the answer on the guard path
    cpx #0
    beq @done
    txa
    asl a                               ; A = 2*count: the offset one PAST the
    tay                                 ;   last slot; the scan pre-decrements
    ldx #0                              ; X accumulates the live count
@scan:
    .a16
    .i16
    dey
    dey
    lda [ES_POOL_PTR], y
    beq @skip
    inx
@skip:
    .a16
    .i16
    cpy #0                              ; `lda` clobbered `dey`'s Z, so the
    bne @scan                           ;   bound needs its own compare
    txa                                 ; the count answers in A
@done:
    .a16
    .i16
    rts
