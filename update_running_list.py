"""
Daily parser job: searches ota.tournamentsoftware.com for tournaments starting
between today+2 weeks and today+3 months near postal code M6S 2Y5, then merges
the results into a running list (data/tournaments.json).

New tournaments are stamped with the date they were discovered. Tournaments whose
start date is older than today are dropped from the list.

Usage:
    python update_running_list.py [--store data/tournaments.json]
"""
import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from fetch_tournaments import DEFAULT_ORG_GROUP_ID, fetch_all_tournaments, fetch_entry_open_dates

POSTAL_CODE = "M6S 2Y5"
DISTANCE = ""  # blank = site default / unrestricted
WINDOW_START_DAYS = 14
WINDOW_END_MONTHS = 3
DEFAULT_STORE = Path("data") / "tournaments.json"


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def load_store(path: Path) -> dict:
    if not path.exists():
        return {"updated_at": None, "tournaments": []}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, ensure_ascii=False)


def prune(records: list, today: date) -> list:
    kept = []
    for rec in records:
        start = rec.get("start_date")
        if not start:
            kept.append(rec)
            continue
        try:
            if datetime.strptime(start, "%Y-%m-%d").date() >= today:
                kept.append(rec)
        except ValueError:
            kept.append(rec)
    return kept


def merge(existing: list, fetched: list, discovered_on: str) -> tuple:
    by_id = {rec["id"]: rec for rec in existing if rec.get("id")}
    new_records = []

    for t in fetched:
        rec = asdict(t)
        if not rec["id"]:
            continue
        if rec["id"] in by_id:
            # Refresh mutable fields but preserve the original discovery date.
            discovered = by_id[rec["id"]].get("discovered_date", discovered_on)
            rec["discovered_date"] = discovered
            rec["entry_open_date"] = by_id[rec["id"]].get("entry_open_date")
            for field in ("street_address", "postal_code", "locality", "region", "address", "maps_url"):
                rec[field] = by_id[rec["id"]].get(field)
            by_id[rec["id"]].update(rec)
        else:
            rec["discovered_date"] = discovered_on
            rec["entry_open_date"] = None
            for field in ("street_address", "postal_code", "locality", "region", "address", "maps_url"):
                rec[field] = None
            by_id[rec["id"]] = rec
            new_records.append(rec)

    return list(by_id.values()), new_records


def run(store_path: Path, today: date | None = None) -> dict:
    today = today or date.today()
    start_date = (today + timedelta(days=WINDOW_START_DAYS)).isoformat()
    end_date = add_months(today, WINDOW_END_MONTHS).isoformat()

    fetched = fetch_all_tournaments(
        start_date=start_date,
        end_date=end_date,
        org_group_id=DEFAULT_ORG_GROUP_ID,
        distance=DISTANCE,
        postal_code=POSTAL_CODE,
    )

    store = load_store(store_path)
    records, new_records = merge(store.get("tournaments", []), fetched, today.isoformat())
    records = prune(records, today)
    records.sort(key=lambda r: (r.get("start_date") or "", r.get("name") or ""))

    # Entry dates and addresses only live on detail pages, so fetch missing details.
    pending = [r["url"] for r in records
               if (not r.get("entry_open_date") or not r.get("maps_url")) and r.get("url")]
    entry_dates = fetch_entry_open_dates(pending)
    for rec in records:
        details = entry_dates.get(rec.get("url"), {})
        for field in ("entry_open_date", "street_address", "postal_code", "locality", "region",
                      "address", "maps_url"):
            if not rec.get(field) and details.get(field):
                rec[field] = details[field]

    store = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "search_window": {"start": start_date, "end": end_date},
        "postal_code": POSTAL_CODE,
        "tournaments": records,
    }
    save_store(store_path, store)

    return {
        "fetched": len(fetched),
        "new": len(new_records),
        "total": len(records),
        "entry_dates_fetched": len(pending),
        "window": (start_date, end_date),
        "new_records": new_records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args()

    result = run(args.store)
    start, end = result["window"]
    print(f"Window {start} .. {end} (postal {POSTAL_CODE})")
    print(f"Fetched {result['fetched']}, new {result['new']}, running list now {result['total']}")
    print(f"Entry-open lookups: {result['entry_dates_fetched']}")
    for rec in result["new_records"]:
        print(f"  NEW  {rec['start_date']}  {rec['name']}")


if __name__ == "__main__":
    main()
