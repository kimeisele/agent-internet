from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import FederationTransport
from .steward_substrate import StewardSubstrateBindings, load_steward_substrate


def _directive_id_of(directive: object) -> str:
    if isinstance(directive, dict):
        directive_id = directive.get("id", "")
    else:
        directive_id = getattr(directive, "id", "")
    if not isinstance(directive_id, str) or not directive_id:
        raise ValueError("Directive must provide a non-empty id")
    return directive_id


@dataclass(slots=True)
class StewardFederationAdapter:
    """Typed adapter over the generic federation transport.

    Reads and writes canonical steward-protocol federation objects while keeping
    the underlying transport simple and agent-city-compatible.
    """

    transport: FederationTransport
    bindings: StewardSubstrateBindings = field(default_factory=load_steward_substrate)

    def read_outbox_messages(self) -> list[object]:
        return [self.bindings.FederationMessage.from_dict(item) for item in self.transport.read_outbox()]

    def append_inbox_messages(self, messages: list[object]) -> int:
        return self.transport.append_to_inbox(messages)

    def list_city_reports(self) -> list[object]:
        return [self.bindings.CityReport.from_dict(item) for item in self.transport.list_reports()]

    def latest_city_report(self) -> object | None:
        reports = self.list_city_reports()
        if not reports:
            return None
        return max(reports, key=lambda report: (report.heartbeat, report.timestamp))

    def list_directives(self) -> list[object]:
        return [
            self.bindings.FederationDirective.from_dict(item)
            for item in self.transport.list_directives()
        ]

    def write_directive(self, directive: object) -> None:
        self.transport.write_directive(directive, directive_id=_directive_id_of(directive))
