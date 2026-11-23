import io
import json
import fitz # PyMuPDF
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database.models import DocumentChunk
from app.database.session import AsyncSessionLocal, init_db
from app.ingestion.worker import IngestionWorker
from sqlalchemy import select

def create_sample_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

@pytest.mark.asyncio
async def test_langgraph_agent_and_knowledge_gap():
    await init_db()

    pdf_content = (
        "Nexus AI architecture documentation. "
        "The system incorporates LangGraph for stateful multi-step agent execution. "
        "Storage is managed by Qdrant and relational metadata is tracked with PostgreSQL or SQLite."
    )
    pdf_bytes = create_sample_pdf(pdf_content)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "test_agent_user"}) as client:
        # 1. Upload document
        files = {"file": ("architecture_spec.pdf", pdf_bytes, "application/pdf")}
        data = {}
        upload_resp = await client.post("/api/documents", files=files, data=data)
        assert upload_resp.status_code == 201
        upload_data = upload_resp.json()
        doc_id = upload_data["id"]
        await IngestionWorker(AsyncSessionLocal, worker_id="agent-test-worker").process_one(
            upload_data["job_id"]
        )

        async with AsyncSessionLocal() as db:
            chunk_result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            source_chunk = chunk_result.scalars().first()
        assert source_chunk is not None
        annotation_resp = await client.post("/api/evidence-annotations", json={
            "source_id": source_chunk.id,
            "claim": "LangGraph is used for stateful multi-step agent execution.",
            "label": "supports",
        })
        assert annotation_resp.status_code == 200
        assert annotation_resp.json()["label"] == "supports"
        unauthorized_annotation = await client.post("/api/evidence-annotations", json={
            "source_id": source_chunk.id,
            "claim": "This should not access another owner's passage.",
            "label": "insufficient",
        }, headers={"X-Dev-User": "different_owner"})
        assert unauthorized_annotation.status_code == 404

        # A second labeled source document makes a document-disjoint export possible.
        second_upload = await client.post("/api/documents", files={
            "file": ("protocol_notes.pdf", create_sample_pdf("The protocol requires three reviewers before release."), "application/pdf")
        }, data={})
        assert second_upload.status_code == 201
        second_upload_data = second_upload.json()
        second_doc_id = second_upload_data["id"]
        await IngestionWorker(AsyncSessionLocal, worker_id="agent-test-worker").process_one(
            second_upload_data["job_id"]
        )
        async with AsyncSessionLocal() as db:
            second_chunk_result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == second_doc_id))
            second_chunk = second_chunk_result.scalars().first()
        assert second_chunk is not None
        second_label = await client.post("/api/evidence-annotations", json={
            "source_id": second_chunk.id,
            "claim": "Three reviewers are needed for release.",
            "label": "supports",
        })
        assert second_label.status_code == 200

        summary = await client.get("/api/evidence-annotations/summary")
        assert summary.status_code == 200
        assert summary.json()["total"] == 2
        assert len(summary.json()["documents"]) == 2

        exported = await client.post("/api/evidence-annotations/export", json={
            "test_document_ids": [second_doc_id],
        })
        assert exported.status_code == 200
        export_data = exported.json()
        assert export_data["train_documents"] == 1
        assert export_data["test_documents"] == 1
        assert json.loads(export_data["train_jsonl"].strip())["source_document_id"] == doc_id
        assert json.loads(export_data["test_jsonl"].strip())["source_document_id"] == second_doc_id

        # 2. Test successful grounded answer with activity logs
        query = "What framework is used for stateful multi-step agent execution?"
        chat_resp = await client.post("/api/chat", json={
            "query": query,
            "document_ids": [doc_id]
        })
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()

        assert "langgraph" in chat_data["answer"].lower()
        assert chat_data["response_language"] == "en"
        assert len(chat_data["citations"]) >= 1
        assert len(chat_data["claims"]) >= 1
        citation_ids = {citation["source_id"] for citation in chat_data["citations"]}
        assert all(set(claim["source_ids"]).issubset(citation_ids) for claim in chat_data["claims"])
        assert chat_data["citations"][0]["document_name"] == "architecture_spec.pdf"
        assert len(chat_data["activity_logs"]) >= 3
        assert any("validating" in log.lower() for log in chat_data["activity_logs"])
        assert any("searching" in log.lower() for log in chat_data["activity_logs"])

        # 3. Test unanswerable question / knowledge gap
        unanswerable_q = "What is the secret recipe for quantum cold brew coffee?"
        gap_resp = await client.post("/api/chat", json={
            "query": unanswerable_q,
            "document_ids": [doc_id]
        })
        assert gap_resp.status_code == 200
        gap_data = gap_resp.json()
        assert gap_data["has_knowledge_gap"] is True or "not contain" in gap_data["answer"].lower()
        if gap_data["has_knowledge_gap"]:
            assert gap_data["claims"] == []

        # 4. Clean up
        await client.delete(f"/api/documents/{doc_id}")
        await client.delete(f"/api/documents/{second_doc_id}")
