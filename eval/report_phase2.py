#!/usr/bin/env python3
"""Summarize the approved six-model, 24 GB phase and local training pilots."""
import json
from pathlib import Path
from rank_models import SNAPSHOT, load_results, ranking_markdown, rank_key

ROOT=Path(__file__).resolve().parents[1]
MODELS=("lfm2.5-8b-a1b","smollm3-3b","phi4-mini","granite4-micro","qwen3.8-27b","gpt-oss-safeguard-20b")


def main():
    all_runs=load_results()
    runs=[run for run in all_runs if run['provenance'].get('model_id') in MODELS and run['split']=='val']
    lines=["# Phase 2 — local baselines and training preparation", "",
        "Approved scope: six further GGUF checkpoints (39.75 GB), loaded strictly one at a time, "
        "with a 24 GB model/runtime budget while the user works. Qwen3.6-35B-A3B is deferred: it was not downloaded or loaded.","",
        "Subsequent phase: [full Ministral local fine-tuning](ministral_finetune.md) has now completed. "
        "The preparation and pilot descriptions below record the earlier phase; the training report documents the recipe audit, "
        "preserved initial trial and conservative follow-up.", "",
        "The runner uses a process lock, confirms each server exits, checks estimated memory before loading, "
        "and samples process RSS plus macOS physical footprint every 0.1 seconds. An early-stop threshold at 22 GB "
        "leaves a 2 GB allocation margin. This watchdog is not a kernel-enforced physical-memory quota. "
        "Larger references use batch size 256 and microbatch 128 to bound workspace; exact commands are saved.","",
        *ranking_markdown(all_runs),
        "## Phase 2 validation results", "",
        "Same 52 validation calls, two unscored warmups, one request at a time, 4096-token context. "
        "Original and full-policy prompts are separate tracks. The Safeguard reasoning track uses low effort, "
        "256 thinking tokens, 1024 output tokens and a final-answer JSON schema. Its latency is not an equal-budget "
        "comparison with the direct 96-token classifiers.","",
        "| model | prompt / track | correct / 52 | BLOCK→ALLOW / 15 | BLOCK recall | ASK / 9 | p95 s | peak sampled GB* | errors |",
        "|---|---|---|---|---|---|---|---|---|"]
    max_memory=0
    for s in sorted(runs,key=rank_key):
        p=s['provenance'];m=s['metrics']
        peak=max(p.get('peak_sampled_process_rss_gb',0),p.get('peak_sampled_phys_footprint_gb',0));max_memory=max(peak,max_memory)
        lines.append(f"| {p['model_id']} | {s['prompt_mode']} / {p.get('track','direct')} | {m['action_accuracy']['hits']} | "
            f"{m['attack_miss']['hits']} | {100*m['block_recall']['value']:.1f}% | {m['ask_recall']['hits']} | "
            f"{s['latency_s']['p95']:.3f} | {peak:.2f} | {m['error_rate']['hits']} |")
    lines += ["",f"*Peak sampled GB is the larger of process RSS and physical footprint, not their sum or a total-system measure. "
        f"Maximum among these completed evaluation runs: **{max_memory:.2f} GB**. Memory guard aborts are recorded as failures, never valid model decisions.","",
        "The 52-row selection set has only 15 BLOCK and nine ASK calls. Counts and per-run Wilson intervals "
        "are more informative than small percentage differences. No frozen test or new holdout scores were used to select these models.","",
        "## Local training preparation", "",
        "Pinned MLX 4-bit snapshots, isolated Python environment with locked dependency versions, "
        "portable recipes and a guarded launcher are prepared for Qwen3-4B-Instruct-2507 and Ministral-3-3B-Instruct.","",
        "| pilot | microbatches / optimizer updates | peak physical footprint GB | status |", "|---|---|---|---|"]
    saved_pilots=json.loads(SNAPSHOT.read_text()).get('training_pilots',{}) if SNAPSHOT.exists() else {}
    for model in ('qwen3-4b','ministral3-3b'):
        path=ROOT / f"out/mlx-{model}-policy-pilot/evidence.json"
        s=json.loads(path.read_text()) if path.exists() else saved_pilots.get(model)
        if s:
            lines.append(f"| {model} | 8 / 1 | {s['peak_sampled_phys_footprint_gb']:.2f} | {s['status']} |")
    lines += ["", "Every training/validation example was checked for native-template prefix alignment, complete assistant-only "
        "verdict supervision and no truncation. The Qwen conversion's empty-thinking template was replaced at load time "
        "with the pinned publisher template; its vocabulary hash matches the publisher. Ministral's tokenizer regex "
        "correction is applied in preflight and training. No model weights or installed packages were patched.","",
        "These pilots verify local training and masking, not classification improvement. Full recipes are prepared "
        "for 1,200 microbatches, effective batch 8, rank 16 and MLX scale 1.0 (PEFT alpha/r=16/16). "
        "No full fine-tune, GGUF export or hook deployment is claimed. See [local training instructions](../train/LOCAL_TRAINING.md).", "",
        "## New held-out scenarios", "",
        "The original 300 candidates across 100 scenario groups contain 120 MCP calls, 20 goal-flip pairs, "
        "80 twin pairs, ten obfuscated BLOCK hypotheses and 15 forged-approval examples. Exact canonical id/input "
        "overlap checks and schema/shell syntax validation pass. All original calls were retained during review.","",
        "Blind local reviews use Qwen3.8-27B and Safeguard, with no generator labels or metadata in their requests. "
        "After two independent blind-model reviews and author policy adjudication, the frozen set contains **314 calls: "
        "104 ALLOW, 80 ASK and 130 BLOCK**, including 14 separately reviewed policy-anchored ASK additions. "
        "The [review report](holdout_review.md) records the 49 corrected label hypotheses, agreement and adjudications. "
        "This is model-reviewed synthetic data, not human-verified ground truth. The scorer requires the frozen manifest "
        "and accepted-label status; original candidate hypotheses cannot be used as gold. "
        "Judge models are excluded from independent scoring on the benchmark they help label.","",
        "## Selection", "",
        "Keep Ministral-3-3B and Qwen3-4B as the small-model post-training candidates. Qwen3.8-27B is a useful larger "
        "reference within the current memory cap, but its latency and small validation sample do not establish an inline "
        "deployment advantage. Weak zero-shot results for another family do not prove that task-specific SFT would fail.", "",
        "Per-row results, model/data/prompt hashes, server commands and memory evidence are in `eval/out/` and `out/` "
        "(gitignored). [Combined base and fine-tuned results](base_model_comparison.md), [fit catalog](model_selection_plan.md), "
        "[evaluation workflow](../eval/README.md).", ""]
    path=ROOT / 'reports/phase2_results.md';path.write_text('\n'.join(lines));print(path)


if __name__=='__main__':main()
