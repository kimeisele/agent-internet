from agent_internet.local_lab import LocalDualCityLab


def test_bidirectional_sync_worker_drains_both_city_outboxes(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.emit_outbox_message(
        "city-a",
        "city-b",
        operation="sync-a",
        payload={"from": "a"},
        correlation_id="env-a",
    )
    lab.emit_outbox_message(
        "city-b",
        "city-a",
        operation="sync-b",
        payload={"from": "b"},
        correlation_id="env-b",
    )

    result = lab.sync_once(drain_delivered=True)

    assert result.total_receipts == 2
    assert [receipt.status.value for receipt in result.receipts_by_city["city-a"]] == ["delivered"]
    assert [receipt.status.value for receipt in result.receipts_by_city["city-b"]] == ["delivered"]
    assert lab.read_outbox("city-a") == []
    assert lab.read_outbox("city-b") == []
    assert lab.read_inbox("city-a")[0].payload == {"from": "b"}
    assert lab.read_inbox("city-b")[0].payload == {"from": "a"}


def test_bidirectional_sync_worker_supports_multiple_bounded_cycles(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.emit_outbox_message(
        "city-a",
        "city-b",
        operation="sync-a",
        payload={"n": 1},
        correlation_id="env-1",
    )

    cycles = lab.sync_cycles(2, drain_delivered=True)

    assert [cycle.total_receipts for cycle in cycles] == [1, 0]