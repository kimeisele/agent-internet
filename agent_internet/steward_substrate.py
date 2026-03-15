from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StewardSubstrateBindings:
    CityReport: type
    FederationDirective: type
    FederationMessage: type
    FederationPriority: type
    HEADER_SIZE_BYTES: int
    MahaHeader: type
    NADI_BUFFER_SIZE: int
    NadiOp: type
    NadiPriority: type


def load_steward_substrate() -> StewardSubstrateBindings:
    """Load canonical substrate symbols from steward-protocol lazily.

    This avoids re-defining protocol primitives inside agent-internet while also
    keeping the top-level package importable when the substrate is not installed.

    Falls back to lightweight stubs when vibe_core is unavailable (e.g. CI,
    tests, or environments without steward-protocol checked out).
    """

    _ensure_local_steward_repo_on_path()

    try:
        from vibe_core.mahamantra.federation.types import (
            CityReport,
            FederationDirective,
            FederationMessage,
            FederationPriority,
        )
        from vibe_core.mahamantra.protocols._header import HEADER_SIZE_BYTES, MahaHeader
        from vibe_core.mahamantra.substrate.state.nadi import NADI_BUFFER_SIZE, NadiOp, NadiPriority

        return StewardSubstrateBindings(
            CityReport=CityReport,
            FederationDirective=FederationDirective,
            FederationMessage=FederationMessage,
            FederationPriority=FederationPriority,
            HEADER_SIZE_BYTES=HEADER_SIZE_BYTES,
            MahaHeader=MahaHeader,
            NADI_BUFFER_SIZE=NADI_BUFFER_SIZE,
            NadiOp=NadiOp,
            NadiPriority=NadiPriority,
        )
    except ImportError:
        return _build_stub_bindings()


def _build_stub_bindings() -> StewardSubstrateBindings:
    """Lightweight stubs that replicate the vibe_core interface for relay-only use."""
    import enum

    class _NadiPriority(enum.IntEnum):
        TAMAS = 0
        RAJAS = 1
        SATTVA = 2
        SUDDHA = 3

    class _NadiOp(enum.Enum):
        SEND = "send"
        RECEIVE = "receive"
        RELAY = "relay"
        BROADCAST = "broadcast"
        SUBSCRIBE = "subscribe"

    class _FederationMessage:
        __slots__ = ("source", "target", "operation", "payload", "priority",
                     "correlation_id", "timestamp", "ttl_s")

        def __init__(self, *, source: str, target: str, operation: str,
                     payload: dict, priority: int = 1, correlation_id: str = "",
                     timestamp: float = 0.0, ttl_s: float = 24.0):
            self.source = source
            self.target = target
            self.operation = operation
            self.payload = payload
            self.priority = priority
            self.correlation_id = correlation_id
            self.timestamp = timestamp
            self.ttl_s = ttl_s

        def to_dict(self) -> dict:
            return {
                "source": self.source, "target": self.target,
                "operation": self.operation, "payload": self.payload,
                "priority": self.priority, "correlation_id": self.correlation_id,
                "timestamp": self.timestamp, "ttl_s": self.ttl_s,
            }

        @classmethod
        def from_dict(cls, data: dict) -> "_FederationMessage":
            return cls(
                source=str(data.get("source", "")),
                target=str(data.get("target", "")),
                operation=str(data.get("operation", "")),
                payload=dict(data.get("payload", {})),
                priority=int(data.get("priority", 1)),
                correlation_id=str(data.get("correlation_id", "")),
                timestamp=float(data.get("timestamp", 0.0)),
                ttl_s=float(data.get("ttl_s", 24.0)),
            )

    class _Stub:
        pass

    return StewardSubstrateBindings(
        CityReport=_Stub,
        FederationDirective=_Stub,
        FederationMessage=_FederationMessage,
        FederationPriority=_Stub,
        HEADER_SIZE_BYTES=64,
        MahaHeader=_Stub,
        NADI_BUFFER_SIZE=4096,
        NadiOp=_NadiOp,
        NadiPriority=_NadiPriority,
    )


def _ensure_local_steward_repo_on_path() -> None:
    """Support sibling-repo development without requiring package installation."""

    repo_root = Path(__file__).resolve().parents[1]
    steward_root = repo_root.parent / "steward-protocol"
    if steward_root.exists() and str(steward_root) not in sys.path:
        sys.path.insert(0, str(steward_root))
