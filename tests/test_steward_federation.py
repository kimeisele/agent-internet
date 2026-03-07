import json

import pytest

pytest.importorskip("vibe_core")

from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.filesystem_transport import FilesystemFederationTransport
from agent_internet.steward_federation import StewardFederationAdapter
from agent_internet.steward_substrate import load_steward_substrate


def test_adapter_reads_typed_messages_reports_and_directives(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    contract.ensure_dirs()
    contract.nadi_outbox.write_text(
        json.dumps([{"source": "city-a", "target": "steward", "operation": "sync", "payload": {}, "priority": 1}]),
    )
    (contract.reports_dir / "report_9.json").write_text(
        json.dumps({
            "heartbeat": 9,
            "timestamp": 9.0,
            "population": 3,
            "alive": 3,
            "dead": 0,
            "elected_mayor": None,
            "council_seats": 0,
            "open_proposals": 0,
            "chain_valid": True,
        }),
    )
    contract.directive_path("dir-1").write_text(
        json.dumps({"id": "dir-1", "directive_type": "sync", "params": {}, "timestamp": 1.0}),
    )
    adapter = StewardFederationAdapter(transport=FilesystemFederationTransport(contract=contract))

    messages = adapter.read_outbox_messages()
    reports = adapter.list_city_reports()
    directives = adapter.list_directives()

    assert messages[0].operation == "sync"
    assert reports[0].heartbeat == 9
    assert directives[0].directive_type == "sync"


def test_adapter_writes_typed_directive_and_inbox_message(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)
    adapter = StewardFederationAdapter(transport=transport)
    bindings = load_steward_substrate()

    directive = bindings.FederationDirective(id="dir-2", directive_type="route", params={"city": "b"})
    message = bindings.FederationMessage(source="steward", target="city-b", operation="send", payload={})

    adapter.write_directive(directive)
    assert adapter.append_inbox_messages([message]) == 1

    assert json.loads(contract.directive_path("dir-2").read_text())["directive_type"] == "route"
    assert json.loads(contract.nadi_inbox.read_text())[0]["source"] == "steward"
