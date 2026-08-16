#!/usr/bin/env python3
"""reg-ownership census: what the gate RESOLVES and how it VERDICTS, per site.

The instrument for the one question a gate's exit code cannot answer:
*"did this change alter any verdict I didn't intend?"*. It exists because
widening the resolver moved the gate's coverage from 110 to 158 checked sites,
and a coverage change that is asserted rather than measured is exactly the kind
of claim this repo does not accept.

It answers two questions the gate's own exit code cannot:

  1. **What does the resolver SEE?** Every write-shaped instruction in the
     live population, with the register `no_literals` resolves it to. A site the
     resolver returns None for is invisible to every downstream rule, and a
     None is indistinguishable from "checked and fine" in a green run.
  2. **What does the gate DO about it?** Each resolved site's category
     (`channel` / `latch` / `data` / `in-class` / `unnamed` / `unresolved`),
     which is the axis the whole coverage argument runs along.

Usage:

    # snapshot the tree as it stands
    python3 tools/reg_census.py --out build/census_before.json

    # ... change the tool ...

    python3 tools/reg_census.py --out build/census_after.json
    python3 tools/reg_census.py --compare build/census_before.json \
                                          build/census_after.json

`--compare` exits 0 always: it is an instrument, not a gate. Read its report.
An UNEXPECTED row is one where a site's resolved port changed — the shape the
a follow-up review instrument found 94 of, all inside `$4300-$437F`, when the fold was
fixed. A category transition (e.g. `unnamed` -> `latch`) is the shape a
category port is SUPPOSED to produce, and is reported separately so the two
never get confused.

**Population** = every `.asm` any live invocation hands the tool, which is not
the same as every `.asm` the Makefile hands it. `vendor/probes/probe_vb2reg.asm`
is the case that taught the distinction: gated by `tests/test_vb2reg_probe.py`
rather than by the Makefile, it was swept but never resolved, and surfaced as
three red tests instead of as a finding. Enumerated in POPULATION
below, with the invocation that owns each entry named.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))
import no_literals as NL                                        # noqa: E402

# (asm glob, map dir, the invocation that owns it). The map matters: a site's
# resolution depends on the map's io window, and the scene/feature tier
# depends on the map's scene list.
POPULATION = [
    ("engine/toy/main.asm", "build", "Makefile `no-literals`"),
    ("game/microzero/main.asm", "build/mz", "Makefile microzero"),
    ("game/microzero/scenes/*.asm", "build/mz", "Makefile microzero"),
    ("engine/features/*/*.asm", "build/mz", "Makefile microzero (MZ_ASM)"),
    ("game/room/main.asm", "build/rm", "Makefile room"),
    ("game/room/scenes/*.asm", "build/rm", "Makefile room"),
    ("vendor/probes/probe_vblank.asm", "build/probe_map", "Makefile probes"),
    ("vendor/probes/probe_colmap.asm", "build/colmap_map", "Makefile colmap"),
    ("vendor/probes/probe_vb2reg.asm", None, "tests/test_vb2reg_probe.py"),
]


import re                                                       # noqa: E402

# The ca65 width/bank prefix, in the ATOMIC form (letter and colon together).
# The non-atomic `[azf]?:?` spelling is the defect fixed in 20c5c63 — it
# eats the leading letter of `sta FADE_EN`. Spelling it
# correctly here is not cosmetic: an instrument that mis-parses the same way
# the bug did would report the bug's own blind spot as empty.
_PREFIX_RE = re.compile(r"^\s*(?:[azf]:)?\s*", re.I)


def _resolve_site(rest: str, aliases: dict, io) -> int | None:
    """The register a write operand reaches, through whichever resolver this
    version of the tool carries. Written to survive a change of resolver: the
    older one is `_store_port(dest)` — which expects the width/bank prefix
    ALREADY consumed, because its STORE_RE eats it — and the newer one is
    `_write_target(rest, aliases, io)`, which parses the prefix itself. Binding
    to either one's *name* would make the instrument stop working exactly when
    it is needed."""
    if hasattr(NL, "_write_target"):
        return NL._write_target(rest, aliases, io)
    return NL._store_port(_PREFIX_RE.sub("", rest, count=1), aliases)


def _aliases(lines: list[str], io) -> dict:
    if hasattr(NL, "_io_aliases"):
        return NL._io_aliases(lines, io)
    return NL._port_aliases(lines)


def _write_mnemonics() -> set[str]:
    return set(getattr(NL, "REG_WRITE_MN", {"sta", "stx", "sty", "stz"}))


def _category(port) -> str:
    """The gate's category for a port, or a stand-in when it supplies none."""
    if port == getattr(NL, "UNRESOLVED_PORT", -1) and port is not None \
            and port < 0:
        return "unresolved"
    if hasattr(NL, "_reg_category"):
        return NL._reg_category(port)[0]
    # Pre-port: the landed gate has no categories. Reconstruct the only
    # distinction it makes so a before/after diff is still meaningful.
    import schemas
    if port in (0x420B, 0x420C) or 0x4300 <= port <= 0x437F:
        return "channel"
    return ("in-class" if port in NL._port_names(schemas.REGISTER_FOOTPRINT)
            else "unnamed")


def _sites_in(path: Path, io) -> list[dict]:
    """Every write-shaped instruction in one file, with what it resolves to.

    Deliberately scans with the WIDER of the two shapes (the mnemonic set),
    not with STORE_RE, so that a site the narrower STORE_RE shape cannot
    even see (an
    `inc a:$2105`) still appears in the before-census as `port: null`. That is
    what makes "the RMW port added N sites" a measured number rather than an
    asserted one."""
    out = []
    lines = path.read_text().splitlines()
    aliases = _aliases(lines, io)
    mns = _write_mnemonics() | {"sta", "stx", "sty", "stz",
                                "inc", "dec", "asl", "lsr", "rol", "ror",
                                "trb", "tsb"}
    label_re = getattr(NL, "LABEL_RE", None)
    for i, raw in enumerate(lines, start=1):
        line = NL._strip(raw)
        if not line.strip() or NL.DIRECTIVE_RE.match(line):
            continue
        body = label_re.sub("", line) if label_re else line
        m = NL.MNEMONIC_RE.match(body) if hasattr(NL, "MNEMONIC_RE") else None
        if m:
            mn, rest = m.group("mn").lower(), (m.group("rest") or "")
        else:                            # narrower shape: STORE_RE only
            sm = NL.STORE_RE.match(line)
            if not sm:
                continue
            mn, rest = "sta", sm.group("dest")
        if mn not in mns:
            continue
        port = _resolve_site(rest, aliases, io)
        rec = {"file": str(path.relative_to(SUPERFORGE)), "line": i, "mn": mn,
               "operand": rest.strip()[:60], "port": port}
        rec["category"] = _category(port) if port is not None else None
        # `checked` = the gate would actually verdict this site. The whole
        # point of the census: a resolved site the pass never reaches is
        # indistinguishable from a clean one in the exit code.
        rec["checked"] = port is not None and rec["category"] != "channel" \
            and (hasattr(NL, "_reg_category")
                 or rec["category"] != "unnamed")
        out.append(rec)
    return out


def take_census() -> dict:
    io_by_map: dict[str, list] = {}
    sites: list[dict] = []
    missing: list[str] = []
    for pat, mapdir, owner in POPULATION:
        if mapdir is None:               # vb2reg builds its map in a tmpdir
            mapdir = "build/mz"          # any map: the io window is substrate
        mp = SUPERFORGE / mapdir / "symbol_map.json"
        if not mp.exists():
            missing.append(f"{pat} (needs {mapdir}/symbol_map.json)")
            continue
        if mapdir not in io_by_map:
            io, _pl, _raw = NL.load_map(mp)
            io_by_map[mapdir] = io
        io = io_by_map[mapdir]
        paths = (sorted(SUPERFORGE.glob(pat)) if "*" in pat
                 else [SUPERFORGE / pat])
        for p in paths:
            if not p.exists():
                missing.append(str(pat))
                continue
            for rec in _sites_in(p, io):
                rec["owner"] = owner
                sites.append(rec)
    return {"sites": sites, "missing": missing,
            "tool_has_categories": hasattr(NL, "_reg_category")}


def _summarise(c: dict) -> None:
    sites = c["sites"]
    resolved = [s for s in sites if s["port"] is not None]
    checked = [s for s in resolved if s["checked"]]
    print(f"files scanned                : "
          f"{len({s['file'] for s in sites})}")
    print(f"write-shaped sites total     : {len(sites)}")
    print(f"  resolver -> None           : {len(sites) - len(resolved)}")
    print(f"  RESOLVED                   : {len(resolved)}")
    cats: dict[str, int] = {}
    for s in resolved:
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    for k in sorted(cats):
        print(f"     {k:<24}: {cats[k]}")
    print(f"  CHECKED by the reg pass    : {len(checked)}")
    print(f"  skipped (unreachable)      : {len(resolved) - len(checked)}")
    if c["missing"]:
        print(f"  NOT SCANNED (build first)  : {len(c['missing'])}")
        for m in c["missing"][:8]:
            print(f"     {m}")


def _compare(a: dict, b: dict) -> None:
    key = lambda s: (s["file"], s["line"], s["mn"])          # noqa: E731
    ka = {key(s): s for s in a["sites"]}
    kb = {key(s): s for s in b["sites"]}
    port_moved, cat_moved, newly, lost = [], [], [], []
    for k in sorted(set(ka) | set(kb)):
        x, y = ka.get(k), kb.get(k)
        if x is None or y is None:
            continue                     # site set changed: reported below
        if x["port"] != y["port"]:
            port_moved.append((k, x, y))
        elif x["category"] != y["category"]:
            cat_moved.append((k, x, y))
        if not x["checked"] and y["checked"]:
            newly.append((k, y))
        if x["checked"] and not y["checked"]:
            lost.append((k, x))
    print("=== reg census comparison ===")
    print(f"sites in A / B               : {len(ka)} / {len(kb)}")
    print(f"sites only in A (vanished)   : {len(set(ka) - set(kb))}")
    print(f"sites only in B (new shapes) : {len(set(kb) - set(ka))}")
    print(f"RESOLVED PORT MOVED          : {len(port_moved)}"
          "   <-- each one needs a reason")
    for k, x, y in port_moved[:20]:
        print(f"   {k[0]}:{k[1]} {x['port']} -> {y['port']}  :: {y['operand']}")
    print(f"category changed (same port) : {len(cat_moved)}")
    for k, x, y in cat_moved[:30]:
        print(f"   {k[0]}:{k[1]} {x['category']} -> {y['category']}"
              f"  ${y['port']:04X}" if y["port"] and y["port"] > 0 else
              f"   {k[0]}:{k[1]} {x['category']} -> {y['category']}")
    print(f"NEWLY CHECKED                : {len(newly)}"
          "   <-- the coverage gain, measured")
    bycat: dict[str, int] = {}
    for _k, y in newly:
        bycat[y["category"]] = bycat.get(y["category"], 0) + 1
    for k2 in sorted(bycat):
        print(f"     {k2:<24}: {bycat[k2]}")
    print(f"COVERAGE LOST                : {len(lost)}"
          "   <-- must be 0 unless intended")
    for k, x in lost[:20]:
        print(f"   {k[0]}:{k[1]} {x['category']} ${x['port']:04X}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the census JSON here")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"),
                    help="diff two census JSONs")
    args = ap.parse_args(argv)
    if args.compare:
        a = json.loads(Path(args.compare[0]).read_text())
        b = json.loads(Path(args.compare[1]).read_text())
        _compare(a, b)
        return 0
    c = take_census()
    _summarise(c)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(c, indent=1))
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
