#!/usr/bin/env python3
"""
STADTRADELN scraper for Dataciders teams.
Uses Playwright to scrape leaderboard data for each configured team.
Appends timestamped snapshots to data/snapshots.json.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

REPO_ROOT = Path(__file__).parent.parent
TEAMS_FILE = REPO_ROOT / "docs" / "data" / "teams.json"
SNAPSHOTS_FILE = REPO_ROOT / "docs" / "data" / "snapshots.json"

STADTRADELN_BASE = "https://www.stadtradeln.de"

# Mapping of german number formatting (1.234,5 -> 1234.5)
def parse_german_number(s: str) -> float:
    if not s or s.strip() == "-":
        return 0.0
    cleaned = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def scrape_team(page, city_slug: str, team_name: str) -> dict | None:
    """
    Navigate to the city leaderboard and find the team row.
    Returns a dict with sum_km, rides, riders, km_per_head or None if not found.
    """
    url = f"{STADTRADELN_BASE}/{city_slug}"
    print(f"  → Visiting {url}")

    try:
        page.goto(url, timeout=30_000, wait_until="networkidle")
    except PlaywrightTimeoutError:
        print(f"  ✗ Timeout loading {url}")
        return None

    # Wait for the team table to appear and click "alle" to show all entries
    try:
        # Look for a "show all" selector (e.g. dropdown or button labelled "alle")
        # The table is rendered by a Vue app — wait for it
        page.wait_for_selector("table", timeout=15_000)
    except PlaywrightTimeoutError:
        print(f"  ✗ Table not found on {url}")
        return None

    # Try to expand the table to show all rows (select "alle" in per-page dropdown)
    try:
        # Common pattern: a <select> with option "alle" or a button
        selects = page.query_selector_all("select")
        for sel in selects:
            options = sel.query_selector_all("option")
            for opt in options:
                text = (opt.text_content() or "").strip().lower()
                if text in ("alle", "all"):
                    sel.select_option(label=opt.text_content().strip())
                    page.wait_for_load_state("networkidle", timeout=10_000)
                    break
    except Exception:
        pass  # If no "alle" option, proceed with what's visible

    # Search for the team row in the table
    rows = page.query_selector_all("table tbody tr")
    if not rows:
        # Try alternate table structure
        rows = page.query_selector_all("tr")

    team_name_lower = team_name.lower()
    for row in rows:
        cells = row.query_selector_all("td")
        if not cells:
            continue
        row_text = " ".join((c.text_content() or "").strip() for c in cells)
        # Check if this row contains our team name (case-insensitive, partial match)
        if team_name_lower in row_text.lower():
            texts = [(c.text_content() or "").strip() for c in cells]
            print(f"  ✓ Found row: {texts}")
            # Typical columns: rank, team, sum_km, rides, riders, km_per_head
            # Try to identify columns by position (usually: rank|team|km|rides|riders|km_head)
            # We try to extract numeric values robustly
            numbers = []
            team_col_idx = -1
            for i, t in enumerate(texts):
                if team_name_lower in t.lower():
                    team_col_idx = i
                else:
                    v = parse_german_number(t)
                    if v > 0 or t == "0":
                        numbers.append((i, v))

            if len(numbers) >= 4:
                # Usually ordered: km, rides, riders, km_per_head
                return {
                    "sum_km": numbers[0][1],
                    "rides": int(numbers[1][1]),
                    "riders": int(numbers[2][1]),
                    "km_per_head": numbers[3][1],
                }
            elif len(numbers) >= 1:
                return {"sum_km": numbers[0][1], "rides": 0, "riders": 0, "km_per_head": 0.0}

    print(f"  ✗ Team '{team_name}' not found in leaderboard (may not have started yet)")
    return None


def load_data() -> tuple[list, dict]:
    with open(TEAMS_FILE, encoding="utf-8") as f:
        teams_data = json.load(f)
    with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
        snapshots_data = json.load(f)
    return teams_data["teams"], snapshots_data


def save_snapshots(snapshots_data: dict):
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots_data, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Saved {len(snapshots_data['snapshots'])} total snapshots")


def main():
    teams, snapshots_data = load_data()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for team in teams:
            print(f"\n[{team['city']}] Scraping {team['team_name']}...")
            result = scrape_team(page, team["city_slug"], team["team_name"])

            if result is not None:
                entry = {
                    "timestamp": timestamp,
                    "team_id": team["id"],
                    **result,
                }
                new_entries.append(entry)
                print(
                    f"  km={result['sum_km']}, rides={result['rides']}, "
                    f"riders={result['riders']}, km/head={result['km_per_head']}"
                )
            else:
                print(f"  → Skipped (no data)")

        browser.close()

    if new_entries:
        snapshots_data["snapshots"].extend(new_entries)
        snapshots_data["last_updated"] = timestamp
        save_snapshots(snapshots_data)
        print(f"✓ Added {len(new_entries)} new entries at {timestamp}")
    else:
        print("⚠ No new data collected")
        sys.exit(1)


if __name__ == "__main__":
    main()
