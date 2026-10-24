#!/usr/bin/env python3
"""Shared validation ranking and portable evidence for the Markdown reports."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from metrics import summarize

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "reports/base_model_results.json"


def load_results():
    """Merge recorded evidence with newer local runs, keyed by unique run name."""
    recorded = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    runs = {s["name"]: s for s in recorded.get("runs", [])}
    for path in sorted((ROOT / "eval/out").glob("base-*.summary.json")):
        summary = json.loads(path.read_text())
        if summary["split"] == "val":
            runs[summary["name"]] = summary
    for summary in historical_results():
        runs[summary["name"]] = summary
    return list(runs.values())


def validate_historical_rows(predictions, canonical):
    """Require identical IDs, inputs, labels and metadata on the full val split."""
    if len(canonical) != 52 or len(predictions) != 52:
        raise ValueError("historical comparison requires the complete 52-row validation set")
    expected = {r["id"]: r for r in canonical}
    if len({p["id"] for p in predictions}) != 52 or set(expected) != {p["id"] for p in predictions}:
        raise ValueError("historical validation IDs differ from the canonical set")
    for prediction in predictions:
        row = expected[prediction["id"]]
        if any(prediction.get(key) != value for key, value in row.items()):
            raise ValueError(f"historical validation input/label differs: {prediction['id']}")


def historical_results():
    paths = [(quant, ROOT / f"eval/out/ft-{quant}-val.jsonl") for quant in ("q4", "q8")]
    if not any(path.exists() for _, path in paths):
        return []
    canonical = []
    for name in ("accepted", "adjudicated"):
        canonical.extend(json.loads(line) for line in
                         (ROOT / f"data/synth/out/{name}.jsonl").read_text().splitlines() if line.strip())
    canonical = [row for row in canonical if row["split"] == "val"]
    dataset_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    results = []
    for quant, path in paths:
        if not path.exists():
            continue
        predictions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        validate_historical_rows(predictions, canonical)
        latency = sorted(p["latency_s"] for p in predictions if p["latency_s"] is not None)
        quant_name = "Q4_K_M" if quant == "q4" else "Q8_0"
        results.append({
            "name": f"ft-{quant}-val", "split": "val", "rows": len(predictions),
            "prompt_mode": "original", "dataset_sha256": dataset_hash, "concurrency": 4,
            "provenance": {
                "model_id": f"lfm2.5-1.2b-seccal-ft-{quant}",
                "display_name": f"LFM2.5-1.2B seccal FT {quant_name}",
                "source_model": "LiquidAI/LFM2.5-1.2B-Instruct",
                "checkpoint_kind": "fine-tuned", "quantization": quant_name,
                "track": "direct", "historical": True,
                "source_predictions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "validation_verification": "All 52 unique IDs and every canonical field match the current validation split.",
                "runtime_note": "Historical concurrency 4; latency is not comparable to the new concurrency-1 sweep. Runtime/model revision metadata was not recorded.",
            },
            "metrics": summarize(predictions),
            "latency_s": {"p50": latency[len(latency) // 2], "p95": latency[int(len(latency) * .95) - 1],
                          "note": "Historical concurrency 4; excluded from ranking latency tie-breaks."},
        })
    return results


def latency_text(run, percentiles=("p95",)):
    if run["provenance"].get("historical"):
        return "n/a (legacy c=4)"
    return " / ".join(f"{run['latency_s'][key]:.3f}" if run['latency_s'][key] is not None else "n/a"
                      for key in percentiles)


def rank_key(run):
    """Accuracy first; ties prefer fewer attack misses, then BLOCK/ASK recall."""
    m = run["metrics"]
    return (
        -(m["action_accuracy"]["value"] or 0),
        m["attack_miss"]["value"] if m["attack_miss"]["value"] is not None else 1,
        -(m["block_recall"]["value"] or 0),
        -(m["ask_recall"]["value"] or 0),
        -(m["pair_consistency"]["value"] or 0),
        run["latency_s"]["p95"] if run["latency_s"]["p95"] is not None and not run["provenance"].get("historical") else float("inf"),
        run["name"],
    )


def ranked_models(runs):
    best = {}
    for run in runs:
        if run["split"] != "val" or run["rows"] != 52 or run["metrics"]["error_rate"]["hits"]:
            continue
        model = run["provenance"]["model_id"]
        if model not in best or rank_key(run) < rank_key(best[model]):
            best[model] = run
    return sorted(best.values(), key=rank_key)


def ranking_table(runs, report_prefix=""):
    lines = [
        "| rank | model | checkpoint | selected prompt / track | correct | BLOCK→ALLOW / 15 | BLOCK / 15 | ASK / 9 | p95 s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for number, run in enumerate(ranked_models(runs), 1):
        m, p = run["metrics"], run["provenance"]
        model = p.get("display_name", p["model_id"])
        if number == 1:
            model = f"**{model} — BEST measured accuracy**"
        report = f"{report_prefix}eval_{run['name']}.md"
        lines.append(
            f"| {number} | [{model}]({report}) | {p.get('checkpoint_kind', 'base')} | "
            f"{run['prompt_mode']} / {p.get('track', 'direct')} | "
            f"{m['action_accuracy']['hits']}/{run['rows']} ({100*m['action_accuracy']['value']:.1f}%) | "
            f"{m['attack_miss']['hits']} | {m['block_recall']['hits']} | {m['ask_recall']['hits']} | "
            f"{latency_text(run)} |"
        )
    return lines


def ranking_markdown(runs):
    lines = [
        "## Best-to-worst model ranking", "",
        "One row per base checkpoint or fine-tuned quantization, selecting its best measured prompt on the same 52-row validation set. "
        "Ranked by action accuracy, then fewer BLOCK→ALLOW misses, higher BLOCK recall, ASK recall, "
        "pair consistency and lower p95 latency. Only complete, error-free runs qualify. "
        "This is a validation selection ranking, not an independent test or a production-safety ranking; "
        "choosing the prompt on these same rows can overestimate performance. Safeguard uses a larger reasoning budget. "
        "The two historical seccal fine-tuned quantizations use the original prompt; all 52 IDs, inputs and labels were verified "
        "against the current canonical validation set. Their concurrency-4 latencies are excluded from speed comparisons and latency tie-breaks.", "",
        *ranking_table(runs),
    ]
    lines += ["",
        "**Best measured accuracy: Qwen3.8-27B, policy prompt — 44/52 (84.6%), zero observed BLOCK→ALLOW misses, "
        "p95 1.325 s.** **Best fast local candidate: Ministral-3-3B, policy prompt — 42/52 (80.8%), "
        "zero observed BLOCK→ALLOW misses, p95 0.220 s.** Its ASK recall is 0/9; Qwen's is 2/9. "
        "Both still need evaluation beyond this small selection set.", "",
        "Unranked: LFM2.5-2.6B loaded but failed the direct verdict protocol on all 52 calls. "
        "Other catalog entries have no comparable completed run. Qwen3.6-35B-A3B remains deferred and was not downloaded or loaded.", "",
        "Portable metrics and provenance: [recorded results](base_model_results.json). "
        "The 49-row test split and the new 314-call holdout were not scored in this sweep.", "",
    ]
    return lines


def update_readme(runs):
    path = ROOT / "README.md"
    text = path.read_text()
    start, end = "<!-- validation-ranking:start -->", "<!-- validation-ranking:end -->"
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(before + start + "\n\n" + "\n".join(ranking_table(runs, "reports/")) + "\n\n" + end + after)


def snapshot_results():
    """Freeze measured summaries without publishing machine-specific file paths."""
    runs = load_results()
    previous = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    pilots = previous.get("training_pilots", {})
    for model in ("qwen3-4b", "ministral3-3b"):
        path = ROOT / f"out/mlx-{model}-policy-pilot/evidence.json"
        if path.exists():
            evidence = json.loads(path.read_text())
            pilots[model] = {k: evidence[k] for k in (
                "status", "peak_sampled_phys_footprint_gb", "peak_sampled_process_rss_gb"
            ) if k in evidence}
            pilots[model].update(microbatches=8, optimizer_updates=1)
    result = {"schema_version": 1, "selection_split": "val", "rows_per_run": 52,
              "runs": sorted(runs, key=lambda s: s["name"]), "training_pilots": pilots}
    # Preserve exact commands while making repository paths portable.
    SNAPSHOT.write_text(json.dumps(result, indent=2).replace(str(ROOT), "<repo>") + "\n")
    print(SNAPSHOT)


if __name__ == "__main__":
    snapshot_results()
