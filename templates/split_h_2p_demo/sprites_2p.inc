; =============================================================================
; sprites_2p.inc — SPRITE STRESS RAIL for the 2-player rotating floor
; =============================================================================
; World-space sprites (players + AI followers) projected PER BAND PER FRAME
; onto the two independent Mode-7 cameras. Inverse of the floor map:
;
;   floor (scanline k, band-local): texel = P + S(k)/256 * R(th) * (sx-128, k-112)
;   sprite:  (u,v) = R(-th) * (W - P)
;            k     = sp_vk[-v]                  (build-time inverse LUT)
;            tier  = sp_tier[k]                 (size ladder + seam-margin cull)
;            sx    = 128 + u * recip(k) >> 8    (recip(k) = 65536/S8.8(k))
;            sy    = band_top + k
;
; THE MEASURED-FIRST CORE (this sprint's cold-start extension — the trial's
; naive 4x-smul16 core cost 8,522 mc/sprite/visible-band and, critically,
; 6,965 mc for CULLED sprites because both dots ran before the v-cull):
;   1. CULL ORDER: wrap-sub dx -> |dx|>176 out; dy likewise (Chebyshev
;      pre-cull, no multiplies) -> v dot -> v/d/k/tier culls -> ONLY THEN
;      the u dot. Culled sprites cost cycles, not multiplies.
;   2. 8-BIT HARDWARE MULTIPLY core: after the pre-cull |dx|,|dy| <= 176 and
;      the sincos LUT is magnitude-clamped to 255, so every rotation product
;      is 8x8 via $4202/$4203 (8-cycle product, overlapped with sign-mask
;      staging). Sign/magnitude split: per-term
;          t  = (|a| * |c| + 128) >> 8          (rounded, 0..176)
;          t' = (t ^ m) - m,  m = sign(a) ^ sign(c)  ($0000/$FFFF masks)
;      Each term magnitude <= 176 so the two-term dot fits s16 with no s32
;      accumulator (the smul16 path needed one).
;   3. OAM SLOT COMPACTION: visible sprites take consecutive shadow slots;
;      culled sprites cost NO park store. The tail is parked only up to the
;      previous frame's watermark. 544-B shadow -> one GP-DMA in VBlank.
;
; Shared snapshot (trial-proven, kept): ONE VBlank commits OAM + pose
; pointers/banks + origins from the SAME H/POS values; state then advances
; and the next frame's projection runs during active display (WRAM-only).
;
; -D switches (build_split_h_2p_variants.sh):
;   SPRITES=N      enable the sprite rail, default sprite count N (1..128).
;                  Requires ROTATE + POSES=256. Live count is WRAM-poked at
;                  SP_N ($7E:C0C0) — the stress sweep pokes it per run.
;   SP_INPUT=1     joypad-driven cameras (auto-joypad reads $4218/$421A;
;                  D-pad Left/Right = heading -/+1 per frame held, B =
;                  forward 2 px/f). Without it cameras auto-rotate/drive
;                  exactly like the plain ROTATE build.
;   SP_STATIC=1    no AI, no player->entity sync (instrument/still worlds).
;   SP_PIN=1 + SP_H1/SP_H2   pin both headings (with FREEZE: a true still).
;   SP_CYCLES=1    free-running ticks/frames instrument (persp_cycles
;                  pattern): tick u32 $7E:E030 = project both bands + OAM
;                  commit; frames u32 $7E:E034 (NMI); HDMA dark, screen
;                  blanked. SP_CYCAI=1 adds the AI tick to the instrument.
;   SP_VISWORLD/SP_FARWORLD/SP_TIERWORLD  select the instrument worlds.
;   SP_MIR=1       debug screen-position mirrors at $7E:E400 (diagnostics
;                  for the pin stills; NEVER the test oracle).
;   SP_FORWARD=1   NON-VACUITY CONTROL: forward floor matrix (sin negated).
;   SP_CULLOFF=1   NON-VACUITY CONTROL: no seam-margin culls in the tier LUT.
;   SP_TIEROFF=1   NON-VACUITY CONTROL: constant tier 2 (no size ladder).
;
; WIDTH DISCIPLINE: every multi-path label annotated; A8 windows are only the
; $4202/$4203/$2xxx stores and hi-table RMW, each sep/rep balanced.
; DP SCRATCH REUSE ($B0-$CF): the engine math-wrapper block ($B0-$BD,
; ES_ATAN2_*) and the hires-box/M7-PV block ($C0-$CF) are QUIESCENT in this
; rail — it never calls atan2/sqrt, never arms the PV renderer or hires box
; (same reuse the audited trial documented). No new persistent DP state.
; WRAM: engine-free demo gap $7E:C0C0-$C7FF (below the allocator's $C800+).
; CLEAN-ROOM: mechanism only.
; =============================================================================

.ifndef ROTATE
    .error "SPRITES requires the rotating rail — build with ROTATE=1 POSES=256"
.endif
.if POSES <> 256
    .error "SPRITES requires POSES=256 (the rotate default)"
.endif
.if SPRITES < 1 || SPRITES > 128
    .error "SPRITES must be 1..128"
.endif

; --- DP scratch (quiescent engine blocks — see header) ------------------------
sp_adx   = $B0                  ; |dx| word (0..176 after pre-cull)
sp_ady   = $B2                  ; |dy| word
sp_mdx   = $B4                  ; dx sign mask ($0000/$FFFF)
sp_mdy   = $B6                  ; dy sign mask
sp_tmpm  = $B8                  ; per-term sign-mask / half-size scratch
sp_vacc  = $BA                  ; dot accumulator; later TRUE sx
sp_u     = $BC                  ; camera-frame u (s16)
sp_top   = $BE                  ; band top row (0/112)
sp_cmag  = $C0                  ; |cos| byte (<= 255 — LUT is clamped)
sp_smag  = $C1                  ; |sin| byte
sp_mc    = $C2                  ; cos sign mask word
sp_ms    = $C4                  ; sin sign mask word
sp_px    = $C6                  ; current band camera X
sp_py    = $C8                  ; current band camera Y
sp_ent   = $CA                  ; entity byte offset (index * 8)
sp_cnt   = $CC                  ; sprites remaining in band loop
sp_aux   = $CE                  ; |u| / 9-bit OAM x / misc

; --- WRAM state (demo-owned gap; SP_N is the sweep's poke target) -------------
SP_N       = $C0C0              ; word: live sprite count (poked 1..128)
SP_SLOT    = $C0C2              ; word: OAM-shadow byte cursor (0..512)
SP_WATER   = $C0C4              ; word: previous frame's slot watermark
SP_MIRW    = $C0C8              ; word: mirror byte base for band (SP_MIR)
SP_OVER    = $C0CA              ; word: visible sprites beyond the 128 slots
SP_HOLD    = $C0CC              ; word: poked nonzero -> freeze input/AI
SP_JOY1    = $C0D0              ; word: this frame's P1 pad ($4218)
SP_JOY2    = $C0D2              ; word: P2 pad ($421A)
SP_SY_MIR  = $C0D6              ; word: mirror-only sy staging (SP_MIR builds)
; (visible count = SP_SLOT/4 + SP_OVER; band top lives in DP sp_top)
; --- SP_ALTFRAME (alternate-frame reprojection probe) ---
SP_CAP     = $C0DA              ; word: this half's slot cap (region end)
SP_HALF    = $C0DC              ; word: active half (0/1), toggles per frame
SP_WATER2  = $C0DE              ; word: half-B region watermark
SP_ENT0    = $C0E0              ; word: active half's first entity byte offset
SP_HCNT    = $C0E2              ; word: active half's entity count

SP_SHADOW   = $C100             ; 544 B OAM shadow ($C100-$C31F)
SP_SHAD_HI  = SP_SHADOW + 512
SP_ENTS     = $C320             ; 128 x 8 B entities ($C320-$C71F):
                                ;   +0 x u16, +2 y u16, +4 heading byte,
                                ;   +5 waypoint byte, +6/+7 frac accumulators
SP_MIRBASE  = $E400             ; SP_MIR: (sx,sy) words per sprite per band
                                ;   $E400 + band*512 + i*4  ($E400-$E7FF)

; =============================================================================
; sp_init — one-time setup under FORCED BLANK: OBJ CHR upload, OBSEL, OBJ
; palettes, TM, parked OAM shadow, entity copy-in, first projection + commit
; (frame 1 shows a consistent snapshot).
; WIDTH-RISK: entry/exit .a16/.i16; sep/rep pairs balanced inside.
; =============================================================================
sp_init:
    .a16
    .i16
    ; --- disc CHR -> VRAM word $4000 (OBJ name base; Mode 7 owns $0000-$3FFF)
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word after $2119
    rep #$20
    .a16
    lda #$4000
    sta $2116                   ; VMADD = word $4000
    sep #$20
    .a8
    lda #$01
    sta $4300                   ; DMAP0: mode 1 ($2118/$2119)
    lda #$18
    sta $4301
    rep #$20
    .a16
    lda #.loword(sp_chr)
    sta $4302
    sep #$20
    .a8
    lda #^sp_chr
    sta $4304
    rep #$20
    .a16
    lda #2048                   ; 64 names (5 disc variants, 4x4 blocks padded)
    sta $4305
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; fire GP-DMA ch0
    ; --- OBSEL: size pair 16x16/32x32 (%011), OBJ name base word $4000 ---
    lda #$62
    sta $2101
    ; --- OBJ palette 0 colour 1 = white (AI), palette 1 colour 1 = magenta
    ;     (player markers) — both disjoint from the floor's green/red space --
    lda #$81
    sta $2121
    lda #$FF
    sta $2122
    lda #$7F
    sta $2122                   ; CGRAM $81 = $7FFF
    lda #$91
    sta $2121
    lda #$1F
    sta $2122
    lda #$7C
    sta $2122                   ; CGRAM $91 = $7C1F
    ; --- TM: BG1 + OBJ ---
    lda #$11
    sta $212C
    rep #$30
    .a16
    .i16
    ; --- shadow: all 128 entries parked (Y=$F0, kit cull convention), hi
    ;     table $00 (X8=0, size=16x16 — parked entries must stay SMALL or a
    ;     32x32 at Y=$F0 wraps into the visible top rows) ---
    ldx #$0000
@park:
    .a16
    .i16
    lda #$F000                  ; Y=$F0 << 8 | X=0
    sta f:$7E0000 + SP_SHADOW, x
    lda #$3004                  ; attr $30 (prio 3, pal 0) | tile 4
    sta f:$7E0000 + SP_SHADOW + 2, x
    inx
    inx
    inx
    inx
    cpx #512
    bcc @park
    ldx #$0000
    lda #$0000
@hi:
    .a16
    .i16
    sta f:$7E0000 + SP_SHAD_HI, x
    inx
    inx
    cpx #32
    bcc @hi
    ; --- entities: copy the world table in; heading/frac zero; follower i
    ;     (i >= 2) starts at waypoint ((i-2)>>3)&3 of loop (i-2)&7 ---
    ldx #$0000                  ; X = entity byte offset (i*8)
@ent:
    .a16
    .i16
    phx
    txa
    lsr a
    tax                         ; X = world byte offset (i*4; long idx is X-only)
    lda f:sp_world, x
    sta z:sp_adx                ; stage through free DP scratch
    lda f:sp_world + 2, x
    sta z:sp_ady
    plx                         ; X = entity byte offset again
    lda z:sp_adx
    sta f:$7E0000 + SP_ENTS + 0, x
    lda z:sp_ady
    sta f:$7E0000 + SP_ENTS + 2, x
    ; +4 heading byte = 0, +5 waypoint byte = ((i-2)>>3)&3 (i = x>>3)
    txa
    lsr a
    lsr a
    lsr a                       ; A = entity index i
    sec
    sbc #2
    bmi @wp0                    ; players: wp slot unused
    lsr a
    lsr a
    lsr a
    and #$0003
    bra @wpst
@wp0:
    .a16
    lda #$0000
@wpst:
    .a16
    xba
    and #$FF00                  ; wp -> the +5 byte of the +4 word
    sta f:$7E0000 + SP_ENTS + 4, x
    lda #$0000
    sta f:$7E0000 + SP_ENTS + 6, x
    txa
    clc
    adc #8
    tax
    cpx #(128 * 8)
    bcc @ent
    ; --- state ---
    lda #SPRITES
    sta f:$7E0000 + SP_N
    lda #$0000
    sta f:$7E0000 + SP_WATER
    sta f:$7E0000 + SP_OVER
    sta f:$7E0000 + SP_HOLD
    ; --- first snapshot (forced blank -> no race) ---
    jsr sp_project_all
    jsr sp_oam_commit
    rts

; =============================================================================
; sp_oam_commit — OAMADD=0 + 544-byte GP-DMA (ch0) of the WRAM shadow to $2104.
; Caller guarantees VBlank window or forced blank.
; WIDTH-RISK: entry/exit .a16/.i16; sep/rep pairs balanced.
; =============================================================================
sp_oam_commit:
    .a16
    .i16
    sep #$20
    .a8
    stz $2102                   ; OAMADD = 0 (reload point for the DMA)
    stz $2103
    lda #$00
    sta $4300                   ; DMAP0: mode 0, single register
    lda #$04
    sta $4301                   ; BBAD = $2104 (OAM data port)
    rep #$20
    .a16
    lda #SP_SHADOW
    sta $4302
    sep #$20
    .a8
    lda #$7E
    sta $4304
    rep #$20
    .a16
    lda #544
    sta $4305
    sep #$20
    .a8
    lda #$01
    sta $420B                   ; fire
    rep #$20
    .a16
    rts

; =============================================================================
; sp_band_coeffs — A = heading (0..255) -> the band's split-sign coefficients:
; sp_cmag/sp_smag (magnitudes, <= 255 by LUT clamp) + sp_mc/sp_ms (sign masks).
; INVERSE rotation is the default; -DSP_FORWARD negates sin = the FORWARD
; floor matrix (the wrong-math non-vacuity control).
; WIDTH-RISK: entry/exit .a16/.i16; sep/rep balanced (A8 magnitude stores).
; Clobbers A, X.
; =============================================================================
sp_band_coeffs:
    .a16
    .i16
    and #$00FF
    asl a
    asl a                       ; heading * 4 (cos word + sin word)
    tax
    lda f:sp_sincos, x          ; cos (s16, |cos| <= 255)
    bpl @cpos
    eor #$FFFF
    inc a
    tay                         ; Y = |cos|
    lda #$FFFF
    bra @cst
@cpos:
    .a16
    tay
    lda #$0000
@cst:
    .a16
    sta z:sp_mc
    tya
    sep #$20
    .a8
    sta z:sp_cmag
    rep #$20
    .a16
    lda f:sp_sincos + 2, x      ; sin (s16)
.ifdef SP_FORWARD
    eor #$FFFF                  ; CONTROL: forward matrix = sin negated
    inc a
.endif
    bpl @spos
    eor #$FFFF
    inc a
    tay
    lda #$FFFF
    bra @sst
@spos:
    .a16
    tay
    lda #$0000
@sst:
    .a16
    sta z:sp_ms
    tya
    sep #$20
    .a8
    sta z:sp_smag
    rep #$20
    .a16
    rts

; =============================================================================
; sp_project_all — project SP_N entities against BOTH cameras into the OAM
; shadow with SLOT COMPACTION (visible sprites take consecutive slots; the
; tail is parked up to last frame's watermark). WRAM/DP/ROM/$4202 only — safe
; during active display. Entry/exit .a16/.i16.
; =============================================================================
sp_project_all:
    .a16
    .i16
    ; --- hi-table re-arm: all $00 (X8=0, size=16x16); the store path ORs the
    ;     X8/size bits back per visible sprite. NEVER carried across frames. --
    ldx #$0000
    lda #$0000
@hia:
    .a16
    .i16
    sta f:$7E0000 + SP_SHAD_HI, x
    inx
    inx
    cpx #32
    bcc @hia
    sta f:$7E0000 + SP_SLOT     ; compaction cursor restarts at 0
    sta f:$7E0000 + SP_OVER     ; per-pass overflow count (diagnostic)
    ; ---- band 1: P1/H1, top row 0 ----
    lda f:$7E0000 + POS1X
    sta z:sp_px
    lda f:$7E0000 + POS1Y
    sta z:sp_py
    lda #$0000
    sta z:sp_top
.ifdef SP_MIR
    sta f:$7E0000 + SP_MIRW
.endif
    lda f:$7E0000 + H1
    jsr sp_band_coeffs
    jsr sp_project_band
    ; ---- band 2: P2/H2, top row 112 ----
    lda f:$7E0000 + POS2X
    sta z:sp_px
    lda f:$7E0000 + POS2Y
    sta z:sp_py
    lda #112
    sta z:sp_top
.ifdef SP_MIR
    lda #512
    sta f:$7E0000 + SP_MIRW
.endif
    lda f:$7E0000 + H2
    jsr sp_band_coeffs
    jsr sp_project_band
    ; ---- tail park: slots [SP_SLOT, SP_WATER) were visible last frame ----
    lda f:$7E0000 + SP_WATER
    sta z:sp_tmpm               ; cpx has no long mode — stage the bound in DP
    lda f:$7E0000 + SP_SLOT
    tax
@parkt:
    .a16
    .i16
    cpx z:sp_tmpm
    bcs @parked
    lda #$F000                  ; Y=$F0 (park), X=0
    sta f:$7E0000 + SP_SHADOW, x
    inx
    inx
    inx
    inx
    bra @parkt
@parked:
    .a16
    .i16
    lda f:$7E0000 + SP_SLOT
    sta f:$7E0000 + SP_WATER
    rts

; =============================================================================
; sp_project_band — the per-sprite loop for one band (coeffs + sp_px/sp_py +
; SP_BANDTOP staged by sp_project_all). Cull order: Chebyshev -> v dot ->
; v/d/k/tier -> u dot -> x range. Culled sprites store NOTHING (compaction).
; WIDTH-RISK: A8 windows are the $4202/$4203 stores and the hi-table RMW,
; each sep/rep balanced; every multi-path label annotated. Clobbers A, X, Y
; and the DP scratch block.
; =============================================================================
; sp_project_band — the per-sprite loop for one band (coeffs + sp_px/sp_py +
; sp_top staged by sp_project_all). Cull order: Chebyshev (no multiplies) ->
; v dot -> v/d/k + tier-margin culls -> u dot -> x range. Culled sprites
; store NOTHING (slot compaction). Wrap+abs uses the raw (W-P)&1023 residue:
; [0,176] = positive, [848,1023] = negative (|dx| = 1024-raw), else cull —
; bit-identical to the mirror's ((W-P+512)&1023)-512 form.
; WIDTH-RISK: A8 windows are only the $4202/$4203 stores and the hi-table
; RMW, each sep/rep balanced; every multi-path label annotated.
; Clobbers A, X, Y + the DP scratch block.
; =============================================================================
sp_project_band:
    .a16
    .i16
.ifndef SP_ALTFRAME
    lda #$0000
    sta z:sp_ent
    lda f:$7E0000 + SP_N
    sta z:sp_cnt
.else
    lda f:$7E0000 + SP_ENT0     ; alt: the active half's entity window
    sta z:sp_ent
    lda f:$7E0000 + SP_HCNT
    sta z:sp_cnt
    bne @go
    rts                         ; empty half (degenerate poke)
@go:
    .a16
    .i16
.endif
@loop:
    .a16
    .i16
.ifdef SP_MIR
    ; default mirror = $7FFF sentinel (culled); the store path overwrites it
    lda z:sp_ent
    lsr a                       ; i*8 -> i*4
    clc
    adc f:$7E0000 + SP_MIRW
    tax
    lda #$7FFF
    sta f:$7E0000 + SP_MIRBASE, x
    sta f:$7E0000 + SP_MIRBASE + 2, x
.endif
    ldx z:sp_ent
    ; --- dx: raw = (wx - px) & 1023; [0,176] pos / [848,1023] neg / else cull
    lda f:$7E0000 + SP_ENTS + 0, x
    sec
    sbc z:sp_px
    and #$03FF
    ldy #$0000                  ; sign mask
    cmp #177
    bcc @xok
    cmp #848
    bcs @xneg
    jmp @next                   ; Chebyshev cull (X axis)
@xneg:
    .a16
    eor #$FFFF
    clc
    adc #1025                   ; |dx| = 1024 - raw
    dey                         ; sign mask = $FFFF
@xok:
    .a16
    sta z:sp_adx
    sty z:sp_mdx
    ; --- dy likewise ---
    lda f:$7E0000 + SP_ENTS + 2, x
    sec
    sbc z:sp_py
    and #$03FF
    ldy #$0000
    cmp #177
    bcc @yok
    cmp #848
    bcs @yneg
    jmp @next                   ; Chebyshev cull (Y axis)
@yneg:
    .a16
    eor #$FFFF
    clc
    adc #1025
    dey
@yok:
    .a16
    sta z:sp_ady
    sty z:sp_mdy
    ; --- v = dx*sin + dy*cos: 8x8 HW multiplies, per-term (mag+128)>>8 with
    ;     sign masks; both terms <= 176 so the sum fits s16. ------------------
    sep #$20
    .a8
    lda z:sp_adx
    sta $4202                   ; WRMPYA = |dx|
    lda z:sp_smag
    sta $4203                   ; WRMPYB = |sin| -> product cooking (8 cycles)
    rep #$20
    .a16
    lda z:sp_mdx
    eor z:sp_ms
    sta z:sp_tmpm               ; term-1 sign mask (>= 8 cycles of cover work)
    lda $4216                   ; |dx| * |sin|
    clc
    adc #$0080
    xba
    and #$00FF                  ; rounded >> 8
    eor z:sp_tmpm
    sec
    sbc z:sp_tmpm               ; t' = (t ^ m) - m
    sta z:sp_vacc
    sep #$20
    .a8
    lda z:sp_ady
    sta $4202
    lda z:sp_cmag
    sta $4203
    rep #$20
    .a16
    lda z:sp_mdy
    eor z:sp_mc
    sta z:sp_tmpm
    lda $4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:sp_tmpm
    sec
    sbc z:sp_tmpm
    clc
    adc z:sp_vacc               ; A = v
    ; --- the camera sees v < 0 only ---
    beq @cullj1
    bpl @cullj1                 ; v >= 0: at/behind the pivot row
    eor #$FFFF
    inc a                       ; d = -v
    cmp #$0100
    bcs @cullj1                 ; beyond the 256-px inverse-LUT window
    tax
    lda f:sp_vk, x
    and #$00FF
    cmp #$00FF
    beq @cullj1                 ; horizon / behind-pivot band
    tax                         ; X = band-local row k (0..111) — kept
                                ; through the u dot and the recip lookup
    ; --- tier-margin cull check BEFORE the u dot ($FF = cull; the tier
    ;     VALUE is re-read after the recip while X still holds k) ---
.ifndef SP_TIEROFF
    lda f:sp_tier_tbl, x
    and #$00FF
    cmp #$00FF
    beq @cullj1
.endif
    bra @udot
@cullj1:
    .a16
    .i16
    jmp @next
@udot:
    .a16
    .i16
    ; --- u = dx*cos - dy*sin (only survivors pay for it) ---
    sep #$20
    .a8
    lda z:sp_adx
    sta $4202
    lda z:sp_cmag
    sta $4203
    rep #$20
    .a16
    lda z:sp_mdx
    eor z:sp_mc
    sta z:sp_tmpm
    lda $4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:sp_tmpm
    sec
    sbc z:sp_tmpm
    sta z:sp_vacc
    sep #$20
    .a8
    lda z:sp_ady
    sta $4202
    lda z:sp_smag
    sta $4203
    rep #$20
    .a16
    lda z:sp_mdy
    eor z:sp_ms
    eor #$FFFF                  ; the u dot SUBTRACTS the sin term
    sta z:sp_tmpm
    lda $4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:sp_tmpm
    sec
    sbc z:sp_tmpm
    clc
    adc z:sp_vacc               ; A = u
    sta z:sp_u
    ; abs(u) without touching X (X = k): cmp #$8000 carries the sign
    cmp #$8000
    bcc @aupos
    eor #$FFFF
    inc a
@aupos:
    .a16
    cmp #$0100
    bcs @cullj2                 ; |u| >= 256: off-screen at any row
    sta z:sp_aux                ; |u|
    ; --- sxoff = (|u| * recip(k)) >> 8: recip is 9 bits (171..410); lo byte
    ;     via ONE HW multiply, the 256s bit adds |u| (carry survives rep) ---
    sep #$20
    .a8
    sta $4202                   ; WRMPYA = |u|
    lda f:sp_recip_lo, x        ; X = k
    sta $4203
    lda f:sp_recip_hi, x        ; cover work for the 8-cycle product
    lsr a                       ; carry = recip bit 8
    rep #$20
    .a16
    lda $4216                   ; |u| * recip_lo
    xba
    and #$00FF                  ; >> 8
    bcc @nohi
    clc
    adc z:sp_aux                ; + |u| (the 9th recip bit)
@nohi:
    .a16
    cmp #160                    ; 32x32 fully off-screen past +-160
    bcc @havex
@cullj2:
    .a16
    .i16
    jmp @next
@havex:
    .a16
    .i16
    ; --- sx = 128 +- sxoff; Y (free since the vk lookup) carries u's sign ---
    ldy z:sp_u                  ; N flag = u's sign
    bpl @upos
    eor #$FFFF
    inc a
@upos:
    .a16
    clc
    adc #128
    sta z:sp_vacc               ; TRUE sx (s16; survives to the mirror store)
    ; --- sy + tier geometry (X = k until here; mdx/mdy free after the dots) --
    txa
    clc
    adc z:sp_top
    sta z:sp_mdx                ; sy = band top + k
.ifdef SP_MIR
    sta f:$7E0000 + SP_SY_MIR   ; sy for the mirror (mdx is reused below)
.endif
.ifdef SP_TIEROFF
    ldx #$0002                  ; CONTROL: constant mid tier (no ladder)
.else
    lda f:sp_tier_tbl, x
    and #$00FF
    tax                         ; X = tier (0..4)
.endif
    lda f:sp_tier_half, x
    and #$00FF
    sta z:sp_ady                ; half box size (8/16)
    lda f:sp_tier_tile, x
    and #$00FF
    sta z:sp_mdy                ; CHR name
    ; --- word0 = (y byte << 8) | x low ---
    lda z:sp_vacc
    sec
    sbc z:sp_ady
    and #$01FF
    sta z:sp_aux                ; 9-bit OAM x (bit 8 -> hi table)
    lda z:sp_mdx
    sec
    sbc z:sp_ady
    and #$00FF                  ; OAM y byte
    xba
    and #$FF00
    sta z:sp_mdx                ; y << 8 (sy consumed)
    lda z:sp_aux
    and #$00FF
    ora z:sp_mdx                ; word0
    ; --- claim the next shadow slot (cap = 128 entries / the half region) ---
    pha
    lda f:$7E0000 + SP_SLOT
.ifndef SP_ALTFRAME
    cmp #512
.else
    cmp f:$7E0000 + SP_CAP
.endif
    bcc @room
    pla                         ; OAM full: count the drop, no store
    lda f:$7E0000 + SP_OVER
    inc a
    sta f:$7E0000 + SP_OVER
    jmp @next
@room:
    .a16
    .i16
    tax                         ; X = slot byte offset (ldx has no long mode)
    pla
    sta f:$7E0000 + SP_SHADOW, x
    ; --- word1 = attr<<8 | tile: attr $30 (AI white) / $32 (player magenta) --
.ifndef SP_STATIC
    lda z:sp_ent
    cmp #16                     ; entities 0/1 = the player markers
    bcs @ai
    lda z:sp_mdy
    ora #$3200                  ; prio 3, palette 1 (magenta)
    bra @attr
@ai:
    .a16
.endif
    lda z:sp_mdy
    ora #$3000                  ; prio 3, palette 0 (white)
@attr:
    .a16
    sta f:$7E0000 + SP_SHADOW + 2, x
    ; --- advance the cursor while X still holds the slot ---
    txa
    clc
    adc #4
    sta f:$7E0000 + SP_SLOT
    ; --- hi table: X8 bit (aux bit 8) | 32x32 size bit ((half>>3)&2) ---
    lda z:sp_aux
    xba                         ; 9-bit x: bit 8 -> bit 0
    and #$0001
    sta z:sp_tmpm
    lda z:sp_ady                ; half: 16 -> bit 1 set after >>3, 8 -> 0
    lsr a
    lsr a
    lsr a
    and #$0002
    ora z:sp_tmpm
    beq @hidone                 ; nothing to OR for this slot
    sta z:sp_tmpm               ; bits (1..3)
    txa                         ; A = slot byte offset
    lsr a
    lsr a                       ; OAM entry index (0..127)
    sta z:sp_mdy                ; (tile consumed)
    and #$0003
    asl a
    asl a                       ; pair position * 4
    ora z:sp_tmpm
    tax
    lda f:sp_hi_pos, x          ; positioned bits = bits << (pair*2)
    and #$00FF
    sta z:sp_tmpm
    lda z:sp_mdy
    lsr a
    lsr a                       ; hi-table byte index (0..15)
    tax
    sep #$20
    .a8
    lda z:sp_tmpm
    ora f:$7E0000 + SP_SHAD_HI, x
    sta f:$7E0000 + SP_SHAD_HI, x
    rep #$20
    .a16
@hidone:
    .a16
    .i16
.ifdef SP_MIR
    ; --- debug mirror: TRUE sx, sy (pin-still forensics only, NEVER the
    ;     test oracle — tests read the framebuffer) ---
    lda z:sp_ent
    lsr a                       ; i*8 -> i*4
    clc
    adc f:$7E0000 + SP_MIRW
    tax
    lda z:sp_vacc
    sta f:$7E0000 + SP_MIRBASE, x
    lda f:$7E0000 + SP_SY_MIR
    sta f:$7E0000 + SP_MIRBASE + 2, x
.endif
@next:
    .a16
    .i16
    lda z:sp_ent
    clc
    adc #8
    sta z:sp_ent
    dec z:sp_cnt
    beq @done
    jmp @loop
@done:
    .a16
    .i16
    rts

.ifdef SP_ALTFRAME
; =============================================================================
; sp_alt_toggle / sp_project_all_alt — ALTERNATE-FRAME REPROJECTION (probe;
; owner feel-test question, NOT the default): the entity set splits into two
; INDEX HALVES, each owning a fixed 64-entry OAM shadow REGION (region =
; half*256 bytes; hi-table bytes half*16..+15 — disjoint by construction).
; Each frame ONE half re-projects (compacting within its region, tail parked
; to that half's own watermark) while the other region HOLDS its 1-frame-old
; sprites: display stays 60 Hz, each sprite re-projects at 30 Hz. Players keep
; 60 Hz camera input; their MARKERS ride the half rate like everything else.
; WIDTH-RISK: .a16/.i16 throughout both routines (sep/rep balanced in the
; hi re-arm store loop). Clobbers A, X + DP scratch.
; =============================================================================
sp_alt_toggle:
    .a16
    .i16
    lda f:$7E0000 + SP_HALF
    eor #$0001
    sta f:$7E0000 + SP_HALF
    ; HCNT = SP_N/2 (even N contract); ENT0 = half * HCNT * 8
    lda f:$7E0000 + SP_N
    lsr a
    sta f:$7E0000 + SP_HCNT
    lda f:$7E0000 + SP_HALF
    beq @hA
    lda f:$7E0000 + SP_HCNT
    asl a
    asl a
    asl a                       ; * 8 bytes per entity
    sta f:$7E0000 + SP_ENT0
    rts
@hA:
    .a16
    lda #$0000
    sta f:$7E0000 + SP_ENT0
    rts

sp_project_all_alt:
    .a16
    .i16
    ; --- hi-table re-arm: ONLY the active half's 16 bytes ---
    lda f:$7E0000 + SP_HALF
    asl a
    asl a
    asl a
    asl a                       ; half*16
    tax
    lda #$0000
    ldy #$0008                  ; 8 word stores = 16 bytes
@hia:
    .a16
    .i16
    sta f:$7E0000 + SP_SHAD_HI, x
    inx
    inx
    dey
    bne @hia
    ; --- region cursor + cap ---
    lda f:$7E0000 + SP_HALF
    xba                         ; half * 256
    and #$FF00
    sta f:$7E0000 + SP_SLOT
    sta f:$7E0000 + SP_OVER     ; (reuse as scratch is unsafe — keep count 0)
    lda #$0000
    sta f:$7E0000 + SP_OVER
    lda f:$7E0000 + SP_SLOT
    clc
    adc #256
    sta f:$7E0000 + SP_CAP
    ; ---- band 1 ----
    lda f:$7E0000 + POS1X
    sta z:sp_px
    lda f:$7E0000 + POS1Y
    sta z:sp_py
    lda #$0000
    sta z:sp_top
    lda f:$7E0000 + H1
    jsr sp_band_coeffs
    jsr sp_project_band
    ; ---- band 2 ----
    lda f:$7E0000 + POS2X
    sta z:sp_px
    lda f:$7E0000 + POS2Y
    sta z:sp_py
    lda #112
    sta z:sp_top
    lda f:$7E0000 + H2
    jsr sp_band_coeffs
    jsr sp_project_band
    ; ---- tail park within the region, against the HALF's watermark ----
    lda f:$7E0000 + SP_HALF
    beq @wA
    lda f:$7E0000 + SP_WATER2
    bra @wgot
@wA:
    .a16
    lda f:$7E0000 + SP_WATER
@wgot:
    .a16
    sta z:sp_tmpm
    lda f:$7E0000 + SP_SLOT
    tax
@parkt:
    .a16
    .i16
    cpx z:sp_tmpm
    bcs @parked
    lda #$F000
    sta f:$7E0000 + SP_SHADOW, x
    inx
    inx
    inx
    inx
    bra @parkt
@parked:
    .a16
    .i16
    lda f:$7E0000 + SP_HALF
    beq @sA
    lda f:$7E0000 + SP_SLOT
    sta f:$7E0000 + SP_WATER2
    rts
@sA:
    .a16
    lda f:$7E0000 + SP_SLOT
    sta f:$7E0000 + SP_WATER
    rts
.endif

; =============================================================================
; sp_pose_ptrs — pose pointers for BOTH bands from the CURRENT H1/H2 (verbatim
; copy of the shipping loop's pointer math; the sprite loop commits floor(S)
; and sprites(S) in the same VBlank before advancing S).
; ptr(h) = slice_base + (h & 63)*448; banks via stamp_pose_banks.
; WIDTH-RISK: .a16/.i16 throughout. Clobbers A.
; =============================================================================
sp_pose_ptrs:
    .a16
    .i16
    lda f:$7E0000 + H1
    and #$003F
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; m<<6
    sta f:$7E0000 + PTRTMP
    asl a
    asl a
    asl a                       ; m<<9
    sec
    sbc f:$7E0000 + PTRTMP      ; m*448
    sta f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_ab_base)
    sta f:$7E0000 + IDX_AB + 1  ; band 1 AB
    lda f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_cd_base)
    sta f:$7E0000 + IDX_CD + 1  ; band 1 CD
    lda f:$7E0000 + H2
    and #$003F
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta f:$7E0000 + PTRTMP
    asl a
    asl a
    asl a
    sec
    sbc f:$7E0000 + PTRTMP
    sta f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_ab_base)
    sta f:$7E0000 + B2_AB_PTR   ; band 2 AB
    lda f:$7E0000 + PTRTMP
    clc
    adc #.loword(pose_cd_base)
    sta f:$7E0000 + B2_CD_PTR   ; band 2 CD
    rts

; =============================================================================
; sp_move_auto — both cameras drive FORWARD along their headings (verbatim
; copy of the shipping POSES=256 movement: move_lut 8.8 + per-axis fraction
; accumulators, constant 2.0 px/frame). Used when SP_INPUT is absent.
; WIDTH-RISK: .a16/.i16 throughout. Clobbers A, X.
; =============================================================================
sp_move_auto:
    .a16
    .i16
    lda f:$7E0000 + H1
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F1X
    sta f:$7E0000 + F1X
    xba                         ; A low byte = signed integer delta
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00                  ; sign-extend
:
    clc
    adc f:$7E0000 + POS1X
    and #$03FF
    sta f:$7E0000 + POS1X
    lda f:$7E0000 + F1X
    and #$00FF
    sta f:$7E0000 + F1X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F1Y
    sta f:$7E0000 + F1Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS1Y
    and #$03FF
    sta f:$7E0000 + POS1Y
    lda f:$7E0000 + F1Y
    and #$00FF
    sta f:$7E0000 + F1Y
    lda f:$7E0000 + H2
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F2X
    sta f:$7E0000 + F2X
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2X
    and #$03FF
    sta f:$7E0000 + POS2X
    lda f:$7E0000 + F2X
    and #$00FF
    sta f:$7E0000 + F2X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F2Y
    sta f:$7E0000 + F2Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2Y
    and #$03FF
    sta f:$7E0000 + POS2Y
    lda f:$7E0000 + F2Y
    and #$00FF
    sta f:$7E0000 + F2Y
    rts

; =============================================================================
; sp_read_pads — latch both joypads from the auto-read registers. $4200 has
; the auto-joypad bit set in SP_INPUT builds (the composed $81 store); the
; $4212 bit-0 poll guards the auto-read window (it usually completes before
; the VBlank commits finish — the poll is the safety, verified on emulator).
; WIDTH-RISK: entry/exit .a16/.i16; sep/rep balanced around the A8 poll.
; =============================================================================
sp_read_pads:
    .a16
    .i16
    sep #$20
    .a8
@wait:
    .a8
    lda $4212
    lsr a                       ; bit 0 = auto-read in progress
    bcs @wait
    rep #$20
    .a16
    lda $4218                   ; P1: AXLR....  |  BYSelSt UDLR (high byte)
    sta f:$7E0000 + SP_JOY1
    lda $421A                   ; P2 likewise
    sta f:$7E0000 + SP_JOY2
    rts

; =============================================================================
; sp_players — joypad-driven cameras, matching the 256-pose step-per-frame
; model: D-pad Right/Left = heading +1/-1 per frame HELD (one pose step per
; frame — the rotation-smoothness DoD rate), B = forward 2.0 px/f via the
; move256 8.8 fractional accumulators (identical math to the auto drive).
; Player 1 -> camera 1 (port $4218), player 2 -> camera 2 (port $421A).
; WIDTH-RISK: .a16/.i16 throughout. Clobbers A, X.
; =============================================================================
sp_players:
    .a16
    .i16
    ; ---- camera 1 ----
    lda f:$7E0000 + SP_JOY1
    bit #$0100                  ; Right
    beq :+
    lda f:$7E0000 + H1
    inc a
    and #$00FF
    sta f:$7E0000 + H1
    lda f:$7E0000 + SP_JOY1
:
    .a16
    bit #$0200                  ; Left
    beq :+
    lda f:$7E0000 + H1
    dec a
    and #$00FF
    sta f:$7E0000 + H1
    lda f:$7E0000 + SP_JOY1
:
    .a16
    bit #$8000                  ; B = forward (2.0 px/f, 8.8 accumulators)
    beq @p1done
    lda f:$7E0000 + H1
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F1X
    sta f:$7E0000 + F1X
    xba                         ; low byte = signed integer delta
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00                  ; sign-extend
:
    clc
    adc f:$7E0000 + POS1X
    and #$03FF
    sta f:$7E0000 + POS1X
    lda f:$7E0000 + F1X
    and #$00FF
    sta f:$7E0000 + F1X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F1Y
    sta f:$7E0000 + F1Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS1Y
    and #$03FF
    sta f:$7E0000 + POS1Y
    lda f:$7E0000 + F1Y
    and #$00FF
    sta f:$7E0000 + F1Y
@p1done:
    .a16
    .i16
    ; ---- camera 2 ----
    lda f:$7E0000 + SP_JOY2
    bit #$0100                  ; Right
    beq :+
    lda f:$7E0000 + H2
    inc a
    and #$00FF
    sta f:$7E0000 + H2
    lda f:$7E0000 + SP_JOY2
:
    .a16
    bit #$0200                  ; Left
    beq :+
    lda f:$7E0000 + H2
    dec a
    and #$00FF
    sta f:$7E0000 + H2
    lda f:$7E0000 + SP_JOY2
:
    .a16
    bit #$8000                  ; B = forward
    beq @p2done
    lda f:$7E0000 + H2
    asl a
    asl a
    tax
    lda f:move_lut + 0, x
    clc
    adc f:$7E0000 + F2X
    sta f:$7E0000 + F2X
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2X
    and #$03FF
    sta f:$7E0000 + POS2X
    lda f:$7E0000 + F2X
    and #$00FF
    sta f:$7E0000 + F2X
    lda f:move_lut + 2, x
    clc
    adc f:$7E0000 + F2Y
    sta f:$7E0000 + F2Y
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    clc
    adc f:$7E0000 + POS2Y
    and #$03FF
    sta f:$7E0000 + POS2Y
    lda f:$7E0000 + F2Y
    and #$00FF
    sta f:$7E0000 + F2Y
@p2done:
    .a16
    .i16
    rts

; =============================================================================
; sp_sync_players — entities 0/1 mirror the camera positions so each player's
; marker renders in the OTHER band (in its OWN band the marker projects to
; v = 0 = behind the pivot row and self-culls by construction).
; WIDTH-RISK: .a16/.i16 throughout. Clobbers A.
; =============================================================================
sp_sync_players:
    .a16
    .i16
    lda f:$7E0000 + POS1X
    sta f:$7E0000 + SP_ENTS + 0
    lda f:$7E0000 + POS1Y
    sta f:$7E0000 + SP_ENTS + 2
    lda f:$7E0000 + POS2X
    sta f:$7E0000 + SP_ENTS + 8
    lda f:$7E0000 + POS2Y
    sta f:$7E0000 + SP_ENTS + 10
    rts

; =============================================================================
; sp_ai_tick — table-driven waypoint followers (entities 2..SP_N-1), the
; EXACT integer model the asset generator simulates at build time (which
; proves every follower reaches waypoints in bounded frames):
;   target = way[(i-2)&7][wp];  dx,dy = wrap-signed offsets
;   reached (Chebyshev < 24) -> wp = (wp+1)&3, 1-frame pause
;   else steer: cross((fx,fy)>>3, (dx,dy)>>3) < 0 -> h += 1; > 0 -> h -= 1
;        (fwd(h) = move256[h] = (-sin,-cos) rotates negative-cross-ward as h
;         grows); cross == 0 and dot < 0 -> h += 1 (180-degree tie-break);
;   then move at HALF speed: move256[h] asr 1 through the 8.8 accumulators.
; World-space only — the AI never reads the matrix (rotation-invariant by
; construction). All multiplies are 8x8 hardware ($4202) on >>3 magnitudes
; (<= 64, products <= 4096 -> the cross fits s16).
; WIDTH-RISK: A8 windows are the $4202/$4203 stores, sep/rep balanced;
; every multi-path label annotated. Clobbers A, X, Y + DP scratch (shared
; with the projection, which runs AFTER this in the frame).
; =============================================================================
sp_ai_tick:
    .a16
    .i16
.ifndef SP_ALTFRAME
    lda f:$7E0000 + SP_N
    cmp #3
    bcs :+
    rts                         ; N <= 2: players only, no followers
:
    .a16
    sec
    sbc #2
    sta z:sp_cnt                ; follower count
    lda #16
    sta z:sp_ent                ; entity byte offset (i = 2)
.else
    ; alt: the game loop staged z:sp_ent/z:sp_cnt (the active half's
    ; followers, players excluded); zero-count callers bail here
    lda z:sp_cnt
    bne :+
    rts
:
    .a16
.endif
@loop:
    .a16
    .i16
    ldx z:sp_ent
    ; --- target = sp_way + ((i-2)&7)*16 + wp*4 ---
    txa
    sec
    sbc #16
    lsr a
    lsr a
    lsr a
    and #$0007                  ; loop id
    asl a
    asl a
    asl a
    asl a                       ; loop*16
    sta z:sp_tmpm
    lda f:$7E0000 + SP_ENTS + 4, x  ; wp<<8 | heading
    xba
    and #$0003                  ; wp
    asl a
    asl a                       ; wp*4
    clc
    adc z:sp_tmpm
    phx
    tax
    lda f:sp_way, x
    sta z:sp_adx                ; tx (staging; becomes fx3 later)
    lda f:sp_way + 2, x
    sta z:sp_ady                ; ty
    plx
    ; --- wrap residues: raw = (t - pos) & 1023 ---
    lda z:sp_adx
    sec
    sbc f:$7E0000 + SP_ENTS + 0, x
    and #$03FF
    sta z:sp_mdx                ; raw dx (10-bit residue)
    lda z:sp_ady
    sec
    sbc f:$7E0000 + SP_ENTS + 2, x
    and #$03FF
    sta z:sp_mdy
    ; --- reached? Chebyshev < 24 on both axes (raw < 24 or raw > 1000) ---
    lda z:sp_mdx
    cmp #24
    bcc @nearx
    cmp #1001
    bcs @nearx
    bra @steer
@nearx:
    .a16
    lda z:sp_mdy
    cmp #24
    bcc @reach
    cmp #1001
    bcs @reach
    bra @steer
@reach:
    .a16
    ; wp = (wp+1)&3; heading byte preserved; 1-frame pause (no move)
    lda f:$7E0000 + SP_ENTS + 4, x
    clc
    adc #$0100
    and #$03FF
    sta f:$7E0000 + SP_ENTS + 4, x
    jmp @next
@steer:
    .a16
    .i16
    ; --- sign-extend the residues, arithmetic >>3 (|.| <= 64) ---
    lda z:sp_mdx
    cmp #512
    bcc :+
    ora #$FC00                  ; s16 from the 10-bit residue
:
    .a16
    cmp #$8000                  ; carry = sign; asr = ror with sign carry
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    sta z:sp_mdx                ; dx>>3
    lda z:sp_mdy
    cmp #512
    bcc :+
    ora #$FC00
:
    .a16
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    sta z:sp_mdy                ; dy>>3
    ; --- fwd = move256[h] >> 3 ---
    lda f:$7E0000 + SP_ENTS + 4, x
    and #$00FF
    asl a
    asl a
    phx
    tax
    lda f:move_lut + 0, x
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    sta z:sp_adx                ; fx>>3
    lda f:move_lut + 2, x
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    sta z:sp_ady                ; fy>>3
    plx
    ; --- t1 = (fx3)*(dy3) signed, via 8x8 HW multiply + sign masks ---
    ldy #$0000
    lda z:sp_adx
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4202                   ; |fx3|
    rep #$20
    .a16
    sty z:sp_u                  ; t1 sign accumulator
    ldy #$0000
    lda z:sp_mdy
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4203                   ; start |fx3|*|dy3|
    rep #$20
    .a16
    tya
    eor z:sp_u
    sta z:sp_u                  ; t1 sign mask (cover work for the product)
    lda $4216
    eor z:sp_u
    sec
    sbc z:sp_u                  ; t1 signed
    sta z:sp_vacc
    ; --- t2 = (fy3)*(dx3) ---
    ldy #$0000
    lda z:sp_ady
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4202                   ; |fy3|
    rep #$20
    .a16
    sty z:sp_u
    ldy #$0000
    lda z:sp_mdx
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4203                   ; start |fy3|*|dx3|
    rep #$20
    .a16
    tya
    eor z:sp_u
    sta z:sp_u
    lda $4216
    eor z:sp_u
    sec
    sbc z:sp_u                  ; t2 signed
    ; --- cross = t1 - t2; steer (see header for the sense derivation) ---
    sta z:sp_tmpm
    lda z:sp_vacc
    sec
    sbc z:sp_tmpm               ; A = cross
    beq @tiej
    cmp #$8000
    bcs @hplusj                 ; cross < 0 -> h += 1
    bra @hminus                 ; cross > 0 -> h -= 1
@tiej:
    .a16
    .i16
    jmp @tie                    ; (long trampolines: targets out of bra range)
@hplusj:
    .a16
    .i16
    jmp @hplus
@hminus:
    .a16
    lda f:$7E0000 + SP_ENTS + 4, x
    tay
    dec a
    and #$00FF
    sta z:sp_tmpm
    tya
    and #$FF00
    ora z:sp_tmpm
    sta f:$7E0000 + SP_ENTS + 4, x
    jmp @move
@tie:
    .a16
    .i16
    ; cross == 0: dot = fx3*dx3 + fy3*dy3; dot < 0 (facing away) -> h += 1
    ldy #$0000
    lda z:sp_adx
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4202
    rep #$20
    .a16
    sty z:sp_u
    ldy #$0000
    lda z:sp_mdx
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4203
    rep #$20
    .a16
    tya
    eor z:sp_u
    sta z:sp_u
    lda $4216
    eor z:sp_u
    sec
    sbc z:sp_u
    sta z:sp_vacc               ; fx3*dx3
    ldy #$0000
    lda z:sp_ady
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4202
    rep #$20
    .a16
    sty z:sp_u
    ldy #$0000
    lda z:sp_mdy
    cmp #$8000
    bcc :+
    eor #$FFFF
    inc a
    dey
:
    .a16
    sep #$20
    .a8
    sta $4203
    rep #$20
    .a16
    tya
    eor z:sp_u
    sta z:sp_u
    lda $4216
    eor z:sp_u
    sec
    sbc z:sp_u
    clc
    adc z:sp_vacc               ; dot
    cmp #$8000
    bcc @move                   ; dot >= 0: keep heading
@hplus:
    .a16
    lda f:$7E0000 + SP_ENTS + 4, x
    tay
    inc a
    and #$00FF
    sta z:sp_tmpm
    tya
    and #$FF00
    ora z:sp_tmpm
    sta f:$7E0000 + SP_ENTS + 4, x
@move:
    .a16
    .i16
    ; --- move at HALF speed along the (post-turn) heading ---
    lda f:$7E0000 + SP_ENTS + 4, x
    and #$00FF
    asl a
    asl a
    phx
    tax
    lda f:move_lut + 0, x
.ifndef SP_ALTFRAME
    cmp #$8000
    ror a                       ; vx/2 (1.0 px/f in 8.8)
.endif
    sta z:sp_adx                ; (alt: FULL vel per tick at HALF tick rate =
    lda f:move_lut + 2, x       ;  the same 1.0 px/f average world speed;
.ifndef SP_ALTFRAME
    cmp #$8000
    ror a
.endif
    sta z:sp_ady                ;  steering rate halves — feel-test item)
    plx
    ; x axis: s = fracx + vx2; pos += s>>8 (sign-extended); fracx = s & $FF
    lda f:$7E0000 + SP_ENTS + 6, x  ; fracy<<8 | fracx
    and #$00FF
    clc
    adc z:sp_adx
    sta z:sp_tmpm               ; s (s16, -256..511)
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00                  ; sign-extend the delta
:
    .a16
    clc
    adc f:$7E0000 + SP_ENTS + 0, x
    and #$03FF
    sta f:$7E0000 + SP_ENTS + 0, x
    lda f:$7E0000 + SP_ENTS + 6, x
    and #$FF00
    sta z:sp_u
    lda z:sp_tmpm
    and #$00FF
    ora z:sp_u
    sta f:$7E0000 + SP_ENTS + 6, x
    ; y axis (frac byte is the HIGH byte of the +6 word)
    lda f:$7E0000 + SP_ENTS + 6, x
    xba
    and #$00FF
    clc
    adc z:sp_ady
    sta z:sp_tmpm
    xba
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00
:
    .a16
    clc
    adc f:$7E0000 + SP_ENTS + 2, x
    and #$03FF
    sta f:$7E0000 + SP_ENTS + 2, x
    lda z:sp_tmpm
    and #$00FF
    xba
    and #$FF00
    sta z:sp_u
    lda f:$7E0000 + SP_ENTS + 6, x
    and #$00FF
    ora z:sp_u
    sta f:$7E0000 + SP_ENTS + 6, x
@next:
    .a16
    .i16
    lda z:sp_ent
    clc
    adc #8
    sta z:sp_ent
    dec z:sp_cnt
    beq @done
    jmp @loop
@done:
    .a16
    .i16
    rts

; =============================================================================
; sp_game_loop — the sprite-rail restructure of the shipping loop. VBlank
; commits the WHOLE snapshot S (OAM + pose ptrs/banks + origins) from the
; SAME H/POS values; then S advances (input/auto + AI); then the projection
; for S' runs into active display (WRAM-only). Zero floor/sprite skew.
; =============================================================================
sp_game_loop:
    .a16
    .i16
    wai
    lda f:G_FRAMES
    inc a
    sta f:G_FRAMES
    ; --- VBlank window: commit S ---
    jsr sp_oam_commit
    jsr sp_pose_ptrs
    jsr stamp_pose_banks
    jsr stamp_origins
    ; --- advance S -> S' ---
.ifdef SP_PIN
    ; pinned headings (with FREEZE this is a true still; pointers/banks are
    ; still restamped every frame from these values)
    lda #SP_H1
    sta f:$7E0000 + H1
    lda #SP_H2
    sta f:$7E0000 + H2
.else
    lda f:$7E0000 + SP_HOLD
    bne @held                   ; poked hold: world freezes (still capture)
.ifdef SP_INPUT
    jsr sp_read_pads            ; joypad-driven cameras (scripted in tests)
    jsr sp_players
.else
    lda f:$7E0000 + H1
    inc a
    and #$00FF                  ; 256 headings, +1/frame
    sta f:$7E0000 + H1
    lda f:$7E0000 + H2
    dec a                       ; opposite sense
    and #$00FF
    sta f:$7E0000 + H2
.ifndef FREEZE
    jsr sp_move_auto
.endif
.endif
.ifndef SP_STATIC
.ifndef SP_ALTFRAME
    jsr sp_ai_tick              ; waypoint followers (world-space only)
.else
    ; alt: tick ONLY the active half's followers (players 0/1 excluded)
    jsr sp_alt_toggle
    lda f:$7E0000 + SP_ENT0
    sta z:sp_ent
    lda f:$7E0000 + SP_HCNT
    sta z:sp_cnt
    lda f:$7E0000 + SP_HALF
    bne @aigo                   ; half B: all its entities are followers
    lda #16
    sta z:sp_ent                ; half A: skip the two players
    lda f:$7E0000 + SP_HCNT
    sec
    sbc #2
    bpl :+
    lda #$0000
:
    .a16
    sta z:sp_cnt
@aigo:
    .a16
    .i16
    jsr sp_ai_tick
.endif
.endif
@held:
    .a16
    .i16
.endif
.ifndef SP_STATIC
    jsr sp_sync_players         ; entities 0/1 = the player markers
.endif
    ; --- active display: project S' into the shadow ---
.ifndef SP_ALTFRAME
    jsr sp_project_all
.else
    jsr sp_project_all_alt
.endif
    jmp sp_game_loop

.ifdef SP_CYCLES
; =============================================================================
; sp_cycles_loop — free-running budget instrument (persp_cycles pattern):
; tick = project both bands (SP_N sprites) + OAM commit (+ AI if SP_CYCAI).
; NMI counts frames (u32 $E034); ticks u32 at $E030. HDMA dark + screen
; blanked (the caller staged that): the tick measures the CPU work only.
;     master_clocks_per_tick = frames * 357368 / ticks
; =============================================================================
sp_cycles_loop:
    .a16
    .i16
.ifdef SP_CYCAI
    jsr sp_ai_tick              ; AI-ONLY tick: pure per-follower cost
.elseif .defined(SP_CYCINT)
    jsr sp_ai_tick              ; INTEGRATED tick: the sweep's whole frame
    jsr sp_sync_players         ; work (pads/stamps excluded, ~1k mc)
    jsr sp_project_all
    jsr sp_oam_commit
.else
    jsr sp_project_all
    jsr sp_oam_commit
.endif
    lda f:$7E0000 + $E030
    inc a
    sta f:$7E0000 + $E030
    bne :+
    lda f:$7E0000 + $E032
    inc a
    sta f:$7E0000 + $E032
:
    jmp sp_cycles_loop
.endif

; =============================================================================
; data: build-time LUTs + worlds (gen_sprite_assets.py — deterministic,
; provenance-manifested; the S(k) ramp inside them is IMPORTED from the pose
; tool, never re-derived)
; =============================================================================
.segment "RODATA"
sp_sincos:    .incbin "assets/sp_sincos.bin"   ; 256 x (cos,sin) s8.8, |.|<=255
sp_vk:        .incbin "assets/sp_vk.bin"       ; d -> band row k ($FF = cull)
sp_recip_lo:  .incbin "assets/sp_recip_lo.bin" ; recip(k) low byte
sp_recip_hi:  .incbin "assets/sp_recip_hi.bin" ; recip(k) bit 8
.ifdef SP_CULLOFF
sp_tier_tbl:  .incbin "assets/sp_tier_nocull.bin" ; CONTROL: no margin culls
.else
sp_tier_tbl:  .incbin "assets/sp_tier_lut.bin" ; tier ladder + margin culls
.endif
sp_tier_tile:  .byte 0, 2, 4, 8, 12            ; CHR name per tier
sp_tier_half:  .byte 8, 8, 8, 16, 16           ; half box size (size bit is
                                               ; derived: (half>>3) & 2)
; positioned hi-table bits: entry (pair*4 + bits) = bits << (pair*2)
sp_hi_pos:     .byte $00, $01, $02, $03
               .byte $00, $04, $08, $0C
               .byte $00, $10, $20, $30
               .byte $00, $40, $80, $C0
sp_chr:       .incbin "assets/sp_chr.bin"      ; 64 names: 5 disc variants
.ifdef SP_VISWORLD
sp_world:     .incbin "assets/sp_world_vis.bin"  ; instrument: all visible
.elseif .defined(SP_FARWORLD)
sp_world:     .incbin "assets/sp_world_far.bin"  ; instrument: all pre-culled
.elseif .defined(SP_TIERWORLD)
sp_world:     .incbin "assets/sp_world_tier.bin" ; tier ladder + overflow row
.else
sp_world:     .incbin "assets/sp_world_main.bin" ; players + followers
.endif
sp_way:       .incbin "assets/sp_way.bin"      ; 8 loops x 4 waypoints
