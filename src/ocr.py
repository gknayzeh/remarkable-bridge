"""
OCR handwritten pages using minicpm-v via Ollama.

Proven in R0 discovery: minicpm-v scores 3.4/5, 7.8s/page on RTX 3080.
"""
import base64
import threading
import time
from pathlib import Path

import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "minicpm-v"
PAGE_TIMEOUT = 90  # seconds — kill hung pages

PROMPT = (
    "This is a photograph of a handwritten page. "
    "Please transcribe all the handwritten text you see into Markdown format. "
    "Preserve any headings, bullet points, lists, indentation, and structure. "
    "If there are diagrams, describe the text labels on them. "
    "Output only the transcribed text as Markdown. Do not add commentary."
)


def _do_ocr(image_b64: str, result: dict) -> None:
    """Run the actual OCR call in a thread."""
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": PROMPT,
                "images": [image_b64],
                "stream": False,
                "keep_alive": "30m",
            },
            timeout=httpx.Timeout(PAGE_TIMEOUT, connect=10.0),
        )
        resp.raise_for_status()
        result["text"] = resp.json()["response"]
    except Exception as e:
        result["error"] = e


def ocr_page(image_path: Path) -> tuple[str, float]:
    """OCR a single page image. Returns (markdown_text, elapsed_seconds).

    Runs OCR in a daemon thread with a hard timeout. If the thread hangs
    (Ollama keeps connection alive), we abandon it and move on.
    """
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()
    result = {}

    start = time.monotonic()
    thread = threading.Thread(target=_do_ocr, args=(image_b64, result), daemon=True)
    thread.start()
    thread.join(timeout=PAGE_TIMEOUT)
    elapsed = time.monotonic() - start

    if thread.is_alive():
        # Thread is hung — abandon it (daemon thread dies with process)
        raise TimeoutError(f"OCR timed out after {PAGE_TIMEOUT}s")

    if "error" in result:
        raise result["error"]

    return result["text"], elapsed


def ocr_notebook(page_pngs: list[Path]) -> tuple[str, float]:
    """OCR all pages of a notebook. Returns (combined_markdown, total_seconds)."""
    pages = []
    total_time = 0.0

    for i, png in enumerate(sorted(page_pngs)):
        try:
            text, elapsed = ocr_page(png)
            pages.append(text)
            total_time += elapsed
        except Exception as e:
            print(f"\n    Warning: OCR failed on page {i} ({png.name}): {e}")
            pages.append(f"[OCR failed for page {i}]")

    combined = "\n\n---\n\n".join(pages)
    return combined, total_time
