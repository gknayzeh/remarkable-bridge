"""
Preprocess Markdown for reMarkable PDF rendering.

Handles:
- Strip YAML frontmatter (--- delimited blocks at start of file)
- Strip Obsidian block IDs ( ^block-id at end of lines)
- Convert Obsidian wikilinks to bold readable text (not clickable in PDF)
- Escape bare @references outside code blocks (prevents Pandoc citation errors)
"""
import re
import sys
from pathlib import Path


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from the start of a Markdown file."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def strip_block_ids(text: str) -> str:
    """Remove Obsidian block IDs (e.g. ^REQ-CRYPT-006) from end of lines."""
    return re.sub(r' \^[\w-]+$', '', text, flags=re.MULTILINE)


def convert_wikilinks(text: str) -> str:
    """Convert Obsidian wikilinks to bold readable text.

    Examples:
        [[file#^REQ-CRYPT-006|REQ-CRYPT-006]] -> **REQ-CRYPT-006**
        [[file#^REQ-CRYPT-006]] -> **REQ-CRYPT-006**
        [[crypto-protocol|Crypto Protocol]] -> **Crypto Protocol**
        [[crypto-protocol]] -> **crypto-protocol**
    """
    def _resolve(m: re.Match) -> str:
        target, display = m.group(1), m.group(2)
        if display:
            return f'**{display}**'
        if '#' in target:
            fragment = target.split('#', 1)[1]
            return f'**{fragment.lstrip("^")}**'
        return f'**{target}**'

    return re.sub(r'\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]', _resolve, text)


def escape_citations(text: str) -> str:
    """Escape bare @references outside code blocks to prevent Pandoc citation errors.

    @Published, @objc etc. in prose trigger Pandoc's citation parser.
    Escaping to \\@ makes them literal in the output.
    Leaves @references inside ``` fenced code blocks untouched.
    """
    lines = text.split('\n')
    result = []
    in_code_block = False
    for line in lines:
        if line.startswith('```'):
            in_code_block = not in_code_block
        if not in_code_block:
            line = re.sub(r'(?<!\S)@(\w+)', r'\\@\1', line)
        result.append(line)
    return '\n'.join(result)


def preprocess(text: str) -> str:
    """Run all preprocessing steps."""
    text = strip_frontmatter(text)
    text = strip_block_ids(text)
    text = convert_wikilinks(text)
    text = escape_citations(text)
    return text


def main():
    """CLI: read from stdin or file arg, write to stdout."""
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text()
    else:
        text = sys.stdin.read()
    sys.stdout.write(preprocess(text))


if __name__ == "__main__":
    main()
