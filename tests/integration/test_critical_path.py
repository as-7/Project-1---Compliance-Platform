"""Critical-path integration test (live).

Exercises the demo flow against a running stack:
  1. Upload a small text snippet via /api/documents
  2. Poll until status is READY (or FAILED)
  3. Assert that controls were extracted and gaps were computed

Run with the full stack up:
    RUN_LIVE=1 pytest tests/integration -k critical_path
"""
from __future__ import annotations

import asyncio
import io

import httpx
import pytest

SAMPLE = b"""Article 5.4 - Storage Limitation
Personal data shall be retained only as long as necessary. Retention schedules
must be documented and reviewed at least annually.

Article 32 - Security of Processing
Implement encryption of personal data and ensure ongoing confidentiality and
integrity of processing systems.
"""


@pytest.mark.live
@pytest.mark.asyncio
async def test_critical_path():
    base = "http://localhost:8080"
    async with httpx.AsyncClient(timeout=180.0) as client:
        files = {"file": ("test.txt", io.BytesIO(SAMPLE), "text/plain")}
        upload = await client.post(f"{base}/api/documents", files=files)
        assert upload.status_code == 201, upload.text
        doc_id = upload.json()["document"]["id"]

        for _ in range(60):
            poll = await client.get(f"{base}/api/documents/{doc_id}")
            assert poll.status_code == 200
            status = poll.json()["status"]
            if status in {"READY", "FAILED"}:
                break
            await asyncio.sleep(2)
        assert status == "READY", f"Document ended in {status}"

        ctrls = await client.get(
            f"{base}/api/controls/regulatory?document_id={doc_id}&limit=200"
        )
        assert ctrls.status_code == 200
        body = ctrls.json()
        assert body["total"] >= 1, "Expected at least one extracted control"

        summary = await client.get(f"{base}/api/gaps/summary")
        assert summary.status_code == 200
        assert summary.json()["total_regulatory_controls"] >= 1
