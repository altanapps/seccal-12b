#!/usr/bin/env python3
"""Check holdout isolation and schema without accepting generator labels."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "synth"))
from common import read_jsonl, validate_row  # noqa: E402
from validate import command_key  # noqa: E402


def check(rows, canonical):
    problems = []
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):problems.append("duplicate holdout id")
    canonical_ids = {r["id"] for r in canonical}
    canonical_inputs = {command_key(r) for r in canonical}
    scenarios = defaultdict(list)
    for row in rows:
        problems += [f"{row['id']}: {p}" for p in validate_row(row)]
        if row["id"] in canonical_ids:problems.append(f"{row['id']}: canonical id overlap")
        if command_key(row) in canonical_inputs:problems.append(f"{row['id']}: exact canonical input overlap")
        if row.get("split") != "holdout":problems.append(f"{row['id']}: must stay in holdout")
        if row.get("review_status") != "candidate":problems.append(f"{row['id']}: candidate file cannot claim accepted labels")
        scenarios[row["scenario_id"]].append(row)
    for scenario, members in scenarios.items():
        if len(members) != 3 or {r["gold_action"] for r in members} != {"ALLOW", "ASK", "BLOCK"}:
            problems.append(f"{scenario}: expected three candidate verdict hypotheses")
        paired=[r for r in members if r.get("pair_id")]
        if paired and paired[0]["pair_id"].startswith("pf-"):
            if paired[0]["tool_input"]!=paired[1]["tool_input"] or paired[0]["tool_name"]!=paired[1]["tool_name"]:
                problems.append(f"{scenario}: goal-flip inputs must match")
            if paired[0]["user_goal"]==paired[1]["user_goal"]:problems.append(f"{scenario}: goal-flip goals must differ")
        elif len({r["user_goal"] for r in members}) != 1:problems.append(f"{scenario}: twin goals differ")
    return problems


if __name__ == "__main__":
    rows=read_jsonl(HERE / "candidates.jsonl")
    canonical=read_jsonl(HERE.parent / "synth/out/accepted.jsonl")+read_jsonl(HERE.parent / "synth/out/adjudicated.jsonl")
    problems=check(rows,canonical)
    print(json.dumps({"rows":len(rows), "scenarios":len({r['scenario_id'] for r in rows}),
        "candidate_actions":dict(Counter(r['gold_action'] for r in rows)),
        "tools":dict(Counter('mcp' if r['tool_name'].startswith('mcp__') else r['tool_name'] for r in rows)),
        "obfuscated":sum(bool(r.get('obfuscated')) for r in rows),
        "judge_injection":sum(bool(r.get('judge_injection')) for r in rows),
        "problems":problems}, indent=2))
    sys.exit(bool(problems))
