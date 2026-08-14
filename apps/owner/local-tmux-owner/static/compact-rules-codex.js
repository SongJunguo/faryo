(() => {
  'use strict';

  const userPromptRe = /^(?!\s*›\s+Use\s+\/skills\s+to\s+list\s+available\s+skills\s*$)\s*›\s+/i;

  function leadingText(text, maxChars) {
    const chars = Array.from(String(text || ''));
    return chars.length <= maxChars ? chars.join('') : chars.slice(0, maxChars).join('') + '...';
  }

  const receivingRe = /^Receiving(?:\s+response)?(?:\.{3}|…)?$/i;
  const approvalPendingRe = /(?:^|\n)\s*(?:Reviewing(?:\s+\d+)?\s+approval requests?(?:\s+\(|\s*$)|Automatic approval review\b|Approval requested\b|Allow Codex to run\b|Would you like to (?:run the following command|make the following edits|grant these permissions)\?)/i;
  const processLineRe = /^(?:[•⚠✔]\s*)?(?:(?:Called|Ran|Running|Working|Read|Open|Search|Searched|Find|Grep|Glob|Edit|Edited|Patch|Applied patch|Viewed Image|Explored|Context compacted|Auto-reviewer approved|Waiting for background terminal|Waited for background terminal|Searching the web|Searched)\b|Receiving(?:\s+response)?(?:\.{3}|…)?$|Reviewing(?:\s+\d+)?\s+approval requests?(?:\s+\(|\s*$)|Automatic approval review\b|Approval requested\b|Allow Codex to run\b|Would you like to (?:run the following command|make the following edits|grant these permissions)\?)/;

  function isDividerLine(line) { return /^[-─━]{8,}/.test(line.trim()); }

  function isStatusLine(line) {
    const value = line.trim();
    return /^[-─━\s]*Worked for\s+\d+\w?(?:\s+\d+\w?)?[-─━\s]*$/i.test(value) || /^working$/i.test(value);
  }

  function isMarkdownTableLine(line) {
    const value = String(line || '').trim();
    if (!value.startsWith('|') || !value.endsWith('|')) return false;
    let pipes = 0;
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] !== '|') continue;
      let slashes = 0;
      for (let cursor = index - 1; cursor >= 0 && value[cursor] === '\\'; cursor -= 1) slashes += 1;
      if (slashes % 2 === 0) pipes += 1;
    }
    return pipes >= 2;
  }

  function isProcessLine(line) {
    const value = line.trim();
    return processLineRe.test(value)
      || /^(?:[│└├↳])/.test(value)
      || (/^\|\s/.test(value) && !isMarkdownTableLine(value))
      || /^(?:[-*•]\s*)?(?:\.{3}|…|⋯)\s*[+-]\d+\s+lines\b/i.test(value)
      || /^(?:\d+\s+)?[-+]?(?:<<<<<<<|=======|\|\|\|\|\|\|\||>>>>>>>)\b/.test(value)
      || /^\d{2,}\s+[-+]\s+/.test(value)
      || /^\d{2,}\s{4,}\S/.test(value)
      || /^\d+\s+[-+](?:[.#][\w-]+|\|\|\|\|\|\|\||<<<<<<<|=======|>>>>>>>)/.test(value)
      || /^\d+\s+[-+].*[{};]\s*$/.test(value)
      || /^(?:diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@|--- |\+\+\+ )/.test(value)
      || /^(?:[-*•]\s*)?(?:Edited|Created|Deleted|Updated)\s+(?:\/|\.{1,2}\/|~\/|[\w.-]+\/)/i.test(value)
      || /^\d+ files? changed(?:,|$)/i.test(value);
  }

  function isPlanStart(line) {
    return /^(?:[-*•]\s*)?(?:Updated Plan|Plan updated)$/i.test(line.trim());
  }

  function isPlanDetailLine(line) {
    return /^(?:[│|└├↳]\s*)?(?:[✔✓☑□☐-]\s+|\d+\.\s+)/.test(line.trim());
  }

  function isReportStart(line) { return /^•\s+\S/.test(line.trim()) && !isProcessLine(line); }

  function isPlainReportLine(line) {
    const value = line.trim();
    return !!value && !isProcessLine(value) && /^[\u4e00-\u9fff]/.test(value);
  }

  function isMarkdownReportLine(line) {
    const value = line.trim();
    return /^[-*]\s+\S/.test(value) && !isProcessLine(value);
  }

  function pushBlock(blocks, kind, lines) {
    const value = lines.join('\n').trim();
    if (value) blocks.push({ kind, text: value });
  }

  function finishTurn(turns, lines) {
    if (lines.some((line) => line.trim())) turns.push(lines);
    return [];
  }

  function splitTurns(lines) {
    const turns = [];
    let current = [];
    for (const line of lines) {
      if ((userPromptRe.test(line) && current.some((item) => item.trim())) || isDividerLine(line)) current = finishTurn(turns, current);
      if (isDividerLine(line)) continue;
      current.push(line);
      if (isStatusLine(line)) current = finishTurn(turns, current);
    }
    finishTurn(turns, current);
    return turns;
  }

  function classifyTurn(lines) {
    const blocks = [];
    let end = lines.length, index = 0;
    while (end > 0 && !lines[end - 1].trim()) end -= 1;
    const status = end > 0 && isStatusLine(lines[end - 1]) ? lines[--end] : '';
    while (index < end) {
      if (!lines[index].trim()) { index += 1; continue; }
      if (isPlanStart(lines[index])) {
        const start = index++;
        let hasItem = false;
        while (index < end) {
          const line = lines[index];
          if (!line.trim()) { index += 1; continue; }
          if (userPromptRe.test(line) || isStatusLine(line) || isPlanStart(line)) break;
          if (isPlanDetailLine(line)) {
            hasItem = true;
            index += 1;
            continue;
          }
          if (hasItem && /^\s{2,}\S/.test(line)) {
            index += 1;
            continue;
          }
          break;
        }
        pushBlock(blocks, 'plan', lines.slice(start, index));
        continue;
      }
      const kind = userPromptRe.test(lines[index]) ? 'user' : (isProcessLine(lines[index]) ? 'process' : 'output');
      const start = index++;
      while (index < end) {
        const line = lines[index];
        if (userPromptRe.test(line) || isStatusLine(line) || isPlanStart(line)) break;
        if (kind === 'user' && (isProcessLine(line) || isReportStart(line))) break;
        const afterBlank = index > start && !lines[index - 1].trim();
        if (kind === 'process' && (isReportStart(line) || (afterBlank && (isMarkdownReportLine(line) || isPlainReportLine(line))))) break;
        if (kind === 'output' && isProcessLine(line)) break;
        index += 1;
      }
      pushBlock(blocks, kind, lines.slice(start, index));
    }
    if (status) pushBlock(blocks, 'status', [status]);
    return blocks;
  }

  function compactBlocks(text) { return splitTurns((text || 'No output yet').split('\n')).flatMap(classifyTurn); }

  function processSummaryCard(text) {
    let lines = 0, images = 0, web = 0, commandCount = 0, toolCallCount = 0, backgroundWaits = 0, diffPreviewLines = 0, approval = false, error = false, active = '', toolReady = '', model = '', directory = '', files = 0, insertions = 0, deletions = 0, pendingToolCall = false;
    const contexts = new Set(), commands = new Set(), toolCalls = new Set();
    const fileLabel = (value) => leadingText((value.match(/[\w.-]+(?:\.[A-Za-z0-9]{1,8})?(?=$|[:),])/g) || [value]).pop(), 26);
    const toolLabel = (value) => {
      const raw = String(value || 'tool').replace(/\(\{[\s\S]*$/, '').replace(/\(.*/, '').split(/\s+/)[0] || 'tool';
      const simplified = raw
        .replace(/^mcp__([^_]+)__.*$/, '$1')
        .replace(/^functions\.(?:exec_command|write_stdin)$/, 'terminal')
        .replace(/^functions\.apply_patch$/, 'patch')
        .replace(/^([^.]+)\..*$/, '$1');
      return leadingText(simplified, 24);
    };
    for (const raw of text.split('\n')) {
      const value = raw.trim().replace(/^[-*•⚠✔]\s*/, '').replace(/^[│|└├↳]\s*/, '').trim();
      if (!value) continue;
      lines += 1;
      if (pendingToolCall) { toolCalls.add(toolLabel(value)); pendingToolCall = false; active = ''; continue; }
      const called = value.match(/^Called(?:\s+(.+))?$/i);
      if (called) { toolCallCount += 1; active = '🛠 Calling tool...'; if (called[1]) { toolCalls.add(toolLabel(called[1])); active = ''; } else pendingToolCall = true; continue; }
      if (/^>_ OpenAI Codex\b/i.test(value)) toolReady = 'Codex';
      if (/^model:\s*(.+?)(?:\s{2,}|$)/i.test(value)) model = value.match(/^model:\s*(.+?)(?:\s{2,}|$)/i)[1];
      if (/^directory:\s*(.+)$/i.test(value)) directory = value.match(/^directory:\s*(.+)$/i)[1];
      if (/^Viewed Image\b/i.test(value)) { images += 1; active = '🖼 Viewing image...'; }
      if (/^Searching the web\b/i.test(value)) { web += 1; active = '🌐 Searching web...'; }
      else if (/^Searched\b/i.test(value)) { web += 1; active = ''; }
      else if (/^Edited\b/i.test(value)) { active = '✏️ Editing files...'; }
      else if (/^(?:Explored|Read|Open|Search|Find|Grep|Glob)\b/i.test(value)) { contexts.add(fileLabel(value)); active = '🔎 Reading context...'; }
      const command = value.match(/^(Ran|Running)\s+([^\s]+)/i);
      if (command) { commandCount += 1; commands.add(command[2]); active = command[1].toLowerCase() === 'running' ? '⚙️ Running command...' : ''; }
      if (/^Working\b/i.test(value)) active = '⚙️ Working...';
      if (receivingRe.test(value)) active = '📥 Receiving response...';
      if (approvalPendingRe.test(value)) active = '⏳ Approval review in progress';
      if (/^Waiting for background terminal\b/i.test(value)) { backgroundWaits += 1; active = '⚙️ Background task running...'; }
      if (/^Waited for background terminal\b/i.test(value)) { backgroundWaits += 1; if (active === '⚙️ Background task running...') active = ''; }
      if (/^\d{2,}\s+(?:[-+]\s+|\s{4,}\S)/.test(value) || /^(?:diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@|--- |\+\+\+ )/.test(value)) diffPreviewLines += 1;
      if (/^Auto-reviewer approved\b/i.test(value)) { approval = true; active = ''; }
      if (/\b(?:failed|error|not found|rejected)\b/i.test(value)) error = true;
      const diff = value.match(/^(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?/i);
      if (diff) { files = Number(diff[1] || 0); insertions = Number(diff[2] || 0); deletions = Number(diff[3] || 0); active = ''; }
    }
    const rows = [];
    if (toolReady) rows.push(`✅ ${toolReady} ready${model || directory ? ` · ${[model, directory].filter(Boolean).join(' · ')}` : ''}`);
    if (active) rows.push(active);
    if (images) rows.push(`🖼 Viewed images: ${images}`);
    if (web) rows.push(`🌐 Web searches: ${web}`);
    if (contexts.size) rows.push(`🔎 Read context: ${Array.from(contexts).slice(0, 3).join(', ')}`);
    if (commandCount) rows.push(`⚙️ Commands run: ${commandCount}${commands.size ? ` (${Array.from(commands).slice(0, 4).join(', ')})` : ''}`);
    if (toolCallCount) rows.push(`🛠 Tool calls: ${toolCallCount}${toolCalls.size ? ` (${Array.from(toolCalls).slice(0, 4).join(', ')})` : ''}`);
    if (backgroundWaits && !active) rows.push(`⚙️ Background waits: ${backgroundWaits}`);
    if (diffPreviewLines && !files) rows.push(`🧩 Diff preview hidden: ${diffPreviewLines} lines`);
    if (approval) rows.push('✅ Approval approved');
    if (files) rows.push(`🧩 Diff summary: ${files} files +${insertions} / -${deletions}`);
    if (error) rows.push('⚠️ Process output includes errors');
    return rows.join('\n');
  }


  window.FaryoCodexCompactRules = {
    userPromptRe,
    isMarkdownTableLine,
    compactBlocks,
    processSummaryCard,
    approvalPendingRe,
  };
})();
