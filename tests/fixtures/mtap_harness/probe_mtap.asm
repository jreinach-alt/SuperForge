; =============================================================================
; probe_mtap — the four-pad adapter, read by hand, with NO SuperForge code.
; =============================================================================
; The Level-0 ground truth for docs/102's harness: does a port-2 adapter the
; harness configures answer the hardware protocol, and which override index
; reaches which slot? Nothing here is engine code — no allocator, no feature,
; no shared routine — so a failure in the engine's `mtap` cannot be hidden by
; a matching failure here. tests/test_mtap_harness.py assembles it at test
; time and reads the result block at the R_* equates below, which it parses
; out of THIS file (the vendor/probes precedent: a fixture ROM's own equates
; are the primary source for addresses the allocator never placed).
;
; The sequence is fullsnes' (docs/102 §2): detection with the strobe held
; high then low, reading 8 bits of $4017 bit 1 each way; then, every frame,
; the auto-read's $4218-$421F, ONE more clock of each port (the 17th bit of
; port 1 and of port 2's two lines — fullsnes: "17th and up: Padding (always
; 1=Low) (or 0=High when no pad connected)"), and a manual 17-clock read of
; $4017 under WRIO.7 = 0 (bit 0 = slot 3, bit 1 = slot 4; the first 16 into
; the words, the 17th kept apart), WRIO restored to $FF after.
;
; THE AUTO-READ IS WAITED OUT FROM ITS START, not just to its end: the
; frame loop waits for VBlank, then for $4212 bit 0 to SET, then to CLEAR.
; Waiting only for "clear" lets the manual read begin before the auto-read
; has started, and the probe that did that read $007F out of an idle $421A.
.p816
.smart
SYS_STACK_TOP = $01FF                   ; vendor/rom/init.inc's one input
.import SF_LD_ROM_SIZE
.define SF_HDR_TITLE "SF PROBE MTAP"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "init.inc"

; --- the result block (low WRAM via the bank-0 mirror, DB = 0) -------------
R_DETA  = $1000                         ; detection byte A (strobe high)
R_DETB  = $1001                         ; detection byte B (strobe low)
R_JOY   = $1010                         ; $4218..$421F, copied (8 B)
R_MAN0  = $1020                         ; manual word, $4017 bit 0 (slot 3)
R_MAN1  = $1022                         ; manual word, $4017 bit 1 (slot 4)
R_X17   = $1024                         ; 17th bits: $4016 bit 0 (port 1),
                                        ;   $4017 bits 0-1 (port 2's lines)
R_X17B  = $1025                         ; 17th bit of slots 3/4 ($4017 bits
                                        ;   0-1 under WRIO.7 = 0)
R_FRAME = $1030                         ; frames completed
R_SIG   = $1032                         ; $1234 once detection has run

.segment "CODE"
NMI_STUB:
NMI:
    rti

MAIN:
    .a16
    .i16
    stz R_FRAME
    stz R_SIG
    stz R_DETA                          ; both detection bytes: written before
                                        ;   the rol loops read them back
    sep #$20
    .a8
    lda #$FF
    sta $4201                           ; WRIO: every line HighZ (select 1/2)
    ; --- detection (auto-joypad off: init.inc zeroed $4200) ---------------
    lda #$01
    sta $4016                           ; strobe on: the adapter forces bit 1
    ldx #8
@det_a:
    lda $4017
    lsr
    lsr                                 ; C = bit 1
    rol R_DETA
    dex
    bne @det_a
    stz $4016                           ; strobe off
    ldx #8
@det_b:
    lda $4017
    lsr
    lsr
    rol R_DETB
    dex
    bne @det_b
    lda #$01
    sta $4200                           ; NMITIMEN: auto-joypad on, no NMI
    rep #$20
    .a16
    lda #$1234
    sta R_SIG

@frame:
    .a16
    sep #$20
    .a8
@wait_vbl:
    lda $4212
    bpl @wait_vbl                       ; VBlank
@wait_start:
    lda $4212
    lsr
    bcc @wait_start                     ; auto-read has STARTED
@wait_end:
    lda $4212
    lsr
    bcs @wait_end                       ; ...and finished
    rep #$20
    .a16
    lda $4218
    sta R_JOY
    lda $421A
    sta R_JOY + 2
    lda $421C
    sta R_JOY + 4
    lda $421E
    sta R_JOY + 6
    stz R_MAN0
    stz R_MAN1
    sep #$20
    .a8
    lda $4017                           ; port 2's 17th bit, both lines
    and #$03
    asl
    sta R_X17
    lda $4016                           ; port 1's 17th bit
    and #$01
    ora R_X17
    sta R_X17                           ; bit 0 port 1, 1 port 2 pin 4, 2 pin 5
    lda #$7F
    sta $4201                           ; WRIO.7 = 0: select slots 3/4
    ldx #16
@manual:
    lda $4017
    lsr                                 ; C = bit 0 (slot 3)
    rol R_MAN0
    rol R_MAN0 + 1
    lsr                                 ; C = bit 1 (slot 4)
    rol R_MAN1
    rol R_MAN1 + 1
    dex
    bne @manual
    lda $4017                           ; slots 3/4's 17th bit
    and #$03
    sta R_X17B
    lda #$FF
    sta $4201                           ; WRIO.7 = 1: slots 1/2 for next frame
    rep #$20
    .a16
    inc R_FRAME
    sep #$20
    .a8
@wait_active:
    lda $4212
    bmi @wait_active                    ; out of VBlank before looping
    rep #$20
    .a16
    jmp @frame
