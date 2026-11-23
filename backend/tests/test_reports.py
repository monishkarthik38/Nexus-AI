import uuid

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api import reports as reports_api
from app.database.models import Document, DocumentChunk, ResearchReport
from app.database.session import AsyncSessionLocal, init_db
from app.main import app
from app.retrieval.grounded_answer import GroundedResponse
from app.reports.pdf import render_research_report_pdf
from app.reports.study_guide import extract_experiments
from app.retrieval.search import SearchResult


def test_extract_experiments_preserves_source_order_and_citations():
    chunks = [
        SearchResult(
            chunk_id="first",
            document_id="doc",
            title="lab.pdf",
            page_number=1,
            text="Lab manual\nExperiment No. 1: Ohm's Law\nAim: Measure resistance.",
            score=1,
        ),
        SearchResult(
            chunk_id="second",
            document_id="doc",
            title="lab.pdf",
            page_number=2,
            text="Procedure: Connect the circuit.\nExp - 2 - Find focal length\nAim: Measure the lens.",
            score=1,
        ),
    ]

    experiments = extract_experiments(chunks)

    assert [(experiment.number, experiment.title) for experiment in experiments] == [
        ("1", "Ohm's Law"),
        ("2", "Find focal length"),
    ]
    assert [chunk.chunk_id for chunk in experiments[0].chunks] == ["first", "second"]
    assert [chunk.chunk_id for chunk in experiments[1].chunks] == ["second"]


def test_extract_experiments_supports_end_markers_and_grouped_aim_sections():
    chunks = [
        SearchResult(
            chunk_id="experiment-one",
            document_id="manual",
            title="manual.pdf",
            page_number=6,
            text=(
                "AIM : Solve the XOR problem.\n"
                "ALGORITHM:\nTrain the MLP.\n"
                "EX.NO : 1\nDATE :\nSOLVING XOR PROBLEM"
            ),
            score=1,
        ),
        SearchResult(
            chunk_id="experiment-seven-a",
            document_id="manual",
            title="manual.pdf",
            page_number=21,
            text=(
                "i) INSTALLATION OF WEKA TOOL\nAIM : Install Weka.\nCheck the installation.\n"
                "EX.NO : 7\nDATE :\n"
                "i) INSTALLATION OF WEKA TOOL ii) CREATING NEW ARFF FILE "
                "iii) DATA PROCESSING TECHNIQUES iv) DATA CUBE CONSTRUCTION"
            ),
            score=1,
        ),
        SearchResult(
            chunk_id="experiment-seven-b",
            document_id="manual",
            title="manual.pdf",
            page_number=22,
            text=(
                "ii) CREATING NEW ARFF FILE\nAIM: Create an ARFF file.\n"
                "iii) DATA PROCESSING TECHNIQUES\nAIM: Process the dataset.\n"
                "iv) DATA CUBE CONSTRUCTION\nAIM: Construct a data cube.\n"
                "RESULT: The data cube was created."
            ),
            score=1,
        ),
        SearchResult(
            chunk_id="experiment-eight",
            document_id="manual",
            title="manual.pdf",
            page_number=24,
            text=(
                "AIM: Implement Apriori.\nFind frequent itemsets.\n"
                "EX.NO : 8\nDATE :\nIMPLEMENTATION OF APRIORI ALGORITHM"
            ),
            score=1,
        ),
    ]

    experiments = extract_experiments(chunks)

    assert [(experiment.number, experiment.title) for experiment in experiments] == [
        ("1", "SOLVING XOR PROBLEM"),
        (
            "7",
            "i) INSTALLATION OF WEKA TOOL ii) CREATING NEW ARFF FILE "
            "iii) DATA PROCESSING TECHNIQUES iv) DATA CUBE CONSTRUCTION",
        ),
        ("8", "IMPLEMENTATION OF APRIORI ALGORITHM"),
    ]
    assert [chunk.chunk_id for chunk in experiments[1].chunks] == [
        "experiment-seven-a",
        "experiment-seven-b",
    ]
    assert "iv) DATA CUBE CONSTRUCTION" in experiments[1].chunks[-1].text
    assert "AIM: Implement Apriori." in experiments[2].chunks[0].text


@pytest.mark.asyncio
async def test_report_generation_is_grounded_saved_and_downloadable(monkeypatch):
    await init_db()
    user_id = f"report_user_{uuid.uuid4().hex}"
    document_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    excerpt = "The strategy proposes a staged expansion and quarterly risk review."

    async with AsyncSessionLocal() as db:
        db.add(Document(
            id=document_id,
            owner_id=user_id,
            filename="strategy.pdf",
            storage_path="unused-for-report-test.pdf",
            status="ready",
        ))
        db.add(DocumentChunk(
            id=chunk_id,
            document_id=document_id,
            page_number=3,
            locator_type="page",
            locator_value="3",
            chunk_index=0,
            content_hash="test-hash",
            chunk_text=excerpt,
        ))
        await db.commit()

    class FakeResearchGraph:
        async def ainvoke(self, state):
            if state["question"].startswith("Identify opportunities"):
                return {
                    "answer": "No supported opportunities were found.",
                    "citations": [],
                    "confidence": "insufficient_evidence",
                    "has_knowledge_gap": True,
                }
            return {
                "answer": f"Evidence-based analysis for {state['question']}.",
                "citations": [{
                    "source_id": chunk_id,
                    "document_name": "untrusted-name.pdf",
                    "page_number": 999,
                    "excerpt": "This fabricated quote must not be used.",
                }],
                "confidence": "high",
                "has_knowledge_gap": False,
            }

    monkeypatch.setattr(reports_api, "research_graph", FakeResearchGraph())

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Dev-User": user_id},
        ) as client:
            response = await client.post("/api/reports", json={
                "topic": "Expansion strategy",
                "document_ids": [document_id],
            })
            assert response.status_code == 201, response.text
            report = response.json()
            report_id = report["id"]

            assert len(report["sections"]) == 6
            unsupported_section = next(
                section for section in report["sections"]
                if section["section_id"] == "opportunities"
            )
            assert unsupported_section["citations"] == []
            assert unsupported_section["has_knowledge_gap"] is True
            assert "did not provide sufficient verified evidence" in unsupported_section["content"]
            cited_section = next(section for section in report["sections"] if section["citations"])
            first_citation = cited_section["citations"][0]
            assert first_citation["document_name"] == "strategy.pdf"
            assert first_citation["page_number"] == 3
            assert first_citation["excerpt"] == excerpt

            listing = await client.get("/api/reports")
            assert listing.status_code == 200
            assert listing.json()[0]["id"] == report_id
            assert listing.json()[0]["citation_count"] == 1

            detail = await client.get(f"/api/reports/{report_id}")
            assert detail.status_code == 200
            assert detail.json()["topic"] == "Expansion strategy"

            pdf_response = await client.get(f"/api/reports/{report_id}/pdf")
            assert pdf_response.status_code == 200
            assert pdf_response.headers["content-type"] == "application/pdf"
            pdf_document = fitz.open(stream=pdf_response.content, filetype="pdf")
            assert pdf_document.page_count >= 8
            assert "SOURCE APPENDIX" in pdf_document[-1].get_text().replace("\xa0", " ")
            pdf_document.close()

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-Dev-User": f"other_{user_id}"},
            ) as other_user:
                assert (await other_user.get(f"/api/reports/{report_id}")).status_code == 404
                assert (await other_user.get(f"/api/reports/{report_id}/pdf")).status_code == 404
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ResearchReport).where(ResearchReport.owner_id == user_id))
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            await db.execute(delete(Document).where(Document.id == document_id))
            await db.commit()


@pytest.mark.asyncio
async def test_report_rejects_unowned_or_unready_documents():
    await init_db()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": f"report_user_{uuid.uuid4().hex}"},
    ) as client:
        response = await client.post("/api/reports", json={
            "topic": "A valid research question",
            "document_ids": [str(uuid.uuid4())],
        })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_study_guide_explains_every_experiment_and_exports_pdf(monkeypatch):
    await init_db()
    user_id = f"study_user_{uuid.uuid4().hex}"
    document_id = str(uuid.uuid4())
    first_chunk_id = f"{document_id}_first"
    second_chunk_id = f"{document_id}_second"

    async with AsyncSessionLocal() as db:
        db.add(Document(
            id=document_id,
            owner_id=user_id,
            filename="physics_lab.pdf",
            storage_path="unused-study-guide.pdf",
            status="ready",
            media_type="pdf",
        ))
        db.add_all([
            DocumentChunk(
                id=first_chunk_id,
                document_id=document_id,
                page_number=1,
                chunk_index=0,
                content_hash="first-hash",
                chunk_text="Experiment 1: Ohm's Law\nAim: Measure resistance.\nProcedure: Connect the circuit.",
            ),
            DocumentChunk(
                id=second_chunk_id,
                document_id=document_id,
                page_number=2,
                chunk_index=1,
                content_hash="second-hash",
                chunk_text="Experiment 2: Focal Length\nAim: Find the focal length of a convex lens.",
            ),
        ])
        await db.commit()

    calls = []

    async def fake_generate_answer(question, chunks, response_language=None, answer_style="concise"):
        calls.append((question, [chunk.chunk_id for chunk in chunks], response_language, answer_style))
        return GroundedResponse(
            answer=(
                "## What you will learn\nUnderstand the experiment step by step.\n\n"
                "## Program walkthrough\n```python\nprint('hello')\n```\n\n"
                "## Additional explanation (AI knowledge; not stated in the PDF)\n"
                "Review the underlying concept before the exam."
            ),
            confidence="high",
            has_knowledge_gap=False,
        )

    monkeypatch.setattr(reports_api.synthesizer, "generate_answer", fake_generate_answer)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Dev-User": user_id},
        ) as client:
            response = await client.post("/api/reports", json={
                "report_type": "study_guide",
                "topic": "Write clear English study notes",
                "document_ids": [document_id],
            })
            assert response.status_code == 201, response.text
            guide = response.json()

            assert guide["report_type"] == "study_guide"
            assert len(guide["sections"]) == 2
            assert guide["sections"][0]["title"] == "Experiment 1: Ohm's Law"
            assert guide["sections"][1]["title"] == "Experiment 2: Focal Length"
            assert guide["sections"][0]["citations"][0]["page_number"] == 1
            assert guide["sections"][1]["citations"][0]["page_number"] == 2
            assert "Additional explanation" in guide["sections"][0]["content"]
            assert all(call[3] == "study_guide" for call in calls)
            assert all(call[2] == "en" for call in calls)
            assert len(calls) == 2

            pdf_response = await client.get(f"/api/reports/{guide['id']}/pdf")
            assert pdf_response.status_code == 200
            assert "study_guide-" in pdf_response.headers["content-disposition"]
            pdf = fitz.open(stream=pdf_response.content, filetype="pdf")
            text = "\n".join(page.get_text() for page in pdf).replace("\xa0", " ")
            assert "STUDENT STUDY GUIDE" in text
            assert "CONTENTS" in pdf[1].get_text()
            assert "Experiment 1: Ohm's Law" in text
            assert "print('hello')" in text
            assert "Additional explanation" in text
            assert "SOURCE APPENDIX" in text
            toc_links = pdf[1].get_links()
            assert len(toc_links) == 2
            assert [link["page"] for link in toc_links] == [2, 3]
            assert any(bookmark[1] == "Experiment 1: Ohm's Law" for bookmark in pdf.get_toc())
            pdf.close()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ResearchReport).where(ResearchReport.owner_id == user_id))
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            await db.execute(delete(Document).where(Document.id == document_id))
            await db.commit()


def test_study_guide_pdf_keeps_devanagari_text():
    hindi_heading = "\u092e\u0941\u0916\u094d\u092f \u0938\u093f\u0926\u094d\u0927\u093e\u0902\u0924"
    hindi_text = "\u092f\u0939 \u092a\u094d\u0930\u092f\u094b\u0917 \u092a\u094d\u0930\u0915\u093e\u0936 \u0915\u0940 \u092b\u094b\u0915\u0932 \u0926\u0942\u0930\u0940 \u092e\u093e\u092a\u0924\u093e \u0939\u0948\u0964"
    content = render_research_report_pdf({
        "report_type": "study_guide",
        "title": f"Study Guide: {hindi_heading}",
        "topic": hindi_heading,
        "document_names": ["physics.pdf"],
        "created_at": "2026-11-01",
        "sections": [{
            "title": f"Experiment 1: {hindi_heading}",
            "content": f"## {hindi_heading}\n{hindi_text}",
            "citations": [],
            "has_knowledge_gap": False,
        }],
    })
    pdf = fitz.open(stream=content, filetype="pdf")
    extracted_text = "\n".join(page.get_text() for page in pdf)
    pdf.close()

    normalized_text = extracted_text.replace("\xa0", " ")
    assert hindi_heading in normalized_text
    assert hindi_text in normalized_text


@pytest.mark.asyncio
async def test_study_guide_requires_detectable_experiment_headings():
    await init_db()
    user_id = f"study_user_{uuid.uuid4().hex}"
    document_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as db:
        db.add(Document(
            id=document_id,
            owner_id=user_id,
            filename="questions.pdf",
            storage_path="unused-question-bank.pdf",
            status="ready",
            media_type="pdf",
        ))
        db.add(DocumentChunk(
            id=f"{document_id}_chunk",
            document_id=document_id,
            page_number=1,
            chunk_index=0,
            content_hash="question-hash",
            chunk_text="These are practice questions without experiment headings.",
        ))
        await db.commit()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Dev-User": user_id},
        ) as client:
            response = await client.post("/api/reports", json={
                "report_type": "study_guide",
                "document_ids": [document_id],
            })
        assert response.status_code == 422
        assert "No numbered experiment sections were found" in response.json()["detail"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            await db.execute(delete(Document).where(Document.id == document_id))
            await db.commit()
