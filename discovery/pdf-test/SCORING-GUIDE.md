# PDF Engine Scoring Guide

View each PDF on both the Paper Pro (color) and rM2 (grayscale).
Score 1-5 on each criterion.

## Test cases
- test-simple: headings, paragraphs, blockquote, wikilinks
- test-code: Python code blocks, inline code
- test-table: table, numbered list, checklist
- test-long: all three combined, tests pagination

## Criteria

### For COLOR profile (view on Paper Pro):
1. **Font readability** — is the text comfortable to read on e-ink?
2. **Code block clarity** — is syntax highlighting visible and useful?
   Are the colors distinguishable on Kaleido 3?
3. **Heading hierarchy** — can you instantly see the structure?
4. **Table rendering** — are columns aligned and readable?
5. **Overall polish** — does it feel like a well-formatted document?

### For GRAYSCALE profile (view on rM2):
1. **Font readability** — same criterion, grayscale display
2. **Code block clarity** — is the gray background visible? Is monospace
   text legible?
3. **Heading hierarchy** — clear without color cues?
4. **Table rendering** — same criterion
5. **Overall polish** — same criterion

### Cross-cutting:
- **Frontmatter handling** — stripped or rendered cleanly?
- **Wikilinks** — rendered as plain text without broken links?
- **Page breaks** — sensible pagination in test-long?

## Record scores

| Engine | Profile | Font | Code | Headings | Tables | Polish | Notes |
|--------|---------|------|------|----------|--------|--------|-------|
| pandoc-latex | color | | | | | | |
| pandoc-latex | grayscale | | | | | | |
| pandoc-typst | color | | | | | | |
| pandoc-typst | grayscale | | | | | | |
