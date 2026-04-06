#!/usr/bin/env python3
"""
Playwright scraper za sv-ana.si → knowledge.jsonl
Rešuje problem Joomla JS-rendered vsebine (svetniki, župani, itd.)
Zaženite LOKALNO, ne na Railway.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Page
from bs4 import BeautifulSoup

BASE_URL = "https://www.sv-ana.si"
OUTPUT = Path(__file__).parent / "knowledge.jsonl"

SKIP_PATTERNS = [
    "/administrator/", "/templates/", "/modules/", "/plugins/",
    "/cache/", "/tmp/", "/media/", "/components/", "/includes/",
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
    ".ico", ".woff", ".svg", ".xml", "/feed", "format=feed",
    "tmpl=component", "print=1", "lang=",
    # Preskoči stare seje OS (preveč strani, malo koristi)
    "/pretekli-os/",
    # Preskoči posamezne seje (dokumenti)
    "/seja-os/", "/seja/",
]

MAX_CONTENT = 3000
MIN_CONTENT = 80

PRIORITY_SEED_URLS = [
    BASE_URL + "/",
    BASE_URL + "/obcina",
    BASE_URL + "/o-sveti-ani",
    BASE_URL + "/o-sveti-ani/drustva",
    BASE_URL + "/o-sveti-ani/obcinski-svet",
    BASE_URL + "/o-sveti-ani/zupan",
    BASE_URL + "/aktualno",
    BASE_URL + "/o-sveti-ani/obcinska-uprava",
    BASE_URL + "/o-sveti-ani/vloge-in-obrazci",
    BASE_URL + "/o-sveti-ani/kraji",
    BASE_URL + "/o-sveti-ani/nagrade-in-priznanja",
    BASE_URL + "/o-sveti-ani/bivsi-zupani",
]


def classify(url: str, title: str, content: str) -> tuple[str, str, str, int]:
    u = url.lower()

    if any(x in u for x in ["kontakt", "contact"]):
        return ("contact", "contact", "kontakt", 100)
    if any(x in u for x in ["obcinska-uprava", "uprava"]):
        return ("administration", "administration", "uprava", 95)
    if any(x in u for x in ["vloge", "obrazci"]):
        return ("forms", "forms", "vloge_obrazci", 90)
    if any(x in u for x in ["zupan", "župan"]):
        return ("mayor", "person", "zupan", 90)
    if any(x in u for x in ["obcinski-svet", "svetniki"]):
        return ("council", "council", "obcinski_svet", 90)
    if any(x in u for x in ["bivsi-zupani", "bivši-župani"]):
        return ("former_mayors", "person", "bivsi_zupani", 88)
    if any(x in u for x in ["nagrade", "priznanja"]):
        return ("awards", "awards", "nagrade_priznanja", 85)
    if any(x in u for x in ["drustvo", "društvo"]):
        name = u.split("/drustvo")[-1].strip("/").replace("-", "_")[:30]
        return ("society", "society", name or "drustvo", 80)
    if any(x in u for x in ["razpis", "javni-razpis"]):
        return ("tender", "tender", "razpisi", 85)
    if any(x in u for x in ["aktualno", "novosti", "novice"]):
        return ("news", "news", "aktualno", 70)
    if any(x in u for x in ["kraji", "naselja"]):
        name = u.split("/kraji")[-1].strip("/").replace("-", "_")[:30]
        return ("settlement", "settlement", name or "kraj", 75)
    if any(x in u for x in ["izobrazevanje", "šola", "sola"]):
        return ("education", "education", "izobrazevanje", 75)
    if any(x in u for x in ["zdravstvo", "zdravje"]):
        return ("health", "health", "zdravstvo", 80)
    if any(x in u for x in ["turizem", "turisticno"]):
        return ("tourism", "tourism", "turizem", 75)
    if any(x in u for x in ["sport", "dvorana"]):
        return ("sport", "sport", "sport", 75)
    if any(x in u for x in ["o-sveti-ani", "o_sveti_ani"]):
        return ("about", "general", "o_obcini", 70)
    if any(x in u for x in ["obcina"]):
        return ("municipality", "general", "obcina", 70)
    if any(x in u for x in ["prostorski", "nacrt"]):
        return ("spatial", "general", "prostorski_nacrt", 65)
    return ("general", "general", "splosno", 60)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_from_html(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form", "iframe", "nav", "footer"]):
        tag.decompose()

    title_tag = soup.find("h1") or soup.find("title")
    title = normalize(title_tag.get_text(" ")) if title_tag else ""

    root = (
        soup.find("div", class_=re.compile(r"article|content|main|body|com-content", re.I))
        or soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    lines = []
    seen = set()
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "span"]):
        line = normalize(el.get_text(" "))
        if len(line) < 15:
            continue
        if line.lower().startswith(("cookie", "piškot", "copyright", "©", "powered by", "home", "domov")):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    content = "\n".join(lines)
    return title, content[:MAX_CONTENT]


def should_skip(url: str) -> bool:
    return any(p in url.lower() for p in SKIP_PATTERNS)


def get_links_from_html(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base, href)
        parsed = urlparse(full)
        if parsed.netloc not in ("www.sv-ana.si", "sv-ana.si"):
            continue
        clean = parsed._replace(fragment="", query="").geturl()
        if should_skip(clean):
            continue
        links.append(clean)
    return links


async def scrape_page(page: Page, url: str) -> tuple[str, str, str]:
    """Naloži stran z Playwrightom in počaka na JS rendering."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        # Počakaj da se dinamična vsebina naloži
        await page.wait_for_timeout(800)
        html = await page.content()
        return html, "", ""
    except Exception as e:
        return "", "", str(e)


async def scrape() -> None:
    records: list[dict] = []
    fp_seen: set[str] = set()
    visited: set[str] = set()
    queue: list[str] = list(PRIORITY_SEED_URLS)
    stats = Counter()

    print(f"[Playwright] Scraping {BASE_URL} ...")
    print(f"[Playwright] Seed URLs: {len(queue)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            locale="sl-SI",
        )
        page = await context.new_page()

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            html, _, err = await scrape_page(page, url)
            if not html:
                print(f"  ✗ ERR {url}: {err}")
                stats["errors"] += 1
                continue

            title, content = extract_from_html(html)

            if len(content) >= MIN_CONTENT:
                topic, entity_type, entity_name, priority = classify(url, title, content)
                rec = {
                    "url": url,
                    "title": title or urlparse(url).path.strip("/") or url,
                    "content": content,
                    "lang": "sl",
                    "topic": topic,
                    "entity_type": entity_type,
                    "entity_name": entity_name,
                    "priority": priority,
                    "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                }
                fp = hashlib.sha1(f"{rec['url']}|{rec['content'][:200]}".encode()).hexdigest()
                if fp not in fp_seen:
                    fp_seen.add(fp)
                    records.append(rec)
                    stats["kept"] += 1
                    print(f"  ✓ [{stats['kept']}] {topic}/{priority} — {url[:80]}")
                    print(f"    title: {title[:60]}")
                else:
                    stats["deduped"] += 1
            else:
                stats["skip_short"] += 1
                print(f"  — skip_short ({len(content)}ch) — {url[:80]}")

            # Poberi linke za nadaljnje scrapanje
            new_links = get_links_from_html(html, url)
            for link in new_links:
                if link not in visited and link not in queue:
                    queue.append(link)

            # Kratek premor
            await page.wait_for_timeout(300)

        await browser.close()

    # Sortiraj po prioriteti
    records.sort(key=lambda r: -r["priority"])

    OUTPUT.parent.mkdir(exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n{'='*50}")
    print(f"Output: {OUTPUT}")
    print(f"Skupaj zapisov: {len(records)}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"\nSedaj zaženite:")
    print(f"  gzip -k -f knowledge.jsonl")
    print(f"  cd '{OUTPUT.parent}' && git add knowledge.jsonl.gz && git commit -m 'feat: update knowledge base with JS-rendered content' && git push")


if __name__ == "__main__":
    asyncio.run(scrape())
