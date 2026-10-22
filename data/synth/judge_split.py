#!/usr/bin/env python3
"""Prepare blind re-judge inputs.

Usage: python3 data/synth/judge_split.py data/synth/out/raw.jsonl <chunk_size>

Writes data/synth/out/blind/chunk_NN.jsonl with ONLY id, user_goal, tool_name,
tool_input (no label, kind, pair_id, rationale, or modifier flags), rows shuffled
with a fixed seed so pair members are not adjacent.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_jsonl  # noqa: E402


def main() -> None:
    src = Path(sys.argv[1])
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    rows = read_jsonl(src)
    random.Random(1234).shuffle(rows)
    out_dir = src.parent / "blind"
    out_dir.mkdir(exist_ok=True)
    for f in out_dir.glob("chunk_*.jsonl"):
        f.unlink()
    for i in range(0, len(rows), size):
        path = out_dir / f"chunk_{i // size:02d}.jsonl"
        with path.open("w") as fh:
            for r in rows[i : i + size]:
                blind = {k: r[k] for k in ("id", "user_goal", "tool_name", "tool_input")}
                fh.write(json.dumps(blind, ensure_ascii=False) + "\n")
        print(path, min(size, len(rows) - i))


if __name__ == "__main__":
    main()
