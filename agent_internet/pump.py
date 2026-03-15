from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .control_plane import AgentInternetControlPlane
from .filesystem_transport import FilesystemFederationTransport
from .transport import DeliveryEnvelope, DeliveryReceipt, DeliveryStatus


_DRAINABLE_SUCCESS = {DeliveryStatus.DELIVERED, DeliveryStatus.DUPLICATE}


@dataclass(slots=True)
class OutboxRelayPump:
    plane: AgentInternetControlPlane

    def pump_city_root(
        self,
        root: Path | str,
        *,
        drain_delivered: bool = False,
    ) -> list[DeliveryReceipt]:
        transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
        raw_messages = transport.read_outbox()
        receipts: list[DeliveryReceipt] = []
        remaining: list[dict] = []
        relay_at = time.time()

        for message in raw_messages:
            # TTL clock starts at relay time, not message write time.
            # Without this, every message written more than ~24 s ago
            # (the default Nadi TTL) would expire before the relay even
            # attempts delivery.
            receipt = self.plane.relay_envelope(
                DeliveryEnvelope(
                    source_city_id=str(message.get("source", "")),
                    target_city_id=str(message.get("target", "")),
                    operation=str(message.get("operation", "")),
                    payload=dict(message.get("payload", {})),
                    envelope_id=str(message.get("envelope_id", "")) or str(message.get("correlation_id", "")),
                    correlation_id=str(message.get("correlation_id", "")),
                    created_at=relay_at,
                    ttl_s=float(message.get("ttl_s", 0.0)) or None,
                    nadi_type=str(message.get("nadi_type", "")),
                    nadi_op=str(message.get("nadi_op", "")),
                    priority=str(message.get("nadi_priority", "")),
                    ttl_ms=int(message.get("ttl_ms", 0)) or None,
                    maha_header_hex=str(message.get("maha_header_hex", "")),
                ),
            )
            receipts.append(receipt)
            if not (drain_delivered and receipt.status in _DRAINABLE_SUCCESS):
                remaining.append(message)

        if drain_delivered:
            transport.replace_outbox(remaining)

        return receipts
