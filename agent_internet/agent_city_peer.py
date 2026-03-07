from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .agent_city_bridge import AgentCityBridge
from .agent_city_contract import AgentCityFilesystemContract
from .control_plane import AgentInternetControlPlane
from .file_locking import read_locked_json_value, write_locked_json_value
from .filesystem_transport import FilesystemFederationTransport
from .git_federation import detect_git_remote_metadata, write_git_federation_manifest
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
    def discover_from_repo_root(cls, root: Path | str) -> "AgentCityPeer":
        repo_root = Path(root).resolve()
        contract = AgentCityFilesystemContract(root=repo_root)
        raw = read_locked_json_value(contract.peer_descriptor_path, default={})
        if not isinstance(raw, dict) or not raw:
            raise FileNotFoundError(f"No peer descriptor found at {contract.peer_descriptor_path}")

        identity_raw = raw.get("identity")
        endpoint_raw = raw.get("endpoint")
        if not isinstance(identity_raw, dict) or not isinstance(endpoint_raw, dict):
            raise TypeError(f"Invalid peer descriptor at {contract.peer_descriptor_path}")

        capabilities = tuple(str(item) for item in raw.get("capabilities", ()))
        identity = CityIdentity(**identity_raw)
        endpoint = CityEndpoint(**endpoint_raw)
        transport = FilesystemFederationTransport(contract=contract)
        bridge = AgentCityBridge(city_id=identity.city_id, transport=transport, capabilities=capabilities)
        return cls(
            root=repo_root,
            identity=identity,
            endpoint=endpoint,
            contract=contract,
            transport=transport,
            bridge=bridge,
        )

    @classmethod
    def from_repo_root(
        cls,
        root: Path | str,
        *,
        city_id: str,
        repo: str | None = None,
        slug: str | None = None,
        public_key: str = "",
        capabilities: tuple[str, ...] = (),
        endpoint_transport: str = "filesystem",
        endpoint_location: str | None = None,
    ) -> "AgentCityPeer":
        repo_root = Path(root).resolve()
        repo_ref = repo or detect_git_remote_metadata(repo_root).repo_ref
        identity = CityIdentity(
            city_id=city_id,
            slug=slug or city_id,
            repo=repo_ref,
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

    def publish_self_description(self) -> dict:
        self.contract.ensure_dirs()
        payload = {
            "identity": asdict(self.identity),
            "endpoint": asdict(self.endpoint),
            "capabilities": list(self.bridge.capabilities),
        }
        try:
            remote = detect_git_remote_metadata(self.root)
        except Exception:
            remote = None
        if remote is not None:
            payload["git_federation"] = write_git_federation_manifest(
                self.contract.git_federation_manifest_path,
                peer_descriptor=payload,
                remote=remote,
                shared_pages=("Home.md", "Cities.md", "Services.md", "Routes.md", "Git-Federation.md"),
            )
        write_locked_json_value(self.contract.peer_descriptor_path, payload)
        return payload
