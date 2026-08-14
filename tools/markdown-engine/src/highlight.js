/*
 * Faryo's on-demand Shiki highlighter follows the DeepSeek Harness strategy:
 * one JavaScript-regex engine, a tiny boot grammar set, explicit aliases, and
 * dynamic imports for wider language coverage. DeepSeek Harness reference:
 * commit 47f943859bef60e4160492346772ded9b24f765a (MIT).
 */

import langJson from '@shikijs/langs/json';
import langShell from '@shikijs/langs/shellscript';
import langTypeScript from '@shikijs/langs/typescript';
import { createHighlighterCoreSync, createCssVariablesTheme } from 'shiki/core';
import {
  createJavaScriptRegexEngine,
  defaultJavaScriptRegexConstructor,
} from 'shiki/engine/javascript';

const bootGrammars = [langTypeScript, langShell, langJson];
const lazyGrammars = new Map([
  ['python', () => import('@shikijs/langs/python')],
  ['latex', () => import('@shikijs/langs/latex')],
  ['lean', () => import('@shikijs/langs/lean')],
  ['matlab', () => import('@shikijs/langs/matlab')],
  ['markdown', () => import('@shikijs/langs/markdown')],
  ['yaml', () => import('@shikijs/langs/yaml')],
  ['html', () => import('@shikijs/langs/html')],
  ['css', () => import('@shikijs/langs/css')],
  ['cpp', () => import('@shikijs/langs/cpp')],
  ['c', () => import('@shikijs/langs/c')],
  ['rust', () => import('@shikijs/langs/rust')],
  ['go', () => import('@shikijs/langs/go')],
  ['java', () => import('@shikijs/langs/java')],
  ['sql', () => import('@shikijs/langs/sql')],
]);

const aliases = new Map([
  ['typescript', 'typescript'],
  ['ts', 'typescript'],
  ['tsx', 'typescript'],
  ['javascript', 'typescript'],
  ['js', 'typescript'],
  ['jsx', 'typescript'],
  ['shellscript', 'shellscript'],
  ['bash', 'shellscript'],
  ['sh', 'shellscript'],
  ['shell', 'shellscript'],
  ['zsh', 'shellscript'],
  ['json', 'json'],
  ['jsonc', 'json'],
  ['python', 'python'],
  ['py', 'python'],
  ['latex', 'latex'],
  ['tex', 'latex'],
  ['lean', 'lean'],
  ['lean4', 'lean'],
  ['matlab', 'matlab'],
  ['markdown', 'markdown'],
  ['md', 'markdown'],
  ['yaml', 'yaml'],
  ['yml', 'yaml'],
  ['html', 'html'],
  ['xml', 'html'],
  ['css', 'css'],
  ['cpp', 'cpp'],
  ['c++', 'cpp'],
  ['cc', 'cpp'],
  ['c', 'c'],
  ['rust', 'rust'],
  ['rs', 'rust'],
  ['go', 'go'],
  ['java', 'java'],
  ['sql', 'sql'],
]);

const theme = createCssVariablesTheme({
  name: 'css-variables',
  variablePrefix: '--shiki-',
  fontStyle: true,
});
const regexEngine = createJavaScriptRegexEngine({
  forgiving: true,
  regexConstructor: (pattern) => defaultJavaScriptRegexConstructor(pattern, {
    lazyCompileLength: Number.POSITIVE_INFINITY,
  }),
});
const requested = new Set();
let singleton;

function highlighter() {
  if (!singleton) {
    singleton = createHighlighterCoreSync({
      themes: [theme],
      langs: bootGrammars,
      engine: regexEngine,
    });
    for (const sample of [
      { lang: 'typescript', code: 'const answer: number = 42' },
      { lang: 'shellscript', code: 'printf "%s\\n" "$HOME"' },
      { lang: 'json', code: '{"ready":true}' },
    ]) {
      singleton.codeToTokens(sample.code, {
        lang: sample.lang,
        theme: 'css-variables',
        tokenizeTimeLimit: 0,
      });
    }
  }
  return singleton;
}

function notifyReady() {
  globalThis.dispatchEvent(new CustomEvent('faryo-markdown-highlighter-ready'));
}

function ensureGrammar(language) {
  const load = lazyGrammars.get(language);
  if (!load) return true;
  if (highlighter().getLoadedLanguages().includes(language)) return true;
  if (!requested.has(language)) {
    requested.add(language);
    void load()
      .then((module) => {
        highlighter().loadLanguageSync(module.default);
        notifyReady();
      })
      .catch(() => {
        // Unknown or unavailable grammars deliberately keep the plain fallback.
      });
  }
  return false;
}

function highlight(code, languageHint) {
  const language = aliases.get(String(languageHint || '').toLowerCase());
  if (!language || !ensureGrammar(language)) return '';
  try {
    return highlighter().codeToHtml(String(code ?? ''), {
      lang: language,
      theme: 'css-variables',
      tokenizeTimeLimit: 500,
    });
  } catch {
    return '';
  }
}

function install(attempt = 0) {
  const engine = globalThis.FaryoMarkdownAst;
  if (engine && typeof engine.setHighlighter === 'function') {
    engine.setHighlighter({ highlight });
    notifyReady();
    return;
  }
  if (attempt < 20) setTimeout(() => install(attempt + 1), 25);
}

setTimeout(() => {
  try {
    highlighter();
    install();
  } catch {
    // Markdown remains fully functional with the plain code fallback.
  }
}, 0);
