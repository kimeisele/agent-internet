from __future__ import annotations

import json
import time
from pathlib import Path

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.discovery_bootstrap import (
    DiscoveryAnnouncement,
    DiscoveryBootstrapService,
    DiscoveryMethod,
    FilesystemBeaconScanner,
    SeedListLoader,
)
from agent_internet.models import TrustLevel


def test_write_and_scan_beacon(tmp_path: Path):
    scanner = FilesystemBeaconScanner(beacon_dir=tmp_path)
    ann = DiscoveryAnnouncement(
        city_id="alpha",
        slug="alpha-city",
        repo="test/alpha",
        transport="filesystem",
        location="/data/alpha",
    )
    scanner.write_beacon(ann)
    results = scanner.scan()
    assert len(results) == 1
    assert results[0].city_id == "alpha"


def test_expired_beacon_filtered(tmp_path: Path):
    scanner = FilesystemBeaconScanner(beacon_dir=tmp_path)
    ann = DiscoveryAnnouncement(
        city_id="alpha",
        announced_at=time.time() - 7200,
        ttl_s=3600.0,
    )
    scanner.write_beacon(ann)
    results = scanner.scan()
    assert len(results) == 0


def test_seed_list_loader(tmp_path: Path):
    seed_path = tmp_path / "seeds.json"
    seed_path.write_text(json.dumps([
        {"city_id": "alpha", "slug": "alpha", "transport": "filesystem"},
        {"city_id": "beta", "slug": "beta"},
    ]))
    loader = SeedListLoader()
    results = loader.load(seed_path)
    assert len(results) == 2
    assert results[0].method == DiscoveryMethod.SEED_LIST


def test_discover_and_register(tmp_path: Path):
    plane = AgentInternetControlPlane()
    scanner = FilesystemBeaconScanner(beacon_dir=tmp_path)
    scanner.write_beacon(DiscoveryAnnouncement(
        city_id="beta",
        slug="beta-city",
        repo="test/beta",
        transport="filesystem",
        location="/data/beta",
    ))

    service = DiscoveryBootstrapService(
        own_city_id="alpha",
        auto_register=True,
        auto_trust_level=TrustLevel.OBSERVED,
    )
    service.add_scanner(scanner)
    new_peers = service.discover_and_register(plane)

    assert len(new_peers) == 1
    assert new_peers[0].auto_registered is True
    assert new_peers[0].auto_trusted is True

    identity = plane.registry.get_identity("beta")
    assert identity is not None
    assert identity.slug == "beta-city"


def test_own_city_filtered(tmp_path: Path):
    scanner = FilesystemBeaconScanner(beacon_dir=tmp_path)
    scanner.write_beacon(DiscoveryAnnouncement(city_id="alpha"))

    service = DiscoveryBootstrapService(own_city_id="alpha")
    service.add_scanner(scanner)
    announcements = service.scan()
    assert len(announcements) == 0


def test_expire_stale():
    service = DiscoveryBootstrapService(own_city_id="alpha")
    from agent_internet.discovery_bootstrap import DiscoveryPeer

    service._known_peers["beta"] = DiscoveryPeer(
        city_id="beta",
        announcement=DiscoveryAnnouncement(
            city_id="beta",
            announced_at=time.time() - 7200,
            ttl_s=3600.0,
        ),
    )
    expired = service.expire_stale()
    assert expired == ["beta"]
    assert len(service.known_peers()) == 0


def test_announce_self(tmp_path: Path):
    scanner = FilesystemBeaconScanner(beacon_dir=tmp_path)
    service = DiscoveryBootstrapService(own_city_id="alpha")
    service.add_scanner(scanner)
    ann = service.announce_self(slug="alpha-city", transport="filesystem")
    assert ann.city_id == "alpha"
    assert (tmp_path / "alpha.beacon.json").exists()
