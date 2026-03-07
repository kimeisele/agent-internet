import json

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.assistant_surface import assistant_surface_snapshot_from_repo_root
from agent_internet.models import HealthStatus


def test_assistant_surface_snapshot_reads_city_artifacts(tmp_path, monkeypatch):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_9.json").write_text(
        json.dumps({"heartbeat": 9, "timestamp": 200.0, "population": 3, "alive": 3, "dead": 0, "chain_valid": True}),
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


def test_assistant_surface_snapshot_accepts_city_id_without_peer_descriptor(tmp_path):
    repo_root = tmp_path / "city"
    (repo_root / "data").mkdir(parents=True)
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"]}))

    snapshot = assistant_surface_snapshot_from_repo_root(repo_root, city_id="city-fallback")

    assert snapshot.city_id == "city-fallback"
    assert snapshot.following == 1
    assert snapshot.repo == ""
    assert snapshot.city_health == HealthStatus.UNKNOWN