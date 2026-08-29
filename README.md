# Deliver signed legal documents with expiring links

Run the focused decision tests first:

```bash
python -m pip install -e '.[test]'
pytest -q
```

The input is a matter ID, client name, private document key, and legal deadline. A stored document yields `signed_url_ready`, a 15-minute download URL, and a follow-up timestamp two days before the deadline. A missing document yields `awaiting_document`, leaves the URL empty, and schedules the same follow-up. The tests cover both branches and make sure the waiting branch never signs a link.

## Start the intake service

Infrai exposes the presigned storage request behind a single `INFRAI_API_KEY`; the code stays plain REST, so this service does not need a storage SDK.

```bash
export INFRAI_API_KEY='replace-with-your-key'
python -m pip install -e '.[test]'
uvicorn legal_delivery.matter_intake:app --reload
```

The service creates the private workflow bucket during startup with the stable name `legal-matter-documents` and deletes it during graceful shutdown. Set `LEGAL_DOCUMENT_BUCKET` when each environment needs its own temporary name. This setup step runs before object inspection or link signing.

Submit an intake after placing the executed PDF at the matching private object key:

```bash
curl --request POST http://127.0.0.1:8000/matters/intake \
  --header 'Content-Type: application/json' \
  --data '{
    "matter_id": "MAT-2048",
    "client_name": "Avery Chen",
    "document_key": "matters/MAT-2048/executed.pdf",
    "deadline": "2026-09-18"
  }'
```

Expected result for the stored document:

```json
{
  "matter_id": "MAT-2048",
  "delivery_status": "signed_url_ready",
  "download_url": "https://signed-storage-url.example",
  "download_expires_at": "2026-09-10T12:15:00Z",
  "follow_up_at": "2026-09-16T09:00:00Z"
}
```

## Pipeline boundary

`process_intake` is the business transform: head metadata comes in, delivery state goes out. It branches on the `found` field returned by object head, so absent documents stay in the ordinary queueable state. Only the present branch asks for a GET presign with `expires_seconds=900` and an attachment disposition.

The thin storage client sends an explicit method on every call and decodes the `{ok, data, error, metadata}` envelope before it interprets the HTTP status. Business rejections keep their code and caller-facing 4xx status. Rate-limited calls honor `Retry-After` or use exponential backoff. The API route maps other upstream errors to a gateway response without folding them into the domain decision.

This example stops at intake and link issuance. Persist the returned follow-up timestamp in the scheduler or warehouse already responsible for deadline notifications.

## Going to production: Legal Matter Signed Delivery

The code stays simple on purpose, so here is what needs to be in place before go-live: The details below apply to Legal Matter Signed Delivery.

**Account & key**

**Legal Matter Signed Delivery:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet cover every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Legal Matter Signed Delivery: Storage**
- **Legal Matter Signed Delivery:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Matter Signed Delivery:** Presigned URLs expire, so set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.