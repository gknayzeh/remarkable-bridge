#!/usr/bin/env python3
"""Run OCR engines against rendered handwriting pages.

Usage:
    uv run discovery/run_ocr.py --engine olmocr2
    uv run discovery/run_ocr.py --engine glm-ocr
    uv run discovery/run_ocr.py --engine ade --api-key <key> --endpoint <url>
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

ENGINE_MODELS = {
    "olmocr2": "richardyoung/olmocr2:7b-q8",
    "glm-ocr": "glm-ocr",
}

PROMPT = (
    "Transcribe the handwritten text in this image into Markdown format. "
    "Preserve headings, lists, hierarchy, and structure. "
    "Output only the transcribed Markdown, no commentary."
)


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def run_ollama(model: str, image_path: Path) -> tuple[str, float]:
    """Send image to Ollama and return (response_text, elapsed_seconds)."""
    payload = {
        "model": model,
        "prompt": PROMPT,
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


def run_ade(image_path: Path, api_key: str, endpoint: str) -> tuple[str, float]:
    """Skeleton for Azure Document Intelligence. Not yet implemented."""
    raise NotImplementedError(
        "ADE engine requires API key and endpoint verification. "
        "Set --api-key and --endpoint, then implement this function."
    )


def main():
    parser = argparse.ArgumentParser(description="Run OCR on rendered pages")
    parser.add_argument(
        "--engine",
        required=True,
        choices=["olmocr2", "glm-ocr", "ade"],
        help="OCR engine to use",
    )
    parser.add_argument("--api-key", help="API key (for ADE)")
    parser.add_argument("--endpoint", help="Endpoint URL (for ADE)")
    args = parser.parse_args()

    if not RENDERED_DIR.exists():
        print(f"FAIL: {RENDERED_DIR} does not exist. Run pdftoppm first.")
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

    print(f"Engine: {args.engine}")
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

            if args.engine == "ade":
                text, elapsed = run_ade(page, args.api_key, args.endpoint)
            else:
                model = ENGINE_MODELS[args.engine]
                text, elapsed = run_ollama(model, page)

            tc_texts.append(text)
            tc_timings.append({"page": page.name, "seconds": round(elapsed, 2)})
            print(f"{elapsed:.1f}s")

        # Write combined output
        combined = "\n\n---\n\n".join(tc_texts)
        out_file = output_dir / f"{tc_dir.name}.md"
        out_file.write_text(combined)

        total_time = sum(t["seconds"] for t in tc_timings)
        timing_data[tc_dir.name] = {
            "pages": tc_timings,
            "total_seconds": round(total_time, 2),
        }
        print(f"    -> {out_file.name} ({total_time:.1f}s total)")

    # Write timing data
    timing_file = output_dir / "timing.json"
    timing_file.write_text(json.dumps(timing_data, indent=2))
    print(f"\nTiming saved to {timing_file}")

    # Summary
    grand_total = sum(v["total_seconds"] for v in timing_data.values())
    total_pages = sum(
        len(v["pages"]) for v in timing_data.values()
    )
    print(f"\nSummary: {total_pages} pages, {grand_total:.1f}s total")
    if total_pages:
        print(f"Average: {grand_total / total_pages:.1f}s/page")


if __name__ == "__main__":
    main()
