from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StewardProtocolBindings:
    available: bool
    source: str
    allowed_nadi_types: tuple[str, ...]
    allowed_priorities: tuple[str, ...]
    default_route_nadi_type: str
    default_route_priority: str
    default_timeout_ms: int
    maha_header_available: bool
    MahaHeader: type | None = None


def _ensure_local_steward_protocol_repo_on_path() -> str | None:
    repo_root = Path(__file__).resolve().parents[1]
    steward_root = repo_root.parent / "steward-protocol"
    if steward_root.exists() and str(steward_root) not in sys.path:
        sys.path.insert(0, str(steward_root))
        return "local_repo"
    if steward_root.exists():
        return "local_repo"
    return None


def load_steward_protocol_bindings() -> StewardProtocolBindings:
    source = _ensure_local_steward_protocol_repo_on_path() or "fallback"
    try:
        from vibe_core.mahamantra.protocols._header import MahaHeader
        from vibe_core.mahamantra.substrate.state.nadi import NADI_TIMEOUT_MS, NadiPriority, NadiType

        return StewardProtocolBindings(
            available=True,
            source=source if source != "fallback" else "installed",
            allowed_nadi_types=tuple(member.name.lower() for member in NadiType),
            allowed_priorities=tuple(member.name.lower() for member in NadiPriority),
            default_route_nadi_type=NadiType.VYANA.name.lower(),
            default_route_priority=NadiPriority.RAJAS.name.lower(),
            default_timeout_ms=int(NADI_TIMEOUT_MS),
            maha_header_available=True,
            MahaHeader=MahaHeader,
        )
    except Exception:
        return StewardProtocolBindings(
            available=False,
            source="fallback",
            allowed_nadi_types=("prana", "apana", "vyana", "udana", "samana"),
            allowed_priorities=("tamas", "rajas", "sattva", "suddha"),
            default_route_nadi_type="vyana",
            default_route_priority="rajas",
            default_timeout_ms=24_000,
            maha_header_available=False,
            MahaHeader=None,
        )


def summarize_steward_protocol_bindings() -> dict:
    bindings = load_steward_protocol_bindings()
    return asdict(bindings) | {"MahaHeader": None}


def build_maha_route_header_hex(*, source_key: str, target_key: str, ttl_ms: int, metric: int) -> str:
    bindings = load_steward_protocol_bindings()
    if bindings.MahaHeader is None:
        return ""
    MahaHeader = bindings.MahaHeader
    source_id = _stable_u64(source_key)
    target_id = _stable_u64(target_key)
    link_id = _stable_u64(f"{source_key}->{target_key}")
    operation_id = _stable_u64("lotus.route.v1")
    signature_id = _stable_u64("steward-protocol")
    intent_mask = metric & ((1 << 64) - 1)
    state_value = _stable_u64(f"metric:{metric}")
    checksum = source_id ^ target_id ^ link_id ^ operation_id ^ signature_id ^ intent_mask ^ ttl_ms ^ state_value
    header = MahaHeader(
        sravanam=source_id,
        kirtanam=target_id,
        smaranam=link_id,
        pada_sevanam=operation_id,
        arcanam=signature_id,
        vandanam=intent_mask,
        dasyam=max(0, int(ttl_ms)),
        sakhyam=state_value,
        atma_nivedanam=checksum,
    )
    return header.to_bytes().hex()


def _stable_u64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")