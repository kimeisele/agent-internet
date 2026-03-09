"""Contract verification and health probes for semantic capabilities.

Validates that cities actually provide the capabilities they advertise in
their semantic contracts.  Supports both passive verification (schema checks)
and active probing (liveness and capability checks).
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex

logger = logging.getLogger(__name__)


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    SKIPPED = "skipped"


class ProbeKind(StrEnum):
    LIVENESS = "liveness"
    CAPABILITY_SCHEMA = "capability_schema"
    CONTRACT_COMPLIANCE = "contract_compliance"
    PERFORMANCE = "performance"
    FEDERATION_REACHABILITY = "federation_reachability"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Result of a single health probe."""

    probe_id: str = field(default_factory=lambda: f"prb_{token_hex(6)}")
    kind: ProbeKind = ProbeKind.LIVENESS
    target_city_id: str = ""
    target_service: str = ""
    status: VerificationStatus = VerificationStatus.SKIPPED
    latency_ms: float = 0.0
    detail: str = ""
    checked_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContractVerificationResult:
    """Aggregate result of verifying a city's advertised contracts."""

    verification_id: str = field(default_factory=lambda: f"ver_{token_hex(6)}")
    city_id: str = ""
    contract_name: str = ""
    contract_version: str = ""
    overall_status: VerificationStatus = VerificationStatus.SKIPPED
    probes: tuple[ProbeResult, ...] = ()
    verified_at: float = field(default_factory=time.time)
    violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """A single capability claimed by a city."""

    name: str
    version: str = "1.0"
    transport: str = ""
    endpoint: str = ""
    required_scopes: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContractManifest:
    """A published contract declaring what a city provides."""

    manifest_id: str = field(default_factory=lambda: f"man_{token_hex(6)}")
    city_id: str = ""
    contract_name: str = ""
    contract_version: str = "1.0"
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    published_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


class ContractProbe:
    """Base class for contract verification probes."""

    kind: ProbeKind = ProbeKind.LIVENESS

    def probe(self, city_id: str, capability: CapabilityDescriptor) -> ProbeResult:
        return ProbeResult(
            kind=self.kind,
            target_city_id=city_id,
            target_service=capability.name,
            status=VerificationStatus.SKIPPED,
            detail="Base probe does not execute",
        )


@dataclass(slots=True)
class LivenessProbe(ContractProbe):
    """Checks if a city's endpoint is reachable."""

    kind: ProbeKind = ProbeKind.LIVENESS
    timeout_s: float = 5.0

    def probe(self, city_id: str, capability: CapabilityDescriptor) -> ProbeResult:
        start = time.time()
        if not capability.endpoint:
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.SKIPPED,
                detail="No endpoint configured",
            )

        try:
            from urllib.request import urlopen, Request

            req = Request(capability.endpoint, method="HEAD")
            req.add_header("User-Agent", "agent-internet-probe/0.2.0")
            resp = urlopen(req, timeout=self.timeout_s)
            latency = (time.time() - start) * 1000
            status = VerificationStatus.PASSED if resp.status < 400 else VerificationStatus.DEGRADED
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=status,
                latency_ms=latency,
                detail=f"HTTP {resp.status}",
            )
        except Exception as exc:
            latency = (time.time() - start) * 1000
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.UNREACHABLE,
                latency_ms=latency,
                detail=f"{type(exc).__name__}: {exc}",
            )


@dataclass(slots=True)
class SchemaProbe(ContractProbe):
    """Validates a capability against its declared schema."""

    kind: ProbeKind = ProbeKind.CAPABILITY_SCHEMA

    def probe(self, city_id: str, capability: CapabilityDescriptor) -> ProbeResult:
        violations: list[str] = []
        if not capability.name:
            violations.append("Missing capability name")
        if not capability.version:
            violations.append("Missing version")

        if violations:
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.FAILED,
                detail="; ".join(violations),
                metadata={"violations": violations},
            )
        return ProbeResult(
            kind=self.kind,
            target_city_id=city_id,
            target_service=capability.name,
            status=VerificationStatus.PASSED,
            detail="Schema valid",
        )


@dataclass(slots=True)
class FederationReachabilityProbe(ContractProbe):
    """Checks if a city is reachable via the federation transport."""

    kind: ProbeKind = ProbeKind.FEDERATION_REACHABILITY
    discovery: object = None

    def probe(self, city_id: str, capability: CapabilityDescriptor) -> ProbeResult:
        if self.discovery is None:
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.SKIPPED,
                detail="No discovery service available",
            )

        presence = getattr(self.discovery, "get_presence", lambda _: None)(city_id)
        if presence is None:
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.UNREACHABLE,
                detail="City not found in discovery",
            )

        health = getattr(presence, "health", "unknown")
        if str(health) == "offline":
            return ProbeResult(
                kind=self.kind,
                target_city_id=city_id,
                target_service=capability.name,
                status=VerificationStatus.UNREACHABLE,
                detail=f"City health: {health}",
            )

        return ProbeResult(
            kind=self.kind,
            target_city_id=city_id,
            target_service=capability.name,
            status=VerificationStatus.PASSED,
            detail=f"City reachable, health: {health}",
        )


@dataclass(slots=True)
class ContractVerifier:
    """Orchestrates contract verification across multiple probes."""

    _probes: list[ContractProbe] = field(default_factory=list)
    _manifests: dict[str, ContractManifest] = field(default_factory=dict)
    _results: list[ContractVerificationResult] = field(default_factory=list)

    @classmethod
    def with_defaults(cls, *, discovery: object = None) -> ContractVerifier:
        """Create a verifier with standard probes."""
        return cls(
            _probes=[
                LivenessProbe(),
                SchemaProbe(),
                FederationReachabilityProbe(discovery=discovery),
            ],
        )

    def register_manifest(self, manifest: ContractManifest) -> None:
        self._manifests[manifest.manifest_id] = manifest

    def register_probe(self, probe: ContractProbe) -> None:
        self._probes.append(probe)

    def verify_manifest(self, manifest: ContractManifest) -> ContractVerificationResult:
        """Run all probes against all capabilities in a manifest."""
        all_probes: list[ProbeResult] = []
        violations: list[str] = []

        for capability in manifest.capabilities:
            for probe in self._probes:
                result = probe.probe(manifest.city_id, capability)
                all_probes.append(result)
                if result.status == VerificationStatus.FAILED:
                    violations.append(f"{capability.name}: {result.detail}")

        if violations:
            overall = VerificationStatus.FAILED
        elif any(p.status == VerificationStatus.UNREACHABLE for p in all_probes):
            overall = VerificationStatus.UNREACHABLE
        elif any(p.status == VerificationStatus.DEGRADED for p in all_probes):
            overall = VerificationStatus.DEGRADED
        elif all(p.status in (VerificationStatus.PASSED, VerificationStatus.SKIPPED) for p in all_probes):
            overall = VerificationStatus.PASSED
        else:
            overall = VerificationStatus.SKIPPED

        result = ContractVerificationResult(
            city_id=manifest.city_id,
            contract_name=manifest.contract_name,
            contract_version=manifest.contract_version,
            overall_status=overall,
            probes=tuple(all_probes),
            violations=tuple(violations),
        )
        self._results.append(result)
        return result

    def verify_city(self, city_id: str) -> list[ContractVerificationResult]:
        """Verify all manifests published by a city."""
        results: list[ContractVerificationResult] = []
        for manifest in self._manifests.values():
            if manifest.city_id == city_id:
                results.append(self.verify_manifest(manifest))
        return results

    def verify_all(self) -> list[ContractVerificationResult]:
        """Verify all registered manifests."""
        return [self.verify_manifest(m) for m in self._manifests.values()]

    def results(self) -> list[ContractVerificationResult]:
        return list(self._results)
