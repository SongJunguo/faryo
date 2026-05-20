(() => {
  'use strict';

  const userPromptRe = /^\s*(?:[│┃]\s*)?❯(?:\s+(?!\d+\.\s)|$)/;
  const approvalPendingRe = /(?:Do you want to (?:proceed|create|edit|write|run|allow|make)[^?\n]*\?|Yes, and don['’]t ask again|Enter to confirm|Esc to cancel)/i;
  const ctrlExpandRe = /\(ctrl\+o to expand\)/i;

  function leadingText(text, maxChars) {
    const chars = Array.from(String(text || ''));
    return chars.length <= maxChars ? chars.join('') : chars.slice(0, maxChars).join('') + '...';
  }

  function isDividerLine(line) { return /^[-─━]{8,}/.test(line.trim()); }
  function isClaudeActivityLine(line) {
    const value = line.trim();
    return /^\*\s+[A-Za-z][A-Za-z -]*(?:\.{3}|…)\s*\([^)]*(?:\d+\s*(?:ms|s|m|h)|tokens?|thinking|thought)[^)]*\)\s*$/i.test(value)
      || /^[·✢✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿★]\s+\S+.*(?:\bfor\s+\d+\w?|\bstill thinking\b|\.{3}|…)/i.test(value);
  }
  function isStatusLine(line) { return isClaudeActivityLine(line); }
  function isAssistantLine(line) { return /^\s*●\s+\S/.test(line); }
  function isClaudeChromeLine(line) {
    const value = line.trim();
    return /^(?:❯|›)$/.test(value)
      || /^esc to interrupt$/i.test(value)
      || /^\? for shortcuts\b/i.test(value)
      || /^[◇✧]\s+\S+\s*·\s*\/effort\b/i.test(value);
  }
  function isEditPreviewLine(line) {
    const value = line.trim();
    return /^(?:Update|Edit|Write|Create|MultiEdit)\(.+\)$/i.test(value)
      || /^(?:Edit file|File\s+\S+)$/i.test(value)
      || /^(?:[-─━]{8,}|\d+\s+[ +-])/.test(value);
  }
  function isApprovalOptionLine(line) {
    return /^(?:[❯›]\s*)?\d+\.\s+(?:Yes|No)\b/i.test(line.trim());
  }
  function hasApprovalPrompt(text) {
    return approvalPendingRe.test(text) || String(text || '').split('\n').some(isApprovalOptionLine);
  }
  function approvalBlockText(text) {
    const lines = String(text || '').split('\n');
    const start = lines.findIndex((line) => /^(?:Bash command|Do you want to\b)/i.test(line.trim()));
    return lines.slice(start < 0 ? 0 : start).join('\n').trim();
  }
  function cleanOutput(line) { return String(line || '').replace(/^\s*●\s?/, ''); }

  function isProcessLine(line) {
    const value = line.trim().replace(/^●\s*/, '');
    return ctrlExpandRe.test(value)
      || approvalPendingRe.test(value)
      || /^(?:⎿|✻)\s*/.test(value)
      || isEditPreviewLine(value)
      || /^(?:Not logged in\b|Please run \/login\b|Auto-updating\b|Running\b|Waiting\b|Bash(?:\(| command\b)|Read\(|Write\(|Edit\(|MultiEdit\(|Grep\(|Glob\(|LS\(|TodoWrite\(|Task\(|Glob patterns are not allowed\b|Esc to cancel\b)/i.test(value)
      || isApprovalOptionLine(value);
  }

  function stripLeadingStartupBanner(lines) {
    const start = lines.findIndex((line) => /Claude Code v/i.test(line));
    if (start < 0 || lines.slice(0, start).some((line) => line.trim() && !isDividerLine(line))) return lines;
    let end = start + 1;
    if (lines[start].trim().startsWith('╭')) {
      while (end < lines.length && !lines[end].trim().startsWith('╰')) end += 1;
      if (end < lines.length) end += 1;
    }
    while (end < lines.length && !lines[end].trim()) end += 1;
    return lines.slice(0, start).concat(lines.slice(end));
  }

  function blockText(kind, lines) {
    return (kind === 'output' ? lines.map(cleanOutput) : lines).join('\n').trim();
  }

  function push(blocks, kind, lines) {
    const text = blockText(kind, lines);
    if (!text) return;
    blocks.push({ kind, text });
  }

  function lineKind(line) {
    if (isStatusLine(line)) return 'status';
    if (userPromptRe.test(line)) return 'user';
    return isProcessLine(line) ? 'process' : 'output';
  }

  function compactBlocks(text) {
    const rawLines = (text || 'No output yet').split('\n');
    const hasTranscript = rawLines.some((line) => (userPromptRe.test(line) && line.replace(userPromptRe, '').trim()) || isAssistantLine(line));
    if (!hasTranscript && rawLines.some((line) => /Claude Code v/i.test(line))) return [{ kind: 'process', text: rawLines.join('\n').trim() }];

    const blocks = [];
    let kind = '', lines = [];
    const flush = () => { if (kind) push(blocks, kind, lines); kind = ''; lines = []; };
    for (const line of stripLeadingStartupBanner(rawLines)) {
      if (isClaudeChromeLine(line)) { flush(); continue; }
      if (isDividerLine(line)) { if (kind !== 'process') flush(); continue; }
      if (!line.trim()) { if (kind === 'output' || kind === 'user') lines.push(line); continue; }
      const next = lineKind(line);
      if (kind === 'user' && next === 'output' && /^\s+\S/.test(line) && !isAssistantLine(line)) { lines.push(line); continue; }
      if (kind === 'process' && next === 'output' && /^\s+\S/.test(line) && !isAssistantLine(line)) { lines.push(line); continue; }
      if (next === 'status') { flush(); push(blocks, 'status', [line]); continue; }
      if (next !== kind || kind === 'user') flush();
      kind = next;
      lines.push(line);
    }
    flush();
    const statusIndex = blocks.map((block) => block.kind).lastIndexOf('status');
    return statusIndex >= 0 && blocks.slice(statusIndex + 1).every((block) => block.kind === 'process')
      ? blocks.slice(0, statusIndex).concat(blocks.slice(statusIndex + 1), blocks[statusIndex])
      : blocks;
  }

  function processSummaryCard(text) {
    if (hasApprovalPrompt(text)) return approvalBlockText(text);
    let active = '', ready = '', error = false, resultCount = 0;
    const contexts = new Set(), commands = new Set(), tools = new Set(), edits = new Set();
    for (const raw of text.split('\n')) {
      const value = raw.trim().replace(/^●\s*/, '');
      if (!value) continue;
      if (/Claude Code v/i.test(value)) ready = 'Claude';
      if (/Not logged in\b|Please run \/login\b/i.test(value)) error = true;
      const edit = value.match(/^(?:Update|Edit|Write|Create|MultiEdit)\((.+)\)$/i);
      if (edit) { edits.add(leadingText(edit[1], 32)); active = '✏️ Editing files...'; }
      if (ctrlExpandRe.test(value)) {
        const label = leadingText(value.replace(/\s*\(ctrl\+o to expand\)/i, ''), 80);
        if (/^(?:Read|Listed|Searched|Found|Opened|Glob|Grep|LS)\b/i.test(label)) { contexts.add(label); active = '🔎 Reading context...'; }
        else { tools.add(label); active = '🛠 Using tool...'; }
      }
      const command = value.match(/^(?:Bash\(|Running\s+)([^\s)]*)/i);
      if (command) { commands.add(command[1] || 'command'); if (/^Running\b|Waiting/i.test(value)) active = '⚙️ Running command...'; }
      if (/^⎿/.test(value)) resultCount += 1;
    }
    const rows = [];
    if (ready && !error) rows.push(`✅ ${ready} ready`);
    if (active) rows.push(active);
    if (contexts.size) rows.push(`🔎 Read context: ${Array.from(contexts).slice(0, 3).join(', ')}`);
    if (edits.size) rows.push(`✏️ Updated files: ${Array.from(edits).slice(0, 3).join(', ')}`);
    if (commands.size) rows.push(`⚙️ Commands run: ${Array.from(commands).slice(0, 3).join(', ')}`);
    if (tools.size) rows.push(`🛠 Tool activity: ${Array.from(tools).slice(0, 3).join(', ')}`);
    if (resultCount) rows.push(`📎 Tool results: ${resultCount}`);
    if (error) rows.push('⚠️ Claude not logged in');
    if (!rows.length) rows.push(leadingText(text.trim(), 120));
    return rows.join('\n');
  }

  window.FaryoClaudeCompactRules = { userPromptRe, compactBlocks, processSummaryCard, approvalPendingRe };
})();
