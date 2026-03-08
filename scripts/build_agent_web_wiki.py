#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_internet.publisher import build_agent_internet_wiki


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local Agent Internet wiki surfaces")
    parser.add_argument("--output-dir", default=".agent_internet/wiki-build")
    parser.add_argument("--state-path", default="data/control_plane/state.json")
    parser.add_argument("--city-id", default="agent-internet")
    args = parser.parse_args()
    built = build_agent_internet_wiki(
        root=ROOT,
        output_dir=ROOT / args.output_dir,
        state_path=ROOT / args.state_path,
        city_id=args.city_id,
    )
    print(f"built {len(built)} pages into {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())