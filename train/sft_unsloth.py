# /// script
# requires-python = ">=3.10"
# dependencies = ["unsloth", "trl>=0.15", "datasets", "transformers", "torch"]
# ///
"""LoRA SFT of LiquidAI/LFM2.5-1.2B-Instruct on the seccal dataset, then GGUF export.

This runs on a CUDA GPU (free Colab T4 is enough for 1.2B); it does not run on
the Mac. See train/README.md for the exact Colab / HF Jobs invocation.

  python train/sft_unsloth.py --train data/sft/train.jsonl --val data/sft/val.jsonl \
      --out out/seccal-12b [--epochs 3] [--lr 2e-4] [--r 16]

Notes that matter for this model:
- LFM2.5 is a hybrid conv + grouped-query-attention architecture. Its LoRA
  target modules are q_proj, k_proj, v_proj, out_proj, in_proj, w1, w2, w3.
  A generic Llama list (gate_proj/up_proj/down_proj/o_proj) silently skips
  layers, so do not "simplify" this.
- Loss is computed on the assistant turn only (train_on_responses_only). The
  instruction/response markers below are the LFM2 chat-template boundaries;
  the script asserts they occur in a rendered example before training.
- Rows already carry the system prompt and rendering from data/synth/common.py.
  Nothing here reformats them, so training, eval and the hook stay identical.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import load_dataset

MODEL = "LiquidAI/LFM2.5-1.2B-Instruct"
LFM_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj", "in_proj", "w1", "w2", "w3"]
INSTRUCTION_PART = "<|im_start|>user\n"
RESPONSE_PART = "<|im_start|>assistant\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", default="out/seccal-12b")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--bs", type=int, default=2, help="per-device batch size")
    ap.add_argument("--grad-accum", type=int, default=4, help="effective batch = bs * grad_accum")
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--quants", nargs="+", default=["q4_k_m", "q8_0"])
    ap.add_argument("--no-gguf", action="store_true")
    args = ap.parse_args()

    from unsloth import FastLanguageModel  # imported late so --help works without a GPU
    from unsloth.chat_templates import train_on_responses_only
    from trl import SFTConfig, SFTTrainer
    import torch

    # Colab's free T4 (Turing) has no bf16; Ampere+ does. Pick whichever the GPU supports.
    use_bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'}  "
          f"precision: {'bf16' if use_bf16 else 'fp16'}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL, max_seq_length=args.max_seq, dtype=None, load_in_4bit=False,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=args.r, lora_alpha=args.alpha, lora_dropout=0.0, bias="none",
        target_modules=LFM_TARGETS, use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    ds = load_dataset("json", data_files={"train": args.train, "val": args.val})

    def render(batch):
        return {"text": [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
                         for m in batch["messages"]]}

    ds = ds.map(render, batched=True, remove_columns=[c for c in ds["train"].column_names if c != "messages"])
    sample = ds["train"][0]["text"]
    assert INSTRUCTION_PART in sample and RESPONSE_PART in sample, (
        "chat-template markers not found; update INSTRUCTION_PART/RESPONSE_PART for this tokenizer:\n" + sample
    )
    print("rendered example:\n" + sample)

    out = Path(args.out)
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
    trainer = train_on_responses_only(trainer, instruction_part=INSTRUCTION_PART, response_part=RESPONSE_PART)
    stats = trainer.train()
    (out / "train_stats.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "train_stats.json").write_text(json.dumps(stats.metrics, indent=2))
    print(trainer.evaluate())

    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    if not args.no_gguf:
        # Merges LoRA into the base and writes one GGUF per quant into out/gguf.
        model.save_pretrained_gguf(str(out / "gguf"), tokenizer, quantization_method=args.quants)
        print("GGUFs written under", out / "gguf")


if __name__ == "__main__":
    main()
