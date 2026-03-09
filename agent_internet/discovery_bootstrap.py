"""Federation auto-discovery protocol.

Enables cities to announce themselves and be automatically discovered by peers,
eliminating the need for manual onboarding of every city.
"""

from __future__ import annotations

import json
import time
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from secrets import token_hex

from .models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    HealthStatus,
    TrustLevel,
    TrustRecord,
)

logger = logging.getLogger(__name__)


class DiscoveryMethod(StrEnum):
    FILESYSTEM_BEACON = "filesystem_beacon"
    GIT_WIKI_ANNOUNCE = "git_wiki_announce"
    HTTPS_ANNOUNCE = "https_announce"
    MANUAL = "manual"
    SEED_LIST = "seed_list"


@dataclass(frozen=True, slots=True)
class DiscoveryAnnouncement:
    """An announcement from a city declaring its presence and reachability."""

    announcement_id: str = field(default_factory=lambda: f"ann_{token_hex(6)}")
    city_id: str = ""
    slug: str = ""
    repo: str = ""
    transport: str = ""
    location: str = ""
    public_key: str = ""
    capabilities: tuple[str, ...] = ()
    method: DiscoveryMethod = DiscoveryMethod.MANUAL
    announced_at: float = field(default_factory=time.time)
    ttl_s: float = 3600.0
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.announced_at + self.ttl_s


@dataclass(frozen=True, slots=True)
class DiscoveryPeer:
    """A discovered peer city with its announcement and processing metadata."""

    city_id: str
    announcement: DiscoveryAnnouncement
    discovered_at: float = field(default_factory=time.time)
    auto_registered: bool = False
    auto_trusted: bool = False


@dataclass(slots=True)
class FilesystemBeaconScanner:
    """Scans a directory for discovery beacons written by neighboring cities.

    Each beacon is a JSON file named ``{city_id}.beacon.json`` containing
    a serialized ``DiscoveryAnnouncement``.
    """

    beacon_dir: Path = field(default_factory=lambda: Path(".agent-internet/beacons"))

    def write_beacon(self, announcement: DiscoveryAnnouncement) -> Path:
        """Write a beacon file for this city."""
        self.beacon_dir.mkdir(parents=True, exist_ok=True)
        path = self.beacon_dir / f"{announcement.city_id}.beacon.json"
        data = {
            "announcement_id": announcement.announcement_id,
            "city_id": announcement.city_id,
            "slug": announcement.slug,
            "repo": announcement.repo,
            "transport": announcement.transport,
            "location": announcement.location,
            "public_key": announcement.public_key,
            "capabilities": list(announcement.capabilities),
            "method": announcement.method.value,
            "announced_at": announcement.announced_at,
            "ttl_s": announcement.ttl_s,
            "labels": announcement.labels,
        }
        path.write_text(json.dumps(data, indent=2))
        return path

    def scan(self) -> list[DiscoveryAnnouncement]:
        """Scan beacon directory and return active announcements."""
        if not self.beacon_dir.exists():
            return []
        announcements: list[DiscoveryAnnouncement] = []
        for path in sorted(self.beacon_dir.glob("*.beacon.json")):
            try:
                data = json.loads(path.read_text())
                ann = DiscoveryAnnouncement(
                    announcement_id=data.get("announcement_id", f"ann_{token_hex(6)}"),
                    city_id=data["city_id"],
                    slug=data.get("slug", ""),
                    repo=data.get("repo", ""),
                    transport=data.get("transport", ""),
                    location=data.get("location", ""),
                    public_key=data.get("public_key", ""),
                    capabilities=tuple(data.get("capabilities", ())),
                    method=DiscoveryMethod(data.get("method", "filesystem_beacon")),
                    announced_at=data.get("announced_at", 0.0),
                    ttl_s=data.get("ttl_s", 3600.0),
                    labels=data.get("labels", {}),
                )
                if not ann.is_expired:
                    announcements.append(ann)
            except Exception as exc:
                logger.warning("Failed to parse beacon %s: %s", path.name, exc)
        return announcements


@dataclass(slots=True)
class SeedListLoader:
    """Loads a list of known cities from a seed file.

    Seed files are JSON arrays of announcement objects, typically committed
    to the repository or fetched from a known URL.
    """

    def load(self, path: Path) -> list[DiscoveryAnnouncement]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, list):
                return []
            return [
                DiscoveryAnnouncement(
                    city_id=entry["city_id"],
                    slug=entry.get("slug", ""),
                    repo=entry.get("repo", ""),
                    transport=entry.get("transport", ""),
                    location=entry.get("location", ""),
                    capabilities=tuple(entry.get("capabilities", ())),
                    method=DiscoveryMethod.SEED_LIST,
                    labels=entry.get("labels", {}),
                )
                for entry in data
                if isinstance(entry, dict) and "city_id" in entry
            ]
        except Exception as exc:
            logger.warning("Failed to load seed list %s: %s", path, exc)
            return []


@dataclass(slots=True)
class DiscoveryBootstrapService:
    """Orchestrates discovery from multiple sources and auto-registers peers.

    Merges announcements from filesystem beacons, seed lists, and manual
    registrations into a unified view.  Optionally auto-registers and
    auto-trusts discovered peers at a configurable trust level.
    """

    _known_peers: dict[str, DiscoveryPeer] = field(default_factory=dict)
    _scanners: list[FilesystemBeaconScanner] = field(default_factory=list)
    _seed_paths: list[Path] = field(default_factory=list)
    auto_register: bool = True
    auto_trust_level: TrustLevel = TrustLevel.OBSERVED
    own_city_id: str = ""

    def add_scanner(self, scanner: FilesystemBeaconScanner) -> None:
        self._scanners.append(scanner)

    def add_seed_path(self, path: Path) -> None:
        self._seed_paths.append(path)

    def scan(self) -> list[DiscoveryAnnouncement]:
        """Scan all sources for announcements."""
        announcements: list[DiscoveryAnnouncement] = []
        for scanner in self._scanners:
            announcements.extend(scanner.scan())
        loader = SeedListLoader()
        for path in self._seed_paths:
            announcements.extend(loader.load(path))
        # Deduplicate by city_id, keeping latest
        by_city: dict[str, DiscoveryAnnouncement] = {}
        for ann in announcements:
            if ann.city_id == self.own_city_id:
                continue
            existing = by_city.get(ann.city_id)
            if existing is None or ann.announced_at > existing.announced_at:
                by_city[ann.city_id] = ann
        return list(by_city.values())

    def discover_and_register(self, control_plane: object) -> list[DiscoveryPeer]:
        """Scan all sources and register newly discovered peers.

        Returns the list of *newly* discovered peers (not previously known).
        """
        announcements = self.scan()
        new_peers: list[DiscoveryPeer] = []

        for ann in announcements:
            if self._is_stale_announcement(ann):
                continue
            peer = self._process_announcement(ann, control_plane)
            self._known_peers[ann.city_id] = peer
            new_peers.append(peer)

        return new_peers

    def _is_stale_announcement(self, ann: DiscoveryAnnouncement) -> bool:
        """Check if this announcement is older than what we already know."""
        old = self._known_peers.get(ann.city_id)
        return old is not None and ann.announced_at <= old.announcement.announced_at

    def _process_announcement(self, ann: DiscoveryAnnouncement, control_plane: object) -> DiscoveryPeer:
        """Process a single announcement: register, announce presence, establish trust."""
        registered = False
        trusted = False

        if self.auto_register and control_plane is not None:
            registered = self._try_register_city(ann, control_plane)
            self._try_announce_presence(ann, control_plane)
            trusted = self._try_establish_trust(ann, control_plane)

        return DiscoveryPeer(
            city_id=ann.city_id,
            announcement=ann,
            auto_registered=registered,
            auto_trusted=trusted,
        )

    def _try_register_city(self, ann: DiscoveryAnnouncement, plane: object) -> bool:
        register_city = getattr(plane, "register_city", None)
        if not callable(register_city):
            return False
        identity = CityIdentity(
            city_id=ann.city_id, slug=ann.slug, repo=ann.repo,
            public_key=ann.public_key, labels=dict(ann.labels),
        )
        endpoint = CityEndpoint(
            city_id=ann.city_id, transport=ann.transport or "filesystem", location=ann.location,
        )
        register_city(identity, endpoint)
        logger.info("Auto-registered discovered city: %s (%s)", ann.city_id, ann.slug)
        return True

    def _try_announce_presence(self, ann: DiscoveryAnnouncement, plane: object) -> bool:
        announce_city = getattr(plane, "announce_city", None)
        if not callable(announce_city):
            return False
        announce_city(CityPresence(
            city_id=ann.city_id, health=HealthStatus.HEALTHY,
            last_seen_at=ann.announced_at, capabilities=ann.capabilities,
        ))
        return True

    def _try_establish_trust(self, ann: DiscoveryAnnouncement, plane: object) -> bool:
        if self.auto_trust_level == TrustLevel.UNKNOWN or not self.own_city_id:
            return False
        record_trust = getattr(plane, "record_trust", None)
        if not callable(record_trust):
            return False
        record_trust(TrustRecord(
            issuer_city_id=self.own_city_id, subject_city_id=ann.city_id,
            level=self.auto_trust_level, reason=f"auto-discovered via {ann.method.value}",
        ))
        return True

    def announce_self(
        self,
        *,
        slug: str = "",
        repo: str = "",
        transport: str = "filesystem",
        location: str = "",
        capabilities: tuple[str, ...] = (),
        labels: dict[str, str] | None = None,
    ) -> DiscoveryAnnouncement:
        """Create and broadcast an announcement for this city."""
        ann = DiscoveryAnnouncement(
            city_id=self.own_city_id,
            slug=slug,
            repo=repo,
            transport=transport,
            location=location,
            capabilities=capabilities,
            method=DiscoveryMethod.FILESYSTEM_BEACON,
            labels=labels or {},
        )
        for scanner in self._scanners:
            scanner.write_beacon(ann)
        return ann

    def known_peers(self) -> list[DiscoveryPeer]:
        return list(self._known_peers.values())

    def get_peer(self, city_id: str) -> DiscoveryPeer | None:
        return self._known_peers.get(city_id)

    def expire_stale(self) -> list[str]:
        """Remove peers whose announcements have expired.  Returns removed city IDs."""
        expired: list[str] = []
        for city_id, peer in list(self._known_peers.items()):
            if peer.announcement.is_expired:
                del self._known_peers[city_id]
                expired.append(city_id)
        return expired
