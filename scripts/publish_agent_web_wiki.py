#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_internet.publisher import publish_agent_internet_wiki, write_publication_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Agent Internet wiki surfaces")
    parser.add_argument("--state-path", default="data/control_plane/state.json")
    parser.add_argument("--wiki-path")
    parser.add_argument("--wiki-url")
    parser.add_argument("--city-id", default="agent-internet")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--result-path")
    args = parser.parse_args()
    result = publish_agent_internet_wiki(
        root=ROOT,
        state_path=ROOT / args.state_path,
        wiki_path=Path(args.wiki_path).resolve() if args.wiki_path else None,
        wiki_repo_url=args.wiki_url,
        push=args.push,
        city_id=args.city_id,
    )
    if args.result_path:
        write_publication_result(ROOT / args.result_path, result)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())