; =============================================================================
; sf_core.inc — boot + debug-region macros (macro library, rung A0)
; =============================================================================
; The first rung of the keystone macro library. These macros own the boot
; contract and the debug-region protocol that every later ROM and every test
; depends on. They expand to self-contained 65816 — no engine, no init.inc,
; no external runtime is required to use them.
;
; This file is `.include`d AFTER header.inc, which sets `.p816` / `.smart` and
; leaves the assembler in the VECTORS segment. Macros here emit into whatever
; segment is active at their call site, so the call site must select CODE
; first (see tests/a0_coldstart.asm).
;
; Macros
; ------
;   sf_coldstart        Full CPU bring-up + 128 KB WRAM clear. Owns RESET.
;                       Falls through to the next instruction in A16/I16.
;   sf_debug_magic      Write the "SFDB" magic to $7E:E000 (proves boot reached).
;   sf_debug_complete   Write $0001 to $7E:E008 (proves the ROM ran to the end).
;
; Debug-region contract (WRAM bank $7E)
; -------------------------------------
;   $E000-$E003   "SFDB" magic
;   $E008-$E009   completion flag ($0001)
; A test reads these back over MesenRunner:
;   read_bytes(SnesWorkRam, 0xE000, 4) == b"SFDB"
;   read_u16  (SnesWorkRam, 0xE008)    == 1
; =============================================================================

.ifndef SF_CORE_INC
SF_CORE_INC = 1

DEBUG_MAGIC      = $E000        ; "SFDB" (4 bytes)
DEBUG_COMPLETE   = $E008        ; completion flag (2 bytes)
DEBUG_STATE      = $E016        ; canonical scene/win-state mirror (2 bytes)

; -----------------------------------------------------------------------------
; sf_coldstart — standard SNES cold-boot, owning the RESET entry point.
; -----------------------------------------------------------------------------
; Invoke this as the first thing under your RESET label. It performs the full
; native-mode bring-up, blanks the screen, enables FastROM, clears all 128 KB
; of WRAM via DMA, restores the stack (the clear zeroed it), and falls through
; to the next instruction. After it runs:
;   - native mode (65816), A/X/Y 16-bit
;   - stack at $1FFF, Direct Page $0000, Data Bank $00
;   - interrupts + NMI disabled, screen force-blanked, FastROM on
;   - all WRAM ($7E:0000-$7F:FFFF) zeroed
;   - all CGRAM (256 colours) zeroed -> defined black backdrop + palettes
;   - all VRAM (64 KB) zeroed -> defined (empty) tiles + tilemaps
;
; Leaving NO undefined hardware state is the point: a project never has to
; reason about power-on garbage in CGRAM/VRAM. Set the colours/tiles you want
; on top of this defined-zero baseline; anything you don't set stays black/empty
; rather than showing nondeterministic power-on memory.
;
; WIDTH-RISK: entry = emulation mode / width unknown (hardware RESET state).
; Exit = native, A16/I16 (.a16/.i16 asserted at the tail). The macro toggles
; A-width several times internally; the final `rep #$30` + `.a16`/`.i16` is the
; documented exit contract the fall-through code relies on.
;
; The DMA zero-source byte is emitted inside the macro and branched over, so
; the macro is fully self-contained and never executes its own data byte.
.macro sf_coldstart
    .local _zero_byte, _boot
    bra _boot               ; skip over the inline DMA zero-source byte
_zero_byte:
    .byte $00
_boot:
    sei                     ; disable IRQ
    clc
    xce                     ; native mode (clear emulation flag)
    rep #$30
    .a16
    .i16
    ldx #$1FFF              ; stack -> top of low RAM
    txs
    lda #$0000
    tcd                     ; Direct Page -> $0000
    sep #$20
    .a8
    lda #$00
    pha
    plb                     ; Data Bank -> $00
    rep #$20
    .a16

    ; --- Force blank, disable NMI/IRQ/auto-joypad, enable FastROM ---
    sep #$20
    .a8
    lda #$80
    sta $2100               ; INIDISP: forced blank
    stz $4200               ; NMITIMEN: NMI/IRQ/auto-joypad off
    lda #$01
    sta $420D               ; MEMSEL: FastROM

    ; --- Clear WRAM bank $7E via DMA ch0 (fixed source = _zero_byte) ---
    rep #$20
    .a16
    stz $2181               ; WRAM addr low/mid = $0000
    sep #$20
    .a8
    stz $2183               ; WRAM bank bit = 0 ($7E)
    lda #$08                ; DMA: fixed source, single dest register
    sta $4300
    lda #$80                ; dest = $2180 (WRAM data port)
    sta $4301
    rep #$20
    .a16
    lda #.loword(_zero_byte)
    sta $4302
    sep #$20
    .a8
    lda #^_zero_byte
    sta $4304
    rep #$20
    .a16
    stz $4305               ; count $0000 -> 65536 bytes (full bank)
    sep #$20
    .a8
    lda #$01
    sta $420B               ; start DMA ch0 -> clears $7E

    ; --- Clear WRAM bank $7F (same fixed source) ---
    lda #$01
    sta $2183               ; WRAM bank bit = 1 ($7F)
    rep #$20
    .a16
    stz $4305               ; count $0000 again
    sep #$20
    .a8
    lda #$01
    sta $420B               ; start DMA ch0 -> clears $7F

    ; --- Clear CGRAM (256 colours -> black): no undefined backdrop/palettes ---
    ; Screen is force-blanked above, so CGRAM is writable. CGADD auto-increments
    ; after each colour's high byte, so two stz $2122 per colour walk all 256.
    rep #$10
    .i16
    sep #$20
    .a8
    stz $2121               ; CGADD = 0
    ldx #$0000
:   stz $2122               ; colour low  = 0
    stz $2122               ; colour high = 0
    inx
    cpx #$0100              ; 256 colours
    bne :-

    ; --- Clear VRAM (64 KB -> 0): no undefined tiles/tilemaps ---
    ; Reuse the fixed-source _zero_byte on DMA ch0, mode 1 (2 regs -> $2118/9).
    lda #$80
    sta $2115               ; VMAIN: +1 word, increment after high byte
    rep #$20
    .a16
    stz $2116               ; VMADD = 0
    sep #$20
    .a8
    lda #$09                ; DMAP: fixed source (bit3), mode 1 (write L/H)
    sta $4300
    lda #$18                ; BBAD: dest $2118 (VMDATAL)
    sta $4301
    rep #$20
    .a16
    lda #.loword(_zero_byte)
    sta $4302
    sep #$20
    .a8
    lda #^_zero_byte
    sta $4304               ; source bank
    rep #$20
    .a16
    stz $4305               ; count $0000 -> 65536 bytes (all of VRAM)
    sep #$20
    .a8
    lda #$01
    sta $420B               ; start DMA ch0 -> clears VRAM

    ; --- Restore stack (WRAM clear zeroed it) and exit A16/I16 ---
    rep #$30
    .a16
    .i16
    ldx #$1FFF
    txs
.endmacro

; -----------------------------------------------------------------------------
; sf_debug_magic — write the "SFDB" magic to $7E:E000.
; -----------------------------------------------------------------------------
; Proves the ROM booted and reached this point. WRAM above $8000 in bank $00
; maps to ROM under LoROM, so $7E:E000 needs true 24-bit addressing; the
; `ldx #0` + `sta f:$7E0000+addr,x` form (opcode $9F, absolute-long,X) is the
; reliable encoding (a bare `sta f:$7Exxxx` can be mis-encoded DB-relative).
;
; WIDTH-RISK: asserts its own A16/I16 entry width (safe-by-default) rather than
; trusting the caller, so it is correct regardless of preceding width state.
.macro sf_debug_magic
    rep #$30
    .a16
    .i16
    ldx #$0000
    lda #$4653              ; "SF"  ('S'=$53 lo, 'F'=$46 hi)
    sta f:$7E0000 + DEBUG_MAGIC, x
    lda #$4244              ; "DB"  ('D'=$44 lo, 'B'=$42 hi)
    sta f:$7E0000 + DEBUG_MAGIC + 2, x
.endmacro

; -----------------------------------------------------------------------------
; sf_debug_complete — write the completion flag $0001 to $7E:E008.
; -----------------------------------------------------------------------------
; Proves the ROM ran all the way to the end (typically the last write before
; STP). Same 24-bit addressing rationale as sf_debug_magic.
;
; WIDTH-RISK: asserts its own A16/I16 entry width (safe-by-default).
.macro sf_debug_complete
    rep #$30
    .a16
    .i16
    ldx #$0000
    lda #$0001
    sta f:$7E0000 + DEBUG_COMPLETE, x
.endmacro

; -----------------------------------------------------------------------------
; sf_state_mirror value — write the current scene/win-state to $7E:E016.
; -----------------------------------------------------------------------------
; Gives the generalized verification oracle a self-describing, canonical hook to
; the template's win/lose/scene machine, so it never has to recover that address
; from prose or per-template config. The macro owns the *location* ($E016) and
; the write mechanism; the *meaning* of each value (which one is "win") lives in
; the template's oracle.json [state] block. Call on every state transition:
;
;   STATE_WAIT = 0 : STATE_PLAY = 1 : STATE_OVER = 2 : STATE_WIN = 3
;   ...
;   lda #STATE_PLAY
;   sf_state_mirror                 ; value already in A (16-bit)
;   ; or, for a constant transition:
;   sf_state_mirror STATE_WIN       ; loads the immediate for you
;
; For a state held in a variable, mirror it directly instead:
;   lda MY_STATE_VAR  ;  ldx #0 : sta f:$7E0000 + DEBUG_STATE, x
;
; Same 24-bit absolute-long,X addressing rationale as sf_debug_magic (WRAM above
; $8000 in bank $00 maps to ROM under LoROM).
;
; WIDTH-RISK: asserts its own A16/I16 entry width (safe-by-default); when called
; with no argument the caller's A value is preserved (rep widens, low 16 bits
; intact). When called with an argument the macro loads it as a 16-bit immediate.
.macro sf_state_mirror value
    rep #$30
    .a16
    .i16
    ldx #$0000
.if .paramcount > 0
    lda #value
.endif
    sta f:$7E0000 + DEBUG_STATE, x
.endmacro

.endif ; SF_CORE_INC
