# =============================================================================
# SuperForge (asm-primary) — build the example scenarios + run their tests.
# =============================================================================
# Works from a materialized repo root (the engine subset, rom_template, macro
# library, and harness all present). For a dry-run tree, tools/dryrun_split.sh
# assembles that layout, then `make test` here proves it end-to-end.
# =============================================================================

CA65   := ca65 --cpu 65816
LD65   := ld65
INCLUDES := -I infrastructure/rom_template -I lib/macros -I engine
LDCFG  := infrastructure/rom_template/lorom.cfg
LDCFG_64K := infrastructure/rom_template/lorom_64k.cfg
LDCFG_SRAM := infrastructure/rom_template/lorom_sram.cfg
# 512KB LoROM for the Mode 7 streaming rail (flat tilemap + collision banks)
LDCFG_STREAM := infrastructure/rom_template/lorom_stream.cfg

# --- TAD audio (see lib/macros/sf_audio.inc for the audio build shape) ---
TADAPI    := lib/tad/audio-driver/ca65-api
LDCFG_TAD := infrastructure/rom_template/lorom_tad.cfg
# Audio + battery saves (lorom_tad.cfg + the SRAM window — the cfg headers
# carry the story; the platformer flagship's save/continue uses this shape)
LDCFG_TAD_SRAM := infrastructure/rom_template/lorom_tad_sram.cfg
# Audio + a dedicated Mode 7 map bank (lorom_tad.cfg + a BANK1 for the 32KB
# interleaved map — the rpg template's overworld + keep_music build shape)
LDCFG_TAD_M7 := infrastructure/rom_template/lorom_tad_m7.cfg
# Audio + Mode 7 map bank + battery SRAM (the rpg template's full shape: overworld
# + keep_music + a save point writing to SRAM slot 0, auto-loaded on boot)
LDCFG_TAD_M7_SRAM := infrastructure/rom_template/lorom_tad_m7_sram.cfg
AUDIO_INC := -I $(TADAPI) -I assets/audio
TAD_OBJS  := build/tad_audio_wrapper.o build/tad_audio_data.o

# Auto-discovered: any examples/<name>/main.asm or templates/<name>/main.asm is
# a buildable project (`make <name>` / `make all`) with NO Makefile edit needed.
#
# NON-DEFAULT LINK SHAPES (GAP-2): the generic build/%.sfc rule links lorom.cfg
# by default, so a game needing battery SRAM, TAD audio, or a Mode 7 map bank
# would otherwise build FINE but silently lack the SRAM window / audio banks /
# map bank — a silent copy-to-adapt trap. Instead of a bespoke per-game Makefile
# rule, a TEMPLATE DECLARES its linker cfg with a sentinel comment in main.asm:
#
#     ; LDCFG: lorom_tad_m7_sram.cfg
#
# The generic templates/%.sfc rule greps that line (sf_ldcfg below), resolves
# the cfg under infrastructure/rom_template/, and links it. A cfg name matching
# *_tad*.cfg ALSO pulls in the TAD audio objects + the audio include path (the
# audio templates need the wrapper + data objects linked in). Absent a sentinel,
# the default lorom.cfg is used. Copy-to-adapt a template -> keep the sentinel
# line, no Makefile edit. (See docs/guides/adapting_a_rail.md.)
#
# Standalone test ROMs in tests/ that need a non-default cfg (save_test,
# mode7_test, audio_test) keep their explicit rules below — the sentinel
# mechanism is for the templates/ home only.
#
# sf_ldcfg: read the "LDCFG:" sentinel from a source file, default lorom.cfg.
# Returns the full path under infrastructure/rom_template/. $(call sf_ldcfg,<src>)
SF_LDCFG_DIR := infrastructure/rom_template
sf_ldcfg = $(SF_LDCFG_DIR)/$(or $(strip $(shell sed -n 's/^.*LDCFG:[[:space:]]*\([^[:space:]]*\).*/\1/p' $(1) | head -1)),lorom.cfg)

EXAMPLES  := $(notdir $(patsubst %/main.asm,%,$(wildcard examples/*/main.asm)))
TEMPLATES := $(notdir $(patsubst %/main.asm,%,$(wildcard templates/*/main.asm)))
PROJECTS  := $(EXAMPLES) $(TEMPLATES)
ROMS      := $(addprefix build/,$(addsuffix .sfc,$(PROJECTS)))

# Standalone test ROMs in tests/ (debug-region result ROMs, e.g. col_box_test)
# that a pytest loads + asserts on. Built into build/ alongside projects.
TESTROMS  := window_test col_box_test bg_scroll_test text_test col_map_test jump_test patrol_test stomp_test level_test \
             png2snes_sprite_test png2snes_bg_test pool_test autoscroll_test anim_test meta_test physics_tail_test level_tail_test \
             mode7_test math_test parallax_test gradient_test bend_test bend_parabola_test bend_cycles_test \
             bend_layer_test bend_hscroll_test bend_reverse_test \
             bend_slide_test bend_cycles_refill_test \
             bend_v_test bend_v_reverse_test bend_v_scroll_test \
             horizon_compose_test \
             colormath_test bright_fade_test pal_cycle_test save_test \
             dialog_test mosaic_transition_test mode7_stream_test mode7_chamber_cycles_test persp_cycles_test \
             mode0_test mode1_test mode2_test mode3_test mode4_test mode5_test mode6_test \
             obj_hud_test obj_hud_mode3_test opt_curve_test

# Audio-linked ROMs (different build shape: lorom_tad.cfg + the TAD objects)
AUDIOROMS := audio_test

# Shared sources every ROM transitively includes — listed as prerequisites so
# editing the engine or a macro rebuilds dependents (the acceptance agent
# re-tested a silently-stale ROM after an engine edit before this existed).
ENGINE_DEPS := $(wildcard engine/*.asm) $(wildcard engine/*.inc) $(wildcard lib/macros/*.inc)

# Everything the width gate lints: the macro library + every project + test ROM.
# width_lint.py does NOT follow .include directives, so a project's main.asm being
# linted does NOT cover the page/harness sources it pulls from assets/*.inc — a
# real width finding sitting in unlinted page source would let the gate report
# "clean" anyway (the Mode-0 pilot audit's P1-process gap, F-2). The fix is to lint
# EVERY rail's assets/*.inc, not just mode_showcase's: the broad globs below subsume
# the old `templates/mode_showcase/assets/*.inc` line. Most rails' assets are pure
# data (palettes/tile blobs/collision maps/LUTs) and lint trivially clean; only
# mode_showcase ships executable code in assets/, but covering all of them closes
# the gate-invisibility hole for any future code-in-assets across all rails.
LINT_ASM := $(wildcard lib/macros/*.inc) $(wildcard examples/*/main.asm) \
            $(wildcard templates/*/main.asm) $(wildcard templates/*/*.inc) \
            $(wildcard tests/*.asm) \
            $(wildcard templates/*/assets/*.inc) $(wildcard examples/*/assets/*.inc)

.PHONY: all examples templates testroms test check width-check zp-check zp-baseline cleanroom-check provenance-check clean $(PROJECTS) $(TESTROMS)

all: examples templates testroms audioroms

audioroms: $(addprefix build/,$(addsuffix .sfc,$(AUDIOROMS)))

build/tad_audio_wrapper.o: engine/tad_audio_wrapper.asm | build
	$(CA65) -I $(TADAPI) $< -o $@

build/tad_audio_data.o: assets/audio/tad_audio_data.asm | build
	$(CA65) -I assets/audio $< -o $@

# Audio test ROMs: main object + wrapper + data, linked with the TAD config
build/audio_test.sfc: tests/audio_test.asm $(TAD_OBJS) $(ENGINE_DEPS)
	$(CA65) $(INCLUDES) $(AUDIO_INC) $< -o build/audio_test.o
	$(LD65) -C $(LDCFG_TAD) build/audio_test.o $(TAD_OBJS) -o $@
	@echo "built $@"

# NOTE (GAP-2): platformer and rpg formerly had bespoke rules here. Both now
# build through the generic templates/%.sfc rule above, which reads their
# "; LDCFG:" sentinel (platformer -> lorom_tad_sram.cfg; rpg ->
# lorom_tad_m7_sram.cfg) and links the TAD objects because the cfg matches
# *_tad*.cfg. No Makefile edit is needed to copy-to-adapt either rail.

# Mode 7 run-gate: 64KB image (the 32KB interleaved map blob fills BANK1),
# linked with lorom_64k.cfg (explicit rule wins over the generic pattern).
build/mode7_test.sfc: tests/mode7_test.asm tests/fixtures/mode7/checker_map.bin $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/mode7_test.o
	$(LD65) -C $(LDCFG_64K) build/mode7_test.o -o $@
	@echo "built $@"

# Mode 7 chamber per-frame CPU cost gate (64KB image, lorom_64k.cfg). No map
# blob — it times the engine tick, not rendering.
build/mode7_chamber_cycles_test.sfc: tests/mode7_chamber_cycles_test.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/mode7_chamber_cycles_test.o
	$(LD65) -C $(LDCFG_64K) build/mode7_chamber_cycles_test.o -o $@
	@echo "built $@"

# Perspective live-camera-B budget gate (64KB image, lorom_64k.cfg). Times a
# per-scanline pv_rebuild at the split_h_persp_demo params; the pytest builds
# -D variants (line-count / interp / double-solve). Default build = camera A's
# full solve. No map blob — it times the CPU table build, not rendering.
build/persp_cycles_test.sfc: tests/persp_cycles_test.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/persp_cycles_test.o
	$(LD65) -C $(LDCFG_64K) build/persp_cycles_test.o -o $@
	@echo "built $@"

# Mode 7 2-axis streaming run-gate: 512KB image (lorom_stream.cfg). The flat
# tilemap (BANK2/3) + world-space collision (BANK4/5) + the interleaved seed
# (BANK1) live in dedicated banks. Defines MODE7_STREAM_NMI so nmi_handler.asm
# pulls the streaming VBlank DMA dispatch. Explicit rule wins over the generic
# pattern. The fixture .bin/.inc are prerequisites so editing the world rebuilds.
build/mode7_stream_test.sfc: tests/mode7_stream_test.asm \
		tests/fixtures/mode7_stream/world_seed.bin \
		tests/fixtures/mode7_stream/world_flat_bank0.bin \
		tests/fixtures/mode7_stream/world_flat_bank1.bin \
		tests/fixtures/mode7_stream/world_collision_bank0.bin \
		tests/fixtures/mode7_stream/world_collision_bank1.bin \
		tests/fixtures/mode7_stream/world_stream.inc $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) -I tests/fixtures/mode7_stream -D MODE7_STREAM_NMI $< -o build/mode7_stream_test.o
	$(LD65) -C $(LDCFG_STREAM) build/mode7_stream_test.o -o $@
	@echo "built $@"

# Mode-1 normal-BG horizontal column-streaming run-gate (Streaming rail Mode 1
# / Sprint S1): 512KB image (lorom_stream.cfg). The WIDE flat level (BANK1) +
# the Four Seasons CHR (BANK2) live in dedicated banks. NO -D needed — the kit
# nmi_handler.asm already carries the STREAM_PENDING drain. The fixture
# .bin/.inc are prerequisites so regenerating the level rebuilds the ROM.
build/bg_stream_test.sfc: tests/bg_stream_test.asm \
		tests/fixtures/bg_stream/level_flat.bin \
		tests/fixtures/bg_stream/level_chr.bin \
		tests/fixtures/bg_stream/bg_stream_world.inc $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) -I tests/fixtures/bg_stream $< -o build/bg_stream_test.o
	$(LD65) -C $(LDCFG_STREAM) build/bg_stream_test.o -o $@
	@echo "built $@"

# Mode-1 normal-BG 2-AXIS (horizontal + vertical) streaming run-gate (Streaming
# rail Mode 1 / Sprint S2a): 512KB image (lorom_stream.cfg). BANK1 = column-
# major level (32KB), BANK2 = row-major level (32KB), BANK3 = Four Seasons CHR.
# -D BG_STREAM_2AXIS makes the column producer emit the rows-32..63 sub-slot for
# the 64x64 tilemap; the kit nmi_handler.asm carries both the STREAM_PENDING
# (column) and STREAM_ROW_PENDING (row) drains. Fixture .bin/.inc are prereqs.
build/bg_stream2d_test.sfc: tests/bg_stream2d_test.asm \
		tests/fixtures/bg_stream2d/level_flat.bin \
		tests/fixtures/bg_stream2d/level_flat_row.bin \
		tests/fixtures/bg_stream2d/level_chr.bin \
		tests/fixtures/bg_stream2d/bg_stream_world.inc $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) -I tests/fixtures/bg_stream2d -D BG_STREAM_2AXIS $< -o build/bg_stream2d_test.o
	$(LD65) -C $(LDCFG_STREAM) build/bg_stream2d_test.o -o $@
	@echo "built $@"

# platformer_stream — the PLAYABLE Mode-1 platformer on the 2-axis BG1 streaming
# substrate (Streaming rail Mode 1 / Sprint S2b-M2, FINAL). Same 512KB image +
# -D BG_STREAM_2AXIS as bg_stream2d_test, but a full player-physics + world-space
# collision template (fork base templates/platformer). BANK1 = column-major
# level, BANK2 = row-major level, BANK3 = Four Seasons CHR, BANK4 = world-space
# collision table. Explicit rule (wins over the generic templates/%.sfc rule)
# because it needs the -D and the tests/fixtures/platformer_stream/*.bin prereqs.
build/platformer_stream.sfc: templates/platformer_stream/main.asm \
		templates/platformer_stream/assets/hero.inc \
		tests/fixtures/platformer_stream/level_flat.bin \
		tests/fixtures/platformer_stream/level_flat_row.bin \
		tests/fixtures/platformer_stream/level_chr.bin \
		tests/fixtures/platformer_stream/level_collision.bin \
		tests/fixtures/platformer_stream/bg_stream_world.inc $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) -I templates/platformer_stream -I tests/fixtures/platformer_stream -D BG_STREAM_2AXIS $< -o build/platformer_stream.o
	$(LD65) -C $(LDCFG_STREAM) build/platformer_stream.o -o $@
	@echo "built $@"

# Battery-SRAM run-gate: linked with lorom_sram.cfg (the kit cfg mapping
# the $70:0000-$70:1FFF SRAM window — its header explains why no header.inc
# variant is needed). Explicit rule wins over the generic pattern.
build/save_test.sfc: tests/save_test.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/save_test.o
	$(LD65) -C $(LDCFG_SRAM) build/save_test.o -o $@
	@echo "built $@"

# OBJ sprite-font HUD brick: ONE source, TWO ROMs. obj_hud_test (Mode 1) builds
# through the generic tests/%.sfc rule below. obj_hud_mode3_test is the same
# source with -D HUD_MODE3 (the 256-colour Mode 3 variant — the critical case
# where the BG owns CGRAM 0-239 and the HUD owns OBJ pal 7 = CGRAM 240-255).
# Explicit rule wins over the generic pattern. Default 32KB lorom.cfg.
build/obj_hud_mode3_test.sfc: tests/obj_hud_test.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) -D HUD_MODE3 $< -o build/obj_hud_mode3_test.o
	$(LD65) -C $(LDCFG) build/obj_hud_mode3_test.o -o $@
	@echo "built $@"

# NOTE (GAP-2): racer, railshooter, boss, and boss_saucer formerly had bespoke
# 64KB rules here. All four now build through the generic templates/%.sfc rule
# above, which reads their "; LDCFG: lorom_64k.cfg" sentinel (the 32KB Mode 7
# map blob fills BANK1). Their assets/*.bin is auto-discovered as a prerequisite
# by that rule's $(wildcard templates/%/assets/*.bin). No Makefile edit needed.

build:
	@mkdir -p build

examples: $(addprefix build/,$(addsuffix .sfc,$(EXAMPLES)))
templates: $(addprefix build/,$(addsuffix .sfc,$(TEMPLATES)))
testroms: $(addprefix build/,$(addsuffix .sfc,$(TESTROMS)))

# Per-project phony aliases: `make hello_world`, `make sprite_game`
$(PROJECTS): %: build/%.sfc

# Per-test-ROM phony aliases: `make mode0_test`, `make colormath_test`, etc.
$(TESTROMS): %: build/%.sfc

# Projects live in examples/ or templates/; make picks whichever has the source.
build/%.sfc: examples/%/main.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/$*.o
	$(LD65) -C $(LDCFG) build/$*.o -o $@
	@echo "built $@"

# Generic template rule (GAP-2 sentinel-driven). The cfg comes from the
# "; LDCFG:" sentinel in the template's main.asm (sf_ldcfg, default lorom.cfg);
# a *_tad*.cfg name also links the TAD audio objects + audio include path. The
# template's own assets/ is on the include path so a copy-safe basename .incbin
# (GAP-3) resolves, and any assets/*.bin OR assets/*.inc is a prerequisite so
# editing the map blob OR a template's included logic module (e.g. the showcase
# harness's showcase_*.inc) rebuilds the ROM — without the *.inc dep, `make`
# reports "Nothing to be done" and you test a STALE ROM (S1 paper cut).
# .SECONDEXPANSION lets the per-target wildcard see $*.
.SECONDEXPANSION:
build/%.sfc: templates/%/main.asm $$(wildcard templates/%/assets/*.bin) $$(wildcard templates/%/assets/*.inc) $(TAD_OBJS) $(ENGINE_DEPS)
	@mkdir -p build
	@cfg='$(call sf_ldcfg,$<)'; \
	 case "$$cfg" in \
	   *_tad*.cfg) \
	     echo "$(CA65) $(INCLUDES) $(AUDIO_INC) -I templates/$*/assets $< -o build/$*.o  [cfg=$$cfg +TAD]"; \
	     $(CA65) $(INCLUDES) $(AUDIO_INC) -I templates/$*/assets $< -o build/$*.o && \
	     $(LD65) -C "$$cfg" build/$*.o $(TAD_OBJS) -o $@ ;; \
	   *) \
	     echo "$(CA65) $(INCLUDES) -I templates/$*/assets $< -o build/$*.o  [cfg=$$cfg]"; \
	     $(CA65) $(INCLUDES) -I templates/$*/assets $< -o build/$*.o && \
	     $(LD65) -C "$$cfg" build/$*.o -o $@ ;; \
	 esac
	@echo "built $@ (cfg=$(notdir $(call sf_ldcfg,$<)))"

build/%.sfc: tests/%.asm $(ENGINE_DEPS)
	@mkdir -p build
	$(CA65) $(INCLUDES) $< -o build/$*.o
	$(LD65) -C $(LDCFG) build/$*.o -o $@
	@echo "built $@"

# Width-tracking gate (the platform's #1 silent-corruption class). Zero
# findings allowed — these are clean files, no grandfather baseline. Run by the
# .claude lint hook after every asm/inc edit, and by `make check`.
# NOTE: this target does NOT consume reports/width_lint_baseline.json — it runs
# width_lint.py per-file expecting zero output. That baseline JSON is parent-repo
# infrastructure for a different --baseline invocation and is not used here.
width-check:
	@fail=0; for f in $(LINT_ASM); do \
	  out=$$(python3 tools/width_lint.py "$$f" 2>&1); \
	  if [ -n "$$out" ]; then echo "$$out"; fail=1; fi; \
	done; \
	if [ $$fail -ne 0 ]; then echo "width-check: FAIL"; exit 1; fi; \
	echo "width-check: clean ($(words $(LINT_ASM)) files)"

# ZP / DP-allocation gate (F4 — streaming rail v2 remediation). Sibling of
# width-check: catches the DP-byte collision silent-corruption class (two
# subsystems claiming the same Direct Page byte). The symbol table is built from
# engine/engine_state.inc (materialized into the kit); runs against the committed
# baseline (reports/zp_lint_baseline.json) so only NEW findings fail. Gates new
# streaming-style DP allocations (e.g. the streaming engine's ES_M7S_PTR=$9A).
# Requires the materialized engine/ (present after dryrun_split). See
# tools/zp_lint.py and CLAUDE.md "ZP Allocation Discipline".
ZP_LINT_TARGETS := engine lib/macros templates tests
ZP_BASELINE     := reports/zp_lint_baseline.json
zp-check:
	@if [ ! -f engine/engine_state.inc ]; then \
	  echo "zp-check: SKIP (no engine/engine_state.inc — run from a materialized kit)"; \
	else \
	  python3 tools/zp_lint.py $(ZP_LINT_TARGETS) --baseline $(ZP_BASELINE) --summary; \
	fi

zp-baseline:
	@python3 tools/zp_lint.py $(ZP_LINT_TARGETS) --write-baseline $(ZP_BASELINE)
	@echo "zp baseline written to $(ZP_BASELINE) — review before committing."

# Clean-room NAME TRIPWIRE (cheap floor; NON-EXHAUSTIVE). Scans committed text
# AND zip-internal text members for retail game / company / eliminated-lineage
# names. A hit is a provenance SIGNAL ("look closer"), not a guarantee. The
# COMPLETE high-risk control is provenance-check below. See docs/cleanroom_policy.md.
cleanroom-check:
	@bash tools/cleanroom_check.sh .

# Reproducible-assets / provenance gate (the COMPLETE high-risk control).
# Enumerates every committed blob + large data table and proves each is
# regenerable-from-a-committed-generator OR registered third-party OR attested
# (tools/provenance_manifest.toml). FAILs any opaque blob — the rip-detector —
# and verifies every third-party blob's NOTICE attribution chain is intact.
# Re-runs each generator in a sandbox and byte-diffs (the strong proof); pass
# PROVENANCE_FLAGS=--no-regen for the fast coverage-only check.
PROVENANCE_FLAGS ?=
provenance-check:
	@python3 tools/provenance_check.py $(PROVENANCE_FLAGS) .

# Full gate: clean-room (tripwire + provenance) + lint (width + zp) + build +
# the projects' done-conditions. The clean-room gates now RUN here (previously
# they existed but were never wired into CI — the gap the recovery-gate closed).
check: cleanroom-check provenance-check width-check zp-check test

# The projects' done-conditions (boots, renders, responds to input, plays).
test: all
	PYTHONPATH=. python3 -m pytest tests/ -v

clean:
	rm -rf build
