"""Tests for agent_web_browser_content — Content-Type Intelligence."""

from __future__ import annotations

from agent_internet.agent_web_browser_content import (
    detect_content_type,
    parse_csv,
    parse_markdown,
    parse_toml,
    parse_xml,
    parse_yaml_basic,
    render_content,
    render_markdown_for_agent,
)


# ---------------------------------------------------------------------------
# Content-type detection
# ---------------------------------------------------------------------------

def test_detect_markdown_from_extension():
    assert detect_content_type("README.md") == "markdown"
    assert detect_content_type("docs/guide.markdown") == "markdown"


def test_detect_toml_from_extension():
    assert detect_content_type("pyproject.toml") == "toml"


def test_detect_csv_from_extension():
    assert detect_content_type("data.csv") == "csv"
    assert detect_content_type("data.tsv") == "csv"


def test_detect_xml_from_extension():
    assert detect_content_type("feed.xml") == "xml"


def test_detect_yaml_from_extension():
    assert detect_content_type("config.yaml") == "yaml"
    assert detect_content_type("config.yml") == "yaml"


def test_detect_from_content_type_header():
    assert detect_content_type("", "text/markdown") == "markdown"
    assert detect_content_type("", "text/csv") == "csv"
    assert detect_content_type("", "application/xml") == "xml"
    assert detect_content_type("", "application/json") == "json"


def test_detect_unknown():
    assert detect_content_type("mystery.bin") == "unknown"
    assert detect_content_type("", "application/octet-stream") == "unknown"


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

_SAMPLE_MD = """\
# My Project

This is a test project for agents.

## Installation

Run `pip install myproject`.

## Links

- [Documentation](https://docs.example.com)
- [GitHub](https://github.com/example/project)
"""


def test_parse_markdown_title():
    data = parse_markdown(_SAMPLE_MD)
    assert data["title"] == "My Project"


def test_parse_markdown_sections():
    data = parse_markdown(_SAMPLE_MD)
    headings = [s["heading"] for s in data["sections"]]
    assert "Installation" in headings
    assert "Links" in headings


def test_parse_markdown_links():
    data = parse_markdown(_SAMPLE_MD)
    urls = [l["url"] for l in data["links"]]
    assert "https://docs.example.com" in urls


def test_parse_markdown_summary():
    data = parse_markdown(_SAMPLE_MD)
    assert "test project" in data["summary"]


def test_render_markdown_preserves_structure():
    rendered = render_markdown_for_agent(_SAMPLE_MD)
    assert "# My Project" in rendered
    assert "## Installation" in rendered


# ---------------------------------------------------------------------------
# TOML parser
# ---------------------------------------------------------------------------

def test_parse_toml_basic():
    toml = '[project]\nname = "foo"\nversion = "1.0"\n'
    result = parse_toml(toml)
    assert "name" in result
    assert "foo" in result


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def test_parse_csv_basic():
    csv_content = "name,age,city\nAlice,30,Berlin\nBob,25,Munich\n"
    result = parse_csv(csv_content)
    assert "name" in result
    assert "Alice" in result
    assert "2 rows" in result


def test_parse_csv_empty():
    assert "(empty CSV)" in parse_csv("")


def test_parse_csv_truncation():
    rows = "id,val\n" + "\n".join(f"{i},{i*2}" for i in range(200))
    result = parse_csv(rows, max_rows=50)
    assert "truncated at 50" in result


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

def test_parse_xml_basic():
    xml_content = '<root><item id="1">Hello</item><item id="2">World</item></root>'
    result = parse_xml(xml_content)
    assert "root" in result
    assert "item" in result
    assert "Hello" in result


def test_parse_xml_invalid():
    result = parse_xml("not xml at all <>>")
    assert "XML parse error" in result


# ---------------------------------------------------------------------------
# YAML parser
# ---------------------------------------------------------------------------

def test_parse_yaml_simple():
    yaml_content = "name: foo\nversion: 1.0\n"
    result = parse_yaml_basic(yaml_content)
    assert "name: foo" in result


def test_parse_yaml_complex():
    yaml_content = '- {key: val, key2: val2}\n- [1, 2, 3]\n'
    result = parse_yaml_basic(yaml_content)
    assert "YAML" in result  # Falls back to raw with header


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def test_render_content_markdown():
    result = render_content("# Title\nParagraph.", "markdown")
    assert "# Title" in result


def test_render_content_csv():
    result = render_content("a,b\n1,2\n", "csv")
    assert "a" in result


def test_render_content_unknown_passthrough():
    result = render_content("raw text", "plain")
    assert result == "raw text"
