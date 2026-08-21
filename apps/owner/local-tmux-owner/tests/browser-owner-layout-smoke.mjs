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
const composerLayoutSource = await readFile(
  path.join(root, "apps/owner/local-tmux-owner/static/composer-layout.js"),
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
        <main><div id="scrollFixture" style="height: 1000px; display: flex; align-items: flex-end"><span id="lastMessage">Latest message</span></div></main>
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
    await page.addScriptTag({ content: composerLayoutSource });

    const composerController = await page.evaluate(() => {
      const main = document.querySelector("main");
      window.__faryoTailPinned = true;
      const controller = window.FaryoComposerLayout.createComposerLayout(
        window,
        {
          isTailPinned: () => window.__faryoTailPinned,
          onChange: ({ tailPinned }) => {
            if (tailPinned)
              requestAnimationFrame(() => {
                main.scrollTop = main.scrollHeight;
              });
          },
        },
      );
      window.__faryoComposerController = controller;
      return {
        snapshot: controller.getSnapshot(),
        mode: document.documentElement.dataset.faryoComposerLayout,
      };
    });
    if (
      composerController.snapshot.height <= 0 ||
      composerController.mode !== "transparent-overlay"
    ) {
      throw new Error(
        `Transparent composer controller failed: ${JSON.stringify(composerController)}`,
      );
    }

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
        const footerElement = document.querySelector("footer");
        const footer = footerElement.getBoundingClientRect();
        main.scrollTop = main.scrollHeight;
        const lastMessage = document
          .getElementById("lastMessage")
          .getBoundingClientRect();
        return {
          appHeight: app.height,
          appLeft: app.left,
          appRight: app.right,
          mainHeight: main.getBoundingClientRect().height,
          mainLeft: main.getBoundingClientRect().left,
          mainRight: main.getBoundingClientRect().right,
          mainBottom: main.getBoundingClientRect().bottom,
          mainPaddingBottom: Number.parseFloat(
            getComputedStyle(main).paddingBottom,
          ),
          mainOverflow: getComputedStyle(main).overflowY,
          mainOverflowAnchor: getComputedStyle(main).overflowAnchor,
          footerPosition: getComputedStyle(footerElement).position,
          footerBackground: getComputedStyle(footerElement).backgroundColor,
          footerHeight: footer.height,
          footerLeft: footer.left,
          footerRight: footer.right,
          footerTop: footer.top,
          footerBottom: footer.bottom,
          reserve: Number.parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue(
              "--faryo-composer-reserve",
            ),
          ),
          lastMessageBottom: lastMessage.bottom,
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
      keyboardClosed.footerBackground !== "rgba(0, 0, 0, 0)" ||
      Math.abs(keyboardClosed.mainLeft - keyboardClosed.appLeft) > 1 ||
      Math.abs(keyboardClosed.mainRight - keyboardClosed.appRight) > 1 ||
      Math.abs(keyboardClosed.footerLeft - keyboardClosed.appLeft) > 1 ||
      Math.abs(keyboardClosed.footerRight - keyboardClosed.appRight) > 1 ||
      Math.abs(keyboardOpen.mainLeft - keyboardOpen.appLeft) > 1 ||
      Math.abs(keyboardOpen.mainRight - keyboardOpen.appRight) > 1 ||
      Math.abs(keyboardOpen.footerLeft - keyboardOpen.appLeft) > 1 ||
      Math.abs(keyboardOpen.footerRight - keyboardOpen.appRight) > 1 ||
      keyboardClosed.documentOverflow ||
      keyboardOpen.documentOverflow ||
      Math.abs(
        keyboardClosed.reserve - Math.ceil(keyboardClosed.footerHeight),
      ) > 1 ||
      Math.abs(keyboardClosed.mainPaddingBottom - keyboardClosed.reserve - 18) >
        1 ||
      Math.abs(keyboardOpen.mainPaddingBottom - keyboardOpen.reserve - 18) >
        1 ||
      Math.abs(keyboardClosed.mainHeight - keyboardOpen.mainHeight - 240) > 1 ||
      Math.abs(keyboardClosed.mainBottom - keyboardClosed.innerHeight) > 1 ||
      Math.abs(keyboardOpen.mainBottom - keyboardOpen.innerHeight) > 1 ||
      Math.abs(keyboardClosed.footerBottom - keyboardOpen.footerBottom - 240) >
        1 ||
      Math.abs(keyboardClosed.footerBottom - keyboardClosed.innerHeight) > 1 ||
      Math.abs(keyboardOpen.footerBottom - keyboardOpen.innerHeight) > 1 ||
      keyboardClosed.footerTop >= keyboardClosed.mainBottom ||
      keyboardOpen.footerTop >= keyboardOpen.mainBottom ||
      keyboardClosed.lastMessageBottom > keyboardClosed.footerTop - 17 ||
      keyboardOpen.lastMessageBottom > keyboardOpen.footerTop - 17
    ) {
      throw new Error(
        `Keyboard app shell violated its grid contract: ${JSON.stringify({ keyboardClosed, keyboardOpen })}`,
      );
    }

    const focusedFooter = await page.evaluate(() => {
      const root = document.documentElement;
      root.dataset.faryoUi = "workbench-v2";
      root.classList.remove("keyboard-open");
      const idlePadding = Number.parseFloat(
        getComputedStyle(document.querySelector("footer")).paddingBottom,
      );
      root.classList.add("keyboard-open");
      window.__faryoComposerController.update(true);
      const footer = document.querySelector("footer");
      const shell = document.querySelector(".prompt-shell");
      const app = document.querySelector(".app");
      return {
        coarsePointer: matchMedia("(hover: none) and (pointer: coarse)")
          .matches,
        idlePadding,
        focusedPadding: Number.parseFloat(
          getComputedStyle(footer).paddingBottom,
        ),
        transparent: getComputedStyle(footer).backgroundColor,
        reserve: Number.parseFloat(
          getComputedStyle(root).getPropertyValue("--faryo-composer-reserve"),
        ),
        footerHeight: footer.getBoundingClientRect().height,
        shellToAppBottom:
          app.getBoundingClientRect().bottom -
          shell.getBoundingClientRect().bottom,
      };
    });
    if (
      !focusedFooter.coarsePointer ||
      focusedFooter.idlePadding < 10 ||
      focusedFooter.focusedPadding !== 6 ||
      focusedFooter.transparent !== "rgba(0, 0, 0, 0)" ||
      Math.abs(focusedFooter.reserve - Math.ceil(focusedFooter.footerHeight)) >
        1 ||
      Math.abs(focusedFooter.shellToAppBottom - 6) > 1
    ) {
      throw new Error(
        `Focused mobile composer retained an avoidable bottom gap: ${JSON.stringify(focusedFooter)}`,
      );
    }

    const dynamicComposer = await page.evaluate(async () => {
      const main = document.querySelector("main");
      const shell = document.querySelector(".prompt-shell");
      main.scrollTop = main.scrollHeight;
      const before = Number.parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue(
          "--faryo-composer-reserve",
        ),
      );
      shell.style.minHeight = "132px";
      await new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      );
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const after = Number.parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue(
          "--faryo-composer-reserve",
        ),
      );
      return {
        before,
        after,
        footerHeight: document.querySelector("footer").getBoundingClientRect()
          .height,
        tailGap: main.scrollHeight - main.scrollTop - main.clientHeight,
      };
    });
    if (
      dynamicComposer.after <= dynamicComposer.before ||
      Math.abs(
        dynamicComposer.after - Math.ceil(dynamicComposer.footerHeight),
      ) > 1 ||
      dynamicComposer.tailGap > 1
    ) {
      throw new Error(
        `Dynamic composer reserve lost the conversation tail: ${JSON.stringify(dynamicComposer)}`,
      );
    }

    const historyAnchor = await page.evaluate(async () => {
      const main = document.querySelector("main");
      const shell = document.querySelector(".prompt-shell");
      window.__faryoTailPinned = false;
      main.scrollTop = 180;
      const before = main.scrollTop;
      shell.style.minHeight = "154px";
      await new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      );
      return { before, after: main.scrollTop };
    });
    if (Math.abs(historyAnchor.after - historyAnchor.before) > 1) {
      throw new Error(
        `Composer growth pulled a reader away from older history: ${JSON.stringify(historyAnchor)}`,
      );
    }

    const expandedHeader = await page.evaluate(() => {
      const app = document.querySelector(".app");
      const header = document.querySelector("header");
      const main = document.querySelector("main");
      const footer = document.querySelector("footer");
      app.classList.remove("header-collapsed");
      header.classList.remove("collapsed");
      const appRect = app.getBoundingClientRect();
      const headerRect = header.getBoundingClientRect();
      const mainRect = main.getBoundingClientRect();
      const footerRect = footer.getBoundingClientRect();
      return {
        appLeft: appRect.left,
        appRight: appRect.right,
        headerBottom: headerRect.bottom,
        mainTop: mainRect.top,
        mainLeft: mainRect.left,
        mainRight: mainRect.right,
        mainBottom: mainRect.bottom,
        footerLeft: footerRect.left,
        footerRight: footerRect.right,
        footerBottom: footerRect.bottom,
        appBottom: appRect.bottom,
      };
    });
    if (
      expandedHeader.mainTop < expandedHeader.headerBottom - 1 ||
      Math.abs(expandedHeader.mainLeft - expandedHeader.appLeft) > 1 ||
      Math.abs(expandedHeader.mainRight - expandedHeader.appRight) > 1 ||
      Math.abs(expandedHeader.footerLeft - expandedHeader.appLeft) > 1 ||
      Math.abs(expandedHeader.footerRight - expandedHeader.appRight) > 1 ||
      Math.abs(expandedHeader.mainBottom - expandedHeader.appBottom) > 1 ||
      Math.abs(expandedHeader.footerBottom - expandedHeader.appBottom) > 1
    ) {
      throw new Error(
        `Expanded header broke the overlapping Grid tracks: ${JSON.stringify(expandedHeader)}`,
      );
    }

    await page.evaluate(() => window.__faryoComposerController.destroy());
  },
);

console.log(
  "faryo-owner-layout=PASS collapsed-label=safe keyboard-app-shell=viewport-resize composer=transparent-overlay",
);
