from agent_internet.local_lab import LocalDualCityLab
from agent_internet.transport import DeliveryStatus


def test_local_dual_city_lab_creates_city_roots_and_relays_messages(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")

    assert lab.city_root("city-a").is_dir()
    assert lab.city_root("city-b").is_dir()
    assert (lab.city_root("city-a") / "data" / "federation" / "peer.json").exists()
    assert lab.lotus_addresses("city-a")["link"]["mac_address"].startswith("02:00:")
    assert lab.lotus_addresses("city-b")["network"]["ip_address"].startswith("fd10:")

    receipt = lab.send(
        "city-a",
        "city-b",
        operation="sync",
        payload={"heartbeat": 2},
        correlation_id="corr-7",
        nadi_type="udana",
        nadi_op="delegate",
        priority="suddha",
        ttl_ms=48000,
    )

    assert receipt.status == DeliveryStatus.DELIVERED
    inbox = lab.read_inbox("city-b")
    assert len(inbox) == 1
    assert inbox[0].operation == "sync"
    assert inbox[0].payload == {"heartbeat": 2}
    assert inbox[0].correlation_id == "corr-7"
    assert inbox[0].nadi_type == "udana"
    assert inbox[0].nadi_op == "delegate"
    assert inbox[0].priority == "suddha"
    assert inbox[0].ttl_ms == 48000
