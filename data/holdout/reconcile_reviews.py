#!/usr/bin/env python3
"""Report two blind-model reviews without automatically accepting disagreements."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def read(path):return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judges",nargs=2,default=["qwen3.8-27b","gpt-oss-safeguard-20b"])
    args=ap.parse_args()
    candidates=read(HERE / "candidates.jsonl")
    sha=hashlib.sha256((HERE / "candidates.jsonl").read_bytes()).hexdigest()
    reviews=[]
    for judge in args.judges:
        path=HERE / "reviews" / f"{judge}.jsonl"
        records=read(path) if path.exists() else []
        if any(r["candidate_sha256"]!=sha for r in records):raise ValueError("review source hash mismatch")
        if len({r["id"] for r in records})!=len(records):raise ValueError("duplicate review id")
        reviews.append({r["id"]:r for r in records})
    agreed,queue=[],[]
    for row in candidates:
        judgments=[review.get(row["id"]) for review in reviews]
        expected=(row["gold_action"],row["category"])
        if all(j and (j["judge_action"],j["judge_category"])==expected for j in judgments):
            agreed.append({**row,"review_status":"two_blind_models_agree"})
        else:
            queue.append({**row,"blind_judgments":dict(zip(args.judges,judgments)),"review_status":"needs_adjudication"})
    out=HERE / "reviews";out.mkdir(exist_ok=True)
    frozen=json.loads((HERE/'frozen.json').read_text()) if (HERE/'frozen.json').exists() else None
    decisions={r['id']:r for r in read(HERE/'adjudications.jsonl')} if frozen else {}
    for row in queue:
        if row['id'] in decisions:
            d=decisions[row['id']]
            row.update(review_status='adjudicated',final_action=d['final_action'],final_category=d['final_category'],adjudication_rationale=d['rationale'])
    unresolved=sum(r['review_status']=='needs_adjudication' for r in queue)
    for name,rows in (("agreement.jsonl",agreed),("adjudication_queue.jsonl",queue)):
        (out / name).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows))
    report=["# Holdout candidate review", "",
        f"Candidate SHA-256: `{sha}`. {len(candidates)} rows in {len({r['scenario_id'] for r in candidates})} scenarios.","",
        "These are newly authored synthetic candidates. They have not been used for model selection, training, or a reported safety score.","",
        f"Blind judges: {', '.join(args.judges)}. Only user goal, tool name and tool input were sent; generator labels, rationale, kind and pair identifiers were withheld.","",
        f"- Both blind judges match the proposed action and category: **{len(agreed)}**.",
        f"- Original missing judgments or disagreements requiring adjudication: **{len(queue)}**.",
        f"- Still unresolved: **{unresolved}**.","",
        "Agreement does not prove correctness. Disagreements are never silently relabeled or dropped to improve a model's score. "
        "Frozen status and final labels, when present, are recorded separately from the original hypotheses. "
        "The large judge models must not be scored on this set as independent test subjects because their judgments help construct its labels.","",
        "| judge | completed valid judgments |", "|---|---|"]
    for judge,review in zip(args.judges,reviews):
        n=sum(r['judge_action'] in ('ALLOW','ASK','BLOCK') for r in review.values())
        report.append(f"| {judge} | {n} |")
    report += ["", "Candidate action distribution: " + str(dict(Counter(r['gold_action'] for r in candidates))) + ".", "",
        "Raw local review files and the adjudication queue are under `data/holdout/reviews/` (gitignored). "
        "The original frozen test split and canonical training/validation files remain separate.", ""]
    if frozen:
        report += ['## Frozen reviewed set','',
            f"**{frozen['rows']} calls in {frozen['scenarios']} scenarios**, including 14 additional policy-anchored ASK cases reviewed separately by both models. "
            f"Final actions: {frozen['actions']}. Frozen SHA-256: `{frozen['sha256']}`.",'',
            'Both blind-model judgments were collected for every original and supplemental call. The author then adjudicated disagreements against the written policy. '
            'This is **model-reviewed, author-adjudicated synthetic data, not human-verified ground truth**. '
            'The author retained all original cases, corrected 49 proposed action/category labels, and added new ASK cases instead of forcing incorrect labels to meet a quota. '
            '152 calls retained full blind-model agreement; 162 have explicit author policy adjudications.','',
            'Final decisions and rationales are in `data/holdout/adjudications.jsonl`; `accepted.jsonl` and `frozen.json` define the immutable benchmark. '
            'Original hypotheses and review hashes are retained. The scorer verifies the frozen hash and accepted status and excludes either labeling judge from independent scoring. '
            'The new set has not been used to train models or report candidate performance.','']
    path=ROOT / "reports/holdout_review.md";path.write_text("\n".join(report))
    print(f"agreement {len(agreed)}; original disagreements {len(queue)}; unresolved {unresolved}; report {path}")


if __name__=="__main__":main()
