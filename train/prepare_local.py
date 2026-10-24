#!/usr/bin/env python3
"""Prepare pinned local QLoRA recipes and train/validation data, without loading weights.

Run with .venv-mlx/bin/python after installing mlx-lm[train]. Downloads are optional:
  .venv-mlx/bin/python train/prepare_local.py --download
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data/synth"))
from common import read_jsonl, render_target  # noqa: E402
sys.path.insert(0, str(ROOT / "eval"))
from run_eval import messages_for  # noqa: E402

PRESETS = {
    "qwen3-4b": {
        "repo": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "revision": "50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b",
    },
    "ministral3-3b": {
        "repo": "mlx-community/Ministral-3-3B-Instruct-2512-4bit",
        "revision": "a962dcb09eee4169c890e544c9eb938f1113fdee",
    },
}


def prepare_data(mode):
    output = ROOT / "data/sft" / f"mlx-{mode}"
    output.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(ROOT / "data/synth/out/accepted.jsonl") + read_jsonl(ROOT / "data/synth/out/adjudicated.jsonl")
    manifest = {"prompt_mode": mode, "splits": {}}
    # Deliberately do not copy the test split into the training directory.
    for split, name in (("train", "train.jsonl"), ("val", "valid.jsonl")):
        records = [{"id": r["id"], "messages": messages_for(r, mode) + [
            {"role": "assistant", "content": render_target(r)}]} for r in rows if r["split"] == split]
        data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        (output / name).write_text(data)
        manifest["splits"][split] = {"n": len(records), "sha256": hashlib.sha256(data.encode()).hexdigest()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--models", nargs="+", choices=sorted(PRESETS), default=list(PRESETS))
    ap.add_argument("--prompt-mode", choices=["original", "policy"], default="policy")
    args = ap.parse_args()
    data = prepare_data(args.prompt_mode)
    recipes = ROOT / "train/recipes"
    recipes.mkdir(exist_ok=True)
    for key in args.models:
        preset = PRESETS[key]
        model = ROOT / "models/train" / key
        if args.download:
            from huggingface_hub import snapshot_download
            snapshot_download(preset["repo"], revision=preset["revision"], local_dir=model,
                              allow_patterns=["*.json", "*.jinja", "*.safetensors", "*.model"], max_workers=2)
            (model / "seccal-source.json").write_text(json.dumps(preset, indent=2) + "\n")
        config = {
            "model": str(model.relative_to(ROOT)), "data": str(data.relative_to(ROOT)), "train": True,
            "fine_tune_type": "lora", "optimizer": "adam", "mask_prompt": True,
            "num_layers": -1, "batch_size": 1, "iters": 1200,
            "grad_accumulation_steps": 8, "learning_rate": 0.0002,
            "max_seq_length": 2048, "grad_checkpoint": True,
            "seed": 3407, "steps_per_report": 40, "steps_per_eval": 400,
            "val_batches": -1, "save_every": 400,
            "adapter_path": f"out/mlx-{key}-{args.prompt_mode}",
            # MLX scale multiplies the delta directly, unlike alpha/r in PEFT.
            "lora_parameters": {"rank": 16, "scale": 1.0, "dropout": 0.0},
        }
        # JSON is also valid YAML for mlx_lm's config parser.
        path = recipes / f"{key}-{args.prompt_mode}.json"
        path.write_text(json.dumps(config, indent=2) + "\n")
        print(f"prepared {key}: {path}")
    print(f"training data: {data}; no test or new holdout examples copied")


if __name__ == "__main__":
    main()
