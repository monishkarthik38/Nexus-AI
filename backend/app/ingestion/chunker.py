import hashlib
import re
from dataclasses import dataclass
from typing import List
from app.ingestion.parser import PageData

@dataclass
class MediaChunk:
    chunk_id: str
    document_id: str
    page_number: int
    chunk_index: int
    title: str
    content_hash: str
    text: str
    locator_type: str
    locator_value: str

@dataclass
class TextChunk:
    chunk_id: str
    document_id: str
    page_number: int
    chunk_index: int
    title: str
    content_hash: str
    text: str
    locator_type: str = "page"
    locator_value: str | None = None

class TextChunker:
    def __init__(self, target_chunk_tokens: int = 700, overlap_tokens: int = 100):
        # 1 token ~ 4 characters
        self.target_chars = target_chunk_tokens * 4 # ~2800 chars
        self.overlap_chars = overlap_tokens * 4 # ~400 chars

    def chunk_document(self, document_id: str, document_title: str, pages: List[PageData]) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        chunk_counter = 0

        for page in pages:
            text = page.text.strip()
            if not text:
                continue

            # Split text by paragraphs
            paragraphs = re.split(r"\n{2,}", text)
            current_buffer = []
            current_len = 0

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                para_len = len(para)

                if current_len + para_len > self.target_chars and current_buffer:
                    chunk_str = "\n\n".join(current_buffer)
                    c_hash = hashlib.sha256(chunk_str.encode("utf-8")).hexdigest()
                    c_id = f"{document_id}_p{page.page_number}_c{chunk_counter}_{c_hash[:8]}"
                    chunks.append(TextChunk(
                        chunk_id=c_id,
                        document_id=document_id,
                        page_number=page.page_number,
                        chunk_index=chunk_counter,
                        title=document_title,
                        content_hash=c_hash,
                        text=chunk_str,
                        locator_type="page",
                        locator_value=str(page.page_number)
                    ))
                    chunk_counter += 1

                    overlap_buffer = []
                    overlap_len = 0
                    for prev_p in reversed(current_buffer):
                        if overlap_len + len(prev_p) <= self.overlap_chars:
                            overlap_buffer.insert(0, prev_p)
                            overlap_len += len(prev_p)
                        else:
                            break
                    current_buffer = overlap_buffer
                    current_len = overlap_len

                current_buffer.append(para)
                current_len += para_len

            if current_buffer:
                chunk_str = "\n\n".join(current_buffer)
                c_hash = hashlib.sha256(chunk_str.encode("utf-8")).hexdigest()
                c_id = f"{document_id}_p{page.page_number}_c{chunk_counter}_{c_hash[:8]}"
                chunks.append(TextChunk(
                    chunk_id=c_id,
                    document_id=document_id,
                    page_number=page.page_number,
                    chunk_index=chunk_counter,
                    title=document_title,
                    content_hash=c_hash,
                    text=chunk_str,
                    locator_type="page",
                    locator_value=str(page.page_number)
                ))
                chunk_counter += 1

        return chunks
