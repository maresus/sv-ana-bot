#!/usr/bin/env python3
"""
Scraper za sv-ana.si → knowledge.jsonl
Enak princip kot KOVACNIK V2 AI scraper.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sv-ana.si"
USER_AGENT = "SvAnaAIBot/1.0 (+https://sv-ana.si)"
OUTPUT = Path(__file__).parent.parent / "knowledge.jsonl"

SKIP_PATTERNS = [
    "/administrator/", "/templates/", "/modules/", "/plugins/",
    "/cache/", "/tmp/", "/media/", "/components/", "/includes/",
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
    ".ico", ".woff", ".svg", ".xml", "/feed", "format=feed",
    "tmpl=component", "print=1", "lang=",
]

# Prioritete glede na URL
def classify(url: str, title: str, content: str) -> tuple[str, str, str, int]:
    u = url.lower()
    t = title.lower()

    if any(x in u for x in ["kontakt", "contact"]):
        return ("contact", "contact", "kontakt", 100)
    if any(x in u for x in ["obcinska-uprava", "uprava"]):
        return ("administration", "administration", "uprava", 95)
    if any(x in u for x in ["vloge", "obrazci"]):
        return ("forms", "forms", "vloge_obrazci", 90)
    if any(x in u for x in ["zupan", "župan"]):
        return ("mayor", "person", "zupan", 90)
    if any(x in u for x in ["obcinski-svet", "svetniki"]):
        return ("council", "council", "obcinski_svet", 85)
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


def extract(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form", "iframe", "nav", "footer"]):
        tag.decompose()

    # Title
    title_tag = soup.find("h1") or soup.find("title")
    title = normalize(title_tag.get_text(" ")) if title_tag else ""

    # Main content
    root = (
        soup.find("div", class_=re.compile(r"article|content|main|body", re.I))
        or soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    lines = []
    seen = set()
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th"]):
        line = normalize(el.get_text(" "))
        if len(line) < 15:
            continue
        if line.lower().startswith(("cookie", "piškot", "copyright", "©", "powered by")):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    return title, "\n".join(lines)


def should_skip(url: str) -> bool:
    return any(p in url.lower() for p in SKIP_PATTERNS)


def get_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base, href)
        parsed = urlparse(full)
        # samo sv-ana.si domene
        if parsed.netloc not in ("www.sv-ana.si", "sv-ana.si"):
            continue
        # brez fragmentov in query
        clean = parsed._replace(fragment="", query="").geturl()
        if should_skip(clean):
            continue
        links.append(clean)
    return links


def scrape() -> None:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    visited: set[str] = set()
    queue: list[str] = [BASE_URL + "/", BASE_URL + "/obcina", BASE_URL + "/o-sveti-ani",
                        BASE_URL + "/o-sveti-ani/drustva", BASE_URL + "/aktualno"]
    records: list[dict] = []
    fp_seen: set[str] = set()
    stats = Counter()

    print(f"Scraping {BASE_URL} ...")

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            html = r.text

            title, content = extract(html)

            if len(content) >= 80:
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
                    print(f"  ✓ [{stats['kept']}] {topic}/{priority} — {url}")
                else:
                    stats["deduped"] += 1
            else:
                stats["skip_short"] += 1

            # Dodaj nove linke v queue
            new_links = get_links(html, url)
            for link in new_links:
                if link not in visited and link not in queue:
                    queue.append(link)

        except Exception as e:
            stats["errors"] += 1
            print(f"  ✗ ERR {url}: {e}")

        time.sleep(0.3)

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


if __name__ == "__main__":
    scrape()
