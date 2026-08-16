# superforge — build: allocator -> gates -> toy ROM.
# Run from superforge/. The allocator is part of the BUILD: an infeasible
# declaration or a raw address literal STOPS the build (non-zero exit).

PY      := python3
BUILD   := build
VROM    := vendor/rom
CA65    := ca65 --cpu 65816
LD65    := ld65

# `microzero`, `probes`, `measure` and `rom-unbacked` were absent here until
# `make rail-registered` was written and named microzero on its first run —
# the FIRST rail in the tree, missing site 1 of the six. All four are recipe
# targets that build no file of their own name, so a stray file called
# `microzero` in the repo root would have made `make microzero` a silent
# no-op. The other three are the same shape and are fixed alongside it.
.PHONY: all toy alloc no-literals toy-bad rom-unbacked clean test width-check \
	cleanroom \
	time-check falsify determinism \
	probe-colmap microzero room probes measure rail-registered \
	register register-write push gates breaker shmup platformer split_v_fight \
	hud_game \
	m7dg-assets m7_dungeon m7dg-labels m7dg-measure m7dg-measure-logic \
	sh2-assets split_h_2p_demo sh2-variants sh2-labels sh2-measure bare-check \
	m7x-assets mode7_explore pfs-assets platformer_stream scroller \
	camera_follow maze jumper patrol sprite_game stomper scroll_run brawler \
	split_h_matrix_demo split_h_persp3_demo \
	svd-assets split_v_demo svd-nowin split_v_seamtrial \
	split_h_demo shd-autodemo shp-assets split_h_persp_demo shp-autodemo \
	racer rc-assets seam_irq_trial sit-origin sit-mistime \
	split_h_irq_grad_demo shg-nograd shg-origin \
	m7c-assets mode7_chamber railshooter rs-assets m7_oshoot mo-assets \
	rpg rpg-assets boss bs-assets boss_saucer sau-assets \
	meteor_event met-assets mode7_flight m7f-assets

all: toy

# Every rule that writes into $(BUILD) carries it as an order-only
# prerequisite — nothing may depend on "some earlier target happened to
# create the directory" (that masked bug broke the clean-slate build).
$(BUILD):
	mkdir -p $(BUILD)

# ---- the allocator: emits the map or fails the build ----------------------
alloc $(BUILD)/engine_state_toy.inc $(BUILD)/engine_state_globals.inc \
		$(BUILD)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/toy/*/feature.toml) engine/toy/game.toml \
		engine/toy/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game engine/toy --out $(BUILD)

# ---- the no-literals gate: engine sources use emitted symbols only --------
no-literals: $(BUILD)/symbol_map.json
	$(PY) allocator/no_literals.py --map $(BUILD)/symbol_map.json \
		engine/toy/main.asm

# ---- the good toy ROM -----------------------------------------------------
$(BUILD)/toy.o: engine/toy/main.asm $(BUILD)/engine_state_toy.inc \
		$(BUILD)/engine_state_globals.inc \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc | $(BUILD)
	$(CA65) -I $(BUILD) -I $(VROM) -o $@ engine/toy/main.asm

$(BUILD)/toy.sfc: $(BUILD)/toy.o $(VROM)/lorom_32k.cfg | $(BUILD)
	$(LD65) -C $(VROM)/lorom_32k.cfg -o $@ $(BUILD)/toy.o
	$(PY) tools/fix_checksum.py $@

toy: no-literals $(BUILD)/toy.sfc

# ---- microzero: the tiny complete game ------------------
MZ      := game/microzero
MZ_MAP  := $(BUILD)/mz
MZ_ASM  := $(MZ)/main.asm $(wildcard $(MZ)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(MZ_MAP)/engine_state_globals.inc $(MZ_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(MZ)/game.toml \
		$(MZ)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(MZ) --features-dir engine/features \
		--out $(MZ_MAP)

$(BUILD)/assets/font_2bpp.bin: tools/gen_font.py vendor/fonts/unscii-8.hex | $(BUILD)
	$(PY) tools/gen_font.py vendor/fonts/unscii-8.hex $@

# The VWF face: 1bpp LEFT-ALIGNED glyph masks + the per-glyph advance table.
# The compositor's only two inputs, so a face swap is this rule's input changing
# and nothing else (docs/11_font_assets.md §3 keeps the face question open).
$(BUILD)/assets/vwf_glyphs.bin $(BUILD)/assets/vwf_widths.bin: \
		tools/gen_vwf_font.py vendor/fonts/unscii-8.hex | $(BUILD)
	$(PY) tools/gen_vwf_font.py vendor/fonts/unscii-8.hex $(BUILD)/assets

$(BUILD)/assets/world_map.bin $(BUILD)/assets/floor_tiles.bin \
$(BUILD)/assets/floor_pal.bin: tools/gen_m7_assets.py | $(BUILD)
	$(PY) tools/gen_m7_assets.py $(BUILD)/assets

# The collision flag table: DERIVED from gen_m7_assets' tile-semantics sets,
# so it cannot drift from the map it describes (the design review).
$(BUILD)/assets/col_flags.bin: tools/gen_col_flags.py tools/gen_m7_assets.py | $(BUILD)
	$(PY) tools/gen_col_flags.py $(BUILD)/assets

$(BUILD)/assets/poses_ab.bin $(BUILD)/assets/poses_cd.bin: \
		tools/gen_pose_tables.py | $(BUILD)
	$(PY) tools/gen_pose_tables.py --lines 180 --scale-far 436 \
		--scale-near 77 $(BUILD)/assets

$(BUILD)/assets/gradient_tabs.bin: tools/gen_gradient.py | $(BUILD)
	$(PY) tools/gen_gradient.py $(BUILD)/assets

$(BUILD)/assets/car_chr.bin $(BUILD)/assets/car_pal.bin: \
		tools/gen_car_sprite.py | $(BUILD)
	$(PY) tools/gen_car_sprite.py $(BUILD)/assets

$(BUILD)/assets/sky_chr.bin $(BUILD)/assets/sky_map.bin \
$(BUILD)/assets/sky_pal.bin: tools/gen_sky.py | $(BUILD)
	$(PY) tools/gen_sky.py $(BUILD)/assets

$(MZ_MAP)/move_lut.inc: tools/gen_move_lut.py | $(BUILD)
	$(PY) tools/gen_move_lut.py $(MZ_MAP)

$(BUILD)/microzero.sfc: $(MZ_ASM) $(MZ)/world.inc \
		$(MZ_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin $(BUILD)/assets/world_map.bin \
		$(BUILD)/assets/poses_ab.bin $(BUILD)/assets/gradient_tabs.bin \
		$(BUILD)/assets/car_chr.bin $(BUILD)/assets/sky_chr.bin \
		$(BUILD)/assets/vwf_glyphs.bin $(BUILD)/assets/vwf_widths.bin \
		$(BUILD)/assets/col_flags.bin \
		$(MZ_MAP)/move_lut.inc \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(MZ_MAP)/symbol_map.json $(MZ_ASM)
	$(CA65) -I $(MZ_MAP) -I $(VROM) -I $(MZ) -I engine/features/scene_mgr \
		-I engine/features/input -I engine/features/fade \
		-I engine/features/bg_text -I engine/features/mode7_floor \
		-I engine/features/split_band -I engine/features/mode7_persp \
		-I engine/features/rgb_gradient -I engine/features/mode7_stream \
		-I engine/features/oam_sprites -I engine/features/player_car \
		-I engine/features/race_logic -I engine/features/sky_band \
		-I engine/features/vwf -I engine/features/col_map \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/microzero.o $(MZ)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/microzero.o
	$(PY) tools/fix_checksum.py $@

microzero: $(BUILD)/microzero.sfc

# ---- room: "the room" ---------------------------------
# A playable slice whose subject is WINDOWING: a lantern the player carries,
# built from WH0/WH1 per scanline, with colour math confined to its outside.
RM      := game/room
RM_MAP  := $(BUILD)/rm
RM_ASM  := $(RM)/main.asm $(wildcard $(RM)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(RM_MAP)/engine_state_globals.inc $(RM_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(RM)/game.toml \
		$(RM)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(RM) --features-dir engine/features \
		--out $(RM_MAP)

$(BUILD)/assets/bg1_chr.bin $(BUILD)/assets/bg1_map.bin \
$(BUILD)/assets/bg1_pal.bin $(BUILD)/assets/bg2_chr.bin \
$(BUILD)/assets/bg2_map.bin $(BUILD)/assets/bg2_pal.bin: \
		tools/gen_room_assets.py | $(BUILD)
	$(PY) tools/gen_room_assets.py $(BUILD)/assets

$(BUILD)/assets/hero_chr.bin $(BUILD)/assets/hero_pal.bin: \
		tools/gen_hero_sprite.py | $(BUILD)
	$(PY) tools/gen_hero_sprite.py $(BUILD)/assets

$(BUILD)/assets/iris_lut.bin: tools/gen_iris_lut.py | $(BUILD)
	$(PY) tools/gen_iris_lut.py $(BUILD)/assets

$(BUILD)/assets/crc16_lut.bin: tools/gen_crc16_lut.py | $(BUILD)
	$(PY) tools/gen_crc16_lut.py $(BUILD)/assets

# --- TAD audio objects (room) ----------------------------------------------
# Separate compilation units: tad-audio.s owns its own
# .bss/.zeropage layout; the generated export owns AUDIO_DATA0. Neither is
# in RM_ASM — the no_literals scope covers hand-authored engine ASM only,
# and these are vendored + generated (assets/audio/README.md). The wrapper
# needs the ROOM's emitted map for its allocator<->linker bridge asserts,
# so its object is per-game.
$(BUILD)/rm_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(RM_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(RM_MAP) -I vendor/tad -o $@ $<

$(BUILD)/rm_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

$(BUILD)/room.sfc: $(RM_ASM) $(RM_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin \
		$(BUILD)/assets/bg1_chr.bin $(BUILD)/assets/bg1_map.bin \
		$(BUILD)/assets/bg1_pal.bin $(BUILD)/assets/bg2_chr.bin \
		$(BUILD)/assets/bg2_map.bin $(BUILD)/assets/bg2_pal.bin \
		$(BUILD)/assets/hero_chr.bin $(BUILD)/assets/hero_pal.bin \
		$(BUILD)/assets/iris_lut.bin $(BUILD)/assets/crc16_lut.bin \
		$(BUILD)/rm_tad_wrapper.o $(BUILD)/rm_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(RM_MAP)/symbol_map.json $(RM_ASM)
	$(CA65) -I $(RM_MAP) -I $(VROM) -I $(RM) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/input2 \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/room_bg \
		-I engine/features/room_hero -I engine/features/room_logic \
		-I engine/features/window_iris -I engine/features/save \
		-I vendor/tad -I assets/audio/export \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/room.o $(RM)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/room.o \
		$(BUILD)/rm_tad_wrapper.o $(BUILD)/rm_tad_data.o
	$(PY) tools/fix_checksum.py $@

room: $(BUILD)/room.sfc

# ---- breaker: the paddle-and-ball rail ----------
# The BG keystone: a per-rail BG feature (breaker_bg) owning BOTH of the
# rail's co-resident layers.
BK      := game/breaker
BK_MAP  := $(BUILD)/bk
BK_ASM  := $(BK)/main.asm $(wildcard $(BK)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(BK_MAP)/engine_state_globals.inc $(BK_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(BK)/game.toml \
		$(BK)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(BK) --features-dir engine/features \
		--out $(BK_MAP)

$(BUILD)/assets/brk_bg_chr.bin $(BUILD)/assets/brk_bg_pal.bin \
$(BUILD)/assets/brk_sky_chr.bin $(BUILD)/assets/brk_sky_pal.bin \
$(BUILD)/assets/brk_obj_chr.bin $(BUILD)/assets/brk_obj_pal.bin \
$(BUILD)/assets/brk_grad.bin: tools/gen_breaker_assets.py | $(BUILD)
	$(PY) tools/gen_breaker_assets.py $(BUILD)/assets

# --- TAD audio objects (breaker) -------------------------------------------
# Per-game objects for the same reason room's are: the wrapper needs THIS
# game's emitted map for its allocator<->linker bridge asserts. Neither is in
# BK_ASM — the no_literals scope covers hand-authored engine ASM only, and
# these are vendored + generated (assets/audio/README.md).
$(BUILD)/bk_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(BK_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(BK_MAP) -I vendor/tad -o $@ $<

$(BUILD)/bk_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

$(BUILD)/breaker.sfc: $(BK_ASM) $(BK)/breaker.inc \
		$(BK_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin \
		$(BUILD)/assets/brk_bg_chr.bin $(BUILD)/assets/brk_bg_pal.bin \
		$(BUILD)/assets/brk_sky_chr.bin $(BUILD)/assets/brk_sky_pal.bin \
		$(BUILD)/assets/brk_obj_chr.bin $(BUILD)/assets/brk_obj_pal.bin \
		$(BUILD)/assets/brk_grad.bin \
		$(BUILD)/bk_tad_wrapper.o $(BUILD)/bk_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BK_MAP)/symbol_map.json $(BK_ASM)
	$(CA65) -I $(BK_MAP) -I $(VROM) -I $(BK) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/breaker_bg \
		-I engine/features/breaker_obj -I engine/features/rgb_gradient \
		-I vendor/tad -I assets/audio/export \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/breaker.o $(BK)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/breaker.o \
		$(BUILD)/bk_tad_wrapper.o $(BUILD)/bk_tad_data.o
	$(PY) tools/fix_checksum.py $@

breaker: $(BUILD)/breaker.sfc

# ---- hud_game: the text-surface rail ---------------
# The smallest rail in the tree: ONE scene, no transitions, no audio. Its
# subject is bg_text end-to-end — the label printed once under the enter-time
# forced blank, the counter reprinted through the VBlank cell queue only on
# the frames its value changed.
HD      := game/hud_game
HD_MAP  := $(BUILD)/hud
HD_ASM  := $(HD)/main.asm $(wildcard $(HD)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(HD_MAP)/engine_state_globals.inc $(HD_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(HD)/game.toml \
		$(HD)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(HD) --features-dir engine/features \
		--out $(HD_MAP)

$(BUILD)/assets/hud_obj_chr.bin $(BUILD)/assets/hud_obj_pal.bin: \
		tools/gen_hud_assets.py | $(BUILD)
	$(PY) tools/gen_hud_assets.py $(BUILD)/assets

$(BUILD)/hud_game.sfc: $(HD_ASM) $(HD)/hud.inc \
		$(HD_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin \
		$(BUILD)/assets/hud_obj_chr.bin $(BUILD)/assets/hud_obj_pal.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(HD_MAP)/symbol_map.json $(HD_ASM)
	$(CA65) -I $(HD_MAP) -I $(VROM) -I $(HD) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/hud_obj \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/hud_game.o $(HD)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/hud_game.o
	$(PY) tools/fix_checksum.py $@

hud_game: $(BUILD)/hud_game.sfc

# ---- sprite_game: the OBJ-only catch game -
# The oam_sprites ISOLATION rail: no BG feature, no text — two 8x8 sprites
# from ONE shared tile through TWO OBJ palettes, over the backdrop colour.
# Chase the yellow dot with the red player; a catch bumps the score and jumps
# the dot to the next of four preset spots.
SPRG      := game/sprite_game
SPRG_MAP  := $(BUILD)/sprg
SPRG_ASM  := $(SPRG)/main.asm $(wildcard $(SPRG)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

$(SPRG_MAP)/engine_state_globals.inc $(SPRG_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SPRG)/game.toml \
		$(SPRG)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SPRG) --features-dir engine/features \
		--out $(SPRG_MAP)

$(BUILD)/assets/sprg_obj_chr.bin $(BUILD)/assets/sprg_obj_pal.bin: \
		tools/gen_sprite_game_assets.py | $(BUILD)
	$(PY) tools/gen_sprite_game_assets.py $(BUILD)/assets

$(BUILD)/sprite_game.sfc: $(SPRG_ASM) $(SPRG)/sprg.inc \
		$(SPRG_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/sprg_obj_chr.bin $(BUILD)/assets/sprg_obj_pal.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SPRG_MAP)/symbol_map.json $(SPRG_ASM)
	$(CA65) -I $(SPRG_MAP) -I $(VROM) -I $(SPRG) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade \
		-I engine/features/oam_sprites -I engine/features/sprg_obj \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/sprite_game.o $(SPRG)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/sprite_game.o
	$(PY) tools/fix_checksum.py $@

sprite_game: $(BUILD)/sprite_game.sfc

# ---- shmup: the vertical shooter ----------------
# The rail that debuts POOL. Its BG feature (shmup_bg) owns both co-resident
# layers and shares ONE CHR page between them; its OBJ feature
# (shmup_obj) owns the sprites AND the pools they live in.
SH      := game/shmup
SH_MAP  := $(BUILD)/sh
SH_ASM  := $(SH)/main.asm $(wildcard $(SH)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(SH_MAP)/engine_state_globals.inc $(SH_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SH)/game.toml \
		$(SH)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SH) --features-dir engine/features \
		--out $(SH_MAP)

# The art comes from the pack's ORIGINAL PNGs, vendored under
# vendor/art/spaceship_pack — not from a converted .inc blob. See the
# generator's header and the asset-import rule.
$(BUILD)/assets/shm_bg_chr.bin $(BUILD)/assets/shm_bg_pal.bin \
$(BUILD)/assets/shm_obj_chr.bin $(BUILD)/assets/shm_ship_pal.bin \
$(BUILD)/assets/shm_foe_pal.bin $(BUILD)/assets/shm_burst_pal.bin: \
		tools/gen_shmup_assets.py $(wildcard vendor/art/spaceship_pack/*.png) \
		| $(BUILD)
	$(PY) tools/gen_shmup_assets.py $(BUILD)/assets

# --- TAD audio objects (shmup) ---------------------------------------------
# Per-game objects for the same reason room's and breaker's are: the wrapper
# needs THIS game's emitted map for its allocator<->linker bridge asserts.
# Neither is in SH_ASM — the no_literals scope covers hand-authored engine ASM
# only, and these are vendored + generated (assets/audio/README.md).
$(BUILD)/sh_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(SH_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(SH_MAP) -I vendor/tad -o $@ $<

$(BUILD)/sh_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

$(BUILD)/shmup.sfc: $(SH_ASM) $(SH)/shmup.inc \
		$(SH_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin \
		$(BUILD)/assets/shm_bg_chr.bin $(BUILD)/assets/shm_bg_pal.bin \
		$(BUILD)/assets/shm_obj_chr.bin $(BUILD)/assets/shm_ship_pal.bin \
		$(BUILD)/assets/shm_foe_pal.bin $(BUILD)/assets/shm_burst_pal.bin \
		$(BUILD)/sh_tad_wrapper.o $(BUILD)/sh_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SH_MAP)/symbol_map.json $(SH_ASM)
	$(CA65) -I $(SH_MAP) -I $(VROM) -I $(SH) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/shmup_bg \
		-I engine/features/shmup_obj \
		-I vendor/tad -I assets/audio/export \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/shmup.o $(SH)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/shmup.o \
		$(BUILD)/sh_tad_wrapper.o $(BUILD)/sh_tad_data.o
	$(PY) tools/fix_checksum.py $@

shmup: $(BUILD)/shmup.sfc

# ---- platformer: the flagship rail --------------
# The rail that debuts PARALLAX. Its BG feature (platformer_bg) owns BOTH
# co-resident layers -- which is the whole point here, because a
# level layer plus a parallax sky layer is exactly the composition
# F-A measured as refused -- and drives BG2HOFS from a three-entry HDMA
# non-repeat-pause table rather than a 224-entry per-scanline fill.
PL      := game/platformer
PL_MAP  := $(BUILD)/pl
PL_ASM  := $(PL)/main.asm $(wildcard $(PL)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(PL_MAP)/engine_state_globals.inc $(PL_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(PL)/game.toml \
		$(PL)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(PL) --features-dir engine/features \
		--out $(PL_MAP)

# The art is HAND-AUTHORED in the generator, not imported: a converted hero or
# ghost blob is png2snes output whose source PNGs this rail does not carry, so
# a byte conversion would owe a ground-truth render it cannot produce
# (the asset-import rule). See the generator's header.
$(BUILD)/assets/plf_bg_chr.bin $(BUILD)/assets/plf_bg_pal.bin \
$(BUILD)/assets/plf_obj_chr.bin $(BUILD)/assets/plf_hero_pal.bin \
$(BUILD)/assets/plf_ghost_pal.bin $(BUILD)/assets/plf_level.bin \
$(BUILD)/assets/plf_sky.bin $(BUILD)/assets/plf_grad.bin: \
		tools/gen_platformer_assets.py | $(BUILD)
	$(PY) tools/gen_platformer_assets.py $(BUILD)/assets

# --- TAD audio objects (platformer) ---------------------------------------
# Per-game objects for the same reason room's, breaker's and shmup's are: the
# wrapper needs THIS game's emitted map for its allocator<->linker bridge
# asserts. Neither is in PL_ASM -- the no_literals scope covers hand-authored
# engine ASM only, and these are vendored + generated.
$(BUILD)/pl_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(PL_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(PL_MAP) -I vendor/tad -o $@ $<

$(BUILD)/pl_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

$(BUILD)/platformer.sfc: $(PL_ASM) $(PL)/platformer.inc \
		$(PL_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin $(BUILD)/assets/crc16_lut.bin \
		$(BUILD)/assets/plf_bg_chr.bin $(BUILD)/assets/plf_bg_pal.bin \
		$(BUILD)/assets/plf_obj_chr.bin $(BUILD)/assets/plf_hero_pal.bin \
		$(BUILD)/assets/plf_ghost_pal.bin $(BUILD)/assets/plf_level.bin \
		$(BUILD)/assets/plf_sky.bin $(BUILD)/assets/plf_grad.bin \
		$(BUILD)/pl_tad_wrapper.o $(BUILD)/pl_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(PL_MAP)/symbol_map.json $(PL_ASM)
	$(CA65) -I $(PL_MAP) -I $(VROM) -I $(PL) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/save \
		-I engine/features/platformer_bg -I engine/features/platformer_obj \
		-I engine/features/rgb_gradient \
		-I vendor/tad -I assets/audio/export \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/platformer.o $(PL)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/platformer.o \
		$(BUILD)/pl_tad_wrapper.o $(BUILD)/pl_tad_data.o
	$(PY) tools/fix_checksum.py $@

platformer: $(BUILD)/platformer.sfc

# ---- the measurement probes -------------------
# probe_vblank: fresh superforge code — allocator-mapped + no-literals-gated.
$(BUILD)/probe_map/engine_state_probe.inc $(BUILD)/probe_map/symbol_map.json: \
		allocator/substrate.toml vendor/probes/probe_vblank/game.toml \
		vendor/probes/probe_vblank/state.toml \
		vendor/probes/probe_vblank/probe_vblank/feature.toml | $(BUILD)
	$(PY) allocator/allocate.py --game vendor/probes/probe_vblank \
		--out $(BUILD)/probe_map

$(BUILD)/probe_vblank.sfc: vendor/probes/probe_vblank.asm \
		$(BUILD)/probe_map/engine_state_probe.inc \
		$(BUILD)/probe_map/symbol_map.json \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BUILD)/probe_map/symbol_map.json \
		vendor/probes/probe_vblank.asm
	$(CA65) -I $(BUILD)/probe_map -I $(VROM) -o $(BUILD)/probe_vblank.o \
		vendor/probes/probe_vblank.asm
	$(LD65) -C $(VROM)/lorom_32k.cfg -o $@ $(BUILD)/probe_vblank.o

# probe_colmap: DESIGN-REVIEW scaffolding for the col_map work (
# item 2 — the per-query cost must be MEASURED). Not wired into `probes` or
# `measure`: it moves no pin and is not part of the substrate instrument set.
$(BUILD)/colmap_map/engine_state_probe.inc $(BUILD)/colmap_map/symbol_map.json: \
		allocator/substrate.toml vendor/probes/probe_colmap/game.toml \
		vendor/probes/probe_colmap/state.toml \
		vendor/probes/probe_colmap/probe_colmap/feature.toml | $(BUILD)
	$(PY) allocator/allocate.py --game vendor/probes/probe_colmap \
		--out $(BUILD)/colmap_map

$(BUILD)/probe_colmap.sfc: vendor/probes/probe_colmap.asm \
		engine/features/col_map/col_map.asm \
		$(BUILD)/colmap_map/engine_state_probe.inc \
		$(BUILD)/colmap_map/symbol_map.json \
		$(BUILD)/assets/world_map.bin $(BUILD)/assets/col_flags.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BUILD)/colmap_map/symbol_map.json \
		vendor/probes/probe_colmap.asm
	$(CA65) -I $(BUILD)/colmap_map -I $(VROM) \
		-I engine/features/col_map \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/probe_colmap.o vendor/probes/probe_colmap.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/probe_colmap.o
	$(PY) tools/fix_checksum.py $@

probe-colmap: $(BUILD)/probe_colmap.sfc

# probe_pfs: the pfs_stream MECHANISM probe. Proves and
# measures the 2-axis normal-BG 64x64 ring streamer WITHOUT the
# platformer_stream rail, which is what let the two be built in parallel. Like
# probe_colmap it .includes the SHIPPED engine/features/pfs_stream/
# pfs_stream.asm rather than a copy, so what is tested is always the kernel
# that ships. Not wired into `probes` or `measure`: it moves no substrate pin.
#
# Its blobs go to a PROBE-PRIVATE asset dir rather than $(BUILD)/assets. The
# generator is shared with the rail and its outputs are byte-identical either
# way; a private dir just means this target owns one rule of its own and can
# never collide with the rail's assets rule.
PFS_PROBE_ASSETS := $(BUILD)/pfs_probe_assets

$(BUILD)/pfs_map/engine_state_probe.inc $(BUILD)/pfs_map/symbol_map.json: \
		allocator/substrate.toml vendor/probes/probe_pfs/game.toml \
		vendor/probes/probe_pfs/state.toml \
		vendor/probes/probe_pfs/probe_pfs/feature.toml | $(BUILD)
	$(PY) allocator/allocate.py --game vendor/probes/probe_pfs \
		--out $(BUILD)/pfs_map

$(PFS_PROBE_ASSETS)/pfs_flat.bin $(PFS_PROBE_ASSETS)/pfs_flat_row.bin: \
		tools/gen_platformer_stream_assets.py | $(BUILD)
	$(PY) tools/gen_platformer_stream_assets.py $(PFS_PROBE_ASSETS)

$(BUILD)/probe_pfs.sfc: vendor/probes/probe_pfs_stream.asm \
		engine/features/pfs_stream/pfs_stream.asm \
		$(BUILD)/pfs_map/engine_state_probe.inc \
		$(BUILD)/pfs_map/symbol_map.json \
		$(PFS_PROBE_ASSETS)/pfs_flat.bin \
		$(PFS_PROBE_ASSETS)/pfs_flat_row.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BUILD)/pfs_map/symbol_map.json \
		vendor/probes/probe_pfs_stream.asm \
		engine/features/pfs_stream/pfs_stream.asm
	$(CA65) -I $(BUILD)/pfs_map -I $(VROM) \
		-I engine/features/pfs_stream \
		--bin-include-dir $(PFS_PROBE_ASSETS) \
		-o $(BUILD)/probe_pfs.o vendor/probes/probe_pfs_stream.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/probe_pfs.o
	$(PY) tools/fix_checksum.py $@

probe-pfs: $(BUILD)/probe_pfs.sfc

# probe_cpu: the DERIVED instrumented copy of the mini racing reference
# (see make_probe_cpu.py — measures the vendored reference scene).
#
# Its dependencies are VENDORED under vendor/probe_ref (frozen snapshot; see that
# directory's README): `inc/` is flat because ca65 resolves .include by
# basename off -I, while `assets/racing/` keeps its prefix because .incbin
# names that path literally and resolves it against --bin-include-dir.
# NOTE: vendor/probe_ref/lorom_512k.cfg is NOT vendor/rom/lorom_512k.cfg — the
# segment names and SRAM layout differ, and the probe needs this one.
PROBE_REF     := vendor/probe_ref
CPU_PROBE_INC := --bin-include-dir $(PROBE_REF) -I $(PROBE_REF)/inc
CPU_PROBE_CFG := $(PROBE_REF)/lorom_512k.cfg

vendor/probes/probe_cpu_ref.asm: vendor/probes/make_probe_cpu.py \
		$(PROBE_REF)/src/probe_scene_ref.asm
	$(PY) vendor/probes/make_probe_cpu.py

# probe_cpu: the plain instrumented reference — scenarios are driven live
# by the tests via MesenRunner input injection (there is no forced-input
# build variant; this target is the single source of truth for the recipe)
$(BUILD)/probe_cpu.sfc: vendor/probes/probe_cpu_ref.asm | $(BUILD)
	$(CA65) $(CPU_PROBE_INC) \
		-o $(BUILD)/probe_cpu.o vendor/probes/probe_cpu_ref.asm
	$(LD65) -C $(CPU_PROBE_CFG) -o $@ $(BUILD)/probe_cpu.o
	$(PY) -c "f=open('$@','r+b');f.seek(0x7FD7);f.write(b'\x09');f.close()"

$(BUILD)/probe_cpu_step.sfc: vendor/probes/probe_cpu_ref.asm | $(BUILD)
	$(CA65) $(CPU_PROBE_INC) -D CY_STEP=1 \
		-o $(BUILD)/probe_cpu_step.o vendor/probes/probe_cpu_ref.asm
	$(LD65) -C $(CPU_PROBE_CFG) -o $@ $(BUILD)/probe_cpu_step.o
	$(PY) -c "f=open('$@','r+b');f.seek(0x7FD7);f.write(b'\x09');f.close()"

probes: $(BUILD)/probe_vblank.sfc $(BUILD)/probe_cpu.sfc \
	$(BUILD)/probe_cpu_step.sfc

# ---- the collision toy: the ALLOCATOR must refuse this declaration --------
# (the gate's teeth deliverable 5)
#
# `make toy-bad` SUCCEEDS when the allocator refused for the right reason, and
# FAILS otherwise. That is the opposite of what this target did until 2026-07-29
# and the inversion is the point — read on before flipping it back.
#
# The refusal must be for the RIGHT REASON. A bare non-zero exit from the
# allocator is satisfied by any refusal at all — a SchemaError from a malformed
# declaration passes just as well as the collision this gate exists to prove.
# So the recipe greps the diagnostic, as tests/test_toy_boot.py has since
# the collision gate.
#
# WHY THE TARGET IS NOT ITSELF INVERTED ANY MORE. When it failed on every path,
# its exit status carried no information: with the collision DELETED from
# engine/toy_bad/pin_b, `make toy-bad` still exited 2, so `if make toy-bad;
# then error; fi` in CI, the documented `test $? -ne 0` check, and the `if make
# toy-bad; then fail; fi` in tools/setup.sh all reported "refused as designed"
# against an allocator with no teeth at all. Seven consumers, all blind.
#
# The obvious repair — keep failing, but exit 1 for the good case and 3 for the
# bad one, and have consumers check the code — CANNOT WORK: GNU make reports
# ANY recipe failure as its own exit 2 regardless of the code the recipe
# returned (verified: a recipe ending `exit 3` yields `make: *** Error 3` and
# `$? = 2`). Distinct recipe codes are invisible to every consumer of `make`.
#
# So the status has to be a plain success/failure verdict, which forces the
# polarity: success = "the allocator refused, correctly". The decisive property
# is what happens to a consumer nobody updates. Under the old polarity a missed
# consumer FAILS OPEN — it silently passes a toothless gate, which is exactly
# how this shipped. Under this one it FAILS LOUD: an un-updated `if make
# toy-bad; then error; fi` now reports the error on a healthy repo. Noisy beats
# silent for a gate whose entire job is to notice.
#
# TOY_BAD_SRC is overridable so tests can point the real recipe at a planted
# tree (a no-teeth copy, a malformed copy) without editing engine/toy_bad in
# the live working tree — see tests/test_make_gates.py.
TOY_BAD_SRC ?= engine/toy_bad

toy-bad:
	@mkdir -p $(BUILD)
	@$(PY) allocator/allocate.py --game $(TOY_BAD_SRC) --out $(BUILD)/bad \
	    2> $(BUILD)/toy_bad.err; st=$$?; \
	  cat $(BUILD)/toy_bad.err >&2; \
	  if [ $$st -eq 0 ]; then \
	    echo "toy-bad FAILED: the allocator ACCEPTED $(TOY_BAD_SRC) —"; \
	    echo "        the collision gate has no teeth"; exit 1; fi; \
	  grep -q "ALLOCATION FAILED" $(BUILD)/toy_bad.err || { \
	    echo "toy-bad FAILED: refused, but NOT with ALLOCATION FAILED — it"; \
	    echo "        fired for the wrong reason (see $(BUILD)/toy_bad.err)"; \
	    exit 1; }; \
	  grep -q "VRAM overlap" $(BUILD)/toy_bad.err || { \
	    echo "toy-bad FAILED: refused, but not on the VRAM overlap this toy"; \
	    echo "        declares (see $(BUILD)/toy_bad.err)"; exit 1; }; \
	  echo "toy-bad OK: allocator refused as designed (VRAM overlap) —"; \
	  echo "        collision gate intact"

# ---- split_v_fight: the seamless vertical split -----------
# The rail that debuts WINDOW DUAL-CAMERA. Its BG feature (split_v_bg) owns
# BG1+BG2+BG3 and points BOTH camera layers at ONE stage copy; its
# OBJ feature (split_v_obj) owns the two fighters and OBSEL.
SV      := game/split_v_fight
SV_MAP  := $(BUILD)/sv
SV_ASM  := $(SV)/main.asm $(wildcard $(SV)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

$(SV_MAP)/engine_state_globals.inc $(SV_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SV)/game.toml \
		$(SV)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SV) --features-dir engine/features \
		--out $(SV_MAP)

# The stage palette and the fighter CHR come from two art packs — under two
# DIFFERENT grants, only one of which is CC0; per-pack detail in NOTICE —
# vendored under vendor/art/split_v so a bare checkout builds; everything else
# the generator emits is authored. See its header for
# provenance and for why the vendored copies cannot drift silently.
SV_ASSETS := $(BUILD)/assets/sv_stage_chr.bin $(BUILD)/assets/sv_stage_map.bin \
             $(BUILD)/assets/sv_stage_pal.bin $(BUILD)/assets/sv_bevel_chr.bin \
             $(BUILD)/assets/sv_bevel_pal.bin $(BUILD)/assets/sv_knight_chr.bin \
             $(BUILD)/assets/sv_knight_pal_r.bin $(BUILD)/assets/sv_knight_pal_b.bin

$(SV_ASSETS): tools/gen_split_v_assets.py $(wildcard vendor/art/split_v/*.bin) \
		| $(BUILD)
	$(PY) tools/gen_split_v_assets.py $(BUILD)/assets

# ---- m7_dungeon assets ------------------------------------
# The rail's art, ahead of the rail. Everything is AUTHORED (a maze string, a
# palette, three procedural sprites) — nothing is read from a pack, so there is
# no reference fallback here and none is needed on a bare runner.
#
# What vendor/art/m7_dungeon holds instead is a committed reference OUTPUT, as
# an oracle: the generator shares no code with the program that produced those blobs and
# REFUSES to write anything that disagrees with them. It is therefore also a
# gate, not only a build step. See its header and that directory's README.
#
# No rail links these yet; the target exists so `make m7dg-assets` builds and
# checks them, and so the rail work item adds a prerequisite rather than a rule.
M7DG_ASSETS := $(BUILD)/assets/m7dg_map.bin $(BUILD)/assets/m7dg_pal.bin \
               $(BUILD)/assets/m7dg_tilemap.bin \
               $(BUILD)/assets/m7dg_flags.bin \
               $(BUILD)/assets/m7dg_hero_chr.bin \
               $(BUILD)/assets/m7dg_hero_pal.bin \
               $(BUILD)/assets/m7dg_enemy_chr.bin \
               $(BUILD)/assets/m7dg_enemy_pal.bin \
               $(BUILD)/assets/m7dg_win_chr.bin \
               $(BUILD)/assets/m7dg_win_pal.bin

$(M7DG_ASSETS): tools/gen_m7_dungeon_assets.py \
		$(wildcard vendor/art/m7_dungeon/ref_*) | $(BUILD)
	$(PY) tools/gen_m7_dungeon_assets.py $(BUILD)/assets

m7dg-assets: $(M7DG_ASSETS)

# --- TAD audio objects (split_v_fight) -------------------------------------
# Per-game for the same reason room's and shmup's are: the wrapper needs THIS
# game's emitted map for its allocator<->linker bridge asserts.
$(BUILD)/sv_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(SV_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(SV_MAP) -I vendor/tad -o $@ $<

$(BUILD)/sv_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

SV_INC := -I $(SV_MAP) -I $(VROM) -I $(SV) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/input2 -I engine/features/oam_sprites -I engine/features/fade \
          -I engine/features/split_v_bg -I engine/features/split_v_obj \
          -I vendor/tad -I assets/audio/export

$(BUILD)/split_v_fight.sfc: $(SV_ASM) $(SV)/split_v.inc \
		$(SV_MAP)/engine_state_globals.inc $(SV_ASSETS) \
		$(BUILD)/sv_tad_wrapper.o $(BUILD)/sv_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SV_MAP)/symbol_map.json $(SV_ASM)
	$(CA65) $(SV_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_v_fight.o $(SV)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_v_fight.o \
		$(BUILD)/sv_tad_wrapper.o $(BUILD)/sv_tad_data.o
	$(PY) tools/fix_checksum.py $@

split_v_fight: $(BUILD)/split_v_fight.sfc

# ---- m7_dungeon: the rotating Mode 7 floor ----------------
# The rail that debuts STATIC AFFINE Mode 7 (m7_affine, a global feature later
# rails reuse) over a one-DMA interleaved plane (m7dg_floor, scene-scoped).
# The floor renders and turns; sprites, physics and collision grow this same
# scene.
#
# No TAD objects here — `tad_rom` is not in this game's globals, so the link is
# one object.
M7DG      := game/m7_dungeon
M7DG_MAP  := $(BUILD)/m7dg
M7DG_ASM  := $(M7DG)/main.asm $(wildcard $(M7DG)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

$(M7DG_MAP)/engine_state_globals.inc $(M7DG_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(M7DG)/game.toml \
		$(M7DG)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(M7DG) --features-dir engine/features \
		--out $(M7DG_MAP)

# The 256-entry affine matrix table. m7_affine's asset, not the rail's, which is
# why it has its own generator and its own rule — waves 6 and 7 depend on this
# target, not on m7dg-assets.
$(BUILD)/assets/m7_affine_lut.bin: tools/gen_m7_affine_lut.py | $(BUILD)
	$(PY) tools/gen_m7_affine_lut.py $(BUILD)/assets

M7DG_INC := -I $(M7DG_MAP) -I $(VROM) -I $(M7DG) \
            -I engine/features/scene_mgr -I engine/features/input \
            -I engine/features/oam_sprites -I engine/features/fade \
            -I engine/features/m7_affine -I engine/features/m7_project \
            -I engine/features/m7dg_floor -I engine/features/m7dg_obj \
            -I engine/features/col_map

$(BUILD)/m7_dungeon.sfc: $(M7DG_ASM) \
		$(M7DG_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/m7dg_map.bin $(BUILD)/assets/m7dg_pal.bin \
		$(BUILD)/assets/m7dg_tilemap.bin $(BUILD)/assets/m7dg_flags.bin \
		$(BUILD)/assets/m7dg_hero_chr.bin $(BUILD)/assets/m7dg_hero_pal.bin \
		$(BUILD)/assets/m7dg_enemy_chr.bin $(BUILD)/assets/m7dg_enemy_pal.bin \
		$(BUILD)/assets/m7dg_win_chr.bin $(BUILD)/assets/m7dg_win_pal.bin \
		$(BUILD)/assets/m7_affine_lut.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(M7DG_MAP)/symbol_map.json $(M7DG_ASM)
	$(CA65) $(M7DG_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/m7_dungeon.o $(M7DG)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/m7_dungeon.o
	$(PY) tools/fix_checksum.py $@

m7_dungeon: $(BUILD)/m7_dungeon.sfc

# --- the labelled twin: measurement scaffolding, never a shipping artifact ---
# Same sources, same linker config, `-g` on the assembler and `-Ln` on the
# linker. The `cmp` is the whole point: it proves the label file describes the
# binary that actually ships, so tools/measure_m7_project.py can put execution
# breakpoints on routines by NAME instead of on transcribed addresses. A twin
# that drifts from the shipped ROM fails here rather than measuring something
# else and reporting it as fact.
$(BUILD)/m7_dungeon.lbl: $(BUILD)/m7_dungeon.sfc
	$(CA65) $(M7DG_INC) --bin-include-dir $(BUILD)/assets -g \
		-o $(BUILD)/m7_dungeon_dbg.o $(M7DG)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -Ln $@ \
		-o $(BUILD)/m7_dungeon_dbg.sfc $(BUILD)/m7_dungeon_dbg.o
	$(PY) tools/fix_checksum.py $(BUILD)/m7_dungeon_dbg.sfc
	cmp $(BUILD)/m7_dungeon_dbg.sfc $(BUILD)/m7_dungeon.sfc

m7dg-labels: $(BUILD)/m7_dungeon.lbl

# The projection's measured per-frame cost (CLAUDE.md rule 1: measure, never
# estimate). Not part of `make measure`'s pinned budgets — it is a reported
# figure, and the pins it is compared against are read from substrate.toml.
m7dg-measure: $(BUILD)/m7_dungeon.lbl
	$(PY) tools/measure_m7_project.py

# The GAME's measured per-frame cost — collision, patrol, contact, and the rest
# of the tick's routines. Same discipline and the same label twin as above; the
# two together account for the whole tick.
m7dg-measure-logic: $(BUILD)/m7_dungeon.lbl
	$(PY) tools/measure_m7dg_logic.py

# ---- mode7_explore assets ---------------------------------
# The rail's world, ahead of the rail. Everything is AUTHORED — a height field,
# eleven hand-drawn 8x8 textures, a spawn clearing and a demo house — so there
# is no reference fallback here and none is needed on a bare runner. The generator
# was verified byte-identical to independently-produced committed blobs (a different
# program, on a different run) when it landed; it also emits m7x_world.inc, the
# EQUATES the rail's asm binds against, so the world's geometry has one author.
M7X_ASSETS := $(BUILD)/assets/m7x_map.bin $(BUILD)/assets/m7x_seed.bin \
              $(BUILD)/assets/m7x_pal.bin $(BUILD)/assets/m7x_terr.bin \
              $(BUILD)/assets/m7x_obj_chr.bin $(BUILD)/assets/m7x_obj_pal.bin \
              $(BUILD)/assets/m7x_town_chr.bin $(BUILD)/assets/m7x_town_pal.bin \
              $(BUILD)/assets/m7x_world.inc

$(M7X_ASSETS): tools/gen_mode7_explore_assets.py | $(BUILD)
	$(PY) tools/gen_mode7_explore_assets.py $(BUILD)/assets

m7x-assets: $(M7X_ASSETS)

# ---- mode7_explore: the streaming Mode 7 overworld --------
# 512x512 tiles — sixteen times what the Mode 7 window holds — walked on a tile
# grid by an avatar pinned at the affine pivot. The rail reuses m7_affine (at
# heading 0: the identity matrix, so it never rotates), mode7_stream (bound to
# THIS rail's blob through the streamer's binding contract) and col_map (bound to the same
# blob, so what you see and what blocks you are one table).
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is one
# object.
M7X      := game/mode7_explore
M7X_MAP  := $(BUILD)/m7x
M7X_ASM  := $(M7X)/main.asm $(wildcard $(M7X)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

$(M7X_MAP)/engine_state_globals.inc $(M7X_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(M7X)/game.toml \
		$(M7X)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(M7X) --features-dir engine/features \
		--out $(M7X_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(M7X_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(M7X) for the scene.
# m7x_world.inc is emitted into $(BUILD)/assets, so that dir is on the include
# path too — it is the one generated .inc that is not a map.
M7X_INC := -I $(M7X_MAP) -I $(VROM) -I $(M7X) -I $(BUILD)/assets \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/oam_sprites -I engine/features/fade \
           -I engine/features/m7_affine -I engine/features/mode7_stream \
           -I engine/features/col_map -I engine/features/m7x_floor \
           -I engine/features/m7x_obj -I engine/features/m7x_logic \
           -I engine/features/m7x_town -I engine/features/mosaic

$(BUILD)/mode7_explore.sfc: $(M7X_ASM) \
		$(M7X_MAP)/engine_state_globals.inc \
		$(M7X_ASSETS) $(BUILD)/assets/m7_affine_lut.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(M7X_MAP)/symbol_map.json $(M7X_ASM)
	$(CA65) $(M7X_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/mode7_explore.o $(M7X)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/mode7_explore.o
	$(PY) tools/fix_checksum.py $@

mode7_explore: $(BUILD)/mode7_explore.sfc

# ---- platformer_stream assets -----------------------------
# THREE SOURCES, one staging directory, and the split is deliberate.
#
#   GENERATED — the level, twice (column- and row-major), the world-space
#     collision blob, col_map's flag LUT, the dusk COLDATA ramp and the
#     geometry .inc the rail assembles against. Pure integer code, no image
#     input, byte-identical on every run. Its correctness is a byte
#     comparison against independently-produced committed fixtures
#     (tests/test_platformer_stream_assets.py, oracle-gated).
#
#   VENDORED — the 25-tile BG CHR and its 16-word palette. They are quantized
#     from a Four Seasons tileset image that is in neither reference, so there is
#     nothing to regenerate from; vendor/art/platformer_stream/README.md
#     carries the provenance. Staged under this rail's claim names so the
#     .incbin sites read like every other blob's.
#
# SHARED — the hero. The platformer rail already vendored the source PNGs at
#     vendor/art/dungeon_sprites/ and gen_platformer_assets.py already converts
#     them; this rail takes the hero HALF of that 64-tile OBJ sheet (tiles
#     0..31 = 1,024 B) rather than vendoring a second copy of the same art.
#     The slice is 1,024 B off the front because the sheet is laid out
#     hero-then-ghost, which that generator's header states and its
#     PLF_HERO_TILE = 0 / PLF_GHOST_TILE = 32 equates fix.
PFS_ASSETS := $(BUILD)/assets/pfs_flat.bin $(BUILD)/assets/pfs_flat_row.bin \
              $(BUILD)/assets/pfs_col.bin $(BUILD)/assets/pfs_flags.bin \
              $(BUILD)/assets/pfs_grad.bin $(BUILD)/assets/pfs_world.inc \
              $(BUILD)/assets/pfs_chr.bin $(BUILD)/assets/pfs_pal.bin \
              $(BUILD)/assets/pfs_hero_chr.bin $(BUILD)/assets/pfs_hero_pal.bin

# NAMED prerequisites, not $(wildcard ...) — the SH2 rule below records why:
# a wildcard prerequisite evaporates with the files it matches, so a deleted
# vendored blob would leave the staged copy looking up to date forever.
$(PFS_ASSETS): tools/gen_platformer_stream_assets.py \
		vendor/art/platformer_stream/ref_level_chr.bin \
		vendor/art/platformer_stream/ref_level_pal.bin \
		$(BUILD)/assets/plf_obj_chr.bin $(BUILD)/assets/plf_hero_pal.bin \
		| $(BUILD)
	$(PY) tools/gen_platformer_stream_assets.py $(BUILD)/assets
	cp vendor/art/platformer_stream/ref_level_chr.bin \
	   $(BUILD)/assets/pfs_chr.bin
	cp vendor/art/platformer_stream/ref_level_pal.bin \
	   $(BUILD)/assets/pfs_pal.bin
	head -c 1024 $(BUILD)/assets/plf_obj_chr.bin \
	   > $(BUILD)/assets/pfs_hero_chr.bin
	cp $(BUILD)/assets/plf_hero_pal.bin $(BUILD)/assets/pfs_hero_pal.bin

pfs-assets: $(PFS_ASSETS)

# ---- platformer_stream: the two-axis streaming platformer --
# A side-view level four screens wide AND tall, streamed over a 64x64 BG1 ring.
# ONE SCENE — the rail has no title screen by design, so it boots straight into
# gameplay — a title screen would add a scene edge this rail does not teach.
#
# COMPLETE: the ring is armed at scene enter and SLIDES on both axes as the
# follow camera pans, through `pfs_stream`'s staging kernel and its VBlank
# drain in `sm_nmi_hook`.
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is one
# object (mode7_explore's shape).
PFS      := game/platformer_stream
PFS_MAP  := $(BUILD)/pfs
PFS_ASM  := $(PFS)/main.asm $(wildcard $(PFS)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

$(PFS_MAP)/engine_state_globals.inc $(PFS_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(PFS)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(PFS) --features-dir engine/features \
		--out $(PFS_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(PFS_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(PFS) for the scene.
# pfs_world.inc is emitted into $(BUILD)/assets, so that dir is on the include
# path too — it is the one generated .inc that is not a map.
PFS_INC := -I $(PFS_MAP) -I $(VROM) -I $(PFS) -I $(BUILD)/assets \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/oam_sprites -I engine/features/fade \
           -I engine/features/pfs_bg -I engine/features/pfs_stream \
           -I engine/features/pfs_logic \
           -I engine/features/col_map -I engine/features/rgb_gradient

$(BUILD)/platformer_stream.sfc: $(PFS_ASM) \
		$(PFS_MAP)/engine_state_globals.inc $(PFS_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(PFS_MAP)/symbol_map.json $(PFS_ASM)
	$(CA65) $(PFS_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/platformer_stream.o $(PFS)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/platformer_stream.o
	$(PY) tools/fix_checksum.py $@

platformer_stream: $(BUILD)/platformer_stream.sfc

# ---- scroller: the BG pipeline alone --------------
# A green checkerboard on BG1, the d-pad scrolling it in all four directions,
# and a red sprite pinned at screen centre so the world appears to slide
# beneath it.
#
# ONE SCENE, no edges — this rail needs no scene machine at all. The
# smallest rail in the tree: four blobs totalling 160 B, two tiles, one sprite.
#
# NO TILEMAP BLOB, which is the point. The 32x32 map is BUILT at scene enter by
# scroller_bg's `(col ^ row) & 1` loop, because that loop is what the rail
# teaches (scroller_rom/feature.toml carries the argument).
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is one
# object (platformer_stream's shape).
SCR      := game/scroller
SCR_MAP  := $(BUILD)/scr
SCR_ASM  := $(SCR)/main.asm $(wildcard $(SCR)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

SCR_ASSETS := $(BUILD)/assets/scr_bg_chr.bin $(BUILD)/assets/scr_bg_pal.bin \
              $(BUILD)/assets/scr_obj_chr.bin $(BUILD)/assets/scr_obj_pal.bin

$(SCR_ASSETS): tools/gen_scroller_assets.py | $(BUILD)
	$(PY) tools/gen_scroller_assets.py $(BUILD)/assets

$(SCR_MAP)/engine_state_globals.inc $(SCR_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SCR)/game.toml \
		$(SCR)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SCR) --features-dir engine/features \
		--out $(SCR_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(SCR_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(SCR) for the scene
# and scroller.inc.
SCR_INC := -I $(SCR_MAP) -I $(VROM) -I $(SCR) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/oam_sprites -I engine/features/fade \
           -I engine/features/scroller_bg -I engine/features/scroller_obj

$(BUILD)/scroller.sfc: $(SCR_ASM) $(SCR)/scroller.inc \
		$(SCR_MAP)/engine_state_globals.inc $(SCR_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SCR_MAP)/symbol_map.json $(SCR_ASM)
	$(CA65) $(SCR_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/scroller.o $(SCR)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/scroller.o
	$(PY) tools/fix_checksum.py $@

scroller: $(BUILD)/scroller.sfc

# ---- camera_follow: the camera/world-space split --
# A red player moved with the d-pad through a 512x448 world over a repeating
# checkerboard; the camera centres the player and CLAMPS at the world edges,
# where the player walks toward the screen edge instead.
#
# ONE SCENE, no edges — this rail needs no scene machine at all. The same
# blob set as scroller (four blobs, 160 B, no tilemap — the 32x32 map is
# BUILT at scene enter, and here the 256 px map repeating under a 512x448
# world is itself the rail's third lesson).
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is
# one object (scroller's shape).
CF       := game/camera_follow
CF_MAP   := $(BUILD)/cf
CF_ASM   := $(CF)/main.asm $(wildcard $(CF)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

CF_ASSETS := $(BUILD)/assets/cf_bg_chr.bin $(BUILD)/assets/cf_bg_pal.bin \
             $(BUILD)/assets/cf_obj_chr.bin $(BUILD)/assets/cf_obj_pal.bin

$(CF_ASSETS): tools/gen_cf_assets.py | $(BUILD)
	$(PY) tools/gen_cf_assets.py $(BUILD)/assets

$(CF_MAP)/engine_state_globals.inc $(CF_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(CF)/game.toml \
		$(CF)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(CF) --features-dir engine/features \
		--out $(CF_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(CF_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(CF) for the scene
# and cf.inc.
CF_INC := -I $(CF_MAP) -I $(VROM) -I $(CF) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/oam_sprites -I engine/features/fade \
          -I engine/features/cf_bg -I engine/features/cf_obj

$(BUILD)/camera_follow.sfc: $(CF_ASM) $(CF)/cf.inc \
		$(CF_MAP)/engine_state_globals.inc $(CF_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(CF_MAP)/symbol_map.json $(CF_ASM)
	$(CA65) $(CF_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/camera_follow.o $(CF)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/camera_follow.o
	$(PY) tools/fix_checksum.py $@

camera_follow: $(BUILD)/camera_follow.sfc
# ---- maze: col_map against a hand-built map -------
# A red player walks a grey walled room (border + two interior walls) with
# the canonical per-axis move-check: tentative position, probe, keep the axis
# only if clear — slide, never stick, never tunnel.
#
# ONE SCENE, no edges. The load-bearing blob is mz_room: a 32x32 byte tile-id
# map that maze_bg RENDERS to the BG1 tilemap at enter AND col_map binds as
# its world, so the walls drawn and the walls probed are one byte
# (maze_rom/feature.toml carries the argument).
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is
# one object (scroller's shape).
MZE      := game/maze
MZE_MAP  := $(BUILD)/maze
MZE_ASM  := $(MZE)/main.asm $(wildcard $(MZE)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

MZE_ASSETS := $(BUILD)/assets/mz_room.bin $(BUILD)/assets/mz_flags.bin \
              $(BUILD)/assets/mz_bg_chr.bin $(BUILD)/assets/mz_bg_pal.bin \
              $(BUILD)/assets/mz_obj_chr.bin $(BUILD)/assets/mz_obj_pal.bin

$(MZE_ASSETS): tools/gen_maze_assets.py | $(BUILD)
	$(PY) tools/gen_maze_assets.py $(BUILD)/assets

$(MZE_MAP)/engine_state_globals.inc $(MZE_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(MZE)/game.toml \
		$(MZE)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(MZE) --features-dir engine/features \
		--out $(MZE_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(MZE_MAP)
# for the emitted maps, $(VROM) for the header/init/reset and $(MZE) for the
# scene and maze.inc.
MZE_INC := -I $(MZE_MAP) -I $(VROM) -I $(MZE) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/oam_sprites -I engine/features/fade \
           -I engine/features/maze_bg -I engine/features/maze_obj \
           -I engine/features/col_map

$(BUILD)/maze.sfc: $(MZE_ASM) $(MZE)/maze.inc \
		$(MZE_MAP)/engine_state_globals.inc $(MZE_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(MZE_MAP)/symbol_map.json $(MZE_ASM)
	$(CA65) $(MZE_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/maze.o $(MZE)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/maze.o
	$(PY) tools/fix_checksum.py $@

maze: $(BUILD)/maze.sfc
# ---- jumper: jump physics --------------------------------
# "SKY HOPPER": a red player with gravity over grey terrain — run with the
# d-pad, jump with A; ground, three platforms, an overhang to bonk on.
#
# ONE SCENE, no edges. The rail's one structural addition to the keystone
# pattern: the 32x32 world is ONE ROM blob (jr_world) — jumper_bg builds the
# display tilemap from it at enter, col_map probes it for collision — so the
# drawn terrain and the solid terrain agree by construction.
#
# No TAD objects — `tad_rom` is not in this game's globals (scroller's shape).
JR       := game/jumper
JR_MAP   := $(BUILD)/jr
JR_ASM   := $(JR)/main.asm $(wildcard $(JR)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

JR_ASSETS := $(BUILD)/assets/jr_bg_chr.bin $(BUILD)/assets/jr_bg_pal.bin \
             $(BUILD)/assets/jr_obj_chr.bin $(BUILD)/assets/jr_obj_pal.bin \
             $(BUILD)/assets/jr_world.bin $(BUILD)/assets/jr_flags.bin

$(JR_ASSETS): tools/gen_jumper_assets.py | $(BUILD)
	$(PY) tools/gen_jumper_assets.py $(BUILD)/assets

$(JR_MAP)/engine_state_globals.inc $(JR_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(JR)/game.toml \
		$(JR)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(JR) --features-dir engine/features \
		--out $(JR_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(JR_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(JR) for the scene
# and jumper.inc.
JR_INC := -I $(JR_MAP) -I $(VROM) -I $(JR) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/oam_sprites -I engine/features/fade \
          -I engine/features/jumper_bg -I engine/features/jumper_obj \
          -I engine/features/col_map

$(BUILD)/jumper.sfc: $(JR_ASM) $(JR)/jumper.inc \
		$(JR_MAP)/engine_state_globals.inc $(JR_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(JR_MAP)/symbol_map.json $(JR_ASM)
	$(CA65) $(JR_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/jumper.o $(JR)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/jumper.o
	$(PY) tools/fix_checksum.py $@

jumper: $(BUILD)/jumper.sfc
# ---- patrol: the composition reference ----
# Two magenta enemies pace their beats — one on the ground between two low
# walls, one on a floating platform turning at its ledges — while a red
# player runs and jumps through. Contact knocks the player back to the spawn
# and ticks a "HITS" counter on BG3.
#
# THE LEVEL IS ONE BLOB WITH TWO CONSUMERS, maze's shape: pat_map.bin is
# rendered to the BG1 tilemap by patrol_bg at enter AND bound as col_map's
# CM_WORLD_BLOB by the play scene — the picture and the collision cannot
# drift. The four level-build loops live in tools/gen_patrol_assets.py.
#
# No TAD objects — no audio in this game's globals, so the link is one object.
PAT      := game/patrol
PAT_MAP  := $(BUILD)/pat
PAT_ASM  := $(PAT)/main.asm $(wildcard $(PAT)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

PAT_ASSETS := $(BUILD)/assets/pat_bg_chr.bin $(BUILD)/assets/pat_bg_pal.bin \
              $(BUILD)/assets/pat_obj_chr.bin $(BUILD)/assets/pat_obj_pal.bin \
              $(BUILD)/assets/pat_map.bin $(BUILD)/assets/pat_flags.bin

$(PAT_ASSETS): tools/gen_patrol_assets.py | $(BUILD)
	$(PY) tools/gen_patrol_assets.py $(BUILD)/assets

$(PAT_MAP)/engine_state_globals.inc $(PAT_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(PAT)/game.toml \
		$(PAT)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(PAT) --features-dir engine/features \
		--out $(PAT_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(PAT_MAP)
# for the emitted maps, $(VROM) for the header/init/reset and $(PAT) for the
# scene and patrol.inc.
PAT_INC := -I $(PAT_MAP) -I $(VROM) -I $(PAT) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/fade -I engine/features/bg_text \
           -I engine/features/oam_sprites -I engine/features/col_map \
           -I engine/features/patrol_bg -I engine/features/patrol_obj

$(BUILD)/patrol.sfc: $(PAT_ASM) $(PAT)/patrol.inc \
		$(PAT_MAP)/engine_state_globals.inc $(PAT_ASSETS) \
		$(BUILD)/assets/font_2bpp.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(PAT_MAP)/symbol_map.json $(PAT_ASM)
	$(CA65) $(PAT_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/patrol.o $(PAT)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/patrol.o
	$(PY) tools/fix_checksum.py $@

patrol: $(BUILD)/patrol.sfc
# ---- stomper: enemy resolution on jumper physics ---
# Two magenta patrollers over a grey arena; land on one to defeat it (culled
# sprite, ~17 px bounce), any other contact knocks back to spawn; "FOES"
# ticks down per stomp and CLEAR prints when both are gone.
#
# THE WORLD IS ONE BLOB, twice consumed: stomper_bg renders st_world.bin to
# the BG1 tilemap at enter and the scene's col_map binding probes the same
# bytes — display and collision cannot disagree.
ST      := game/stomper
ST_MAP  := $(BUILD)/st
ST_ASM  := $(ST)/main.asm $(wildcard $(ST)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

ST_ASSETS := $(BUILD)/assets/st_world.bin $(BUILD)/assets/st_flags.bin \
             $(BUILD)/assets/st_bg_chr.bin $(BUILD)/assets/st_bg_pal.bin \
             $(BUILD)/assets/st_obj_chr.bin $(BUILD)/assets/st_obj_pal.bin

$(ST_ASSETS): tools/gen_stomper_assets.py | $(BUILD)
	$(PY) tools/gen_stomper_assets.py $(BUILD)/assets

$(ST_MAP)/engine_state_globals.inc $(ST_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(ST)/game.toml \
		$(ST)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(ST) --features-dir engine/features \
		--out $(ST_MAP)

$(BUILD)/stomper.sfc: $(ST_ASM) $(ST)/stomper.inc \
		$(ST_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin $(ST_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(ST_MAP)/symbol_map.json $(ST_ASM)
	$(CA65) -I $(ST_MAP) -I $(VROM) -I $(ST) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites -I engine/features/col_map \
		-I engine/features/stomper_bg -I engine/features/stomper_obj \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/stomper.o $(ST)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/stomper.o
	$(PY) tools/fix_checksum.py $@

stomper: $(BUILD)/stomper.sfc
# ---- scroll_run: the page-seam world --------------------
# 512px world = two 256px BG pages on the hardware 64x32 tilemap. The level,
# the flag table and all four art blobs come from tools/gen_sr_assets.py; the
# display tilemap is BUILT from the sr_world blob at scene enter (both pages),
# so what col_map probes and what BG1 shows derive from one source.
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is
# one object (scroller's shape).
SR       := game/scroll_run
SR_MAP   := $(BUILD)/sr
SR_ASM   := $(SR)/main.asm $(wildcard $(SR)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

SR_ASSETS := $(BUILD)/assets/sr_bg_chr.bin $(BUILD)/assets/sr_bg_pal.bin \
             $(BUILD)/assets/sr_obj_chr.bin $(BUILD)/assets/sr_obj_pal.bin \
             $(BUILD)/assets/sr_world.bin $(BUILD)/assets/sr_flags.bin

$(SR_ASSETS): tools/gen_sr_assets.py | $(BUILD)
	$(PY) tools/gen_sr_assets.py $(BUILD)/assets

$(SR_MAP)/engine_state_globals.inc $(SR_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SR)/game.toml \
		$(SR)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SR) --features-dir engine/features \
		--out $(SR_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(SR_MAP)
# for the emitted maps, $(VROM) for the header/init/reset and $(SR) for the
# scene and scroll_run.inc. bg_text + col_map are scene features; the font
# blob comes from vendor/font (font_rom's claim, hud_game's shape).
SR_INC := -I $(SR_MAP) -I $(VROM) -I $(SR) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/oam_sprites -I engine/features/fade \
          -I engine/features/bg_text -I engine/features/col_map \
          -I engine/features/sr_bg -I engine/features/sr_obj

$(BUILD)/scroll_run.sfc: $(SR_ASM) $(SR)/scroll_run.inc \
		$(SR_MAP)/engine_state_globals.inc $(SR_ASSETS) \
		$(BUILD)/assets/font_2bpp.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SR_MAP)/symbol_map.json $(SR_ASM)
	$(CA65) $(SR_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/scroll_run.o $(SR)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/scroll_run.o
	$(PY) tools/fix_checksum.py $@

scroll_run: $(BUILD)/scroll_run.sfc

# ---- brawler: the SECOND OBJ NAME TABLE -----------
# Arthur Pendragon versus Mordred: two animated multi-frame 32x32 knights on a
# terrain floor, HP / FOE / WINS text HUD, four-way lane movement with H-flip
# facing, and a timed swing hitbox.
#
# THE ONE RAIL THAT TOUCHES AN ALLOCATOR `partial`.
# §4.5b): Arthur fills OBJ name table 0 (tiles 0..255) exactly, so Mordred has
# to live at the second base, reached through OBSEL's name-select gap and the
# OAM attribute's 9th tile bit. Two obj vram claims; the gap between the two
# emitted bases is re-derived and ASSERTED in brawler_obj.asm.
#
# The art is the ORIGINAL PACK PNGs (vendor/art/camelot, CC0;
# vendor/art/four_seasons_tileset, a permissive non-CC0 grant) converted by
# tools/gen_brawler_assets.py — not a derived .inc blob.
BR      := game/brawler
BR_MAP  := $(BUILD)/br
BR_ASM  := $(BR)/main.asm $(wildcard $(BR)/scenes/*.asm) \
           $(wildcard engine/features/*/*.asm)

BR_ASSETS := $(BUILD)/assets/br_art_chr.bin $(BUILD)/assets/br_art_pal.bin \
             $(BUILD)/assets/br_mor_chr.bin $(BUILD)/assets/br_mor_pal.bin \
             $(BUILD)/assets/br_bg_chr.bin $(BUILD)/assets/br_bg_pal.bin \
             $(BUILD)/assets/br_bg_map.bin $(BUILD)/assets/br_anim.bin \
             $(BUILD)/assets/br_anim_meta.bin

$(BR_ASSETS): tools/gen_brawler_assets.py \
		vendor/art/camelot/arthurPendragon_.png \
		vendor/art/camelot/mordred_.png \
		vendor/art/four_seasons_tileset/four-seasons-tileset.png | $(BUILD)
	$(PY) tools/gen_brawler_assets.py $(BUILD)/assets

$(BR_MAP)/engine_state_globals.inc $(BR_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(BR)/game.toml \
		$(BR)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(BR) --features-dir engine/features \
		--out $(BR_MAP)

$(BUILD)/brawler.sfc: $(BR_ASM) $(BR)/brawler.inc \
		$(BR_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/font_2bpp.bin $(BR_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BR_MAP)/symbol_map.json $(BR_ASM)
	$(CA65) -I $(BR_MAP) -I $(VROM) -I $(BR) \
		-I engine/features/scene_mgr -I engine/features/input \
		-I engine/features/fade -I engine/features/bg_text \
		-I engine/features/oam_sprites \
		-I engine/features/brawler_bg -I engine/features/brawler_obj \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/brawler.o $(BR)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/brawler.o
	$(PY) tools/fix_checksum.py $@

brawler: $(BUILD)/brawler.sfc

# ---- split_v_seamtrial: THE SEAM IN ISOLATION -----------
# One stage, two cameras at mid +- spread, an always-on centre window, and a
# bevelled BG3 bar whose band ramps from zero width. `spread` sweeps a
# 128-frame triangle with no input, so every proof frame is a determined state
# that `Machine(rom).advance(N)` lands on exactly.
#
# ZERO NEW ENGINE FEATURES: the mechanism is split_v_bg, shipped for
# split_v_fight. This rail supplies a different DIRECTOR and nothing
# else. Its art is AUTHORED from the source's own equates by
# tools/gen_seamtrial_assets.py -- no pack, no trace, no external read, so the
# rail has no oracle-gated test and builds identically on a bare runner.
#
# NO -D VARIANTS, deliberately: split_v_fight needs five of them to freeze a
# swept variable for a race-free proof; a frame-driven triangle is already
# frozen at every absolute frame.
SVS      := game/split_v_seamtrial
SVS_MAP  := $(BUILD)/svs
SVS_ASM  := $(SVS)/main.asm $(wildcard $(SVS)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

SVS_ASSETS := $(BUILD)/assets/svs_stage_chr.bin \
              $(BUILD)/assets/svs_stage_map.bin \
              $(BUILD)/assets/svs_stage_pal.bin \
              $(BUILD)/assets/svs_bevel_chr.bin \
              $(BUILD)/assets/svs_bevel_pal.bin \
              $(BUILD)/assets/svs_pad2048.bin \
              $(BUILD)/assets/svs_pad32.bin

$(SVS_ASSETS): tools/gen_seamtrial_assets.py | $(BUILD)
	$(PY) tools/gen_seamtrial_assets.py $(BUILD)/assets

$(SVS_MAP)/engine_state_globals.inc $(SVS_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SVS)/game.toml \
		$(SVS)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SVS) --features-dir engine/features \
		--out $(SVS_MAP)

$(BUILD)/split_v_seamtrial.sfc: $(SVS_ASM) $(SVS)/seamtrial.inc \
		$(SVS_MAP)/engine_state_globals.inc $(SVS_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SVS_MAP)/symbol_map.json $(SVS_ASM)
	$(CA65) -I $(SVS_MAP) -I $(VROM) -I $(SVS) \
		-I engine/features/scene_mgr -I engine/features/fade \
		-I engine/features/split_v_bg \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_v_seamtrial.o $(SVS)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_v_seamtrial.o
	$(PY) tools/fix_checksum.py $@

split_v_seamtrial: $(BUILD)/split_v_seamtrial.sfc
# ---- split_h_persp assets -------------------------------
# The rail's art. Everything is AUTHORED (a checker algebra, two hyperbolic
# perspective ramps, five colours) — nothing is read from a pack, so there is
# no reference fallback here and none is needed on a bare runner.
#
# What vendor/art holds instead is a committed reference OUTPUT, as an oracle: the generator
# shares no code with the programs that produced those artefacts and REFUSES to
# write anything that disagrees with them. It is therefore a gate, not only a
# build step. The MAP oracle is the neighbouring rail's file on purpose — the
# reference ships byte-identical checker_map.bin under split_h_2p_demo and
# split_h_persp_demo — and vendor/art/split_h_persp/README.md records why it is
# named rather than copied.
SHP_ASSETS := $(BUILD)/assets/shp_map.bin $(BUILD)/assets/shp_pal.bin \
              $(BUILD)/assets/shp_poseA_ab.bin $(BUILD)/assets/shp_poseA_cd.bin \
              $(BUILD)/assets/shp_poseB_ab.bin $(BUILD)/assets/shp_poseB_cd.bin

# NAMED, not $(wildcard ...), as on the sh2 generator. A wildcard
# prerequisite EVAPORATES with the files it matches: delete the oracle and make
# stops depending on it, so already-built blobs stay "up to date" and the gate
# never runs again. Named explicitly, a missing reference is "No rule to make
# target ..." and the build stops. (The generator refuses an absent oracle too
# — that covers the case where it does run; this covers the case where make
# decides it need not.)
SHP_ORACLE := vendor/art/split_h_2p/ref_checker_map.bin \
              vendor/art/split_h_persp/ref_palette.inc

$(SHP_ASSETS): tools/gen_split_h_persp_assets.py $(SHP_ORACLE) | $(BUILD)
	$(PY) tools/gen_split_h_persp_assets.py $(BUILD)/assets

shp-assets: $(SHP_ASSETS)

# ---- split_h_persp_demo: two PERSPECTIVE cameras --------
# SIX active HDMA channels over one scene: a per-band INDIRECT matrix pair
# streaming that band's own ROM pose set through M7A-M7D in REPEAT mode (which
# is what makes each band a per-scanline trapezoid), and a per-band DIRECT
# origin pair giving each band its own M7X/M7Y + M7HOFS/M7VOFS. The FLOOR
# drives itself off the PPU; the per-frame CPU is four stores in VBlank.
SHP       := game/split_h_persp_demo
SHP_MAP   := $(BUILD)/shp
SHP_ASM   := $(SHP)/main.asm $(wildcard $(SHP)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

$(SHP_MAP)/engine_state_globals.inc $(SHP_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SHP)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SHP) --features-dir engine/features \
		--out $(SHP_MAP)

SHP_INC := -I $(SHP_MAP) -I $(VROM) -I $(SHP) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/input \
           -I engine/features/shp_floor -I engine/features/shp_cam

$(BUILD)/split_h_persp_demo.sfc: $(SHP_ASM) \
		$(SHP_MAP)/engine_state_globals.inc $(SHP_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SHP_MAP)/symbol_map.json $(SHP_ASM)
	$(CA65) $(SHP_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_persp_demo.o $(SHP)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_persp_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_persp_demo: $(BUILD)/split_h_persp_demo.sfc

# The CONTROLLER-FREE PILOT ROM. This one RESTORES the reference
# DEFAULT rather than porting a `-D`: that template ships eleven variants and
# no autodemo because it reads no pad at all — camera A auto-rotates and
# camera B zoom-loops off its frame counter. The shipping ROM makes both
# pad-driven so the two axes can be stopped and walked back; this gives the
# autonomous pair back for
# piloting. `sh2_autocam`'s shape exactly. Inside `.ifdef SHP_AUTODEMO`, no
# new state, so the shipping ROM above is byte-identical either way.
shp-autodemo: $(BUILD)/split_h_persp_demo.sfc
	bash tools/build_shp_autodemo.sh

# ---- racer: THE CHANNEL-PRESSURE RAIL --
# SEVEN of the eight channels over one scene: split_band's BGMODE + indirect
# TM, mode7_persp's two indirect matrix channels, and rc_grad's three indirect
# COLDATA planes — with oam_sprites and mode7_stream time-sharing two of those
# numbers in the VBlank phase. is the ledger, including the
# synthetic probe that measures where the wall actually is.
RC        := game/racer
RC_MAP    := $(BUILD)/rc
RC_ASM    := $(RC)/main.asm $(wildcard $(RC)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
RC_ASSETS := $(BUILD)/assets/racer_kart_chr.bin \
             $(BUILD)/assets/racer_kart_pal.bin \
             $(BUILD)/assets/racer_sky_keys.bin \
             $(RC_MAP)/racer_move.inc

$(RC_ASSETS): tools/gen_racer_assets.py tools/gen_move_lut.py \
		tools/gen_m7_assets.py | $(BUILD)
	$(PY) tools/gen_racer_assets.py $(BUILD)/assets $(RC_MAP)

$(RC_MAP)/engine_state_globals.inc $(RC_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(RC)/game.toml \
		$(RC)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(RC) --features-dir engine/features \
		--out $(RC_MAP)

# TAD audio objects (racer): separate compilation units, per the room rule —
# tad-audio.s owns its own .bss/.zeropage layout and the generated export owns
# AUDIO_DATA0. Neither is in RC_ASM: the no_literals scope covers hand-authored
# engine ASM only, and these are vendored + generated.
$(BUILD)/rc_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(RC_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(RC_MAP) -I vendor/tad -o $@ $<

$(BUILD)/rc_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

RC_INC := -I $(RC_MAP) -I $(VROM) -I $(RC) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/fade -I engine/features/mode7_floor \
          -I engine/features/split_band -I engine/features/mode7_persp \
          -I engine/features/mode7_stream -I engine/features/oam_sprites \
          -I engine/features/rc_grad -I engine/features/rc_kart \
          -I engine/features/rc_logic -I engine/features/sky_band \
          -I engine/features/col_map \
          -I vendor/tad -I assets/audio/export

# $(RC)/world.inc: NAMED here for the reason microzero names its own at :115 —
# it is an assembly INPUT that is not an .asm, so nothing else in this rule's
# prerequisites covers it. It was MISSING, and racer was the tree's only
# instance (a census of all 20 rails: 18 NAMED, 1 wildcard, this one
# absent). Measured before the fix: `touch $(RC)/world.inc && make -q racer`
# exited 0 — make believed a stale racer.sfc was up to date.
$(BUILD)/racer.sfc: $(RC_ASM) $(RC)/world.inc \
		$(RC_MAP)/engine_state_globals.inc $(RC_ASSETS) \
		$(BUILD)/assets/world_map.bin $(BUILD)/assets/poses_ab.bin \
		$(BUILD)/assets/col_flags.bin $(BUILD)/assets/floor_tiles.bin \
		$(BUILD)/assets/sky_chr.bin \
		$(BUILD)/rc_tad_wrapper.o $(BUILD)/rc_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(RC_MAP)/symbol_map.json $(RC_ASM)
	$(CA65) $(RC_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/racer.o $(RC)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/racer.o \
		$(BUILD)/rc_tad_wrapper.o $(BUILD)/rc_tad_data.o
	$(PY) tools/fix_checksum.py $@

racer: $(BUILD)/racer.sfc

# ---- mode7_chamber assets: the four-effect rail ----------------------------
# The rail's art and its two matrix columns. The floor is AUTHORED from the
# design rule (a two-tone ashlar checker with mortar relief and full-width
# brass ribs) rather than converted from a PNG, and the generator REFUSES to
# emit anything that disagrees with the vendored reference oracles — so it is a
# gate, not only a build step. See its header and vendor/art/mode7_chamber's
# README.
#
# NAMED, not $(wildcard ...), as on the sh2 generator. A wildcard
# prerequisite EVAPORATES with the files it matches: delete the oracle and make
# stops depending on it, so already-built blobs stay "up to date" and the gate
# never runs again. Named explicitly, a missing reference is "No rule to make
# target ..." and the build stops.
M7C_ASSETS := $(BUILD)/assets/m7c_map.bin $(BUILD)/assets/m7c_pal.bin \
              $(BUILD)/assets/bow_a.bin $(BUILD)/assets/persp_d.bin \
              $(BUILD)/assets/m7c_vign.bin

M7C_ORACLE := vendor/art/mode7_chamber/ref_chamber_map.bin \
              vendor/art/mode7_chamber/ref_chamber_palette.inc \
              vendor/art/mode7_chamber/ref_chamber_tables.inc

$(M7C_ASSETS): tools/gen_chamber_assets.py $(M7C_ORACLE) | $(BUILD)
	$(PY) tools/gen_chamber_assets.py $(BUILD)/assets

m7c-assets: $(M7C_ASSETS)

# ---- mode7_chamber: FOUR EFFECTS ON ONE PLANE -------
# SEVEN of the eight channels over one scene: m7_barrel's two INDIRECT mode-2
# matrix columns (M7A carries a raised-cosine BOW, M7D the perspective
# hyperbola), split_band's BGMODE + indirect TM at scanline 32, and
# rgb_gradient's three indirect COLDATA planes. One spare. The per-frame CPU is
# one roll kernel on the main thread and two commits in VBlank; nothing rebuilds
# a matrix, because there is no solve to rebuild.
M7C       := game/mode7_chamber
M7C_MAP   := $(BUILD)/m7c
M7C_ASM   := $(M7C)/main.asm $(wildcard $(M7C)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
# world.inc is an INPUT to the assembly and not an .asm, so it is a
# prerequisite here and NOT in the no_literals file list (which is the reg
# ownership pass's scope — a file of equates has no write sites). Without this
# line, editing the seam or a band byte leaves `make` a no-op and the ROM
# stale: found by tools/plants/mode7_chamber.py, whose seam plants both
# reported PLANT-DID-NOT-REACH-ARTIFACT until it was added.
#
# NAMED, not $(wildcard $(M7C)/*.inc). A wildcard prerequisite
# EVAPORATES with the files it matches, which is the same argument the
# SH2_ORACLE block makes 40 lines up; 18 of the tree's 20 rails name theirs and
# this one was the only wildcard.

$(M7C_MAP)/engine_state_globals.inc $(M7C_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(M7C)/game.toml \
		$(M7C)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(M7C) --features-dir engine/features \
		--out $(M7C_MAP)

M7C_INC := -I $(M7C_MAP) -I $(VROM) -I $(M7C) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/input \
           -I engine/features/m7c_floor -I engine/features/m7_barrel \
           -I engine/features/split_band -I engine/features/rgb_gradient \
           -I engine/features/m7c_roll

$(BUILD)/mode7_chamber.sfc: $(M7C_ASM) $(M7C)/world.inc \
		$(M7C_MAP)/engine_state_globals.inc $(M7C_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(M7C_MAP)/symbol_map.json $(M7C_ASM)
	$(CA65) $(M7C_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/mode7_chamber.o $(M7C)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/mode7_chamber.o
	$(PY) tools/fix_checksum.py $@

mode7_chamber: $(BUILD)/mode7_chamber.sfc
# ---- railshooter: THE POOL DEBUT --
# An on-rails forward shooter on the Mode-7 perspective floor: the grid rushes
# at a constant speed, six pooled hazards approach out of the horizon through
# four pre-drawn size tiers, four pooled bullets recede toward it, and the
# obstacle OAM order is re-derived from DEPTH every frame.
#
# The rail debuts `pool` — the mechanism four templates share (this one,
# m7_oshoot, boss, boss_saucer). Its plane is its OWN 32 KB blob rather than
# microzero's 256 KB circuit, so the whole image is a third of
# the window.
#
# The POSES are microzero's shared pair: this rail's seam is 44, the same
# 224 - HUD_LINES the pose blob is generated at, so there is nothing to
# regenerate and nothing to move aside.
RS        := game/railshooter
RS_MAP    := $(BUILD)/rs
RS_ASM    := $(RS)/main.asm $(wildcard $(RS)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
RS_ASSETS := $(BUILD)/assets/rs_map.bin $(BUILD)/assets/rs_floor_pal.bin \
             $(BUILD)/assets/rs_obj_chr.bin $(BUILD)/assets/rs_obj_pal.bin \
             $(BUILD)/assets/rs_proj_scan.bin $(BUILD)/assets/rs_proj_scale.bin \
             $(BUILD)/assets/rs_path.bin

$(RS_ASSETS): tools/gen_railshooter_assets.py | $(BUILD)
	$(PY) tools/gen_railshooter_assets.py $(BUILD)/assets

$(RS_MAP)/engine_state_globals.inc $(RS_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(RS)/game.toml \
		$(RS)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(RS) --features-dir engine/features \
		--out $(RS_MAP)

RS_INC := -I $(RS_MAP) -I $(VROM) -I $(RS) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/fade -I engine/features/pool \
          -I engine/features/split_band -I engine/features/oam_sprites \
          -I engine/features/mode7_persp -I engine/features/rs_floor \
          -I engine/features/sky_band -I engine/features/rs_obj \
          -I engine/features/rs_logic

$(BUILD)/railshooter.sfc: $(RS_ASM) $(RS)/railshooter.inc \
		$(RS_MAP)/engine_state_globals.inc $(RS_ASSETS) \
		$(BUILD)/assets/poses_ab.bin $(BUILD)/assets/poses_cd.bin \
		$(BUILD)/assets/sky_chr.bin $(BUILD)/assets/sky_map.bin \
		$(BUILD)/assets/sky_pal.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(RS_MAP)/symbol_map.json $(RS_ASM)
	$(CA65) $(RS_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/railshooter.o $(RS)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/railshooter.o
	$(PY) tools/fix_checksum.py $@

railshooter: $(BUILD)/railshooter.sfc

rs-assets: $(RS_ASSETS)

# ---- m7_oshoot: the rotating Mode-7 arena shooter ----------
# A top-down run-and-gun on a spinning Mode 7 plane: eight-way aim/move, a
# pivot re-pinned to the walking player EVERY FRAME, timed waves of chasers and
# a bullet pool, everything but the hero projected onto the floor through the
# render matrix's transpose, and all of the gameplay in world space.
#
# NO NEW ENGINE FEATURE. The rail's SCALE_VIEW is the
# constant $0100 that m7_affine's 256-entry LUT already tabulates, so this is
# the one static-affine rail the feature supplies AS BUILT; `pool` arrives from
# railshooter and this is its first external consumption.
MO        := game/m7_oshoot
MO_MAP    := $(BUILD)/mo
MO_ASM    := $(MO)/main.asm $(wildcard $(MO)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
MO_ASSETS := $(BUILD)/assets/mo_map.bin $(BUILD)/assets/mo_tilemap.bin \
             $(BUILD)/assets/mo_flags.bin $(BUILD)/assets/mo_pal.bin \
             $(BUILD)/assets/mo_hero_chr.bin $(BUILD)/assets/mo_hero_pal.bin \
             $(BUILD)/assets/mo_enemy_chr.bin $(BUILD)/assets/mo_enemy_pal.bin \
             $(BUILD)/assets/mo_bullet_pal.bin $(BUILD)/assets/mo_score_pal.bin

$(MO_ASSETS): tools/gen_m7_oshoot_assets.py | $(BUILD)
	$(PY) tools/gen_m7_oshoot_assets.py $(BUILD)/assets

$(MO_MAP)/engine_state_globals.inc $(MO_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(MO)/game.toml \
		$(MO)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(MO) --features-dir engine/features \
		--out $(MO_MAP)

MO_INC := -I $(MO_MAP) -I $(VROM) -I $(MO) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/fade -I engine/features/oam_sprites \
          -I engine/features/pool -I engine/features/m7_affine \
          -I engine/features/m7_project -I engine/features/mo_floor \
          -I engine/features/mo_obj -I engine/features/col_map

$(BUILD)/m7_oshoot.sfc: $(MO_ASM) $(MO)/m7_oshoot.inc \
		$(MO_MAP)/engine_state_globals.inc $(MO_ASSETS) \
		$(BUILD)/assets/m7_affine_lut.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(MO_MAP)/symbol_map.json $(MO_ASM)
	$(CA65) $(MO_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/m7_oshoot.o $(MO)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/m7_oshoot.o
	$(PY) tools/fix_checksum.py $@

m7_oshoot: $(BUILD)/m7_oshoot.sfc

mo-assets: $(MO_ASSETS)

# ---- mode7_flight: the altitude axis --------------------------------------
# Free flight over a Mode 7 perspective floor with INPUT-CONTROLLED ALTITUDE
# driving the perspective scale. The settled mechanism (project decision
# 2026-08-15) is the SEPARABLE HYBRID: the pose factors as
# S_a(k) * R(h), both factors are baked (~28 KB, exact on both axes), and
# m7f_cam joins them per frame through the hardware multiplier into a
# double-buffered WRAM band table that two DIRECT HDMA channels stream. The
# product table the factoring replaces would be 12.7 MB.
#
# TWO GENERATORS, deliberately kept apart: gen_m7f_factors.py emits the rail's
# distinctive LUTs and carries their provenance and their build-time identity
# checks; gen_m7f_assets.py draws the overworld and the cast. A change to the
# join's arithmetic touches one file and a change to the art touches the other.
M7F        := game/mode7_flight
M7F_MAP    := $(BUILD)/m7f
M7F_ASM    := $(M7F)/main.asm $(wildcard $(M7F)/scenes/*.asm) \
              $(wildcard engine/features/*/*.asm)
M7F_ASSETS := $(BUILD)/assets/m7f_ground.bin $(BUILD)/assets/m7f_pal.bin \
              $(BUILD)/assets/m7f_obj_chr.bin $(BUILD)/assets/m7f_ship_pal.bin \
              $(BUILD)/assets/m7f_shadow_pal.bin
M7F_FACTORS := $(BUILD)/assets/m7f_prof.bin $(BUILD)/assets/m7f_trig.bin
# The COLDATA sky ramp + horizon fog: rgb_gradient's `grad_tabs` claim, backed
# by THIS rail's blob. A third generator, kept apart from the other two for the
# reason already recorded above — it answers a different question (the look)
# and a change to it must not force the factor tables to rebuild.
M7F_GRAD   := $(BUILD)/assets/m7f_grad.bin $(BUILD)/assets/m7f_tod.bin \
              $(BUILD)/assets/m7f_todpal.bin

$(M7F_ASSETS): tools/gen_m7f_assets.py | $(BUILD)
	$(PY) tools/gen_m7f_assets.py $(BUILD)/assets

$(M7F_GRAD): tools/gen_m7f_gradient.py tools/gen_m7f_assets.py | $(BUILD)
	$(PY) tools/gen_m7f_gradient.py $(BUILD)/assets

$(M7F_FACTORS): tools/gen_m7f_factors.py | $(BUILD)
	$(PY) tools/gen_m7f_factors.py $(BUILD)/assets

$(M7F_MAP)/m7f_join.inc: tools/gen_m7f_join.py | $(BUILD)
	$(PY) tools/gen_m7f_join.py $(M7F_MAP)

$(M7F_MAP)/engine_state_globals.inc $(M7F_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(M7F)/game.toml \
		$(M7F)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(M7F) --features-dir engine/features \
		--out $(M7F_MAP)

M7F_INC := -I $(M7F_MAP) -I $(VROM) -I $(M7F) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/fade -I engine/features/oam_sprites \
           -I engine/features/m7f_cam -I engine/features/m7f_floor \
           -I engine/features/m7f_obj -I engine/features/m7f_logic \
           -I engine/features/rgb_gradient

$(BUILD)/mode7_flight.sfc: $(M7F_ASM) $(M7F)/mode7_flight.inc \
		$(M7F_MAP)/engine_state_globals.inc $(M7F_MAP)/m7f_join.inc \
		$(M7F_ASSETS) $(M7F_FACTORS) $(M7F_GRAD) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(M7F_MAP)/symbol_map.json $(M7F_ASM)
	$(CA65) $(M7F_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/mode7_flight.o $(M7F)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/mode7_flight.o
	$(PY) tools/fix_checksum.py $@

mode7_flight: $(BUILD)/mode7_flight.sfc

m7f-assets: $(M7F_ASSETS) $(M7F_FACTORS) $(M7F_GRAD)

# ---- boss: the scale-ramping static-affine debut -----
# "The boss IS the screen": the boss face is the Mode 7 BG, scaled + rotated
# by one uniform matrix per frame; the ship, the rain and the HP HUD are
# sprites over it. Every animated state's matrix comes from a BAKED track
# (ring / reveal / death) through the shared m7_track player — no runtime
# trig, no multiply, no HDMA channel. `boss_saucer` and `meteor_event`
# inherit the player unchanged (m7_track/feature.toml is the contract).
BS        := game/boss
BS_MAP    := $(BUILD)/bs
BS_ASM    := $(BS)/main.asm $(wildcard $(BS)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
BS_ASSETS := $(BUILD)/assets/bs_map.bin $(BUILD)/assets/bs_pal.bin \
             $(BUILD)/assets/bs_sprite_chr.bin \
             $(BUILD)/assets/bs_sprite_pal.bin \
             $(BUILD)/assets/bs_ring.bin $(BUILD)/assets/bs_reveal.bin \
             $(BUILD)/assets/bs_death.bin

$(BUILD)/assets/bs_map.bin $(BUILD)/assets/bs_pal.bin \
$(BUILD)/assets/bs_sprite_chr.bin $(BUILD)/assets/bs_sprite_pal.bin: \
		tools/gen_boss_assets.py | $(BUILD)
	$(PY) tools/gen_boss_assets.py $(BUILD)/assets

$(BUILD)/assets/bs_ring.bin $(BUILD)/assets/bs_reveal.bin \
$(BUILD)/assets/bs_death.bin: tools/gen_boss_tracks.py | $(BUILD)
	$(PY) tools/gen_boss_tracks.py $(BUILD)/assets

$(BS_MAP)/engine_state_globals.inc $(BS_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(BS)/game.toml \
		$(BS)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(BS) --features-dir engine/features \
		--out $(BS_MAP)

BS_INC := -I $(BS_MAP) -I $(VROM) -I $(BS) \
          -I engine/features/scene_mgr -I engine/features/input \
          -I engine/features/fade -I engine/features/oam_sprites \
          -I engine/features/pool -I engine/features/m7_affine \
          -I engine/features/m7_track -I engine/features/bs_floor \
          -I engine/features/bs_obj

$(BUILD)/boss.sfc: $(BS_ASM) $(BS)/boss.inc \
		$(BS_MAP)/engine_state_globals.inc $(BS_ASSETS) \
		$(BUILD)/assets/m7_affine_lut.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(BS_MAP)/symbol_map.json $(BS_ASM)
	$(CA65) $(BS_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/boss.o $(BS)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/boss.o
	$(PY) tools/fix_checksum.py $@

boss: $(BUILD)/boss.sfc

bs-assets: $(BS_ASSETS)

# ---- boss_saucer: the second m7_track consumer, and an audio rail ---------
# The static-affine boss shape with SCALING as the headline: the saucer IS the
# Mode 7 BG, it LUNGES at the camera (a scale ramp DOWN, so the plane grows to
# fill the view) and at the apex fires a BEAM down a column locked to the
# player. FIVE baked matrix tracks through the shared m7_track player — the
# reveal, both halves of the lunge, the hold's ring, the death recede — plus
# TAD music and SFX through the `audio` occupant.
SAU        := game/boss_saucer
SAU_MAP    := $(BUILD)/sau
SAU_ASM    := $(SAU)/main.asm $(wildcard $(SAU)/scenes/*.asm) \
              $(wildcard engine/features/*/*.asm)
SAU_ASSETS := $(BUILD)/assets/sau_map.bin $(BUILD)/assets/sau_pal.bin \
              $(BUILD)/assets/sau_sprite_chr.bin \
              $(BUILD)/assets/sau_sprite_pal.bin \
              $(BUILD)/assets/sau_ring.bin $(BUILD)/assets/sau_reveal.bin \
              $(BUILD)/assets/sau_appr.bin $(BUILD)/assets/sau_retr.bin \
              $(BUILD)/assets/sau_death.bin

$(BUILD)/assets/sau_map.bin $(BUILD)/assets/sau_pal.bin \
$(BUILD)/assets/sau_sprite_chr.bin $(BUILD)/assets/sau_sprite_pal.bin: \
		tools/gen_saucer_assets.py | $(BUILD)
	$(PY) tools/gen_saucer_assets.py $(BUILD)/assets

$(BUILD)/assets/sau_ring.bin $(BUILD)/assets/sau_reveal.bin \
$(BUILD)/assets/sau_appr.bin $(BUILD)/assets/sau_retr.bin \
$(BUILD)/assets/sau_death.bin: tools/gen_saucer_tracks.py | $(BUILD)
	$(PY) tools/gen_saucer_tracks.py $(BUILD)/assets

$(SAU_MAP)/engine_state_globals.inc $(SAU_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SAU)/game.toml \
		$(SAU)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SAU) --features-dir engine/features \
		--out $(SAU_MAP)

# TAD audio objects (boss_saucer): separate compilation units, per the room
# rule — tad-audio.s owns its own .bss/.zeropage layout and the generated
# export owns AUDIO_DATA0. Neither is in SAU_ASM: the no_literals scope covers
# hand-authored engine ASM only, and these are vendored + generated.
$(BUILD)/sau_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(SAU_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(SAU_MAP) -I vendor/tad -o $@ $<

$(BUILD)/sau_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

SAU_INC := -I $(SAU_MAP) -I $(VROM) -I $(SAU) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/fade -I engine/features/oam_sprites \
           -I engine/features/pool -I engine/features/m7_affine \
           -I engine/features/m7_track -I engine/features/sau_floor \
           -I engine/features/sau_obj \
           -I vendor/tad -I assets/audio/export

$(BUILD)/boss_saucer.sfc: $(SAU_ASM) $(SAU)/saucer.inc \
		$(SAU_MAP)/engine_state_globals.inc $(SAU_ASSETS) \
		$(BUILD)/assets/m7_affine_lut.bin \
		$(BUILD)/sau_tad_wrapper.o $(BUILD)/sau_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SAU_MAP)/symbol_map.json $(SAU_ASM)
	$(CA65) $(SAU_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/boss_saucer.o $(SAU)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/boss_saucer.o \
		$(BUILD)/sau_tad_wrapper.o $(BUILD)/sau_tad_data.o
	$(PY) tools/fix_checksum.py $@

boss_saucer: $(BUILD)/boss_saucer.sfc

sau-assets: $(SAU_ASSETS)

# ---- meteor_event: the Mode-1 <-> Mode-7 cutscene ---------------
# A tiny platformer slice becomes a set-piece and returns: the walk, the
# freeze, the BG->OBJ capture, the swap, the far-approach meteor sprite, the
# crossover, the Mode-7 grow/slide/tumble, the red glow, the swap back. The
# scale-ramping affine trio's third rail — it inherits `m7_track` unchanged
# and brings its own baked ramp (MET_SCALE_STEP $0030) and its own capture.
MET        := game/meteor_event
MET_MAP    := $(BUILD)/met
MET_ASM    := $(MET)/main.asm $(wildcard $(MET)/scenes/*.asm) \
              $(wildcard engine/features/*/*.asm)
MET_ASSETS := $(BUILD)/assets/met_map.bin $(BUILD)/assets/met_pal.bin \
              $(BUILD)/assets/met_obj_chr.bin $(BUILD)/assets/met_obj_pal.bin \
              $(BUILD)/assets/met_bg_chr.bin $(BUILD)/assets/met_bg_pal.bin \
              $(BUILD)/assets/met_grow.bin

$(BUILD)/assets/met_map.bin $(BUILD)/assets/met_pal.bin \
$(BUILD)/assets/met_obj_chr.bin $(BUILD)/assets/met_obj_pal.bin \
$(BUILD)/assets/met_bg_chr.bin $(BUILD)/assets/met_bg_pal.bin: \
		tools/gen_meteor_assets.py | $(BUILD)
	$(PY) tools/gen_meteor_assets.py $(BUILD)/assets

$(BUILD)/assets/met_grow.bin: tools/gen_meteor_tracks.py | $(BUILD)
	$(PY) tools/gen_meteor_tracks.py $(BUILD)/assets

$(MET_MAP)/engine_state_globals.inc $(MET_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(MET)/game.toml \
		$(MET)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(MET) --features-dir engine/features \
		--out $(MET_MAP)

MET_INC := -I $(MET_MAP) -I $(VROM) -I $(MET) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/fade -I engine/features/oam_sprites \
           -I engine/features/m7_affine -I engine/features/m7_track \
           -I engine/features/met_obj -I engine/features/met_bg \
           -I engine/features/met_floor -I engine/features/met_glow

$(BUILD)/meteor_event.sfc: $(MET_ASM) $(MET)/meteor.inc \
		$(MET_MAP)/engine_state_globals.inc $(MET_ASSETS) \
		$(BUILD)/assets/m7_affine_lut.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(MET_MAP)/symbol_map.json $(MET_ASM)
	$(CA65) $(MET_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/meteor_event.o $(MET)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/meteor_event.o
	$(PY) tools/fix_checksum.py $@

meteor_event: $(BUILD)/meteor_event.sfc

met-assets: $(MET_ASSETS)

# ---- split_h_2p assets ------------------------------------
# The rail's art. Everything is AUTHORED (a checker algebra, a hyperbolic
# perspective ramp, five colours) — nothing is read from a pack, so there is no
# reference fallback here and none is needed on a bare runner.
#
# What vendor/art/split_h_2p holds instead is a committed reference OUTPUT, as
# an oracle: the generator shares no code with the program that produced those blobs and
# REFUSES to write anything that disagrees with them. It is therefore also a
# gate, not only a build step. See its header and that directory's README.
SH2_SLICES := 0 1 2 3
SH2_ASSETS := $(BUILD)/assets/sh2_map.bin $(BUILD)/assets/sh2_pal.bin \
              $(BUILD)/assets/sh2_pose1_ab.bin $(BUILD)/assets/sh2_pose1_cd.bin \
              $(BUILD)/assets/sh2_move256.bin \
              $(foreach k,$(SH2_SLICES),$(BUILD)/assets/sh2_pose256_ab_s$(k).bin) \
              $(foreach k,$(SH2_SLICES),$(BUILD)/assets/sh2_pose256_cd_s$(k).bin) \
              $(BUILD)/assets/sh2_sp_sincos.bin $(BUILD)/assets/sh2_sp_vk.bin \
              $(BUILD)/assets/sh2_sp_recip_lo.bin \
              $(BUILD)/assets/sh2_sp_recip_hi.bin \
              $(BUILD)/assets/sh2_sp_tier.bin $(BUILD)/assets/sh2_sp_chr.bin \
              $(BUILD)/assets/sh2_ents.bin $(BUILD)/assets/sh2_way.bin

# NAMED, not $(wildcard ...). A wildcard prerequisite EVAPORATES
# with the files it matches: delete the oracle and make stops depending on it,
# so already-built blobs stay "up to date" and the gate never runs again. Named
# explicitly, a missing reference is "No rule to make target ..." and the build
# stops. (The generator refuses an absent oracle too — that covers the case
# where it does run; this covers the case where make decides it need not.)
SH2_ORACLE := vendor/art/split_h_2p/ref_checker_map.bin \
              vendor/art/split_h_2p/ref_poses1_ab.bin \
              vendor/art/split_h_2p/ref_poses1_cd.bin \
              vendor/art/split_h_2p/ref_poses256_ab.bin \
              vendor/art/split_h_2p/ref_poses256_cd.bin \
              vendor/art/split_h_2p/ref_move256.bin \
              vendor/art/split_h_2p/ref_palette.inc \
              vendor/art/split_h_2p/ref_sp_sincos.bin \
              vendor/art/split_h_2p/ref_sp_vk.bin \
              vendor/art/split_h_2p/ref_sp_recip_lo.bin \
              vendor/art/split_h_2p/ref_sp_recip_hi.bin \
              vendor/art/split_h_2p/ref_sp_tier_nocull.bin \
              vendor/art/split_h_2p/ref_sp_chr.bin

# --oam-slots is sh2_obj's OWN claim, passed through rather than restated in
# the generator: the swarm's peak concurrent sprite count is gated against the
# number of slots that actually exist, and the feature.toml is the authority on
# that. A peak the claim cannot hold fails at ASSET time, before a sprite is
# ever dropped on hardware.
SH2_OAM_SLOTS := 32
$(SH2_ASSETS): tools/gen_split_h_2p_assets.py $(SH2_ORACLE) | $(BUILD)
	$(PY) tools/gen_split_h_2p_assets.py $(BUILD)/assets \
		--oam-slots $(SH2_OAM_SLOTS)

sh2-assets: $(SH2_ASSETS)

# ---- split_h_demo: the horizontal split ---------------
# The cockpit horizontal raster-band split: a BG3 tile instrument panel in the
# top 40 scanlines over a receding Mode-7 perspective floor, with `split_band`
# rewriting BGMODE and TM at the seam while mode7_persp's two INDIRECT matrix
# channels are re-pointed every VBlank the camera turns.
#
# THE SECOND BINDING of the generalised split_band table (microzero is the
# first) — same claims, different seam and different band bytes.
#
# The world map, floor art and font are microzero's blobs, reused: the plane is
# not this rail's subject and a second 256 KB map would be ROM spent on nothing
# the tests read. The POSES are this rail's own, because PERSP_LINES is
# 224 - HUD_LINES and this seam is 40, not 44 — 184 rows, not 180.
SHD      := game/split_h_demo
SHD_MAP  := $(BUILD)/shd
SHD_ASM  := $(SHD)/main.asm $(wildcard $(SHD)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

# Generated into a SCRATCH DIR, not into $(BUILD)/assets, and this is
# load-bearing rather than tidy. `gen_pose_tables.py` always writes
# `poses_ab.bin` / `poses_cd.bin` under the directory it is given — the same
# names `racer` and `microzero` consume at DIFFERENT parameters (`--lines 180`
# here vs 184 there; 224 minus this rail's 40-line HUD, not the 44 the others
# use). This recipe used to generate into $(BUILD)/assets and `mv` the two
# files aside, which CLOBBERED the shared pair inside a single make
# invocation:
#
#   $ rm -f build/assets/*poses_*.bin build/{microzero,split_h_demo,racer}.sfc
#   $ make microzero split_h_demo racer
#   game/racer/main.asm(66): Error: Cannot open include file 'poses_ab.bin'
#
# microzero builds the pair, make records it as up to date FOR THIS
# INVOCATION, split_h_demo's `mv` takes it away, and racer — which declares it
# as a prerequisite — is never given it back, because make will not remake a
# target it already made in the same run. That is exactly the order the
# `test:` prerequisite list is site 12, which exists so
# `make test` pre-builds the tree), so on a cold tree `make test` could not
# build the tree it exists to build. Found and fixed 2026-08-07, a DX
# work item; both ROMs are byte-identical across the change — same
# generator, same arguments, only the path differs.
$(BUILD)/assets/shd_poses_ab.bin $(BUILD)/assets/shd_poses_cd.bin: \
		tools/gen_pose_tables.py | $(BUILD)
	@mkdir -p $(BUILD)/assets/shd_poses
	$(PY) tools/gen_pose_tables.py --lines 184 --scale-far 436 \
		--scale-near 77 $(BUILD)/assets/shd_poses
	mv $(BUILD)/assets/shd_poses/poses_ab.bin $(BUILD)/assets/shd_poses_ab.bin
	mv $(BUILD)/assets/shd_poses/poses_cd.bin $(BUILD)/assets/shd_poses_cd.bin
	@rmdir $(BUILD)/assets/shd_poses 2>/dev/null || true

SHD_INC := -I $(SHD_MAP) -I $(VROM) -I $(SHD) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/fade -I engine/features/bg_text \
           -I engine/features/mode7_floor -I engine/features/split_band \
           -I engine/features/mode7_persp

$(SHD_MAP)/engine_state_globals.inc $(SHD_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SHD)/game.toml \
		$(SHD)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SHD) --features-dir engine/features \
		--out $(SHD_MAP)

$(BUILD)/split_h_demo.sfc: $(SHD_ASM) $(SHD)/split_h_demo.inc \
		$(SHD_MAP)/engine_state_globals.inc \
		$(BUILD)/assets/shd_poses_ab.bin $(BUILD)/assets/shd_poses_cd.bin \
		$(BUILD)/assets/world_map.bin $(BUILD)/assets/floor_tiles.bin \
		$(BUILD)/assets/font_2bpp.bin \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SHD_MAP)/symbol_map.json $(SHD_ASM)
	$(CA65) $(SHD_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_demo.o $(SHD)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_demo: $(BUILD)/split_h_demo.sfc

# The CONTROLLER-FREE PILOT ROM, in the shape build_svd_nowin.sh
# established. Not a non-vacuity control — a PILOT build, whose job is to let
# the rail be watched with no pad attached. The pad axes compile out and the
# heading steps itself; the panel readout follows because it IS the heading.
# Every line is inside `.ifdef SHD_AUTODEMO` and it declares no state, so the
# shipping ROM above is byte-identical with or without this target.
shd-autodemo: $(BUILD)/split_h_demo.sfc
	bash tools/build_shd_autodemo.sh

# ---- split_h_2p_demo: two Mode 7 cameras on one plane -----
# SIX active HDMA channels over one scene (the per-band shape, not the
# four-channel one): a per-band INDIRECT matrix pair streaming that band's heading's ROM
# pose through M7A-M7D, and a per-band DIRECT origin pair giving each band its
# own M7X/M7Y + M7HOFS/M7VOFS. The FLOOR drives itself off the PPU; the swarm,
# the AI and the projection run in the scene tick during active display and are
# MEASURED (`make sh2-measure`) rather than counted.
#
# No TAD objects — see the block below; this rail is silent.
SH2       := game/split_h_2p_demo
SH2_MAP   := $(BUILD)/sh2
SH2_ASM   := $(SH2)/main.asm $(wildcard $(SH2)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

$(SH2_MAP)/engine_state_globals.inc $(SH2_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SH2)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SH2) --features-dir engine/features \
		--out $(SH2_MAP)

# NO TAD OBJECTS. A music-playing build would link the wrapper + the export;
# this is the ROTATE build, and it is SILENT on purpose — its per-frame cadence
# is MEASURED, and an audio driver's own tick would land inside the number.
# `audio`/`tad_rom` are off game.toml, so the
# objects, the include paths and the vendor/tad prerequisites all go with them.
SH2_INC := -I $(SH2_MAP) -I $(VROM) -I $(SH2) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/input -I engine/features/input2 \
           -I engine/features/sh2_floor -I engine/features/sh2_cam \
           -I engine/features/oam_sprites -I engine/features/m7_persp_project \
           -I engine/features/sh2_swarm -I engine/features/sh2_obj

$(BUILD)/split_h_2p_demo.sfc: $(SH2_ASM) \
		$(SH2_MAP)/engine_state_globals.inc $(SH2_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SH2_MAP)/symbol_map.json $(SH2_ASM)
	$(CA65) $(SH2_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_2p_demo.o $(SH2)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_2p_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_2p_demo: $(BUILD)/split_h_2p_demo.sfc

# ---- seam_irq_trial: the sweep tail's SCANLINE-IRQ DEBUT --------
# Band 2's Mode 7 origin by a seam-scanline V-IRQ firing a pre-armed GP-DMA
# pair (ch ES_H_SITXY/SITHV, OUT of the HDMAEN mask), vs the classic
# HDMA-origin control. TWO whole-frame INDIRECT matrix channels stream ONE
# fixed-angle pose to both bands. The four asset blobs are the sh2
# generator's oracle-gated output — this trial `.incbin`s exactly those bytes —
# so SIT_ASSETS names files the $(SH2_ASSETS) rule already makes.
SIT       := game/seam_irq_trial
SIT_MAP   := $(BUILD)/sit
SIT_ASM   := $(SIT)/main.asm $(wildcard $(SIT)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
SIT_ASSETS := $(BUILD)/assets/sh2_map.bin $(BUILD)/assets/sh2_pal.bin \
              $(BUILD)/assets/sh2_pose1_ab.bin $(BUILD)/assets/sh2_pose1_cd.bin

$(SIT_MAP)/engine_state_globals.inc $(SIT_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SIT)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SIT) --features-dir engine/features \
		--out $(SIT_MAP)

SIT_INC := -I $(SIT_MAP) -I $(VROM) -I $(SIT) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/irq -I engine/features/sit_floor \
           -I engine/features/sit_cam

$(BUILD)/seam_irq_trial.sfc: $(SIT_ASM) \
		$(SIT_MAP)/engine_state_globals.inc $(SIT_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SIT_MAP)/symbol_map.json $(SIT_ASM)
	$(CA65) $(SIT_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/seam_irq_trial.o $(SIT)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/seam_irq_trial.o
	$(PY) tools/fix_checksum.py $@

seam_irq_trial: $(BUILD)/seam_irq_trial.sfc

# The two CONTROL ROMs (-DSIT_HDMA_ORIGIN gold / -DSIT_MISTIME non-vacuity).
# The generic rule cannot pass -D, so they live in the variants script — the
# svd-nowin shape. Controls, not pilots: the shipping ROM is the subject.
sit-origin sit-mistime: $(SIT_ASSETS) $(SIT_MAP)/engine_state_globals.inc
	bash tools/build_seam_irq_variants.sh $(subst sit-,,$@)

# ---- split_h_irq_grad_demo: the sweep tail's APPLIED IRQ case ----
# `seam_irq_trial` freed the origin channel pair; this rail SPENDS it. Two
# MOVING Mode 7 cameras over one plane, band 2's origin by the same seam V-IRQ
# (ch ES_H_SHGXY/SHGHV, out of the HDMAEN mask), and one freed channel
# (ES_H_SHGGR) driving a per-scanline COLDATA gradient — 5 channels claimed of
# 8, 3 in the mask, 3 free. Its three asset blobs are the sh2 generator's
# oracle-gated output, byte-identical to the files the reference rail .incbins
# across the template boundary — so SHG_ASSETS names files the $(SH2_ASSETS)
# rule already makes. There is no palette blob: the rail's five colours are
# CPU-written and blue-zero, which is its gradient metric (shg_floor.asm).
SHG       := game/split_h_irq_grad_demo
SHG_MAP   := $(BUILD)/shg
SHG_ASM   := $(SHG)/main.asm $(wildcard $(SHG)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)
SHG_ASSETS := $(BUILD)/assets/sh2_map.bin \
              $(BUILD)/assets/sh2_pose1_ab.bin $(BUILD)/assets/sh2_pose1_cd.bin

$(SHG_MAP)/engine_state_globals.inc $(SHG_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SHG)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SHG) --features-dir engine/features \
		--out $(SHG_MAP)

SHG_INC := -I $(SHG_MAP) -I $(VROM) -I $(SHG) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/irq -I engine/features/shg_floor \
           -I engine/features/shg_cam -I engine/features/shg_grad

$(BUILD)/split_h_irq_grad_demo.sfc: $(SHG_ASM) \
		$(SHG_MAP)/engine_state_globals.inc $(SHG_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SHG_MAP)/symbol_map.json $(SHG_ASM)
	$(CA65) $(SHG_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_irq_grad_demo.o $(SHG)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_irq_grad_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_irq_grad_demo: $(BUILD)/split_h_irq_grad_demo.sfc

# The two CONTROL ROMs (-DSHG_NO_GRAD gradient flip / -DSHG_HDMA_ORIGIN gold).
# The generic rule cannot pass -D, so they live in the variants script — the
# sit-origin / svd-nowin shape. Controls, not pilots: the shipping ROM is the
# subject.
shg-nograd shg-origin: $(SHG_ASSETS) $(SHG_MAP)/engine_state_globals.inc
	bash tools/build_shg_variants.sh $(subst shg-,,$@)

# ---- split_v_demo: the vertical window dual-view -------
# ONE stage, TWO cameras, clipped to opposite screen halves by PPU window 1,
# with a backdrop seam bar cut by window 2. The per-half OBJ clip and the
# diagonal seam would each need their own `-D` VARIANT ROM if the composition
# were not declared; here they are runtime
# MODES over one composition, so this rule builds the whole rail and there is
# no variants target for them. `-DSVD_NOWIN` is the exception and it IS a
# variant — the non-vacuity control, built by svd-nowin below.
#
# No TAD objects — `tad_rom` is not in this game's globals, so the link is one
# object (scroller's / scroll_run's shape).
SVD       := game/split_v_demo
SVD_MAP   := $(BUILD)/svd
SVD_ASM   := $(SVD)/main.asm $(wildcard $(SVD)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

SVD_ASSETS := $(BUILD)/assets/svd_stage_chr.bin \
              $(BUILD)/assets/svd_stage_map.bin \
              $(BUILD)/assets/svd_stage_pal.bin \
              $(BUILD)/assets/svd_obj_chr.bin \
              $(BUILD)/assets/svd_obj_pal.bin \
              $(BUILD)/assets/svd_diag_tab.bin

$(SVD_ASSETS): tools/gen_svd_assets.py | $(BUILD)
	$(PY) tools/gen_svd_assets.py $(BUILD)/assets

svd-assets: $(SVD_ASSETS)

$(SVD_MAP)/engine_state_globals.inc $(SVD_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SVD)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SVD) --features-dir engine/features \
		--out $(SVD_MAP)

SVD_INC := -I $(SVD_MAP) -I $(VROM) -I $(SVD) \
           -I engine/features/scene_mgr -I engine/features/fade \
           -I engine/features/input -I engine/features/input2 \
           -I engine/features/oam_sprites \
           -I engine/features/svd_bg -I engine/features/svd_obj

$(BUILD)/split_v_demo.sfc: $(SVD_ASM) $(SVD)/split_v_demo.inc \
		$(SVD_MAP)/engine_state_globals.inc $(SVD_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SVD_MAP)/symbol_map.json $(SVD_ASM)
	$(CA65) $(SVD_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_v_demo.o $(SVD)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_v_demo.o
	$(PY) tools/fix_checksum.py $@

split_v_demo: $(BUILD)/split_v_demo.sfc

# The NON-VACUITY CONTROL, in the shape tools/build_split_v_variants.sh and
# sh2-variants established: the window recipe compiled OUT, so BG1 (camera A)
# fills the whole screen and the split COLLAPSES. The two-region assertion
# must FAIL on this ROM — which is what proves it is not vacuous. It has to be
# a separate BINARY rather than a mode: a control the code under test can
# write is not a control.
svd-nowin: $(SVD_ASSETS) $(SVD_MAP)/engine_state_globals.inc
	bash tools/build_svd_nowin.sh


# ---- the label twin, and the measurement it makes possible ----------------
# Same sources, same linker config, `-g` on the assembler and `-Ln` on the
# linker; the `cmp` is the whole point. It proves the label file describes the
# binary that actually SHIPS, so tools/measure_sh2_swarm.py can put execution
# breakpoints on routines by NAME instead of on transcribed addresses — a twin
# that drifts fails here rather than measuring something else and reporting it
# as fact. The pattern is m7dg-labels', unchanged.
$(BUILD)/split_h_2p_demo.lbl: $(BUILD)/split_h_2p_demo.sfc
	$(CA65) $(SH2_INC) --bin-include-dir $(BUILD)/assets -g \
		-o $(BUILD)/split_h_2p_demo_dbg.o $(SH2)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -Ln $@ \
		-o $(BUILD)/split_h_2p_demo_dbg.sfc $(BUILD)/split_h_2p_demo_dbg.o
	$(PY) tools/fix_checksum.py $(BUILD)/split_h_2p_demo_dbg.sfc
	cmp $(BUILD)/split_h_2p_demo_dbg.sfc $(BUILD)/split_h_2p_demo.sfc

sh2-labels: $(BUILD)/split_h_2p_demo.lbl

# DESIGN REVIEW G10, and the reason this rail exists: it is the MEASURED
# sprite-stress rail, so `SPRITES=24` has to be a number rather than a
# preference. Not part of `make measure`'s pinned budgets — it is a reported
# figure, and the frame it is a fraction of is read from substrate.toml.
sh2-measure: $(BUILD)/split_h_2p_demo.lbl
	$(PY) tools/measure_sh2_swarm.py


# The NON-VACUITY CONTROL, in the shape tools/build_split_v_variants.sh
# established: camera 2 folded onto camera 1, so band 2 leaves the warm stripe
# and the red position signal must DIE. A variant, not a second rail — the
# generic rule above cannot pass -D.
sh2-variants: $(SH2_ASSETS) $(SH2_MAP)/engine_state_globals.inc
	bash tools/build_split_h_2p_variants.sh

# ---- the matrix-band PAIR --
# TWO rails, ONE feature set. `split_h_matrix_demo` stacks two Mode 7 cameras
# over one plane and `split_h_persp3_demo` stacks three, both on the SAME two
# DIRECT HDMA channels and the same 32 KB checker world — the band count lives
# in `shm_cam`'s WRAM table, not in its declaration — one feature plus a
# band-count variant, literally.
#
# ONE generator and ONE oracle for both, because the two rails want
# byte-identical checker maps. The oracle is NAMED rather
# than wildcarded so its absence cannot make the dependency evaporate, and the
# generator refuses to emit without it.
SHM_ORACLE := vendor/art/split_h_matrix/ref_checker_map.bin
SHM_ASSETS := $(BUILD)/assets/shm_map.bin $(BUILD)/assets/shm_pal.bin

$(SHM_ASSETS): tools/gen_split_h_matrix_assets.py $(SHM_ORACLE) | $(BUILD)
	$(PY) tools/gen_split_h_matrix_assets.py $(BUILD)/assets

# -I every feature dir whose asm each composition includes, PLUS the emitted
# map, $(VROM) for the header/init/reset and the rail dir for its scene. The
# two lists are identical because the two compositions are.
SHM_INC_COMMON := -I $(VROM) \
                  -I engine/features/scene_mgr -I engine/features/fade \
                  -I engine/features/input \
                  -I engine/features/shm_floor -I engine/features/shm_cam

# ---- rail 1: split_h_matrix_demo (two bands) ------------------------------
SHM      := game/split_h_matrix_demo
SHM_MAP  := $(BUILD)/shm
SHM_ASM  := $(SHM)/main.asm $(wildcard $(SHM)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)

$(SHM_MAP)/engine_state_globals.inc $(SHM_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SHM)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SHM) --features-dir engine/features \
		--out $(SHM_MAP)

$(BUILD)/split_h_matrix_demo.sfc: $(SHM_ASM) \
		$(SHM_MAP)/engine_state_globals.inc $(SHM_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SHM_MAP)/symbol_map.json $(SHM_ASM)
	$(CA65) -I $(SHM_MAP) -I $(SHM) $(SHM_INC_COMMON) \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_matrix_demo.o $(SHM)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_matrix_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_matrix_demo: $(BUILD)/split_h_matrix_demo.sfc

# ---- rail 2: split_h_persp3_demo (three bands) ----------------------------
SHP3      := game/split_h_persp3_demo
SHP3_MAP  := $(BUILD)/shp3
SHP3_ASM  := $(SHP3)/main.asm $(wildcard $(SHP3)/scenes/*.asm) \
             $(wildcard engine/features/*/*.asm)

$(SHP3_MAP)/engine_state_globals.inc $(SHP3_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(SHP3)/game.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(SHP3) --features-dir engine/features \
		--out $(SHP3_MAP)

$(BUILD)/split_h_persp3_demo.sfc: $(SHP3_ASM) \
		$(SHP3_MAP)/engine_state_globals.inc $(SHM_ASSETS) \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(SHP3_MAP)/symbol_map.json $(SHP3_ASM)
	$(CA65) -I $(SHP3_MAP) -I $(SHP3) $(SHM_INC_COMMON) \
		--bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/split_h_persp3_demo.o $(SHP3)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/split_h_persp3_demo.o
	$(PY) tools/fix_checksum.py $@

split_h_persp3_demo: $(BUILD)/split_h_persp3_demo.sfc

# ---- rom-unbacked: the rom-claim BACKING gate (docs/37) -------------------
# The presence-side twin of toy-bad, and the same polarity for the same reason
# (see toy-bad's block above): SUCCESS MEANS THE GATE REFUSED. A consumer
# nobody updates then fails LOUD on a healthy repo rather than passing a
# toothless check in silence.
#
# TWO ARMS over ONE allocation, because a gate that refuses everything is not a
# gate either:
#
#   control   main_backed.asm    -> must be ACCEPTED (exit 0)
#   violation main_unbacked.asm  -> must be REFUSED with ROM CLAIM UNBACKED,
#                                   naming BOTH missing claims and NOT the
#                                   `backed_by`-declared one
#
# The two mains differ in exactly one thing — whether the claim sites exist —
# so the only variable is the one the gate reads.
#
# ROM_UNBACKED_SRC is overridable on toy-bad's precedent, so a test can point
# the real recipe at a planted tree without editing the live fixture.
ROM_UNBACKED_SRC ?= tests/fixtures/rom_backing

rom-unbacked:
	@mkdir -p $(BUILD)
	@$(PY) allocator/allocate.py --game $(ROM_UNBACKED_SRC) \
	    --out $(BUILD)/romgate > $(BUILD)/romgate_alloc.out 2>&1 || { \
	    echo "rom-unbacked FAILED: the allocator could not place the fixture —"; \
	    echo "        the gate never ran (see $(BUILD)/romgate_alloc.out)"; \
	    cat $(BUILD)/romgate_alloc.out; exit 1; }
	@$(PY) allocator/no_literals.py --map $(BUILD)/romgate/symbol_map.json \
	    $(ROM_UNBACKED_SRC)/main_backed.asm > $(BUILD)/romgate_ok.out 2>&1; \
	  if [ $$? -ne 0 ]; then \
	    cat $(BUILD)/romgate_ok.out >&2; \
	    echo "rom-unbacked FAILED: the gate REFUSED the backed control arm — it"; \
	    echo "        fires on claim sites that are present, so a green"; \
	    echo "        violation arm would prove nothing"; exit 1; fi
	@$(PY) allocator/no_literals.py --map $(BUILD)/romgate/symbol_map.json \
	    $(ROM_UNBACKED_SRC)/main_unbacked.asm > $(BUILD)/romgate_bad.out 2>&1; \
	  st=$$?; \
	  if [ $$st -eq 0 ]; then \
	    echo "rom-unbacked FAILED: the gate ACCEPTED $(ROM_UNBACKED_SRC)/main_unbacked.asm —"; \
	    echo "        a rom claim with no .incbin anywhere; the backing gate has"; \
	    echo "        no teeth (this is the grad_tabs shape, docs/37 §1)"; exit 1; fi; \
	  grep -q "ROM CLAIM UNBACKED" $(BUILD)/romgate_bad.out || { \
	    echo "rom-unbacked FAILED: refused, but NOT with ROM CLAIM UNBACKED — it"; \
	    echo "        fired for the wrong reason (see $(BUILD)/romgate_bad.out)"; \
	    exit 1; }; \
	  grep -q "ES_R_FIXTURE_BLOB'" $(BUILD)/romgate_bad.out || { \
	    echo "rom-unbacked FAILED: the plain (literal-assert) claim was not"; \
	    echo "        reported (see $(BUILD)/romgate_bad.out)"; exit 1; }; \
	  grep -q "ES_R_FIXTURE_TILES_T0'" $(BUILD)/romgate_bad.out || { \
	    echo "rom-unbacked FAILED: the bank_tiled (templated) chunk was not"; \
	    echo "        reported (see $(BUILD)/romgate_bad.out)"; exit 1; }; \
	  if grep -q "ES_R_FIXTURE_EXTERN" $(BUILD)/romgate_bad.out; then \
	    echo "rom-unbacked FAILED: the backed_by-declared claim was reported as"; \
	    echo "        unbacked — the escape hatch is not being honoured"; exit 1; fi; \
	  echo "rom-unbacked OK: backed arm accepted, unbacked arm refused (plain +"; \
	  echo "        templated claims named, declared backed_by honoured) —"; \
	  echo "        rom-claim backing gate intact"

# ---- the feature register: generate the supply half from the tree ---------
# docs/08 acceptance 5, closed by the work item. `register` CHECKS and
# prints the diff; `register-write` regenerates. That split follows
# `make measure`, which runs pin_budgets --check rather than re-pinning: every
# target in the gate list is a check, so none of them can quietly rewrite the
# thing it is supposed to be proving.
#
# The checker also reads the prose that cites the census — never rewriting a
# word of it. Three of the four recorded register-drift instances lived in that
# prose, so a census-only generator would have caught one of four.
#
# What that check actually covers, stated narrowly because it was documented
# far wider than it reached (measured at 5 of 30 demand rows): in
# docs/09, a TABLE ROW that resolves to an existing dir — via
# its subject cell or its `supplied by` column — may not also say not built /
# not started / unimplemented / TODO / pending / ❌; no live row in §5 may
# resolve to an existing dir at all; and a `engine/features/X` citation must
# name a real dir. It does NOT read paragraphs, and it cannot resolve a row
# that names no dir in either place. The target prints its reach
# ("demand lint reached N/M demand rows") so that residual stays visible.
register:
	$(PY) tools/gen_register.py --check

register-write:
	$(PY) tools/gen_register.py --write

# ---- rail-registered: a game/ rail is TWELVE edits, not one ---------------
# Adding a rail under game/ has to be registered in twelve places, and four
# of the first six have each been missed at least once across successive waves
# 1-5 . One of the six is
# silent AND points the wrong way: a map in conftest.MAPS but not in
# conftest._SUBDIR_MAP leaves `_map_of()` falling back to the TOY map, so the
# rail's freshness goes unchecked while its module demands `make toy` -- which
# reads as a missing prerequisite rather than an unregistered rail.
#
# `` §5 documented two of the lists; a later brief said four; the
# gate shipped checking six; a later review measured ELEVEN — two rails went
# green on the six sites the gate knew and still tripped over
# bare_check.sh's two lists, the freshness guard's reviewed dict, AGENTS.md's
# build-first block, and this file's own `determinism:` prereqs), so the gate
# checked all eleven. A TWELFTH landed with the prerequisite
# change: the `test:` prerequisite list, which is what now
# makes "the tree must be pre-built" a fact of the build rather than a
# sentence in a comment. Same shape as `register`: derived from
# the tree (rails are the game.toml dirs; a rail's map comes from the
# Makefile's own allocate.py invocation), read-only, seconds-scale, it names
# WHICH site is missing for WHICH rail, and its summary prints the count of
# site checks that ran so a disarmed pass reads as disarmed.
rail-registered:
	@$(PY) tools/rail_registered.py

# ---- push: the documented front door for shipping a commit ----------------
# Runs the SECONDS-scale gate set (register + width-check + toy-bad +
# rom-unbacked, ~0.1-0.3 s each) as ordinary prerequisites, then delegates to
# `git push`. `rom-unbacked` is toy-bad's presence-side twin and was missing
# from this set, from the pre-push hook and from CI's own step when it landed —
# covered only indirectly through `make test`. It measures ~0.3 s,
# well inside this target's SECONDS-scale bar, and nothing argued for excluding
# it. The same
# gates also run in tools/git-hooks/pre-push (installed by tools/setup.sh via
# `git config core.hooksPath tools/git-hooks`), so on a hook-installed clone
# they run twice — a deliberate choice: prerequisites here mean this target
# FAILS CLOSED on a clone where setup.sh has not run and the hook is absent,
# instead of silently degrading to a bare push (the fails-open pattern the
# toy-bad history above exists to warn about). The double run costs under a
# second on a green tree.
#
# `-u origin HEAD` rather than a bare `git push`, so the FIRST push of a new
# branch works too. A bare push exits 128 ("no upstream configured") the moment
# a branch was created without -u or was renamed — which is every worktree-
# isolated work item branch, so the documented front door failed on its own first
# use and each session hand-rolled `git push -u origin HEAD` past the gates
# `HEAD` resolves to the current branch, so this stays a
# push of what you are on; on a branch that already has an upstream it is the
# same push with the tracking ref reasserted. Emergency bypass, for a
# deliberately-red WIP push: `git push --no-verify` (guardrail, not a prison —
# CI will still report the red you chose to ship).
push: register width-check time-check toy-bad rom-unbacked
	git push -u origin HEAD

# ---- gates: the whole documented gate block as one target -----------------
# Runs every gate in AGENTS.md's documented order — toy, toy-bad, width-check, register,
# measure, microzero, room, test — each PLAINLY (no pipes anywhere: a
# pipeline returns tail's status, which has pushed a red suite here; this
# target exists so nobody hand-rolls the sequence and reinvents that bug),
# each exit code captured individually, one summary table at the end, plus
# both game ROMs' md5s so verifying the render against a known binary is one
# glance.
#
# Failure policy: a red gate does NOT stop the run — the remaining gates
# still execute so one pass reports the whole tree's state — EXCEPT
# `make test` (~8 min), which is skipped once an earlier gate has failed:
# a broken tree means a fix-and-rerun anyway, and the suite would mostly
# re-report what the summary already names. Overall exit = the FIRST
# failure's captured code (make itself then reports 2, as it does for any
# recipe failure — see the toy-bad block above).
#
# ONE GATE IS EXEMPT FROM THE SKIP DECISION: `measure`. It still runs, it
# still marks the summary FAILED, and it still sets the overall exit — its
# POLARITY IS UNCHANGED, it is a gate in every sense. What it no longer does
# is suppress the suite. The reason is measured and pre-existing:
# `measure` drives the LEGACY free-running MesenRunner, which
# wedges intermittently — measured 4 pass / 1 fail over 5 invocations on an
# idle box, with a `TimeoutError: the emulated frame counter has not advanced
# for 30.0s`. Because `measure` runs BEFORE `test` in this sequence, one flake
# skipped the ~8-minute suite, and the audit lost its suite run to exactly
# that; it then had to run `make test` separately to learn anything about the
# tree it was auditing. A gate that is red 1 run in 5 for reasons unrelated to
# the tree must not be able to decide whether the tree gets tested.
#
# So: `test` runs unless a gate OTHER THAN measure failed. A measure-only red
# leaves the summary reading `measure FAILED` and `test ok` side by side,
# which is the honest picture — one flaky legacy-runner gate red, the suite
# green — and the final line still says FIRST FAILURE = measure, still
# non-zero. Nothing is being waved through: what changes is only WHICH
# failures are allowed to cost you the other eight minutes.
#
# The proper fix is a later stage of the docs/53 lockstep migration, which removes
# the free-running runner from `measure` altogether. Until then this keeps
# the flake's blast radius to one summary line. If `measure` ever becomes
# deterministic, delete the exemption — it exists for a measured flake rate,
# not for a permanent belief about the gate.
gates: | $(BUILD)
	@rm -f $(BUILD)/gates_summary.txt; overall=0; first=""; blocking=""; \
	run() { \
	  printf '\n=== gates: make %s ===\n' "$$1"; \
	  $(MAKE) "$$1"; rc=$$?; \
	  res=ok; if [ $$rc -ne 0 ]; then res=FAILED; fi; \
	  printf '  %-12s %-8s exit %s\n' "$$1" "$$res" "$$rc" \
	    >> $(BUILD)/gates_summary.txt; \
	  if [ $$rc -ne 0 ] && [ -z "$$first" ]; then first="$$1"; overall=$$rc; fi; \
	  if [ $$rc -ne 0 ] && [ "$$1" != measure ] && [ -z "$$blocking" ]; then \
	    blocking="$$1"; fi; \
	}; \
	run cleanroom; \
	run toy; run toy-bad; run rom-unbacked; run width-check; run time-check; \
	run register; \
	run rail-registered; run measure; \
	run microzero; run room; run breaker; run shmup; run platformer; \
	run hud_game; \
	run split_v_fight; run m7_dungeon; run split_h_2p_demo; \
	run sh2-variants; \
	run mode7_explore; run platformer_stream; run scroller; \
	run camera_follow; run maze; run jumper; run patrol; \
	run sprite_game; \
	run stomper; \
	run scroll_run; run split_h_demo; run shd-autodemo; \
	run brawler; \
	run split_h_matrix_demo; run split_h_persp3_demo; \
	run split_v_demo; run svd-nowin; \
	run split_v_seamtrial; \
	run split_h_persp_demo; run shp-autodemo; run racer; \
	run mode7_chamber; run railshooter; \
	run m7_oshoot; run rpg; run boss; run boss_saucer; run meteor_event; \
	run mode7_flight; \
	run seam_irq_trial; run sit-origin; run sit-mistime; \
	run split_h_irq_grad_demo; run shg-nograd; run shg-origin; \
	if [ -z "$$blocking" ]; then run test; else \
	  printf '  %-12s %-8s (earlier gate failed: %s)\n' test skipped "$$blocking" \
	    >> $(BUILD)/gates_summary.txt; fi; \
	printf '\n---- make gates summary (the documented gate block) ----\n'; \
	cat $(BUILD)/gates_summary.txt; \
	for rom in microzero room breaker shmup platformer split_v_fight m7_dungeon \
	           split_h_2p_demo mode7_explore platformer_stream hud_game \
	           scroller camera_follow maze jumper patrol sprite_game \
	           stomper scroll_run brawler \
	           split_h_matrix_demo split_h_persp3_demo split_v_demo \
	           split_v_seamtrial split_h_demo split_h_persp_demo \
	           racer mode7_chamber railshooter m7_oshoot mode7_flight rpg boss \
	           boss_saucer meteor_event seam_irq_trial \
	           split_h_irq_grad_demo; do \
	  if [ -f $(BUILD)/$$rom.sfc ]; then \
	    m=$$(md5sum $(BUILD)/$$rom.sfc); \
	    printf '  %s.sfc md5 = %s\n' "$$rom" "$${m%% *}"; \
	  else \
	    printf '  %s.sfc md5 = (not built)\n' "$$rom"; \
	  fi; \
	done; \
	if [ -z "$$first" ]; then printf 'gates: ALL GREEN\n'; else \
	  printf 'gates: FIRST FAILURE = %s (exit %s)\n' "$$first" "$$overall"; fi; \
	exit $$overall

# ---- bare-check: the landing gate (replaces the CI push trigger) ----------
# `make gates` runs in THIS tree, which is exactly what it cannot vouch for:
# your uncommitted files are on the build path, and last run's build/ artifacts
# can make a target a no-op (the documented probe_vblank defect, missed locally
# three times). bare-check clones HEAD into a scratch dir and runs the gate
# block there — so it sees only committed content, no stale artifacts, and
# nothing outside the clone.
#
# It writes build/bare_check.json: the SHA, the per-gate verdicts, the suite
# summary and the eight ROM md5s. That file is the citable result the landing
# rule now asks for, in place of a CI run id.
#
# XDIST is passed through to the suite inside the clone (default 2). It runs a
# suite of its own: do not run `make test` at the same time.
bare-check:
	@bash tools/bare_check.sh

# ---- tests ----------------------------------------------------------------
# Runs the suite WITHOUT masking its exit code, and keeps the full log.
# `pytest -q | tail` reports TAIL's status, not pytest's — that masked a red
# suite once and cost a review the diagnostic of the one
# flake it caught. Redirect first, tail after: the summary stays readable and
# the status stays true. (Deliberately no `set -o pipefail`: the Makefile
# sets no SHELL, so recipes run under /bin/sh where it is not portable and
# silently does nothing.)
#
# XDIST=N runs the suite on N pytest-xdist workers: `make test XDIST=3`.
# UNSET IS THE DEFAULT and stays single-threaded, so a local `make test` is
# the command it has always been — CI opts in explicitly, in one place, where
# the choice is reviewable next to the number that justified it.
#
# Two things make the suite safe to parallelise, and both are load-bearing:
# each worker gets its own Mesen home (tests/conftest.py, so no two workers
# share a Screenshots/ or a Saves/*.srm), and the modules that plant into this
# repo's working tree hold an exclusive lock (also tests/conftest.py). The
# tree must also be PRE-BUILT — several fixtures shell out to `make`, and on a
# cold tree two workers race the same object file. CI builds toy, microzero,
# room and probes in earlier steps for exactly this reason; locally,
# `make toy microzero room` first.
XDIST ?=
PYTEST_DIST := $(if $(strip $(XDIST)),-n $(strip $(XDIST)),)

# `-rs` prints the REASON for every skip in the short summary. AGENTS.md says
# "read the skip count as a defect signal" — but the surface everyone actually
# reads (`-q`'s last line, and the CI step's tail) prints a bare NUMBER, and a
# number cannot be read as a signal. CI reported "3 skipped" against a tree
# that reports 0 locally, and answering "which three?" took a git unshallow, a
# decorator census and a run of the CI logs. With `-rs` the run answers it
# itself. Costs three lines of output on a green run.
#
# THE PREREQUISITE LIST IS THE DEFUSAL OF THE MISATTRIBUTING xdist CRASH
# (pre-existing). The "PRE-BUILT" precondition
# above used to be prose only, and breaking it produced the worst diagnostic
# in the repo: EIGHT modules read their rail's symbol_map.json at MODULE
# SCOPE, so the freshness guard refuses at COLLECTION time; under `-n` a
# worker-side collection failure surfaces as
#
#     INTERNALERROR> AssertionError: ('tests/test_allocator.py::test_good_toy_
#     allocates_non_overlapping', <WorkerController gw3>)
#     no tests ran in 0.73s
#
# — an INTERNALERROR naming an INNOCENT module (test_allocator.py is pure
# Python and passes alone, and alone under -n 2 and -n 4). Serially the same
# tree names the real cause in one line ("build/bk/symbol_map.json is
# MISSING ... Minimal fix for this module: make breaker"). The audit spent
# real time on this and then reproduced it identically on the pre-batch-2
# base 564574e, so it is neither new nor anyone's port.
#
# Making the list a PREREQUISITE means `make test` cannot be run against an
# unbuilt rail at all — the tree is warm before pytest is invoked, which also
# removes the second race the prose warns about (fixtures that shell out to
# `make` while two workers share build/*.o). This mirrors `determinism:`'s
# prerequisite list, which exists for the same reason one module at a time.
#
# The list is AGENTS.md's BUILD-FIRST block, verbatim: every rail, plus
# `probes` and the `sh2-variants` fixture ROMs. `tools/rail_registered.py`
# site 12 keeps it equal to the set of rails under game/ — a rail added
# without landing here would restore exactly the failure above.
#
# RESIDUAL, stated rather than papered over: this defuses `make test`, not
# `pytest`. A direct `python3 -m pytest tests/ -n 4` on a cold tree still
# produces the misattributing INTERNALERROR, because the refusal happens
# inside pytest's collection and nothing outside `make` runs first. Fixing
# THAT means changing how the guard reports under xdist, which is a different
# work item.
test: toy microzero room probes breaker shmup platformer split_v_fight \
	m7_dungeon split_h_2p_demo sh2-variants mode7_explore platformer_stream \
	hud_game scroller camera_follow maze jumper patrol sprite_game stomper \
	scroll_run brawler split_h_matrix_demo split_h_persp3_demo \
	split_v_demo svd-nowin split_v_seamtrial split_h_demo shd-autodemo \
	split_h_persp_demo shp-autodemo racer mode7_chamber railshooter \
	m7_oshoot rpg boss boss_saucer meteor_event mode7_flight seam_irq_trial \
	sit-origin sit-mistime \
	split_h_irq_grad_demo shg-nograd shg-origin | $(BUILD)
	@$(PY) -m pytest tests/ -q -rs $(PYTEST_DIST) > $(BUILD)/pytest.log 2>&1; rc=$$?; \
	  tail -n 20 $(BUILD)/pytest.log; \
	  echo "--- full log: $(BUILD)/pytest.log (exit $$rc) ---"; exit $$rc

# ---- measurement + write-back -------------
# pin-or-check: pin_budgets.py writes the pins while the substrate still
# carries MEASURE placeholders, and thereafter CHECKS fresh measurements
# against the pinned values (vblank exact, cpu within 5%) — so this target
# stays green on an agreeing re-measure and goes red on real drift.
measure: probes
	$(PY) -m pytest tests/test_measure_vblank.py tests/test_measure_cpu.py \
		tests/test_measure_rebuild.py -q
	$(PY) allocator/pin_budgets.py

# ---- the clean-room name tripwire ----------------------------------------
# A denylist scan of committed text (and of committed zips' text members) for
# retail game, company and hardware brand names, plus a filename-class and an
# oversize check. It is a FLOOR, not a guarantee — a wordlist cannot be
# complete, and the high-risk artifacts (copied assets, broken attribution) are
# guarded by NOTICE and by the per-pack provenance READMEs under vendor/art/,
# not by grep. Cheapest of the three, so it runs first: a name that should not
# be in the tree is worth catching before eight minutes of ROM builds.
#
# Two normalisations, both because the naive form certifies nothing: the
# patterns are anchored on "not an alphanumeric" rather than on `\b`, so a name
# embedded in a snake_case identifier or a filename is a hit too (`\b` treats
# `_` as a word character and is blind to exactly that); and the multiword
# titles are swept again over a comment-JOIN view, because a line grep cannot
# see a title a comment reflow broke across a wrap.
#
# Exemptions live in tools/cleanroom_allow.txt as `path<TAB>substring`, and
# adding one is a conscious act — see that file's header. The gate prints how
# much it swept and how many hits the allowlist absorbed, so a disarmed pass
# does not read as a clean one.
cleanroom:
	@bash tools/cleanroom_check.sh

# ---- width-tracking lint (CLAUDE.md critical rule 6) ----------------------
# STRICT: no baseline file, zero findings tolerated. Measured clean at
# extraction (0 findings across 19 files), so there is nothing to grandfather
# — and no baseline file that can quietly grow to hide a regression.
#
# Scope is this repo's OWN assembly. vendor/ is frozen and stays out
# — with one correction: the probes under vendor/probes/ are
# NOT all frozen. probe_vblank.asm and probe_vb2reg.asm are first-party superforge code,
# allocator-mapped and no-literals-gated (see the probe recipes below), so they
# were on the wrong side of the line and the gate simply was not watching them.
# Both measure clean, so bringing them in costs nothing and keeps the zero
# baseline honest.
#
# The exclusion is now BY NAME rather than by directory, so a probe added later
# is covered by default instead of silently escaping. probe_cpu_ref.asm is
# the vendored reference scene, instrumented (vendor/probe_ref/README.md) — 7
# findings in frozen code nobody here is going to fix, which is what the
# whole-directory exclusion existed for.
#
# The same gate is asserted from pytest (tests/test_width_lint.py::
# test_repo_width_lint_is_clean) so a violation fails the suite too, not only
# this target. That list mirrors this one — keep them together.
WIDTH_LINT          = $(PY) tools/width_lint.py
WIDTH_LINT_SALVAGE  = vendor/probes/probe_cpu_ref.asm
WIDTH_LINT_TARGETS  = engine game \
                      $(filter-out $(WIDTH_LINT_SALVAGE),$(wildcard vendor/probes/*.asm))

width-check:
	@$(WIDTH_LINT) $(WIDTH_LINT_TARGETS) --summary

# ---- time-check: the TIME-COUPLING gate (docs/45) -------------------------
# The sibling of width-check, for the class that has cost this repo the most
# per hour: a test whose result is a function of HOST LOAD. AGENTS.md has
# carried the rule as prose since and the tree carried 22 violating
# call sites anyway; prose is not a gate.
#
# Scope is tests/ + tools/ — the two places emulator-driving Python lives.
# vendor/ is deliberately OUT: mesen_runner.py IMPLEMENTS the wall-clock
# primitives, and a gate that flags its own subject is noise.
#
# THE BASELINE IS CURRENTLY EMPTY, and that is the shipped state — the
# work item drove all 56 findings to zero rather than grandfathering them.
# Adding an entry needs a reason in the PR; the override
# (`# WALL-CLOCK: ok — <reason>`) is the in-tree way to express a
# legitimate exception, and it keeps the reason NEXT TO THE CODE, where a
# reviewer sees it. A baseline entry does not.
TIME_LINT          = $(PY) tools/no_wallclock.py
TIME_LINT_BASELINE = reports/time_lint_baseline.json
TIME_LINT_TARGETS  = tests tools

time-check:
	@$(TIME_LINT) $(TIME_LINT_TARGETS) --baseline $(TIME_LINT_BASELINE) --summary

# ---- falsify: prove the gates still have teeth (docs/46) ------------------
# NOT part of `make gates` and deliberately not in the push set: it plants
# defects into the working tree and rebuilds ROMs, so it costs minutes and
# must not run beside a suite. Run it when you add a gate, when you change
# an assertion a plant targets, and at a phase boundary.
#
#   make falsify                 every plant set under tools/plants/
#   make falsify SET=col_map_kernel
#   make falsify ONLY=binding-CM_FLAGS
#
# Exit 0 iff every selected plant FIRED and the tree restored EXACTLY (the
# artifact md5 came back). A plant that did not reach the artifact is
# reported as a failure of the PLANT, separately from a test that could not
# see a defect that did reach it — the two call for opposite responses.
SET  ?=
ONLY ?=

falsify:
	@$(PY) tools/falsify.py $(SET) $(if $(ONLY),--only $(ONLY))

# The D-DH5 determinism gate (docs/53): run MODULE twice in
# fresh processes and require every recorded Machine read and every PNG
# hash BIT-IDENTICAL — not merely green twice. Exit 0 = the property held
# (toy-bad's non-inverted polarity; a deterministically-RED module with
# identical manifests still passes, and the summary says so — a
# reproducible red is a finding, not a gate failure). Needs the lockstep
# core (vendor/mesen_patches/apply.sh; setup.sh step 3a builds it).
# `make determinism FALSIFY=1` runs the planted sensitivity+liveness
# control instead. NOT in `make gates` — it runs a pytest module of its
# own, twice, and must not race a live suite (same reason as falsify).
# THE MODULE LIST GROWS WITH THE SWEEP. The gate compares ONE module's two
# manifests per invocation, so "the list" is this target's rail prerequisites
# plus whatever `MODULE=` names — every lockstep-native module a landed rail
# ships is expected to be green here, and its rail belongs in the prerequisites
# so the ROM exists when someone runs it:
#     make determinism MODULE=tests/test_scroller.py
MODULE  ?= tests/test_split_h_2p_sprites.py
FALSIFY ?=
determinism: split_h_2p_demo sh2-variants microzero hud_game scroller \
	camera_follow maze jumper patrol sprite_game stomper scroll_run \
	brawler split_h_matrix_demo split_h_persp3_demo \
	split_v_demo svd-nowin split_v_seamtrial split_h_demo shd-autodemo \
	split_h_persp_demo shp-autodemo racer mode7_chamber railshooter \
	m7_oshoot rpg boss boss_saucer meteor_event mode7_flight seam_irq_trial \
	sit-origin sit-mistime \
	split_h_irq_grad_demo shg-nograd shg-origin
	@$(PY) tools/determinism_gate.py --module $(MODULE) $(if $(FALSIFY),--falsify)

clean:
	rm -rf $(BUILD)

# ---- rpg: the top-down RPG -------------------
# A Mode 7 perspective overworld walked on a tile grid, a MOSAIC WIPE into a
# Mode 1 town, an OPAQUE BG3 dialog box with paged text, a battery save, and
# music across every swap. It debuts ONE engine feature: `dialog`.
#
# TAD objects are linked, like `room`'s: tad_rom is in this game's globals, so
# the link is three objects and the wrapper needs THIS game's emitted map for
# its allocator<->linker bridge asserts.
RPG      := game/rpg
RPG_MAP  := $(BUILD)/rpg
RPG_ASM  := $(RPG)/main.asm $(wildcard $(RPG)/scenes/*.asm) \
            $(wildcard engine/features/*/*.asm)
RPG_ASSETS := $(BUILD)/assets/rpg_m7.bin $(BUILD)/assets/rpg_col.bin \
              $(BUILD)/assets/rpg_flags.bin $(BUILD)/assets/rpg_m7_pal.bin \
              $(BUILD)/assets/rpg_town_chr.bin $(BUILD)/assets/rpg_town_map.bin \
              $(BUILD)/assets/rpg_town_pal.bin $(BUILD)/assets/rpg_obj_chr.bin \
              $(BUILD)/assets/rpg_obj_pal.bin
DLG_ASSETS := $(BUILD)/assets/dlg_chr.bin $(BUILD)/assets/dlg_pal.bin

$(RPG_ASSETS): tools/gen_rpg_assets.py | $(BUILD)
	$(PY) tools/gen_rpg_assets.py $(BUILD)/assets

$(DLG_ASSETS): tools/gen_dialog_assets.py | $(BUILD)
	$(PY) tools/gen_dialog_assets.py $(BUILD)/assets

rpg-assets: $(RPG_ASSETS) $(DLG_ASSETS)

$(RPG_MAP)/engine_state_globals.inc $(RPG_MAP)/symbol_map.json: \
		allocator/substrate.toml allocator/allocate.py allocator/schemas.py \
		$(wildcard engine/features/*/feature.toml) $(RPG)/game.toml \
		$(RPG)/state.toml | $(BUILD)
	$(PY) allocator/allocate.py --game $(RPG) --features-dir engine/features \
		--out $(RPG_MAP)

# -I every feature dir whose asm this composition includes, PLUS $(RPG_MAP) for
# the emitted maps, $(VROM) for the header/init/reset and $(RPG) for the scenes.
RPG_INC := -I $(RPG_MAP) -I $(VROM) -I $(RPG) \
           -I engine/features/scene_mgr -I engine/features/input \
           -I engine/features/oam_sprites -I engine/features/fade \
           -I engine/features/mosaic -I engine/features/save \
           -I engine/features/bg_text -I engine/features/split_band \
           -I engine/features/mode7_persp -I engine/features/col_map \
           -I engine/features/dialog -I engine/features/rpg_floor \
           -I engine/features/rpg_town -I engine/features/rpg_obj \
           -I engine/features/rpg_logic \
           -I vendor/tad -I assets/audio/export

$(BUILD)/rpg_tad_wrapper.o: engine/features/audio/tad_wrapper.asm \
		vendor/tad/tad-audio.s vendor/tad/tad-audio.inc \
		$(RPG_MAP)/engine_state_globals.inc | $(BUILD)
	$(CA65) -I $(RPG_MAP) -I vendor/tad -o $@ $<

$(BUILD)/rpg_tad_data.o: assets/audio/export/tad_audio_data.asm \
		assets/audio/export/tad_audio_data.bin | $(BUILD)
	$(CA65) --bin-include-dir assets/audio/export -o $@ $<

$(BUILD)/rpg.sfc: $(RPG_ASM) $(RPG_MAP)/engine_state_globals.inc \
		$(RPG_ASSETS) $(DLG_ASSETS) \
		$(BUILD)/assets/font_2bpp.bin $(BUILD)/assets/crc16_lut.bin \
		$(BUILD)/assets/poses_ab.bin $(BUILD)/assets/poses_cd.bin \
		$(BUILD)/rpg_tad_wrapper.o $(BUILD)/rpg_tad_data.o \
		$(VROM)/header.inc $(VROM)/init.inc $(VROM)/ppu_reset.inc \
		$(VROM)/lorom_512k.cfg | $(BUILD)
	$(PY) allocator/no_literals.py --map $(RPG_MAP)/symbol_map.json $(RPG_ASM)
	$(CA65) $(RPG_INC) --bin-include-dir $(BUILD)/assets \
		-o $(BUILD)/rpg.o $(RPG)/main.asm
	$(LD65) -C $(VROM)/lorom_512k.cfg -o $@ $(BUILD)/rpg.o \
		$(BUILD)/rpg_tad_wrapper.o $(BUILD)/rpg_tad_data.o
	$(PY) tools/fix_checksum.py $@

rpg: $(BUILD)/rpg.sfc
