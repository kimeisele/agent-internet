from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


def _ensure_local_agent_city_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_city_root = repo_root.parent / "agent-city"
    if agent_city_root.exists() and str(agent_city_root) not in sys.path:
        sys.path.insert(0, str(agent_city_root))


@dataclass(frozen=True, slots=True)
class AgentCityImmigrationBindings:
    ApplicationReason: type
    ApplicationStatus: type
    ImmigrationService: type
    VisaClass: type


def load_agent_city_immigration_bindings() -> AgentCityImmigrationBindings:
    _ensure_local_agent_city_repo_on_path()

    from city.immigration import ApplicationReason, ApplicationStatus, ImmigrationService
    from city.visa import VisaClass

    return AgentCityImmigrationBindings(
        ApplicationReason=ApplicationReason,
        ApplicationStatus=ApplicationStatus,
        ImmigrationService=ImmigrationService,
        VisaClass=VisaClass,
    )


@dataclass(slots=True)
class AgentCityImmigrationAdapter:
    root: Path | str
    bindings: AgentCityImmigrationBindings = field(default_factory=load_agent_city_immigration_bindings)
    _service: object | None = field(default=None, init=False, repr=False)

    @property
    def repo_root(self) -> Path:
        return Path(self.root).resolve()

    @property
    def db_path(self) -> Path:
        return self.repo_root / "data" / "immigration.sqlite3"

    def service(self) -> object:
        if self._service is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._service = self.bindings.ImmigrationService(str(self.db_path))
        return self._service

    def ensure_mahajan(self, agent_name: str) -> object:
        visa = self.get_visa(agent_name)
        if visa is not None:
            return visa
        return self.service().register_mahajan(agent_name)

    def submit_application(self, agent_name: str, *, reason: str, visa_class: str) -> object:
        return self.service().submit_application(
            agent_name,
            self.bindings.ApplicationReason(reason),
            self.bindings.VisaClass(visa_class),
        )

    def approve_and_grant(
        self,
        app_id: str,
        *,
        reviewer: str = "dual-city-lab",
        sponsor: str = "city_genesis",
        community_score: float = 1.0,
        council_vote_id: str | None = None,
        vote_tally: dict[str, int] | None = None,
    ) -> object:
        service = self.service()
        if not service.start_review(app_id, reviewer):
            raise RuntimeError(f"Could not start review for application {app_id}")
        if not service.complete_review(
            app_id,
            kyc_passed=True,
            contracts_passed=True,
            community_score=community_score,
            notes="dual-city-lab auto approval",
        ):
            raise RuntimeError(f"Could not complete review for application {app_id}")
        vote_id = council_vote_id or f"lab-vote-{int(time.time())}"
        if not service.move_to_council(app_id, vote_id):
            raise RuntimeError(f"Could not move application {app_id} to council")
        tally = vote_tally or {"yes": 5, "no": 0, "abstain": 0}
        if not service.record_council_vote(app_id, approved=True, vote_tally=tally):
            raise RuntimeError(f"Could not record council vote for application {app_id}")
        visa = service.grant_citizenship(app_id, sponsor=sponsor)
        if visa is None:
            raise RuntimeError(f"Could not grant citizenship for application {app_id}")
        return visa

    def get_application(self, app_id: str) -> object | None:
        return self.service().get_application(app_id)

    def get_visa(self, agent_name: str) -> object | None:
        return self.service().get_visa(agent_name)

    def stats(self) -> dict:
        return dict(self.service().stats())
