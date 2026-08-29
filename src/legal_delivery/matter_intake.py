from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import AsyncIterator, Literal, Protocol

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .infrai_storage import InfraiError, InfraiStorage


class MatterIntake(BaseModel):
    matter_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,64}$")
    client_name: str = Field(min_length=1, max_length=120)
    document_key: str = Field(min_length=1, max_length=512)
    deadline: date


class IntakeResult(BaseModel):
    matter_id: str
    delivery_status: Literal["signed_url_ready", "awaiting_document"]
    download_url: str | None
    download_expires_at: datetime | None
    follow_up_at: datetime


class StoragePort(Protocol):
    async def create_bucket(self, name: str) -> dict:
        pass

    async def delete_bucket(self, bucket: str) -> dict:
        pass

    async def object_head(self, bucket: str, key: str) -> dict:
        pass

    async def presign_download(
        self, bucket: str, key: str, expires_seconds: int, response_disposition: str
    ) -> dict:
        pass


def follow_up_time(deadline: date) -> datetime:
    return datetime.combine(deadline - timedelta(days=2), time(hour=9), timezone.utc)


async def process_intake(
    intake: MatterIntake,
    storage: StoragePort,
    bucket: str,
    now: datetime,
    link_ttl_seconds: int = 900,
) -> IntakeResult:
    follow_up_at = follow_up_time(intake.deadline)
    head = await storage.object_head(bucket, intake.document_key)
    if not head.get("found", False):
        return IntakeResult(
            matter_id=intake.matter_id,
            delivery_status="awaiting_document",
            download_url=None,
            download_expires_at=None,
            follow_up_at=follow_up_at,
        )

    signed = await storage.presign_download(
        bucket,
        intake.document_key,
        link_ttl_seconds,
        f'attachment; filename="{intake.matter_id}-signed.pdf"',
    )
    return IntakeResult(
        matter_id=intake.matter_id,
        delivery_status="signed_url_ready",
        download_url=signed["url"],
        download_expires_at=now + timedelta(seconds=link_ttl_seconds),
        follow_up_at=follow_up_at,
    )


def create_app(storage: InfraiStorage | None = None) -> FastAPI:
    bucket = os.getenv("LEGAL_DOCUMENT_BUCKET", "legal-matter-documents")
    storage_client = storage or InfraiStorage()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # The stable bucket name is the client-supplied identity for this setup write.
        await storage_client.create_bucket(bucket)
        try:
            yield
        finally:
            try:
                await storage_client.delete_bucket(bucket)
            finally:
                if storage is None:
                    await storage_client.close()

    service = FastAPI(title="Private legal document delivery", lifespan=lifespan)

    @service.post("/matters/intake", response_model=IntakeResult)
    async def intake_matter(payload: MatterIntake) -> IntakeResult:
        try:
            return await process_intake(
                payload, storage_client, bucket, datetime.now(timezone.utc)
            )
        except InfraiError as exc:
            caller_status = exc.status_code if 400 <= exc.status_code < 500 else 502
            raise HTTPException(
                status_code=caller_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return service


app = create_app()
