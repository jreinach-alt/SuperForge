#!/usr/bin/env python3
"""Fold `build/worker_schedule.jsonl` into the shape a RED needs.

The schedule itself is one JSON row per test module (written by
`tests/conftest.py`, "the worker schedule record"). This turns it into the
two facts an investigation actually opens it for:

  * **per-worker module order** — the shared-Mesen-core adjacency. The core
    is a process-global singleton, so a module can only be poisoned by
    modules that ran in ITS worker; a list per worker is that history.
  * **for every module that went red, its predecessors, nearest first** —
    which is the replay order for a pair hunt: re-run the red module after
    its immediate predecessor, then after the one before that.

Why this is a separate file rather than a block inside `tools/bare_check.sh`:
the gate embeds the summary in `build/bare_check.json`, which outlives the
clone the gate deletes on green — so the summariser runs INSIDE the clone
against a file that is about to be thrown away, and the only way to test it
is to call it with a record of one's own. A function in a module is callable;
a heredoc inside a shell script is not.

NEVER RAISES. A crashed worker leaves a truncated record (its last module
never reached the boundary that writes a row) and a killed one can leave a
partial final line. Both are ordinary here. A summariser that threw on either
would turn "the suite went red and here is why" into "the suite went red and
the tool that explains it also went red", which is the failure mode this
whole record exists to remove.
"""
import json
import sys
from pathlib import Path

# The per-worker lists are the artifact's bulk. A full suite is ~120 modules
# over 2 workers, which is a few KB — fine. This is the guard for a pathological
# record (a `-n 16` run, or a file that somehow escaped truncation).
MAX_MODULES_PER_WORKER = 400

# Predecessors carried per red module. The pair hunt walks nearest-first and
# gives up long before this; the whole worker list is in `workers` anyway.
MAX_PREDECESSORS = 25


def load_rows(path) -> list:
    """Every well-formed row in the file. A torn final line is dropped."""
    rows = []
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue                    # a torn line: skip it, keep the rest
        if isinstance(row, dict) and row.get("module"):
            rows.append(row)
    return rows


def summarise_schedule(path) -> dict:
    """`{workers, red_modules, runs, module_count, parked_at_boundary}`."""
    rows = load_rows(path)
    if not rows:
        return {"workers": {}, "red_modules": [], "module_count": 0,
                "note": "no schedule recorded (file absent, empty, or the "
                        "run never reached a module boundary)"}

    def seq_of(r):
        v = r.get("seq")
        return v if isinstance(v, int) else 0

    workers: dict = {}
    for row in rows:
        workers.setdefault(str(row.get("worker", "?")), []).append(row)
    for w in workers:
        workers[w].sort(key=seq_of)

    red = []
    for w, wrows in workers.items():
        for i, row in enumerate(wrows):
            if not row.get("failed"):
                continue
            entry = {
                "module": row["module"],
                "worker": w,
                "seq": seq_of(row),
                "failed": row.get("failed"),
                # nearest predecessor first — the order a pair hunt replays in
                "predecessors": [p["module"] for p in
                                 reversed(wrows[max(0, i - MAX_PREDECESSORS):i])],
            }
            for k in ("failed_tests", "t_start", "t_end"):
                if row.get(k) is not None:
                    entry[k] = row[k]
            red.append(entry)

    # A module that handed on a PARKED core is the one leak the boundary guard
    # already names; recording it here too means the artifact carries it even
    # when the guard's own error scrolled out of a truncated log.
    parked = [r["module"] for r in rows if r.get("parked") is True]

    # A MODULE ON TWO WORKERS is a structural violation, not a statistic.
    # xdist's default `--dist load` distributes individual tests, which
    # splits a module across processes: intra-module state (a module-level
    # dict, a file an earlier test wrote) is then invisible to the later
    # test, and module-scoped fixtures run twice — two ROM boots, and two
    # concurrent `make` runs in one `build/`. `tests/conftest.py` pins
    # `loadfile` to prevent it; this names it if the pin ever comes off,
    # so the next occurrence arrives already diagnosed instead of as a red
    # on a module whose inputs did not change.
    homes: dict = {}
    for row in rows:
        homes.setdefault(row["module"], set()).add(str(row.get("worker", "?")))
    split = {m: sorted(ws) for m, ws in homes.items() if len(ws) > 1}

    out = {
        "workers": {w: [r["module"] for r in wrows][:MAX_MODULES_PER_WORKER]
                    for w, wrows in sorted(workers.items())},
        "module_count": len(rows),
        "red_modules": sorted(red, key=lambda e: (e["worker"], e["seq"])),
        "runs": sorted({str(r.get("run", "-")) for r in rows}),
    }
    if parked:
        out["parked_at_boundary"] = parked
    if split:
        out["split_modules"] = split
        out["split_note"] = (
            "these modules ran on more than one worker — xdist distributed "
            "their tests individually. Intra-module state and module-scoped "
            "fixtures do not survive that. tests/conftest.py pins "
            "--dist loadfile; check that pin.")
    return out


def main(argv) -> int:
    src = argv[1] if len(argv) > 1 else "build/worker_schedule.jsonl"
    json.dump(summarise_schedule(src), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
