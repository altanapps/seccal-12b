#!/usr/bin/env python3
"""Build a validation leaderboard from local model sweep summaries."""
from __future__ import annotations

import json
from pathlib import Path

from download_models import ROOT, load_models, model_path
from metrics import summarize
from rank_models import load_results, ranking_markdown, rank_key


def pct(metric):
    return "n/a" if metric["value"] is None else f"{100 * metric['value']:.1f}%"


def main():
    catalog = load_models()
    summaries = load_results()
    lines = ["# Local base-model comparison", "",
             "Selection set: the existing 52 validation rows (28 ALLOW, 9 ASK, 15 BLOCK; 10 contrast pairs). "
             "The frozen 49-row test set has not been run in this sweep. "
             "These small samples cannot establish production safety; even 0/15 attack misses has a roughly 20% Wilson upper bound.", "",
             "Direct runs use one server slot, request concurrency 1, two unscored warmups, temperature 0, "
             "the repository verdict grammar, 4096-token context and thinking disabled. Reasoning runs are labeled separately, "
             "with low effort, 256 thinking tokens, a 1024-token total output budget and final-answer JSON schema. Original and policy prompts are separate tracks. "
             "The policy track appends the existing labeling policy, which is not the prompt used to train iteration 1.", "",
             *ranking_markdown(summaries),
             "## All measured prompt variants", "",
             "Within each prompt track, successful runs are sorted by the same ranking criteria; protocol failures follow.", "",
             "| model / prompt | correct | BLOCK recall | BLOCK→ALLOW | ASK recall | ALLOW precision | false BLOCK | pairs | p50 / p95 s | errors |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in sorted(summaries, key=lambda s: (s["prompt_mode"], bool(s["metrics"]["error_rate"]["hits"]), rank_key(s))):
        m, lat = s["metrics"], s["latency_s"]
        time_text = f"{lat['p50']:.3f} / {lat['p95']:.3f}" if lat["p50"] is not None else "n/a"
        label = s["provenance"].get("model_id", s["name"])
        if s["provenance"].get("track") == "reasoning":label += " (reasoning)"
        if m["error_rate"]["hits"] == s["rows"]:
            lines.append(f"| {label} / {s['prompt_mode']} | protocol failure | n/a | n/a | n/a | n/a | n/a | n/a | {time_text} | {s['rows']} |")
            continue
        lines.append(f"| {label} / {s['prompt_mode']} | {m['action_accuracy']['hits']}/{s['rows']} | "
                     f"{pct(m['block_recall'])} | {m['attack_miss']['hits']}/{m['attack_miss']['n']} | "
                     f"{pct(m['ask_recall'])} | {pct(m['allow_precision'])} | {pct(m['false_block'])} | "
                     f"{pct(m['pair_consistency'])} | {time_text} | {m['error_rate']['hits']} |")
    historical = ROOT / "eval/out/ft-q4-val.jsonl"
    if historical.exists():
        predictions = [json.loads(line) for line in historical.read_text().splitlines() if line.strip()]
        m = summarize(predictions)
        lines += ["", "Historical iteration-1 fine-tuned LFM Q4 on the same validation split: "
                  f"{m['action_accuracy']['hits']}/52 correct, BLOCK recall {pct(m['block_recall'])}, "
                  f"BLOCK→ALLOW {m['attack_miss']['hits']}/15, ASK recall {pct(m['ask_recall'])}. "
                  "Its old latency numbers used different concurrency and are not comparable to this sweep."]
    lines += ["", "## Downloads and runtime evidence", "",
              "Artifact sizes are decimal GB. RSS is sampled process resident memory, not total unified-memory use; "
              "do not interpret it as the full Metal allocation or use it alone to certify a fit.", "",
              "| initial model | GGUF GB | download | runtime | sampled peak process RSS GB |", "|---|---|---|---|---|"]
    for model in [m for m in catalog if m["wave"] == "initial"]:
        artifacts = model["artifacts"]
        present = all(model_path(model, a).exists() for a in artifacts)
        matching = [s for s in summaries if s["provenance"].get("model_id") == model["id"]]
        clean = [s for s in matching if s["metrics"]["error_rate"]["hits"] == 0]
        rss = max((s["provenance"].get("peak_sampled_process_rss_gb", 0) for s in matching), default=0)
        runtime = "protocol adapter required" if model.get("direct_eval_compatible") is False else ("measured" if clean else "pending / inspect logs")
        lines.append(f"| {model['id']} | {sum(a['bytes'] for a in artifacts) / 1e9:.2f} | "
                     f"{'verified locally' if present else ('recorded run; absent locally' if matching else 'pending')} | {runtime} | "
                     f"{rss:.2f} |")
    lines += ["", "Per-run reports contain uncertainty intervals, tool slices and individual errors. "
              "Full per-row predictions, model revisions, artifact hashes, prompt/dataset hashes and server commands are in `eval/out/` (gitignored).", ""]
    target = ROOT / "reports/base_model_comparison.md"
    target.write_text("\n".join(lines))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
