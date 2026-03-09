from __future__ import annotations

import time

from agent_internet.models import TrustLevel, TrustRecord
from agent_internet.trust_enhanced import (
    EnhancedTrustEngine,
    EnhancedTrustRecord,
    EvidenceKind,
    RevocationReason,
    TrustDelegation,
    TrustEvidence,
)


def test_basic_compat():
    engine = EnhancedTrustEngine()
    record = TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
        reason="test",
    )
    engine.record(record)
    assert engine.evaluate("alpha", "beta") == TrustLevel.VERIFIED


def test_self_trust():
    engine = EnhancedTrustEngine()
    assert engine.evaluate("alpha", "alpha") == TrustLevel.TRUSTED


def test_expiration():
    engine = EnhancedTrustEngine()
    record = EnhancedTrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
        expires_at=time.time() - 1.0,
    )
    engine.record_enhanced(record)
    assert engine.evaluate("alpha", "beta") == TrustLevel.UNKNOWN


def test_revocation():
    engine = EnhancedTrustEngine()
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.TRUSTED,
    ))
    result = engine.revoke("alpha", "beta", RevocationReason.BEHAVIORAL_VIOLATION)
    assert result is not None
    assert result.revoked_at is not None
    assert engine.evaluate("alpha", "beta") == TrustLevel.UNKNOWN


def test_evidence():
    engine = EnhancedTrustEngine()
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
    ))
    evidence = TrustEvidence(kind=EvidenceKind.PUBLIC_KEY_VERIFIED, confidence=0.9)
    result = engine.add_evidence("alpha", "beta", evidence)
    assert result is not None
    assert len(result.evidence) == 1
    assert result.aggregate_confidence == 0.9


def test_delegation():
    engine = EnhancedTrustEngine()
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="gamma",
        level=TrustLevel.TRUSTED,
    ))
    delegation = TrustDelegation(
        delegator_city_id="alpha",
        delegate_city_id="beta",
        subject_city_id="gamma",
        max_level=TrustLevel.VERIFIED,
    )
    engine.register_delegation(delegation)
    assert engine.evaluate("beta", "gamma") == TrustLevel.VERIFIED


def test_expire_stale():
    engine = EnhancedTrustEngine()
    engine.record_enhanced(EnhancedTrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
        expires_at=time.time() - 1.0,
    ))
    expired = engine.expire_stale()
    assert len(expired) == 1
    assert expired[0].revocation_reason == RevocationReason.TRUST_EXPIRED


def test_list_records_compat():
    engine = EnhancedTrustEngine()
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.OBSERVED,
    ))
    records = engine.list_records()
    assert len(records) == 1
    assert isinstance(records[0], TrustRecord)


def test_revocation_log():
    engine = EnhancedTrustEngine()
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.TRUSTED,
    ))
    engine.revoke("alpha", "beta")
    log = engine.revocation_log()
    assert len(log) == 1
    assert log[0][1] == "alpha"
    assert log[0][2] == "beta"


def test_default_ttl():
    engine = EnhancedTrustEngine(default_ttl_s=3600.0)
    engine.record(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
    ))
    record = engine.get_record("alpha", "beta")
    assert record is not None
    assert record.expires_at is not None
