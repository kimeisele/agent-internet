from __future__ import annotations

from agent_internet.contract_verification import (
    CapabilityDescriptor,
    ContractManifest,
    ContractVerifier,
    SchemaProbe,
    VerificationStatus,
)


def test_schema_probe_passes():
    probe = SchemaProbe()
    cap = CapabilityDescriptor(name="search", version="1.0")
    result = probe.probe("alpha", cap)
    assert result.status == VerificationStatus.PASSED


def test_schema_probe_fails_missing_name():
    probe = SchemaProbe()
    cap = CapabilityDescriptor(name="", version="1.0")
    result = probe.probe("alpha", cap)
    assert result.status == VerificationStatus.FAILED


def test_verify_manifest():
    verifier = ContractVerifier(_probes=[SchemaProbe()])
    manifest = ContractManifest(
        city_id="alpha",
        contract_name="agent-web",
        capabilities=(
            CapabilityDescriptor(name="search", version="1.0"),
            CapabilityDescriptor(name="crawl", version="1.0"),
        ),
    )
    result = verifier.verify_manifest(manifest)
    assert result.overall_status == VerificationStatus.PASSED
    assert len(result.probes) == 2


def test_verify_manifest_with_violation():
    verifier = ContractVerifier(_probes=[SchemaProbe()])
    manifest = ContractManifest(
        city_id="alpha",
        contract_name="agent-web",
        capabilities=(
            CapabilityDescriptor(name="", version="1.0"),
        ),
    )
    result = verifier.verify_manifest(manifest)
    assert result.overall_status == VerificationStatus.FAILED
    assert len(result.violations) == 1


def test_verify_city():
    verifier = ContractVerifier(_probes=[SchemaProbe()])
    manifest = ContractManifest(
        city_id="alpha",
        contract_name="agent-web",
        capabilities=(CapabilityDescriptor(name="search", version="1.0"),),
    )
    verifier.register_manifest(manifest)
    results = verifier.verify_city("alpha")
    assert len(results) == 1
    assert results[0].overall_status == VerificationStatus.PASSED


def test_verify_all():
    verifier = ContractVerifier(_probes=[SchemaProbe()])
    for city_id in ["alpha", "beta"]:
        verifier.register_manifest(ContractManifest(
            city_id=city_id,
            contract_name="test",
            capabilities=(CapabilityDescriptor(name="x", version="1.0"),),
        ))
    results = verifier.verify_all()
    assert len(results) == 2


def test_results_tracked():
    verifier = ContractVerifier(_probes=[SchemaProbe()])
    manifest = ContractManifest(
        city_id="alpha",
        contract_name="test",
        capabilities=(CapabilityDescriptor(name="x", version="1.0"),),
    )
    verifier.verify_manifest(manifest)
    assert len(verifier.results()) == 1
