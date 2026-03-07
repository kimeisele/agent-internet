from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .control_plane import AgentInternetControlPlane
from .models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    HealthStatus,
    HostedEndpoint,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusServiceAddress,
    TrustLevel,
    TrustRecord,
)


def snapshot_control_plane(plane: AgentInternetControlPlane) -> dict:
    return {
        "minimum_trust": plane.minimum_trust.value,
        "identities": [asdict(identity) for identity in plane.registry.list_identities()],
        "endpoints": [asdict(endpoint) for endpoint in plane.registry.list_endpoints()],
        "link_addresses": [asdict(address) for address in plane.registry.list_link_addresses()],
        "network_addresses": [asdict(address) for address in plane.registry.list_network_addresses()],
        "hosted_endpoints": [asdict(endpoint) for endpoint in plane.registry.list_hosted_endpoints()],
        "service_addresses": [asdict(service) for service in plane.registry.list_service_addresses()],
        "api_tokens": [asdict(token) for token in plane.registry.list_api_tokens()],
        "presence": [asdict(presence) for presence in plane.registry.list_cities()],
        "trust": [asdict(record) for record in plane.trust_engine.list_records()],
        "allocator": plane.registry.allocation_state(),
    }


def restore_control_plane(payload: dict) -> AgentInternetControlPlane:
    plane = AgentInternetControlPlane(minimum_trust=TrustLevel(payload.get("minimum_trust", "observed")))

    for data in payload.get("identities", []):
        plane.registry.upsert_identity(CityIdentity(**data))
    for data in payload.get("endpoints", []):
        plane.registry.upsert_endpoint(CityEndpoint(**data))
    for data in payload.get("link_addresses", []):
        plane.registry._link_addresses[data["city_id"]] = LotusLinkAddress(**data)
    for data in payload.get("network_addresses", []):
        plane.registry._network_addresses[data["city_id"]] = LotusNetworkAddress(**data)
    for data in payload.get("hosted_endpoints", []):
        hosted = HostedEndpoint(
            endpoint_id=data["endpoint_id"],
            owner_city_id=data["owner_city_id"],
            public_handle=data["public_handle"],
            transport=data["transport"],
            location=data["location"],
            link_address=data["link_address"],
            network_address=data["network_address"],
            visibility=EndpointVisibility(data.get("visibility", "public")),
            lease_started_at=data.get("lease_started_at"),
            lease_expires_at=data.get("lease_expires_at"),
            labels=dict(data.get("labels", {})),
        )
        plane.registry.upsert_hosted_endpoint(hosted)
    for data in payload.get("service_addresses", []):
        plane.registry.upsert_service_address(
            LotusServiceAddress(
                service_id=data["service_id"],
                owner_city_id=data["owner_city_id"],
                service_name=data["service_name"],
                public_handle=data["public_handle"],
                transport=data["transport"],
                location=data["location"],
                network_address=data["network_address"],
                visibility=EndpointVisibility(data.get("visibility", "federated")),
                auth_required=bool(data.get("auth_required", True)),
                required_scopes=tuple(data.get("required_scopes", ())),
                lease_started_at=data.get("lease_started_at"),
                lease_expires_at=data.get("lease_expires_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("api_tokens", []):
        plane.registry.upsert_api_token(
            LotusApiToken(
                token_id=data["token_id"],
                subject=data["subject"],
                token_hint=data["token_hint"],
                token_sha256=data["token_sha256"],
                scopes=tuple(data.get("scopes", ())),
                issued_at=data.get("issued_at"),
                revoked_at=data.get("revoked_at"),
            ),
        )
    for data in payload.get("presence", []):
        plane.registry.announce(
            CityPresence(
                city_id=data["city_id"],
                health=HealthStatus(data.get("health", "unknown")),
                last_seen_at=data.get("last_seen_at"),
                heartbeat=data.get("heartbeat"),
                capabilities=tuple(data.get("capabilities", ())),
            ),
        )
    for data in payload.get("trust", []):
        plane.trust_engine.record(
            TrustRecord(
                issuer_city_id=data["issuer_city_id"],
                subject_city_id=data["subject_city_id"],
                level=TrustLevel(data.get("level", "unknown")),
                reason=data.get("reason", ""),
            ),
        )
    allocator = payload.get("allocator", {})
    plane.registry.restore_allocation_state(
        next_link_id=allocator.get("next_link_id", len(payload.get("link_addresses", [])) + 1),
        next_network_id=allocator.get("next_network_id", len(payload.get("network_addresses", [])) + 1),
    )

    return plane


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


@dataclass(slots=True)
class ControlPlaneStateStore:
    path: Path

    def load(self) -> AgentInternetControlPlane:
        if not self.path.exists():
            return AgentInternetControlPlane()
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict payload in {self.path}")
        return restore_control_plane(data)

    def save(self, plane: AgentInternetControlPlane) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, snapshot_control_plane(plane))
