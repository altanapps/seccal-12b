#!/usr/bin/env python3
"""Pretty-print rows for human review.

Usage:
  python3 data/synth/show.py accepted <N>   # N random accepted rows (seeded)
  python3 data/synth/show.py queue          # every review_queue row
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_jsonl  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def fmt_input(ti: dict) -> str:
    s = json.dumps(ti, ensure_ascii=False)
    return s if len(s) <= 240 else s[:237] + "..."


def show(r: dict, judged: bool) -> None:
    print(f"[{r['id']}] {r.get('project', '?')} / {r['kind']}  pair={r.get('pair_id')}")
    print(f"  goal : {r['user_goal']}")
    print(f"  tool : {r['tool_name']}  {fmt_input(r['tool_input'])}")
    gold = f"{r['gold_action']}/{r['category']}"
    if judged:
        jd = f"{r.get('judge_action')}/{r.get('judge_category')}"
        print(f"  gold : {gold}    judge: {jd}    [{r.get('disagreement')}]")
    else:
        print(f"  gold : {gold}")
    print(f"  why  : {r.get('rationale', '')}")
    print()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "queue"
    if mode == "accepted":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        rows = read_jsonl(OUT / "accepted.jsonl")
        random.Random(7).shuffle(rows)
        print(f"=== {min(n, len(rows))} random accepted rows (of {len(rows)}) ===\n")
        for r in rows[:n]:
            show(r, judged=False)
    else:
        rows = read_jsonl(OUT / "review_queue.jsonl")
        print(f"=== all {len(rows)} review_queue rows ===\n")
        for r in rows:
            show(r, judged=True)


if __name__ == "__main__":
    main()
