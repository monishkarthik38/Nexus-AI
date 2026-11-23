from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings, validate_runtime_config
from app.database.ingestion_models import IngestionJob
from app.database.models import Document, DocumentChunk
from app.database.session import TenantAwareSession, set_session_tenant
from app.ingestion.chunker import MediaChunk, TextChunker
from app.ingestion.media_parser import MediaParser
from app.ingestion.parser import PDFParser
from app.retrieval.indexer import indexer
from app.storage import get_document_storage

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
LEASE_SECONDS = 600
HEARTBEAT_SECONDS = 60
IDLE_POLL_SECONDS = 2
chunker = TextChunker(target_chunk_tokens=700, overlap_tokens=100)


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    document_id: str
    owner_id: str
    attempts: int
    worker_id: str


class IngestionWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.session_factory = session_factory
        self.worker_id = worker_id or str(uuid.uuid4())
        self.sleep = sleep
        self._role_verified = False

    async def verify_worker_database(self) -> None:
        async with self.session_factory() as session:
            if session.bind is None or session.bind.dialect.name != "postgresql":
                self._role_verified = True
                return
            result = await session.execute(text(
                """
                SELECT current_user AS role_name, role.rolsuper, role.rolbypassrls,
                       EXISTS (
                           SELECT 1
                           FROM pg_roles AS privileged_role
                           WHERE (privileged_role.rolsuper OR privileged_role.rolbypassrls)
                             AND pg_has_role(role.rolname, privileged_role.oid, 'MEMBER')
                       ) AS has_privileged_membership,
                       (SELECT version_num FROM alembic_version) AS revision
                FROM pg_roles AS role
                WHERE role.rolname = current_user
                """
            ))
            role = result.one_or_none()
            if (
                role is None
                or role.role_name != "nexus_worker"
                or role.rolsuper
                or role.rolbypassrls
                or role.has_privileged_membership
            ):
                raise RuntimeError(
                    "Ingestion worker must connect as non-bypass nexus_worker"
                )
            if role.revision != "003_durable_ingestion":
                raise RuntimeError(
                    "PostgreSQL schema is not at revision 003_durable_ingestion"
                )
            policy_result = await session.execute(text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       p.permissive, p.qual, p.with_check
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                LEFT JOIN pg_policies AS p
                  ON p.schemaname = n.nspname
                 AND p.tablename = c.relname
                 AND p.policyname = 'tenant_isolation'
                WHERE n.nspname = current_schema()
                  AND c.relname = 'ingestion_jobs'
                """
            ))
            policy = policy_result.one_or_none()
            if (
                policy is None
                or not policy.relrowsecurity
                or not policy.relforcerowsecurity
                or policy.permissive != "PERMISSIVE"
                or not policy.qual
                or not policy.with_check
                or "app.current_user_id" not in policy.qual
                or "app.current_user_id" not in policy.with_check
                or "nexus_worker" not in policy.qual
                or "nexus_worker" not in policy.with_check
            ):
                raise RuntimeError(
                    "PostgreSQL ingestion queue does not have its forced tenant/worker RLS policy"
                )
        self._role_verified = True

    async def _claim(
        self, job_id: str | None = None, tenant_id: str | None = None
    ) -> ClaimedJob | None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            if tenant_id is not None:
                set_session_tenant(session, tenant_id)
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                eligible = or_(
                    and_(
                        IngestionJob.status == "queued",
                        IngestionJob.available_at <= now,
                    ),
                    and_(
                        IngestionJob.status == "running",
                        IngestionJob.locked_until <= now,
                    ),
                )
                candidate = select(IngestionJob.id).where(eligible)
                if job_id is not None:
                    candidate = candidate.where(IngestionJob.id == job_id)
                if tenant_id is not None:
                    candidate = candidate.where(IngestionJob.owner_id == tenant_id)
                candidate = candidate.order_by(
                    IngestionJob.available_at, IngestionJob.created_at
                ).limit(1).scalar_subquery()
                result = await session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.id == candidate, eligible)
                    .values(
                        status="running",
                        attempts=IngestionJob.attempts + 1,
                        worker_id=self.worker_id,
                        locked_until=now + timedelta(seconds=LEASE_SECONDS),
                        updated_at=now,
                    )
                    .returning(
                        IngestionJob.id,
                        IngestionJob.document_id,
                        IngestionJob.owner_id,
                        IngestionJob.attempts,
                    )
                )
                row = result.one_or_none()
                if row is None:
                    await session.rollback()
                    return None
                claimed = ClaimedJob(
                    id=row.id,
                    document_id=row.document_id,
                    owner_id=row.owner_id,
                    attempts=row.attempts,
                    worker_id=self.worker_id,
                )
                await session.commit()
                return claimed

            statement = (
                select(IngestionJob)
                .where(
                    or_(
                        and_(
                            IngestionJob.status == "queued",
                            IngestionJob.available_at <= now,
                        ),
                        and_(
                            IngestionJob.status == "running",
                            IngestionJob.locked_until <= now,
                        ),
                    )
                )
                .order_by(IngestionJob.available_at, IngestionJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job_id is not None:
                statement = statement.where(IngestionJob.id == job_id)
            if tenant_id is not None:
                statement = statement.where(IngestionJob.owner_id == tenant_id)
            result = await session.execute(statement)
            job = result.scalar_one_or_none()
            if job is None:
                await session.rollback()
                return None

            job.status = "running"
            job.attempts += 1
            job.worker_id = self.worker_id
            job.locked_until = now + timedelta(seconds=LEASE_SECONDS)
            job.updated_at = now
            claimed = ClaimedJob(
                id=job.id,
                document_id=job.document_id,
                owner_id=job.owner_id,
                attempts=job.attempts,
                worker_id=self.worker_id,
            )
            await session.commit()
            return claimed

    async def _renew_lease(self, job: ClaimedJob) -> bool:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            set_session_tenant(session, job.owner_id)
            result = await session.execute(
                select(IngestionJob).where(
                    IngestionJob.id == job.id,
                    IngestionJob.status == "running",
                    IngestionJob.worker_id == self.worker_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.rollback()
                return False
            row.locked_until = now + timedelta(seconds=LEASE_SECONDS)
            row.updated_at = now
            await session.commit()
            return True

    async def _load_document(self, job: ClaimedJob) -> tuple[Document, bytes]:
        async with self.session_factory() as session:
            set_session_tenant(session, job.owner_id)
            result = await session.execute(
                select(Document).where(
                    Document.id == job.document_id,
                    Document.owner_id == job.owner_id,
                )
            )
            document = result.scalar_one_or_none()
            if document is None:
                raise ValueError("Document no longer exists.")
            content = await get_document_storage().read(document.storage_path)
            return document, content

    async def _extract(self, job: ClaimedJob, document: Document, content: bytes):
        if document.media_type == "pdf":
            parsed = await asyncio.to_thread(PDFParser.extract_text, content)
            if parsed.is_empty:
                raise ValueError(
                    "Scanned or empty PDF: No extractable text detected. OCR is required."
                )
            chunks = chunker.chunk_document(
                document_id=job.document_id,
                document_title=document.filename,
                pages=parsed.pages,
            )
            return chunks, parsed.total_pages, None

        parsed_media = await asyncio.to_thread(
            MediaParser.parse, content, document.mime_type or "", document.filename
        )
        chunks = []
        for index, evidence in enumerate(parsed_media.evidence):
            content_hash = hashlib.sha256(evidence.text.encode("utf-8")).hexdigest()
            chunks.append(MediaChunk(
                chunk_id=f"{job.document_id}_{evidence.locator_type}_{index}_{content_hash[:8]}",
                document_id=job.document_id,
                page_number=index + 1,
                chunk_index=index,
                title=document.filename,
                content_hash=content_hash,
                text=evidence.text,
                locator_type=evidence.locator_type,
                locator_value=evidence.locator_value,
            ))
        return chunks, len(chunks), parsed_media.duration_seconds

    async def _finalize(
        self,
        job: ClaimedJob,
        chunks: list,
        page_count: int,
        duration_seconds: int | None,
    ) -> bool:
        async with self.session_factory() as session:
            set_session_tenant(session, job.owner_id)
            result = await session.execute(
                select(IngestionJob)
                .where(IngestionJob.id == job.id)
                .with_for_update()
            )
            queue_row = result.scalar_one_or_none()
            if queue_row is None or queue_row.status != "running":
                await session.rollback()
                if queue_row is None:
                    indexer.delete_document(job.document_id, owner_id=job.owner_id)
                return False
            if queue_row.worker_id != self.worker_id:
                await session.rollback()
                return False

            document_result = await session.execute(
                select(Document).where(
                    Document.id == job.document_id,
                    Document.owner_id == job.owner_id,
                )
            )
            document = document_result.scalar_one_or_none()
            if document is None:
                await session.rollback()
                indexer.delete_document(job.document_id, owner_id=job.owner_id)
                return False

            for chunk in chunks:
                session.add(DocumentChunk(
                    id=chunk.chunk_id,
                    document_id=job.document_id,
                    page_number=chunk.page_number,
                    locator_type=getattr(chunk, "locator_type", "page"),
                    locator_value=getattr(chunk, "locator_value", str(chunk.page_number)),
                    chunk_index=chunk.chunk_index,
                    content_hash=chunk.content_hash,
                    chunk_text=chunk.text,
                ))
            document.page_count = page_count
            document.duration_seconds = duration_seconds
            document.status = "ready"
            document.error_message = None
            queue_row.status = "completed"
            queue_row.locked_until = None
            queue_row.worker_id = None
            queue_row.last_error = None
            queue_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True

    async def _record_failure(self, job: ClaimedJob, error: Exception) -> None:
        permanent = isinstance(error, ValueError)
        retry = not permanent and job.attempts < MAX_ATTEMPTS
        now = datetime.now(timezone.utc)
        safe_message = (
            str(error)[:500]
            if permanent
            else (
                "Ingestion temporarily failed; retry scheduled."
                if retry else "Ingestion failed after several attempts."
            )
        )
        async with self.session_factory() as session:
            set_session_tenant(session, job.owner_id)
            result = await session.execute(
                select(IngestionJob)
                .where(IngestionJob.id == job.id)
                .with_for_update()
            )
            queue_row = result.scalar_one_or_none()
            if (
                queue_row is None
                or queue_row.status != "running"
                or queue_row.worker_id != self.worker_id
            ):
                await session.rollback()
                return
            queue_row.status = "queued" if retry else "failed"
            queue_row.last_error = safe_message
            queue_row.locked_until = None
            queue_row.worker_id = None
            queue_row.available_at = now + timedelta(seconds=min(300, 2 ** job.attempts)) if retry else now
            queue_row.updated_at = now
            document_result = await session.execute(
                select(Document).where(
                    Document.id == job.document_id,
                    Document.owner_id == job.owner_id,
                )
            )
            document = document_result.scalar_one_or_none()
            if document is not None:
                document.status = "processing" if retry else "failed"
                document.error_message = None if retry else safe_message
            await session.commit()

    async def _process(self, job: ClaimedJob) -> None:
        document, content = await self._load_document(job)
        chunks, page_count, duration_seconds = await self._extract(job, document, content)
        await indexer.index_chunks(chunks, owner_id=job.owner_id)
        await self._finalize(job, chunks, page_count, duration_seconds)

    async def process_one(
        self, job_id: str | None = None, *, tenant_id: str | None = None
    ) -> bool:
        if tenant_id is None and not self._role_verified:
            await self.verify_worker_database()
        job = await self._claim(job_id, tenant_id)
        if job is None:
            return False

        processing = asyncio.create_task(self._process(job))
        try:
            while True:
                completed, _ = await asyncio.wait(
                    {processing}, timeout=HEARTBEAT_SECONDS
                )
                if processing in completed:
                    await processing
                    return True
                if not await self._renew_lease(job):
                    processing.cancel()
                    try:
                        await processing
                    except asyncio.CancelledError:
                        pass
                    return True
        except Exception as error:
            logger.error(
                "Ingestion job %s failed (%s)", job.id, type(error).__name__
            )
            await self._record_failure(job, error)
            return True

    async def run_forever(self) -> None:
        while True:
            try:
                processed = await self.process_one()
            except SQLAlchemyError as error:
                logger.error(
                    "Ingestion worker database operation failed (%s)",
                    type(error).__name__,
                )
                await self.sleep(IDLE_POLL_SECONDS)
                continue
            if not processed:
                await self.sleep(IDLE_POLL_SECONDS)


async def run_worker(once: bool = False) -> None:
    validate_runtime_config()
    if settings.DATABASE_URL.startswith("sqlite"):
        raise RuntimeError(
            "SQLite development ingestion runs as a single in-process worker "
            "in the API lifespan; do not start a separate worker process."
        )
    if not settings.QDRANT_URL:
        raise RuntimeError(
            "A separate ingestion worker requires shared remote Qdrant; "
            "embedded Qdrant cannot be shared by the API and worker processes"
        )
    worker_url = settings.INGESTION_WORKER_DATABASE_URL or settings.DATABASE_URL
    worker_engine = create_async_engine(worker_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        worker_engine,
        expire_on_commit=False,
        class_=AsyncSession,
        sync_session_class=TenantAwareSession,
    )
    try:
        worker = IngestionWorker(session_factory)
        await worker.verify_worker_database()
        if once:
            await worker.process_one()
        else:
            await worker.run_forever()
    finally:
        await worker_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the durable document-ingestion worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one available job and exit.")
    arguments = parser.parse_args()
    asyncio.run(run_worker(once=arguments.once))


if __name__ == "__main__":
    main()
