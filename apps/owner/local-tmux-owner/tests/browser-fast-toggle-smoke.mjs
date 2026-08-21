import { readFile } from "node:fs/promises";

import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const targetUrl = process.env.FARYO_SMOKE_URL;
const sessionA = process.env.FARYO_SMOKE_SESSION_A || "";
const sessionB = process.env.FARYO_SMOKE_SESSION_B || "";
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || "";
const passwordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || "";
const loginPassword = passwordFile
  ? (await readFile(passwordFile, "utf8")).trim()
  : "";
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";

if (!targetUrl || !sessionA || !sessionB || sessionA === sessionB)
  throw new Error("FARYO_SMOKE_URL and two distinct sessions are required");

await withBrowser(
  {
    executablePath: chromeBin,
    viewport: { width: 390, height: 844 },
    mobile: true,
  },
  async ({ context, page: firstPage }) => {
    const speed = new Map([
      [sessionA, "off"],
      [sessionB, "off"],
    ]);
    const commands = [];
    const emptyCapture = {
      ok: true,
      text: "",
      captureSource: "codex-app-server",
      agentSource: "codex-cli",
      agentProfile: "codex",
      agentRunning: false,
      queuedSendNowAvailable: false,
      sessionId: "anonymous-fast-toggle-thread",
      updatedAt: "2026-01-01T00:00:00Z",
    };

    const attachRoutes = async (page) => {
      await page.route("**/api/status**", async (route) => {
        const session = new URL(route.request().url()).searchParams.get("session") || "";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            tmuxAlive: true,
            targetAlive: true,
            session,
            ownerLabel: "Workstation",
            displayCwd: "~/workspace",
            model: "gpt-5.6-sol max",
            reasoningEffort: "max",
            fastStatus: speed.get(session) || "off",
            gitStatus: { available: false },
            sessionTitle: "Anonymous session",
            sessionId: `anonymous-${session}`,
            contextUsage: null,
            goalStatus: null,
            interaction: null,
            interactionRevision: "none",
            weeklyRateLimit: null,
            agentRunning: false,
            agentState: "waiting",
            queuedSendNowAvailable: false,
            agentSource: "codex-cli",
            agentProfile: "codex",
            updatedAt: "2026-01-01T00:00:00Z",
          }),
        });
      });
      await page.route("**/api/interaction/start", async (route) => {
        const body = route.request().postDataJSON();
        commands.push(body);
        const session = String(body?.session || "");
        if (body?.command === "/fast" && speed.has(session))
          speed.set(session, speed.get(session) === "on" ? "off" : "on");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            command: "/fast",
            behavior: "local_action",
            commandState: "completed",
            interaction: null,
            interactionRevision: "none",
            changed: true,
          }),
        });
      });
      await page.route("**/api/capture**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(emptyCapture),
        }),
      );
      await page.route("**/api/events**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `event: capture\ndata: ${JSON.stringify(emptyCapture)}\n\n`,
        }),
      );
    };

    const openSession = async (page, session) => {
      await attachRoutes(page);
      const url = new URL(targetUrl);
      url.searchParams.set("session", session);
      await page.goto(url.toString(), { waitUntil: "domcontentloaded" });
      if (loginUser && loginPassword) {
        const username = page.locator('input[name="username"]');
        if (await username.count()) {
          await username.fill(loginUser);
          await page.locator('input[name="password"]').fill(loginPassword);
          await page.locator("form").evaluate((form) => form.requestSubmit());
        }
      }
      await page.waitForFunction(
        () =>
          document.documentElement.dataset.faryoAppReady === "1" &&
          !document.getElementById("fastToggle")?.hidden &&
          !document.getElementById("fastToggle")?.disabled,
        null,
        { timeout: 25_000 },
      );
    };

    await openSession(firstPage, sessionA);
    const secondPage = await context.newPage();
    try {
      await openSession(secondPage, sessionB);
      await firstPage.reload({ waitUntil: "domcontentloaded" });
      await firstPage.waitForFunction(
        () =>
          document.documentElement.dataset.faryoAppReady === "1" &&
          document.getElementById("fastToggle")?.textContent?.trim() ===
            "Default" &&
          !document.getElementById("fastToggle")?.disabled,
        null,
        { timeout: 25_000 },
      );
      await firstPage.locator("#promptInput").fill("unsent draft A");
      await secondPage.locator("#promptInput").fill("unsent draft B");

      await firstPage.locator("#fastToggle").click();
      await firstPage.waitForFunction(
        () =>
          document.getElementById("fastToggle")?.getAttribute("aria-pressed") ===
          "true",
      );
      const isolated = {
        first: await firstPage.locator("#fastToggle").textContent(),
        second: await secondPage.locator("#fastToggle").textContent(),
        draftA: await firstPage.locator("#promptInput").inputValue(),
        draftB: await secondPage.locator("#promptInput").inputValue(),
      };
      if (
        isolated.first?.trim() !== "Fast" ||
        isolated.second?.trim() !== "Default" ||
        isolated.draftA !== "unsent draft A" ||
        isolated.draftB !== "unsent draft B" ||
        commands.length !== 1 ||
        commands[0]?.command !== "/fast" ||
        commands[0]?.session !== sessionA
      ) {
        throw new Error(
          `Per-session Fast toggle was not isolated: ${JSON.stringify(isolated)}`,
        );
      }

      await firstPage.locator("#fastToggle").click();
      await firstPage.waitForFunction(
        () =>
          document.getElementById("fastToggle")?.getAttribute("aria-pressed") ===
          "false",
      );
      if (
        commands.length !== 2 ||
        commands[1]?.session !== sessionA ||
        speed.get(sessionA) !== "off" ||
        speed.get(sessionB) !== "off"
      ) {
        throw new Error("Fast toggle did not restore its original session state");
      }
    } finally {
      await secondPage.close();
    }

    console.log(
      "faryo-browser-fast-toggle=PASS per-session=isolated drafts=preserved command=/fast ordinary-reload=yes",
    );
  },
);
