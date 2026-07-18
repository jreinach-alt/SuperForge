; =============================================================================
; sf_scene.inc — scene state machine + dispatch (macro library)
; =============================================================================
; The scene-flow pattern proven by the platformer flagship (title -> game ->
; over / win -> soft restart), formalized: a scene-state word, a declared
; id -> init/tick table, immediate-init transitions, and a one-line per-frame
; dispatch. The state machine and transition plumbing live here; scene init
; and tick BODIES stay game code.
;
;   sf_scene_begin state_addr            — bind the scene-state word (yours)
;   sf_scene      id, init_sub, tick_sub — declare one scene (dense ids from 0)
;   sf_scene_end                         — close the table (EMITS the tick
;                                          jump table — place in CODE/RODATA)
;   sf_scene_goto id                     — transition: state := id, run init
;   sf_scene_dispatch                    — per-frame: jsr the current tick
;
; Usage (the flagship shape):
;
;   SC_TITLE = 0                        ; ids are YOUR constants, dense from 0
;   SC_GAME  = 1
;   ...
;   game_loop:
;       sf_frame_begin
;       ... per-frame work shared by every scene (audio tick, fades, anim) ...
;       sf_scene_dispatch               ; runs the current scene's tick
;       jmp game_loop
;   ...
;   menu_tick:                          ; tick = ONE FRAME of the scene; rts
;       btnp #BTN_START
;       beq @idle
;       sf_scene_goto SC_GAME           ; transition mid-tick...
;       rts                             ; ...then RETURN — never fall through
;   @idle:
;       sf_frame_end
;       rts
;   ...
;   sf_scene_begin SCENE                ; SCENE = your WRAM word (e.g. $1804)
;   sf_scene SC_TITLE, scene_title, menu_tick
;   sf_scene SC_GAME,  scene_game,  game_tick
;   sf_scene SC_OVER,  scene_over,  menu_tick
;   sf_scene SC_WIN,   scene_win,   menu_tick
;   sf_scene_end
;
; SOFT-RESTART CONTRACT (the load-bearing rule of scene flow):
;   NEVER re-run sf_coldstart or sf_audio_init from a scene init — the S-SMP
;   is no longer in IPL state and the PPU is live; a scene change is a SOFT
;   restart, not a power cycle. A scene init re-builds ONLY what the scene
;   owns: its text rows (sf_text_clear), its sprites (spr_clear), its game
;   state, its level (sf_level_load re-msets the pages — pickups respawn),
;   and its music (sf_music switches songs). Everything else — uploaded CHR,
;   palettes, tile flags, armed HDMA effects, the engine spine — PERSISTS
;   across a goto by design. Boot-once work belongs before the first
;   sf_scene_goto; per-scene work belongs in the init.
;
; TRANSITION SEMANTICS (immediate init — the flagship's proven shape):
;   sf_scene_goto stores the new id to the state word, then JSRs the new
;   scene's init RIGHT THERE and returns to the caller. There is no deferred/
;   pending scene: by the time goto falls through, the world is already the
;   new scene's. Therefore the caller MUST NOT continue into stale-scene code
;   — return to the loop top (rts from the tick, or check the state word
;   after any jsr that might transition, e.g. a life_lost helper, and bail).
;   The dispatch at the loop top re-reads the state word every frame, so the
;   next frame ticks the new scene.
;
; SETUP CONTRACT:
;   - Declare ids as assemble-time constants, DENSE and ASCENDING from 0.
;     sf_scene enforces declaration order (.error on a gap or duplicate);
;     sf_scene_goto on an undeclared id fails at assemble/link time
;     (unresolved `_sf_scene_init_<id>` / .assert) — no runtime dispatch into
;     the void is possible: the state word is written ONLY by sf_scene_goto,
;     and every goto id is checked against the table.
;   - sf_scene_begin/sf_scene emit no code or data (symbol bookkeeping only);
;     sf_scene_end EMITS the tick jump table — place the declaration block in
;     the CODE (or RODATA) segment, conventionally next to the scene inits.
;     Use sites (goto/dispatch) may appear before the block; forward refs are
;     fine.
;   - The state word is a 16-bit WRAM word the GAME allocates (game-array
;     region, e.g. $1804) so tests/tools can read it at a stable address.
;     After sf_scene_begin it is macro-owned: write it only via sf_scene_goto.
;   - Inits and ticks are subroutines: entered A16/I16, end with rts, and
;     must return with A16/I16 (every kit macro that toggles width restores
;     A16 on exit, so straight-line macro composition satisfies this).
;   - These macros define no labels and no .local symbols — they do not end
;     a cheap-local (@) scope at the call site.
; =============================================================================

.ifndef SF_SCENE_INC
SF_SCENE_INC = 1

; -----------------------------------------------------------------------------
; sf_scene_begin — bind the scene-state word and open the table.
; -----------------------------------------------------------------------------
; Args:    state_addr — 16-bit WRAM word holding the current scene id
; Emits:   nothing (symbol bookkeeping only)
.macro sf_scene_begin state_addr
    _SF_SCENE_STATE = state_addr
__sf_scene_n .set 0
.endmacro

; -----------------------------------------------------------------------------
; sf_scene — declare one scene: id -> (init subroutine, tick subroutine).
; -----------------------------------------------------------------------------
; Args:    id       — assemble-time constant; must equal the declaration index
;                     (dense, ascending from 0 — enforced with .error)
;          init_sub — subroutine run by sf_scene_goto on transition
;          tick_sub — subroutine run by sf_scene_dispatch every frame
; Emits:   nothing (the tick table is emitted by sf_scene_end)
.macro sf_scene id, init_sub, tick_sub
    .if (id) <> __sf_scene_n
        .error "sf_scene: ids must be dense and ascending from 0 (declaration order = id)"
    .endif
    .ident(.sprintf("_sf_scene_init_%d", id)) = init_sub
    .ident(.sprintf("_sf_scene_tick_%d", id)) = tick_sub
__sf_scene_n .set __sf_scene_n + 1
.endmacro

; -----------------------------------------------------------------------------
; sf_scene_end — close the table; emit the tick jump table.
; -----------------------------------------------------------------------------
; Emits:   _sf_scene_tick_tbl (.addr per scene) — place in CODE/RODATA.
; Defines: SF_SCENE_COUNT (assemble-time scene count; backs the goto .assert)
.macro sf_scene_end
    SF_SCENE_COUNT = __sf_scene_n
_sf_scene_tick_tbl:
    .repeat __sf_scene_n, I
        .addr .ident(.sprintf("_sf_scene_tick_%d", I))
    .endrepeat
.endmacro

; -----------------------------------------------------------------------------
; sf_scene_goto — transition to scene `id`: state := id, then run its init.
; -----------------------------------------------------------------------------
; Args:     id — assemble-time constant, a declared scene id (checked: an
;                undeclared id is an assemble/link-time error)
; Result:   state word = id; the scene's init has run to completion
; Clobbers: A (+ whatever the init clobbers)
; Contract: the init owns the state write's companion work — the caller must
;           return to the loop top after this macro (see TRANSITION SEMANTICS).
;
; WIDTH-RISK: forces A16 for the 16-bit state store; the init is entered
; A16/I16 (rep #$30) and must return A16/I16. Exits A16/I16.
.macro sf_scene_goto id
    .assert (id) >= 0 && (id) < SF_SCENE_COUNT, error, "sf_scene_goto: undeclared scene id"
    rep #$30
    .a16
    .i16
    lda #(id)
    sta _SF_SCENE_STATE
    jsr .ident(.sprintf("_sf_scene_init_%d", id))
.endmacro

; -----------------------------------------------------------------------------
; sf_scene_dispatch — run the current scene's tick (once per frame).
; -----------------------------------------------------------------------------
; Result:   the tick subroutine for the scene in the state word has run
; Clobbers: A, X (+ whatever the tick clobbers)
; Safety:   the state word is only ever written by sf_scene_goto with an
;           assemble-time-checked id, so the table index is in range by
;           construction — no runtime bounds check is needed (or emitted).
;
; WIDTH-RISK: forces A16/I16 for the table index math + jsr (abs,x); the tick
; is entered A16/I16 and must return A16/I16. Exits A16/I16.
.macro sf_scene_dispatch
    rep #$30
    .a16
    .i16
    lda _SF_SCENE_STATE
    asl a
    tax
    jsr (_sf_scene_tick_tbl, x)
.endmacro

.endif ; SF_SCENE_INC
