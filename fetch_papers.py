#!/usr/bin/env python3
# fetch_papers.py
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}
ET_TZ = ZoneInfo("America/New_York")

# Default categories (no stat.ML)
CATEGORIES = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MM", "cs.GR", "cs.RO"]


def parse_entry(e):
    arxiv_id = e.find("atom:id", NS).text
    pdf_link = arxiv_id.replace("abs", "pdf") + ".pdf"

    cats = [c.attrib.get("term") for c in e.findall("atom:category", NS)]
    authors = [a.find("atom:name", NS).text for a in e.findall("atom:author", NS)]

    return {
        "id": arxiv_id,
        "title": (e.find("atom:title", NS).text or "").strip(),
        "summary": (e.find("atom:summary", NS).text or "").strip(),
        "published": e.find("atom:published", NS).text,  # e.g., '2025-09-24T12:34:56Z'
        # "updated": e.find("atom:updated", NS).text,    # uncomment if you want it
        "link": pdf_link,
        "category": cats,
        "authors": authors,
    }


def et_issue_window(announce_date_et):
    """
    For announcement day D in ET, the issue contains papers with <published> in:
      [D-1 14:00 ET, D 14:00 ET)
    Returns (start_utc, end_utc).
    """
    end_et = datetime(announce_date_et.year, announce_date_et.month, announce_date_et.day,
                      14, 0, 0, tzinfo=ET_TZ)
    start_et = end_et - timedelta(days=1)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def fetch_recent_desc(category: str, page_cap: int = 3, page_size: int = 300):
    """
    Fetch recent entries for a category, sorted by submittedDate descending.
    We page a few times (default up to 900 entries) to comfortably cover the day.
    """
    headers = {"User-Agent": "daily-arxiv-fetch/0.3 (your_email@example.com)"}
    all_entries = []
    for i in range(page_cap):
        start = i * page_size
        params = {
            "search_query": f"cat:{category}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": page_size,
        }
        r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        batch = root.findall("atom:entry", NS)
        all_entries.extend(batch)
        # If fewer than a full page, we've hit the end.
        if len(batch) < page_size:
            break
    print(f"[DEBUG] {category}: fetched {len(all_entries)} recent (desc)")
    return all_entries


def fetch_for_announce_day(category: str, announce_day_et):
    """
    Keep entries whose <published> falls within the ET window for this announcement day.
    """
    start_utc, end_utc = et_issue_window(announce_day_et)
    entries = fetch_recent_desc(category)

    kept = []
    for e in entries:
        pub = e.find("atom:published", NS).text
        if not pub:
            continue
        pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        if start_utc <= pub_dt < end_utc:
            kept.append(parse_entry(e))

    print(f"[DEBUG] {category}: kept {len(kept)} for announce {announce_day_et} "
          f"(window {start_utc.isoformat()} .. {end_utc.isoformat()})")
    return kept


def load_index(index_path: Path):
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(index_path: Path, date_str: str, count: int):
    index = load_index(index_path)
    entry = {"date": date_str, "count": count}
    index = [e for e in index if e.get("date") != date_str] + [entry]
    index.sort(key=lambda x: x["date"])  # ascending
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[fetch_papers] Updated index: {index_path}")


def main():
    parser = argparse.ArgumentParser(description="Fetch arXiv issue by announcement day (ET).")
    parser.add_argument(
        "--date",
        help="Announcement day in ET (YYYY-MM-DD). Default: today in ET."
    )
    parser.add_argument("--out-dir", default="paper_json", help="Output directory.")
    parser.add_argument(
        "--categories", nargs="*", default=CATEGORIES,
        help="Override categories (space-separated)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Write files but skip any commit/push (handled by workflow)."
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    # Interpret --date as ET (announcement day). Default to 'today' in ET.
    if args.date:
        announce_day_et = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        announce_day_et = datetime.now(ET_TZ).date()

    # Gather
    all_entries = []
    for cat in args.categories:
        all_entries.extend(fetch_for_announce_day(cat, announce_day_et))

    # De-duplicate by id
    seen, deduped = set(), []
    for e in all_entries:
        if e["id"] not in seen:
            deduped.append(e)
            seen.add(e["id"])

    # Write daily file named by *announcement day (ET)*
    out_file = out_dir / f"{announce_day_et}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"[fetch_papers] AnnounceDay(ET)={announce_day_et} -> {len(deduped)} papers")
    print(f"[fetch_papers] Wrote: {out_file}")

    # Update index.json for the calendar
    save_index(out_dir / "index.json", str(announce_day_et), len(deduped))


if __name__ == "__main__":
    main()
