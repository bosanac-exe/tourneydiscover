"""
Recreates the /find/tournament/DoSearch XHR call used by ota.tournamentsoftware.com's
"find a tournament" search page, and parses the returned HTML fragment into structured
tournament records.

Usage:
    python fetch_tournaments.py --start 2026-08-31 --end 2026-09-30 --org 1E0C1B66-6BCC-427A-9B16-D5F3F06913A4

The OrganizationGroupIDList value identifies the sport/organization (Ontario Tennis
Association in the captured .har). Distance/PostalCode filter by location; leave
PostalCode empty and Distance at a default to get all results in the date range.
"""
import argparse
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ota.tournamentsoftware.com"
SEARCH_URL = f"{BASE_URL}/find/tournament/DoSearch"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
DETAIL_REQUEST_DELAY = 0.5  # seconds between tournament detail page requests

# Ontario Tennis Association
DEFAULT_ORG_GROUP_ID = "1E0C1B66-6BCC-427A-9B16-D5F3F06913A4"

# Static False-valued list fields the site's form always posts; kept as-is for parity
# with the real browser request (unchecked checkboxes still serialize as "false").
FALSE_LIST_FIELDS = {
    "TournamentExtendedFilter.TournamentCategoryIDList": 8,
    "TournamentExtendedFilter.EventLevelIDList": 7,
    "TournamentExtendedFilter.EventGameTypeIDList": 5,
}


@dataclass
class Tournament:
    id: str
    name: str
    url: str
    location: str
    distance_km: Optional[float]
    start_date: Optional[str]
    end_date: Optional[str]
    status_tags: list
    category_tags: list
    cancelled: bool


def build_payload(page: int, start_date: str, end_date: str, org_group_id: str,
                   distance: str = "", postal_code: str = "", query: str = "",
                   date_filter_type: int = 0, sport_id: int = 0) -> dict:
    payload = {
        "Page": page,
        "TournamentExtendedFilter.SportID": sport_id,
        "TournamentFilter.Q": query,
        "TournamentFilter.DateFilterType": date_filter_type,
        "TournamentFilter.StartDate": start_date,
        "TournamentFilter.EndDate": end_date,
        "TournamentFilter.PostalCode": postal_code,
        "TournamentFilter.Distance": distance,
        "TournamentExtendedFilter.OrganizationGroupIDList": org_group_id,
        "TournamentExtendedFilter.StatusFilterID": "false",
        "X-Requested-With": "XMLHttpRequest",
    }
    for field, count in FALSE_LIST_FIELDS.items():
        for i in range(count):
            payload[f"{field}[{i}]"] = "false"
    return payload


def parse_tournaments(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    tournaments = []

    for li in soup.select("li.list__item"):
        media = li.select_one(".media")
        if media is None:
            continue

        link = media.select_one(".media__title a")
        if link is None:
            continue

        href = link.get("href", "")
        match = re.search(r"id=([0-9A-Fa-f-]{36})", href)
        tid = match.group(1) if match else ""
        name = link.get_text(strip=True)

        location_el = media.select_one(".media__subheading .nav-link__value")
        location = location_el.get_text(strip=True) if location_el else ""

        # Distance from the searched postal code is appended as e.g. "... | Toronto (7.1 km)".
        distance_km = None
        dist_match = re.search(r"\(([\d.]+)\s*km\)\s*$", location)
        if dist_match:
            distance_km = float(dist_match.group(1))
            location = location[:dist_match.start()].strip()

        times = media.select(".media__subheading--muted time")
        start_date = times[0].get("datetime", "").split(" ")[0] if len(times) > 0 else None
        end_date = times[1].get("datetime", "").split(" ")[0] if len(times) > 1 else start_date

        status_tags = [t.get_text(strip=True) for t in media.select(".tag--danger .nav-link__value")]
        cancelled = any("cancel" in t.lower() for t in status_tags)

        category_tags = [t.get_text(strip=True) for t in media.select(".tag, .tag--soft") if t.get_text(strip=True)]

        tournaments.append(Tournament(
            id=tid,
            name=name,
            url=f"{BASE_URL}{href}",
            location=location,
            distance_km=distance_km,
            start_date=start_date,
            end_date=end_date,
            status_tags=status_tags,
            category_tags=category_tags,
            cancelled=cancelled,
        ))

    return tournaments


def fetch_all_tournaments(start_date: str, end_date: str, org_group_id: str = DEFAULT_ORG_GROUP_ID,
                           distance: str = "", postal_code: str = "", query: str = "",
                           max_pages: int = 50) -> list:
    session = requests.Session()
    session.headers.update({
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/find?StartDate={start_date}&EndDate={end_date}"
                   f"&DateFilterType=0&Distance={distance}"
                   f"&OrganizationGroupIDList={org_group_id}&page=1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    })
    # Note: each page response is cumulative (page N includes all results from
    # pages 1..N), so we only need to keep parsing the latest response.
    latest_tournaments = []
    page = 1
    while page <= max_pages:
        payload = build_payload(page, start_date, end_date, org_group_id, distance, postal_code, query)
        resp = session.post(SEARCH_URL, data=payload, timeout=30)
        resp.raise_for_status()

        page_tournaments = parse_tournaments(resp.text)
        if not page_tournaments:
            break

        latest_tournaments = page_tournaments

        has_more = resp.headers.get("hasmoreresults", "false").lower() == "true"
        if not has_more:
            break
        page += 1

    return latest_tournaments


def _text_or_none(element) -> Optional[str]:
    if element is None:
        return None
    text = " ".join(element.get_text(" ", strip=True).split())
    return text or None


def parse_tournament_address(html: str) -> dict:
    """Extracts the address microformat fields from a tournament detail page."""
    soup = BeautifulSoup(html, "html.parser")
    address = soup.select_one(".p-adr.h-adr")
    fields_root = soup
    fields = {
        "street_address": _text_or_none(address.select_one(".p-street-address"))
        if address else None,
        "postal_code": _text_or_none(fields_root.select_one(".p-postal-code")),
        "locality": _text_or_none(fields_root.select_one(".p-locality")),
        "region": _text_or_none(fields_root.select_one(".p-region")),
    }
    address_parts = [fields[key] for key in ("street_address", "locality", "region", "postal_code")
                     if fields[key]]
    fields["address"] = ", ".join(address_parts) or None
    fields["maps_url"] = build_maps_url(fields["address"])
    return fields


def build_maps_url(destination: Optional[str]) -> Optional[str]:
    if not destination:
        return None
    params = urlencode({
        "api": "1",
        "origin": "Toronto, ON M6S 2Y5",
        "destination": destination,
        "travelmode": "driving",
        "avoid": "tolls",
    })
    return f"https://www.google.com/maps/dir/?{params}"


def parse_entry_open_date(html: str) -> Optional[str]:
    """Extracts the 'Entry opens' date (YYYY-MM-DD) from a tournament detail page."""
    soup = BeautifulSoup(html, "html.parser")

    item = soup.select_one("li.is-entry-open")
    if item is None:
        for value in soup.select(".list__value"):
            if value.get_text(strip=True).lower().startswith("entry open"):
                item = value.parent
                break
    if item is None:
        return None

    time_el = item.find("time")
    if time_el is None or not time_el.get("datetime"):
        return None
    return time_el["datetime"][:10]


def fetch_entry_open_dates(urls: list, delay: float = DETAIL_REQUEST_DELAY,
                            session: Optional[requests.Session] = None) -> dict:
    """Maps each tournament URL to detail fields, pausing between requests."""
    session = session or requests.Session()
    # The site returns 404 for the default requests user-agent.
    session.headers.update({
        "user-agent": USER_AGENT,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    results = {}
    for i, url in enumerate(urls):
        if i:
            time.sleep(delay)
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            details = parse_tournament_address(resp.text)
            details["entry_open_date"] = parse_entry_open_date(resp.text)
            results[url] = details
        except requests.RequestException as exc:
            print(f"WARN: could not fetch {url}: {exc}", file=sys.stderr)
            results[url] = {}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--org", default=DEFAULT_ORG_GROUP_ID, help="OrganizationGroupIDList GUID")
    parser.add_argument("--distance", default="")
    parser.add_argument("--postal-code", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a table")
    args = parser.parse_args()

    tournaments = fetch_all_tournaments(
        start_date=args.start,
        end_date=args.end,
        org_group_id=args.org,
        distance=args.distance,
        postal_code=args.postal_code,
        query=args.query,
    )

    if args.json:
        import json
        print(json.dumps([asdict(t) for t in tournaments], indent=2))
        return

    print(f"Found {len(tournaments)} tournaments between {args.start} and {args.end}\n")
    for t in tournaments:
        flag = " [CANCELLED]" if t.cancelled else ""
        print(f"- {t.start_date} to {t.end_date}: {t.name}{flag}")
        print(f"    {t.location}")
        print(f"    {t.url}")


if __name__ == "__main__":
    sys.exit(main())
