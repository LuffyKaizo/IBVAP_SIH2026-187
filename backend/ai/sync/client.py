"""Central synchronization HTTP client.

Communicates with the central IBVAP server to push events, evidence metadata,
and evidence files. Classifies failures for retry decisions.

Supports Edge node authentication via short-lived JWTs (Section 14).
Falls back to API key authentication if Edge token manager is not configured.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger("ibvap.sync")


@dataclass
class SyncResult:
    success: bool
    status_code: int = 0
    error: Optional[str] = None
    retryable: bool = False


class CentralSyncClient:
    """HTTP client for communicating with the central IBVAP sync API.

    Authentication priority:
    1. Edge JWT token (if edge_token_manager is configured)
    2. X-API-Key header (if api_key is set)
    3. No authentication (last resort)
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: int = 15,
        verify_tls: bool = True,
        ca_bundle: str = "",
        edge_token_manager=None,
        edge_token_refresh_sec: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._verify_tls = verify_tls
        self._ca_bundle = ca_bundle
        self._edge_token_manager = edge_token_manager
        self._edge_token_refresh_sec = edge_token_refresh_sec
        self._client: Optional[httpx.AsyncClient] = None
        self._edge_token: Optional[str] = None
        self._edge_token_expires: float = 0
        self._retrying_401: bool = False

    async def _ensure_client(self):
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self._api_key and not self._edge_token_manager:
                headers["X-API-Key"] = self._api_key
            verify = self._verify_tls
            if self._ca_bundle:
                verify = self._ca_bundle
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
                verify=verify,
            )

    async def _get_edge_token(self) -> Optional[str]:
        """Acquire or refresh Edge JWT token."""
        if not self._edge_token_manager:
            return None

        import time
        now = time.time()

        # Refresh if token is missing or near expiry
        if self._edge_token and now < self._edge_token_expires:
            return self._edge_token

        try:
            from ai.config import settings
            node_id = settings.EDGE_NODE_ID
            if not node_id:
                return None

            # Create a fresh token using the node_id
            token = self._edge_token_manager.create_token(node_id)
            self._edge_token = token
            self._edge_token_expires = now + (settings.EDGE_TOKEN_TTL_SECONDS - self._edge_token_refresh_sec)
            return token
        except Exception as e:
            logger.warning("[SYNC] Failed to acquire Edge token: %s", type(e).__name__)
            return None

    def _invalidate_edge_token(self) -> None:
        """Invalidate cached Edge token (e.g. on 401)."""
        self._edge_token = None
        self._edge_token_expires = 0

    def _build_auth_headers(self) -> dict:
        """Build authentication headers for requests."""
        headers = {}
        if self._edge_token:
            headers["Authorization"] = f"Bearer {self._edge_token}"
        elif self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def health_check(self) -> bool:
        """Check if central server is reachable."""
        try:
            await self._ensure_client()
            token = await self._get_edge_token()
            headers = self._build_auth_headers()
            resp = await self._client.get("/health", headers=headers)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
            return False
        except Exception:
            return False

    async def push_event(self, event_payload: dict, sync_id: str) -> SyncResult:
        """Push event metadata to central server."""
        try:
            await self._ensure_client()
            token = await self._get_edge_token()
            payload = {**event_payload, "sync_id": sync_id}
            headers = self._build_auth_headers()
            resp = await self._client.post("/sync/events", json=payload, headers=headers)
            result = self._classify_response(resp)

            # 401 → refresh token and retry once
            if result.status_code == 401 and not self._retrying_401:
                self._invalidate_edge_token()
                self._retrying_401 = True
                try:
                    return await self.push_event(event_payload, sync_id)
                finally:
                    self._retrying_401 = False

            return result
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
            return SyncResult(success=False, error=str(e), retryable=True)
        except Exception as e:
            return SyncResult(success=False, error=str(e), retryable=False)

    async def push_evidence_metadata(self, evidence_payload: dict, sync_id: str) -> SyncResult:
        """Push evidence metadata to central server."""
        try:
            await self._ensure_client()
            token = await self._get_edge_token()
            payload = {**evidence_payload, "sync_id": sync_id}
            headers = self._build_auth_headers()
            resp = await self._client.post("/sync/evidence", json=payload, headers=headers)
            result = self._classify_response(resp)

            if result.status_code == 401 and not self._retrying_401:
                self._invalidate_edge_token()
                self._retrying_401 = True
                try:
                    return await self.push_evidence_metadata(evidence_payload, sync_id)
                finally:
                    self._retrying_401 = False

            return result
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
            return SyncResult(success=False, error=str(e), retryable=True)
        except Exception as e:
            return SyncResult(success=False, error=str(e), retryable=False)

    async def push_evidence_file(
        self, evidence_id: str, file_bytes: bytes, sha256: str, sync_id: str
    ) -> SyncResult:
        """Push evidence file to central server with integrity verification."""
        try:
            await self._ensure_client()
            token = await self._get_edge_token()
            headers = {
                "Content-Type": "application/octet-stream",
                "X-SHA256": sha256,
                "X-Sync-ID": sync_id,
            }
            auth_headers = self._build_auth_headers()
            headers.update(auth_headers)
            resp = await self._client.post(
                f"/sync/evidence/{evidence_id}/file",
                content=file_bytes,
                headers=headers,
            )
            result = self._classify_response(resp)

            if result.status_code == 401 and not self._retrying_401:
                self._invalidate_edge_token()
                self._retrying_401 = True
                try:
                    return await self.push_evidence_file(evidence_id, file_bytes, sha256, sync_id)
                finally:
                    self._retrying_401 = False

            return result
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
            return SyncResult(success=False, error=str(e), retryable=True)
        except Exception as e:
            return SyncResult(success=False, error=str(e), retryable=False)

    def _classify_response(self, resp: httpx.Response) -> SyncResult:
        """Classify HTTP response for retry decisions."""
        code = resp.status_code
        if 200 <= code < 300:
            return SyncResult(success=True, status_code=code)
        if code == 429:
            return SyncResult(success=False, status_code=code, error="rate_limited", retryable=True)
        if code in (401, 403):
            return SyncResult(success=False, status_code=code, error="auth_error", retryable=False)
        if code >= 500:
            return SyncResult(success=False, status_code=code, error="server_error", retryable=True)
        # Other 4xx — validation error, not retryable
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        return SyncResult(success=False, status_code=code, error=detail, retryable=False)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
