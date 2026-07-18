; SuperForge — Canonical full PPU-register power-on init
;
; Purpose
; -------
; Power-on FULL-fidelity. Real SNES hardware (and Mesen2 with
; EnableRandomPowerOnState=True) leaves the PPU register-mirror state
; SCRAMBLED at cold power-on (SnesPpu::RandomizeState). A ROM that never
; re-initializes those registers leaks the random latch state into the
; rendered frame indefinitely — the whole-frame power-on flap class.
;
; This block writes EVERY display-affecting PPU register $2101-$2133 to a
; known value under forced blank, flushing the write-twice latches (scroll +
; Mode-7 matrix/center) by writing each twice. After it runs, the rendered
; frame is byte-identical across fresh power-ons whether the PPU latches are
; randomized or not — and identical to the no-latch golden (the writes are
; the same values Mesen's default PPU init already holds, so it is
; pixel-transparent on the default path).
;
; This is the bare-metal-correct discipline regardless of emulator: official
; SNES Dev Manual, Book 1 p.2-26-1 (forced blank -> full register init ->
; write-twice flush).
;
; Contract / usage
; ----------------
;   - INCLUDE this AFTER forced blank is asserted ($2100 = $80) and BEFORE
;     NMI is enabled / any VRAM/CGRAM/OAM upload or display enable.
;   - The CPU must be in 8-bit accumulator mode (.a8 / sep #$20) on entry;
;     every write here is an 8-bit register store. The block neither toggles
;     nor depends on index width, and leaves A-width unchanged (A8 in, A8 out).
;   - Data Bank does not matter: $21xx are bank-$00 I/O writes; ca65 emits
;     absolute (DB-relative) stores. The standard RESET paths that include
;     this run with DB=$00, so $00:21xx hits the PPU.
;
; The canonical order + value set below is exactly the proof-of-concept block
; that produced a byte-identical golden under latches-on for both a Mode-7
; ROM (s1) and a Mode-1 ROM (s2). Do NOT prune it to a subset — a hand-pruned
; "minimal gap" subset left the top sky row flapping (plan §3).
;
; WIDTH-RISK: A8 entry/exit — all PPU writes are 8-bit. The write-twice
; latch flushes (two stz to the same scroll / Mode-7 register) toggle nothing
; risky: they only push two $00 bytes through the register's shared
; write-twice latch so its final 16-bit value is a known $0000.

; --- $2101-$210C: OBJ / BG mode / mosaic / tilemap + chr base (single write) ---
    stz $2101               ; OBSEL    — OBJ size/base
    stz $2102               ; OAMADDL  — OAM address low
    stz $2103               ; OAMADDH  — OAM address high + priority-rotate
    stz $2105               ; BGMODE   — BG mode + BG3 priority + tile sizes
    stz $2106               ; MOSAIC   — mosaic size + enable
    stz $2107               ; BG1SC    — BG1 tilemap base/size
    stz $2108               ; BG2SC    — BG2 tilemap base/size
    stz $2109               ; BG3SC    — BG3 tilemap base/size
    stz $210A               ; BG4SC    — BG4 tilemap base/size
    stz $210B               ; BG12NBA  — BG1/BG2 chr base
    stz $210C               ; BG34NBA  — BG3/BG4 chr base

; --- $210D-$2114: BG scroll (write-twice — flush the shared HOFS/VOFS latch) ---
    stz $210D               ; BG1HOFS
    stz $210D
    stz $210E               ; BG1VOFS
    stz $210E
    stz $210F               ; BG2HOFS
    stz $210F
    stz $2110               ; BG2VOFS
    stz $2110
    stz $2111               ; BG3HOFS
    stz $2111
    stz $2112               ; BG3VOFS
    stz $2112
    stz $2113               ; BG4HOFS
    stz $2113
    stz $2114               ; BG4VOFS
    stz $2114

; --- $2115 VMAIN, $211A M7SEL (single write) ---
    stz $2115               ; VMAIN    — VRAM increment mode
    stz $211A               ; M7SEL    — Mode-7 screen-over / mirror flags

; --- $211B-$2120: Mode-7 matrix + center (write-twice — flush shared latch) ---
    stz $211B               ; M7A
    stz $211B
    stz $211C               ; M7B
    stz $211C
    stz $211D               ; M7C
    stz $211D
    stz $211E               ; M7D
    stz $211E
    stz $211F               ; M7X (center X)
    stz $211F
    stz $2120               ; M7Y (center Y)
    stz $2120

; --- $2121 CGADD (single write) ---
    stz $2121               ; CGADD    — CGRAM address

; --- $2123-$212B: window mask block (single write) ---
    stz $2123               ; W12SEL   — window 1/2 BG1/BG2 enable+invert
    stz $2124               ; W34SEL   — window 1/2 BG3/BG4 enable+invert
    stz $2125               ; WOBJSEL  — window 1/2 OBJ/color enable+invert
    stz $2126               ; WH0      — window 1 left
    stz $2127               ; WH1      — window 1 right
    stz $2128               ; WH2      — window 2 left
    stz $2129               ; WH3      — window 2 right
    stz $212A               ; WBGLOG   — window BG mask logic
    stz $212B               ; WOBJLOG  — window OBJ/color mask logic

; --- $212C-$212F: main/sub screen + window-mask main/sub (single write) ---
    stz $212C               ; TM       — main screen layer enable
    stz $212D               ; TS       — sub screen layer enable
    stz $212E               ; TMW      — window mask main screen
    stz $212F               ; TSW      — window mask sub screen

; --- $2130-$2133: color math + fixed color + SETINI (known defaults) ---
    lda #$30
    sta $2130               ; CGWSEL   — color-math control (clip/prevent off,
                            ;            direct-color off; $30 = HW default)
    stz $2131               ; CGADSUB  — color-math add/sub enable (all off)
    lda #$E0
    sta $2132               ; COLDATA  — fixed color = black (R=G=B=0; $E0
                            ;            selects all 3 channels, value 0)
    stz $2133               ; SETINI   — interlace / hires / overscan / extbg
