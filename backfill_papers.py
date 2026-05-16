#!/usr/bin/env python3
"""Backfill paper_json/{date}.json for a range of past ET announcement days.

Matches fetch_papers.py's bucketing rule: a paper belongs to day D (ET) if
its <updated> (or <published>) timestamp falls on calendar date D in ET.

Strategy: walk the range in week-sized chunks; for each chunk + category,
query arXiv with submittedDate:[chunk_start-3 TO chunk_end+1] and paginate
fully. Bucket entries by updated-ET date and write per-day files.

Note: catches all new submissions whose updated lands in the window, plus
any revisions of papers submitted in the prior ~3 days. Misses revisions
of long-old papers — acceptable for backfill, since arXiv listings are
dominated by fresh submissions.
"""
from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

from fetch_papers import (
    ARXIV_API,
    CATEGORIES,
    ET_TZ,
    NS,
    _user_agent,
    parse_atom_date,
    parse_entry,
    save_index,
)


def _get(params, max_tries: int = 15, pause: float = 30.0) -> str:
    headers = {"User-Agent": _user_agent()}
    last = None
    for i in range(max_tries):
        try:
            r = requests.get(ARXIV_API, params=params, headers=headers, timeout=60)
            if r.status_code in (429, 503):
                last = f"HTTP {r.status_code}"
                # Capped backoff: 30, 60, 120, 240, 240, ...
                wait = min(pause * (2 ** i), 240.0)
                print(f"  [rate-limited] sleeping {wait:.0f}s (attempt {i+1}/{max_tries})", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(pause)
    raise RuntimeError(f"arXiv API failed after {max_tries} tries: {last!r}")


def fetch_window(category: str, start_dt: datetime, end_dt: datetime,
                 page_size: int = 200, page_cap: int = 15, polite_sleep: float = 3.0):
    """Fetch all entries for `category` with submittedDate in [start_dt, end_dt]."""
    s = start_dt.strftime("%Y%m%d%H%M")
    e = end_dt.strftime("%Y%m%d%H%M")
    query = f"cat:{category} AND submittedDate:[{s} TO {e}]"
    out = []
    for i in range(page_cap):
        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": i * page_size,
            "max_results": page_size,
        }
        xml_text = _get(params)
        root = ET.fromstring(xml_text)
        batch = root.findall("atom:entry", NS)
        out.extend(batch)
        if len(batch) < page_size:
            break
        time.sleep(polite_sleep)
    print(f"  [{category}] window {s}-{e}: {len(out)} entries")
    return out


def bucket_by_et_date(entries):
    """Return {date: [parsed_entry, ...]} keyed by ET date of <updated>."""
    buckets: dict[date, list[dict]] = {}
    for e in entries:
        upd_el = e.find("atom:updated", NS)
        pub_el = e.find("atom:published", NS)
        upd = (upd_el.text if upd_el is not None and upd_el.text else "").strip()
        pub = (pub_el.text if pub_el is not None and pub_el.text else "").strip()
        dt = parse_atom_date(upd) or parse_atom_date(pub)
        if dt is None:
            continue
        d = dt.astimezone(ET_TZ).date()
        buckets.setdefault(d, []).append(parse_entry(e))
    return buckets


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main():
    p = argparse.ArgumentParser(description="Backfill arXiv day files in a range.")
    p.add_argument("--start", required=True, help="Inclusive start (YYYY-MM-DD, ET).")
    p.add_argument("--end", required=True, help="Inclusive end (YYYY-MM-DD, ET).")
    p.add_argument("--out-dir", default="paper_json")
    p.add_argument("--categories", nargs="*", default=CATEGORIES)
    p.add_argument("--chunk-days", type=int, default=7,
                   help="Days per arXiv query window (default 7).")
    p.add_argument("--lookback-days", type=int, default=3,
                   help="Extra days before chunk_start to widen submittedDate filter.")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing non-empty files (default: skip).")
    p.add_argument("--polite-sleep", type=float, default=3.0)
    args = p.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        raise SystemExit("--end must be >= --start")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    index_path = out_dir / "index.json"

    # Walk in chunk-sized windows; each chunk covers chunk_days ET days.
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=args.chunk_days - 1), end)

        # Window in UTC, with lookback to catch revisions of recent submissions.
        win_start_et = datetime(
            (chunk_start - timedelta(days=args.lookback_days)).year,
            (chunk_start - timedelta(days=args.lookback_days)).month,
            (chunk_start - timedelta(days=args.lookback_days)).day,
            0, 0, tzinfo=ET_TZ,
        )
        win_end_et = datetime(chunk_end.year, chunk_end.month, chunk_end.day,
                              23, 59, tzinfo=ET_TZ) + timedelta(days=1)
        win_start_utc = win_start_et.astimezone(timezone.utc)
        win_end_utc = win_end_et.astimezone(timezone.utc)

        print(f"\n=== Chunk {chunk_start} → {chunk_end} "
              f"(UTC submittedDate {win_start_utc:%Y%m%d%H%M}–{win_end_utc:%Y%m%d%H%M}) ===")

        all_entries = []
        for cat in args.categories:
            all_entries.extend(fetch_window(cat, win_start_utc, win_end_utc,
                                            polite_sleep=args.polite_sleep))
            time.sleep(args.polite_sleep)

        buckets = bucket_by_et_date(all_entries)

        # Write per-day files for days that fall within [chunk_start, chunk_end].
        for d in daterange(chunk_start, chunk_end):
            day_papers = buckets.get(d, [])
            # Dedupe by id (papers can appear in multiple categories).
            seen, deduped = set(), []
            for e in day_papers:
                if e["id"] not in seen:
                    deduped.append(e)
                    seen.add(e["id"])

            out_file = out_dir / f"{d}.json"
            if out_file.exists() and not args.overwrite:
                try:
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
                if isinstance(existing, list) and len(existing) > 0:
                    print(f"  SKIP {out_file.name}: already has {len(existing)} papers")
                    continue

            out_file.write_text(json.dumps(deduped, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            print(f"  WROTE {out_file.name}: {len(deduped)} papers")
            save_index(index_path, str(d), len(deduped))

        chunk_start = chunk_end + timedelta(days=1)

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
