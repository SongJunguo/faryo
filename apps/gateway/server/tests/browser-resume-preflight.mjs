import { readFile } from "node:fs/promises";

import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const targetUrl = process.env.FARYO_RESUME_URL;
const username = process.env.FARYO_RESUME_LOGIN_USER || "";
const passwordFile = process.env.FARYO_RESUME_LOGIN_PASSWORD_FILE || "";
const password = passwordFile ? (await readFile(passwordFile, "utf8")).trim() : "";
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";
if (!targetUrl || !username || !password)
  throw new Error("FARYO_RESUME_URL and login credentials are required");

await withBrowser(
  { executablePath: chromeBin, viewport: { width: 390, height: 844 }, mobile: true },
  async ({ page }) => {
    const resumeBodies = [];
    await page.route("**/api/agent/resume", async (route) => {
      const body = route.request().postDataJSON();
      resumeBodies.push(body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          resumeBodies.length === 1
            ? {
                ok: true,
                requiresWorkingDirectory: true,
                reason: "recorded-directory-unavailable",
                recordedDisplayCwd: "~/moved-project",
              }
            : { ok: true, session: "faryo99", redirect: "#resume-complete" },
        ),
      });
    });
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.locator('form[action="/login"]').evaluate((form) => form.requestSubmit());
    await page.waitForFunction(
      () => document.querySelectorAll("#sessionList .session-card").length >= 1,
      null,
      { timeout: 20_000 },
    );
    await page.locator("#sessionList .session-card").first().click();
    await page.waitForFunction(
      () =>
        document.getElementById("modal")?.classList.contains("directory-mode") &&
        document.getElementById("modalBody")?.textContent.includes("unavailable"),
      null,
      { timeout: 10_000 },
    );
    const picker = await page.evaluate(() => ({
      title: document.getElementById("modalTitle")?.textContent || "",
      hiddenToggle: Boolean(document.getElementById("directoryHiddenToggle")?.getClientRects().length),
      canSelect: [...document.querySelectorAll("#modalActions button")].some((button) =>
        button.textContent.includes("Start resumed Codex here"),
      ),
    }));
    if (picker.title !== "Choose working directory" || !picker.hiddenToggle || !picker.canSelect)
      throw new Error(`Resume directory picker failed: ${JSON.stringify(picker)}`);
    await page.evaluate(() =>
      [...document.querySelectorAll("#modalActions button")]
        .find((button) => button.textContent.includes("Start resumed Codex here"))
        ?.click(),
    );
    await page.waitForFunction(() => location.hash === "#resume-complete");
    if (
      resumeBodies.length !== 2 ||
      !resumeBodies[1].cwd ||
      !resumeBodies[1].cwd_token ||
      resumeBodies[1].agent_session_id !== resumeBodies[0].agent_session_id
    ) {
      throw new Error(`Resume retry payload failed: ${JSON.stringify(resumeBodies)}`);
    }
  },
);

console.log("faryo-gateway-resume-preflight=PASS missing-cwd=yes signed-retry=yes");
