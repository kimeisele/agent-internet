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

    lab_emit_outbox = subparsers.add_parser(
        "lab-emit-outbox",
        help="Append a message to a local lab city's real federation outbox",
    )
    lab_emit_outbox.add_argument("--root", required=True)
    lab_emit_outbox.add_argument("--source-city-id", required=True)
    lab_emit_outbox.add_argument("--target-city-id", required=True)
    lab_emit_outbox.add_argument("--operation", required=True)
    lab_emit_outbox.add_argument("--payload-json", default="{}")
    lab_emit_outbox.add_argument("--correlation-id", default="")

    lab_pump_outbox = subparsers.add_parser(
        "lab-pump-outbox",
        help="Pump a local lab city's federation outbox through agent-internet relay",
    )
    lab_pump_outbox.add_argument("--root", required=True)
    lab_pump_outbox.add_argument("--source-city-id", required=True)
    lab_pump_outbox.add_argument("--drain-delivered", action="store_true")

    lab_sync = subparsers.add_parser(
        "lab-sync",
        help="Run bounded bidirectional sync cycles between the two local lab cities",
    )
    lab_sync.add_argument("--root", required=True)
    lab_sync.add_argument("--city-a-id", default="city-a")
    lab_sync.add_argument("--city-b-id", default="city-b")
    lab_sync.add_argument("--cycles", type=int, default=1)
    lab_sync.add_argument("--drain-delivered", action="store_true")

    lab_compact_receipts = subparsers.add_parser(
        "lab-compact-receipts",
        help="Compact a local lab city's receipt journal by age and/or max retained entries",
    )
    lab_compact_receipts.add_argument("--root", required=True)
    lab_compact_receipts.add_argument("--city-id", required=True)
    lab_compact_receipts.add_argument("--max-entries", type=int)
    lab_compact_receipts.add_argument("--older-than-s", type=float)

    lab_issue_directive = subparsers.add_parser(
        "lab-issue-directive",
        help="Write an agent-city federation directive into a local lab city's directive intake",
    )
    lab_issue_directive.add_argument("--root", required=True)
    lab_issue_directive.add_argument("--city-id", required=True)
    lab_issue_directive.add_argument("--directive-type", required=True)
    lab_issue_directive.add_argument("--params-json", default="{}")
    lab_issue_directive.add_argument("--directive-id", default="")
    lab_issue_directive.add_argument("--source", default="agent-internet")

    lab_run_directives = subparsers.add_parser(
        "lab-run-directives",
        help="Execute pending agent-city federation directives through the real GENESIS directive hook",
    )
    lab_run_directives.add_argument("--root", required=True)
    lab_run_directives.add_argument("--city-id", required=True)
    lab_run_directives.add_argument("--agent-name", default="")

    lab_immigrate = subparsers.add_parser(
        "lab-immigrate",
        help="Run a dual-city immigration flow against a host city's real ImmigrationService",
    )
    lab_immigrate.add_argument("--root", required=True)
    lab_immigrate.add_argument("--source-city-id", required=True)
    lab_immigrate.add_argument("--host-city-id", required=True)
    lab_immigrate.add_argument("--agent-name", required=True)
    lab_immigrate.add_argument("--visa-class", default="worker")
    lab_immigrate.add_argument("--reason", default="temporary_visitor")
    lab_immigrate.add_argument("--sponsor", default="city_genesis")

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


def cmd_lab_emit_outbox(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.target_city_id)
    count = lab.emit_outbox_message(
        args.source_city_id,
        args.target_city_id,
        operation=args.operation,
        payload=json.loads(args.payload_json),
        correlation_id=args.correlation_id,
    )
    print(
        json.dumps(
            {
                "appended": count,
                "source_outbox": lab.read_outbox(args.source_city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_pump_outbox(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.source_city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=other_city)
    receipts = lab.pump_outbox(args.source_city_id, drain_delivered=args.drain_delivered)
    print(
        json.dumps(
            {
                "receipts": [
                    {
                        "status": receipt.status,
                        "transport": receipt.transport,
                        "target_city_id": receipt.target_city_id,
                        "detail": receipt.detail,
                    }
                    for receipt in receipts
                ],
                "remaining_outbox": lab.read_outbox(args.source_city_id),
                "target_receipts": lab.read_receipts(other_city),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_sync(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_a_id, city_b_id=args.city_b_id)
    cycles = lab.sync_cycles(args.cycles, drain_delivered=args.drain_delivered)
    print(
        json.dumps(
            {
                "cycles": [
                    {
                        "cycle": cycle.cycle,
                        "receipts_by_city": {
                            city_id: [
                                {
                                    "status": receipt.status,
                                    "transport": receipt.transport,
                                    "target_city_id": receipt.target_city_id,
                                    "detail": receipt.detail,
                                }
                                for receipt in receipts
                            ]
                            for city_id, receipts in cycle.receipts_by_city.items()
                        },
                        "total_receipts": cycle.total_receipts,
                    }
                    for cycle in cycles
                ],
                "outboxes": {city_id: lab.read_outbox(city_id) for city_id in lab.city_ids},
                "receipts": {city_id: lab.read_receipts(city_id) for city_id in lab.city_ids},
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_compact_receipts(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    removed = lab.compact_receipts(
        args.city_id,
        max_entries=args.max_entries,
        older_than_s=args.older_than_s,
    )
    print(
        json.dumps(
            {
                "removed": removed,
                "remaining_receipts": lab.read_receipts(args.city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_issue_directive(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    directive_id = lab.issue_directive(
        args.city_id,
        directive_type=args.directive_type,
        params=json.loads(args.params_json),
        directive_id=args.directive_id,
        source=args.source,
    )
    print(
        json.dumps(
            {
                "directive_id": directive_id,
                "pending_directives": lab.read_directives(args.city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_run_directives(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    result = lab.execute_directives(args.city_id)
    print(
        json.dumps(
            {
                "operations": result.operations,
                "acknowledged": result.acknowledged,
                "pending_directives": result.pending_directives,
                "agent": None if not args.agent_name else lab.read_agent(args.city_id, args.agent_name),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_immigrate(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.host_city_id)
    result = lab.run_immigration_flow(
        source_city_id=args.source_city_id,
        host_city_id=args.host_city_id,
        agent_name=args.agent_name,
        visa_class=args.visa_class,
        reason=args.reason,
        sponsor=args.sponsor,
    )
    application = result["application"]
    visa = result["visa"]
    receipt = result["receipt"]
    print(
        json.dumps(
            {
                "receipt": {
                    "status": receipt.status,
                    "transport": receipt.transport,
                    "target_city_id": receipt.target_city_id,
                },
                "application": {
                    "application_id": application.application_id,
                    "agent_name": application.agent_name,
                    "status": application.status.value,
                    "requested_visa_class": application.requested_visa_class.value,
                },
                "visa": {
                    "agent_name": visa.agent_name,
                    "visa_class": visa.visa_class.value,
                    "sponsor": visa.sponsor,
                    "lineage_depth": visa.lineage_depth,
                },
                "stats": result["stats"],
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
    if args.command == "lab-emit-outbox":
        return cmd_lab_emit_outbox(args)
    if args.command == "lab-pump-outbox":
        return cmd_lab_pump_outbox(args)
    if args.command == "lab-sync":
        return cmd_lab_sync(args)
    if args.command == "lab-compact-receipts":
        return cmd_lab_compact_receipts(args)
    if args.command == "lab-issue-directive":
        return cmd_lab_issue_directive(args)
    if args.command == "lab-run-directives":
        return cmd_lab_run_directives(args)
    if args.command == "lab-immigrate":
        return cmd_lab_immigrate(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
