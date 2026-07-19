; =============================================================================
; seam_irq_trial — SEAM-IRQ TRIAL: band-2 Mode-7 origin via a SEAM-SCANLINE
;                  IRQ + pre-armed GP-DMA pair, vs the classic HDMA-origin
;                  control. A trial rail that proves H1 + H2 (below) in isolation,
;                  before the composed split_h_irq_grad_demo template relies on them.
; =============================================================================
; WHAT IS PROVEN HERE (the two riskiest unknowns of the seam-IRQ line):
;
;   H1 — `wai` wakes on IRQ too. The classic loop's wai-then-write pattern
;        assumes NMI woke it; with a mid-frame IRQ armed, wai ALSO returns at
;        the seam. The loop below gates on the NMI counter (sleep until E010
;        actually advanced); the raw wake counter at $7E:E058 measures ~2
;        wakes/frame (IRQ + NMI) while the cadence gate stays +1/+1 — the
;        hazard is real AND the gate closes it.
;
;   H2 — the seam write window. Timing model, VERIFIED against the emulator
;        core source (kit rule 7) AND corrected by on-emulator measurement
;        (the first trial build fired one content line early — see below):
;          * THE RENDER PIPELINE IS ONE LINE DEEP: content line L's pixels are
;            drawn during INTERNAL scanline L+1 (SnesPpu.cpp:1410 — the output
;            row is `_scanline + 6` while the harness screenshot offset for
;            content line L is L + 7; internal scanline 0 is a pre-render line
;            and is never drawn, SnesPpu.cpp:883 `_scanline > 0`). The V
;            counter (IRQ match + OPVCT latch) counts INTERNAL scanlines.
;            => the seam-write IRQ arms VTIME = SEAM (112) — the fire lands in
;            internal scanline 112's trailing HBlank: content line 111 (drawn
;            during scanline 112) is already flushed, content line 112 (drawn
;            during scanline 113) picks the new values up. VTIME = SEAM - 1
;            corrupts content line 111 — measured, one full row wrong.
;          * V-IRQ fire point: the V counter increments at H-clock 6 of each
;            scanline; on VTIME match the IRQ latches through a master-clock/4
;            tick circuit -> CPU IRQ asserted ~H-clock 14 (dot ~3) of the
;            matching internal scanline (InternalRegisters.h: UpdateIrqLevel +
;            ProcessIrqCounters). H+V: asserted 2 ticks after the H counter
;            (in dots) matches HTIME.
;          * Pixel flush is LAZY: pixels up to hPos-22 are flushed on each PPU
;            register write using PRE-write state (SnesPpu.cpp:1885 Write ->
;            RenderScanline; :883-884 drawEndX = hPos-22), and the line's
;            remainder at end-of-scanline. The practical window: the DMA's
;            B-bus bytes must land after dot ~277 of scanline 112 (all of
;            content line 111 flushed) and complete by dot 22 of scanline 113
;            (content line 112's first flush trigger).
;          * HBlank flag ($4212 bit 6) sets at H-clock > 1096 = dot 274
;            (InternalRegisters.cpp case 0x4212); the per-line HDMA transfer
;            event fires at H-clock 1104 = dot 276 (SnesMemoryManager.cpp
;            HdmaStart). A handler that spin-gates on the HBlank flag and THEN
;            fires MDMAEN always lands strictly after that line's HDMA (the
;            spin exit + fire sequence is >2 dots; if HDMA is mid-transfer the
;            CPU is paused and resumes after) — no GP-DMA/HDMA overlap window.
;            MEASURED (OPHCT/OPVCT latched one instruction after the MDMAEN
;            write returns): HBlank-flag-gated fire completes at dot ~19 of
;            the NEXT internal scanline — inside the window with ~4 dots of
;            hard margin, and the only PPU writes between dot 23 and the
;            completion point are the DMA's own bytes (the next external
;            flush trigger is the matrix-HDMA write at dot 276), so the
;            failure mode of a late fire degrades to a bounded left-edge
;            partial-flush, not a hard wall.
;          * ALL Mode-7 registers share ONE write-twice ValueLatch
;            (SnesPpu.cpp cases $211B-$2120: reg = value<<8 | latch). Each
;            register's lo/hi bytes MUST be written back-to-back; interleaving
;            pairs corrupts BOTH registers. GP-DMA mode $03 (2 regs write
;            twice: B,B,B+1,B+1) delivers exactly the per-register lo/hi
;            order — the same byte pattern the HDMA-origin channel sends.
;          * H+V dot-precision is NOT needed: with the HBlank-flag spin gate,
;            an H+V trigger converges to the same dot-274 sync point as
;            V-only (measured identical completion), and an H+V trigger
;            WITHOUT the gate risks landing MDMAEN in the dot-274..276 zone
;            where GP-DMA start meets the HDMA trigger. V-only + spin gate is
;            the shipping design; -DHV proves the H+V build renders
;            identically through the same gate.
;
; MECHANISM UNDER TEST (default build):
;   Boot (forced blank): band-1's four origin registers written directly
;   (they hold all frame); 2 matrix channels stream the shared fixed-angle
;   pose per band (classic 2p index-table shape); CH0/CH1 (allocator-reserved
;   for general DMA — never handed to HDMA effects) are pre-armed as GP-DMA:
;     CH0: DMAP $03, BBAD $1F, 4 bytes from $7E:C100 -> M7X/M7Y
;     CH1: DMAP $03, BBAD $0D, 4 bytes from $7E:C104 -> M7HOFS/M7VOFS
;   V-only IRQ armed at VTIME = SEAM = 112 (internal scanlines; see H2).
;   Seam IRQ (once/frame): latch + record entry H/V, spin on the HBlank flag,
;   ONE MDMAEN write fires both channels (8 bytes -> the four write-twice
;   pairs; measured completion ~dot 19 of scanline 113), ack, count.
;   VBlank (game loop after gated wai): re-stamp band-1's origin registers
;   directly (VBlank = safe latch window), re-stamp the staged band-2 bytes,
;   re-arm CH0/CH1 A1T/DAS (GP-DMA consumes them every fire).
;
; COMPILE-TIME SWITCHES (variant script passes them):
;   -DHDMA_ORIGIN=1  the CONTROL: classic origin channel pair (NON-REPEAT
;                    DMAP $03 splice) instead of the IRQ+DMA path — the same
;                    static scene through the shipped mechanism. The gold
;                    assertion: default vs control framebuffer BYTE-IDENTICAL.
;   -DMISTIME=1      NON-VACUITY control: VTIME=60 — the same DMA fires in
;                    scanline 60's HBlank, so content lines 60..111 render
;                    with band-2's origin (visibly warm). The SAME full-frame
;                    metric flips.
;   -DHV=1           H+V trigger (HTIME=190) through the same HBlank spin
;                    gate: must render identically to the V-only default
;                    (the H+V-not-needed evidence).
;
; Static scene (both cameras frozen): camera 1 over the COOL stripe (world
; 512,512), camera 2 over the WARM stripe (768,512) — band-2 red = the
; independent-origin signal, cross-ROM pixel equality valid (no motion).
;
; Debug mirrors ($7E:E0xx): E010 NMI count (word), E020 matrix mask, E022
; origin mask (control builds; 0 = channels FREED on the IRQ build), E030
; loop iterations (word), E050 IRQ count (word), E054/E055 entry OPHCT lo/hi,
; E056/E057 entry OPVCT lo/hi, E05A..E05D same pair re-latched post-fire,
; E058 raw wai-wake count (word).
;
; Controls: none — autonomous. The scene is frozen (camera 1 over the cool stripe,
;   camera 2 over the warm stripe) and the seam IRQ fires once per frame on its
;   own. The -DHDMA_ORIGIN / -DMISTIME / -DHV builds select the control variants.
;
; File layout (top to bottom):
;   (interrupts)  NMI (re-arm HDMA + heartbeat) and seam_irq (the seam-scanline
;                 fire) sit above INIT, per the engine's vector convention.
;   INIT          RESET: upload the world + CGRAM + band-1 registers under forced
;                 blank, bind the matrix HDMA pair, then arm the seam IRQ + GP-DMA
;                 pair (or, under -DHDMA_ORIGIN, the classic origin HDMA pair).
;   MAIN LOOP     game_loop — gated wai, then re-stamp the origins in VBlank.
;   SUBROUTINES   origin/stage stampers, seam-DMA arm/re-arm, the allocator-mask
;                 helpers, and the HDMA channel allocator (.include).
;   DATA          the shared fixed-angle pose tables + the 32KB checker map.
;
; Frame loop: `game_loop` is the once-per-frame heartbeat — start reading there.
;
; Build:  make seam_irq_trial
;         bash templates/seam_irq_trial/build_seam_irq_trial_variants.sh
; LDCFG: lorom_64k.cfg   (bank 0 = code + pose tables; BANK1 = 32KB map)
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

.ifndef HDMA_ORIGIN
SF_IRQ_VECTOR = seam_irq        ; engine opt-in IRQ vector — MUST precede the
                                ; header.inc include (forward label ref is fine)
.endif
; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SEAM IRQ TRIAL"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_irq.inc"           ; SHADOW_NMITIMEN compose + arm macros
.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0
.include "engine_state.inc"

; --- band geometry -------------------------------------------------------------
SEAM       = 112                ; band 1 = lines 0..111, band 2 = 112..223
B_LINES    = 112

; --- IRQ timing (dots for HTIME, INTERNAL scanline for VTIME) -------------------
.ifdef MISTIME
VTIME_VAL  = 60                 ; mid-band fire: the corruption control
.else
VTIME_VAL  = SEAM               ; = 112: content line 111 draws during internal
                                ; scanline 112; the fire lands in its trailing
                                ; HBlank and content line 112 picks it up
.endif
HTIME_VAL  = 190                ; -DHV builds only: assert ~dot 192; the HBlank
                                ; spin gate (dot 274) syncs both trigger shapes
                                ; to the same fire point

; --- camera positions (world px; the map wraps at 1024) -------------------------
P1_X0      = 512                ; camera 1: COOL stripe
P1_Y0      = 512
P2_X0      = 768                ; camera 2: WARM stripe (+256 in X)
P2_Y0      = 512

; band origin values (fixed heading: pure subtraction, no solve)
B1_HOFS    = P1_X0 - 128
B1_VOFS    = P1_Y0 - SEAM
B2_HOFS    = P2_X0 - 128
B2_VOFS    = P2_Y0 - 224

; --- CGRAM (15-bit BGR): cool pair = green only; warm pair = green + FULL RED ---
COLOR_BACKDROP    = $5400
COLOR_COOL_DARK   = $01E0       ; G=15
COLOR_COOL_LIGHT  = $03E0       ; G=31
COLOR_WARM_DARK   = $01FF       ; G=15 + R=31
COLOR_WARM_LIGHT  = $03FF       ; G=31 + R=31

FX_M7_MATRIX = $2B              ; allocator effect tags
FX_M7_ORIGIN = $2C

; --- WRAM layout (engine-free $7E:C000 gap; no new DP state -> zp-check clean) --
IDX_AB     = $C000              ; 7 B  AB index table: [$80|112,ptr][$80|112,ptr][0]
IDX_CD     = $C010              ; 7 B  CD index table
OTBL_XY    = $C020              ; 11 B origin table (control build only)
OTBL_HV    = $C040              ; 11 B origin table (control build only)
STAGE_XY   = $C100              ; 4 B  staged band-2 M7X/M7Y bytes (CH0 source)
STAGE_HV   = $C104              ; 4 B  staged band-2 HOFS/VOFS bytes (CH1 source)
PREV_NMI   = $C110              ; word: gated-wai NMI-counter snapshot

G_MSK      = $7EE020            ; word: matrix channel mask (debug read)
G_MSK2     = $7EE022            ; word: origin channel mask (0 on the IRQ build)
G_FRAMES   = $7EE030            ; word: MAIN-LOOP iteration counter (cadence)
G_IRQCNT   = $7EE050            ; word: seam-IRQ fire counter
G_ENTRY_H  = $7EE054            ; 2 B: OPHCT at handler entry (lo, hi bit)
G_ENTRY_V  = $7EE056            ; 2 B: OPVCT at handler entry
G_WAKES    = $7EE058            ; word: raw wai-wake counter (H1 evidence)
G_FIRE_H   = $7EE05A            ; 2 B: OPHCT just after the MDMAEN fire
G_FIRE_V   = $7EE05C            ; 2 B: OPVCT just after the MDMAEN fire

.segment "CODE"

; -----------------------------------------------------------------------------
; NMI — minimal (2p pattern): re-arm HDMA, heartbeat, ack. The heartbeat is a
; DISPLAY/NMI liveness counter ONLY — the loop-rate gate is G_FRAMES.
; WIDTH-RISK: NMI entry width unknown -> php/rep at top, plp at exit.
; -----------------------------------------------------------------------------
NMI:
    php
    rep #$30
    .a16
    .i16
    pha
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    sta $420C                   ; HDMAEN: re-arm all bound channels every VBlank
    rep #$20
    .a16
    lda f:$7E0000 + $E010
    inc a
    sta f:$7E0000 + $E010
    sep #$20
    .a8
    lda $4210                   ; RDNMI ack
    rep #$20
    .a16
    pla
    plp
    rti

NMI_STUB:
    rti

.ifndef HDMA_ORIGIN
; -----------------------------------------------------------------------------
; seam_irq — the trial's core: fire the pre-armed CH0+CH1 GP-DMA pair in the
; blanking gap between band-1's last line and band-2's first.
;
; Contract: template-wide DB=$00 and DP=$0000 (sf_coldstart; never changed).
; Preserves A (16-bit push); X/Y untouched; P restored by rti.
; Critical section = entry .. MDMAEN write (~26 CPU cycles + the HBlank spin);
; everything after the fire is measurement/count tail and may spill into line
; 112 freely (no register writes).
; WIDTH-RISK: IRQ entry width unknown -> rep #$20 before the save; the DMA
; fire runs A8; exits through rep #$20 + 16-bit pla; rti restores caller P.
; -----------------------------------------------------------------------------
seam_irq:
    rep #$20
    .a16
    pha
    sep #$20
    .a8
    lda $2137                   ; latch entry H/V (WRIO bit 7 = power-on default)
.ifndef HV
    ; V-only enters at dot ~47 of the VTIME scanline: there is time to read
    ; the entry latch out BEFORE the spin (the tail re-latch would overwrite
    ; it). The -DHV build enters closer to the HBlank edge — it skips the
    ; entry readout so its fire goes through the same-gate path undelayed.
    lda $213F                   ; reset read toggles
    lda $213C
    sta f:$7E0000 + $E054
    lda $213C
    and #$01
    sta f:$7E0000 + $E055       ; entry H bit 8
    lda $213D
    sta f:$7E0000 + $E056       ; entry V low 8
    lda $213D
    and #$01
    sta f:$7E0000 + $E057       ; entry V bit 8
.endif
@spin:                          ; gate on the HBlank flag (sets at dot 274; the
    .a8                         ; HDMA event at dot 276 pauses the CPU, so the
    bit $4212                   ; fire below always lands after that line's HDMA)
    bvc @spin
    lda #$03
    sta $420B                   ; MDMAEN FIRE: CH0 (M7X/M7Y) + CH1 (HOFS/VOFS), 8 bytes
    lda $2137                   ; re-latch IMMEDIATELY: the fire-completion point
    ; --- non-critical tail ---
    lda $4211                   ; TIMEUP read: ack the V/H-count IRQ
    lda $213F
    lda $213C
    sta f:$7E0000 + $E05A
    lda $213C
    and #$01
    sta f:$7E0000 + $E05B
    lda $213D
    sta f:$7E0000 + $E05C
    lda $213D
    and #$01
    sta f:$7E0000 + $E05D
    rep #$20
    .a16
    lda f:$7E0000 + $E050
    inc a
    sta f:$7E0000 + $E050       ; IRQ fire counter (lockstep with E010 expected)
    pla
    rti
.endif

; =============================================================================
; INIT — one-time setup at RESET: upload the warm/cool world + CGRAM + band-1's
;        Mode-7 registers under forced blank, bind the matrix HDMA pair, then arm
;        either the seam IRQ + GP-DMA pair (default) or, under -DHDMA_ORIGIN, the
;        classic origin HDMA pair.
; =============================================================================
RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    jsr hdma_alloc_init         ; reserves CH0/CH1 (general-DMA use = ours)

    ; --- upload the warm/cool checker world (GP-DMA ch0, forced blank) --------
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after $2119
    rep #$20
    .a16
    stz $2116                   ; VMADD = $0000
    sep #$20
    .a8
    lda #$01
    sta $4300                   ; DMAP0: mode 1 (2 regs $2118/$2119)
    lda #$18
    sta $4301                   ; BBAD0 = VMDATA
    rep #$20
    .a16
    lda #.loword(checker_map)
    sta $4302                   ; A1T0L (DMA0 src addr low/mid): checker_map
    sep #$20
    .a8
    lda #^checker_map
    sta $4304                   ; A1B0 (DMA0 src bank)
    rep #$20
    .a16
    lda #$8000
    sta $4305                   ; DAS0 (DMA0 byte count): 16-bit, fills $4305/$4306
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; fire GP-DMA ch0 (MDMAEN)

    ; --- CGRAM: backdrop + cool pair + warm pair (forced blank) ---------------
    stz $2121                   ; CGADD (CGRAM address): start at colour 0
    lda #<COLOR_BACKDROP
    sta $2122                   ; CGDATA (CGRAM data): write colour byte; index auto-advances
    lda #>COLOR_BACKDROP
    sta $2122
    lda #<COLOR_COOL_DARK
    sta $2122
    lda #>COLOR_COOL_DARK
    sta $2122
    lda #<COLOR_COOL_LIGHT
    sta $2122
    lda #>COLOR_COOL_LIGHT
    sta $2122
    lda #<COLOR_WARM_DARK
    sta $2122
    lda #>COLOR_WARM_DARK
    sta $2122
    lda #<COLOR_WARM_LIGHT
    sta $2122
    lda #>COLOR_WARM_LIGHT
    sta $2122

    ; --- Mode-7 registers under forced blank. Band-1's origin registers get
    ;     their REAL values here (IRQ build: they hold through lines 0..111
    ;     every frame; the VBlank loop re-stamps them after the seam DMA). ----
    lda #$07
    sta $2105                   ; BGMODE = 7
    lda #$01
    sta $212C                   ; TM = BG1 only
    lda #$00
    sta $211A                   ; M7SEL = wrap
    lda #<B1_HOFS
    sta $210D
    lda #>B1_HOFS
    sta $210D                   ; M7HOFS = band-1 (posx - 128)
    lda #<B1_VOFS
    sta $210E
    lda #>B1_VOFS
    sta $210E                   ; M7VOFS = band-1 (posy - 112)
    lda #<P1_X0
    sta $211F
    lda #>P1_X0
    sta $211F                   ; M7X = camera 1 X
    lda #<P1_Y0
    sta $2120
    lda #>P1_Y0
    sta $2120                   ; M7Y = camera 1 Y

    ; --- MATRIX index tables (INDIRECT-mode 3-byte entries, 2p classic shape):
    ;     both bands stream the SAME fixed-angle pose; position distinguishes. -
    lda #($80 | B_LINES)        ; repeat mode: a NEW 4-byte unit per scanline
    sta f:$7E0000 + IDX_AB + 0
    sta f:$7E0000 + IDX_CD + 0
    sta f:$7E0000 + IDX_AB + 3
    sta f:$7E0000 + IDX_CD + 3
    lda #$00
    sta f:$7E0000 + IDX_AB + 6  ; terminator
    sta f:$7E0000 + IDX_CD + 6
    rep #$20
    .a16
    lda #.loword(poses1_ab)
    sta f:$7E0000 + IDX_AB + 1  ; band 1 AB -> fixed-angle pose
    sta f:$7E0000 + IDX_AB + 4  ; band 2 AB -> same pose
    lda #.loword(poses1_cd)
    sta f:$7E0000 + IDX_CD + 1
    sta f:$7E0000 + IDX_CD + 4

    ; --- allocate + bind the MATRIX pair (INDIRECT, DMAP $43, BBAD $1B/$1D) ----
    lda #$0002
    ldx #FX_M7_MATRIX
    jsr hdma_request
    sta f:G_MSK
    bcs @matrix_done
    jsr split_mask
    sep #$20
    .a8
    lda #<IDX_AB
    sta API_BLOCK_BASE + 0
    lda #>IDX_AB
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$43
    sta API_BLOCK_BASE + 3      ; DMAP: INDIRECT + write-2-registers-twice
    rep #$20
    .a16
    lda API_BLOCK_BASE + 10
    ldx #$001B                  ; BBAD = M7A/M7B
    jsr hdma_bind_direct
    sep #$20
    .a8
    lda #<IDX_CD
    sta API_BLOCK_BASE + 0
    lda #>IDX_CD
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$43
    sta API_BLOCK_BASE + 3
    rep #$20
    .a16
    lda API_BLOCK_BASE + 12
    ldx #$001D                  ; BBAD = M7C/M7D
    jsr hdma_bind_direct
    jsr set_indirect_banks      ; DASB (both channels): the poses' bank
@matrix_done:
    .a16

.ifdef HDMA_ORIGIN
    ; =========================================================================
    ; CONTROL: the classic ORIGIN channel pair (proven 2p shape) — counts +
    ; terminators here, value slots stamped by stamp_origins.
    ; =========================================================================
    sep #$20
    .a8
    lda #SEAM                   ; band 1 entry: transfer once, HOLD 112 lines
    sta f:$7E0000 + OTBL_XY + 0
    sta f:$7E0000 + OTBL_HV + 0
    lda #$01                    ; band 2 entry: fires at line 112, HOLDs
    sta f:$7E0000 + OTBL_XY + 5
    sta f:$7E0000 + OTBL_HV + 5
    lda #$00
    sta f:$7E0000 + OTBL_XY + 10
    sta f:$7E0000 + OTBL_HV + 10
    rep #$20
    .a16
    jsr stamp_origins           ; initial values (forced blank; no race)

    lda #$0002
    ldx #FX_M7_ORIGIN
    jsr hdma_request
    sta f:G_MSK2
    bcs @origin_done
    jsr split_mask
    sep #$20
    .a8
    lda #<OTBL_XY
    sta API_BLOCK_BASE + 0
    lda #>OTBL_XY
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3      ; DMAP: direct, write-2-registers-twice
    rep #$20
    .a16
    lda API_BLOCK_BASE + 10
    ldx #$001F                  ; BBAD = M7X/M7Y
    jsr hdma_bind_direct
    sep #$20
    .a8
    lda #<OTBL_HV
    sta API_BLOCK_BASE + 0
    lda #>OTBL_HV
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$03
    sta API_BLOCK_BASE + 3
    rep #$20
    .a16
    lda API_BLOCK_BASE + 12
    ldx #$000D                  ; BBAD = M7HOFS/M7VOFS
    jsr hdma_bind_direct
@origin_done:
    .a16
.else
    ; =========================================================================
    ; IRQ BUILD: stage band-2's 8 origin bytes + pre-arm CH0/CH1 as GP-DMA.
    ; The origin channel pair is NEVER requested — G_MSK2 stays 0 (the FREED-
    ; channels structural signal the python test asserts).
    ; =========================================================================
    jsr stamp_band2_stage       ; the 8 staged bytes (forced blank; no race)
    jsr arm_seam_dma            ; CH0/CH1 DMAP/BBAD/A1B + first A1T/DAS
.endif

    sf_debug_magic              ; "SFDB" at $7E:E000

    ; --- screen on + NMI on (+ V-IRQ on the IRQ builds), all NMITIMEN bits
    ;     composed through the SHADOW_NMITIMEN engine shadow (sf_irq.inc) ------
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP (display control): brightness 15, display on
    rep #$30
    .a16
    .i16
    sf_nmitimen_or $80          ; NMI on (via the shadow — no blind $4200 store)
.ifndef HDMA_ORIGIN
.ifdef HV
    lda #HTIME_VAL
    sta $4207                   ; HTIME lo+hi ($4207/$4208)
    sf_nmitimen_or $10          ; + H trigger (the same-gate probe build)
.endif
    sf_irq_arm_v VTIME_VAL      ; VTIME + V-IRQ enable + CLI (coldstart SEI)
.endif

; =============================================================================
; MAIN LOOP — game_loop: GATED wai (the H1 export). Sleep until the NMI counter
;   actually advanced; a wai return that was only the seam IRQ goes back to sleep.
;   All table/register writes then happen inside the VBlank window. G_WAKES counts
;   RAW wai returns (~2/frame with the IRQ armed) — the measured H1 evidence.
; =============================================================================
game_loop:
    .a16
    .i16
    lda f:$7E0000 + $E010
    sta f:$7E0000 + PREV_NMI
@sleep:
    .a16
    wai
    lda f:$7E0000 + $E058
    inc a
    sta f:$7E0000 + $E058       ; raw wake counter (IRQ wakes land here too)
    lda f:$7E0000 + $E010
    cmp f:$7E0000 + PREV_NMI
    beq @sleep                  ; woke on the seam IRQ -> sleep again
    ; --- VBlank window (NMI just ran) -----------------------------------------
    lda f:G_FRAMES
    inc a
    sta f:G_FRAMES
.ifdef HDMA_ORIGIN
    jsr stamp_origins           ; classic: re-stamp both bands' table slots
.else
    jsr stamp_band1_regs        ; band-1 origin registers direct (VBlank-safe)
    jsr stamp_band2_stage       ; staged band-2 bytes (static here, live later)
    jsr rearm_seam_dma          ; A1T/DAS re-arm (GP-DMA consumed them)
.endif
    jmp game_loop

; =============================================================================
; SUBROUTINES — the origin/stage stampers, the seam-DMA arm/re-arm pair, the
;   allocator-mask helpers, and the HDMA channel allocator (.include at the end).
;   Which stampers are compiled depends on the build (-DHDMA_ORIGIN vs the default
;   IRQ path); each routine's own header documents its width contract.
; =============================================================================

.ifdef HDMA_ORIGIN
; =============================================================================
; stamp_origins — write both bands' origin values into the HDMA tables (the
; proven 2p subroutine, static positions). Caller guarantees VBlank/blank.
; WIDTH-RISK: entry A16/I16; exits A16/I16. Long addressing (no DB dependency).
; Clobbers A.
; =============================================================================
stamp_origins:
    .a16
    .i16
    lda #P1_X0
    sta f:$7E0000 + OTBL_XY + 1     ; M7X (band 1)
    lda #B1_HOFS
    sta f:$7E0000 + OTBL_HV + 1     ; HOFS = posx - 128
    lda #P1_Y0
    sta f:$7E0000 + OTBL_XY + 3     ; M7Y (band 1)
    lda #B1_VOFS
    sta f:$7E0000 + OTBL_HV + 3     ; VOFS = posy - 112
    lda #P2_X0
    sta f:$7E0000 + OTBL_XY + 6     ; M7X (band 2)
    lda #B2_HOFS
    sta f:$7E0000 + OTBL_HV + 6
    lda #P2_Y0
    sta f:$7E0000 + OTBL_XY + 8     ; M7Y (band 2)
    lda #B2_VOFS
    sta f:$7E0000 + OTBL_HV + 8     ; VOFS = posy - 224
    rts

.else
; =============================================================================
; stamp_band1_regs — write band-1's four origin registers directly. VBlank (or
; forced blank) only: these are shared-latch write-twice registers.
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced).
; =============================================================================
stamp_band1_regs:
    .a16
    .i16
    sep #$20
    .a8
    lda #<P1_X0
    sta $211F
    lda #>P1_X0
    sta $211F                   ; M7X
    lda #<P1_Y0
    sta $2120
    lda #>P1_Y0
    sta $2120                   ; M7Y
    lda #<B1_HOFS
    sta $210D
    lda #>B1_HOFS
    sta $210D                   ; M7HOFS
    lda #<B1_VOFS
    sta $210E
    lda #>B1_VOFS
    sta $210E                   ; M7VOFS
    rep #$20
    .a16
    rts

; =============================================================================
; stamp_band2_stage — write band-2's 8 origin bytes into the staged GP-DMA
; source blocks (STAGE_XY -> M7X/M7Y, STAGE_HV -> HOFS/VOFS). Byte order per
; block = the DMA mode-$03 send order: reg lo, reg hi, reg+1 lo, reg+1 hi.
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced).
; =============================================================================
stamp_band2_stage:
    .a16
    .i16
    sep #$20
    .a8
    lda #<P2_X0
    sta f:$7E0000 + STAGE_XY + 0
    lda #>P2_X0
    sta f:$7E0000 + STAGE_XY + 1
    lda #<P2_Y0
    sta f:$7E0000 + STAGE_XY + 2
    lda #>P2_Y0
    sta f:$7E0000 + STAGE_XY + 3
    lda #<B2_HOFS
    sta f:$7E0000 + STAGE_HV + 0
    lda #>B2_HOFS
    sta f:$7E0000 + STAGE_HV + 1
    lda #<B2_VOFS
    sta f:$7E0000 + STAGE_HV + 2
    lda #>B2_VOFS
    sta f:$7E0000 + STAGE_HV + 3
    rep #$20
    .a16
    rts

; =============================================================================
; arm_seam_dma — one-time CH0/CH1 GP-DMA arm (DMAP/BBAD/A1B), then the first
; A1T/DAS load via rearm_seam_dma. Forced blank at call time (boot).
; CH0: $7E:C100 -> $211F (M7X/M7Y). CH1: $7E:C104 -> $210D (HOFS/VOFS).
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced).
; =============================================================================
arm_seam_dma:
    .a16
    .i16
    sep #$20
    .a8
    lda #$03
    sta $4300                   ; DMAP0: A->B, mode 3 (2 regs write twice)
    lda #$1F
    sta $4301                   ; BBAD0 = M7X ($211F/$2120)
    lda #$7E
    sta $4304                   ; A1B0 = WRAM
    lda #$03
    sta $4310                   ; DMAP1: same mode
    lda #$0D
    sta $4311                   ; BBAD1 = M7HOFS ($210D/$210E)
    lda #$7E
    sta $4314                   ; A1B1 = WRAM
    rep #$20
    .a16
    ; fall through: first A1T/DAS arm
; =============================================================================
; rearm_seam_dma — re-stamp CH0/CH1 A1T + DAS (a GP-DMA fire consumes both;
; the DAS-is-single-shot lesson). Called every VBlank after the gated wai.
; WIDTH-RISK: A16/I16 in and out.
; =============================================================================
rearm_seam_dma:
    .a16
    .i16
    lda #STAGE_XY
    sta $4302                   ; A1T0
    lda #$0004
    sta $4305                   ; DAS0
    lda #STAGE_HV
    sta $4312                   ; A1T1
    lda #$0004
    sta $4315                   ; DAS1
    rts
.endif

; =============================================================================
; split_mask — split a 2-channel allocator mask into its two single-bit masks.
; In:  A16 = mask (two bits set among bits 2..7)
; Out: API_BLOCK_BASE+8 = full mask, +10 = lowest bit, +12 = the other bit.
; WIDTH-RISK: A16/I16 throughout. Clobbers A.
; =============================================================================
split_mask:
    .a16
    .i16
    and #$00FF
    sta API_BLOCK_BASE + 8
    eor #$FFFF
    inc a
    and API_BLOCK_BASE + 8          ; A = lowest set bit
    sta API_BLOCK_BASE + 10
    eor API_BLOCK_BASE + 8          ; the remaining bit
    sta API_BLOCK_BASE + 12
    rts

; =============================================================================
; set_indirect_banks — write $43x7 (indirect DATA bank) for both MATRIX
; channels: the pose tables live in the code/RODATA bank ($00) on this 64KB
; image. hdma_bind_direct programs DMAP/BBAD/A1T only. Forced blank at call.
; In: API_BLOCK_BASE+10/+12 = the two single-bit channel masks (split_mask).
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced). Clobbers A, X.
; =============================================================================
set_indirect_banks:
    .a16
    .i16
    ldx #$0000                      ; X = channel reg base ($00,$10,..,$70)
    lda #$0001                      ; A = walking channel bit
@walk:
    .a16
    bit API_BLOCK_BASE + 10
    bne @set
    bit API_BLOCK_BASE + 12
    bne @set
    bra @next
@set:
    .a16
    pha
    sep #$20
    .a8
    lda #^poses1_ab                 ; both channels fetch from the same bank
    sta a:$4307, x                  ; DASBx
    rep #$20
    .a16
    pla
@next:
    .a16
    asl a
    pha
    txa
    clc
    adc #$0010
    tax
    pla
    cmp #$0100                      ; walked CH0..CH7
    bcc @walk
    rts

; --- engine link: the HDMA channel allocator (routes the matrix/origin bindings) ---
.include "hdma_alloc.asm"

; =============================================================================
; DATA — ROM-resident pose tables (the SAME committed fixed-angle pose the 2p
;   rail streams) + the 32KB checker map. Both are read-only cross-template
;   references; their regeneration is covered by split_h_2p_demo's provenance tests.
; =============================================================================
.segment "RODATA"
poses1_ab:    .incbin "templates/split_h_2p_demo/assets/poses1_ab.bin"
poses1_cd:    .incbin "templates/split_h_2p_demo/assets/poses1_cd.bin"

.segment "BANK1"
checker_map:
    .incbin "templates/split_h_2p_demo/assets/checker_map.bin"

; (Header + vectors come from header.inc — the IRQ builds set SF_IRQ_VECTOR
;  before the include; the HDMA_ORIGIN control exercises the stub default.)
