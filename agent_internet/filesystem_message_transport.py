from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .filesystem_transport import FilesystemFederationTransport
from .models import CityEndpoint
from .receipt_store import FilesystemReceiptStore
from .steward_protocol_compat import build_maha_message_header_hex
from .steward_substrate import StewardSubstrateBindings, load_steward_substrate
from .transport import DeliveryEnvelope, DeliveryReceipt, DeliveryStatus


@dataclass(slots=True)
class AgentCityFilesystemMessageTransport:
    """Deliver envelopes into the current agent-city federation inbox format."""

    bindings: StewardSubstrateBindings = field(default_factory=load_steward_substrate)

    def send(self, endpoint: CityEndpoint, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        if envelope.is_expired:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.EXPIRED,
                transport=endpoint.transport,
                target_city_id=endpoint.city_id,
                detail="Envelope TTL expired before filesystem delivery",
            )

        root = Path(endpoint.location)
        if not root.exists():
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport=endpoint.transport,
                target_city_id=endpoint.city_id,
                detail=f"Target root does not exist: {root}",
            )

        contract = AgentCityFilesystemContract(root=root)
        transport = FilesystemFederationTransport(contract)
        receipt_store = FilesystemReceiptStore(contract)
        if receipt_store.has_envelope(envelope.envelope_id):
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.DUPLICATE,
                transport=endpoint.transport,
                target_city_id=endpoint.city_id,
                detail="Envelope already recorded in receipt journal",
            )

        semantics = envelope.nadi_semantics
        priority = getattr(self.bindings.NadiPriority, semantics.priority.upper()).value
        message = self.bindings.FederationMessage(
            source=envelope.source_city_id,
            target=envelope.target_city_id,
            operation=envelope.operation,
            payload=dict(envelope.payload),
            priority=priority,
            correlation_id=envelope.correlation_id,
            timestamp=envelope.created_at,
            ttl_s=semantics.ttl_s,
        )
        raw_message = message.to_dict()
        raw_message["envelope_id"] = envelope.envelope_id
        raw_message["nadi_type"] = semantics.nadi_type
        raw_message["nadi_op"] = semantics.nadi_op
        raw_message["nadi_priority"] = semantics.priority
        raw_message["ttl_ms"] = semantics.ttl_ms
        raw_message["maha_header_hex"] = envelope.maha_header_hex or build_maha_message_header_hex(
            source_key=envelope.source_city_id,
            target_key=envelope.target_city_id,
            operation_key=envelope.operation,
            nadi_type=semantics.nadi_type,
            priority=semantics.priority,
            ttl_ms=semantics.ttl_ms,
        )
        transport.append_to_inbox([raw_message])
        receipt_store.record_delivery(
            envelope_id=envelope.envelope_id,
            source_city_id=envelope.source_city_id,
            target_city_id=envelope.target_city_id,
            operation=envelope.operation,
            correlation_id=envelope.correlation_id,
        )
        return DeliveryReceipt(
            envelope_id=envelope.envelope_id,
            status=DeliveryStatus.DELIVERED,
            transport=endpoint.transport,
            target_city_id=endpoint.city_id,
        )

    def receive(self, root: Path | str) -> list[DeliveryEnvelope]:
        transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
        return [self._from_dict(item) for item in transport.read_inbox()]

    def _from_dict(self, data: dict) -> DeliveryEnvelope:
        message = self.bindings.FederationMessage.from_dict(data)
        raw_priority = data.get("nadi_priority")
        if not isinstance(raw_priority, str) or not raw_priority:
            raw_priority = self.bindings.NadiPriority(int(getattr(message, "priority"))).name.lower()
        return DeliveryEnvelope(
            source_city_id=getattr(message, "source"),
            target_city_id=getattr(message, "target"),
            operation=getattr(message, "operation"),
            payload=dict(getattr(message, "payload")),
            envelope_id=str(data.get("envelope_id", "")) or getattr(message, "correlation_id") or "",
            correlation_id=getattr(message, "correlation_id"),
            created_at=float(getattr(message, "timestamp")),
            ttl_s=float(getattr(message, "ttl_s")),
            nadi_type=str(data.get("nadi_type", "")),
            nadi_op=str(data.get("nadi_op", "")),
            priority=raw_priority,
            ttl_ms=int(data.get("ttl_ms", 0)) or None,
            maha_header_hex=str(data.get("maha_header_hex", "")),
        )
