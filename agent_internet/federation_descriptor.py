from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


FEDERATION_DESCRIPTOR_KIND = "agent_federation_descriptor"
FEDERATION_DESCRIPTOR_VERSION = 1


class FederationProjectionIntent(StrEnum):
    NONE = "none"
    PUBLIC_AUTHORITY_PAGE = "public_authority_page"


class FederationDescriptorStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class FederationDescriptor:
    repo_id: str
    display_name: str
    authority_feed_manifest_url: str
    projection_intents: tuple[FederationProjectionIntent, ...] = (FederationProjectionIntent.PUBLIC_AUTHORITY_PAGE,)
    status: FederationDescriptorStatus = FederationDescriptorStatus.ACTIVE
    owner_boundary: str = ""


def _is_url(locator: str) -> bool:
    parsed = urlsplit(locator)
    return parsed.scheme in {"http", "https", "file"}


def _expand_locator(locator: str | Path) -> str:
    return os.path.expandvars(str(locator).strip())


def _load_json_bytes(payload: bytes, *, source: str) -> dict[str, object]:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"expected_json_object:{source}")
    return data


def _descriptor_default_display_name(repo_id: str) -> str:
    words = [word for word in str(repo_id).replace("_", "-").split("-") if word]
    return " ".join(word.capitalize() for word in words) or str(repo_id)


def parse_federation_descriptor(payload: dict[str, object]) -> FederationDescriptor:
    if str(payload.get("kind", "")).strip() != FEDERATION_DESCRIPTOR_KIND:
        raise ValueError("invalid_federation_descriptor_kind")
    raw_version = payload.get("version", 0)
    try:
        version = int(raw_version)
    except (ValueError, TypeError):
        # Tolerate semver strings like "0.1.0" — extract major version
        version = int(str(raw_version).split(".")[0]) if str(raw_version).split(".")[0].isdigit() else 0
    if version < 1:
        raise ValueError(f"unsupported_federation_descriptor_version:{raw_version}")
    repo_id = str(payload.get("repo_id", "")).strip()
    manifest_url = str(payload.get("authority_feed_manifest_url", "")).strip()
    if not repo_id:
        raise ValueError("invalid_federation_descriptor_required_fields")
    intents_payload = payload.get("projection_intents", [FederationProjectionIntent.PUBLIC_AUTHORITY_PAGE.value])
    if not isinstance(intents_payload, list):
        raise TypeError("invalid_federation_descriptor_projection_intents")
    projection_intents: list[FederationProjectionIntent] = []
    for item in intents_payload:
        try:
            intent = FederationProjectionIntent(str(item))
        except ValueError:
            continue  # Skip unknown intents — federation evolves
        if intent not in projection_intents:
            projection_intents.append(intent)
    if not projection_intents:
        projection_intents = [FederationProjectionIntent.NONE]
    return FederationDescriptor(
        repo_id=repo_id,
        display_name=str(payload.get("display_name", "")).strip() or _descriptor_default_display_name(repo_id),
        authority_feed_manifest_url=_expand_locator(manifest_url),
        projection_intents=tuple(projection_intents),
        status=FederationDescriptorStatus(str(payload.get("status", FederationDescriptorStatus.ACTIVE.value))),
        owner_boundary=str(payload.get("owner_boundary", "")).strip(),
    )


def load_federation_descriptor(locator: str | Path) -> tuple[FederationDescriptor, str]:
    expanded = _expand_locator(locator)
    if _is_url(expanded):
        request = Request(expanded, headers={"User-Agent": "agent-internet-federation-descriptor/0.1"})
        with urlopen(request, timeout=30) as response:
            return parse_federation_descriptor(_load_json_bytes(response.read(), source=expanded)), expanded
    path = Path(expanded).resolve()
    return parse_federation_descriptor(_load_json_bytes(path.read_bytes(), source=str(path))), str(path)


def _normalize_seed_entries(entries: object) -> tuple[str, ...]:
    if isinstance(entries, dict):
        entries = entries.get("descriptor_urls", [])
    if not isinstance(entries, list):
        raise TypeError("invalid_federation_descriptor_seed_payload")
    values: list[str] = []
    for item in entries:
        if isinstance(item, str) and item.strip():
            values.append(_expand_locator(item))
            continue
        if isinstance(item, dict):
            value = _expand_locator(item.get("descriptor_url") or item.get("url") or "")
            if value:
                values.append(value)
                continue
        raise TypeError("invalid_federation_descriptor_seed_entry")
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return tuple(deduped)


def load_federation_descriptor_seed(locator: str | Path) -> tuple[str, ...]:
    expanded = _expand_locator(locator)
    if _is_url(expanded):
        request = Request(expanded, headers={"User-Agent": "agent-internet-federation-descriptor/0.1"})
        with urlopen(request, timeout=30) as response:
            return _normalize_seed_entries(json.loads(response.read().decode("utf-8")))
    path = Path(expanded).resolve()
    return _normalize_seed_entries(json.loads(path.read_text()))