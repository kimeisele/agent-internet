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


def test_receipt_store_compacts_by_age_and_max_entries(tmp_path):
    store = FilesystemReceiptStore(AgentCityFilesystemContract(root=tmp_path))

    store.record_delivery(
        envelope_id="env-1",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )
    store.record_delivery(
        envelope_id="env-2",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )
    store.record_delivery(
        envelope_id="env-3",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )

    receipts = store.list_receipts()
    receipts[0]["delivered_at"] = 10.0
    receipts[1]["delivered_at"] = 20.0
    receipts[2]["delivered_at"] = 30.0
    from agent_internet.file_locking import write_locked_json_value

    write_locked_json_value(store.contract.receipts_path, receipts)

    assert store.compact(older_than_s=15.0, now=40.0) == 2
    assert [entry["envelope_id"] for entry in store.list_receipts()] == ["env-3"]

    store.record_delivery(
        envelope_id="env-4",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )
    store.record_delivery(
        envelope_id="env-5",
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )
    assert store.compact(max_entries=2) == 1
    assert len(store.list_receipts()) == 2