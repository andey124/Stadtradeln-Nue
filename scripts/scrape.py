#!/usr/bin/env python3
"""
STADTRADELN scraper for Dataciders teams.
- Finished teams: seeded from docs/data/final_results.json (manual entry, no scraping)
- Active teams:   scraped via Playwright 2x daily once their event has started
"""

import json
import sys
from datetime import datetime, timezone, date
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

REPO_ROOT       = Path(__file__).parent.parent
TEAMS_FILE      = REPO_ROOT / "docs" / "data" / "teams.json"
SNAPSHOTS_FILE  = REPO_ROOT / "docs" / "data" / "snapshots.json"
FINAL_FILE      = REPO_ROOT / "docs" / "data" / "final_results.json"

STADTRADELN_BASE = "https://www.stadtradeln.de"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_german_number(s: str) -> float:
    """Parse German-formatted numbers like '1.234,5' -> 1234.5"""
    if not s or s.strip() in ("-", ""):
        return 0.0
    cleaned = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def load_data() -> tuple:
    with open(TEAMS_FILE, encoding="utf-8") as f:
        teams_data = json.load(f)
    with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
        snapshots_data = json.load(f)
    return teams_data["teams"], snapshots_data


def load_final_results() -> dict:
    """Load manually entered final results keyed by team_id."""
    if not FINAL_FILE.exists():
        return {}
    with open(FINAL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {r["team_id"]: r for r in data.get("results", [])}


def save_snapshots(snapshots_data: dict):
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshots_data, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(snapshots_data['snapshots'])} total snapshots")


# ---------------------------------------------------------------------------
# Scraping (active teams only)
# ---------------------------------------------------------------------------

def try_show_all_rows(page) -> None:
    """Try to expand the leaderboard table to show all teams."""
    # Strategy 1: <select> with an "alle" option
    try:
        for sel in page.query_selector_all("select"):
            for opt in sel.query_selector_all("option"):
                if (opt.text_content() or "").strip().lower() in ("alle", "all"):
                    sel.select_option(label=(opt.text_content() or "").strip())
                    page.wait_for_timeout(2_000)
                    return
    except Exception:
        pass

    # Strategy 2: any clickable element whose text is "alle"
    try:
        for selector in ("button", "a", "span", "li", "[role='option']"):
            for el in page.query_selector_all(selector):
                if (el.text_content() or "").strip().lower() == "alle":
                    el.click()
                    page.wait_for_timeout(2_000)
                    return
    except Exception:
        pass


def detect_columns(page) -> dict:
    """Read thead to map column keywords to 0-based indices."""
    col_map = {"km": None, "rides": None, "riders": None, "km_per_head": None}
    try:
        header_cells = page.query_selector_all("table thead tr th") or \
                       page.query_selector_all("table tr:first-child th")
        headers = [(h.text_content() or "").strip().lower() for h in header_cells]
        print(f"  Table headers: {headers}")
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
        print(f"  Could not read headers: {e}")
    return col_map


def extract_row_values(texts: list, col_map: dict):
    """Extract values using header-mapped indices, or positional fallback."""
    def cell(idx):
        if idx is not None and idx < len(texts):
            return parse_german_number(texts[idx])
        return 0.0

    if col_map["km"] is not None:
        return {
            "sum_km":      cell(col_map["km"]),
            "rides":       int(cell(col_map["rides"])),
            "riders":      int(cell(col_map["riders"])),
            "km_per_head": cell(col_map["km_per_head"]),
        }

    # Fallback: skip index 0 (rank column) and use remaining numerics
    numeric_vals = [parse_german_number(t) for t in texts
                    if parse_german_number(t) > 0 or t.strip() == "0"]
    if len(numeric_vals) >= 4:
        return {
            "sum_km":      numeric_vals[1],
            "rides":       int(numeric_vals[2]),
            "riders":      int(numeric_vals[3]),
            "km_per_head": numeric_vals[4] if len(numeric_vals) > 4 else 0.0,
        }
    if len(numeric_vals) >= 2:
        return {"sum_km": numeric_vals[1], "rides": 0, "riders": 0, "km_per_head": 0.0}
    return None


def scrape_team(page, city_slug: str, team_name: str):
    url = f"{STADTRADELN_BASE}/{city_slug}"
    print(f"  -> {url}")

    try:
        page.goto(url, timeout=30_000, wait_until="networkidle")
    except PlaywrightTimeoutError:
        print(f"  x Timeout")
        return None

    try:
        page.wait_for_selector("table", timeout=20_000)
    except PlaywrightTimeoutError:
        print(f"  x Table not found")
        return None

    try_show_all_rows(page)
    col_map = detect_columns(page)

    rows = page.query_selector_all("table tbody tr") or page.query_selector_all("table tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if not cells:
            continue
        texts = [(c.text_content() or "").strip() for c in cells]
        if team_name.lower() in " ".join(texts).lower():
            print(f"  + Matched: {texts}")
            return extract_row_values(texts, col_map)

    print(f"  x '{team_name}' not found in visible rows")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
            continue  # already seeded
        if result.get("sum_km", 0) == 0:
            print(f"[{result.get('city', team_id)}] sum_km is 0 in final_results.json - fill in the data first")
            continue
        # Use event_end date as the timestamp so charts position it correctly
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
        print(f"[{result.get('city', team_id)}] Seeded from manual data: {result['sum_km']} km")

    # --- Scrape active teams ---
    active_teams = [t for t in teams if t.get("status") != "finished"]

    if active_teams:
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
