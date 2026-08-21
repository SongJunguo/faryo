import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const targetUrl = process.env.FARYO_GOAL_URL;
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";
if (!targetUrl) throw new Error("FARYO_GOAL_URL is required");

await withBrowser(
  { executablePath: chromeBin, viewport: { width: 390, height: 844 }, mobile: true },
  async ({ page }) => {
    const requests = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/goal")) requests.push(request.url());
    });
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.faryoAppReady === "1" &&
        !document.getElementById("goalPill")?.hidden,
      null,
      { timeout: 15_000 },
    );
    if (requests.length !== 0)
      throw new Error("Goal objective was fetched before an explicit click");
    await page.locator("#goalPill").click();
    await page.waitForFunction(
      () =>
        !document.getElementById("goalDetailsSection")?.hidden &&
        (document.getElementById("goalDetailsObjective")?.textContent || "").length > 0 &&
        document.getElementById("goalDetailsState")?.textContent !== "Loading…",
      null,
      { timeout: 10_000 },
    );
    const details = await page.evaluate(() => ({
      state: document.getElementById("goalDetailsState")?.textContent || "",
      objectiveChars: (document.getElementById("goalDetailsObjective")?.textContent || "").length,
      expanded: document.getElementById("goalPill")?.getAttribute("aria-expanded"),
      storedObjective: Object.keys(localStorage).some((key) => key.toLowerCase().includes("goal"))
        || Object.keys(sessionStorage).some((key) => key.toLowerCase().includes("goal")),
    }));
    if (
      requests.length !== 1 ||
      details.objectiveChars < 1 ||
      details.expanded !== "true" ||
      details.storedObjective
    ) {
      throw new Error(`Goal detail contract failed: ${JSON.stringify({ requests: requests.length, details })}`);
    }
    await page.locator("#detailsPanel [data-close-panel]").click();
    const cleared = await page.evaluate(() => ({
      hidden: document.getElementById("goalDetailsSection")?.hidden,
      objectiveChars: (document.getElementById("goalDetailsObjective")?.textContent || "").length,
      expanded: document.getElementById("goalPill")?.getAttribute("aria-expanded"),
    }));
    if (!cleared.hidden || cleared.objectiveChars !== 0 || cleared.expanded !== "false")
      throw new Error(`Goal details were retained after close: ${JSON.stringify(cleared)}`);
  },
);

console.log("faryo-owner-goal-details=PASS on-demand=yes storage=no clear-on-close=yes");
