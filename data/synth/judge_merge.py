#!/usr/bin/env python3
"""Merge blind judgments back onto generated rows.

Usage: python3 data/synth/judge_merge.py data/synth/out/raw.jsonl data/synth/out/blind/judged_*.jsonl

Judgment rows: {"id", "judge_action", "judge_category"}.
Rows whose gold_action AND category match the judge go to accepted.jsonl.
Everything else (including rows with no judgment) goes to review_queue.jsonl
with both labels and the generator's rationale. Prints agreement stats.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_jsonl, write_jsonl  # noqa: E402


def main() -> None:
    src = Path(sys.argv[1])
    rows = read_jsonl(src)
    judged: dict[str, dict] = {}
    for p in sys.argv[2:]:
        for j in read_jsonl(p):
            judged[j["id"]] = j

    accepted, queue = [], []
    action_agree = 0
    confusion: Counter = Counter()
    for r in rows:
        j = judged.get(r["id"])
        if j is None:
            queue.append({**r, "judge_action": None, "judge_category": None, "disagreement": "no judgment"})
            continue
        confusion[(r["gold_action"], j["judge_action"])] += 1
        same_action = j["judge_action"] == r["gold_action"]
        same_cat = j.get("judge_category") == r["category"]
        action_agree += same_action
        if same_action and same_cat:
            accepted.append(r)
        else:
            queue.append({
                **r,
                "judge_action": j["judge_action"],
                "judge_category": j.get("judge_category"),
                "disagreement": "action" if not same_action else "category",
            })

    write_jsonl(src.parent / "accepted.jsonl", accepted)
    write_jsonl(src.parent / "review_queue.jsonl", queue)
    n = len(rows)
    print(f"rows {n}  judged {len(judged)}  accepted {len(accepted)}  review_queue {len(queue)}")
    print(f"action agreement: {action_agree}/{n} = {100 * action_agree / max(1, n):.1f}%")
    print(f"action+category agreement: {len(accepted)}/{n} = {100 * len(accepted) / max(1, n):.1f}%")
    print("\nconfusion (gold -> judge):")
    for (g, jj), c in sorted(confusion.items()):
        print(f"  {g:<6} -> {jj:<6} {c}")
    by_kind: Counter = Counter()
    by_kind_total: Counter = Counter()
    acc_ids = {r["id"] for r in accepted}
    for r in rows:
        by_kind_total[r["kind"]] += 1
        by_kind[r["kind"]] += r["id"] in acc_ids
    print("\nagreement by kind:")
    for k in by_kind_total:
        print(f"  {k:<12} {by_kind[k]}/{by_kind_total[k]}")


if __name__ == "__main__":
    main()
