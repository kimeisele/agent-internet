from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")


def load_agent_web_wordnet_bridge(path: Path | str | None = None) -> dict:
    resolved = resolve_agent_web_wordnet_bridge_path(path)
    state = _load_wordnet_bridge_state("" if resolved is None else str(resolved))
    return {
        "kind": "agent_web_wordnet_bridge",
        "version": 1,
        "available": bool(state["available"]),
        "path": str(resolved) if resolved is not None else "",
        "source": str(state["source"]),
        "stats": {
            "synset_count": int(state["synset_count"]),
            "word_entry_count": int(state["word_entry_count"]),
            "token_count": int(state["token_count"]),
        },
    }


def resolve_agent_web_wordnet_bridge_path(path: Path | str | None = None) -> Path | None:
    candidates: list[Path] = []
    if path is not None and str(path).strip():
        candidates.append(Path(str(path)).expanduser())
    env_path = os.environ.get("AGENT_WEB_WORDNET_BRIDGE_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    project_root = Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            project_root / "data" / "wordnet_bridge.json",
            project_root / "data" / "control_plane" / "wordnet_bridge.json",
            project_root.parent / "steward-protocol" / "vibe_core" / "mahamantra" / "data" / "wordnet_bridge.json",
        ],
    )
    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def wordnet_phrase_score(text: str, candidate_text: str, *, bridge: dict | None = None, path: Path | str | None = None) -> float:
    input_tokens = set(_input_tokens(text))
    candidate_tokens = set(_input_tokens(candidate_text))
    if not input_tokens or not candidate_tokens:
        return 0.0

    exact = input_tokens & candidate_tokens
    if exact:
        return min(1.0, len(exact) / len(input_tokens))

    active_bridge = bridge or load_agent_web_wordnet_bridge(path)
    state = _load_wordnet_bridge_state(str(active_bridge.get("path", "")))
    if bool(state["available"]):
        input_chain = _phrase_chain_ints(text, state)
        candidate_chain = _phrase_chain_ints(candidate_text, state)
        if input_chain and candidate_chain:
            inter = len(input_chain & candidate_chain)
            union = len(input_chain | candidate_chain)
            if union > 0:
                jaccard = inter / union
                if jaccard > 0.01:
                    return min(0.8, jaccard * 2.0)

    morph = _input_stems(text) & _input_stems(candidate_text)
    if morph:
        return min(0.5, len(morph) * 0.15)
    return 0.0


@lru_cache(maxsize=8)
def _load_wordnet_bridge_state(resolved_path: str) -> dict:
    if not resolved_path:
        return _empty_state()
    path = Path(resolved_path)
    if not path.exists():
        return _empty_state()
    payload = json.loads(path.read_text())
    word_entries = dict(payload.get("words", {})) if isinstance(payload.get("words", {}), dict) else {}
    token_to_chains: dict[str, set[int]] = {}
    for entry in word_entries.values():
        if not isinstance(entry, dict):
            continue
        chains = [int(item) for item in entry.get("c", [])]
        for token in entry.get("t", []):
            normalized = str(token).strip().lower()
            if not normalized:
                continue
            token_to_chains.setdefault(normalized, set()).update(chains)
    source = "steward-protocol" if "steward-protocol" in resolved_path else "custom"
    return {
        "available": True,
        "source": source,
        "synset_count": len(list(payload.get("synsets", []))),
        "word_entry_count": len(word_entries),
        "token_count": len(token_to_chains),
        "token_to_chains": {key: frozenset(value) for key, value in token_to_chains.items()},
    }


def _phrase_chain_ints(text: str, state: dict) -> frozenset[int]:
    combined: set[int] = set()
    token_to_chains = dict(state.get("token_to_chains", {}))
    for token in _input_tokens(text):
        combined.update(token_to_chains.get(token, ()))
    return frozenset(combined)


def _input_tokens(text: str) -> list[str]:
    return [match.group().lower() for match in _TOKEN_RE.finditer(str(text))]


def _input_stems(text: str) -> frozenset[str]:
    stems: set[str] = set()
    for token in _input_tokens(text):
        stems.add(token)
        if len(token) >= 4:
            stems.add(token[:4])
    return frozenset(stems)


def _empty_state() -> dict:
    return {
        "available": False,
        "source": "unavailable",
        "synset_count": 0,
        "word_entry_count": 0,
        "token_count": 0,
        "token_to_chains": {},
    }