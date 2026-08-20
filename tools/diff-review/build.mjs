import { createHash } from 'node:crypto';
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const target = path.join(root, 'apps/owner/local-tmux-owner/static/vendor/diff-review');
const checkOnly = process.argv.includes('--check');
const files = [
  'diff-review.min.js',
  'diff2html.min.css',
  'LICENSE.diff2html',
  'LICENSE.dompurify',
  'LICENSE.diff',
  'LICENSE.hogan',
  'manifest.json',
];

const digest = (value) => createHash('sha256').update(value).digest('hex');

async function packageVersion(name) {
  return JSON.parse(await readFile(path.join(root, 'node_modules', name, 'package.json'), 'utf8')).version;
}

async function buildInto(outdir) {
  await mkdir(outdir, { recursive: true });
  await build({
    entryPoints: [path.join(root, 'tools/diff-review/src/index.js')],
    bundle: true,
    format: 'iife',
    legalComments: 'none',
    minify: true,
    outfile: path.join(outdir, 'diff-review.min.js'),
    platform: 'browser',
    target: ['chrome100', 'edge100', 'safari16'],
  });
  await Promise.all([
    copyFile(path.join(root, 'node_modules/diff2html/bundles/css/diff2html.min.css'), path.join(outdir, 'diff2html.min.css')),
    copyFile(path.join(root, 'node_modules/diff2html/LICENSE.md'), path.join(outdir, 'LICENSE.diff2html')),
    copyFile(path.join(root, 'node_modules/dompurify/LICENSE'), path.join(outdir, 'LICENSE.dompurify')),
    copyFile(path.join(root, 'node_modules/diff/LICENSE'), path.join(outdir, 'LICENSE.diff')),
    copyFile(path.join(root, 'node_modules/@profoundlogic/hogan/LICENSE'), path.join(outdir, 'LICENSE.hogan')),
  ]);
  const assets = {};
  for (const name of files.filter((item) => item !== 'manifest.json')) {
    const value = await readFile(path.join(outdir, name));
    assets[name] = { bytes: value.length, sha256: digest(value) };
  }
  const manifest = {
    schemaVersion: 1,
    packages: {
      diff2html: await packageVersion('diff2html'),
      dompurify: await packageVersion('dompurify'),
    },
    assets,
  };
  await writeFile(path.join(outdir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
}

if (!checkOnly) {
  await buildInto(target);
  console.log('diff-review-build=PASS');
} else {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'faryo-diff-review-'));
  try {
    await buildInto(temp);
    for (const name of files) {
      const [expected, actual] = await Promise.all([readFile(path.join(temp, name)), readFile(path.join(target, name))]);
      if (!expected.equals(actual)) throw new Error(`generated diff-review asset is stale: ${name}`);
    }
    console.log('diff-review-generated-assets=PASS');
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
}
