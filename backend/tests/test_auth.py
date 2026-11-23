import uuid

import fitz
import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api import chat as chat_api, evaluation as evaluation_api
from app.auth import _verify_supabase_token
from app.config import settings
from app.database.models import (
    Conversation,
    Document,
    DocumentChunk,
    EvaluationRun,
    EvidenceAnnotation,
    Message,
    ResearchReport,
)
from app.database.session import AsyncSessionLocal, init_db
from app.main import app


def make_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "aud": "authenticated",
            "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
            "exp": 4_000_000_000,
            "email": f"{user_id}@example.test",
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_verifies_signed_supabase_access_token(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://nexus-test.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "unit-test-only-jwt-secret-with-sufficient-length")

    principal = await _verify_supabase_token(make_token("verified-user"))

    assert principal.id == "verified-user"
    assert principal.email == "verified-user@example.test"


@pytest.mark.asyncio
async def test_supabase_auth_fails_with_service_error_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")

    with pytest.raises(HTTPException) as error:
        await _verify_supabase_token("not-a-token")

    assert error.value.status_code == 503


def make_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 72), "Tenant scoped authenticated test document with enough searchable source text.")
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.asyncio
async def test_supabase_mode_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://nexus-test.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "unit-test-only-jwt-secret-with-sufficient-length")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/api/documents")
        invalid = await client.get("/api/documents", headers={"Authorization": "Bearer not-a-jwt"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


@pytest.mark.asyncio
async def test_jwt_identity_scopes_documents_and_ignores_spoofed_owner(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://nexus-test.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "unit-test-only-jwt-secret-with-sufficient-length")

    alice_headers = {"Authorization": f"Bearer {make_token('jwt-alice')}", "X-Dev-User": "jwt-bob"}
    bob_headers = {"Authorization": f"Bearer {make_token('jwt-bob')}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"file": ("private.pdf", make_pdf(), "application/pdf")},
            data={"owner_id": "jwt-bob"},
            headers=alice_headers,
        )
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]

        alice_docs = await client.get("/api/documents", headers=alice_headers)
        bob_docs = await client.get("/api/documents", headers=bob_headers)
        bob_cannot_read = await client.get(f"/api/documents/{document_id}", headers=bob_headers)
        bob_cannot_delete = await client.delete(f"/api/documents/{document_id}", headers=bob_headers)
        alice_can_read = await client.get(f"/api/documents/{document_id}", headers=alice_headers)

    assert any(item["id"] == document_id for item in alice_docs.json())
    assert not any(item["id"] == document_id for item in bob_docs.json())
    assert alice_can_read.status_code == 200
    assert bob_cannot_read.status_code == 404
    assert bob_cannot_delete.status_code == 404
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete(f"/api/documents/{document_id}", headers=alice_headers)


@pytest.mark.asyncio
async def test_conversation_history_and_deletion_are_owner_scoped(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "development")
    await init_db()
    conversation_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Conversation(
            id=conversation_id,
            owner_id="conversation-owner",
            title="Private research thread",
        ))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_headers = {"X-Dev-User": "conversation-owner"}
        other_headers = {"X-Dev-User": "other-owner"}

        owner_history = await client.get(
            f"/api/chat/{conversation_id}",
            headers=owner_headers,
        )
        other_history = await client.get(
            f"/api/chat/{conversation_id}",
            headers=other_headers,
        )
        other_delete = await client.delete(
            f"/api/chat/{conversation_id}",
            headers=other_headers,
        )
        still_available = await client.get(
            f"/api/chat/{conversation_id}",
            headers=owner_headers,
        )
        owner_delete = await client.delete(
            f"/api/chat/{conversation_id}",
            headers=owner_headers,
        )

    assert owner_history.status_code == 200
    assert owner_history.json()["conversation_id"] == conversation_id
    assert other_history.status_code == 404
    assert other_delete.status_code == 404
    assert still_available.status_code == 200
    assert owner_delete.status_code == 200


@pytest.mark.asyncio
async def test_chat_rejects_foreign_document_before_creating_conversation(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "development")
    await init_db()
    foreign_document_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Document(
            id=foreign_document_id,
            owner_id="another-tenant",
            filename="private.pdf",
            storage_path="unused-for-auth-test.pdf",
            status="ready",
        ))
        await db.commit()

    class FailIfInvokedGraph:
        async def ainvoke(self, _state):
            raise AssertionError("Research graph must not run for a foreign document")

    monkeypatch.setattr(chat_api, "research_graph", FailIfInvokedGraph())
    headers = {"X-Dev-User": "chat-scope-owner"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/chat", headers=headers, json={
                "query": "Summarize this document",
                "document_ids": [foreign_document_id],
            })
            conversations = await client.get("/api/chat/conversations", headers=headers)

        assert response.status_code == 404
        assert response.json()["detail"] == "One or more selected documents are unavailable."
        assert conversations.status_code == 200
        assert conversations.json() == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Document).where(Document.id == foreign_document_id))
            await db.commit()


@pytest.mark.asyncio
async def test_evaluation_rejects_foreign_document_before_running(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "development")
    await init_db()
    foreign_document_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Document(
            id=foreign_document_id,
            owner_id="another-evaluation-tenant",
            filename="private.pdf",
            storage_path="unused-for-auth-test.pdf",
            status="ready",
        ))
        await db.commit()

    def fail_if_instantiated(*_args, **_kwargs):
        raise AssertionError("Evaluation must not run for a foreign document")

    monkeypatch.setattr(evaluation_api, "EvaluationRunner", fail_if_instantiated)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/evaluation/run",
                headers={"X-Dev-User": "evaluation-scope-owner"},
                json={"document_ids": [foreign_document_id]},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "One or more selected documents are unavailable."
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Document).where(Document.id == foreign_document_id))
            await db.commit()


@pytest.mark.asyncio
async def test_resource_lists_and_reads_are_scoped_across_tenants(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "development")
    await init_db()
    tenant_a = f"tenant_a_{uuid.uuid4().hex}"
    tenant_b = f"tenant_b_{uuid.uuid4().hex}"
    document_a_id, document_b_id = str(uuid.uuid4()), str(uuid.uuid4())
    chunk_a_id, chunk_b_id = str(uuid.uuid4()), str(uuid.uuid4())
    report_a_id, report_b_id = str(uuid.uuid4()), str(uuid.uuid4())
    conversation_a_id, conversation_b_id = str(uuid.uuid4()), str(uuid.uuid4())
    run_a_id, run_b_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add_all([
            Document(
                id=document_a_id, owner_id=tenant_a, filename="tenant-a-private.pdf",
                storage_path="unused-tenant-a.pdf", status="ready",
            ),
            Document(
                id=document_b_id, owner_id=tenant_b, filename="tenant-b-private.pdf",
                storage_path="unused-tenant-b.pdf", status="ready",
            ),
            DocumentChunk(
                id=chunk_a_id, document_id=document_a_id, page_number=1,
                chunk_index=0, content_hash="tenant-a-hash", chunk_text="tenant A private passage",
            ),
            DocumentChunk(
                id=chunk_b_id, document_id=document_b_id, page_number=1,
                chunk_index=0, content_hash="tenant-b-hash", chunk_text="tenant B private passage",
            ),
            ResearchReport(
                id=report_a_id, owner_id=tenant_a, report_type="executive_dossier",
                title="Tenant A private report", topic="private A",
                document_ids=[document_a_id], document_names=["tenant-a-private.pdf"],
                sections=[{"section_id": "findings", "title": "Findings", "content": "private A"}],
            ),
            ResearchReport(
                id=report_b_id, owner_id=tenant_b, report_type="executive_dossier",
                title="Tenant B report", topic="private B",
                document_ids=[document_b_id], document_names=["tenant-b-private.pdf"],
                sections=[{"section_id": "findings", "title": "Findings", "content": "private B"}],
            ),
            EvaluationRun(
                id=run_a_id, owner_id=tenant_a, dataset_version="test",
                metrics={"tenant_marker": tenant_a},
            ),
            EvaluationRun(
                id=run_b_id, owner_id=tenant_b, dataset_version="test",
                metrics={"tenant_marker": tenant_b},
            ),
            EvidenceAnnotation(
                id=str(uuid.uuid4()), owner_id=tenant_a, document_id=document_a_id,
                source_id=chunk_a_id, claim="private claim A",
                passage="private passage A", label="supports",
            ),
            EvidenceAnnotation(
                id=str(uuid.uuid4()), owner_id=tenant_b, document_id=document_b_id,
                source_id=chunk_b_id, claim="private claim B",
                passage="private passage B", label="contradicts",
            ),
            Conversation(id=conversation_a_id, owner_id=tenant_a, title="Tenant A thread"),
            Conversation(id=conversation_b_id, owner_id=tenant_b, title="Tenant B thread"),
            Message(
                id=str(uuid.uuid4()), conversation_id=conversation_a_id,
                role="user", content="tenant A private message",
            ),
            Message(
                id=str(uuid.uuid4()), conversation_id=conversation_b_id,
                role="user", content="tenant B private message",
            ),
        ])
        await db.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"X-Dev-User": tenant_b}
            documents = await client.get("/api/documents", headers=headers)
            runs = await client.get("/api/evaluation/runs", headers=headers)
            reports = await client.get("/api/reports", headers=headers)
            report_detail = await client.get(f"/api/reports/{report_a_id}", headers=headers)
            report_pdf = await client.get(f"/api/reports/{report_a_id}/pdf", headers=headers)
            annotation_summary = await client.get("/api/evidence-annotations/summary", headers=headers)
            foreign_annotation = await client.post(
                "/api/evidence-annotations", headers=headers,
                json={"source_id": chunk_a_id, "claim": "claim", "label": "supports"},
            )
            foreign_export = await client.post(
                "/api/evidence-annotations/export", headers=headers,
                json={"test_document_ids": [document_a_id]},
            )
            foreign_history = await client.get(
                f"/api/chat/{conversation_a_id}", headers=headers,
            )
            own_history = await client.get(
                f"/api/chat/{conversation_b_id}", headers=headers,
            )
            foreign_document = await client.get(
                f"/api/documents/{document_a_id}", headers=headers,
            )

        assert [document["id"] for document in documents.json()] == [document_b_id]
        assert [run["id"] for run in runs.json()] == [run_b_id]
        assert [report["id"] for report in reports.json()] == [report_b_id]
        assert report_detail.status_code == 404
        assert report_pdf.status_code == 404
        assert annotation_summary.json()["total"] == 1
        assert annotation_summary.json()["documents"][0]["document_id"] == document_b_id
        assert foreign_annotation.status_code == 404
        assert foreign_export.status_code == 400
        assert foreign_history.status_code == 404
        assert own_history.status_code == 200
        assert [message["content"] for message in own_history.json()["messages"]] == [
            "tenant B private message"
        ]
        assert foreign_document.status_code == 404
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Message).where(
                Message.conversation_id.in_([conversation_a_id, conversation_b_id])
            ))
            await db.execute(delete(Conversation).where(
                Conversation.id.in_([conversation_a_id, conversation_b_id])
            ))
            await db.execute(delete(EvidenceAnnotation).where(
                EvidenceAnnotation.document_id.in_([document_a_id, document_b_id])
            ))
            await db.execute(delete(ResearchReport).where(
                ResearchReport.id.in_([report_a_id, report_b_id])
            ))
            await db.execute(delete(EvaluationRun).where(
                EvaluationRun.id.in_([run_a_id, run_b_id])
            ))
            await db.execute(delete(DocumentChunk).where(
                DocumentChunk.document_id.in_([document_a_id, document_b_id])
            ))
            await db.execute(delete(Document).where(
                Document.id.in_([document_a_id, document_b_id])
            ))
            await db.commit()
