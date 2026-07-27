(() => {
  'use strict';

  const userPromptRe = /^\s*❯(?:\s+(?!\d+\.\s)|$)/;
  const approvalPendingRe = /(?:Do you want to (?:proceed|create|edit|write|run|allow|make)[^?\n]*\?|Yes, and don['’]t ask again|Enter to confirm|Esc to cancel)/i;
  const spinnerRe = /^[·*✢✣✤✥✦✧✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿]\s+\S+…\s*(?:\([^)]*\))?$/;
  const doneRe = /^[·*✢✣✤✥✦✧✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿]\s+\w+ for \d+\w*(?:\s+\d+\w*)?\s*$/;
  const toolSummaryRe = /^(?:Read(?:ing)?|Ran|Running|Wr(?:iting|ote)|Edit(?:ing|ed)|List(?:ing|ed)|Search(?:ing|ed)|Fetch(?:ing|ed)|Creat(?:ing|ed)|Updat(?:ing|ed)|Check(?:ing|ed))\b.*\b\d+\s+(?:files?|director(?:y|ies)|shell commands?|lines?|todos?|edits?)\b/i;
  const toolCallRe = /^(?:Bash|Read|Write|Edit|Update|MultiEdit|Grep|Glob|LS|Task|TodoWrite|WebFetch|WebSearch|Skill|Agent)\(/;
  const ctrlExpandRe = /\s*\(ctrl\+\w+ to expand\)/i;

  function leadingText(text, maxChars) {
    const chars = Array.from(String(text || ''));
    return chars.length <= maxChars ? chars.join('') : chars.slice(0, maxChars).join('') + '...';
  }

  function isDividerLine(line) { return /^[-─━]{8,}/.test(line.trim()); }
  function isStatusLine(line) {
    const value = line.trim();
    return spinnerRe.test(value) || doneRe.test(value);
  }
  function isChromeLine(line) {
    const value = line.trim();
    return /^[❯›]$/.test(value)
      || /^esc to interrupt$/i.test(value)
      || /^\? for shortcuts\b/i.test(value)
      || /shift\+tab to cycle/i.test(value)
      || /\/clear to save\b/i.test(value)
      || /^⎿\s*Tip:/i.test(value);
  }
  function isBottomChromeLine(line) {
    const value = line.trim();
    return /^[█░▓]{3,}\s*\d+%\s*context\b/.test(value) || isChromeLine(line);
  }
  function isApprovalOptionLine(line) {
    return /^(?:[❯›]\s*)?\d+\.\s+(?:Yes|No)\b/i.test(line.trim());
  }
  function hasApprovalPrompt(text) {
    return approvalPendingRe.test(text) || String(text || '').split('\n').some(isApprovalOptionLine);
  }
  function approvalBlockText(text) {
    const lines = String(text || '').split('\n');
    const start = lines.findIndex((line) => /^●?\s*(?:Bash command|Do you want to\b)/i.test(line.trim()));
    return lines.slice(start < 0 ? 0 : start).join('\n').trim();
  }
  function isProcessLine(line) {
    if (/^\s{3,}\d+(?:\s+\S.*)?$/.test(line)) return true;
    const value = line.trim().replace(/^●\s*/, '');
    return /^⎿/.test(value)
      || toolSummaryRe.test(value)
      || toolCallRe.test(value)
      || ctrlExpandRe.test(value)
      || approvalPendingRe.test(value)
      || isApprovalOptionLine(value)
      || /^(?:Bash command\b|Not logged in\b|Please run \/login\b)/i.test(value)
      || /^\d+\s*[+-]\s/.test(value);
  }

  function stripStartupBanner(lines) {
    let start = 0;
    while (start < lines.length && !lines[start].trim()) start += 1;
    let end = start;
    while (end < lines.length && lines[end].trim()) end += 1;
    const run = lines.slice(start, end);
    const isBanner = run.length <= 6
      && run.some((line) => /Claude Code v\d/.test(line))
      && run.some((line) => /[▘▝▖▗▌▐█▛▜▙▟]/.test(line));
    return isBanner ? lines.slice(0, start).concat(lines.slice(end)) : lines;
  }

  // The owner's clean_capture drops the composer box's divider lines before
  // the text reaches the browser, so nothing here may anchor on dividers.
  // Instead walk up from the end of the frame: the bottom-most ❯ line with
  // only chrome, blanks, or a few wrapped continuation lines below it is the
  // live composer — typed-but-unsubmitted input included — and everything
  // from it down is bottom chrome. Keep only the mode footer.
  function stripBottomChrome(lines) {
    let composer = -1;
    let plain = 0;
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const line = lines[i];
      if (!line.trim()) continue;
      if (/^\s*[❯›]/.test(line.trim())) { composer = i; break; }
      if (isBottomChromeLine(line) || isDividerLine(line)) continue;
      if (isStatusLine(line) || plain >= 6) break;
      plain += 1;
    }
    if (composer < 0) return lines;
    const kept = lines.slice(composer + 1).filter((line) => /shift\+tab to cycle/i.test(line));
    return lines.slice(0, composer).concat(kept);
  }

  function cleanOutput(line) { return String(line || '').replace(/^\s*●\s?/, ''); }
  function blockText(kind, lines) {
    return (kind === 'output' ? lines.map(cleanOutput) : lines).join('\n').trim();
  }

  function compactBlocks(text) {
    const blocks = [];
    let kind = '', lines = [];
    const flush = () => {
      if (kind) {
        const value = blockText(kind, lines);
        if (value) blocks.push({ kind, text: value });
      }
      kind = ''; lines = [];
    };
    for (const line of stripBottomChrome(stripStartupBanner(String(text || '').split('\n')))) {
      const footerMode = /shift\+tab to cycle/i.test(line) && line.match(/\b((?:bypass permissions|accept edits|plan mode|default mode)\s+(?:on|off))\b/i);
      if (footerMode) { flush(); blocks.push({ kind: 'status', text: '⏵ ' + footerMode[1].toLowerCase() }); continue; }
      if (isChromeLine(line) || isDividerLine(line)) { flush(); continue; }
      if (!line.trim()) { if (kind === 'output' || kind === 'user') lines.push(line); continue; }
      if (isStatusLine(line)) { flush(); blocks.push({ kind: 'status', text: line.trim() }); continue; }
      const next = userPromptRe.test(line) ? 'user' : (isProcessLine(line) ? 'process' : 'output');
      if (next === 'output' && (kind === 'user' || kind === 'process') && /^\s+\S/.test(line) && !/^\s*●/.test(line)) { lines.push(line); continue; }
      if (next !== kind || next === 'user') flush();
      kind = next;
      lines.push(line);
    }
    flush();
    const merged = [];
    for (const block of blocks) {
      const last = merged[merged.length - 1];
      if (block.kind === 'status' && last && last.kind === 'status') last.text += '\n' + block.text;
      else merged.push(block);
    }
    return merged.length ? merged : [{ kind: 'status', text: '✅ Claude ready' }];
  }

  function processSummaryCard(text) {
    if (hasApprovalPrompt(text)) return approvalBlockText(text);
    const rows = new Set();
    let error = false;
    for (const raw of String(text || '').split('\n')) {
      const value = raw.trim().replace(/^●\s*/, '');
      if (!value) continue;
      if (/^\d+\s*[+-]\s/.test(value) || /^\d+(?:\s|$)/.test(value)) { rows.add('✏️ Editing files…'); continue; }
      if (/^(?:Not logged in\b|Please run \/login\b)/i.test(value)) { error = true; continue; }
      if (toolSummaryRe.test(value)) { rows.add('⚙️ ' + leadingText(value, 80)); continue; }
      if (toolCallRe.test(value)) { rows.add('🛠 ' + leadingText(value.replace(ctrlExpandRe, ''), 80)); continue; }
      if (/^⎿/.test(value)) rows.add('📎 ' + leadingText(value.replace(/^⎿\s*/, '').replace(ctrlExpandRe, ''), 80));
    }
    if (error) rows.add('⚠️ Claude not logged in');
    const list = Array.from(rows).slice(0, 4);
    return list.length ? list.join('\n') : leadingText(String(text || '').trim(), 120);
  }

  window.FaryoClaudeCompactRules = { userPromptRe, compactBlocks, processSummaryCard, approvalPendingRe };
})();
