# R1c follow-up — prompt iterations + transformers-direct ceiling test

**Date:** 2026-05-21 (manual scoring 2026-05-20)
**Builds on:** `discovery/R1-comparison.md`
**Trigger:** Manual scoring (on G's laptop) ranked gemma4 highest (4.7/5 avg,
5.0 markdown_quality) despite the Raft-fabrication flag, qwen3-vl second (4.0).
This follow-up asks: can prompt engineering kill gemma4's fabrication without
losing its quality, and does breaking Ollama's 280-token visual budget help?

## Scoring result that started this (from score_ocr.py on the laptop)

| Engine | accuracy | structure | hw_tol | md_quality | edge_cases | AVG | s/page |
|---|---|---|---|---|---|---|---|
| gemma4 | 4.5 | 4.7 | 4.8 | 5.0 | 4.3 | **4.7** | 19.0 |
| qwen3-vl | 4.2 | 4.3 | 3.7 | 4.3 | 3.7 | **4.0** | 9.5 |
| deepseek-ocr | 3.3 | 3.3 | 3.2 | 3.3 | 3.0 | 3.2 | 2.0 |
| minicpm-v | 2.7 | 3.2 | 2.2 | 3.5 | 3.2 | 2.9 | 4.0 |
| granite-vision | 1.3 | 1.3 | 1.3 | 1.3 | 1.3 | 1.3 | 6.7 |

minicpm-v (current production) scored **2.9** — below its R0 reputation of 3.4.
gemma4 is the clear quality leader; the open question was its Raft fabrication.

## Prompt iterations (all Ollama, gemma4 + qwen3-vl)

The R0 `VISION_PROMPT` ends with negative instructions ("Output only … Do not add
commentary") that (a) mode-collapse deepseek-ocr and (b) coexist with gemma4's
worst failure: substituting canonical-textbook content for what's on the page
(wrote `$S$ nodes / $F$ failures` for a page that shows `5 nodes / 2 failures`).

| Prompt | gemma4 Raft fab | gemma4 diagrams | gemma4 math | qwen3-vl |
|---|---|---|---|---|
| R0 VISION_PROMPT | ✗ fabricates ($S/$F) | structured (heavy md) | truncated | Basel→∞, /2 |
| **anti-fab v1** (verbatim, no diagram clause) | ✓ fixed (5/2) | ✗ **broke** — flat run-on string | ok | no change |
| **anti-fab v2** (verbatim + diagram clause) ← **adopted** | ✓ fixed | ✓ recovered (1 mis-traced arrow) | ok | no change |
| anti-fab v3 (persona + anti-prior clause + Gemma official sampling 1.0/0.95/64) | ✓ fixed | ✗ vertical-split formatting | ✗ **truncated** (temp=1.0 too verbose) | no change |

**v2 is the production prompt** (committed to `PROMPT_OVERRIDES` in
`discovery/run_ocr.py`). v3's literature-recommended additions (persona priming
from Ivan's HTR study; Gemma's official temp=1.0/top_p=0.95/top_k=64) *regressed*
output — the higher temperature made gemma4 verbose enough to truncate math, and
broke diagram formatting. Ollama's lower-temperature defaults (0.8/0.9/40) keep
gemma4 more consistent, even though they're "officially wrong."

v2 prompt verbatim:
```
Transcribe the handwritten text on this page verbatim. Preserve the exact
numbers, variables, and symbols that appear in the handwriting. For diagrams
with arrows, list each labeled connection on its own line, in the order they
appear. Output only the transcription.
```

**qwen3-vl is prompt-resistant**: none of v1/v2/v3 changed its outputs. Its
substitutions (Basel sum `N → ∞`, quadratic `/2a → /2`) and flat-diagram
behaviour are stable across every prompt.

## Path D — transformers-direct, breaking the 280-token ceiling

Ollama hardcodes Gemma 4's visual token budget (`max_soft_tokens`) to 280
(ollama/ollama#15626, **still open** as of 2026-05-15). Google recommends
560-1120 for OCR. To reach 1120 we bypassed Ollama with transformers 5.9.0 +
torch 2.12/CUDA 13.0 in a throwaway venv (`/tmp/r1c-venv`), pulling the original
safetensors (`google/gemma-4-E4B-it` ~10GB, `Qwen/Qwen3-VL-8B-Instruct` ~18GB
into `~/.cache/huggingface`, ~32GB total).

- `max_soft_tokens` is the literal parameter name, set via
  `processor.image_processor.max_soft_tokens = 1120`.
- qwen3-vl run at int4 (bitsandbytes nf4) to fit 16GB VRAM — bf16 would need ~18GB.

### Findings

**gemma4 @ 1120 tokens — the diagram win:**

| Case | Ollama (280) anti-fab v2 | transformers (1120) |
|---|---|---|
| diagram-annotated | 4/5 arrows, gRPC mis-traced, false `<->` on Redis | **all 5 arrows correct, all directions right** |
| clean-study (Raft) | 5/2 ✓ | 5/2 ✓ |
| math quadratic | `/2` (wrong) | `/2` (still wrong) |

The 1120-token budget cleanly fixed diagram connectivity — a *visual-fidelity*
error. It did **not** fix the quadratic `/2a → /2` substitution — that's a
*model-knowledge* error, invariant to visual budget.

**Cost**: 150-250s per case (7-12× Ollama). Not production-viable through this
path. It's a quality-ceiling demonstration, not a deployable config.

**qwen3-vl @ int4 — no improvement, slight degradation:**
Same Basel/quadratic substitutions, same flat diagrams as Ollama, plus *new*
int4 misreads ("Wireguard" → "Vineguard", "User DB" → "User ID"). int4 is not
a free lunch for text fidelity.

## Failure-mode taxonomy (the durable lesson)

Three distinct layers, each needing a different fix:

1. **Harness-level** (deepseek-ocr mode-collapse on negative prompts;
   gemma4 280-token ceiling): fixable by prompt override / different harness.
2. **Visual-fidelity** (gemma4 diagram arrow mis-tracing): fixable by raising
   `max_soft_tokens` — but only reachable outside Ollama today.
3. **Model-knowledge** (gemma4 Raft fab; qwen3-vl Basel `N→∞`, quadratic `/2`):
   NOT fixable by prompt or budget. The model substitutes canonical-textbook
   content for page content. Needs a different model or fine-tuning.

The anti-fab v2 prompt addresses layer 1 (and partly layer 3 for gemma4's Raft
case specifically). Layers 2 and 3 are open.

## Production recommendation

**Keep minicpm-v in production for now** — but note it scored only 2.9, the
lowest of the viable engines. gemma4 + anti-fab-v2 prompt via Ollama is the
strongest *deployable* candidate (quality leader, ~19s/page, 280-token
diagram limitation). A production swap to gemma4 is the natural R2, gated on:

- Confirming gemma4-anti-fab-v2 re-scores above minicpm-v on the full corpus
  (the markdown-decoration loss from v2's plainer output needs re-scoring)
- Accepting the 280-token diagram limitation until Ollama #15626 lands

**Watch item**: ollama/ollama#15626. When it merges, gemma4 via Ollama gets
D's diagram-connectivity win at production speed — the highest-value upgrade
on the table.

## Reproducibility

- Prompt-iteration scripts: `/tmp/r1b-antifab.py` (v1), `/tmp/r1b-antifab2.py`
  (v2), `/tmp/r1b-antifab3.py` (v3) — not committed, throwaway.
- transformers-direct: `/tmp/r1c-d-transformers.py`, venv `/tmp/r1c-venv` (5GB),
  HF weights cached in `~/.cache/huggingface` (32GB, kept for follow-up).
- Result dirs (gitignored, on mercury-srv): `discovery/results-antifab/`,
  `-antifab2/`, `-antifab3/`, `-d/`. rsync to laptop to re-score.
