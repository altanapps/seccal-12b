# Holdout candidate review

Candidate SHA-256: `1bd42f94efbc9e9daebaf68d2202641e576763496a74903d563ede7be10522cd`. 300 rows in 100 scenarios.

These are newly authored synthetic candidates. They have not been used for model selection, training, or a reported safety score.

Blind judges: qwen3.8-27b, gpt-oss-safeguard-20b. Only user goal, tool name and tool input were sent; generator labels, rationale, kind and pair identifiers were withheld.

- Both blind judges match the proposed action and category: **152**.
- Original missing judgments or disagreements requiring adjudication: **148**.
- Still unresolved: **0**.

Agreement does not prove correctness. Disagreements are never silently relabeled or dropped to improve a model's score. Frozen status and final labels, when present, are recorded separately from the original hypotheses. The large judge models must not be scored on this set as independent test subjects because their judgments help construct its labels.

| judge | completed valid judgments |
|---|---|
| qwen3.8-27b | 300 |
| gpt-oss-safeguard-20b | 300 |

Candidate action distribution: {'ALLOW': 100, 'ASK': 100, 'BLOCK': 100}.

Raw local review files and the adjudication queue are under `data/holdout/reviews/` (gitignored). The original frozen test split and canonical training/validation files remain separate.

## Frozen reviewed set

**314 calls in 114 scenarios**, including 14 additional policy-anchored ASK cases reviewed separately by both models. Final actions: {'ALLOW': 104, 'BLOCK': 130, 'ASK': 80}. Frozen SHA-256: `c78861c6f7f967c17a35dd9f92f406b7d1370d61be9284d6a244ad9b11ccf675`.

Both blind-model judgments were collected for every original and supplemental call. The author then adjudicated disagreements against the written policy. This is **model-reviewed, author-adjudicated synthetic data, not human-verified ground truth**. The author retained all original cases, corrected 49 proposed action/category labels, and added new ASK cases instead of forcing incorrect labels to meet a quota. 152 calls retained full blind-model agreement; 162 have explicit author policy adjudications.

Final decisions and rationales are in `data/holdout/adjudications.jsonl`; `accepted.jsonl` and `frozen.json` define the immutable benchmark. Original hypotheses and review hashes are retained. The scorer verifies the frozen hash and accepted status and excludes either labeling judge from independent scoring. The new set has not been used to train models or report candidate performance.
