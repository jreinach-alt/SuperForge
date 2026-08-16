#!/usr/bin/env python3
"""superforge — pin-or-check the measured budgets in substrate.toml
. Explicit action, never a test side effect:

    make measure                     # probe suites -> build/measurements_*.json,
                                     # then this tool runs pin-or-check
    python3 allocator/pin_budgets.py           # auto: pin when the substrate
                                     # still carries "MEASURE" placeholders,
                                     # CHECK against the pins once pinned
    python3 allocator/pin_budgets.py --check   # force check mode (error if
                                     # the substrate is not pinned yet)

PIN replaces the two "MEASURE" placeholders and regenerates the [measured]
section with full provenance. CHECK re-compares fresh measurements against
the pinned values — vblank must match EXACTLY (it reproduces exactly run
over run); cpu must agree within 5% (the measurement is bounded by the
in-test pass-agreement gate, but hosts differ) — exit 0 with a printed
comparison on agreement, exit 1 with a legible diff on drift. A partial /
hand-edited substrate (one placeholder, one number) is refused: this tool
never guesses which side is authoritative.
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
SUB = SUPERFORGE / "allocator" / "substrate.toml"
VB = SUPERFORGE / "build" / "measurements_vblank.json"
CPU = SUPERFORGE / "build" / "measurements_cpu.json"
REBUILD = SUPERFORGE / "build" / "measurements_rebuild.json"

CPU_TOLERANCE = 0.05            # check mode: |fresh - pin| / pin must be <= 5%


def _load_measurements() -> tuple[dict, dict] | None:
    for p in (VB, CPU):
        if not p.exists():
            print(f"pin_budgets: {p} missing — run `make measure` first",
                  file=sys.stderr)
            return None
    return json.loads(VB.read_text()), json.loads(CPU.read_text())


def _substrate_state() -> tuple[str, dict[str, int]]:
    """Classify substrate.toml:
    'placeholders' unpinned (both frame pins are MEASURE)
    'pinned+arm' frame pins set, arm_cost still MEASURE
    'pinned'            everything pinned (frame pins + arm_cost)
    'partial'           any other mix — hand-edited; refuse to guess
    """
    with open(SUB, "rb") as f:
        d = tomllib.load(f)
    frame = d["frame"]["ntsc"]
    vb, cpu = frame["vblank_usable_bytes"], frame["cpu_worst_frame_mc"]
    arm = d.get("measured", {}).get("vblank", {}).get("arm_cost_bytes", "MEASURE")
    if vb == "MEASURE" and cpu == "MEASURE":
        return "placeholders", {}
    if isinstance(vb, int) and isinstance(cpu, int):
        pins = {"vblank": vb, "cpu": cpu}
        if arm == "MEASURE":
            return "pinned+arm", pins
        if isinstance(arm, int):
            pins["arm"] = arm
            return "pinned", pins
    return "partial", {}


def check(pins: dict[str, int]) -> int:
    """Compare fresh measurements against the pinned substrate values.
    Checks the arm-cost pin too when present in `pins`."""
    loaded = _load_measurements()
    if loaded is None:
        return 2
    vbm, cpum = loaded
    fresh_vb = vbm["vblank_usable_bytes"]
    fresh_cpu = cpum["pin"]["cpu_cycles_per_frame_worst_mc"]

    vb_ok = fresh_vb == pins["vblank"]
    cpu_drift = abs(fresh_cpu - pins["cpu"]) / pins["cpu"]
    cpu_ok = cpu_drift <= CPU_TOLERANCE

    print("pin_budgets --check: fresh measurements vs pinned substrate")
    print(f"  vblank_usable_bytes : pinned {pins['vblank']}, fresh {fresh_vb} "
          f"(exact match required) -> {'OK' if vb_ok else 'DRIFT'}")
    print(f"  cpu_worst_frame_mc  : pinned {pins['cpu']}, fresh {fresh_cpu} "
          f"(drift {cpu_drift * 100:.1f}%, tolerance "
          f"{CPU_TOLERANCE * 100:.0f}%) -> {'OK' if cpu_ok else 'DRIFT'}")
    arm_ok = True
    if "arm" in pins:
        fresh_arm = vbm.get("arm_cost_bytes")
        arm_ok = fresh_arm == pins["arm"]
        print(f"  arm_cost_bytes      : pinned {pins['arm']}, fresh {fresh_arm} "
              f"(exact match required) -> {'OK' if arm_ok else 'DRIFT'}")
    if vb_ok and cpu_ok and arm_ok:
        print("check OK: substrate pins agree with fresh measurements")
        return 0
    print("CHECK FAILED: the pinned substrate no longer matches what the "
          "hardware measures.", file=sys.stderr)
    if not vb_ok:
        print(f"  vblank: pinned {pins['vblank']} B but measured {fresh_vb} B "
              f"— the VBlank probe reproduces exactly; any difference means "
              f"the probe, the emulator core, or the substrate changed",
              file=sys.stderr)
    if not cpu_ok:
        print(f"  cpu: pinned {pins['cpu']} mc but measured {fresh_cpu} mc "
              f"({cpu_drift * 100:.1f}% > {CPU_TOLERANCE * 100:.0f}%) — "
              f"re-examine the scenario driving before considering a re-pin "
              f"(restore the two MEASURE placeholders to re-pin explicitly)",
              file=sys.stderr)
    if not arm_ok:
        print(f"  arm: pinned {pins['arm']} B but measured "
              f"{vbm.get('arm_cost_bytes')} B — the multi-queue probe is "
              f"frame-deterministic; any difference means the probe, the "
              f"emulator core, or the substrate changed", file=sys.stderr)
    return 1


def pin_arm(pins: dict[str, int]) -> int:
    """incremental pin: mains already pinned, arm_cost still MEASURE.
    Guard: fresh mains must agree with their pins BEFORE the arm is written —
    never stack a new pin on top of drifted old ones."""
    loaded = _load_measurements()
    if loaded is None:
        return 2
    vbm, _ = loaded
    arm = vbm.get("arm_cost_bytes")
    if not isinstance(arm, int):
        print("pin_budgets: measurements_vblank.json has no arm_cost_bytes — "
              "re-run `make measure` (the multi-queue test writes it)",
              file=sys.stderr)
        return 2
    if check(pins) != 0:
        print("pin_budgets: refusing to pin arm_cost while the existing pins "
              "drift", file=sys.stderr)
        return 1
    lines_out, replaced = [], False
    for line in SUB.read_text().splitlines():
        if line.startswith('arm_cost_bytes = "MEASURE"'):
            line = (f"arm_cost_bytes = {arm}            "
                    f"# MEASURED (multi-queue probe)")
            replaced = True
        lines_out.append(line)
    if not replaced:
        print("pin_budgets: arm_cost placeholder line not found — hand-edited; "
              "refusing to guess", file=sys.stderr)
        return 2
    SUB.write_text("\n".join(lines_out) + "\n")
    print(f"pinned: arm_cost_bytes={arm} -> {SUB.relative_to(SUPERFORGE)}")
    return 0


def pin() -> int:
    loaded = _load_measurements()
    if loaded is None:
        return 2
    vb, cpu = loaded
    vblank = vb["vblank_usable_bytes"]
    pin_val = cpu["pin"]["cpu_cycles_per_frame_worst_mc"]

    lines_out = []
    replaced = {"vb": False, "cpu": False}
    for line in SUB.read_text().splitlines():
        if line.startswith('vblank_usable_bytes = "MEASURE"'):
            line = (f"vblank_usable_bytes = {vblank}        "
                    f"# MEASURED (deliverable 6.1)")
            replaced["vb"] = True
        elif line.startswith('cpu_worst_frame_mc = "MEASURE"'):
            line = (f"cpu_worst_frame_mc = {pin_val}      "
                    f"# MEASURED (deliverable 6.2) — master clock")
            replaced["cpu"] = True
        lines_out.append(line)
    if not all(replaced.values()):
        print(f"pin_budgets: placeholder lines not found ({replaced}) — "
              f"already pinned or hand-edited; refusing to guess",
              file=sys.stderr)
        return 2
    text = "\n".join(lines_out) + "\n"

    # the [measured] SECTION HEADER is a whole line at the end of the file —
    # match it exactly (a substring match once truncated the file at a
    # comment that mentioned the section name)
    marker = "\n[measured]"
    idx = text.rindex(marker)
    assert text[idx + 1:].startswith("[measured]")
    head = text[:idx + 1]
    ladder_lines = "\n".join(
        f"# {k}: iters/120f = {v['iters_per_120_frames']}, "
        f"work max = {v['work_mc_max']} mc"
        for k, v in cpu["speed_ladder"].items())
    passes = cpu["pin"].get("passes")
    pass_lines = ""
    if passes:
        pass_lines = (
            f"# Pin = MAX over {len(passes)} frame-deterministic passes of the "
            f"winning rung:\n"
            f"# passes {passes} mc, spread "
            f"{cpu['pin'].get('spread_pct', '?')}% (agreement gate: 5%).\n")
    arm = vb.get("arm_cost_bytes")
    arm_line = (f"arm_cost_bytes = {arm}            "
                f"# MEASURED (multi-queue probe)"
                if isinstance(arm, int) else
                'arm_cost_bytes = "MEASURE" # arm pin '
                "(probe cmd 2; pin_budgets)")
    measured = f"""[measured]                      # written by allocator/pin_budgets.py
# Probes: vendor/probes/probe_vblank.asm (allocator-mapped) +
# vendor/probes/probe_cpu_ref.asm (the instrumented copy of the
# reference scene — see make_probe_cpu.py). Cycle-accurate MesenRunner, NTSC.

[measured.vblank]
usable_bytes_per_frame = {vblank}   # largest fully-delivered NMI GP-DMA, 64-B steps
# This is a SINGLE-transfer ceiling (one GP-DMA fired from NMI entry); a real
# frame queues several transfers (OAM + stream rows + HUD), each paying its
# own arm overhead — the multi-queue refinement (closes the single-transfer gap):
# arm_cost_bytes is the per-additional-transfer overhead in byte-equivalents,
# measured by the probe's K-transfer command; the allocator budgets
#   sum(bytes) + arm_cost_bytes * (transfers - 1) <= usable_bytes_per_frame.
{arm_line}
completion_v = {vb['completion_v_at_max']}              # last VBlank line — an honest ceiling
completion_h_dots = {vb['completion_h_at_max']}
old_engine_start_pin = 5500     # the shipped constant was 92% of measured

[measured.cpu]
# THE PIN: worst frame that HOLDS 60 fps game-loop cadence on the reference
# (cruise at vel {cpu['pin']['scenario'].split('@')[1].split(' ')[0]}): work {cpu['pin']['work_mc']} + NMI {cpu['pin']['nmi_mc']} mc = {cpu['pin']['pct_of_frame']}% of 357368.
{pass_lines}worst_60fps_frame_mc = {pin_val}
parked_frame_mc = {cpu['parked']['work_mc_max'] + cpu['parked']['nmi_mc_max']}
# The reference demo's 60fps envelope is NARROW — its naive staging kernel
# ({cpu['stream_row_step']['mc_per_step']} mc per 128-B row, measured below) breaks pose cadence at
# speed while the PPU/HDMA display keeps rendering 60 fps:
{ladder_lines}
# flat-out (vel $3000): pose cadence {cpu['flat_out_vmax']['pose_cadence_hz']} Hz;
# turning (full software pv_rebuild every pose frame): {cpu['turning_rebuild']['pose_cadence_hz']} Hz.
# REQUIREMENT derived from these numbers: the rebuilt streaming
# stage kernel + LUT-driven pose path must beat the naive reference costs
# (engine/mode7_stream.asm + the split_h_2p techniques).

[measured.stream]
row_stage_mc = {cpu['stream_row_step']['mc_per_step']}            # stage one 128-B row from flat ROM (CPU)
row_upload_bytes = 128          # VBlank DMA side: 128 B x 8 mc/B + arm
"""
    SUB.write_text(head + measured)
    print(f"pinned: vblank_usable_bytes={vblank}, cpu_worst_frame_mc={pin_val} "
          f"-> {SUB.relative_to(SUPERFORGE)}")
    return 0


def rebuild_section(existing: str) -> str:
    """Render [measured.rebuild] from build/measurements_rebuild.json.

    Stage 4 writes the REBUILT engine's numbers here, beside —
    not over — the reference pins, because D5 makes the rebuild's
    own certificate the thing that supersedes the reference baseline.

    Idempotent: the section is regenerated from the measurement file every
    run, so this is a write-back, not a one-shot placeholder swap. Only the
    parts Stage 4 has actually measured are emitted; the rest stays absent
    rather than being written as a guess."""
    m = json.loads(REBUILD.read_text())
    c = m["cadence"]
    out = [
        "",
        "[measured.rebuild]",
        "# The REBUILT engine's own certificate (D5): microzero's race scene,",
        "# not the reference scene. Written by allocator/pin_budgets.py from",
        "# tests/test_measure_rebuild.py.",
        "#",
        "# GATE CONDITION 5, cadence half: 60 fps pose cadence HELD at the",
        "# declared max envelope. The surface is the engine's own arithmetic,",
        "# not a timer — the race tick integrates once per frame and the",
        "# harness advances the ROM one frame per oracle step, so a frame the",
        "# loop failed to finish inside its frame shows up as a PERMANENT",
        "# integer divergence from tools/gen_move_lut.Sim. Holding lockstep",
        "# across the window is the statement that every frame's work fit.",
        "# Verified to fire: advancing the oracle one extra step diverges",
        "# position, heading and both sub-pixel accumulators immediately.",
        f"cadence_held = {str(c['held']).lower()}",
        f"cadence_window_frames = {c['window_frames']}",
        f"cadence_hw_frames_elapsed = {c['hw_frames_elapsed']}",
        f"cadence_loop_iterations = {c['loop_iterations']}",
        f"cadence_velocity = 0x{c['velocity']:04X}"
        f"        # declared max, {c['velocity'] >> 8} px/frame",
        f"cadence_turn_steps_per_frame = {c['turn_steps_per_frame']}"
        f"   # declared max turn",
        f"cadence_distinct_poses_applied = {c['distinct_poses_applied']}",
        f"cadence_revolutions = {c['revolutions']}"
        f"        # every heading swept, so every row/col entry mix occurs",
        "",
        "# STILL OWED by Stage 4: isolated row_stage_mc / col_stage_mc for the",
        "# rebuilt kernels versus the 68,578 mc/row reference bar. What exists",
        "# today is an UPPER bound from whole-frame attribution (see",
        "# tests/test_microzero_stream.py) — valid as a bound, since a bound",
        "# below the bar proves the bar is beaten, but not the isolated number",
        "# asks for. That needs in-ROM SLHV latch rings like the",
        "# measurement probe: MesenRunner exposes no usable cycle counter (Mesen's",
        "# CycleCount ticks through WAI and halts during DMA, so busy frames",
        "# read FEWER cycles than idle ones).",
    ]
    marker = "\n[measured.rebuild]"
    if marker in existing:
        existing = existing[:existing.rindex(marker)] + "\n"
    return existing.rstrip("\n") + "\n" + "\n".join(out) + "\n"


def pin_rebuild() -> int:
    """Write back [measured.rebuild]. Runs after the reference pins agree —
    never stack the rebuild's certificate on top of drifted old pins."""
    if not REBUILD.exists():
        print(f"pin_budgets: {REBUILD} missing — run `make measure` first",
              file=sys.stderr)
        return 2
    SUB.write_text(rebuild_section(SUB.read_text()))
    m = json.loads(REBUILD.read_text())["cadence"]
    print(f"  rebuild cadence     : {m['loop_iterations']} loop iterations / "
          f"{m['hw_frames_elapsed']} hardware frames at vel "
          f"0x{m['velocity']:04X} + max turn -> "
          f"{'HELD' if m['held'] else 'LOST'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Pin the measured budgets into substrate.toml, or "
                    "check fresh measurements against the existing pins.")
    ap.add_argument("--check", action="store_true",
                    help="force check mode (error if the substrate is unpinned)")
    args = ap.parse_args(argv)

    state, pins = _substrate_state()
    if state == "partial":
        print("pin_budgets: substrate.toml is partially pinned (an unexpected "
              "mix of placeholders and numbers) — hand-edited; refusing to "
              "guess", file=sys.stderr)
        return 2
    if args.check and state != "pinned":
        print("pin_budgets: --check needs a fully pinned substrate, but "
              "MEASURE placeholders are still present — run without --check "
              "to pin first", file=sys.stderr)
        return 2
    if state == "pinned":
        rc = check(pins)
        # the rebuild certificate is written back only once the reference
        # pins agree — a drifted substrate is not a base to record against
        return rc or pin_rebuild()
    if state == "pinned+arm":
        return pin_arm(pins)
    return pin()


if __name__ == "__main__":
    sys.exit(main())
