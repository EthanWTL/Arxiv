#!/usr/bin/env python3
# fetch_papers.py — tracks arXiv daily announcement dates in America/New_York.
import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

ARXIV_API = "https://export.arxiv.org/api/query"  # HTTPS
NS = {"atom": "http://www.w3.org/2005/Atom"}
ET_TZ = ZoneInfo("America/New_York")
ANNOUNCEMENT_HOUR_ET = 20
NO_ANNOUNCEMENT_WEEKDAYS = {4, 5}  # Friday, Saturday. Sunday-Thursday announce.
MIN_API_INTERVAL_SECONDS = 3.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_last_api_request_at = 0.0

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


def has_announcement_day(announce_day_et: date) -> bool:
    return announce_day_et.weekday() not in NO_ANNOUNCEMENT_WEEKDAYS


def default_announcement_day(now_et: datetime | None = None) -> date:
    """
    Pick the ET calendar date whose announcement should be available now.

    arXiv announces at about 20:00 ET. If this job is delayed past midnight
    but before the next 20:00 ET announcement, use yesterday instead of
    accidentally writing an empty file for the next calendar date.
    """
    now_et = now_et or datetime.now(ET_TZ)
    announce_day = now_et.date()
    if now_et.hour < ANNOUNCEMENT_HOUR_ET:
        announce_day = announce_day - timedelta(days=1)
    return announce_day


def _wait_for_rate_limit():
    """Keep all arXiv API calls at least ~3 seconds apart."""
    global _last_api_request_at
    now = time.monotonic()
    elapsed = now - _last_api_request_at
    if elapsed < MIN_API_INTERVAL_SECONDS:
        time.sleep(MIN_API_INTERVAL_SECONDS - elapsed)
    _last_api_request_at = time.monotonic()


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return min(max(0.0, float(value)), 300.0)
    except ValueError:
        return None


def _response_snippet(text: str, limit: int = 300) -> str:
    return " ".join((text or "").split())[:limit]


def _get_with_retries(params, max_tries: int = 8, pause: float = 10.0) -> str:
    headers = {"User-Agent": _user_agent()}
    last_error = None
    for attempt in range(1, max_tries + 1):
        try:
            _wait_for_rate_limit()
            r = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
            if r.status_code in RETRYABLE_STATUS_CODES:
                snippet = _response_snippet(r.text)
                last_error = f"HTTP {r.status_code}; response={snippet!r}; url={r.url}"
                retry_after = _retry_after_seconds(r.headers.get("Retry-After"))
                wait = (
                    retry_after
                    if retry_after is not None
                    else min(pause * (2 ** (attempt - 1)), 180.0)
                )
                if attempt < max_tries:
                    print(
                        f"[WARN] arXiv API {last_error}; retrying in {wait:.0f}s "
                        f"(attempt {attempt}/{max_tries})",
                        flush=True,
                    )
                    time.sleep(wait)
                    continue
                break
            if r.status_code >= 400:
                snippet = _response_snippet(r.text)
                raise RuntimeError(
                    f"arXiv API returned HTTP {r.status_code}: {snippet!r}; url={r.url}"
                )
            return r.text
        except requests.RequestException as e:
            last_error = repr(e)
            wait = min(pause * (2 ** (attempt - 1)), 180.0)
            if attempt < max_tries:
                print(
                    f"[WARN] arXiv request failed: {last_error}; "
                    f"retrying in {wait:.0f}s (attempt {attempt}/{max_tries})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            break
    raise RuntimeError(f"arXiv API failed after {max_tries} attempts: {last_error}")


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
    print(f"[DEBUG] {category}: fetched {len(all_entries)} (lastUpdatedDate desc)")
    return all_entries


def fetch_for_announce_day(category: str, announce_day_et):
    """
    Keep entries whose <updated> (or <published> fallback) falls on this
    *announcement calendar date in America/New_York*.
    This corresponds to: "papers that became public on this ET day".
    """
    # Accept either a date or a datetime for announce_day_et
    if isinstance(announce_day_et, datetime):
        target_date = announce_day_et.date()
    else:
        target_date = announce_day_et  # assume it's already a date

    entries = fetch_recent_desc(category)
    kept = []

    for e in entries:
        upd_el = e.find("atom:updated", NS)
        pub_el = e.find("atom:published", NS)

        upd = (upd_el.text if upd_el is not None and upd_el.text else "").strip()
        pub = (pub_el.text if pub_el is not None and pub_el.text else "").strip()

        dt = parse_atom_date(upd) or parse_atom_date(pub)
        if dt is None:
            continue

        # Convert the timestamp to Eastern Time and compare the *date* only
        dt_et = dt.astimezone(ET_TZ)
        if dt_et.date() == target_date:
            kept.append(parse_entry(e))

    print(
        f"[DEBUG] {category}: kept {len(kept)} entries for announce_day_et={target_date}"
    )
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
        announce_day_et = default_announcement_day()

    # Gather
    all_entries = []
    if has_announcement_day(announce_day_et):
        for cat in args.categories:
            all_entries.extend(fetch_for_announce_day(cat, announce_day_et))
    else:
        print(
            f"[fetch_papers] AnnounceDay(ET)={announce_day_et} has no arXiv "
            "announcement; writing an empty JSON file."
        )

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
