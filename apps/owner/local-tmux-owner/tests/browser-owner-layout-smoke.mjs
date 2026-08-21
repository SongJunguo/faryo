import { readFile } from "node:fs/promises";
import path from "node:path";

import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const root = path.resolve(import.meta.dirname, "../../../..");
const styles = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/style.css"),
  "utf8",
);
const keyboardLayoutSource = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/keyboard-layout.js"),
  "utf8",
);

await withBrowser(
  {
    viewport: { width: 320, height: 720 },
    mobile: true,
  },
  async ({ page }) => {
    await page.setContent(`
      <meta name="viewport" content="width=device-width, initial-scale=1, interactive-widget=resizes-content" />
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
      <div class="app header-collapsed">
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
    await page.evaluate(() => {
      const keyboard = new EventTarget();
      keyboard.overlaysContent = true;
      keyboard.boundingRect = { height: 240 };
      Object.defineProperty(navigator, "virtualKeyboard", {
        configurable: true,
        value: keyboard,
      });
      window.__faryoBrowserKeyboard = keyboard;
    });
    await page.addScriptTag({ content: keyboardLayoutSource });

    const keyboardController = await page.evaluate(async () => {
      const keyboard = window.__faryoBrowserKeyboard;
      const controller =
        window.FaryoKeyboardLayout.createKeyboardLayout(window);
      const initial = controller.getSnapshot();
      window.dispatchEvent(new Event("resize"));
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const resized = controller.getSnapshot();
      const active = {
        overlay: keyboard.overlaysContent,
        viewport: document
          .querySelector('meta[name="viewport"]')
          ?.getAttribute("content"),
        mode: document.documentElement.dataset.faryoKeyboardLayout,
        open: document.documentElement.dataset.faryoKeyboardOpen,
        classActive: document.documentElement.classList.contains(
          "virtual-keyboard-layout",
        ),
      };
      controller.destroy();
      return {
        initial,
        resized,
        active,
        finalOverlay: keyboard.overlaysContent,
        finalViewport: document
          .querySelector('meta[name="viewport"]')
          ?.getAttribute("content"),
        cleaned:
          !document.documentElement.classList.contains(
            "virtual-keyboard-layout",
          ) && !("faryoKeyboardLayout" in document.documentElement.dataset),
      };
    });
    if (
      keyboardController.initial.mode !== "viewport-resize" ||
      keyboardController.initial.visible ||
      keyboardController.initial.insetHeight !== 0 ||
      !keyboardController.resized.changed ||
      keyboardController.active.overlay ||
      !keyboardController.active.viewport?.includes(
        "interactive-widget=resizes-content",
      ) ||
      keyboardController.active.mode !== "viewport-resize" ||
      keyboardController.active.open !== "0" ||
      keyboardController.active.classActive ||
      keyboardController.finalOverlay ||
      !keyboardController.finalViewport?.includes(
        "interactive-widget=resizes-content",
      ) ||
      !keyboardController.cleaned
    ) {
      throw new Error(
        `Viewport-resize keyboard controller failed: ${JSON.stringify(keyboardController)}`,
      );
    }

    const viewportContract = await page
      .locator('meta[name="viewport"]')
      .getAttribute("content");
    if (!viewportContract?.includes("interactive-widget=resizes-content")) {
      throw new Error(
        `Mobile keyboard viewport contract is missing: ${viewportContract || ""}`,
      );
    }

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
        geometry.ownerRight > geometry.titleRight - geometry.paddingRight + 0.5
      ) {
        throw new Error(
          `Collapsed owner label escaped its safe area: ${JSON.stringify({ fixture, geometry })}`,
        );
      }
    }

    const appShell = async () =>
      page.evaluate(() => {
        const app = document.querySelector(".app").getBoundingClientRect();
        const main = document.querySelector("main");
        const footer = document.querySelector("footer").getBoundingClientRect();
        return {
          appHeight: app.height,
          mainHeight: main.getBoundingClientRect().height,
          mainPaddingBottom: Number.parseFloat(
            getComputedStyle(main).paddingBottom,
          ),
          mainOverflow: getComputedStyle(main).overflowY,
          mainOverflowAnchor: getComputedStyle(main).overflowAnchor,
          footerPosition: getComputedStyle(document.querySelector("footer"))
            .position,
          footerBottom: footer.bottom,
          innerHeight,
          documentOverflow:
            (document.scrollingElement || document.documentElement)
              .scrollHeight >
            innerHeight + 1,
        };
      });
    const keyboardClosed = await appShell();
    await page.setViewportSize({ width: 320, height: 480 });
    const keyboardOpen = await appShell();
    if (
      keyboardClosed.mainOverflow !== "auto" ||
      keyboardClosed.mainOverflowAnchor !== "none" ||
      keyboardClosed.footerPosition !== "relative" ||
      keyboardClosed.documentOverflow ||
      keyboardOpen.documentOverflow ||
      keyboardClosed.mainPaddingBottom > 40 ||
      Math.abs(keyboardClosed.mainHeight - keyboardOpen.mainHeight - 240) > 1 ||
      Math.abs(keyboardClosed.footerBottom - keyboardOpen.footerBottom - 240) >
        1 ||
      Math.abs(keyboardClosed.footerBottom - keyboardClosed.innerHeight) > 1 ||
      Math.abs(keyboardOpen.footerBottom - keyboardOpen.innerHeight) > 1
    ) {
      throw new Error(
        `Keyboard app shell violated its grid contract: ${JSON.stringify({ keyboardClosed, keyboardOpen })}`,
      );
    }
  },
);

console.log(
  "faryo-owner-layout=PASS collapsed-label=safe keyboard-app-shell=viewport-resize",
);
