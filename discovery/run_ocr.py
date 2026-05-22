#!/usr/bin/env python3
"""Run OCR engines against rendered handwriting pages.

Usage:
    uv run discovery/run_ocr.py --engine llama-vision
    uv run discovery/run_ocr.py --engine minicpm-v
    uv run discovery/run_ocr.py --engine ade --ade-key YOUR_KEY
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import httpx

OLLAMA_URL = "http://localhost:11434"
RENDERED_DIR = Path(__file__).parent / "rendered-pages"
RESULTS_DIR = Path(__file__).parent / "results"

# Round 1 — print-OCR models (failed, kept for reference)
LEGACY_MODELS = {
    "olmocr2": "richardyoung/olmocr2:7b-q8",
    "glm-ocr": "glm-ocr",
}

# Round 2 — general vision LLMs
OLLAMA_MODELS = {
    "llama-vision": "llama3.2-vision:11b",
    "minicpm-v": "minicpm-v",
}

# Round 3 (R1, 2026-05-20) — 2026-era VLMs benchmarked against the R0 6-case corpus.
# Tier mix: two generalists (new architectures), two purpose-built document/OCR models.
R1_MODELS = {
    "qwen3-vl": "qwen3-vl:8b-instruct",
    "gemma4": "gemma4:e4b",
    "deepseek-ocr": "deepseek-ocr:3b",
    "granite-vision": "granite3.2-vision:2b",
}

ALL_OLLAMA = {**LEGACY_MODELS, **OLLAMA_MODELS, **R1_MODELS}

ADE_API_URL = "https://api.va.landing.ai/v1/ade/parse"

# Terse OCR prompt (legacy, for reference)
PROMPT = (
    "Transcribe the handwritten text in this image into Markdown format. "
    "Preserve headings, lists, hierarchy, and structure. "
    "Output only the transcribed Markdown, no commentary."
)

# Conversational vision prompt — works better with general vision LLMs
VISION_PROMPT = (
    "This is a photograph of a handwritten page. "
    "Please transcribe all the handwritten text you see into Markdown format. "
    "Preserve any headings, bullet points, lists, indentation, and structure. "
    "If there are diagrams, describe the text labels on them. "
    "Output only the transcribed text as Markdown. Do not add commentary."
)

# Per-engine prompt overrides (R1, 2026-05-20). VISION_PROMPT's negative-
# instruction tail mode-collapses some 2026-era models — they auto-complete
# more "Do not..." clauses instead of transcribing. Override per-engine
# rather than swapping the default, so R0 baselines (minicpm-v, llama-vision)
# stay anchored to the prompt they were originally scored on.
PROMPT_OVERRIDES = {
    # deepseek-ocr:3b emits EOS immediately if the prompt mentions "Markdown"
    # or "Preserve … structure" — likely a quirk of its document-OCR training
    # distribution. This minimal prompt was verified empirically to produce
    # well-structured markdown output on the corpus.
    "deepseek-ocr": "Transcribe the handwritten text in this image. Output only the transcribed text.",
    # gemma4:e4b fabricates canonical-textbook content under VISION_PROMPT
    # (e.g. wrote "$S nodes / $F failures" for a Raft consensus page that
    # actually shows "5 nodes / 2 failures"). This anti-fabrication prompt
    # kills the substitution. The explicit diagram clause recovers the
    # arrow-structure inference that an earlier verbatim-only variant broke
    # (gemma4 was producing flat run-on strings for service-flow diagrams).
    # See discovery/R1-comparison.md and the R1b iteration commit message.
    "gemma4": (
        "Transcribe the handwritten text on this page verbatim. "
        "Preserve the exact numbers, variables, and symbols that appear in the handwriting. "
        "For diagrams with arrows, list each labeled connection on its own line, in the order they appear. "
        "Output only the transcription."
    ),
}

# Hard cap on generated tokens — defense-in-depth against any verbose / looping
# model. One page of handwriting is typically <400 tokens; 1024 leaves headroom.
NUM_PREDICT = 1024


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def run_ollama(engine: str, model: str, image_path: Path) -> tuple[str, float]:
    prompt = PROMPT_OVERRIDES.get(engine, VISION_PROMPT)
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [encode_image(image_path)],
        "stream": False,
        "options": {"num_predict": NUM_PREDICT},
    }
    start = time.monotonic()
    resp = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json=payload,
        timeout=300.0,
    )
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return resp.json()["response"], elapsed


def run_ade(image_path: Path, api_key: str) -> tuple[str, float]:
    """Run LandingAI ADE Parse API on an image. Returns (markdown_text, elapsed_seconds)."""
    start = time.monotonic()
    with open(image_path, "rb") as f:
        resp = httpx.post(
            ADE_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            files={"document": (image_path.name, f, "image/png")},
            data={"model": "dpt-2-latest"},
            timeout=120.0,
        )
    elapsed = time.monotonic() - start
    resp.raise_for_status()

    result = resp.json()
    # On first call, print the response structure so we can find the right field
    if not hasattr(run_ade, "_schema_printed"):
        run_ade._schema_printed = True
        print(f"  ADE response structure: {_describe_json(result)}")

    # Try common response field names
    if isinstance(result, dict):
        for key in ("markdown", "text", "content", "result", "data"):
            if key in result:
                val = result[key]
                if isinstance(val, str):
                    return val, elapsed
                if isinstance(val, dict) and "markdown" in val:
                    return val["markdown"], elapsed
                if isinstance(val, dict) and "text" in val:
                    return val["text"], elapsed
    # Fallback: return full JSON as string
    return json.dumps(result, indent=2), elapsed


def _describe_json(obj, depth=0):
    """Describe JSON structure (keys + types) without full content."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        items = {k: _describe_json(v, depth + 1) for k, v in obj.items()}
        return items
    if isinstance(obj, list):
        if obj:
            return [_describe_json(obj[0], depth + 1), f"... ({len(obj)} items)"]
        return []
    return type(obj).__name__


def main():
    all_engines = list(ALL_OLLAMA.keys()) + ["ade"]
    parser = argparse.ArgumentParser(description="Run OCR on rendered pages")
    parser.add_argument("--engine", required=True, choices=all_engines)
    parser.add_argument("--ade-key", help="LandingAI ADE API key (required for ade engine)")
    args = parser.parse_args()

    if args.engine == "ade" and not args.ade_key:
        print("FAIL: --ade-key required for ade engine")
        sys.exit(1)

    if not RENDERED_DIR.exists():
        print(f"FAIL: {RENDERED_DIR} does not exist. Run extract_and_render.sh first.")
        sys.exit(1)

    test_cases = sorted(
        [d for d in RENDERED_DIR.iterdir() if d.is_dir()],
        key=lambda p: p.name,
    )
    if not test_cases:
        print(f"FAIL: No test case directories in {RENDERED_DIR}")
        sys.exit(1)

    output_dir = RESULTS_DIR / args.engine
    output_dir.mkdir(parents=True, exist_ok=True)
    timing_data = {}

    if args.engine == "ade":
        print(f"Engine: ade (LandingAI ADE)")
    else:
        model = ALL_OLLAMA[args.engine]
        print(f"Engine: {args.engine} ({model})")
    print(f"Test cases: {[tc.name for tc in test_cases]}")
    print()

    for tc_dir in test_cases:
        pages = sorted(tc_dir.glob("*.png"))
        if not pages:
            print(f"  SKIP: {tc_dir.name} — no PNGs")
            continue

        print(f"  {tc_dir.name} ({len(pages)} page(s))...")
        tc_texts = []
        tc_timings = []

        for page in pages:
            print(f"    {page.name}...", end=" ", flush=True)
            try:
                if args.engine == "ade":
                    text, elapsed = run_ade(page, args.ade_key)
                else:
                    text, elapsed = run_ollama(args.engine, ALL_OLLAMA[args.engine], page)
                tc_texts.append(text)
                tc_timings.append({"page": page.name, "seconds": round(elapsed, 2)})
                print(f"{elapsed:.1f}s")
            except Exception as e:
                print(f"ERROR: {e}")
                tc_texts.append(f"[ERROR: {e}]")
                tc_timings.append({"page": page.name, "seconds": -1, "error": str(e)})

        combined = "\n\n---\n\n".join(tc_texts)
        out_file = output_dir / f"{tc_dir.name}.md"
        out_file.write_text(combined)

        total_time = sum(t["seconds"] for t in tc_timings if t["seconds"] > 0)
        timing_data[tc_dir.name] = {
            "pages": tc_timings,
            "total_seconds": round(total_time, 2),
        }
        print(f"    -> {out_file.name} ({total_time:.1f}s total)")

    timing_file = output_dir / "timing.json"
    timing_file.write_text(json.dumps(timing_data, indent=2))
    print(f"\nTiming saved to {timing_file}")

    grand_total = sum(v["total_seconds"] for v in timing_data.values())
    total_pages = sum(len(v["pages"]) for v in timing_data.values())
    print(f"\nSummary: {total_pages} pages, {grand_total:.1f}s total")
    if total_pages:
        print(f"Average: {grand_total / total_pages:.1f}s/page")


if __name__ == "__main__":
    main()
