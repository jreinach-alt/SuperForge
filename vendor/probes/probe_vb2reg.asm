; REVIEW attack ROM — two same-register VBlank claims WIRED, plus channel-0
; time-sharing with a live active-phase HDMA.
;
; Every frame the NMI fires two GP-DMAs, both writing VMDATAL:
;   claim vba (ES_H_VBA_CH): 512 B of pattern A -> ES_V_TARG_A
;   claim vbb (ES_H_VBB_CH): 512 B of pattern B -> ES_V_TARG_B
; then re-arms channel ES_H_VBC_CH's $43xx register file for the COLDATA
; HDMA (pinned to channel 0 = vba's channel — the GP-DMA above clobbers the
; register file every frame, exactly the time-share `_register_exclusive`'s
; relaxation reasons about) and writes HDMAEN. The COLDATA table splits the
; frame into a blue top band and a red bottom band over a color-math-tinted
; backdrop, so the active channel's health is a RENDERED claim, and the two
; VRAM targets are byte-exact rendered-output claims for the VBlank pair.
;
; Host switches (state.toml): skip_b stops claim B's fire (the falsification
; hook — target B's pattern assertion must then fail), rewipe re-wipes both
; targets to $EEEE inside one VBlank before the uploads run.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE VB2REG"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "engine_state_probe.inc"
.include "header.inc"
.include "init.inc"
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

; DMAP bit 3: hold the A-bus address fixed. A source-side bit, so it is
; not part of any register claim's destination footprint (see D6) and is
; OR-ed onto the emitted encoding at the site that wants it.
DMAP_FIXED_SRC = $08

VBA_REGS = $4300 + ES_H_VBA_CH * 16  ; claim vba's DMA register file
VBB_REGS = $4300 + ES_H_VBB_CH * 16  ; claim vbb's DMA register file
VBC_REGS = $4300 + ES_H_VBC_CH * 16  ; COLDATA HDMA channel's register file

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

    ; ---- rewipe? (host-triggered): both targets back to $EEEE -------------
    lda f:US_REWIPE_LONG
    beq @no_wipe
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_TARG_A
    sta $2116
    sep #$20
    .a8
    lda #(ES_H_VBA_DMAP | DMAP_FIXED_SRC)   ; declared mode 1 + FIXED A
    sta VBA_REGS + 0
    lda #ES_H_VBA_BBAD          ; BBAD: VMDATAL (VMDATAH is the mode-1 pair)
    sta VBA_REGS + 1
    rep #$20
    .a16
    lda #.loword(wipe_word)
    sta VBA_REGS + 2
    sep #$20
    .a8
    lda #^wipe_word
    sta VBA_REGS + 4
    stz VBA_REGS + 5            ; DAS low — single-shot, re-armed per fire
    lda #2
    sta VBA_REGS + 6            ; DAS high: 2 * 256 = 512 B
    lda #(1 << ES_H_VBA_CH)
    sta $420B
    rep #$20
    .a16
    lda #ES_V_TARG_B
    sta $2116
    sep #$20
    .a8
    stz VBA_REGS + 5            ; DAS low again (consumed by the first wipe)
    lda #2
    sta VBA_REGS + 6            ; DAS high: 512 B
    lda #(1 << ES_H_VBA_CH)
    sta $420B
    lda #0
    sta f:US_REWIPE_LONG
@no_wipe:
    .a8
    ; ---- claim vba: pattern A -> targ_a (VMDATAL, GP-DMA, every frame) ----
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_TARG_A
    sta $2116                   ; VMADD = target A
    sep #$20
    .a8
    lda #ES_H_VBA_DMAP          ; DMAP: declared mode 1, A->B
    sta VBA_REGS + 0
    lda #ES_H_VBA_BBAD          ; BBAD: VMDATAL (VMDATAH is the mode-1 pair)
    sta VBA_REGS + 1
    rep #$20
    .a16
    lda #.loword(pattern_a)
    sta VBA_REGS + 2
    sep #$20
    .a8
    lda #^pattern_a
    sta VBA_REGS + 4
    stz VBA_REGS + 5            ; DAS low — re-armed (single-shot)
    lda #2
    sta VBA_REGS + 6            ; DAS high: 512 B
    lda #(1 << ES_H_VBA_CH)
    sta $420B                   ; fire A

    ; ---- claim vbb: pattern B -> targ_b (SAME register, own channel) ------
    lda f:US_SKIP_B_LONG
    bne @skip_b
    rep #$20
    .a16
    lda #ES_V_TARG_B
    sta $2116                   ; VMADD = target B
    sep #$20
    .a8
    lda #ES_H_VBB_DMAP          ; DMAP: declared mode 1, A->B
    sta VBB_REGS + 0
    lda #ES_H_VBB_BBAD          ; BBAD: VMDATAL — the shared register
    sta VBB_REGS + 1
    rep #$20
    .a16
    lda #.loword(pattern_b)
    sta VBB_REGS + 2
    sep #$20
    .a8
    lda #^pattern_b
    sta VBB_REGS + 4
    stz VBB_REGS + 5            ; DAS low — re-armed (single-shot)
    lda #2
    sta VBB_REGS + 6            ; DAS high: 512 B
    lda #(1 << ES_H_VBB_CH)
    sta $420B                   ; fire B
@skip_b:
    .a8
    ; ---- re-arm the COLDATA HDMA channel the GP-DMA above clobbered -------
    ; (the scene_mgr discipline, minimally: the small tab-select array below
    ; is the shadow). tab_sel picks the table STRUCTURE so the host can walk
    ; the HDMA init/line alignment matrix on one channel:
    ;   0 direct non-repeat bands · 1 indirect repeat ramp · 2 direct repeat
    ;   ramp · 3 close-repro (counts sum 223) · 4 close-fix (sum 224)
    lda f:US_TAB_SEL_LONG
    and #7
    cmp #5
    bcc :+
    lda #0
:   .a8
    rep #$20
    .a16
    and #15                     ; (A16: clear the stale high byte too)
    asl
    asl
    tax                         ; X = tab_sel * 4 (dmap, dasb, a1t.lo, a1t.hi)
    sep #$20
    .a8
    lda a:tab_cfg + 0, x
    ; vbc's DMAP is picked at RUNTIME from tab_cfg so the host can walk the
    ; HDMA table-structure matrix on one channel. All five structures are
    ; DMAP $02/$40/$00/$02/$02 = modes 2/0/0/2/2, every one span 1, so each
    ; agrees with vbc's declared COLDATA footprint (vb_b/feature.toml says
    ; why `mode` is omitted there).
    ; CHANNEL-LINT: ok — runtime table select; all five DMAPs are span 1
    sta VBC_REGS + 0            ; DMAP for this structure
    lda #ES_H_VBC_BBAD          ; BBAD: COLDATA
    sta VBC_REGS + 1
    lda a:tab_cfg + 1, x
    sta VBC_REGS + 7            ; DASB: indirect data bank (indirect only)
    rep #$20
    .a16
    lda a:tab_cfg + 2, x
    sta VBC_REGS + 2            ; A1T = the selected header table
    sep #$20
    .a8
    lda #^coldata_tab
    sta VBC_REGS + 4            ; A1B (all tables live in the code bank)
    lda #(1 << ES_H_VBC_CH)
    sta $420C                   ; HDMAEN — every frame, scene_mgr-style

    ; ---- seq++ then ack ----------------------------------------------------
    rep #$20
    .a16
    lda f:US_SEQ_LONG
    inc a
    sta f:US_SEQ_LONG
    sep #$20
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
    ; ---- init contract: control block, backdrop colour, target wipes ------
    sep #$20
    .a8
    lda #0
    sta f:US_SKIP_B_LONG
    sta f:US_REWIPE_LONG
    sta f:US_TAB_SEL_LONG       ; NMI reads it every frame — init contract
    rep #$20
    .a16
    lda #0
    sta f:US_SEQ_LONG

    ; CGRAM word 0 (the backdrop this probe displays) = black — power-on
    ; CGRAM is random and the COLDATA tint adds to it
    sep #$20
    .a8
    lda #0
    sta $2121                   ; CGADD = 0
    lda #0
    sta $2122                   ; low
    sta $2122                   ; high

    ; COLDATA all planes to 0 — the register's power-on state is not
    ; guaranteed, and the band table only ever drives R and B
    lda #$E0
    sta $2132

    ; wipe both targets to $EEEE under forced blank (still asserted from
    ; init.inc) so a stale pattern can never fake a delivery
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #ES_V_TARG_A
    sta $2116
    sep #$20
    .a8
    lda #(ES_H_VBA_DMAP | DMAP_FIXED_SRC)   ; declared mode 1 + FIXED A
    sta VBA_REGS + 0
    lda #ES_H_VBA_BBAD
    sta VBA_REGS + 1
    rep #$20
    .a16
    lda #.loword(wipe_word)
    sta VBA_REGS + 2
    sep #$20
    .a8
    lda #^wipe_word
    sta VBA_REGS + 4
    stz VBA_REGS + 5            ; DAS low — single-shot, re-armed per fire
    lda #2
    sta VBA_REGS + 6            ; DAS high: 512 B
    lda #(1 << ES_H_VBA_CH)
    sta $420B
    rep #$20
    .a16
    lda #ES_V_TARG_B
    sta $2116
    sep #$20
    .a8
    stz VBA_REGS + 5            ; DAS low re-armed (consumed by the first wipe)
    lda #2
    sta VBA_REGS + 6            ; DAS high: 512 B
    lda #(1 << ES_H_VBA_CH)
    sta $420B

    ; ---- colour math: add the COLDATA fixed colour to the backdrop --------
    lda #$00
    sta $2130                   ; CGWSEL: fixed colour is the math operand
    lda #$20                    ; CGADSUB: add, backdrop participates
    sta $2131
    lda #$00
    sta $212C                   ; TM: no layers — backdrop only
    lda #$0F
    sta $2100                   ; INIDISP: end forced blank
    lda #$80
    sta $4200                   ; NMITIMEN: NMI on

@spin:
    .a8
    wai
    bra @spin

.segment "RODATA"

; COLDATA band table: blue top half, red bottom half (direct, TWO bytes per
; entry under DMAP mode 2 — each band writes its own plane at 31 AND zeroes
; the other, since a COLDATA write only touches the planes its top bits
; select; counts 112+112 cover the 224-line frame). $9F = B|31, $20 = R|0,
; $3F = R|31, $80 = B|0.
coldata_tab:
    .byte 112, $9F, $20
    .byte 112, $3F, $80
    .byte 0

; --- tab_sel dispatch: 4 B/slot = dmap, dasb, a1t.lo, a1t.hi ----------------
tab_cfg:
    .byte $02, $00
    .word coldata_tab           ; 0: direct non-repeat bands
    .byte $40, ^ramp_bytes
    .word ramp_ind_tab          ; 1: indirect repeat ramp (gradient's shape)
    .byte $00, $00
    .word ramp_dir_tab          ; 2: direct repeat ramp
    .byte $02, $00
    .word close223_tab          ; 3: close repro, pre-final counts sum 223
    .byte $02, $00
    .word close224_tab          ; 4: close fix, pre-final counts sum 224

; The ramp: byte k = B-plane | (k & 31). Read back from rendered rows, the
; blue intensity names WHICH table byte a scanline displays — the byte<->
; scanline map, measured, for each table structure.
ramp_bytes:
.repeat 224, I
    .byte $80 | (I & 31)
.endrepeat

; indirect repeat, gen_gradient's exact shape: 128|127 + 128|97 = 224 lines
ramp_ind_tab:
    .byte 128 | 127
    .word ramp_bytes
    .byte 128 | 97
    .word ramp_bytes + 127
    .byte 0

; direct repeat, same ramp inline: count byte then n data bytes
ramp_dir_tab:
    .byte 128 | 127
.repeat 127, I
    .byte $80 | (I & 31)
.endrepeat
    .byte 128 | 97
.repeat 97, I
    .byte $80 | ((127 + I) & 31)
.endrepeat
    .byte 0

; split_band close-experiment repro (mode-2 pairs, blue = "sky", red =
; "floor"): [44][1][127][51][1] — counts before the final 1-line entry sum
; to 223, the shape the authors measured landing on line 223
close223_tab:
    .byte 44,  $9F, $20         ; "sky" lines
    .byte 1,   $3F, $80         ; "floor" from the seam
    .byte 127, $3F, $80
    .byte 51,  $3F, $80
    .byte 1,   $9F, $20         ; the wrap re-latch under test
    .byte 0

; the same close with the pre-final counts summing to 224 ([44][1][127][52])
close224_tab:
    .byte 44,  $9F, $20
    .byte 1,   $3F, $80
    .byte 127, $3F, $80
    .byte 52,  $3F, $80
    .byte 1,   $9F, $20
    .byte 0

pattern_a:                      ; 256 words, distinct high byte $A5
.repeat 256, I
    .word $A500 + I
.endrepeat

pattern_b:                      ; 256 words, distinct high byte $B7
.repeat 256, I
    .word $B700 + I
.endrepeat

wipe_word:
    .word $EEEE
