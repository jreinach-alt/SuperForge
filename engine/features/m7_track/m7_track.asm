; =============================================================================
; m7_track.asm — the frame-indexed Mode 7 matrix-track player
; =============================================================================
; One macro and one routine over one 4-byte DP pointer (ES_M7T_PTR):
;
;  M7T_BIND <addr24> main thread stamp the track blob's base
;  m7t_apply main thread entry index in A -> m7_affine's shadow
;
; A TRACK is a matrix blob (feature.toml carries the full format):
;  +0 u16 N = entry count (1..256 — a generator contract, unenforced
;  here for the same reason pool.asm's (c) leaves its upper
;  bound to the caller: the data is baked by our own generator,
;  which asserts it, and a runtime guard would turn a build bug
;  into a plausible matrix)
;  +2+4*i i16 M7A of entry i (cos * scale) >> 8 — bytes 1..2 of the
;  +4+4*i i16 M7B of entry i 32-bit product, floor-shifted and baked
;
; The other two matrix words are DERIVED here by the uniform-scale identity:
; M7C = -M7B with the negate taken AFTER the baked shift (two's complement,
; `eor #$FFFF` + `inc a`) — negate first and the rounding differs by a bit at
; the odd scale. M7D = M7A. Two words stored, not four.
;
; WHY THE WRITE LANDS IN m7_affine's SHADOW rather than a shadow of its own:
; that feature already owns the eight-port NMI commit that latches the matrix
; with the pivot and origin tear-free, and it is UNTOUCHED by this feature —
; m7t_apply writes exactly the eight bytes m7a_set_heading writes, from a track
; entry instead of the scale-1.0 heading LUT. A second shadow would be a second
; owner for one register set, which is the class the reg gate exists to refuse.
;
; OUT-OF-RANGE INDICES CLAMP to the last entry, so a state timer that
; overshoots its track rests on the final pose instead of reading past the
; blob. A RING track (N = 256, indexed by a masked heading byte) never clamps,
; by construction of the mask.
;
; Must NOT set .p816/.smart — included into a parent that already does.
; =============================================================================

;
; M7T_BIND <addr24> — stamp the track blob's base for the next apply.
;
; `addr24` is a 24-bit CONSTANT expression (an emitted ES_R_*_LONG). Two 16-bit
; stores; A is clobbered, X and Y are not. POOL_BIND's shape, and its width
; warning verbatim: the silent breach is the assembler tracking A16 while the
; CPU is in A8 — both stores assemble full width, the CPU reads the second
; operand byte as an opcode, and a stray $00 executes as BRK.
;
; WIDTH-RISK: requires A16 on entry and leaves A16. Contains no sep/rep and
; toggles neither width axis, so it drops into an A16/I16 kernel.
.macro M7T_BIND addr24
    lda #.loword(addr24)
    sta z:ES_M7T_PTR
    lda #.hiword(addr24)                ; bank byte in the low half; the high
    sta z:ES_M7T_PTR + 2                ;   half lands on the claim's pad byte
.endmacro

;
; m7t_apply — apply track entry A to the m7_affine matrix shadow.
;
; In: A16/I16. A = entry index (ENTRIES, not bytes). ES_M7T_PTR bound. Out:
; A16/I16. ES_M7AFF+0..+7 = the entry's M7A/M7B/M7C/M7D. X PRESERVED
;  (consumers keep pool cursors there — pool.asm's idiom); A and Y
;  clobbered. DB irrelevant (all data access is [dp] indirect long).
;
; The commit to hardware is NOT here: the NMI hook's m7a_nmi_commit latches the
; shadow's eight ports during VBlank, so a mid-frame apply cannot tear.
;
; WIDTH-RISK: A16/I16 entry AND exit, no sep/rep anywhere in the routine.
; Cross-file callers are invisible to width_lint, so this contract is the
; checkable statement (CLAUDE.md rule 6's single-file limit).
m7t_apply:
    .a16
    .i16
    cmp [ES_M7T_PTR]                    ; index >= count?
    bcc @in_range
    lda [ES_M7T_PTR]
    dec a                               ; clamp to the last entry
@in_range:
    .a16
    asl
    asl                                 ; * 4 bytes per entry...
    inc a
    inc a                               ; ...+ 2 for the count header
    tay
    lda [ES_M7T_PTR], y
    sta z:ES_M7AFF + 0                  ; M7A
    sta z:ES_M7AFF + 6                  ; M7D = M7A (uniform scale)
    iny
    iny
    lda [ES_M7T_PTR], y
    sta z:ES_M7AFF + 2                  ; M7B
    eor #$FFFF
    inc a
    sta z:ES_M7AFF + 4                  ; M7C = -M7B (negated AFTER the baked
                                        ;  floor shift — negating first would
                                        ;  round differently)
    rts
