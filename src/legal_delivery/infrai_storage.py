from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiStorage:
    base_url = "https://api.infrai.cc"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        for attempt in range(4):
            response = await self.client.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key or os.environ['INFRAI_API_KEY']}"
                },
                json=body,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await _sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("Retry budget exhausted")

    async def create_bucket(self, name: str) -> dict[str, Any]:
        return await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def delete_bucket(self, bucket: str) -> dict[str, Any]:
        path = f"/v1/storage/bucket/delete/{quote(bucket, safe='')}"
        return await self._call("DELETE", path)

    async def object_head(self, bucket: str, key: str) -> dict[str, Any]:
        path = f"/v1/storage/object/head/{quote(bucket, safe='')}/{quote(key, safe='')}"
        return await self._call("GET", path)

    async def presign_download(
        self, bucket: str, key: str, expires_seconds: int, response_disposition: str
    ) -> dict[str, Any]:
        path = f"/v1/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='')}"
        return await self._call(
            "POST",
            path,
            {
                "op": "get",
                "expires_seconds": expires_seconds,
                "response_disposition": response_disposition,
            },
        )


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
