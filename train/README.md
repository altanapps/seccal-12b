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

## Colab (free T4): the one-file path

The repo is private, so Colab cannot clone it. `train/seccal_colab.ipynb` is a
single self-contained notebook with the training script and the rendered
train/val data embedded (as a small base64 zip). Nothing else to upload.

1. Open https://colab.research.google.com → `File → Upload notebook` →
   pick `train/seccal_colab.ipynb`.
2. `Runtime → Change runtime type → T4 GPU`.
3. `Runtime → Run all`. Approve the Google Drive prompt near the end.
4. The GGUFs land in `MyDrive/seccal-12b/`. Copy them into this repo's
   `models/` folder on the Mac.

~400 rows x 3 epochs at effective batch 8 is a few minutes of training; with
installs, 10–20 minutes end to end. The first cell asserts a GPU is present,
and the script picks fp16 on T4 (no bf16 there) automatically.

Rebuild the notebook after any change to the script or dataset:

```bash
python3 data/synth/render_sft.py && python3 train/make_colab_notebook.py
```

## HF Jobs

```bash
hf jobs uv run --flavor t4-small \
  --with unsloth --with "trl>=0.15" --with datasets \
  train/sft_unsloth.py --train data/sft/train.jsonl --val data/sft/val.jsonl --out out/seccal-12b
```

(`hf jobs uv run` honours the inline `# /// script` dependency block.)

## After training

1. Copy the GGUFs into `models/` (gitignored):
   `models/seccal_1.2b_Q4_K_M.gguf`, `models/seccal_1.2b_Q8_0.gguf`.
2. Serve and evaluate each against the frozen test split, and compare with the
   base-model baseline you already have:
   ```bash
   serve/run_server.sh models/seccal_1.2b_Q8_0.gguf &
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
