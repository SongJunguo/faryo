import { readFile } from "node:fs/promises";
import path from "node:path";

import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const root = path.resolve(import.meta.dirname, "../../../..");
const bundle = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/owner-ui.js"),
  "utf8",
);
const styles = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/style.css"),
  "utf8",
);
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1280, height: 800 },
]) {
  await withBrowser(
    {
      executablePath: chromeBin,
      viewport,
      mobile: viewport.width < 720,
    },
    async ({ page }) => {
      await page.setContent('<div class="app"><div id="status"></div><div id="composer"></div></div><div id="root"></div>');
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: bundle });
      await page.evaluate(() => {
        window.__composerClicks = [];
        window.__goalClicks = 0;
        window.__statusController = window.FaryoOwnerUI.mountStatusShell(
          document.getElementById("status"),
          { onGoalClick() { window.__goalClicks += 1; } },
        );
        window.__statusController.update({
          contextText: "Ctx 42% · 108k/258k",
          contextTitle: "108,000 / 258,000 tokens",
          quotaText: "Week 58% left",
          quotaTitle: "Weekly quota",
          quotaPercent: 42,
          quotaWeekPercent: 51,
          modelText: "GPT Example",
          modelTitle: "gpt-example",
          subtitleTitle: "Synthetic status",
          goalVisible: true,
          goalText: "Goal Active",
          goalTitle: "Goal status · Active",
          goalTone: "active",
          gitText: "🌿 main",
          gitTitle: "Clean",
          gitState: "clean",
        });
        window.__composerController = window.FaryoOwnerUI.mountComposerShell(
          document.getElementById("composer"),
          { onSuggestionSelect(index) { window.__composerClicks.push(index); } },
        );
        window.__composerController.updateControls({ sendVisible: true, plusVisible: false });
        window.__composerController.updateSuggestions([
          {
            label: "<img src=x onerror=alert(1)>",
            hint: "",
            description: "Synthetic command",
            category: "Test",
            aliases: "",
            risk: "unclassified",
          },
        ], 0, "1 command");
        window.__interactionRequests = [];
        window.__interactionController = window.FaryoOwnerUI.mountInteractionHost(
          document.getElementById("root"),
          {
            async onRespond(request) {
              window.__interactionRequests.push(request);
              if (request.optionId === "opt-model-b") {
                return {
                  interaction: {
                    id: "ix-reasoning",
                    generation: 2,
                    kind: "reasoning_select",
                    title: "Select reasoning level",
                    prompt: "Choose reasoning.",
                    options: [
                      {
                        id: "opt-high",
                        label: "High",
                        description: "Greater reasoning depth",
                        selected: true,
                        current: false,
                        disabled: false,
                      },
                    ],
                    actions: ["previous", "next", "choose", "cancel"],
                    source: "codex-tui",
                    status: "pending",
                  },
                };
              }
              return { interaction: null, resolved: true };
            },
          },
        );
        window.__interactionController.update({
          id: "ix-model",
          generation: 1,
          kind: "model_select",
          title: "Select model",
          prompt: "Choose the model used by the next turn.",
          options: [
            {
              id: "opt-model-a",
              label: "<img src=x onerror=alert(1)>",
              description: "Current model",
              selected: true,
              current: true,
              disabled: false,
            },
            {
              id: "opt-model-b",
              label: "Model B",
              description: "Balanced model",
              selected: false,
              current: false,
              disabled: false,
            },
          ],
          actions: ["previous", "next", "choose", "cancel"],
          source: "codex-tui",
          status: "pending",
        });
      });
      await page.locator('.interaction-backdrop[data-interaction-kind="model_select"]').waitFor();
      const composer = await page.evaluate(() => ({
        prompt: Boolean(document.getElementById("promptInput")),
        sendVisible: !document.getElementById("sendBtn").classList.contains("hidden"),
        plusHidden: document.getElementById("dockPlusBtn").classList.contains("hidden"),
        suggestionCount: document.querySelectorAll("#commandSuggest [role=option]").length,
        injectedImage: Boolean(document.querySelector("#commandSuggest img")),
        status: {
          context: document.getElementById("ctxText")?.textContent || "",
          goal: document.getElementById("goalPill")?.textContent || "",
          git: document.getElementById("phasePill")?.textContent || "",
        },
      }));
      if (!composer.prompt || !composer.sendVisible || !composer.plusHidden
        || composer.suggestionCount !== 1 || composer.injectedImage
        || composer.status.context !== "Ctx 42% · 108k/258k"
        || composer.status.goal !== "Goal Active" || composer.status.git !== "🌿 main") {
        throw new Error(`Owner composer shell failed: ${JSON.stringify({ viewport, composer })}`);
      }
      await page.evaluate(() => document.getElementById("goalPill").click());
      if ((await page.evaluate(() => window.__goalClicks)) !== 1)
        throw new Error("Status Goal callback failed");
      await page.evaluate(() => document.querySelector("#commandSuggest [role=option]").click());
      if ((await page.evaluate(() => window.__composerClicks[0])) !== 0)
        throw new Error("Composer suggestion callback failed");
      const first = await page.evaluate(() => {
        const sheet = document.querySelector(".interaction-sheet");
        const rect = sheet.getBoundingClientRect();
        return {
          optionCount: document.querySelectorAll(".interaction-option").length,
          injectedImage: Boolean(document.querySelector(".interaction-option img")),
          horizontalOverflow:
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth + 1,
          sheetBottom: Math.round(rect.bottom),
          viewportBottom: innerHeight,
        };
      });
      if (
        first.optionCount !== 2 ||
        first.injectedImage ||
        first.horizontalOverflow ||
        first.sheetBottom > first.viewportBottom + 1
      ) {
        throw new Error(
          `Owner interaction baseline failed: ${JSON.stringify({ viewport, first })}`,
        );
      }
      await page.locator(".interaction-option").nth(1).click();
      await page.locator(
        '.interaction-backdrop[data-interaction-kind="reasoning_select"]',
      ).waitFor();
      const request = await page.evaluate(() => window.__interactionRequests[0]);
      if (
        request.interactionId !== "ix-model" ||
        request.optionId !== "opt-model-b"
      ) {
        throw new Error(`Option response mismatch: ${JSON.stringify(request)}`);
      }
      await page.waitForTimeout(60);
      await page.keyboard.press("Escape");
      await page.locator(".interaction-backdrop").waitFor({ state: "detached" });
      const finalRequest = await page.evaluate(
        () => window.__interactionRequests.at(-1),
      );
      if (
        finalRequest.interactionId !== "ix-reasoning" ||
        finalRequest.action !== "cancel"
      ) {
        throw new Error(
          `Keyboard cancel mismatch: ${JSON.stringify(finalRequest)}`,
        );
      }
      await page.evaluate(() => {
        window.__confirmResult = window.__interactionController.confirmCommand({
          command: "/future-command <img src=x onerror=alert(1)>",
          description: "Unclassified command",
          risk: "unclassified",
        });
      });
      await page.locator('[data-interaction-kind="command_confirm"]').waitFor();
      const confirmation = await page.evaluate(() => ({
        injectedImage: Boolean(document.querySelector(".interaction-confirm-sheet img")),
        command: document.querySelector(".interaction-confirm-command")?.textContent || "",
      }));
      if (confirmation.injectedImage || !confirmation.command.includes("<img"))
        throw new Error(`Command confirmation escaping failed: ${JSON.stringify(confirmation)}`);
      await page.locator(".interaction-confirm-sheet button").first().click();
      if (await page.evaluate(async () => await window.__confirmResult))
        throw new Error("Cancelled command confirmation resolved true");
    },
  );
}

console.log("faryo-owner-interaction-ui=PASS mobile=yes desktop=yes injection=text");
