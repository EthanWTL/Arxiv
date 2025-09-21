#!/usr/bin/env python3
"""
fetch_papers.py
Fetch ALL arXiv papers for selected categories (today only) and save JSON daily
into paper_json/YYYY-MM-DD.json. Keeps only last N days.
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import json
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}

# Categories to fetch
CATEGORIES = ["cs.AI", "cs.CV", "cs.LG", "stat.ML"]

OUTPUT_DIR = Path("paper_json")
OUTPUT_DIR.mkdir(exist_ok=True)
KEEP_DAYS = 5


def parse_entry(e):
    # Extract first PDF link safely
    arxiv_id = e.find("atom:id", NS).text
    pdf_link = arxiv_id.replace("abs", "pdf") + ".pdf"

    # Some entries have multiple <category>; collect all
    cats = [c.attrib.get("term") for c in e.findall("atom:category", NS)]

    # Authors (optional, useful for on-page filtering later if you add it)
    authors = [a.find("atom:name", NS).text for a in e.findall("atom:author", NS)]

    return {
        "id": arxiv_id,
        "title": e.find("atom:title", NS).text.strip(),
        "summary": e.find("atom:summary", NS).text.strip(),
        "published": e.find("atom:published", NS).text,
        "link": pdf_link,
        "category": cats,
        "authors": authors,
    }


def fetch_recent(category="cs.AI", max_results=300):
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    headers = {"User-Agent": "daily-arxiv-fetch/0.2 (your_email@example.com)"}
    r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    return [parse_entry(e) for e in root.findall("atom:entry", NS)]


def filter_by_date(entries, target_date):
    results = []
    for e in entries:
        pub = datetime.fromisoformat(e["published"].replace("Z", "+00:00")).date()
        if pub == target_date:
            results.append(e)
    return results


if __name__ == "__main__":
    today = datetime.now(timezone.utc).date()
    all_today = []
    for cat in CATEGORIES:
        recent = fetch_recent(cat, max_results=300)
        today_entries = filter_by_date(recent, today)
        all_today.extend(today_entries)

    # Deduplicate by arXiv id
    seen = set()
    deduped = []
    for e in all_today:
        if e["id"] not in seen:
            deduped.append(e)
            seen.add(e["id"])

    out_file = OUTPUT_DIR / f"{today}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(deduped)} papers to {out_file}")

    # keep only last N days
    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    if len(json_files) > KEEP_DAYS:
        for old in json_files[:-KEEP_DAYS]:
            old.unlink()
            print(f"Deleted old file {old}")
