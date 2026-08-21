import { readFile } from "node:fs/promises";
import path from "node:path";

import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const root = path.resolve(import.meta.dirname, "../../../..");
const styles = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/style.css"),
  "utf8",
);

await withBrowser(
  {
    viewport: { width: 320, height: 720 },
    mobile: true,
  },
  async ({ page }) => {
    await page.setContent(`
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        :root {
          --font-step: 0px;
          --bg: #0f1115;
          --text: #f3f4f6;
          --muted: #a6acb8;
          --line: #30343d;
          --plan-bg: #1a1e26;
          --header-bg: #0f1115;
          --app-font: sans-serif;
        }
      </style>
      <div class="app">
        <header class="collapsed">
          <div class="title-row">
            <div>
              <strong id="sessionTitle" class="brand-title">
                <a class="brand-home"><img class="brand-logo" alt="" /></a>
                <span id="ownerText">NODE5</span>
                <span id="topicText">Synthetic session</span>
              </strong>
            </div>
          </div>
        </header>
        <main></main>
        <footer><div class="composer"><div class="prompt-shell"></div></div></footer>
      </div>
    `);
    await page.addStyleTag({ content: styles });

    for (const fixture of [
      { label: "NODE5", fontStep: "0px" },
      { label: "WORKSTATION12", fontStep: "4px" },
    ]) {
      const geometry = await page.evaluate(({ label, fontStep }) => {
        document.documentElement.style.setProperty("--font-step", fontStep);
        document.getElementById("ownerText").textContent = label;
        const title = document.getElementById("sessionTitle");
        const owner = document.getElementById("ownerText");
        const titleRect = title.getBoundingClientRect();
        const ownerRect = owner.getBoundingClientRect();
        const style = getComputedStyle(title);
        return {
          titleLeft: titleRect.left,
          titleRight: titleRect.right,
          titleWidth: titleRect.width,
          ownerRight: ownerRect.right,
          paddingRight: Number.parseFloat(style.paddingRight),
          horizontalOverflow:
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth + 1,
        };
      }, fixture);
      if (
        geometry.horizontalOverflow ||
        geometry.titleLeft < 7 ||
        geometry.titleRight > 313 ||
        geometry.titleWidth > 133 ||
        geometry.ownerRight >
          geometry.titleRight - geometry.paddingRight + 0.5
      ) {
        throw new Error(
          `Collapsed owner label escaped its safe area: ${JSON.stringify({ fixture, geometry })}`,
        );
      }
    }

    const keyboardLayout = await page.evaluate(() => {
      document.documentElement.classList.add(
        "document-scroll-mode",
        "keyboard-open",
      );
      document.documentElement.style.setProperty(
        "--faryo-visual-viewport-obscured-bottom",
        "264px",
      );
      return {
        mainPaddingBottom: Number.parseFloat(
          getComputedStyle(document.querySelector("main")).paddingBottom,
        ),
      };
    });
    if (keyboardLayout.mainPaddingBottom < 391) {
      throw new Error(
        `Keyboard reserve did not reach the conversation surface: ${JSON.stringify(keyboardLayout)}`,
      );
    }
  },
);

console.log(
  "faryo-owner-layout=PASS collapsed-label=safe mobile-keyboard-reserve=shared",
);
