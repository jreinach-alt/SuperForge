; =============================================================================
; sf_asm.inc — the shared 65816 macro header
; =============================================================================
; WHERE IT LIVES, AND WHY HERE. Every ROM in this tree already assembles with
; `-I vendor/rom` (the Makefile spells it as `$(VROM)` on all 37 rails), and
; this directory is where the first-party includes every ROM shares already
; sit — `header.inc`, `init.inc`, `ppu_reset.inc`. Putting the macro header
; beside them costs no per-rail include path and no Makefile edit, which is
; what makes it adoptable one site at a time. It is first-party, like the rest
; of this directory (docs/92 §, `vendor/rom/` = authored here), and it is in
; `make width-check`'s target set for exactly the reason the lint exists: a
; macro is the one place a width mistake is written ONCE and assembled many
; times.
;
; Include it AFTER the generated `engine_state_*.inc` (nothing here reads an
; emitted symbol, but every CALLER's arguments do) and before the code that
; uses it. It emits NO bytes on its own: everything here is either an equate,
; an assertion, or a macro that is only expanded where it is written.
;
; -----------------------------------------------------------------------------
; WHAT IS IN HERE
; -----------------------------------------------------------------------------
;   1. Placement assertions — SF_ASSERT_DP / SF_ASSERT_NO_PAGE_CROSS /
;      SF_ASSERT_NO_BANK_CROSS. A routine states where its data must LIVE for
;      its own addressing modes to be correct.
;   2. Data-bank idioms — SF_SET_DB / SF_SET_P_DB. The push-effective-address
;      forms that establish DB (and, in the second, the status byte with it)
;      from a build-time constant without spending the accumulator.
;
; Every macro here carries a contract comment: what it expects on entry, what
; it leaves, what it clobbers, and what it asserts. A macro whose contract is
; not written down is a macro whose caller has to read its body, which is the
; opposite of why it exists.
;
; -----------------------------------------------------------------------------
; THE PLACEMENT-ASSERTION DOCTRINE, IN ONE SENTENCE
; -----------------------------------------------------------------------------
; THE ALLOCATOR IS THE AUTHORITY ON WHERE THINGS GO; THESE ASSERTIONS STATE
; WHERE THE CODE NEEDS THEM.
;
; They are not a second placement mechanism and they must never become one.
; `allocator/allocate.py` packs every claim and emits the symbol; nothing here
; moves a byte, and a failing assertion is never fixed by editing the
; assertion. What they add is the OTHER direction: a routine that reads its
; table with `abs,x`, or fires a DMA from a blob, or reaches its state through
; `z:`, is depending on a property of the placement it was handed — that the
; symbol fits direct-page addressing, that the block does not cross a page,
; that the block does not cross a bank. Those dependencies were prose, in a
; header comment, checked by whoever last read it. Written as an assertion
; they are checked by ca65 on every build, and a re-pack that breaks one stops
; the build naming the claim instead of shipping a blob read as its
; neighbour's bytes.
;
; So: an assertion added here must be TRUE on the day it is written. It
; CODIFIES a property the code already relies on. If one fires, the answer is
; a declaration change (a size, an alignment, a window) — never a weaker
; assertion.

; -----------------------------------------------------------------------------
; THE UNITS
; -----------------------------------------------------------------------------
; Written as shifts rather than as 256 / 65536 for the reason tick_scale.asm
; gives: `no_literals` reads an operand's numeric tokens and cannot tell a page
; size from an address, and building every constant out of shifts keeps the
; arithmetic visible AND the gate satisfied.
SF_PAGE = 1 << 8                ; bytes in one 65816 page
SF_BANK = 1 << 16               ; bytes in one 65816 bank

; Bank $00 — the CPU's own map (I/O at $2100-$21FF / $4200-$43FF, and the
; direct page). It is NOT an allocated resource, so no allocator symbol names
; it; this equate exists so a DB establishment can say WHICH bank in the same
; symbolic shape an allocated one would (`SF_SET_DB SF_BANK_SYS`) instead of
; spelling a bare number at the call site.
SF_BANK_SYS = 0

; =============================================================================
; SF_ASSERT_DP — this symbol must be reachable by direct-page addressing
; =============================================================================
;   SF_ASSERT_DP <symbol>, "<message>"
;
; In/out: nothing. Emits no bytes, touches no register, is legal in any
; segment and at any width.
;
; Asserts: the symbol's address is inside the direct page. DP is $0000 for the
; program's life (vendor/rom/init.inc's `tcd`, the tree's one setting of it),
; so "inside the direct page" and "below $0100" are the same statement here —
; which is why this takes the symbol and not a base/size pair.
;
; Write it beside a routine that reaches its state through `z:`. `z:` is a
; FORCED direct-page mode: ca65 emits the 2-byte form whatever the symbol's
; value is, so a claim that grows past the page does not produce an assembler
; error, it produces a store to the wrong byte of page zero. That is the hole
; this closes.
.macro SF_ASSERT_DP sf_sym, sf_msg
    .assert (sf_sym) < SF_PAGE, error, sf_msg
.endmacro

; =============================================================================
; SF_ASSERT_NO_PAGE_CROSS — this block lies inside one page
; =============================================================================
;   SF_ASSERT_NO_PAGE_CROSS <base>, <size in bytes>, "<message>"
;
; In/out: nothing. Emits no bytes, touches no register.
;
; Asserts: base .. base+size-1 share a page — i.e. the low byte can be stepped
; across the whole block without the high byte having to move. Write it where
; an indexed walk depends on that: a table whose index is added to the LOW byte
; only, a direct-page block indexed with `z:sym,x` (where x must not carry the
; walk out of the page the symbol was placed in), a run whose end is computed
; as `base + size` and compared as a byte.
;
; `size` is in BYTES and must be positive — a zero-length block has no last
; byte to test and would pass vacuously, so it is refused rather than allowed.
.macro SF_ASSERT_NO_PAGE_CROSS sf_base, sf_size, sf_msg
    .assert (sf_size) > 0, error, "SF_ASSERT_NO_PAGE_CROSS: size must be positive"
    .assert (((sf_base) + (sf_size) - 1) >> 8) = ((sf_base) >> 8), error, sf_msg
.endmacro

; =============================================================================
; SF_ASSERT_NO_BANK_CROSS — this block lies inside one bank
; =============================================================================
;   SF_ASSERT_NO_BANK_CROSS <base>, <size in bytes>, "<message>"
;
; In/out: nothing. Emits no bytes, touches no register.
;
; Asserts: base .. base+size-1 share a bank. This is CLAUDE.md rule 4's first
; clause made checkable — a DMA's A-bus address wraps WITHIN its bank rather
; than carrying into the next one, and MVN/MVP take their banks as operands
; and wrap the same way, so a block transfer whose source straddles a bank
; seam silently reads the bank's own low bytes instead of the neighbour's.
;
; `base` may be a 16-bit in-bank offset (an emitted `ES_R_*_ADDR`, where the
; test reads "does this run past $FFFF") or a full 24-bit address (an emitted
; `_LONG`, or a `(BANK << 16) | ADDR` built from the pair). Both work: the
; expression compares the bank byte of the first and last bytes of the block,
; and a 16-bit base simply has bank 0 on both sides of the comparison.
.macro SF_ASSERT_NO_BANK_CROSS sf_base, sf_size, sf_msg
    .assert (sf_size) > 0, error, "SF_ASSERT_NO_BANK_CROSS: size must be positive"
    .assert (((sf_base) + (sf_size) - 1) >> 16) = ((sf_base) >> 16), error, sf_msg
.endmacro

; =============================================================================
; SF_SET_DB — establish the data bank from a build-time constant
; =============================================================================
;   SF_SET_DB <bank byte expression>
;
; In: any A width, any I width, any DB. Out: DB = the named bank, WIDTH
; UNCHANGED — this macro contains no `sep`/`rep` at all, so it cannot leak a
; width to its caller and needs no directive after it.
;
; Clobbers: N and Z (`plb` sets them from the byte it pulls). A, X, Y, DP and
; the carry are untouched. Costs 13 cycles in 5 bytes; the stack rises by two
; bytes and comes straight back down, so the site must be one where the stack
; is writable (i.e. anywhere in this engine except between a push and its
; matching pull).
;
; WHY, against the `lda #bank / pha / plb` form it replaces. That form spends
; the accumulator, and — the part that actually costs — it only works in A8, so
; a caller sitting in A16 pays a `sep`/`rep` round trip around it and two width
; annotations for the assembler to track through. `pea` pushes a 16-bit
; immediate whatever the M flag says, so the bank byte is duplicated into both
; halves of one push and pulled twice: the first `plb` takes the low copy into
; DB, the second takes the high copy (into DB again, harmlessly) and balances
; the stack. Measured against the A16 form it replaces: 16 cycles / 9 bytes
; becomes 13 / 5, A survives, and the two width transitions disappear.
;
; It does NOT replace a bank the code COMPUTED — `pea` takes a build-time
; constant, so a chunk bank derived from a row index still goes through
; `pha`/`plb` with the value already in A. Those sites are not worse; they are
; a different shape.
.macro SF_SET_DB sf_bank
    .assert (sf_bank) >= 0 && (sf_bank) < SF_PAGE, error, "SF_SET_DB: the bank must be a single byte"
    ; `.loword` is not decoration: a `pea` operand that STARTS with `(` is
    ; parsed as an indirect addressing mode and refused as "Illegal
    ; addressing mode", so the word is built inside a function call.
    pea .loword((sf_bank) | ((sf_bank) << 8))
    plb
    plb
.endmacro

; =============================================================================
; SF_SET_P_DB — establish the status byte AND the data bank together
; =============================================================================
;   SF_SET_P_DB <bank byte expression>, <P byte expression>
;
; In: any A width, any I width, any DB, any P. Out: P = the named status byte,
; DB = the named bank. Costs 13 cycles in 5 bytes; A, X, Y and DP untouched;
; the stack rises two bytes and comes back down.
;
; The same push, read as two bytes instead of one: `pea` pushes high byte then
; low, so `plp` takes the low half (the status) and `plb` takes the high half
; (the bank). One constant, one push, and both of the things a routine's entry
; contract is written in are established at once — which is what makes it worth
; naming, because the two are normally set by two unrelated sequences and only
; the comment says they belong together.
;
; WIDTH-RISK: `plp` establishes the M and X flags AT RUNTIME and ca65 cannot
; see through it — the assembler's tracked width after this macro is whatever
; it was before. THE CALLER MUST FOLLOW IT with the `.a8`/`.a16` and
; `.i8`/`.i16` that match the P byte it passed. This is the one macro here
; that leaves an obligation behind.
;
; AND IT ESTABLISHES THE WHOLE BYTE, not the width bits: the interrupt-disable,
; decimal, carry, overflow, negative and zero flags all become whatever the
; constant says. That is the point where it is right (an entry that is defining
; its own machine state) and a defect anywhere else. In particular a constant
; with the interrupt-disable bit clear UNMASKS interrupts, which inside an ISR
; is not a style change.
;
; ADOPTED NOWHERE TODAY, and deliberately: see AGENTS.md — the tree's DB setups
; either need only the bank (SF_SET_DB is strictly better there) or sit in the
; NMI entry and the RESET path, where the form costs a cycle to save a byte and
; would newly pin flags those two paths currently inherit. It is written down
; here because it is the counterpart idiom and the next entry contract that
; wants both should not have to re-derive it.
.macro SF_SET_P_DB sf_bank, sf_p
    .assert (sf_bank) >= 0 && (sf_bank) < SF_PAGE, error, "SF_SET_P_DB: the bank must be a single byte"
    .assert (sf_p) >= 0 && (sf_p) < SF_PAGE, error, "SF_SET_P_DB: the status must be a single byte"
    ; `.loword` for the reason SF_SET_DB gives: a `pea` operand starting
    ; with `(` is parsed as an indirect mode.
    pea .loword((sf_p) | ((sf_bank) << 8))
    plp
    plb
.endmacro
