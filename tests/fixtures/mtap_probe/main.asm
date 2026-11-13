; =============================================================================
; mtap_probe — the input stack alone, driven at the WORST moment (test_mtap.py)
; =============================================================================
; No NMI, no display: the frame loop polls HVBJOY and calls mtap_read the
; instant VBlank begins — BEFORE the automatic read has started, which is the
; race docs/102 D7 names and mtap_read's guard exists for. input_read and
; input2_read then run after it (mtap_read has already waited the automatic
; read out), and pad_btn / pad_btnp are asked about players 5..0 with every
; button bit set. Players 4 and 5 are out of range on purpose.
;
; Everything is allocator-placed (this dir's game.toml + state.toml);
; tests/test_mtap.py reads the result words by name from the emitted map. The
; test runs no_literals over the FEATURE files this probe composes, not over
; this file: the probe arms NMITIMEN itself with no scene manager composed to
; own it — fixture scaffolding, the status vendor/probes/ has in the reg gate.
.p816
.smart

.define SF_HDR_TITLE "SF PROBE MTAP ENGINE"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "header.inc"
.include "init.inc"
.include "sf_asm.inc"

PROBE_SLOTS = 6                     ; players 0..5 asked; 4 and 5 out of range

.segment "CODE"
NMI_STUB:
NMI:
    rti

.include "input.asm"
.include "input2.asm"
.include "mtap.asm"

MAIN:
    .a16
    .i16
    jsr input_init
    jsr input2_init
    jsr mtap_init                   ; detection: auto-read still off
    ldx #0
@clear:
    .a16
    stz z:US_HELD, x
    stz z:US_PRESS, x
    inx
    inx
    cpx #(PROBE_SLOTS * 2)
    bcc @clear
    stz z:US_ZFLAG
    stz z:US_FRAMES
    sep #$20
    .a8
    lda #$01
    sta a:$4200                     ; NMITIMEN: automatic joypad read only
    rep #$20
    .a16
probe_frame:
    .a16
    sep #$20
    .a8
@active:
    lda a:$4212
    bmi @active                     ; leave the previous VBlank first
@vblank:
    lda a:$4212
    bpl @vblank                     ; VBlank has JUST begun: auto-read not yet
    rep #$20
    .a16
    jsr mtap_read                   ; D7: its guard must wait the race out
    ; input_read / input2_read assume the automatic read has STARTED (their
    ; contracts); with an adapter, mtap_read's guard has just waited it out.
    ; Without one, mtap_read returned at once and nothing has — so the probe
    ; waits it out itself, and both configurations call input_read at the
    ; same point in the read: after it. (Measured: without this wait the
    ; plain-pad run read P1 mid-auto-read and lost a held A.)
    lda z:ES_MTAP_ON
    bne @read_done
    sep #$20
    .a8
@ar_start:
    lda a:$4212
    lsr a
    bcc @ar_start
@ar_end:
    lda a:$4212
    lsr a
    bcs @ar_end
    rep #$20
    .a16
@read_done:
    .a16
    jsr input_read
    jsr input2_read
    stz z:US_ZFLAG
    ldx #(PROBE_SLOTS - 1)
@ask:
    .a16
    lda #$FFFF
    jsr pad_btn                     ; A = held AND mask, Z = none held
    sec
    beq @zset
    clc
@zset:
    .a16
    rol z:US_ZFLAG                  ; asked 5..0, so bit X = player X's Z
    phx
    pha
    txa
    asl a
    tax
    pla
    sta z:US_HELD, x
    plx
    lda #$FFFF
    jsr pad_btnp
    phx
    pha
    txa
    asl a
    tax
    pla
    sta z:US_PRESS, x
    plx
    dex
    bpl @ask
    inc z:US_FRAMES
    jmp probe_frame
