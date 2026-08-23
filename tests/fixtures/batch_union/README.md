# `batch_union` fixtures — the ci.yml drops, as they were

Five files, two shapes. The first three **lose a line**; the last two **move
one**, which is the half the arithmetic contract cannot see.

## Shape 1 — the line is lost (three consecutive landings)

Three consecutive landings lost a rail step's

```
          test "$size" -eq 524288 || { echo "::error::expected 524288 bytes, got $size"; exit 1; }
```

line to the union script — patrol's in the sprite_game merge, jumper's in the
stomper merge, stomper's in the scroll_run merge. `make rail-registered` named
each one (site 4, by rail), which is the only reason they were caught.

These three files are those conflicts in the alignment git actually produced.
The shape is the point, and it is not a freak: every rail step ends with an
assert and is followed by a blank line and `- name: make <next>`, so when two
branches each append a step, git aligns the hunk on the **blank line** rather
than on the assert. That puts the PREVIOUS rail's assert inside *both* sides
and the last new rail's assert in the shared trailing context — so the region
holds three steps and only two assert lines.

That is why the drop was invisible on review. Every rail asserts the same
524,288 bytes, so the file still reads as full of identical assert lines; it
simply has one fewer than it has steps. A resolver that "dedupes the repeated
boundary line" produces exactly that file.

`tests/test_batch_union.py` unions each fixture and asserts the invariant the
landings violated: **every `- name: make <rail>` step is terminated by an
assert line**, plus strict no-line-loss and a YAML parse.

## Shape 2 — the line MOVES (one landing, uncaught)

`ci_svd_nowin_f1.yml` and `ci_svd_nowin_absorbed_conflict.yml`.

`an earlier commit inserted `split_v_seamtrial`'s `- name:` between `svd-nowin`'s
`echo` and its assert line, so the assert ended up terminating the **seamtrial**
step and `svd-nowin` had none. Nothing
was deleted. Every line survived, the count matched, the YAML parsed — and
`make rail-registered` was green, because its ci.yml site was scoped to rails
under `game/` and `svd-nowin` is a **variant target**, not a rail. Combined
with `bare_check.sh`'s size list being rail-scoped too,
`build/svd_nowin.sfc`'s 524,288 bytes were asserted **nowhere**. Fifth
instance of the drop class across waves; first not caught.

Since 2026-08-23 the gate-time end is covered again, by derivation rather than
by a shape check: `bare_check.sh` measures every `build/*.sfc` the gate block
leaves behind against that image's own header, and demands the set derived
from `make gates`'s own run-list — `svd_nowin` included (docs/44 §7). These
fixtures hold the **union-time** half, which fires before there is a commit
to gate.

- **`ci_svd_nowin_f1.yml`** is the file as it landed — **no conflict markers**,
  because the real damage was a landing-side hand repair applied after the
  union. It is the shape a reviewer actually sees, and
  `tools/batch_union.py --check <file>` runs the battery on an unconflicted
  file, which is the surface that has to catch it.
- **`ci_svd_nowin_absorbed_conflict.yml`** reaches the same shape through a
  keep-both **union**, and is the fixture that separates the two contracts:
  `u.dropped == 0`, every input line reaches the output, and the result is
  still broken — because the question is which *block* a line landed in, and
  arithmetic counts lines. Its residue is a duplicated assert in the seamtrial
  block, which is the tool's declared bias (a duplicate is a visible, harmless
  nuisance) and the signpost back to the missing one.

Both are refused by the battery's one semantic member, `ci_step_shape` — a
step that runs make and stats a `build/*.sfc` must assert its size, in its own
block, *after* the stat that feeds `$size`. The same condition backs
`tools/rail_registered.py`'s ROM-step sweep, deliberately, so the two tools
cannot disagree about what a ROM step is: this one catches the shape at UNION
time, the gate catches it at GATE time, and neither subsumes the other.
