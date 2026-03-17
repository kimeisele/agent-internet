"""HTML parser for the Agent Web Browser.

Extracts text, links, forms, and metadata from raw HTML using stdlib only.
"""

from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .agent_web_browser import FormField, PageForm, PageLink, PageMeta

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.PARSER")

_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "header", "footer", "nav", "main",
    "aside", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd",
    "blockquote", "pre", "table", "tr", "br", "hr",
})

_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})


class _PageParser(HTMLParser):
    """Stateful HTML parser that extracts text, links, forms, and metadata."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.text_parts: list[str] = []
        self.links: list[PageLink] = []
        self.forms: list[PageForm] = []
        self.meta = PageMeta()

        # Internal parser state
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._current_link_href = ""
        self._current_link_rel = ""
        self._link_text_parts: list[str] = []
        self._in_link = False
        self._current_form_action = ""
        self._current_form_method = "GET"
        self._current_form_id = ""
        self._current_form_fields: list[FormField] = []
        self._in_form = False
        self._meta_extra: dict[str, str] = {}
        self._meta_description = ""
        self._meta_keywords: tuple[str, ...] = ()
        self._meta_author = ""
        self._meta_robots = ""
        self._meta_og_title = ""
        self._meta_og_description = ""
        self._meta_og_image = ""
        self._meta_og_url = ""
        self._meta_canonical = ""
        self._meta_charset = "utf-8"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower in _SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower in _BLOCK_TAGS:
            self.text_parts.append("\n")

        if tag_lower == "title":
            self._in_title = True
            self._title_parts = []

        elif tag_lower == "a":
            href = attr_dict.get("href", "")
            if href:
                self._in_link = True
                self._current_link_href = urljoin(self.base_url, href)
                self._current_link_rel = attr_dict.get("rel", "")
                self._link_text_parts = []

        elif tag_lower == "form":
            self._in_form = True
            action = attr_dict.get("action", "")
            self._current_form_action = urljoin(self.base_url, action) if action else self.base_url
            self._current_form_method = attr_dict.get("method", "GET").upper()
            self._current_form_id = attr_dict.get("id", "")
            self._current_form_fields = []

        elif tag_lower == "input" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type=attr_dict.get("type", "text"),
                value=attr_dict.get("value", ""),
                required="required" in attr_dict,
            ))

        elif tag_lower == "textarea" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type="textarea",
                required="required" in attr_dict,
            ))

        elif tag_lower == "select" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type="select",
            ))

        elif tag_lower == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            content = attr_dict.get("content", "")
            http_equiv = attr_dict.get("http-equiv", "").lower()
            charset = attr_dict.get("charset", "")

            if charset:
                self._meta_charset = charset
            elif http_equiv == "content-type" and "charset=" in content.lower():
                parts = content.lower().split("charset=")
                if len(parts) > 1:
                    self._meta_charset = parts[1].strip().rstrip(";")

            if name == "description":
                self._meta_description = content
            elif name == "keywords":
                self._meta_keywords = tuple(k.strip() for k in content.split(",") if k.strip())
            elif name == "author":
                self._meta_author = content
            elif name == "robots":
                self._meta_robots = content
            elif prop == "og:title":
                self._meta_og_title = content
            elif prop == "og:description":
                self._meta_og_description = content
            elif prop == "og:image":
                self._meta_og_image = content
            elif prop == "og:url":
                self._meta_og_url = content
            elif name or prop:
                key = name or prop
                self._meta_extra[key] = content

        elif tag_lower == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if rel == "canonical" and href:
                self._meta_canonical = urljoin(self.base_url, href)

        elif tag_lower == "img":
            alt = attr_dict.get("alt", "")
            if alt:
                self.text_parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()

        elif tag_lower == "a" and self._in_link:
            self._in_link = False
            link_text = " ".join(self._link_text_parts).strip()
            if self._current_link_href:
                self.links.append(PageLink(
                    href=self._current_link_href,
                    text=link_text,
                    rel=self._current_link_rel,
                    index=len(self.links),
                ))

        elif tag_lower == "form" and self._in_form:
            self._in_form = False
            self.forms.append(PageForm(
                action=self._current_form_action,
                method=self._current_form_method,
                fields=tuple(self._current_form_fields),
                form_id=self._current_form_id,
                index=len(self.forms),
            ))

        if tag_lower in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_link:
            self._link_text_parts.append(data)
        self.text_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        char = html.unescape(f"&{name};")
        self.handle_data(char)

    def handle_charref(self, name: str) -> None:
        char = html.unescape(f"&#{name};")
        self.handle_data(char)

    def build_meta(self) -> PageMeta:
        return PageMeta(
            charset=self._meta_charset,
            description=self._meta_description,
            keywords=self._meta_keywords,
            author=self._meta_author,
            robots=self._meta_robots,
            og_title=self._meta_og_title,
            og_description=self._meta_og_description,
            og_image=self._meta_og_image,
            og_url=self._meta_og_url,
            canonical_url=self._meta_canonical,
            extra=dict(self._meta_extra),
        )


def _clean_text(raw: str) -> str:
    """Collapse whitespace, preserve paragraph breaks."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cleaned = [" ".join(line.split()) for line in lines]
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def parse_html(
    raw_html: str, base_url: str,
) -> tuple[str, str, tuple[PageLink, ...], tuple[PageForm, ...], PageMeta]:
    """Parse raw HTML into structured components.

    Returns (title, content_text, links, forms, meta).
    """
    parser = _PageParser(base_url)
    try:
        parser.feed(raw_html)
    except Exception as exc:
        logger.debug("HTML parse warning for %s: %s", base_url, exc)
    content_text = _clean_text("".join(parser.text_parts))
    return (
        parser.title,
        content_text,
        tuple(parser.links),
        tuple(parser.forms),
        parser.build_meta(),
    )
