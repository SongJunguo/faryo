import { withBrowser } from "./playwright.mjs";

const targetUrl = process.env.FARYO_SMOKE_URL || "";
if (!targetUrl) throw new Error("FARYO_SMOKE_URL is required");
const traceEnabled = process.env.FARYO_PROFILE_TRACE === "1";

const delay = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

await withBrowser(
  {
    viewport: { width: 1280, height: 720 },
    mobile: false,
  },
  async ({ page }) => {
    let historyRequests = 0;
    page.on("request", (request) => {
      if (
        new URL(request.url()).pathname.endsWith("/api/conversation-history")
      ) {
        historyRequests += 1;
      }
    });
    await page.addInitScript(
      ({ traceEnabled: enableTrace }) => {
        window.__faryoProfile = {
          audioPlayCalls: 0,
          vibrationCalls: 0,
          longTasks: [],
          frameGaps: [],
          timeline: [],
          traceEnabled: Boolean(enableTrace),
          scrollEvents: 0,
          richStateChanges: 0,
        };
        const scrollTopDescriptor = Object.getOwnPropertyDescriptor(
          Element.prototype,
          "scrollTop",
        );
        if (
          window.__faryoProfile.traceEnabled &&
          scrollTopDescriptor?.get &&
          scrollTopDescriptor?.set
        ) {
          Object.defineProperty(Element.prototype, "scrollTop", {
            configurable: scrollTopDescriptor.configurable,
            enumerable: scrollTopDescriptor.enumerable,
            get: scrollTopDescriptor.get,
            set(value) {
              if (
                this.id === "outputWrap" &&
                window.__faryoProfile.timeline.length < 240
              ) {
                window.__faryoProfile.timeline.push({
                  type: "write",
                  at: performance.now(),
                  top: Number(value),
                  stack: String(new Error().stack || "")
                    .split("\n")
                    .slice(1, 4),
                });
              }
              return scrollTopDescriptor.set.call(this, value);
            },
          });
        }
        const originalPlay = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function profiledPlay(...args) {
          window.__faryoProfile.audioPlayCalls += 1;
          return originalPlay.apply(this, args);
        };
        if (typeof navigator.vibrate === "function") {
          const originalVibrate = navigator.vibrate.bind(navigator);
          navigator.vibrate = (...args) => {
            window.__faryoProfile.vibrationCalls += 1;
            return originalVibrate(...args);
          };
        }
        try {
          const observer = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              window.__faryoProfile.longTasks.push({
                startTime: entry.startTime,
                duration: entry.duration,
              });
            }
          });
          observer.observe({ type: "longtask", buffered: true });
        } catch (_error) {}
      },
      { traceEnabled },
    );

    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => document.documentElement.dataset.faryoAppReady === "1",
      null,
      { timeout: 15_000 },
    );
    await page.waitForSelector("#output .compact-block.user", {
      timeout: 15_000,
    });
    const main = page.locator("#outputWrap");
    const bounds = await main.boundingBox();
    if (!bounds) throw new Error("Conversation scrollport is unavailable");
    await page.mouse.move(
      bounds.x + bounds.width / 2,
      bounds.y + bounds.height / 2,
    );

    const counts = () =>
      page.evaluate(() => ({
        loaded: document.querySelectorAll("#output .compact-block.user").length,
        total: Number(
          document.getElementById("questionNavTotal")?.textContent || 0,
        ),
        unloaded: document.querySelectorAll(
          "#questionNavMarkers .question-nav-marker.unloaded",
        ).length,
      }));
    let settledPasses = 0;
    for (let pass = 0; pass < 10; pass += 1) {
      await page.mouse.wheel(0, -20_000);
      await delay(900);
      const state = await counts();
      if (
        state.total > 0 &&
        state.loaded >= state.total &&
        state.unloaded === 0
      ) {
        settledPasses += 1;
        if (settledPasses >= 2) break;
      } else {
        settledPasses = 0;
      }
    }
    await page.waitForFunction(
      () => {
        const loaded = document.querySelectorAll(
          "#output .compact-block.user",
        ).length;
        const total = Number(
          document.getElementById("questionNavTotal")?.textContent || 0,
        );
        const unloaded = document.querySelectorAll(
          "#questionNavMarkers .question-nav-marker.unloaded",
        ).length;
        return total > 0 && loaded >= total && unloaded === 0;
      },
      null,
      { timeout: 15_000 },
    );
    // Let the final prepend-anchor restoration and deferred rich-block release
    // settle before recording the independent rapid-scroll sample.
    await delay(600);

    await page.evaluate(() => {
      const profile = window.__faryoProfile;
      profile.longTasks.length = 0;
      profile.frameGaps.length = 0;
      profile.scrollEvents = 0;
      profile.richStateChanges = 0;
      profile.timeline.length = 0;
      const scroller = document.getElementById("outputWrap");
      scroller.scrollTop = scroller.scrollHeight;
      scroller.addEventListener(
        "scroll",
        () => {
          profile.scrollEvents += 1;
          if (profile.traceEnabled && profile.timeline.length < 240) {
            profile.timeline.push({
              type: "scroll",
              at: performance.now(),
              top: scroller.scrollTop,
            });
          }
        },
        { passive: true },
      );
      new MutationObserver((records) => {
        profile.richStateChanges += records.length;
        if (profile.traceEnabled && profile.timeline.length < 240) {
          profile.timeline.push({
            type: "rich",
            at: performance.now(),
            top: scroller.scrollTop,
            records: records.length,
          });
        }
      }).observe(document.getElementById("output"), {
        attributes: true,
        attributeFilter: ["data-faryo-rich-state"],
        subtree: true,
      });
      let previous = performance.now();
      const deadline = previous + 3000;
      const tick = (now) => {
        profile.frameGaps.push({ at: now, gap: now - previous });
        previous = now;
        if (now < deadline) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    const session = await page.context().newCDPSession(page);
    const scrollStartedAt = await page.evaluate(() => performance.now());
    let wheelEvents = 0;
    for (let index = 0; index < 240; index += 1) {
      await session.send("Input.dispatchMouseEvent", {
        type: "mouseWheel",
        x: Math.round(bounds.x + bounds.width / 2),
        y: Math.round(bounds.y + bounds.height / 2),
        deltaX: 0,
        deltaY: -420,
      });
      wheelEvents += 1;
      await delay(8);
      if (index % 8 === 7) {
        const reachedTop = await page.evaluate(
          () => document.getElementById("outputWrap")?.scrollTop <= 1,
        );
        if (reachedTop) break;
      }
    }
    const scrollEndedAt = await page.evaluate(() => performance.now());
    const scrollTopAfterInput = await page.evaluate(
      () => document.getElementById("outputWrap")?.scrollTop || 0,
    );
    await session.detach();
    await delay(250);
    const scrollTopAfterIdle = await page.evaluate(
      () => document.getElementById("outputWrap")?.scrollTop || 0,
    );
    await delay(3200);

    const metrics = await page.evaluate(
      ({
        scrollStartedAt,
        scrollEndedAt,
        scrollTopAfterInput,
        scrollTopAfterIdle,
        wheelEvents,
      }) => {
        const profile = window.__faryoProfile;
        const longTasks = profile.longTasks.map((entry) => ({
          startTime: Number(entry.startTime),
          duration: Number(entry.duration),
        }));
        const frameGaps = profile.frameGaps.map((entry) => ({
          at: Number(entry.at),
          gap: Number(entry.gap),
        }));
        const activeLongTasks = longTasks.filter(
          (entry) =>
            entry.startTime <= scrollEndedAt &&
            entry.startTime + entry.duration >= scrollStartedAt,
        );
        const activeFrameGaps = frameGaps.filter(
          (entry) =>
            entry.at >= scrollStartedAt && entry.at <= scrollEndedAt + 34,
        );
        const output = document.getElementById("output");
        const scroller = document.getElementById("outputWrap");
        return {
          release:
            document.getElementById("versionToggle")?.textContent?.trim() || "",
          totalQuestions: Number(
            document.getElementById("questionNavTotal")?.textContent || 0,
          ),
          loadedQuestions: output.querySelectorAll(".compact-block.user")
            .length,
          blocks: output.children.length,
          domNodes: document.querySelectorAll("*").length,
          richRendered: output.querySelectorAll(
            '[data-faryo-rich-state="rendered"]',
          ).length,
          richDeferred: output.querySelectorAll(
            '[data-faryo-rich-state="deferred"]',
          ).length,
          scrollHeight: Math.round(scroller.scrollHeight),
          scrollTop: Math.round(scroller.scrollTop),
          scrollTopAfterInput: Math.round(scrollTopAfterInput),
          scrollTopAfterIdle: Math.round(scrollTopAfterIdle),
          wheelEvents,
          scrollEvents: profile.scrollEvents,
          richStateChanges: profile.richStateChanges,
          ...(profile.traceEnabled ? { timeline: profile.timeline } : {}),
          longTaskCount: longTasks.length,
          longTaskTotalMs: Math.round(
            longTasks.reduce((sum, entry) => sum + entry.duration, 0),
          ),
          longestTaskMs: Math.round(
            Math.max(0, ...longTasks.map((entry) => entry.duration)),
          ),
          activeLongTaskCount: activeLongTasks.length,
          activeLongestTaskMs: Math.round(
            Math.max(0, ...activeLongTasks.map((entry) => entry.duration)),
          ),
          framesOver32Ms: frameGaps.filter((entry) => entry.gap > 32).length,
          framesOver50Ms: frameGaps.filter((entry) => entry.gap > 50).length,
          longestFrameMs: Math.round(
            Math.max(0, ...frameGaps.map((entry) => entry.gap)),
          ),
          activeFramesOver32Ms: activeFrameGaps.filter(
            (entry) => entry.gap > 32,
          ).length,
          activeFramesOver50Ms: activeFrameGaps.filter(
            (entry) => entry.gap > 50,
          ).length,
          activeLongestFrameMs: Math.round(
            Math.max(0, ...activeFrameGaps.map((entry) => entry.gap)),
          ),
          audioPlayCalls: profile.audioPlayCalls,
          vibrationCalls: profile.vibrationCalls,
          bellCharacters: (output.textContent.match(/\u0007/gu) || []).length,
        };
      },
      {
        scrollStartedAt,
        scrollEndedAt,
        scrollTopAfterInput,
        scrollTopAfterIdle,
        wheelEvents,
      },
    );
    console.log(
      JSON.stringify(
        {
          profile: metrics,
          historyRequests,
        },
        null,
        2,
      ),
    );
  },
);
