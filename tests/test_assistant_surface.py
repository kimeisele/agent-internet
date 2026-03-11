import json

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.assistant_surface import (
    assistant_social_slot_from_snapshot,
    assistant_space_from_snapshot,
    assistant_surface_snapshot_from_repo_root,
)
from agent_internet.models import HealthStatus, SlotStatus, SpaceKind


def test_assistant_surface_snapshot_reads_city_artifacts(tmp_path, monkeypatch):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_9.json").write_text(
        json.dumps(
            {
                "heartbeat": 9,
                "timestamp": 200.0,
                "population": 3,
                "alive": 3,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [
                    {
                        "id": "internet-adaptation",
                        "title": "Internet adaptation",
                        "north_star": "Continuously adapt to relevant new protocols and standards.",
                        "status": "active",
                        "last_gap_summary": ["keep execution bounded"],
                    }
                ],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(
        json.dumps(
            {
                "followed": ["alice", "bob", "carol"],
                "invited": ["alice"],
                "spotlighted": ["post-1", "post-2"],
                "last_post_time": 150.0,
                "series_cursor": 4,
                "ops": {"follows": 5, "invites": 2, "posts": 1},
            },
        ),
    )
    AgentCityPeer.from_repo_root(repo_root, city_id="city-social", slug="social", repo="org/city-social").publish_self_description()
    monkeypatch.setattr("agent_internet.assistant_surface.time.time", lambda: 210.0)

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root)

    assert snapshot.city_id == "city-social"
    assert snapshot.city_slug == "social"
    assert snapshot.repo == "org/city-social"
    assert snapshot.heartbeat == 9
    assert snapshot.city_health == HealthStatus.HEALTHY
    assert snapshot.state_present is True
    assert snapshot.following == 3
    assert snapshot.invited == 1
    assert snapshot.spotlighted == 2
    assert snapshot.total_follows == 5
    assert snapshot.total_invites == 2
    assert snapshot.total_posts == 1
    assert snapshot.last_post_age_s == 60
    assert snapshot.series_cursor == 4
    assert snapshot.active_campaigns[0]["id"] == "internet-adaptation"
    assert snapshot.active_campaigns[0]["north_star"].startswith("Continuously adapt")


def test_assistant_surface_snapshot_accepts_city_id_without_peer_descriptor(tmp_path):
    repo_root = tmp_path / "city"
    (repo_root / "data").mkdir(parents=True)
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"]}))

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root, city_id="city-fallback")

    assert snapshot.city_id == "city-fallback"
    assert snapshot.following == 1
    assert snapshot.repo == ""
    assert snapshot.city_health == HealthStatus.UNKNOWN


def test_assistant_surface_snapshot_projects_space_and_slot(tmp_path, monkeypatch):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_3.json").write_text(
        json.dumps({"heartbeat": 3, "timestamp": 30.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    AgentCityPeer.from_repo_root(repo_root, city_id="city-space", slug="space", repo="org/city-space").publish_self_description()
    monkeypatch.setattr("agent_internet.assistant_surface.time.time", lambda: 60.0)

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root)
    space = assistant_space_from_snapshot(snapshot)
    slot = assistant_social_slot_from_snapshot(snapshot)

    assert space.space_id == "space:city-space:moltbook_assistant"
    assert space.kind == SpaceKind.ASSISTANT
    assert space.owner_subject_id == "city-space"
    assert slot.space_id == space.space_id
    assert slot.slot_kind == "assistant_social"
    assert slot.status == SlotStatus.ACTIVE
    assert space.last_seen_at == 30.0
    assert slot.last_seen_at == 30.0
    assert slot.lease_expires_at == 7230.0
    assert slot.labels["total_posts"] == "2"
    assert space.labels["campaign_count"] == "0"
    assert slot.labels["campaign_count"] == "0"


def test_assistant_surface_projects_stale_slot_as_dormant(tmp_path, monkeypatch):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_3.json").write_text(
        json.dumps({"heartbeat": 3, "timestamp": 30.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    AgentCityPeer.from_repo_root(repo_root, city_id="city-space", slug="space", repo="org/city-space").publish_self_description()
    monkeypatch.setattr("agent_internet.assistant_surface.time.time", lambda: 9000.0)

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root)
    slot = assistant_social_slot_from_snapshot(snapshot)

    assert slot.status == SlotStatus.DORMANT
    assert slot.lease_expires_at == 7230.0


def test_assistant_surface_projects_campaign_focus_labels(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [
                    {
                        "id": "internet-adaptation",
                        "title": "Internet adaptation",
                        "north_star": "Continuously adapt to relevant new protocols and standards.",
                        "status": "active",
                        "last_gap_summary": ["keep execution bounded"],
                    }
                ],
            },
        ),
    )
    AgentCityPeer.from_repo_root(repo_root, city_id="city-focus", slug="focus", repo="org/city-focus").publish_self_description()

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root)
    space = assistant_space_from_snapshot(snapshot)
    slot = assistant_social_slot_from_snapshot(snapshot)

    assert space.labels["campaign_count"] == "1"
    assert space.labels["campaign_focus"] == "Internet adaptation"
    assert slot.labels["campaign_count"] == "1"
    assert slot.labels["campaign_focus"] == "Internet adaptation"