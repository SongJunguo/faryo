import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export const BRACKETED_PASTE_START = '\u001b[200~';
export const BRACKETED_PASTE_END = '\u001b[201~';

function markerPrefixLength(value, marker) {
  const limit = Math.min(value.length, marker.length - 1);
  for (let length = limit; length > 0; length -= 1) {
    if (marker.startsWith(value.slice(-length))) return length;
  }
  return 0;
}

/**
 * Parse the exact terminal protocol used by tmux `paste-buffer -p` followed by
 * Enter. Keeping this parser independent from a shell prompt makes multiline
 * and non-ASCII delivery deterministic in browser smoke tests.
 */
export class TerminalDeliveryParser {
  constructor() {
    this.buffer = '';
    this.mode = 'waiting-for-paste';
    this.pastedText = '';
  }

  push(chunk) {
    this.buffer += String(chunk);
    const events = [];

    while (this.buffer) {
      if (this.mode === 'waiting-for-paste') {
        const start = this.buffer.indexOf(BRACKETED_PASTE_START);
        if (start < 0) {
          const keep = markerPrefixLength(this.buffer, BRACKETED_PASTE_START);
          this.buffer = keep ? this.buffer.slice(-keep) : '';
          break;
        }
        this.buffer = this.buffer.slice(start + BRACKETED_PASTE_START.length);
        this.pastedText = '';
        this.mode = 'reading-paste';
        continue;
      }

      if (this.mode === 'reading-paste') {
        const end = this.buffer.indexOf(BRACKETED_PASTE_END);
        if (end < 0) {
          const keep = markerPrefixLength(this.buffer, BRACKETED_PASTE_END);
          const bodyLength = this.buffer.length - keep;
          this.pastedText += this.buffer.slice(0, bodyLength);
          this.buffer = this.buffer.slice(bodyLength);
          break;
        }
        this.pastedText += this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + BRACKETED_PASTE_END.length);
        events.push({ type: 'paste', text: this.pastedText });
        this.mode = 'waiting-for-enter';
        continue;
      }

      const enter = this.buffer.search(/[\r\n]/u);
      if (enter < 0) {
        // Ignore terminal control noise while retaining no unbounded buffer.
        this.buffer = '';
        break;
      }
      this.buffer = this.buffer.slice(enter + 1);
      events.push({ type: 'submit', text: this.pastedText });
      this.pastedText = '';
      this.mode = 'waiting-for-paste';
    }

    return events;
  }
}

export function compactProbe(text) {
  return String(text).trim().split(/\s+/u).filter(Boolean).join(' ');
}

function lineCount(text) {
  return String(text).split(/\r\n|\r|\n/u).length;
}

function runReceiver() {
  if (!process.stdin.isTTY || !process.stdout.isTTY || typeof process.stdin.setRawMode !== 'function') {
    throw new Error('terminal-delivery-receiver requires a TTY');
  }

  const parser = new TerminalDeliveryParser();
  let sequence = 0;
  const restore = () => {
    try { process.stdout.write('\u001b[?2004l'); } catch {}
    try { process.stdin.setRawMode(false); } catch {}
  };
  const exit = (code) => {
    restore();
    process.exit(code);
  };

  process.stdin.setEncoding('utf8');
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdout.write('\u001b[?2004hFARYO_DELIVERY_READY\r\n');

  process.stdin.on('data', (chunk) => {
    if (chunk.includes('\u0003')) exit(0);
    for (const event of parser.push(chunk)) {
      if (event.type === 'paste') {
        // Owner confirms paste readiness by observing the compact tail in the
        // pane. Test payloads are intentionally anonymous and non-sensitive.
        process.stdout.write(`FARYO_DELIVERY_PASTE ${compactProbe(event.text)}\r\n`);
        continue;
      }
      sequence += 1;
      const index = String(sequence).padStart(2, '0');
      const characters = [...event.text].length;
      const digest = createHash('sha256').update(event.text, 'utf8').digest('hex').slice(0, 16);
      process.stdout.write(`FARYO_DELIVERY_ACK_${index} sha256=${digest} chars=${characters} lines=${lineCount(event.text)}\r\n`);
      process.stdout.write('FARYO_DELIVERY_READY\r\n');
    }
  });
  process.once('SIGINT', () => exit(0));
  process.once('SIGTERM', () => exit(0));
  process.once('exit', restore);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) runReceiver();
