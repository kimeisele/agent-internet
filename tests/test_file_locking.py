from multiprocessing import get_context
from pathlib import Path

from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.filesystem_transport import FilesystemFederationTransport
from agent_internet.receipt_store import FilesystemReceiptStore


def _append_outbox_entry(root: str, item_id: int) -> None:
    transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
    transport.append_to_outbox([{"id": item_id}])


def _record_receipt(root: str, envelope_id: str) -> None:
    store = FilesystemReceiptStore(AgentCityFilesystemContract(root=Path(root)))
    store.record_delivery(
        envelope_id=envelope_id,
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
    )


def test_parallel_outbox_appends_do_not_lose_messages(tmp_path):
    root = str(tmp_path / "city")
    ctx = get_context("spawn")
    processes = [ctx.Process(target=_append_outbox_entry, args=(root, idx)) for idx in range(8)]

    for process in processes:
        process.start()
    for process in processes:
        process.join()
        assert process.exitcode == 0

    transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
    assert sorted(item["id"] for item in transport.read_outbox()) == list(range(8))


def test_parallel_receipt_recording_keeps_single_envelope_entry(tmp_path):
    root = str(tmp_path / "city")
    ctx = get_context("spawn")
    processes = [ctx.Process(target=_record_receipt, args=(root, "env-1")) for _ in range(6)]

    for process in processes:
        process.start()
    for process in processes:
        process.join()
        assert process.exitcode == 0

    store = FilesystemReceiptStore(AgentCityFilesystemContract(root=Path(root)))
    receipts = store.list_receipts()
    assert len(receipts) == 1
    assert receipts[0]["envelope_id"] == "env-1"