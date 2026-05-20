# R1 OCR engine comparison

**Date:** 2026-05-20
**Hardware:** mercury-srv, RTX 3080 16GB (shared with whisperx/immich-ml/jellyfin)
**Corpus:** `discovery/rendered-pages/{clean-study, code-adjacent, diagram-annotated, math-equations, messy-quick, mixed-content}` (6 cases × 1 page each)
**Ollama:** local, all models pulled in this session
**Harness changes:** `discovery/run_ocr.py` — added `PROMPT_OVERRIDES` per-engine and global `num_predict: 1024` cap. See diff vs R0.

## Headline

**Recommendation: no production swap. Hold for manual scoring before any
further action.** A spot-check across math-equations, code-adjacent, and
mixed-content revealed that *every* candidate (including the refreshed
minicpm-v baseline) has real content-fidelity issues on hard pages —
fabrications from canonical-form priors (gemma4 on Raft, qwen3-vl on math),
or outright mangling (minicpm-v on math/code). The clean-study spot-check
that drove this writeup's first draft was misleading because it's the
easiest case. **The 5-dimension scoring rubric is the only reliable way to
rank these — the objective signal alone doesn't pick a winner.**

## Engines

| Engine | Tag | Disk | Peak VRAM (MiB) | Success | Avg s/page |
|---|---|---|---|---|---|
| minicpm-v (R1 refresh) | `minicpm-v:latest` | 5.5GB | **5681** | 6/6 | 4.0 |
| qwen3-vl | `qwen3-vl:8b-instruct` | 6.1GB | **15827** | 6/6 | 9.5 |
| deepseek-ocr | `deepseek-ocr:3b` | ~3GB | 8883¹ | 6/6 | **2.0** |
| gemma4 | `gemma4:e4b` | 9.6GB | 9695 | 6/6 | 19.0 |
| granite-vision | `granite3.2-vision:2b` | 2.4GB | **3401** | 5/6² | 5.5 |

¹ Measured during the broken-prompt run; model weights + KV cache + image
encoder don't depend on prompt content, so the figure transfers.
² 1 timeout on `mixed-content` at 300s.

## Per-case timing (seconds)

| Case | minicpm-v | qwen3-vl | deepseek-ocr | gemma4 | granite-vision |
|---|---:|---:|---:|---:|---:|
| clean-study       | 3.5  | 22.2³ | 1.2 | 15.0³ | 1.6   |
| code-adjacent     | 5.0  | 7.4   | 2.6 | 22.4  | 5.8   |
| diagram-annotated | 2.6  | 5.5   | 1.5 | 17.9  | 3.4   |
| math-equations    | 5.2  | 8.2   | 2.4 | 22.8  | 18.4  |
| messy-quick       | 3.8  | 6.3   | 2.1 | 17.4  | 4.1   |
| mixed-content     | 4.1  | 7.7   | 2.4 | 18.3  | **TIMEOUT** |

³ Cold-load run (first page after pull). Steady-state is ~5-8s for qwen3-vl,
~17-22s for gemma4.

## Output size sanity-check vs ground-truth (bytes)

| Case | ground-truth | minicpm-v | qwen3-vl | deepseek-ocr | gemma4 | granite-vision |
|---|---:|---:|---:|---:|---:|---:|
| clean-study       | 577 | 419  | 567 | 565 | 565  | (large)⁴ |
| code-adjacent     | 664 | 694  | 680 | 634 | 660  | (large)⁴ |
| diagram-annotated | 238 | 205  | 318 |  50 | 323  | (large)⁴ |
| math-equations    | 431 | 473  | 445 | 444 | 368  | (large)⁴ |
| messy-quick       | 375 | 368  | 359 | 374 | 358  | (large)⁴ |
| mixed-content     | 831 | 685  | 785 | 755 | 720  | — (timed out) |

⁴ Granite-vision tends to produce verbose flowing output with mid-word
hyphenation; sizes are 2-5× ground-truth length. Not directly comparable to
the other engines' clean transcriptions.

## Qualitative findings

### Clean-study (easiest case)

**Ground truth anchor:**
> A cluster of 5 nodes can tolerate 2 failures.

| Engine | Same line |
|---|---|
| minicpm-v R1 | `A cluster of 5 nodes can tolerate 2 failures.` ✓ exact |
| qwen3-vl     | `A cluster of 5 nodes can tolerate 2 failures.` ✓ exact |
| deepseek-ocr | `A cluster of 5 nodes can tolerate 2 failures.` ✓ exact |
| gemma4       | `A cluster of $S$ nodes can tolerate $F$ failures.` ✗ **prior-knowledge fabrication** |
| granite      | `3 nodes can tolerate 2 heartbeats every 150 ms general clock...` ✗ (word salad — granite flattened the whole page) |

Gemma4 substituted abstract variables for the concrete numbers actually on
the page. Confirmed across two runs (sanity-check used `⌊N/2⌋`, benchmark
used `$F$`) — the substitution itself is consistent.

### Spot-check on harder cases (math-equations, code-adjacent, mixed-content)

The clean-study impression that qwen3-vl is "essentially verbatim" and gemma4
is a "categorical fabricator" doesn't hold up on harder content. Per-case
findings:

**math-equations** (sum from k=1 to N → π²/6; quadratic formula x = (-b ± √(b²-4ac))/2a):

| Engine | What it did |
|---|---|
| qwen3-vl | Wrote `\sum_{k=1}^{\infty}` (page says `N`); wrote `/2` (page says `/2a`); used `X(k)` instead of `X(f)` for Fourier. **Multiple silent "corrections" toward canonical Basel/quadratic forms.** |
| gemma4 | Wrote `X(R)` (matches page where the `f` is drawn ambiguously); `\theta - \alpha \gamma J` (gamma instead of nabla — symbol drift, not fabrication); output **truncated** at summation by the 1024-token cap. |
| minicpm-v | `e^{i1} + 1 = a` (mangled iπ → i1, 0 → a); `Bajis' Theorem` (Bayes); heavy mangling throughout. Worst of the three. |
| deepseek-ocr | (not inspected in detail — sizes match ground-truth) |

**code-adjacent** (Python function with literal strings):

| Engine | What it did |
|---|---|
| qwen3-vl | Code preserved; minor typo `rmap.put` (vs `rmapi.put`); `log.info` line indentation shifted into the loop. |
| gemma4 | Real *omissions* (dropped lines), duplicated `log.info("nothing to push")` and `return`, missing `=note.hash` arg. Not prior-knowledge fabrication — looks like ordinary OCR/copy errors. |
| minicpm-v | Wholly mangled: `def \`sync-vault\`, to - remarkable`, `pdR` instead of `pdf`, backticks injected everywhere. |

**mixed-content** (memory-consistency-models notes with code-y inline content like `arch/arm/core/barrier.h`):
- All three engines preserved the file path correctly.
- All three made minor word-substitution errors (`use thr!` for `use this!` etc).
- qwen3-vl shuffled section order; gemma4 dropped two callout lines; minicpm-v mangled less here than on the math/code cases.

**Updated picture of fabrication patterns:**
- **gemma4** fabricates specifically when the canonical form is well-known
  (Raft consensus). On math/code/notes it makes ordinary OCR errors, not
  knowledge-substitution. So the disqualifier is narrower than the first
  draft claimed: *"weak on canonical-textbook content where prior knowledge
  intrudes"*, not *"categorical fabricator"*.
- **qwen3-vl** has its own canonical-substitution issue (writing the Basel
  sum to ∞ when the page shows N) — caught only because the spot-check
  looked at math. On clean-study (Raft) qwen3-vl was honest about the
  concrete numbers; on math-equations it isn't. **The "best on quality"
  read from clean-study alone is misleading.**
- **minicpm-v R1** is much worse than R0 reputation suggested *on hard
  content* — clean prose pages OK, math/code pages heavily mangled.
- **deepseek-ocr** wasn't deeply inspected here but already disqualified
  by missing diagram structure entirely on `diagram-annotated`.
- **granite-vision** word-salads everything.

This is exactly what the 5-dimension rubric (especially `accuracy` +
`edge_cases`) is designed to catch. The objective bytes-and-timing comparison
can't tell you which engine is *honest* about what's on the page; only
side-by-side scoring against ground truth can.

## Engine-by-engine notes

### minicpm-v (R1 refresh)

**Behavioural shift from R0**: outputs now use real markdown headings
(`# Consensus Algorithms`, `## Raft Protocol`) instead of R0's plain-text
+ code-fence wrapper. R1 average 4.0s/page is materially faster than R0's
reported 7.8s/page — likely a combination of refreshed weights and the new
`num_predict: 1024` cap reducing trailing generation.

**Concerning regression**: on `clean-study`, the R1 output ends mid-section at
`## Paxos vs Raft` with no body text. R0 output (now lost from disk, but
observed during this session) included the full Paxos paragraph. Truncation
isn't the harness — 1024 tokens ≫ the missing content. The model decided to
stop on its own. Worth verifying whether other cases show similar early-stop
behaviour before concluding R1-minicpm-v is the new baseline.

### qwen3-vl:8b-instruct

**Quality leader on prose, mixed on math.** On clean-study (prose),
essentially verbatim: "three subproblems" ✓ (deepseek-ocr got "two"),
"150 ms" ✓ (deepseek had "150 ns"), "non-Byzantine" ✓ (deepseek truncated
to "non-B"), proper paragraph spacing, no code-fence wrapper.

**But on math-equations**, qwen3-vl makes silent "corrections" toward
canonical form: wrote `\sum_{k=1}^{\infty}` where the page says `N`
(rewriting the page's finite-N sum into the Basel problem's infinite form),
wrote `\frac{...}{2}` where the page says `2a` for the quadratic formula
(arguably an error against the canonical form), `X(k)` where ground-truth
has `X(f)`. This is a category-similar failure mode to gemma4's Raft
fabrication — substituting canonical content for what's actually on the
page — just on a different content slice.

**Cost**: peak VRAM **15827 MiB out of 16384**. The 6.1GB model expanded
to 2.6× its disk footprint at runtime — Ollama's default context window
(likely 32K-128K) and KV cache allocation account for the difference. As
a drop-in replacement for minicpm-v in production this would cause OOMs
against whisperx/immich-ml/jellyfin. Mitigation exists (`options.num_ctx`
per-request to ~4K) but adds harness complexity and was not tested here.

### deepseek-ocr:3b

**Required a per-engine prompt override.** The R0 `VISION_PROMPT` ("...
Output only the transcribed text as Markdown. Do not add commentary.")
causes deepseek-ocr to **mode-collapse** — it generates "Do not include line
breaks." thousands of times instead of transcribing. Outputs hit 200-400×
ground-truth size before timeout. With the short prompt
("Transcribe the handwritten text in this image. Output only the transcribed
text.") it produces excellent prose transcription at 2.0s/page average.

**Strong on prose, weak on diagrams.** On `diagram-annotated` (a service-flow
diagram with 5 labelled arrows), deepseek-ocr produced **only the bottom
annotation** (50 bytes) — completely missing the diagram structure. R0
minicpm-v attempted (messy ASCII art with all labels). For G's notes which
mix prose, diagrams, and code, this is a meaningful blind spot.

**Other quirks**: minor word-form drift ("heartbeats" → "heartbeat"),
unit-letter substitution ("150 ms" → "150 ns"), occasional truncation
("non-Byzantine" → "non-B").

### gemma4:e4b

**Conditional disqualifier — depends on G's content mix.** On clean-study
(Raft), gemma4 substitutes abstract variables for concrete page numbers.
The substitution is two-run-consistent (sanity-check produced `⌊N/2⌋`,
benchmark produced `$F$`). On math-equations, code-adjacent, and
mixed-content, gemma4 makes *ordinary OCR errors* (omissions, symbol
drift, duplicated lines) but **does not** substitute canonical formulas.
The fabrication appears to fire specifically when the model has strong
canonical priors over the page content.

If G's notes frequently cover canonical textbook material (consensus
algorithms, classical theorems, well-known designs), this is a meaningful
risk — those notes would silently get rewritten into textbook form. If
they're mostly novel/personal content, the risk is lower.

**Also slowest** at 19.0s/page (~5× minicpm-v) and produces verbose
markdown with `**bold**` and `*bullet*` decoration that doesn't match
G's vault style.

**Also: output truncated by the 1024-token cap on math-equations** — the
summation formula cut off mid-expression. Either gemma4 needs a higher
cap or the cap is doing the right thing by killing a model that wants to
emit far more than the page contains.

### granite3.2-vision:2b

**Smallest VRAM footprint by far (3.4GB peak).** Worth keeping on the
shortlist for memory-constrained scenarios.

**But timed out on `mixed-content`** at the harness 300s limit — and
production `src/ocr.py` has a stricter 90s per-page timeout. A model that
can hang for 5+ minutes on a single page is incompatible with the systemd-
scheduled production pipeline without further safety work.

**Output quality is poor across the board**: tends to flatten page structure
into prose with mid-word hyphenation ("separa- tion", "repl ication"),
loses paragraph breaks, garbles content order. The on-page reading order
seems unreliable — likely tuned for tables/charts (Granite's stated strong
suit) rather than free-form handwriting.

## Harness changes (R1)

Minimal additions to `discovery/run_ocr.py`:
- `R1_MODELS` dict registering the four new engines + a `granite-vision` key
- `PROMPT_OVERRIDES` dict — deepseek-ocr-specific short prompt
- `NUM_PREDICT = 1024` — global token cap defending against verbose / looping
  models
- `run_ollama()` now takes engine name as first arg to look up the override

`discovery/score_ocr.py`'s `ENGINES` list extended with the four new keys
plus `minicpm-v` (which was missing from the R0 scoring list).

## VRAM management lesson (operational)

Between successive engine runs, Ollama's `keep_alive` cache retains
previous models. On this 16GB card, two ~10GB models cannot coexist —
attempting to load gemma4 while qwen3-vl was still resident produced a
clean `500 model failed to load, resource limitations` error from Ollama,
not an OOM crash. Explicit eviction
(`POST /api/generate {"model":"X","keep_alive":0}`) before swapping engines
is required for unattended benchmark loops.

## Verification status

- [x] `discovery/results/{minicpm-v,qwen3-vl,gemma4,deepseek-ocr,granite-vision}/`
      each contain 6 `.md` files + `timing.json` (granite has 6 files but
      `mixed-content.md` is empty due to timeout)
- [x] Peak VRAM recorded for each engine
- [ ] **Pending — G's laptop**: `discovery/score_ocr.py` to populate
      `discovery/scores.json` with 5-dimension manual ratings for all 5
      engines × 6 cases (= 150 ratings)
- [x] `src/ocr.py` and `src/render.py` untouched (verify: `git status`)

## R2 trigger conditions (from the R1 plan)

> If any candidate scores ≥4.0 avg and beats minicpm-v on at least 4/5
> dimensions on clean-study + messy-quick, that's the trigger for an R2
> plan to wire it into `src/ocr.py`.

**Subjective preview (must be confirmed or walked back by scoring on the
full 6-case corpus, not just clean-study + messy-quick):**

- **No candidate is a clean R2 trigger from this side.** Each has a
  content-class blind spot:
  - qwen3-vl substitutes canonical math forms; also 15.8/16GB VRAM
  - gemma4 substitutes canonical Raft-style content; slowest engine
  - deepseek-ocr misses diagram structure entirely
  - granite-vision word-salads everything, plus a 5-min timeout
  - minicpm-v R1 itself regressed on hard content vs R0 reputation
- **If scoring confirms qwen3-vl wins on prose despite the math issue**, a
  conditional R2 would still need an `num_ctx` cap (4K likely fine) before
  any production swap. The cap should be co-tested for accuracy regression
  alongside the VRAM win.
- **A separate R1b worth scoping**: re-evaluate minicpm-v R1's math/code
  regression. The R1 refresh may have shifted the model weights in a way
  that costs us on edge cases. If a model-version pin would recover R0
  behaviour, no swap is needed.

## What to score next (on G's laptop)

```
# rsync results from mercury-srv to laptop, then:
cd ~/dev/tools/remarkable-bridge && uv run discovery/score_ocr.py
```

The 5-dimension rubric in `score_ocr.py:18-24` is unchanged from R0.
Pay attention to whether `markdown_quality` differentiates engines that all
score high on `accuracy` — that's where qwen3-vl's lack of code-fence wrapper
should show up vs minicpm-v's structural quirks.
