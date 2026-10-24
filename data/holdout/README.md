# Separate holdout candidates

The reviewed benchmark is now **314 calls in 114 scenario groups** in
`accepted.jsonl`, with 104 ALLOW, 80 ASK and 130 BLOCK labels. `frozen.json`
records its immutable hash, input/review hashes, policy version and labeling
method. The original 300 hypotheses below remain unchanged, and a separate
14-call policy-anchored ASK supplement is preserved under `supplement/`.

Both local judges reviewed every call blindly; final disagreements were
adjudicated by the author against the policy, with per-row decisions in
`adjudications.jsonl`. This is **model-reviewed, author-adjudicated synthetic
data, not human-verified ground truth**. No small-model scores on this new set
have been used for model selection or training.

`candidates.jsonl` contains **300 candidate calls in 100 scenario groups**:
100 proposed ALLOW, 100 ASK and 100 BLOCK. It is newly authored synthetic data,
not a copy of the original training/validation/test splits. There are 120 MCP
calls, 20 goal-flip pairs, 80 twin pairs, ten obfuscated BLOCK hypotheses and
15 forged-approval/judge-injection examples. The pair and scenario groups are
the units of separation; individual variants must never be split across sets.

The source is `build_candidates.py`. It represents shell commands as data and
never executes them. The validator checks Bash syntax with `bash -n`, schema,
scenario and pair invariants, and exact input/id overlap with the canonical set.
Simulated MCP operations use explicit targets and environments; they are not
claims about any installed provider's exact API schema.

```bash
python3 data/holdout/build_candidates.py
python3 data/holdout/validate_candidates.py
```

All generated rows are marked **candidate**. Proposed labels are hypotheses;
passing schema validation does not accept them. The manifest hashes the complete
candidate file. Once blind review begins, preserve that file and resolve labels
in a separate artifact rather than editing it underneath a partial review.

## Blind review

Two locally served models review each call independently: Qwen3.8-27B and
gpt-oss-safeguard-20B. Only the goal, tool name and tool input enter each request;
the proposed action/category, rationale, scenario id, pair id, kind and modifier
flags do not. Each request has a fresh chat history. The goal is independent
model review, not human review or proof that the consensus is correct.

```bash
python3 eval/run_matrix.py --models qwen3.8-27b --prompt-mode policy \
  --review-input data/holdout/candidates.jsonl --max-runtime-gb 24
python3 eval/run_matrix.py --models gpt-oss-safeguard-20b --track reasoning \
  --prompt-mode policy --review-input data/holdout/candidates.jsonl --max-runtime-gb 24
python3 data/holdout/reconcile_reviews.py
```

The same model lock, one-server lifecycle and memory watchdog cover review.
Outputs are resumable per-row judgments under `reviews/` (gitignored). A changed
candidate hash invalidates a partial review. Transport/format errors stop the
job; retries revisit failed rows, rather than accepting errors as decisions.

The reconciliation report is `reports/holdout_review.md`. Both judges agreeing
with the proposal is an audit signal. Disagreement, missing judgments and format
errors require explicit adjudication. They are not silently relabeled or removed
to improve accuracy. The accepted set must record reviewed labels, provenance,
adjudication rationale and a frozen hash before it becomes a scored benchmark.

Do not train on these calls. Do not tune prompts, models or thresholds against
their results. The two judge models must not be presented as independent test
subjects on a benchmark they helped label. Evaluate the selected small models
after choices are fixed, and keep the historical 49-row test split untouched
during selection.
