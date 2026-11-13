"""Read-only client for the Phone Cloud daily XHS batch API."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from urllib.parse import urlsplit

import httpx


class CloudDataError(ValueError):
    """Safe error code: never include an upstream body or credential."""


class PhoneCloudXHSDataClient:
    PREFIX = "/api/v1/open/xhs-data"

    def __init__(self, base_url: str, client_id: str, secret: str, *,
                 http_origins: str = "", transport: httpx.AsyncBaseTransport | None = None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise CloudDataError("cloud_data_invalid_base_url")
        try:
            parsed.port
        except ValueError:
            raise CloudDataError("cloud_data_invalid_base_url") from None
        self.base = base_url.rstrip("/")
        if parsed.scheme == "http" and self.base not in {v.strip().rstrip("/") for v in http_origins.split(",")}:
            raise CloudDataError("cloud_data_http_origin_not_approved")
        if not client_id or not secret:
            raise CloudDataError("cloud_data_credentials_missing")
        self.client_id, self.secret = client_id, secret
        self.transport = transport

    async def _get(self, path: str) -> dict:
        timestamp, nonce = str(int(time.time() * 1000)), str(uuid.uuid4())
        canonical = "\n".join(("GET", path, timestamp, nonce, hashlib.sha256(b"").hexdigest()))
        headers = {"X-Client-Id": self.client_id, "X-Timestamp": timestamp, "X-Nonce": nonce,
                   "X-Signature": hmac.new(self.secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()}
        try:
            async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False,
                                         transport=self.transport) as client:
                async with client.stream("GET", self.base + path, headers=headers) as response:
                    if response.status_code != 200:
                        raise CloudDataError(f"cloud_data_http_{response.status_code}")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 3_000_000:
                            raise CloudDataError("cloud_data_response_too_large")
                        chunks.append(chunk)
            body = json.loads(b"".join(chunks))
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
            raise CloudDataError("cloud_data_transport_or_json_error") from None
        if not isinstance(body, dict):
            raise CloudDataError("cloud_data_invalid_response")
        return body

    async def _pages(self, suffix: str, key: str, *, run_id: str | None = None):
        offset, seen = 0, set()
        for _ in range(100):
            query = f"{suffix}?offset={offset}" + ("&limit=10" if run_id else "")
            body = await self._get(self.PREFIX + query)
            if body.get("offset") != offset or not isinstance(body.get(key), list):
                raise CloudDataError("cloud_data_invalid_pagination")
            if run_id and body.get("runId") != run_id:
                raise CloudDataError("cloud_data_run_identity_mismatch")
            yield body
            following = body.get("nextOffset")
            if following is None:
                return
            if (type(following) is not int or following != offset + len(body[key])
                    or following <= offset or following in seen or not body[key]):
                raise CloudDataError("cloud_data_invalid_pagination")
            seen.add(offset)
            offset = following
        raise CloudDataError("cloud_data_pagination_budget_exhausted")

    async def latest_items(self, xhs_ids: set[str], *, max_batches: int = 5) -> dict[str, tuple[str, dict]]:
        """Read newest account observations; a new failure never becomes an old success."""
        summaries = []
        async for page in self._pages("/batches", "batches"):
            summaries.extend(page["batches"])
            if len(summaries) >= max_batches:
                break
        for item in summaries:
            if (not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("runId", "")))
                    or not isinstance(item.get("createdAt"), str)):
                raise CloudDataError("cloud_data_invalid_batch")
        summaries.sort(key=lambda item: item["createdAt"], reverse=True)
        found = {}
        seen_runs = set()
        for summary in summaries[:max_batches]:
            run_id = summary["runId"]
            if run_id in seen_runs:
                raise CloudDataError("cloud_data_duplicate_batch")
            seen_runs.add(run_id)
            batch_items, seen_items, seen_accounts = [], set(), set()
            expected_count = None
            async for page in self._pages(f"/batches/{run_id}", "items", run_id=run_id):
                counts = page.get("counts")
                if not isinstance(counts, dict):
                    raise CloudDataError("cloud_data_invalid_batch_count")
                total = counts.get("total")
                if type(total) is not int or total < 0 or (expected_count is not None and total != expected_count):
                    raise CloudDataError("cloud_data_invalid_batch_count")
                expected_count = total
                for item in page["items"]:
                    if not isinstance(item, dict) or not str(item.get("itemId", "")).isdigit():
                        raise CloudDataError("cloud_data_invalid_item")
                    xid = str(item.get("xhsId", ""))
                    if item["itemId"] in seen_items or xid in seen_accounts:
                        raise CloudDataError("cloud_data_duplicate_item_or_account")
                    seen_items.add(item["itemId"])
                    seen_accounts.add(xid)
                    if xid in xhs_ids and xid not in found:
                        batch_items.append(item)
            if len(seen_items) != expected_count:
                raise CloudDataError("cloud_data_incomplete_batch_pages")
            for item in batch_items:
                xid = str(item.get("xhsId", ""))
                if xid in xhs_ids and xid not in found:
                    found[xid] = (run_id, item)
            if xhs_ids <= found.keys():
                break
        return found
