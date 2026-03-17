"""Content-Type Intelligence for the Agent Web Browser.

Parsers for non-HTML content types that agents encounter when browsing
GitHub raw files, APIs, and the open web: Markdown, TOML, CSV, XML.

All parsers are stdlib-only and return clean, agent-readable text.
"""

from __future__ import annotations

import csv
import io
import logging
import re

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.CONTENT")


# ---------------------------------------------------------------------------
# Content-type detection
# ---------------------------------------------------------------------------

# Map file extensions → content type
_EXT_TO_TYPE: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".toml": "application/toml",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".xml": "application/xml",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".json": "application/json",
    ".txt": "text/plain",
    ".rst": "text/x-rst",
    ".ini": "text/x-ini",
    ".cfg": "text/x-ini",
}

# Content-Type header patterns
_CT_PATTERNS: dict[str, str] = {
    "text/markdown": "markdown",
    "text/csv": "csv",
    "text/tab-separated-values": "csv",
    "application/toml": "toml",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/yaml": "yaml",
    "application/x-yaml": "yaml",
    "text/x-rst": "rst",
}


def detect_content_type(url: str, content_type_header: str = "") -> str:
    """Detect the logical content type from URL extension or Content-Type header.

    Returns one of: 'markdown', 'toml', 'csv', 'xml', 'yaml', 'json',
    'html', 'rst', 'ini', 'plain', or 'unknown'.
    """
    # Check Content-Type header first
    ct_lower = content_type_header.lower().split(";")[0].strip()
    for pattern, kind in _CT_PATTERNS.items():
        if pattern in ct_lower:
            return kind

    if "application/json" in ct_lower:
        return "json"
    if "text/html" in ct_lower:
        return "html"
    if "text/plain" in ct_lower:
        # text/plain could be anything — check URL extension
        pass

    # Check URL extension
    url_path = url.split("?")[0].split("#")[0]
    for ext, ct in _EXT_TO_TYPE.items():
        if url_path.endswith(ext):
            for pattern, kind in _CT_PATTERNS.items():
                if pattern == ct:
                    return kind
            if ct == "application/json":
                return "json"
            if ct == "text/plain":
                return "plain"
            if ct == "text/x-ini":
                return "ini"
    return "unknown"


# ---------------------------------------------------------------------------
# Markdown parser (lightweight — no external deps)
# ---------------------------------------------------------------------------

def parse_markdown(content: str) -> dict:
    """Parse Markdown into structured components.

    Returns: {title, sections, links, summary}
    """
    lines = content.strip().split("\n")
    title = ""
    sections: list[dict] = []
    current_section = ""
    current_lines: list[str] = []
    links: list[dict] = []

    # Extract links from markdown
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    for line in lines:
        stripped = line.strip()

        # H1 title
        if stripped.startswith("# ") and not stripped.startswith("## ") and not title:
            title = stripped[2:].strip()
            continue

        # H2/H3 section headers
        if stripped.startswith("## ") or stripped.startswith("### "):
            if current_section or current_lines:
                sections.append({
                    "heading": current_section,
                    "content": "\n".join(current_lines).strip(),
                })
            level = 3 if stripped.startswith("### ") else 2
            current_section = stripped[level + 1:].strip()
            current_lines = []
            continue

        current_lines.append(line)

        # Extract links
        for match in link_re.finditer(line):
            links.append({"text": match.group(1), "url": match.group(2)})

    # Final section
    if current_section or current_lines:
        sections.append({
            "heading": current_section,
            "content": "\n".join(current_lines).strip(),
        })

    # Summary: first non-empty paragraph
    summary = ""
    for section in sections:
        text = section["content"].strip()
        if text:
            summary = text.split("\n\n")[0][:300]
            break

    return {
        "title": title,
        "sections": sections,
        "links": links,
        "summary": summary,
    }


def render_markdown_for_agent(content: str) -> str:
    """Render Markdown as clean agent-readable text.

    Strips excessive formatting while preserving structure.
    """
    data = parse_markdown(content)
    parts = []
    if data["title"]:
        parts.append(f"# {data['title']}")
        parts.append("")
    for section in data["sections"]:
        if section["heading"]:
            parts.append(f"## {section['heading']}")
        if section["content"]:
            parts.append(section["content"])
        parts.append("")
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# TOML parser (stdlib tomllib, Python 3.11+)
# ---------------------------------------------------------------------------

def parse_toml(content: str) -> str:
    """Parse TOML and return agent-readable formatted output."""
    try:
        import tomllib
    except ImportError:
        # Python < 3.11 fallback: return as-is with header
        return f"[TOML content — requires Python 3.11+ for parsing]\n\n{content}"

    try:
        data = tomllib.loads(content)
        return _format_nested(data)
    except Exception as exc:
        logger.debug("TOML parse error: %s", exc)
        return f"[TOML parse error: {exc}]\n\n{content}"


def _format_nested(data: dict | list, indent: int = 0) -> str:
    """Format nested dict/list as readable indented text."""
    prefix = "  " * indent
    parts: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                parts.append(f"{prefix}{key}:")
                parts.append(_format_nested(value, indent + 1))
            else:
                parts.append(f"{prefix}{key}: {value}")
    elif isinstance(data, list):
        for i, item in enumerate(data[:50]):
            if isinstance(item, (dict, list)):
                parts.append(f"{prefix}- [{i}]:")
                parts.append(_format_nested(item, indent + 1))
            else:
                parts.append(f"{prefix}- {item}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def parse_csv(content: str, *, delimiter: str = ",", max_rows: int = 100) -> str:
    """Parse CSV/TSV and return agent-readable table format."""
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)

    if not rows:
        return "(empty CSV)"

    # Detect header row
    header = rows[0]
    data_rows = rows[1:]

    parts = [" | ".join(header), "-" * (len(" | ".join(header)))]
    for row in data_rows:
        # Pad to header length
        padded = row + [""] * (len(header) - len(row))
        parts.append(" | ".join(padded[:len(header)]))

    footer = f"\n({len(data_rows)} rows"
    if len(rows) >= max_rows:
        footer += f", truncated at {max_rows}"
    footer += ")"
    parts.append(footer)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# XML parser (stdlib xml.etree)
# ---------------------------------------------------------------------------

def parse_xml(content: str, *, max_depth: int = 5) -> str:
    """Parse XML and return agent-readable tree format."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.debug("XML parse error: %s", exc)
        return f"[XML parse error: {exc}]\n\n{content[:2000]}"

    parts: list[str] = []
    _walk_xml(root, parts, depth=0, max_depth=max_depth)
    return "\n".join(parts)


def _walk_xml(
    element: object, parts: list[str], depth: int, max_depth: int,
) -> None:
    """Recursively walk XML tree and format as indented text."""
    import xml.etree.ElementTree as ET

    if depth > max_depth:
        return

    prefix = "  " * depth
    # Strip namespace from tag
    tag = element.tag  # type: ignore[union-attr]
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    attrs = element.attrib  # type: ignore[union-attr]
    attr_str = " ".join(f'{k}="{v}"' for k, v in list(attrs.items())[:5]) if attrs else ""
    text = (element.text or "").strip()  # type: ignore[union-attr]

    if text and not list(element):  # type: ignore[arg-type]
        line = f"{prefix}<{tag}"
        if attr_str:
            line += f" {attr_str}"
        line += f"> {text[:200]}"
        parts.append(line)
    else:
        line = f"{prefix}<{tag}"
        if attr_str:
            line += f" {attr_str}"
        line += ">"
        parts.append(line)
        if text:
            parts.append(f"{prefix}  {text[:200]}")
        for child in list(element)[:30]:  # type: ignore[arg-type]
            _walk_xml(child, parts, depth + 1, max_depth)


# ---------------------------------------------------------------------------
# YAML parser (best-effort, no external deps)
# ---------------------------------------------------------------------------

def parse_yaml_basic(content: str) -> str:
    """Best-effort YAML rendering without PyYAML.

    YAML is not in stdlib so we do a lightweight parse for simple cases
    and return the raw content with structure annotations for complex ones.
    """
    lines = content.strip().split("\n")
    if not lines:
        return "(empty YAML)"

    # Check if it's simple enough to understand
    has_complex = any(
        line.strip().startswith(("{", "[", "- {", "- ["))
        for line in lines[:20]
    )
    if has_complex:
        return f"[YAML — {len(lines)} lines]\n\n{content}"

    # Simple YAML: key: value pairs and lists
    return content


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def render_content(content: str, content_type: str, url: str = "") -> str:
    """Render content of any supported type as agent-readable text.

    Uses content_type as detected by detect_content_type().
    """
    if content_type == "markdown":
        return render_markdown_for_agent(content)
    if content_type == "toml":
        return parse_toml(content)
    if content_type == "csv":
        delimiter = "\t" if ".tsv" in url else ","
        return parse_csv(content, delimiter=delimiter)
    if content_type == "xml":
        return parse_xml(content)
    if content_type == "yaml":
        return parse_yaml_basic(content)
    # Plain text, RST, INI — return as-is (already readable)
    return content
