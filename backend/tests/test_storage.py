import httpx
import pytest

from app.storage import LocalDocumentStorage, StorageError, SupabaseDocumentStorage


@pytest.mark.asyncio
async def test_supabase_storage_uses_private_owner_scoped_objects_and_server_credentials():
    requests = []
    content = b"private document"

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={"Key": "stored"})

    storage = SupabaseDocumentStorage(
        "https://project.example.supabase.co",
        "server-only-secret",
        "private-documents",
        transport=httpx.MockTransport(handle),
    )
    key = storage.build_key("alice@example.com", "document-id", "financial report.pdf")

    assert key == "alice@example.com/document-id/financial_report.pdf"
    await storage.put(key, content, "application/pdf")
    assert await storage.read(key) == content
    await storage.delete(key)

    assert [request.method for request in requests] == ["POST", "GET", "DELETE"]
    assert requests[0].url.path == "/storage/v1/object/private-documents/alice@example.com/document-id/financial_report.pdf"
    assert requests[0].headers["authorization"] == "Bearer server-only-secret"
    assert requests[0].headers["content-type"] == "application/pdf"
    assert requests[0].content == content
    assert requests[2].url.path == "/storage/v1/object/private-documents"
    assert requests[2].read() == b'{"prefixes":["alice@example.com/document-id/financial_report.pdf"]}'


@pytest.mark.asyncio
async def test_supabase_storage_surfaces_provider_errors_without_response_body():
    storage = SupabaseDocumentStorage(
        "https://project.example.supabase.co",
        "server-only-secret",
        "private-documents",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, text="sensitive provider detail")
        ),
    )

    with pytest.raises(StorageError, match="HTTP 500") as error:
        await storage.read("alice/document/file.pdf")

    assert "sensitive provider detail" not in str(error.value)


@pytest.mark.asyncio
async def test_supabase_storage_rejects_public_bucket():
    storage = SupabaseDocumentStorage(
        "https://project.example.supabase.co",
        "server-only-secret",
        "private-documents",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"public": True})
        ),
    )

    with pytest.raises(StorageError, match="bucket must be private"):
        await storage.verify_private_bucket()


@pytest.mark.asyncio
async def test_supabase_storage_accepts_verified_private_bucket():
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"public": False})

    storage = SupabaseDocumentStorage(
        "https://project.example.supabase.co",
        "server-only-secret",
        "private-documents",
        transport=httpx.MockTransport(handle),
    )

    await storage.verify_private_bucket()

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/storage/v1/bucket/private-documents"


@pytest.mark.asyncio
async def test_local_storage_rejects_paths_outside_its_root(tmp_path):
    storage = LocalDocumentStorage(str(tmp_path / "private"))

    with pytest.raises(ValueError, match="Unsafe local storage path"):
        await storage.read(str(tmp_path / "outside.pdf"))
