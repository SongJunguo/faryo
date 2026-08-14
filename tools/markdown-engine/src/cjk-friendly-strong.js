/*
 * Adapted from DeepSeek Harness at commit
 * 47f943859bef60e4160492346772ded9b24f765a.
 * Copyright (c) 2026 DeepSeek. MIT licensed; see the vendored notices.
 */

import { attention } from 'micromark-core-commonmark';
import { unicodePunctuation } from 'micromark-util-character';
import { classifyCharacter } from 'micromark-util-classify-character';
import { codes, constants } from 'micromark-util-symbol';

const cjkCharacter = new RegExp([
  '\\p{Script_Extensions=Han}',
  '\\p{Script_Extensions=Hiragana}',
  '\\p{Script_Extensions=Katakana}',
  '\\p{Script_Extensions=Hangul}',
  '\\p{Script_Extensions=Bopomofo}',
].join('|'), 'u');

function isCjkCharacter(code) {
  return code !== null && code >= 0 && cjkCharacter.test(String.fromCodePoint(code));
}

const tokenizeCjkFriendlyAttention = function (effects, ok, nok) {
  const configuredMarkers = this.parser.constructs.attentionMarkers.null;
  if (configuredMarkers === undefined) {
    throw new Error('micromark CommonMark attention markers are unavailable');
  }
  const previous = this.previous;
  const before = classifyCharacter(previous);
  let marker = codes.eof;

  return start;

  function start(code) {
    if (code !== codes.asterisk) return nok(code);
    marker = code;
    effects.enter('attentionSequence');
    return inside(code);
  }

  function inside(code) {
    if (code === marker) {
      effects.consume(code);
      return inside;
    }

    const token = effects.exit('attentionSequence');
    const after = classifyCharacter(code);
    const open = !after
      || (after === constants.characterGroupPunctuation && Boolean(before))
      || configuredMarkers.includes(code);
    const commonMarkClose = !before
      || (before === constants.characterGroupPunctuation && Boolean(after))
      || configuredMarkers.includes(previous);
    const markerCount = token.end.offset - token.start.offset;
    const cjkStrongClose = markerCount >= 2
      && unicodePunctuation(previous)
      && isCjkCharacter(code);

    token._open = open;
    token._close = commonMarkClose || cjkStrongClose;
    return ok(code);
  }
};

const cjkFriendlyAttention = {
  name: 'cjkFriendlyAttention',
  resolveAll: attention.resolveAll,
  tokenize: tokenizeCjkFriendlyAttention,
};

const extension = {
  text: { [codes.asterisk]: cjkFriendlyAttention },
};

export function cjkFriendlyStrong() {
  return extension;
}
