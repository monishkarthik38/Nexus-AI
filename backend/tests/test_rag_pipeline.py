import io
import fitz # PyMuPDF
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.database.models import DocumentChunk
from app.main import app
from app.database.session import AsyncSessionLocal, init_db
from app.ingestion.worker import IngestionWorker

def create_sample_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

@pytest.mark.asyncio
async def test_full_rag_vertical_slice():
    # Ensure database tables exist
    await init_db()

    # 1. Create a synthetic test PDF
    pdf_content = (
        "Project NEXUS AI was founded in 2026 to revolutionize agentic document research. "
        "The system utilizes Qdrant for vector storage and implements LangGraph for bounded agent workflows. "
        "Every factual claim is strictly supported by source citations with page numbers."
    )
    pdf_bytes = create_sample_pdf(pdf_content)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "test_researcher"}) as client:
        # 2. Test upload endpoint
        files = {
            "file": ("nexus_intro.pdf", pdf_bytes, "application/pdf")
        }
        data = {}
        upload_resp = await client.post("/api/documents", files=files, data=data)
        assert upload_resp.status_code == 201, upload_resp.text
        doc_data = upload_resp.json()
        assert doc_data["status"] == "processing"
        assert doc_data["job_id"]
        await IngestionWorker(AsyncSessionLocal, worker_id="rag-test-worker").process_one(
            doc_data["job_id"]
        )
        doc_data = (await client.get(f"/api/documents/{doc_data['id']}")).json()
        assert doc_data["status"] == "ready"
        assert doc_data["filename"] == "nexus_intro.pdf"
        assert doc_data["page_count"] == 1
        async with AsyncSessionLocal() as db:
            chunks = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == doc_data["id"])
            )
            assert len(chunks.scalars().all()) >= 1
        doc_id = doc_data["id"]

        # 3. Test list documents
        list_resp = await client.get("/api/documents")
        assert list_resp.status_code == 200
        docs_list = list_resp.json()
        assert any(d["id"] == doc_id for d in docs_list)

        # 4. Test question answering (grounded RAG)
        chat_payload = {
            "query": "When was Project NEXUS AI founded and what vector storage does it use?",
            "document_ids": [doc_id]
        }
        chat_resp = await client.post("/api/chat", json=chat_payload)
        assert chat_resp.status_code == 200, chat_resp.text
        chat_data = chat_resp.json()

        assert "2026" in chat_data["answer"].lower() or "nexus" in chat_data["answer"].lower()
        assert len(chat_data["citations"]) >= 1
        citation = chat_data["citations"][0]
        assert citation["page_number"] == 1
        assert citation["document_name"] == "nexus_intro.pdf"
        assert len(citation["excerpt"]) > 0

        # 5. Test conversation history
        conv_id = chat_data["conversation_id"]
        history_resp = await client.get(f"/api/chat/{conv_id}")
        assert history_resp.status_code == 200
        hist_data = history_resp.json()
        assert len(hist_data["messages"]) == 2 # 1 user, 1 assistant

        # 6. Test delete document
        del_resp = await client.delete(f"/api/documents/{doc_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "success"

        # Verify deletion
        list_after_del = await client.get("/api/documents")
        assert not any(d["id"] == doc_id for d in list_after_del.json())
