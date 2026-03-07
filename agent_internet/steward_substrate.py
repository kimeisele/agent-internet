from __future__ import annotations

from dataclasses import dataclass


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
    """

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
