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
CATEGORIES = ["cs.AI","cs.CL","cs.CV","cs.LG","cs.MM","cs.GR","cs.RO"]

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
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
        "max_results": 300,
    }
    r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    print("[DEBUG] GET:", r.url)
    root = ET.fromstring(r.text)
    return root.findall("atom:entry", NS)

# add this extra line in parse_entry if you want to see revision dates too:
# "updated": e.find("atom:updated", NS).text,

def fetch_for_day(category: str, day_utc):
    """Fetch recent in the category and filter locally by the UTC date."""
    # 1) get recent (descending) — 500 is usually plenty for a single day/window
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": 500,
    }
    headers = {"User-Agent": "daily-arxiv-fetch/0.2 (YOUR_REAL_EMAIL@domain)"}
    r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    entries = root.findall("atom:entry", NS)
    print(f"[DEBUG] {category}: fetched {len(entries)} recent")

    # 2) local filter by <published> date (and optionally include <updated> matches)
    want = []
    for e in entries:
        pub = e.find("atom:published", NS).text  # e.g. '2025-09-24T12:34:56Z'
        pub_day = datetime.fromisoformat(pub.replace("Z", "+00:00")).date()
        if pub_day == day_utc:
            want.append(parse_entry(e))
            continue

        # OPTIONAL: uncomment to also include revisions updated on that date
        # upd = e.find("atom:updated", NS).text
        # upd_day = datetime.fromisoformat(upd.replace("Z", "+00:00")).date()
        # if upd_day == day_utc:
        #     want.append(parse_entry(e))

    print(f"[DEBUG] {category}: kept {len(want)} for {day_utc}")
    return want

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="UTC date to fetch (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--out-dir", default="paper_json", help="Output directory.")
    parser.add_argument("--dry-run", action="store_true", help="Skip commit in workflow (still writes files).")
    parser.add_argument("--categories", nargs="*", default=CATEGORIES, help="Override categories.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        day = datetime.now(timezone.utc).date()

    all_entries = []
    for cat in args.categories:
        all_entries.extend(fetch_for_day(cat, day))

    # de-dupe
    seen, deduped = set(), []
    for e in all_entries:
        if e["id"] not in seen:
            deduped.append(e); seen.add(e["id"])

    # write daily file (always, even if empty)
    out_file = out_dir / f"{day}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"[fetch_papers] Date={day} -> {len(deduped)} papers")
    print(f"[fetch_papers] Wrote: {out_file}")

    # update index.json (list of {date, count}) so the site can bound the calendar
    index_path = out_dir / "index.json"
    index = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(index, list):
                index = []
        except Exception:
            index = []

    # replace or append today’s entry
    day_str = str(day)
    entry = {"date": day_str, "count": len(deduped)}
    index = [e for e in index if e.get("date") != day_str] + [entry]
    index.sort(key=lambda x: x["date"])  # ascending
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[fetch_papers] Updated index: {index_path}")

if __name__ == "__main__":
    main()
