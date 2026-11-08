"""
Pulls clean plaintext from a list of Auburn Engineering giving-site URLs
and saves each page as its own .txt file for the RAG ingestion pipeline.

Some pages (give.auburn.edu/campaigns/*) render their content client-side
with JavaScript, so a plain static fetch comes back nearly empty. For those,
this script falls back to rendering the page with a headless browser
(Playwright/Chromium) before extracting text.

Setup (run once):
    pip install trafilatura playwright
    playwright install chromium

Usage:
    python scrape_giving_pages.py

Output:
    ../scraped_pages/<slugified-url>.txt   (one file per URL)
    ../scraped_pages/_manifest.csv         (url -> filename -> char count, for a sanity check)
"""

import csv
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import trafilatura
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# 1. Add every URL you want pulled in here. One string per page.
#    Include department campaign pages, news articles, ways-to-give, etc.
# ---------------------------------------------------------------------------
URLS = [
    "https://eng.auburn.edu/giving/",
    "https://eng.auburn.edu/giving/annual-giving/",
    "https://eng.auburn.edu/giving/annual-giving/eagle-society.html",
    "https://eng.auburn.edu/giving/ways-to-give",
    "https://eng.auburn.edu/admin/development/index.html",
    "https://eng.auburn.edu/giving/giving-news.html",
    "https://give.auburn.edu/pages/home-2694",
    # department campaign pages
    "https://give.auburn.edu/campaigns/aerospace-engineering-department-2",
    "https://give.auburn.edu/campaigns/biosystems-engineering-2",
    "https://give.auburn.edu/campaigns/chemical-engineering-department-7",
    "https://give.auburn.edu/campaigns/civil-engineering-department-8",
    "https://give.auburn.edu/campaigns/computer-science-and-software-engineering-gifts",
    "https://give.auburn.edu/campaigns/electrical-and-computer-engineering-department-5",
    "https://give.auburn.edu/campaigns/industrial-and-systems-engineering",
    "https://give.auburn.edu/campaigns/materials-engineering-2",
    "https://give.auburn.edu/campaigns/mechanical-engineering-department-3",
    "https://give.auburn.edu/campaigns/wireless-engineering-program-2",
    # add more: department landing pages, individual news articles, etc.
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "scraped_pages"  # 3_Code/scraped_pages
REQUEST_DELAY_SECONDS = 1.0  # be polite to the server between requests


def slugify(url: str) -> str:
    """Turn a URL into a safe filename, e.g. https://eng.auburn.edu/giving/ways-to-give
    -> eng.auburn.edu_giving_ways-to-give.txt"""
    no_scheme = re.sub(r"^https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", no_scheme).strip("_")
    return f"{slug}.txt"


MIN_CONTENT_CHARS = 50

# Domains where trafilatura's boilerplate detector reliably drops real,
# page-specific content (short link grids / contact blurbs surrounded by a
# big sitewide nav+footer). For these we also try a manual clean of the
# rendered page text and keep whichever result is longer.
DOMAINS_NEEDING_MANUAL_CLEAN = {"eng.auburn.edu"}

# eng.auburn.edu's sitewide nav/footer, copied verbatim from a rendered page
# so it can be stripped out. Verified identical across multiple pages on
# the site as of 2026-09.
_ENG_AUBURN_COOKIE_BLOCK = """Cookie Acknowledgement

This website uses cookies to collect information to improve your browsing experience. Please review our Privacy Statement for more information.

I Understand
"""
_ENG_AUBURN_NAV_PREAMBLE = """Skip to Primary Navigation
Skip to Content
Skip to Primary Navigation
Skip to Content
Toggle site navigation
Visit
Apply
AU Access
Search
"""
_ENG_AUBURN_SITE_NAV_BLOCK = """Home
About
Academics
Students
Careers
Research
Giving
Alumni
News
Spirit Store
"""
_ENG_AUBURN_FOOTER_MARKER = "\nRender\nLink to Auburn Engineering Facebook page"


def clean_eng_auburn_page_text(text: str):
    """Strip eng.auburn.edu's sitewide nav/footer and giving-news teasers
    from a page's full rendered text, leaving just the page-specific
    content trafilatura tends to misclassify as boilerplate."""
    # Normalize trailing whitespace per line so the block constants above
    # (which had trailing spaces stripped when this file was edited) still
    # match the live page's text (some nav lines render with a trailing
    # space, e.g. "Academics ").
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    idx = text.find(_ENG_AUBURN_FOOTER_MARKER)
    if idx != -1:
        text = text[:idx]
    text = text.replace(_ENG_AUBURN_COOKIE_BLOCK, "")
    text = text.replace(_ENG_AUBURN_NAV_PREAMBLE, "")
    text = text.replace(_ENG_AUBURN_SITE_NAV_BLOCK, "")
    text = re.sub(r"GIVING NEWS\n.*?More News\n?", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def extract_text(html: str):
    text = trafilatura.extract(
        html,
        include_links=False,
        include_images=False,
        include_tables=True,
    )
    if not text or len(text.strip()) < MIN_CONTENT_CHARS:
        return None
    return text


def render_with_browser(browser, url: str):
    """Load a URL in headless Chromium, scroll to the bottom to trigger any
    lazy-loaded widgets, and return the fully rendered HTML and visible
    body text (for pages that build their content with JavaScript)."""
    page = browser.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        return page.content(), page.inner_text("body")
    finally:
        page.close()


def scrape_url(url: str, browser):
    """Fetch a URL and extract clean article text. Tries a plain static
    fetch first; for domains where a headless render can recover more
    content (JS-rendered pages, or ones where trafilatura drops real
    content as boilerplate) it also renders with a headless browser and
    keeps whichever result is longest. Returns (text, method) or
    (None, None) on total failure."""
    domain = urlparse(url).netloc
    candidates = {}

    downloaded = trafilatura.fetch_url(url)
    if downloaded is not None:
        static_text = extract_text(downloaded)
        if static_text is not None:
            candidates["static"] = static_text

    needs_browser = domain in DOMAINS_NEEDING_MANUAL_CLEAN or not candidates
    if needs_browser:
        if not candidates:
            print(f"  [INFO] Static fetch thin/failed, trying headless browser: {url}")
        try:
            rendered_html, rendered_text = render_with_browser(browser, url)
        except Exception as exc:
            print(f"  [WARN] Headless browser render failed: {url} ({exc})")
            rendered_html, rendered_text = None, None

        if rendered_html is not None:
            browser_text = extract_text(rendered_html)
            if browser_text is not None:
                candidates["browser"] = browser_text

            if domain in DOMAINS_NEEDING_MANUAL_CLEAN:
                cleaned = clean_eng_auburn_page_text(rendered_text)
                if cleaned is not None and len(cleaned) >= MIN_CONTENT_CHARS:
                    candidates["browser+cleaned"] = cleaned

    if not candidates:
        print(f"  [FAILED] No usable content from any method: {url}")
        return None, None

    method, text = max(candidates.items(), key=lambda kv: len(kv[1]))
    return text, method


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    manifest_rows = []

    print(f"Scraping {len(URLS)} URLs...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for i, url in enumerate(URLS, 1):
                print(f"[{i}/{len(URLS)}] {url}")
                text, method = scrape_url(url, browser)

                if text is None:
                    manifest_rows.append([url, "", 0, "FAILED"])
                    time.sleep(REQUEST_DELAY_SECONDS)
                    continue

                filename = slugify(url)
                out_path = OUTPUT_DIR / filename
                out_path.write_text(text, encoding="utf-8")

                char_count = len(text)
                print(f"  -> saved {filename} ({char_count} chars, via {method})")
                manifest_rows.append([url, filename, char_count, f"OK ({method})"])

                time.sleep(REQUEST_DELAY_SECONDS)
        finally:
            browser.close()

    # Write a manifest so you can quickly spot pages that failed or came back thin
    manifest_path = OUTPUT_DIR / "_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "filename", "char_count", "status"])
        writer.writerows(manifest_rows)

    failed = [r for r in manifest_rows if r[3] == "FAILED"]
    print(f"\nDone. {len(manifest_rows) - len(failed)} succeeded, {len(failed)} failed/thin.")
    print(f"Check {manifest_path} for details.")
    if failed:
        print("Pages that failed even with headless rendering -- check these manually:")
        for r in failed:
            print(f"  - {r[0]}")


if __name__ == "__main__":
    main()
