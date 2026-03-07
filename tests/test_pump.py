from agent_internet.local_lab import LocalDualCityLab


def test_outbox_pump_relays_and_optionally_drains_delivered_messages(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.emit_outbox_message(
        "city-a",
        "city-b",
        operation="sync",
        payload={"heartbeat": 9},
        correlation_id="env-9",
        nadi_type="udana",
        nadi_op="delegate",
        priority="suddha",
        ttl_ms=48000,
    )

    receipts = lab.pump_outbox("city-a", drain_delivered=True)

    assert len(receipts) == 1
    assert receipts[0].status.value == "delivered"
    assert lab.read_outbox("city-a") == []
    inbox = lab.read_inbox("city-b")
    assert len(inbox) == 1
    assert inbox[0].payload == {"heartbeat": 9}
    assert inbox[0].correlation_id == "env-9"
    assert inbox[0].nadi_type == "udana"
    assert inbox[0].nadi_op == "delegate"
    assert inbox[0].priority == "suddha"
    assert inbox[0].ttl_ms == 48000
    assert lab.read_receipts("city-b")[0]["envelope_id"] == "env-9"


def test_outbox_pump_treats_duplicate_delivery_as_drainable_success(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.emit_outbox_message(
        "city-a",
        "city-b",
        operation="sync",
        payload={"heartbeat": 10},
        correlation_id="env-10",
    )

    first = lab.pump_outbox("city-a", drain_delivered=False)
    second = lab.pump_outbox("city-a", drain_delivered=True)

    assert first[0].status.value == "delivered"
    assert second[0].status.value == "duplicate"
    assert lab.read_outbox("city-a") == []
