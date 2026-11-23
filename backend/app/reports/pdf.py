import re
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 54
FONT = "helv"
FONT_CANDIDATES = [
    ("Nirmala.ttf", "NirmalaB.ttf"),
    ("ebrima.ttf", "ebrimabd.ttf"),
    ("segoeui.ttf", "segoeuib.ttf"),
    ("malgun.ttf", "malgunbd.ttf"),
    ("msgothic.ttc", "msgothic.ttc"),
    ("simsun.ttc", "simsunb.ttf"),
    ("arial.ttf", "arialbd.ttf"),
]


def _safe_text(value: str) -> str:
    return value.replace("\x00", "")


@lru_cache(maxsize=32)
def _font(fontfile: str | None) -> fitz.Font:
    return fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname=FONT)


def _font_file(text: str, bold: bool = False) -> str | None:
    windows_fonts = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
    candidates: list[tuple[Path, Path]] = [
        (windows_fonts / regular, windows_fonts / bold_file)
        for regular, bold_file in FONT_CANDIDATES
    ]
    candidates.extend([
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")),
    ])
    codepoints = {ord(char) for char in text if not char.isspace()}
    available = [(regular, bold_path) for regular, bold_path in candidates if regular.is_file()]
    for regular, bold_path in available:
        try:
            font = _font(str(regular))
        except (RuntimeError, ValueError):
            continue
        if all(font.has_glyph(codepoint) for codepoint in codepoints):
            return str(bold_path if bold and bold_path.is_file() else regular)
    if available:
        regular, bold_path = max(
            available,
            key=lambda paths: sum(_font(str(paths[0])).has_glyph(codepoint) for codepoint in codepoints),
        )
        return str(bold_path if bold and bold_path.is_file() else regular)
    return None


def _insert_text(
    page: fitz.Page,
    point: tuple[float, float],
    text: str,
    fontsize: float,
    color: tuple[float, float, float],
    bold: bool = False,
) -> None:
    fontfile = _font_file(text, bold)
    fontname = f"Nexus-{Path(fontfile).stem}" if fontfile else ("hebo" if bold else FONT)
    page.insert_text(
        point,
        _safe_text(text),
        fontname=fontname,
        fontfile=fontfile,
        fontsize=fontsize,
        color=color,
    )


def _new_content_page(document: fitz.Document, document_kind: str) -> fitz.Page:
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _insert_text(page, (MARGIN, 38), f"NEXUS AI  /  {document_kind}", 8, (0.42, 0.46, 0.54), bold=True)
    page.draw_line((MARGIN, 50), (PAGE_WIDTH - MARGIN, 50), color=(0.84, 0.86, 0.9), width=0.7)
    return page


def _wrap_text(text: str, font_size: float, max_width: float, fontfile: str | None = None) -> list[str]:
    words = _safe_text(text).split()
    lines: list[str] = []
    current = ""
    font = _font(fontfile)

    for word in words:
        candidate = f"{current} {word}".strip()
        if font.text_length(candidate, fontsize=font_size) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
        current = word

        while font.text_length(current, fontsize=font_size) > max_width:
            split_at = max(1, len(current) - 1)
            while split_at > 1 and font.text_length(current[:split_at], fontsize=font_size) > max_width:
                split_at -= 1
            lines.append(current[:split_at])
            current = current[split_at:]

    if current:
        lines.append(current)
    return lines


def _wrap_code_line(text: str, font_size: float, max_width: float, fontfile: str | None = None) -> list[str]:
    font = _font(fontfile)
    remaining = _safe_text(text).expandtabs(4)
    lines: list[str] = []
    while font.text_length(remaining, fontsize=font_size) > max_width:
        split_at = len(remaining)
        while split_at > 1 and font.text_length(remaining[:split_at], fontsize=font_size) > max_width:
            split_at -= 1
        lines.append(remaining[:split_at])
        remaining = remaining[split_at:]
    lines.append(remaining)
    return lines


def render_research_report_pdf(report: dict[str, Any]) -> bytes:
    is_study_guide = report.get("report_type") == "study_guide"
    document_kind = "STUDENT STUDY GUIDE" if is_study_guide else "EXECUTIVE RESEARCH DOSSIER"
    document = fitz.open()
    cover = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    cover.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, 12), color=(0.31, 0.27, 0.9), fill=(0.31, 0.27, 0.9))
    cover.insert_text((MARGIN, 94), "NEXUS AI  /  DEEP RESEARCH", fontname="hebo", fontsize=11, color=(0.31, 0.27, 0.9))
    title_y = 150
    for line in _wrap_text(report["title"], 27, PAGE_WIDTH - MARGIN * 2, _font_file(report["title"], True)):
        _insert_text(cover, (MARGIN, title_y), line, 27, (0.08, 0.12, 0.22), bold=True)
        title_y += 36
    _insert_text(cover, (MARGIN, max(318, title_y + 12)), document_kind, 10, (0.36, 0.4, 0.49), bold=True)
    topic_y = max(350, title_y + 45)
    for line in _wrap_text(report["topic"], 12, PAGE_WIDTH - MARGIN * 2, _font_file(report["topic"])):
        _insert_text(cover, (MARGIN, topic_y), line, 12, (0.16, 0.2, 0.29))
        topic_y += 17
    line_y = max(520, topic_y + 25)
    cover.draw_line((MARGIN, line_y), (PAGE_WIDTH - MARGIN, line_y), color=(0.82, 0.84, 0.89), width=1)
    _insert_text(cover, (MARGIN, line_y + 34), f"Prepared {report['created_at'][:10]}", 10, (0.38, 0.42, 0.5))
    _insert_text(cover, (MARGIN, line_y + 58), f"Evidence scope: {len(report['document_names'])} selected source document(s)", 10, (0.38, 0.42, 0.5))
    cover_note = (
        "Study explanations may include general AI knowledge; those parts are explicitly labeled and are not claims from the uploaded PDFs."
        if is_study_guide
        else "This dossier is synthesized only from the selected NEXUS AI document library. Sections with insufficient supporting evidence are explicitly marked."
    )
    note_y = line_y + 104
    for line in _wrap_text(cover_note, 10, PAGE_WIDTH - MARGIN * 2, _font_file(cover_note)):
        _insert_text(cover, (MARGIN, note_y), line, 10, (0.38, 0.42, 0.5))
        note_y += 15

    toc_entries: list[tuple[int, fitz.Rect, int]] = []
    toc_page = _new_content_page(document, document_kind)
    _insert_text(toc_page, (MARGIN, 91), "CONTENTS", 21, (0.08, 0.12, 0.22), bold=True)
    contents_note = (
        "Select an experiment title to jump to its study notes."
        if is_study_guide
        else "Select a section title to jump to its analysis."
    )
    _insert_text(toc_page, (MARGIN, 113), contents_note, 9, (0.38, 0.42, 0.5))
    toc_y = 150
    title_width = PAGE_WIDTH - MARGIN * 2 - 48
    for index, section in enumerate(report["sections"]):
        title = _safe_text(section["title"])
        lines = _wrap_text(title, 10, title_width, _font_file(title))
        line_height = 15
        row_height = max(25, len(lines) * line_height + 8)
        if toc_y + row_height > PAGE_HEIGHT - 72:
            toc_page = _new_content_page(document, document_kind)
            _insert_text(toc_page, (MARGIN, 91), "CONTENTS (CONTINUED)", 18, (0.08, 0.12, 0.22), bold=True)
            toc_y = 130
        start_y = toc_y
        for line in lines:
            _insert_text(toc_page, (MARGIN, toc_y), line, 10, (0.16, 0.2, 0.29))
            toc_y += line_height
        toc_page.draw_line(
            (MARGIN, toc_y + 1),
            (PAGE_WIDTH - MARGIN, toc_y + 1),
            color=(0.88, 0.89, 0.92),
            width=0.5,
        )
        toc_entries.append((
            toc_page.number,
            fitz.Rect(MARGIN, start_y - 10, PAGE_WIDTH - MARGIN, toc_y + 3),
            index,
        ))
        toc_y += 10

    section_pages: list[int] = []
    for section in report["sections"]:
        page = _new_content_page(document, document_kind)
        section_pages.append(page.number + 1)
        y = 88
        for line in _wrap_text(section["title"], 19, PAGE_WIDTH - MARGIN * 2, _font_file(section["title"], True)):
            _insert_text(page, (MARGIN, y), line, 19, (0.08, 0.12, 0.22), bold=True)
            y += 26
        y += 10

        if section["has_knowledge_gap"]:
            warning = "Evidence gap: the selected sources did not provide sufficient support for this section."
            _insert_text(page, (MARGIN, y), warning, 9, (0.65, 0.35, 0.08), bold=True)
            y += 20

        content = _safe_text(section["content"])
        blocks: list[tuple[str, str]] = []
        paragraph_lines: list[str] = []
        in_code_block = False
        for raw_line in content.splitlines():
            text = raw_line.strip()
            if text.startswith("```"):
                if paragraph_lines:
                    blocks.append(("paragraph", " ".join(paragraph_lines)))
                    paragraph_lines.clear()
                in_code_block = not in_code_block
                continue
            if in_code_block:
                blocks.append(("code", raw_line.rstrip()))
                continue
            if not text:
                if paragraph_lines:
                    blocks.append(("paragraph", " ".join(paragraph_lines)))
                    paragraph_lines.clear()
                continue
            heading = re.match(r"^#{1,3}\s+(.+)$", text)
            bullet = re.match(r"^[-*]\s+(.+)$", text)
            numbered = re.match(r"^(\d+[.)])\s+(.+)$", text)
            if heading or bullet or numbered:
                if paragraph_lines:
                    blocks.append(("paragraph", " ".join(paragraph_lines)))
                    paragraph_lines.clear()
                if heading:
                    blocks.append(("heading", heading.group(1).replace("**", "")))
                elif bullet:
                    blocks.append(("bullet", bullet.group(1).replace("**", "")))
                else:
                    blocks.append(("numbered", f"{numbered.group(1)} {numbered.group(2).replace('**', '')}"))
            else:
                paragraph_lines.append(text.replace("**", ""))
        if paragraph_lines:
            blocks.append(("paragraph", " ".join(paragraph_lines)))

        for block_type, paragraph in blocks:
            if block_type == "code":
                font_size = 8
                line_height = 12
                code_fontfile = _font_file(paragraph)
                lines = _wrap_code_line(
                    paragraph,
                    font_size,
                    PAGE_WIDTH - MARGIN * 2 - 20,
                    code_fontfile,
                )
                for line in lines:
                    if y + line_height > PAGE_HEIGHT - 72:
                        page = _new_content_page(document, document_kind)
                        y = 76
                    page.draw_rect(
                        fitz.Rect(MARGIN, y - 10, PAGE_WIDTH - MARGIN, y + 3),
                        color=(0.91, 0.93, 0.96),
                        fill=(0.95, 0.96, 0.98),
                        width=0.2,
                    )
                    fontname = f"Nexus-{Path(code_fontfile).stem}" if code_fontfile else "cour"
                    page.insert_text(
                        (MARGIN + 8, y),
                        line,
                        fontname=fontname,
                        fontfile=code_fontfile,
                        fontsize=font_size,
                        color=(0.12, 0.18, 0.27),
                    )
                    y += line_height
                continue
            font_size = 11 if block_type == "heading" else 9 if block_type == "bullet" else 10
            line_height = 17 if block_type == "heading" else 14
            prefix = "- " if block_type == "bullet" else ""
            indent = 14 if block_type in {"bullet", "numbered"} else 0
            bold = block_type == "heading"
            prefix_text = prefix
            available_width = PAGE_WIDTH - MARGIN * 2 - indent
            lines = _wrap_text(f"{prefix_text}{paragraph}", font_size, available_width, _font_file(paragraph, bold))
            for line in lines:
                if y + line_height > PAGE_HEIGHT - 72:
                    page = _new_content_page(document, document_kind)
                    y = 76
                _insert_text(
                    page,
                    (MARGIN + indent, y),
                    line,
                    font_size,
                    (0.16, 0.2, 0.29),
                    bold=bold,
                )
                y += line_height
            y += 9 if block_type == "heading" else 6

        citations = section["citations"]
        if citations:
            if y + 24 > PAGE_HEIGHT - 72:
                page = _new_content_page(document, document_kind)
                y = 76
            _insert_text(page, (MARGIN, y + 4), "SOURCE REFERENCES", 8, (0.31, 0.27, 0.9), bold=True)
            y += 20
            for citation in citations:
                reference = f"{citation['document_name']} - page {citation['page_number']}"
                fontfile = _font_file(reference)
                for line in _wrap_text(reference, 8, PAGE_WIDTH - MARGIN * 2, fontfile):
                    if y + 12 > PAGE_HEIGHT - 72:
                        page = _new_content_page(document, document_kind)
                        y = 76
                    _insert_text(page, (MARGIN, y), line, 8, (0.38, 0.42, 0.5))
                    y += 12

    unique_citations: dict[str, dict[str, Any]] = {}
    for section in report["sections"]:
        for citation in section["citations"]:
            unique_citations.setdefault(citation["source_id"], citation)

    page = _new_content_page(document, document_kind)
    appendix_page = page.number + 1
    _insert_text(page, (MARGIN, 88), "SOURCE APPENDIX", 21, (0.08, 0.12, 0.22), bold=True)
    y = 128
    if not unique_citations:
        _insert_text(page, (MARGIN, y), "No source references were available in the generated sections.", 10, (0.38, 0.42, 0.5))
    for citation in unique_citations.values():
        heading = f"{citation['document_name']}  /  Page {citation['page_number']}"
        excerpt = _safe_text(citation["excerpt"])
        for line in _wrap_text(heading, 10, PAGE_WIDTH - MARGIN * 2, _font_file(heading, True)):
            if y + 14 > PAGE_HEIGHT - 72:
                page = _new_content_page(document, document_kind)
                y = 76
            _insert_text(page, (MARGIN, y), line, 10, (0.16, 0.2, 0.29), bold=True)
            y += 14
        for line in _wrap_text(excerpt, 9, PAGE_WIDTH - MARGIN * 2 - 12, _font_file(excerpt)):
            if y + 13 > PAGE_HEIGHT - 72:
                page = _new_content_page(document, document_kind)
                y = 76
            _insert_text(page, (MARGIN + 12, y), line, 9, (0.38, 0.42, 0.5))
            y += 13
        y += 12

    for toc_page_number, link_rect, section_index in toc_entries:
        toc_page = document.load_page(toc_page_number)
        target_page = section_pages[section_index] - 1
        toc_page.insert_link({
            "kind": fitz.LINK_GOTO,
            "from": link_rect,
            "page": target_page,
            "to": fitz.Point(MARGIN, 60),
        })
        toc_page.insert_text(
            (PAGE_WIDTH - MARGIN - 30, link_rect.y0 + 10),
            str(target_page + 1),
            fontname="helv",
            fontsize=9,
            color=(0.31, 0.27, 0.9),
        )

    bookmarks = [[1, "Cover", 1]]
    bookmarks.append([1, "Contents", 2])
    bookmarks.extend(
        [1, section["title"], page_number]
        for section, page_number in zip(report["sections"], section_pages)
    )
    bookmarks.append([1, "Source Appendix", appendix_page])
    document.set_toc(bookmarks)

    page_count = len(document)
    for page_number, current_page in enumerate(document, start=1):
        current_page.draw_line((MARGIN, PAGE_HEIGHT - 48), (PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 48), color=(0.84, 0.86, 0.9), width=0.7)
        _insert_text(
            current_page,
            (PAGE_WIDTH - MARGIN - 55, PAGE_HEIGHT - 30),
            f"{page_number} / {page_count}",
            8,
            (0.42, 0.46, 0.54),
        )

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes
