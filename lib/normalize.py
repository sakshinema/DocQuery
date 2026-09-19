from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedPage:
    page: Optional[int]
    section: Optional[str]
    text: str


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph boundaries."""
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    previous_blank = False
    for raw in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            if not previous_blank:
                lines.append("")
            previous_blank = True
        else:
            lines.append(line)
            previous_blank = False
    return "\n".join(lines).strip()


def _normalized_boundary_line(line: str) -> str:
    line = line.lower().strip()
    line = re.sub(r"\d+", "#", line)
    line = re.sub(r"\s+", " ", line)
    return line


def remove_repeated_headers_footers(pages: list[ParsedPage], min_repeat_pages: int = 3) -> list[ParsedPage]:
    """Drop repeated first/last non-empty lines that look like page furniture.

    This intentionally uses a conservative threshold. A line must recur on at least
    three pages and remain short enough to plausibly be a header/footer.
    """
    if len(pages) < min_repeat_pages:
        return pages

    top_counts: Counter[str] = Counter()
    bottom_counts: Counter[str] = Counter()
    top_values: dict[str, str] = {}
    bottom_values: dict[str, str] = {}

    for page in pages:
        nonempty = [x.strip() for x in page.text.splitlines() if x.strip()]
        if not nonempty:
            continue
        for original, counter, values in [
            (nonempty[0], top_counts, top_values),
            (nonempty[-1], bottom_counts, bottom_values),
        ]:
            normalized = _normalized_boundary_line(original)
            if 3 <= len(normalized) <= 120:
                counter[normalized] += 1
                values[normalized] = original

    repeated_tops = {value for value, count in top_counts.items() if count >= min_repeat_pages}
    repeated_bottoms = {value for value, count in bottom_counts.items() if count >= min_repeat_pages}

    output: list[ParsedPage] = []
    for page in pages:
        lines = page.text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and _normalized_boundary_line(lines[0]) in repeated_tops:
            lines.pop(0)
        if lines and _normalized_boundary_line(lines[-1]) in repeated_bottoms:
            lines.pop()
        output.append(ParsedPage(page.page, page.section, clean_text("\n".join(lines))))
    return output


def chunk_pages(pages: list[ParsedPage], target_chars: int = 1800, overlap_chars: int = 250) -> list[ParsedPage]:
    """Chunk page text while retaining page and section provenance."""
    chunks: list[ParsedPage] = []
    for page in pages:
        text = clean_text(page.text)
        if not text:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= target_chars:
                current = candidate
                continue
            if current:
                chunks.append(ParsedPage(page.page, page.section, current))
                tail = current[-overlap_chars:].strip()
                current = f"{tail}\n\n{paragraph}".strip()
            else:
                for start in range(0, len(paragraph), target_chars - overlap_chars):
                    piece = paragraph[start : start + target_chars]
                    chunks.append(ParsedPage(page.page, page.section, piece))
                current = ""
        if current:
            chunks.append(ParsedPage(page.page, page.section, current))
    return chunks
