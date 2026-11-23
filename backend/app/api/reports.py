import re
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import research_graph
from app.agents.state import AgentState
from app.auth import CurrentUser, get_current_user
from app.database.models import Document, DocumentChunk, ResearchReport
from app.database.session import get_db
from app.reports.pdf import render_research_report_pdf
from app.nlp.language import detect_language
from app.reports.study_guide import extract_experiments
from app.retrieval.grounded_answer import synthesizer
from app.retrieval.search import SearchResult

router = APIRouter(prefix="/api/reports", tags=["Research Reports"])
MAX_STUDY_GUIDE_EXPERIMENTS = 30
MAX_EXPERIMENT_CONTEXT_CHARACTERS = 48_000

SECTION_SPECS = [
    ("executive_summary", "Executive Summary", "Write an executive summary of the most decision-relevant evidence about"),
    ("strategic_context", "Strategic Context", "Explain the current context, background, and important changes related to"),
    ("key_findings", "Key Findings", "Synthesize the most important findings, measurable facts, and supporting evidence about"),
    ("opportunities", "Opportunities", "Identify opportunities, benefits, and potential areas for action supported by evidence about"),
    ("risks", "Risks and Considerations", "Describe material risks, constraints, uncertainties, and counter-evidence related to"),
    ("recommendations", "Recommendations and Next Steps", "Recommend practical next steps that follow from the evidence about"),
]


class ReportRequest(BaseModel):
    topic: str = Field(default="Complete experiment-by-experiment study guide", min_length=3, max_length=500)
    document_ids: list[str] = Field(..., min_length=1, max_length=20)
    report_type: Literal["executive_dossier", "study_guide"] = "executive_dossier"


class ReportCitation(BaseModel):
    source_id: str
    document_id: str
    document_name: str
    page_number: int
    excerpt: str
    locator_type: str = "page"
    locator_value: Optional[str] = None


class ReportSection(BaseModel):
    section_id: str
    title: str
    content: str
    citations: list[ReportCitation]
    confidence: str
    has_knowledge_gap: bool


class ReportResponse(BaseModel):
    id: str
    report_type: str
    title: str
    topic: str
    document_ids: list[str]
    document_names: list[str]
    sections: list[ReportSection]
    created_at: str


class ReportSummary(BaseModel):
    id: str
    report_type: str
    title: str
    topic: str
    document_names: list[str]
    section_count: int
    citation_count: int
    created_at: str


def _report_response(report: ResearchReport) -> ReportResponse:
    return ReportResponse(
        id=report.id,
        report_type=report.report_type,
        title=report.title,
        topic=report.topic,
        document_ids=report.document_ids,
        document_names=report.document_names,
        sections=report.sections,
        created_at=report.created_at.isoformat(),
    )


async def _owned_report(report_id: str, owner_id: str, db: AsyncSession) -> ResearchReport:
    result = await db.execute(
        select(ResearchReport).where(
            ResearchReport.id == report_id,
            ResearchReport.owner_id == owner_id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Research report not found")
    return report


def _canonical_excerpt(text: str) -> str:
    normalized = " ".join(text.split())
    first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return (first_sentence or normalized)[:280]


@router.post("", response_model=ReportResponse, status_code=201)
async def create_research_report(
    request: ReportRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    topic = request.topic.strip()
    if len(topic) < 3:
        raise HTTPException(status_code=422, detail="Research topic must contain at least three non-space characters.")

    document_ids = list(dict.fromkeys(request.document_ids))
    if not document_ids:
        raise HTTPException(status_code=422, detail="Select at least one ready document.")

    result = await db.execute(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.owner_id == user.id,
            Document.status == "ready",
        )
    )
    documents = result.scalars().all()
    if len(documents) != len(document_ids):
        raise HTTPException(status_code=404, detail="One or more selected documents are unavailable.")

    document_by_id = {document.id: document for document in documents}
    if request.report_type == "study_guide":
        if any(document_by_id[document_id].media_type != "pdf" for document_id in document_ids):
            raise HTTPException(
                status_code=422,
                detail="Experiment-by-experiment study guides currently require text-based PDF documents.",
            )
        return await _create_study_guide(
            topic=topic,
            document_ids=document_ids,
            document_by_id=document_by_id,
            owner_id=user.id,
            db=db,
        )

    response_language = detect_language(topic)
    sections: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for section_id, title, prompt_prefix in SECTION_SPECS:
        research_question = f"{prompt_prefix} {topic}. Use only the selected source documents."
        initial_state: AgentState = {
            "question": research_question,
            "response_language": response_language,
            "owner_id": user.id,
            "document_ids": document_ids,
            "is_valid": True,
            "intent": "summary",
            "retrieved_chunks": [],
            "retry_count": 0,
            "max_retries": 1,
            "rewritten_query": None,
            "evidence_sufficient": False,
            "answer": "",
            "citations": [],
            "claims": [],
            "confidence": "insufficient_evidence",
            "has_knowledge_gap": False,
            "activity_logs": [],
            "error": None,
        }
        state = await research_graph.ainvoke(initial_state)
        citations = state.get("citations", [])
        source_ids.update(
            citation.get("source_id", "")
            for citation in citations
            if citation.get("source_id")
        )
        sections.append({
            "section_id": section_id,
            "title": title,
            "content": str(state.get("answer", "")).strip(),
            "citations": [],
            "confidence": state.get("confidence", "insufficient_evidence"),
            "has_knowledge_gap": state.get("has_knowledge_gap", False),
            "_candidate_source_ids": [
                citation.get("source_id", "")
                for citation in citations
                if citation.get("source_id")
            ],
        })

    chunks_by_id: dict[str, DocumentChunk] = {}
    if source_ids:
        chunk_result = await db.execute(
            select(DocumentChunk).where(
                DocumentChunk.id.in_(source_ids),
                DocumentChunk.document_id.in_(document_ids),
            )
        )
        chunks_by_id = {chunk.id: chunk for chunk in chunk_result.scalars().all()}

    for section in sections:
        section_citations: list[dict[str, Any]] = []
        for source_id in dict.fromkeys(section.pop("_candidate_source_ids")):
            chunk = chunks_by_id.get(source_id)
            if chunk is None:
                continue
            source_document = document_by_id.get(chunk.document_id)
            if source_document is None:
                continue
            citation = {
                "source_id": chunk.id,
                "document_id": chunk.document_id,
                "document_name": source_document.filename,
                "page_number": chunk.page_number,
                "excerpt": _canonical_excerpt(chunk.chunk_text),
                "locator_type": chunk.locator_type,
                "locator_value": chunk.locator_value,
            }
            section_citations.append(citation)
        section["citations"] = section_citations
        if not section_citations:
            section["has_knowledge_gap"] = True
            section["confidence"] = "insufficient_evidence"
            section["content"] = (
                f"The selected documents did not provide sufficient verified evidence for "
                f"the {section['title'].lower()} on {topic}."
            )

    report = ResearchReport(
        id=str(uuid.uuid4()),
        owner_id=user.id,
        report_type="executive_dossier",
        title=f"Research Dossier: {topic[:230]}",
        topic=topic,
        document_ids=document_ids,
        document_names=[document_by_id[document_id].filename for document_id in document_ids],
        sections=sections,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return _report_response(report)


async def _create_study_guide(
    topic: str,
    document_ids: list[str],
    document_by_id: dict[str, Document],
    owner_id: str,
    db: AsyncSession,
) -> ReportResponse:
    chunk_result = await db.execute(
        select(DocumentChunk).where(
            DocumentChunk.document_id.in_(document_ids),
        )
    )
    document_order = {document_id: position for position, document_id in enumerate(document_ids)}
    stored_chunks = sorted(
        chunk_result.scalars().all(),
        key=lambda chunk: (
            document_order[chunk.document_id],
            chunk.page_number,
            chunk.chunk_index,
        ),
    )
    search_chunks = [
        SearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            title=document_by_id[chunk.document_id].filename,
            page_number=chunk.page_number,
            text=chunk.chunk_text,
            score=1.0,
            locator_type=chunk.locator_type,
            locator_value=chunk.locator_value,
        )
        for chunk in stored_chunks
    ]
    experiments = extract_experiments(search_chunks)
    if not experiments:
        raise HTTPException(
            status_code=422,
            detail=(
                "No numbered experiment sections were found in the selected PDFs. "
                "Use headings such as 'Experiment 1: Title' or sections with an AIM and "
                "an 'EX.NO: 1' marker, and upload text-based PDFs."
            ),
        )
    if len(experiments) > MAX_STUDY_GUIDE_EXPERIMENTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Found {len(experiments)} experiments; the maximum per guide is "
                f"{MAX_STUDY_GUIDE_EXPERIMENTS}. Split the source into smaller document sets."
            ),
        )

    response_language = detect_language(topic)
    sections: list[dict[str, Any]] = []
    for index, experiment in enumerate(experiments, start=1):
        source_chunks = experiment.chunks
        context_size = sum(len(chunk.text) for chunk in source_chunks)
        if context_size > MAX_EXPERIMENT_CONTEXT_CHARACTERS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Experiment {experiment.number} in '{experiment.document_name}' is too long "
                    "to explain reliably in one section. Split that experiment across smaller PDFs."
                ),
            )

        title = f"Experiment {experiment.number}"
        if experiment.title:
            title += f": {experiment.title}"
        if len(document_ids) > 1:
            title = f"{experiment.document_name} — {title}"
        prompt = (
            f"Prepare complete, clear exam-preparation study material for {title}. "
            f"Keep the experiment's original order and explain its source material. Learner's focus/output request: {topic}"
        )
        try:
            generated = await synthesizer.generate_answer(
                prompt,
                source_chunks,
                response_language=response_language,
                answer_style="study_guide",
            )
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        citations = [
            {
                "source_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_name": chunk.title,
                "page_number": chunk.page_number,
                "excerpt": _canonical_excerpt(chunk.text),
                "locator_type": chunk.locator_type,
                "locator_value": chunk.locator_value,
            }
            for chunk in source_chunks
        ]
        sections.append({
            "section_id": f"experiment_{index}",
            "title": title,
            "content": generated.answer,
            "citations": citations,
            "confidence": generated.confidence,
            "has_knowledge_gap": generated.has_knowledge_gap,
        })

    report = ResearchReport(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        report_type="study_guide",
        title=f"Study Guide: {topic[:240]}",
        topic=topic,
        document_ids=document_ids,
        document_names=[document_by_id[document_id].filename for document_id in document_ids],
        sections=sections,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return _report_response(report)


@router.get("", response_model=list[ReportSummary])
async def list_research_reports(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ResearchReport)
        .where(ResearchReport.owner_id == user.id)
        .order_by(ResearchReport.created_at.desc())
        .limit(50)
    )
    reports = result.scalars().all()
    return [
        ReportSummary(
            id=report.id,
            report_type=report.report_type,
            title=report.title,
            topic=report.topic,
            document_names=report.document_names,
            section_count=len(report.sections),
            citation_count=len({
                citation["source_id"]
                for section in report.sections
                for citation in section.get("citations", [])
            }),
            created_at=report.created_at.isoformat(),
        )
        for report in reports
    ]


@router.get("/{report_id}/pdf")
async def download_research_report_pdf(
    report_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _owned_report(report_id, user.id, db)
    pdf_bytes = render_research_report_pdf({
        "report_type": report.report_type,
        "title": report.title,
        "topic": report.topic,
        "document_names": report.document_names,
        "sections": report.sections,
        "created_at": report.created_at.isoformat(),
    })
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.report_type}-{report.id}.pdf"'},
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_research_report(
    report_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _owned_report(report_id, user.id, db)
    return _report_response(report)
