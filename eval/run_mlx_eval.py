#!/usr/bin/env python3
"""Sequential, guarded MLX base/adapter evaluation on val and frozen holdout.

Uses native templates and canonical-verdict constrained greedy generation, with strict verdict
parsing. Compare MLX base to MLX adapter; this is a different serving track from
the grammar-constrained llama.cpp leaderboard. Never trains or scores historical test rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train"))
from run_local import tokenizer_options
from run_eval import messages_for, parse_verdict
from common import ACTIONS, CATEGORIES
from metrics import summarize
from run_matrix import sweep_lock, measure_memory, process_memory


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_verdicts():
    return [json.dumps({"action": action, "category": category})
            for action in ACTIONS for category in CATEGORIES
            if (action == "ALLOW") == (category == "benign")]


class VerdictTrie:
    """Token-prefix constraints for all 19 schema-valid verdicts, never gold labels."""
    def __init__(self, sequences, eos_ids):
        self.prefixes = {}
        self.eos_ids = set(eos_ids)
        self.terminals = {tuple(sequence) for sequence in sequences}
        for sequence in sequences:
            for index, token in enumerate(sequence):
                self.prefixes.setdefault(tuple(sequence[:index]), set()).add(token)
            self.prefixes.setdefault(tuple(sequence), set()).update(eos_ids)

    def allowed(self, generated):
        # MLX computes one token ahead before its consumer notices EOS.
        if generated and generated[-1] in self.eos_ids:
            completed = list(generated)
            while completed and completed[-1] in self.eos_ids:
                completed.pop()
            if tuple(completed) in self.terminals:
                return sorted(self.eos_ids)
        result = self.prefixes.get(tuple(generated))
        if not result:
            raise ValueError("generated token prefix left the verdict language")
        return sorted(result)


def evaluation_rows(split):
    if split == "holdout":
        path = ROOT / "data/holdout/accepted.jsonl"
        manifest = json.loads(path.with_name("frozen.json").read_text())
        if manifest["status"] != "frozen" or manifest["file"] != path.name or digest(path) != manifest["sha256"]:
            raise ValueError("holdout manifest does not match frozen data")
        if "ministral3-3b" in manifest["exclude_models_as_independent_test"]:
            raise ValueError("model helped label this holdout")
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(rows) != manifest["rows"] or any(row.get("review_status") != "accepted" for row in rows):
            raise ValueError("holdout rows are incomplete or not accepted")
        return rows
    rows = []
    for filename in ("accepted", "adjudicated"):
        rows.extend(json.loads(line) for line in
                    (ROOT / f"data/synth/out/{filename}.jsonl").read_text().splitlines() if line.strip())
    return [row for row in rows if row["split"] == "val"]


def write_report(summary, predictions):
    m = summary["metrics"]
    lines = [f"# MLX evaluation: {summary['name']}", "",
        f"Split: **{summary['split']}**, rows: **{summary['rows']}**. Full-policy prompt, native Ministral template, "
        "temperature 0, 96-token budget, two unscored warmups, one request at a time. "
        "Greedy decoding constrained to the 19 canonical schema-valid JSON verdicts; strict parsing still applies. "
        "Constraints contain no gold labels and prevent Markdown, extra fields or invalid action/category combinations. "
        "Compare against the matching MLX base run, rather than attributing differences from GGUF to training alone.", "",
        "| metric | count | rate | 95% Wilson interval |", "|---|---|---|---|"]
    for label in ("action_accuracy", "block_recall", "attack_miss", "ask_recall", "allow_precision", "false_block", "pair_consistency", "error_rate"):
        value = m[label]
        interval = value["ci95"]
        interval_text = f"{100*interval[0]:.1f}–{100*interval[1]:.1f}%" if interval else "n/a"
        rate_text = f"{100*value['value']:.1f}%" if value["value"] is not None else "n/a"
        lines.append(f"| {label} | {value['hits']}/{value['n']} | {rate_text} | {interval_text} |")
    lines += ["", f"p50 / p95 latency: {summary['latency_s']['p50']:.3f} / {summary['latency_s']['p95']:.3f} s. "
        "These timings use the MLX Python backend and are not directly comparable to llama.cpp HTTP timings.", "",
        "## Misjudged calls", ""]
    for row in predictions:
        if row["gold_action"] != row["pred_action"]:
            lines.append(f"- `{row['id']}`: gold **{row['gold_action']}**, predicted **{row['pred_action']}**.")
    if summary["split"] == "holdout":
        lines += ["", "The frozen holdout is model-reviewed, author-adjudicated synthetic data, not human-verified ground truth. "
                  "It was not used in training or to select this run's recipe."]
    (ROOT / f"reports/eval_{summary['name']}.md").write_text("\n".join(lines) + "\n")


def worker(args):
    import mlx.core as mx
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    mx.set_memory_limit(20_000_000_000)
    mx.set_cache_limit(500_000_000)
    mx.random.seed(3407)
    model_path = ROOT / "models/train/ministral3-3b"
    model, tokenizer = load(str(model_path), adapter_path=str(args.adapter.resolve()) if args.adapter else None,
                            tokenizer_config=tokenizer_options("ministral3-3b"), trust_remote_code=False)
    model.eval()
    source = json.loads((model_path / "seccal-source.json").read_text())
    sampler = make_sampler(temp=0)
    verdicts = valid_verdicts()
    sequences = [tokenizer.encode(text, add_special_tokens=False) for text in verdicts]
    if any(tokenizer.decode(tokens) != text for tokens, text in zip(sequences, verdicts)):
        raise ValueError("canonical verdict tokenization does not round-trip")
    trie = VerdictTrie(sequences, tokenizer.eos_token_ids)
    def query(row):
        prompt = tokenizer.apply_chat_template(messages_for(row, "policy"), tokenize=True, add_generation_prompt=True, return_dict=False)
        if len(prompt) + 96 > 4096:
            raise ValueError("evaluation prompt exceeds the fixed context budget")
        def constrain(tokens, logits):
            allowed = mx.array(trie.allowed(tokens[len(prompt):].tolist()))
            masked = mx.full(logits.shape, -float("inf"))
            masked[:, allowed] = logits[:, allowed]
            return masked
        start = time.perf_counter()
        text = generate(model, tokenizer, prompt=prompt, max_tokens=96, sampler=sampler, logits_processors=[constrain], verbose=False)
        mx.synchronize()
        elapsed = time.perf_counter() - start
        mx.clear_cache()
        return text, round(elapsed, 3)
    warmup = {"user_goal": "inspect the working tree", "tool_name": "Bash", "tool_input": {"command": "git status --short"}}
    for _ in range(2):
        query(warmup)
    for split in args.splits:
        rows = evaluation_rows(split)
        name = f"{args.name}-{split}"
        predictions = []
        path = ROOT / f"eval/out/{name}.jsonl"
        with path.open("x") as output:
            for index, row in enumerate(rows, 1):
                text, elapsed = query(row)
                action, category = parse_verdict(text)
                prediction = {**row, "pred_action": action, "pred_category": category, "raw": text, "latency_s": elapsed}
                predictions.append(prediction)
                output.write(json.dumps(prediction, ensure_ascii=False) + "\n")
                output.flush()
                if index % 20 == 0 or index == len(rows):
                    print(f"{name}: {index}/{len(rows)}", flush=True)
        latency = sorted(row["latency_s"] for row in predictions)
        provenance = {"model_id": "ministral3-3b-policy-ft" if args.adapter else "ministral3-3b",
            "checkpoint_kind": "fine-tuned" if args.adapter else "base", "track": "mlx-canonical-verdict",
            "model_source": source, "tokenizer_options": ["fix_mistral_regex"], "context_tokens": 4096,
            "adapter_sha256": digest(args.adapter / "adapters.safetensors") if args.adapter else None,
            "adapter_config_sha256": digest(args.adapter / "adapter_config.json") if args.adapter else None}
        provenance["evaluation_code_sha256"] = digest(Path(__file__))
        provenance["verdict_language_sha256"] = hashlib.sha256(json.dumps(verdicts).encode()).hexdigest()
        if args.adapter and (args.adapter / "checkpoint.json").exists():
            provenance["training_checkpoint"] = json.loads((args.adapter / "checkpoint.json").read_text())
        summary = {"name": name, "split": split, "rows": len(rows), "prompt_mode": "policy",
            "dataset_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "prompt_system_sha256": hashlib.sha256(messages_for(warmup, "policy")[0]["content"].encode()).hexdigest(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "concurrency": 1, "max_tokens": 96, "warmup_requests": 2, "provenance": provenance,
            "metrics": summarize(predictions), "latency_s": {"p50": latency[len(latency)//2], "p95": latency[int(len(latency)*.95)-1]}}
        (ROOT / f"eval/out/{name}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_report(summary, predictions)
        print(f"{name}: {summary['metrics']['action_accuracy']['hits']}/{len(rows)} correct", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--splits", nargs="+", choices=("val", "holdout"), default=["val", "holdout"])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in args.name):
        parser.error("invalid output name")
    if args.worker:
        worker(args)
        return
    os.chdir(ROOT)
    for split in args.splits:
        evaluation_rows(split)
        for suffix in ("jsonl", "summary.json", "runtime.json"):
            if (ROOT / f"eval/out/{args.name}-{split}.{suffix}").exists():
                raise FileExistsError("preserving existing evaluation; choose a new --name")
    stop, sample = threading.Event(), {}
    process_memory(os.getpid())
    with sweep_lock():
        process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), *sys.argv[1:], "--worker"], cwd=ROOT)
        monitor = threading.Thread(target=measure_memory, args=(process, stop, sample, 24), daemon=True)
        monitor.start()
        try:
            code = process.wait()
        finally:
            stop.set()
            monitor.join(timeout=4)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        for split in args.splits:
            runtime = {**sample, "exit_code": code, "max_runtime_gb": 24, "memory_abort_threshold_gb": 22}
            (ROOT / f"eval/out/{args.name}-{split}.runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
        if code or sample.get("memory_abort"):
            raise RuntimeError(f"evaluation failed: exit={code}, {sample}")


if __name__ == "__main__":
    main()
