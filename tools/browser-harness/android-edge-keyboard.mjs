import { chromium } from "playwright-core";

const cdpUrl = process.env.FARYO_ANDROID_CDP_URL || "http://127.0.0.1:9223";
const targetUrl = process.env.FARYO_SMOKE_URL || "";
const action = process.argv.includes("--reload")
  ? "reload"
  : process.argv.includes("--resize-contract")
    ? "resize-contract"
    : process.argv.includes("--tap")
      ? "tap"
      : process.argv.includes("--blur")
        ? "blur"
        : "measure";

const browser = await chromium.connectOverCDP(cdpUrl);
const context = browser.contexts()[0];
if (!context) throw new Error("Android Edge did not expose a browser context");

const pages = context.pages();
const targetOrigin = targetUrl ? new URL(targetUrl).origin : "";
let page = targetOrigin
  ? pages.find((candidate) => candidate.url().startsWith(targetOrigin))
  : null;
page ||= pages.find((candidate) => candidate.url() === "about:blank");
page ||= pages.at(-1);
if (!page) throw new Error("Android Edge did not expose a page target");

if (targetUrl && !page.url().startsWith(targetOrigin)) {
  try {
    await page.goto(targetUrl, {
      waitUntil: "domcontentloaded",
      timeout: 20_000,
    });
  } catch (_error) {
    throw new Error("Android Edge could not load the private smoke-test page");
  }
}
if (action === "reload") {
  try {
    await page.reload({ waitUntil: "domcontentloaded", timeout: 20_000 });
  } catch (_error) {
    throw new Error(
      "Android Edge could not reload the private smoke-test page",
    );
  }
}
await page.waitForSelector("#promptInput", {
  state: "visible",
  timeout: 20_000,
});

if (action === "resize-contract") {
  await page.evaluate(() => {
    if (navigator.virtualKeyboard) {
      navigator.virtualKeyboard.overlaysContent = false;
    }
    const viewport = document.querySelector('meta[name="viewport"]');
    if (viewport) {
      const parts = (viewport.getAttribute("content") || "")
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part && !/^interactive-widget\s*=/i.test(part));
      parts.push("interactive-widget=resizes-content");
      viewport.setAttribute("content", parts.join(", "));
    }
    document.documentElement.style.setProperty(
      "--faryo-keyboard-inset",
      "0px",
      "important",
    );
  });
  await page.waitForTimeout(1_200);
} else if (action === "tap") {
  const bounds = await page.locator("#promptInput").boundingBox();
  if (!bounds) throw new Error("The Android composer has no visible bounds");
  const session = await page.context().newCDPSession(page);
  const point = {
    x: bounds.x + bounds.width / 2,
    y: bounds.y + bounds.height / 2,
    radiusX: 2,
    radiusY: 2,
    force: 1,
    id: 1,
  };
  await session.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [point],
  });
  await session.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await session.detach();
  await page.waitForTimeout(1_200);
} else if (action === "blur") {
  await page.locator("#promptInput").evaluate((element) => element.blur());
  await page.waitForTimeout(500);
}

const snapshot = await page.evaluate(() => {
  const round = (value) =>
    Number.isFinite(Number(value))
      ? Math.round(Number(value) * 100) / 100
      : null;
  const rect = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    const bounds = element.getBoundingClientRect();
    return {
      top: round(bounds.top),
      bottom: round(bounds.bottom),
      left: round(bounds.left),
      right: round(bounds.right),
      width: round(bounds.width),
      height: round(bounds.height),
    };
  };
  const viewport = window.visualViewport;
  const keyboard = navigator.virtualKeyboard;
  const environmentLength = (name) => {
    const probe = document.createElement("div");
    probe.style.cssText = [
      "position:fixed",
      "visibility:hidden",
      "pointer-events:none",
      `height:env(${name},0px)`,
      "width:1px",
    ].join(";");
    document.body.append(probe);
    const value = round(probe.getBoundingClientRect().height);
    probe.remove();
    return value;
  };
  const keyboardInsets = Object.fromEntries(
    ["top", "right", "bottom", "left", "width", "height"].map((side) => [
      side,
      environmentLength(`keyboard-inset-${side}`),
    ]),
  );

  const units = {};
  for (const unit of ["vh", "dvh", "svh", "lvh"]) {
    const element = document.createElement("div");
    element.style.cssText = [
      "position:fixed",
      "visibility:hidden",
      "pointer-events:none",
      `height:100${unit}`,
      "width:1px",
    ].join(";");
    document.body.append(element);
    units[unit] = round(element.getBoundingClientRect().height);
    element.remove();
  }

  const app = document.querySelector(".app");
  const footer = document.querySelector("footer");
  return {
    release:
      document.querySelector("#versionToggle")?.textContent?.trim() || null,
    activeElement:
      document.activeElement?.id || document.activeElement?.tagName || null,
    window: {
      innerWidth: round(window.innerWidth),
      innerHeight: round(window.innerHeight),
      outerWidth: round(window.outerWidth),
      outerHeight: round(window.outerHeight),
      screenX: round(window.screenX),
      screenY: round(window.screenY),
      devicePixelRatio: round(window.devicePixelRatio),
    },
    screen: {
      width: round(screen.width),
      height: round(screen.height),
      availWidth: round(screen.availWidth),
      availHeight: round(screen.availHeight),
    },
    document: {
      clientWidth: round(document.documentElement.clientWidth),
      clientHeight: round(document.documentElement.clientHeight),
      scrollHeight: round(document.documentElement.scrollHeight),
    },
    visualViewport: viewport
      ? {
          width: round(viewport.width),
          height: round(viewport.height),
          offsetTop: round(viewport.offsetTop),
          pageTop: round(viewport.pageTop),
          scale: round(viewport.scale),
        }
      : null,
    virtualKeyboard: keyboard
      ? {
          overlaysContent: Boolean(keyboard.overlaysContent),
          boundingRect: keyboard.boundingRect
            ? {
                x: round(keyboard.boundingRect.x),
                y: round(keyboard.boundingRect.y),
                width: round(keyboard.boundingRect.width),
                height: round(keyboard.boundingRect.height),
              }
            : null,
        }
      : null,
    viewportMeta:
      document
        .querySelector('meta[name="viewport"]')
        ?.getAttribute("content") || null,
    root: {
      layout: document.documentElement.dataset.faryoKeyboardLayout || null,
      open: document.documentElement.dataset.faryoKeyboardOpen || null,
      keyboardInsets,
      safeArea: {
        top: environmentLength("safe-area-inset-top"),
        right: environmentLength("safe-area-inset-right"),
        bottom: environmentLength("safe-area-inset-bottom"),
        left: environmentLength("safe-area-inset-left"),
      },
      units,
    },
    layout: {
      app: rect(".app"),
      main: rect("#outputWrap"),
      footer: rect("footer"),
      promptShell: rect(".prompt-shell"),
      promptInput: rect("#promptInput"),
      appGridRows: app ? getComputedStyle(app).gridTemplateRows : null,
      footerPosition: footer ? getComputedStyle(footer).position : null,
      footerPaddingBottom: footer
        ? round(Number.parseFloat(getComputedStyle(footer).paddingBottom))
        : null,
    },
  };
});

console.log(JSON.stringify({ action, snapshot }, null, 2));
process.exit(0);
