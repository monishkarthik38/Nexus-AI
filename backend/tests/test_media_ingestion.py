import io
import subprocess
from unittest.mock import patch

import pytest
from PIL import Image
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database.models import Document, DocumentChunk
from app.database.session import AsyncSessionLocal, init_db
from app.ingestion.media_parser import MediaParser
from app.ingestion.worker import IngestionWorker
from app.main import app


def make_png() -> bytes:
    image = Image.new("RGB", (48, 32), color=(20, 120, 220))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_parser_describes_and_returns_image_locator():
    with patch.object(MediaParser, "_describe_images", return_value=["Blue rectangle, 48 by 32 pixels."]):
        parsed = MediaParser.parse(make_png(), "image/png", "sample.png")

    assert parsed.media_type == "image"
    assert parsed.mime_type == "image/png"
    assert parsed.evidence[0].locator_type == "image"
    assert parsed.evidence[0].locator_value == "image"
    assert "Blue rectangle" in parsed.evidence[0].text


def test_image_parser_rejects_declared_mime_mismatch():
    with pytest.raises(ValueError, match="does not match"):
        MediaParser.parse(make_png(), "image/jpeg", "sample.jpg")


def test_image_parser_rejects_svg():
    with pytest.raises(ValueError, match="SVG"):
        MediaParser.parse(b"<svg></svg>", "image/svg+xml", "sample.svg")


def test_image_parser_rejects_images_over_pixel_limit(monkeypatch):
    monkeypatch.setattr(MediaParser, "MAX_IMAGE_PIXELS", 1000)

    with patch.object(MediaParser, "_describe_images") as describe_images:
        with pytest.raises(ValueError, match="24 megapixel"):
            MediaParser.parse(make_png(), "image/png", "sample.png")

    describe_images.assert_not_called()


def test_image_parser_rejects_images_over_byte_limit():
    oversized_content = b"x" * (15 * 1024 * 1024 + 1)

    with pytest.raises(ValueError, match="15 MB limit"):
        MediaParser.parse(oversized_content, "image/png", "sample.png")


def test_video_parser_samples_frames_with_timestamps(tmp_path):
    frame_image = Image.new("RGB", (24, 24), color="red")
    frame_bytes = io.BytesIO()
    frame_image.save(frame_bytes, format="JPEG")

    def fake_run(command, **kwargs):
        if "-i" in command and "-frames:v" not in command:
            return type("Completed", (), {"stderr": "Duration: 00:00:10.00, start: 0.000000", "returncode": 1, "stdout": b""})()
        return type("Completed", (), {"stderr": "", "returncode": 0, "stdout": frame_bytes.getvalue()})()

    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"), \
         patch("app.ingestion.media_parser.subprocess.run", side_effect=fake_run), \
         patch.object(MediaParser, "_describe_images", return_value=["A red test frame."] * 5):
        parsed = MediaParser.parse(b"video", "video/mp4", "clip.mp4")

    assert parsed.media_type == "video"
    assert parsed.duration_seconds == 10
    assert len(parsed.evidence) == 5
    assert parsed.evidence[0].locator_type == "video_frame"
    assert parsed.evidence[0].locator_value == "1.00"
    assert "red test frame" in parsed.evidence[0].text


def test_video_parser_rejects_overlong_video():
    def fake_run(command, **kwargs):
        return type("Completed", (), {"stderr": "Duration: 00:02:01.00, start: 0.000000", "returncode": 1, "stdout": b""})()

    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"), patch("app.ingestion.media_parser.subprocess.run", side_effect=fake_run):
        with pytest.raises(ValueError, match="120 second"):
            MediaParser.parse(b"video", "video/mp4", "clip.mp4")


def test_video_parser_reports_probe_timeout():
    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"), \
         patch(
             "app.ingestion.media_parser.subprocess.run",
             side_effect=subprocess.TimeoutExpired("ffmpeg", 45),
         ):
        with pytest.raises(ValueError, match="inspection exceeded its time limit"):
            MediaParser.parse(b"video", "video/mp4", "clip.mp4")


def test_video_parser_rejects_unreadable_duration():
    def fake_run(command, **kwargs):
        return type("Completed", (), {"stderr": "Input has no duration metadata", "returncode": 1, "stdout": b""})()

    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"), \
         patch("app.ingestion.media_parser.subprocess.run", side_effect=fake_run):
        with pytest.raises(ValueError, match="Could not read video duration"):
            MediaParser.parse(b"video", "video/mp4", "clip.mp4")


@pytest.mark.asyncio
async def test_image_upload_preview_and_owner_boundary():
    await init_db()
    image_content = make_png()
    with patch.object(MediaParser, "_describe_images", return_value=["A blue rectangular graphic."]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "media_test_owner"}) as client:
            upload = await client.post(
                "/api/documents",
                files={"file": ("graphic.png", image_content, "image/png")},
                data={},
            )
            assert upload.status_code == 201, upload.text
            document = upload.json()
            assert document["media_type"] == "image"
            assert document["status"] == "processing"
            await IngestionWorker(AsyncSessionLocal, worker_id="media-test-worker").process_one(
                document["job_id"]
            )

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document["id"]))
                chunk = result.scalars().first()
            assert chunk is not None
            assert chunk.locator_type == "image"

            preview = await client.get(f"/api/documents/{document['id']}/preview")
            assert preview.status_code == 200
            assert preview.content == image_content
            forbidden_preview = await client.get(f"/api/documents/{document['id']}/preview", headers={"X-Dev-User": "other_owner"})
            assert forbidden_preview.status_code == 404

            deleted = await client.delete(f"/api/documents/{document['id']}?owner_id=media_test_owner")
            assert deleted.status_code == 200

            invalid = await client.post(
                "/api/documents",
                files={"file": ("fake.png", b"not a PNG", "image/png")},
                data={},
            )
            assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_upload_uses_private_owner_scoped_storage_and_checksum(tmp_path, monkeypatch):
    await init_db()
    monkeypatch.setattr("app.config.settings.STORAGE_DIR", str(tmp_path))
    image_content = make_png()

    with patch.object(MediaParser, "_describe_images", return_value=["A blue rectangular graphic."]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "alice@example.com"}) as client:
            upload = await client.post(
                "/api/documents",
                files={"file": ("graphic.png", image_content, "image/png")},
                data={},
            )
            assert upload.status_code == 201, upload.text
            document = upload.json()
            await IngestionWorker(AsyncSessionLocal, worker_id="media-test-worker").process_one(
                document["job_id"]
            )

    async with AsyncSessionLocal() as db:
        query = select(Document).where(Document.id == document["id"])
        result = await db.execute(query)
        stored = result.scalar_one()

    assert stored.owner_id == "alice@example.com"
    assert stored.storage_path.startswith(str(tmp_path / "alice@example.com"))
    assert stored.checksum_sha256 == __import__("hashlib").sha256(image_content).hexdigest()
    assert not stored.storage_path.startswith(str(tmp_path / "other_owner"))


@pytest.mark.asyncio
async def test_video_upload_indexes_timestamped_frames():
    await init_db()
    frame_image = Image.new("RGB", (24, 24), color="green")
    frame_bytes = io.BytesIO()
    frame_image.save(frame_bytes, format="JPEG")

    def fake_run(command, **kwargs):
        if "-frames:v" not in command:
            return type("Completed", (), {"stderr": "Duration: 00:00:10.00, start: 0.000000", "returncode": 1, "stdout": b""})()
        return type("Completed", (), {"stderr": "", "returncode": 0, "stdout": frame_bytes.getvalue()})()

    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"), \
         patch("app.ingestion.media_parser.subprocess.run", side_effect=fake_run), \
         patch.object(MediaParser, "_describe_images", return_value=["A green frame."] * 5):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "video_test_owner"}) as client:
            upload = await client.post(
                "/api/documents",
                files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypisommock video", "video/mp4")},
                data={},
            )
            assert upload.status_code == 201, upload.text
            document = upload.json()
            await IngestionWorker(AsyncSessionLocal, worker_id="media-test-worker").process_one(
                document["job_id"]
            )
            assert document["media_type"] == "video"
            completed = await client.get(f"/api/documents/{document['id']}")
            assert completed.json()["duration_seconds"] == 10

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document["id"]))
                chunks = result.scalars().all()
            assert len(chunks) == 5
            assert all(chunk.locator_type == "video_frame" for chunk in chunks)
            assert {chunk.locator_value for chunk in chunks} == {"1.00", "3.00", "5.00", "7.00", "9.00"}
            await client.delete(f"/api/documents/{document['id']}")
