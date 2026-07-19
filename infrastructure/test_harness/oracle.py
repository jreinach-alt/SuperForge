"""Oracle manifest schema, loader, and validator — Brick 1 of the generalized
verification loop (spec: docs/snes_homebrew_oracle_loop_spec.md).

This module is the *declarative contract* half of the loop. A template ships an
``oracle.json`` next to its ``main.asm``; this module parses it into typed
dataclasses and enforces, at load time, the discipline that makes
indirect-evidence gates impossible to express (CLAUDE.md "Indirect-Evidence
Tests Are Worse Than No Tests"):

  * the assert vocabulary is *closed* — only named hardware-region reads exist;
  * an "outcome" scenario (one that drives toward / asserts a win-or-lose state)
    MUST carry at least one assertion on a real output region
    (OAM / CGRAM / VRAM / screenshot / SRAM); a win proven by a WRAM state
    variable alone is rejected as tautological;
  * single-axis movement coverage is flagged (the D-9/D-11 both-directions rule).

Brick 1 is schema + loader + validator ONLY — no emulator driving. The drive
and assert *engines* (Bricks 2-4) live elsewhere and import these types.

Manifest format is JSON (decision O-3, revised 2026-06-14: the kit's templates
carry no config files; TOML was a Studio-era convention with no kit-side
precedent, so the machine-first format wins — JSON is stdlib read+write and the
cleanest emission target for agent-generated off-catalog templates).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.test_harness.mesen_runner import MemoryType

SCHEMA_VERSION = 1

# --- closed vocabularies -----------------------------------------------------
# Adding a kind here is a deliberate act; the validator rejects anything else,
# so a manifest cannot smuggle an arbitrary "read this WRAM var and compare"
# success assertion. Bricks 2-4 implement the *behavior* of each kind.

DRIVE_KINDS = {
    "settle",       # release input, advance N frames
    "hold",         # hold a button set N frames
    "script",       # explicit per-frame button list (deterministic)
    "axis_sweep",   # replay the same hold per axis; capture per-axis deltas
    "axis_branch",  # from ONE shared baseline, branch each axis independently
                    # (reload+re-prelude per axis so palette phase + forward
                    # distance match); capture an after-screenshot per branch so
                    # screenshot_axis_diff compares the two endpoints directly.
    "bot",          # named closed-loop navigation policy
    "search",       # bounded input search toward [state].win
    "power_cycle",  # reload the ROM (re-seeds SRAM)
}

# assert kind -> the hardware region it reads. The region drives the
# anti-indirect-evidence rule below.
REGION_OF_ASSERT: dict[str, str] = {
    "oam_entry": "oam",
    "oam_delta": "oam",
    "cgram_palette": "cgram",
    "vram_bytes": "vram",
    "vram_tilemap_count": "vram",
    "bg3_text": "vram",
    "screenshot_pixel": "screenshot",
    "screenshot_blob": "screenshot",
    "screenshot_text": "screenshot",
    "screenshot_changed": "screenshot",  # before/after single-axis pixel diff
    "screenshot_axis_diff": "screenshot",  # two-branch endpoint pixel diff
    "pixels_unchanged": "screenshot",
    "sram_bytes": "sram",
    # WRAM / proxy reads — supplements, never sole evidence for an outcome:
    "state_is": "wram",
    "state_cycled": "wram",
    "heartbeat_advances": "wram",
}
ASSERT_KINDS = set(REGION_OF_ASSERT)

# Regions that count as real hardware output. An outcome scenario needs >=1.
REAL_OUTPUT_REGIONS = {"oam", "cgram", "vram", "screenshot", "sram"}

# Drives whose entire reason for existing is to reach an outcome — their
# scenario is outcome-class regardless of which asserts it carries.
OUTCOME_DRIVE_KINDS = {"bot", "search"}

DIRECTION_OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up"}


class ManifestError(ValueError):
    """A manifest is structurally invalid or violates the test-surface
    discipline. Raised at load time, before any ROM runs."""


# --- typed schema ------------------------------------------------------------

@dataclass
class Assert:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def region(self) -> str:
        return REGION_OF_ASSERT[self.kind]


@dataclass
class Drive:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    drive: Drive
    asserts: list[Assert]
    description: str = ""
    continue_from_previous: bool = False


@dataclass
class Boot:
    magic_addr: int = 0xE000
    magic: bytes = b"SFDB"
    heartbeat_addr: int | None = None


@dataclass
class State:
    addr: int
    values: dict[str, int]
    region: str = "wram"
    win: str | None = None
    lose: str | None = None


@dataclass
class Manifest:
    template: str
    rom: str
    boot: Boot
    scenarios: list[Scenario]
    state: State | None = None
    boot_seconds: float = 0.5
    schema_version: int = SCHEMA_VERSION
    source_path: str | None = None
    # Neutral ROM basename used by fresh_sram to flush the process-global
    # emulator's live battery SRAM out to disk BEFORE deleting the .srm (the
    # unload-flush trap; see _virgin_srm). Defaults to the conventional
    # SRAM-free test ROM; override per-manifest with the "neutral_rom" key.
    neutral_rom: str = "text_test.sfc"
    warnings: list[str] = field(default_factory=list)


# --- parsing -----------------------------------------------------------------

def _req(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise ManifestError(f"{where}: missing required key '{key}'")
    return d[key]


def _as_int(v: Any, where: str) -> int:
    # JSON has no hex literals; accept "0xE016" strings and plain ints.
    if isinstance(v, bool):  # bool is an int subclass — reject explicitly
        raise ManifestError(f"{where}: expected an integer, got a boolean")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 0)
        except ValueError:
            raise ManifestError(f"{where}: '{v}' is not an integer")
    raise ManifestError(f"{where}: expected an integer, got {type(v).__name__}")


def _parse_assert(d: dict, where: str) -> Assert:
    if not isinstance(d, dict):
        raise ManifestError(f"{where}: each assert must be an object")
    kind = _req(d, "kind", where)
    if kind not in ASSERT_KINDS:
        raise ManifestError(
            f"{where}: unknown assert kind '{kind}'. "
            f"Allowed: {', '.join(sorted(ASSERT_KINDS))}"
        )
    params = {k: v for k, v in d.items() if k != "kind"}
    return Assert(kind=kind, params=params)


def _parse_drive(d: dict, where: str) -> Drive:
    if not isinstance(d, dict):
        raise ManifestError(f"{where}: 'drive' must be an object")
    kind = _req(d, "kind", where)
    if kind not in DRIVE_KINDS:
        raise ManifestError(
            f"{where}: unknown drive kind '{kind}'. "
            f"Allowed: {', '.join(sorted(DRIVE_KINDS))}"
        )
    params = {k: v for k, v in d.items() if k != "kind"}
    return Drive(kind=kind, params=params)


def _parse_scenario(d: dict, idx: int) -> Scenario:
    where = f"scenario[{idx}]"
    if not isinstance(d, dict):
        raise ManifestError(f"{where}: each scenario must be an object")
    name = _req(d, "name", where)
    where = f"scenario '{name}'"
    drive = _parse_drive(_req(d, "drive", where), where)
    raw_asserts = _req(d, "assert", where)
    if not isinstance(raw_asserts, list):
        raise ManifestError(f"{where}: 'assert' must be a list")
    asserts = [_parse_assert(a, f"{where} assert[{i}]")
               for i, a in enumerate(raw_asserts)]
    return Scenario(
        name=name,
        drive=drive,
        asserts=asserts,
        description=d.get("description", ""),
        continue_from_previous=bool(d.get("continue_from_previous", False)),
    )


def _parse_boot(d: dict | None) -> Boot:
    if d is None:
        return Boot()
    magic = d.get("magic", "SFDB")
    if isinstance(magic, str):
        magic = magic.encode("ascii")
    return Boot(
        magic_addr=_as_int(d.get("magic_addr", 0xE000), "boot.magic_addr"),
        magic=magic,
        heartbeat_addr=(None if d.get("heartbeat_addr") is None
                        else _as_int(d["heartbeat_addr"], "boot.heartbeat_addr")),
    )


def _parse_state(d: dict | None) -> State | None:
    if d is None:
        return None
    raw_values = _req(d, "values", "state")
    if not isinstance(raw_values, dict) or not raw_values:
        raise ManifestError("state.values must be a non-empty object")
    values = {k: _as_int(v, f"state.values.{k}") for k, v in raw_values.items()}
    win = d.get("win")
    lose = d.get("lose")
    for label, sym in (("win", win), ("lose", lose)):
        if sym is not None and sym not in values:
            raise ManifestError(
                f"state.{label} = '{sym}' is not one of state.values "
                f"({', '.join(sorted(values))})"
            )
    return State(
        addr=_as_int(_req(d, "addr", "state"), "state.addr"),
        values=values,
        region=d.get("region", "wram"),
        win=win,
        lose=lose,
    )


def _identity_from_path(source_path: str) -> tuple[str, str] | None:
    """Derive ``(template, rom_basename)`` from a manifest's on-disk location, or
    ``None`` when the path is NOT a canonical manifest home (so identity is not
    pinned — unit-test fixtures named e.g. ``valid_breaker.json`` are exempt).

    The kit pins a manifest's identity to its PATH so a copied oracle can't
    silently test the ROM it was copied FROM (GAP-1, the cold-start false-green:
    a stale ``"rom":"build/rpg.sfc"`` in a freshly-copied
    ``templates/starstation/oracle.json`` runs the rpg ROM, PASSES, and never
    tests starstation). The two canonical homes ``discover`` walks are:

      * ``templates/<X>/oracle.json``  -> template ``X``,        rom ``build/X.sfc``
      * ``tests/<Y>.oracle.json``      -> template ``<Y>``,       rom ``build/<Y>.sfc``
        (the test-ROM-backed gate, e.g. ``save_test.oracle.json``)

    Only those two filename shapes pin identity; any other ``*.json`` returns
    ``None`` (the validator leaves ``template``/``rom`` required-as-declared).
    ``rom_basename`` is the ``build/<name>.sfc`` form the manifest's ``rom`` field
    should carry (compared by basename so a different prefix still matches)."""
    p = Path(source_path)
    if p.name == "oracle.json":
        name = p.resolve().parent.name           # templates/<X>/oracle.json -> X
    elif p.name.endswith(".oracle.json"):
        name = p.name[: -len(".oracle.json")]     # tests/<Y>.oracle.json    -> Y
    else:
        return None                              # not a canonical home -> not pinned
    return name, f"build/{name}.sfc"


def parse_manifest(data: dict, source_path: str | None = None) -> Manifest:
    """Parse a manifest dict (already JSON-decoded) into a typed Manifest and
    validate it. Raises ManifestError on any structural or discipline failure;
    non-fatal issues land in ``manifest.warnings``.

    Path-pinned identity (GAP-1): when ``source_path`` is known, ``template`` and
    ``rom`` are DERIVED from it by default (both fields are optional in the JSON).
    If the manifest DOES carry them, they MUST agree with the path — a mismatch
    is a hard ManifestError naming both values, so a copied-but-not-re-pointed
    oracle fails LOUDLY instead of green-but-testing-the-wrong-ROM. Without a
    ``source_path`` (a raw dict with no file), both fields stay required."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object at the top level")

    sv = data.get("schema_version", SCHEMA_VERSION)
    if sv != SCHEMA_VERSION:
        raise ManifestError(
            f"schema_version {sv} unsupported (this loader speaks {SCHEMA_VERSION})"
        )

    raw_scenarios = _req(data, "scenario", "manifest")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ManifestError("manifest needs a non-empty 'scenario' list")

    exp_template = exp_rom_basename = None
    if source_path is not None:
        ident = _identity_from_path(source_path)
        if ident is not None:
            exp_template, exp_rom_basename = ident

    # --- template: derive from path; if declared, enforce agreement ----------
    template = data.get("template")
    if template is None:
        if exp_template is None:
            raise ManifestError(
                "manifest: missing 'template' (and no path to infer it)")
        template = exp_template
    elif exp_template is not None and template != exp_template:
        raise ManifestError(
            f"manifest at '{source_path}': declared template '{template}' does "
            f"not match its directory ('{exp_template}'). A copied oracle must "
            f"be RE-POINTED: either set \"template\": \"{exp_template}\" or drop "
            f"the field (it defaults from the path). This guard exists so a "
            f"copied oracle can't silently test the ROM it was copied from "
            f"(GAP-1 false-green)."
        )

    # --- rom: derive from path; if declared, enforce agreement (by basename) -
    rom = data.get("rom")
    if rom is None:
        if exp_rom_basename is None:
            raise ManifestError("manifest: missing 'rom' (and no path to infer it)")
        rom = exp_rom_basename
    elif exp_rom_basename is not None and \
            Path(rom).name != Path(exp_rom_basename).name:
        raise ManifestError(
            f"manifest at '{source_path}': declared rom '{rom}' does not match "
            f"its directory (expected '{exp_rom_basename}'). A copied oracle must "
            f"be RE-POINTED: either set \"rom\": \"{exp_rom_basename}\" or drop "
            f"the field (it defaults from the path). This guard exists so a "
            f"copied oracle can't silently test the ROM it was copied from "
            f"(GAP-1 false-green)."
        )

    manifest = Manifest(
        template=template,
        rom=rom,
        boot=_parse_boot(data.get("boot")),
        scenarios=[_parse_scenario(s, i) for i, s in enumerate(raw_scenarios)],
        state=_parse_state(data.get("state")),
        boot_seconds=float(data.get("boot_seconds", 0.5)),
        schema_version=sv,
        source_path=source_path,
        neutral_rom=str(data.get("neutral_rom", "text_test.sfc")),
    )
    manifest.warnings = _validate(manifest)
    return manifest


def load_manifest(path: str | Path) -> Manifest:
    """Load + validate a manifest from a JSON file on disk."""
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        raise ManifestError(f"manifest not found: {p}")
    except json.JSONDecodeError as e:
        raise ManifestError(f"{p}: invalid JSON — {e}")
    return parse_manifest(data, source_path=str(p))


def discover(*patterns: str, root: str | Path | None = None) -> list[Path]:
    """Find oracle manifest files for the parametrized harness (B.3:
    ``discover("templates/**/oracle.json")``).

    The canonical home for a manifest is next to its template's ``main.asm``
    (``templates/<name>/oracle.json``). Test-ROM-backed manifests with no
    template directory (e.g. the save/SRAM gate, whose ROM is
    ``tests/save_test.asm``) live as ``<rom_stem>.oracle.json`` siblings of
    their ``.asm``; the default patterns cover both. ``root`` defaults to the
    repo root inferred from this module's location (``…/infrastructure/
    test_harness/oracle.py`` -> repo root), so a call with no ``root`` works
    from any cwd. Returns a sorted, de-duplicated list of Paths."""
    if not patterns:
        patterns = ("templates/**/oracle.json", "tests/*.oracle.json")
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    found: set[Path] = set()
    for pat in patterns:
        found.update(p.resolve() for p in base.glob(pat) if p.is_file())
    return sorted(found)


# --- the discipline (anti-indirect-evidence) ---------------------------------

def _is_outcome_scenario(sc: Scenario, manifest: Manifest) -> bool:
    """An outcome scenario claims a terminal result (win/lose). Either it is
    driven by a policy/search whose whole job is to reach one, or it asserts a
    state value the manifest has labelled as win/lose."""
    if sc.drive.kind in OUTCOME_DRIVE_KINDS:
        return True
    if manifest.state is not None:
        terminal = {manifest.state.win, manifest.state.lose} - {None}
        for a in sc.asserts:
            if a.kind == "state_is" and a.params.get("value") in terminal:
                return True
    return False


def _directions_in(drive: Drive) -> set[str]:
    """Movement directions a drive exercises, for the both-axes check."""
    out: set[str] = set()
    if drive.kind in ("axis_sweep", "axis_branch"):
        out |= {a for a in drive.params.get("axes", []) if a in DIRECTION_OPPOSITE}
    elif drive.kind == "hold":
        out |= {b for b in drive.params.get("buttons", []) if b in DIRECTION_OPPOSITE}
    elif drive.kind == "script":
        for frame in drive.params.get("frames", []):
            buttons = frame.get("buttons", []) if isinstance(frame, dict) else []
            out |= {b for b in buttons if b in DIRECTION_OPPOSITE}
    return out


def _validate(manifest: Manifest) -> list[str]:
    """Hard rules raise ManifestError; soft rules return warning strings."""
    warnings: list[str] = []

    seen_names: set[str] = set()
    for sc in manifest.scenarios:
        if sc.name in seen_names:
            raise ManifestError(f"duplicate scenario name '{sc.name}'")
        seen_names.add(sc.name)

        if not sc.asserts:
            raise ManifestError(
                f"scenario '{sc.name}' has no assertions — every scenario must "
                "read at least one output region"
            )

        # state_is references require a declared, consistent [state] block.
        for a in sc.asserts:
            if a.kind == "state_is":
                if manifest.state is None:
                    raise ManifestError(
                        f"scenario '{sc.name}': 'state_is' used but no [state] "
                        "block is declared"
                    )
                v = a.params.get("value")
                if v not in manifest.state.values:
                    raise ManifestError(
                        f"scenario '{sc.name}': state_is value '{v}' is not one "
                        f"of state.values ({', '.join(sorted(manifest.state.values))})"
                    )

        # The load-bearing rule: an outcome cannot be proven by proxy alone.
        if _is_outcome_scenario(sc, manifest):
            real = [a for a in sc.asserts if a.region in REAL_OUTPUT_REGIONS]
            if not real:
                proxy_regions = sorted({a.region for a in sc.asserts})
                raise ManifestError(
                    f"scenario '{sc.name}' is an outcome scenario but asserts "
                    f"only on proxy region(s) {{{', '.join(proxy_regions)}}}. "
                    "Add at least one assertion on a real output region "
                    f"({', '.join(sorted(REAL_OUTPUT_REGIONS))}). "
                    "Anti-indirect-evidence: a win/lose cannot be proven by a "
                    "WRAM state variable alone (see the oracle spec B.4)."
                )

    # Soft rule: both-directions axis coverage (D-9/D-11). Warn, don't fail.
    held: set[str] = set()
    for sc in manifest.scenarios:
        held |= _directions_in(sc.drive)
    for d in ("left", "right", "up", "down"):
        if d in held and DIRECTION_OPPOSITE[d] not in held:
            warnings.append(
                f"axis coverage: '{d}' is driven but its opposite "
                f"'{DIRECTION_OPPOSITE[d]}' never is; movement gates should cover "
                "both directions (prefer drive.kind='axis_sweep'). See the D-9/D-11 "
                "state-cycle-coverage rule."
            )

    return warnings


# =============================================================================
# Brick 2 — the assert engine (region reads; no drives yet).
# =============================================================================
# Each assert kind is a pure read of a hardware region over a *loaded*
# MesenRunner, returning an AssertResult. These are implemented self-contained
# over MesenRunner (NOT via infrastructure/test_harness/visual_assertions.py):
# dryrun_split.sh deliberately does not ship visual_assertions into the kit
# ("no kit test uses them ... written against the parent's eliminated front
# door"), so depending on it would break the oracle in the materialized tree.
# The decode conventions mirror the existing per-template gates exactly
# (e.g. asm_repo_staging/tests/test_breaker.py): tilemap word -> tile id is the
# low 10 bits; OAM slot N is 4 bytes [x, y, tile, attr] at N*4, with X9/size in
# the hi-table at OAM+512.
#
# Drives (settle/hold/script/axis_sweep/bot/search) and the screenshot / 2-sample
# kinds (oam_delta, heartbeat_advances, screenshot_*, sram_bytes round-trip) land
# in Bricks 3-4; the remaining deferred kinds (screenshot_text, state_cycled,
# pixels_unchanged) return a clear "not implemented yet" failure from
# evaluate_assert until a Brick-5 manifest needs them.

_MEM = {
    "wram": MemoryType.SnesWorkRam,
    "vram": MemoryType.SnesVideoRam,
    "oam": MemoryType.SnesSpriteRam,
    "cgram": MemoryType.SnesCgRam,
    "sram": MemoryType.SnesSaveRam,
}


@dataclass
class AssertResult:
    kind: str
    ok: bool
    detail: str
    region_read: str = ""


def _pint(params: dict, key: str, where: str, default: Any = None) -> int:
    if key not in params:
        if default is not None:
            return default
        raise ManifestError(f"{where}: missing param '{key}'")
    return _as_int(params[key], f"{where}.{key}")


def _parse_range(spec: Any, where: str) -> list[int]:
    """Accept a list of ints or a 'lo..hi' string (hi exclusive, matching the
    gates' Python range() convention, e.g. cols '1..31' == range(1, 31))."""
    if isinstance(spec, list):
        return [int(x) for x in spec]
    if isinstance(spec, str) and ".." in spec:
        lo, hi = spec.split("..", 1)
        return list(range(int(lo, 0), int(hi, 0)))
    raise ManifestError(f"{where}: bad range spec {spec!r} (want list or 'lo..hi')")


def _read(runner, region: str, addr: int, n: int) -> bytes:
    return bytes(runner.read_bytes(_MEM[region], addr, n))


def _a_vram_tilemap_count(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    base = _pint(a.params, "base", "vram_tilemap_count")
    stride = _pint(a.params, "row_stride", "vram_tilemap_count", default=64)
    rows = a.params.get("rows")
    if not rows:
        raise ManifestError("vram_tilemap_count: missing 'rows'")
    cols = _parse_range(a.params.get("cols", "0..32"), "vram_tilemap_count.cols")
    tile_in = {int(t) for t in a.params.get("tile_in", [])}
    expect = _pint(a.params, "expect_count", "vram_tilemap_count")
    span = (max(rows) + 1) * stride
    buf = _read(runner, "vram", base, span)
    n = 0
    for row in rows:
        for c in cols:
            off = row * stride + c * 2
            tid = buf[off] | ((buf[off + 1] & 0x03) << 8)
            if tid in tile_in:
                n += 1
    ok = n == expect
    return AssertResult(
        "vram_tilemap_count", ok,
        f"counted {n} cells with tile in {sorted(tile_in)}, expected {expect}",
        f"VRAM[{hex(base)}..]",
    )


def _a_vram_bytes(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    addr = _pint(a.params, "addr", "vram_bytes")
    want = [int(b) for b in a.params.get("bytes", [])]
    got = list(_read(runner, "vram", addr, len(want)))
    ok = got == want
    return AssertResult("vram_bytes", ok, f"got {got} want {want}",
                        f"VRAM[{hex(addr)}]")


def _a_cgram_palette(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    pal = _pint(a.params, "palette", "cgram_palette", default=0)
    colors = a.params.get("colors") or {}
    tol = _pint(a.params, "tolerance", "cgram_palette", default=0)
    buf = _read(runner, "cgram", pal * 32, 32)
    bad = []
    for k, v in colors.items():
        e = int(k)
        want = _as_int(v, f"cgram_palette.colors.{k}")
        got = buf[e * 2] | (buf[e * 2 + 1] << 8)
        if abs(got - want) > tol:
            bad.append(f"entry {e}: got {hex(got)} want {hex(want)}")
    ok = not bad
    return AssertResult("cgram_palette", ok, "ok" if ok else "; ".join(bad),
                        f"CGRAM pal {pal}")


def _a_oam_entry(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    slot = _pint(a.params, "slot", "oam_entry")
    e = _read(runner, "oam", slot * 4, 4)
    hi = _read(runner, "oam", 512 + slot // 4, 1)[0]
    shift = (slot % 4) * 2
    fields = {
        "x": e[0], "y": e[1], "tile": e[2], "attr": e[3],
        "x9": (hi >> shift) & 1, "size": (hi >> (shift + 1)) & 1,
    }
    bad = []
    for key in ("tile", "x", "y", "attr", "x9", "size"):
        if key in a.params:
            want = _as_int(a.params[key], f"oam_entry.{key}")
            if fields[key] != want:
                bad.append(f"{key}: got {fields[key]} want {want}")
    ok = not bad
    return AssertResult("oam_entry", ok, "ok" if ok else "; ".join(bad),
                        f"OAM slot {slot}")


def _a_state_is(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    if m.state is None:
        raise ManifestError("state_is: no [state] block")
    sym = a.params.get("value")
    if sym not in m.state.values:
        raise ManifestError(f"state_is: '{sym}' not in state.values")
    want = m.state.values[sym]
    region = m.state.region if m.state.region in _MEM else "wram"
    raw = _read(runner, region, m.state.addr, 2)
    got = raw[0] | (raw[1] << 8)
    ok = got == want
    return AssertResult("state_is", ok,
                        f"state={got} want {want} ('{sym}')",
                        f"{region.upper()}[{hex(m.state.addr)}]")


_ASSERT_IMPLS = {
    "vram_tilemap_count": _a_vram_tilemap_count,
    "vram_bytes": _a_vram_bytes,
    "cgram_palette": _a_cgram_palette,
    "oam_entry": _a_oam_entry,
    "state_is": _a_state_is,
}


def evaluate_assert(runner, a: Assert, manifest: Manifest, ctx=None) -> AssertResult:
    """Evaluate one assert over a loaded MesenRunner. ``ctx`` is the DriveContext
    from the scenario's drive (carries axis_sweep before/after samples for
    oam_delta / screenshot_changed). Exceptions become a failing AssertResult so
    one bad assert fails its scenario without crashing the run."""
    impl = _ASSERT_IMPLS.get(a.kind)
    if impl is None:
        return AssertResult(
            a.kind, False,
            f"assert kind '{a.kind}' not implemented yet "
            "(implemented: static region reads + oam_delta + screenshot_* + "
            "sram_bytes + heartbeat_advances ; screenshot_text / state_cycled / "
            "pixels_unchanged land in later bricks)",
            REGION_OF_ASSERT[a.kind],
        )
    try:
        return impl(runner, a, manifest, ctx)
    except Exception as exc:  # noqa: BLE001 — surface as a failing assert
        return AssertResult(a.kind, False, f"error: {exc}", REGION_OF_ASSERT[a.kind])


def boot_check(runner, manifest: Manifest) -> AssertResult:
    """Verify the boot magic — the universal precondition every template meets."""
    magic = _read(runner, "wram", manifest.boot.magic_addr, len(manifest.boot.magic))
    ok = magic == manifest.boot.magic
    return AssertResult("boot.magic", ok,
                        f"magic={magic!r} want {manifest.boot.magic!r}",
                        f"WRAM[{hex(manifest.boot.magic_addr)}]")


# =============================================================================
# Brick 3 — the drive engine + verify() orchestrator.
# =============================================================================
# Drives advance the ROM under input; verify() loads the ROM per scenario, runs
# its drive, evaluates its asserts, and aggregates a verdict. Non-outcome drives
# (settle/hold/script/axis_sweep) land here; outcome drives (bot/search) and
# power_cycle land in Brick 4 and report "not implemented yet" until then.
#
# axis_sweep is the both-directions primitive: it replays a hold per axis and
# captures per-axis OAM + (optional) screenshot before/after, which oam_delta and
# screenshot_changed consume. reset_each=True (default) reloads the ROM per axis
# for an independent baseline (paddle-style, matches test_breaker); reset_each=
# False sweeps sequentially (steer-style, matches test_racer where left then
# right rotate the view in turn). An optional prelude (hold a button set once
# before the sweep) reproduces "accelerate, then steer".

import os
import tempfile

_AXIS_BTN = {
    "left": {"left": True}, "right": {"right": True},
    "up": {"up": True}, "down": {"down": True},
}
_AXIS_SIGN = {"right": 1, "left": -1, "down": 1, "up": -1}  # natural +dir per axis
_FIELD_OFF = {"x": 0, "y": 1, "tile": 2, "attr": 3}

# Screen y-bands as fractions of the 224-line NTSC active area; screenshots may
# be overscan/scaled, so callers scale by actual height (see _region_pixels).
_REGION_Y = {"full": (0, 224), "floor": (100, 220), "top": (0, 112),
             "bottom": (112, 224)}

# Named pixel predicates, matching the per-template gates' color tests so a
# manifest reproduces them faithfully (test_sprite_game _RED/_YELLOW, etc.).
_NAMED_PRED = {
    "red": lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90,
    "yellow": lambda p: p[0] > 150 and p[1] > 150 and p[2] < 90,
    "green": lambda p: p[1] > 150 and p[0] < 120 and p[2] < 120,
    "white": lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200,
    "cyan": lambda p: p[0] < 120 and p[1] > 150 and p[2] > 150,
    "grey": lambda p: abs(p[0] - p[1]) < 24 and abs(p[1] - p[2]) < 24 and 60 < p[0] < 200,
    # m7_dungeon dungeonSprites DEMON body — a WARM/BRIGHT orange-red (Wave-D
    # dressing; enemy_pal body ~(224,104,72), rendered ~(231,107,74)). Retuned on
    # the emulator to a byte-exact mirror of tests/test_m7_dungeon _is_enemy_red:
    # r>=205 clears the demon (231) yet rejects every brick wall tone (WALL_LT
    # rendered ~189); g<=130 rejects the bone highlight; b<=110 and r-b>=120 reject
    # the cool floor + the grey knight hero. Only a real demon-body pixel passes,
    # so an invisible / wrong-palette enemy reads 0 (-DENEMY_MISCOLOR is the
    # non-vacuity control). The plain "red" predicate above stays untouched so the
    # other templates' gates are unaffected.
    "enemy_red": lambda p: p[0] >= 205 and p[1] <= 130 and p[2] <= 110 and (p[0] - p[2]) >= 120,
}


@dataclass
class DriveContext:
    ok: bool = True
    detail: str = ""
    before_oam: dict[str, bytes] = field(default_factory=dict)
    after_oam: dict[str, bytes] = field(default_factory=dict)
    before_shot: dict[str, str] = field(default_factory=dict)
    after_shot: dict[str, str] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    asserts: list[AssertResult]
    evidence: list[str]


@dataclass
class OracleVerdict:
    template: str
    passed: bool
    scenarios: list[ScenarioResult]
    used_extension: bool = False
    determinism_ok: bool | None = None


# --- screenshot helpers ------------------------------------------------------

def _load_rgb(path: str):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    # Image.getdata() is deprecated and removed in Pillow 14 (2027-10-15) in
    # favor of get_flattened_data(). Prefer the new method when present, fall
    # back to getdata() on older Pillow.
    flat = getattr(im, "get_flattened_data", im.getdata)()
    return list(flat), im.size[0], im.size[1]


def _region_pixels(data, w, h, region: str):
    y0f, y1f = _REGION_Y.get(region, _REGION_Y["full"])
    y0, y1 = int(y0f * h / 224.0), int(y1f * h / 224.0)
    return data[y0 * w:y1 * w]


def _shot(runner, tag: str) -> str:
    path = os.path.join(tempfile.gettempdir(), f"_oracle_{tag}.png")
    runner.take_screenshot(path)
    return path


def _region_diff_frac(path_a: str, path_b: str, region: str) -> float:
    """Fraction of pixels that differ between two screenshots within `region`.

    Shared by axis_branch's same-direction control gate and the
    screenshot_axis_diff assert so both speak the same units."""
    ad, w, h = _load_rgb(path_a)
    bd, _, _ = _load_rgb(path_b)
    pa = _region_pixels(ad, w, h, region)
    pb = _region_pixels(bd, w, h, region)
    diff = sum(1 for x, y in zip(pa, pb) if x != y)
    return diff / max(1, len(pa))


def _oam(runner) -> bytes:
    return bytes(runner.read_bytes(MemoryType.SnesSpriteRam, 0, 544))


def _btn(spec) -> dict:
    """Accept ['b','left'] or {'b': true} -> set_input kwargs."""
    if isinstance(spec, dict):
        return {k: bool(v) for k, v in spec.items()}
    return {b: True for b in (spec or [])}


# --- drives ------------------------------------------------------------------

def _apply_prelude(runner, pre: dict):
    runner.set_input(0, **_btn(pre.get("buttons", [])))
    runner.run_frames(int(pre.get("frames", 30)))
    runner.set_input(0)
    runner.run_frames(2)


def _drive_axis_sweep(runner, manifest, drive, rom, ctx: DriveContext):
    p = drive.params
    axes = p.get("axes", [])
    frames = int(p.get("frames", 20))
    reset_each = bool(p.get("reset_each", True))
    shots = bool(p.get("screenshot", False))
    prelude = p.get("prelude")
    prev_oam = prev_shot = None
    for i, ax in enumerate(axes):
        if ax not in _AXIS_BTN:
            ctx.ok = False
            ctx.detail = f"axis_sweep: unknown axis '{ax}'"
            return
        if reset_each:
            runner.load_rom(rom, run_seconds=manifest.boot_seconds)
            if prelude:
                _apply_prelude(runner, prelude)
            b_oam = _oam(runner)
            b_shot = _shot(runner, f"{ax}_before") if shots else None
        elif i == 0:
            if prelude:
                _apply_prelude(runner, prelude)
            b_oam = _oam(runner)
            b_shot = _shot(runner, f"{ax}_before") if shots else None
        else:
            b_oam, b_shot = prev_oam, prev_shot
        runner.set_input(0, **_AXIS_BTN[ax])
        runner.run_frames(frames)
        runner.set_input(0)
        runner.run_frames(2)
        a_oam = _oam(runner)
        a_shot = _shot(runner, f"{ax}_after") if shots else None
        ctx.before_oam[ax], ctx.after_oam[ax] = b_oam, a_oam
        if shots:
            ctx.before_shot[ax], ctx.after_shot[ax] = b_shot, a_shot
        prev_oam, prev_shot = a_oam, a_shot


def _drive_axis_branch(runner, manifest, drive, rom, ctx: DriveContext):
    """Branch each axis from ONE shared baseline and capture an after-screenshot
    per branch. Unlike axis_sweep (which is before/after on a single hold, so an
    independently-animating background — the racer's palette-cycling, forward-
    scrolling Mode-7 floor — registers a large diff whether or not steering does
    anything), axis_branch reloads the ROM and re-applies the same prelude before
    EACH axis, so the two branches share an identical palette phase and forward
    distance. The only difference between the two endpoint screenshots is the
    steer direction itself — so screenshot_axis_diff(left, right) is a real-output
    test of "steering rotates the floor", not of "the floor animates". (B.6 row 4,
    audit-1 MED-A: the screenshot_changed form passed on genuinely frozen steering.)

    FRAME-DETERMINISTIC baseline (audit-1 H-1 remediation). The Phase-1/Phase-2
    form equalized the two branches' animation phase with WALL-CLOCK timing —
    ``load_rom(run_seconds=)`` boots a real-time duration, ``run_frames(n)`` sleeps
    n/60 s — so the two branches' boot frame counts JITTERED apart (observed
    park_fc 119 vs 120; the in-ROM heartbeat 111 vs 112). The racer floor is
    animated by a frame-counted palette cycle (PALCYC_SPEED=16) + a frame-counted
    day-night phase machine (tod_update); a few frames of boot jitter lands the
    two branches on opposite sides of a 16-frame CGRAM rotation step, flipping a
    large block of floor pixels — a 29-79% floor diff WITH STEERING FROZEN, which
    spuriously PASSED the discriminator on a broken ROM (~1/14 isolated).

    The fix drives boot-align + prelude + steer hold under
    ``runner.frame_stepping()`` with ``runner.frame_step(n, **buttons)`` so both
    branches advance the SAME number of EXACT frames from a SHARED absolute frame
    floor (``align_frame``). After load, each branch parks (auto-break) at its
    jittery boot frame, then steps forward to the common ``align_frame`` with the
    pad neutral, then runs the identical prelude + steer step counts. Both branches
    therefore reach an identical absolute frame count => identical palette-cycle +
    day-night phase => the only between-branch difference is the steer direction.

    Invariant guard (the structural backstop that converts H-1 from "flaky" to
    "can't regress silently"): after driving both branches, this drive reads each
    branch's heartbeat ($E010, manifest boot.heartbeat_addr) + day-night phase
    ($E014, drive param phase_addr) and FAILS THE DRIVE LOUDLY if they diverge
    across branches. Equal frame count => equal hb/phase => animation phase
    equalized; any future desync (a timing change, a step-count typo) trips the
    guard instead of silently re-opening the spurious-PASS window. The frame-count
    guard is the boot-jitter backstop — necessary, but NOT sufficient for H-1.

    SAME-DIRECTION CONTROL + RETRY ("D_stable+retry", H-1 round-2 remediation;
    default-OFF via ``control_branches``, racer opts in). The audit-2 H-1
    diagnosis (docs/audit/oracle_loop_brick5-h1-diagnosis.md) found a residual
    confounder the frame-count guard is structurally blind to: a per-capture
    render-phase "bucket". On a spurious-PASS spike, EVERY queryable field across
    the branches is byte-identical — R_POSX/Y, R_ANGLE, $E010 heartbeat, $E014
    day-night phase, AND ppu_frame_count() — yet take_screenshot() returns floor
    framebuffers differing 6.5-91%. The bucket is assigned independently to each
    ``load_rom -> align -> prelude -> steer -> capture`` sequence (deterministic
    for a given parked state, but re-rolled per separate load/capture sequence —
    save/load-state does NOT eliminate it, proven empirically). No in-ROM/PPU-frame
    guard can observe it because the frame count is also identical, and no absolute
    threshold separates a 91% frozen bucket from the 42.4% good steering signal.

    The fix: for each axis, capture a PRIMARY and a SAME-DIRECTION CONTROL (both
    drive the identical buttons). The diff(L,R) reading is trusted ONLY when both
    directions are internally bucket-stable — i.e. diff(L,L') <= control_eps AND
    diff(R,R') <= control_eps. When a same-direction control exceeds eps, the
    capture pair is bucket-confounded, so we RE-DRIVE that direction (a fresh
    load_rom re-rolls the bucket draw), up to ``max_retries``. If a direction never
    stabilizes within max_retries the drive FAILS LOUDLY (genuine non-determinism,
    never a silent pass). The control shots are stored under f"{ax}__ctl" so the
    screenshot_axis_diff assert's baseline-stability gate can re-verify them as an
    in-assert backstop.
    """
    p = drive.params
    axes = p.get("axes", [])
    if len(axes) < 2:
        ctx.ok = False
        ctx.detail = "axis_branch: needs >= 2 axes to diff"
        return
    frames = int(p.get("frames", 30))
    prelude = p.get("prelude") or {}
    pre_btn = _btn(prelude.get("buttons", []))
    pre_frames = int(prelude.get("frames", 0)) if prelude else 0
    # Shared absolute PPU-frame floor: chosen above any plausible boot park (~120
    # at boot_seconds=2.0). Both branches step UP to it before the prelude so the
    # boot jitter is fully absorbed and the prelude starts at the same frame on
    # every branch and every run. Override via the drive's "align_frame" param.
    align_frame = int(p.get("align_frame", 130))
    # Invariant-guard addresses: heartbeat from the manifest's boot block;
    # day-night phase from the drive param (defaults to heartbeat_addr + 4, the
    # racer's $E014 layout next to $E010).
    hb_addr = manifest.boot.heartbeat_addr
    phase_addr = p.get("phase_addr")
    if phase_addr is not None:
        phase_addr = _as_int(phase_addr, "axis_branch.phase_addr")
    elif hb_addr is not None:
        phase_addr = hb_addr + 4
    guard = bool(p.get("phase_guard", True)) and hb_addr is not None
    # Same-direction control + retry params (H-1 round-2; default OFF).
    control_branches = bool(p.get("control_branches", False))
    control_eps = float(p.get("control_eps", 0.02))
    control_region = p.get("control_region", "floor")
    max_retries = int(p.get("max_retries", 3))
    branch_hb: dict[str, int] = {}
    branch_phase: dict[str, int] = {}
    # FREEZE-CAPTURE (racer opt-in; default OFF via freeze_button=None). The racer
    # floor ANIMATES every frame independently of steering: a palette cycle, the
    # day-night blend, and forward coast-scroll. take_screenshot after a
    # load->drive carries a 1-frame presentation-lag "render bucket" (see
    # docs/audit/racer-oracle-steer-gate.md): two independent same-direction
    # captures can land one ANIMATED frame apart and read a large spurious floor
    # diff. The S3 racer remediation paces the perspective rebuild across two
    # frames, which widened the bucket until control_branches' retry could no
    # longer land both captures in the same phase (the intermittent
    # "same-direction control diff > eps" failure). The deterministic fix is to
    # stop keying on a lucky bucket and instead FREEZE the floor before capturing:
    # tap the pause button (START) so the palette cycle + day-night clock + camera
    # all stop (main.asm R_PAUSE) — a true freeze-frame that renders identically on
    # every run — while the steered heading (the thing under test) is held. Every
    # branch runs the identical extra frames, so the frame-count / phase guard
    # still holds; freeze_pre lets an in-flight rebuild finish so the frozen floor
    # shows the FINAL angle, freeze_post lets the pause engage, and freeze_addr
    # (R_PAUSE) is read back to prove the freeze actually took (fail-loud).
    freeze_btn = p.get("freeze_button")
    freeze_pre = int(p.get("freeze_settle", 4))
    freeze_post = int(p.get("freeze_post", 6))
    freeze_addr = p.get("freeze_addr")
    if freeze_addr is not None:
        freeze_addr = _as_int(freeze_addr, "axis_branch.freeze_addr")
    freeze_value = int(p.get("freeze_value", 1))
    branch_freeze: dict[str, int] = {}

    def _one_branch(ax, tag):
        """One independent load -> align -> prelude -> steer -> capture. Returns
        the screenshot path; also stamps after_oam[ax] / heartbeat / phase for the
        last primary capture of `ax` (used by oam asserts + the frame-count guard).
        Re-rolls the render-phase bucket per call (fresh load_rom)."""
        # Fresh load, then a FRAME-EXACT prelude => identical baseline for every
        # branch (no wall-clock jitter, unlike run_frames/run_seconds).
        runner.load_rom(rom, run_seconds=manifest.boot_seconds)
        with runner.frame_stepping():
            # Absorb boot jitter: step (neutral) up to the shared frame floor.
            fc = runner.ppu_frame_count()
            if fc < align_frame:
                runner.frame_step(align_frame - fc)
            elif fc > align_frame:
                return None, fc  # signal "parked past align"
            # Identical prelude (hold the prelude buttons for exactly pre_frames).
            if pre_frames > 0:
                runner.frame_step(pre_frames, **pre_btn)
            # Steer hold: exactly `frames` frames with this axis's buttons.
            runner.frame_step(frames, **_AXIS_BTN[ax])
            # Freeze-capture: finish any in-flight rebuild, tap pause to freeze the
            # animated floor, then let the freeze engage — so the screenshot is a
            # deterministic freeze-frame (no palette/day-night/scroll bucket).
            if freeze_btn:
                if freeze_pre > 0:
                    runner.frame_step(freeze_pre)
                runner.frame_step(1, **{freeze_btn: True})
                if freeze_post > 0:
                    runner.frame_step(freeze_post)
                if freeze_addr is not None:
                    branch_freeze[ax] = _read(runner, "wram", freeze_addr, 1)[0]
            shot = _shot(runner, f"branch_{tag}")
            ctx.after_oam[ax] = _oam(runner)  # so oam_delta-style asserts read it
            if guard:
                branch_hb[ax] = _read(runner, "wram", hb_addr, 1)[0]
                if phase_addr is not None:
                    branch_phase[ax] = _read(runner, "wram", phase_addr, 1)[0]
        return shot, None

    for ax in axes:
        if ax not in _AXIS_BTN:
            ctx.ok = False
            ctx.detail = f"axis_branch: unknown axis '{ax}'"
            return
        if not control_branches:
            # Legacy two-branch path (non-racer axis_branch users): one capture.
            shot, past = _one_branch(ax, ax)
            if past is not None:
                ctx.ok = False
                ctx.detail = (f"axis_branch: boot parked at frame {past} past "
                              f"align_frame={align_frame}; raise align_frame")
                return
            ctx.after_shot[ax] = shot
            continue
        # Control-branch + retry: re-drive this direction until its same-direction
        # control diff is <= control_eps (both captures in the same render bucket).
        for attempt in range(max_retries + 1):
            prim, past = _one_branch(ax, f"{ax}_p{attempt}")
            if past is not None:
                ctx.ok = False
                ctx.detail = (f"axis_branch: boot parked at frame {past} past "
                              f"align_frame={align_frame}; raise align_frame")
                return
            ctl, past = _one_branch(ax, f"{ax}_c{attempt}")
            if past is not None:
                ctx.ok = False
                ctx.detail = (f"axis_branch: boot parked at frame {past} past "
                              f"align_frame={align_frame}; raise align_frame")
                return
            ctl_diff = _region_diff_frac(prim, ctl, control_region)
            if ctl_diff <= control_eps:
                ctx.after_shot[ax] = prim
                ctx.after_shot[f"{ax}__ctl"] = ctl
                break
        else:
            # Exhausted retries: a same-direction control never stabilized. The
            # render bucket is genuinely non-deterministic here — FAIL LOUDLY
            # rather than trust a confounded reading (never a silent pass).
            ctx.ok = False
            ctx.detail = (
                f"axis_branch: direction '{ax}' never reached a bucket-stable "
                f"capture in {max_retries} retries (last same-direction control "
                f"diff {ctl_diff:.1%} > control_eps {control_eps:.1%}). The "
                f"render-phase bucket is non-deterministic; the floor diff cannot "
                f"be trusted as a steering signal.")
            return
    # Invariant guard: every branch MUST share the same animation phase (equal
    # frame count). If not, fail the drive loudly — a divergence here means the
    # screenshot diff is confounded by animation, exactly the H-1 spurious-PASS.
    if guard:
        hbs = set(branch_hb.values())
        phs = set(branch_phase.values())
        if len(hbs) > 1 or len(phs) > 1:
            ctx.ok = False
            ctx.detail = (
                "axis_branch animation-phase guard FAILED — branches did not "
                "reach an identical frame count, so the floor diff is confounded "
                f"by palette/day-night animation (heartbeat {branch_hb}, "
                f"phase {branch_phase}). Frame-exact stepping must equalize both."
            )
    # Freeze guard: when freeze-capture is armed, every branch must have actually
    # entered the frozen state, or the "deterministic" capture is a fiction (the
    # floor was still animating and the spurious-diff bucket can return).
    if freeze_btn and freeze_addr is not None and ctx.ok:
        bad = {ax: v for ax, v in branch_freeze.items() if v != freeze_value}
        if bad or not branch_freeze:
            ctx.ok = False
            ctx.detail = (
                f"axis_branch freeze guard FAILED — pause did not engage "
                f"(WRAM ${freeze_addr:04X} != {freeze_value}: {bad or 'unread'}); "
                "the floor was not frozen, so the capture is not deterministic.")


def run_drive(runner, manifest, drive: Drive, rom: str) -> DriveContext:
    ctx = DriveContext()
    p = drive.params
    if drive.kind == "settle":
        runner.run_frames(int(p.get("frames", 30)))
    elif drive.kind == "hold":
        runner.set_input(0, **_btn(p.get("buttons", [])))
        runner.run_frames(int(p.get("frames", 30)))
        runner.set_input(0)
        runner.run_frames(2)
    elif drive.kind == "script":
        for step in p.get("steps", []):
            runner.set_input(0, **_btn(step.get("buttons", [])))
            runner.run_frames(int(step.get("frames", 1)))
        runner.set_input(0)
        runner.run_frames(2)
    elif drive.kind == "axis_sweep":
        _drive_axis_sweep(runner, manifest, drive, rom, ctx)
    elif drive.kind == "axis_branch":
        _drive_axis_branch(runner, manifest, drive, rom, ctx)
    elif drive.kind == "power_cycle":
        # Reload the ROM: the emulator flushes SRAM to .srm on unload and
        # reseeds the fresh instance from it — a real battery power cycle.
        runner.load_rom(rom, run_seconds=manifest.boot_seconds)
        runner.run_frames(int(p.get("frames", 0)))
    elif drive.kind == "bot":
        name = p.get("policy")
        fn = _BOT_POLICIES.get(name)
        if fn is None:
            ctx.ok = False
            ctx.detail = (f"bot policy '{name}' not registered "
                          "(call oracle.register_bot before verify)")
        else:
            try:
                won = fn(runner, manifest, drive)
                ctx.ok = bool(won)
                ctx.detail = "won" if won else "bot did not reach win within caps"
            except Exception as exc:  # noqa: BLE001
                ctx.ok = False
                ctx.detail = f"bot '{name}' error: {exc}"
    elif drive.kind == "search":
        ctx.ok = False
        ctx.detail = "drive 'search' not implemented (behind --experimental-search)"
    else:
        ctx.ok = False
        ctx.detail = f"unknown drive '{drive.kind}'"
    return ctx


# --- Brick 3 asserts (drive-coupled + screenshot) ---------------------------

def _a_oam_delta(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    if ctx is None or not ctx.after_oam:
        raise ManifestError("oam_delta requires an axis_sweep drive")
    slot = _pint(a.params, "slot", "oam_delta")
    field_name = a.params.get("field", "x")
    axis = a.params.get("axis")
    mn = _pint(a.params, "min", "oam_delta")
    if axis not in ctx.after_oam:
        raise ManifestError(f"oam_delta: axis '{axis}' not driven by the sweep")
    off = slot * 4 + _FIELD_OFF[field_name]
    bef, aft = ctx.before_oam[axis][off], ctx.after_oam[axis][off]
    delta = aft - bef
    sign = _AXIS_SIGN.get(axis, 1)
    ok = (delta * sign) >= mn
    return AssertResult(
        "oam_delta", ok,
        f"axis {axis}: slot{slot}.{field_name} {bef}->{aft} "
        f"(delta {delta:+d}, need {sign:+d}*delta >= {mn})",
        f"OAM slot {slot}",
    )


def _a_screenshot_blob(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    region = a.params.get("region", "full")
    data, w, h = _load_rgb(_shot(runner, "blob"))
    px = _region_pixels(data, w, h, region)
    if "distinct_min" in a.params:
        n = len(set(px))
        want = _pint(a.params, "distinct_min", "screenshot_blob")
        return AssertResult("screenshot_blob", n >= want,
                            f"{n} distinct colors in {region} (need >= {want})",
                            "screenshot")
    color = a.params.get("color", "red")
    pred = _NAMED_PRED.get(color)
    if pred is None:
        raise ManifestError(f"screenshot_blob: unknown color '{color}'")
    cnt = sum(1 for p in px if pred(p))
    lo = _pint(a.params, "count_min", "screenshot_blob", default=1)
    hi = a.params.get("count_max")
    hi_i = _as_int(hi, "screenshot_blob.count_max") if hi is not None else None
    ok = cnt >= lo and (hi_i is None or cnt <= hi_i)
    rng = f">= {lo}" + ("" if hi_i is None else f", <= {hi_i}")
    return AssertResult("screenshot_blob", ok,
                        f"{color} px={cnt} in {region} ({rng})", "screenshot")


def _a_screenshot_pixel(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    x = _pint(a.params, "x", "screenshot_pixel")
    y = _pint(a.params, "y", "screenshot_pixel")
    rgb = a.params.get("rgb")
    if not rgb or len(rgb) != 3:
        raise ManifestError("screenshot_pixel: 'rgb' must be [r,g,b]")
    tol = _pint(a.params, "tolerance", "screenshot_pixel", default=24)
    data, w, h = _load_rgb(_shot(runner, "pixel"))
    p = data[int(y * h / 224.0) * w + int(x * w / 256.0)]
    ok = all(abs(p[i] - int(rgb[i])) <= tol for i in range(3))
    return AssertResult("screenshot_pixel", ok,
                        f"({x},{y})={p} want {tuple(rgb)} +/-{tol}", "screenshot")


def _a_screenshot_changed(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    if ctx is None or not ctx.after_shot:
        raise ManifestError(
            "screenshot_changed requires axis_sweep with screenshot=true")
    axis = a.params.get("axis")
    region = a.params.get("region", "full")
    min_frac = float(a.params.get("min_frac", 0.05))
    if axis not in ctx.after_shot:
        raise ManifestError(f"screenshot_changed: axis '{axis}' not captured")
    bd, w, h = _load_rgb(ctx.before_shot[axis])
    ad, _, _ = _load_rgb(ctx.after_shot[axis])
    pb = _region_pixels(bd, w, h, region)
    pa = _region_pixels(ad, w, h, region)
    diff = sum(1 for x, y in zip(pb, pa) if x != y)
    frac = diff / max(1, len(pb))
    ok = frac >= min_frac
    return AssertResult("screenshot_changed", ok,
                        f"axis {axis}: {diff}/{len(pb)} px changed in {region} "
                        f"({frac:.1%}, need >= {min_frac:.0%})", "screenshot")


def _a_screenshot_axis_diff(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    """Diff the endpoint screenshots of two axis_branch branches (e.g. left vs
    right). Both branches start from an identical FRAME-EXACT baseline (same
    palette phase + day-night phase + forward distance, equalized by axis_branch's
    frame_stepping drive — see _drive_axis_branch), so a large region diff means
    the two *steer directions* produced different renders — the real-output proof
    that steering rotates the floor. On a frozen-steer ROM both branches render
    the same baseline and the diff collapses to near-zero.

    BASELINE-STABILITY GATE (H-1 round-2; opt-in via ``control_axes``, racer
    enables it). A frame-count-equal diff is NOT sufficient: a per-capture
    render-phase "bucket" can make a frozen ROM's floor diff spike to 6.5-91% at
    an identical frame count (see _drive_axis_branch + the diagnosis doc). The
    drive defends against this by re-driving any bucket-confounded direction until
    its same-direction control diff is <= control_eps; this assert is the in-assert
    BACKSTOP — it re-checks both same-direction controls and FAILS the assert (never
    a silent PASS) if either control diff exceeds control_eps, so a residual
    confounded reading can never be accepted as a steering signal.

    Verified discriminator (H-1 round-2 remediation, control-gated): over a >=100
    good + >=100 frozen alternating stress on the racer with the control gate
    active, GOOD floor diff(L,R) == 42.4% (rock-stable), control-gated frozen
    diff(L,R) <= 0.4% (the kart H-flip lean-frame floor noise; the per-capture
    bucket distance — up to 91% on the RAW diff — is rejected by the control gate
    before it reaches the diff). 0 spurious passes, 0 good failures, margin ~42pp
    at min_frac=0.15. (The raw, un-gated diff is NOT a usable figure — quote the
    control-gated frozen ceiling, not the raw bucket distance.)"""
    if ctx is None or not ctx.after_shot:
        raise ManifestError(
            "screenshot_axis_diff requires an axis_branch drive")
    axes = a.params.get("axes")
    if not axes or len(axes) != 2:
        raise ManifestError("screenshot_axis_diff: 'axes' must be a [a, b] pair")
    region = a.params.get("region", "full")
    min_frac = float(a.params.get("min_frac", 0.15))
    for ax in axes:
        if ax not in ctx.after_shot:
            raise ManifestError(
                f"screenshot_axis_diff: axis '{ax}' not captured by axis_branch")
    ad, w, h = _load_rgb(ctx.after_shot[axes[0]])
    bd, _, _ = _load_rgb(ctx.after_shot[axes[1]])
    pa = _region_pixels(ad, w, h, region)
    pb = _region_pixels(bd, w, h, region)
    diff = sum(1 for x, y in zip(pa, pb) if x != y)
    frac = diff / max(1, len(pa))
    detail = (f"{axes[0]} vs {axes[1]}: {diff}/{len(pa)} px differ in "
              f"{region} ({frac:.1%}, need >= {min_frac:.0%})")
    # Baseline-stability gate (H-1): the diff(L,R) reading is trustworthy only when
    # BOTH directions are internally bucket-stable; otherwise it is render-phase-
    # confounded and must FAIL, never silently PASS. control_axes maps each axis to
    # its same-direction control shot key (e.g. {"left": "left__ctl"}).
    control_axes = a.params.get("control_axes")
    ok = frac >= min_frac
    if control_axes:
        control_eps = float(a.params.get("control_eps", 0.02))
        stable = True
        parts = []
        for ax in axes:
            ctl_key = control_axes.get(ax)
            if not ctl_key or ctl_key not in ctx.after_shot:
                raise ManifestError(
                    f"screenshot_axis_diff: control axis for '{ax}' "
                    f"('{ctl_key}') not captured by axis_branch — set the "
                    f"drive's control_branches=true")
            cd = _region_diff_frac(ctx.after_shot[ax], ctx.after_shot[ctl_key],
                                   region)
            parts.append(f"{ax}/{ax}'={cd:.1%}")
            if cd > control_eps:
                stable = False
        detail += (f"  [stability {' '.join(parts)}, eps={control_eps:.1%}, "
                   f"stable={stable}]")
        ok = ok and stable
    return AssertResult("screenshot_axis_diff", ok, detail, "screenshot")


_ASSERT_IMPLS.update({
    "oam_delta": _a_oam_delta,
    "screenshot_blob": _a_screenshot_blob,
    "screenshot_pixel": _a_screenshot_pixel,
    "screenshot_changed": _a_screenshot_changed,
    "screenshot_axis_diff": _a_screenshot_axis_diff,
})


# --- verify() orchestrator ---------------------------------------------------

def _resolve_rom(manifest: Manifest, rom_dir) -> str:
    if rom_dir:
        return str(Path(rom_dir) / Path(manifest.rom).name)
    return manifest.rom


def _run_scenario(runner, manifest, sc: Scenario, rom: str) -> ScenarioResult:
    # B.3 contract: reload the ROM per scenario UNLESS continue_from_previous,
    # in which case reuse the prior scenario's loaded runner/ROM state so driven
    # state carries across the scenario boundary (e.g. a multi-step interaction).
    if not sc.continue_from_previous:
        # fresh_sram: make the next boot start from VIRGIN battery SRAM (power-on
        # garbage, not a stale save). _virgin_srm flushes the emulator's live SRAM
        # via a neutral ROM BEFORE deleting the .srm — a bare unlink is defeated
        # by the unload-flush trap when a save from this ROM sits in live SRAM
        # (the oracle two-run regression; see _virgin_srm).
        if sc.drive.params.get("fresh_sram"):
            _virgin_srm(runner, rom, _resolve_neutral_rom(manifest, rom))
        runner.load_rom(rom, run_seconds=manifest.boot_seconds)
    bc = boot_check(runner, manifest)
    if not bc.ok:
        return ScenarioResult(sc.name, False, [bc], [f"boot.magic FAIL — {bc.detail}"])
    ctx = run_drive(runner, manifest, sc.drive, rom)
    results = [evaluate_assert(runner, a, manifest, ctx) for a in sc.asserts]
    runner.set_input(0)  # leave the pad neutral for the next scenario
    ok = ctx.ok and all(r.ok for r in results)
    evidence = [f"{r.kind}: {'ok' if r.ok else 'FAIL'} — {r.detail} [{r.region_read}]"
                for r in results]
    if not ctx.ok:
        evidence.insert(0, f"drive: {ctx.detail}")
    return ScenarioResult(sc.name, ok, results, evidence)


def verify(manifest: Manifest, runner=None, *, determinism=False,
           rom_dir=None, only=None) -> OracleVerdict:
    """Drive the ROM per scenario and evaluate every assert. Reloads the ROM per
    scenario UNLESS a scenario sets continue_from_previous (B.3 contract), in
    which case it reuses the prior scenario's runner/ROM state. (Issue #123: one
    runner per process — pass one in for module scope.)
    ``rom_dir`` resolves manifest.rom by basename into a build dir; ``only``
    restricts to a set of scenario names. ``determinism=True`` re-runs the
    deterministic-drive scenarios a second time and verifies the resulting
    hardware state is byte-identical (the spec's "script twice -> byte-identical"
    check; bot/search/power_cycle are skipped — timing/battery state varies)."""
    from infrastructure.test_harness.mesen_runner import MesenRunner
    own = runner is None
    if own:
        runner = MesenRunner()
    rom = _resolve_rom(manifest, rom_dir)
    results: list[ScenarioResult] = []
    det_ok: bool | None = None
    try:
        scenarios = [sc for sc in manifest.scenarios
                     if only is None or sc.name in only]
        for sc in scenarios:
            results.append(_run_scenario(runner, manifest, sc, rom))
        if determinism:
            det_ok = _check_determinism(runner, manifest, scenarios, rom)
    finally:
        if own:
            runner.stop()
    passed = bool(results) and all(r.ok for r in results)
    if determinism and det_ok is False:
        passed = False
    return OracleVerdict(manifest.template, passed, results,
                         determinism_ok=det_ok)


# =============================================================================
# Brick 4 — bot policies, power_cycle / SRAM, bg3_text, determinism.
# =============================================================================
# bot is the irreducible game-specific drive: a registered closed-loop policy
# (the breaker win-bot already lives at tests/_breaker_bot.py). Policies are
# registered by the test/harness owner via register_bot(), NOT imported by this
# module — the dependency points test -> harness, never the reverse ("pluggable
# but not magic", spec B.2).

_BOT_POLICIES: dict[str, Any] = {}


def register_bot(name: str, fn) -> None:
    """Register a closed-loop bot policy. fn(runner, manifest, drive) -> bool
    (won). The policy owns its own frame_stepping context."""
    _BOT_POLICIES[name] = fn


def registered_bots() -> set[str]:
    return set(_BOT_POLICIES)


# --- independent CRC-16/CCITT (poly $1021, init $FFFF) -----------------------
# A second, table-free implementation so an sram_bytes CRC check cross-validates
# the engine's stored CRC against math the engine didn't produce (spec B.6 row 5
# "independent CRC").

def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = (((crc << 1) ^ 0x1021) & 0xFFFF) if (crc & 0x8000) \
                else ((crc << 1) & 0xFFFF)
    return crc


def _srm_path(rom: str) -> Path:
    from infrastructure.test_harness import mesen_runner
    return Path(mesen_runner._DEFAULT_HOME_DIR) / "Saves" / (Path(rom).stem + ".srm")


def _resolve_neutral_rom(manifest: "Manifest", rom: str) -> Path | None:
    """Path to a neutral (SRAM-free) ROM in the SAME build dir as ``rom``, used
    to flush the process-global emulator's live battery SRAM before a fresh_sram
    reset. Returns None if it isn't on disk (caller degrades to a bare unlink)."""
    p = Path(rom).parent / manifest.neutral_rom
    return p if p.exists() else None


def _virgin_srm(runner, rom: str, neutral_rom: Path | None) -> None:
    """Guarantee the NEXT boot of ``rom`` starts from VIRGIN battery SRAM.

    A bare unlink of the .srm is NOT enough (the F-S5-1 / oracle two-run trap):
    the emulator is process-global, so if a save from this same ROM is sitting
    in LIVE SRAM (a prior power_cycle / save scenario left it loaded), the unload
    triggered by the NEXT load_rom flushes that SRAM back to disk AFTER the
    delete — resurrecting the save. Order matters: load a NEUTRAL ROM first (its
    unload flushes ``rom``'s live SRAM now, while the file still exists), THEN
    delete the file. The following load_rom of ``rom`` only unloads the neutral
    ROM and seeds SRAM from the missing file = power-on garbage = virgin cart.

    Mirrors tests/_srm.py::virgin_srm; kept inline so the parent harness carries
    no dependency on a kit-side module. If no neutral ROM is available we fall
    back to the bare unlink (the legacy behavior, safe only when no save-carrying
    instance of ``rom`` is currently loaded)."""
    if neutral_rom is not None:
        runner.load_rom(str(neutral_rom), run_seconds=0.2)  # unload flushes rom's SRAM
    p = _srm_path(rom)
    if p.exists():
        p.unlink()


def _delete_srm(rom: str) -> None:
    """Bare unlink of ``rom``'s .srm. Legacy entry point retained for callers
    that hold no manifest/runner context — prefer _virgin_srm, which is robust
    to the unload-flush trap. (No internal caller uses this anymore.)"""
    p = _srm_path(rom)
    if p.exists():
        p.unlink()


# --- Brick 4 asserts ---------------------------------------------------------

def _a_bg3_text(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    base = _pint(a.params, "base", "bg3_text")
    row = _pint(a.params, "row", "bg3_text")
    col = _pint(a.params, "col", "bg3_text")
    text = a.params.get("text", "")
    glyph_base = _pint(a.params, "glyph_base", "bg3_text")
    ascii_off = _pint(a.params, "ascii_offset", "bg3_text")
    span = len(text) * 2
    buf = _read(runner, "vram", base + (row * 32 + col) * 2, span)
    bad = []
    for i, ch in enumerate(text):
        got = buf[i * 2] | (buf[i * 2 + 1] << 8)
        want = glyph_base | (ascii_off + ord(ch) - 0x20)
        if got != want:
            bad.append(f"glyph {i} '{ch}': {hex(got)} != {hex(want)}")
    ok = not bad
    return AssertResult("bg3_text", ok,
                        f"'{text}' at row {row},col {col}: "
                        + ("ok" if ok else "; ".join(bad)),
                        f"VRAM[{hex(base)}] (BG3 tilemap)")


def _a_sram_bytes(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    """Read SRAM bytes directly. Supports: exact `bytes`, an `ascii` magic, and
    `crc16` slot self-validation (header layout magic(2) ver(1) rsvd(1) len(2)
    crc(2) + payload, CRC field zeroed during compute) against the independent
    crc16_ccitt."""
    addr = _pint(a.params, "addr", "sram_bytes")
    checks = []
    if "ascii" in a.params:
        want = a.params["ascii"].encode()
        got = _read(runner, "sram", addr, len(want))
        checks.append(("ascii", got == want, f"{got!r} want {want!r}"))
    if "bytes" in a.params:
        want = [int(b) & 0xFF for b in a.params["bytes"]]
        got = list(_read(runner, "sram", addr, len(want)))
        checks.append(("bytes", got == want,
                       f"{len(want)} bytes "
                       + ("match" if got == want else f"differ: got {got[:8]}…")))
    if a.params.get("crc16"):
        hdr = _read(runner, "sram", addr, 8)
        plen = hdr[4] | (hdr[5] << 8)
        stored = hdr[6] | (hdr[7] << 8)
        payload = _read(runner, "sram", addr + 8, plen)
        calc = crc16_ccitt(bytes(hdr[0:6]) + b"\x00\x00" + bytes(payload))
        checks.append(("crc16", stored == calc,
                       f"stored {hex(stored)} vs independent {hex(calc)}"))
    if not checks:
        raise ManifestError("sram_bytes: need one of bytes / ascii / crc16")
    ok = all(c[1] for c in checks)
    detail = "; ".join(f"{n}: {'ok' if good else 'FAIL'} ({d})"
                       for n, good, d in checks)
    return AssertResult("sram_bytes", ok, detail, f"SRAM[{hex(addr)}]")


def _a_heartbeat_advances(runner, a: Assert, m: Manifest, ctx=None) -> AssertResult:
    """Liveness proxy: the boot heartbeat counter at ``boot.heartbeat_addr``
    strictly advances over N frames. This is a WRAM proxy (region 'wram' in
    REGION_OF_ASSERT) — it can never satisfy an outcome scenario, only supplement
    a real-output assert; that classification is the anti-indirect-evidence
    invariant. 16-bit wrap (0xFFFF -> small) counts as advanced."""
    if m.boot.heartbeat_addr is None:
        raise ManifestError(
            "heartbeat_advances requires boot.heartbeat_addr in the manifest")
    addr = m.boot.heartbeat_addr
    frames = _pint(a.params, "frames", "heartbeat_advances", default=10)
    raw0 = _read(runner, "wram", addr, 2)
    before = raw0[0] | (raw0[1] << 8)
    runner.run_frames(frames)
    raw1 = _read(runner, "wram", addr, 2)
    after = raw1[0] | (raw1[1] << 8)
    advanced = ((after - before) & 0xFFFF) != 0  # strict advance; wrap = advanced
    return AssertResult(
        "heartbeat_advances", advanced,
        f"counter@{hex(addr)} {before}->{after} over {frames} frames "
        + ("(advanced)" if advanced else "(stalled)"),
        f"WRAM[{hex(addr)}]",
    )


_ASSERT_IMPLS.update({
    "bg3_text": _a_bg3_text,
    "sram_bytes": _a_sram_bytes,
    "heartbeat_advances": _a_heartbeat_advances,
})


# --- determinism re-run ------------------------------------------------------

_DET_DRIVES = {"settle", "hold", "script", "axis_sweep"}


def _det_snapshot(runner) -> tuple:
    return (
        bytes(runner.read_bytes(MemoryType.SnesSpriteRam, 0, 544)),
        bytes(runner.read_bytes(MemoryType.SnesCgRam, 0, 512)),
        bytes(runner.read_bytes(MemoryType.SnesVideoRam, 0, 0x4000)),
    )


def _check_determinism(runner, manifest, scenarios, rom) -> bool:
    """Re-run each deterministic-drive scenario once more and require the
    post-drive hardware snapshot to be byte-identical to the first run."""
    checked = False
    for sc in scenarios:
        if sc.drive.kind not in _DET_DRIVES:
            continue
        snaps = []
        for _ in range(2):
            if sc.drive.params.get("fresh_sram"):
                _virgin_srm(runner, rom, _resolve_neutral_rom(manifest, rom))
            runner.load_rom(rom, run_seconds=manifest.boot_seconds)
            run_drive(runner, manifest, sc.drive, rom)
            snaps.append(_det_snapshot(runner))
            runner.set_input(0)
        checked = True
        if snaps[0] != snaps[1]:
            return False
    return True if checked else None
