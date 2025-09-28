#!/usr/bin/env python3
# fetch_papers.py
import argparse
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import json
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}
CATEGORIES = ["cs.AI", "cs.CV", "cs.LG", "stat.ML"]

def parse_entry(e):
    arxiv_id = e.find("atom:id", NS).text
    pdf_link = arxiv_id.replace("abs", "pdf") + ".pdf"
    cats = [c.attrib.get("term") for c in e.findall("atom:category", NS)]
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

def _ymdhm(d_utc):   # YYYYMMDDHHMM
    return d_utc.strftime("%Y%m%d%H%M")

def _ymdhms(d_utc):  # YYYYMMDDHHMMSS
    return d_utc.strftime("%Y%m%d%H%M%S")

def _do_query(q, headers):
    params = {
        "search_query": q,
        "sortBy": "submittedDate",  # sorting key can stay submittedDate either way
        "sortOrder": "ascending",
        "max_results": 300,
    }
    r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    print("[DEBUG] GET:", r.url)
    root = ET.fromstring(r.text)
    entries = root.findall("atom:entry", NS)
    return entries

def fetch_for_day(category: str, day_utc):
    # Day window in UTC
    start = datetime(day_utc.year, day_utc.month, day_utc.day, 0, 0, 0, tzinfo=timezone.utc)
    end   = datetime(day_utc.year, day_utc.month, day_utc.day, 23, 59, 59, tzinfo=timezone.utc)

    headers = {"User-Agent": "daily-arxiv-fetch/0.2 (YOUR_REAL_EMAIL@domain)"}

    # Try in descending order of “strictness”
    queries = [
        # 1) submittedDate with seconds
        f"cat:{category}+AND+submittedDate:[{_ymdhms(start)}+TO+{_ymdhms(end)}]",
        # 2) lastUpdatedDate with seconds
        f"cat:{category}+AND+lastUpdatedDate:[{_ymdhms(start)}+TO+{_ymdhms(end)}]",
        # 3) submittedDate with minutes
        f"cat:{category}+AND+submittedDate:[{_ymdhm(start)}+TO+{_ymdhm(end)}]",
        # 4) lastUpdatedDate with minutes
        f"cat:{category}+AND+lastUpdatedDate:[{_ymdhm(start)}+TO+{_ymdhm(end)}]",
    ]

    for idx, q in enumerate(queries, 1):
        entries = _do_query(q, headers)
        print(f"[DEBUG] {category}: try#{idx} -> {len(entries)} entries")
        if entries:
            return [parse_entry(e) for e in entries]

    # 5) Sanity check: recent without date filter so we know the pipeline works
    fallback_q = f"cat:{category}"
    entries = _do_query(fallback_q, headers)
    print(f"[DEBUG] {category}: fallback(no date) -> {len(entries)} entries")
    return [parse_entry(e) for e in entries] if entries else []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="UTC date to fetch (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--out-dir", default="paper_json", help="Output directory.")
    parser.add_argument("--keep-days", type=int, default=5, help="How many daily JSONs to keep.")
    parser.add_argument("--dry-run", action="store_true", help="Print stats and write to out-dir, but don't commit (handled by workflow).")
    parser.add_argument("--categories", nargs="*", default=CATEGORIES, help="Override categories.")
    args = parser.parse_args()

    OUTPUT_DIR = Path(args.out_dir)
    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        day = datetime.now(timezone.utc).date()

    all_entries = []
    for cat in args.categories:
        entries = fetch_for_day(cat, day)
        all_entries.extend(entries)

    # Deduplicate by id
    seen, deduped = set(), []
    for e in all_entries:
        if e["id"] not in seen:
            deduped.append(e); seen.add(e["id"])

    out_file = OUTPUT_DIR / f"{day}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"[fetch_papers] Date={day} Categories={args.categories} -> {len(deduped)} papers")
    print(f"[fetch_papers] Wrote: {out_file}")

    # keep only last N days
    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    if len(json_files) > args.keep_days:
        for old in json_files[:-args.keep_days]:
            old.unlink()
            print(f"[fetch_papers] Deleted old file {old}")

if __name__ == "__main__":
    main()