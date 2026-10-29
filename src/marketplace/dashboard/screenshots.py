"""Render the dashboard in headless Chrome, screenshot every page, and verify it works.

Fails (exit 1) on any JS console error / page error, on an empty chart container, or if
changing a filter does not change the KPI values (acceptance E3/E4).

Uses Playwright with the locally installed Google Chrome (channel="chrome"), so no browser
download is needed; set PLAYWRIGHT_CHANNEL="" to use Playwright's bundled Chromium instead.

Run: python -m marketplace.dashboard.screenshots
"""

from __future__ import annotations

import json
import os
import sys

from playwright.sync_api import sync_playwright

from marketplace.paths import DASHBOARD_DIR, IMG, REPORTS

PAGES = ["exec", "growth", "customers", "delivery", "sellers", "rca"]


def main() -> int:
    IMG.mkdir(parents=True, exist_ok=True)
    url = (DASHBOARD_DIR / "index.html").resolve().as_uri()
    errors: list[str] = []
    result = {"pages": {}, "filter_test": {}}
    channel = os.environ.get("PLAYWRIGHT_CHANNEL", "chrome") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page.on(
            "console",
            lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(url + "#exec")
        page.wait_for_function("window.__ready === true", timeout=30000)
        for pid in PAGES:
            page.evaluate(f"location.hash = '{pid}'")
            page.wait_for_timeout(1200)
            empty = page.evaluate(
                f"""Array.from(document.querySelectorAll('#page-{pid} .chart'))
                     .filter(el => !el.querySelector('.main-svg')).map(el => el.id)"""
            )
            n_charts = page.evaluate(f"document.querySelectorAll('#page-{pid} .chart').length")
            if empty:
                errors.append(f"{pid}: empty charts {empty}")
            path = IMG / f"dashboard_{pid}.png"
            page.screenshot(path=str(path), full_page=True)
            result["pages"][pid] = {
                "charts": n_charts,
                "empty": empty,
                "screenshot": str(path.name),
            }
        # Filter test: KPI texts must change when a state filter is applied.
        page.evaluate("location.hash = 'exec'")
        page.wait_for_timeout(500)
        before = page.inner_text("#kpis")
        page.evaluate("window.__setFilters({state: 'RJ'})")
        page.wait_for_timeout(500)
        after_rj = page.inner_text("#kpis")
        page.screenshot(path=str(IMG / "dashboard_exec_filtered_RJ.png"), full_page=True)
        page.evaluate("window.__setFilters({state: 'ALL', cat: 'health_beauty', from: 12, to: 19})")
        page.wait_for_timeout(500)
        after_cat = page.inner_text("#kpis")
        changed = before != after_rj and before != after_cat
        result["filter_test"] = {
            "kpis_changed_with_state_filter": before != after_rj,
            "kpis_changed_with_category_and_date_filter": before != after_cat,
            "gmv_card_all": before.split("\n")[1],
            "gmv_card_RJ": after_rj.split("\n")[1],
        }
        if not changed:
            errors.append("filters did not change KPI values")
        browser.close()
    result["errors"] = errors
    (REPORTS / "dashboard_check.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
