; superforge probe 1 — usable VBlank DMA
; bytes/frame, measured on cycle-accurate hardware.
;
; Method: screen ON (so VRAM writes outside VBlank/forced-blank are DROPPED
; by the PPU — the very constraint being measured). Each command, the NMI
; handler DMAs `param` bytes of an incrementing word pattern from ROM to the
; allocator-emitted VRAM target, then latches H/V at completion. The host
; sweeps `param` ASCENDING and checks whether the transfer's LAST word
; landed: delivery is a prefix (the DMA runs from VBlank start until blocked)
; and the target was wiped to $EEEE once at boot under forced blank, so a
; fresh tail word can only come from the trial that attempted it. The
; largest fully-delivered count is the usable VBlank DMA ceiling through one
; channel, including real NMI-entry + DMA-setup overhead.
;
; All RAM/VRAM addresses are allocator-emitted (engine_state_probe.inc);
; hardware I/O ports are the only literals.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE VBLANK"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "engine_state_probe.inc"

; The measurement channel's register file, addressed through the number the
; probe_dma claim names. The channel is pinned in the declaration because
; this ROM's output is a substrate pin — see feature.toml.
PROBE_REGS = $4300 + ES_H_PROBE_DMA_CH * 16

; DMAP bit 3 holds the A-bus source address FIXED instead of incrementing
; (Mesen2 Core/SNES/SnesDmaController.cpp: FixedTransfer = value & $08). Two
; of the four measurement transfers below need it. It is NOT part of the
; claim: the claim owns the DESTINATION ports, and whether the source pointer
; walks or stays put changes nothing about who drives $2118/$2119. So it is
; OR-ed in locally on top of the declared DMAP rather than declared.
DMAP_FIXED_SRC = $08

.include "header.inc"
.include "init.inc"

.segment "CODE"

NMI_STUB:
    rti

NMI:
    rep #$30
    .a16
    .i16
    pha
    phx
    sep #$20
    .a8
    phb                         ; save caller DB
    lda #$00
    pha
    plb                         ; DB = 0 for I/O

    lda f:US_CMD_LONG
    cmp #1
    beq @measure
    cmp #2
    beq @jmulti
    cmp #3
    beq @jwipe
    cmp #4
    beq @jcpu
    jmp @done
@jmulti:
    jmp @multi
@jwipe:
    jmp @wipe
@jcpu:
    jmp @cpu

@measure:
    .a8
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET
    sta $2116                   ; VMADD = emitted target base
    sep #$20
    .a8
    lda #ES_H_PROBE_DMA_DMAP    ; DMAP: 2-reg write-once ($2118/19), A->B
    sta PROBE_REGS + 0
    lda #ES_H_PROBE_DMA_BBAD    ; BBAD: VMDATAL
    sta PROBE_REGS + 1
    rep #$20
    .a16
    lda #.loword(pattern)
    sta PROBE_REGS + 2                   ; A1T0
    sep #$20
    .a8
    lda #^pattern
    sta PROBE_REGS + 4                   ; A1B0
    rep #$20
    .a16
    lda f:US_PARAM_LONG
    sta PROBE_REGS + 5                   ; DAS0 = byte count
    sep #$20
    .a8
    lda #(1 << ES_H_PROBE_DMA_CH)
    sta $420B                   ; MDMAEN: fire — CPU halts for the transfer

; shared tail: latch H/V at completion, consume the command, bump seq
@latch:
    .a8
    ; (fullsnes: $213F read resets the flip-flops)
    lda $213F                   ; STAT78: reset 213C/D 1st/2nd flip-flops
    lda $2137                   ; SLHV: latch
    lda $213C                   ; OPHCT low
    sta f:US_DONE_H_LONG
    lda $213C                   ; OPHCT high bit
    and #$01
    sta f:US_DONE_H_LONG+1
    lda $213D                   ; OPVCT low
    sta f:US_DONE_V_LONG
    lda $213D                   ; OPVCT high bit
    and #$01
    sta f:US_DONE_V_LONG+1
@ack:
    .a8
    lda #0
    sta f:US_CMD_LONG           ; command consumed
    rep #$20
    .a16
    lda f:US_SEQ_LONG
    inc a
    sta f:US_SEQ_LONG
    sep #$20
    .a8
    jmp @done                   ; (bra can't span the multi/wipe blocks)

; cmd 2 — multi-queue (F9): fire K = param2 transfers of S = param bytes,
; back-to-back, EVERY slot fully re-armed (DMAP/BBAD/A1T/A1B/DAS/VMADD —
; the realistic engine-dispatcher cost; DAS is single-shot and must be
; re-armed per transfer). Slots are contiguous in source and dest, so the
; whole sequence delivers as one prefix and the host checks the final word.
@multi:
    .a8
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET
    sta f:US_MQ_VADDR_LONG      ; slot 0 VMADD
    lda #.loword(pattern)
    sta f:US_MQ_SRC_LONG        ; slot 0 source
    lda f:US_PARAM2_LONG        ; (ldx has no abs-long mode)
    tax                         ; X = K (A16 -> I16)
@mq_slot:
    .a16                        ; entered A16 from fall-in AND loop-back
    sep #$20
    .a8
    lda #ES_H_PROBE_DMA_DMAP
    sta PROBE_REGS + 0                   ; DMAP: A->B, 2-reg write-once
    lda #ES_H_PROBE_DMA_BBAD
    sta PROBE_REGS + 1                   ; BBAD: VMDATAL
    lda #^pattern
    sta PROBE_REGS + 4                   ; A1B0
    rep #$20
    .a16
    lda f:US_MQ_VADDR_LONG
    sta $2116                   ; VMADD for this slot
    lda f:US_PARAM_LONG
    lsr                         ; S/2 = words per slot
    clc
    adc f:US_MQ_VADDR_LONG
    sta f:US_MQ_VADDR_LONG      ; next slot's VMADD
    lda f:US_MQ_SRC_LONG
    sta PROBE_REGS + 2                   ; A1T0
    clc
    adc f:US_PARAM_LONG
    sta f:US_MQ_SRC_LONG        ; next slot's source
    lda f:US_PARAM_LONG
    sta PROBE_REGS + 5                   ; DAS0 — re-armed PER SLOT (single-shot)
    sep #$20
    .a8
    lda #(1 << ES_H_PROBE_DMA_CH)
    sta $420B                   ; fire slot
    rep #$20
    .a16
    dex
    bne @mq_slot
    sep #$20
    .a8
    jmp @latch

; cmd 3 — re-wipe 1 KB of the target to $EEEE at word offset `param`
; (between sweep families, so a stale tail can never fake a delivery;
; 1 KB is far inside the single-transfer VBlank ceiling)
@wipe:
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET
    clc
    adc f:US_PARAM_LONG         ; param = word offset into the target
    sta $2116
    sep #$20
    .a8
    lda #(ES_H_PROBE_DMA_DMAP | DMAP_FIXED_SRC)   ; + FIXED A address
    sta PROBE_REGS + 0
    lda #ES_H_PROBE_DMA_BBAD
    sta PROBE_REGS + 1
    rep #$20
    .a16
    lda #.loword(wipe_word)
    sta PROBE_REGS + 2
    sep #$20
    .a8
    lda #^wipe_word
    sta PROBE_REGS + 4
    rep #$20
    .a16
    lda #1024
    sta PROBE_REGS + 5
    sep #$20
    .a8
    lda #(1 << ES_H_PROBE_DMA_CH)
    sta $420B
    jmp @ack

; cmd 4 — CPU WORD STORES (no DMA at all): commit K = param2 VRAM words with
; a plain load/store loop, the shape text_vblank_commit uses for the txt_q
; run. This is the OTHER side of the txt_q threshold: a commit that claims no
; channel and no claims.dma byte budget, but does spend VBlank *time* that
; nothing currently accounts for. Sweeping K ascending and checking the tail
; (same prefix argument as cmd 1) measures how many words fit before the PPU
; starts dropping writes — i.e. the CPU-store ceiling in words/VBlank, which
; converts to byte-equivalents against cmd 1's DMA ceiling.
;
; Loop shape: `lda f:pattern,x` (long,x = 6 mc-units of CPU time) + 16-bit
; `sta $2118` + inx/inx + dey + bne. A real VWF commit reads its tile buffer
; out of low WRAM with `lda a:buf,x` (absolute,x — one cycle cheaper), so this
; measurement is ~1 cycle/word CONSERVATIVE against the feature it informs.
; The stored value is the word index, so _tail_landed's check is unchanged.
@cpu:
    .a8
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET
    sta $2116                   ; VMADD = emitted target base
    lda f:US_PARAM2_LONG        ; (ldy has no abs-long mode)
    tay                         ; Y = K words to store
    ldx #0                      ; X = byte index into the source pattern
@cpu_word:
    .a16                        ; entered A16 from fall-in AND loop-back
    .i16
    lda f:pattern, x
    sta $2118                   ; 16-bit store = VMDATAL then VMDATAH
    inx
    inx
    dey
    bne @cpu_word
    sep #$20
    .a8
    jmp @latch

@done:
    .a8
    lda $4210                   ; RDNMI: acknowledge
    plb                         ; restore caller DB
    rep #$30
    .a16
    .i16
    plx
    pla
    rti

MAIN:
    .a16
    .i16
    ; ---- init contract: the probe's control block, then wipe the target ----
    sep #$20
    .a8
    lda #0
    sta f:US_CMD_LONG
    sta f:US_SEQ_LONG
    sta f:US_SEQ_LONG+1
    rep #$20
    .a16
    lda #0
    sta f:US_PARAM_LONG
    sta f:US_PARAM2_LONG
    sta f:US_DONE_V_LONG
    sta f:US_DONE_H_LONG

    ; wipe the 8 KB target to $EEEE under forced blank (still asserted from
    ; init.inc) so stale pattern words can never fake a delivery
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET
    sta $2116
    sep #$20
    .a8
    lda #(ES_H_PROBE_DMA_DMAP | DMAP_FIXED_SRC)   ; + FIXED A address
    sta PROBE_REGS + 0
    lda #ES_H_PROBE_DMA_BBAD
    sta PROBE_REGS + 1
    rep #$20
    .a16
    lda #.loword(wipe_word)
    sta PROBE_REGS + 2
    sep #$20
    .a8
    lda #^wipe_word
    sta PROBE_REGS + 4
    rep #$20
    .a16
    lda #ES_V_PROBE_TARGET_WORDS * 2
    sta PROBE_REGS + 5
    sep #$20
    .a8
    lda #(1 << ES_H_PROBE_DMA_CH)
    sta $420B

    ; screen ON (backdrop only, TM=0) — active display now blocks VRAM writes
    lda #$00
    sta $212C                   ; TM: no layers (backdrop)
    lda #$0F
    sta $2100                   ; INIDISP: end forced blank
    lda #$80
    sta $4200                   ; NMITIMEN: NMI on

@spin:
    .a8
    wai
    bra @spin

.segment "RODATA"

pattern:                        ; 4096 incrementing words = 8 KB, one bank
                                ; (no alignment needed — DMA A-bus is byte-addressed)
.repeat 4096, I
    .word I
.endrepeat

wipe_word:
    .word $EEEE
