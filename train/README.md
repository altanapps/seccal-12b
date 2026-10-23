# Training seccal-12b

The Mac cannot train (no CUDA). Training runs on a free Colab T4 or an HF Job;
everything else (splits, rendering, eval, serving, the hook) runs locally.

## Inputs

Produced locally and committed/derivable:

```bash
python3 data/synth/split.py        # assigns train/val/test into the canonical files (frozen test set)
python3 data/synth/render_sft.py   # writes data/sft/{train,val,test}.jsonl
```

Upload `data/sft/train.jsonl` and `data/sft/val.jsonl` with the script.

## Colab (free T4)

```python
!pip install -q unsloth "trl>=0.15" datasets
!python train/sft_unsloth.py --train data/sft/train.jsonl --val data/sft/val.jsonl --out out/seccal-12b
```

~500 rows x 3 epochs at effective batch 8 is a few minutes on a T4. Download
`out/seccal-12b/gguf/*.gguf` when it finishes.

## HF Jobs

```bash
hf jobs uv run --flavor t4-small \
  --with unsloth --with "trl>=0.15" --with datasets \
  train/sft_unsloth.py --train data/sft/train.jsonl --val data/sft/val.jsonl --out out/seccal-12b
```

(`hf jobs uv run` honours the inline `# /// script` dependency block.)

## After training

1. Copy the GGUFs into `models/` (gitignored):
   `models/seccal-12b-Q4_K_M.gguf`, `models/seccal-12b-Q8_0.gguf`.
2. Serve and evaluate each against the frozen test split, and compare with the
   base-model baseline you already have:
   ```bash
   serve/run_server.sh models/seccal-12b-Q8_0.gguf &
   python3 eval/run_eval.py --name ft-q8
   ```
3. Gate on BLOCK recall and attack-miss rate first, then ALLOW precision and
   pair consistency (`reports/eval_*.md`). Pick the quant from the numbers; for
   a security gate Q8_0's extra ~500 MB is usually worth it.
4. Point the hook at the chosen model (`hook/README.md`).

## Knobs

`--r/--alpha` (LoRA rank, default 16/16), `--lr` (2e-4), `--epochs` (3),
`--bs --grad-accum` (2 x 4 = 8 effective), `--quants` (q4_k_m q8_0),
`--no-gguf` to skip export. The LoRA target list is LFM2.5-specific; see the
docstring in `sft_unsloth.py` before changing it.
