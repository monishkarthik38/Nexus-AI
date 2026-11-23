from __future__ import annotations

import asyncio
import hashlib
import httpx
import os
import re
from pathlib import Path
from typing import Protocol, Union
from urllib.parse import quote

from app.config import settings


def sanitize_user_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._@+-]+", "_", value).strip("._@+")
    return cleaned or "user"


def get_private_root(storage_dir: Union[str, os.PathLike[str]], owner_id: str) -> Path:
    root = Path(storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    owner_dir = root / sanitize_user_component(owner_id)
    owner_dir.mkdir(parents=True, exist_ok=True)
    return owner_dir


def build_private_storage_path(storage_dir: Union[str, os.PathLike[str]], owner_id: str, document_id: str, filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._@+-]+", "_", Path(filename).name).strip("._@+") or "upload"
    owner_root = get_private_root(storage_dir, owner_id)
    target = (owner_root / f"{document_id}_{safe_name}").resolve(strict=False)
    if os.path.commonpath([str(owner_root.resolve()), str(target)]) != str(owner_root.resolve()):
        raise ValueError("Unsafe storage path for uploaded document")
    return str(target)


def compute_file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def remove_document_file(storage_path: str, storage_root: str | None = None) -> None:
    if not storage_path:
        return
    target = Path(storage_path).resolve(strict=False)
    root = Path(storage_root or str(target.parent)).resolve(strict=False)
    try:
        if os.path.commonpath([str(root), str(target)]) != str(root):
            return
    except ValueError:
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


class StorageError(RuntimeError):
    pass


class DocumentStorage(Protocol):
    def build_key(self, owner_id: str, document_id: str, filename: str) -> str: ...

    async def put(self, key: str, content: bytes, mime_type: str) -> None: ...

    async def read(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def verify_private_bucket(self) -> None: ...


class LocalDocumentStorage:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir

    def build_key(self, owner_id: str, document_id: str, filename: str) -> str:
        return build_private_storage_path(self.storage_dir, owner_id, document_id, filename)

    def _validated_path(self, key: str) -> Path:
        root = Path(self.storage_dir).expanduser().resolve()
        target = Path(key).expanduser().resolve(strict=False)
        try:
            is_within_root = os.path.commonpath([str(root), str(target)]) == str(root)
        except ValueError:
            is_within_root = False
        if not is_within_root:
            raise ValueError("Unsafe local storage path")
        return target

    async def put(self, key: str, content: bytes, mime_type: str) -> None:
        def write_file() -> None:
            path = self._validated_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(write_file)

    async def read(self, key: str) -> bytes:
        path = self._validated_path(key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._validated_path(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def verify_private_bucket(self) -> None:
        return


class SupabaseDocumentStorage:
    def __init__(
        self,
        project_url: str,
        service_role_key: str,
        bucket: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.project_url = project_url.rstrip("/")
        self.service_role_key = service_role_key
        self.bucket = bucket
        self.transport = transport

    def build_key(self, owner_id: str, document_id: str, filename: str) -> str:
        safe_name = re.sub(r"[^A-Za-z0-9._@+-]+", "_", Path(filename).name).strip("._@+") or "upload"
        return f"{sanitize_user_component(owner_id)}/{document_id}/{safe_name}"

    def _object_url(self, key: str) -> str:
        encoded_bucket = quote(self.bucket, safe="")
        encoded_key = quote(key, safe="/")
        return f"{self.project_url}/storage/v1/object/{encoded_bucket}/{encoded_key}"

    async def _request(
        self,
        method: str,
        key: str,
        *,
        content: bytes | None = None,
        mime_type: str | None = None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }
        if mime_type:
            headers["Content-Type"] = mime_type
        try:
            async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
                url = self._object_url(key)
                if method == "DELETE":
                    url = f"{self.project_url}/storage/v1/object/{quote(self.bucket, safe='')}"
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    content=content,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase Storage {method} request failed") from exc
        if not response.is_success:
            raise StorageError(f"Supabase Storage {method} request returned HTTP {response.status_code}")
        return response

    async def put(self, key: str, content: bytes, mime_type: str) -> None:
        await self._request("POST", key, content=content, mime_type=mime_type)

    async def read(self, key: str) -> bytes:
        response = await self._request("GET", key)
        return response.content

    async def delete(self, key: str) -> None:
        await self._request("DELETE", key, json_body={"prefixes": [key]})

    async def verify_private_bucket(self) -> None:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }
        url = f"{self.project_url}/storage/v1/bucket/{quote(self.bucket, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise StorageError("Supabase Storage bucket verification failed") from exc
        if not response.is_success:
            raise StorageError(
                f"Supabase Storage bucket verification returned HTTP {response.status_code}"
            )
        try:
            is_public = response.json().get("public")
        except (ValueError, AttributeError) as exc:
            raise StorageError("Supabase Storage bucket verification returned invalid data") from exc
        if is_public is not False:
            raise StorageError("Supabase Storage bucket must be private")


def get_document_storage() -> DocumentStorage:
    backend = settings.STORAGE_BACKEND.strip().lower()
    if backend == "local":
        return LocalDocumentStorage(settings.STORAGE_DIR)
    if backend == "supabase":
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase Storage"
            )
        return SupabaseDocumentStorage(
            project_url=settings.SUPABASE_URL,
            service_role_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            bucket=settings.SUPABASE_STORAGE_BUCKET,
        )
    raise RuntimeError("STORAGE_BACKEND must be either local or supabase")
