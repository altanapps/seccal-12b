#!/usr/bin/env python3
"""Select a saved checkpoint using validation, then score the frozen holdout once.

Run with .venv-mlx/bin/python after the full training worker has exited.
No holdout outcome participates in checkpoint selection.
"""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from run_mlx_eval import write_report

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "out/mlx-ministral3-3b-policy"


def select_checkpoint(candidates):
    """Accuracy, fewer dangerous misses, BLOCK/ASK recall, pairs, earlier step."""
    if not candidates or any(run["split"] != "val" or run["rows"] != 52 for run in candidates):
        raise ValueError("checkpoint selection requires complete validation runs, never holdout scores")
    if len({run["dataset_sha256"] for run in candidates}) != 1:
        raise ValueError("checkpoint validation datasets differ")
    def key(run):
        m = run["metrics"]
        return (-m["action_accuracy"]["value"], m["attack_miss"]["value"],
                -m["block_recall"]["value"], -m["ask_recall"]["value"],
                -m["pair_consistency"]["value"], run["checkpoint_microbatches"])
    return min(candidates, key=key)


def evaluate(name, split, adapter=None):
    path = ROOT / f"eval/out/{name}-{split}.summary.json"
    runtime = path.with_name(f"{name}-{split}.runtime.json")
    if path.exists() and runtime.exists():
        evidence = json.loads(runtime.read_text())
        if evidence["exit_code"] == 0 and not evidence.get("memory_abort"):
            return json.loads(path.read_text())
    command = [sys.executable, str(ROOT / "eval/run_mlx_eval.py"), "--name", name, "--splits", split]
    if adapter:
        command += ["--adapter", str(adapter)]
    subprocess.run(command, cwd=ROOT, check=True)
    return json.loads(path.read_text())


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-only", action="store_true", help="select and inspect a checkpoint before releasing any holdout scores")
    parser.add_argument("--run-dir", type=Path, default=RUN)
    parser.add_argument("--tag", default="policy")
    args = parser.parse_args()
    RUN = (ROOT / args.run_dir).resolve()
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in args.tag):
        parser.error("invalid evaluation tag")
    fine_prefix = f"mlx-ministral3-3b-ft-{args.tag}"
    training = json.loads((RUN / "evidence.json").read_text())
    if training["status"] != "completed training" or training.get("memory_abort"):
        raise ValueError("full training has not completed successfully")
    config = json.loads((RUN / "run-config.json").read_text())
    baseline_name = "mlx-ministral3-3b-base-policy"
    evaluate(baseline_name, "val")
    candidates = []
    for step in range(config["save_every"], config["iters"] + 1, config["save_every"]):
        source = RUN / f"{step:07d}_adapters.safetensors"
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        adapter = RUN.with_name(RUN.name + f"-step{step}")
        adapter.mkdir(exist_ok=True)
        target = adapter / "adapters.safetensors"
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != source_hash:
            raise ValueError("preserving different existing checkpoint weights")
        if not target.exists():
            shutil.copy2(source, target)
            shutil.copy2(RUN / "adapter_config.json", adapter / "adapter_config.json")
            (adapter / "checkpoint.json").write_text(json.dumps({"microbatches": step,
                "optimizer_updates": step // config["grad_accumulation_steps"], "sha256": source_hash}, indent=2) + "\n")
        run = evaluate(f"{fine_prefix}-step{step}", "val", adapter)
        run["checkpoint_microbatches"] = step
        run["adapter_path"] = str(adapter.relative_to(ROOT))
        candidates.append(run)
    selected = select_checkpoint(candidates)
    selection = {"criteria": "Highest validation action accuracy, then fewer BLOCK-to-ALLOW misses, higher BLOCK recall, ASK recall, pair consistency, earlier checkpoint.",
        "selected_microbatches": selected["checkpoint_microbatches"], "adapter_path": selected["adapter_path"],
        "adapter_sha256": selected["provenance"]["adapter_sha256"], "candidates": candidates,
        "base_prefix": baseline_name, "fine_tuned_prefix": fine_prefix,
        "holdout_used_for_selection": False}
    manifest = RUN / "checkpoint-selection.json"
    if manifest.exists() and json.loads(manifest.read_text())["adapter_sha256"] != selection["adapter_sha256"]:
        raise ValueError("checkpoint selection was already frozen to a different adapter")
    # Freeze selection on disk BEFORE either model produces holdout scores.
    manifest.write_text(json.dumps(selection, indent=2) + "\n")
    alias = f"{fine_prefix}-val"
    original_name = selected["name"]
    chosen = {**selected, "name": alias, "selected_from": original_name}
    (ROOT / f"eval/out/{alias}.summary.json").write_text(json.dumps(chosen, indent=2) + "\n")
    for suffix in ("jsonl", "runtime.json"):
        shutil.copy2(ROOT / f"eval/out/{original_name}.{suffix}", ROOT / f"eval/out/{alias}.{suffix}")
    predictions = [json.loads(line) for line in (ROOT / f"eval/out/{alias}.jsonl").read_text().splitlines()]
    write_report(chosen, predictions)
    print(f"Selected step {selection['selected_microbatches']} using validation only", flush=True)
    if args.validation_only:
        return
    evaluate(baseline_name, "holdout")
    evaluate(fine_prefix, "holdout", ROOT / selection["adapter_path"])
    subprocess.run([sys.executable, str(ROOT / "eval/report_mlx_training.py"), "--run-dir", str(RUN)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
