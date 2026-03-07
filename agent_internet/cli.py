from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_city_peer import AgentCityPeer
from .models import TrustLevel, TrustRecord
from .snapshot import ControlPlaneStateStore, snapshot_control_plane


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-internet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    onboard = subparsers.add_parser("onboard-agent-city", help="Onboard an agent-city repository root")
    onboard.add_argument("--root", required=True)
    onboard.add_argument("--city-id", required=True)
    onboard.add_argument("--repo", required=True)
    onboard.add_argument("--slug")
    onboard.add_argument("--public-key", default="")
    onboard.add_argument("--capability", action="append", default=[])
    onboard.add_argument("--endpoint-transport", default="filesystem")
    onboard.add_argument("--endpoint-location")
    onboard.add_argument("--state-path", default="data/control_plane/state.json")
    onboard.add_argument("--trust-source", default="agent-internet")
    onboard.add_argument(
        "--trust-level",
        choices=[level.value for level in TrustLevel],
        default=TrustLevel.OBSERVED.value,
    )

    show = subparsers.add_parser("show-state", help="Print the current persisted control-plane state")
    show.add_argument("--state-path", default="data/control_plane/state.json")

    return parser


def cmd_onboard_agent_city(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    peer = AgentCityPeer.from_repo_root(
        args.root,
        city_id=args.city_id,
        repo=args.repo,
        slug=args.slug,
        public_key=args.public_key,
        capabilities=tuple(args.capability),
        endpoint_transport=args.endpoint_transport,
        endpoint_location=args.endpoint_location,
    )
    observed = peer.onboard(plane)
    plane.record_trust(
        TrustRecord(
            issuer_city_id=args.trust_source,
            subject_city_id=args.city_id,
            level=TrustLevel(args.trust_level),
            reason="cli onboarding",
        ),
    )
    store.save(plane)
    print(
        json.dumps(
            {
                "city_id": args.city_id,
                "observed": None
                if observed is None
                else {
                    "health": observed.health,
                    "heartbeat": observed.heartbeat,
                    "last_seen_at": observed.last_seen_at,
                },
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_show_state(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    print(json.dumps(snapshot_control_plane(plane), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "onboard-agent-city":
        return cmd_onboard_agent_city(args)
    if args.command == "show-state":
        return cmd_show_state(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
