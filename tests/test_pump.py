from agent_internet.local_lab import LocalDualCityLab


def test_outbox_pump_relays_and_optionally_drains_delivered_messages(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.emit_outbox_message(
        "city-a",
        "city-b",
        operation="sync",
        payload={"heartbeat": 9},
        correlation_id="corr-9",
    )

    receipts = lab.pump_outbox("city-a", drain_delivered=True)

    assert len(receipts) == 1
    assert receipts[0].status.value == "delivered"
    assert lab.read_outbox("city-a") == []
    inbox = lab.read_inbox("city-b")
    assert len(inbox) == 1
    assert inbox[0].payload == {"heartbeat": 9}
    assert inbox[0].correlation_id == "corr-9"
