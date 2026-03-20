"""Take dashboard screenshots using Playwright against the mock DB."""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8487"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}


def wait_for_charts(page, seconds: float = 3.0) -> None:
    time.sleep(seconds)


def click_tab(page, tab_name: str) -> None:
    tab = page.locator(f'button[role="tab"]:has-text("{tab_name}")')
    tab.click()
    wait_for_charts(page)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            color_scheme="dark",
        )
        page = context.new_page()

        print(f"Navigating to {BASE}...")
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        wait_for_charts(page, 5)

        # 1. Score Overview
        print("Capturing: 01-score-overview.png")
        page.screenshot(
            path=str(OUT / "01-score-overview.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 700},
        )

        # 2. Dimensions — scroll to see them
        print("Capturing: 02-dimensions.png")
        expander = page.locator("text=Project Scores")
        if expander.is_visible():
            expander.click()
            time.sleep(0.5)
        page.evaluate("window.scrollBy(0, 550)")
        time.sleep(0.5)
        page.screenshot(
            path=str(OUT / "02-dimensions.png"),
            clip={"x": 0, "y": 0, "width": 1440, "height": 900},
        )

        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)

        # 3. Activity tab
        print("Capturing: tab-activity.png")
        click_tab(page, "Activity")
        page.screenshot(path=str(OUT / "tab-activity.png"), full_page=False)

        # 4. Projects tab
        print("Capturing: tab-projects.png")
        click_tab(page, "Projects")
        page.screenshot(path=str(OUT / "tab-projects.png"), full_page=False)

        # 5. Tools tab
        print("Capturing: tab-tools.png")
        click_tab(page, "Tools")
        page.screenshot(path=str(OUT / "tab-tools.png"), full_page=False)

        # 6. Cost tab
        print("Capturing: tab-cost.png")
        click_tab(page, "Cost")
        page.screenshot(path=str(OUT / "tab-cost.png"), full_page=False)

        # 7. Patterns tab
        print("Capturing: tab-patterns.png")
        click_tab(page, "Patterns")
        page.screenshot(path=str(OUT / "tab-patterns.png"), full_page=False)

        # 8. Journey tab
        print("Capturing: tab-journey.png")
        click_tab(page, "Journey")
        page.screenshot(path=str(OUT / "tab-journey.png"), full_page=False)

        # 9. Insights tab
        print("Capturing: tab-insights.png")
        click_tab(page, "Insights")
        page.screenshot(path=str(OUT / "tab-insights.png"), full_page=False)

        # 10. Full dashboard
        print("Capturing: full-dashboard.png")
        click_tab(page, "Activity")
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        page.screenshot(path=str(OUT / "full-dashboard.png"), full_page=True)

        browser.close()
        print(f"\nDone! Screenshots saved to {OUT}")


if __name__ == "__main__":
    run()
