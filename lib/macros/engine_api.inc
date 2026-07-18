; =============================================================================
; engine_api.inc — the engine calling-convention SSoT (API block + return slot)
; =============================================================================
; The single source of truth for the direct-page slots the macros marshal
; arguments into and the engine functions read back. BOTH the macro library and
; the engine modules include this, so the offsets cannot drift (audit A1-1).
;
; Include it once, BEFORE any engine `.asm` module, so engine files that read
; `API_BLOCK_BASE` / `ENGINE_A0` resolve them to these canonical values rather
; than a module-local fallback.
;
;   API_BLOCK_BASE  $60   16 parameter slots x 4 bytes ($60-$9F). The macros
;                         store each arg's low word into a slot; the engine fn
;                         reads it. Slot n is at API_BLOCK_BASE + n*4. THIS is
;                         the symbol an engine module like collision_engine.asm
;                         needs defined to assemble standalone (it reads the
;                         param slots); without it the module won't build.
;   ENGINE_A0       $20   return slot for engine fns that return via A0 (low 16
;                         bits). Hard-locked to $20 (design decision O7): the
;                         engine files' legacy default of $40 collides with hot
;                         globals; engine files guard it behind `.ifndef
;                         ENGINE_A0` (default $40), so defining $20 here first
;                         wins. (Note: not every engine fn uses A0 — e.g.
;                         engine_col_box returns its 0/1 directly in A.)
; =============================================================================

.ifndef SF_ENGINE_API_INC
SF_ENGINE_API_INC = 1

.ifndef ENGINE_A0
ENGINE_A0       = $20
.endif

.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif

.endif ; SF_ENGINE_API_INC
