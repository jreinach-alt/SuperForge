; =============================================================================
; split_h_irq_grad_demo — TWO-BAND SPLIT, SEAM-IRQ BAND-2 ORIGIN, GRADIENT
;                         PAYLOAD on a freed HDMA channel
; =============================================================================
; The unlock this rail exists to prove: the 2-player split family spends a
; CHANNEL PAIR on the per-band origin splice; the 256-pose rail therefore has
; ALL SIX allocator channels busy and per-scanline raster payloads are locked
; out. Moving the band-2 origin to a SEAM-SCANLINE IRQ frees both origin
; channels — and this demo spends one of them on a real per-scanline COLDATA
; gradient over the floor. 3 channels used (2 matrix + 1 gradient), 3 free.
;
; ORIGIN MECHANISM (proven by the seam_irq_trial cold-start rail — byte-
; identical to an HDMA-origin control; all timing measured on-emulator):
;   * Boot: band-1's four origin registers written directly under forced
;     blank (they hold through lines 0..111 every frame).
;   * VBlank (game loop after the GATED wai): re-stamp band-1's origin
;     registers directly (VBlank = safe latch window), advance both camera
;     positions, restage band-2's 8 origin bytes into the WRAM DMA-source
;     blocks, re-arm CH0/CH1 A1T/DAS (a general-DMA fire consumes them).
;   * Seam IRQ (V-count, VTIME = SEAM = 112 INTERNAL scanlines — content
;     line L draws during internal scanline L+1): spin on the HBlank flag
;     ($4212 bit 6, sets dot 274; the per-line HDMA event at dot 276 pauses
;     the CPU so the fire never overlaps HDMA), then ONE MDMAEN write fires
;     the two pre-armed general-DMA channels:
;       CH0: DMAP $03, 4 bytes $7E:C100 -> $211F/$2120 (M7X/M7Y)
;       CH1: DMAP $03, 4 bytes $7E:C104 -> $210D/$210E (M7HOFS/M7VOFS)
;     Mode $03 keeps per-register lo/hi byte order — REQUIRED: all Mode-7
;     registers share one write-twice ValueLatch (interleaving corrupts).
;     Measured completion: dot ~11-15 of scanline 113, inside the window.
;   * The game loop gates its wai on the NMI counter (H1: wai ALSO wakes on
;     the seam IRQ — measured ~2 wakes/frame; a bare-wai loop would write
;     tables mid-frame).
;
; GRADIENT PAYLOAD (the point of the exercise):
;   One freed allocator channel drives COLDATA ($2132) with 1 byte/line —
;   the plane-select trick ($E0 | v) sets R=G=B in a single write, so a
;   224-line vertical gray ramp is a 227-byte repeat-mode table. The table
;   is built AT BOOT into WRAM (a ~15-line loop; no committed generated
;   binary, no provenance surface, values v = line >> 3 = 0..27 down the
;   screen). Color math: fixed-color ADD on BG1 (CGWSEL $00 = fixed-color
;   source + no clip/prevent windows; CGADSUB $01 = add, full, BG1 only —
;   bit meanings verified against the emulator core register decode and the
;   in-tree colormath engine, not memory). The world's four colors and the
;   backdrop all have BLUE = 0, so the rendered BLUE channel is EXACTLY the
;   gradient term — the test suite's checker-immune monotonicity signal.
;
; COMPILE-TIME SWITCHES (variant script passes them):
;   -DFREEZE=1        both cameras hold position (stills for comparisons and
;                     the owner render).
;   -DNO_GRAD=1       gradient channel not requested, color math off. The
;                     gradient test's flip control, and the equivalence
;                     comparison side (gradient rows would differ trivially).
;   -DHDMA_ORIGIN=1   the CONTROL: classic origin channel pair instead of
;                     the IRQ (implies no gradient; no IRQ armed, stub
;                     vector). Gold assertion: FREEZE+NO_GRAD IRQ build vs
;                     FREEZE HDMA build render BYTE-IDENTICAL.
;   -DIRQ_INTERLEAVE=1  H4 TEAR CONTROL: the seam handler writes the same 8
;                     bytes by CPU as two 16-bit stores per register pair —
;                     byte order Xlo,Ylo,Xhi,Yhi through the SHARED Mode-7
;                     ValueLatch -> both registers corrupt (the latch
;                     discipline violation made visible). Compared frozen-
;                     vs-frozen per the rotating-baseline lesson.
;
; Default build MOVES both cameras (cam 1 pans +1 px/frame in Y, cam 2 +2 —
; different speeds = the independent-driver signal; X fixed so each band
; stays on its stripe): the seam IRQ feeds LIVE per-frame values, not a
; boot-time constant.
;
; Debug mirrors ($7E:E0xx): E010 NMI count | E020 matrix mask | E022 origin
; mask (0 = freed) | E024 gradient mask | E030 loop iterations | E050 IRQ
; count | E058 raw wai-wake count.
;
; Build:  make split_h_irq_grad_demo
;         bash templates/split_h_irq_grad_demo/build_split_h_irq_grad_variants.sh
; LDCFG: lorom_64k.cfg   (bank 0 = code + pose tables; BANK1 = 32KB map)
; CLEAN-ROOM: mechanism only, no game references.
; =============================================================================

.p816
.smart

.ifdef HDMA_ORIGIN
.ifdef IRQ_INTERLEAVE
    .error "IRQ_INTERLEAVE is an IRQ-path control — do not combine with HDMA_ORIGIN"
.endif
.ifndef NO_GRAD
NO_GRAD = 1                     ; the control has no freed channel to spend
.endif
.endif

.ifndef HDMA_ORIGIN
SF_IRQ_VECTOR = seam_irq        ; engine opt-in IRQ vector (precedes header.inc)
.endif
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_irq.inc"           ; SHADOW_NMITIMEN compose + arm macros
.include "engine_api.inc"       ; API_BLOCK_BASE, ENGINE_A0
.include "engine_state.inc"

; --- band geometry -------------------------------------------------------------
SEAM       = 112                ; band 1 = content lines 0..111, band 2 = 112..223
B_LINES    = 112

; --- camera start positions (world px; the map wraps at 1024) -------------------
P1_X0      = 512                ; camera 1: COOL stripe
P1_Y0      = 512
P2_X0      = 768                ; camera 2: WARM stripe (+256 in X)
P2_Y0      = 512

; --- CGRAM (15-bit BGR): cool pair = green only; warm pair = green + FULL RED.
;     ALL colors keep BLUE = 0 — the rendered blue channel belongs to the
;     gradient alone (the test metric). ------------------------------------------
COLOR_BACKDROP    = $0000       ; black backdrop (B=0 like everything else)
COLOR_COOL_DARK   = $01E0       ; G=15
COLOR_COOL_LIGHT  = $03E0       ; G=31
COLOR_WARM_DARK   = $01FF       ; G=15 + R=31
COLOR_WARM_LIGHT  = $03FF       ; G=31 + R=31

FX_M7_MATRIX = $2B              ; allocator effect tags
FX_M7_ORIGIN = $2C
FX_GRADIENT  = $2E

; --- WRAM layout (engine-free $7E:C000 gap; no new DP state -> zp-check clean) --
IDX_AB     = $C000              ; 7 B  AB index table: [$80|112,ptr][$80|112,ptr][0]
IDX_CD     = $C010              ; 7 B  CD index table
OTBL_XY    = $C020              ; 11 B origin table (HDMA_ORIGIN control only)
OTBL_HV    = $C040              ; 11 B origin table (HDMA_ORIGIN control only)
POS1X      = $C060              ; 4 words: the two camera positions
POS1Y      = $C062
POS2X      = $C064
POS2Y      = $C066
PREV_NMI   = $C110              ; word: gated-wai NMI-counter snapshot
STAGE_XY   = $C100              ; 4 B  staged band-2 M7X/M7Y bytes (CH0 source)
STAGE_HV   = $C104              ; 4 B  staged band-2 HOFS/VOFS bytes (CH1 source)
GRAD_TBL   = $C200              ; 227 B COLDATA HDMA table, built at boot:
                                ;   [$80|112, 112 vals][$80|112, 112 vals][0]

G_MSK      = $7EE020            ; word: matrix channel mask (debug read)
G_MSK2     = $7EE022            ; word: origin channel mask (0 = channels FREED)
G_GRAD     = $7EE024            ; word: gradient channel mask
G_FRAMES   = $7EE030            ; word: MAIN-LOOP iteration counter (cadence)
G_IRQCNT   = $7EE050            ; word: seam-IRQ fire counter
G_WAKES    = $7EE058            ; word: raw wai-wake counter (H1 evidence)

.segment "CODE"

; -----------------------------------------------------------------------------
; NMI — minimal (2p pattern): re-arm HDMA, heartbeat, ack.
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
    sta $420C                   ; re-arm all bound channels every VBlank
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
; seam_irq — fire the pre-armed CH0+CH1 general-DMA pair in the blanking gap
; between content lines 111 and 112 (the trial's proven shape).
; -DIRQ_INTERLEAVE replaces the DMA fire with CPU 16-bit stores whose byte
; order interleaves the write-twice pairs through the shared Mode-7
; ValueLatch — the H4 latch-discipline violation, made visible.
;
; Contract: template-wide DB=$00 and DP=$0000 (sf_coldstart; never changed).
; Preserves A (16-bit push); X/Y untouched; P restored by rti.
; WIDTH-RISK: IRQ entry width unknown -> rep #$20 before the save; A8 for the
; fire; exits through rep #$20 + 16-bit pla; rti restores caller P.
; -----------------------------------------------------------------------------
seam_irq:
    rep #$20
    .a16
    pha
    sep #$20
    .a8
@spin:                          ; gate on the HBlank flag (sets at dot 274; the
    .a8                         ; HDMA event at dot 276 pauses the CPU, so the
    bit $4212                   ; fire below always lands after this line's HDMA)
    bvc @spin
.ifndef IRQ_INTERLEAVE
    lda #$03
    sta $420B                   ; FIRE: CH0 (M7X/M7Y) + CH1 (HOFS/VOFS), 8 bytes
.else
    ; TEAR CONTROL: same 8 bytes, but 16-bit stores interleave each pair's
    ; bytes across the two registers (Xlo->$211F, Ylo->$2120, Xhi->$211F,
    ; Yhi->$2120): every write latches value<<8 | prev through the ONE shared
    ; ValueLatch, so M7X ends up (Xhi<<8)|Ylo and M7Y (Yhi<<8)|Xhi — corrupt.
    rep #$20
    .a16
    lda f:$7E0000 + STAGE_XY + 0
    sta $211F                   ; 16-bit store: lo -> $211F, hi -> $2120
    lda f:$7E0000 + STAGE_XY + 2
    sta $211F
    lda f:$7E0000 + STAGE_HV + 0
    sta $210D                   ; 16-bit store: lo -> $210D, hi -> $210E
    lda f:$7E0000 + STAGE_HV + 2
    sta $210D
    sep #$20
    .a8
.endif
    ; --- non-critical tail ---
    lda $4211                   ; TIMEUP read: ack the V-count IRQ
    rep #$20
    .a16
    lda f:$7E0000 + $E050
    inc a
    sta f:$7E0000 + $E050       ; IRQ fire counter (lockstep with E010)
    pla
    rti
.endif

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    jsr hdma_alloc_init         ; reserves CH0/CH1 (general-DMA use = ours)

    ; --- upload the warm/cool checker world (general-DMA ch0, forced blank) ---
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
    sta $4302
    sep #$20
    .a8
    lda #^checker_map
    sta $4304
    rep #$20
    .a16
    lda #$8000
    sta $4305
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; fire

    ; --- CGRAM: backdrop + cool pair + warm pair (forced blank) ---------------
    stz $2121
    lda #<COLOR_BACKDROP
    sta $2122
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

    ; --- Mode-7 registers under forced blank; band-1 origin gets REAL values --
    lda #$07
    sta $2105                   ; BGMODE = 7
    lda #$01
    sta $212C                   ; TM = BG1 only
    lda #$00
    sta $211A                   ; M7SEL = wrap
    lda #<(P1_X0 - 128)
    sta $210D
    lda #>(P1_X0 - 128)
    sta $210D                   ; M7HOFS = posx - 128
    lda #<(P1_Y0 - SEAM)
    sta $210E
    lda #>(P1_Y0 - SEAM)
    sta $210E                   ; M7VOFS = posy - 112
    lda #<P1_X0
    sta $211F
    lda #>P1_X0
    sta $211F                   ; M7X
    lda #<P1_Y0
    sta $2120
    lda #>P1_Y0
    sta $2120                   ; M7Y

.ifndef NO_GRAD
    ; --- color math: fixed-color ADD on BG1 (bits verified vs the emulator
    ;     core register decode: CGWSEL bit1=0 -> fixed-color source, bits
    ;     7-4=0 -> never clip / never prevent; CGADSUB bit7=0 add, bit6=0
    ;     full, bit0 = BG1). COLDATA itself is HDMA-driven per line. --------
    lda #$00
    sta $2130                   ; CGWSEL
    lda #$01
    sta $2131                   ; CGADSUB: add fixed color to BG1
.endif

    ; --- camera positions ------------------------------------------------------
    rep #$30
    .a16
    .i16
    lda #P1_X0
    sta f:$7E0000 + POS1X
    lda #P1_Y0
    sta f:$7E0000 + POS1Y
    lda #P2_X0
    sta f:$7E0000 + POS2X
    lda #P2_Y0
    sta f:$7E0000 + POS2Y

    ; --- MATRIX index tables (INDIRECT-mode 3-byte entries, 2p classic shape):
    ;     both bands stream the SAME fixed-angle pose; position distinguishes. -
    sep #$20
    .a8
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
    ; CONTROL: the classic ORIGIN channel pair (proven 2p shape).
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
    ; IRQ BUILD: stage band-2's origin bytes + pre-arm CH0/CH1 as general-DMA.
    ; The origin pair is NEVER requested — G_MSK2 stays 0: both channels FREED.
    ; =========================================================================
    jsr stamp_band2_stage       ; the 8 staged bytes (forced blank; no race)
    jsr arm_seam_dma            ; CH0/CH1 DMAP/BBAD/A1B + first A1T/DAS
.endif

.ifndef NO_GRAD
    ; --- GRADIENT: build the 224-line COLDATA table in WRAM, then spend ONE
    ;     freed channel on it (DMAP $00: 1 byte -> $2132 per line). ------------
    jsr build_grad_table
    lda #$0001
    ldx #FX_GRADIENT
    jsr hdma_request
    sta f:G_GRAD
    bcs @grad_done
    sep #$20
    .a8
    lda #<GRAD_TBL
    sta API_BLOCK_BASE + 0
    lda #>GRAD_TBL
    sta API_BLOCK_BASE + 1
    lda #$7E
    sta API_BLOCK_BASE + 2
    lda #$00
    sta API_BLOCK_BASE + 3      ; DMAP: direct, 1 byte -> 1 register
    rep #$20
    .a16
    lda f:G_GRAD                ; the 1-channel mask hdma_request returned
    ldx #$0032                  ; BBAD = COLDATA
    jsr hdma_bind_direct
@grad_done:
    .a16
.endif

    sf_debug_magic              ; "SFDB" at $7E:E000

    ; --- screen on; NMITIMEN bits composed through SHADOW_NMITIMEN ------------
    sep #$20
    .a8
    lda #$0F
    sta $2100
    rep #$30
    .a16
    .i16
    sf_nmitimen_or $80          ; NMI on
.ifndef HDMA_ORIGIN
    sf_irq_arm_v SEAM           ; VTIME = 112 + V-IRQ enable + CLI
.endif

; =============================================================================
; game_loop — GATED wai (the H1 export), then ALL writes inside VBlank.
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
    sta f:$7E0000 + $E058       ; raw wake counter (seam-IRQ wakes land here)
    lda f:$7E0000 + $E010
    cmp f:$7E0000 + PREV_NMI
    beq @sleep                  ; woke on the seam IRQ -> sleep again
    ; --- VBlank window (NMI just ran) -----------------------------------------
    lda f:G_FRAMES
    inc a
    sta f:G_FRAMES
.ifndef FREEZE
    ; independent motion: cam 1 pans +1 px/frame in Y, cam 2 +2 (different
    ; speeds = the independent-driver signal; X fixed -> stripes hold)
    lda f:$7E0000 + POS1Y
    inc a
    and #$03FF                  ; world wraps at 1024
    sta f:$7E0000 + POS1Y
    lda f:$7E0000 + POS2Y
    inc a
    inc a
    and #$03FF
    sta f:$7E0000 + POS2Y
.endif
.ifdef HDMA_ORIGIN
    jsr stamp_origins           ; classic: re-stamp both bands' table slots
.else
    jsr stamp_band1_regs        ; band-1 origin registers direct (VBlank-safe)
    jsr stamp_band2_stage       ; band-2's 8 staged bytes from POS2X/POS2Y
    jsr rearm_seam_dma          ; A1T/DAS re-arm (general-DMA consumed them)
.endif
    jmp game_loop

.ifdef HDMA_ORIGIN
; =============================================================================
; stamp_origins — write both bands' origin values into the HDMA tables (the
; proven 2p subroutine). Caller guarantees the VBlank window (or forced blank).
; WIDTH-RISK: entry A16/I16; exits A16/I16. Long addressing (no DB dependency).
; Clobbers A.
; =============================================================================
stamp_origins:
    .a16
    .i16
    lda f:$7E0000 + POS1X
    sta f:$7E0000 + OTBL_XY + 1     ; M7X (band 1)
    sec
    sbc #128
    sta f:$7E0000 + OTBL_HV + 1     ; HOFS = posx - 128
    lda f:$7E0000 + POS1Y
    sta f:$7E0000 + OTBL_XY + 3     ; M7Y (band 1)
    sec
    sbc #SEAM
    sta f:$7E0000 + OTBL_HV + 3     ; VOFS = posy - 112
    lda f:$7E0000 + POS2X
    sta f:$7E0000 + OTBL_XY + 6
    sec
    sbc #128
    sta f:$7E0000 + OTBL_HV + 6
    lda f:$7E0000 + POS2Y
    sta f:$7E0000 + OTBL_XY + 8
    sec
    sbc #224
    sta f:$7E0000 + OTBL_HV + 8     ; VOFS = posy - 224
    rts

.else
; =============================================================================
; stamp_band1_regs — write band-1's four origin registers directly from
; POS1X/POS1Y. VBlank (or forced blank) only: shared-latch write-twice regs.
; Per register: load the word A16, drop to A8 (B keeps the high byte), write
; lo, XBA, write hi — the per-register lo/hi order the shared latch requires.
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced). Clobbers A.
; =============================================================================
stamp_band1_regs:
    .a16
    .i16
    lda f:$7E0000 + POS1X
    sep #$20
    .a8
    sta $211F
    xba
    sta $211F                   ; M7X
    rep #$20
    .a16
    lda f:$7E0000 + POS1X
    sec
    sbc #128
    sep #$20
    .a8
    sta $210D
    xba
    sta $210D                   ; M7HOFS = posx - 128
    rep #$20
    .a16
    lda f:$7E0000 + POS1Y
    sep #$20
    .a8
    sta $2120
    xba
    sta $2120                   ; M7Y
    rep #$20
    .a16
    lda f:$7E0000 + POS1Y
    sec
    sbc #SEAM
    sep #$20
    .a8
    sta $210E
    xba
    sta $210E                   ; M7VOFS = posy - 112
    rep #$20
    .a16
    rts

; =============================================================================
; stamp_band2_stage — compute band-2's four origin words from POS2X/POS2Y and
; write them into the staged general-DMA source blocks. Word layout matches
; the DMA mode-$03 send order (little-endian word = reg lo then reg hi):
;   STAGE_XY: [M7X word][M7Y word]   STAGE_HV: [HOFS word][VOFS word]
; WIDTH-RISK: A16/I16 in and out. Long addressing. Clobbers A.
; =============================================================================
stamp_band2_stage:
    .a16
    .i16
    lda f:$7E0000 + POS2X
    sta f:$7E0000 + STAGE_XY + 0    ; M7X
    sec
    sbc #128
    sta f:$7E0000 + STAGE_HV + 0    ; HOFS = posx - 128
    lda f:$7E0000 + POS2Y
    sta f:$7E0000 + STAGE_XY + 2    ; M7Y
    sec
    sbc #224
    sta f:$7E0000 + STAGE_HV + 2    ; VOFS = posy - 224 (band-2 bottom line)
    rts

; =============================================================================
; arm_seam_dma — one-time CH0/CH1 general-DMA arm (DMAP/BBAD/A1B), then falls
; into the first A1T/DAS load. Forced blank at call time (boot).
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
; rearm_seam_dma — re-stamp CH0/CH1 A1T + DAS (a general-DMA fire consumes
; both; the DAS-is-single-shot lesson). Called every VBlank after the gated
; wai. WIDTH-RISK: A16/I16 in and out.
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

.ifndef NO_GRAD
; =============================================================================
; build_grad_table — build the COLDATA gradient HDMA table in WRAM at boot:
;   [$80|112, 112 values][$80|112, 112 values][$00]
; value(line) = $E0 | (line >> 3): the plane-select trick writes R=G=B in one
; byte; intensity ramps 0..27 down the 224 content lines. Repeat-mode: one
; NEW byte per scanline. Built once under forced blank; ROM stays free of
; committed generated blobs (no provenance surface).
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced). Clobbers A, X, Y.
; =============================================================================
build_grad_table:
    .a16
    .i16
    sep #$20
    .a8
    lda #($80 | B_LINES)
    sta f:$7E0000 + GRAD_TBL + 0            ; entry 1 header (lines 0..111)
    sta f:$7E0000 + GRAD_TBL + 113          ; entry 2 header (lines 112..223)
    lda #$00
    sta f:$7E0000 + GRAD_TBL + 226          ; terminator
    ldx #$0000                              ; X = content line 0..223
@fill:
    .a8
    txa                                     ; A8: X's low byte (X <= 223 fits)
    lsr a
    lsr a
    lsr a                                   ; line >> 3 = 0..27
    ora #$E0                                ; all three planes, one write
    cpx #B_LINES
    bcs @entry2
    sta f:$7E0000 + GRAD_TBL + 1, x         ; entry 1 payload byte
    bra @next
@entry2:
    .a8
    sta f:$7E0000 + GRAD_TBL + 2, x         ; entry 2 payload (skip its header)
@next:
    .a8
    inx
    cpx #224
    bcc @fill
    rep #$20
    .a16
    rts
.endif

; =============================================================================
; split_mask — split a 2-channel allocator mask into its two single-bit masks.
; In:  A16 = mask. Out: API+8 full, +10 lowest bit, +12 the other bit.
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
; channels: the pose tables live in the code/RODATA bank on this 64KB image.
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

; =============================================================================
.include "hdma_alloc.asm"

; --- ROM-resident pose tables: the SAME committed fixed-angle pose the 2p rail
;     streams (read-only cross-template reference; regeneration is covered by
;     that rail's provenance tests). --------------------------------------------
.segment "RODATA"
poses1_ab:    .incbin "templates/split_h_2p_demo/assets/poses1_ab.bin"
poses1_cd:    .incbin "templates/split_h_2p_demo/assets/poses1_cd.bin"

.segment "BANK1"
checker_map:
    .incbin "templates/split_h_2p_demo/assets/checker_map.bin"
