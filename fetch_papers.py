#!/usr/bin/env python3
"""
fetch_papers.py
Fetch arXiv papers for AI-related categories and save JSON daily
into paper_json/YYYY-MM-DD.json. Keeps only last N days.
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import json
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}

CATEGORIES = ["cs.AI", "cs.CV", "stat.ML", "cs.LG"]
KEYWORDS = ["multimodal", "reasoning", "llm", "large language model"]

OUTPUT_DIR = Path("paper_json")
OUTPUT_DIR.mkdir(exist_ok=True)
KEEP_DAYS = 5


def parse_entry(e):
    return {
        "id": e.find("atom:id", NS).text,
        "title": e.find("atom:title", NS).text.strip(),
        "summary": e.find("atom:summary", NS).text.strip(),
        "published": e.find("atom:published", NS).text,
        "link": e.find("atom:id", NS).text.replace("abs", "pdf") + ".pdf",
        "category": [c.attrib.get("term") for c in e.findall("atom:category", NS)],
    }


def fetch_recent(category="cs.AI", max_results=200):
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    headers = {"User-Agent": "daily-arxiv-fetch/0.1 (your_email@example.com)"}
    r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    return [parse_entry(e) for e in root.findall("atom:entry", NS)]


def filter_by_date(entries, target_date):
    results = []
    for e in entries:
        pub = datetime.fromisoformat(
            e["published"].replace("Z", "+00:00")
        ).date()
        if pub == target_date:
            results.append(e)
    return results


def keyword_filter(entries, keywords):
    if not keywords:
        return entries
    out = []
    for e in entries:
        text = (e["title"] + " " + e["summary"]).lower()
        if any(kw.lower() in text for kw in keywords):
            out.append(e)
    return out


if __name__ == "__main__":
    today = datetime.now(timezone.utc).date()
    all_today = []
    for cat in CATEGORIES:
        recent = fetch_recent(cat, max_results=300)
        today_entries = filter_by_date(recent, today)
        all_today.extend(today_entries)

    # deduplicate
    seen = set()
    deduped = []
    for e in all_today:
        if e["id"] not in seen:
            deduped.append(e)
            seen.add(e["id"])

    # add keyword hits
    filtered = deduped + keyword_filter(deduped, KEYWORDS)

    # save to timestamped file
    out_file = OUTPUT_DIR / f"{today}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(filtered)} papers to {out_file}")

    # keep only last N days
    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    if len(json_files) > KEEP_DAYS:
        for old in json_files[:-KEEP_DAYS]:
            old.unlink()
            print(f"Deleted old file {old}")
