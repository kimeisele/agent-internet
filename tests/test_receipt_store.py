from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.receipt_store import FilesystemReceiptStore


def test_receipt_store_records_once_per_envelope(tmp_path):
    store = FilesystemReceiptStore(AgentCityFilesystemContract(root=tmp_path))

    store.record_delivery(
        envelope_id="env-1",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )
    store.record_delivery(
        envelope_id="env-1",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )

    entries = store.list_receipts()
    assert len(entries) == 1
    assert store.has_envelope("env-1") is True