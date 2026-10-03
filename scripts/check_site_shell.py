#!/usr/bin/env python3
"""Verify the public shell stays lightweight, navigable, and presentation-only."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web"
if not SITE.is_absolute():
    SITE = ROOT / SITE

PAGES = ("index.html", "applications.html", "conversation.html", "technical.html", "metrics.html")
MAX_HTML_BYTES = 12_000
MAX_CSS_BYTES = 24_000
MAX_JS_BYTES = 24_000
MAX_TOTAL_BYTES = 96_000


class AuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1_count = 0
        self.main_ids: list[str] = []
        self.links: list[str] = []
        self.skip_links: list[str] = []
        self.current_pages = 0
        self.images_without_alt: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        elif tag == "main":
            self.main_ids.append(data.get("id", ""))
        elif tag == "a":
            href = data.get("href", "")
            if href:
                self.links.append(href)
            classes = set(data.get("class", "").split())
            if "skip-link" in classes:
                self.skip_links.append(href)
            if data.get("aria-current") == "page":
                self.current_pages += 1
        elif tag == "img" and "alt" not in data:
            self.images_without_alt.append(data.get("src", ""))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"site-shell check failed: {message}")


def audit_page(path: Path) -> None:
    require(path.exists(), f"missing {path.relative_to(SITE)}")
    size = path.stat().st_size
    require(size <= MAX_HTML_BYTES, f"{path.name} is {size} bytes; budget is {MAX_HTML_BYTES}")

    text = path.read_text(encoding="utf-8")
    require("\\n" not in text, f"{path.name} contains a literal escaped newline sequence")
    parser = AuditParser()
    parser.feed(text)
    require(parser.h1_count == 1, f"{path.name} must have exactly one h1")
    require("main" in parser.main_ids, f"{path.name} must expose main#main")
    require("#main" in parser.skip_links, f"{path.name} must provide a skip link to #main")
    require(parser.current_pages == 1, f"{path.name} must mark exactly one aria-current page")
    require(not parser.images_without_alt, f"{path.name} has images without alt text")

    for href in parser.links:
        parsed = urlparse(href)
        if parsed.scheme or href.startswith(("#", "mailto:", "tel:")):
            continue
        local = href.split("#", 1)[0].split("?", 1)[0]
        if not local:
            continue
        target = SITE / local
        require(target.exists(), f"{path.name} links to missing local target {local}")


def main() -> None:
    require(SITE.exists(), f"shell directory does not exist: {SITE}")
    for page in PAGES:
        audit_page(SITE / page)

    css = SITE / "assets" / "site.css"
    js = SITE / "assets" / "site.js"
    require(css.exists(), "missing assets/site.css")
    require(js.exists(), "missing assets/site.js")
    require(css.stat().st_size <= MAX_CSS_BYTES, "site.css exceeds lightweight-shell budget")
    require(js.stat().st_size <= MAX_JS_BYTES, "site.js exceeds lightweight-shell budget")

    prohibited = list(SITE.rglob("*.sqlite")) + list(SITE.rglob("*.db"))
    require(not prohibited, "raw database files may not be shipped in the public shell")

    total = sum(path.stat().st_size for path in SITE.rglob("*") if path.is_file())
    require(total <= MAX_TOTAL_BYTES, f"shell is {total} bytes; budget is {MAX_TOTAL_BYTES}")
    print(f"site-shell check passed: {SITE} ({total} bytes)")


if __name__ == "__main__":
    main()
