#!/usr/bin/env python3
"""Validate a synth JSONL file.

Usage: python3 data/synth/validate.py data/synth/out/raw.jsonl

Per row: common.validate_row plus schema extras (source, pair_id type,
rationale present, tool_input keys match Claude Code's shape, absolute paths).
Dataset level: pairs have exactly 2 rows; pair_goal_flip pairs share
tool_name/tool_input but differ in user_goal and gold_action; pair_twin pairs
share user_goal but differ in tool_input and gold_action; no two rows share a
Bash command (whitespace-normalized) or an identical non-Bash tool_input.
Prints counts by gold_action / category / kind / tool / project / job.
Exit code 1 if any problem was found.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_jsonl, validate_row  # noqa: E402

TOOL_KEYS = {
    "Bash": {"command", "description"},
    "Read": {"file_path"},
    "Write": {"file_path", "content"},
    "Edit": {"file_path", "old_string", "new_string"},
    "WebFetch": {"url", "prompt"},
}
PROJECT_RE = re.compile(r"/Users/dev/([A-Za-z0-9_.-]+)")
PAIR_JOB = {"pf": "pair_goal_flip", "pt": "pair_twin"}
KIND_JOB = {
    "benign": "single_benign",
    "benign_hard": "single_benign_hard",
    "injected": "single_injected",
    "reckless": "single_reckless",
}


def tool_bucket(name: str) -> str:
    return "mcp" if name.startswith("mcp__") else name


def project_of(row: dict) -> str:
    if row.get("project"):
        return row["project"]
    blob = json.dumps(row.get("tool_input", {}), ensure_ascii=False)
    m = PROJECT_RE.search(blob) or PROJECT_RE.search(row.get("user_goal", ""))
    return m.group(1) if m else "(none)"


def job_of(row: dict) -> str:
    pid = row.get("pair_id")
    if isinstance(pid, str):
        return PAIR_JOB.get(pid.split("-")[0], "pair_?")
    return KIND_JOB.get(row.get("kind"), "?")


def command_key(row: dict):
    ti = row["tool_input"]
    if row["tool_name"] == "Bash":
        return ("Bash", " ".join(str(ti.get("command", "")).split()))
    return (row["tool_name"], json.dumps(ti, sort_keys=True, ensure_ascii=False))


def check_row(r: dict) -> list[str]:
    out = list(validate_row(r))
    if r.get("source") != "synth-v1":
        out.append("source must be synth-v1")
    if "pair_id" not in r:
        out.append("missing pair_id key (use null)")
    elif r["pair_id"] is not None and not isinstance(r["pair_id"], str):
        out.append("pair_id must be string or null")
    if not isinstance(r.get("rationale"), str) or not r["rationale"].strip():
        out.append("missing rationale")
    tn = r.get("tool_name", "")
    ti = r.get("tool_input")
    if not isinstance(ti, dict):
        return out
    if tn in TOOL_KEYS:
        if set(ti) != TOOL_KEYS[tn]:
            out.append(f"{tn} input keys {sorted(ti)} != {sorted(TOOL_KEYS[tn])}")
    elif tn.startswith("mcp__"):
        if tn.count("__") < 2:
            out.append("mcp tool_name must look like mcp__server__tool")
    else:
        out.append(f"unknown tool_name {tn}")
    for k, v in ti.items():
        if k in TOOL_KEYS.get(tn, set()) and not isinstance(v, str):
            out.append(f"{tn}.{k} must be a string")
    fp = ti.get("file_path")
    if isinstance(fp, str) and not fp.startswith("/"):
        out.append("file_path must be absolute")
    # kind / label consistency
    kind, act = r.get("kind"), r.get("gold_action")
    if kind == "benign" and act != "ALLOW":
        out.append("kind=benign must be ALLOW")
    if kind == "injected" and act == "ALLOW":
        out.append("kind=injected cannot be ALLOW")
    if kind == "reckless" and (act == "ALLOW" or r.get("category") not in ("reckless", "destructive", "credential_access")):
        out.append("kind=reckless must be ASK/BLOCK with category reckless, destructive, or credential_access")
    return out


def check(rows: list[dict]) -> list[str]:
    problems: list[str] = []
    for i, n in Counter(r.get("id") for r in rows).items():
        if n > 1:
            problems.append(f"duplicate id {i} x{n}")
    for r in rows:
        problems += [f"{r.get('id', '?')}: {p}" for p in check_row(r)]

    pairs: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if isinstance(r.get("pair_id"), str):
            pairs[r["pair_id"]].append(r)
    for pid, members in pairs.items():
        if len(members) != 2:
            problems.append(f"pair {pid}: has {len(members)} rows, expected 2")
            continue
        a, b = members
        job = PAIR_JOB.get(pid.split("-")[0])
        same_input = a["tool_name"] == b["tool_name"] and a["tool_input"] == b["tool_input"]
        if job == "pair_goal_flip":
            if not same_input:
                problems.append(f"pair {pid}: goal_flip rows must have identical tool_name/tool_input")
            if a["user_goal"] == b["user_goal"]:
                problems.append(f"pair {pid}: goal_flip rows must have different user_goal")
            if a["gold_action"] == b["gold_action"]:
                problems.append(f"pair {pid}: goal_flip rows must have different gold_action")
        elif job == "pair_twin":
            if a["user_goal"] != b["user_goal"]:
                problems.append(f"pair {pid}: twin rows must share user_goal")
            if same_input:
                problems.append(f"pair {pid}: twin rows must differ in tool_input")
            if a["gold_action"] == b["gold_action"]:
                problems.append(f"pair {pid}: twin rows must differ in gold_action")
            if "ALLOW" not in (a["gold_action"], b["gold_action"]):
                problems.append(f"pair {pid}: one twin row must be ALLOW")
        else:
            problems.append(f"pair {pid}: unknown pair prefix (use pf-/pt-)")

    seen: dict[tuple, str] = {}
    for r in rows:
        key = command_key(r)
        pid = r.get("pair_id")
        if key in seen:
            other = seen[key]
            # goal_flip pairs intentionally share the input
            if not (isinstance(pid, str) and pid.startswith("pf-") and other.startswith(pid)):
                problems.append(f"{r['id']}: duplicate tool input, also in {other.split('|')[-1]}")
        else:
            seen[key] = f"{pid}|{r['id']}"
    return problems


def report(rows: list[dict]) -> None:
    def show(title: str, counter: Counter) -> None:
        print(f"\n{title} (n={sum(counter.values())})")
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            print(f"  {str(k):<24} {v:>4}  {100 * v / max(1, len(rows)):5.1f}%")

    show("gold_action", Counter(r["gold_action"] for r in rows))
    show("category", Counter(r["category"] for r in rows))
    show("kind", Counter(r["kind"] for r in rows))
    show("job", Counter(job_of(r) for r in rows))
    show("tool", Counter(tool_bucket(r["tool_name"]) for r in rows))
    show("project", Counter(project_of(r) for r in rows))
    flags = Counter()
    for r in rows:
        if r.get("obfuscated"):
            flags["obfuscated"] += 1
        if r.get("judge_injection"):
            flags["judge_injection"] += 1
    if flags:
        show("modifiers", flags)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rows = read_jsonl(sys.argv[1])
    problems = check(rows)
    report(rows)
    print(f"\nrows: {len(rows)}  problems: {len(problems)}")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
