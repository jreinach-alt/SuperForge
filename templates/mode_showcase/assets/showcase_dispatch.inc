; =============================================================================
; showcase_dispatch.inc — the ALL-MODES DISPATCH LAYER (S1.5).
; =============================================================================
; The framework that turns the harness from "hardwired to Mode 1" into "one ROM,
; eight live modes." `SHOW_CUR_MODE` ($7E:E23D) selects the mode; every per-mode
; contract symbol (4 procs + 4 data symbols) is resolved THROUGH a per-mode
; vtable instead of a fixed page label. The shell + every generic module compose
; the ACTIVE mode's tables; the per-mode fan-out (S2..Sn) just registers a row.
;
; THE REGISTRATION CONTRACT (the only thing a page touches in this layer):
;   show_register_mode N, init, apply, field, arena, ptbl, snames, pnames, costknob
;     N         mode index 0..7
;     init      .proc — once on demo entry (forced blank): engine_gfxmode N +
;               author BG/CHR/palette/tilemaps + field init + arm preset 0.
;     apply     .proc — every frame: push knobs to engine SHADOWS (NMI commits).
;     field     .proc — every frame: the sprite field at OAM base 48+.
;     arena     .proc — every frame: the $C000-arena owner indicator (OBJ 39).
;     ptbl      label — SHOW_PARAM_TBL: 30 x 4 bytes (min,max,step,default).
;     snames    label — 6 .addr slot-label string ptrs.
;     pnames    label — 30 .addr param-tag string ptrs.
;     costknob  byte  — the meter's cost/OAM proxy knob index (F1).
; A page invokes this ONCE with UNIQUE symbol names (prefix by mode, e.g.
; m1_demo_init / m1_param_tbl). It NEVER edits the tables below, the Makefile, or
; main.asm — that is what keeps the per-mode fan-out conflict-free.
;
; HOW THE TABLES ARE BUILT (no hand-editing): show_register_mode stashes each
; argument as a uniquely-named alias `_sh_<field>_<N>` (via .ident/.sprintf).
; show_dispatch_emit_tables (called once from main.asm AFTER all 8 pages have
; registered) walks N=0..7 and emits the dispatch tables from those aliases.
; A mode left unregistered => a ca65 ASSEMBLE-time "Symbol '_sh_*_<N>' is undefined"
; error (one per missing alias) names the gap.
;
; DATA-POINTER INDIRECTION: all page tables/strings live in ROM bank $00 (CODE/
; RODATA). On demo entry, show_resolve_active_tables COPIES the selected mode's
; param table + name-pointer tables into a fixed WRAM staging window so every
; generic module keeps its `f:<fixed base>,x` long-indexed access pattern (only
; the base symbol changed). The copy is once-per-demo-entry, never per-frame.
; =============================================================================

; --- ACTIVE-mode resolved tables (WRAM staging, $7E:E380-$E440; verified-free
;     tail per allocations §1 "extend into $7E:E300-$EFFF and record the claim").
;     The generic modules read these FIXED bases (long-indexed, bank $7E). ----
SHOW_A_PARAM_TBL  = $7EE380       ; 120 B: active 30 x 4 param descriptors
SHOW_A_SLOT_NAME  = $7EE3F8       ; 12 B : active 6 x .addr slot-label ptrs
SHOW_A_PARM_NAME  = $7EE404       ; 60 B : active 30 x .addr param-tag ptrs
SHOW_A_COST_KNOB  = $7EE440       ; 1 B  : active meter cost/OAM proxy knob index
; All page string/table DATA links into ROM bank $00 (CODE/RODATA), so the
; copied .addr pointers' BANK byte is a constant — the generic name printers use
; this instead of `#^SHOW_SLOT_NAME` (which named the Mode-1 page symbol).
SHOW_PAGE_BANK    = $00

SHOW_N_MODES      = 8

; -----------------------------------------------------------------------------
; show_register_mode — a page calls this ONCE to register its row (deliverable
; 1). Stashes each contract symbol as a per-mode alias the table emitter reads.
; Assemble-time only (no code emitted at the call site).
; -----------------------------------------------------------------------------
.macro show_register_mode N, init, apply, field, arena, ptbl, snames, pnames, costknob
    .ident(.sprintf("_sh_init_%d",  N)) = init
    .ident(.sprintf("_sh_apply_%d", N)) = apply
    .ident(.sprintf("_sh_field_%d", N)) = field
    .ident(.sprintf("_sh_arena_%d", N)) = arena
    .ident(.sprintf("_sh_ptbl_%d",  N)) = ptbl
    .ident(.sprintf("_sh_snm_%d",   N)) = snames
    .ident(.sprintf("_sh_pnm_%d",   N)) = pnames
    .ident(.sprintf("_sh_cost_%d",  N)) = costknob
.endmacro

; -----------------------------------------------------------------------------
; show_dispatch_emit_tables — emit the 8-entry vtables from the registered
; aliases. Called ONCE from main.asm after every page's show_register_mode. The
; proc tables are .addr (jsr (tbl,x), x = mode*2); the data tables are .addr ptrs
; resolved into the WRAM staging window; SHOW_COST_KNOB_TBL is one byte per mode.
; -----------------------------------------------------------------------------
.macro show_dispatch_emit_tables
SHOW_DEMO_INIT:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_init_%d", I))
    .endrepeat
SHOW_APPLY:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_apply_%d", I))
    .endrepeat
SHOW_FIELD_TICK:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_field_%d", I))
    .endrepeat
SHOW_ARENA_IND:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_arena_%d", I))
    .endrepeat
SHOW_PARAM_TBL_PTR:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_ptbl_%d", I))
    .endrepeat
SHOW_SLOT_NAME_PTR:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_snm_%d", I))
    .endrepeat
SHOW_PARM_NAME_PTR:
    .repeat SHOW_N_MODES, I
        .addr .ident(.sprintf("_sh_pnm_%d", I))
    .endrepeat
SHOW_COST_KNOB_TBL:
    .repeat SHOW_N_MODES, I
        .byte .ident(.sprintf("_sh_cost_%d", I))
    .endrepeat

; --- F-1 BANK-0 GUARD (the fan-out footgun) ------------------------------------
; jsr (TBL,x) fetches a 2-byte .addr and jumps WITHIN the program bank (bank 0,
; where these vtables link); the resolver likewise reads the data tables with the
; bank HARDCODED to SHOW_PAGE_BANK ($00). A dispatched proc OR data table placed
; in a data bank (BANK1..BANK7 — which the cfg invites for bulky assets) has its
; .addr truncated to 16 bits and is SILENTLY mis-dispatched/mis-read into bank 0
; — no assemble/link error. Catch it at link time: assert every registered
; symbol's bank byte equals the dispatch table's (SHOW_DEMO_INIT links in CODE =>
; bank 0). A page that puts a proc/table in BANKn now FAILS THE BUILD by name.
    .repeat SHOW_N_MODES, I
        .assert .bankbyte(.ident(.sprintf("_sh_init_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d init proc must link in bank 0 (jsr (TBL,x) is bank-local)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_apply_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d apply proc must link in bank 0 (jsr (TBL,x) is bank-local)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_field_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d field proc must link in bank 0 (jsr (TBL,x) is bank-local)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_arena_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d arena proc must link in bank 0 (jsr (TBL,x) is bank-local)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_ptbl_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d ptbl data must link in bank 0 (resolver hardcodes bank $00)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_snm_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d snames data must link in bank 0 (resolver hardcodes bank $00)", I)
        .assert .bankbyte(.ident(.sprintf("_sh_pnm_%d", I))) = .bankbyte(SHOW_DEMO_INIT), error, .sprintf("showcase: mode %d pnames data must link in bank 0 (resolver hardcodes bank $00)", I)
    .endrepeat
.endmacro

; -----------------------------------------------------------------------------
; _show_cur_mode_x2 — X = SHOW_CUR_MODE * 2 (the .addr table index), I16, A
; clobbered. Helper for the four indexed-indirect dispatch calls.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte read; exits A16/I16, X = mode*2.
.proc _show_cur_mode_x2
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07                          ; clamp 0..7 (defensive; menu sets 0..7)
    rep #$20
    .a16
    and #$00FF
    asl                               ; mode * 2 (.addr = 2 bytes/entry)
    tax
    rts
.endproc

; -----------------------------------------------------------------------------
; The four generic dispatch entry points the shell calls. Each resolves the
; ACTIVE mode's proc via SHOW_CUR_MODE and tail-calls it through the vtable.
; jsr (tbl,x) fetches the pointer from the PROGRAM bank (bank 0, where the table
; links) — independent of DBR, so it is correct regardless of the caller's DB.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; the dispatched proc runs (and restores) its own
; width contract (A16/I16 in/out per the page-author contract); exits A16/I16.
.proc show_demo_init
    rep #$30
    .a16
    .i16
    ; Resolve the active mode's data tables into the WRAM staging window FIRST so
    ; the page's init (and the first frame's HUD) read the right SHOW_A_* tables.
    jsr show_resolve_active_tables
    jsr _show_cur_mode_x2             ; X = mode*2
    jsr (SHOW_DEMO_INIT, x)           ; -> the selected mode's init
    rts
.endproc

; WIDTH-RISK: A16/I16 entry/exit; dispatched proc honors the A16/I16 contract.
.proc show_apply
    rep #$30
    .a16
    .i16
    jsr _show_cur_mode_x2
    jsr (SHOW_APPLY, x)
    rts
.endproc

; WIDTH-RISK: A16/I16 entry/exit; dispatched proc honors the A16/I16 contract.
.proc show_field_tick
    rep #$30
    .a16
    .i16
    jsr _show_cur_mode_x2
    jsr (SHOW_FIELD_TICK, x)
    rts
.endproc

; WIDTH-RISK: A16/I16 entry/exit; dispatched proc honors the A16/I16 contract.
.proc show_arena_indicator
    rep #$30
    .a16
    .i16
    jsr _show_cur_mode_x2
    jsr (SHOW_ARENA_IND, x)
    rts
.endproc

; --- 16-bit (bank $7E) offsets of the staging tables, for abs,y stores under a
;     DB=$7E bracket. The 65816 has NO `sta long,y` form (long-indexed is X-only),
;     so the copy reads via [dp],y (indirect long, bank from the ptr) and stores
;     via `sta abs,y` with DBR=$7E. ----------------------------------------------
SHOW_A_PARAM_TBL_LO = (SHOW_A_PARAM_TBL & $FFFF)
SHOW_A_SLOT_NAME_LO = (SHOW_A_SLOT_NAME & $FFFF)
SHOW_A_PARM_NAME_LO = (SHOW_A_PARM_NAME & $FFFF)

; -----------------------------------------------------------------------------
; show_resolve_active_tables — copy the SELECTED mode's param table + name-ptr
; tables + cost-knob index from ROM (bank $00) into the WRAM staging window
; (SHOW_A_*). Runs once on demo entry. After this, every generic module reads
; the fixed SHOW_A_* bases (long-indexed) — fully generic over SHOW_CUR_MODE.
;
; Source addresses come from the SHOW_*_PTR vtables (each .addr is the page
; table's 16-bit offset in bank $00). The copy uses a DP scratch pointer ($00-$02)
; for indirect-long reads from ROM and DBR=$7E for the abs,y staging stores. DP
; $00-$02 is free transiently here: we run under forced blank in the main thread
; with no intervening call between the pointer set and its use.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for byte copies; DB=$7E bracket; exits A16/I16,
; DB restored. Uses DP $00-$02 as a transient indirect-read pointer.
.proc show_resolve_active_tables
    rep #$30
    .a16
    .i16
    phb                               ; save caller DB

    ; --- param table: 120 bytes (30 x 4) from SHOW_PARAM_TBL_PTR[mode] -> WRAM ---
    jsr _show_cur_mode_x2             ; X = mode*2 (index into the .addr vtables)
    lda f:SHOW_PARAM_TBL_PTR, x       ; 16-bit ROM offset of the page param table
    sta $00                           ; DP ptr lo16
    sep #$20
    .a8
    lda #SHOW_PAGE_BANK               ; bank $00
    sta $02                           ; DP ptr bank (for [dp],y long read)
    lda #$7E
    pha
    plb                               ; DBR = $7E (staging window bank)
    rep #$20
    .a16
    ldy #0
@cp_ptbl:
    sep #$20
    .a8
    lda [$00], y                      ; ROM byte (bank $00 page table)
    sta SHOW_A_PARAM_TBL_LO, y        ; WRAM staging (abs,y, DBR=$7E)
    rep #$20
    .a16
    iny
    cpy #(SHOW_N_SLOTS * SHOW_N_PARAMS * 4)   ; 120 bytes
    bcc @cp_ptbl

    ; --- slot-name pointer table: 12 bytes (6 x .addr) ---
    jsr _show_cur_mode_x2             ; X = mode*2 (rebuild after the copy)
    lda f:SHOW_SLOT_NAME_PTR, x
    sta $00                           ; (DP ptr bank $02 still $00 from above)
    ldy #0
@cp_snm:
    sep #$20
    .a8
    lda [$00], y
    sta SHOW_A_SLOT_NAME_LO, y
    rep #$20
    .a16
    iny
    cpy #(SHOW_N_SLOTS * 2)           ; 12 bytes
    bcc @cp_snm

    ; --- param-name pointer table: 60 bytes (30 x .addr) ---
    jsr _show_cur_mode_x2
    lda f:SHOW_PARM_NAME_PTR, x
    sta $00
    ldy #0
@cp_pnm:
    sep #$20
    .a8
    lda [$00], y
    sta SHOW_A_PARM_NAME_LO, y
    rep #$20
    .a16
    iny
    cpy #(SHOW_N_SLOTS * SHOW_N_PARAMS * 2)    ; 60 bytes
    bcc @cp_pnm

    plb                               ; restore caller DB

    ; --- cost-knob index: 1 byte from SHOW_COST_KNOB_TBL[mode] ---
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    rep #$20
    .a16
    and #$00FF
    tax                               ; X = mode (byte table => *1)
    sep #$20
    .a8
    lda f:SHOW_COST_KNOB_TBL, x
    sta f:SHOW_A_COST_KNOB
    rep #$20
    .a16
    rts
.endproc
