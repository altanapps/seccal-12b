# Local MLX QLoRA preparation

The local path uses Python 3.12 and `mlx-lm[train]`, with package versions captured
in `requirements-mlx.lock`. The original CUDA/Unsloth script and its embedded
Colab notebooks are unchanged.

## Current Ministral experiment

The initial full all-linear rank-16 recipe regressed on validation. Its three
checkpoints scored 15/52, 29/52 and 27/52 versus the matching MLX base's 38/52.
No holdout scores were released for that trial, and its artifacts are preserved.
The conservative follow-up reduces adapter capacity to q/v rank 8 and uses
400 microbatches / 50 updates, a peak learning rate of 2e-5, five optimizer
updates of warmup and 45 of cosine decay to 2e-6:

```bash
.venv-mlx/bin/python train/run_local.py --model ministral3-3b \
  --recipe train/recipes/ministral3-3b-policy-conservative.json
.venv-mlx/bin/python eval/evaluate_ministral_training.py \
  --run-dir out/mlx-ministral3-3b-policy-conservative \
  --tag policy-conservative --validation-only
```

Inspect validation before running the same evaluation command without
`--validation-only` to release the frozen holdout scores. Do not modify the
recipe, prompt or checkpoint choice in response to holdout outcomes. Reporting
preserves both the original failed trial and the conservative follow-up.

## Environment and initial recipe reproduction

```bash
uv venv --python 3.12 .venv-mlx
uv pip install --python .venv-mlx/bin/python -r train/requirements-mlx.lock
.venv-mlx/bin/python train/prepare_local.py --download
.venv-mlx/bin/python train/run_local.py --model qwen3-4b --check-only
.venv-mlx/bin/python train/run_local.py --model ministral3-3b --check-only
```

The two MLX 4-bit snapshots are pinned in `prepare_local.py`; downloads include
weights, configs and tokenizer files, without running repository Python code.
Model snapshots and adapters remain gitignored. Recipes use portable paths
relative to the repository, and the launcher sets that working directory.

## Prompt and loss verification

Both recipes use the full-policy system message, 399 training rows and 52
validation rows. No historical test or new holdout rows are copied into the
training directory. `valid.jsonl` is the MLX spelling of the validation split.
Training uses prompt masking: only the assistant's JSON verdict and native
end-of-turn tokens contribute to loss.

The preflight checks **every train and validation row** for native-template prefix
alignment, a nonempty assistant target and no truncation. Maximum lengths are
about 1,100–1,200 tokens, below the configured 2,048. It also checks that empty
thinking spans have not been inserted into the supervised completion.

Two tokenizer issues were found and addressed:

- The MLX Qwen conversion's chat template inserts `<think>` tags despite the
  non-thinking checkpoint. The launcher supplies the original publisher's
  pinned Instruct-2507 template from `tokenizer_templates/`. Its SHA-256 is
  checked and recorded. The MLX tokenizer vocabulary file was verified to have
  the identical SHA-256 as the original publisher's tokenizer.
- Ministral uses Transformers' `fix_mistral_regex=True` correction in both
  preflight and training. The launcher passes it through the MLX tokenizer loader.

No installed package or model weight is patched. Tokenizer options are scoped
to the worker process and recorded in each run's evidence.

## Bounded pilot and full recipe

```bash
.venv-mlx/bin/python train/run_local.py --model qwen3-4b --pilot
.venv-mlx/bin/python train/run_local.py --model ministral3-3b --pilot
```

Each pilot uses eight microbatches, batch size 1 and gradient accumulation 8:
**one optimizer update**, not a trained candidate for deployment. Both corrected
pilots completed at roughly 5 GB maximum sampled physical footprint. Pilot
adapters and evidence live under `out/mlx-<model>-policy-pilot/`. Superseded pilot
artifacts from before the tokenizer fixes are retained with explanatory suffixes.

The full prepared recipes use rank 16, zero dropout, all decoder layers, gradient
checkpointing, learning rate 2e-4, and 1,200 microbatches: approximately three
passes over the current training set and 150 optimizer updates. MLX's LoRA
`scale` directly multiplies the adapter delta, so it is **1.0** to match PEFT
alpha/r = 16/16. It must not be copied as scale 16. These local recipes currently
use a constant learning rate, rather than silently claiming the CUDA cosine
schedule. Full training is not inferred from a successful pilot.

The 24 October recipe audit found that the committed Ministral recipe still had
150 microbatches and scale 16, despite the generator and documentation specifying
1,200 and scale 1. The recipe was regenerated before full training. The earlier
scale-16 pilot is preserved at its original path; the new scale-1 check is in
`out/mlx-ministral3-3b-policy-scale1-pilot/`. The launcher refuses to overwrite
existing run artifacts; use `--output-dir` with a new directory for another run.

Start the full run after validating the pilot:

```bash
.venv-mlx/bin/python train/run_local.py --model ministral3-3b
```

After training exits, evaluate the original MLX checkpoint and the three saved
adapters **sequentially** with the same full-policy prompt, greedy decoding
constrained to the 19 canonical schema-valid JSON verdicts and strict parsing.
The token constraints contain no gold labels. Select a checkpoint on validation, freeze that choice,
then score the original checkpoint and selected adapter on the holdout:

```bash
.venv-mlx/bin/python eval/evaluate_ministral_training.py
```

The command scores validation and the frozen synthetic holdout; the historical
49-row test remains untouched. MLX canonical-verdict decoding is a separate serving track
from grammar-constrained GGUF inference. Compare the two matching MLX runs to
measure the training effect. Existing evaluation names cannot be overwritten.
Checkpoint selection uses accuracy, fewer BLOCK→ALLOW misses, BLOCK recall,
ASK recall, pair consistency and the earlier checkpoint. Holdout scores cannot
be passed to the selector. `python3 eval/report_mlx_training.py` regenerates the
result report from local evidence or its committed snapshot.

The launcher shares the evaluation process lock and waits for its worker to
exit. The memory watchdog samples RSS and macOS physical footprint every 0.1 s
and stops near 22 GB, reserving 2 GB below the 24 GB cap. MLX also receives a
20 GB allocator guideline and 0.5 GB cache limit. These sampled/allocator limits
are not a kernel physical-memory quota. Do not run inference and training
concurrently through separate uncoordinated applications.

Each run saves an effective config hash, data hashes, tokenizer options, pinned
model source, memory readings, exit status, adapter and training log. No model is
uploaded or deployed. GGUF fusion/export and final quality evaluation are
separate verification steps before using a trained adapter in the hook.
