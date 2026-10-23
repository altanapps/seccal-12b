#!/usr/bin/env python3
"""Assemble and validate the full curated dataset.

Usage:
  python3 data/synth/assemble.py check             # validate current canonical set
  python3 data/synth/assemble.py check B1 B2 ...    # canonical + batch dirs (dry run)
  python3 data/synth/assemble.py write B1 B2 ...    # append batch accepted+adjudicated
                                                     # into canonical files, then validate

A "batch dir" is e.g. data/synth/out/batch_D ; its accepted.jsonl and
adjudicated.jsonl are the integrated rows. `check` only reads and reports;
`write` mutates out/accepted.jsonl and out/adjudicated.jsonl in place.
The combined validation always runs on accepted + adjudicated together so
pair integrity holds across files.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validate as V  # noqa: E402
from common import read_jsonl, write_jsonl  # noqa: E402

OUT = HERE / "out"
CANON_ACC = OUT / "accepted.jsonl"
CANON_ADJ = OUT / "adjudicated.jsonl"


def load_all(batch_dirs: list[str]) -> list[dict]:
    rows = read_jsonl(CANON_ACC) + (read_jsonl(CANON_ADJ) if CANON_ADJ.exists() else [])
    for d in batch_dirs:
        p = Path(d)
        for name in ("accepted.jsonl", "adjudicated.jsonl"):
            f = p / name
            if f.exists():
                rows += read_jsonl(f)
    return rows


def do_write(batch_dirs: list[str]) -> None:
    acc = read_jsonl(CANON_ACC)
    adj = read_jsonl(CANON_ADJ) if CANON_ADJ.exists() else []
    for d in batch_dirs:
        p = Path(d)
        if (p / "accepted.jsonl").exists():
            acc += read_jsonl(p / "accepted.jsonl")
        if (p / "adjudicated.jsonl").exists():
            adj += read_jsonl(p / "adjudicated.jsonl")
    write_jsonl(CANON_ACC, acc)
    write_jsonl(CANON_ADJ, adj)
    print(f"wrote {len(acc)} accepted + {len(adj)} adjudicated = {len(acc) + len(adj)}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    batch_dirs = sys.argv[2:]
    if mode == "write":
        do_write(batch_dirs)
        batch_dirs = []  # already folded into canonical
    rows = load_all(batch_dirs)
    problems = V.check(rows)
    V.report(rows)
    print(f"\nCOMBINED rows: {len(rows)}  problems: {len(problems)}")
    for p in problems[:50]:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
