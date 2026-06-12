#!/usr/bin/env python3
"""
STADTRADELN scraper for Dataciders teams.
- Finished teams: seeded from docs/data/final_results.json (manual entry, no scraping)
- Active teams:   scraped via Playwright 2x daily once their event has started
"""

import json
import re
import sys
from datetime import datetime, timezone, date
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

REPO_ROOT      = Path(__file__).parent.parent
TEAMS_FILE     = REPO_ROOT / "docs" / "data" / "teams.json"
SNAPSHOTS_FILE = REPO_ROOT / "docs" / "data" / "snapshots.json"
FINAL_FILE     = REPO_ROOT / "docs" / "data" / "final_results.json"

STADTRADELN_BASE = "https://www.stadtradeln.de"
# DataTables table ID used on all STADTRADELN leaderboard pages
DATATABLE_ID = "auswertungKommune"


def parse_number(s: str) -> float:
    """
    Extract the first numeric value from a string.
    Handles German formatting (1.234,5), unit suffixes ('361 km'),
    and multi-line DataTables cells ('2\n  2 Aktive Radelnde...').
    """
    if not s:
        return 0.0
    # Find the first number (digits with optional German thousand/decimal separators)
    match = re.search(r"[\d]+(?:[.,][\d]+)*", s.strip())
    if not match:
        return 0.0
    raw = match.group()
    # German format: dots = thousands sep, comma = decimal sep
    # e.g. "1.234,5" -> "1234.5"
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def detect_columns(page) -> dict:
    """Read DataTables thead to map column keywords to 0-based indices."""
    col_map = {"km": None, "rides": None, "riders": None, "km_per_head": None}
    try:
        ths = page.query_selector_all(f"#{DATATABLE_ID} thead th")
        headers = [(th.text_content() or "").strip().lower() for th in ths]
        print(f"  Headers: {headers}")
        for i, h in enumerate(headers):
            if "km" in h and "kopf" not in h and "head" not in h and col_map["km"] is None:
                col_map["km"] = i
            if ("fahrt" in h or "ride" in h) and col_map["rides"] is None:
                col_map["rides"] = i
            if ("radeln" in h or "rider" in h or "teilnehm" in h) and col_map["riders"] is None:
                col_map["riders"] = i
            if ("kopf" in h or "head" in h) and col_map["km_per_head"] is None:
                col_map["km_per_head"] = i
    except Exception as e:
        print(f"  Header read failed: {e}")
    print(f"  Column map: {col_map}")
    return col_map


def scrape_team(page, city_slug: str, team_name: str):
    """
    Uses the DataTables JS API to search for the team, then reads the result row.
    Returns dict with sum_km/rides/riders/km_per_head or None if not found.
    """
    url = f"{STADTRADELN_BASE}/{city_slug}"
    print(f"  -> {url}")

    try:
        page.goto(url, timeout=30_000, wait_until="networkidle")
        page.wait_for_selector(f"#{DATATABLE_ID}", timeout=20_000)
    except PlaywrightTimeoutError:
        print(f"  x Page or table timed out")
        return None

    col_map = detect_columns(page)

    # Use DataTables JS API to filter to our team
    try:
        safe_name = team_name.replace("'", "\\'")
        page.evaluate(f"$('#{DATATABLE_ID}').DataTable().search('{safe_name}').draw()")
        page.wait_for_timeout(1_500)
    except Exception as e:
        print(f"  x DataTables search failed: {e}")
        return None

    rows = page.query_selector_all(f"#{DATATABLE_ID} tbody tr")
    if not rows:
        print(f"  x No rows after search")
        return None

    for row in rows:
        cells = row.query_selector_all("td")
        texts = [(c.text_content() or "").strip() for c in cells]
        if team_name.lower() in " ".join(texts).lower():
            print(f"  + Matched: {texts}")

            def cell(idx):
                if idx is not None and idx < len(texts):
                    return parse_number(texts[idx])
                return 0.0

            if col_map["km"] is not None:
                return {
                    "sum_km":      cell(col_map["km"]),
                    "rides":       int(cell(col_map["rides"])),
                    "riders":      int(cell(col_map["riders"])),
                    "km_per_head": cell(col_map["km_per_head"]),
                }

            # Fallback: skip index 0 (rank), take next 4 numbers
            nums = [parse_number(t) for t in texts if parse_number(t) > 0 or t.strip() == "0"]
            if len(nums) >= 4:
                return {"sum_km": nums[1], "rides": int(nums[2]), "riders": int(nums[3]),
                        "km_per_head": nums[4] if len(nums) > 4 else 0.0}

    print(f"  x '{team_name}' not found")
    return None


def load_data() -> tuple:
    with open(TEAMS_FILE, encoding="utf-8") as f:
        teams_data = json.load(f)
    with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
        snapshots_data = json.load(f)
    return teams_data["teams"], snapshots_data


def load_final_results() -> dict:
    if not FINAL_FILE.exists():
        return {}
    with open(FINAL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {r["team_id"]: r for r in data.get("results", [])}


def save_snapshots(snapshots_data: dict):
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots_data, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(snapshots_data['snapshots'])} total snapshots")


def main():
    teams, snapshots_data = load_data()
    final_results = load_final_results()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = date.today()
    new_entries = []

    existing_team_ids = {s["team_id"] for s in snapshots_data.get("snapshots", [])}

    # --- Seed finished teams from manual file (once) ---
    for team_id, result in final_results.items():
        if team_id in existing_team_ids:
            continue
        if result.get("sum_km", 0) == 0:
            print(f"[{result.get('city', team_id)}] sum_km=0 in final_results.json, skipping")
            continue
        ts = result["event_end"] + "T22:00:00Z"
        entry = {
            "timestamp":   ts,
            "team_id":     team_id,
            "sum_km":      float(result["sum_km"]),
            "rides":       int(result.get("rides", 0)),
            "riders":      int(result.get("riders", 0)),
            "km_per_head": float(result.get("km_per_head", 0.0)),
        }
        new_entries.append(entry)
        print(f"[{result.get('city', team_id)}] Seeded: {result['sum_km']} km")

    # --- Scrape active teams ---
    active_teams = [t for t in teams if t.get("status") not in ("finished", "no_team")]

    if active_teams:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ))
            page = context.new_page()

            for team in active_teams:
                city = team["city"]
                event_start = date.fromisoformat(team["event_start"])

                if today < event_start:
                    print(f"\n[{city}] Event starts {event_start} - skipping until then")
                    continue

                print(f"\n[{city}] Scraping '{team['team_name']}'...")
                result = scrape_team(page, team["city_slug"], team["team_name"])

                if result is not None:
                    entry = {"timestamp": timestamp, "team_id": team["id"], **result}
                    new_entries.append(entry)
                    print(f"  km={result['sum_km']}, rides={result['rides']}, riders={result['riders']}")
                else:
                    print(f"  -> Not found yet")

            browser.close()

    if new_entries:
        snapshots_data["snapshots"].extend(new_entries)
        snapshots_data["last_updated"] = timestamp
        save_snapshots(snapshots_data)
        print(f"\nAdded {len(new_entries)} entries at {timestamp}")
    else:
        print("\nNo new data - fill in final_results.json or wait for event start (June 15)")
        sys.exit(0)


if __name__ == "__main__":
    main()
