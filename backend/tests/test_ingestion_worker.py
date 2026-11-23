import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database.ingestion_models import IngestionJob
from app.database.models import Document, DocumentChunk
from app.database.session import AsyncSessionLocal, init_db
from app.ingestion.worker import IngestionWorker
from app.main import app
from app.config import settings


def make_pdf(text: str) -> bytes:
    source = fitz.open()
    page = source.new_page()
    if text:
        page.insert_text((50, 72), text)
    content = source.tobytes()
    source.close()
    return content


@pytest.mark.asyncio
async def test_upload_enqueues_durable_job_then_worker_completes_it():
    await init_db()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": f"worker-{uuid.uuid4()}"},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={
                "file": (
                    "queued.pdf",
                    make_pdf("Durable queue evidence has enough text to pass the PDF content threshold."),
                    "application/pdf",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        queued = upload.json()
        assert queued["status"] == "processing"
        assert queued["job_id"]

        before = await client.get(f"/api/documents/{queued['id']}/ingestion")
        assert before.status_code == 200
        assert before.json()["status"] == "queued"
        assert before.json()["attempts"] == 0

        async with AsyncSessionLocal() as db:
            chunks_before = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == queued["id"])
            )
            assert chunks_before.scalars().all() == []

        worker = IngestionWorker(AsyncSessionLocal, worker_id="worker-test-one")
        assert await worker.process_one(queued["job_id"])

        completed = await client.get(f"/api/documents/{queued['id']}/ingestion")
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert completed.json()["attempts"] == 1
        document = (await client.get(f"/api/documents/{queued['id']}")).json()
        assert document["status"] == "ready"
        async with AsyncSessionLocal() as db:
            chunks_after = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == queued["id"])
            )
            assert chunks_after.scalars().first() is not None
        await client.delete(f"/api/documents/{queued['id']}")


@pytest.mark.asyncio
async def test_ingestion_job_status_is_owner_scoped():
    await init_db()
    owner = f"job-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as owner_client:
        upload = await owner_client.post(
            "/api/documents",
            files={"file": ("queued.pdf", make_pdf("private job status"), "application/pdf")},
        )
        upload_data = upload.json()
        document_id = upload_data["id"]
        await owner_client.delete(f"/api/documents/{document_id}")

    async with AsyncSessionLocal() as db:
        job_result = await db.execute(
            select(IngestionJob).where(IngestionJob.id == upload_data["job_id"])
        )
        assert job_result.scalar_one_or_none() is None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": "other-job-owner"},
    ) as other_client:
        response = await other_client.get(f"/api/documents/{document_id}/ingestion")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_document_fails_without_retrying():
    await init_db()
    owner = f"invalid-job-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={"file": ("empty.pdf", make_pdf(""), "application/pdf")},
        )
        assert upload.status_code == 201, upload.text
        data = upload.json()
        worker = IngestionWorker(AsyncSessionLocal, worker_id="worker-test-invalid")
        assert await worker.process_one(data["job_id"])

        status = await client.get(f"/api/documents/{data['id']}/ingestion")
        assert status.json()["status"] == "failed"
        assert status.json()["attempts"] == 1
        document = (await client.get(f"/api/documents/{data['id']}")).json()
        assert document["status"] == "failed"
        assert "OCR is required" in document["error_message"]
        await client.delete(f"/api/documents/{data['id']}")


@pytest.mark.asyncio
async def test_transient_failure_is_retried_with_backoff_and_safe_error():
    await init_db()
    owner = f"retry-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={
                "file": (
                    "retry.pdf",
                    make_pdf("This evidence is long enough to be parsed and indexed after retry."),
                    "application/pdf",
                )
            },
        )
        data = upload.json()
        worker = IngestionWorker(AsyncSessionLocal, worker_id="worker-test-retry")
        with patch(
            "app.ingestion.worker.indexer.index_chunks",
            new=AsyncMock(side_effect=[RuntimeError("private provider response"), 1]),
        ):
            assert await worker.process_one(data["job_id"])
            status = await client.get(f"/api/documents/{data['id']}/ingestion")
            assert status.json()["status"] == "queued"
            assert status.json()["attempts"] == 1
            assert status.json()["last_error"] == "Ingestion temporarily failed; retry scheduled."

            async with AsyncSessionLocal() as db:
                job_result = await db.execute(
                    select(IngestionJob).where(IngestionJob.id == data["job_id"])
                )
                job = job_result.scalar_one()
                job.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()

            assert await worker.process_one(data["job_id"])
        status = await client.get(f"/api/documents/{data['id']}/ingestion")
        assert status.json()["status"] == "completed"
        assert status.json()["attempts"] == 2
        await client.delete(f"/api/documents/{data['id']}")


@pytest.mark.asyncio
async def test_expired_worker_lease_is_reclaimed():
    await init_db()
    owner = f"lease-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={
                "file": (
                    "lease.pdf",
                    make_pdf("The worker lease can expire and this queued job can be safely reclaimed."),
                    "application/pdf",
                )
            },
        )
        data = upload.json()
        async with AsyncSessionLocal() as db:
            job_result = await db.execute(
                select(IngestionJob).where(IngestionJob.id == data["job_id"])
            )
            job = job_result.scalar_one()
            job.status = "running"
            job.attempts = 1
            job.worker_id = "crashed-worker"
            job.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

        assert await IngestionWorker(
            AsyncSessionLocal, worker_id="worker-after-crash"
        ).process_one(data["job_id"])
        status = await client.get(f"/api/documents/{data['id']}/ingestion")
        assert status.json()["status"] == "completed"
        assert status.json()["attempts"] == 2
        await client.delete(f"/api/documents/{data['id']}")


@pytest.mark.asyncio
async def test_local_development_keeps_inline_ingestion(monkeypatch):
    await init_db()
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "INGESTION_INLINE_DEVELOPMENT", True)
    owner = f"inline-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={
                "file": (
                    "inline.pdf",
                    make_pdf("Inline development preserves the previous ready-on-upload experience."),
                    "application/pdf",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        data = upload.json()
        assert data["status"] == "ready"
        assert data["chunks_count"] > 0
        status = await client.get(f"/api/documents/{data['id']}/ingestion")
        assert status.json()["status"] == "completed"
        await client.delete(f"/api/documents/{data['id']}")


@pytest.mark.asyncio
async def test_two_sqlite_workers_cannot_claim_the_same_job():
    await init_db()
    owner = f"concurrent-owner-{uuid.uuid4()}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User": owner},
    ) as client:
        upload = await client.post(
            "/api/documents",
            files={
                "file": (
                    "concurrent.pdf",
                    make_pdf("Atomic SQLite claims allow only one worker to own a queue job."),
                    "application/pdf",
                )
            },
        )
        job_id = upload.json()["job_id"]
        first, second = await asyncio.gather(
            IngestionWorker(AsyncSessionLocal, worker_id="sqlite-worker-a")._claim(job_id),
            IngestionWorker(AsyncSessionLocal, worker_id="sqlite-worker-b")._claim(job_id),
        )
        assert sum(claim is not None for claim in (first, second)) == 1
        await client.delete(f"/api/documents/{upload.json()['id']}")


@pytest.mark.asyncio
async def test_sqlite_lifespan_worker_resumes_durable_jobs():
    await init_db()
    owner = f"lifespan-owner-{uuid.uuid4()}"
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Dev-User": owner},
        ) as client:
            upload = await client.post(
                "/api/documents",
                files={
                    "file": (
                        "background.pdf",
                        make_pdf("SQLite lifespan workers resume durable ingestion jobs."),
                        "application/pdf",
                    )
                },
            )
            data = upload.json()
            assert data["status"] == "processing"
            for _ in range(50):
                status = await client.get(
                    f"/api/documents/{data['id']}/ingestion"
                )
                if status.json()["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
            assert status.json()["status"] == "completed"
            await client.delete(f"/api/documents/{data['id']}")
