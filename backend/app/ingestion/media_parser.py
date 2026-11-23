"""Bounded raster-image and video-frame parsing for evidence indexing."""

from __future__ import annotations

import io
import base64
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass
class MediaEvidence:
    locator_type: str
    locator_value: str
    text: str


@dataclass
class ParsedMedia:
    media_type: str
    mime_type: str
    duration_seconds: int | None
    evidence: list[MediaEvidence]


class MediaParser:
    IMAGE_MIME_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    VIDEO_MIME_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
    MAX_IMAGE_PIXELS = 24_000_000
    MAX_VIDEO_SECONDS = 120
    MAX_VIDEO_BYTES = 100 * 1024 * 1024
    MAX_FRAMES = 12
    MAX_FRAME_DIMENSION = 1024
    FFMPEG_TIMEOUT_SECONDS = 45

    @classmethod
    def parse(cls, content: bytes, mime_type: str, filename: str) -> ParsedMedia:
        mime_type = (mime_type or "").split(";")[0].strip().lower()
        if mime_type.startswith("image/"):
            if mime_type not in cls.IMAGE_MIME_TYPES:
                raise ValueError("Supported images: JPEG, PNG, and WebP. SVG and other formats are not accepted.")
            return cls._parse_image(content, mime_type)
        if mime_type.startswith("video/"):
            if mime_type not in cls.VIDEO_MIME_TYPES:
                raise ValueError("Supported videos: MP4, MOV, and WebM.")
            return cls._parse_video(content, mime_type, filename)
        raise ValueError("Unsupported media type.")

    @classmethod
    def _parse_image(cls, content: bytes, mime_type: str) -> ParsedMedia:
        if len(content) > 15 * 1024 * 1024:
            raise ValueError("Image exceeds the 15 MB limit.")
        try:
            with Image.open(io.BytesIO(content)) as source:
                expected_format = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime_type]
                if source.format != expected_format:
                    raise ValueError("Image content does not match its declared file type.")
                if source.width * source.height > cls.MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions exceed the 24 megapixel limit.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((cls.MAX_FRAME_DIMENSION, cls.MAX_FRAME_DIMENSION))
                image_bytes = io.BytesIO()
                image.save(image_bytes, format="JPEG", quality=82, optimize=True)
                data_uri = "data:image/jpeg;base64," + base64.b64encode(image_bytes.getvalue()).decode("ascii")
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Unable to decode the uploaded image.") from exc

        observations = cls._describe_images([data_uri])
        text = observations[0] if observations else "Image evidence. Visual description unavailable; inspect the original image."
        return ParsedMedia("image", mime_type, None, [MediaEvidence("image", "image", text)])

    @classmethod
    def _parse_video(cls, content: bytes, mime_type: str, filename: str) -> ParsedMedia:
        if len(content) > cls.MAX_VIDEO_BYTES:
            raise ValueError("Video exceeds the 100 MB limit.")
        try:
            import imageio_ffmpeg
        except ImportError as exc:
            raise ValueError("Video processing is unavailable. Install imageio-ffmpeg.") from exc

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        extension = cls.VIDEO_MIME_TYPES[mime_type]
        with tempfile.TemporaryDirectory(prefix="nexus-media-") as temp_dir:
            input_path = Path(temp_dir) / f"source{extension}"
            input_path.write_bytes(content)
            # imageio-ffmpeg bundles ffmpeg (not ffprobe), so obtain duration from its input diagnostics.
            probe_command = [ffmpeg, "-hide_banner", "-i", str(input_path)]
            try:
                probe = subprocess.run(probe_command, capture_output=True, text=True, timeout=cls.FFMPEG_TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Video inspection exceeded its time limit.") from exc
            diagnostics = probe.stderr
            duration = cls._duration_from_diagnostics(diagnostics)
            if duration is None or duration <= 0:
                raise ValueError("Could not read video duration. The file may be malformed or unsupported.")
            if duration > cls.MAX_VIDEO_SECONDS:
                raise ValueError("Video exceeds the 120 second limit.")

            timestamps = sorted({min(duration - 0.05, duration * fraction) for fraction in (0.1, 0.3, 0.5, 0.7, 0.9)})
            data_uris: list[str] = []
            extracted_timestamps: list[float] = []
            for timestamp in timestamps[: cls.MAX_FRAMES]:
                frame_command = [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
                    "-i", str(input_path), "-frames:v", "1", "-vf",
                    f"scale='min({cls.MAX_FRAME_DIMENSION},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-",
                ]
                try:
                    frame = subprocess.run(frame_command, capture_output=True, timeout=cls.FFMPEG_TIMEOUT_SECONDS, check=False)
                except subprocess.TimeoutExpired as exc:
                    raise ValueError("Video frame extraction exceeded its time limit.") from exc
                if frame.returncode != 0 or not frame.stdout:
                    continue
                data_uris.append("data:image/jpeg;base64," + base64.b64encode(frame.stdout).decode("ascii"))
                extracted_timestamps.append(timestamp)

            if not data_uris:
                raise ValueError("Could not extract frames from the video.")
            descriptions = cls._describe_images(data_uris)

        evidence = []
        for index, timestamp in enumerate(extracted_timestamps):
            description = descriptions[index] if index < len(descriptions) else "Frame description unavailable; inspect the video at this timestamp."
            evidence.append(MediaEvidence("video_frame", f"{timestamp:.2f}", description))
        return ParsedMedia("video", mime_type, duration, evidence)

    @staticmethod
    def _duration_from_diagnostics(diagnostics: str) -> int | None:
        match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", diagnostics)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds))

    @staticmethod
    def _describe_images(data_uris: list[str]) -> list[str]:
        from app.config import settings
        provider = settings.LLM_PROVIDER.lower()
        api_key = settings.openai_api_key
        if provider in {"openai", "ollama"}:
            is_ollama = provider == "ollama"
            if not is_ollama and not api_key:
                return ["Visual description unavailable: configure an OpenAI API key to analyze this image."] * len(data_uris)

            from openai import OpenAI
            client = OpenAI(
                api_key="ollama" if is_ollama else api_key,
                base_url=f"{settings.OLLAMA_BASE_URL.rstrip('/')}/v1" if is_ollama else None,
            )
            descriptions = []
            for data_uri in data_uris:
                response = client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Describe only directly visible details useful for factual evidence retrieval. "
                                    "Transcribe clear text verbatim when possible. Mark uncertainty. "
                                    "Do not infer identity, intent, or events outside the image."
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }],
                    temperature=0,
                )
                descriptions.append(
                    (response.choices[0].message.content or "").strip()
                    or "No visual description was returned."
                )
            return descriptions

        if provider != "gemini" or not api_key:
            return ["Visual description unavailable: configure an image-capable model to analyze this image."] * len(data_uris)

        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        descriptions = []
        for data_uri in data_uris:
            encoded_image = data_uri.partition(",")[2]
            response = client.models.generate_content(
                model=settings.LLM_MODEL,
                contents=[
                    types.Part.from_bytes(data=base64.b64decode(encoded_image), mime_type="image/jpeg"),
                    "Describe only directly visible details useful for factual evidence retrieval. Transcribe clear text verbatim when possible. Mark uncertainty. Do not infer identity, intent, or events outside the image.",
                ],
                config=types.GenerateContentConfig(temperature=0),
            )
            descriptions.append((response.text or "").strip() or "No visual description was returned.")
        return descriptions
