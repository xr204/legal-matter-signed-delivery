from datetime import date, datetime, timezone

import pytest

from legal_delivery.matter_intake import MatterIntake, create_app, process_intake


class MemoryStorage:
    def __init__(self, found: bool) -> None:
        self.found = found
        self.presign_calls = 0
        self.created_buckets: list[str] = []
        self.deleted_buckets: list[str] = []

    async def create_bucket(self, name: str) -> dict:
        self.created_buckets.append(name)
        return {"name": name}

    async def delete_bucket(self, bucket: str) -> dict:
        self.deleted_buckets.append(bucket)
        return {"bucket": bucket}

    async def object_head(self, bucket: str, key: str) -> dict:
        return {"found": self.found}

    async def presign_download(
        self, bucket: str, key: str, expires_seconds: int, response_disposition: str
    ) -> dict:
        self.presign_calls += 1
        return {"url": "https://signed.example/matter.pdf"}


@pytest.mark.asyncio
async def test_missing_document_waits_without_issuing_a_link() -> None:
    storage = MemoryStorage(found=False)
    intake = MatterIntake(
        matter_id="MAT-2048",
        client_name="Avery Chen",
        document_key="matters/MAT-2048/executed.pdf",
        deadline=date(2026, 9, 18),
    )

    result = await process_intake(
        intake,
        storage,
        "legal-matter-documents",
        datetime(2026, 9, 10, 12, tzinfo=timezone.utc),
    )

    assert result.delivery_status == "awaiting_document"
    assert result.download_url is None
    assert result.follow_up_at == datetime(2026, 9, 16, 9, tzinfo=timezone.utc)
    assert storage.presign_calls == 0


@pytest.mark.asyncio
async def test_app_lifespan_deletes_the_bucket_created_at_startup() -> None:
    storage = MemoryStorage(found=False)
    app = create_app(storage)

    async with app.router.lifespan_context(app):
        assert storage.created_buckets == ["legal-matter-documents"]
        assert storage.deleted_buckets == []

    assert storage.deleted_buckets == ["legal-matter-documents"]


@pytest.mark.asyncio
async def test_existing_document_gets_expiring_delivery() -> None:
    storage = MemoryStorage(found=True)
    intake = MatterIntake(
        matter_id="MAT-2048",
        client_name="Avery Chen",
        document_key="matters/MAT-2048/executed.pdf",
        deadline=date(2026, 9, 18),
    )
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)

    result = await process_intake(
        intake, storage, "legal-matter-documents", now, link_ttl_seconds=900
    )

    assert result.delivery_status == "signed_url_ready"
    assert result.download_url == "https://signed.example/matter.pdf"
    assert result.download_expires_at == datetime(2026, 9, 10, 12, 15, tzinfo=timezone.utc)
    assert result.follow_up_at == datetime(2026, 9, 16, 9, tzinfo=timezone.utc)
