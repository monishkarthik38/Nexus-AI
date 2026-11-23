import re
from dataclasses import dataclass, field

from app.retrieval.search import SearchResult

EXPERIMENT_HEADER = re.compile(
    r"^\s*(?:experiment|exp\.?|expt\.?)\s*"
    r"(?:no\.?\s*)?[-:#]?\s*(\d{1,3}|[ivxlcdm]+)\b"
    r"(?:\s*[:.)\-–—]\s*|\s+)?(.*)$",
    re.IGNORECASE,
)
EXPERIMENT_END_MARKER = re.compile(
    r"^\s*ex\s*\.?\s*no\s*\.?\s*[:#-]?\s*(\d{1,3})\b",
    re.IGNORECASE,
)
AIM_HEADER = re.compile(r"^\s*aim\s*:", re.IGNORECASE)
DATE_HEADER = re.compile(r"^\s*date\b\s*:?\s*$", re.IGNORECASE)
AIM_SUBSECTION = re.compile(r"^\s*(iv|iii|ii|i)\s*[).]\s*", re.IGNORECASE)
AIM_SUBSECTION_MENTION = re.compile(r"(?<!\w)(iv|iii|ii|i)\s*[).]", re.IGNORECASE)
ROMAN_SECTION_NUMBERS = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


@dataclass
class Experiment:
    number: str
    title: str
    document_id: str
    document_name: str
    _text_by_chunk: dict[str, list[str]] = field(default_factory=dict)
    _chunk_by_id: dict[str, SearchResult] = field(default_factory=dict)

    def add_text(self, chunk: SearchResult, text: str) -> None:
        self._chunk_by_id[chunk.chunk_id] = chunk
        self._text_by_chunk.setdefault(chunk.chunk_id, []).append(text)

    @property
    def chunks(self) -> list[SearchResult]:
        return [
            SearchResult(
                chunk_id=chunk_id,
                document_id=self._chunk_by_id[chunk_id].document_id,
                title=self._chunk_by_id[chunk_id].title,
                page_number=self._chunk_by_id[chunk_id].page_number,
                text="\n".join(self._text_by_chunk[chunk_id]),
                score=self._chunk_by_id[chunk_id].score,
                locator_type=self._chunk_by_id[chunk_id].locator_type,
                locator_value=self._chunk_by_id[chunk_id].locator_value,
            )
            for chunk_id in self._text_by_chunk
        ]


def extract_experiments(chunks: list[SearchResult]) -> list[Experiment]:
    """Split ordered PDF chunks at explicit experiment headings."""
    chunks_by_document: dict[str, list[SearchResult]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

    experiments: list[Experiment] = []
    for document_chunks in chunks_by_document.values():
        document_experiments = _extract_heading_started_experiments(document_chunks)
        if not document_experiments:
            document_experiments = _extract_end_marked_experiments(document_chunks)
        experiments.extend(document_experiments)
    return experiments


def _extract_heading_started_experiments(chunks: list[SearchResult]) -> list[Experiment]:
    experiments: list[Experiment] = []
    current: Experiment | None = None

    for chunk in chunks:
        for line in chunk.text.splitlines():
            match = EXPERIMENT_HEADER.match(line)
            if match:
                number = match.group(1).upper()
                title = match.group(2).strip(" .:-–—")
                if (
                    current
                    and current.document_id == chunk.document_id
                    and current.number == number
                ):
                    if title and not current.title:
                        current.title = title
                else:
                    current = Experiment(
                        number=number,
                        title=title,
                        document_id=chunk.document_id,
                        document_name=chunk.title,
                    )
                    experiments.append(current)
                current.add_text(chunk, line)
            elif current and current.document_id == chunk.document_id:
                current.add_text(chunk, line)

    return [experiment for experiment in experiments if experiment.chunks]


def _extract_end_marked_experiments(chunks: list[SearchResult]) -> list[Experiment]:
    lines = [
        (chunk, line)
        for chunk in chunks
        for line in chunk.text.splitlines()
    ]
    experiments: list[Experiment] = []
    current: Experiment | None = None
    grouped_final_section: int | None = None
    final_section_heading_seen = False
    final_section_aim_seen = False
    after_marker_metadata = False

    for index, (chunk, line) in enumerate(lines):
        aim_match = AIM_HEADER.match(line)
        if current and after_marker_metadata:
            if aim_match:
                after_marker_metadata = False
            else:
                continue

        if (
            current
            and grouped_final_section is not None
            and aim_match
            and final_section_heading_seen
            and final_section_aim_seen
        ):
            experiments.append(current)
            current = None
            grouped_final_section = None
            final_section_heading_seen = False
            final_section_aim_seen = False

        if current is None:
            if aim_match:
                current = Experiment(
                    number="",
                    title="",
                    document_id=chunk.document_id,
                    document_name=chunk.title,
                )
            else:
                continue
        elif aim_match and grouped_final_section is not None and final_section_heading_seen:
            final_section_aim_seen = True

        marker = EXPERIMENT_END_MARKER.match(line)
        if marker and current.document_id == chunk.document_id:
            current.number = marker.group(1)
            current.add_text(chunk, line)
            marker_title_lines = []
            for following_chunk, following_line in lines[index + 1:]:
                if following_chunk.page_number != chunk.page_number:
                    break
                if AIM_HEADER.match(following_line):
                    break
                if following_line.strip() and not DATE_HEADER.match(following_line):
                    marker_title_lines.append(following_line.strip())
            current.title = " ".join(" ".join(marker_title_lines).split()).strip(" .:-–—")[:300]
            numbered_subsections = {
                ROMAN_SECTION_NUMBERS[match.group(1).lower()]
                for match in AIM_SUBSECTION_MENTION.finditer(" ".join(marker_title_lines))
            }
            if len(numbered_subsections) > 1:
                grouped_final_section = max(numbered_subsections)
                after_marker_metadata = True
            else:
                experiments.append(current)
                current = None
        elif current.document_id == chunk.document_id:
            subsection = AIM_SUBSECTION.match(line)
            if (
                subsection
                and grouped_final_section is not None
                and ROMAN_SECTION_NUMBERS[subsection.group(1).lower()] == grouped_final_section
            ):
                final_section_heading_seen = True
            current.add_text(chunk, line)
        else:
            current = None

    if current and grouped_final_section is not None and final_section_aim_seen:
        experiments.append(current)
    return experiments
