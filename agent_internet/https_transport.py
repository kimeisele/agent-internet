"""HTTPS transport for real network federation between cities.

Implements envelope delivery over HTTP POST, enabling cities to communicate
across network boundaries without shared filesystem access.
"""

from __future__ import annotations

import json
import time
import logging
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPSConnection
from secrets import token_hex
from urllib.parse import urlparse

from .models import CityEndpoint
from .transport import DeliveryEnvelope, DeliveryReceipt, DeliveryStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpsTransportConfig:
    """Configuration for HTTPS transport behavior."""

    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_retries: int = 3
    retry_backoff_base_s: float = 1.0
    user_agent: str = "agent-internet/0.2.0"
    verify_tls: bool = True
    bearer_token: str = ""
    max_payload_bytes: int = 1_048_576  # 1 MiB


def _envelope_to_wire(envelope: DeliveryEnvelope) -> dict:
    """Serialize an envelope to wire format."""
    return {
        "envelope_id": envelope.envelope_id,
        "source_city_id": envelope.source_city_id,
        "target_city_id": envelope.target_city_id,
        "operation": envelope.operation,
        "payload": envelope.payload,
        "correlation_id": envelope.correlation_id,
        "content_type": envelope.content_type,
        "created_at": envelope.created_at,
        "ttl_s": envelope.ttl_s,
        "nadi_type": envelope.nadi_type,
        "nadi_op": envelope.nadi_op,
        "priority": envelope.priority,
        "ttl_ms": envelope.ttl_ms,
        "maha_header_hex": envelope.maha_header_hex,
    }


def _envelope_from_wire(data: dict) -> DeliveryEnvelope:
    """Deserialize an envelope from wire format."""
    return DeliveryEnvelope(
        envelope_id=data.get("envelope_id", f"env_{token_hex(8)}"),
        source_city_id=data.get("source_city_id", ""),
        target_city_id=data.get("target_city_id", ""),
        operation=data.get("operation", ""),
        payload=data.get("payload", {}),
        correlation_id=data.get("correlation_id", ""),
        content_type=data.get("content_type", "application/json"),
        created_at=data.get("created_at", time.time()),
        ttl_s=data.get("ttl_s"),
        nadi_type=data.get("nadi_type", ""),
        nadi_op=data.get("nadi_op", ""),
        priority=data.get("priority", ""),
        ttl_ms=data.get("ttl_ms"),
        maha_header_hex=data.get("maha_header_hex", ""),
    )


@dataclass(slots=True)
class HttpsTransport:
    """HTTPS-based federation transport.

    Sends delivery envelopes as JSON over HTTP(S) POST to a target city's
    ingress endpoint.  The endpoint ``location`` is expected to be a URL
    like ``https://city.example.com/lotus/inbox``.
    """

    config: HttpsTransportConfig = field(default_factory=HttpsTransportConfig)
    _delivery_log: list[DeliveryReceipt] = field(default_factory=list)

    def send(self, endpoint: CityEndpoint, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        """Send an envelope to a remote city via HTTP(S) POST."""
        if envelope.is_expired:
            receipt = DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.EXPIRED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail="Envelope TTL expired before delivery",
            )
            self._delivery_log.append(receipt)
            return receipt

        wire = _envelope_to_wire(envelope)
        body = json.dumps(wire).encode("utf-8")

        if len(body) > self.config.max_payload_bytes:
            receipt = DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail=f"Payload exceeds max size ({len(body)} > {self.config.max_payload_bytes})",
            )
            self._delivery_log.append(receipt)
            return receipt

        last_error = ""
        for attempt in range(self.config.max_retries):
            try:
                status_code, response_body = self._do_post(endpoint.location, body)
                if 200 <= status_code < 300:
                    receipt = DeliveryReceipt(
                        envelope_id=envelope.envelope_id,
                        status=DeliveryStatus.DELIVERED,
                        transport="https",
                        target_city_id=endpoint.city_id,
                        detail=f"HTTP {status_code}",
                    )
                    self._delivery_log.append(receipt)
                    return receipt
                elif status_code == 409:
                    receipt = DeliveryReceipt(
                        envelope_id=envelope.envelope_id,
                        status=DeliveryStatus.DUPLICATE,
                        transport="https",
                        target_city_id=endpoint.city_id,
                        detail=f"HTTP {status_code}: duplicate envelope",
                    )
                    self._delivery_log.append(receipt)
                    return receipt
                elif status_code >= 500:
                    last_error = f"HTTP {status_code}: {response_body[:200]}"
                    if attempt < self.config.max_retries - 1:
                        time.sleep(self.config.retry_backoff_base_s * (2 ** attempt))
                        continue
                else:
                    receipt = DeliveryReceipt(
                        envelope_id=envelope.envelope_id,
                        status=DeliveryStatus.REJECTED,
                        transport="https",
                        target_city_id=endpoint.city_id,
                        detail=f"HTTP {status_code}: {response_body[:200]}",
                    )
                    self._delivery_log.append(receipt)
                    return receipt
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "HTTPS transport attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self.config.max_retries,
                    endpoint.city_id,
                    last_error,
                )
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_backoff_base_s * (2 ** attempt))

        receipt = DeliveryReceipt(
            envelope_id=envelope.envelope_id,
            status=DeliveryStatus.REJECTED,
            transport="https",
            target_city_id=endpoint.city_id,
            detail=f"All {self.config.max_retries} attempts failed: {last_error}",
        )
        self._delivery_log.append(receipt)
        return receipt

    def _do_post(self, url: str, body: bytes) -> tuple[int, str]:
        """Execute a single HTTP(S) POST request."""
        parsed = urlparse(url)
        is_https = parsed.scheme == "https"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if is_https else 80)
        path = parsed.path or "/lotus/inbox"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
        }
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"

        conn_cls = HTTPSConnection if is_https else HTTPConnection
        conn = conn_cls(host, port, timeout=self.config.connect_timeout_s)
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp_body
        finally:
            conn.close()

    def receive_from_wire(self, raw: bytes | str) -> DeliveryEnvelope:
        """Parse an incoming envelope from wire bytes (for the receiving side)."""
        data = json.loads(raw)
        return _envelope_from_wire(data)

    def delivery_log(self) -> list[DeliveryReceipt]:
        return list(self._delivery_log)
