"""SQLite-backed durable city registry.

Provides persistent storage for all control plane state, replacing the
in-memory registry for production deployments where state must survive
process restarts.

Uses the stdlib ``sqlite3`` module — no external dependencies.
"""

from __future__ import annotations

import json
import sqlite3
import time
import threading
from dataclasses import dataclass, field

from .models import (
    ClaimStatus,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    ForkLineageRecord,
    ForkMode,
    HealthStatus,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    IntentType,
    LeaseStatus,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    OperationReceiptRecord,
    LotusRoute,
    LotusServiceAddress,
    SlotDescriptor,
    SlotLeaseRecord,
    SlotStatus,
    SpaceClaimRecord,
    SpaceDescriptor,
    SpaceKind,
    UpstreamSyncPolicy,
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS identities (
    city_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL DEFAULT '',
    repo TEXT NOT NULL DEFAULT '',
    public_key TEXT NOT NULL DEFAULT '',
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS endpoints (
    city_id TEXT PRIMARY KEY,
    transport TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS presence (
    city_id TEXT PRIMARY KEY,
    health TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at REAL,
    heartbeat INTEGER,
    capabilities TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS link_addresses (
    city_id TEXT PRIMARY KEY,
    mac_address TEXT NOT NULL,
    interface TEXT NOT NULL DEFAULT 'lotus0',
    lease_started_at REAL,
    lease_expires_at REAL
);

CREATE TABLE IF NOT EXISTS network_addresses (
    city_id TEXT PRIMARY KEY,
    ip_address TEXT NOT NULL,
    prefix_length INTEGER NOT NULL DEFAULT 64,
    lease_started_at REAL,
    lease_expires_at REAL
);

CREATE TABLE IF NOT EXISTS hosted_endpoints (
    endpoint_id TEXT PRIMARY KEY,
    owner_city_id TEXT NOT NULL,
    public_handle TEXT NOT NULL,
    transport TEXT NOT NULL,
    location TEXT NOT NULL,
    link_address TEXT NOT NULL,
    network_address TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'public',
    lease_started_at REAL,
    lease_expires_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_hosted_handle ON hosted_endpoints(public_handle);

CREATE TABLE IF NOT EXISTS service_addresses (
    service_id TEXT PRIMARY KEY,
    owner_city_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    public_handle TEXT NOT NULL,
    transport TEXT NOT NULL,
    location TEXT NOT NULL,
    network_address TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'federated',
    auth_required INTEGER NOT NULL DEFAULT 1,
    required_scopes TEXT NOT NULL DEFAULT '[]',
    lease_started_at REAL,
    lease_expires_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_service_name ON service_addresses(owner_city_id, service_name);

CREATE TABLE IF NOT EXISTS routes (
    route_id TEXT PRIMARY KEY,
    owner_city_id TEXT NOT NULL,
    destination_prefix TEXT NOT NULL,
    target_city_id TEXT NOT NULL,
    next_hop_city_id TEXT NOT NULL,
    metric INTEGER NOT NULL DEFAULT 100,
    nadi_type TEXT NOT NULL DEFAULT 'vyana',
    priority TEXT NOT NULL DEFAULT 'rajas',
    ttl_ms INTEGER NOT NULL DEFAULT 24000,
    maha_header_hex TEXT NOT NULL DEFAULT '',
    lease_started_at REAL,
    lease_expires_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    token_hint TEXT NOT NULL,
    token_sha256 TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    issued_at REAL,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_token_hash ON api_tokens(token_sha256);

CREATE TABLE IF NOT EXISTS operation_receipts (
    operation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    action TEXT NOT NULL,
    operator_subject TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied',
    response_payload TEXT NOT NULL DEFAULT '{}',
    created_at REAL,
    last_replayed_at REAL,
    replay_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_operation_receipt_request ON operation_receipts(action, operator_subject, request_id);

CREATE TABLE IF NOT EXISTS spaces (
    space_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'public_surface',
    owner_subject_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    city_id TEXT NOT NULL DEFAULT '',
    repo TEXT NOT NULL DEFAULT '',
    heartbeat_source TEXT NOT NULL DEFAULT '',
    heartbeat INTEGER,
    last_seen_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS slots (
    slot_id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    slot_kind TEXT NOT NULL DEFAULT '',
    holder_subject_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    capacity INTEGER NOT NULL DEFAULT 1,
    heartbeat_source TEXT NOT NULL DEFAULT '',
    heartbeat INTEGER,
    last_seen_at REAL,
    lease_expires_at REAL,
    reclaimable_since_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS space_claims (
    claim_id TEXT PRIMARY KEY,
    source_intent_id TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    space_id TEXT NOT NULL DEFAULT '',
    slot_id TEXT NOT NULL DEFAULT '',
    claim_type TEXT NOT NULL DEFAULT 'space_claim',
    status TEXT NOT NULL DEFAULT 'granted',
    requested_at REAL,
    granted_at REAL,
    released_at REAL,
    expires_at REAL,
    supersedes_claim_id TEXT NOT NULL DEFAULT '',
    superseded_by_claim_id TEXT NOT NULL DEFAULT '',
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS slot_leases (
    lease_id TEXT PRIMARY KEY,
    source_intent_id TEXT NOT NULL DEFAULT '',
    holder_subject_id TEXT NOT NULL DEFAULT '',
    space_id TEXT NOT NULL DEFAULT '',
    slot_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    granted_at REAL,
    released_at REAL,
    expires_at REAL,
    reclaimable_since_at REAL,
    supersedes_lease_id TEXT NOT NULL DEFAULT '',
    superseded_by_lease_id TEXT NOT NULL DEFAULT '',
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS fork_lineage (
    lineage_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    upstream_repo TEXT NOT NULL DEFAULT '',
    line_root_repo TEXT NOT NULL DEFAULT '',
    fork_mode TEXT NOT NULL DEFAULT 'experiment',
    sync_policy TEXT NOT NULL DEFAULT 'manual_only',
    space_id TEXT NOT NULL DEFAULT '',
    upstream_space_id TEXT NOT NULL DEFAULT '',
    forked_by_subject_id TEXT NOT NULL DEFAULT '',
    created_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    intent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    requested_by_subject_id TEXT NOT NULL DEFAULT '',
    repo TEXT NOT NULL DEFAULT '',
    city_id TEXT NOT NULL DEFAULT '',
    space_id TEXT NOT NULL DEFAULT '',
    slot_id TEXT NOT NULL DEFAULT '',
    lineage_id TEXT NOT NULL DEFAULT '',
    discussion_id TEXT NOT NULL DEFAULT '',
    linked_issue_url TEXT NOT NULL DEFAULT '',
    linked_pr_url TEXT NOT NULL DEFAULT '',
    created_at REAL,
    updated_at REAL,
    labels TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS allocator (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 1
);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_sql: str) -> None:
    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_sql}")


def _lease_active(expires_at: float | None, now: float | None) -> bool:
    current = time.time() if now is None else now
    return expires_at is None or expires_at > current


def _format_link_address(index: int) -> str:
    return f"02:00:{(index >> 24) & 0xFF:02x}:{(index >> 16) & 0xFF:02x}:{(index >> 8) & 0xFF:02x}:{index & 0xFF:02x}"


def _format_network_address(index: int) -> str:
    return f"fd10:{(index >> 16) & 0xFFFF:04x}:{index & 0xFFFF:04x}:0000::1"


@dataclass(slots=True)
class SqliteCityRegistry:
    """SQLite-backed city registry implementing the CityRegistry and DiscoveryService protocols.

    Thread-safe — each operation acquires the connection from a thread-local pool
    and all writes are serialized via SQLite's built-in write-ahead log.
    """

    db_path: str = ":memory:"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _shared_conn: sqlite3.Connection | None = field(default=None, repr=False)
    _local: threading.local = field(default_factory=threading.local, repr=False)

    def __post_init__(self) -> None:
        if self.db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        conn = self._conn()
        conn.executescript(_SCHEMA)
        _ensure_column(conn, "spaces", "last_seen_at", "REAL")
        _ensure_column(conn, "slots", "last_seen_at", "REAL")
        _ensure_column(conn, "slots", "lease_expires_at", "REAL")
        _ensure_column(conn, "slots", "reclaimable_since_at", "REAL")
        _ensure_column(conn, "space_claims", "released_at", "REAL")
        _ensure_column(conn, "space_claims", "supersedes_claim_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "space_claims", "superseded_by_claim_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slot_leases", "released_at", "REAL")
        _ensure_column(conn, "slot_leases", "supersedes_lease_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slot_leases", "superseded_by_lease_id", "TEXT NOT NULL DEFAULT ''")
        conn.execute("INSERT OR IGNORE INTO allocator (key, value) VALUES ('next_link_id', 1)")
        conn.execute("INSERT OR IGNORE INTO allocator (key, value) VALUES ('next_network_id', 1)")
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _execute_write(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn().execute(sql, params)
            self._conn().commit()

    def _execute_read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn().execute(sql, params).fetchall()

    def _execute_read_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn().execute(sql, params).fetchone()

    # --- Identities ---

    def upsert_identity(self, identity: CityIdentity) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO identities (city_id, slug, repo, public_key, labels) VALUES (?, ?, ?, ?, ?)",
            (identity.city_id, identity.slug, identity.repo, identity.public_key, json.dumps(identity.labels)),
        )

    def get_identity(self, city_id: str) -> CityIdentity | None:
        row = self._execute_read_one("SELECT * FROM identities WHERE city_id = ?", (city_id,))
        if row is None:
            return None
        return CityIdentity(city_id=row["city_id"], slug=row["slug"], repo=row["repo"], public_key=row["public_key"], labels=json.loads(row["labels"]))

    def list_identities(self) -> list[CityIdentity]:
        rows = self._execute_read("SELECT * FROM identities ORDER BY city_id")
        return [CityIdentity(city_id=r["city_id"], slug=r["slug"], repo=r["repo"], public_key=r["public_key"], labels=json.loads(r["labels"])) for r in rows]

    # --- Endpoints ---

    def upsert_endpoint(self, endpoint: CityEndpoint) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO endpoints (city_id, transport, location) VALUES (?, ?, ?)",
            (endpoint.city_id, endpoint.transport, endpoint.location),
        )

    def get_endpoint(self, city_id: str) -> CityEndpoint | None:
        row = self._execute_read_one("SELECT * FROM endpoints WHERE city_id = ?", (city_id,))
        if row is None:
            return None
        return CityEndpoint(city_id=row["city_id"], transport=row["transport"], location=row["location"])

    def list_endpoints(self) -> list[CityEndpoint]:
        rows = self._execute_read("SELECT * FROM endpoints ORDER BY city_id")
        return [CityEndpoint(city_id=r["city_id"], transport=r["transport"], location=r["location"]) for r in rows]

    # --- Link addresses ---

    def assign_link_address(self, city_id: str, *, ttl_s: float | None = None, interface: str = "lotus0", now: float | None = None) -> LotusLinkAddress:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT * FROM link_addresses WHERE city_id = ?", (city_id,)).fetchone()
            if row is not None and _lease_active(row["lease_expires_at"], now):
                return LotusLinkAddress(
                    city_id=row["city_id"], mac_address=row["mac_address"], interface=row["interface"],
                    lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"],
                )
            started_at = time.time() if now is None else float(now)
            expires_at = None if ttl_s is None else started_at + max(ttl_s, 0.0)
            next_id = conn.execute("SELECT value FROM allocator WHERE key = 'next_link_id'").fetchone()["value"]
            mac = _format_link_address(next_id)
            conn.execute("UPDATE allocator SET value = ? WHERE key = 'next_link_id'", (next_id + 1,))
            conn.execute(
                "INSERT OR REPLACE INTO link_addresses (city_id, mac_address, interface, lease_started_at, lease_expires_at) VALUES (?, ?, ?, ?, ?)",
                (city_id, mac, interface, started_at, expires_at),
            )
            conn.commit()
            return LotusLinkAddress(city_id=city_id, mac_address=mac, interface=interface, lease_started_at=started_at, lease_expires_at=expires_at)

    def get_link_address(self, city_id: str) -> LotusLinkAddress | None:
        row = self._execute_read_one("SELECT * FROM link_addresses WHERE city_id = ?", (city_id,))
        if row is None:
            return None
        return LotusLinkAddress(city_id=row["city_id"], mac_address=row["mac_address"], interface=row["interface"], lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"])

    def list_link_addresses(self) -> list[LotusLinkAddress]:
        rows = self._execute_read("SELECT * FROM link_addresses ORDER BY city_id")
        return [LotusLinkAddress(city_id=r["city_id"], mac_address=r["mac_address"], interface=r["interface"], lease_started_at=r["lease_started_at"], lease_expires_at=r["lease_expires_at"]) for r in rows]

    # --- Network addresses ---

    def assign_network_address(self, city_id: str, *, ttl_s: float | None = None, prefix_length: int = 64, now: float | None = None) -> LotusNetworkAddress:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT * FROM network_addresses WHERE city_id = ?", (city_id,)).fetchone()
            if row is not None and _lease_active(row["lease_expires_at"], now):
                return LotusNetworkAddress(
                    city_id=row["city_id"], ip_address=row["ip_address"], prefix_length=row["prefix_length"],
                    lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"],
                )
            started_at = time.time() if now is None else float(now)
            expires_at = None if ttl_s is None else started_at + max(ttl_s, 0.0)
            next_id = conn.execute("SELECT value FROM allocator WHERE key = 'next_network_id'").fetchone()["value"]
            ip = _format_network_address(next_id)
            conn.execute("UPDATE allocator SET value = ? WHERE key = 'next_network_id'", (next_id + 1,))
            conn.execute(
                "INSERT OR REPLACE INTO network_addresses (city_id, ip_address, prefix_length, lease_started_at, lease_expires_at) VALUES (?, ?, ?, ?, ?)",
                (city_id, ip, prefix_length, started_at, expires_at),
            )
            conn.commit()
            return LotusNetworkAddress(city_id=city_id, ip_address=ip, prefix_length=prefix_length, lease_started_at=started_at, lease_expires_at=expires_at)

    def get_network_address(self, city_id: str) -> LotusNetworkAddress | None:
        row = self._execute_read_one("SELECT * FROM network_addresses WHERE city_id = ?", (city_id,))
        if row is None:
            return None
        return LotusNetworkAddress(city_id=row["city_id"], ip_address=row["ip_address"], prefix_length=row["prefix_length"], lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"])

    def list_network_addresses(self) -> list[LotusNetworkAddress]:
        rows = self._execute_read("SELECT * FROM network_addresses ORDER BY city_id")
        return [LotusNetworkAddress(city_id=r["city_id"], ip_address=r["ip_address"], prefix_length=r["prefix_length"], lease_started_at=r["lease_started_at"], lease_expires_at=r["lease_expires_at"]) for r in rows]

    # --- Hosted endpoints ---

    def upsert_hosted_endpoint(self, endpoint: HostedEndpoint) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO hosted_endpoints (endpoint_id, owner_city_id, public_handle, transport, location, link_address, network_address, visibility, lease_started_at, lease_expires_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (endpoint.endpoint_id, endpoint.owner_city_id, endpoint.public_handle, endpoint.transport, endpoint.location, endpoint.link_address, endpoint.network_address, endpoint.visibility.value, endpoint.lease_started_at, endpoint.lease_expires_at, json.dumps(endpoint.labels)),
        )

    def get_hosted_endpoint(self, endpoint_id: str) -> HostedEndpoint | None:
        row = self._execute_read_one("SELECT * FROM hosted_endpoints WHERE endpoint_id = ?", (endpoint_id,))
        if row is None:
            return None
        return self._row_to_hosted_endpoint(row)

    def get_hosted_endpoint_by_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        row = self._execute_read_one("SELECT * FROM hosted_endpoints WHERE public_handle = ?", (public_handle,))
        if row is None:
            return None
        ep = self._row_to_hosted_endpoint(row)
        if not _lease_active(ep.lease_expires_at, now):
            return None
        return ep

    def list_hosted_endpoints(self) -> list[HostedEndpoint]:
        rows = self._execute_read("SELECT * FROM hosted_endpoints ORDER BY endpoint_id")
        return [self._row_to_hosted_endpoint(r) for r in rows]

    @staticmethod
    def _row_to_hosted_endpoint(row: sqlite3.Row) -> HostedEndpoint:
        return HostedEndpoint(
            endpoint_id=row["endpoint_id"], owner_city_id=row["owner_city_id"], public_handle=row["public_handle"],
            transport=row["transport"], location=row["location"], link_address=row["link_address"],
            network_address=row["network_address"], visibility=EndpointVisibility(row["visibility"]),
            lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"], labels=json.loads(row["labels"]),
        )

    # --- Service addresses ---

    def upsert_service_address(self, service: LotusServiceAddress) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO service_addresses (service_id, owner_city_id, service_name, public_handle, transport, location, network_address, visibility, auth_required, required_scopes, lease_started_at, lease_expires_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (service.service_id, service.owner_city_id, service.service_name, service.public_handle, service.transport, service.location, service.network_address, service.visibility.value, int(service.auth_required), json.dumps(service.required_scopes), service.lease_started_at, service.lease_expires_at, json.dumps(service.labels)),
        )

    def get_service_address(self, service_id: str) -> LotusServiceAddress | None:
        row = self._execute_read_one("SELECT * FROM service_addresses WHERE service_id = ?", (service_id,))
        if row is None:
            return None
        svc = self._row_to_service(row)
        if not _lease_active(svc.lease_expires_at, None):
            return None
        return svc

    def get_service_address_by_name(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        row = self._execute_read_one("SELECT * FROM service_addresses WHERE owner_city_id = ? AND service_name = ?", (owner_city_id, service_name))
        if row is None:
            return None
        svc = self._row_to_service(row)
        if not _lease_active(svc.lease_expires_at, now):
            return None
        return svc

    def list_service_addresses(self) -> list[LotusServiceAddress]:
        rows = self._execute_read("SELECT * FROM service_addresses ORDER BY service_id")
        return [self._row_to_service(r) for r in rows]

    @staticmethod
    def _row_to_service(row: sqlite3.Row) -> LotusServiceAddress:
        return LotusServiceAddress(
            service_id=row["service_id"], owner_city_id=row["owner_city_id"], service_name=row["service_name"],
            public_handle=row["public_handle"], transport=row["transport"], location=row["location"],
            network_address=row["network_address"], visibility=EndpointVisibility(row["visibility"]),
            auth_required=bool(row["auth_required"]), required_scopes=tuple(json.loads(row["required_scopes"])),
            lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"], labels=json.loads(row["labels"]),
        )

    # --- Routes ---

    def upsert_route(self, route: LotusRoute) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO routes (route_id, owner_city_id, destination_prefix, target_city_id, next_hop_city_id, metric, nadi_type, priority, ttl_ms, maha_header_hex, lease_started_at, lease_expires_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (route.route_id, route.owner_city_id, route.destination_prefix, route.target_city_id, route.next_hop_city_id, route.metric, route.nadi_type, route.priority, route.ttl_ms, route.maha_header_hex, route.lease_started_at, route.lease_expires_at, json.dumps(route.labels)),
        )

    def get_route(self, route_id: str) -> LotusRoute | None:
        row = self._execute_read_one("SELECT * FROM routes WHERE route_id = ?", (route_id,))
        if row is None:
            return None
        route = self._row_to_route(row)
        if not _lease_active(route.lease_expires_at, None):
            return None
        return route

    def list_routes(self) -> list[LotusRoute]:
        rows = self._execute_read("SELECT * FROM routes ORDER BY route_id")
        return [self._row_to_route(r) for r in rows]

    @staticmethod
    def _row_to_route(row: sqlite3.Row) -> LotusRoute:
        return LotusRoute(
            route_id=row["route_id"], owner_city_id=row["owner_city_id"], destination_prefix=row["destination_prefix"],
            target_city_id=row["target_city_id"], next_hop_city_id=row["next_hop_city_id"],
            metric=row["metric"], nadi_type=row["nadi_type"], priority=row["priority"],
            ttl_ms=row["ttl_ms"], maha_header_hex=row["maha_header_hex"],
            lease_started_at=row["lease_started_at"], lease_expires_at=row["lease_expires_at"], labels=json.loads(row["labels"]),
        )

    # --- API tokens ---

    def upsert_api_token(self, token: LotusApiToken) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO api_tokens (token_id, subject, token_hint, token_sha256, scopes, issued_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token.token_id, token.subject, token.token_hint, token.token_sha256, json.dumps(token.scopes), token.issued_at, token.revoked_at),
        )

    def get_api_token(self, token_id: str) -> LotusApiToken | None:
        row = self._execute_read_one("SELECT * FROM api_tokens WHERE token_id = ?", (token_id,))
        if row is None:
            return None
        return self._row_to_token(row)

    def get_api_token_by_sha256(self, token_sha256: str) -> LotusApiToken | None:
        row = self._execute_read_one("SELECT * FROM api_tokens WHERE token_sha256 = ?", (token_sha256,))
        if row is None:
            return None
        return self._row_to_token(row)

    def list_api_tokens(self) -> list[LotusApiToken]:
        rows = self._execute_read("SELECT * FROM api_tokens ORDER BY token_id")
        return [self._row_to_token(r) for r in rows]

    @staticmethod
    def _row_to_token(row: sqlite3.Row) -> LotusApiToken:
        return LotusApiToken(
            token_id=row["token_id"], subject=row["subject"], token_hint=row["token_hint"],
            token_sha256=row["token_sha256"], scopes=tuple(json.loads(row["scopes"])),
            issued_at=row["issued_at"], revoked_at=row["revoked_at"],
        )

    # --- Operation receipts ---

    def upsert_operation_receipt(self, receipt: OperationReceiptRecord) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO operation_receipts (operation_id, request_id, action, operator_subject, request_sha256, status, response_payload, created_at, last_replayed_at, replay_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt.operation_id,
                receipt.request_id,
                receipt.action,
                receipt.operator_subject,
                receipt.request_sha256,
                receipt.status,
                json.dumps(receipt.response_payload, sort_keys=True),
                receipt.created_at,
                receipt.last_replayed_at,
                receipt.replay_count,
            ),
        )

    def get_operation_receipt_by_id(self, operation_id: str) -> OperationReceiptRecord | None:
        row = self._execute_read_one(
            "SELECT * FROM operation_receipts WHERE operation_id = ?",
            (operation_id,),
        )
        if row is None:
            return None
        return self._row_to_operation_receipt(row)

    def get_operation_receipt(self, *, action: str, operator_subject: str, request_id: str) -> OperationReceiptRecord | None:
        row = self._execute_read_one(
            "SELECT * FROM operation_receipts WHERE action = ? AND operator_subject = ? AND request_id = ?",
            (action, operator_subject, request_id),
        )
        if row is None:
            return None
        return self._row_to_operation_receipt(row)

    def list_operation_receipts(self) -> list[OperationReceiptRecord]:
        rows = self._execute_read("SELECT * FROM operation_receipts ORDER BY operation_id")
        return [self._row_to_operation_receipt(r) for r in rows]

    @staticmethod
    def _row_to_operation_receipt(row: sqlite3.Row) -> OperationReceiptRecord:
        return OperationReceiptRecord(
            operation_id=row["operation_id"],
            request_id=row["request_id"],
            action=row["action"],
            operator_subject=row["operator_subject"],
            request_sha256=row["request_sha256"],
            status=row["status"],
            response_payload=dict(json.loads(row["response_payload"])),
            created_at=row["created_at"],
            last_replayed_at=row["last_replayed_at"],
            replay_count=row["replay_count"],
        )

    # --- Spaces ---

    def upsert_space(self, space: SpaceDescriptor) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO spaces (space_id, kind, owner_subject_id, display_name, city_id, repo, heartbeat_source, heartbeat, last_seen_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (space.space_id, space.kind.value, space.owner_subject_id, space.display_name, space.city_id, space.repo, space.heartbeat_source, space.heartbeat, space.last_seen_at, json.dumps(space.labels)),
        )

    def get_space(self, space_id: str) -> SpaceDescriptor | None:
        row = self._execute_read_one("SELECT * FROM spaces WHERE space_id = ?", (space_id,))
        if row is None:
            return None
        return self._row_to_space(row)

    def list_spaces(self) -> list[SpaceDescriptor]:
        rows = self._execute_read("SELECT * FROM spaces ORDER BY space_id")
        return [self._row_to_space(r) for r in rows]

    @staticmethod
    def _row_to_space(row: sqlite3.Row) -> SpaceDescriptor:
        return SpaceDescriptor(
            space_id=row["space_id"], kind=SpaceKind(row["kind"]), owner_subject_id=row["owner_subject_id"],
            display_name=row["display_name"], city_id=row["city_id"], repo=row["repo"],
            heartbeat_source=row["heartbeat_source"], heartbeat=row["heartbeat"], last_seen_at=row["last_seen_at"], labels=json.loads(row["labels"]),
        )

    # --- Slots ---

    def upsert_slot(self, slot: SlotDescriptor) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO slots (slot_id, space_id, slot_kind, holder_subject_id, status, capacity, heartbeat_source, heartbeat, last_seen_at, lease_expires_at, reclaimable_since_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slot.slot_id, slot.space_id, slot.slot_kind, slot.holder_subject_id, slot.status.value, slot.capacity, slot.heartbeat_source, slot.heartbeat, slot.last_seen_at, slot.lease_expires_at, slot.reclaimable_since_at, json.dumps(slot.labels)),
        )

    def get_slot(self, slot_id: str) -> SlotDescriptor | None:
        row = self._execute_read_one("SELECT * FROM slots WHERE slot_id = ?", (slot_id,))
        if row is None:
            return None
        return self._row_to_slot(row)

    def list_slots(self) -> list[SlotDescriptor]:
        rows = self._execute_read("SELECT * FROM slots ORDER BY slot_id")
        return [self._row_to_slot(r) for r in rows]

    @staticmethod
    def _row_to_slot(row: sqlite3.Row) -> SlotDescriptor:
        return SlotDescriptor(
            slot_id=row["slot_id"], space_id=row["space_id"], slot_kind=row["slot_kind"],
            holder_subject_id=row["holder_subject_id"], status=SlotStatus(row["status"]),
            capacity=row["capacity"], heartbeat_source=row["heartbeat_source"],
            heartbeat=row["heartbeat"], last_seen_at=row["last_seen_at"], lease_expires_at=row["lease_expires_at"], reclaimable_since_at=row["reclaimable_since_at"], labels=json.loads(row["labels"]),
        )

    # --- Space claims ---

    def upsert_space_claim(self, claim: SpaceClaimRecord) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO space_claims (claim_id, source_intent_id, subject_id, space_id, slot_id, claim_type, status, requested_at, granted_at, released_at, expires_at, supersedes_claim_id, superseded_by_claim_id, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (claim.claim_id, claim.source_intent_id, claim.subject_id, claim.space_id, claim.slot_id, claim.claim_type, claim.status.value, claim.requested_at, claim.granted_at, claim.released_at, claim.expires_at, claim.supersedes_claim_id, claim.superseded_by_claim_id, json.dumps(claim.labels)),
        )

    def get_space_claim(self, claim_id: str) -> SpaceClaimRecord | None:
        row = self._execute_read_one("SELECT * FROM space_claims WHERE claim_id = ?", (claim_id,))
        if row is None:
            return None
        return self._row_to_space_claim(row)

    def list_space_claims(self) -> list[SpaceClaimRecord]:
        rows = self._execute_read("SELECT * FROM space_claims ORDER BY claim_id")
        return [self._row_to_space_claim(r) for r in rows]

    @staticmethod
    def _row_to_space_claim(row: sqlite3.Row) -> SpaceClaimRecord:
        return SpaceClaimRecord(
            claim_id=row["claim_id"], source_intent_id=row["source_intent_id"], subject_id=row["subject_id"],
            space_id=row["space_id"], slot_id=row["slot_id"], claim_type=row["claim_type"], status=ClaimStatus(row["status"]),
            requested_at=row["requested_at"], granted_at=row["granted_at"], released_at=row["released_at"], expires_at=row["expires_at"], supersedes_claim_id=row["supersedes_claim_id"], superseded_by_claim_id=row["superseded_by_claim_id"], labels=json.loads(row["labels"]),
        )

    # --- Slot leases ---

    def upsert_slot_lease(self, lease: SlotLeaseRecord) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO slot_leases (lease_id, source_intent_id, holder_subject_id, space_id, slot_id, status, granted_at, released_at, expires_at, reclaimable_since_at, supersedes_lease_id, superseded_by_lease_id, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (lease.lease_id, lease.source_intent_id, lease.holder_subject_id, lease.space_id, lease.slot_id, lease.status.value, lease.granted_at, lease.released_at, lease.expires_at, lease.reclaimable_since_at, lease.supersedes_lease_id, lease.superseded_by_lease_id, json.dumps(lease.labels)),
        )

    def get_slot_lease(self, lease_id: str) -> SlotLeaseRecord | None:
        row = self._execute_read_one("SELECT * FROM slot_leases WHERE lease_id = ?", (lease_id,))
        if row is None:
            return None
        return self._row_to_slot_lease(row)

    def list_slot_leases(self) -> list[SlotLeaseRecord]:
        rows = self._execute_read("SELECT * FROM slot_leases ORDER BY lease_id")
        return [self._row_to_slot_lease(r) for r in rows]

    @staticmethod
    def _row_to_slot_lease(row: sqlite3.Row) -> SlotLeaseRecord:
        return SlotLeaseRecord(
            lease_id=row["lease_id"], source_intent_id=row["source_intent_id"], holder_subject_id=row["holder_subject_id"],
            space_id=row["space_id"], slot_id=row["slot_id"], status=LeaseStatus(row["status"]), granted_at=row["granted_at"],
            released_at=row["released_at"], expires_at=row["expires_at"], reclaimable_since_at=row["reclaimable_since_at"], supersedes_lease_id=row["supersedes_lease_id"], superseded_by_lease_id=row["superseded_by_lease_id"], labels=json.loads(row["labels"]),
        )

    # --- Fork lineage ---

    def upsert_fork_lineage(self, lineage: ForkLineageRecord) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO fork_lineage (lineage_id, repo, upstream_repo, line_root_repo, fork_mode, sync_policy, space_id, upstream_space_id, forked_by_subject_id, created_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (lineage.lineage_id, lineage.repo, lineage.upstream_repo, lineage.line_root_repo, lineage.fork_mode.value, lineage.sync_policy.value, lineage.space_id, lineage.upstream_space_id, lineage.forked_by_subject_id, lineage.created_at, json.dumps(lineage.labels)),
        )

    def get_fork_lineage(self, lineage_id: str) -> ForkLineageRecord | None:
        row = self._execute_read_one("SELECT * FROM fork_lineage WHERE lineage_id = ?", (lineage_id,))
        if row is None:
            return None
        return self._row_to_lineage(row)

    def list_fork_lineage(self) -> list[ForkLineageRecord]:
        rows = self._execute_read("SELECT * FROM fork_lineage ORDER BY lineage_id")
        return [self._row_to_lineage(r) for r in rows]

    @staticmethod
    def _row_to_lineage(row: sqlite3.Row) -> ForkLineageRecord:
        return ForkLineageRecord(
            lineage_id=row["lineage_id"], repo=row["repo"], upstream_repo=row["upstream_repo"],
            line_root_repo=row["line_root_repo"], fork_mode=ForkMode(row["fork_mode"]),
            sync_policy=UpstreamSyncPolicy(row["sync_policy"]), space_id=row["space_id"],
            upstream_space_id=row["upstream_space_id"], forked_by_subject_id=row["forked_by_subject_id"],
            created_at=row["created_at"], labels=json.loads(row["labels"]),
        )

    # --- Intents ---

    def upsert_intent(self, intent: IntentRecord) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO intents (intent_id, intent_type, status, title, description, requested_by_subject_id, repo, city_id, space_id, slot_id, lineage_id, discussion_id, linked_issue_url, linked_pr_url, created_at, updated_at, labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (intent.intent_id, intent.intent_type.value, intent.status.value, intent.title, intent.description, intent.requested_by_subject_id, intent.repo, intent.city_id, intent.space_id, intent.slot_id, intent.lineage_id, intent.discussion_id, intent.linked_issue_url, intent.linked_pr_url, intent.created_at, intent.updated_at, json.dumps(intent.labels)),
        )

    def get_intent(self, intent_id: str) -> IntentRecord | None:
        row = self._execute_read_one("SELECT * FROM intents WHERE intent_id = ?", (intent_id,))
        if row is None:
            return None
        return self._row_to_intent(row)

    def list_intents(self) -> list[IntentRecord]:
        rows = self._execute_read("SELECT * FROM intents ORDER BY intent_id")
        return [self._row_to_intent(r) for r in rows]

    @staticmethod
    def _row_to_intent(row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            intent_id=row["intent_id"], intent_type=IntentType(row["intent_type"]),
            status=IntentStatus(row["status"]), title=row["title"], description=row["description"],
            requested_by_subject_id=row["requested_by_subject_id"], repo=row["repo"], city_id=row["city_id"],
            space_id=row["space_id"], slot_id=row["slot_id"], lineage_id=row["lineage_id"],
            discussion_id=row["discussion_id"], linked_issue_url=row["linked_issue_url"],
            linked_pr_url=row["linked_pr_url"], created_at=row["created_at"], updated_at=row["updated_at"],
            labels=json.loads(row["labels"]),
        )

    # --- Discovery / Presence ---

    def announce(self, presence: CityPresence) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO presence (city_id, health, last_seen_at, heartbeat, capabilities) VALUES (?, ?, ?, ?, ?)",
            (presence.city_id, presence.health.value, presence.last_seen_at, presence.heartbeat, json.dumps(presence.capabilities)),
        )

    def get_presence(self, city_id: str) -> CityPresence | None:
        row = self._execute_read_one("SELECT * FROM presence WHERE city_id = ?", (city_id,))
        if row is None:
            return None
        return CityPresence(city_id=row["city_id"], health=HealthStatus(row["health"]), last_seen_at=row["last_seen_at"], heartbeat=row["heartbeat"], capabilities=tuple(json.loads(row["capabilities"])))

    def list_cities(self) -> list[CityPresence]:
        rows = self._execute_read("SELECT * FROM presence ORDER BY city_id")
        return [CityPresence(city_id=r["city_id"], health=HealthStatus(r["health"]), last_seen_at=r["last_seen_at"], heartbeat=r["heartbeat"], capabilities=tuple(json.loads(r["capabilities"]))) for r in rows]

    # --- Allocation state ---

    def allocation_state(self) -> dict[str, int]:
        rows = self._execute_read("SELECT key, value FROM allocator")
        return {r["key"]: r["value"] for r in rows}

    def restore_allocation_state(self, *, next_link_id: int = 1, next_network_id: int = 1) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute("INSERT OR REPLACE INTO allocator (key, value) VALUES ('next_link_id', ?)", (max(1, int(next_link_id)),))
            conn.execute("INSERT OR REPLACE INTO allocator (key, value) VALUES ('next_network_id', ?)", (max(1, int(next_network_id)),))
            conn.commit()
