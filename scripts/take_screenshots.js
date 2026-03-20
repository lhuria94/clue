/**
 * Take dashboard screenshots using Playwright against the mock DB.
 *
 * Usage:
 *   CLUE_DB_PATH=./mock_clue.db PORT=8487 .venv/bin/streamlit run src/clue/dashboard/app.py --server.port 8487
 *   npx playwright test scripts/take_screenshots.js
 *
 * Or run via: node scripts/take_screenshots.js
 */

const { chromium } = require('playwright');
const path = require('path');

const BASE = process.env.CLUE_URL || 'http://localhost:8487';
const OUT = path.join(__dirname, '..', 'docs', 'screenshots');
const VIEWPORT = { width: 1440, height: 900 };

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function waitForPlotly(page) {
  // Wait for Plotly charts to render
  await sleep(3000);
  // Also wait for any Streamlit spinners to disappear
  try {
    await page.waitForSelector('[data-testid="stSpinner"]', { state: 'hidden', timeout: 10000 });
  } catch {
    // No spinner, that's fine
  }
}

async function clickTab(page, tabName) {
  const tab = page.locator(`button[role="tab"]:has-text("${tabName}")`);
  await tab.click();
  await waitForPlotly(page);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    colorScheme: 'dark',
  });
  const page = await context.newPage();

  console.log(`Navigating to ${BASE}...`);
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 });
  await waitForPlotly(page);

  // 1. Score Overview — top section with gauge + KPIs
  console.log('Capturing: 01-score-overview.png');
  await page.screenshot({
    path: path.join(OUT, '01-score-overview.png'),
    clip: { x: 0, y: 0, width: 1440, height: 700 },
  });

  // 2. Dimensions — scroll down to see dimension scores
  console.log('Capturing: 02-dimensions.png');
  // Click the Project Scores expander if visible
  const expander = page.locator('text=Project Scores');
  if (await expander.isVisible()) {
    await expander.click();
    await sleep(500);
  }
  await page.evaluate(() => window.scrollBy(0, 550));
  await sleep(500);
  await page.screenshot({
    path: path.join(OUT, '02-dimensions.png'),
    clip: { x: 0, y: 0, width: 1440, height: 900 },
  });

  // Scroll back to top for tabs
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(300);

  // 3. Activity tab
  console.log('Capturing: tab-activity.png');
  await clickTab(page, 'Activity');
  await page.screenshot({
    path: path.join(OUT, 'tab-activity.png'),
    fullPage: false,
  });

  // 4. Projects tab
  console.log('Capturing: tab-projects.png');
  await clickTab(page, 'Projects');
  await page.screenshot({
    path: path.join(OUT, 'tab-projects.png'),
    fullPage: false,
  });

  // 5. Tools tab
  console.log('Capturing: tab-tools.png');
  await clickTab(page, 'Tools');
  await page.screenshot({
    path: path.join(OUT, 'tab-tools.png'),
    fullPage: false,
  });

  // 6. Cost tab
  console.log('Capturing: tab-cost.png');
  await clickTab(page, 'Cost');
  await page.screenshot({
    path: path.join(OUT, 'tab-cost.png'),
    fullPage: false,
  });

  // 7. Patterns tab
  console.log('Capturing: tab-patterns.png');
  await clickTab(page, 'Patterns');
  await page.screenshot({
    path: path.join(OUT, 'tab-patterns.png'),
    fullPage: false,
  });

  // 8. Journey tab
  console.log('Capturing: tab-journey.png');
  await clickTab(page, 'Journey');
  await page.screenshot({
    path: path.join(OUT, 'tab-journey.png'),
    fullPage: false,
  });

  // 9. Insights tab
  console.log('Capturing: tab-insights.png');
  await clickTab(page, 'Insights');
  await page.screenshot({
    path: path.join(OUT, 'tab-insights.png'),
    fullPage: false,
  });

  // 10. Full dashboard (scroll back up, Activity tab)
  console.log('Capturing: full-dashboard.png');
  await clickTab(page, 'Activity');
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(500);
  await page.screenshot({
    path: path.join(OUT, 'full-dashboard.png'),
    fullPage: true,
  });

  await browser.close();
  console.log(`\nDone! Screenshots saved to ${OUT}`);
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});
