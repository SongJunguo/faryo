import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const targetUrl = process.env.FARYO_INTERACTION_URL;
const gatewayCookie = process.env.FARYO_INTERACTION_COOKIE || "";
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const width = Number(process.env.FARYO_INTERACTION_WIDTH || 390);
const height = Number(process.env.FARYO_INTERACTION_HEIGHT || 844);
if (!targetUrl) throw new Error("FARYO_INTERACTION_URL is required");

await withBrowser(
  {
    executablePath: chromeBin,
    viewport: { width, height },
    mobile: width < 720,
    extraHTTPHeaders: gatewayCookie ? { Cookie: gatewayCookie } : {},
  },
  async ({ page }) => {
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.faryoAppReady === "1" &&
        document.documentElement.dataset.faryoInteractionUi === "preact" &&
        Boolean(document.getElementById("promptInput")),
      null,
      { timeout: 20_000 },
    );
    await page.waitForFunction(
      () => {
        const model = document.getElementById("modelText")?.textContent || "";
        return Boolean(model) && !/(connecting|loading)/i.test(model);
      },
      null,
      { timeout: 20_000 },
    );

    const baseline = await page.evaluate(() => ({
      catalog: document.documentElement.dataset.faryoCommandCatalog || "",
      composerRoot: Boolean(document.querySelector("#composerShellRoot #promptInput")),
      duplicatePrompt: document.querySelectorAll("#promptInput").length,
      horizontalOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    if (
      !baseline.composerRoot ||
      baseline.duplicatePrompt !== 1 ||
      baseline.horizontalOverflow
    ) {
      throw new Error(`Owner composer baseline failed: ${JSON.stringify(baseline)}`);
    }

    const prompt = page.locator("#promptInput");
    await prompt.fill("/model");
    await page.locator("#sendBtn").click();
    await page.waitForFunction(
      () =>
        Boolean(
          document.querySelector(
            '.interaction-backdrop[data-interaction-kind="model_select"]',
          ),
        ) ||
        Boolean(
          document.getElementById("errorBox")?.textContent &&
          !document.getElementById("errorBox")?.classList.contains("hidden"),
        ),
      null,
      { timeout: 10_000 },
    );
    const modelStartError = await page
      .locator("#errorBox")
      .evaluate((element) =>
        element.classList.contains("hidden") ? "" : element.textContent || "",
      );
    if (modelStartError)
      throw new Error(`Model interaction start failed: ${modelStartError}`);
    const model = await page.evaluate(() => ({
      options: document.querySelectorAll(".interaction-option").length,
      promptValue: document.getElementById("promptInput").value,
      fallbackKeysVisible: Boolean(
        document.querySelector(".key-nav")?.getClientRects().length,
      ),
      composerInert: Boolean(document.querySelector("footer")?.inert),
    }));
    if (
      model.options < 5 ||
      model.promptValue !== "" ||
      model.fallbackKeysVisible ||
      !model.composerInert
    ) {
      throw new Error(`Structured model interaction failed: ${JSON.stringify(model)}`);
    }
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.faryoAppReady === "1" &&
        document.querySelector('.interaction-backdrop[data-interaction-kind="model_select"]'),
      null,
      { timeout: 15_000 },
    );
    await page.locator(".interaction-cancel").click();
    await page.locator(".interaction-backdrop").waitFor({ state: "detached" });

    await prompt.fill("/usage");
    await page.locator("#sendBtn").click();
    await page
      .locator('.interaction-backdrop[data-interaction-kind="usage_select"]')
      .waitFor({ timeout: 10_000 });
    const usageOptions = await page.locator(".interaction-option").count();
    if (usageOptions !== 1)
      throw new Error(`Usage interaction has ${usageOptions} options`);
    await page.locator(".interaction-option").click();
    await page.locator(".interaction-backdrop").waitFor({ state: "detached" });

    const geometry = async () =>
      page.locator(".prompt-shell").evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
    const idle = await geometry();
    await prompt.focus();
    const focused = await geometry();
    await prompt.blur();
    await page.waitForTimeout(150);
    const blurred = await geometry();
    if (
      Math.abs(idle.width - focused.width) > 1 ||
      Math.abs(idle.height - focused.height) > 1 ||
      Math.abs(idle.width - blurred.width) > 1 ||
      Math.abs(idle.height - blurred.height) > 1
    ) {
      throw new Error(
        `Composer geometry changed: ${JSON.stringify({ idle, focused, blurred })}`,
      );
    }
  },
);

console.log(
  `faryo-owner-structured-interactions=PASS viewport=${width}x${height} model=yes usage=yes composer=preact`,
);
