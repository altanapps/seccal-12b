#!/usr/bin/env python3
"""Freeze local fine-tune evidence and report matched MLX base/adapter scores."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "reports/ministral_finetune_results.json"
RUN = ROOT / "out/mlx-ministral3-3b-policy-conservative"


def load_evidence():
    evidence_path = RUN / "evidence.json"
    if not evidence_path.exists():
        if SNAPSHOT.exists():
            return json.loads(SNAPSHOT.read_text())
        raise ValueError("full training and its evaluations have not completed")
    training = json.loads(evidence_path.read_text())
    if training["status"] != "completed training" or training.get("memory_abort"):
        raise ValueError("cannot report failed or incomplete training as a completed fine-tune")
    config = json.loads((RUN / "run-config.json").read_text())
    selection = json.loads((RUN / "checkpoint-selection.json").read_text())
    adapter = ROOT / selection["adapter_path"] / "adapters.safetensors"
    adapter_hash = hashlib.sha256(adapter.read_bytes()).hexdigest()
    runs = []
    base_prefix = selection.get("base_prefix", "mlx-ministral3-3b-base-policy")
    fine_prefix = selection.get("fine_tuned_prefix", "mlx-ministral3-3b-ft-policy")
    holdout_paths = [ROOT / f"eval/out/{prefix}-holdout.summary.json" for prefix in (base_prefix, fine_prefix)]
    holdout_scored = all(path.exists() for path in holdout_paths)
    if any(path.exists() for path in holdout_paths) and not holdout_scored:
        raise ValueError("holdout comparison is incomplete")
    for role in ("base", "ft"):
        for split in ("val", "holdout"):
            if split == "holdout" and not holdout_scored:
                continue
            prefix = base_prefix if role == "base" else fine_prefix
            name = f"{prefix}-{split}"
            summary = json.loads((ROOT / f"eval/out/{name}.summary.json").read_text())
            runtime = json.loads((ROOT / f"eval/out/{name}.runtime.json").read_text())
            if runtime["exit_code"] or runtime.get("memory_abort"):
                raise ValueError("cannot report an aborted evaluation as a successful run")
            summary["runtime"] = runtime
            if role == "ft" and summary["provenance"]["adapter_sha256"] != adapter_hash:
                raise ValueError("evaluated adapter differs from the frozen selected checkpoint")
            runs.append(summary)
    for split in ("val", "holdout"):
        matching = [r for r in runs if r["split"] == split]
        if matching and (len(matching) != 2 or len({r["dataset_sha256"] for r in matching}) != 1 or len({r["prompt_system_sha256"] for r in matching}) != 1):
            raise ValueError("base and trained evaluations do not use matching data/prompts")
    result = {"run_dir": str(RUN.relative_to(ROOT)), "holdout_scored": holdout_scored,
              "training": training, "config": config, "selection": selection, "adapter_sha256": adapter_hash,
              "adapter_bytes": adapter.stat().st_size, "runs": runs,
              "holdout_file_sha256": hashlib.sha256((ROOT / "data/holdout/accepted.jsonl").read_bytes()).hexdigest()}
    initial = ROOT / "out/mlx-ministral3-3b-policy"
    if initial != RUN and (initial / "checkpoint-selection.json").exists():
        result["initial_trial"] = {"training": json.loads((initial / "evidence.json").read_text()),
            "config": json.loads((initial / "run-config.json").read_text()),
            "selection": json.loads((initial / "checkpoint-selection.json").read_text())}
    SNAPSHOT.write_text(json.dumps(result, indent=2).replace(str(ROOT), "<repo>") + "\n")
    return result


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RUN)
    args = parser.parse_args()
    RUN = (ROOT / args.run_dir).resolve()
    result = load_evidence()
    training, config = result["training"], result["config"]
    peak = max(training.get("peak_sampled_process_rss_gb", 0), training.get("peak_sampled_phys_footprint_gb", 0))
    lines = ["# Ministral-3-3B local fine-tune", "",
        "**Completed, not promoted: retain the base checkpoint.** The selected adapter's validation accuracy improved, "
        "but holdout accuracy declined from 221/314 (70.4%) to 211/314 (67.2%). ASK recognition fell from 26/80 to 11/80 "
        "and false blocks rose from 6/104 to 17/104. Dangerous misses improved slightly, from 18/130 to 16/130. "
        "These mixed results do not justify replacing the base. No deployment was changed.", "",
        f"Completed **{config['iters']:,} microbatches / {config['iters']//config['grad_accumulation_steps']} optimizer updates** "
        "with MLX 4-bit QLoRA on the local Apple GPU. Training used 399 canonical examples and 52 validation examples, "
        "the full labeling-policy prompt and assistant-only verdict loss. No historical test or new holdout examples entered training.", "",
        f"Rank {config['lora_parameters']['rank']}, MLX scale {config['lora_parameters']['scale']}, learning rate "
        f"{config['learning_rate']}, batch {config['batch_size']}, accumulation {config['grad_accumulation_steps']}, "
        f"maximum sequence length {config['max_seq_length']}, all decoder layers, gradient checkpointing, seed {config['seed']}. "
        f"Training peaked at **{peak:.2f} GB** sampled process RSS/physical footprint, under the 24 GB working cap.", "",
        "The saved Ministral recipe was corrected from 150 microbatches / scale 16 to the documented 1,200 / scale 1 "
        "before the initial trial. This conservative follow-up uses its own recorded recipe. Earlier pilot outputs are preserved. "
        "Its eight-microbatch, scale-1 pilot passed before training.", "",
        "## Validation checkpoint selection", "",
        f"Selected the adapter at **{result['selection']['selected_microbatches']} microbatches** using the 52-row validation set. "
        f"{result['selection']['criteria']} The selection manifest was saved before either model's holdout evaluation. "
        "The complete training run and every saved checkpoint remain available.", "",
        "| checkpoint | correct / 52 | BLOCK→ALLOW / 15 | ASK / 9 |", "|---|---|---|---|",
    ]
    for candidate in result["selection"]["candidates"]:
        m = candidate["metrics"]
        label = str(candidate["checkpoint_microbatches"])
        if candidate["checkpoint_microbatches"] == result["selection"]["selected_microbatches"]:
            label = f"**{label} — selected**"
        lines.append(f"| [{label}](eval_{candidate['name']}.md) | {m['action_accuracy']['hits']} | "
                     f"{m['attack_miss']['hits']} | {m['ask_recall']['hits']} |")
    if config["lora_parameters"].get("keys"):
        lines += ["", "Adapter targets: `" + "`, `".join(config["lora_parameters"]["keys"]) + "`. "
            "Learning rate uses the recorded warmup/cosine schedule; schedule steps count optimizer updates.", ""]
    lines += ["",
        "## Matched evaluation", "",
        "Both rows for each split use the same pinned MLX 4-bit checkpoint, native tokenizer with the Mistral regex correction, "
        "full-policy prompt, greedy decoding constrained to the same 19 canonical schema-valid JSON verdicts, "
        "96-token output limit, strict verdict parser, two unscored warmups "
        "and one request at a time. Invalid outputs count as errors and incorrect decisions. "
        "The decoder does not see gold labels. The initial unconstrained probe emitted Markdown and extra JSON fields; "
        "it is preserved locally and excluded from these classification comparisons. "
        "This is a separate serving track from GGUF, with fixed canonical whitespace and field order; differences from that "
        "leaderboard cannot be attributed to training alone.", "",
        "| split | checkpoint | correct | BLOCK→ALLOW | BLOCK recall | ASK recall | false BLOCK | pairs | errors | p95 s |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    for run in result["runs"]:
        m = run["metrics"]
        def count(key):
            return f"{m[key]['hits']}/{m[key]['n']}"
        role = run["provenance"]["checkpoint_kind"]
        lines.append(f"| {run['split']} | [{role}](eval_{run['name']}.md) | {count('action_accuracy')} "
            f"({100*m['action_accuracy']['value']:.1f}%) | {count('attack_miss')} | {count('block_recall')} | "
            f"{count('ask_recall')} | {count('false_block')} | {count('pair_consistency')} | "
            f"{m['error_rate']['hits']} | {run['latency_s']['p95']:.3f} |")
    lines += ["", "Each linked report includes Wilson uncertainty intervals and misjudged IDs. "
        "The 314-call frozen holdout contains 104 ALLOW, 80 ASK and 130 BLOCK calls. It is model-reviewed, "
        "author-adjudicated synthetic data, not human-verified ground truth. "
        + ("Recipe and final-checkpoint choices were fixed before scoring it. Do not tune this model against these holdout outcomes. "
           if result["holdout_scored"] else "No holdout scores were released; it remains reserved. ") +
        "The historical 49-row test set remains untouched in this phase.", "",
        "## Artifacts and reproduction", "",
        f"The selected adapter is saved locally at `{result['selection']['adapter_path']}/adapters.safetensors`. "
        "Its configuration is in the same directory; the effective recipe, every checkpoint, training log and memory "
        f"evidence are under `{result['run_dir']}`. "
        "It requires the pinned MLX base weights; it is not a standalone GGUF. No hook or deployment was changed.", "",
        f"Adapter SHA-256: `{result['adapter_sha256']}`. "
        "[Portable metrics and training evidence](ministral_finetune_results.json) are committed; weights and raw logs remain local. "
        "See [training and evaluation commands](../train/LOCAL_TRAINING.md). Regenerate this report with "
        "`python3 eval/report_mlx_training.py`; a fresh checkout can use the recorded snapshot without loading a model.", ""]
    if "initial_trial" in result:
        lines += ["## Earlier trial — preserved, not promoted", "",
            "The initial all-linear, rank-16, constant-learning-rate 2e-4 run completed 1,200 microbatches / 150 updates. "
            "It regressed against the matched base's 38/52 validation accuracy. Its checkpoints scored:", "",
            "| microbatches | correct / 52 | BLOCK→ALLOW / 15 | ASK / 9 |", "|---|---|---|---|"]
        for run in result["initial_trial"]["selection"]["candidates"]:
            m = run["metrics"]
            lines.append(f"| [{run['checkpoint_microbatches']}](eval_{run['name']}.md) | {m['action_accuracy']['hits']} | "
                         f"{m['attack_miss']['hits']} | {m['ask_recall']['hits']} |")
        lines += ["", "No holdout outcomes were released for that trial. The conservative recipe was chosen using training/validation "
            "evidence only, before any holdout score. Earlier adapters, checkpoints and logs remain preserved.", ""]
    target = ROOT / "reports/ministral_finetune.md"
    target.write_text("\n".join(lines))
    readme = ROOT / "README.md"
    text = readme.read_text()
    start, end = "<!-- mlx-finetune-results:start -->", "<!-- mlx-finetune-results:end -->"
    if start in text and end in text:
        table = ["| split | checkpoint | correct | BLOCK→ALLOW | ASK correct | false BLOCK |",
                 "|---|---|---|---|---|---|"]
        for run in sorted(result["runs"], key=lambda r: (r["split"] != "val", r["provenance"]["checkpoint_kind"] != "base")):
            m = run["metrics"]
            def count(key):
                return f"{m[key]['hits']}/{m[key]['n']}"
            label = run["provenance"]["checkpoint_kind"]
            table.append(f"| {run['split']} | [{label}](reports/eval_{run['name']}.md) | {count('action_accuracy')} "
                f"({100*m['action_accuracy']['value']:.1f}%) | {count('attack_miss')} | {count('ask_recall')} | {count('false_block')} |")
        before, rest = text.split(start, 1)
        _, after = rest.split(end, 1)
        readme.write_text(before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after)
    print(target)


if __name__ == "__main__":
    main()
