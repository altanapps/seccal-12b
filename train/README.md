# Training seccal

The Mac cannot train (no CUDA). Training runs on a free Colab T4 or an HF Job;
everything else (splits, rendering, eval, serving, the hook) runs locally.

## Presets

`train/sft_unsloth.py --model <preset>` fixes the base model, the LoRA target
modules for that architecture, and the chat-template markers for
completion-only loss. The script asserts the markers appear in a rendered
example before training, so a wrong preset fails fast.

| preset | base model | license | notes |
|---|---|---|---|
| `lfm2.5-1.2b` (default) | `LiquidAI/LFM2.5-1.2B-Instruct` | LFM Open | iteration 1; hybrid conv + GQA, LFM-specific module list |
| `qwen3-4b` | `unsloth/Qwen3-4B-Instruct-2507` | Apache-2.0 | iteration 2 candidate; same ChatML markers, standard module list, no thinking tokens, ~2.5 GB at Q4_K_M |
| `lfm2-2.6b` | `LiquidAI/LFM2-2.6B` | LFM Open | larger sibling of iteration 1, drop-in |

Why `qwen3-4b` next: a 1.2B model under-predicts ASK and leans on the command's
surface; the 4B class reads the goal materially better (IFEval ~83 vs ~75) at a
latency that is still sub-second per hook call on Apple Silicon. Pin a revision
with `--revision <sha>` for reproducible retrains.

## Inputs

Produced locally and committed/derivable:

```bash
python3 data/synth/split.py        # assigns train/val/test into the canonical files (frozen test set)
python3 data/synth/render_sft.py   # writes data/sft/{train,val,test}.jsonl
```

## Colab (free T4): the one-file path

Each preset has a self-contained notebook with the training script and the
rendered train/val data embedded as a reproducible base64 zip, plus a SHA-256
manifest the notebook checks before extracting anything. Nothing to upload
beyond the notebook.

| preset | notebook |
|---|---|
| `lfm2.5-1.2b` | `train/seccal_colab.ipynb` |
| `qwen3-4b` | `train/seccal_colab_qwen3-4b.ipynb` |

1. Open https://colab.research.google.com → `File → Upload notebook` → pick the notebook.
2. `Runtime → Change runtime type → T4 GPU`.
3. `Runtime → Run all`. Approve the Google Drive prompt near the end. If a 4B
   preset runs out of memory in 16-bit LoRA, add `--load-in-4bit` to the
   training cell.
4. The GGUFs land in `MyDrive/seccal-12b/`. Copy them into this repo's
   `models/` folder as `models/seccal_<preset>_Q4_K_M.gguf` and `..._Q8_0.gguf`.

~400 rows x 3 epochs at effective batch 8 is a few minutes of training; with
installs, 10–25 minutes end to end. The first cell asserts a GPU is present,
and the script picks fp16 on T4 (no bf16 there) automatically.

### Rebuilding and verifying the notebooks

Rebuild after any change to the script or dataset, and verify in review for
any change that touches a notebook (the embedded blob is not readable in a diff;
the check is):

```bash
python3 data/synth/render_sft.py
python3 train/make_colab_notebook.py                     # lfm2.5-1.2b -> train/seccal_colab.ipynb
python3 train/make_colab_notebook.py --model qwen3-4b    # -> train/seccal_colab_qwen3-4b.ipynb
python3 train/make_colab_notebook.py --check
python3 train/make_colab_notebook.py --check --model qwen3-4b
```

The zip uses fixed timestamps, so a rebuild from the same sources is
byte-identical to the committed notebook.

## HF Jobs

```bash
hf jobs uv run --flavor t4-small \
  --with unsloth --with "trl>=0.15" --with datasets \
  train/sft_unsloth.py --model qwen3-4b --train data/sft/train.jsonl --val data/sft/val.jsonl
```

(`hf jobs uv run` honours the inline `# /// script` dependency block.)

## After training

1. Copy the GGUFs into `models/` (gitignored), named by preset.
2. Serve and evaluate each against the frozen test split, and compare with the
   baselines already in `reports/` (base model, and iteration 1 at
   `reports/eval_ft-q4.md`):
   ```bash
   serve/run_server.sh models/seccal_qwen3-4b_Q4_K_M.gguf &
   python3 eval/run_eval.py --name ft-qwen3-4b-q4
   python3 eval/run_eval.py --name ft-qwen3-4b-q4-val --split val
   ```
3. Gate on BLOCK recall and attack-miss rate first, then ALLOW precision and
   pair consistency. Pick the quant from the numbers; also compare the hook's
   p50/p95 latency in the eval report, since a 4B model is slower per call.
4. Point the hook at the chosen model (`hook/README.md`).

## Knobs

`--r/--alpha` (LoRA rank, default 16/16), `--lr` (2e-4), `--epochs` (3),
`--bs --grad-accum` (2 x 4 = 8 effective), `--max-seq` (1024), `--quants`
(q4_k_m q8_0), `--load-in-4bit` (QLoRA), `--revision`, `--no-gguf`.
