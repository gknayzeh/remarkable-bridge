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

ALL_OLLAMA = {**LEGACY_MODELS, **OLLAMA_MODELS}

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


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def run_ollama(model: str, image_path: Path) -> tuple[str, float]:
    payload = {
        "model": model,
        "prompt": VISION_PROMPT,
        "images": [encode_image(image_path)],
        "stream": False,
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
                    text, elapsed = run_ollama(ALL_OLLAMA[args.engine], page)
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
