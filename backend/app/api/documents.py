import os
import asyncio
import uuid
import subprocess
import tempfile
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.auth import CurrentUser, get_current_user
from app.database.session import AsyncSessionLocal, get_db
from app.database.models import Document, DocumentChunk
from app.database.ingestion_models import IngestionJob
from app.ingestion.parser import PDFParser
from app.ingestion.media_parser import MediaParser
from app.ingestion.worker import IngestionWorker
from app.retrieval.indexer import indexer
from app.storage import StorageError, compute_file_sha256, get_document_storage

router = APIRouter(prefix="/api/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    filename = (file.filename or "upload").replace("\\", "/").split("/")[-1]
    extension = os.path.splitext(filename)[1].lower()
    max_bytes = PDFParser.MAX_FILE_SIZE_BYTES if extension == ".pdf" else (
        MediaParser.MAX_VIDEO_BYTES if extension in {".mp4", ".mov", ".webm"} else 15 * 1024 * 1024
    )
    content_buffer = bytearray()
    while True:
        block = await file.read(min(1024 * 1024, max_bytes + 1 - len(content_buffer)))
        if not block:
            break
        content_buffer.extend(block)
        if len(content_buffer) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
    content = bytes(content_buffer)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    declared_mime = (file.content_type or "").split(";")[0].lower()
    if extension == ".pdf" and declared_mime == "application/pdf":
        media_type = "pdf"
        mime_type = "application/pdf"
        try:
            PDFParser.validate_content(content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        supported_extensions = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        }
        expected_mime = supported_extensions.get(extension)
        if not expected_mime or declared_mime != expected_mime:
            raise HTTPException(status_code=400, detail="Upload a PDF, JPEG, PNG, WebP, MP4, MOV, or WebM with a matching file type.")
        if extension in {".mp4", ".mov", ".webm"} and len(content) > MediaParser.MAX_VIDEO_BYTES:
            raise HTTPException(status_code=400, detail="Video exceeds the 100 MB limit.")
        if extension in {".jpg", ".jpeg", ".png", ".webp"} and len(content) > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image exceeds the 15 MB limit.")
        media_type = "video" if expected_mime.startswith("video/") else "image"
        mime_type = expected_mime

    if media_type in {"image", "video"} and declared_mime != mime_type:
        raise HTTPException(status_code=400, detail="The uploaded file's declared type does not match its extension.")
    if media_type in {"image", "video"}:
        expected_signatures = {
            "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
            "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            "video/mp4": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
            "video/quicktime": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
            "video/webm": lambda data: data.startswith(b"\x1aE\xdf\xa3"),
        }
        if not expected_signatures[mime_type](content):
            raise HTTPException(status_code=400, detail="File content does not match the declared media type.")

    if media_type == "pdf" and (not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]):
        raise HTTPException(status_code=400, detail="PDF content has an invalid header or is incomplete.")

    doc_id = str(uuid.uuid4())
    storage = get_document_storage()
    storage_path = storage.build_key(user.id, doc_id, filename)
    checksum = compute_file_sha256(content)

    # 1. Save file to storage
    try:
        await storage.put(storage_path, content, mime_type)
    except StorageError as err:
        raise HTTPException(status_code=503, detail="Document storage is unavailable.") from err

    job_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        owner_id=user.id,
        filename=filename,
        storage_path=storage_path,
        status="processing",
        file_size=len(content),
        checksum_sha256=checksum,
        page_count=0,
        media_type=media_type,
        mime_type=mime_type,
    )
    db.add(doc_record)
    db.add(IngestionJob(
        id=job_id,
        document_id=doc_id,
        owner_id=user.id,
        status="queued",
    ))
    try:
        await db.commit()
    except Exception as err:
        await db.rollback()
        try:
            await storage.delete(storage_path)
        except StorageError:
            logger.exception("Could not remove unqueued upload %s", doc_id)
        raise HTTPException(
            status_code=503, detail="Unable to queue document ingestion."
        ) from err

    if (
        settings.ENVIRONMENT.strip().lower() == "development"
        and settings.INGESTION_INLINE_DEVELOPMENT
    ):
        try:
            await IngestionWorker(
                AsyncSessionLocal, worker_id=f"inline-{uuid.uuid4()}"
            ).process_one(job_id, tenant_id=user.id)
        except Exception:
            logger.exception("Inline development ingestion failed for job %s", job_id)
        await db.refresh(doc_record)
        chunk_count_result = await db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == doc_id
            )
        )
        chunks_count = chunk_count_result.scalar_one()
    else:
        chunks_count = 0

    return {
        "id": doc_record.id,
        "job_id": job_id,
        "filename": doc_record.filename,
        "status": doc_record.status,
        "page_count": doc_record.page_count,
        "media_type": media_type,
        "duration_seconds": doc_record.duration_seconds,
        "chunks_count": chunks_count,
        "file_size": doc_record.file_size,
        "created_at": doc_record.created_at.isoformat()
    }

@router.get("")
async def list_documents(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc())
    res = await db.execute(stmt)
    docs = res.scalars().all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "status": d.status,
            "page_count": d.page_count,
            "media_type": d.media_type,
            "duration_seconds": d.duration_seconds,
            "file_size": d.file_size,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat()
        }
        for d in docs
    ]

@router.get("/{document_id}/preview")
async def preview_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.media_type not in {"image", "video"}:
        raise HTTPException(status_code=415, detail="Preview is available for images and videos only")
    try:
        content = await get_document_storage().read(doc.storage_path)
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail="Document not found") from err
    except StorageError as err:
        raise HTTPException(status_code=503, detail="Document storage is unavailable.") from err
    return Response(
        content=content,
        media_type=doc.mime_type or "application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )

@router.get("/{document_id}")
async def get_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "page_count": doc.page_count,
        "media_type": doc.media_type,
        "mime_type": doc.mime_type,
        "duration_seconds": doc.duration_seconds,
        "file_size": doc.file_size,
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat()
    }

@router.get("/{document_id}/ingestion")
async def get_ingestion_status(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document_result = await db.execute(
        select(Document.id).where(
            Document.id == document_id,
            Document.owner_id == user.id,
        )
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Document not found")
    job_result = await db.execute(
        select(IngestionJob).where(
            IngestionJob.document_id == document_id,
            IngestionJob.owner_id == user.id,
        )
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return {
        "job_id": job.id,
        "document_id": job.document_id,
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error,
        "updated_at": job.updated_at.isoformat(),
    }

@router.get("/{document_id}/frames/{timestamp}/preview")
async def preview_video_frame(
    document_id: str,
    timestamp: float,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if timestamp < 0:
        raise HTTPException(status_code=400, detail="Timestamp cannot be negative")
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.media_type != "video":
        raise HTTPException(status_code=415, detail="Document is not an available video")
    if doc.duration_seconds is not None and timestamp > doc.duration_seconds:
        raise HTTPException(status_code=400, detail="Timestamp exceeds the video duration")

    try:
        video_content = await get_document_storage().read(doc.storage_path)
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail="Document not found") from err
    except StorageError as err:
        raise HTTPException(status_code=503, detail="Document storage is unavailable.") from err

    def extract_preview() -> bytes:
        import imageio_ffmpeg
        suffix = os.path.splitext(doc.filename)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix) as source:
            source.write(video_content)
            source.flush()
            command = [
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-ss", f"{timestamp:.3f}", "-i", source.name, "-frames:v", "1",
                "-vf", "scale='min(1024,iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ]
            completed = subprocess.run(command, capture_output=True, timeout=15, check=False)
            if completed.returncode or not completed.stdout:
                raise ValueError("Could not decode the requested video frame")
            return completed.stdout

    try:
        frame_bytes = await asyncio.to_thread(extract_preview)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Could not preview this video frame") from exc
    return Response(content=frame_bytes, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Lock the job so an active worker cannot finish indexing after deletion.
    job_result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .with_for_update()
    )
    ingestion_job = job_result.scalar_one_or_none()
    if ingestion_job is not None:
        await db.delete(ingestion_job)

    try:
        await get_document_storage().delete(doc.storage_path)
    except StorageError as err:
        raise HTTPException(status_code=503, detail="Document storage is unavailable.") from err

    # Remove vectors before commit; a worker that was already processing will
    # detect the deleted job at finalization and repeat this cleanup.
    indexer.delete_document(document_id, owner_id=user.id)
    await db.delete(doc)
    await db.commit()

    return {"status": "success", "message": f"Document {document_id} deleted successfully."}
