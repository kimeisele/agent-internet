"""Enhanced trust engine with expiration, evidence chains, and revocation.

Builds on the simple trust ledger with time-bound trust, evidence-based
decisions, revocation tracking, and trust delegation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex

from .models import TrustLevel, TrustRecord


_TRUST_RANK = {
    TrustLevel.UNKNOWN: 0,
    TrustLevel.OBSERVED: 1,
    TrustLevel.VERIFIED: 2,
    TrustLevel.TRUSTED: 3,
}


def trust_rank(level: TrustLevel) -> int:
    return _TRUST_RANK.get(level, 0)


class EvidenceKind(StrEnum):
    MANUAL_ATTESTATION = "manual_attestation"
    MUTUAL_HEARTBEAT = "mutual_heartbeat"
    SHARED_SECRET_VERIFIED = "shared_secret_verified"
    PUBLIC_KEY_VERIFIED = "public_key_verified"
    DELEGATION_CHAIN = "delegation_chain"
    FEDERATION_HANDSHAKE = "federation_handshake"
    BEHAVIORAL_OBSERVATION = "behavioral_observation"
    CONTRACT_COMPLIANCE = "contract_compliance"
    REPUTATION_SCORE = "reputation_score"


class RevocationReason(StrEnum):
    MANUAL_REVOCATION = "manual_revocation"
    TRUST_EXPIRED = "trust_expired"
    EVIDENCE_INVALIDATED = "evidence_invalidated"
    BEHAVIORAL_VIOLATION = "behavioral_violation"
    CONTRACT_BREACH = "contract_breach"
    KEY_COMPROMISE = "key_compromise"
    DELEGATION_REVOKED = "delegation_revoked"


@dataclass(frozen=True, slots=True)
class TrustEvidence:
    """A single piece of evidence supporting a trust claim."""

    evidence_id: str = field(default_factory=lambda: f"evi_{token_hex(6)}")
    kind: EvidenceKind = EvidenceKind.MANUAL_ATTESTATION
    description: str = ""
    observed_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at


@dataclass(frozen=True, slots=True)
class EnhancedTrustRecord:
    """Trust record with expiration, evidence, and revocation tracking."""

    record_id: str = field(default_factory=lambda: f"tr_{token_hex(6)}")
    issuer_city_id: str = ""
    subject_city_id: str = ""
    level: TrustLevel = TrustLevel.UNKNOWN
    reason: str = ""
    evidence: tuple[TrustEvidence, ...] = ()
    established_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    revoked_at: float | None = None
    revocation_reason: RevocationReason | None = None
    delegated_from: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        now = time.time()
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and now > self.expires_at:
            return False
        return True

    @property
    def active_evidence(self) -> tuple[TrustEvidence, ...]:
        return tuple(e for e in self.evidence if not e.is_expired)

    @property
    def aggregate_confidence(self) -> float:
        active = self.active_evidence
        if not active:
            return 0.0
        return sum(e.confidence for e in active) / len(active)

    def to_basic_record(self) -> TrustRecord:
        """Downcast to the base TrustRecord for backward compatibility."""
        return TrustRecord(
            issuer_city_id=self.issuer_city_id,
            subject_city_id=self.subject_city_id,
            level=self.level,
            reason=self.reason,
        )


@dataclass(frozen=True, slots=True)
class TrustDelegation:
    """Records a delegation of trust from one city to another."""

    delegation_id: str = field(default_factory=lambda: f"del_{token_hex(6)}")
    delegator_city_id: str = ""
    delegate_city_id: str = ""
    subject_city_id: str = ""
    max_level: TrustLevel = TrustLevel.VERIFIED
    expires_at: float | None = None
    revoked_at: float | None = None
    reason: str = ""


@dataclass(slots=True)
class EnhancedTrustEngine:
    """Trust engine with expiration, evidence chains, delegation, and revocation.

    Backward-compatible with the TrustEngine protocol — supports ``record()``
    and ``evaluate()`` — while adding richer semantics.
    """

    _records: dict[tuple[str, str], EnhancedTrustRecord] = field(default_factory=dict)
    _delegations: dict[str, TrustDelegation] = field(default_factory=dict)
    _revocation_log: list[tuple[float, str, str, RevocationReason]] = field(default_factory=list)
    _default_level: TrustLevel = TrustLevel.UNKNOWN
    default_ttl_s: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --- TrustEngine protocol compat ---

    def record(self, trust: TrustRecord) -> None:
        """Accept a basic TrustRecord (backward compat with TrustEngine protocol)."""
        with self._lock:
            key = (trust.issuer_city_id, trust.subject_city_id)
            existing = self._records.get(key)
            evidence: tuple[TrustEvidence, ...] = ()
            if existing is not None:
                evidence = existing.evidence
            enhanced = EnhancedTrustRecord(
                issuer_city_id=trust.issuer_city_id,
                subject_city_id=trust.subject_city_id,
                level=trust.level,
                reason=trust.reason,
                evidence=evidence,
                expires_at=(time.time() + self.default_ttl_s) if self.default_ttl_s else None,
            )
            self._records[key] = enhanced

    def evaluate(self, source_city_id: str, target_city_id: str) -> TrustLevel:
        """Evaluate trust level, accounting for expiration and revocation."""
        if source_city_id == target_city_id:
            return TrustLevel.TRUSTED

        with self._lock:
            record = self._records.get((source_city_id, target_city_id))
            if record is None:
                return self._evaluate_delegated(source_city_id, target_city_id)

            if not record.is_active:
                return self._default_level

            return record.level

    # --- Enhanced API ---

    def record_enhanced(self, record: EnhancedTrustRecord) -> None:
        """Record an enhanced trust record with full metadata."""
        with self._lock:
            key = (record.issuer_city_id, record.subject_city_id)
            self._records[key] = record

    def get_record(self, source_city_id: str, target_city_id: str) -> EnhancedTrustRecord | None:
        with self._lock:
            record = self._records.get((source_city_id, target_city_id))
            if record is not None and not record.is_active:
                return None
            return record

    def list_records(self) -> list[TrustRecord]:
        """Return active records as basic TrustRecords for compat."""
        with self._lock:
            return [r.to_basic_record() for r in sorted(self._records.values(), key=lambda r: (r.issuer_city_id, r.subject_city_id)) if r.is_active]

    def list_enhanced_records(self) -> list[EnhancedTrustRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: (r.issuer_city_id, r.subject_city_id))

    def add_evidence(
        self,
        source_city_id: str,
        target_city_id: str,
        evidence: TrustEvidence,
    ) -> EnhancedTrustRecord | None:
        """Append evidence to an existing trust record."""
        with self._lock:
            key = (source_city_id, target_city_id)
            record = self._records.get(key)
            if record is None:
                return None
            updated = EnhancedTrustRecord(
                record_id=record.record_id,
                issuer_city_id=record.issuer_city_id,
                subject_city_id=record.subject_city_id,
                level=record.level,
                reason=record.reason,
                evidence=record.evidence + (evidence,),
                established_at=record.established_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
                revocation_reason=record.revocation_reason,
                delegated_from=record.delegated_from,
                labels=record.labels,
            )
            self._records[key] = updated
            return updated

    def revoke(
        self,
        source_city_id: str,
        target_city_id: str,
        reason: RevocationReason = RevocationReason.MANUAL_REVOCATION,
    ) -> EnhancedTrustRecord | None:
        """Revoke trust between two cities."""
        with self._lock:
            key = (source_city_id, target_city_id)
            record = self._records.get(key)
            if record is None:
                return None
            now = time.time()
            revoked = EnhancedTrustRecord(
                record_id=record.record_id,
                issuer_city_id=record.issuer_city_id,
                subject_city_id=record.subject_city_id,
                level=record.level,
                reason=record.reason,
                evidence=record.evidence,
                established_at=record.established_at,
                expires_at=record.expires_at,
                revoked_at=now,
                revocation_reason=reason,
                delegated_from=record.delegated_from,
                labels=record.labels,
            )
            self._records[key] = revoked
            self._revocation_log.append((now, source_city_id, target_city_id, reason))
            return revoked

    def register_delegation(self, delegation: TrustDelegation) -> None:
        """Register a trust delegation from one city to another."""
        with self._lock:
            self._delegations[delegation.delegation_id] = delegation

    def revoke_delegation(self, delegation_id: str) -> TrustDelegation | None:
        with self._lock:
            delegation = self._delegations.get(delegation_id)
            if delegation is None:
                return None
            revoked = TrustDelegation(
                delegation_id=delegation.delegation_id,
                delegator_city_id=delegation.delegator_city_id,
                delegate_city_id=delegation.delegate_city_id,
                subject_city_id=delegation.subject_city_id,
                max_level=delegation.max_level,
                expires_at=delegation.expires_at,
                revoked_at=time.time(),
                reason=delegation.reason,
            )
            self._delegations[delegation_id] = revoked
            return revoked

    def list_delegations(self) -> list[TrustDelegation]:
        with self._lock:
            return list(self._delegations.values())

    def revocation_log(self) -> list[tuple[float, str, str, RevocationReason]]:
        with self._lock:
            return list(self._revocation_log)

    def expire_stale(self) -> list[EnhancedTrustRecord]:
        """Scan and mark expired records. Returns newly expired records."""
        with self._lock:
            expired: list[EnhancedTrustRecord] = []
            now = time.time()
            for key, record in list(self._records.items()):
                if record.revoked_at is not None:
                    continue
                if record.expires_at is not None and now > record.expires_at:
                    revoked = EnhancedTrustRecord(
                        record_id=record.record_id,
                        issuer_city_id=record.issuer_city_id,
                        subject_city_id=record.subject_city_id,
                        level=record.level,
                        reason=record.reason,
                        evidence=record.evidence,
                        established_at=record.established_at,
                        expires_at=record.expires_at,
                        revoked_at=now,
                        revocation_reason=RevocationReason.TRUST_EXPIRED,
                        delegated_from=record.delegated_from,
                        labels=record.labels,
                    )
                    self._records[key] = revoked
                    expired.append(revoked)
            return expired

    def _evaluate_delegated(self, source_city_id: str, target_city_id: str) -> TrustLevel:
        """Check if trust can be inferred via delegation chains."""
        now = time.time()
        best_level = self._default_level
        for delegation in self._delegations.values():
            if delegation.revoked_at is not None:
                continue
            if delegation.expires_at is not None and now > delegation.expires_at:
                continue
            if delegation.delegate_city_id != source_city_id:
                continue
            if delegation.subject_city_id != target_city_id:
                continue
            delegator_trust = self._records.get((delegation.delegator_city_id, target_city_id))
            if delegator_trust is None or not delegator_trust.is_active:
                continue
            effective = min(
                trust_rank(delegator_trust.level),
                trust_rank(delegation.max_level),
            )
            if effective > trust_rank(best_level):
                for level, rank in _TRUST_RANK.items():
                    if rank == effective:
                        best_level = level
                        break
        return best_level
