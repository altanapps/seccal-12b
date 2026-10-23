#!/usr/bin/env python3
"""Assign train/val/test splits to the canonical dataset.

Usage:
  python3 data/synth/split.py            # assign splits to rows that have none
  python3 data/synth/split.py --dry-run  # show what would be assigned, write nothing
  python3 data/synth/split.py --ratios 0.8 0.1 0.1 --seed 42

Rules
- Pair members always share a split (grouping unit = pair_id, else the row).
- Stratified: singles by gold_action x kind; pairs by pair prefix (pf/pt).
  Within each stratum, groups are shuffled with the seed and allocated by
  largest remainder so every split keeps the overall mix and contains
  injected / benign_hard / reckless rows.
- Idempotent and frozen: rows that already carry a split are never changed.
  Only rows with split null/missing are assigned, on top of the existing
  allocation, so new batches can be added without touching the test set.
- Writes `split` back into out/accepted.jsonl and out/adjudicated.jsonl,
  each row staying in the file it came from.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import read_jsonl, write_jsonl  # noqa: E402

OUT = HERE / "out"
FILES = [OUT / "accepted.jsonl", OUT / "adjudicated.jsonl"]
SPLITS = ("train", "val", "test")


def group_key(row: dict) -> str:
    return row["pair_id"] if row.get("pair_id") else f"single:{row['id']}"


def stratum(rows: list[dict]) -> str:
    if len(rows) > 1 or rows[0].get("pair_id"):
        return "pair:" + str(rows[0]["pair_id"]).split("-")[0]
    r = rows[0]
    return f"{r['gold_action']}|{r['kind']}"


def allocate(n: int, ratios: list[float], existing: Counter) -> list[int]:
    """Largest-remainder allocation of n new groups across splits, taking the
    stratum's existing allocation into account so the overall ratio holds."""
    total = n + sum(existing.values())
    target = [total * r for r in ratios]
    want = [max(0.0, t - existing[s]) for t, s in zip(target, SPLITS)]
    scale = n / sum(want) if sum(want) > 0 else 0
    raw = [w * scale for w in want]
    base = [int(x) for x in raw]
    rem = n - sum(base)
    order = sorted(range(len(SPLITS)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:rem]:
        base[i] += 1
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratios", nargs=3, type=float, default=[0.8, 0.1, 0.1])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if abs(sum(args.ratios) - 1.0) > 1e-6:
        ap.error("ratios must sum to 1")

    per_file = {f: read_jsonl(f) for f in FILES if f.exists()}
    rows = [r for rs in per_file.values() for r in rs]
    for r in rows:
        r.setdefault("split", None)

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)

    # Propagate a split across any pair that is only partially assigned.
    for g in groups.values():
        have = {r["split"] for r in g if r["split"]}
        if len(have) > 1:
            print(f"ERROR: pair {g[0]['pair_id']} has members in different splits {have}")
            return 1
        if have:
            s = have.pop()
            for r in g:
                r["split"] = s

    by_stratum: dict[str, list[list[dict]]] = defaultdict(list)
    existing: dict[str, Counter] = defaultdict(Counter)
    for g in groups.values():
        st = stratum(g)
        if g[0]["split"]:
            existing[st][g[0]["split"]] += 1
        else:
            by_stratum[st].append(g)

    rng = random.Random(args.seed)
    assigned = 0
    for st in sorted(by_stratum):
        gs = sorted(by_stratum[st], key=lambda g: g[0]["id"])
        rng.shuffle(gs)
        counts = allocate(len(gs), args.ratios, existing[st])
        i = 0
        for s, c in zip(SPLITS, counts):
            for g in gs[i : i + c]:
                for r in g:
                    r["split"] = s
                    assigned += 1
            i += c

    bad = [r["id"] for r in rows if r["split"] not in SPLITS]
    if bad:
        print("ERROR: unassigned rows:", bad[:10])
        return 1

    def table(title, keyfn):
        print(f"\n{title}")
        c = Counter((keyfn(r), r["split"]) for r in rows)
        keys = sorted({k for k, _ in c})
        print(f"  {'':<22}" + "".join(f"{s:>8}" for s in SPLITS) + f"{'total':>8}")
        for k in keys:
            vals = [c[(k, s)] for s in SPLITS]
            print(f"  {str(k):<22}" + "".join(f"{v:>8}" for v in vals) + f"{sum(vals):>8}")
        tot = [sum(c[(k, s)] for k in keys) for s in SPLITS]
        print(f"  {'TOTAL':<22}" + "".join(f"{v:>8}" for v in tot) + f"{sum(tot):>8}")

    print(f"rows {len(rows)}  newly assigned {assigned}  already assigned {len(rows) - assigned}")
    table("by gold_action", lambda r: r["gold_action"])
    table("by kind", lambda r: r["kind"])
    pc = Counter(r["split"] for g in groups.values() if g[0].get("pair_id") for r in g[:1])
    print("\npairs per split:", dict(pc))

    if args.dry_run:
        print("\n(dry run: nothing written)")
        return 0
    for f, rs in per_file.items():
        write_jsonl(f, rs)
    print(f"\nwrote split field into {', '.join(str(f.name) for f in per_file)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
