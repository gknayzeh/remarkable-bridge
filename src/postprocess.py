"""
Post-process OCR output into vault-ready Markdown with frontmatter.
"""
import re
from datetime import datetime, timezone


def create_vault_markdown(
    ocr_text: str,
    notebook_name: str,
    rm_folder: str,
    page_count: int,
    attachment_path: str | None = None,
) -> str:
    """Wrap OCR text in frontmatter for the vault."""
    now = datetime.now(timezone.utc).isoformat()

    frontmatter = f"""---
title: "{notebook_name}"
source: remarkable
remarkable_notebook: "{notebook_name}"
remarkable_folder: "{rm_folder}"
page_count: {page_count}
date_converted: {now}
tags:
  - type/handwritten
  - source/remarkable
  - status/needs-review
---"""

    parts = [frontmatter, "", ocr_text]

    if attachment_path:
        parts.extend([
            "",
            "---",
            f"> **Original**: [[{attachment_path}]]",
        ])

    return "\n".join(parts)


def sanitize_filename(name: str) -> str:
    """Convert a reMarkable notebook name to a safe filename.

    - Lowercase
    - Replace spaces with hyphens
    - Remove special characters
    - Collapse multiple hyphens
    """
    name = name.lower().strip()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s_]+', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')


def sanitize_folder_path(rm_path: str) -> str:
    """Convert a reMarkable folder path to a vault-safe directory path.

    /Study/Distributed Systems → study/distributed-systems
    """
    parts = rm_path.strip("/").split("/")
    return "/".join(sanitize_filename(p) for p in parts if p)
