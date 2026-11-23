"""Rebuild Qdrant vectors from the authoritative SQL document chunks."""

import argparse
import asyncio

from sqlalchemy import select

from app.database.models import Document, DocumentChunk
from app.database.session import (
    AsyncSessionLocal,
    engine,
    init_db,
    set_session_tenant,
)
from app.ingestion.chunker import TextChunk
from app.retrieval.indexer import indexer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-embed stored document chunks into the configured Qdrant collection. "
            "The operation is safe to rerun: Qdrant point IDs are deterministic."
        )
    )
    parser.add_argument(
        "--owner-id",
        required=True,
        help="Required tenant scope; only reindex documents belonging to this user.",
    )
    parser.add_argument("--document-id", help="Only reindex this document.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Maximum chunks embedded per request (default: 32).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible documents and chunk counts without embedding or writing vectors.",
    )
    return parser.parse_args()


async def reindex(args: argparse.Namespace) -> int:
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1.")

    await init_db()
    async with AsyncSessionLocal() as db:
        set_session_tenant(db, args.owner_id)
        statement = (
            select(Document)
            .where(Document.status == "ready")
            .order_by(Document.created_at, Document.id)
        )
        if args.owner_id:
            statement = statement.where(Document.owner_id == args.owner_id)
        if args.document_id:
            statement = statement.where(Document.id == args.document_id)
        documents = (await db.execute(statement)).scalars().all()

        if not documents:
            print("No ready documents matched the requested filters.")
            return 0

        processed_documents = 0
        processed_chunks = 0
        for document in documents:
            chunk_statement = (
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
            )
            rows = (await db.execute(chunk_statement)).scalars().all()
            if not rows:
                print(
                    f"Skipping {document.filename} ({document.id}): "
                    "ready document has no stored chunks.",
                    flush=True,
                )
                continue

            print(
                f"{'Would reindex' if args.dry_run else 'Reindexing'} "
                f"{document.filename} ({document.id}): {len(rows)} chunks.",
                flush=True,
            )
            if args.dry_run:
                continue
            if indexer.using_in_memory_fallback:
                raise RuntimeError(
                    "The local Qdrant storage is locked and this process is using "
                    "temporary in-memory storage. Stop the running backend and retry "
                    "so reindexed vectors are written to persistent storage."
                )

            chunks = [
                TextChunk(
                    chunk_id=row.id,
                    document_id=document.id,
                    page_number=row.page_number,
                    chunk_index=row.chunk_index,
                    title=document.filename,
                    content_hash=row.content_hash,
                    text=row.chunk_text,
                    locator_type=row.locator_type or "page",
                    locator_value=row.locator_value,
                )
                for row in rows
            ]
            for start in range(0, len(chunks), args.batch_size):
                batch = chunks[start:start + args.batch_size]
                await indexer.index_chunks(batch, owner_id=document.owner_id)
                processed_chunks += len(batch)
            processed_documents += 1

        if not args.dry_run:
            print(
                f"Reindexed {processed_chunks} chunks across "
                f"{processed_documents} documents into '{indexer.collection_name}'.",
                flush=True,
            )
    return 0


async def main() -> int:
    try:
        return await reindex(parse_args())
    finally:
        indexer.client.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
