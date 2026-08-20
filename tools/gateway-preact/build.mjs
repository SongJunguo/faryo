import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { gzipSync } from "node:zlib";

import { build } from "esbuild";

const root = path.resolve(import.meta.dirname, "../..");
const entry = path.join(root, "apps/gateway/ui/preact-workbench.jsx");
const output = path.join(
  root,
  "apps/gateway/server/static/workbench-preact.js",
);
const noticeOutput = path.join(
  root,
  "apps/gateway/server/static/workbench-preact.LICENSE.txt",
);
const preactRoot = path.join(root, "node_modules/preact");
const preactPackage = JSON.parse(
  await readFile(path.join(preactRoot, "package.json"), "utf8"),
);
if (preactPackage.version !== "10.29.8" || preactPackage.license !== "MIT") {
  throw new Error(
    `Unexpected Preact dependency: ${preactPackage.version} ${preactPackage.license}`,
  );
}
const check = process.argv.includes("--check");
const result = await build({
  entryPoints: [entry],
  bundle: true,
  write: false,
  minify: true,
  format: "iife",
  target: ["es2020"],
  legalComments: "none",
  jsxFactory: "h",
  jsxFragment: "Fragment",
});
const bytes = result.outputFiles[0].contents;
const sha256 = createHash("sha256").update(bytes).digest("hex");
const gzipBytes = gzipSync(bytes, { level: 9 }).length;
if (gzipBytes > 12 * 1024) {
  throw new Error(
    `Gateway Preact bundle exceeds 12 KiB gzip: ${gzipBytes} bytes`,
  );
}
const license = (
  await readFile(path.join(preactRoot, "LICENSE"), "utf8")
).trim();
const notice = Buffer.from(
  [
    `Preact ${preactPackage.version}`,
    "https://preactjs.com/",
    `Bundle SHA-256: ${sha256}`,
    `Bundle size: ${bytes.length} bytes raw; ${gzipBytes} bytes gzip -9`,
    "Transitive production dependencies: none",
    "",
    license,
    "",
  ].join("\n"),
);
if (check) {
  const [current, currentNotice] = await Promise.all([
    readFile(output),
    readFile(noticeOutput),
  ]);
  if (!current.equals(bytes) || !currentNotice.equals(notice)) {
    throw new Error(
      "Gateway Preact bundle or notice is stale; run npm run build:gateway-preact",
    );
  }
} else {
  await Promise.all([
    writeFile(output, bytes),
    writeFile(noticeOutput, notice),
  ]);
}
console.log(
  `gateway-preact-bundle=${bytes.length} gzip=${gzipBytes} sha256=${sha256}${check ? " check=PASS" : ""}`,
);
