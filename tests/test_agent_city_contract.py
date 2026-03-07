from pathlib import Path

from agent_internet.agent_city_contract import AgentCityFilesystemContract


def test_contract_resolves_standard_paths(tmp_path: Path):
    contract = AgentCityFilesystemContract(root=tmp_path)

    assert contract.data_dir == tmp_path / "data"
    assert contract.assistant_state_path == tmp_path / "data" / "assistant_state.json"
    assert contract.federation_dir == tmp_path / "data" / "federation"
    assert contract.nadi_outbox == tmp_path / "data" / "federation" / "nadi_outbox.json"
    assert contract.nadi_inbox == tmp_path / "data" / "federation" / "nadi_inbox.json"
    assert contract.directive_path("dir-1") == contract.directives_dir / "dir-1.json"


def test_contract_creates_required_directories(tmp_path: Path):
    contract = AgentCityFilesystemContract(root=tmp_path)

    contract.ensure_dirs()

    assert contract.federation_dir.is_dir()
    assert contract.reports_dir.is_dir()
    assert contract.directives_dir.is_dir()
