import { html as diffHtml } from 'diff2html';
import createDOMPurify from 'dompurify';

function create(windowRef) {
  if (!windowRef?.document) throw new TypeError('diff review requires a browser window');
  const purifier = createDOMPurify(windowRef);

  function render(source, options = {}) {
    const diff = String(source || '');
    if (!diff.trim()) return '<div class="diff-review-empty">No uncommitted text changes</div>';
    const raw = diffHtml(diff, {
      colorScheme: 'auto',
      diffMaxChanges: 2000,
      diffMaxLineLength: 4000,
      drawFileList: true,
      matching: 'lines',
      outputFormat: options.sideBySide ? 'side-by-side' : 'line-by-line',
      renderNothingWhenEmpty: true,
    });
    return purifier.sanitize(raw, {
      FORBID_ATTR: ['style'],
      FORBID_TAGS: ['button', 'embed', 'form', 'iframe', 'input', 'object', 'script', 'select', 'style', 'textarea'],
      USE_PROFILES: { html: true },
    });
  }

  return { render };
}

const api = create(window);
window.FaryoDiffReview = api;
