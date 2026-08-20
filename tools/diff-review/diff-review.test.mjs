import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';

import { withBrowser } from '../browser-harness/playwright.mjs';

const root = path.resolve(import.meta.dirname, '../..');
const bundle = path.join(root, 'apps/owner/local-tmux-owner/static/vendor/diff-review/diff-review.min.js');

test('bundled diff renderer sanitizes untrusted diff content and supports both layouts', async () => {
  await withBrowser({ viewport: { width: 390, height: 844 } }, async ({ page }) => {
    await page.setContent('<div id="target"></div>');
    await page.addScriptTag({ path: bundle });
    const result = await page.evaluate(() => {
      window.__diffReviewXss = 0;
      const source = [
        'diff --git a/example.txt b/example.txt',
        '--- a/example.txt',
        '+++ b/example.txt',
        '@@ -1 +1 @@',
        '-safe',
        '+<img src=x onerror="window.__diffReviewXss=1"><script>window.__diffReviewXss=2</script>',
      ].join('\n');
      const line = window.FaryoDiffReview.render(source);
      const side = window.FaryoDiffReview.render(source, { sideBySide: true });
      document.getElementById('target').innerHTML = line;
      return {
        line,
        side,
        xss: window.__diffReviewXss,
        scripts: document.querySelectorAll('#target script').length,
        handlers: document.querySelectorAll('#target [onerror]').length,
      };
    });
    assert.match(result.line, /d2h-file-wrapper/);
    assert.match(result.side, /d2h-files-diff/);
    assert.equal(result.xss, 0);
    assert.equal(result.scripts, 0);
    assert.equal(result.handlers, 0);
    assert.doesNotMatch(result.line, /<script/i);
  });
});
