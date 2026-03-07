from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_city_peer import AgentCityPeer
from .local_lab import LocalDualCityLab
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

    lab_init = subparsers.add_parser("init-dual-city-lab", help="Create a local two-city filesystem lab")
    lab_init.add_argument("--root", required=True)
    lab_init.add_argument("--city-a-id", default="city-a")
    lab_init.add_argument("--city-b-id", default="city-b")

    lab_send = subparsers.add_parser("lab-send", help="Relay a message between two local lab cities")
    lab_send.add_argument("--root", required=True)
    lab_send.add_argument("--source-city-id", required=True)
    lab_send.add_argument("--target-city-id", required=True)
    lab_send.add_argument("--operation", required=True)
    lab_send.add_argument("--payload-json", default="{}")
    lab_send.add_argument("--correlation-id", default="")

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


def cmd_init_dual_city_lab(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(
        args.root,
        city_a_id=args.city_a_id,
        city_b_id=args.city_b_id,
    )
    print(
        json.dumps(
            {
                "root": str(lab.root),
                "cities": [
                    {"city_id": city_id, "root": str(lab.city_root(city_id))}
                    for city_id in lab.city_ids
                ],
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_send(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.target_city_id)
    receipt = lab.send(
        args.source_city_id,
        args.target_city_id,
        operation=args.operation,
        payload=json.loads(args.payload_json),
        correlation_id=args.correlation_id,
    )
    inbox = lab.read_inbox(args.target_city_id)
    print(
        json.dumps(
            {
                "receipt": {
                    "status": receipt.status,
                    "transport": receipt.transport,
                    "target_city_id": receipt.target_city_id,
                    "detail": receipt.detail,
                },
                "target_inbox": [
                    {
                        "source_city_id": env.source_city_id,
                        "target_city_id": env.target_city_id,
                        "operation": env.operation,
                        "payload": env.payload,
                        "correlation_id": env.correlation_id,
                    }
                    for env in inbox
                ],
            },
            indent=2,
        ),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "onboard-agent-city":
        return cmd_onboard_agent_city(args)
    if args.command == "show-state":
        return cmd_show_state(args)
    if args.command == "init-dual-city-lab":
        return cmd_init_dual_city_lab(args)
    if args.command == "lab-send":
        return cmd_lab_send(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
