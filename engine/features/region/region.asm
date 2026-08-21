; =============================================================================
; region.asm — the console's own region line, read once at boot
; =============================================================================
; ES_RGN_PAL reads 0 on an NTSC console and 1 on a PAL one. That word is the
; whole of this feature's public surface: game code reads it with one
; `lda z:ES_RGN_PAL` and branches.
;
; WHERE THE BIT COMES FROM. $213F is STAT78, the PPU status byte. Bit 4 is the
; console's region line and is SET on PAL. Measured in-ROM rather than taken
; from a document — docs/95 §1.3 patched the read into a built image and read
; it back out of WRAM: $03 under SF_REGION=ntsc, $13 under pal. Bits 0-3 are
; the PPU version (3 on both machines) and bit 7 is the odd/even frame flag,
; which changes under the ROM's feet — so the test is a MASK on bit 4, never a
; compare against $13.
;
; READING $213F ALSO RESETS THE OPHCT/OPVCT READ FLIP-FLOPS. That side effect
; is the only reason the other three $213F reads in this tree exist
; (sit_cam.asm:409,430 / shg_cam.asm:475,496 / m7f_cam.asm:230), and it is why
; a boot-time read here cannot disturb them: every one of those sites issues
; its OWN `lda a:$213F` immediately before the $213C/$213D pair it cares
; about, so the toggle state each of them reads from is the one it has just
; established. Read those sites rather than believing this paragraph — they
; are three lines each and the pattern fits on one screen.
;
; NO [[claims.reg]]. The reg-ownership pass in allocator/no_literals.py is a
; WRITER-side gate — its write set is sta/stx/sty/stz plus the RMW family —
; and this feature never writes a PPU port. Read, not asserted: the pass is
; read in that file, and the three $213F sites above have carried no reg claim
; for as long as they have existed.

; Bit 4 of $213F, written as a shift rather than as $10. `no_literals` reads an
; operand's numeric tokens and cannot tell a hardware bit from an address, so
; the hex form is refused — and the gate is right to refuse it. The shift also
; says what the number IS, which $10 does not.
RGN_PAL_BIT = 1 << 4

; --- region_init: boot init contract ---------------------------------------
; In/out: A16/I16, DB=0. Clobbers A. Call ONCE from MAIN's boot block.
;
; The word is written on BOTH paths — stz first, then the PAL case — because
; power-on RAM is random, and a flag written in only one branch reads garbage
; on the other machine (CLAUDE.md rule 5).
region_init:
    .a16
    .i16
    stz z:ES_RGN_PAL
    sep #$20
    .a8
    lda a:$213F
    and #RGN_PAL_BIT
    beq @done
    rep #$20
    .a16
    lda #1
    sta z:ES_RGN_PAL
    sep #$20
    .a8
@done:
    .a8
    .i16
    rep #$20
    .a16
    rts
