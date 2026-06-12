#!/usr/bin/env python3
"""
Dry-run verification tool for the STADTRADELN scraper.

Usage:
  python scripts/verify_scraper.py <city-slug> "<Team Name>"

Examples:
  python scripts/verify_scraper.py frankfurt-am-main "Dataciders Frankfurt"
  python scripts/verify_scraper.py berlin "Dataciders Berlin"
  python scripts/verify_scraper.py nuernberg "Dataciders Nürnberg"

This script scrapes the leaderboard page and prints the full table headers,
the matched team row, and the extracted values — without modifying any data files.
Use it to verify team names and column mapping before the event starts.
"""

import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

STADTRADELN_BASE = "https://www.stadtradeln.de"


def parse_german_number(s: str) -> float:
    if not s or s.strip() in ("-", ""):
        return 0.0
    try:
        return float(s.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def verify(city_slug: str, team_name: str):
    url = f"{STADTRADELN_BASE}/{city_slug}"
    print(f"\n{'='*60}")
    print(f"Verifying:  {team_name}")
    print(f"URL:        {url}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        print(f"Loading page…")
        try:
            page.goto(url, timeout=30_000, wait_until="networkidle")
        except PlaywrightTimeoutError:
            print("✗ Timeout loading page")
            browser.close()
            return

        try:
            page.wait_for_selector("table", timeout=20_000)
            print("✓ Table found\n")
        except PlaywrightTimeoutError:
            print("✗ No table found on page — page may not have leaderboard yet")
            browser.close()
            return

        # Try to show all rows
        shown_all = False
        try:
            for sel in page.query_selector_all("select"):
                for opt in sel.query_selector_all("option"):
                    if (opt.text_content() or "").strip().lower() in ("alle", "all"):
                        sel.select_option(label=(opt.text_content() or "").strip())
                        page.wait_for_timeout(2_000)
                        shown_all = True
                        print('✓ Selected "alle" in dropdown\n')
                        break
        except Exception:
            pass

        if not shown_all:
            try:
                for selector in ("button", "a", "span", "li", "[role='option']"):
                    for el in page.query_selector_all(selector):
                        if (el.text_content() or "").strip().lower() == "alle":
                            el.click()
                            page.wait_for_timeout(2_000)
                            shown_all = True
                            print('✓ Clicked "alle" element\n')
                            break
            except Exception:
                pass

        if not shown_all:
            print('⚠ Could not trigger "alle" — only first visible rows will be searched\n')

        # Print headers
        header_cells = page.query_selector_all("table thead tr th") or \
                       page.query_selector_all("table tr:first-child th")
        headers = [(h.text_content() or "").strip() for h in header_cells]
        print(f"Table headers ({len(headers)} columns):")
        for i, h in enumerate(headers):
            print(f"  [{i}] {h!r}")

        # Detect column indices
        col_map = {"km": None, "rides": None, "riders": None, "km_per_head": None}
        for i, h in enumerate([hh.lower() for hh in headers]):
            if "km" in h and "kopf" not in h and "head" not in h and col_map["km"] is None:
                col_map["km"] = i
            if ("fahrt" in h or "ride" in h) and col_map["rides"] is None:
                col_map["rides"] = i
            if ("radeln" in h or "rider" in h or "teilnehm" in h) and col_map["riders"] is None:
                col_map["riders"] = i
            if ("kopf" in h or "head" in h) and col_map["km_per_head"] is None:
                col_map["km_per_head"] = i

        print(f"\nDetected column mapping: {col_map}")

        # Search for the team
        team_name_lower = team_name.lower()
        rows = page.query_selector_all("table tbody tr") or page.query_selector_all("table tr")
        print(f"\nSearching {len(rows)} rows for '{team_name}'…\n")

        found = False
        for row in rows:
            cells = row.query_selector_all("td")
            if not cells:
                continue
            texts = [(c.text_content() or "").strip() for c in cells]
            if team_name_lower in " ".join(texts).lower():
                found = True
                print(f"✓ MATCHED ROW:")
                for i, t in enumerate(texts):
                    print(f"  [{i}] {t!r}")

                def cell(idx):
                    if idx is not None and idx < len(texts):
                        return parse_german_number(texts[idx])
                    return 0.0

                print(f"\nExtracted values:")
                if col_map["km"] is not None:
                    print(f"  sum_km      = {cell(col_map['km'])}  (col {col_map['km']})")
                    print(f"  rides       = {int(cell(col_map['rides']))}  (col {col_map['rides']})")
                    print(f"  riders      = {int(cell(col_map['riders']))}  (col {col_map['riders']})")
                    print(f"  km_per_head = {cell(col_map['km_per_head'])}  (col {col_map['km_per_head']})")
                else:
                    nums = [parse_german_number(t) for t in texts
                            if parse_german_number(t) > 0 or t.strip() == "0"]
                    print(f"  (fallback mode — all numerics: {nums})")
                    if len(nums) >= 2:
                        print(f"  sum_km      = {nums[1]}  (index 1, skipping rank at index 0)")
                break

        if not found:
            print(f"✗ Team not found. Partial matches in visible rows:")
            for row in rows:
                cells = row.query_selector_all("td")
                texts = [(c.text_content() or "").strip() for c in cells]
                row_str = " | ".join(texts)
                if "datacider" in row_str.lower() or team_name.split()[0].lower() in row_str.lower():
                    print(f"  → {row_str[:120]}")

        browser.close()
        print(f"\n{'='*60}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    verify(sys.argv[1], sys.argv[2])
