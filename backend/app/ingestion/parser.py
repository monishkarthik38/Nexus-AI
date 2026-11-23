import fitz # PyMuPDF
from dataclasses import dataclass
from typing import List

@dataclass
class PageData:
    page_number: int # 1-indexed
    text: str
    char_count: int
    word_count: int

@dataclass
class ParseResult:
    total_pages: int
    pages: List[PageData]
    total_characters: int
    is_empty: bool

class PDFParser:
    MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024 # 25 MB
    MAX_PAGES = 500

    @staticmethod
    def validate_content(content: bytes) -> None:
        if len(content) > PDFParser.MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size exceeds limit of {PDFParser.MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB")
        if not content.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF format: file content must start with %PDF- header")

    @staticmethod
    def extract_text(content: bytes) -> ParseResult:
        PDFParser.validate_content(content)

        doc = fitz.open(stream=content, filetype="pdf")
        total_pages = len(doc)

        if total_pages == 0:
            doc.close()
            raise ValueError("PDF has 0 pages.")

        if total_pages > PDFParser.MAX_PAGES:
            doc.close()
            raise ValueError(f"PDF exceeds maximum allowed page count ({PDFParser.MAX_PAGES})")

        pages_data: List[PageData] = []
        total_chars = 0

        for idx, page in enumerate(doc):
            text = page.get_text("text")
            # Normalize whitespace while preserving paragraphs
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            cleaned_text = "\n".join(lines)
            char_count = len(cleaned_text)
            word_count = len(cleaned_text.split())
            total_chars += char_count

            pages_data.append(PageData(
                page_number=idx + 1,
                text=cleaned_text,
                char_count=char_count,
                word_count=word_count
            ))

        doc.close()

        # Detection for scanned / image-only / empty PDFs
        is_empty = total_chars < 50
        return ParseResult(
            total_pages=total_pages,
            pages=pages_data,
            total_characters=total_chars,
            is_empty=is_empty
        )
