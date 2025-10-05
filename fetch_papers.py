#!/usr/bin/env python3
# fetch_papers.py — tracks arXiv daily announcement via <updated>/lastUpdatedDate
import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

ARXIV_API = "https://export.arxiv.org/api/query"  # HTTPS
NS = {"atom": "http://www.w3.org/2005/Atom"}
ET_TZ = ZoneInfo("America/New_York")

# Default categories (no stat.ML)
CATEGORIES = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MM", "cs.GR", "cs.RO"]


def _user_agent() -> str:
    """Polite, descriptive UA without requiring extra env vars."""
    return "daily-arxiv-fetch/0.6 (GitHub Actions; contact owner via repo issues)"


def parse_atom_date(s: str) -> datetime | None:
    """Robust ISO-8601 parser for arXiv timestamps (e.g., '...Z' or '+00:00')."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_entry(e):
    arxiv_id = e.find("atom:id", NS).text
    pdf_link = arxiv_id.replace("abs", "pdf") + ".pdf"
    cats = [c.attrib.get("term") for c in e.findall("atom:category", NS)]
    authors = [a.find("atom:name", NS).text for a in e.findall("atom:author", NS)]

    return {
        "id": arxiv_id,
        "title": (e.find("atom:title", NS).text or "").strip(),
        "summary": (e.find("atom:summary", NS).text or "").strip(),
        "published": (e.find("atom:published", NS).text or "").strip(),
        "updated": (e.find("atom:updated", NS).text or "").strip(),
        "link": pdf_link,
        "category": cats,
        "authors": authors,
    }


def et_issue_window(announce_date_et):
    """
    For announcement day D (ET), arXiv's batch covers updates in:
      [D-1 14:00 ET, D 14:00 ET)
    Returns UTC window.
    """
    end_et = datetime(announce_date_et.year, announce_date_et.month, announce_date_et.day,
                      14, 0, 0, tzinfo=ET_TZ)
    start_et = end_et - timedelta(days=1)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _get_with_retries(params, max_tries: int = 4, pause: float = 3.0) -> str:
    headers = {"User-Agent": _user_agent()}
    last_exc = None
    for i in range(max_tries):
        try:
            r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
            if r.status_code in (429, 503):
                time.sleep(pause * (i + 1))
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_exc = e
            time.sleep(pause * (i + 1))
    raise RuntimeError(f"arXiv API failed after retries: {last_exc!r}")


def fetch_recent_desc(category: str, page_cap: int = 4, page_size: int = 200):
    """
    Fetch recent entries for a category, **sorted by lastUpdatedDate desc**.
    """
    all_entries = []
    for i in range(page_cap):
        start = i * page_size
        params = {
            "search_query": f"cat:{category}",
            "sortBy": "lastUpdatedDate",   # key change
            "sortOrder": "descending",
            "start": start,
            "max_results": page_size,
        }
        xml_text = _get_with_retries(params)
        root = ET.fromstring(xml_text)
        batch = root.findall("atom:entry", NS)
        all_entries.extend(batch)
        if len(batch) < page_size:
            break
        time.sleep(3)  # be polite
    print(f"[DEBUG] {category}: fetched {len(all_entries)} (lastUpdatedDate desc)")
    return all_entries


def fetch_for_announce_day(category: str, announce_day_et):
    """
    Keep entries whose **<updated>** falls within the ET window for this announcement day.
    Fallback to <published> if updated is missing (rare).
    """
    start_utc, end_utc = et_issue_window(announce_day_et)
    entries = fetch_recent_desc(category)

    kept = []
    for e in entries:
        upd = (e.find("atom:updated", NS).text or "").strip()
        pub = (e.find("atom:published", NS).text or "").strip()
        dt = parse_atom_date(upd) or parse_atom_date(pub)
        if dt is None:
            continue
        if start_utc <= dt < end_utc:
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
    parser.add_argument("--date", help="Announcement day in ET (YYYY-MM-DD). Default: today in ET.")
    parser.add_argument("--out-dir", default="paper_json", help="Output directory.")
    parser.add_argument("--categories", nargs="*", default=CATEGORIES,
                        help="Override categories (space-separated).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write files but skip any commit/push (handled by workflow).")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    # Announcement day in ET
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

    # Write daily file named by announcement day (ET)
    out_file = out_dir / f"{announce_day_et}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"[fetch_papers] AnnounceDay(ET)={announce_day_et} -> {len(deduped)} papers")
    print(f"[fetch_papers] Wrote: {out_file}")

    # Update index.json for the calendar
    save_index(out_dir / "index.json", str(announce_day_et), len(deduped))


if __name__ == "__main__":
    main()
