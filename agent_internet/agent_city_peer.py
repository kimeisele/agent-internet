from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent_city_bridge import AgentCityBridge
from .agent_city_contract import AgentCityFilesystemContract
from .control_plane import AgentInternetControlPlane
from .filesystem_transport import FilesystemFederationTransport
from .models import CityEndpoint, CityIdentity, CityPresence


@dataclass(slots=True)
class AgentCityPeer:
    root: Path
    identity: CityIdentity
    endpoint: CityEndpoint
    contract: AgentCityFilesystemContract
    transport: FilesystemFederationTransport
    bridge: AgentCityBridge

    @classmethod
    def from_repo_root(
        cls,
        root: Path | str,
        *,
        city_id: str,
        repo: str,
        slug: str | None = None,
        public_key: str = "",
        capabilities: tuple[str, ...] = (),
        endpoint_transport: str = "filesystem",
        endpoint_location: str | None = None,
    ) -> "AgentCityPeer":
        repo_root = Path(root).resolve()
        identity = CityIdentity(
            city_id=city_id,
            slug=slug or city_id,
            repo=repo,
            public_key=public_key,
        )
        endpoint = CityEndpoint(
            city_id=city_id,
            transport=endpoint_transport,
            location=endpoint_location or str(repo_root),
        )
        contract = AgentCityFilesystemContract(root=repo_root)
        transport = FilesystemFederationTransport(contract=contract)
        bridge = AgentCityBridge(city_id=city_id, transport=transport, capabilities=capabilities)
        return cls(
            root=repo_root,
            identity=identity,
            endpoint=endpoint,
            contract=contract,
            transport=transport,
            bridge=bridge,
        )

    def onboard(self, plane: AgentInternetControlPlane) -> CityPresence | None:
        plane.register_city(self.identity, self.endpoint)
        return plane.observe_agent_city(self.bridge, identity=self.identity, endpoint=self.endpoint)
