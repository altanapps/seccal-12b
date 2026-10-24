# Local model comparison

The catalog in `model_catalog.json` records per-checkpoint inference fit on the
48 GB M5 Pro, rough local-training feasibility, publisher links, exact GGUF
revisions, artifact sizes and SHA-256 hashes. Memory estimates assume one loaded
model, one slot, short context and quantized text-only inference. A memory fit
is not a measured backend compatibility or latency result.

“Base” in these commands means the original publisher's checkpoint before
**seccal** fine-tuning. Most are instruction-tuned already. Raw `-Base` checkpoints
are different experiments and are not silently substituted for instruct models.

## Download and evaluate

All scripts use the Python standard library. `llama-server` must be on PATH.

```bash
python3 eval/download_models.py --wave initial --dry-run
python3 eval/download_models.py --wave initial
python3 eval/run_matrix.py --wave initial
python3 eval/run_matrix.py --wave initial --prompt-mode policy
python3 eval/rank_models.py
python3 eval/compare_models.py
python3 eval/report_phase2.py
```

The Markdown reports rank each model's best error-free validation run by action
accuracy. Ties use fewer BLOCK→ALLOW misses, higher BLOCK recall, ASK recall,
pair consistency and lower p95 latency. The recorded JSON snapshot includes all
26 runs (25 successful and one protocol failure), metrics, hashes and portable
server commands. Report generation can use this snapshot on a fresh checkout
without downloading or loading any model. `rank_models.py` updates the snapshot
from local results; the other two commands regenerate the Markdown reports.

Weights live in `models/base/<id>/` with integrity receipts. Downloads resume via
`.part` files and are renamed only after size and SHA-256 verification. The
default download selection cap is 25 decimal GB; larger explicit selections need
`--max-gb`. For another candidate:

```bash
python3 eval/download_models.py --models lfm2.5-8b-a1b
python3 eval/run_matrix.py --models lfm2.5-8b-a1b
```

The matrix starts and stops its own loopback server on port 8091. It evaluates
models **sequentially**, with one slot, concurrency 1, 4096-token context, two
unscored warmups, temperature 0 and the existing verdict grammar. Thinking is
disabled for the initial shortlist. Do not run other inference workloads when
comparing latency. `--wait-downloads 1800` waits for the downloader's verified
artifacts rather than treating a partial download as a valid model.

A process lock prevents overlapping matrix invocations even on different ports.
Each server is terminated and `wait()` confirms it has exited before the next
model can start. The default estimated model/runtime ceiling is **24 GB**, leaving
roughly half the device memory for other work; larger reference models need an
explicit higher `--max-runtime-gb` after considering the user's running apps.
This lock coordinates these scripts, not independently started Ollama/LM Studio
instances. Download workers stream to disk and do not load model weights.

The 24 GB budget also has a live watchdog: RSS and macOS physical footprint are
sampled every 0.1 seconds, with an early stop near 22 GB to leave a 2 GB margin.
This is not a kernel-enforced physical-memory quota. Phase 2 stayed below
20.73 GB in all sampled inference/review runs; local training pilots used about
5 GB. The same lock and watchdog protect blind holdout review and MLX training.

LFM2.5-2.6B fits memory and loads, but its native template unconditionally opens
a thinking span. This installed llama.cpp puts the constrained verdict in
`reasoning_content` with empty `content` even with thinking disabled; forcing
zero thinking tokens also conflicts with the grammar. Its 52 failed direct
requests are preserved for diagnosis and excluded from quality ranking. The
matrix explicitly skips it until a separate protocol adapter is validated.

Default split is **val**, the selection set. The frozen test split is reserved
for a final comparison after selection. `run_eval.py` retains its original test
default for historical CLI compatibility; use the matrix defaults for sweeps.
Never select prompts or training hyperparameters using the test results.

## Two distinct prompt tracks

- `original`: the exact system/user rendering used by the existing SFT data and
  hook. It defines the verdict shape and lists categories, without the full label
  policy. It preserves the historical comparison.
- `policy`: appends the existing `data/LABELING.md` to the system message. This
  tests a stronger zero-shot baseline. It does not alter canonical examples,
  labels, existing training prompts or the deployed hook. If chosen for training,
  the SFT renderer and runtime must deliberately adopt the same version later.

Use each GGUF's native chat template. This preserves message text across models
while letting their required special tokens differ.

Reasoning-first and guard models require separate protocol/prompt adapters and
token budgets; catalog fit does not make them eligible for a direct matrix run.
Prompt Guard and ModernBERT are encoders and need a separate classification
pipeline. Content-safety labels must not be relabeled mechanically as tool-call
authorization decisions.

The implemented Safeguard track is explicit:

```bash
python3 eval/run_matrix.py --models gpt-oss-safeguard-20b \
  --track reasoning --prompt-mode policy --max-runtime-gb 24
```

It uses low reasoning effort, 256 thinking tokens, a 1024-token total output
budget and JSON schema for the final answer. Only final content is parsed as a
verdict. Thinking text is not silently accepted as the final decision.

The separate reviewed holdout now contains 314 calls. Scoring requires its
frozen hash, accepted-label status and model provenance. Either local model that
helped label it is excluded from independent test scoring. See
`data/holdout/README.md` and `reports/holdout_review.md`; these are model-reviewed,
author-adjudicated synthetic labels rather than human-verified truth.

## Outputs and interpretation

Each run writes:

- `eval/out/<name>.jsonl`: every gold row and its prediction, errors, usage,
  completion reason and wall-clock latency.
- `eval/out/<name>.summary.json`: metrics, 95% Wilson intervals, per-tool/kind/
  category/modifier slices, prompt/dataset hashes and model provenance.
- `eval/out/<name>.runtime.json` and `.server.log`: server command, model hashes,
  llama.cpp version, context settings and sampled process RSS.
- `reports/eval_<name>.md`: reviewable results and individual misjudgments.
- `reports/base_model_comparison.md`: combined validation comparison.

`eval/out/` and model weights are gitignored. Markdown reports and the catalog are
reviewable repository files. Completed clean runs are skipped unless `--rerun`
is supplied; use a fresh run or `--rerun` after changing inputs or settings.

Prioritize BLOCK→ALLOW mistakes, BLOCK recall, ASK recall, ALLOW precision,
false blocks, goal-flip consistency, errors and p95 latency. Accuracy alone can
hide a model that never predicts ASK. Invalid verdicts and transport failures
remain errors, count as incorrect, and cause a nonzero exit; they are never
silently treated as safe. All-failed runs still preserve their diagnostic files.

The current validation split has only 15 BLOCK and nine ASK rows. Zero misses
would still have a roughly 20% upper Wilson bound on the miss rate; paired rows
also violate a strict independence assumption. These are selection experiments,
not production safety certification. Process RSS does not measure total Metal
or system unified-memory use.

```bash
python3 -m unittest discover -s eval -p 'test_*.py'
```
