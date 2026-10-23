# /// script
# requires-python = ">=3.10"
# dependencies = ["unsloth", "trl>=0.15", "datasets", "transformers", "torch"]
# ///
"""LoRA SFT of a small instruct model on the seccal dataset, then GGUF export.

Runs on a CUDA GPU (a free Colab T4 is enough for the 1.2B and 4B presets);
it does not run on the Mac. See train/README.md for the Colab / HF Jobs path.

  python train/sft_unsloth.py --model qwen3-4b --train data/sft/train.jsonl \
      --val data/sft/val.jsonl --out out/seccal-qwen3-4b [--epochs 3] [--lr 2e-4]

Presets (see PRESETS): each fixes the HF model id, the LoRA target modules for
that architecture, and the chat-template boundary markers used for
completion-only loss. Picking the wrong module list silently skips layers and
the wrong markers make the loss mask miss the assistant turn, so the script
asserts the markers occur in a rendered example before training.

Rows already carry the system prompt and rendering from data/synth/common.py.
Nothing here reformats them, so training, eval and the hook stay identical.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PRESETS = {
    # Iteration 1 base. Hybrid conv + GQA: generic Llama module names skip layers.
    "lfm2.5-1.2b": {
        "model": "LiquidAI/LFM2.5-1.2B-Instruct",
        "targets": ["q_proj", "k_proj", "v_proj", "out_proj", "in_proj", "w1", "w2", "w3"],
        "instruction_part": "<|im_start|>user\n",
        "response_part": "<|im_start|>assistant\n",
    },
    # Iteration 2 recommendation: same ChatML markers, standard Llama-style modules,
    # no thinking tokens, Apache-2.0. ~2.5 GB at Q4_K_M.
    "qwen3-4b": {
        "model": "unsloth/Qwen3-4B-Instruct-2507",
        "targets": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        "instruction_part": "<|im_start|>user\n",
        "response_part": "<|im_start|>assistant\n",
    },
    # Same family as iteration 1, larger. LFM Open License (commercial use limits).
    "lfm2-2.6b": {
        "model": "LiquidAI/LFM2-2.6B",
        "targets": ["q_proj", "k_proj", "v_proj", "out_proj", "in_proj", "w1", "w2", "w3"],
        "instruction_part": "<|im_start|>user\n",
        "response_part": "<|im_start|>assistant\n",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="lfm2.5-1.2b", choices=sorted(PRESETS), help="preset name")
    ap.add_argument("--model-id", default=None, help="override the preset's HF model id")
    ap.add_argument("--revision", default=None, help="pin the HF model revision (commit sha or tag)")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", default=None, help="default: out/seccal-<preset>")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--bs", type=int, default=2, help="per-device batch size")
    ap.add_argument("--grad-accum", type=int, default=4, help="effective batch = bs * grad_accum")
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--load-in-4bit", action="store_true", help="QLoRA; use if 16-bit LoRA OOMs on a T4")
    ap.add_argument("--quants", nargs="+", default=["q4_k_m", "q8_0"])
    ap.add_argument("--no-gguf", action="store_true")
    args = ap.parse_args()

    preset = PRESETS[args.model]
    model_id = args.model_id or preset["model"]
    out = Path(args.out or f"out/seccal-{args.model}")

    # Imported late so --help and `from sft_unsloth import PRESETS` work without the training stack.
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only
    from trl import SFTConfig, SFTTrainer
    from datasets import load_dataset
    import torch

    # Colab's free T4 (Turing) has no bf16; Ampere+ does. Pick whichever the GPU supports.
    use_bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    print(f"preset: {args.model}  model: {model_id}  revision: {args.revision or 'latest'}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'}  "
          f"precision: {'bf16' if use_bf16 else 'fp16'}  4bit: {args.load_in_4bit}")

    load_kwargs = dict(model_name=model_id, max_seq_length=args.max_seq, dtype=None,
                       load_in_4bit=args.load_in_4bit)
    if args.revision:
        load_kwargs["revision"] = args.revision
    model, tokenizer = FastLanguageModel.from_pretrained(**load_kwargs)
    model = FastLanguageModel.get_peft_model(
        model, r=args.r, lora_alpha=args.alpha, lora_dropout=0.0, bias="none",
        target_modules=preset["targets"], use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    ds = load_dataset("json", data_files={"train": args.train, "val": args.val})

    def render(batch):
        return {"text": [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
                         for m in batch["messages"]]}

    ds = ds.map(render, batched=True, remove_columns=[c for c in ds["train"].column_names if c != "messages"])
    sample = ds["train"][0]["text"]
    ip, rp = preset["instruction_part"], preset["response_part"]
    assert ip in sample and rp in sample, (
        f"chat-template markers {ip!r}/{rp!r} not found in a rendered example; fix the preset:\n" + sample
    )
    print("rendered example:\n" + sample)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds["val"],
        args=SFTConfig(
            output_dir=str(out / "checkpoints"),
            dataset_text_field="text",
            max_seq_length=args.max_seq,
            per_device_train_batch_size=args.bs,
            gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            weight_decay=0.01,
            logging_steps=10,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            bf16=use_bf16,
            fp16=not use_bf16,
            seed=args.seed,
            report_to="none",
        ),
    )
    trainer = train_on_responses_only(trainer, instruction_part=ip, response_part=rp)
    stats = trainer.train()
    out.mkdir(parents=True, exist_ok=True)
    (out / "train_stats.json").write_text(json.dumps({
        **stats.metrics, "preset": args.model, "model_id": model_id, "revision": args.revision,
        "lora_r": args.r, "lora_alpha": args.alpha, "epochs": args.epochs, "lr": args.lr,
    }, indent=2))
    print(trainer.evaluate())

    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    if not args.no_gguf:
        # Merges LoRA into the base and writes one GGUF per quant (Unsloth may place them under gguf/ or gguf_gguf/).
        model.save_pretrained_gguf(str(out / "gguf"), tokenizer, quantization_method=args.quants)
        print("GGUFs written under", out)


if __name__ == "__main__":
    main()
