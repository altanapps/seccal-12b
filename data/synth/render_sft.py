#!/usr/bin/env python3
"""Render the canonical dataset into SFT files, one per split.

Usage: python3 data/synth/render_sft.py [--out data/sft]

Writes data/sft/{train,val,test}.jsonl. Each line:
  {"id": ..., "messages": [{"role": "system", ...}, {"role": "user", ...},
                           {"role": "assistant", ...}]}
The messages come from common.to_chat(), the single source of truth shared
with the eval harness and the hook. Fails if any row has no split or does
not pass common.validate_row.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import read_jsonl, to_chat, validate_row  # noqa: E402

OUT = HERE / "out"
SPLITS = ("train", "val", "test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "sft"))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(OUT / "accepted.jsonl") + read_jsonl(OUT / "adjudicated.jsonl")
    problems = []
    for r in rows:
        if r.get("split") not in SPLITS:
            problems.append(f"{r['id']}: no split (run split.py first)")
        problems += [f"{r['id']}: {p}" for p in validate_row(r)]
    if problems:
        print(f"{len(problems)} problems; nothing written")
        for p in problems[:20]:
            print("  -", p)
        return 1

    handles = {s: (out_dir / f"{s}.jsonl").open("w") for s in SPLITS}
    counts = Counter()
    try:
        for r in rows:
            rec = {"id": r["id"], "messages": to_chat(r)["prompt"]}
            handles[r["split"]].write(json.dumps(rec, ensure_ascii=False) + "\n")
            counts[r["split"]] += 1
    finally:
        for h in handles.values():
            h.close()
    for s in SPLITS:
        print(f"{out_dir / (s + '.jsonl')}: {counts[s]} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
