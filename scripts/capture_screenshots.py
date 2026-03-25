"""Capture dashboard screenshots for README using Playwright.

Streamlit renders inside [data-testid="stMain"] with overflow:auto,
so full_page=True doesn't capture below-fold content. Fix: use JS to
expand all scroll containers, then full_page captures everything.
"""
from playwright.sync_api import sync_playwright
import time

URL = "http://localhost:8486"
DIR = "docs/screenshots"

EXPAND_JS = """() => {
    const main = document.querySelector('[data-testid="stMain"]');
    if (main) {
        main.style.overflow = 'visible';
        main.style.height = 'auto';
        main.style.maxHeight = 'none';
        main.style.position = 'relative';
    }
    let el = main;
    while (el && el !== document.body) {
        el.style.overflow = 'visible';
        el.style.height = 'auto';
        el.style.maxHeight = 'none';
        el = el.parentElement;
    }
    document.body.style.overflow = 'visible';
    document.body.style.height = 'auto';
    document.documentElement.style.overflow = 'visible';
    document.documentElement.style.height = 'auto';
}"""


def wait_for_streamlit(page):
    page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=30000)
    time.sleep(4)
    page.wait_for_load_state("networkidle")
    time.sleep(2)


def expand(page):
    page.evaluate(EXPAND_JS)
    time.sleep(1)


def click_tab(page, tab_name):
    tab = page.locator(f'button[role="tab"]:has-text("{tab_name}")')
    if tab.count() > 0:
        tab.click()
        time.sleep(4)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return True
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(URL, wait_until="networkidle", timeout=30000)
        wait_for_streamlit(page)
        expand(page)

        # 1. Hero section
        page.screenshot(
            path=f"{DIR}/01-score-overview.png",
            full_page=True,
            clip={"x": 0, "y": 0, "width": 1400, "height": 850},
        )
        print("01-score-overview.png")

        # 2. KPIs section
        page.screenshot(
            path=f"{DIR}/02-dimensions.png",
            full_page=True,
            clip={"x": 0, "y": 500, "width": 1400, "height": 550},
        )
        print("02-dimensions.png")

        # 3. Tab screenshots
        tabs = [
            ("Activity", "tab-activity.png"),
            ("Projects", "tab-projects.png"),
            ("Tools", "tab-tools.png"),
            ("Cost", "tab-cost.png"),
            ("Patterns", "tab-patterns.png"),
            ("Journey", "tab-journey.png"),
            ("Insights", "tab-insights.png"),
            ("Advanced", "tab-advanced.png"),
            ("Security", "tab-security.png"),
        ]

        # Find tab bar Y position
        first_tab = page.locator('button[role="tab"]').first
        tab_bar_y = 870
        if first_tab.count() > 0:
            box = first_tab.bounding_box()
            if box:
                tab_bar_y = box["y"] - 10

        for tab_name, filename in tabs:
            if click_tab(page, tab_name):
                expand(page)
                # Full page, then clip from tab bar downward
                page.screenshot(path=f"{DIR}/{filename}", full_page=True)
                print(f"{filename}")
            else:
                print(f"Tab '{tab_name}' not found")

        # Full dashboard
        click_tab(page, "Activity")
        expand(page)
        page.screenshot(path=f"{DIR}/full-dashboard.png", full_page=True)
        print("full-dashboard.png")

        browser.close()
        print("Done!")


if __name__ == "__main__":
    main()
