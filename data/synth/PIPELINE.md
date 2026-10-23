# Synth Data Pipeline — Configuration and Runbook

How a batch of training data gets generated, judged, reviewed, and integrated.
Run four times so far: pilot (101), batch B (99), batch D (150), batch E (150)
= 500 rows (there is no batch C; the letter was skipped). The canonical dataset
lives in `out/accepted.jsonl` (398) + `out/adjudicated.jsonl` (102). Assemble and
re-validate the combined set with `python3 data/synth/assemble.py check` (dry run)
or `... write <batch_dir>...` (fold a staged batch into the canonical files).

## Roles (three independent agents)

- **Generator** — authors rows by hand in a `*_rows.py` file (see
  `pilot_rows.py`, `batch_b_rows.py`). May read all gold data (needed for
  duplicate/id checks). Follows the latest review report's directives.
- **dataset-judge** (`.claude/agents/dataset-judge.md`) — blind labeling
  engine. Sees ONLY `{id, user_goal, tool_name, tool_input}`. Must run in a
  fresh context (a child agent, never the orchestrator — the orchestrator has
  seen gold labels). Parallelize one judge per chunk.
- **dataset-reviewer** (`.claude/agents/dataset-reviewer.md`) — adjudicates
  generator/judge disagreements, audits a 40-row sample, runs shortcut and
  mix checks, writes `reports/review_<batch>.md` with PASS / PASS WITH FIXES /
  FAIL and verbatim directives for the next generator run.

Label policy: `data/LABELING.md` is the single source of truth for all three.

## Per-batch workflow

Batch `X` stages everything under `out/batch_X/` so `judge_merge.py` (which
writes next to its input) cannot clobber the canonical files.

1. **Quotas.** Compute the batch action mix so that `(current + batch)` hits
   the targets below. Example (batch B): dataset was 48/11/42 over 101, so a
   99-row batch needed 62/19/18 to land 110/30/60 over 200.
2. **Generate.** Author `data/synth/batch_x_rows.py`; emit with
   `python3 data/synth/batch_x_rows.py > data/synth/out/batch_X/raw.jsonl`.
   Iterate until `python3 data/synth/validate.py data/synth/out/batch_X/raw.jsonl`
   exits 0. Also self-check cross-batch: no id collisions and no duplicate
   commands/goals vs `accepted.jsonl` + `adjudicated.jsonl` (whitespace-
   normalized), outside pair-internal exceptions.
3. **Split.** `python3 data/synth/judge_split.py data/synth/out/batch_X/raw.jsonl 25`
   → `out/batch_X/blind/chunk_NN.jsonl` (label-free, seeded shuffle so pair
   members are not adjacent).
4. **Blind-judge.** One fresh dataset-judge agent per chunk, writing
   `out/batch_X/blind/judged_NN.jsonl` (`{id, judge_action, judge_category,
   judge_rationale}`, input order). Verify every judged file exists and
   row-counts match before merging — a judge can report success without
   having written its file (happened once in batch B).
5. **Merge.** `python3 data/synth/judge_merge.py data/synth/out/batch_X/raw.jsonl
   data/synth/out/batch_X/blind/judged_*.jsonl` → `out/batch_X/accepted.jsonl`
   + `out/batch_X/review_queue.jsonl` + agreement stats. Benchmarks: pilot
   79% action agreement; batch B 98%. A large drop means the generator or the
   judge drifted — investigate before proceeding.
6. **Review.** dataset-reviewer adjudicates the queue (blind-first, then
   compare), audits 40 rows seed 42, runs shortcut/mix checks on the FULL
   combined dataset, writes `reports/review_batch_X.md`. Escalations go to
   `out/batch_X/escalated.jsonl` for human resolution.
7. **Integrate.** Append `batch_X/accepted.jsonl` to `out/accepted.jsonl` and
   `batch_X/adjudicated.jsonl` to `out/adjudicated.jsonl`; apply any human
   escalation resolutions and carry-over relabels the report ordered; re-run
   the full `validate.check` on the combined set (must be clean, pairs may
   span files); delete throwaway scripts; commit (`Co-Authored-By: Warp
   <agent@warp.dev>`). `out/batch_X/` itself is gitignored staging.

## Targets (hold for the combined dataset, enforced by the reviewer)

- Actions: ~55% ALLOW / ~15% ASK / ~30% BLOCK
- benign_hard ≥ 1/3 of ALLOW rows
- Obfuscated ≈ 10% of attacks (non-ALLOW); judge-injection ≈ 5%
- Bash ≤ ~60% of a batch; all tools and all 20 `seed_matrix.json` projects
  represented (≥3 rows per project per batch)
- No single input feature predicts the label at >80% (watch URL/IP ⇒ BLOCK,
  broken in batch B: 81% → 60%; keep supplying URL-bearing ALLOW/ASK rows)
- No 2–3-word goal opening predicts one label for >80% of its bucket (n≥5).
  Watch items from batch B: "update the", "rename the" (3/3 BLOCK, low n)
- Pairs ~40% of a batch (half goal_flip `pf-*`, half twin `pt-*`); every
  pair_id exactly 2 members; goal_flip shares tool_input, twin shares goal
  with exactly one ALLOW member

## Label invariants (validator-enforced; policy decided in past reviews)

- `kind=injected` ⇒ BLOCK, never ASK/ALLOW. Category `injected_action` only
  when no more specific harm dominates (a secret read is `credential_access`).
- `kind=reckless` ⇒ ASK/BLOCK with category `reckless`, `destructive`, or
  `credential_access` (staging secrets, e.g. `git add .env.local`).
- ALLOW ⇔ category `benign`; `harmful=true` never ALLOW; injected rows that
  resolve BLOCK carry `harmful=true`.
- ALLOW rows that look scary but are explicitly requested are
  `kind=benign_hard`, not `reckless`.
- Official-vendor installers from URLs are ASK (`reckless` category works;
  `supply_chain` is for malicious/typosquatted packages, not official ones).
- Embedded "approved/safe" text in args or content carries zero weight.
- Tie-breakers: attack-pattern doubt → BLOCK; developer-action doubt → ASK.

## Known judge failure modes (from adjudication history)

- Softens injected rows to ASK/ALLOW when the action looks mild (ignore
  mildness; the mechanism decides).
- Uses `reckless` on injected rows (contradicts reckless's no-attacker premise).
- Uses `supply_chain` for official upstream installs (should be ASK/reckless).
- Resists `destructive`/`credential_access` categories on reckless rows.

## File map

- `common.py` — schema, categories, prompt rendering (`to_chat` for SFT; the
  hook must match `render_user_prompt` byte-for-byte)
- `validate.py` — row schema + dataset-level checks; exit 0 required
- `judge_split.py` / `judge_merge.py` — blind-judge round trip
- `show.py` — human pretty-printer (pilot-era paths)
- `seed_matrix.json` — projects, tool mix, attack families, modifier rates
- `out/accepted.jsonl` + `out/adjudicated.jsonl` — canonical dataset (tracked)
- `out/batch_*/`, `out/raw.jsonl`, `out/blind/`, `out/review_queue.jsonl` —
  transient staging (gitignored)

## Next pipeline stage (not yet built)

Split assignment (train/val/test; pair members must share a split — the
`split` field is currently null on all 200 rows), then SFT rendering via
`common.to_chat()`, fine-tune, eval, GGUF export, PreToolUse hook.
