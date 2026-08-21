import { withBrowser } from "../../../../tools/browser-harness/playwright.mjs";

const targetUrl = process.env.FARYO_SMOKE_URL || "";
const chromeBin = process.env.CHROME_BIN || "/usr/bin/google-chrome";
if (!targetUrl) throw new Error("FARYO_SMOKE_URL is required");

const prompt = `Reply without tools using exactly these Markdown parts:
## Browser Stream

Write a numbered list from 1 through 12. Each item must be a different complete Chinese sentence about reliable incremental rendering.

$a^2+b^2=c^2$

\`\`\`python
print("ok")
\`\`\`

STREAM_BROWSER_DONE`;

await withBrowser(
  {
    executablePath: chromeBin,
    viewport: { width: 390, height: 844 },
    mobile: true,
  },
  async ({ page }) => {
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error?.message || error)));
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.faryoAppReady === "1" &&
        document.getElementById("output")?.dataset.captureSource ===
          "codex-app-server",
      null,
      { timeout: 25_000 },
    );
    await page.evaluate(() => {
      const output = document.getElementById("output");
      const nodeIds = new WeakMap();
      const state = {
        nextNodeId: 1,
        activeNodeIds: new Set(),
        activeLengths: new Set(),
        sawMutable: false,
        sawStreaming: false,
      };
      const sample = () => {
        if (output?.dataset.streaming !== "true") return;
        state.sawStreaming = true;
        if (!output.dataset.streamItemId) return;
        const node = output.querySelector(".compact-block.output:last-of-type");
        if (!node) return;
        if (!nodeIds.has(node)) nodeIds.set(node, state.nextNodeId++);
        state.activeNodeIds.add(nodeIds.get(node));
        state.activeLengths.add(String(node.innerText || "").length);
        if (node.dataset.faryoBlockMutable === "true") state.sawMutable = true;
      };
      const observer = new MutationObserver(sample);
      observer.observe(output, {
        attributes: true,
        attributeFilter: ["data-streaming", "data-stream-item-id"],
        childList: true,
        characterData: true,
        subtree: true,
      });
      sample();
      globalThis.__faryoRealStream = { state, observer, sample };
    });

    await page.locator("#promptInput").fill(prompt);
    const sendStartedAt = Date.now();
    await page.locator("#sendBtn").click();
    await page.waitForFunction(
      () => document.getElementById("promptInput")?.value === "",
      null,
      { timeout: 10_000 },
    );
    const sendAckMs = Date.now() - sendStartedAt;
    await page.waitForFunction(
      () => {
        const output = document.getElementById("output");
        return (
          output?.dataset.streaming === "false" &&
          output.innerText.includes("STREAM_BROWSER_DONE")
        );
      },
      null,
      { timeout: 180_000 },
    );

    const state = await page.evaluate(() => {
      globalThis.__faryoRealStream.sample();
      globalThis.__faryoRealStream.observer.disconnect();
      const stream = globalThis.__faryoRealStream.state;
      const output = document.getElementById("output");
      const appScript = document.querySelector('script[src*="app.js?"]');
      const appRevision = new URL(appScript.src).searchParams.get("v") || "";
      const captureAsset = performance
        .getEntriesByType("resource")
        .map((entry) => entry.name)
        .find((url) => url.includes("/owner/capture-controller.mjs?"));
      const captureRevision = captureAsset
        ? new URL(captureAsset).searchParams.get("v") || ""
        : "";
      return {
        sawStreaming: stream.sawStreaming,
        sawMutable: stream.sawMutable,
        activeNodeCount: stream.activeNodeIds.size,
        activeLengthCount: stream.activeLengths.size,
        appRevision,
        captureRevision,
        katexCount: output.querySelectorAll(".katex").length,
        codeCount: output.querySelectorAll(".markdown-code-block").length,
        fallback: output.dataset.renderFallback || "",
        streamItemId: output.dataset.streamItemId || "",
        overflow:
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth + 1,
      };
    });

    if (
      !state.sawStreaming ||
      !state.sawMutable ||
      state.activeNodeCount !== 1 ||
      state.activeLengthCount < 1 ||
      !state.appRevision ||
      state.captureRevision !== state.appRevision ||
      state.katexCount < 2 ||
      state.codeCount < 2 ||
      state.fallback ||
      state.streamItemId ||
      state.overflow ||
      sendAckMs > 2_000 ||
      pageErrors.length
    ) {
      throw new Error(
        `Real App Server browser stream failed: ${JSON.stringify({ ...state, sendAckMs, pageErrors })}`,
      );
    }

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.faryoAppReady === "1" &&
        document.getElementById("output")?.innerText.includes(
          "STREAM_BROWSER_DONE",
        ) &&
        document.getElementById("output")?.querySelectorAll(".katex").length >=
          2,
      null,
      { timeout: 25_000 },
    );
    console.log(
      `faryo-browser-real-appserver=PASS send_ack_ms=${sendAckMs} frames=${state.activeLengthCount} keyed_node=yes markdown=yes katex=yes ordinary_reload=yes revision=${state.appRevision}`,
    );
  },
);
