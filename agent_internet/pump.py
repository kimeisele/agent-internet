from __future__ import annotations

import time
import uuid
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
        source_city_id: str = "",
    ) -> list[DeliveryReceipt]:
        transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
        raw_messages = transport.read_outbox()
        if not raw_messages:
            return []

        # Assign envelope_ids to messages that don't have one, then persist
        # back so remove_from_outbox can match them during drain.
        enriched = False
        for message in raw_messages:
            existing_id = str(message.get("envelope_id", "")) or str(message.get("correlation_id", ""))
            if not existing_id:
                generated = str(uuid.uuid4())
                message["envelope_id"] = generated
                message["correlation_id"] = generated
                enriched = True
        if enriched:
            transport.replace_outbox(raw_messages)

        receipts: list[DeliveryReceipt] = []
        relay_at = time.time()
        delivered_ids: set[str] = set()

        for message in raw_messages:
            envelope_id = str(message.get("envelope_id", "")) or str(message.get("correlation_id", ""))
            # TTL clock starts at relay time, not message write time.
            # Without this, every message written more than ~24 s ago
            # (the default Nadi TTL) would expire before the relay even
            # attempts delivery.
            # Use explicit source_city_id when provided — message "source"
            # field may contain internal identifiers (e.g. MURALI phase
            # names like "moksha") instead of the federation city_id.
            effective_source = source_city_id or str(message.get("source", ""))
            receipt = self.plane.relay_envelope(
                DeliveryEnvelope(
                    source_city_id=effective_source,
                    target_city_id=str(message.get("target", "")),
                    operation=str(message.get("operation", "")),
                    payload=dict(message.get("payload", {})),
                    envelope_id=envelope_id,
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
            if receipt.status in _DRAINABLE_SUCCESS and envelope_id:
                delivered_ids.add(envelope_id)

        # Atomic drain: remove only delivered messages from the current
        # outbox contents.  Messages that arrived after our initial read
        # are preserved because remove_from_outbox re-reads the file
        # under an exclusive lock.
        if drain_delivered and delivered_ids:
            transport.remove_from_outbox(delivered_ids)

        return receipts
