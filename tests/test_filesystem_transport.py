import json

from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.filesystem_transport import FilesystemFederationTransport


def test_read_outbox_accepts_single_dict_payload(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    contract.ensure_dirs()
    contract.nadi_outbox.write_text(json.dumps({"source": "city-a", "operation": "report"}))

    transport = FilesystemFederationTransport(contract=contract)

    assert transport.read_outbox() == [{"source": "city-a", "operation": "report"}]


def test_append_to_inbox_merges_existing_messages(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    contract.ensure_dirs()
    contract.nadi_inbox.write_text(json.dumps([{"source": "old", "operation": "keep"}]))

    transport = FilesystemFederationTransport(contract=contract)
    count = transport.append_to_inbox([{"source": "new", "operation": "deliver"}])

    assert count == 1
    assert json.loads(contract.nadi_inbox.read_text()) == [
        {"source": "old", "operation": "keep"},
        {"source": "new", "operation": "deliver"},
    ]


def test_write_directive_uses_agent_city_contract_location(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)

    transport.write_directive({"id": "dir-1", "directive_type": "route"}, directive_id="dir-1")

    payload = json.loads(contract.directive_path("dir-1").read_text())
    assert payload["directive_type"] == "route"


def test_list_reports_reads_report_directory(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    contract.ensure_dirs()
    (contract.reports_dir / "report_2.json").write_text(json.dumps({"heartbeat": 2}))
    (contract.reports_dir / "report_1.json").write_text(json.dumps({"heartbeat": 1}))

    transport = FilesystemFederationTransport(contract=contract)

    assert transport.list_reports() == [{"heartbeat": 1}, {"heartbeat": 2}]


def test_list_directives_reads_pending_directive_directory(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    contract.ensure_dirs()
    contract.directive_path("dir-2").write_text(json.dumps({"id": "dir-2"}))
    contract.directive_path("dir-1").write_text(json.dumps({"id": "dir-1"}))
    (contract.directives_dir / "ignored.done.json").write_text(json.dumps({"id": "ignored"}))

    transport = FilesystemFederationTransport(contract=contract)

    assert transport.list_directives() == [{"id": "dir-1"}, {"id": "dir-2"}]

